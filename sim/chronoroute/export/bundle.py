"""
bundle.py
---------
The ns-3 scenario bundle: everything an ns-3 run needs to replay one
scenario of the real fleet, as plain CSV + one JSON file.

    nodes.csv       every node: satellites (NORAD id, name, plane, slot) and
                    ground stations (city, lat, lon), with its T-CRH SID
    isl.csv         every candidate laser link (Grid-4, MODELLED)
    isl_delay.csv   per 100 ms step: is each laser link up, its light time (ns)
    gsl.csv         per 100 ms step: every (ground station, satellite) pair
                    that is ever visible in the window, up flag, light time
    positions.csv   ECEF positions of every node every 1 s (metres, mm resolution)
    schedule.csv    per flow and per refresh interval: the planned path (SIDs),
                    cumulative budgets, predicted hop delays and the T-CRH bytes
    scenario.json   what the bundle is: snapshot, shell, time base, models and
                    their parameters, flows, invariant results, file columns
    manifest.json   provenance (provenance.write_manifest): commit, config,
                    snapshot sha256, sha256 + size of every file above

The exact formats are in docs/bundle-format.md. Design choices:

  * Integers everywhere a value is compared or summed: times in ms from t0,
    delays in ns, budgets in ns, SIDs as decimal integers. No floats on the
    wire or in deadlines; positions are metres printed from integer
    millimetres (exactly 3 decimals), so they parse identically everywhere.
  * Deterministic: rows sorted by time then id, fixed formatting, no time
    stamps inside the data files (the run time is only in manifest.json), so
    the same inputs give byte-identical files.
  * Size: the 60 s / 463 km milestone bundle is ~100 MB, almost all of it
    isl_delay.csv (5,361 links x 601 steps); see the size printout.
  * Planning knows the topology ahead (BundleConfig.plan_links = "stable",
    the default). Orbits and ground-link handovers are predictable, so the
    ground plans each schedule interval [valid_from, valid_to) only on links
    that stay up from valid_from until the last packet of the interval has
    reached its final deadline (valid_to + the path's final budget B_h).
    A planned path therefore never loses a link while its packets use it;
    any deviation the network sees is a real surprise (a fault), which is
    the situation T-CRH is meant to detect. "instant" (the original rule:
    links up at the planning instant only) is kept as a labelled variant;
    with it a link can vanish inside the interval and its packets are lost.
    invariants.schedule_stability checks the rule on every schedule row.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .. import __version__, labels as labels_mod, provenance
from ..data import cities as cities_mod, omm, snapshot
from ..proto import tcrh as tcrh_mod, timebase
from ..route import scheduler
from ..topo import geometry, graph as graph_mod, gsl as gsl_mod, invariants, isl_grid4

SCHEMA = "chronoroute.bundle/1"
NS_PER_MS = 1_000_000

COLUMNS = {
    "nodes.csv": ("node_id", "kind", "sid", "norad", "name", "shell", "plane", "slot", "lat", "lon"),
    "isl.csv": ("link_id", "a", "b", "kind"),
    "isl_delay.csv": ("t_ms", "link_id", "up", "delay_ns"),
    "gsl.csv": ("t_ms", "gs_node", "sat_node", "up", "delay_ns", "elev_mdeg"),
    "positions.csv": ("t_ms", "node_id", "x_m", "y_m", "z_m"),
    "schedule.csv": ("flow_id", "src_gs", "dst_gs", "valid_from_ms", "valid_to_ms", "sids_fwd",
                     "cumulative_budgets_ns", "predicted_hop_delays_ns", "tcrh_hex_template",
                     "path_nodes"),
}
DATA_FILES = tuple(COLUMNS) + ("scenario.json",)

# Honesty labels: one shared table for every producer (chronoroute/labels.py).
LABELS = labels_mod.pick("orbital_elements", "satellite_positions_sgp4", "city_coordinates",
                         "shells_and_planes", "isl_topology_grid4", "gsl_mask_and_assignment",
                         "processing_delay", "routes_and_budgets", "tcrh_header_bytes")
LABEL_NOTES = labels_mod.notes(*LABELS)

# How a schedule interval is planned (see the module docstring).
PLAN_STABLE = "stable"
PLAN_INSTANT = "instant"
PLAN_MODES = (PLAN_STABLE, PLAN_INSTANT)
# The stable planner widens its look-ahead until the path's own final budget
# fits; each round can only lengthen it, so a few rounds always settle (the
# schedule_stability invariant catches the impossible case anyway).
PLAN_MAX_ROUNDS = 8


class InvariantError(RuntimeError):
    """A scenario failed a physical invariant; no bundle is written."""


@dataclass(frozen=True)
class BundleConfig:
    """Every setting that changes a bundle (recorded in scenario.json and the manifest)."""

    shell_id: str
    cities: tuple
    t0_ns: int
    window_ms: int
    flows: tuple                                  # ((src city, dst city), ...)
    step_ms: int = 100
    position_step_ms: int = 1000
    refresh_ms: int = 1000
    slack: str = scheduler.DEFAULT_SLACK
    unit_code: int = scheduler.DEFAULT_UNIT_CODE
    next_header: int = scheduler.DEFAULT_NEXT_HEADER
    grid: isl_grid4.Grid4Params = field(default_factory=isl_grid4.Grid4Params)
    gsl: gsl_mod.GslParams = field(default_factory=gsl_mod.GslParams)
    plan_links: str = PLAN_STABLE
    processing_ns: int = geometry.PROCESSING_NS

    def validate(self):
        if isinstance(self.processing_ns, bool) or not isinstance(self.processing_ns, int) or self.processing_ns < 0:
            raise ValueError("processing_ns must be a nonnegative integer")
        if self.plan_links not in PLAN_MODES:
            raise ValueError(f"plan_links must be one of {PLAN_MODES}, got {self.plan_links!r}")
        for name in ("window_ms", "step_ms", "position_step_ms", "refresh_ms"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer, got {value!r}")
        for name in ("window_ms", "position_step_ms", "refresh_ms"):
            if getattr(self, name) % self.step_ms:
                raise ValueError(f"{name} must be a multiple of step_ms ({self.step_ms})")
        if len(set(self.cities)) != len(self.cities) or not self.cities:
            raise ValueError("cities must be a non-empty list without repeats")
        for src, dst in self.flows:
            if src not in self.cities or dst not in self.cities:
                raise ValueError(f"flow {src}->{dst}: both cities must be in the city list")
            if src == dst:
                raise ValueError(f"flow {src}->{dst}: source and destination are the same")
        if len(set(self.flows)) != len(self.flows):
            raise ValueError("a flow is listed twice")
        scheduler.exact_slack(self.slack)
        timebase.unit_ns(self.unit_code)

    def as_dict(self):
        return {
            "shell_id": self.shell_id, "cities": list(self.cities),
            "t0_utc": omm.format_utc_ns(self.t0_ns), "window_ms": self.window_ms,
            "step_ms": self.step_ms, "position_step_ms": self.position_step_ms,
            "schedule_refresh_ms": self.refresh_ms, "plan_links": self.plan_links,
            "flows": [[s, d] for s, d in self.flows], "slack": str(scheduler.exact_slack(self.slack)),
            "unit_code": self.unit_code, "next_header": self.next_header,
            "isl_model": {"name": isl_grid4.MODEL_NAME, **self.grid.as_dict()},
            "gsl_model": self.gsl.as_dict(), "processing_ns": self.processing_ns,
        }


@dataclass(frozen=True)
class Bundle:
    """A computed bundle, ready to write."""

    config: BundleConfig
    scenario: object                  # topo.graph.Scenario
    flows: tuple                      # dicts: flow_id, src, dst, src_gs, dst_gs
    entries: tuple                    # (flow_id, valid_from_ms, valid_to_ms, ScheduleEntry)
    gaps: tuple                       # (flow_id, valid_from_ms, valid_to_ms) with no path
    invariants: dict


def build_bundle(fleet, config, registry):
    """Compute a bundle (no files written). Raises InvariantError on a failed check."""
    config.validate()
    by_name = {c.name: c for c in cities_mod.load_cities()}
    missing = [c for c in config.cities if c not in by_name]
    if missing:
        raise ValueError(f"unknown cities {missing}; see data/static/cities.csv")
    registry.ensure_ground_stations(config.cities)
    stations = [gsl_mod.ground_station_from_city(by_name[c], registry.ground_station_number(c))
                for c in config.cities]
    n_steps = config.window_ms // config.step_ms
    times = [config.t0_ns + k * config.step_ms * NS_PER_MS for k in range(n_steps + 1)]
    sc = graph_mod.build_scenario(fleet, config.shell_id, stations, times, registry=registry,
                                  grid_params=config.grid, gsl_params=config.gsl)
    sc = replace(sc, graph=replace(sc.graph, processing_ns=config.processing_ns))

    flows = []
    for fid, (src, dst) in enumerate(config.flows):
        flows.append({"flow_id": fid, "src": src, "dst": dst,
                      "src_gs": sc.gs_node(sc.gs_index(src)), "dst_gs": sc.gs_node(sc.gs_index(dst)),
                      "src_sid": int(sc.gs_sid[sc.gs_index(src)]),
                      "dst_sid": int(sc.gs_sid[sc.gs_index(dst)]),
                      "great_circle_km": round(cities_mod.great_circle_km(by_name[src], by_name[dst]), 3)})
    entries, gaps = [], []
    graphs = {}                      # (first step, last step) -> CSR, shared by the flows

    def graph_for(k0, k1):
        if (k0, k1) not in graphs:
            graphs[(k0, k1)] = sc.graph.csr_stable(k0, k1)
        return graphs[(k0, k1)]

    def plan(f, step, k1):
        return scheduler.plan_path(sc, f["src_gs"], f["dst_gs"], step, slack=config.slack,
                                   unit_code=config.unit_code, next_header=config.next_header,
                                   csr=graph_for(step, k1))

    last_step = len(times) - 1
    for start in range(0, config.window_ms, config.refresh_ms):
        end = min(start + config.refresh_ms, config.window_ms)
        step = start // config.step_ms
        graphs.clear()
        for f in flows:
            if config.plan_links == PLAN_INSTANT:
                e = plan(f, step, step)
            else:
                # Links must stay up until the interval's last packet meets its
                # final deadline: valid_to + B_h. B_h depends on the path, so
                # start with the interval alone and widen until the path fits.
                horizon_ns = 0
                for _ in range(PLAN_MAX_ROUNDS):
                    k1 = max(step, invariants.last_step_needed(end, horizon_ns, config.step_ms, last_step))
                    e = plan(f, step, k1)
                    if e is None or e.budgets_ceil_ns[-1] <= horizon_ns:
                        break
                    horizon_ns = e.budgets_ceil_ns[-1]
            if e is None:
                gaps.append((f["flow_id"], start, end))
            else:
                entries.append((f["flow_id"], start, end, e))
    inv = invariants.run_all(sc, [e for *_, e in entries], rows=entries, step_ms=config.step_ms,
                             stable_required=config.plan_links == PLAN_STABLE)
    if not inv["all_ok"]:
        failed = [k for k, v in inv.items() if k != "all_ok" and not v["ok"]]
        raise InvariantError(f"scenario failed invariants {failed}: {json.dumps(inv)}")
    return Bundle(config=config, scenario=sc, flows=tuple(flows), entries=tuple(entries),
                  gaps=tuple(gaps), invariants=inv)


# ------------------------------------------------------------------ writing

def _check_text(value):
    text = str(value)
    if any(ch in text for ch in ',"\r\n'):
        raise ValueError(f"{text!r} cannot go into a bundle CSV unquoted")
    return text


def _mm_text(km):
    """ECEF km -> metres with exactly 3 decimals, printed from integer millimetres."""
    mm = np.rint(np.asarray(km, dtype=float) * 1e6).astype(np.int64)
    out = []
    for q in mm.tolist():
        sign = "-" if q < 0 else ""
        a = -q if q < 0 else q
        out.append(f"{sign}{a // 1000}.{a % 1000:03d}")
    return out


class _AtomicText:
    """Write a text file through a temp file + rename (no half-written CSV on a crash)."""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, self.tmp = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp")
        self.fh = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
        return self.fh

    def __exit__(self, exc_type, exc, tb):
        self.fh.close()
        if exc_type is None:
            os.chmod(self.tmp, 0o644)
            os.replace(self.tmp, self.path)
        else:
            os.unlink(self.tmp)
        return False


def _write_nodes(fh, b):
    sc = b.scenario
    fh.write(",".join(COLUMNS["nodes.csv"]) + "\n")
    shell_id = _check_text(sc.shell.shell_id)
    for i in range(sc.n_sats):
        fh.write(f"{i},sat,{int(sc.sat_sid[i])},{int(sc.sat_norad[i])},{_check_text(sc.sat_name[i])},"
                 f"{shell_id},{int(sc.sat_plane[i])},{int(sc.sat_slot[i])},,\n")
    for j, gs in enumerate(sc.ground_stations):
        fh.write(f"{sc.gs_node(j)},gs,{int(sc.gs_sid[j])},,{_check_text(gs.name)},,,,"
                 f"{_check_text(gs.lat_text)},{_check_text(gs.lon_text)}\n")


def _write_isl(fh, b):
    sc = b.scenario
    fh.write(",".join(COLUMNS["isl.csv"]) + "\n")
    for lid, (a, c, k) in enumerate(zip(sc.isl_a.tolist(), sc.isl_b.tolist(), sc.isl_kind.tolist())):
        fh.write(f"{lid},{a},{c},{isl_grid4.KIND_NAMES[k]}\n")


def _step_ms(b):
    return [k * b.config.step_ms for k in range(len(b.scenario.times_ns))]


def _write_isl_delay(fh, b):
    sc = b.scenario
    fh.write(",".join(COLUMNS["isl_delay.csv"]) + "\n")
    n_isl = len(sc.isl_a)
    prop = sc.graph.prop_ns[:n_isl]
    up = sc.isl_up.astype(np.int8)
    ids = range(n_isl)
    for k, t_ms in enumerate(_step_ms(b)):
        fh.write("".join(f"{t_ms},{i},{u},{d}\n" for i, u, d in zip(ids, up[:, k].tolist(), prop[:, k].tolist())))


def _write_gsl(fh, b):
    sc = b.scenario
    fh.write(",".join(COLUMNS["gsl.csv"]) + "\n")
    n_isl = len(sc.isl_a)
    prop = sc.graph.prop_ns[n_isl:]
    up = sc.gsl_up.astype(np.int8)
    gs_nodes = (sc.n_sats + sc.gsl_gs).tolist()
    sat_nodes = sc.gsl_sat.tolist()
    elev = np.where(np.isfinite(sc.gsl_elev_deg), np.rint(sc.gsl_elev_deg * 1000.0), -999999).astype(np.int64)
    for k, t_ms in enumerate(_step_ms(b)):
        fh.write("".join(f"{t_ms},{g},{s},{u},{d},{e}\n" for g, s, u, d, e in
                         zip(gs_nodes, sat_nodes, up[:, k].tolist(), prop[:, k].tolist(), elev[:, k].tolist())))


def _write_positions(fh, b):
    sc = b.scenario
    fh.write(",".join(COLUMNS["positions.csv"]) + "\n")
    gs_xyz = [_mm_text(np.asarray(gs.ecef_km)) for gs in sc.ground_stations]
    every = b.config.position_step_ms // b.config.step_ms
    for k in range(0, len(sc.times_ns), every):
        t_ms = k * b.config.step_ms
        xyz = [_mm_text(sc.sat_pos_km[:, k, axis]) for axis in range(3)]
        fh.write("".join(f"{t_ms},{i},{x},{y},{z}\n" for i, (x, y, z) in enumerate(zip(*xyz))))
        for j, (x, y, z) in enumerate(gs_xyz):
            fh.write(f"{t_ms},{sc.gs_node(j)},{x},{y},{z}\n")


def _write_schedule(fh, b):
    fh.write(",".join(COLUMNS["schedule.csv"]) + "\n")
    flows = {f["flow_id"]: f for f in b.flows}
    for fid, start, end, e in sorted(b.entries, key=lambda r: (r[1], r[0])):
        f = flows[fid]
        fh.write(f"{fid},{f['src_gs']},{f['dst_gs']},{start},{end},"
                 f"{' '.join(str(s) for s in e.sids_fwd)},"
                 f"{' '.join(str(x) for x in e.budgets_ceil_ns)},"
                 f"{' '.join(str(x) for x in e.hop_delays_ns)},"
                 f"{e.template.hex()},{' '.join(str(n) for n in e.path)}\n")


def scenario_doc(b, snapshot_info):
    """The scenario.json content (deterministic: no time stamps of its own)."""
    sc, cfg = b.scenario, b.config
    t0_gps = scheduler.utc_ns_to_gps_ns(cfg.t0_ns)
    unit = timebase.unit_ns(cfg.unit_code)
    shell = sc.shell
    synthetic = sc.fleet.layout == "synthetic"
    output_labels = dict(LABELS)
    output_notes = dict(LABEL_NOTES)
    if synthetic:
        output_labels.update(orbital_elements="MODELLED", satellite_positions_sgp4="MODELLED")
        output_notes["satellite_positions_sgp4"] = "SGP4 physics on MODELLED Walker element sets"
    counts = {
        "nodes": sc.graph.n_nodes, "satellites": sc.n_sats, "ground_stations": len(sc.ground_stations),
        "isl_links": int(len(sc.isl_a)), **{f"isl_{k}": v for k, v in sc.grid4.counts().items()},
        "gsl_pairs": int(len(sc.gsl_gs)), "steps": int(len(sc.times_ns)),
        "position_steps": int(len(range(0, len(sc.times_ns), cfg.position_step_ms // cfg.step_ms))),
        "flows": len(b.flows), "schedule_rows": len(b.entries), "schedule_gaps": len(b.gaps),
    }
    return {
        "schema": SCHEMA,
        "labels": output_labels,
        "label_notes": output_notes,
        "snapshot": snapshot_info,
        "shell": {
            "shell_id": shell.shell_id, "layer": shell.shell.layer,
            "inclination_deg": round(shell.shell.inclination_deg, 4),
            "altitude_km": round(shell.shell.altitude_km, 2),
            "members": shell.shell.count, "in_planes": sc.n_sats,
            "off_grid_left_out": sc.excluded["off_grid"], "n_planes": len(shell.planes),
            "plane_quality": round(float(shell.quality["score"]), 4),
            "shares_planes_with": shell.shell.shares_planes_with,
            "label": "DERIVED (inferred from MODELLED element sets)" if synthetic else "DERIVED (inferred from REAL element sets)",
        },
        "time": {
            "t0_utc": omm.format_utc_ns(cfg.t0_ns), "t0_unix_ns": cfg.t0_ns, "t0_gps_ns": t0_gps,
            "timescale_note": "t_ms columns are milliseconds after t0. GPS = UTC + 18 s. "
                              "Epoch_Base of a packet entering at t_ms is "
                              "ceil((t0_gps_ns + t_ms*1e6 [+ sub-ms ns]) / unit_ns) mod 2^32.",
            "window_ms": cfg.window_ms, "step_ms": cfg.step_ms,
            "position_step_ms": cfg.position_step_ms, "schedule_refresh_ms": cfg.refresh_ms,
            "grid4_pairs_chosen_at_utc": omm.format_utc_ns(sc.reference_ns),
        },
        "models": {
            "isl": {"name": isl_grid4.MODEL_NAME, "label": isl_grid4.LABEL, **cfg.grid.as_dict(),
                    "max_cross_du_deg": round(sc.grid4.max_cross_du_deg, 6), "max_degree": isl_grid4.MAX_DEGREE,
                    "inter_shell_links": False},
            "gsl": {**cfg.gsl.as_dict(), "mask_label": gsl_mod.MASK_LABEL, "policy_label": gsl_mod.POLICY_LABEL},
            "planning": {
                "plan_links": cfg.plan_links,
                "rule": ("a schedule row uses only links that are up at every step from valid_from "
                         "until valid_to + the path's final budget (ground planning that knows the "
                         "predictable topology, including ground-link handovers)")
                        if cfg.plan_links == PLAN_STABLE else
                        ("a schedule row uses the links that are up at valid_from only (links may "
                         "go down inside the interval; Sprint A variant)"),
            },
            "delay": {"speed_of_light_m_s": geometry.C_M_PER_S, "processing_ns": cfg.processing_ns,
                      "delay_ns": "round(distance / c) to the nearest ns (halves up); -1 if a position is missing",
                      "edge_weight_ns": "delay_ns + processing_ns (what the router minimises)",
                      "between_steps": "linear interpolation of delay_ns between the two neighbouring "
                                       "100 ms rows is recommended; up/down holds for the whole step"},
        },
        "tcrh": {
            "spec": "tcrh-v1", "unit_code": cfg.unit_code, "unit_ns": unit,
            "slack": str(scheduler.exact_slack(cfg.slack)), "next_header": cfg.next_header,
            "template_epoch_base": 0,
            "budget_rule": "B_k = slack * (predicted_hop_delay_1 + ... + predicted_hop_delay_k); "
                           "cumulative_budgets_ns holds ceil(B_k), which encodes to the same deltas",
            "sids": "satellites: data/static/sid_registry.json (stable, by NORAD id); "
                    "ground stations 0xF000 + g",
            "sid_address_plan_ns3": "fd00::<sid>/128 (ns3/contrib/chronoroute/model/tcrh-address-plan.h)",
            "routing": "canonical Dijkstra (route/dijkstra.py): integer ns weights, lowest node id "
                       "wins ties; ground stations never relay",
        },
        "counts": counts,
        "flows": list(b.flows),
        "schedule_gaps": [{"flow_id": f, "valid_from_ms": s, "valid_to_ms": e} for f, s, e in b.gaps],
        "invariants": b.invariants,
        "files": {name: {"columns": list(cols)} for name, cols in COLUMNS.items()},
    }


def snapshot_info_of(fleet):
    """Snapshot identity for scenario.json and the manifest."""
    if fleet.layout == "synthetic":
        snap = {"id": fleet.snapshot_id, "sha256": fleet.sha256_raw, "sha256_of": "synthetic_omm.json"}
    elif fleet.layout == "pinned":
        snap = provenance.snapshot_from_dir(fleet.folder)
    else:
        omm_path = Path(fleet.folder) / snapshot.WEB_OMM
        snap = {"id": fleet.snapshot_id, "sha256": snapshot.sha256_bytes(omm_path.read_bytes()),
                "sha256_of": snapshot.WEB_OMM}
    return snap, {
        "id": fleet.snapshot_id, "layout": fleet.layout, "source": fleet.source.name,
        "fetched_utc": fleet.fetched_utc, "sha256_raw": fleet.sha256_raw,
        "sha256": snap["sha256"], "sha256_of": snap["sha256_of"],
        "attribution": fleet.source.attribution,
    }


def write_bundle(b, out_dir, *, command, timer=None):
    """Write every file of the bundle plus manifest.json; returns {name: path}."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snap, snap_info = snapshot_info_of(b.scenario.fleet)
    writers = {"nodes.csv": _write_nodes, "isl.csv": _write_isl, "isl_delay.csv": _write_isl_delay,
               "gsl.csv": _write_gsl, "positions.csv": _write_positions, "schedule.csv": _write_schedule}
    paths = {}
    if b.scenario.fleet.layout == "synthetic":
        from ..fwd.presets import walker_omm_bytes, WALKER_PRESETS
        fleet = b.scenario.fleet
        name = fleet.snapshot_id.removeprefix("synthetic-walker-")
        # the element sets the fleet was BUILT from: at its own epoch (presets.walker_fleet sets
        # fetched_ns = epoch), not the bundle's t0, which may differ; the manifest's snapshot
        # sha256 (fleet.sha256_raw) names exactly these bytes
        raw = walker_omm_bytes(WALKER_PRESETS[name], fleet.fetched_ns)
        if snapshot.sha256_bytes(raw) != fleet.sha256_raw:
            raise ValueError(f"cannot reproduce the synthetic element sets of {fleet.snapshot_id}: "
                             "their sha256 differs from the fleet's")
        (out_dir / "synthetic_omm.json").write_bytes(raw)
        paths["synthetic_omm.json"] = out_dir / "synthetic_omm.json"
    for name, writer in writers.items():
        with _AtomicText(out_dir / name) as fh:
            writer(fh, b)
        paths[name] = out_dir / name
    doc = scenario_doc(b, snap_info)
    with _AtomicText(out_dir / "scenario.json") as fh:
        fh.write(json.dumps(doc, indent=1, ensure_ascii=False, allow_nan=False) + "\n")
    paths["scenario.json"] = out_dir / "scenario.json"
    config = {"snapshot_dir": Path(b.scenario.fleet.folder).name, "source": b.scenario.fleet.source.key,
              **b.config.as_dict()}
    manifest = provenance.write_manifest(
        out_dir, tool="cr export bundle", tool_version=__version__, command=command, config=config,
        seeds=[], snapshot=snap, outputs=list(paths.values()), labels=doc["labels"],
        extra={"bundle_schema": SCHEMA, "counts": doc["counts"], "invariants_all_ok": b.invariants["all_ok"],
               "spec": "tcrh-v1"},
        timer=timer)
    paths["manifest.json"] = manifest
    return paths


# ------------------------------------------------------------------ reading

def read_csv(path):
    """(header tuple, list of row tuples of str) for a bundle CSV (no quoting is ever used)."""
    with open(path, encoding="utf-8", newline="") as fh:
        lines = fh.read().split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    header = tuple(lines[0].split(","))
    return header, [tuple(line.split(",")) for line in lines[1:]]


def _iter_rows(path):
    """Yield the header tuple, then each row tuple, one line at a time (big files)."""
    with open(path, encoding="utf-8", newline="") as fh:
        for line in fh:
            yield tuple(line.rstrip("\n").split(","))


def _check_blocks(path, cols, n_key_cols, block_keys, step_ms, n_steps, check_row):
    """Stream a per-step file: block k must list exactly block_keys, in order, at t_ms = k*step_ms.

    Columns 1..n_key_cols are the row's key (link id, node id, or gs+sat).
    block_keys: the keys expected in every block (str tuples), or None to take
    them from the first block (which must then be sorted numerically).
    check_row(row) -> a problem string or None. Returns (problems, n_rows).
    """
    rows = _iter_rows(path)
    header = next(rows, None)
    if header != cols:
        return [f"{path.name}: header {header} != {cols}"], 0
    keys = block_keys
    first = []
    n = 0
    for row in rows:
        if len(row) != len(cols):
            return [f"{path.name}: row {n + 1} has {len(row)} fields"], n
        key = row[1:1 + n_key_cols]
        if keys is None and row[0] == "0":
            first.append(key)                    # still inside the first block
        else:
            if keys is None:                     # the first block just ended
                keys = first
                if sorted(keys, key=lambda k: tuple(int(x) for x in k)) != keys or len(set(keys)) != len(keys):
                    return [f"{path.name}: the first step's ids are not sorted and unique"], n
            k, j = divmod(n, len(keys))
            if int(row[0]) != k * step_ms or key != keys[j]:
                return [f"{path.name}: row {n + 1} out of order (t_ms {row[0]}, key {key})"], n
        bad = check_row(row)
        if bad:
            return [f"{path.name}: row {n + 1}: {bad}"], n
        n += 1
    per_block = len(keys if keys is not None else first)
    if n != per_block * n_steps:
        return [f"{path.name}: {n} rows, expected {per_block} x {n_steps}"], n
    return [], n


def check_bundle(out_dir):
    """Re-read a written bundle and check it against its own scenario.json.

    Returns a list of problems (empty = consistent). Checks: headers, row
    counts, exact row order (every step block lists the same ids in the same
    order, t_ms = k * step), up flags 0/1, positions with 3 decimals, and
    that every schedule row's T-CRH template is exactly what
    proto.build_header makes from its SIDs and budgets (Epoch_Base 0), with
    the flow's destination SID last. The big per-step files are streamed
    line by line, so checking the 60 s bundle needs little memory.
    """
    out_dir = Path(out_dir)
    problems = []
    doc = json.loads((out_dir / "scenario.json").read_text(encoding="utf-8"))
    counts, tm = doc["counts"], doc["time"]
    tables = {}
    for name in ("nodes.csv", "isl.csv", "schedule.csv"):
        header, rows = read_csv(out_dir / name)
        if header != COLUMNS[name]:
            problems.append(f"{name}: header {header} != {COLUMNS[name]}")
        if any(len(r) != len(COLUMNS[name]) for r in rows):
            problems.append(f"{name}: a row has the wrong number of fields")
        tables[name] = rows
    steps = counts["steps"]
    if len(tables["nodes.csv"]) != counts["nodes"]:
        problems.append("nodes.csv row count")
    if [int(r[0]) for r in tables["nodes.csv"]] != list(range(counts["nodes"])):
        problems.append("nodes.csv node ids must be 0..n-1 in order")
    sids = [int(r[2]) for r in tables["nodes.csv"]]
    if len(set(sids)) != len(sids):
        problems.append("nodes.csv: SIDs are not unique")
    if len(tables["isl.csv"]) != counts["isl_links"]:
        problems.append("isl.csv row count")
    if [int(r[0]) for r in tables["isl.csv"]] != list(range(len(tables["isl.csv"]))):
        problems.append("isl.csv link ids must be 0..L-1 in order")

    def up_and_delay(up_col):
        def check(row):
            if row[up_col] not in ("0", "1"):
                return "up must be 0 or 1"
            if int(row[up_col + 1]) < -1:
                return "delay_ns must be >= -1"
            if row[up_col] == "1" and int(row[up_col + 1]) < 0:
                return "an up link needs a delay"
            return None
        return check

    link_keys = [(r[0],) for r in tables["isl.csv"]]
    p, _ = _check_blocks(out_dir / "isl_delay.csv", COLUMNS["isl_delay.csv"], 1, link_keys,
                         tm["step_ms"], steps, up_and_delay(2))
    problems += p
    p, n_gsl = _check_blocks(out_dir / "gsl.csv", COLUMNS["gsl.csv"], 2, None, tm["step_ms"], steps,
                             up_and_delay(3))
    problems += p
    if n_gsl != counts["gsl_pairs"] * steps:
        problems.append("gsl.csv must have one row per pair per step")
    node_keys = [(str(i),) for i in range(counts["nodes"])]

    def three_decimals(row):
        if any(len(v.rpartition(".")[2]) != 3 or "." not in v for v in row[2:5]):
            return "positions need exactly 3 decimals (mm)"
        return None

    p, _ = _check_blocks(out_dir / "positions.csv", COLUMNS["positions.csv"], 1, node_keys,
                         tm["position_step_ms"], counts["position_steps"], three_decimals)
    problems += p
    sat_sid = {int(r[0]): int(r[2]) for r in tables["nodes.csv"]}
    flows = {f["flow_id"]: f for f in doc["flows"]}
    for r in tables["schedule.csv"]:
        fid = int(r[0])
        sids_fwd = [int(x) for x in r[5].split()]
        budgets = [int(x) for x in r[6].split()]
        hops = [int(x) for x in r[7].split()]
        path = [int(x) for x in r[9].split()]
        f = flows[fid]
        if path[0] != f["src_gs"] or path[-1] != f["dst_gs"] or sids_fwd[-1] != f["dst_sid"]:
            problems.append(f"schedule flow {fid} @ {r[3]}: wrong end points")
        if [sat_sid[n] for n in path[1:]] != sids_fwd:
            problems.append(f"schedule flow {fid} @ {r[3]}: SIDs do not match path_nodes")
        if not (len(sids_fwd) == len(budgets) == len(hops)):
            problems.append(f"schedule flow {fid} @ {r[3]}: list lengths differ")
            continue
        want = tcrh_mod.build_header(sids_fwd, budgets, 0, doc["tcrh"]["unit_code"],
                                     next_header=doc["tcrh"]["next_header"]).encode().hex()
        if want != r[8]:
            problems.append(f"schedule flow {fid} @ {r[3]}: T-CRH template differs from build_header")
    return problems


__all__ = ["SCHEMA", "COLUMNS", "DATA_FILES", "LABELS", "PLAN_STABLE", "PLAN_INSTANT", "PLAN_MODES",
           "InvariantError", "BundleConfig", "Bundle", "build_bundle", "write_bundle", "scenario_doc",
           "read_csv", "check_bundle", "snapshot_info_of"]

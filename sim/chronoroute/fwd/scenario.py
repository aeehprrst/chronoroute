"""
scenario.py
-----------
From a normalised config (config.py) to everything a run needs before the
first packet: the fleet (REAL snapshot or synthetic Walker preset), the city
ground stations, the flows, the streaming truth topology and the planner
(the ground's predicted, failure-free schedule).

The planner is the bundle's (export/bundle.py build_bundle, "stable" rule,
docs/bundle-format.md 1.4): for each refresh interval [valid_from, valid_to)
it plans on the links that stay up at every step from valid_from until
valid_to + the path's own final budget B_h, widening the look-ahead until
the path fits; route/scheduler.plan_path does the path, budgets and T-CRH
template. The ground never sees faults: plans use only the predicted
geometry (which, without an orbit-prediction-error model, equals the truth
geometry; faults exist only in the truth).
"""

from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from ..data import cities as cities_mod, omm, snapshot
from ..route import scheduler, sids
from ..topo import gsl as gsl_mod, invariants, isl_grid4
from . import presets
from .config import seconds_to_ns_exact
from .topology import Topology

NS_PER_MS = 1_000_000
PLAN_MAX_ROUNDS = 8          # the bundle planner's limit (export/bundle.py)


@dataclass
class Flow:
    flow_id: int
    src: str
    dst: str
    src_node: int
    dst_node: int
    rate_pps: object                  # Fraction
    model: str                        # cbr | poisson | explicit
    start_offset_ns: int | None
    payload_bytes: int
    send_times_ns: tuple | None = None
    great_circle_km: float = 0.0


@dataclass
class Scenario:
    cfg: dict
    t0_ns: int
    t0_gps_ns: int
    duration_ns: int
    drain_ns: int
    step_ns: int
    n_steps: int
    fleet: object
    topo: Topology
    flows: list
    cities: list
    pairs_report: dict
    registry: object
    snapshot_dir: Path | None
    synthetic_omm: bytes | None = None
    plans: dict = field(default_factory=dict)       # (flow, start_ms) -> ScheduleEntry | None
    plan_calls: int = 0

    @property
    def end_ns(self):
        return self.duration_ns + self.drain_ns

    @property
    def refresh_ms(self):
        return self.cfg["schedule"]["refresh_ms"]

    def interval_of(self, t_ns):
        """(start_ms, end_ms) of the refresh interval holding run time t_ns."""
        r = self.refresh_ms
        start = (t_ns // NS_PER_MS) // r * r
        return start, min(start + r, self.duration_ns // NS_PER_MS)

    def plan(self, flow, start_ms, end_ms, csr_cache=None):
        """ScheduleEntry for a flow and refresh interval (None = no path), cached."""
        key = (flow.flow_id, start_ms)
        if key in self.plans:
            return self.plans[key]
        sh = self.cfg["schedule"]
        step_ms = self.step_ns // NS_PER_MS
        step = start_ms // step_ms
        last_step = self.n_steps - 1
        cache = csr_cache if csr_cache is not None else {}

        def graph_for(k0, k1):
            if (k0, k1) not in cache:
                cache[(k0, k1)] = self.topo.csr_stable(k0, k1)
            return cache[(k0, k1)]

        def one(k1):
            self.plan_calls += 1
            return scheduler.plan_path(self.topo, flow.src_node, flow.dst_node, step, slack=sh["slack"],
                                       unit_code=sh["unit_code"], next_header=self.next_header,
                                       csr=graph_for(step, k1))
        if sh["plan_links"] == "instant":
            e = one(step)
        else:
            horizon_ns = 0
            for _ in range(PLAN_MAX_ROUNDS):
                k1 = max(step, invariants.last_step_needed(end_ms, horizon_ns, step_ms, last_step))
                e = one(k1)
                if e is None or e.budgets_ceil_ns[-1] <= horizon_ns:
                    break
                horizon_ns = e.budgets_ceil_ns[-1]
        self.plans[key] = e
        return e

    @property
    def next_header(self):
        # spec section 8: source insertion carries UDP; gateway encapsulation carries IPv6 (41)
        return 41 if self.cfg["traffic"]["ingress_mode"] == "encap" else scheduler.DEFAULT_NEXT_HEADER

    def path_at(self, flow_id, t_ns):
        """Planned path (node list) of a flow at run time t_ns, or None."""
        flow = self.flows[flow_id]
        s, e = self.interval_of(t_ns)
        entry = self.plan(flow, s, e)
        return None if entry is None else entry.path

    def resolve_on_path(self, op, default_t_ns, want_node):
        """A link (a, b) or a satellite on a flow's planned path (fault placement, config on_path)."""
        flow_id = op["flow"]
        if not 0 <= flow_id < len(self.flows):
            raise ValueError(f"on_path: flow {flow_id} does not exist")
        t = seconds_to_ns_exact(op["at_s"], "at_s") if "at_s" in op else default_t_ns
        path = self.path_at(flow_id, min(t, self.duration_ns - 1))
        if path is None:
            raise ValueError(f"on_path: flow {flow_id} has no path at {t} ns")
        S = self.topo.n_sats
        pos = op.get("position", "middle")
        if want_node:
            cands = [n for n in path if n < S]
        elif op.get("kind", "isl") == "isl":
            cands = [(a, b) for a, b in zip(path[:-1], path[1:]) if a < S and b < S]
        else:
            cands = list(zip(path[:-1], path[1:]))
        if not cands:
            raise ValueError(f"on_path: flow {flow_id} path has no candidate {'node' if want_node else 'link'}")
        if isinstance(pos, int):
            if not 0 <= pos < len(cands):
                raise ValueError(f"on_path: position {pos} outside 0..{len(cands) - 1}")
            return cands[pos]
        # thirds: split the candidates into 3 nearly equal parts, take the middle of that part
        n = len(cands)
        bounds = [0, (n + 2) // 3, (2 * n + 2) // 3, n]
        part = {"first": 0, "middle": 1, "last": 2}[pos]
        lo, hi = bounds[part], max(bounds[part] + 1, bounds[part + 1])
        lo = min(lo, n - 1)
        hi = min(hi, n)
        return cands[(lo + hi - 1) // 2]


def _resolve_snapshot(path_text):
    p = Path(path_text)
    if not p.is_absolute():
        p = presets.REPO / p
    return p


def build_scenario(cfg):
    """Scenario for a normalised config (no packets yet)."""
    sc_cfg, tr = cfg["scenario"], cfg["traffic"]
    t0_ns = omm.parse_epoch_ns(sc_cfg["start_utc"][:-1])
    t0_gps = scheduler.utc_ns_to_gps_ns(t0_ns)
    step_ns = sc_cfg["step_ms"] * NS_PER_MS
    duration_ns = seconds_to_ns_exact(sc_cfg["duration_s"], "scenario.duration_s")
    drain_ns = seconds_to_ns_exact(sc_cfg["drain_s"], "scenario.drain_s")
    if duration_ns % step_ns or drain_ns % step_ns:
        raise ValueError("scenario.duration_s and drain_s must be whole multiples of step_ms")
    n_steps = (duration_ns + drain_ns) // step_ns + 1

    all_cities = {c.name: c for c in cities_mod.load_cities()}
    if tr["flows"] == "science20":
        pairs, report = presets.science_pairs(all_cities)
        flow_cfgs = [{"src": s, "dst": d} for s, d in pairs]
    else:
        flow_cfgs = tr["flows"]
        report = {"plan_pairs": None, "used": len(flow_cfgs), "missing": [], "name_mapping": {}}
    names = list(sc_cfg["cities"]) if sc_cfg["cities"] else []
    for f in flow_cfgs:
        for c in (f["src"], f["dst"]):
            if c not in names and not sc_cfg["cities"]:
                names.append(c)
    unknown = [c for c in names if c not in all_cities]
    if unknown:
        raise ValueError(f"unknown cities {unknown}; see data/static/cities.csv")
    for f in flow_cfgs:
        if f["src"] not in names or f["dst"] not in names:
            raise ValueError(f"flow {f['src']}->{f['dst']}: both cities must be in scenario.cities")

    registry = sids.SidRegistry.load_or_empty(sids.DEFAULT_PATH)     # read only: never saved here
    registry.ensure_ground_stations(names)
    stations = [gsl_mod.ground_station_from_city(all_cities[c], registry.ground_station_number(c))
                for c in names]
    synthetic = None
    snap_dir = None
    if sc_cfg["kind"] == "real":
        snap_dir = _resolve_snapshot(sc_cfg["snapshot"])
        fleet = snapshot.load_pinned(snap_dir, sc_cfg["source"])
        shell_id = sc_cfg["shell"]
    else:
        preset = presets.WALKER_PRESETS[sc_cfg["preset"]]
        fleet = presets.walker_fleet(preset, t0_ns)
        synthetic = presets.walker_omm_bytes(preset, t0_ns)
        shell_id = None
    grid = isl_grid4.Grid4Params(polar_cutoff_deg=float(sc_cfg["isl"]["polar_cutoff_deg"]),
                                 max_range_km=sc_cfg["isl"]["max_range_km"])
    gslp = gsl_mod.GslParams(min_elevation_deg=float(sc_cfg["gsl"]["min_elevation_deg"]),
                             max_links_per_gs=sc_cfg["gsl"]["max_links_per_gs"],
                             policy=sc_cfg["gsl"]["policy"])
    topo = Topology(fleet, shell_id, stations, t0_ns, n_steps, step_ns, registry=registry,
                    grid_params=grid, gsl_params=gslp, chunk_steps=sc_cfg["chunk_steps"],
                    planner_processing_ns=cfg["schedule"]["planner_processing_ns"])

    flows = []
    for fid, f in enumerate(flow_cfgs):
        rate = f.get("rate_pps", tr["rate_pps"])
        rate = Fraction(repr(rate)) if isinstance(rate, float) else Fraction(rate)
        if "send_times_ns" in f:
            model, offset, times = "explicit", None, tuple(f["send_times_ns"])
        else:
            model = f.get("model", tr["model"])
            off = f.get("start_offset", tr["start_offset"])
            offset, times = (None if off == "random" else int(off)), None
        flows.append(Flow(flow_id=fid, src=f["src"], dst=f["dst"],
                          src_node=topo.gs_node(names.index(f["src"])),
                          dst_node=topo.gs_node(names.index(f["dst"])), rate_pps=rate, model=model,
                          start_offset_ns=offset, payload_bytes=f.get("payload_bytes", tr["payload_bytes"]),
                          send_times_ns=times,
                          great_circle_km=cities_mod.great_circle_km(all_cities[f["src"]], all_cities[f["dst"]])))
    return Scenario(cfg=cfg, t0_ns=t0_ns, t0_gps_ns=t0_gps, duration_ns=duration_ns, drain_ns=drain_ns,
                    step_ns=step_ns, n_steps=n_steps, fleet=fleet, topo=topo, flows=flows, cities=names,
                    pairs_report=report, registry=registry, snapshot_dir=snap_dir, synthetic_omm=synthetic)


__all__ = ["Flow", "Scenario", "build_scenario"]

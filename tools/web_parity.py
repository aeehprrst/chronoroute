#!/usr/bin/env python3
"""
web_parity.py
-------------
Python side of the website's route parity check.

The website's route planner (web/src/lib/route/) is a TypeScript port of the
Python router: Grid-4 laser links + 25 deg ground links on the real fleet,
integer-nanosecond weights, Dijkstra with the lowest-node-id tie-break, and
the T-CRH bytes from the scheduler. This script makes the PYTHON reference
compute, for 20 canonical city pairs at one fixed instant on a pinned
snapshot:

  * the positions frame: ECEF position of every satellite the router uses
    (SGP4 on the REAL element sets), exported as JSON so that the TypeScript
    router can run on exactly the same numbers;
  * for every pair: the path (node ids and NORAD ids), its cost in ns, the
    per-hop delays, the T-CRH template and the per-packet header, the whole
    IPv6 + T-CRH + UDP packet and a one-packet pcap file, all as hex.

The vitest test web/tests/route-parity.test.ts then runs the TypeScript
router on that frame and compares. Why a shared frame and not each engine's
own SGP4: satellite.js reads EPOCH through a JavaScript Date, which keeps only
milliseconds, so its positions differ from python-sgp4 by up to about 8 m
(the satellite moves 7.6 m per ms). That is far too small to matter for the
picture, but large enough to flip a near-tie between two paths, which is not
a bug. So route parity is checked on identical positions, and SGP4 is checked
separately with a tolerance (the frame also carries positions computed with
the EPOCH cut to milliseconds, so the test can show that this rounding is the
whole difference).

The deploy gate (see the vitest test) fails only on a header-byte mismatch or
a path-cost difference of more than 1 ns, as the reviewer asked.

web/scripts/build-data.sh runs this twice per build:
  * reference run: the experiments' pinned snapshot (the default below), a
    fixed yardstick that does not move with the data refresh -> web/.parity/;
  * served run: the snapshot the site publishes (--snapshot, the same folder
    `cr export web` used) -> web/.parity/served/. The vitest gate then runs
    the TypeScript planner on the SERVED files (public/data/...), so a defect
    in the data actually published blocks the deploy too.

Usage (repository root, inside WSL):

    venv/bin/python -B tools/web_parity.py                      # -> web/.parity/
    venv/bin/python -B tools/web_parity.py --snapshot data/pinned/20261010T2035Z-celestrak \\
        --out web/.parity/served
    venv/bin/python -B tools/web_parity.py --out /tmp/cr-sb/parity

The output folder gets parity.json and a provenance manifest.json. The same
snapshot and arguments always give a byte-identical parity.json (no time
stamps in it; the manifest has the run times).

Nothing here is written back into data/: the SID registry is read, never saved.
"""

import argparse
import io
import json
import sys
from pathlib import Path

import numpy as np
from sgp4 import omm as sgp4_omm
from sgp4.api import Satrec, SatrecArray

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sim"))       # works without `pip install -e .` too

from chronoroute import __version__, labels as labels_mod, provenance  # noqa: E402
from chronoroute.data import cities as cities_mod, omm, snapshot  # noqa: E402
from chronoroute.export import web as web_mod  # noqa: E402
from chronoroute.orbit import frames, planes as planes_mod  # noqa: E402
from chronoroute.route import scheduler, sids  # noqa: E402
from chronoroute.topo import graph as graph_mod, gsl as gsl_mod  # noqa: E402
from chronoroute.trace import pcap  # noqa: E402

SCHEMA = "chronoroute.web-parity/1"
DEFAULT_SNAPSHOT = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
DEFAULT_OUT = REPO / "web" / ".parity"
DEFAULT_SHELL = "53.2deg-463km"
PARITY_FILE = "parity.json"

# The 20 canonical pairs: the five milestone flows (docs/bundle-format.md 2.1),
# long and short hops on every continent, and one pair with no path at the
# fixed instant (Reykjavik and Oslo lie north of what the 53 deg shell covers
# at a 25 deg mask), so the "no route" answer is compared too.
CANONICAL_PAIRS = (
    ("Chennai", "London"),
    ("New York", "Sydney"),
    ("Sao Paulo", "Tokyo"),
    ("Mumbai", "Frankfurt"),
    ("Singapore", "Johannesburg"),
    ("London", "New York"),
    ("Los Angeles", "Tokyo"),
    ("Delhi", "Singapore"),
    ("Cairo", "Moscow"),
    ("Lagos", "Paris"),
    ("Buenos Aires", "Madrid"),
    ("Toronto", "Mexico City"),
    ("Seoul", "Sydney"),
    ("Bengaluru", "Dubai"),
    ("Nairobi", "Cape Town"),
    ("Honolulu", "San Francisco"),
    ("Santiago", "Lima"),
    ("Jakarta", "Perth"),
    ("Stockholm", "Istanbul"),
    ("Reykjavik", "Oslo"),
)

LABEL_KEYS = ("orbital_elements", "satellite_positions_sgp4", "city_coordinates", "shells_and_planes",
              "isl_topology_grid4", "gsl_mask_and_assignment", "processing_delay", "routes_and_budgets",
              "tcrh_header_bytes", "pcap_addresses", "pcap_timestamps")


def _compact(doc):
    return (json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _ms_epoch_ecef_km(records, t_ns):
    """ECEF km of every record at t_ns, with each EPOCH cut to whole milliseconds.

    This is what satellite.js effectively propagates (its json2satrec parses
    EPOCH with a JavaScript Date, which keeps milliseconds only). Same python-
    sgp4 code otherwise, so the TypeScript positions should match these far
    more closely than the full-precision ones.
    """
    satrecs = []
    for record in records:
        fields = record.sgp4_fields()
        head, _, frac = fields["EPOCH"].partition(".")
        fields["EPOCH"] = f"{head}.{frac[:3].ljust(3, '0')}"
        sat = Satrec()
        sgp4_omm.initialize(sat, fields)
        satrecs.append(sat)
    jd, fr = frames.jday_from_ns([t_ns])
    error, r, v = SatrecArray(satrecs).sgp4(jd, fr)
    r = np.array(r, dtype=float)
    v = np.array(v, dtype=float)
    r[np.asarray(error) != 0] = np.nan
    gmst = np.asarray(frames.gmst_rad(jd, fr), dtype=float)
    r_ecef, _ = frames.teme_to_ecef(r, v, gmst)
    return r_ecef[:, 0, :]


def _xyz_list(arr):
    """(N, 3) floats -> [[x, y, z], ...]; NaN (failed SGP4) -> null. repr floats round-trip exactly."""
    out = []
    for row in np.asarray(arr, dtype=float):
        out.append(None if not np.all(np.isfinite(row)) else [float(x) for x in row])
    return out


def _pair_result(sc, entry, src, dst, by_name, t_ns, gs_number):
    """Everything the TypeScript side must reproduce for one pair."""
    base = {"src": src, "dst": dst,
            "src_g": gs_number[src], "dst_g": gs_number[dst],
            "great_circle_km": cities_mod.great_circle_km(by_name[src], by_name[dst])}
    gsl = {}
    for i, name in enumerate((src, dst)):
        rows = np.flatnonzero(sc.gsl_gs == i)
        gsl[name] = {
            "visible": sorted(int(sc.sat_norad[sc.gsl_sat[r]]) for r in rows if sc.gsl_visible[r, 0]),
            "selected": sorted(int(sc.sat_norad[sc.gsl_sat[r]]) for r in rows if sc.gsl_up[r, 0]),
        }
    base["gsl"] = gsl
    if entry is None:
        base.update(reachable=False, cost_ns=None)
        return base
    hdr_bytes = entry.header_for_packet(t_ns)
    t_gps = scheduler.utc_ns_to_gps_ns(t_ns)
    src_sid = int(sc.gs_sid[0])
    dst_sid = int(sc.gs_sid[1])
    # The packet as it enters the network (source mode, RFC 8200 routing header
    # inserted by the sending host): host -> ingress ground station, fresh
    # T-CRH (Segments Left = Num Hops), UDP checksum over the FINAL
    # destination (SID[0] = destination ground station), exactly as the golden
    # pcaps of chronoroute.trace.pcap are built.
    packet = pcap.packet_with_routing_header(
        hdr_bytes, src=pcap.HOST_SRC, dst=pcap.sid_address(src_sid), final_dst=pcap.sid_address(dst_sid),
        payload=pcap.payload_bytes(0, t_gps), seq=0)
    stream = io.BytesIO()
    pcap.PcapWriter(stream, pcap.LINKTYPE_RAW).write(packet, t_gps_ns=t_gps)
    path = list(entry.path)
    base.update(
        reachable=True,
        cost_ns=int(sum(entry.hop_delays_ns)),
        path_nodes=[int(n) for n in path],
        path_norads=[int(sc.sat_norad[n]) if n < sc.n_sats else None for n in path],
        sids_fwd=[int(s) for s in entry.sids_fwd],
        hop_delays_ns=[int(d) for d in entry.hop_delays_ns],
        prop_ns=[int(p) for p in entry.prop_ns],
        budgets_ceil_ns=[int(b) for b in entry.budgets_ceil_ns],
        template_hex=entry.template.hex(),
        header_hex=hdr_bytes.hex(),
        packet_hex=packet.hex(),
        pcap_hex=stream.getvalue().hex(),
    )
    return base


def compute_parity(fleet, *, t_ns=None, shell_id=DEFAULT_SHELL, pairs=CANONICAL_PAIRS,
                   registry=None, slack=scheduler.DEFAULT_SLACK, unit_code=scheduler.DEFAULT_UNIT_CODE):
    """The parity document (a dict) for one fleet, instant and set of pairs.

    Every pair is planned exactly as `cr route` plans it (graph.build_scenario
    with only that pair's two ground stations, then scheduler.plan_path), with
    one difference made explicit: the Grid-4 pairs are always those chosen at
    the snapshot's fetched_utc (reference_ns), which is what the website's
    isl_grid4.json holds. At t = fetched_utc (the default) this is identical
    to `cr route`.
    """
    t_ns = fleet.fetched_ns if t_ns is None else int(t_ns)
    registry = registry if registry is not None else sids.SidRegistry.load()
    by_name = {c.name: c for c in cities_mod.load_cities()}
    names = sorted({n for pair in pairs for n in pair})
    unknown = [n for n in names if n not in by_name]
    if unknown:
        raise ValueError(f"unknown cities {unknown}; see data/static/cities.csv")
    registry.ensure_ground_stations(names)            # in memory only; never saved here
    gs_number = {n: registry.ground_station_number(n) for n in names}

    # The website's two topology files for this snapshot (same functions as `cr export web`).
    geo = planes_mod.build_fleet_geometry(fleet.records, fleet.fetched_ns, satrecs=fleet.satrecs)
    shells_doc = web_mod.shells_doc(fleet, geo)
    isl_doc = web_mod.isl_doc(fleet, geo)
    isl_shell = next(s for s in isl_doc["shells"] if s["shell_id"] == shell_id)
    doc_pairs = sorted(tuple(p) for p in isl_shell["intra"] + isl_shell["cross"])

    frame = None
    results = []
    for src, dst in pairs:
        stations = [gsl_mod.ground_station_from_city(by_name[n], gs_number[n]) for n in (src, dst)]
        sc = graph_mod.build_scenario(fleet, shell_id, stations, [t_ns], registry=registry,
                                      reference_ns=fleet.fetched_ns)
        pairs_here = sorted(zip(sc.sat_norad[sc.isl_a].tolist(), sc.sat_norad[sc.isl_b].tolist()))
        if pairs_here != doc_pairs:
            raise AssertionError(f"{src}->{dst}: the scenario's Grid-4 pairs differ from isl_grid4.json")
        if frame is None:
            frame = {"norad": sc.sat_norad.copy(), "pos": sc.sat_pos_km[:, 0, :].copy(),
                     "lat": sc.sat_lat_deg[:, 0].copy(), "isl_up": sc.isl_up[:, 0].copy(), "sc": sc}
        elif not (np.array_equal(frame["norad"], sc.sat_norad)
                  and np.array_equal(frame["pos"], sc.sat_pos_km[:, 0, :], equal_nan=True)
                  and np.array_equal(frame["isl_up"], sc.isl_up[:, 0])):
            raise AssertionError(f"{src}->{dst}: positions or laser links differ between scenarios")
        entry = scheduler.plan_path(sc, sc.gs_node(0), sc.gs_node(1), 0, slack=slack, unit_code=unit_code)
        results.append(_pair_result(sc, entry, src, dst, by_name, t_ns, gs_number))

    sc0 = frame["sc"]
    down = [[int(sc0.sat_norad[a]), int(sc0.sat_norad[b])]
            for a, b, up in zip(sc0.isl_a.tolist(), sc0.isl_b.tolist(), frame["isl_up"].tolist()) if not up]
    by_norad = {r.norad: r for r in fleet.records}
    frame_records = [by_norad[int(n)] for n in frame["norad"]]
    ms_epoch = _ms_epoch_ecef_km(frame_records, t_ns)
    city_ecef = {n: [float(x) for x in gsl_mod.ground_station_from_city(by_name[n], gs_number[n]).ecef_km]
                 for n in names}
    return {
        "schema": SCHEMA,
        "note": "Python reference routes for the website parity test (tools/web_parity.py). "
                "Positions are SGP4 (python-sgp4) in ECEF km; t is the snapshot's fetched_utc "
                "unless stated otherwise.",
        "snapshot_id": fleet.snapshot_id,
        "source": fleet.source.name,
        # sha256 of the raw download (checked against SHA256SUMS by load_pinned): lets the
        # served-snapshot run prove that the website files it tests (manifest.json
        # sha256_raw) were made from exactly this download.
        "sha256_raw": fleet.sha256_raw,
        "fetched_utc": fleet.fetched_utc,
        "t_utc": omm.format_utc_ns(t_ns),
        "t_unix_ns": str(t_ns),
        "t_gps_ns": str(scheduler.utc_ns_to_gps_ns(t_ns)),
        "shell_id": shell_id,
        "slack": str(slack),
        "unit_code": unit_code,
        "next_header": scheduler.DEFAULT_NEXT_HEADER,
        "processing_ns": int(sc0.graph.processing_ns),
        "grid_params": sc0.grid_params.as_dict(),
        "gsl_params": sc0.gsl_params.as_dict(),
        "labels": dict(labels_mod.TABLE),
        "label_notes": dict(labels_mod.NOTES),
        "frame": {
            "norad": [int(n) for n in frame["norad"]],
            "ecef_km": _xyz_list(frame["pos"]),
            "lat_deg": [None if not np.isfinite(x) else float(x) for x in frame["lat"]],
            "ecef_ms_epoch_km": _xyz_list(ms_epoch),
            "isl_down": down,
            "city_ecef_km": city_ecef,
        },
        "omm_min": snapshot.omm_min_bytes(frame_records).decode("utf-8"),
        "shells": shells_doc,
        "isl_grid4": isl_doc,
        "cities_csv": cities_mod.DEFAULT_PATH.read_text(encoding="utf-8"),
        "sid_registry": registry_doc(registry),
        "pairs": results,
    }


def registry_doc(registry):
    """The registry entries as {satellites: [[sid, norad]...], ground_stations: [[g, name]...]}."""
    return {"schema": sids.SCHEMA,
            "satellites": [[int(s), int(n)] for s, n in registry.satellites()],
            "ground_stations": [[int(g), name] for g, name in registry.ground_stations()]}


def write_parity(doc, out_dir, *, command, snapshot_dir=None, timer=None):
    """Write out_dir/parity.json and out_dir/manifest.json; returns the parity path."""
    out_dir = Path(out_dir)
    path = out_dir / PARITY_FILE
    snapshot.atomic_write(path, _compact(doc))
    snap = provenance.snapshot_from_dir(snapshot_dir) if snapshot_dir else None
    config = {"snapshot_id": doc["snapshot_id"], "t_utc": doc["t_utc"], "shell_id": doc["shell_id"],
              "slack": doc["slack"], "unit_code": doc["unit_code"],
              "pairs": [[p["src"], p["dst"]] for p in doc["pairs"]],
              "grid_params": doc["grid_params"], "gsl_params": doc["gsl_params"]}
    provenance.write_manifest(out_dir, tool="tools/web_parity.py", tool_version=__version__, command=command,
                              config=config, seeds=[], snapshot=snap, outputs=[path],
                              labels=labels_mod.pick(*LABEL_KEYS),
                              extra={"schema": SCHEMA, "pairs": len(doc["pairs"]),
                                     "reachable": sum(1 for p in doc["pairs"] if p["reachable"])},
                              timer=timer)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT), help="pinned snapshot folder "
                        f"(default {DEFAULT_SNAPSHOT.relative_to(REPO)})")
    parser.add_argument("--at", default=None, help="UTC instant, ISO 8601 ending in Z (default: fetched_utc)")
    parser.add_argument("--shell", default=DEFAULT_SHELL)
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output folder (default web/.parity)")
    args = parser.parse_args(argv)
    if args.at and not args.at.endswith("Z"):
        parser.error("--at must end in Z (UTC)")
    folder = Path(args.snapshot)
    fleet = snapshot.load_pinned(folder, "supgp")
    t_ns = omm.parse_epoch_ns(args.at[:-1]) if args.at else None
    with provenance.RunTimer() as timer:
        doc = compute_parity(fleet, t_ns=t_ns, shell_id=args.shell)
    path = write_parity(doc, args.out, command=["tools/web_parity.py", *(argv or sys.argv[1:])],
                        snapshot_dir=folder, timer=timer)
    reach = sum(1 for p in doc["pairs"] if p["reachable"])
    print(f"web parity: {len(doc['pairs'])} pairs ({reach} with a path) at {doc['t_utc']} on "
          f"{doc['snapshot_id']} shell {doc['shell_id']}: {len(doc['frame']['norad'])} satellites, "
          f"{len(doc['frame']['isl_down'])} Grid-4 pairs down")
    print(f"wrote {path} ({path.stat().st_size:,} B) and {Path(args.out) / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

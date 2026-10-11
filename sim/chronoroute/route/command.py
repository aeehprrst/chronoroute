"""
command.py
----------
`cr route --from Chennai --to London [--at ISO-UTC] [--snapshot DIR] [--slack S]`

Plans one path on today's real fleet and prints it hop by hop: real
satellite names and NORAD ids, per-hop distance and light time, the budget
and cumulative deadline of every hop, the T-CRH bytes a packet entering at
--at would carry, and the latency against the great-circle light-speed bound.

Honesty labels in the printout: positions REAL (SGP4 on REAL element sets),
shells/planes DERIVED, laser links MODELLED (Grid-4), ground-link mask
ASSUMED and assignment MODELLED. The path is hypothetical: Starlink's routing
is not public and does not use T-CRH.
"""

import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

from .. import proto
from ..data import cities as cities_mod, omm, snapshot
from ..proto import timebase
from ..topo import geometry, graph as graph_mod, gsl as gsl_mod
from . import scheduler, sids

REPO = Path(__file__).resolve().parents[3]
PINNED_DIR = REPO / "data" / "pinned"
DEFAULT_SHELL = "53.2deg-463km"


def parse_utc(text):
    """'2026-10-10T14:00:00Z' (fraction allowed, Z required) -> UTC ns."""
    if not isinstance(text, str) or not text.endswith("Z"):
        raise ValueError(f"time {text!r} must be ISO 8601 UTC ending in Z, e.g. 2026-10-10T14:00:00Z")
    return omm.parse_epoch_ns(text[:-1])


def default_snapshot_dir():
    """The newest pinned CelesTrak download (folder names sort by time)."""
    folders = sorted(p for p in PINNED_DIR.glob("*-celestrak") if p.is_dir())
    if not folders:
        raise FileNotFoundError(f"no pinned snapshot in {PINNED_DIR}")
    return folders[-1]


def load_fleet(folder, source=None):
    folder = Path(folder)
    if snapshot.detect_layout(folder) == "web":
        return snapshot.load_web_snapshot(folder)
    return snapshot.load_pinned(folder, source or "supgp")


def route_report(fleet, src, dst, t_ns, *, slack, shell_id, registry, unit_code=scheduler.DEFAULT_UNIT_CODE):
    """Compute the route and return (lines, entry, scenario) for printing/tests."""
    by_name = {c.name: c for c in cities_mod.load_cities()}
    for name in (src, dst):
        if name not in by_name:
            raise ValueError(f"unknown city {name!r}; see data/static/cities.csv")
    registry.ensure_ground_stations([src, dst])
    stations = [gsl_mod.ground_station_from_city(by_name[n], registry.ground_station_number(n)) for n in (src, dst)]
    sc = graph_mod.build_scenario(fleet, shell_id, stations, [t_ns], registry=registry)
    entry = scheduler.plan_path(sc, sc.gs_node(0), sc.gs_node(1), 0, slack=slack, unit_code=unit_code)
    unit = timebase.unit_ns(unit_code)
    n_up = int(sc.isl_up[:, 0].sum())
    lines = []
    add = lines.append
    add(f"ChronoRoute route  {src} -> {dst}  at {omm.format_utc_ns(t_ns)}")
    add(f"  snapshot   {fleet.snapshot_id} ({fleet.source.name}, fetched {fleet.fetched_utc})")
    add(f"  positions  REAL: SGP4 on REAL element sets ({fleet.source.attribution})")
    add(f"  shell      {sc.shell.shell_id} [DERIVED]: {sc.n_sats} satellites in {len(sc.shell.planes)} planes "
        f"({sc.excluded['off_grid']} off-grid satellites left out)")
    add(f"  ISLs       MODELLED (Grid-4): {len(sc.isl_a)} candidate pairs, {n_up} up at this instant; "
        f"cross-plane off above |lat| {sc.grid_params.polar_cutoff_deg:g} deg, line of sight >= "
        f"{sc.grid_params.min_grazing_alt_km:g} km")
    add(f"  ground     mask {sc.gsl_params.min_elevation_deg:g} deg (ASSUMED), up to "
        f"{sc.gsl_params.max_links_per_gs} satellites per station by elevation (MODELLED)")
    add("  NOTE       hypothetical path on MODELLED links; Starlink's routing is not public "
        "and does not use T-CRH.")
    add("")
    if entry is None:
        add(f"  no path from {src} to {dst} at this instant (no visible satellite, or the grid is cut)")
        return lines, None, sc
    hdr_bytes = entry.header_for_packet(t_ns)
    hdr = proto.TcrhHeader.decode(hdr_bytes)
    deadlines = hdr.deadlines()
    add(f"  {'hop':>3}  {'node':<22} {'NORAD':>7} {'SID':>7} {'dist km':>9} {'light ms':>8} "
        f"{'hop ms':>7} {'budget ms':>9} {'cum. budget':>11} {'deadline D_k':>12} {'D_k - E':>8}")
    gs0 = sc.ground_stations[0]
    add(f"  {0:>3}  {gs0.name + ' (ground)':<22} {'':>7} {'0x%04X' % int(sc.gs_sid[0]):>7}"
        f"   (ingress, Epoch_Base E = {hdr.epoch_base})")
    prev_b = Fraction(0)
    for k, (u, v) in enumerate(zip(entry.path[:-1], entry.path[1:]), 1):
        dist = float(np.linalg.norm(sc.node_ecef_km(v, 0) - sc.node_ecef_km(u, 0)))
        is_sat = v < sc.n_sats
        name = sc.node_name(v) if is_sat else f"{sc.node_name(v)} (ground)"
        norad = str(int(sc.sat_norad[v])) if is_sat else ""
        b = entry.budgets_ns[k - 1]
        add(f"  {k:>3}  {name:<22} {norad:>7} {'0x%04X' % entry.sids_fwd[k - 1]:>7} {dist:>9.1f} "
            f"{entry.prop_ns[k - 1] / 1e6:>8.3f} {entry.hop_delays_ns[k - 1] / 1e6:>7.3f} "
            f"{float(b - prev_b) / 1e6:>9.3f} {float(b) / 1e6:>11.3f} {deadlines[k - 1]:>12} "
            f"{(deadlines[k - 1] - hdr.epoch_base) % 2**32 * unit / 1e6:>8.1f}")
        prev_b = b
    gc_km = cities_mod.great_circle_km(by_name[src], by_name[dst])
    bound_ns = float(geometry.light_time_ns_exact(gc_km))
    add("")
    add(f"  hops {entry.num_hops} ({entry.num_hops - 1} satellites); light time {entry.prop_total_ns / 1e6:.3f} ms, "
        f"predicted {entry.predicted_total_ns / 1e6:.3f} ms (incl. {entry.num_hops} x "
        f"{sc.graph.processing_ns / 1e6:g} ms processing, MODELLED)")
    add(f"  great circle {gc_km:,.1f} km -> light-speed bound {bound_ns / 1e6:.3f} ms; "
        f"light time / bound = {entry.prop_total_ns / bound_ns:.3f}, predicted / bound = "
        f"{entry.predicted_total_ns / bound_ns:.3f}")
    add(f"  deadlines: slack S = {entry.slack}, unit {unit / 1e6:g} ms (unit code {unit_code}), "
        f"ceil-cumulative deltas {list(hdr.deltas_fwd)}{' (SAT: a delta was clamped)' if hdr.is_sat else ''}")
    add(f"  T-CRH ({hdr.size} bytes, spec tcrh-v1; Epoch_Base for a packet entering at "
        f"{omm.format_utc_ns(t_ns)} = GPS {scheduler.utc_ns_to_gps_ns(t_ns)} ns):")
    add(f"    {hdr_bytes.hex()}")
    add(f"    Next Header {hdr.next_header}, Hdr Ext Len {hdr.hdr_ext_len}, Segments Left "
        f"{hdr.segments_left}, Flags 0x{hdr.flags:02x}, Num Hops {hdr.num_hops}, Epoch_Base {hdr.epoch_base}")
    return lines, entry, sc


def _run(args):
    folder = Path(args.snapshot) if args.snapshot else default_snapshot_dir()
    fleet = load_fleet(folder, args.source)
    t_ns = parse_utc(args.at) if args.at else fleet.fetched_ns
    registry = sids.SidRegistry.load_or_empty(args.registry)
    lines, entry, _ = route_report(fleet, args.from_city, args.to_city, t_ns, slack=args.slack,
                                   shell_id=args.shell, registry=registry, unit_code=args.unit_code)
    print("\n".join(lines))
    if registry.changed:
        n_s, n_g = len(registry.added_satellites), len(registry.added_ground_stations)
        path = registry.save()
        print(f"\n  sid registry: appended {n_s} satellites and {n_g} ground stations to {path}",
              file=sys.stderr)
    return 0 if entry is not None else 1


def register(registry):
    """`cr route --from A --to B ...` (a group with its own options, no sub-command)."""
    registry.group("route", help="plan one T-CRH path between two cities on the real fleet")
    parser = registry.group_parser("route")
    parser.usage = "cr route --from CITY --to CITY [--at ISO-UTC] [--snapshot DIR] [--slack S] [options]"
    parser.add_argument("--from", dest="from_city", required=True, help="source city (data/static/cities.csv)")
    parser.add_argument("--to", dest="to_city", required=True, help="destination city")
    parser.add_argument("--at", default=None, help="UTC instant, e.g. 2026-10-10T14:00:00Z "
                        "(default: the snapshot's fetch time)")
    parser.add_argument("--snapshot", default=None, help="pinned or website snapshot folder "
                        "(default: newest data/pinned/*-celestrak)")
    parser.add_argument("--source", choices=["supgp", "gp"], default=None,
                        help="pinned folders: which element sets (default supgp)")
    parser.add_argument("--slack", default=scheduler.DEFAULT_SLACK, help="multiplicative slack S (default 1.5)")
    parser.add_argument("--shell", default=DEFAULT_SHELL, help=f"shell id (default {DEFAULT_SHELL})")
    parser.add_argument("--unit-code", type=int, default=scheduler.DEFAULT_UNIT_CODE, choices=[0, 1, 2, 3],
                        help="T-CRH deadline unit code (default 1 = 0.1 ms)")
    parser.add_argument("--registry", default=None, help="SID registry (default data/static/sid_registry.json)")
    parser.set_defaults(func=_run)


__all__ = ["parse_utc", "default_snapshot_dir", "load_fleet", "route_report", "register"]

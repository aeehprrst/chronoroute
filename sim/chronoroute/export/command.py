"""
command.py
----------
The `cr export ...` commands of the topology/routing owner:

  cr export bundle --snapshot DIR --shell ID --cities "A,B,..." --start ISO
                   --duration-s 60 --flow "A->B" [--flow ...] --out DIR
      the ns-3 scenario bundle (bundle.py, docs/bundle-format.md)

  cr export web SNAPSHOT_DIR [--out-root DATA_ROOT]
      shells.json + isl_grid4.json next to a website snapshot's omm.min.json

  cr export sids SNAPSHOT_DIR [SNAPSHOT_DIR ...]
      register every NORAD id of the given snapshots (both GP and SupGP) and
      every city in the stable SID registry (append-only)
"""

import sys
import time
from pathlib import Path

from .. import provenance
from ..data import cities as cities_mod, omm, snapshot
from ..route import command as route_cmd, scheduler, sids
from ..topo import gsl as gsl_mod, isl_grid4
from . import bundle as bundle_mod, web as web_mod

GROUP_HELP = "export data for ns-3, the website and other tools"


def _parse_flow(text):
    src, sep, dst = text.partition("->")
    if not sep or not src.strip() or not dst.strip():
        raise ValueError(f"flow {text!r} must look like 'Chennai->London'")
    return src.strip(), dst.strip()


def _save_registry(registry):
    if registry.changed:
        n_s, n_g = len(registry.added_satellites), len(registry.added_ground_stations)
        path = registry.save()
        print(f"sid registry: appended {n_s} satellites and {n_g} ground stations to {path}")


def _human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:,.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def _run_bundle(args):
    t_start = time.perf_counter()
    folder = Path(args.snapshot) if args.snapshot else route_cmd.default_snapshot_dir()
    fleet = route_cmd.load_fleet(folder, args.source)
    cities = tuple(c.strip() for c in args.cities.split(",") if c.strip())
    flows = [_parse_flow(f) for f in (args.flow or [])]
    if args.reverse:
        flows += [(d, s) for s, d in flows if (d, s) not in flows]
    if args.duration_ms is not None:
        window_ms = args.duration_ms
    else:
        window_ms = int(round(args.duration_s * 1000))
    config = bundle_mod.BundleConfig(
        shell_id=args.shell, cities=cities, t0_ns=route_cmd.parse_utc(args.start), window_ms=window_ms,
        flows=tuple(flows), step_ms=args.step_ms, position_step_ms=args.position_step_ms,
        refresh_ms=args.refresh_ms, slack=args.slack, unit_code=args.unit_code,
        grid=isl_grid4.Grid4Params(max_range_km=args.isl_max_range_km),
        gsl=gsl_mod.GslParams(policy=args.gsl_policy), plan_links=args.plan_links)
    registry = sids.SidRegistry.load_or_empty(args.registry)
    with provenance.RunTimer() as timer:
        t0 = time.perf_counter()
        try:
            b = bundle_mod.build_bundle(fleet, config, registry)
        except bundle_mod.InvariantError as exc:
            print(f"cr export bundle: refusing to write a bundle: {exc}", file=sys.stderr)
            return 3
        t_build = time.perf_counter() - t0
        t0 = time.perf_counter()
        paths = bundle_mod.write_bundle(b, args.out, command=["cr", *args.argv], timer=timer)
        t_write = time.perf_counter() - t0
    _save_registry(registry)
    problems = bundle_mod.check_bundle(args.out)
    sc = b.scenario
    print(f"bundle {args.out}")
    print(f"  snapshot {fleet.snapshot_id} ({fleet.source.name}); shell {sc.shell.shell_id}: "
          f"{sc.n_sats} satellites in planes ({sc.excluded['off_grid']} off-grid left out), "
          f"{len(sc.ground_stations)} ground stations")
    print(f"  window {config.window_ms} ms from {omm.format_utc_ns(config.t0_ns)}, "
          f"{len(sc.times_ns)} steps of {config.step_ms} ms; {len(sc.isl_a)} ISL pairs "
          f"(MODELLED Grid-4), {len(sc.gsl_gs)} ground-link pairs ever visible")
    print(f"  models: ground links {config.gsl.policy} [MODELLED], planning {config.plan_links}, "
          f"laser range limit {config.grid.max_range_km if config.grid.max_range_km else 'none (80 km rule only)'}")
    print(f"  flows {len(b.flows)}, schedule rows {len(b.entries)}, gaps (no path) {len(b.gaps)}")
    inv = b.invariants
    print(f"  invariants all ok: {inv['all_ok']} (ISL min height {inv['isl_clearance']['min_height_km']:.1f} km, "
          f"longest up ISL {inv['isl_clearance']['longest_up_isl_km']:.1f} km, "
          f"GSL min elevation {inv['gsl_geometry']['min_elevation_deg']:.2f} deg, "
          f"max ISL degree {inv['isl_degree']['max_degree']}, "
          f"min light time / great circle {inv['path_latency']['min_light_time_over_great_circle']})")
    stab = inv["schedule_stability"]
    print(f"  schedule rows whose path loses a link while in use: {stab['rows_with_a_link_down_in_use']} "
          f"of {stab['checked']} ({'must be 0' if stab['required'] else 'allowed with --plan-links instant'})")
    total = 0
    for name, path in paths.items():
        size = Path(path).stat().st_size
        total += size
        print(f"    {name:<15} {size:>13,} B  ({_human(size)})")
    print(f"    {'total':<15} {total:>13,} B  ({_human(total)})")
    print(f"  time: build {t_build:.1f} s, write {t_write:.1f} s, total {time.perf_counter() - t_start:.1f} s")
    if problems:
        print("  check_bundle problems:\n    " + "\n    ".join(problems))
        return 3
    print("  check_bundle: OK (headers, row counts, order, SIDs, T-CRH templates re-built)")
    return 0


def _run_web(args):
    folder = Path(args.snapshot_dir)
    layout = snapshot.detect_layout(folder)
    if layout == "pinned":
        if not args.out_root:
            print("cr export web: a pinned folder needs --out-root (the website data directory)", file=sys.stderr)
            return 2
        fleet = snapshot.load_pinned(folder, args.source or "supgp")
        written = snapshot.write_web_snapshot(fleet, args.out_root, snapshot_id=args.snapshot_id,
                                              update_latest=args.update_latest)
        target = written["snapshot_dir"]
        fleet = snapshot.load_web_snapshot(target)
        print(f"wrote website snapshot {target} (manifest.json, omm.min.json) with the data owner's writer")
    else:
        fleet = snapshot.load_web_snapshot(folder)
        target = folder
    out = web_mod.export_web(fleet, target, command=["cr", *args.argv])
    geo = out["geometry"]
    for key in ("shells", "isl_grid4"):
        print(f"wrote {out[key]} ({Path(out[key]).stat().st_size:,} B)")
    print(f"wrote {out['manifest']}")
    print(f"  {len(geo.shells)} shells [DERIVED], Grid-4 pairs [MODELLED] at {fleet.fetched_utc}")
    return 0


def _run_sids(args):
    registry = sids.SidRegistry.load_or_empty(args.registry)
    for folder in args.snapshot_dirs:
        folder = Path(folder)
        if snapshot.detect_layout(folder) == "web":
            norads = [r.norad for r in snapshot.load_web_snapshot(folder).records]
        else:
            norads = []
            for source in snapshot.available_sources(folder):
                norads += [r.norad for r in snapshot.load_pinned(folder, source).records]
        added = registry.ensure_satellites(norads)
        print(f"{folder.name}: {len(set(norads))} NORAD ids, {len(added)} new")
    added = registry.ensure_ground_stations([c.name for c in cities_mod.load_cities()])
    print(f"cities: {len(added)} new ground stations")
    if registry.changed:
        _save_registry(registry)
    else:
        print("sid registry unchanged")
    print(f"registry: {registry.n_satellites} satellites, {registry.n_ground_stations} ground stations")
    return 0


def register(registry):
    p = registry.command("export", "bundle", help="ns-3 scenario bundle (docs/bundle-format.md)",
                         func=_run_bundle, group_help=GROUP_HELP)
    p.add_argument("--snapshot", default=None, help="pinned or website snapshot folder "
                   "(default: newest data/pinned/*-celestrak)")
    p.add_argument("--source", choices=["supgp", "gp"], default=None, help="pinned folders: element sets (default supgp)")
    p.add_argument("--shell", default=route_cmd.DEFAULT_SHELL, help="shell id, e.g. 53.2deg-463km")
    p.add_argument("--cities", required=True, help='comma-separated city names, e.g. "Chennai,London"')
    p.add_argument("--start", required=True, help="t0, ISO 8601 UTC ending in Z")
    dur = p.add_mutually_exclusive_group(required=True)
    dur.add_argument("--duration-s", type=float, default=None, help="window length in seconds")
    dur.add_argument("--duration-ms", type=int, default=None, help="window length in milliseconds")
    p.add_argument("--flow", action="append", help='"Src->Dst"; repeat for more flows')
    p.add_argument("--reverse", action="store_true", help="also add every flow's reverse direction")
    p.add_argument("--step-ms", type=int, default=100, help="link-state / delay step (default 100)")
    p.add_argument("--position-step-ms", type=int, default=1000, help="positions.csv step (default 1000)")
    p.add_argument("--refresh-ms", type=int, default=1000, help="schedule refresh interval (default 1000)")
    p.add_argument("--slack", default=scheduler.DEFAULT_SLACK, help="multiplicative slack S (default 1.5)")
    p.add_argument("--unit-code", type=int, default=scheduler.DEFAULT_UNIT_CODE, choices=[0, 1, 2, 3])
    p.add_argument("--gsl-policy", choices=list(gsl_mod.POLICIES), default=gsl_mod.POLICY_STICKY,
                   help="which visible satellites a city uses (MODELLED): sticky_top_k keeps a "
                        "satellite while it is visible (default); highest_elevation_top_k re-picks "
                        "the 4 highest every step (the original variant)")
    p.add_argument("--plan-links", choices=list(bundle_mod.PLAN_MODES), default=bundle_mod.PLAN_STABLE,
                   help="stable (default): plan each interval on links that stay up until its last "
                        "packet's final deadline; instant: links up at the planning instant only")
    p.add_argument("--isl-max-range-km", type=float, default=None,
                   help="laser range limit in km (default: none, only the 80 km grazing rule)")
    p.add_argument("--registry", default=None, help="SID registry (default data/static/sid_registry.json)")
    p.add_argument("--out", required=True, help="output folder")

    p = registry.command("export", "web", help="shells.json + isl_grid4.json for a website snapshot",
                         func=_run_web, group_help=GROUP_HELP)
    p.add_argument("snapshot_dir", help="website snapshot folder (manifest.json + omm.min.json), "
                   "or a pinned folder together with --out-root")
    p.add_argument("--out-root", default=None, help="website data root (public/data) for a pinned input")
    p.add_argument("--snapshot-id", default=None, help="pinned input: snapshot id (default <fetch time>-<source>)")
    p.add_argument("--source", choices=["supgp", "gp"], default=None)
    p.add_argument("--update-latest", action="store_true", help="pinned input: also point latest.json at it")

    p = registry.command("export", "sids", help="register NORAD ids and cities in the SID registry",
                         func=_run_sids, group_help=GROUP_HELP)
    p.add_argument("snapshot_dirs", nargs="+", help="snapshot folders, oldest first")
    p.add_argument("--registry", default=None, help="SID registry (default data/static/sid_registry.json)")


__all__ = ["register"]

"""
command.py
----------
The viewer's commands (registered in cli.COMMAND_MODULES):

  cr viz globe  --trace DIR | --snapshot DIR  [--follow FLOW] [--shell ID]
                [--record out.mp4 --seconds N] [--screenshot out.png --at S]
                [--bench N]
      the PyVista 3D viewer (globe.py): an interactive WSLg window, or an
      off-screen MP4 / PNG / frame-time benchmark

  cr viz map2d  --trace DIR | --snapshot DIR  [--follow FLOW]
                [--out map.png --at S] [--record out.mp4 --seconds N]
      the matplotlib 2D fallback (map2d.py)

  cr trace from-ns3 RUN_DIR --out DIR [--variant fault]
      ns-3 course-milestone run -> chronoroute.trace/1 (trace/ns3_import.py)

PyVista, VTK and imageio-ffmpeg are imported only when a viz command runs, so
`cr` itself stays fast and works without them.
"""

import json
import os
import statistics
import sys
import time
from pathlib import Path

GROUP_HELP = "the in-tool viewer: 3D globe, 2D map, recordings"


def _size(text):
    try:
        w, h = (int(x) for x in str(text).lower().split("x"))
    except ValueError:
        raise ValueError(f"--size must look like 1920x1080, got {text!r}") from None
    if w < 320 or h < 240:
        raise ValueError("--size must be at least 320x240")
    return w, h


def choose_gl(software=False):
    """Pick the OpenGL driver before VTK creates a context (docs/viewer.md).

    WSLg's default is llvmpipe (software). With /dev/dxg present and nothing set by
    the user, GALLIUM_DRIVER=d3d12 selects the GPU (the plan's measured setup). The
    HUD's renderer line always names what was really used.
    """
    if software:
        os.environ["GALLIUM_DRIVER"] = "llvmpipe"
        os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
        return "software (requested)"
    if "GALLIUM_DRIVER" not in os.environ and "LIBGL_ALWAYS_SOFTWARE" not in os.environ \
            and Path("/dev/dxg").exists():
        os.environ["GALLIUM_DRIVER"] = "d3d12"
        return "GALLIUM_DRIVER=d3d12 (set by cr viz: WSL GPU)"
    return f"GALLIUM_DRIVER={os.environ.get('GALLIUM_DRIVER', '(unset)')}"


def _load(args):
    from . import sources
    from ..route.command import parse_utc
    cities = [c.strip() for c in args.cities.split(",")] if args.cities else None
    start = parse_utc(args.start) if args.start else None
    return sources.load_viewer_data(trace_dir=args.trace, snapshot_dir=args.snapshot, shell=args.shell,
                                    cities=cities, start_utc_ns=start)


def _inputs(args):
    return {"trace": args.trace, "snapshot": args.snapshot, "shell": args.shell,
            "follow": args.follow, "start": args.start}


def bench_globe(viewer, frames, warmup=5):
    """Frame times of the orbit animation, off-screen (the orbit clock runs, so every frame
    has new SGP4 positions, a new link up/down state and a new scene).

    Two loops, because they measure different things:
      * animation: update + Render(), what an interactive window does per frame (an
        on-screen window adds the buffer swap through WSLg, which cannot be measured
        headless);
      * recording: update + Render() + read the pixels back (record.py does this per frame).
    """
    ctl = viewer.ctl
    viewer.render()
    med = statistics.median
    upd, rend = [], []
    for i in range(frames + warmup):
        t0 = time.perf_counter()
        viewer.update(1.0 / 30)
        t1 = time.perf_counter()
        viewer.plotter.ren_win.Render()
        t2 = time.perf_counter()
        if i >= warmup:
            upd.append(t1 - t0)
            rend.append(t2 - t1)
    rec = []
    for i in range(frames + warmup):
        t0 = time.perf_counter()
        viewer.update(1.0 / 30)
        viewer.grab_frame()
        if i >= warmup:
            rec.append(time.perf_counter() - t0)
    return {"frames": frames, "size": list(viewer.window_size), "satellites": ctl.n_sats,
            "laser_links_drawn_last_frame": int(len(ctl.visible_links())),
            "lite": ctl.lite, "renderer": viewer.renderer_text,
            "update_ms_median": round(1000 * med(upd), 2),
            "render_ms_median": round(1000 * med(rend), 2),
            "fps_animation": round(1.0 / (med(upd) + med(rend)), 1),
            "record_frame_ms_median": round(1000 * med(rec), 2),
            "fps_recording": round(1.0 / med(rec), 1)}


def _run_globe(args):
    gl = choose_gl(args.software)
    from . import globe as globe_mod
    size = _size(args.size) if args.size else None
    off = bool(args.record or args.screenshot or args.bench)
    if not off and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("cr viz globe: no display (DISPLAY / WAYLAND_DISPLAY unset). Use --record, "
              "--screenshot or cr viz map2d --out.", file=sys.stderr)
        return 2
    if size is None:
        size = (1920, 1080) if off else (1440, 810)
    t0 = time.perf_counter()
    data = _load(args)
    print(f"loaded {data.mode}: {data.n_sats} satellites, {len(data.isl)} candidate laser links "
          f"({data.isl.source}) in {time.perf_counter() - t0:.1f} s; {gl}")
    for note in data.notes:
        print(f"  note: {note}")
    viewer = globe_mod.GlobeViewer(data, follow=args.follow, off_screen=off, window_size=size,
                                   orbit_speed=args.orbit_speed, slowmo=args.slowmo, lite=args.lite,
                                   autoplay=args.autoplay or bool(args.record) or bool(args.screenshot))
    if args.bench:
        stats = bench_globe(viewer, args.bench)
        print(json.dumps(stats, indent=1))
        if args.bench_json:
            Path(args.bench_json).write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
        viewer.close()
        return 0
    if args.screenshot:
        viewer.run_timeline(args.at)
        viewer.screenshot(args.screenshot)
        print(f"wrote {args.screenshot} ({size[0]}x{size[1]}, {viewer.renderer_text})")
        viewer.close()
        return 0
    if args.record:
        from . import record
        from ..provenance import RunTimer
        record.check_out_dir(args.record)
        with RunTimer() as timer:
            stats = record.record_mp4(viewer, args.record, args.seconds, fps=args.fps,
                                      progress=lambda i, n: print(f"  frame {i}/{n}", end="\r"))
        print()
        snap = data.snapshot.folder if data.snapshot is not None else None
        path = record.write_record_manifest(args.record, stats, command=["cr", *args.argv],
                                            inputs=_inputs(args), labels=_manifest_labels(data),
                                            snapshot_dir=snap, timer=timer)
        print(f"wrote {args.record}: {stats['frames']} frames at {stats['fps']} fps, "
              f"{stats['size'][0]}x{stats['size'][1]}; render {stats['render_ms_per_frame']:.1f} ms/frame "
              f"({stats['renderer']}); manifest {path}")
        viewer.close()
        return 0
    viewer.show()
    return 0


def _manifest_labels(data):
    """Only REAL / DERIVED / MODELLED labels can go into a manifest (provenance schema)."""
    return {k: v for k, v in data.labels.items() if v in ("REAL", "DERIVED", "MODELLED")}


def _run_map2d(args):
    from . import map2d as map2d_mod
    data = _load(args)
    size = _size(args.size) if args.size else (1440, 810)
    interactive = not (args.out or args.record)
    if interactive and not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("cr viz map2d: no display; use --out map.png or --record out.mp4", file=sys.stderr)
        return 2
    view = map2d_mod.Map2D(data, follow=args.follow, size_px=size, interactive=interactive,
                           orbit_speed=args.orbit_speed, slowmo=args.slowmo, lite=args.lite,
                           autoplay=args.autoplay or not interactive)
    if args.out:
        view.run_timeline(args.at)
        view.save_png(args.out)
        print(f"wrote {args.out}")
        return 0
    if args.record:
        from . import record
        from ..provenance import RunTimer
        record.check_out_dir(args.record)
        with RunTimer() as timer:
            stats = view.record_mp4(args.record, args.seconds, fps=args.fps)
        stats.update(update_ms_per_frame=0.0, render_ms_per_frame=0.0, renderer="matplotlib (software)")
        snap = data.snapshot.folder if data.snapshot is not None else None
        record.write_record_manifest(args.record, stats, command=["cr", *args.argv], inputs=_inputs(args),
                                     labels=_manifest_labels(data), snapshot_dir=snap, timer=timer)
        print(f"wrote {args.record}: {stats['frames']} frames")
        return 0
    view.show()
    return 0


def _common(p):
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--trace", default=None,
                     help="chronoroute.trace/1 run folder (run.json + events.jsonl.gz)")
    src.add_argument("--snapshot", default=None, help="pinned snapshot folder: the fleet view, no packets")
    p.add_argument("--follow", default=None, help="flow to show: its id or 'Src->Dst' (default: the flow "
                   "of the first deadline miss)")
    p.add_argument("--shell", default=None, help="snapshot view: only this shell (e.g. 53.2deg-463km), "
                   "with its Grid-4 links; default: the whole fleet")
    p.add_argument("--cities", default=None, help="extra labelled cities, comma-separated")
    p.add_argument("--start", default=None, help="orbit clock start, ISO UTC ending in Z "
                   "(default: the first packet, or the snapshot's fetch time)")
    p.add_argument("--size", default=None, help="window / frame size WxH")
    p.add_argument("--orbit-speed", type=float, default=60.0, help="orbit clock speed (default x60)")
    p.add_argument("--slowmo", type=float, default=100.0, help="packet slow motion (default x100: "
                   "1 ms of packet time takes 100 ms)")
    p.add_argument("--lite", choices=["auto", "on", "off"], default="auto",
                   help="laser links only near the path (auto: above 3,000 satellites)")
    p.add_argument("--autoplay", action="store_true", help="play packets by themselves")
    p.add_argument("--record", default=None, metavar="OUT.mp4", help="record off-screen to MP4")
    p.add_argument("--seconds", type=float, default=10.0, help="length of the recording (default 10)")
    p.add_argument("--fps", type=int, default=30, help="recording frame rate (default 30)")


def register(registry):
    p = registry.command("viz", "globe", help="3D viewer (PyVista): satellites, laser links, a packet "
                         "in slow motion", func=_run_globe, group_help=GROUP_HELP)
    _common(p)
    p.add_argument("--screenshot", default=None, metavar="OUT.png", help="render one frame off-screen")
    p.add_argument("--at", type=float, default=0.0, help="screenshot after this many seconds of autoplay")
    p.add_argument("--bench", type=int, default=0, metavar="N", help="time N off-screen frames and exit")
    p.add_argument("--bench-json", default=None, help="also write the benchmark result here")
    p.add_argument("--software", action="store_true", help="force software OpenGL (llvmpipe)")

    p = registry.command("viz", "map2d", help="2D fallback map (matplotlib)", func=_run_map2d,
                         group_help=GROUP_HELP)
    _common(p)
    p.add_argument("--out", default=None, metavar="OUT.png", help="write one frame to a PNG")
    p.add_argument("--at", type=float, default=0.0, help="the PNG after this many seconds of autoplay")

    from ..trace import ns3_import
    p = registry.command("trace", "from-ns3", help="ns-3 course-milestone run -> chronoroute.trace/1",
                         func=ns3_import.run_command, group_help="trace tools")
    ns3_import.register_args(p)


__all__ = ["register", "choose_gl", "bench_globe"]

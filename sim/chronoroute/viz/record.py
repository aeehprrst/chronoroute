"""
record.py
---------
Off-screen recording of the globe to MP4 (`cr viz globe ... --record out.mp4 --seconds N`).

Why off-screen: a recording must not depend on a window being open, on the
desktop's scaling (WSLg shows apps a 1440x810 screen) or on how fast frames
appear. Every frame advances the viewer by exactly 1/fps of screen time
(GlobeViewer.update), so the same command always produces the same sequence of
frames; only the encoder's bytes may differ between ffmpeg builds.

Frames go straight to ffmpeg through imageio-ffmpeg 0.6.0 (it bundles an ffmpeg
binary, so no system ffmpeg is needed). PyVista's own open_movie() needs the
separate `imageio` package, which this venv does not have, so it is not used.

Each recording folder gets a provenance manifest (provenance.write_manifest),
listing the MP4 and the inputs (trace / snapshot) it was made from. A folder that
already has a manifest from another tool is refused, so a recording never
overwrites another run's provenance: record into its own folder.
"""

import json
import time
from pathlib import Path

import numpy as np

from .. import __version__, provenance

DEFAULT_SIZE = (1920, 1080)
DEFAULT_FPS = 30
TOOL = "cr-viz"


def check_out_dir(out_path):
    """Refuse to overwrite another tool's manifest in the recording's folder."""
    folder = Path(out_path).resolve().parent
    manifest = folder / provenance.MANIFEST_NAME
    if manifest.is_file():
        try:
            tool = json.loads(manifest.read_text(encoding="utf-8")).get("tool")
        except (OSError, ValueError):
            tool = None
        if tool != TOOL:
            raise FileExistsError(f"{manifest} belongs to another run (tool {tool!r}); "
                                  "record into a folder of its own")
    return folder


def record_mp4(viewer, out_path, seconds, *, fps=DEFAULT_FPS, quality=7, progress=None):
    """Render `seconds` of the viewer at `fps` into out_path (H.264 MP4). Returns stats."""
    import imageio_ffmpeg
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n = int(round(seconds * fps))
    w, h = viewer.window_size
    viewer.render()
    # macro_block_size=8: 1080 is a multiple of 8 but not 16, and the default (16)
    # would make ffmpeg rescale the frames.
    writer = imageio_ffmpeg.write_frames(str(out_path), (w, h), fps=fps, quality=quality,
                                         macro_block_size=8, ffmpeg_log_level="error")
    writer.send(None)
    t_render = t_update = 0.0
    try:
        for i in range(n):
            t0 = time.perf_counter()
            viewer.update(1.0 / fps)
            t1 = time.perf_counter()
            img = viewer.grab_frame()          # render + read back THIS frame
            t2 = time.perf_counter()
            if img.shape[0] != h or img.shape[1] != w:
                raise RuntimeError(f"frame {i} is {img.shape[1]}x{img.shape[0]}, expected {w}x{h}")
            writer.send(np.ascontiguousarray(img[:, :, :3]))
            t_update += t1 - t0
            t_render += t2 - t1
            if progress and (i + 1) % fps == 0:
                progress(i + 1, n)
    finally:
        writer.close()
    return {"frames": n, "fps": fps, "seconds": n / fps, "size": [w, h],
            "update_ms_per_frame": 1000 * t_update / max(n, 1),
            "render_ms_per_frame": 1000 * t_render / max(n, 1), "renderer": viewer.renderer_text}


def probe_mp4(path, keep_every=0):
    """(frames, fps, (w, h), kept) read back from an MP4 with imageio-ffmpeg (used by the tests).

    kept: every keep_every'th decoded frame as an (h, w, 3) uint8 array (none if 0).
    """
    import imageio_ffmpeg
    reader = imageio_ffmpeg.read_frames(str(path))
    meta = reader.__next__()
    w, h = meta.get("size", (0, 0))
    frames, kept = 0, []
    for buf in reader:
        if keep_every and frames % keep_every == 0:
            kept.append(np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3))
        frames += 1
    return frames, meta.get("fps"), (w, h), kept


def write_record_manifest(out_path, stats, *, command, inputs, labels, snapshot_dir=None, timer=None):
    """manifest.json next to the MP4 (see the module docstring)."""
    folder = check_out_dir(out_path)
    snapshot = snapshot_dir if snapshot_dir and (Path(snapshot_dir) / "SHA256SUMS").is_file() else None
    return provenance.write_manifest(
        folder, tool=TOOL, tool_version=__version__, command=command,
        config={"inputs": inputs, "frames": stats["frames"], "fps": stats["fps"],
                "size": stats["size"], "timeline": "1/fps screen seconds per frame (deterministic)"},
        seeds=[], snapshot=snapshot, outputs=[out_path], labels=labels,
        extra={"render_ms_per_frame": round(stats["render_ms_per_frame"], 2),
               "update_ms_per_frame": round(stats["update_ms_per_frame"], 2),
               "renderer": stats.get("renderer")},
        timer=timer)


__all__ = ["record_mp4", "probe_mp4", "write_record_manifest", "check_out_dir", "DEFAULT_SIZE",
           "DEFAULT_FPS"]

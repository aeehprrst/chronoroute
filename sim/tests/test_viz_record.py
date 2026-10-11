"""
Off-screen MP4 recording (sim/chronoroute/viz/record.py): a 3 s, 1920x1080, 30 fps
recording of the real-data synthetic trace, read back with imageio-ffmpeg, plus
its provenance manifest.
"""

import json

import numpy as np
import pytest

pytest.importorskip("pyvista")
pytest.importorskip("imageio_ffmpeg")

from chronoroute import provenance                          # noqa: E402
from chronoroute.viz import globe, record, sources          # noqa: E402
from test_viz_sources import SNAPSHOT, make_trace            # noqa: E402


def test_record_three_seconds_at_1080p(tmp_path):
    data = sources.load_viewer_data(trace_dir=make_trace(tmp_path / "run"))
    v = globe.GlobeViewer(data, off_screen=True, window_size=record.DEFAULT_SIZE, autoplay=True)
    out = tmp_path / "rec" / "globe.mp4"
    try:
        stats = record.record_mp4(v, out, 3.0, fps=30)
    finally:
        v.close()
    assert stats["frames"] == 90 and stats["size"] == [1920, 1080]
    assert out.is_file() and out.stat().st_size > 50_000
    frames, fps, size, kept = record.probe_mp4(out, keep_every=10)
    assert frames == 90 and fps == pytest.approx(30.0) and size == (1920, 1080)
    # it is a moving picture, not one frame repeated: every kept frame differs from the next
    # (pixels that changed by more than the encoder noise; the packet and clocks move)
    changed = [int((np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 24).sum())
               for a, b in zip(kept, kept[1:])]
    assert len(kept) == 9 and min(changed) > 100, changed
    path = record.write_record_manifest(out, stats, command=["cr", "viz", "globe", "--record", str(out)],
                                        inputs={"trace": str(tmp_path / "run")},
                                        labels={"satellite_positions_sgp4": "REAL",
                                                "isl_topology_grid4": "MODELLED"},
                                        snapshot_dir=SNAPSHOT)
    doc = provenance.validate_manifest(path)          # raises if the schema, hashes or sizes are off
    assert doc["tool"] == record.TOOL and doc["outputs"][0]["path"] == "globe.mp4"
    assert doc["config"]["frames"] == 90 and doc["extra"]["renderer"].startswith("renderer: ")


def test_recording_never_overwrites_another_runs_manifest(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"tool": "cr run"}))
    with pytest.raises(FileExistsError, match="record into a folder of its own"):
        record.check_out_dir(tmp_path / "x.mp4")
    (tmp_path / "manifest.json").write_text(json.dumps({"tool": record.TOOL}))
    assert record.check_out_dir(tmp_path / "x.mp4") == tmp_path.resolve()

"""
The matplotlib 2D fallback (sim/chronoroute/viz/map2d.py): antimeridian splitting,
a PNG frame, and the texture's orientation on the flat map.
"""

import numpy as np
import pytest

from chronoroute.viz import map2d, sources
from test_viz_sources import make_trace

CITIES = {"Greenwich": (51.4779, -0.0015), "Chennai": (13.0827, 80.2707),
          "New York": (40.7128, -74.0060), "Sydney": (-33.8688, 151.2093)}


def test_split_segment_at_the_antimeridian():
    # no crossing: unchanged
    assert map2d.split_segment(10.0, 5.0, 20.0, 6.0) == [((10.0, 5.0), (20.0, 6.0))]
    # 170E -> 170W (20 deg east across 180): two pieces meeting at +-180, latitude interpolated
    (a, b), (c, d) = map2d.split_segment(170.0, 10.0, -170.0, 30.0)
    assert a == (170.0, 10.0) and b == (180.0, pytest.approx(20.0))
    assert c == (-180.0, pytest.approx(20.0)) and d == (-170.0, 30.0)
    # and westwards
    (a, b), (c, d) = map2d.split_segment(-175.0, -40.0, 165.0, -20.0)
    assert b[0] == -180.0 and c[0] == 180.0 and b[1] == pytest.approx(-35.0) == c[1]
    # every piece stays on the map and no piece is longer than 180 deg of longitude
    rng = np.random.default_rng(1)
    for _ in range(500):
        lon1, lon2 = rng.uniform(-180, 180, 2)
        lat1, lat2 = rng.uniform(-80, 80, 2)
        for (x1, y1), (x2, y2) in map2d.split_segment(lon1, lat1, lon2, lat2):
            assert -180 <= x1 <= 180 and -180 <= x2 <= 180 and abs(x2 - x1) <= 180 + 1e-9
            assert min(lat1, lat2) - 1e-9 <= y1 <= max(lat1, lat2) + 1e-9


def test_vectorised_split_matches_the_scalar_one():
    rng = np.random.default_rng(2)
    lon_a, lon_b = rng.uniform(-180, 180, (2, 300))
    lat_a, lat_b = rng.uniform(-70, 70, (2, 300))
    vec = map2d.split_segments(lon_a, lat_a, lon_b, lat_b)
    scalar = [p for i in range(300) for p in map2d.split_segment(lon_a[i], lat_a[i], lon_b[i], lat_b[i])]
    as_set = lambda segs: sorted(tuple(np.round(np.ravel(s), 9)) for s in segs)
    assert as_set(vec) == as_set(scalar)


def test_split_polyline():
    pieces = map2d.split_polyline([160.0, 175.0, -170.0, -160.0], [0.0, 10.0, 20.0, 25.0])
    assert len(pieces) == 2
    assert pieces[0][0][-1] == 180.0 and pieces[1][0][0] == -180.0
    assert pieces[0][1][-1] == pytest.approx(pieces[1][1][0])


@pytest.fixture(scope="module")
def view(tmp_path_factory):
    data = sources.load_viewer_data(trace_dir=make_trace(tmp_path_factory.mktemp("viz-map2d") / "run"))
    return map2d.Map2D(data, size_px=(1200, 675), engine=None)


def test_map2d_png_frame(view, tmp_path):
    view.ctl.key_degrade()
    view.run_timeline(4.0)
    out = tmp_path / "map.png"
    view.save_png(out)
    assert out.is_file() and out.stat().st_size > 50_000
    assert "2D fallback" in view.t_title.get_text()
    assert "Positions REAL" in view.t_labels.get_text() and "| Queues MODELLED" in view.t_labels.get_text()
    assert "LATE" in view.t_clock.get_text() or "FALLBACK" in view.t_clock.get_text()
    assert "software" in view.t_render.get_text()


def test_map2d_keys(view):
    """The 2D map's key handler drives the same controller as the globe."""
    from types import SimpleNamespace
    ctl = view.ctl
    ctl.key_next()
    first = ctl.track.pkt
    view._on_key(SimpleNamespace(key=" "))
    assert ctl.track.pkt != first
    view._on_key(SimpleNamespace(key="l"))
    assert ctl.overlay and "LINK-STATE VIEW" in view.t_side.get_text()
    view._on_key(SimpleNamespace(key="l"))
    slow = ctl.player.slowmo
    view._on_key(SimpleNamespace(key="+"))
    assert ctl.player.slowmo == slow / 2
    view._on_key(SimpleNamespace(key="d"))
    assert ctl.track.is_late and "replay-only" in ctl.message
    ctl.message = None
    view._on_key(SimpleNamespace(key="f"))
    assert ctl.track.is_late and "replay-only" in ctl.message
    view._on_key(SimpleNamespace(key="x"))                 # unbound: ignored


def test_map2d_texture_orientation(view):
    """Around each city, the figure's background pixels are the texture's pixels at those
    coordinates, and clearly not those of a shifted, mirrored or flipped map."""
    import matplotlib.pyplot as plt
    from chronoroute.viz import globe
    tex = plt.imread(str(globe.TEXTURE))
    drawn = list(view.ax.collections) + list(view.ax.texts)
    for art in drawn:                                   # only the background map is left
        art.set_visible(False)
    try:
        img = view.frame_rgb().astype(float)
    finally:
        for art in drawn:
            art.set_visible(True)
    h = img.shape[0]
    offsets = np.linspace(-4.0, 4.0, 9)                 # a 9 x 9 grid of points, 1 deg apart
    for name, (lat, lon) in CITIES.items():
        LAT, LON = np.meshgrid(lat + offsets, lon + offsets, indexing="ij")
        xy = view.ax.transData.transform(np.column_stack([LON.ravel(), LAT.ravel()]))
        cols = np.round(xy[:, 0]).astype(int)
        rows = np.round(h - xy[:, 1]).astype(int)
        got = img[rows, cols]
        errs = {}
        for wrong in (None, "shift180", "mirror", "flip"):
            la, lo = LAT.ravel(), LON.ravel()
            if wrong == "shift180":
                lo = (lo + 360.0) % 360.0 - 180.0
            elif wrong == "mirror":
                lo = -lo
            elif wrong == "flip":
                la = -la
            r, c = globe.texture_pixel(tex, la, lo)
            errs[wrong] = float(np.abs(got - tex[r, c].astype(float)).mean())
        assert errs[None] < 20, (name, errs)
        assert errs[None] * 2 < min(errs["shift180"], errs["mirror"], errs["flip"]), (name, errs)

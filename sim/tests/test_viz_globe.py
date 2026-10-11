"""
The PyVista globe (sim/chronoroute/viz/globe.py), rendered off-screen (no window,
no display needed: VTK falls back to EGL / OSMesa).

  * smoke test: a frame of the real-data synthetic trace is written to a PNG;
  * texture orientation: markers at Greenwich, Chennai, New York and Sydney, and
    the rendered Earth around each one compared with the texture at those
    coordinates (and with the three wrong orientations a map can have: shifted
    by 180 deg, mirrored east-west, flipped north-south);
  * what is on screen: the HUD text, the header hex, the late node's colour, and
    the link-state view keeping the slowed link green.
"""

import os

import numpy as np
import pytest

pv = pytest.importorskip("pyvista")

from PIL import Image                                         # noqa: E402

from chronoroute.orbit import frames                          # noqa: E402
from chronoroute.viz import globe, hud, player as pl, sources  # noqa: E402
from test_viz_sources import A, B, C, make_trace              # noqa: E402

pv.OFF_SCREEN = True

CITIES = {"Greenwich": (51.4779, -0.0015), "Chennai": (13.0827, 80.2707),
          "New York": (40.7128, -74.0060), "Sydney": (-33.8688, 151.2093)}


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return sources.load_viewer_data(trace_dir=make_trace(tmp_path_factory.mktemp("viz-globe") / "run"))


# ----------------------------------------------------------------------- smoke

def test_offscreen_render_writes_a_png(data, tmp_path):
    v = globe.GlobeViewer(data, off_screen=True, window_size=(800, 450), autoplay=True)
    try:
        v.run_timeline(2.0)
        out = tmp_path / "globe.png"
        img = v.screenshot(out)
        assert out.is_file() and out.stat().st_size > 20_000
        assert img.shape == (450, 800, 3)
        assert img.std() > 20                                 # not a blank frame
        assert v.renderer_text.startswith("renderer: ") and "unknown" not in v.renderer_text
        back = np.asarray(Image.open(out))
        assert back.shape[:2] == (450, 800)
        assert np.array_equal(back, img)
        # the next frame is a new picture (pyvista alone would hand back the previous one)
        v.update(1 / 30)
        nxt = v.grab_frame()
        assert np.abs(nxt.astype(int) - img.astype(int)).sum() > 0
    finally:
        v.close()


# ----------------------------------------------------------------------- texture orientation

def test_earth_mesh_texture_coordinates_follow_lat_lon():
    mesh = globe.make_earth_mesh(91, 181)
    lat, lon = mesh.point_data["lat"], mesh.point_data["lon"]
    glat, glon, h = frames.ecef_to_geodetic(mesh.points.astype(float))
    inner = (np.abs(lat) < 89.9) & (np.abs(lon) < 179.9)        # poles and seam are degenerate
    assert np.max(np.abs(glat[inner] - lat[inner])) < 1e-4
    assert np.max(np.abs(glon[inner] - lon[inner])) < 1e-4
    assert np.max(np.abs(h)) < 1e-3                              # on the WGS84 ellipsoid
    uv = mesh.active_texture_coordinates
    np.testing.assert_allclose(uv[:, 0], (lon + 180) / 360, atol=1e-6)
    np.testing.assert_allclose(uv[:, 1], (lat + 90) / 180, atol=1e-6)


def _tangent_frame(lat, lon):
    la, lo = np.radians(lat), np.radians(lon)
    up = np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])
    east = np.array([-np.sin(lo), np.cos(lo), 0.0])
    north = np.cross(up, east)
    return up, east, north


def _render_close_up(lat, lon, *, half_km=330.0, size=240, marker=False):
    """Unlit globe seen straight down at (lat, lon), parallel projection, north up."""
    p = pv.Plotter(off_screen=True, window_size=(size, size))
    p.set_background("black")
    p.add_mesh(globe.make_earth_mesh(), texture=globe.load_texture(), lighting=False)
    center = np.asarray(frames.geodetic_to_ecef(lat, lon, 0.0))
    if marker:
        p.add_mesh(pv.Sphere(radius=12.0, center=center), color="magenta", lighting=False)
    up, _east, north = _tangent_frame(lat, lon)
    p.camera_position = [tuple(center + 3000.0 * up), tuple(center), tuple(north)]
    p.camera.SetParallelProjection(True)
    p.camera.SetParallelScale(half_km)
    p.reset_camera_clipping_range()
    img = p.screenshot(return_img=True)
    p.close()
    return img


def _expected_close_up(tex, lat, lon, *, half_km=330.0, size=240, wrong=None):
    """The texture colours under every pixel of that close-up (or of a wrongly oriented map)."""
    center = np.asarray(frames.geodetic_to_ecef(lat, lon, 0.0))
    _up, east, north = _tangent_frame(lat, lon)
    px = (np.arange(size) + 0.5 - size / 2) * (2 * half_km / size)
    X, Y = np.meshgrid(px, -px)                                    # row 0 at the top (north)
    pts = center + X[..., None] * east + Y[..., None] * north
    plat, plon, _h = frames.ecef_to_geodetic(pts)
    if wrong == "shift180":
        plon = (plon + 360.0) % 360.0 - 180.0
    elif wrong == "mirror":
        plon = -plon
    elif wrong == "flip":
        plat = -plat
    rows, cols = globe.texture_pixel(tex, plat, plon)
    return tex[rows, cols].astype(float)


def _blocks(img, n=8):
    h, w = img.shape[:2]
    return img[: h // n * n, : w // n * n, :3].reshape(n, h // n, n, w // n, 3).mean(axis=(1, 3))


def test_texture_orientation_at_four_cities():
    tex = np.asarray(Image.open(globe.TEXTURE).convert("RGB"))
    report = {}
    for name, (lat, lon) in CITIES.items():
        shot = _render_close_up(lat, lon).astype(float)
        got = _blocks(shot)
        err = {w: float(np.mean(np.abs(got - _blocks(_expected_close_up(tex, lat, lon, wrong=w)))))
               for w in (None, "shift180", "mirror", "flip")}
        report[name] = err
        assert err[None] < 14.0, (name, err)                      # same picture (JPEG/filter noise only)
        assert err[None] * 2.0 < min(err["shift180"], err["mirror"], err["flip"]), (name, err)
        # the marker placed with the same geodetic -> ECEF code sits at the centre of that view
        marked = _render_close_up(lat, lon, marker=True)
        c = marked[120, 120].astype(int)
        assert c[0] > 200 and c[2] > 200 and c[1] < 80, (name, c)  # magenta
    print("texture orientation, mean |rendered - texture| per block (0-255):", report)


# ----------------------------------------------------------------------- what is on screen

def _play_until_late(v):
    ctl = v.ctl
    ctl.key_degrade()                                   # replay-only: plays the recorded late packet
    assert ctl.track.pkt == 0
    for _ in range(30 * 60):
        if ctl.deviated_rows:
            break
        v.update(1 / 30)
    assert ctl.deviated_rows


def test_hud_on_screen_matches_the_trace(data):
    v = globe.GlobeViewer(data, off_screen=True, window_size=(960, 540), engine=None)
    try:
        _play_until_late(v)
        v.render()
        text = v.hud_text()
        assert text["labels"] == hud.label_line(data.labels, data.snapshot_id)
        assert text["renderer"] == v.renderer_text
        assert "LATE: DEV set" in "\n".join(text[f"hop{i}"] for i in range(16))
        assert text["message"].replace("\n", " ").startswith("MISS by")
        assert "replay-only" in text["mode"]
        # the header bytes on screen are the trace's bytes, SL and Flags in their own actors
        ev, _late = hud.header_context(v.ctl.reached())
        shown = (text["hex_pre"].replace("T-CRH", "") + text["hex_sl"] + text["hex_mid"]
                 + text["hex_fl"] + text["hex_post"] + text["hex_more"])
        assert shown.replace(" ", "").replace("|", "").replace("\n", "") == ev.hex
        raw = bytes.fromhex(ev.hex)
        assert text["hex_sl"] == f"{raw[3]:02x}" and text["hex_fl"] == f"{raw[4]:02x}"
        assert text["clock_orbit"].startswith("Orbit clock") and "frozen" in text["clock_orbit"]
        assert text["clock_packet"].startswith("Packet clock")
        # the late satellite is red (outside a flash-off phase)
        v.ctl.flash.clear()
        v.refresh()
        row = data.row_of_node[C]
        k = int(np.flatnonzero(v.sat_rows == row)[0])
        assert tuple(v.sat_mesh.point_data["rgb"][k]) == globe.SAT_DEVIATED
        assert v.dev_actor.GetVisibility()
    finally:
        v.close()


def test_link_state_view_keeps_the_slowed_link_green(data):
    v = globe.GlobeViewer(data, off_screen=True, window_size=(640, 360), engine=None)
    try:
        _play_until_late(v)
        assert v.sel_actor.GetVisibility()                 # normal view: the slowed link is marked
        v.ctl.key_overlay()
        v.refresh()
        assert not v.sel_actor.GetVisibility()             # link-state view: no special marking...
        lines = v.isl_mesh.lines.reshape(-1, 3)[:, 1:]
        rb, rc = data.row_of_node[B], data.row_of_node[C]
        k = next(i for i, (a, b) in enumerate(lines) if {int(a), int(b)} == {rb, rc})
        assert tuple(v.isl_mesh.cell_data["rgb"][k]) == globe.ISL_UP   # ...it is green: UP
        assert "still UP (green)" in v.hud_text()["overlay"].replace("\n", " ")
        img = v.screenshot()
        assert img.std() > 10
    finally:
        v.close()


def test_every_live_fault_of_a_rerun_is_on_the_hud(tmp_path):
    """A live re-run of a re-run has several live faults, all active: the HUD lists every one
    (run.json rerun.live_faults), not only the newest; a recorded run shows none."""
    import json
    from chronoroute.viz import map2d
    run_dir = make_trace(tmp_path / "run")
    doc = json.loads((run_dir / "run.json").read_text())
    doc["rerun"] = {"of": "x", "original": "x", "flow": 0, "kind": "rate",
                    "fault": {"kind": "rate_cut", "link": [B, C], "start_s": "2001/1000", "stop_s": "4"},
                    "live_faults": [{"kind": "down", "fault": {"kind": "link_down", "link": [A, B],
                                                                "start_s": "2", "stop_s": "4"}},
                                    {"kind": "rate", "fault": {"kind": "rate_cut", "link": [B, C],
                                                                "start_s": "2001/1000", "stop_s": "4"}}]}
    (run_dir / "run.json").write_text(json.dumps(doc))
    d = sources.load_viewer_data(trace_dir=run_dir)
    na, nb, nc = (d.trace.nodes[x].name for x in (A, B, C))
    want = (f"2 live faults in this run (all active; d / f add one more): {na} - {nb} failed from t0 + "
            f"2.000 s; {nb} - {nc} degraded (rate cut) from t0 + 2.001 s")
    assert hud.live_faults_text(d.trace) == want
    lines = ["LIVE FAULTS (2, all active; d/f add one)", f"1. {na} - {nb}", "   failed from t0 + 2.000 s",
             f"2. {nb} - {nc}", "   degraded (rate cut) from t0 + 2.001 s"]
    assert hud.live_faults_lines(d.trace) == lines
    v = globe.GlobeViewer(d, off_screen=True, window_size=(960, 540), engine=None)
    try:
        v.render()
        assert v.hud_text()["live"] == "\n".join(lines)
    finally:
        v.close()
    # a long chain: the newest 4 are listed, the older ones counted, never silently dropped
    many = [(i, {"link": [A, B], "start_s": str(i)}) for i in range(6)]
    doc["rerun"]["live_faults"] = [{"kind": "down", "fault": f} for _i, f in many]
    (run_dir / "run.json").write_text(json.dumps(doc))
    six = sources.load_trace(run_dir)
    got = hud.live_faults_lines(six)
    assert got[0].startswith("LIVE FAULTS (6,") and got[1] == "  ... 2 older ones not listed here"
    assert got[2] == f"3. {na} - {nb}" and got[-1] == "   failed from t0 + 5.000 s" and len(got) == 10
    m = map2d.Map2D(d, size_px=(1200, 675), engine=None)
    m._hud()
    assert want in m.t_side.get_text().replace("\n", " ")
    plain = sources.load_viewer_data(trace_dir=make_trace(tmp_path / "plain"))
    assert hud.live_faults_text(plain.trace) is None


@pytest.mark.skipif(not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")),
                    reason="needs a display for an interactive (never shown) window")
def test_keys_are_bound_in_the_interactive_window(data):
    """Key presses go to the right actions. The window is created but never rendered or shown."""
    v = globe.GlobeViewer(data, off_screen=False, window_size=(320, 240), engine=None)
    try:
        iren = v.plotter.iren.interactor

        def press(sym):
            iren.SetKeySym(sym)
            iren.InvokeEvent("KeyPressEvent")

        ctl = v.ctl
        press("space")
        assert ctl.track is not None and ctl.track.pkt == 0
        press("space")
        assert ctl.track.pkt == 1
        press("d")
        assert ctl.track.pkt == 0 and "replay-only" in ctl.message
        ctl.message = None
        press("f")                                       # fail the link: replay-only here too
        assert ctl.track.pkt == 0 and "replay-only" in ctl.message
        press("l")
        assert ctl.overlay and not v.sel_actor.GetVisibility()
        press("l")
        assert not ctl.overlay
        slow = ctl.player.slowmo
        press("plus")
        assert ctl.player.slowmo == slow / 2                 # pyvista's own point-size binding removed
        press("minus")
        assert ctl.player.slowmo == slow
        assert ctl.selected_hop == 3                          # B - C, the recorded slowed link
        press("bracketleft")
        assert ctl.selected_hop == 2 and ctl.selected_link == (A, B)
        press("bracketright")
        assert ctl.selected_hop == 3
        press("m")
        assert ctl.track.is_late
        press("r")
        assert ctl.player.state == pl.FLIGHT and ctl.player.walk.sim_t == ctl.track.t_start
    finally:
        v.close()


def test_snapshot_view_and_benchmark_helper():
    from chronoroute.viz import command
    data = sources.load_viewer_data(snapshot_dir=sources.PINNED_DIR / "20261010T1358Z-celestrak",
                                    shell="53.2deg-463km")
    v = globe.GlobeViewer(data, off_screen=True, window_size=(640, 360))
    try:
        stats = command.bench_globe(v, 3, warmup=1)
        assert stats["satellites"] == 2847 and stats["laser_links_drawn_last_frame"] > 4000
        assert stats["lite"] is False and stats["render_ms_median"] > 0
        assert v.ctl.player.state == pl.IDLE
        assert v.hud_text()["title"].startswith("ChronoRoute viewer | snapshot 20261010T1358Z-celestrak")
    finally:
        v.close()

"""
globe.py
--------
`cr viz globe`: the PyVista (VTK) 3D viewer. A WSLg window (or an off-screen
render) in which the REAL satellites move over a textured Earth, the MODELLED
Grid-4 laser links are drawn, and one packet hops along its T-CRH path in slow
motion; at the hop where a deadline is missed the satellite flashes red and the
HUD says by how much.

What happens is decided by player.Controller (no graphics, tested on its own);
this module only draws its state.

Frame: everything is drawn in ECEF kilometres (Earth-fixed), so the Earth mesh
and the cities never move and the satellites are exactly where SGP4 (or the
bundle's samples of it) put them. The Earth is the WGS84 ellipsoid, and the
texture is sampled at the GEODETIC latitude of each vertex, the latitude city
coordinates use, so a city marker sits on its own spot of the map
(sim/tests/test_viz_globe.py renders markers at Greenwich, Chennai, New York and
Sydney to check the texture orientation).

One VTK object per kind of thing, updated in place every frame:
  satellites   one point cloud, coloured per point by state:
               normal / on the packet's path / deviated (late detected) /
               fallback / picked
  laser links  one line set (MODELLED). Normal view: only links that are up.
               Link-state view (key l): all links, green = up, red = down, as a
               link-state protocol would see them; an up-but-slow link is green.
  path         one thick polyline: travelled part yellow, after a fallback
               magenta, not yet travelled dim
  packet       a sphere that waits at a node / flies between nodes (player.py)
  HUD          text actors (hud.py builds every string)

Keys (docs/viewer.md): space next packet, m next deadline miss, d degrade the
selected link (rate cut), f fail it (link down) - live re-runs of the engine when
the trace is a python-sim run, else replay-only -, [ ] move the selection along
the path, l link-state view, +/- speed, r replay; right-click picks a satellite.
"""

import textwrap
import time
from pathlib import Path

import numpy as np

from ..orbit import frames
from . import hud
from .player import Controller
from .sources import LITE_THRESHOLD

ASSET_DIR = Path(__file__).resolve().parent / "assets"
TEXTURE = ASSET_DIR / "earth-day-2048.jpg"

# Colours (RGB 0-255), readable on the dark background.
SAT_NORMAL = (200, 210, 220)
SAT_PATH = (255, 210, 60)
SAT_DEVIATED = (255, 40, 40)
SAT_FALLBACK = (255, 60, 255)
SAT_PICKED = (56, 232, 255)
STATE_RGB = np.array([SAT_NORMAL, SAT_PATH, SAT_DEVIATED, SAT_FALLBACK, SAT_PICKED], dtype=np.uint8)
ISL_NORMAL = (90, 160, 255)
ISL_UP = (48, 208, 80)
ISL_DOWN = (200, 40, 40)
PATH_RGB = {"done": (255, 210, 60), "fallback": (255, 60, 255), "todo": (120, 105, 60)}
LINK_SELECTED = (255, 140, 0)
BACKGROUND = (6, 8, 16)
EARTH_A_KM = frames.WGS84_A_KM


def _rgb(c):
    return np.asarray(c, dtype=np.uint8)


def _f(c):
    return [x / 255 for x in c]


def use_freetype_text():
    """Draw all text with FreeType.

    VTK's default text backend 'Detect' sent every string through matplotlib's
    MathText here, which ignores the font file and drops '|' (measured: "a|b"
    rendered as "ab"). The HUD has no math, so plain FreeType is the right backend.
    """
    try:
        from vtkmodules.vtkRenderingCore import vtkTextRenderer
        import vtkmodules.vtkRenderingFreeType  # noqa: F401  (registers the FreeType renderer)
        tr = vtkTextRenderer.GetInstance()
        if tr is not None:
            tr.SetDefaultBackend(vtkTextRenderer.FreeType)
    except Exception:
        pass


def hud_fonts():
    """(monospace, sans) TrueType files for the HUD (DejaVu, shipped inside matplotlib), or (None, None)."""
    try:
        import matplotlib
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        mono, sans = base / "DejaVuSansMono.ttf", base / "DejaVuSans.ttf"
        if mono.is_file() and sans.is_file():
            return str(mono), str(sans)
    except Exception:
        pass
    return None, None


# ----------------------------------------------------------------------- Earth

def lonlat_to_uv(lat_deg, lon_deg):
    """Texture coordinates of the equirectangular Blue Marble map (assets/CREDITS.md)."""
    return (np.asarray(lon_deg) + 180.0) / 360.0, (np.asarray(lat_deg) + 90.0) / 180.0


def texture_pixel(image, lat_deg, lon_deg):
    """The texture pixel (row, col) under a latitude/longitude: row 0 is +90, col 0 is -180."""
    h, w = image.shape[:2]
    u, v = lonlat_to_uv(lat_deg, lon_deg)
    col = np.clip(np.floor(u * w).astype(int), 0, w - 1)
    row = np.clip(np.floor((1.0 - v) * h).astype(int), 0, h - 1)
    return row, col


def make_earth_mesh(nlat=181, nlon=361):
    """WGS84 ellipsoid as a lat/lon grid of quads with texture coordinates.

    Point (i_lon, j_lat) has index j * nlon + i. The seam (lon -180 and +180) has
    two columns of points so the texture does not wrap backwards across it. Point
    data 'lat' / 'lon' are each vertex's own geodetic coordinates (the tests check
    them against the geometry and the texture coordinates).
    """
    import pyvista as pv
    lat = np.linspace(-90.0, 90.0, nlat)
    lon = np.linspace(-180.0, 180.0, nlon)
    LAT, LON = np.meshgrid(lat, lon, indexing="ij")             # (nlat, nlon)
    pts = frames.geodetic_to_ecef(LAT, LON, 0.0).reshape(-1, 3)
    i = np.arange(nlon - 1)
    j = np.arange(nlat - 1)
    J, I = np.meshgrid(j, i, indexing="ij")
    p00 = (J * nlon + I).ravel()
    faces = np.column_stack([np.full(p00.size, 4), p00, p00 + 1, p00 + 1 + nlon, p00 + nlon]).ravel()
    mesh = pv.PolyData(pts, faces=faces)
    u, v = lonlat_to_uv(LAT.ravel(), LON.ravel())
    mesh.point_data["lat"] = LAT.ravel()
    mesh.point_data["lon"] = LON.ravel()
    mesh.active_texture_coordinates = np.column_stack([u, v]).astype(np.float32)
    return mesh


def load_texture():
    import pyvista as pv
    return pv.read_texture(str(TEXTURE))


def lines_array(pairs):
    """VTK 'lines' connectivity for (a, b) row pairs."""
    pairs = np.asarray(pairs, dtype=np.int64).reshape(-1, 2)
    out = np.empty((len(pairs), 3), dtype=np.int64)
    out[:, 0] = 2
    out[:, 1:] = pairs
    return out.ravel()


# ----------------------------------------------------------------------- viewer

class GlobeViewer:
    """The 3D scene; Controller decides, this draws (module docstring)."""

    def __init__(self, data, *, follow=None, off_screen=False, window_size=(1440, 810),
                 orbit_speed=60.0, slowmo=100.0, lite="auto", lighting=True, autoplay=False,
                 earth_resolution=(181, 361), engine="auto"):
        import pyvista as pv
        self.pv = pv
        self.off_screen = off_screen
        self.window_size = tuple(int(x) for x in window_size)
        self.lighting = lighting
        self.ctl = Controller(data, follow=follow, orbit_speed=orbit_speed, slowmo=slowmo,
                              autoplay=autoplay, lite=lite, engine=engine,
                              say=None if off_screen else print)
        self.sat_rows = self.ctl.sat_rows
        self.n_sats = self.ctl.n_sats
        self.renderer_text = None
        self.frame_count = 0
        self._restore_camera = None
        self._last_wall = None
        self._build(earth_resolution)
        self.refresh()

    # ------------------------------------------------------------------ scene

    def _build(self, earth_resolution):
        pv = self.pv
        p = pv.Plotter(off_screen=self.off_screen, window_size=list(self.window_size))
        p.set_background(_f(BACKGROUND))
        self.plotter = p
        self.earth = make_earth_mesh(*earth_resolution)
        self.texture = load_texture()
        if self.lighting:
            self.earth_actor = p.add_mesh(self.earth, texture=self.texture, smooth_shading=True,
                                          ambient=0.35, diffuse=0.75, specular=0.0, pickable=False,
                                          name="earth")
        else:   # flat: the rendered colour is exactly the texture (used by the orientation test)
            self.earth_actor = p.add_mesh(self.earth, texture=self.texture, lighting=False,
                                          pickable=False, name="earth")
        n = len(self.data.node_ids)
        ns = max(self.n_sats, 1)
        self.sat_mesh = pv.PolyData(np.zeros((ns, 3)))
        self.sat_mesh.point_data["rgb"] = np.tile(_rgb(SAT_NORMAL), (ns, 1))
        self.sat_actor = p.add_mesh(self.sat_mesh, scalars="rgb", rgb=True,
                                    point_size=5 if self.n_sats > LITE_THRESHOLD else 7,
                                    render_points_as_spheres=True, pickable=True, name="sats",
                                    show_scalar_bar=False)
        self.isl_mesh = pv.PolyData(np.zeros((n, 3)))
        self.isl_actor = p.add_mesh(self.isl_mesh, color=_f(ISL_NORMAL), line_width=1, opacity=0.3,
                                    pickable=False, name="isl")
        self.sel_mesh = pv.PolyData(np.zeros((2, 3)))
        self.sel_actor = p.add_mesh(self.sel_mesh, color=_f(LINK_SELECTED), line_width=12,
                                    render_lines_as_tubes=True, pickable=False, name="selected-link")
        self.sel_actor.SetVisibility(False)
        self.path_mesh = pv.PolyData(np.zeros((n, 3)))
        self.path_actor = p.add_mesh(self.path_mesh, line_width=6, render_lines_as_tubes=True,
                                     pickable=False, name="path", color="yellow")
        self.path_actor.SetVisibility(False)
        self.hl_mesh = pv.PolyData(np.zeros((1, 3)))
        self.hl_mesh.point_data["rgb"] = np.tile(_rgb(SAT_PATH), (1, 1))
        self.hl_actor = p.add_mesh(self.hl_mesh, scalars="rgb", rgb=True, point_size=14,
                                   render_points_as_spheres=True, pickable=False, name="path-nodes",
                                   show_scalar_bar=False)
        self.hl_actor.SetVisibility(False)
        self.dev_actor = p.add_mesh(pv.Sphere(radius=230.0, theta_resolution=24, phi_resolution=24),
                                    color=_f(SAT_DEVIATED), opacity=0.45, ambient=1.0, diffuse=0.0,
                                    pickable=False, name="deviated-halo")
        self.dev_actor.SetVisibility(False)
        self.packet_actor = p.add_mesh(pv.Sphere(radius=140.0, theta_resolution=24, phi_resolution=24),
                                       color="white", ambient=1.0, diffuse=0.0, pickable=False,
                                       name="packet-sphere")
        self.packet_actor.SetVisibility(False)
        if self.data.cities:
            cpts = np.array([frames.geodetic_to_ecef(lat, lon, 0.0) for _n, lat, lon in self.data.cities])
            s = self.window_size[1] / 810
            p.add_point_labels(pv.PolyData(cpts * 1.002), [c[0] for c in self.data.cities],
                               font_size=int(12 * s), point_size=10, point_color="orange",
                               text_color="white", shape_opacity=0.35, render_points_as_spheres=True,
                               name="cities", always_visible=False, pickable=False)
        self._build_hud()
        self._set_camera()
        if not self.off_screen:
            p.enable_point_picking(callback=self._on_pick, left_clicking=False, show_message=False,
                                   show_point=False, tolerance=0.02, pickable_window=False)
            self._bind_keys()

    def _set_camera(self):
        """Look at the followed flow's two cities (or the first city, or India)."""
        target = None
        pk = self.ctl.picker
        if pk is not None and pk.tracks:
            tr = pk.tracks[0]
            ends = [tr.events[0].node] + ([tr.outcome.node] if tr.outcome is not None else [])
            pts = [frames.geodetic_to_ecef(self.trace.nodes[x].lat, self.trace.nodes[x].lon, 0.0)
                   for x in ends if self.trace.nodes[x].kind == "gs"]
            if pts:
                target = np.mean(pts, axis=0)
        if target is None and self.data.cities:
            _n, lat, lon = self.data.cities[0]
            target = frames.geodetic_to_ecef(lat, lon, 0.0)
        if target is None:
            target = frames.geodetic_to_ecef(20.0, 78.0, 0.0)
        self.look_at_direction(target, distance_radii=3.4, shift=-0.22)

    def look_at_direction(self, target_km, *, distance_radii=3.4, shift=0.0):
        """Camera on the line from the Earth's centre through target_km, north up."""
        d = np.asarray(target_km, dtype=float)
        d = d / np.linalg.norm(d)
        up = np.array([0.0, 0.0, 1.0])
        if abs(d @ up) > 0.95:
            up = np.array([0.0, 1.0, 0.0])
        cam = self.plotter.camera
        self.plotter.camera_position = [tuple(d * EARTH_A_KM * distance_radii), (0.0, 0.0, 0.0), tuple(up)]
        cam.view_angle = 30.0
        cam.SetWindowCenter(shift, 0.0)    # shift the globe right so the hop table covers less of it

    # ------------------------------------------------------------------ HUD actors

    def _build_hud(self):
        p = self.plotter
        W, H = self.window_size
        s = H / 810
        self.s = s
        fs = max(int(round(7.5 * s)), 6)       # pyvista doubles it: about 2 * fs px glyphs
        self.font_px = fs
        self._txt = {}
        self._txt_state = {}
        mono, sans = hud_fonts()
        use_freetype_text()

        def add(name, x, y, size=fs, color="white", font="mono"):
            kw = {"font_file": mono if font == "mono" else sans} if (mono and sans) else \
                {"font": "courier" if font == "mono" else "arial"}
            # pyvista replaces an actor of the same name, so HUD names get their own prefix.
            actor = p.add_text("", position=(int(x), int(y)), font_size=size, color=color,
                               name="hud-" + name, **kw)
            actor.prop.background_color = "black"          # keeps text readable over the globe
            actor.prop.background_opacity = 0.55
            self._txt[name] = actor
            return actor

        lh = int(round(2.35 * fs))             # line height in pixels
        self.lh = lh
        top = H - int(2.7 * fs)
        x0 = int(10 * s)
        add("title", x0, top, int(fs * 1.15), "white", "sans")
        add("clock_orbit", x0, top - 1.3 * lh)
        add("clock_packet", x0, top - 2.3 * lh)
        add("packet_title", x0, top - 3.5 * lh, color="#ffd23c")
        self.hop_row_y0 = top - 4.6 * lh
        for i in range(16):
            add(f"hop{i}", x0, self.hop_row_y0 - i * lh)
        # (a multi-line text grows UP from its position, so these are placed bottom-up)
        y = self.hop_row_y0 - 16.6 * lh
        add("message", x0, y - 1.0 * lh, int(fs * 1.1), "#ff4040", "sans")    # up to 3 lines
        add("link", x0, y - 2.3 * lh, fs, "#ff8c00", "sans")
        add("fault", x0, y - 4.4 * lh, int(fs * 0.9), "#ff8c00", "sans")      # up to 2 lines
        add("overlay", x0, y - 7.5 * lh, int(fs * 0.9), "#30d050", "sans")    # up to 3 lines
        add("mode", x0, y - 8.6 * lh, int(fs * 0.9), "#b0b0b0", "sans")
        base = int(2.4 * lh)
        self.hex_y = base + 3 * lh
        self.hex_x0 = x0
        for name in ("hex_pre", "hex_sl", "hex_mid", "hex_fl", "hex_post"):
            add(name, x0, self.hex_y, color={"hex_sl": "#ffd23c", "hex_fl": "#38e8ff"}.get(name, "white"))
        add("hex_more", x0, base + lh)
        add("hex_decoded", x0, base, color="#ffd23c")
        add("labels", x0, int(1.2 * lh), fs, "#9fe0a0", "sans")
        add("renderer", x0, int(0.25 * lh), fs, "#d0d0d0", "sans")
        self.right_x = int(W - 40 * fs * 1.2)
        add("keys", self.right_x, top - 2.2 * lh, int(fs * 0.9), "#b0b0b0", "sans")     # 3 lines
        add("notes", self.right_x, top - 7.0 * lh, int(fs * 0.85), "#b0b0b0", "sans")   # up to 4
        # live faults of a re-run: up to 10 lines (hud.live_faults_lines), between the notes and
        # the pick panel
        add("live", self.right_x, top - 18.0 * lh, int(fs * 0.9), "#ff8c00", "sans")
        add("pick", self.right_x, int(5.2 * lh), int(fs * 0.9), "#38e8ff", "mono")
        self._char_px = self._measure_char()
        self.left_chars = int((W * 0.5) / (self._char_px or 1.2 * fs))

    def _measure_char(self):
        """Pixel advance of one monospace character at the HUD size (to colour parts of a line)."""
        try:
            from vtkmodules.vtkRenderingCore import vtkTextRenderer
            import vtkmodules.vtkRenderingFreeType  # noqa: F401
            tr = vtkTextRenderer.GetInstance()
            bb = [0, 0, 0, 0]
            prop = self._txt["hex_pre"].prop
            dpi = self.plotter.ren_win.GetDPI()
            tr.GetBoundingBox(prop, "0" * 40, bb, dpi)
            w40 = bb[1] - bb[0]
            tr.GetBoundingBox(prop, "0" * 20, bb, dpi)
            return (w40 - (bb[1] - bb[0])) / 20.0    # per-character advance, side bearings cancel
        except Exception:                            # unavailable: brackets mark SL / Flags instead
            return None

    def _set(self, name, text, color=None):
        # Only touch an actor whose text or colour really changed: setting it marks the
        # actor modified and VTK then rasterises its text again (measured: re-setting all
        # ~40 HUD texts every frame doubled the render time).
        text = text or ""
        key = (text, color)
        if self._txt_state.get(name) == key:
            return
        self._txt_state[name] = key
        actor = self._txt[name]
        if actor.input != text:
            actor.input = text
        if color is not None:
            actor.prop.color = color

    def _place(self, name, x, y):
        pos = (int(x), int(y))
        if self._txt_state.get(("pos", name)) != pos:
            self._txt_state[("pos", name)] = pos
            self._txt[name].position = pos

    @staticmethod
    def _wrap(text, width, lines=2):
        if not text:
            return ""
        return "\n".join(textwrap.wrap(text, max(int(width), 10))[:lines])

    # ------------------------------------------------------------------ keys

    def _bind_keys(self):
        p = self.plotter
        for key in ("plus", "minus"):           # pyvista binds these to point size by default
            p.clear_events_for_key(key)
        ctl = self.ctl
        bindings = {"space": ctl.key_next, "m": ctl.key_next_miss, "d": ctl.key_degrade,
                    "f": self._key_fail,
                    "l": ctl.key_overlay, "plus": ctl.key_faster, "equal": ctl.key_faster,
                    "KP_Add": ctl.key_faster, "minus": ctl.key_slower, "KP_Subtract": ctl.key_slower,
                    "r": self._key_replay, "bracketleft": lambda: ctl.key_move_link(-1),
                    "bracketright": lambda: ctl.key_move_link(+1)}
        for key, fn in bindings.items():
            p.add_key_event(key, self._after(fn))

    def _after(self, fn):
        def run():
            fn()
            self.refresh()
        return run

    def _key_replay(self):
        self._restore_camera = self.plotter.camera_position     # VTK's own 'r' resets the camera
        self.ctl.key_replay()

    def _key_fail(self):
        self._restore_camera = self.plotter.camera_position     # VTK's own 'f' flies the camera
        self.ctl.key_fail()

    # The controller may switch to another run of the same scenario (live mode), so the
    # trace and data on screen are always the controller's.
    @property
    def data(self):
        return self.ctl.data

    @property
    def trace(self):
        return self.ctl.trace

    def _on_pick(self, point, *args):
        self.ctl.pick_nearest(point)
        self.refresh()

    # ------------------------------------------------------------------ per frame

    def update(self, dt_wall_s):
        """One frame: advance the controller by dt_wall_s and redraw its state."""
        if self._restore_camera is not None:
            self.plotter.camera_position = self._restore_camera
            self._restore_camera = None
        self.ctl.update(dt_wall_s)
        self.refresh()
        self.frame_count += 1

    def refresh(self):
        pv = self.pv
        ctl = self.ctl
        pos = ctl.pos
        track = ctl.track
        reached = ctl.reached()
        states = ctl.node_states()
        colors = STATE_RGB[states]
        if self.n_sats:
            self.sat_mesh.points = pos[self.sat_rows]
            self.sat_mesh.point_data["rgb"] = colors[self.sat_rows]

        hl_rows = [r for r in dict.fromkeys(ctl.path_rows()) if self.data.kinds[r] == "sat"]
        if hl_rows:
            m = pv.PolyData(pos[hl_rows])
            m.point_data["rgb"] = colors[hl_rows]
            self.hl_mesh.copy_from(m)
        self.hl_actor.SetVisibility(bool(hl_rows))
        if track is not None and ctl.deviated_rows:
            r = next(iter(ctl.deviated_rows))
            self.dev_actor.SetPosition(*pos[r])
            self.dev_actor.SetVisibility(ctl.flash_on(r))
        else:
            self.dev_actor.SetVisibility(False)

        isl = self.data.isl
        idx = ctl.visible_links()
        if len(idx):
            mesh = pv.PolyData(pos, lines=lines_array(np.column_stack([isl.a[idx], isl.b[idx]])))
            if ctl.overlay:
                c = np.where(ctl.isl_up[idx][:, None], _rgb(ISL_UP)[None, :], _rgb(ISL_DOWN)[None, :])
                mesh.cell_data["rgb"] = c.astype(np.uint8)
            self.isl_mesh.copy_from(mesh)
            mapper = self.isl_actor.mapper
            if ctl.overlay:
                mapper.scalar_visibility = True
                mapper.SetScalarModeToUseCellFieldData()
                mapper.SelectColorArray("rgb")
                mapper.SetColorModeToDirectScalars()
                self.isl_actor.prop.opacity = 0.9
            else:
                mapper.scalar_visibility = False
                self.isl_actor.prop.opacity = 0.3
        self.isl_actor.SetVisibility(bool(len(idx)))

        if ctl.selected_link is not None and self.trace is not None:
            a, b = (ctl.row_of[x] for x in ctl.selected_link)
            self.sel_mesh.copy_from(pv.PolyData(pos[[a, b]], lines=np.array([2, 0, 1])))
            # In the link-state view the slowed link must look like any other up link.
            self.sel_actor.SetVisibility(not ctl.overlay)
        else:
            self.sel_actor.SetVisibility(False)

        segs = ctl.path_segments()
        if segs:
            m = pv.PolyData(pos, lines=lines_array([(a, b) for a, b, _k in segs]))
            m.cell_data["rgb"] = np.array([PATH_RGB[k] for _a, _b, k in segs], dtype=np.uint8)
            self.path_mesh.copy_from(m)
            mapper = self.path_actor.mapper
            mapper.scalar_visibility = True
            mapper.SetScalarModeToUseCellFieldData()
            mapper.SelectColorArray("rgb")
            mapper.SetColorModeToDirectScalars()
        self.path_actor.SetVisibility(bool(segs))
        ppos = ctl.packet_position()
        if ppos is not None:
            self.packet_actor.SetPosition(*ppos)
        self.packet_actor.SetVisibility(ppos is not None)
        self._refresh_hud(track, reached)

    def _refresh_hud(self, track, reached):
        d, ctl = self.data, self.ctl
        if d.mode == "trace":
            title = (f"ChronoRoute viewer | trace {Path(self.trace.run_dir).name} ({self.trace.tool}) | "
                     f"{self.n_sats} satellites")
        else:
            title = (f"ChronoRoute viewer | snapshot {d.snapshot_id} | {self.n_sats} satellites"
                     + (f" ({d.shell_id})" if d.shell_id else " (whole fleet)"))
        if ctl.lite:
            title += f" | LITE: links only near the path (> {LITE_THRESHOLD} satellites)"
        self._set("title", title)
        c1, c2 = hud.clock_lines(ctl.player, d.t0_unix_ns if self.trace is not None else None)
        self._set("clock_orbit", c1)
        self._set("clock_packet", c2)
        self._set("packet_title", hud.packet_title(self.trace, track) if track is not None else "")
        rows = hud.hop_rows(self.trace, track, reached) if track is not None else []
        colours = {"header": "#b0b0b0", "send": "white", "ok": "white", "late": "#ff4040",
                   "fallback": "#ff60ff", "pending": "#808080"}
        for i in range(16):
            text, status = rows[i] if i < len(rows) else ("", "ok")
            self._set(f"hop{i}", text, colours.get(status, "white"))
        self._set_header(*(hud.header_context(reached) if track is not None else (None, None)))

        label = hud.label_line(d.labels, d.snapshot_id, hud.positions_note(d.positions))
        if d.positions.failed:
            label += f" | SGP4 failed for {d.positions.failed} satellites (hidden)"
        self._set("labels", label)
        self._set("renderer", self.renderer_text or "renderer: (not yet rendered)")
        self._set("keys", self._wrap(hud.KEYS_LINE, 46, 3))
        self._set("mode", hud.mode_line(ctl.live_available, ctl.live_reason) if self.trace is not None
                  else "snapshot view (no packets)")
        # every fault live mode has added to the run on screen (they accumulate: a key re-runs the
        # run shown), not only the newest one the last message named
        self._set("live", "\n".join(hud.live_faults_lines(self.trace)))
        colour = {"miss": "#ff4040", "warn": "#ffb000", "info": "#e0e0e0"}[ctl.message_level]
        self._set("message", self._wrap(ctl.message or "", self.left_chars * 0.95, 3), colour)
        if self.trace is not None:
            self._set("link", hud.link_line(self.trace, ctl.selected_link, ctl.selected_hop))
            fault = ctl.selected_fault()
            self._set("fault", self._wrap(hud.fault_text(self.trace, fault), self.left_chars * 1.1)
                      if fault else ("no recorded fault on this link" if ctl.selected_link else ""))
            slowed_up = fault is not None and bool(ctl.link_up(fault.link))
            self._set("overlay", self._wrap(hud.overlay_line(ctl.overlay, slowed_up) or "",
                                            self.left_chars * 1.1, 3))
        else:
            self._set("overlay", self._wrap(hud.overlay_line(ctl.overlay) or "", self.left_chars * 1.1))
        notes = list(d.notes[:2]) + ([f"ISLs: {d.isl.source}"] if len(d.isl) else [])
        self._set("notes", "\n".join(self._wrap(n, 48, 2) for n in notes))
        self._set("pick", "\n".join(self._wrap(x, 46, 2) for x in self.pick_lines())
                  if ctl.picked_row is not None else "")

    def _set_header(self, ev, late=None):
        names = ("hex_pre", "hex_sl", "hex_mid", "hex_fl", "hex_post")
        lines = hud.header_lines(ev, late)
        if ev is None or not ev.hex:
            for name in names:
                self._set(name, "")
            self._place("hex_pre", self.hex_x0, self.hex_y)
            self._set("hex_pre", lines[0])
            self._set("hex_more", "")
            self._set("hex_decoded", "")
            return
        parts, more = hud.header_hex_parts(ev.hex)
        if self._char_px:
            col = 0
            texts = ["T-CRH  " + parts[0][0], parts[1][0], parts[2][0], parts[3][0], parts[4][0]]
            for name, text in zip(names, texts):
                # VTK places text by its ink, so leading blanks would be lost: skip them and
                # move the actor right by that many columns instead.
                lead = len(text) - len(text.lstrip(" "))
                self._set(name, text.lstrip(" "))
                self._place(name, self.hex_x0 + (col + lead) * self._char_px, self.hex_y)
                col += len(text)
            flags = int(parts[3][0], 16)
            self._set("hex_fl", parts[3][0], "#ff4040" if flags & 1 else "#38e8ff")
        else:
            for name in names[1:]:
                self._set(name, "")
            self._set("hex_pre", lines[0])
        self._set("hex_more", "\n".join(f"       {m}" for m in more[:2]))
        self._set("hex_decoded", lines[-1])

    def pick_lines(self):
        r = self.ctl.picked_row
        d = self.data
        norad = d.norads[r]
        el = d.snapshot.elements(norad) if (d.snapshot is not None and norad) else None
        lat, lon, h = frames.ecef_to_geodetic(self.ctl.pos[r])
        return hud.pick_lines(d.names[r], norad, d.sids[r], el, self.ctl.player.orbit_utc_ns,
                              float(lat), float(lon), float(h))

    def hud_text(self):
        """Every HUD string now, keyed by actor name (tests read what is on screen)."""
        return {name: actor.input for name, actor in self._txt.items()}

    # ------------------------------------------------------------------ running

    def detect_renderer(self):
        """Ask VTK which OpenGL renderer draws this window (needs one real render first)."""
        try:
            self.plotter.ren_win.Render()
            self.renderer_text = hud.renderer_line(self.plotter.ren_win.ReportCapabilities())
        except Exception as exc:
            self.renderer_text = f"renderer: unknown ({type(exc).__name__})"
        self._set("renderer", self.renderer_text)
        return self.renderer_text

    def render(self):
        """Draw the current state now.

        Calls the VTK window's Render() directly: pyvista's Plotter.render() does nothing
        until show() has run, and its screenshot() then returns the PREVIOUS frame
        (measured: 0 changed pixels between frames of a moving scene), so an off-screen
        recording made that way would be a still picture.
        """
        if self.renderer_text is None:
            self.detect_renderer()
        # near/far planes from what is visible NOW (the satellites move; the first range was
        # computed before they had positions)
        self.plotter.renderer.ResetCameraClippingRange()
        self.plotter.ren_win.Render()

    def grab_frame(self):
        """Render, then read the pixels back: (H, W, 3) uint8 of exactly this frame."""
        self.render()
        return self.plotter.screenshot(return_img=True)

    def screenshot(self, path=None):
        img = self.grab_frame()
        if path:
            from PIL import Image
            Image.fromarray(img).save(str(path))
        return img

    def run_timeline(self, seconds, fps=30):
        """Deterministic: advance `seconds` of screen time in 1/fps steps (record, screenshots, tests)."""
        for _ in range(int(round(seconds * fps))):
            self.update(1.0 / fps)

    def show(self, fps=30):
        """Open the interactive window (WSLg) and animate from a timer callback."""
        ctl = self.ctl
        if ctl.picker is not None and ctl.player.walk is None:
            ctl.play(ctl.picker.next())
        self._last_wall = time.perf_counter()

        def tick(_step=None):
            now = time.perf_counter()
            dt = min(now - self._last_wall, 0.2)
            self._last_wall = now
            self.update(dt)
            if self.renderer_text is None:
                self.detect_renderer()
            # pyvista renders the window right after this callback (Timer.execute)
            self.plotter.renderer.ResetCameraClippingRange()

        self.plotter.add_timer_event(max_steps=2 ** 31 - 1, duration=int(1000 / fps), callback=tick)
        self.plotter.show(title="ChronoRoute viewer")

    def close(self):
        self.plotter.close()


__all__ = ["GlobeViewer", "make_earth_mesh", "load_texture", "lonlat_to_uv", "texture_pixel",
           "TEXTURE", "use_freetype_text", "hud_fonts", "lines_array"]

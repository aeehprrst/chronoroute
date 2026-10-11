"""
map2d.py
--------
`cr viz map2d`: the matplotlib 2D fallback of the globe, for machines where VTK
cannot open a window (no GPU, no WSLg) and for still figures.

Same data, same Controller (player.py), same HUD strings (hud.py) as the 3D
globe; only the drawing differs:
  * the Blue Marble texture as an equirectangular background
    (imshow extent [-180, 180] x [-90, 90], row 0 = +90, as assets/CREDITS.md says);
  * satellites and cities at their geodetic longitude / latitude (sub-points);
  * laser links (MODELLED), the packet's path and the packet itself as straight
    segments between sub-points. A segment whose two ends are more than 180 deg of
    longitude apart crosses the antimeridian: it is SPLIT there into two pieces
    ending at -180 and +180 (latitude interpolated along the unwrapped segment), so
    no line is drawn the long way round the map (split_segment, tested).

A flat map distorts long links and cannot show altitude; the 3D globe is the
primary view and this one says "2D fallback" in its title.
"""

import textwrap
import time
from pathlib import Path

import numpy as np

from ..orbit import frames
from . import hud
from .globe import PATH_RGB, STATE_RGB, TEXTURE, ISL_DOWN, ISL_NORMAL, ISL_UP, LINK_SELECTED
from .player import Controller


# ----------------------------------------------------------------------- antimeridian

def split_segment(lon1, lat1, lon2, lat2):
    """One segment -> list of 1 or 2 segments [((lon_a, lat_a), (lon_b, lat_b))] that never
    jump across the map. Longitudes in [-180, 180]."""
    d = lon2 - lon1
    if abs(d) <= 180.0:
        return [((lon1, lat1), (lon2, lat2))]
    # Crossing the antimeridian: unwrap the second end next to the first.
    lon2u = lon2 - 360.0 if d > 0 else lon2 + 360.0
    edge = -180.0 if d > 0 else 180.0          # where the first piece leaves the map
    t = (edge - lon1) / (lon2u - lon1)
    lat_c = lat1 + t * (lat2 - lat1)
    return [((lon1, lat1), (edge, lat_c)), ((-edge, lat_c), (lon2, lat2))]


def split_polyline(lons, lats):
    """A polyline -> list of (lons, lats) pieces, split at +-180 deg (see split_segment)."""
    pieces, cur_lon, cur_lat = [], [lons[0]], [lats[0]]
    for i in range(1, len(lons)):
        segs = split_segment(lons[i - 1], lats[i - 1], lons[i], lats[i])
        if len(segs) == 1:
            cur_lon.append(lons[i])
            cur_lat.append(lats[i])
        else:
            (a, b), (c, e) = segs
            cur_lon.append(b[0])
            cur_lat.append(b[1])
            pieces.append((cur_lon, cur_lat))
            cur_lon, cur_lat = [c[0], e[0]], [c[1], e[1]]
    pieces.append((cur_lon, cur_lat))
    return pieces


def split_segments(lon_a, lat_a, lon_b, lat_b):
    """Vectorised split_segment for many segments -> (K, 2, 2) array of [lon, lat] pairs."""
    lon_a, lat_a, lon_b, lat_b = (np.asarray(x, dtype=float) for x in (lon_a, lat_a, lon_b, lat_b))
    d = lon_b - lon_a
    cross = np.abs(d) > 180.0
    out = [np.stack([np.column_stack([lon_a[~cross], lat_a[~cross]]),
                     np.column_stack([lon_b[~cross], lat_b[~cross]])], axis=1)]
    if cross.any():
        la, pa, lb, pb, dd = lon_a[cross], lat_a[cross], lon_b[cross], lat_b[cross], d[cross]
        lbu = np.where(dd > 0, lb - 360.0, lb + 360.0)
        edge = np.where(dd > 0, -180.0, 180.0)
        t = (edge - la) / (lbu - la)
        pc = pa + t * (pb - pa)
        out.append(np.stack([np.column_stack([la, pa]), np.column_stack([edge, pc])], axis=1))
        out.append(np.stack([np.column_stack([-edge, pc]), np.column_stack([lb, pb])], axis=1))
    return np.concatenate(out, axis=0)


def lonlat(pos_km):
    lat, lon, _h = frames.ecef_to_geodetic(pos_km)
    return np.asarray(lon), np.asarray(lat)


# ----------------------------------------------------------------------- the map

class Map2D:
    """The 2D view: Controller decides (player.py), matplotlib draws."""

    def __init__(self, data, *, follow=None, size_px=(1440, 810), dpi=100, interactive=False,
                 orbit_speed=60.0, slowmo=100.0, autoplay=False, lite="auto", engine="auto"):
        import matplotlib
        if not interactive:
            matplotlib.use("Agg", force=True)
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
        self.plt = plt
        self.ctl = Controller(data, follow=follow, orbit_speed=orbit_speed, slowmo=slowmo,
                              autoplay=autoplay, lite=lite, engine=engine,
                              say=print if interactive else None)
        if interactive:
            # free l, k, r, f from matplotlib's own bindings for the viewer's keys
            for key in ("keymap.yscale", "keymap.xscale", "keymap.home", "keymap.fullscreen"):
                plt.rcParams[key] = []
        w, h = size_px
        self.size_px = (int(w), int(h))
        self.fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi, facecolor="#06080f")
        # map left, text column right, header bytes and labels underneath
        self.ax = self.fig.add_axes([0.005, 0.17, 0.60, 0.76])
        ax = self.ax
        ax.set_facecolor("#06080f")
        img = plt.imread(str(TEXTURE))
        ax.imshow(img, extent=[-180, 180, -90, 90], origin="upper", interpolation="bilinear", zorder=0)
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        ax.set_aspect("equal")
        ax.set_xticks(range(-180, 181, 60))
        ax.set_yticks(range(-90, 91, 30))
        ax.tick_params(colors="#909090", labelsize=7)
        self.isl_lc = LineCollection([], linewidths=0.4, colors=[np.array(ISL_NORMAL) / 255],
                                     alpha=0.35, zorder=2)
        ax.add_collection(self.isl_lc)
        self.sel_lc = LineCollection([], linewidths=4.0, colors=[np.array(LINK_SELECTED) / 255], zorder=3)
        ax.add_collection(self.sel_lc)
        self.path_lc = LineCollection([], linewidths=2.5, zorder=4)
        ax.add_collection(self.path_lc)
        self.sats = ax.scatter([], [], s=3, zorder=5, linewidths=0)
        self.packet = ax.scatter([], [], s=70, c="white", edgecolors="black", zorder=7)
        self.halo = ax.scatter([], [], s=420, c=[np.array(STATE_RGB[2]) / 255], alpha=0.45, zorder=6)
        if data.cities:
            ax.scatter([c[2] for c in data.cities], [c[1] for c in data.cities], s=25, c="orange",
                       edgecolors="black", zorder=6)
            for name, lat, lon in data.cities:
                ax.annotate(name, (lon, lat), xytext=(4, 3), textcoords="offset points", color="white",
                            fontsize=7, zorder=8)
        mono = {"family": "monospace", "size": 7.5}
        self.t_title = self.fig.text(0.005, 0.975, "", color="white", fontsize=10, va="top")
        self.t_clock = self.fig.text(0.615, 0.93, "", color="white", fontdict=mono, va="top")
        self.t_msg = self.fig.text(0.615, 0.56, "", color="#ff4040", fontsize=8.5, va="top")
        self.t_side = self.fig.text(0.615, 0.48, "", color="white", fontdict=mono, va="top")
        self.t_hex = self.fig.text(0.005, 0.145, "", color="white", fontdict=mono, va="top")
        self.t_labels = self.fig.text(0.005, 0.035, "", color="#9fe0a0", fontsize=8, va="bottom")
        self.t_render = self.fig.text(0.005, 0.008, "renderer: matplotlib "
                                      f"{matplotlib.__version__} ({matplotlib.get_backend()}, software)",
                                      color="#c0c0c0", fontsize=7.5, va="bottom")
        if interactive:
            self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.refresh()

    # ------------------------------------------------------------------ drawing

    def refresh(self):
        ctl, d = self.ctl, self.data
        pos = ctl.pos
        lon, lat = lonlat(pos)
        sat = ctl.sat_rows
        colors = STATE_RGB[ctl.node_states()] / 255.0
        self.sats.set_offsets(np.column_stack([lon[sat], lat[sat]]) if len(sat) else np.zeros((0, 2)))
        self.sats.set_color(colors[sat])
        isl = d.isl
        idx = ctl.visible_links()
        if len(idx):
            segs = split_segments(lon[isl.a[idx]], lat[isl.a[idx]], lon[isl.b[idx]], lat[isl.b[idx]])
            self.isl_lc.set_segments(segs)
            if ctl.overlay:
                up = ctl.isl_up[idx]
                # colours follow split_segments' order: unsplit links, then both halves of split ones
                cross = np.abs(lon[isl.b[idx]] - lon[isl.a[idx]]) > 180.0
                cols = np.concatenate([up[~cross], up[cross], up[cross]])
                self.isl_lc.set_color([np.array(ISL_UP if u else ISL_DOWN) / 255 for u in cols])
                self.isl_lc.set_alpha(0.9)
            else:
                self.isl_lc.set_color([np.array(ISL_NORMAL) / 255])
                self.isl_lc.set_alpha(0.35)
        else:
            self.isl_lc.set_segments([])
        if ctl.selected_link is not None and self.trace is not None and not ctl.overlay:
            a, b = (ctl.row_of[x] for x in ctl.selected_link)
            self.sel_lc.set_segments(split_segments([lon[a]], [lat[a]], [lon[b]], [lat[b]]))
        else:
            self.sel_lc.set_segments([])
        segs = ctl.path_segments()
        if segs:
            pieces, cols = [], []
            for a, b, kind in segs:
                for p in split_segment(lon[a], lat[a], lon[b], lat[b]):
                    pieces.append(p)
                    cols.append(np.array(PATH_RGB[kind]) / 255)
            self.path_lc.set_segments(pieces)
            self.path_lc.set_color(cols)
        else:
            self.path_lc.set_segments([])
        pp = ctl.packet_position()
        if pp is not None:
            plon, plat = lonlat(pp)
            self.packet.set_offsets([[float(plon), float(plat)]])
        else:
            self.packet.set_offsets(np.zeros((0, 2)))
        if ctl.track is not None and ctl.deviated_rows and ctl.flash_on(next(iter(ctl.deviated_rows))):
            r = next(iter(ctl.deviated_rows))
            self.halo.set_offsets([[lon[r], lat[r]]])
        else:
            self.halo.set_offsets(np.zeros((0, 2)))
        self._hud()

    def _hud(self):
        ctl, d = self.ctl, self.data
        track = ctl.track
        reached = ctl.reached()
        name = (f"trace {Path(self.trace.run_dir).name} ({self.trace.tool})" if self.trace is not None
                else f"snapshot {d.snapshot_id}")
        self.t_title.set_text(f"ChronoRoute viewer (2D fallback) | {name} | {ctl.n_sats} satellites"
                              + (" | LITE" if ctl.lite else ""))
        lines = hud.clock_lines(ctl.player, d.t0_unix_ns if self.trace is not None else None)
        if track is not None:
            lines.append(hud.packet_title(self.trace, track))
            lines += [t for t, _s in hud.hop_rows(self.trace, track, reached)]
        self.t_clock.set_text("\n".join(textwrap.fill(x, 92) if len(x) > 92 else x for x in lines))
        side = []
        if self.trace is not None:
            live = hud.live_faults_text(self.trace)
            side += ([live] if live else [])
            side += [hud.mode_line(ctl.live_available, ctl.live_reason),
                     hud.link_line(self.trace, ctl.selected_link, ctl.selected_hop)]
            f = ctl.selected_fault()
            if f is not None:
                side.append(hud.fault_text(self.trace, f))
            ov = hud.overlay_line(ctl.overlay, f is not None and bool(ctl.link_up(f.link)))
            if ov:
                side.append(ov)
        side += [f"ISLs: {d.isl.source}"] if len(d.isl) else []
        side += d.notes[:2] + ["", hud.KEYS_LINE]
        self.t_side.set_text("\n".join(textwrap.fill(s, 90) if s else "" for s in side))
        self.t_msg.set_text(textwrap.fill(ctl.message or "", 80))
        self.t_hex.set_text("\n".join(hud.header_lines(*hud.header_context(reached)))
                            if track is not None else "")
        self.t_labels.set_text(hud.label_line(d.labels, d.snapshot_id, hud.positions_note(d.positions)))

    # ------------------------------------------------------------------ running

    # the controller may switch to a live re-run of the same scenario: draw ITS trace and data
    @property
    def data(self):
        return self.ctl.data

    @property
    def trace(self):
        return self.ctl.trace

    def _on_key(self, event):
        ctl = self.ctl
        actions = {" ": ctl.key_next, "m": ctl.key_next_miss, "d": ctl.key_degrade, "f": ctl.key_fail,
                   "l": ctl.key_overlay,
                   "+": ctl.key_faster, "=": ctl.key_faster, "-": ctl.key_slower, "r": ctl.key_replay,
                   "[": lambda: ctl.key_move_link(-1), "]": lambda: ctl.key_move_link(+1)}
        fn = actions.get(event.key)
        if fn is not None:
            fn()
            self.refresh()
            self.fig.canvas.draw_idle()

    def update(self, dt_wall_s):
        self.ctl.update(dt_wall_s)
        self.refresh()

    def run_timeline(self, seconds, fps=30):
        for _ in range(int(round(seconds * fps))):
            self.update(1.0 / fps)

    def frame_rgb(self):
        self.fig.canvas.draw()
        buf = np.asarray(self.fig.canvas.buffer_rgba())
        return np.ascontiguousarray(buf[:, :, :3])

    def save_png(self, path):
        self.fig.savefig(str(path), facecolor=self.fig.get_facecolor())

    def record_mp4(self, out_path, seconds, fps=30):
        import imageio_ffmpeg
        w, h = self.fig.canvas.get_width_height()
        writer = imageio_ffmpeg.write_frames(str(out_path), (w, h), fps=fps, quality=7,
                                             macro_block_size=2, ffmpeg_log_level="error")
        writer.send(None)
        n = int(round(seconds * fps))
        try:
            for _ in range(n):
                self.update(1.0 / fps)
                writer.send(self.frame_rgb())
        finally:
            writer.close()
        return {"frames": n, "fps": fps, "size": [w, h]}

    def show(self, fps=20):
        from matplotlib.animation import FuncAnimation
        ctl = self.ctl
        if ctl.picker is not None and ctl.player.walk is None:
            ctl.play(ctl.picker.next())
        last = [time.perf_counter()]

        def step(_i):
            now = time.perf_counter()
            self.update(min(now - last[0], 0.2))
            last[0] = now
            return []

        self._anim = FuncAnimation(self.fig, step, interval=int(1000 / fps), cache_frame_data=False)
        self.plt.show()


__all__ = ["Map2D", "split_segment", "split_polyline", "split_segments", "lonlat"]

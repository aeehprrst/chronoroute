"""
player.py
---------
The viewer's two clocks and the slow-motion packet walk. No graphics here, so the
timing rules can be tested exactly (sim/tests/test_viz_player.py).

Two clocks, both shown in the HUD:

  * the ORBIT clock (UTC) drives the satellite positions. It runs at
    `orbit_speed` (x60 by default: one wall second = one orbit minute) while no
    packet is in flight;
  * the PACKET clock is the trace time of the packet being shown. It runs in slow
    motion: one millisecond of packet time takes `slowmo` milliseconds on screen
    (x100 by default, so a 40 ms trip lasts about 4 s).

While a packet is in flight the orbit clock is FROZEN at the packet's send time.
Why that is honest: a LEO satellite moves about 7.6 m per millisecond, so during a
40-70 ms trip the whole constellation moves well under 1 km, which is far below a
pixel at globe scale; letting the orbit clock run at x60 instead would swing the
satellites thousands of km while the packet crawls along at x0.01.

How the packet moves between two arrivals (hop events at node i, t_i and node j,
t_j). Light needs d/c to cover the straight line between them (d at the frozen
positions), so the packet is drawn WAITING at node i for (t_j - t_i) - d/c
(serialization, queueing, processing: whatever the run put there) and then FLYING
at the speed of light for d/c. In the ns-3 fault run the slowed link's queue holds
probes for up to 1.16 s, which shows as a long wait at the near-end satellite.

A segment never takes more than `max_segment_wall_s` on screen: a 1.16 s queue
wait at x100 would otherwise take two minutes. When a segment is shortened the
HUD says so ("fast-forward") with its real duration, so the time scale on screen
is never misread.
"""

from dataclasses import dataclass

import numpy as np

from .sources import C_KM_PER_NS

ORBIT_SPEED_DEFAULT = 60.0
SLOWMO_DEFAULT = 100.0
MAX_SEGMENT_WALL_S = 2.5
HOLD_WALL_S = 1.5
ORBIT_SPEED_RANGE = (1.0, 3840.0)
SLOWMO_RANGE = (1.0, 12800.0)

IDLE, FLIGHT, HOLD = "idle", "flight", "hold"


@dataclass(frozen=True)
class Segment:
    kind: str            # "wait" (at node_a) or "fly" (node_a -> node_b)
    t_a: float           # trace time, ns since t0
    t_b: float
    node_a: int
    node_b: int


def build_segments(track, pos_of):
    """Wait/fly segments of one packet (module docstring). pos_of(node) -> ECEF km (frozen)."""
    points = []
    for e in track.events:
        if e.ev == "send" and not points:
            points.append((float(e.t), e.node))
        elif e.ev in ("hop", "deliver", "drop"):
            if points and points[-1][1] == e.node and points[-1][0] == float(e.t):
                continue
            points.append((float(e.t), e.node))
    if not points:
        points = [(float(track.t_start), track.events[0].node)]
    segs = []
    for (t_i, n_i), (t_j, n_j) in zip(points[:-1], points[1:]):
        if t_j < t_i:
            raise ValueError(f"packet {track.pkt}: time goes backwards ({t_j} < {t_i})")
        if n_i == n_j:
            if t_j > t_i:
                segs.append(Segment("wait", t_i, t_j, n_i, n_i))
            continue
        d_km = float(np.linalg.norm(np.asarray(pos_of(n_j)) - np.asarray(pos_of(n_i))))
        fly = min(d_km / C_KM_PER_NS, t_j - t_i)
        wait = (t_j - t_i) - fly
        if wait > 0:
            segs.append(Segment("wait", t_i, t_i + wait, n_i, n_i))
        segs.append(Segment("fly", t_i + wait, t_j, n_i, n_j))
    return segs, points


class PacketWalk:
    """Plays one PacketTrack on the packet clock (module docstring)."""

    def __init__(self, track, pos_of, *, slowmo=SLOWMO_DEFAULT, max_segment_wall_s=MAX_SEGMENT_WALL_S):
        self.track = track
        self.pos_of = pos_of
        self.slowmo = float(slowmo)
        self.max_segment_wall_s = float(max_segment_wall_s)
        self.segments, self.points = build_segments(track, pos_of)
        self.restart()

    def restart(self):
        self.sim_t = float(self.track.t_start)
        self.seg_index = 0
        self.event_index = 0
        self.done = not self.segments
        return self._collect_events()

    # --- timing -------------------------------------------------------------

    def segment_wall_s(self, seg):
        """Seconds on screen for one segment: slow motion, capped (fast-forward)."""
        return min((seg.t_b - seg.t_a) * 1e-9 * self.slowmo, self.max_segment_wall_s)

    def is_fast_forward(self, seg):
        return (seg.t_b - seg.t_a) * 1e-9 * self.slowmo > self.max_segment_wall_s

    @property
    def current(self):
        if not self.segments:
            return None
        return self.segments[min(self.seg_index, len(self.segments) - 1)]

    def screen_factor(self):
        """Screen seconds per packet second for the current segment (x100 = slow motion)."""
        seg = self.current
        if seg is None or seg.t_b <= seg.t_a:
            return self.slowmo
        return self.segment_wall_s(seg) / ((seg.t_b - seg.t_a) * 1e-9)

    def total_wall_s(self):
        return sum(self.segment_wall_s(s) for s in self.segments)

    def advance(self, dt_wall_s):
        """Move the packet clock on by dt_wall_s of screen time; returns the events passed."""
        left = float(dt_wall_s)
        while left > 0 and not self.done:
            seg = self.segments[self.seg_index]
            span = seg.t_b - seg.t_a
            wall = self.segment_wall_s(seg)
            if span <= 0 or wall <= 0:
                self.sim_t = seg.t_b
                self._next_segment()
                continue
            rate = span / wall                       # packet ns per screen second
            need = (seg.t_b - self.sim_t) / rate
            if left >= need:
                left -= need
                self.sim_t = seg.t_b
                self._next_segment()
            else:
                self.sim_t += left * rate
                left = 0.0
        return self._collect_events()

    def _next_segment(self):
        self.seg_index += 1
        if self.seg_index >= len(self.segments):
            self.seg_index = len(self.segments) - 1
            self.done = True

    def _collect_events(self):
        out = []
        evs = self.track.events
        # When the walk is done every remaining event is passed (they share the last instant).
        while self.event_index < len(evs) and (evs[self.event_index].t <= self.sim_t or self.done):
            out.append(evs[self.event_index])
            self.event_index += 1
        return out

    # --- where is it ----------------------------------------------------------

    def position(self):
        """ECEF km of the packet now."""
        seg = self.current
        if seg is None:
            return np.asarray(self.pos_of(self.track.events[0].node), dtype=float)
        if seg.kind == "wait" or seg.t_b <= seg.t_a:
            node = seg.node_b if (self.done and seg.kind == "fly") else seg.node_a
            return np.asarray(self.pos_of(node), dtype=float)
        s = min(max((self.sim_t - seg.t_a) / (seg.t_b - seg.t_a), 0.0), 1.0)
        pa = np.asarray(self.pos_of(seg.node_a), dtype=float)
        pb = np.asarray(self.pos_of(seg.node_b), dtype=float)
        return pa + s * (pb - pa)

    def reached_events(self):
        return self.track.events[:self.event_index]


class Player:
    """The state machine idle -> flight -> hold -> idle, and both clocks."""

    def __init__(self, orbit_utc_ns, *, orbit_speed=ORBIT_SPEED_DEFAULT, slowmo=SLOWMO_DEFAULT,
                 max_segment_wall_s=MAX_SEGMENT_WALL_S, hold_wall_s=HOLD_WALL_S):
        self.orbit_utc_ns = int(orbit_utc_ns)
        self.orbit_speed = float(orbit_speed)
        self.slowmo = float(slowmo)
        self.max_segment_wall_s = float(max_segment_wall_s)
        self.hold_wall_s = float(hold_wall_s)
        self.state = IDLE
        self.walk = None
        self.hold_left = 0.0
        self._orbit_frac = 0.0

    @property
    def frozen(self):
        return self.state != IDLE

    def play(self, track, t0_unix_ns, pos_of):
        """Start a packet: jump the orbit clock to its send time and freeze it there."""
        self.orbit_utc_ns = int(t0_unix_ns) + int(track.t_start)
        self._orbit_frac = 0.0
        self.walk = PacketWalk(track, pos_of, slowmo=self.slowmo,
                               max_segment_wall_s=self.max_segment_wall_s)
        self.state = FLIGHT
        return self.walk.restart()

    def replay(self):
        if self.walk is None:
            return []
        self.state = FLIGHT
        return self.walk.restart()

    def advance(self, dt_wall_s):
        """One frame. Returns the packet events passed during it."""
        if self.state == IDLE:
            # Integer ns orbit clock; keep the sub-ns remainder so long runs do not drift.
            step = dt_wall_s * self.orbit_speed * 1e9 + self._orbit_frac
            whole = int(step)
            self._orbit_frac = step - whole
            self.orbit_utc_ns += whole
            return []
        if self.state == FLIGHT:
            events = self.walk.advance(dt_wall_s)
            if self.walk.done:
                self.state = HOLD
                self.hold_left = self.hold_wall_s
            return events
        self.hold_left -= dt_wall_s
        if self.hold_left <= 0:
            self.state = IDLE
        return []

    def faster(self):
        if self.state == IDLE:
            self.orbit_speed = min(self.orbit_speed * 2, ORBIT_SPEED_RANGE[1])
        else:
            self.slowmo = max(self.slowmo / 2, SLOWMO_RANGE[0])
            if self.walk:
                self.walk.slowmo = self.slowmo

    def slower(self):
        if self.state == IDLE:
            self.orbit_speed = max(self.orbit_speed / 2, ORBIT_SPEED_RANGE[0])
        else:
            self.slowmo = min(self.slowmo * 2, SLOWMO_RANGE[1])
            if self.walk:
                self.walk.slowmo = self.slowmo


class PacketPicker:
    """Which packet `space`, `m` and `d` show next (followed flow, late packets, a faulted link)."""

    def __init__(self, trace, follow=None):
        self.trace = trace
        self.flow = self.choose_flow(trace, follow)
        self.tracks = trace.packets_of_flow(self.flow) if self.flow is not None else []
        self.index = -1

    @staticmethod
    def choose_flow(trace, follow):
        """--follow as a flow id or 'Src->Dst'; default: the flow of the first late packet,
        else the lowest flow id."""
        flows = trace.flows()
        if not flows:
            return None
        if follow is not None:
            text = str(follow).strip()
            if text.lstrip("-").isdigit():
                flow = int(text)
                if flow not in flows:
                    raise ValueError(f"flow {flow} is not in the trace (flows: {flows})")
                return flow
            want = text.replace(" ", "").replace("->", ">").lower()
            for f in flows:
                if trace.flow_label(f).replace(" ", "").replace("->", ">").lower() == want:
                    return f
            raise ValueError(f"no flow {follow!r} in the trace; flows: "
                             + ", ".join(f"{f} ({trace.flow_label(f)})" for f in flows))
        for e in trace.events:
            if e.ev == "late":
                return e.flow
        return flows[0]

    @property
    def current(self):
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None

    def next(self):
        if not self.tracks:
            return None
        self.index = (self.index + 1) % len(self.tracks)
        return self.current

    def next_late(self):
        """The next late packet of the followed flow after the current one (wrapping), or None."""
        n = len(self.tracks)
        for step in range(1, n + 1):
            i = (self.index + step) % n
            if self.tracks[i].is_late:
                self.index = i
                return self.tracks[i]
        return None

    def first_crossing(self, link, fault=None, *, prefer_late=True):
        """First packet of the flow that crosses `link` (either direction) while `fault` is active.

        With prefer_late, the first such packet that was also flagged late, if any.
        """
        a, b = link
        hits = []
        for i, tr in enumerate(self.tracks):
            arr = [tr.events[0]] + tr.arrivals
            for x, y in zip(arr[:-1], arr[1:]):
                if {x.node, y.node} == {a, b} and (fault is None or fault.active(y.t) or fault.active(x.t)):
                    hits.append(i)
                    break
        if not hits:
            return None
        chosen = hits[0]
        if prefer_late:
            for i in hits:
                if self.tracks[i].is_late:
                    chosen = i
                    break
        self.index = chosen
        return self.tracks[chosen]


FLASH_PERIOD_S = 0.25
FLASH_TIME_S = 2.0
TOPOLOGY_TICK_NS = 100_000_000          # link up/down recomputed at most every 100 ms of orbit time
AUTOPLAY_IDLE_S = 1.0


class Controller:
    """Everything the viewer DOES, without drawing anything (shared by globe.py and map2d.py).

    It owns the clocks (Player), which packet is shown (PacketPicker), the node
    positions at the orbit clock, the laser links' up/down state, the selected link,
    the link-state overlay flag, the messages, and what each key does. A renderer
    reads its state every frame (node_colors, visible_links, path_segments,
    packet_position, ...) and calls update(dt) and the key_* methods.

    Keys `d` (degrade the selected link: a rate cut) and `f` (fail it: link down),
    LIVE mode: with the engine's re-run hook (sources.engine_api ->
    fwd.engine.rerun_with_fault) on a python-sim trace, the engine re-runs the
    whole run with that one extra fault from the instant on screen (same seed,
    same random numbers), the viewer switches to the new trace (switch_data) and
    plays the first packet of the followed flow that the fault changed. Packets
    that never met the fault are identical in both runs (common random numbers),
    so "changed" is exact. Otherwise (no hook, an ns-3 trace, or the re-run
    failed) the viewer is REPLAY-ONLY and says why, and d / f jump to the first
    packet of the followed flow that crossed the RECORDED faulted link while the
    fault was active (preferring one that was flagged late). It never pretends a
    new fault was simulated.
    """

    def __init__(self, data, *, follow=None, orbit_speed=ORBIT_SPEED_DEFAULT,
                 slowmo=SLOWMO_DEFAULT, autoplay=False, lite="auto", engine="auto", say=None,
                 loader=None):
        from .sources import LITE_THRESHOLD, engine_api
        self.data = data
        self.trace = data.trace
        self.row_of = data.row_of_node
        self.sat_rows = np.array(data.sat_rows, dtype=np.int64)
        self.n_sats = len(self.sat_rows)
        self.lite = (self.n_sats > LITE_THRESHOLD) if lite == "auto" else (lite == "on")
        self.player = Player(data.start_utc_ns, orbit_speed=orbit_speed, slowmo=slowmo)
        self.picker = PacketPicker(self.trace, follow) if self.trace is not None else None
        self.engine = engine_api() if engine == "auto" else engine
        self.loader = loader              # trace folder -> ViewerData (default sources.load_viewer_data)
        self.live_runs = []               # folders the engine wrote in live mode, newest last
        self.autoplay = autoplay
        self.overlay = False
        self.message = None
        self.message_level = "info"
        self.selected_link = None
        self.selected_hop = None
        self.picked_row = None
        self.flash = {}                 # row -> seconds of flashing left
        self.deviated_rows = set()
        self.fallback_rows = set()
        self._packet_story = []         # headlines of the packet on screen (late, fallback, end)
        self.pos = np.zeros((len(data.node_ids), 3))
        self.isl_up = np.zeros(len(data.isl), dtype=bool)
        self._pos_time = None
        self._topo_time = None
        self._idle_wall = 0.0
        self._playlist = []
        self._say_hook = say
        self.default_link()
        self.update_positions(force=True)

    # --- state the renderers read --------------------------------------------

    @property
    def track(self):
        """The packet on screen (in flight or held), or None when idle."""
        w = self.player.walk
        return w.track if w is not None and self.player.state != IDLE else None

    def reached(self):
        return self.player.walk.reached_events() if self.track is not None else []

    @property
    def live_available(self):
        return self.engine is not None and self.trace is not None and self.trace.tool == "python-sim"

    @property
    def live_reason(self):
        """Why the viewer is replay-only (None when live)."""
        if self.engine is None:
            return "engine API not available"
        if self.trace is None:
            return "no trace"
        if self.trace.tool != "python-sim":
            return f"a {self.trace.tool} trace cannot be re-run by the Python engine"
        return None

    def path_rows(self, track=None):
        track = track if track is not None else self.track
        return [self.row_of[n] for n in track.path] if track is not None else []

    def flash_on(self, row):
        if row not in self.flash:
            return True
        return int((FLASH_TIME_S - self.flash[row]) / FLASH_PERIOD_S) % 2 == 0

    def node_states(self):
        """Per node row: 0 normal, 1 on the path, 2 deviated (red, flashing), 3 fallback, 4 picked."""
        st = np.zeros(len(self.pos), dtype=np.uint8)
        if self.track is not None:
            st[self.path_rows()] = 1
            for r in self.fallback_rows:
                st[r] = 3
            for r in self.deviated_rows:
                st[r] = 2 if self.flash_on(r) else 1
        if self.picked_row is not None:
            st[self.picked_row] = 4
        return st

    def visible_links(self):
        """Indices into data.isl drawn now: up links (normal view) or all candidates (overlay);
        in Lite mode only those near the packet's path."""
        from .sources import links_near_path
        isl = self.data.isl
        if not len(isl):
            return np.zeros(0, dtype=np.int64)
        if self.lite:
            cand = np.zeros(len(isl), dtype=bool)
            if self.track is not None:
                cand[links_near_path(isl, self.path_rows())] = True
        else:
            cand = np.ones(len(isl), dtype=bool)
        return np.flatnonzero(cand if self.overlay else (cand & self.isl_up))

    def path_segments(self):
        """[(row_a, row_b, kind)] of the packet's path: kind 'done', 'fallback' or 'todo'."""
        track = self.track
        if track is None:
            return []
        rows = self.path_rows()
        reached = self.reached()
        n_reached = 1 + sum(1 for e in reached if e.ev == "hop")
        fb_index = None
        for e in reached:
            if e.ev == "fallback" and e.node in track.path:
                fb_index = track.path.index(e.node)
                break
        out = []
        for i in range(len(rows) - 1):
            if i + 1 < n_reached:
                kind = "fallback" if fb_index is not None and i >= fb_index else "done"
            else:
                kind = "todo"
            out.append((rows[i], rows[i + 1], kind))
        return out

    def packet_position(self):
        return self.player.walk.position() if self.track is not None else None

    def selected_fault(self):
        if self.selected_link is None:
            return None
        return next((f for f in self.data.faults if f.link and f.touches(*self.selected_link)), None)

    def link_up(self, link):
        """Is this laser link up now (the topology model's rule)? None if it is not a laser link."""
        a, b = (self.row_of[x] for x in link)
        isl = self.data.isl
        hit = np.flatnonzero(((isl.a == a) & (isl.b == b)) | ((isl.a == b) & (isl.b == a)))
        return bool(self.isl_up[hit[0]]) if hit.size else None

    def pick_nearest(self, point):
        if point is None or self.n_sats == 0:
            return None
        d = np.linalg.norm(self.pos[self.sat_rows] - np.asarray(point, dtype=float)[None, :], axis=1)
        self.picked_row = int(self.sat_rows[int(np.argmin(d))])
        return self.picked_row

    # --- clocks and positions ----------------------------------------------

    def update_positions(self, force=False):
        from .sources import isl_up
        t = self.player.orbit_utc_ns
        if not force and t == self._pos_time:
            return False
        pos = self.data.positions.ecef_km(t)
        bad = ~np.isfinite(pos).all(axis=1)
        pos[bad] = 0.0                  # SGP4 failure: parked at the centre (hidden), counted in the HUD
        self.pos = pos
        self._pos_time = t
        if len(self.data.isl) and (force or self._topo_time is None
                                   or abs(t - self._topo_time) >= TOPOLOGY_TICK_NS):
            self.isl_up = isl_up(self.data.isl, pos)
            self._topo_time = t
        return True

    def update(self, dt_wall_s):
        """One frame: both clocks, the events passed, flashing, autoplay, positions."""
        events = self.player.advance(dt_wall_s)
        self.handle_events(events)
        for row in list(self.flash):
            self.flash[row] -= dt_wall_s
            if self.flash[row] <= 0:
                del self.flash[row]
        if self.player.state == IDLE:
            self._idle_wall += dt_wall_s
            if self.autoplay and self._idle_wall >= AUTOPLAY_IDLE_S:
                self._idle_wall = 0.0
                self.autoplay_next()
        else:
            self._idle_wall = 0.0
        self.update_positions()

    def _pos_of(self, node):
        return self.pos[self.row_of[node]]

    # --- messages -------------------------------------------------------------

    def say(self, text, level="info"):
        self.message = text
        self.message_level = level
        if self._say_hook is not None:
            self._say_hook(text)

    def handle_events(self, events):
        """React to the packet events just passed. The headline keeps this packet's story
        (MISS, then FALLBACK, then delivered / dropped) so the miss stays readable."""
        from . import hud
        tr = self.player.walk.track if self.player.walk else None
        for e in events:
            row = self.row_of.get(e.node)
            if e.ev == "late":
                self.deviated_rows.add(row)
                self.flash[row] = FLASH_TIME_S
            elif e.ev == "fallback":
                self.fallback_rows.add(row)
            if e.ev in ("late", "fallback", "deliver", "drop"):
                self._packet_story.append(hud.event_message(self.trace, tr, e))
                bad = self.deviated_rows or self.fallback_rows or e.ev == "drop"
                self.say("  |  ".join(self._packet_story), "miss" if bad else "info")

    # --- playing ----------------------------------------------------------------

    def reset_packet_state(self):
        self.flash.clear()
        self.deviated_rows.clear()
        self.fallback_rows.clear()
        self._packet_story = []
        self.message = None
        self.message_level = "info"

    def play(self, track, keep_link=False):
        if track is None:
            return
        self.reset_packet_state()
        # Positions at the send time FIRST: the walk splits each hop into wait + light-speed
        # flight from these (frozen) positions.
        self.player.orbit_utc_ns = int(self.data.t0_unix_ns) + int(track.t_start)
        self.update_positions(force=True)
        self.player.play(track, self.data.t0_unix_ns, self._pos_of)
        if not keep_link or self.selected_link is None:
            self.default_link(track)
        self.handle_events(self.player.walk.reached_events())

    def default_link(self, track=None):
        """The recorded fault's link if this packet crosses it (or no packet yet), else hop 4."""
        if self.trace is None:
            return
        faults = [f for f in self.data.faults if f.link]
        links = track.links() if track is not None else []
        for f in faults:
            for k, (u, v) in enumerate(links):
                if f.touches(u, v):
                    self.selected_link, self.selected_hop = (u, v), k + 1
                    return
        if faults and not links:
            self.selected_link, self.selected_hop = faults[0].link, None
            return
        if links:
            k = min(3, len(links) - 1)
            self.selected_link, self.selected_hop = links[k], k + 1

    def autoplay_next(self):
        """Record mode / --autoplay: the first packet, then the deadline miss (as d would), then on."""
        if self.picker is None:
            return
        if not self._playlist:
            self._playlist = ["first", "degrade", "next"]
        step = self._playlist.pop(0) if len(self._playlist) > 1 else "next"
        if step == "first":
            self.picker.index = -1
            self.play(self.picker.next())
        elif step == "degrade":
            before = self.picker.index
            self.key_degrade()
            if self.player.state == IDLE:          # nothing recorded to show: just go on
                self.picker.index = before
                self.play(self.picker.next())
        else:
            self.play(self.picker.next())

    # --- keys -------------------------------------------------------------------

    def key_next(self):
        if self.picker is None:
            self.say("snapshot view: no packets (open a trace with --trace)")
            return
        self.play(self.picker.next())

    def key_next_miss(self):
        if self.picker is None:
            return
        tr = self.picker.next_late()
        if tr is None:
            self.say(f"no deadline miss in flow {self.picker.flow}")
            return
        self.play(tr)

    def key_degrade(self):
        """d: degrade the selected link (a rate cut), live or replay-only (class docstring)."""
        self._key_fault("rate")

    def key_fail(self):
        """f: fail the selected link (link down), live or replay-only (class docstring)."""
        self._key_fault("down")

    def _key_fault(self, kind):
        key = "f" if kind == "down" else "d"
        if self.trace is None:
            self.say(f"snapshot view: {key} needs a trace")
            return
        if self.selected_link is None:
            self.say("no link selected: play a packet first, then [ ] to choose a hop")
            return
        if self.live_available:
            # the fault starts at the instant on screen: the send time of the packet being shown
            # (the orbit clock is frozen there), so that packet is the first one that can change
            start = max(0, int(self.player.orbit_utc_ns - self.data.t0_unix_ns))
            flow, link = self.picker.flow, self.selected_link
            try:
                out = self.engine(self.trace.run_dir, flow=flow, link=link, start_ns=start, kind=kind)
            except Exception as exc:              # report it, keep running, show what was recorded
                self._replay_recorded(f"live re-run failed ({type(exc).__name__}: {exc}); replay-only")
                return
            self._go_live(out, kind, flow, link, start)
            return
        self._replay_recorded(f"replay-only ({self.live_reason})")

    def _replay_recorded(self, prefix):
        """Replay-only d / f: the first packet that crossed the RECORDED faulted link."""
        fault = self.selected_fault()
        if fault is None:
            others = [f for f in self.data.faults if f.link]
            hint = ""
            if others:
                a, b = others[0].link
                hint = (f"; the recorded fault is on {self.trace.nodes[a].name} - "
                        f"{self.trace.nodes[b].name} (use [ ] to select it)")
            self.say(f"{prefix}: this link has no recorded fault" + hint, "warn")
            return
        tr = self.picker.first_crossing(fault.link, fault)
        if tr is None:
            self.say(f"{prefix}: no packet of this flow crossed the recorded faulted link", "warn")
            return
        self.play(tr, keep_link=True)
        what = "link-down" if fault.kind == "link_down" else "up-but-slow"
        self.say(f"{prefix}: showing the RECORDED {what} fault on this link", "warn")

    def _go_live(self, out, kind, flow, link, start):
        """Switch to the engine's new run and play the first packet the new fault changed."""
        loader = self.loader
        if loader is None:
            from .sources import load_viewer_data
            loader = load_viewer_data
        try:
            new = loader(trace_dir=out)
        except Exception as exc:
            self.say(f"live: the engine re-ran flow {flow} into {out}, but the viewer cannot load it "
                     f"({type(exc).__name__}: {exc})", "warn")
            return
        from . import hud
        changed = self.switch_data(new)
        self.live_runs.append(str(out))
        what = hud.LIVE_WHAT.get(kind, kind)
        a, b = link
        n_ch = f"{len(changed)} packet{'' if len(changed) == 1 else 's'} of this flow"
        earlier = hud.live_faults(self.trace)[:-1]
        if earlier:
            # the key re-ran the run ON SCREEN, which already had live faults: they are all still
            # active, so name every one (the newest alone would suggest only that link is hit)
            prev = "; ".join(hud.live_fault_phrase(self.trace, k, f) for k, f in earlier)
            head = (f"live: the engine re-ran flow {flow} with {self.trace.nodes[a].name} - "
                    f"{self.trace.nodes[b].name} {what} from t0 + {start / 1e9:.3f} s ADDED to the "
                    f"{len(earlier)} live fault{'' if len(earlier) == 1 else 's'} already in the run on "
                    f"screen, all active: {prev} (same seed, same random numbers; {out}): {n_ch} changed "
                    "by the newest fault")
        else:
            head = (f"live: the engine re-ran flow {flow} with {self.trace.nodes[a].name} - "
                    f"{self.trace.nodes[b].name} {what} from t0 + {start / 1e9:.3f} s (same seed, same "
                    f"random numbers; {out}): {n_ch} changed")
        if not changed:
            self.say(head + " (none of them met the link after that instant)", "warn")
            return
        bad = [t for t in changed if t.is_late or t.fallback_events or (t.outcome and t.outcome.ev == "drop")]
        tr = (bad or changed)[0]
        self.picker.index = self.picker.tracks.index(tr)
        self.play(tr, keep_link=True)
        self.say(head + f"; showing packet {tr.pkt}", "miss" if bad else "info")

    def switch_data(self, data):
        """Show another run of the SAME scenario (a live re-run): new trace, same followed flow and
        selected link. Returns the tracks of the followed flow whose story differs from the
        previous trace's (same packet ids: common random numbers)."""
        def story(track):
            if track is None:
                return None
            return tuple((e.t, e.ev, e.node, e.next, e.flags, e.reason) for e in track.events)

        flow = self.picker.flow if self.picker is not None else None
        old = {t.pkt: t for t in self.picker.tracks} if self.picker is not None else {}
        self.data = data
        self.trace = data.trace
        self.row_of = data.row_of_node
        self.sat_rows = np.array(data.sat_rows, dtype=np.int64)
        self.n_sats = len(self.sat_rows)
        self.picker = PacketPicker(self.trace, flow) if self.trace is not None else None
        self.player.walk = None
        self.player.state = IDLE
        self.reset_packet_state()
        self.update_positions(force=True)
        if self.picker is None:
            return []
        return [t for t in self.picker.tracks if story(t) != story(old.get(t.pkt))]

    def key_overlay(self):
        self.overlay = not self.overlay

    def key_faster(self):
        self.player.faster()

    def key_slower(self):
        self.player.slower()

    def key_replay(self):
        if self.player.walk is not None:
            self.reset_packet_state()
            self.player.replay()
            self.handle_events(self.player.walk.reached_events())

    def key_move_link(self, step):
        tr = self.player.walk.track if self.player.walk else None
        if tr is None:
            return
        links = tr.links()
        if not links:
            return
        k = max(0, min(len(links) - 1, (self.selected_hop or 1) - 1 + step))
        self.selected_hop = k + 1
        self.selected_link = links[k]


__all__ = ["ORBIT_SPEED_DEFAULT", "SLOWMO_DEFAULT", "MAX_SEGMENT_WALL_S", "HOLD_WALL_S",
           "IDLE", "FLIGHT", "HOLD", "Segment", "build_segments", "PacketWalk", "Player",
           "PacketPicker", "Controller", "FLASH_TIME_S", "FLASH_PERIOD_S"]

"""
The viewer's clocks, packet walk and key behaviour (sim/chronoroute/viz/player.py),
without any graphics. Uses the real-data synthetic trace of test_viz_sources.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from chronoroute.viz import hud
from chronoroute.viz import player as pl
from chronoroute.viz import sources
from test_viz_sources import A, B, C, D, E, CHENNAI, LONDON, T0_UNIX, make_trace

C_KM_NS = 299_792.458e-9


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    return sources.load_viewer_data(trace_dir=make_trace(tmp_path_factory.mktemp("viz-player") / "run"))


def pos_of_factory(data, t_ns):
    pos = data.positions.ecef_km(T0_UNIX + t_ns)
    rows = data.row_of_node
    return lambda n: pos[rows[n]]


# ----------------------------------------------------------------------- segments and timing

def test_segments_split_each_hop_into_wait_then_light_speed_flight(data):
    tr = data.trace.packets[0]
    pos_of = pos_of_factory(data, tr.t_start)
    segs, points = pl.build_segments(tr, pos_of)
    assert [n for _t, n in points] == tr.path
    assert segs[0].t_a == tr.t_start and segs[-1].t_b == tr.outcome.t
    for s0, s1 in zip(segs, segs[1:]):
        assert s0.t_b == pytest.approx(s1.t_a)                 # contiguous, no gaps
    for s in segs:
        if s.kind == "fly":
            d = np.linalg.norm(np.asarray(pos_of(s.node_b)) - np.asarray(pos_of(s.node_a)))
            assert (s.t_b - s.t_a) == pytest.approx(d / C_KM_NS, rel=1e-9)   # flies at c
    # the 15 ms queue before the slowed link shows as a long wait at B
    waits = {s.node_a: s.t_b - s.t_a for s in segs if s.kind == "wait"}
    assert waits[B] > 15e6 and all(waits[n] < 1e6 for n in waits if n != B)


def test_slow_motion_and_fast_forward(data):
    tr = data.trace.packets[0]
    walk = pl.PacketWalk(tr, pos_of_factory(data, tr.t_start), slowmo=100.0, max_segment_wall_s=2.5)
    first = walk.segments[0]
    assert first.kind == "wait" and walk.segment_wall_s(first) < 0.1     # 0.5 ms processing
    # at x100, 10 ms of screen time inside an un-capped flight is 0.1 ms of packet time
    walk.advance(walk.segment_wall_s(first))
    seg = walk.current
    assert seg.kind == "fly" and not walk.is_fast_forward(seg)
    t_before = walk.sim_t
    walk.advance(0.010)
    assert walk.sim_t - t_before == pytest.approx(100_000, rel=1e-9)
    assert walk.screen_factor() == pytest.approx(100.0)
    # the 15+ ms wait at B would take > 1.5 s at x100: still under the 2.5 s cap here...
    wait_b = next(s for s in walk.segments if s.kind == "wait" and s.node_a == B)
    assert walk.segment_wall_s(wait_b) == pytest.approx(min((wait_b.t_b - wait_b.t_a) * 1e-7, 2.5))
    # ...but at x1000 it is fast-forwarded and the factor says so
    walk.slowmo = 1000.0
    assert walk.is_fast_forward(wait_b) and walk.segment_wall_s(wait_b) == 2.5
    total = walk.total_wall_s()
    passed = walk.restart()                                    # the send event is passed at once
    passed += walk.advance(total + 1.0)
    assert walk.done and walk.sim_t == tr.outcome.t
    assert passed == tr.events                                 # every event exactly once, in order


def test_events_fire_when_the_packet_clock_reaches_them(data):
    tr = data.trace.packets[0]
    walk = pl.PacketWalk(tr, pos_of_factory(data, tr.t_start))
    assert walk.reached_events() == [tr.events[0]]             # the send is there at once
    seen = list(walk.reached_events())
    while not walk.done:
        new = walk.advance(1 / 30)
        assert all(e.t <= walk.sim_t for e in new)
        seen += new
    assert seen == tr.events
    np.testing.assert_allclose(walk.position(), pos_of_factory(data, tr.t_start)(LONDON))


def test_orbit_clock_runs_freezes_and_resumes(data):
    p = pl.Player(T0_UNIX, orbit_speed=60.0, slowmo=100.0, hold_wall_s=0.5)
    p.advance(1.0)
    assert p.orbit_utc_ns == T0_UNIX + 60_000_000_000           # x60: one wall second = one minute
    for _ in range(3):
        p.advance(1 / 3)
    assert p.orbit_utc_ns == T0_UNIX + 120_000_000_000          # no drift from the fractions
    tr = data.trace.packets[1]
    p.play(tr, T0_UNIX, pos_of_factory(data, tr.t_start))
    assert p.state == pl.FLIGHT and p.orbit_utc_ns == T0_UNIX + tr.t_start   # jumped to the send time
    frozen = p.orbit_utc_ns
    while p.state == pl.FLIGHT:
        p.advance(0.1)
        assert p.orbit_utc_ns == frozen                         # frozen while the packet flies
    assert p.state == pl.HOLD
    p.advance(0.6)
    assert p.state == pl.IDLE
    p.advance(0.5)
    assert p.orbit_utc_ns == frozen + 30_000_000_000            # running again


def test_speed_keys_change_the_active_clock(data):
    p = pl.Player(T0_UNIX)
    p.faster()
    assert p.orbit_speed == 120.0 and p.slowmo == 100.0
    tr = data.trace.packets[1]
    p.play(tr, T0_UNIX, pos_of_factory(data, tr.t_start))
    p.faster()
    assert p.slowmo == 50.0 and p.walk.slowmo == 50.0
    p.slower()
    p.slower()
    assert p.slowmo == 200.0 and p.orbit_speed == 120.0


# ----------------------------------------------------------------------- packet choice

def test_picker_follows_flows(data):
    tr = data.trace
    assert pl.PacketPicker.choose_flow(tr, None) == 0               # the flow of the first late packet
    assert pl.PacketPicker.choose_flow(tr, "1") == 1
    assert pl.PacketPicker.choose_flow(tr, "London -> Chennai") == 1
    assert pl.PacketPicker.choose_flow(tr, "chennai->london") == 0
    with pytest.raises(ValueError, match="no flow"):
        pl.PacketPicker.choose_flow(tr, "Tokyo->Paris")
    with pytest.raises(ValueError, match="not in the trace"):
        pl.PacketPicker.choose_flow(tr, "7")
    pk = pl.PacketPicker(tr, None)
    assert [pk.next().pkt, pk.next().pkt, pk.next().pkt] == [0, 1, 0]    # wraps around
    pk.index = 0
    assert pk.next_late().pkt == 0                                       # the only late one
    fault = tr.faults[0]
    assert pk.first_crossing((C, B), fault).pkt == 0                      # either direction; late first
    assert pk.first_crossing((C, B), fault, prefer_late=False).pkt == 0
    assert pk.first_crossing((A, E)) is None


# ----------------------------------------------------------------------- controller (keys)

def test_degrade_is_replay_only_without_the_engine_and_says_so(data):
    ctl = pl.Controller(data, engine=None)
    assert ctl.selected_link == (B, C)                  # the recorded fault's link
    ctl.key_next()                                      # packet 0 is first in flow 0
    ctl.key_next()                                      # packet 1: on time
    assert ctl.track.pkt == 1 and not ctl.deviated_rows
    ctl.key_degrade()
    assert ctl.track.pkt == 0
    assert ctl.message.startswith("replay-only (engine API not available)")
    assert "RECORDED" in ctl.message and ctl.message_level == "warn"
    # play it through: the late node turns red, the path after the fallback is magenta
    while ctl.player.state == pl.FLIGHT:
        ctl.update(1 / 30)
    rows = data.row_of_node
    assert ctl.deviated_rows == {rows[C]} and ctl.fallback_rows == {rows[C]}
    states = ctl.node_states()
    assert states[rows[C]] in (1, 2)                    # red, or yellow during a flash-off phase
    ctl.flash.clear()
    assert ctl.node_states()[rows[C]] == 2
    kinds = [k for _a, _b, k in ctl.path_segments()]
    path = data.trace.packets[0].path
    fb = path.index(C)
    assert kinds[:fb] == ["done"] * fb and kinds[fb:] == ["fallback"] * (len(path) - 1 - fb)
    assert "MISS by" in ctl.message and "delivered to London" in ctl.message


def test_degrade_on_a_link_without_a_fault_points_to_the_recorded_one(data):
    ctl = pl.Controller(data, engine=None)
    ctl.key_next()
    ctl.key_move_link(-5)                                # first hop: Chennai - A
    assert ctl.selected_link == (CHENNAI, A) and ctl.selected_hop == 1
    ctl.key_degrade()
    assert "no recorded fault" in ctl.message and "use [ ] to select it" in ctl.message


def test_live_mode_calls_the_engine_hook(data):
    calls = []

    def fake_engine(run_dir, **kw):
        calls.append((run_dir, kw))
        return "/tmp/new-run"

    ctl = pl.Controller(data, engine=fake_engine)
    assert ctl.live_available                            # a python-sim trace + a hook
    ctl.key_degrade()
    assert calls and calls[0][1]["link"] == (B, C) and calls[0][1]["flow"] == 0
    assert ctl.message.startswith("live: the engine re-ran flow 0")

    def broken(run_dir, **kw):
        raise RuntimeError("boom")

    ctl = pl.Controller(data, engine=broken)
    ctl.key_degrade()
    assert "live re-run failed (RuntimeError: boom); replay-only" in ctl.message


def test_link_state_overlay_shows_the_slowed_link_up(data):
    ctl = pl.Controller(data, engine=None)
    ctl.key_next()
    normal = set(ctl.visible_links().tolist())
    ctl.key_overlay()
    assert ctl.overlay
    assert set(ctl.visible_links().tolist()) >= normal
    assert ctl.link_up((B, C)) is True                   # up-but-slow: the link state says UP
    assert ctl.link_up((CHENNAI, A)) is None             # a ground link is not a laser link


def test_lite_mode_draws_only_links_near_the_path(data):
    ctl = pl.Controller(data, engine=None, lite="on")
    assert ctl.lite and len(ctl.visible_links()) == 0    # no packet, no links
    ctl.key_next()
    assert len(ctl.visible_links()) == 4                 # all 4 pairs are within 2 hops of the path
    full = pl.Controller(data, engine=None, lite="off")
    assert len(full.visible_links()) == 4


def test_autoplay_goes_first_packet_then_the_recorded_miss(data):
    ctl = pl.Controller(data, engine=None, autoplay=True)
    played = []
    for _ in range(30 * 40):
        before = ctl.track.pkt if ctl.track is not None else None
        ctl.update(1 / 30)
        if ctl.track is not None and ctl.track.pkt != before:
            played.append(ctl.track.pkt)
        if len(played) >= 3:
            break
    assert played[:3] == [0, 0, 1]                       # first packet, the miss (via d), the next one


def test_a_packet_is_split_with_positions_at_its_send_time(data):
    """After minutes of idle orbit, playing a packet first moves the satellites back to its
    send time, and the wait / flight split uses those positions."""
    ctl = pl.Controller(data, engine=None)
    for _ in range(150):
        ctl.update(1 / 30)                                # 5 s at x60: the orbit clock is 5 min on
    assert ctl.player.orbit_utc_ns > T0_UNIX + 290 * 10 ** 9
    ctl.key_next()
    tr = ctl.track
    assert ctl.player.orbit_utc_ns == T0_UNIX + tr.t_start
    pos_of = pos_of_factory(data, tr.t_start)
    for s in ctl.player.walk.segments:
        if s.kind == "fly":
            d = np.linalg.norm(np.asarray(pos_of(s.node_b)) - np.asarray(pos_of(s.node_a)))
            assert (s.t_b - s.t_a) == pytest.approx(d / C_KM_NS, rel=1e-9)
    np.testing.assert_array_equal(ctl.pos, data.positions.ecef_km(T0_UNIX + tr.t_start))


def test_f_without_the_engine_is_replay_only_too(data):
    ctl = pl.Controller(data, engine=None)
    ctl.key_fail()
    assert ctl.track.pkt == 0 and ctl.message.startswith("replay-only (engine API not available)")
    assert "RECORDED up-but-slow fault" in ctl.message


@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    """A real (small) cr run, so the viewer can drive the REAL engine in live mode."""
    from chronoroute.fwd import command, config
    out = tmp_path_factory.mktemp("viz-live") / "run"
    d = {"seed": 4, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 4, "drain_s": 1,
                                 "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
         "traffic": {"flows": [{"src": "London", "dst": "New York"}], "rate_pps": 50},
         "forwarding": {"policy": "greedy"}, "output": {"trace": "sampled", "sample_every": 1}}
    command.run_config(config.normalise(d), out)
    return out


@pytest.mark.parametrize("key", ["d", "f"])
def test_live_mode_drives_the_real_engine(real_run, key):
    """d / f re-run the REAL engine (fwd.engine.rerun_with_fault, found through
    sources.ENGINE_HOOK) with the selected link degraded / failed from the packet on screen; the
    viewer switches to the new run and plays a packet the fault changed. Every packet it says
    is unchanged has the same story in both runs (common random numbers)."""
    data = sources.load_viewer_data(trace_dir=real_run)
    ctl = pl.Controller(data)                                  # engine="auto": the real hook
    assert ctl.live_available and ctl.live_reason is None
    tracks = ctl.picker.tracks
    shown = next(t for t in tracks if t.t_start >= 1_500_000_000)
    ctl.picker.index = tracks.index(shown) - 1
    ctl.key_next()
    assert ctl.track.pkt == shown.pkt
    links = shown.links()
    ctl.key_move_link(-99)
    ctl.key_move_link(len(links) // 2)                          # a laser link in the middle of the path
    link = ctl.selected_link
    old = {t.pkt: t for t in tracks}
    (ctl.key_degrade if key == "d" else ctl.key_fail)()
    assert ctl.message.startswith("live: the engine re-ran flow 0"), ctl.message
    assert ctl.live_runs and ctl.trace.run_dir != data.trace.run_dir
    assert ctl.data is not data and ctl.selected_link == link
    run = json.loads((Path(ctl.live_runs[-1]) / "run.json").read_text())
    assert run["rerun"]["fault"]["link"] == sorted(link) or run["rerun"]["fault"]["link"] == list(link)
    assert run["rerun"]["kind"] == ("rate" if key == "d" else "down")
    tr = ctl.track
    assert tr is not None

    def story(t):
        return [(e.t, e.ev, e.node, e.next, e.flags) for e in t.events]

    assert story(tr) != story(old[tr.pkt])                      # the packet shown really changed
    for t in ctl.picker.tracks:
        if story(t) != story(old[t.pkt]):
            hops = set(zip(t.path, t.path[1:])) | set(zip(old[t.pkt].path, old[t.pkt].path[1:]))
            assert any({u, v} == set(link) for u, v in hops)    # only packets that met the link
            assert t.t_start >= shown.t_start - 200_000_000


def test_live_faults_accumulate_and_are_all_named(real_run):
    """Minor finding: each live key re-runs the run ON SCREEN, so faults accumulate (f, f again
    on another link, then d gives a run with three faults), but the message named only the
    newest. Now the message names every earlier live fault as still active, and the HUD text
    (hud.live_faults_text, from run.json rerun.live_faults) lists all of them."""
    data = sources.load_viewer_data(trace_dir=real_run)
    ctl = pl.Controller(data)
    tracks = ctl.picker.tracks
    shown = next(t for t in tracks if t.t_start >= 1_500_000_000)
    ctl.picker.index = tracks.index(shown) - 1
    ctl.key_next()
    ctl.key_move_link(-99)
    ctl.key_move_link(len(shown.links()) // 2)
    names = lambda link: f"{ctl.trace.nodes[link[0]].name} - {ctl.trace.nodes[link[1]].name}"  # noqa: E731
    l1 = ctl.selected_link
    ctl.key_fail()
    assert ctl.message.startswith("live: the engine re-ran flow 0") and "ADDED" not in ctl.message
    assert hud.live_faults_text(ctl.trace).startswith("1 live fault in this run")
    # the second key: another link of the packet now on screen
    ctl.key_move_link(1 if ctl.selected_hop < len(ctl.track.links()) else -1)
    l2 = ctl.selected_link
    assert set(l2) != set(l1)
    ctl.key_fail()
    ctl.key_degrade()
    msg = ctl.message
    assert "ADDED to the 2 live faults already in the run on screen, all active" in msg, msg
    assert f"{names(l1)} failed" in msg and f"{names(l2)} failed" in msg and "degraded (rate cut)" in msg
    text = hud.live_faults_text(ctl.trace)
    assert text.startswith("3 live faults in this run (all active")
    assert text.count(" failed from t0 + ") == 2 and text.count(" degraded (rate cut) from t0 + ") == 1
    run = json.loads((Path(ctl.trace.run_dir) / "run.json").read_text())
    assert [x["kind"] for x in run["rerun"]["live_faults"]] == ["down", "down", "rate"]
    assert run["rerun"]["original"] == str(real_run)


def test_pick_nearest_satellite(data):
    ctl = pl.Controller(data, engine=None)
    target = ctl.pos[data.row_of_node[D]] + np.array([30.0, -20.0, 10.0])
    assert ctl.pick_nearest(target) == data.row_of_node[D]
    assert ctl.node_states()[data.row_of_node[D]] == 4

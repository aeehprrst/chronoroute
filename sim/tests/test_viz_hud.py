"""
HUD text (sim/chronoroute/viz/hud.py): every string the viewer shows, checked
against values computed independently from the trace.
"""

import pytest

from chronoroute import proto
from chronoroute.proto import timebase
from chronoroute.viz import hud, player as pl, sources
from test_viz_sources import A, B, C, E, LONDON, T0_GPS, T0_UNIX, UNIT, make_trace

U_MS = timebase.unit_ns(UNIT) / 1e6


@pytest.fixture(scope="module")
def trace(tmp_path_factory):
    return sources.load_trace(make_trace(tmp_path_factory.mktemp("viz-hud") / "run"))


def test_label_line_names_what_is_real_and_modelled(trace):
    line = hud.label_line(trace.labels, "20261010T1358Z-celestrak")
    assert line == ("Positions REAL (snapshot 20261010T1358Z-celestrak, SGP4) | ISLs MODELLED (Grid-4) | "
                    "Queues MODELLED")
    # never assumed: a synthetic Walker run's positions are MODELLED, a missing label says so
    walker = {"synthetic_walker_constellation": "MODELLED", "isl_topology_grid4": "MODELLED",
              "link_rate_and_queues": "MODELLED"}
    assert hud.label_line(walker, "synthetic-walker-C1") == (
        "Positions MODELLED (synthetic Walker preset synthetic-walker-C1, SGP4) | ISLs MODELLED (Grid-4) | "
        "Queues MODELLED")
    assert hud.label_line({}, None) == ("Positions NOT LABELLED (SGP4) | ISLs NOT LABELLED (Grid-4) | "
                                        "Queues NOT LABELLED")


def test_bundle_positions_are_not_shown_as_direct_sgp4(trace):
    """An ns-3 trace drawn from the bundle's 1 s positions.csv + a spline says so (minor finding:
    it used to read like a direct SGP4 evaluation); outside the window it says SGP4 is direct."""
    from types import SimpleNamespace
    bp = sources.BundlePositions.__new__(sources.BundlePositions)
    bp.step_ms, bp.clamped = 1000, False
    note = hud.positions_note(SimpleNamespace(last_source=bp, primary=bp))
    assert note == "SGP4 samples at 1 s from the bundle, interpolated"
    assert hud.label_line(trace.labels, "S", note).startswith(
        "Positions REAL (snapshot S, SGP4 samples at 1 s from the bundle, interpolated) |")
    bp.clamped = True
    assert hud.positions_note(SimpleNamespace(last_source=bp, primary=bp)).endswith("HELD outside the bundle window")
    direct = hud.positions_note(SimpleNamespace(last_source=object(), primary=bp))
    assert direct == "SGP4 evaluated directly (outside the bundle's sample window)"
    assert hud.positions_note(SimpleNamespace(last_source=None, primary=object())) == "SGP4"


CAPS_GPU = """OpenGL vendor string:  Microsoft Corporation
OpenGL renderer string:  D3D12 (Intel(R) Iris(R) Xe Graphics)
OpenGL version string:  4.1 (Core Profile) Mesa 26.0.8-1ubuntu0.3
"""
CAPS_SW = """OpenGL vendor string:  Mesa
OpenGL renderer string:  llvmpipe (LLVM 21.1.8, 256 bits)
OpenGL version string:  4.5 (Core Profile) Mesa 26.0.8-1ubuntu0.3
"""


def test_renderer_line_never_hides_a_software_fallback():
    assert hud.renderer_line(CAPS_GPU) == "renderer: D3D12 (Intel(R) Iris(R) Xe Graphics), OpenGL 4.1"
    assert hud.renderer_line(CAPS_SW) == "renderer: llvmpipe (LLVM 21.1.8, 256 bits) (software), OpenGL 4.5"
    assert hud.renderer_info(CAPS_SW)[2] is True and hud.renderer_info(CAPS_GPU)[2] is False
    assert hud.renderer_line("").startswith("renderer: unknown")


def test_hop_table_values(trace):
    tr = trace.packets[0]
    rows = hud.hop_rows(trace, tr)
    assert rows[0][1] == "header" and "deadline" in rows[0][0] and "margin" in rows[0][0]
    assert rows[1][1] == "send" and trace.nodes[tr.send.node].name in rows[1][0]
    hops = [e for e in tr.events if e.ev == "hop"]
    body = rows[2:]
    assert len(body) == len(hops)
    epoch = -(-(T0_GPS + tr.send.t) // timebase.unit_ns(UNIT))     # Epoch_Base, not wrapped
    for (text, status), e in zip(body, hops):
        n = trace.nodes[e.node]
        assert f" {n.sid} " in text and n.name[:16] in text
        arrival_ms = (e.t - tr.send.t) / 1e6
        assert f"{arrival_ms:+.3f} ms" in text
        if e.deadline_u is None:                   # a transit node of the fallback detour
            assert status == "ok" and " - " in text
            continue
        margin_u = timebase.serial_diff(e.deadline_u, e.now_u)
        assert f"{margin_u * U_MS:+.1f} ms" in text
        # deadline instant = end of unit D_k, relative to the send time
        d_rel = ((epoch + timebase.serial_diff(e.deadline_u, epoch % 2 ** 32) + 1)
                 * timebase.unit_ns(UNIT) - (T0_GPS + tr.send.t)) / 1e6
        assert f"{d_rel:+.1f} ms" in text
        late = margin_u < 0
        assert (status in ("late", "fallback")) == late         # fallback = late here, then greedy
        assert late == (e.t - tr.send.t > d_rel * 1e6 - 1e3)      # arrival after the deadline <=> late
        if e.node == C:
            assert status == "fallback" and "LATE: DEV set" in text and "FALLBACK" in text
    # a packet part-way: only the reached hops, then "... n more hops"
    reached = tr.events[:3]
    part = hud.hop_rows(trace, tr, reached)
    assert part[-1][1] == "pending" and "more hop" in part[-1][0]


def test_header_hex_highlights_segments_left_and_flags(trace):
    e = trace.packets[0].events[2]                 # arrival at hop 2 (B)
    assert e.ev == "hop" and e.hex
    parts, more = hud.header_hex_parts(e.hex)
    raw = bytes.fromhex(e.hex)
    assert [role for _t, role in parts] == ["plain", "sl", "plain", "flags", "plain"]
    assert parts[1][0] == f"{raw[3]:02x}" == f"{e.sl:02x}"
    assert parts[3][0] == f"{raw[4]:02x}" == f"{e.flags:02x}"
    # the parts and the entry lines rebuild exactly the trace's bytes (the HUD hex = the trace hex)
    shown = "".join(t for t, _r in parts) + "".join(more)
    assert shown.replace(" ", "").replace("|", "") == e.hex
    lines = hud.header_lines(e)
    assert lines[0].startswith("T-CRH  ") and f"[{raw[3]:02x}] [{raw[4]:02x}]" in lines[0]
    hdr = proto.TcrhHeader.decode(raw)
    assert f"SL={hdr.segments_left} (byte 3)" in lines[-1] and "as it arrived" in lines[-1]
    assert f"Epoch_Base={hdr.epoch_base}" in lines[-1] and "DEV=0" in lines[-1]


def test_header_context_reports_dev_set_at_the_late_node(trace):
    tr = trace.packets[0]
    i = next(k for k, e in enumerate(tr.events) if e.ev == "late")
    ev, late = hud.header_context(tr.events[:i + 1])
    assert ev.ev == "hop" and ev.node == C and late is not None and late.node == C
    line = hud.header_lines(ev, late)[-1]
    assert "DEV=0" in line and f"leaves with Flags=0x{late.flags:02x}" in line
    assert late.flags & proto.FLAG_DEV
    # bytes not sampled: SL / Flags from the event, and it says so
    no_hex = ev._replace(hex=None)
    assert "not sampled" in hud.header_lines(no_hex)[0]


def test_event_messages(trace):
    tr = trace.packets[0]
    late = tr.late_events[0]
    by_u = -timebase.serial_diff(late.deadline_u, late.now_u)
    msg = hud.event_message(trace, tr, late)
    n = trace.nodes[C]
    assert msg == (f"MISS by {by_u * U_MS:.1f} ms (now_u - D = {by_u} units) at {n.name} "
                   f"(SID {n.sid}, hop 3): DEV set")
    fb = hud.event_message(trace, tr, tr.fallback_events[0])
    assert fb.startswith(f"FALLBACK at {n.name}") and "(late)" in fb
    end = hud.event_message(trace, tr, tr.outcome)
    assert end.startswith(f"delivered to London in {tr.latency_ns / 1e6:.3f} ms") and "DEV=1" in end
    ok = trace.packets[1]
    assert hud.event_message(trace, ok, ok.outcome) == f"delivered to London in {ok.latency_ns / 1e6:.3f} ms"


def test_clock_lines(trace):
    p = pl.Player(T0_UNIX + 1_500_000_000, orbit_speed=60)
    orbit, packet = hud.clock_lines(p, T0_UNIX)
    assert orbit == "Orbit clock  2026-10-10 14:00:01.500 UTC  running x60"
    assert packet == "Packet clock  (no packet)  slow motion x100"
    tr = trace.packets[0]
    positions, _snap = sources.positions_for_trace(trace)
    pos = positions.ecef_km(T0_UNIX + tr.t_start)
    p.slowmo = 1000.0
    p.play(tr, T0_UNIX, lambda n: pos[n])
    orbit, packet = hud.clock_lines(p, T0_UNIX)
    assert "frozen while a packet is shown" in orbit and "14:00:00.001 UTC" in orbit
    assert packet.startswith(f"Packet clock  t0 + {tr.t_start / 1e9:.6f} s")
    # move into the long wait before the slowed link: fast-forward is announced with its real length
    for _ in range(10_000):
        if p.walk.current.kind == "wait" and p.walk.current.node_a == B:
            break
        p.advance(0.01)
    else:
        pytest.fail("the packet never waited at B")
    orbit, packet = hud.clock_lines(p, T0_UNIX)
    seg = p.walk.current
    assert "FAST-FORWARD" in packet and f"{(seg.t_b - seg.t_a) / 1e6:,.1f} ms" in packet


def test_pick_panel_shows_elements_and_epoch_age():
    from test_viz_sources import snapshot_fleet
    snap = snapshot_fleet()
    el = snap.elements(66165)
    lines = hud.pick_lines(el.name, 66165, 8223, el, T0_UNIX, 10.0, 20.0, 463.2)
    assert lines[0] == f"{el.name}  NORAD 66165  SID 8223"
    age_h = (T0_UNIX - el.epoch_ns) / 3.6e12
    assert f"age {age_h:+.2f} h at the orbit clock" in lines[1] and el.epoch in lines[1]
    assert "CelesTrak SupGP" in lines[1]
    assert f"i {el.inclination_deg:.4f} deg" in lines[2] and f"e {el.eccentricity:.7f}" in lines[2]
    assert "alt 463.2 km" in lines[3]
    assert hud.pick_lines("X", 1, None, None, T0_UNIX)[1] == "elements: snapshot not loaded"


def test_fault_link_and_mode_lines(trace):
    f = trace.faults[0]
    text = hud.fault_text(trace, f)
    assert text.startswith("fault rate_cut (MODELLED, ground truth)") and "link stays UP" in text
    assert f"t0 + {f.start_ns / 1e9:g} s to {f.stop_ns / 1e9:g} s" in text     # never "a-b s"
    assert hud.link_line(trace, (B, C), 2) == (f"selected link: {trace.nodes[B].name} - "
                                               f"{trace.nodes[C].name} (hop 2)")
    assert "replay-only" in hud.mode_line(False) and "engine API not available" in hud.mode_line(False)
    assert hud.mode_line(True).startswith("live:") and "f with it failed" in hud.mode_line(True)
    why = "a ns-3 trace cannot be re-run by the Python engine"
    assert hud.mode_line(False, why).startswith(f"replay-only: {why}")
    assert "f fail link" in hud.KEYS_LINE and "d degrade link" in hud.KEYS_LINE
    assert hud.overlay_line(False) is None
    assert hud.overlay_line(True, True).endswith("the slowed link is still UP (green)")
    assert "space next packet" in hud.KEYS_LINE and "right-click satellite" in hud.KEYS_LINE


def test_old_format_rerun_shows_the_faults_of_its_parents(tmp_path):
    """An old-format re-run (run.json "rerun" with its own "fault" and its parent "of", no
    "live_faults" list) showed only its own fault, although its parents' faults are active in
    it too. They are recovered from the parent run.json files (fwd/rerun.py's history walk,
    read only); with a parent unavailable the HUD says that earlier faults may be missing."""
    import json
    original, parent = tmp_path / "original", tmp_path / "parent"
    original.mkdir()
    parent.mkdir()
    down = {"kind": "link_down", "link": [A, B], "start_s": "2", "stop_s": "4"}
    rate = {"kind": "rate_cut", "link": [B, C], "start_s": "2001/1000", "stop_s": "4", "factor": "0.0002"}
    (original / "run.json").write_text(json.dumps({"tool": "python-sim"}))
    (parent / "run.json").write_text(json.dumps({"tool": "python-sim", "rerun": {
        "of": str(original), "flow": 0, "kind": "down", "fault": down}}))
    run_dir = make_trace(tmp_path / "run")
    doc = json.loads((run_dir / "run.json").read_text())
    doc["rerun"] = {"of": str(parent), "flow": 0, "kind": "rate", "fault": rate}
    (run_dir / "run.json").write_text(json.dumps(doc))
    files = [original / "run.json", parent / "run.json", run_dir / "run.json"]
    before = [p.read_bytes() for p in files]
    tr = sources.load_trace(run_dir)
    assert hud.live_faults(tr) == [("down", down), ("rate", rate)]
    na, nb, nc = (tr.nodes[x].name for x in (A, B, C))
    assert hud.live_faults_text(tr) == (
        f"2 live faults in this run (all active; d / f add one more): {na} - {nb} failed from t0 + 2.000 s; "
        f"{nb} - {nc} degraded (rate cut) from t0 + 2.001 s")
    assert hud.live_faults_lines(tr) == ["LIVE FAULTS (2, all active; d/f add one)", f"1. {na} - {nb}",
                                         "   failed from t0 + 2.000 s", f"2. {nb} - {nc}",
                                         "   degraded (rate cut) from t0 + 2.001 s"]
    assert [p.read_bytes() for p in files] == before                       # read only
    # the parent has moved: only its own fault is known, and the HUD says so
    doc["rerun"]["of"] = str(tmp_path / "moved")
    (run_dir / "run.json").write_text(json.dumps(doc))
    lone = sources.load_trace(run_dir)
    assert hud.live_faults(lone) == [("rate", rate)]
    assert hud.live_faults_text(lone).startswith("1 live fault in this run")
    assert hud.live_faults_text(lone).endswith(f"({hud.INCOMPLETE_LIVE_NOTE})")
    assert hud.live_faults_lines(lone)[-1] == "  (old-format re-run: earlier live faults may be missing)"

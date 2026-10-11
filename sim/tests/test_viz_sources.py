"""
Viewer data sources (sim/chronoroute/viz/sources.py): reading chronoroute.trace/1
folders strictly, positions from the snapshot (SGP4) and from a bundle's samples,
and the laser links the viewer draws.

make_trace() below builds a small but REAL-data trace that the other viewer tests
reuse (test_viz_player / test_viz_hud / test_viz_globe import it):

  * 5 real Starlink satellites of the 53.2 deg / 463 km shell (NORAD ids from the
    pinned snapshot; four of them are consecutive slots of one plane and the fifth
    is a cross-plane neighbour, so the Grid-4 links between them are real pairs)
    and the cities Chennai and London;
  * positions: the pinned snapshot through SGP4 (run.json positions.source = snapshot,
    the python-sim engine's form: the path of the raw element file);
  * three packets whose header bytes are built and processed by the golden-tested
    reference (proto.build_header / ingress_send / process_at_node, policy greedy),
    with arrival times from the real distances (light time + 0.5 ms per hop):
      pkt 0  flow 0 Chennai->London, held 15 ms in the queue of the slowed link B-C,
             so it arrives LATE at C, which falls back (GREEDY) to E and on to London;
      pkt 1  flow 0, on time all the way;
      pkt 2  flow 1 London->Chennai, on time.
    Event conventions are the engine's (spec/trace-v1.md): a hop event carries the
    header as it arrived, late = after the check, fallback carries the new next hop.
"""

import functools
import gzip
import json
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from chronoroute import proto
from chronoroute.data import cities as cities_mod
from chronoroute.data.omm import parse_epoch_ns
from chronoroute.orbit import frames
from chronoroute.proto import timebase
from chronoroute.route import scheduler, sids as sids_mod
from chronoroute.viz import sources

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
T0_UTC = "2026-10-10T14:00:00Z"
T0_UNIX = parse_epoch_ns(T0_UTC[:-1])
T0_GPS = scheduler.utc_ns_to_gps_ns(T0_UNIX)
UNIT = 1
U_NS = timebase.unit_ns(UNIT)
PROC_NS = 500_000
SLACK = Fraction(3, 2)
C_KM_NS = 299_792.458e-9

# A, B, C, D: slots 13, 12, 11, 10 of plane 43; E: a cross-plane neighbour of C.
SATS = [(66173, "A"), (66148, "B"), (66165, "C"), (66146, "D"), (52848, "E")]
CHENNAI, LONDON = 5, 6
A, B, C, D, E = range(5)


@functools.lru_cache(maxsize=1)
def snapshot_fleet():
    return sources.SnapshotFleet(SNAPSHOT)


def node_table():
    reg = sids_mod.SidRegistry.load()
    fleet = snapshot_fleet()
    nodes = []
    for i, (norad, _tag) in enumerate(SATS):
        nodes.append({"node_id": i, "kind": "sat", "sid": reg.satellite_sid(norad), "norad": norad,
                      "name": fleet.by_norad[norad].name, "lat": None, "lon": None})
    for j, name in enumerate(("Chennai", "London")):
        city = cities_mod.city_by_name(name)
        nodes.append({"node_id": 5 + j, "kind": "gs", "sid": reg.ground_station_sid(name), "norad": None,
                      "name": name, "lat": city.lat_deg, "lon": city.lon_deg})
    return nodes


def positions_at(t_ns):
    """ECEF km of the 7 nodes at trace time t_ns (SGP4 for satellites)."""
    fleet = snapshot_fleet()
    arr = fleet.satellite_array([n for n, _ in SATS]).propagate([T0_UNIX + t_ns], geodetic=False)
    pos = np.zeros((7, 3))
    pos[:5] = arr.r_ecef[:, 0, :]
    for j, name in enumerate(("Chennai", "London")):
        city = cities_mod.city_by_name(name)
        pos[5 + j] = frames.geodetic_to_ecef(city.lat_deg, city.lon_deg, 0.0)
    return pos


def _ev(t, ev, pkt, flow, node, nxt=None, sl=None, flags=None, deadline_u=None, now_u=None,
        reason=None, hexs=None):
    return {"t": t, "ev": ev, "pkt": pkt, "flow": flow, "node": node, "next": nxt, "sl": sl,
            "flags": flags, "deadline_u": deadline_u, "now_u": now_u, "reason": reason, "hex": hexs}


def clock(t):
    return timebase.clock_u(T0_GPS + t, UNIT)


def walk_packet(pkt, flow, planned, send_t, nodes, *, queue_before=None, queue_ns=0, fallback_via=None):
    """Events of one packet along `planned` (node ids), engine conventions (module docstring)."""
    pos = positions_at(send_t)
    sid = {n["node_id"]: n["sid"] for n in nodes}
    node_of_sid = {v: k for k, v in sid.items()}
    light = [int(round(np.linalg.norm(pos[b] - pos[a]) / C_KM_NS)) for a, b in zip(planned, planned[1:])]
    pred = [d + PROC_NS for d in light]
    budgets, acc = [], 0
    for d in pred:
        acc += d
        budgets.append(SLACK * acc)
    hdr = proto.build_header([sid[n] for n in planned[1:]], budgets, T0_GPS + send_t, UNIT)
    raw, first = proto.ingress_send(hdr.encode())
    events = [_ev(send_t, "send", pkt, flow, planned[0], node_of_sid[first], raw[3], raw[4], None,
                  clock(send_t), None, raw.hex())]
    t = send_t
    route = list(planned)
    i = 0
    while True:
        a, b = route[i], route[i + 1]
        t += int(round(np.linalg.norm(pos[b] - pos[a]) / C_KM_NS)) + PROC_NS
        if queue_before is not None and (a, b) == queue_before:
            t += queue_ns
        now = clock(t)
        greedy = bool(raw[4] & proto.FLAG_GREEDY)
        if greedy and b != route[-1]:
            # transit node of a fallback detour: no spec-6 processing, fallback function only
            nxt = route[i + 2]
            events.append(_ev(t, "hop", pkt, flow, b, nxt, raw[3], raw[4], None, now, None, raw.hex()))
            i += 1
            continue
        res = proto.process_at_node(raw, now, "greedy")
        if res.action == "deliver":
            events.append(_ev(t, "hop", pkt, flow, b, None, raw[3], raw[4], res.deadline_u, now, None,
                              raw.hex()))
            if res.late:
                events.append(_ev(t, "late", pkt, flow, b, None, res.out_bytes[3], res.out_bytes[4],
                                  res.deadline_u, now, None, res.out_bytes.hex()))
            out = res.out_bytes
            events.append(_ev(t, "deliver", pkt, flow, b, None, out[3], out[4], res.deadline_u, now,
                              None, out.hex()))
            return events
        if res.action == "fallback":
            assert fallback_via is not None, "test scenario: a late packet needs a fallback route"
            events.append(_ev(t, "hop", pkt, flow, b, None, raw[3], raw[4], res.deadline_u, now, None,
                              raw.hex()))
            events.append(_ev(t, "late", pkt, flow, b, None, res.out_bytes[3], res.out_bytes[4],
                              res.deadline_u, now, None, res.out_bytes.hex()))
            raw = res.out_bytes
            route = route[:i + 2] + list(fallback_via)
            events.append(_ev(t, "fallback", pkt, flow, b, route[i + 2], raw[3], raw[4], None, None,
                              "late", raw.hex()))
            i += 1
            continue
        assert res.action == "forward" and not res.late, res
        nxt = node_of_sid[res.next_sid]
        events.append(_ev(t, "hop", pkt, flow, b, nxt, raw[3], raw[4], res.deadline_u, now, None,
                          raw.hex()))
        raw = res.out_bytes
        i += 1


FAULT = {"kind": "rate_cut", "link": [B, C], "node": None, "start_ns": 0, "stop_ns": 10_000_000_000,
         "params": {"factor": "1/10000", "link_state": "up"}}


def scenario_events(nodes):
    ev = []
    ev += walk_packet(0, 0, [CHENNAI, A, B, C, D, LONDON], 1_000_000, nodes, queue_before=(B, C),
                      queue_ns=15_000_000, fallback_via=[E, LONDON])
    ev += walk_packet(1, 0, [CHENNAI, A, B, C, D, LONDON], 11_000_000, nodes)
    ev += walk_packet(2, 1, [LONDON, D, C, B, A, CHENNAI], 2_000_000, nodes)
    return ev


def write_trace(folder, nodes, events, *, run_overrides=None, raw_lines=None):
    """A trace folder; events are sorted by (t, pkt) keeping each packet's order (stable sort)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    run = {"schema": "chronoroute.trace/1", "tool": "python-sim", "t0_utc": T0_UTC, "t0_gps_ns": T0_GPS,
           "unit_code": UNIT, "snapshot_id": SNAPSHOT.name, "bundle": None, "nodes": nodes,
           "positions": {"source": "snapshot",
                         "path": f"data/pinned/{SNAPSHOT.name}/starlink_supgp.json"},
           "faults": [FAULT],
           "labels": {"satellite_positions_sgp4": "REAL", "isl_topology_grid4": "MODELLED",
                      "link_rate_and_queues": "MODELLED", "fault_slow_link": "MODELLED"},
           "flows": [{"flow_id": 0, "src": "Chennai", "dst": "London"},
                     {"flow_id": 1, "src": "London", "dst": "Chennai"}]}
    run.update(run_overrides or {})
    (folder / "run.json").write_text(json.dumps(run, indent=1), encoding="utf-8")
    keys = ("t", "ev", "pkt", "flow", "node", "next", "sl", "flags", "deadline_u", "now_u", "reason", "hex")
    lines = raw_lines if raw_lines is not None else [
        json.dumps({k: e[k] for k in keys}, separators=(",", ":"))
        for e in sorted(events, key=lambda e: (e["t"], e["pkt"]))]
    with gzip.open(folder / "events.jsonl.gz", "wt", encoding="utf-8") as fh:
        for line in lines:
            fh.write(line + "\n")
    return folder


def make_trace(folder):
    nodes = node_table()
    return write_trace(folder, nodes, scenario_events(nodes))


@pytest.fixture(scope="module")
def trace_dir(tmp_path_factory):
    return make_trace(tmp_path_factory.mktemp("viz-trace") / "run")


# ----------------------------------------------------------------------- parsing

def test_load_trace_groups_packets_and_derives_paths(trace_dir):
    tr = sources.load_trace(trace_dir)
    assert tr.problems == []
    assert tr.tool == "python-sim" and tr.unit_code == UNIT and tr.t0_unix_ns == T0_UNIX
    assert sorted(tr.packets) == [0, 1, 2]
    p0, p1, p2 = tr.packets[0], tr.packets[1], tr.packets[2]
    assert p0.path == [CHENNAI, A, B, C, E, LONDON]          # fell back at C to E
    assert p1.path == [CHENNAI, A, B, C, D, LONDON]
    assert p2.path == [LONDON, D, C, B, A, CHENNAI]
    assert [e.node for e in p0.late_events] == [C]
    assert [(e.node, e.next, e.reason) for e in p0.fallback_events] == [(C, E, "late")]
    assert p0.is_late and not p1.is_late and not p2.is_late
    assert p0.latency_ns == p0.outcome.t - p0.send.t > 0
    assert p0.outcome.ev == "deliver" and p0.outcome.flags & proto.FLAG_DEV
    assert tr.flows() == [0, 1]
    assert tr.flow_label(0) == "Chennai -> London" and tr.flow_label(1) == "London -> Chennai"
    assert [p.pkt for p in tr.packets_of_flow(0)] == [0, 1]
    assert tr.faults[0].link == (B, C) and tr.faults[0].active(5) and not tr.faults[0].active(10 ** 10)
    # events are kept in file order, which is sorted by (t, pkt)
    keys = [(e.t, e.pkt) for e in tr.events]
    assert keys == sorted(keys)


def test_engine_reader_accepts_the_synthetic_trace(trace_dir):
    reader = pytest.importorskip("chronoroute.trace.reader")
    assert reader.validate_run(trace_dir) == []


def _rewrite(src, dst, *, run=None, lines_fn=None):
    """Copy a trace with run.json edits and/or an event-line transformation."""
    nodes = json.loads((src / "run.json").read_text())["nodes"]
    with gzip.open(src / "events.jsonl.gz", "rt") as fh:
        lines = [x.rstrip("\n") for x in fh]
    if lines_fn:
        lines = lines_fn(lines)
    return write_trace(dst, nodes, [], run_overrides=run, raw_lines=lines)


@pytest.mark.parametrize("what, run, lines_fn, message", [
    ("schema", {"schema": "chronoroute.trace/2"}, None, "schema"),
    ("gps", {"t0_gps_ns": T0_GPS + 1}, None, "GPS time"),
    ("tool", {"tool": "omnet"}, None, "tool"),
    ("unsorted", None, lambda ls: [ls[1], ls[0]] + ls[2:], "not sorted"),
    ("unknown node", None, lambda ls: [ls[0].replace('"node":5', '"node":99', 1)] + ls[1:], "node 99"),
    ("bad event", None, lambda ls: [ls[0].replace('"ev":"send"', '"ev":"teleport"', 1)] + ls[1:], "teleport"),
    ("bad hex", None, lambda ls: [ls[0].replace('"hex":"', '"hex":"zz', 1)] + ls[1:], "hex"),
    ("negative t", None, lambda ls: ['{"t":-5,"ev":"send","pkt":9,"flow":0,"node":5}'] + ls, "t must be"),
])
def test_load_trace_refuses_broken_traces(trace_dir, tmp_path, what, run, lines_fn, message):
    bad = _rewrite(trace_dir, tmp_path / what.replace(" ", "_"), run=run, lines_fn=lines_fn)
    with pytest.raises(sources.TraceFormatError, match=message):
        sources.load_trace(bad)


def test_soft_problems_are_reported_not_hidden(trace_dir, tmp_path):
    # Packet 2's second hop claims a node the previous hop did not send it to.
    def tamper(lines):
        out, done = [], False
        for x in lines:
            e = json.loads(x)
            if not done and e["pkt"] == 2 and e["ev"] == "hop" and e["node"] == C:
                x = x.replace(f'"node":{C}', f'"node":{E}', 1)
                done = True
            out.append(x)
        return out
    tr = sources.load_trace(_rewrite(trace_dir, tmp_path / "soft", lines_fn=tamper))
    assert any("packet 2" in p and "previous hop sent it to" in p for p in tr.problems)


def test_missing_files_are_explained(tmp_path):
    with pytest.raises(sources.TraceFormatError, match="run.json"):
        sources.load_trace(tmp_path)


# ----------------------------------------------------------------------- positions

def test_snapshot_positions_are_sgp4_at_the_exact_instant(trace_dir):
    tr = sources.load_trace(trace_dir)
    pos, snap = sources.positions_for_trace(tr)
    assert isinstance(pos.primary, sources.SnapshotPositions)
    assert snap.snapshot_id == SNAPSHOT.name and snap.source_name == "CelesTrak SupGP"
    t = 1_234_567_891
    got = pos.ecef_km(T0_UNIX + t)
    want = positions_at(t)
    assert np.array_equal(got, want)                        # same code path, same instant: identical
    # cities on the WGS84 ellipsoid at height 0
    lat, lon, h = frames.ecef_to_geodetic(got[CHENNAI])
    assert abs(h) < 1e-9 and abs(lat - tr.nodes[CHENNAI].lat) < 1e-9


def test_positions_path_selects_the_element_source(tmp_path):
    folder = sources.SnapshotFleet(SNAPSHOT / "starlink_gp.json")
    assert folder.source_name == "CelesTrak GP" and folder.pinned_folder == SNAPSHOT
    supgp = sources.SnapshotFleet(SNAPSHOT)
    assert supgp.source_name == "CelesTrak SupGP"


def test_nodes_without_norad_are_matched_by_name(trace_dir, tmp_path):
    nodes = node_table()
    for n in nodes[:5]:
        n["norad"] = None                     # what a synthetic Walker run writes today
    events = scenario_events(node_table())
    tr = sources.load_trace(write_trace(tmp_path / "noradless", nodes, events))
    pos, _snap = sources.positions_for_trace(tr)
    assert tr.sat_norad == {i: n for i, (n, _t) in enumerate(SATS)}
    assert np.array_equal(pos.ecef_km(T0_UNIX), positions_at(0))


@pytest.fixture(scope="module")
def small_bundle(tmp_path_factory):
    """The course-milestone small bundle, verified by sha256 (rebuilt from its recipe if missing)."""
    from chronoroute.trace import ns3_import
    run_dir = REPO / "results" / "course-milestone" / "c5-463-10s-small-seed1"
    try:
        return ns3_import.find_bundle(run_dir)
    except ns3_import.BundleMissing:
        return ns3_import.rebuild_bundle(run_dir, tmp_path_factory.mktemp("bundle") / "c5-463-10s-small")


def test_bundle_positions_interpolate_sgp4_to_centimetres(small_bundle):
    """positions.csv holds SGP4 every 1 s; the viewer's cubic Hermite in between must match SGP4."""
    import csv
    with open(small_bundle / "nodes.csv") as fh:
        sats = [(int(r["node_id"]), int(r["norad"])) for r in csv.DictReader(fh) if r["kind"] == "sat"]
    pick = sats[::97]                                         # 30 satellites spread over the shell
    bp = sources.BundlePositions(small_bundle / "positions.csv", [n for n, _ in pick], T0_UNIX)
    assert bp.step_ms == 1000 and bp.window_ns == (0, 10_000_000_000)
    fleet = snapshot_fleet().satellite_array([norad for _, norad in pick])
    # at the samples: the csv's millimetre rounding only
    for t_ms in (0, 3000, 10_000):
        exact = fleet.propagate([T0_UNIX + t_ms * 1_000_000], geodetic=False).r_ecef[:, 0, :]
        assert np.max(np.abs(bp.sat_ecef_km(T0_UNIX + t_ms * 1_000_000) - exact)) < 1e-6   # 1 mm
    # between samples (mid-points and quarter points)
    worst = 0.0
    for t_ns in (500_000_000, 1_250_000_000, 4_750_000_000, 8_500_000_000, 9_500_000_000):
        exact = fleet.propagate([T0_UNIX + t_ns], geodetic=False).r_ecef[:, 0, :]
        worst = max(worst, float(np.max(np.linalg.norm(bp.sat_ecef_km(T0_UNIX + t_ns) - exact, axis=1))))
    assert worst < 5e-5, f"interpolation error {worst * 1e6:.1f} mm"         # < 5 cm (measured 17 mm)
    assert not bp.clamped
    bp.sat_ecef_km(T0_UNIX + 11_000_000_000)
    assert bp.clamped                                                         # outside: held, flagged


def test_bundle_links_equal_grid4_recomputed_from_the_snapshot(small_bundle):
    """The two ways the viewer gets laser links agree: the bundle's isl.csv and Grid-4 at t0."""
    import csv
    with open(small_bundle / "nodes.csv") as fh:
        rows = [r for r in csv.DictReader(fh)]
    row_of_node = {int(r["node_id"]): i for i, r in enumerate(rows)}
    from_bundle = sources.isl_from_bundle(small_bundle, row_of_node)
    row_of_norad = {int(r["norad"]): i for i, r in enumerate(rows) if r["kind"] == "sat"}
    recomputed = sources.isl_from_snapshot(snapshot_fleet(), T0_UNIX, row_of_norad)
    assert len(from_bundle) == len(recomputed) == 5361
    pairs = lambda s: {(min(a, b), max(a, b), int(k)) for a, b, k in zip(s.a, s.b, s.kind)}
    assert pairs(from_bundle) == pairs(recomputed)
    assert "53.2deg-463km" in recomputed.source


def test_synthetic_trace_links_and_lite_selection(trace_dir):
    data = sources.load_viewer_data(trace_dir=trace_dir)
    pairs = {(min(a, b), max(a, b)) for a, b in zip(data.isl.a, data.isl.b)}
    assert pairs == {(A, B), (B, C), (C, D), (C, E)}          # the real Grid-4 pairs among the 5
    up = sources.isl_up(data.isl, data.positions.ecef_km(T0_UNIX))
    assert up.all()                                           # mid-latitudes: all four links up
    near = sources.links_near_path(data.isl, [A], depth=1)
    assert {(min(int(data.isl.a[i]), int(data.isl.b[i])), max(int(data.isl.a[i]), int(data.isl.b[i])))
            for i in near} == {(A, B)}
    assert len(sources.links_near_path(data.isl, [A], depth=3)) == 4
    assert data.cities[0][0] == "Chennai" and data.mode == "trace"


def test_snapshot_view_of_one_shell():
    data = sources.load_viewer_data(snapshot_dir=SNAPSHOT, shell="53.2deg-463km")
    assert data.n_sats == 2847 and len(data.isl) == 5361
    assert any("off-grid" in n for n in data.notes)
    assert data.start_utc_ns == snapshot_fleet().fleet.fetched_ns
    whole = sources.load_viewer_data(snapshot_dir=SNAPSHOT)
    assert whole.n_sats == snapshot_fleet().fleet.count > sources.LITE_THRESHOLD
    assert len(whole.isl) == 0 and "pass --shell" in whole.isl.source


def test_a_real_python_sim_run_with_a_fallback_plays(tmp_path):
    """Integration with the simulator v2 (`cr run`): its trace loads, the viewer's controller
    plays a packet that missed a deadline and fell back, and its path turns magenta."""
    config_mod = pytest.importorskip("chronoroute.fwd.config")
    command = pytest.importorskip("chronoroute.fwd.command")
    from chronoroute.viz import player as pl
    cfg_path = tmp_path / "run.yaml"
    cfg_path.write_text(
        "scenario: {kind: real, duration_s: 6, cities: [Chennai, London]}\n"
        "traffic: {flows: [{src: Chennai, dst: London}, {src: London, dst: Chennai}]}\n"
        "forwarding: {policy: greedy, fallback: greedy_pure}\n"
        "faults:\n"
        "- {kind: rate_cut, on_path: {flow: 0, position: middle}, factor: \"0.0002\", "
        "start_s: 2, stop_s: 4}\n"
        "output: {trace: full, sample_every: 10}\n")
    out = tmp_path / "run"
    command.run_config(config_mod.load_config(cfg_path, seed=1), out, write_manifest=False)
    data = sources.load_viewer_data(trace_dir=out)
    tr = data.trace
    assert tr.tool == "python-sim" and tr.problems == [] and len(data.isl) == 5361
    assert data.positions.primary.snapshot.source_name == "CelesTrak SupGP"
    late = [p for p in tr.packets.values() if p.is_late]
    assert late and all(p.fallback_events for p in late)          # policy greedy: late -> fallback
    ctl = pl.Controller(data, engine=None)
    ctl.key_degrade()                                               # replay-only: the recorded fault
    assert ctl.track.is_late and "replay-only" in ctl.message
    while ctl.player.state == pl.FLIGHT:
        ctl.update(1 / 30)
    kinds = [k for _a, _b, k in ctl.path_segments()]
    assert "fallback" in kinds and kinds[-1] == "fallback"
    assert ctl.message.startswith("MISS by") and "FALLBACK at" in ctl.message


def test_engine_hook_lookup():
    hook = sources.engine_api()
    assert hook is None or callable(hook)
    assert sources.ENGINE_HOOK == ("chronoroute.fwd.engine", "rerun_with_fault")

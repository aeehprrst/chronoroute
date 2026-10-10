"""
Regression tests for the protocol / forwarding bugs in the legacy simulator
(sim/legacy/header.py, scheduler.py, simulator.py).

Bug numbers refer to the P1 bug table in the planning documents:
   #1  the final arrival deadline was never checked
   #2  greedy mode + failed_links on unpruned graphs looped forever
   #4  SIDs forward-ordered, SL never decremented, forwarding ignored the bytes
   #5  CRH16_FIXED = 8 instead of 4
   #6  banker's rounding / 1 ms quantisation of the per-hop budgets
   #7  Epoch_Base came from the schedule epoch instead of the ingress
   #8  no wrap-safe deadline comparison
   #14 strict_drop_on_expiry was labelled DROPPED_NO_NEIGHBOUR
   #17 the header.py self-test claimed a 10-hop CRH-16 is "28" bytes

plus the common-random-numbers property the counterfactual detection metric
needs (critique must-fix #1), and the O(log n) schedule lookup.

Every bug test was run against the v0-semester code first and failed there
(see the report). The tests use small hand-made networkx graphs, NOT the
real constellation, so they do not depend on the geometry code that is
being fixed in parallel. Only the ground-station NAMES are borrowed from
constellation.GROUND_STATIONS, because they are what the SID plan uses.
"""

import contextlib
import math
import os
import random
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from fractions import Fraction

import networkx as nx
import pytest
from hypothesis import given, settings, strategies as st

LEGACY_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'legacy'))
if LEGACY_DIR not in sys.path:
    # the legacy scripts import each other by bare module name
    sys.path.insert(0, LEGACY_DIR)

import header as H             # noqa: E402
import scheduler as SCH        # noqa: E402
import simulator as SIM        # noqa: E402
from constellation import GROUND_STATIONS   # noqa: E402

from chronoroute import proto  # noqa: E402

SRC, DST = 'GS:Chennai', 'GS:London'
FLOW = (SRC, DST)
V0_GOLDEN_HEX = '1102fd0300030000000003e8000708000307000206000000'
MOD32 = 1 << 32


# ---------------------------------------------------------------- helpers

def make_graph(nodes, edges):
    """nodes: {name: (x, y, z) km}; edges: {(a, b): weight_ms}."""
    g = nx.Graph()
    for n, pos in nodes.items():
        g.add_node(n, pos=pos, kind='gs' if isinstance(n, str) else 'sat')
    for (a, b), w in edges.items():
        g.add_edge(a, b, weight=w)
    return g


# A straight chain: Chennai -> 0 -> 1 -> 2 -> London (4 hops, 4 SIDs).
LINE_NODES = {SRC: (0.0, 0.0, 0.0), 0: (1000.0, 0.0, 0.0), 1: (2000.0, 0.0, 0.0),
              2: (3000.0, 0.0, 0.0), DST: (4000.0, 0.0, 0.0)}
LINE_W = {(SRC, 0): 2.9, (0, 1): 4.7, (1, 2): 5.3, (2, DST): 3.1}


def line_graph(weights=None):
    return make_graph(LINE_NODES, weights or LINE_W)


# A ladder with two rows, so a packet can go around a broken top-row link:
#
#            0 --- 1 --- 2
#   SRC <    |     |     |    > DST
#            3 --- 4 --- 5
LADDER_NODES = {SRC: (0.0, 0.0, 0.0), DST: (4000.0, 0.0, 0.0),
                0: (1000.0, 1000.0, 0.0), 1: (2000.0, 1000.0, 0.0),
                2: (3000.0, 1000.0, 0.0), 3: (1000.0, -1000.0, 0.0),
                4: (2000.0, -1000.0, 0.0), 5: (3000.0, -1000.0, 0.0)}
LADDER_W = {(SRC, 0): 3.0, (0, 1): 3.2, (1, 2): 3.2, (2, DST): 3.0,
            (SRC, 3): 3.1, (3, 4): 3.3, (4, 5): 3.3, (5, DST): 3.1,
            (0, 3): 6.0, (1, 4): 6.0, (2, 5): 6.0}


def ladder_graph():
    return make_graph(LADDER_NODES, LADDER_W)


def gs_positions_for(graph):
    """
    One frame of ground-station positions in GROUND_STATIONS order. The v0
    simulator looked the destination up here; ground stations that are not
    in the synthetic graph get a far-away dummy position.
    """
    far = (0.0, 0.0, -1.0e5)
    names = [f"GS:{name}" for name, *_ in GROUND_STATIONS]
    return [graph.nodes[n]['pos'] if n in graph else far for n in names]


def scenario(graphs, duration_s, slack, interval_s=15, flow=FLOW):
    """
    times, graphs, sat_positions, gs_positions, schedules for a synthetic
    run. `graphs` is one graph (static network) or one graph per second.
    Schedules are built with build_schedule_entry, which has the same
    positional signature in v0 and now, so the bug tests also run on v0.
    """
    times = list(range(duration_s + 1))
    if isinstance(graphs, nx.Graph):
        graphs = [graphs] * len(times)
    gs_pos = [gs_positions_for(g) for g in graphs]
    sch = {}
    for i, t in enumerate(times):
        if t % interval_s == 0:
            e = SCH.build_schedule_entry(graphs[i], flow[0], flow[1], slack, t * 1000)
            sch[t] = {flow: e} if e is not None else {}
    return times, graphs, None, gs_pos, sch


def links_of(path):
    return {frozenset(p) for p in zip(path[:-1], path[1:])}


@contextlib.contextmanager
def time_limit(seconds):
    """Abort a call that runs too long (the v0 simulator looped forever)."""
    def _raise(signum, frame):
        raise TimeoutError(f"still running after {seconds} s")
    old = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


DELIVERED = (SIM.Outcome.ON_SCHEDULE, SIM.Outcome.VIA_FALLBACK)


# ---------------------------------------------------------------- bug #1

def test_bug1_final_deadline_is_checked_at_the_destination():
    # last link slowed 20x at S = 1.2: every packet arrives far too late.
    # v0 broke out of the loop at current == dst BEFORE the deadline check,
    # so all of them were reported ON_SCHEDULE.
    times, graphs, sp, gp, sch = scenario(line_graph(), 20, slack=1.2)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 100, 100,
                            degraded_links={frozenset({2, DST}): 20.0},
                            rng=random.Random(1))
    predicted = sum(LINE_W.values())
    # the final deadline is S x prediction plus at most one unit (1 ms) for
    # the rounded-up anchor and one for the rounded-up deltas
    final_deadline_ms = 1.2 * predicted + 2.0
    late = [r for r in res if r['latency_ms'] > final_deadline_ms]
    assert len(late) == 100                      # the slow link really bites
    labelled_on_schedule = [r for r in late if r['outcome'] == SIM.Outcome.ON_SCHEDULE]
    assert labelled_on_schedule == []


def test_bug1_late_at_destination_is_delivered_late_with_dev_hop_h():
    times, graphs, sp, gp, sch = scenario(line_graph(), 20, slack=1.2)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 20, 100,
                            degraded_links={frozenset({2, DST}): 20.0}, seed=1,
                            queueing_mean_ms=0.0)
    for r in res:
        assert r['outcome'] == SIM.Outcome.DELIVERED_LATE
        assert r['deviated'] and r['deviation_reason'] == 'deadline_missed'
        assert r['dev_hop'] == 4 and r['dev_node'] == DST     # k = h at the final endpoint
        assert r['path_taken'] == [SRC, 0, 1, 2, DST]          # it never left the plan
        out = proto.TcrhHeader.decode(r['header_out'])
        assert out.is_dev and out.dev_hop == 4 and out.segments_left == 0
    s = SIM.summarise(res)
    assert s['delivered'] == 20 and s['on_schedule'] == 0 and s['delivered_late'] == 20


def test_healthy_line_is_on_schedule():
    times, graphs, sp, gp, sch = scenario(line_graph(), 20, slack=1.2)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 50, 100, seed=3,
                            queueing_mean_ms=0.0)
    assert {r['outcome'] for r in res} == {SIM.Outcome.ON_SCHEDULE}
    assert not any(r['deviated'] for r in res)


# ---------------------------------------------------------------- bug #2

def test_bug2_failed_link_on_unpruned_graph_terminates():
    # v0: at node 1 the planned link 1-2 is failed -> greedy; greedy picked 2
    # again (it ignored failed_links), the forward failed, nothing advanced,
    # and the loop spun forever.
    times, graphs, sp, gp, sch = scenario(line_graph(), 20, slack=1.5)
    t0 = time.perf_counter()
    with time_limit(5.0):
        res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 50, 100,
                                failed_links={frozenset({1, 2})},
                                rng=random.Random(1))
    assert time.perf_counter() - t0 < 1.0
    assert len(res) == 50
    # the chain has no way around the broken link
    assert not any(r['outcome'] in DELIVERED for r in res)


def test_bug2_greedy_routes_around_failed_link_same_as_pruned_graph():
    healthy = ladder_graph()
    failed = {frozenset({1, 2})}
    pruned = healthy.copy()
    pruned.remove_edge(1, 2)
    # the schedule is computed on the healthy network (the planner does not
    # know about the failure)
    times, graphs, sp, gp, sch = scenario(healthy, 10, slack=3.0)
    with time_limit(5.0):
        unpruned_res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 20, 250,
                                         failed_links=failed, rng=random.Random(2))
    pruned_res = SIM.simulate_flow(times, [pruned] * len(times), sp, gp, sch, FLOW,
                                   20, 250, failed_links=failed, rng=random.Random(2))
    assert unpruned_res == pruned_res
    for r in unpruned_res:
        assert r['outcome'] == SIM.Outcome.VIA_FALLBACK
        assert r['deviation_reason'] == 'link_failed'
        assert r['path_taken'] == [SRC, 0, 1, 4, 5, DST]
        assert frozenset({1, 2}) not in links_of(r['path_taken'])


def test_bug2_no_progress_is_dropped_stuck(monkeypatch):
    # put the v0 greedy back (it ignores failed links): the loop must still
    # end, with the new DROPPED_STUCK outcome, instead of spinning
    original = SIM.greedy_next_hop

    def v0_greedy(graph, current, dst_pos, visited, failed_links=None):
        return original(graph, current, dst_pos, visited)

    monkeypatch.setattr(SIM, 'greedy_next_hop', v0_greedy)
    times, graphs, sp, gp, sch = scenario(ladder_graph(), 10, slack=3.0)
    t0 = time.perf_counter()
    with time_limit(5.0):
        res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 20, 250,
                                failed_links={frozenset({1, 2})}, seed=2)
    assert time.perf_counter() - t0 < 1.0
    assert {r['outcome'] for r in res} == {SIM.Outcome.DROPPED_STUCK}


def test_hop_limit_still_applies():
    times, graphs, sp, gp, sch = scenario(line_graph(), 5, slack=1.5)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 3, 100, seed=1, hop_limit=2)
    assert {r['outcome'] for r in res} == {SIM.Outcome.DROPPED_HOP_LIMIT}
    assert all(r['hops'] == 2 for r in res)


# ---------------------------------------------------------------- bug #4

def test_bug4_legacy_encode_reproduces_v0_golden_vector():
    raw = H.encode([2, 3, 7], [6, 7, 8], 1000, next_header=17)
    assert raw.hex() == V0_GOLDEN_HEX


def test_bug4_legacy_decode_reads_reverse_order_wire():
    d = H.decode(bytes.fromhex(V0_GOLDEN_HEX))
    assert d['sat_ids'] == [2, 3, 7]           # path order
    assert d['deltas_ms'] == [6, 7, 8]
    assert d['segments_left'] == 3 and d['num_hops'] == 3
    assert d['epoch_base_ms'] == 1000
    assert d['sids_wire'] == [7, 3, 2]         # SID[0] is the final endpoint
    assert d['deadlines_u'] == [1006, 1013, 1021]
    assert H.absolute_deadlines(1000, d['deltas_ms']) == [1000, 1006, 1013, 1021]


def test_bug4_forwarding_uses_only_the_header_bytes():
    # S = 3 so that no packet deviates and every one must follow the plan
    times, graphs, sp, gp, sch = scenario(ladder_graph(), 10, slack=3.0)
    before = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 20, 250,
                               rng=random.Random(3))
    # mutate every list in the schedule entries AFTER the headers were built:
    # the bottom row is still a valid route, so a simulator that followed
    # entry['path'] would now take it
    for entries in sch.values():
        e = entries[FLOW]
        e['path'][1:-1] = [3, 4, 5]
        e['per_hop_predicted_ms'][:] = [0.0] * len(e['per_hop_predicted_ms'])
        e['deltas_ms'][:] = [0.0] * len(e['deltas_ms'])
    after = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 20, 250,
                              rng=random.Random(3))
    assert after == before
    for r in after:
        assert r['path_taken'] == [SRC, 0, 1, 2, DST]
        hdr = proto.TcrhHeader.decode(r['header_in'])
        assert [SCH.sid_to_node(s) for s in hdr.sids_fwd] == r['path_taken'][1:]
        assert hdr.segments_left == hdr.num_hops == 4          # fresh at ingress
        assert proto.TcrhHeader.decode(r['header_out']).segments_left == 0


def test_bug4_sid_plan_round_trip():
    assert SCH.node_to_sid(0) == 0 and SCH.node_to_sid(479) == 479
    assert SCH.node_to_sid(SRC) == H.GS_SID_BASE + 0
    for g, (name, *_rest) in enumerate(GROUND_STATIONS):
        assert SCH.sid_to_node(SCH.node_to_sid(f"GS:{name}")) == f"GS:{name}"
    with pytest.raises(ValueError):
        SCH.node_to_sid(0xF000)               # would collide with the GS block
    with pytest.raises(KeyError):
        SCH.sid_to_node(0xFFFF)               # reserved, no FIB entry


# ---------------------------------------------------------------- bug #5

def test_bug5_crh16_fixed_part_is_four_bytes():
    assert H.CRH16_FIXED == 4
    assert [H.crh16_size(n) for n in (5, 10, 13)] == [16, 24, 32]


def test_legacy_size_functions_match_spec():
    assert [H.tcrh_size(n) for n in (1, 3, 5, 10, 13)] == [16, 24, 32, 48, 56]
    assert [H.srh_size(n) for n in (1, 10, 13)] == [24, 168, 216]
    assert H.tcrh_size_authenticated(10) == 88      # pad8(12 + 30 + 40)
    assert H.pad_to_8(13) == 16


# ---------------------------------------------------------------- bug #6

def test_bug6_no_hop_budget_below_prediction():
    # v0 used round() per hop: [2.5, 3.5, 2.4, 2.6] -> [2, 4, 2, 3], so the
    # first deadline (2 ms) was BELOW the 2.5 ms the hop needs
    budgets_ms = [2.5, 3.5, 2.4, 2.6]
    d = H.decode(H.encode([1, 2, 3, 4], budgets_ms, 0))
    cum_budget = Fraction(0)
    cum_encoded = 0
    for b, delta in zip(budgets_ms, d['deltas_ms']):
        cum_budget += Fraction(str(b))
        cum_encoded += delta
        assert cum_encoded >= cum_budget            # never below the budget
        assert cum_encoded - cum_budget < 1         # and within one unit


def test_bug6_unit_code_selects_the_deadline_unit():
    raw = H.encode([1, 2, 3, 4], [2.5, 3.5, 2.4, 2.6], 0, unit_code=1)
    d = H.decode(raw)
    assert d['unit_code'] == 1
    assert d['deltas'] == [25, 35, 24, 26]          # 0.1 ms units, exact
    assert d['deltas_ms'] == [2.5, 3.5, 2.4, 2.6]


def test_bug6_ceil_is_exact_for_float_noise():
    # hops of 0.1 ms and 0.2 ms reach the second node after exactly 0.3 ms
    # = 3 units of 0.1 ms, but the float sum is 0.30000000000000004 and a
    # float ceil(0.30000000000000004 / 0.1) would give 4
    assert math.ceil((0.1 + 0.2) / 0.1) == 4
    g = make_graph({SRC: (0.0, 0.0, 0.0), 0: (1.0, 0.0, 0.0), DST: (2.0, 0.0, 0.0)},
                   {(SRC, 0): 0.1, (0, DST): 0.2})
    e = SCH.build_schedule_entry(g, SRC, DST, 1.0, 0, unit_code=1)
    hdr = proto.TcrhHeader.decode(e['header_template'])
    assert hdr.deltas_fwd == (1, 2)
    e = SCH.build_schedule_entry(g, SRC, DST, 1.2, 0, unit_code=3)   # 0.125 ms units
    # 1.2 x 0.1 = 0.12 ms -> 0.96 units -> 1; 1.2 x 0.3 = 0.36 ms -> 2.88 -> 3
    assert proto.TcrhHeader.decode(e['header_template']).deltas_fwd == (1, 2)
    assert not hdr.is_sat


@settings(max_examples=60, deadline=None)
@given(weights=st.lists(st.floats(min_value=0.05, max_value=40.0,
                                  allow_nan=False, allow_infinity=False),
                        min_size=1, max_size=12),
       slack=st.sampled_from([1.0, 1.05, 1.1, 1.2, 1.25, 1.3, 1.5, 2.0]),
       unit_code=st.sampled_from([0, 1, 2, 3]))
def test_bug6_schedule_deadlines_never_below_prediction(weights, slack, unit_code):
    nodes = {SRC: (0.0, 0.0, 0.0), DST: (float(len(weights)), 0.0, 0.0)}
    chain = [SRC] + list(range(len(weights) - 1)) + [DST]
    for i, n in enumerate(chain[1:-1]):
        nodes[n] = (float(i + 1), 0.0, 0.0)
    g = make_graph(nodes, dict(zip(zip(chain[:-1], chain[1:]), weights)))
    e = SCH.build_schedule_entry(g, SRC, DST, slack, 0, unit_code=unit_code)
    hdr = proto.TcrhHeader.decode(e['header_template'])
    u = proto.UNIT_NS[unit_code]
    s = Fraction(str(slack))
    cum_pred_ns = 0
    for k, w in enumerate(weights, start=1):
        cum_pred_ns += proto.ms_to_ns(w)
        budget_ns = s * cum_pred_ns
        deadline_ns = hdr.deadline(k) * u          # Epoch_Base is 0 in the template
        if not hdr.is_sat:
            assert deadline_ns >= budget_ns >= cum_pred_ns
            assert deadline_ns - budget_ns < u     # rounding never accumulates
    assert e['delta_overflow'] == hdr.is_sat


# ---------------------------------------------------------------- bug #7

def test_bug7_epoch_base_is_stamped_per_packet_at_ingress():
    # schedule epoch 0, interval 15 s, packets at 0, 1, ..., 14 s on a
    # healthy static network with an exact budget (S = 1, no jitter): with
    # Epoch_Base taken from the schedule epoch, the packet sent 14 s later
    # would be 14 s late at its first hop
    times, graphs, sp, gp, sch = scenario(line_graph(), 16, slack=1.0)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 15, 1000, seed=5,
                            queueing_mean_ms=0.0)
    assert [r['staleness_s'] for r in res] == list(range(15))
    for r in res:
        assert r['outcome'] == SIM.Outcome.ON_SCHEDULE
        assert not r['deviated']
        hdr = proto.TcrhHeader.decode(r['header_in'])
        t_ingress = SIM.T0_GPS_NS + r['pid'] * 1_000_000_000
        assert hdr.epoch_base == proto.epoch_base_at_ingress(t_ingress, 0)


@pytest.mark.parametrize('unit_code', [0, 1, 2, 3])
def test_bug7_exact_budget_is_never_late_for_any_unit(unit_code):
    times, graphs, sp, gp, _ = scenario(line_graph(), 16, slack=1.0)
    sch = SCH.generate_schedules(times, None, None, [FLOW], slack_factor=1.0,
                                 graphs=graphs, unit_code=unit_code)
    # 333 ms is not a whole number of 0.25 ms / 0.125 ms units after the
    # 2026 anchor, so the ceil'd anchor is exercised too
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 45, 333, seed=5,
                            queueing_mean_ms=0.0)
    assert {r['outcome'] for r in res} == {SIM.Outcome.ON_SCHEDULE}
    assert {proto.TcrhHeader.decode(r['header_in']).unit_code for r in res} == {unit_code}


def test_bug7_gps_time_base_is_the_constellation_epoch():
    import constellation as C
    epoch = datetime(C.EPOCH_YEAR, C.EPOCH_MONTH, C.EPOCH_DAY, tzinfo=timezone.utc)
    assert SIM.SIM_EPOCH_UTC == epoch
    assert SIM.T0_GPS_NS == proto.utc_to_gps_ns(epoch)


# ---------------------------------------------------------------- bug #8

def test_bug8_legacy_header_exposes_wrap_safe_compare():
    assert H.is_late(2, MOD32 - 3)                 # clock wrapped past the deadline
    assert not H.is_late(MOD32 - 1, 3)             # deadline wrapped, clock not yet
    assert H.serial_diff(1, MOD32 - 1) == 2


@pytest.mark.parametrize('unit_code, units_before_wrap', [(0, 3), (1, 30)])
def test_bug8_deadlines_across_the_2_32_boundary(unit_code, units_before_wrap):
    # The case that needs serial arithmetic: at the first hop the DEADLINE
    # has wrapped past 2^32 but the CLOCK has not yet. (If both have wrapped,
    # a plain comparison happens to give the right answer, which is why the
    # 0.1 ms case used to pass even with a non-wrapping compare.)
    # Hop 1 takes 2.9 ms and its budget at S = 1.2 is 3.48 ms, i.e.
    #   1 ms units:   clock + 2 units, deadline + 4 units -> start 3 before the wrap
    #   0.1 ms units: clock + 29,      deadline + 35      -> start 30 before the wrap
    u = proto.UNIT_NS[unit_code]
    # a 2026-sized GPS time whose unit count is a few units before a 2^32 wrap
    t0_gps_ns = (342 * MOD32 + MOD32 - units_before_wrap) * u
    times, graphs, sp, gp, _ = scenario(line_graph(), 2, slack=1.2)
    sch = SCH.generate_schedules(times, None, None, [FLOW], slack_factor=1.2,
                                 graphs=graphs, unit_code=unit_code)
    healthy = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 1, 100, seed=1,
                                t0_gps_ns=t0_gps_ns, queueing_mean_ms=0.0)
    r = healthy[0]
    hdr = proto.TcrhHeader.decode(r['header_in'])
    assert hdr.epoch_base == MOD32 - units_before_wrap
    assert hdr.deadlines()[-1] < hdr.epoch_base       # the deadlines really wrap
    # the scenario really is "deadline wrapped, clock not yet" at hop 1
    d1 = hdr.deadline(1)
    clock1 = proto.clock_u(t0_gps_ns + r['arrival_ns'][1], unit_code)
    assert d1 < units_before_wrap + 10 and clock1 > MOD32 - units_before_wrap
    assert clock1 > d1                                  # a plain compare says "late"
    assert not proto.is_late(clock1, d1)                # serial arithmetic: on time
    assert r['outcome'] == SIM.Outcome.ON_SCHEDULE and not r['deviated']

    # the same packet with the second link 20x slower is caught at node 1
    slow = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 1, 100, seed=1,
                             t0_gps_ns=t0_gps_ns, queueing_mean_ms=0.0,
                             degraded_links={frozenset({0, 1}): 20.0})
    assert slow[0]['deviated'] and slow[0]['dev_hop'] == 2
    assert slow[0]['deviation_reason'] == 'deadline_missed'


# ---------------------------------------------------------------- bug #14

def test_bug14_strict_drop_has_its_own_outcome():
    times, graphs, sp, gp, sch = scenario(line_graph(), 20, slack=1.2)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 30, 100,
                            degraded_links={frozenset({0, 1}): 20.0},
                            strict_drop_on_expiry=True, rng=random.Random(1))
    assert {r['outcome'] for r in res} == {SIM.Outcome.DROPPED_DEADLINE_STRICT}


def test_disable_fallback_drops_a_late_packet():
    times, graphs, sp, gp, sch = scenario(line_graph(), 20, slack=1.2)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 10, 100,
                            degraded_links={frozenset({0, 1}): 20.0},
                            disable_fallback=True, seed=1)
    assert {r['outcome'] for r in res} == {SIM.Outcome.DROPPED_NO_FALLBACK}


def test_continue_policy_flags_and_keeps_following_the_sids():
    times, graphs, sp, gp, sch = scenario(line_graph(), 20, slack=1.2)
    res = SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 10, 100,
                            degraded_links={frozenset({0, 1}): 20.0},
                            deviation_policy='continue', seed=1, queueing_mean_ms=0.0)
    for r in res:
        assert r['outcome'] == SIM.Outcome.DELIVERED_LATE
        assert r['dev_hop'] == 2 and r['path_taken'] == [SRC, 0, 1, 2, DST]
    with pytest.raises(ValueError):
        SIM.simulate_flow(times, graphs, sp, gp, sch, FLOW, 1, 100,
                          deviation_policy='continue', strict_drop_on_expiry=True)


def test_first_link_down_falls_back_from_the_ingress():
    healthy = ladder_graph()
    broken = healthy.copy()
    broken.remove_edge(SRC, 0)
    times, _, sp, gp, sch = scenario(healthy, 10, slack=1.5)
    res = SIM.simulate_flow(times, [broken] * len(times), sp, gp, sch, FLOW, 5, 250, seed=4)
    for r in res:
        assert r['outcome'] == SIM.Outcome.VIA_FALLBACK
        assert r['deviation_reason'] == 'link_failed'
        assert r['dev_node'] == SRC and r['dev_hop'] == 0
        # spec 1.0.1, section 2 and section 6 step 7: DEV with Dev Hop 0 means
        # "the ingress found its first link down"; the bytes are exactly what
        # the reference link_down_fallback makes of the ingress packet
        out = proto.TcrhHeader.decode(r['header_out'])
        assert out.is_greedy and out.is_dev and out.dev_hop == 0 and out.segments_left == 0
        sent, _first = proto.ingress_send(r['header_in'])
        assert r['header_out'] == proto.link_down_fallback(sent).out_bytes


# ---------------------------------------------------------------- bug #17

def test_bug17_header_self_test_prints_correct_crh16_size():
    out = subprocess.run([sys.executable, '-B', 'header.py'], cwd=LEGACY_DIR,
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert 'says 28' not in out.stdout
    assert '10-hop CRH-16   = 24 bytes' in out.stdout


# ------------------------------------------------- common random numbers

def phased_graphs():
    """
    20 one-second graphs. For t < 10 the shortest path is the top chain
    SRC-0-1-2-DST, which crosses link {0, 1}. From t = 10 that link is gone
    and the path is SRC-3-4-DST, which never touches it. Node 5 is a dead
    end that greedy forwarding walks into from node 1 (it is the neighbour
    closest to DST), so a late packet at node 1 is dropped after fewer hops
    than an on-time one.
    """
    nodes = {SRC: (0.0, 0.0, 0.0), DST: (4000.0, 0.0, 0.0),
             0: (1000.0, 0.0, 0.0), 1: (2000.0, 0.0, 0.0),
             2: (3000.0, 1000.0, 0.0), 5: (3000.0, -100.0, 0.0),
             3: (1000.0, -3000.0, 0.0), 4: (3000.0, -3000.0, 0.0)}
    edges = {(SRC, 0): 3.0, (0, 1): 3.0, (1, 2): 3.0, (2, DST): 3.0, (1, 5): 3.0,
             (SRC, 3): 6.0, (3, 4): 6.0, (4, DST): 6.0}
    phase1 = make_graph(nodes, edges)
    phase2 = phase1.copy()
    phase2.remove_edge(0, 1)
    return [phase1] * 10 + [phase2] * 10


FAULTY_LINK = frozenset({0, 1})


def crn_run(**kw):
    times = list(range(20))
    graphs = phased_graphs()
    sch = SCH.generate_schedules(times, None, None, [FLOW], slack_factor=1.5,
                                 interval_s=10, graphs=graphs)
    return SIM.simulate_flow(times, graphs, None, [gs_positions_for(g) for g in graphs],
                             sch, FLOW, 100, 190, **kw)


def test_crn_no_fault_runs_are_identical():
    a = crn_run(seed=11)
    assert crn_run(seed=11) == a
    # a phantom fault (multiplier 1.0) is the null-fault control: identical
    assert crn_run(seed=11, degraded_links={FAULTY_LINK: 1.0}) == a
    assert SIM.attributed_deviations(a, crn_run(seed=11, degraded_links={FAULTY_LINK: 1.0})) == []
    # the old rng= argument still works and is just as reproducible
    assert crn_run(rng=random.Random(1)) == crn_run(rng=random.Random(1))
    assert crn_run(seed=12) != a
    with pytest.raises(ValueError):
        crn_run(seed=1, rng=random.Random(1))


def test_crn_only_packets_crossing_the_faulty_link_can_differ():
    base = crn_run(seed=11)
    faulty = crn_run(seed=11, degraded_links={FAULTY_LINK: 20.0})
    assert [r['pid'] for r in base] == [r['pid'] for r in faulty]
    crossing = {r['pid'] for r in base if FAULTY_LINK in links_of(r['path_taken'])}
    differing = {b['pid'] for b, f in zip(base, faulty) if b != f}
    assert differing <= crossing
    assert differing                                   # the fault does something
    assert len(base) - len(crossing) >= 40             # and many packets avoid it
    # the faulty run drops some packets after FEWER hops; with one shared
    # rng stream that shifted every later packet's draws (the v0 design)
    assert any(f['hops'] < b['hops'] for b, f in zip(base, faulty))
    attributed = SIM.attributed_deviations(base, faulty)
    assert attributed and set(attributed) <= crossing


def test_crn_draws_do_not_depend_on_other_packets():
    full = crn_run(seed=3)
    times = list(range(20))
    graphs = phased_graphs()
    sch = SCH.generate_schedules(times, None, None, [FLOW], slack_factor=1.5,
                                 interval_s=10, graphs=graphs)
    short = SIM.simulate_flow(times, graphs, None, None, sch, FLOW, 30, 190, seed=3)
    assert short == full[:30]


def test_crn_uniform_is_keyed_and_in_range():
    u = SIM.crn_uniform(1, 2, 3)
    assert u == SIM.crn_uniform(1, 2, 3)
    assert 0.0 < u <= 1.0
    others = {SIM.crn_uniform(*k) for k in [(2, 2, 3), (1, 3, 3), (1, 2, 4), (1, 2, 3, 1)]}
    assert u not in others and len(others) == 4
    draws = [SIM.crn_uniform(9, p, h) for p in range(200) for h in range(10)]
    assert all(0.0 < x <= 1.0 for x in draws)
    assert abs(sum(draws) / len(draws) - 0.5) < 0.03


def test_records_have_the_pairing_fields():
    res = crn_run(seed=11, degraded_links={FAULTY_LINK: 20.0})
    for r in res:
        for key in ('pid', 'outcome', 'deviated', 'dev_hop', 'dev_node', 'path_taken',
                    'arrival_ns', 'send_ns', 'latency_ms', 'hops', 'header_in', 'header_out'):
            assert key in r
        assert len(r['arrival_ns']) == len(r['path_taken']) == r['hops'] + 1
        assert r['arrival_ns'][0] == r['send_ns']
        assert r['arrival_ns'] == sorted(r['arrival_ns'])
        assert r['latency_ms'] == (r['arrival_ns'][-1] - r['send_ns']) / 1e6


# ------------------------------------------------- schedule lookup

def _linear_schedule_for(schedules, t):
    valid = [e for e in schedules if e <= t]
    if not valid:
        return None, None
    return max(valid), schedules[max(valid)]


def test_schedule_for_matches_the_linear_scan():
    rnd = random.Random(4)
    epochs = sorted(rnd.sample(range(0, 5000), 300))
    table = SCH.ScheduleTable({e: {'epoch': e} for e in reversed(epochs)})
    plain = dict(table)
    for t in [-1, 0, 0.5, 4999, 5000, 10**6] + [rnd.uniform(0, 5000) for _ in range(500)]:
        assert SCH.schedule_for(table, t) == _linear_schedule_for(plain, t)
        assert SCH.schedule_for(plain, t) == _linear_schedule_for(plain, t)


def test_schedule_table_stays_sorted_after_mutation():
    table = SCH.ScheduleTable({0: 'a', 15: 'b'})
    assert SCH.schedule_for(table, 20) == (15, 'b')
    table[18] = 'c'
    assert SCH.schedule_for(table, 20) == (18, 'c')
    del table[18]
    table.update({19: 'd'})
    assert SCH.schedule_for(table, 20) == (19, 'd')
    table.pop(19)
    table.setdefault(17, 'e')
    assert SCH.schedule_for(table, 20) == (17, 'e')
    table.clear()
    assert SCH.schedule_for(table, 20) == (None, None)


def test_schedule_for_is_logarithmic():
    table = SCH.ScheduleTable({e: e for e in range(0, 2_000_000, 15)})
    t0 = time.perf_counter()
    for t in range(0, 2_000_000, 2000):
        SCH.schedule_for(table, t)
    # 1000 lookups in a 133k-epoch table; the O(n) scan takes seconds
    assert time.perf_counter() - t0 < 0.5


def test_generate_schedules_on_given_graphs():
    times, graphs, _, _, _ = scenario(line_graph(), 30, slack=1.3)
    sch = SCH.generate_schedules(times, None, None, [FLOW], slack_factor=1.3,
                                 graphs=graphs)
    assert isinstance(sch, SCH.ScheduleTable) and sorted(sch) == [0, 15, 30]
    e = sch[15][FLOW]
    assert e['path'] == [SRC, 0, 1, 2, DST] and e['num_hops'] == 4
    assert e['header_bytes'] == 24 and e['unit_code'] == 0
    assert proto.TcrhHeader.decode(e['header_template']).epoch_base == 0
    assert SCH.control_plane_bytes_tcrh(sch, 0) == 3 * 24


# ------------------------------------------------- legacy API kept

def test_legacy_names_still_exist():
    for name in ('encode', 'decode', 'absolute_deadlines', 'tcrh_size', 'crh16_size',
                 'srh_size', 'tcrh_size_authenticated', 'pad_to_8', 'MAX_DELTA_MS',
                 'GS_SID_BASE', 'FLAG_DEVIATION', 'FLAG_GREEDY_MODE', 'IPV6_BASE_HEADER'):
        assert hasattr(H, name), name
    assert (H.MAX_DELTA_MS, H.GS_SID_BASE, H.FLAG_DEVIATION, H.FLAG_GREEDY_MODE) == \
        (255, 0xF000, 0x01, 0x02)
    for name in ('generate_schedules', 'schedule_for', 'SCHEDULE_INTERVAL_S',
                 'control_plane_bytes_tcrh', 'control_plane_bytes_table_upload',
                 'build_schedule_entry', 'compute_path', 'node_to_sid'):
        assert hasattr(SCH, name), name
    for name in ('simulate_flow', 'summarise', 'Outcome', 'greedy_next_hop',
                 'QUEUEING_MEAN_MS', 'HOP_LIMIT'):
        assert hasattr(SIM, name), name


def test_legacy_encode_validates_and_sets_sat():
    with pytest.raises(ValueError):
        H.encode([1, 2], [3.0], 0)                  # one delta per hop
    with pytest.raises(ValueError):
        H.encode([1, 2], [3.0, -1.0], 0)            # a budget cannot be negative
    d = H.decode(H.encode([1, 2], [300.0, 2.0], 0))
    assert d['deltas_ms'] == [255, 47] and d['flags'] & H.FLAG_SAT
    d = H.decode(H.encode([1, 2], [3.0, 2.0], 0, flags=H.FLAG_DEVIATION))
    assert d['flags'] == H.FLAG_DEVIATION


def test_summarise_counts_late_deliveries_as_delivered():
    res = [{'pid': 0, 'outcome': SIM.Outcome.ON_SCHEDULE, 'latency_ms': 10.0, 'hops': 4, 'deviated': False},
           {'pid': 1, 'outcome': SIM.Outcome.DELIVERED_LATE, 'latency_ms': 30.0, 'hops': 4, 'deviated': True},
           {'pid': 2, 'outcome': SIM.Outcome.DROPPED_STUCK, 'latency_ms': 5.0, 'hops': 2, 'deviated': True}]
    s = SIM.summarise(res)
    assert s['delivered'] == 2 and s['on_schedule'] == 1 and s['delivered_late'] == 1
    assert s['mean_latency_ms'] == 20.0
    assert math.isclose(s['deviation_rate'], 2 / 3)
    assert s['outcomes'] == {'delivered_on_schedule': 1, 'delivered_late': 1, 'dropped_stuck': 1}

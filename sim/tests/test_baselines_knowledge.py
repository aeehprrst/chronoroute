"""The control-plane timing models in isolation: the hello/dead-interval detector against hand
computations, interval merging, and the link-state belief (per-node knowledge times, the OSPF
two-way check, settling) on a real C1 topology."""

import copy

import numpy as np
import pytest

from chronoroute.baselines import keyed, params
from chronoroute.baselines.engine import SchemeEngine
from chronoroute.baselines.knowledge import NEVER, hello_detections, merge_intervals
from chronoroute.fwd import config, scenario as sm

S = 1_000_000_000
MS = 1_000_000


def test_hello_detector_hand_cases():
    H, D, ph = 1 * S, 3 * S, 300 * MS
    # 5 s outage: hellos at 2.3 .. 6.3 lost, last heard 1.3 -> dead at 4.3, back at 7.3
    assert hello_detections([(2 * S, 7 * S)], ph, H, D) == [(4300 * MS, 7 * S, 7300 * MS)]
    # gap of exactly D (lost 2.3, 3.3; next 4.3): the hello at r + D arrives in time
    assert hello_detections([(2 * S, 3500 * MS)], ph, H, D) == []
    assert hello_detections([(2 * S, 4 * S)], ph, H, D) == []
    # one more lost hello (4.3) makes the gap 4 s > D
    assert hello_detections([(2 * S, 4400 * MS)], ph, H, D) == [(4300 * MS, 4400 * MS, 5300 * MS)]
    # an outage that loses no hello is invisible
    assert hello_detections([(2400 * MS, 3200 * MS)], ph, H, D) == []
    # two outages with no hello between them act as one
    assert hello_detections([(2 * S, 2500 * MS), (2600 * MS, 5 * S)], ph, H, D) == \
        [(4300 * MS, 5 * S, 5300 * MS)]
    # a hello sent exactly at the start of the outage is lost ([s, e))
    assert hello_detections([(2300 * MS, 2310 * MS)], ph, H, D) == []
    # BFD-like timers: 100 ms x 3
    assert hello_detections([(1 * S, 2 * S)], 50 * MS, 100 * MS, 300 * MS) == \
        [(950 * MS + 300 * MS, 2 * S, 2050 * MS)]


def test_merge_intervals():
    assert merge_intervals([(5, 7), (1, 3), (2, 4), (7, 8), (9, 9)]) == [(1, 4), (5, 8)]


def ls_engine(faults, scheme, forwarding=None):
    doc = {"seed": 11, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 10, "drain_s": 1,
                                    "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
           "traffic": {"flows": [{"src": "London", "dst": "New York"}], "rate_pps": 10},
           "faults": copy.deepcopy(faults), "output": {"trace": "none", "packets_csv": False}}
    if forwarding:
        doc["forwarding"] = forwarding
    sc = sm.build_scenario(config.normalise(doc))
    return sc, SchemeEngine(sc, params.normalise_scheme(scheme))


SILENT = {"name": "ls_h", "ls": {"fault_detection": "hello"}}


def believed_up(kn, node, t, a, b):
    k = kn.truth.step_of(t)
    g = kn._graph(kn.key(node, t, k))
    return any(u == a for u, _w in g.senders(b))


def test_link_state_knowledge_times_and_two_way_check():
    sc0, _ = ls_engine([], "ls_h")
    a, b = sc0.resolve_on_path({"flow": 0, "position": "middle"}, 1 * S, False)
    faults = [{"kind": "link_down", "link": [a, b], "start_s": 2, "stop_s": 6}]
    sc, eng = ls_engine(faults, SILENT)               # the hello detector (a silent failure)
    kn = eng.kn
    li = sc.topo.link_index[(a, b)]
    la, lb = int(sc.topo.link_a[li]), int(sc.topo.link_b[li])
    H, D, spf = 1 * S, 3 * S, 50 * MS
    ph = keyed.phases_ns(11, "ls_hello_phase", 2 * sc.topo.n_links, H)
    # end 0 (= link_a) hears link_b's hellos: direction index 2 li + 1
    td = {}
    for e, d_idx in ((0, 2 * li + 1), (1, 2 * li)):
        p = int(ph[d_idx])
        r = p + ((2 * S - 1 - p) // H) * H            # last hello before the onset
        td[e] = r + D
    t_first = min(td.values())
    kn.advance(t_first - 1)
    assert believed_up(kn, la, t_first - 1, la, lb) and believed_up(kn, lb, t_first - 1, la, lb)
    kn.advance(t_first + spf)
    first_end = 0 if td[0] <= td[1] else 1
    det_node = la if first_end == 0 else lb
    # the detecting end knows at td + SPF (its own LSA, no flooding), so it stops using the link
    assert not believed_up(kn, det_node, t_first + spf, la, lb)
    ch = [c for c in kn.pending if c.li == li]
    assert ch and ch[0].K[det_node] == td[first_end] + spf
    # every other node learns at td + flood time + SPF, never earlier
    assert all(x >= td[first_end] + spf for x in ch[0].K if x < NEVER)
    far = int(np.argmax([x if x < NEVER else -1 for x in ch[0].K]))
    assert believed_up(kn, far, t_first + spf, la, lb)          # the flood has not reached it yet
    # once everyone knows, the change settles into the shared state
    kn.advance(ch[0].kmax + 1)
    assert not kn.pending or all(c.li != li or c.kmax > ch[0].kmax + 1 for c in kn.pending)
    assert not believed_up(kn, far, ch[0].kmax + 1, la, lb)
    # recovery at 6 s: the link is used again only when BOTH ends list it (two-way check)
    kn.advance(9 * S)
    assert believed_up(kn, far, 9 * S, la, lb)
    ups = sorted(t for t, kind, *_ in kn.detections if kind == "adjacency_down")
    assert len(ups) == 2 and abs(ups[0] - (t_first + spf)) == 0


def test_carrier_detection_mode_is_immediate():
    sc0, _ = ls_engine([], "ls_h")
    a, b = sc0.resolve_on_path({"flow": 0, "position": "middle"}, 1 * S, False)
    faults = [{"kind": "link_down", "link": [a, b], "start_s": 2, "stop_s": 6}]
    for scheme in ({"name": "ls_h", "ls": {"fault_detection": "carrier"}}, "ls_h"):    # carrier = default
        sc, eng = ls_engine(faults, scheme)
        eng.kn.advance(3 * S)
        downs = [d for d in eng.kn.detections if d[1] == "adjacency_down"]
        assert len(downs) == 2 and all(d[0] == 2 * S + 50 * MS for d in downs)
        assert eng.failure_visibility()["like_for_like"] is True


def test_one_failure_visibility_model_for_every_scheme():
    """The carrier detection delay is the ENGINE's (forwarding.carrier_detect_ms): LS-H notices
    a failure exactly when ChronoRoute's step 7 and SNAP do; another LS value is refused."""
    sc0, _ = ls_engine([], "ls_h")
    a, b = sc0.resolve_on_path({"flow": 0, "position": "middle"}, 1 * S, False)
    faults = [{"kind": "link_down", "link": [a, b], "start_s": 2, "stop_s": 6}]
    fw = {"carrier_detect_ms": 20}
    sc, eng = ls_engine(faults, "ls_h", fw)
    assert eng.carrier_ns == 20 * MS and eng.kn.carrier == 20 * MS
    eng.kn.advance(3 * S)
    downs = [d for d in eng.kn.detections if d[1] == "adjacency_down"]
    assert downs and all(d[0] == 2 * S + 20 * MS + 50 * MS for d in downs)
    li = sc.topo.link_index[(a, b)]
    # the engine's own view (every local decision of every scheme) sees it at 2 s + 20 ms
    assert not eng.seen.link_is_down(li, a, b, 2 * S + 20 * MS - 1)
    assert eng.seen.link_is_down(li, a, b, 2 * S + 20 * MS) and eng.faults.link_is_down(li, a, b, 2 * S)
    try:
        ls_engine(faults, {"name": "ls_h", "ls": {"carrier_detect_ms": 5}}, fw)
        raise AssertionError("a different LS carrier delay must be refused")
    except ValueError as exc:
        assert "every scheme must notice" in str(exc)
    _sc, ok = ls_engine(faults, {"name": "ls_h", "ls": {"carrier_detect_ms": 20}}, fw)    # equal: fine
    silent = ls_engine(faults, SILENT, fw)[1].failure_visibility()
    assert silent["like_for_like"] is False and "NOT a like-for-like" in silent["note"]


@pytest.mark.parametrize("scheme", ["ls_h", {"name": "ls_h", "ls": {"fault_detection": "hello", "bfd": True}},
                                    {"name": "ls_d", "ls_d": {"window_s": 1}}])
def test_ls_shortcut_gives_every_node_its_own_answer(scheme):
    """The exact shortcut (LinkState._fast_tree: the step's shared tree when a node's own view
    provably gives the same next hop and distance) is checked against a full computation of
    the node's own view at EVERY decision it answers, on a churny C1 run (5 % of laser links
    failing, 0.3 s repairs) with a rate cut for LS-D's metrics."""
    doc = {"seed": 13, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 4, "drain_s": 1,
                                    "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
           "traffic": {"flows": [{"src": "London", "dst": "New York"}, {"src": "Tokyo", "dst": "Los Angeles"},
                                 {"src": "Chennai", "dst": "London"}], "rate_pps": 200},
           "faults": [{"kind": "link_renewal", "unavailability": 0.05, "mttr_s": 0.3}],
           "output": {"trace": "none", "packets_csv": False}}
    sc = sm.build_scenario(config.normalise(doc))
    a, b = sc.resolve_on_path({"flow": 0, "position": "middle"}, 1 * S, False)
    doc["faults"].append({"kind": "rate_cut", "link": [a, b], "factor": "0.0002", "start_s": 1, "stop_s": 3})
    sc = sm.build_scenario(config.normalise(doc))
    eng = SchemeEngine(sc, params.normalise_scheme(scheme))
    eng.kn.verify_fast = True                # raises on the first answer that differs
    s = eng.run()
    st = eng.kn.stats
    assert st["changes"] > 20 and st.get("fast_answers", 0) > 100, st
    assert s["conservation"]["ok"]


def test_min_ls_interval_batches_originations():
    sc, eng = ls_engine([], {"name": "ls_h", "ls": {"preset": "ospf"}})
    kn = eng.kn
    assert kn.minlsi == 5 * S
    assert kn._originate(7, 10 * S) == 10 * S              # first: at once
    assert kn._originate(7, 11 * S) == 15 * S              # within MinLSInterval: deferred
    assert kn._originate(7, 14 * S) == 15 * S              # joins the deferred LSA
    assert kn._originate(7, 21 * S) == 21 * S              # free again
    assert kn._originate(8, 11 * S) == 11 * S              # per router

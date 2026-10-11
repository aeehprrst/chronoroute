"""Fault models and their ground-truth log (fwd/faults.py)."""

from fractions import Fraction
from types import SimpleNamespace

import numpy as np
import pytest

from chronoroute.fwd import faults as F
from chronoroute.fwd.rng import KeyedStreams


def fake_topo(n_sats=6, links=((0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (0, 6))):
    a = np.array([x for x, _ in links])
    b = np.array([y for _, y in links])
    idx = {}
    for i, (x, y) in enumerate(links):
        idx[(x, y)] = idx[(y, x)] = i
    names = {f"S{i}": i for i in range(n_sats)}
    names["City"] = 6
    return SimpleNamespace(n_links=len(links), n_isl=len(links) - 1, n_sats=n_sats, n_nodes=n_sats + 1,
                           link_a=a, link_b=b, link_index=idx, node_by_name=lambda n: names[n])


def test_renewal_long_run_fraction_is_u_and_periods_have_the_means():
    rng = KeyedStreams(4)
    u, mttr, T = Fraction(1, 20), 2_000_000_000, 4000 * 10**9
    downs = []
    for e in range(40):
        downs += F.renewal_periods(rng, "link_fault", (0, e), 0, T, u, mttr)
    frac = sum(b - a for a, b in downs) / (40 * T)
    assert abs(frac - 0.05) < 0.006
    inner = [b - a for a, b in downs if a > 0 and b < T]
    assert abs(np.mean(inner) / mttr - 1) < 0.1
    for a, b in downs:
        assert 0 <= a < b <= T


def test_renewal_is_keyed_per_element():
    rng = KeyedStreams(4)
    x = F.renewal_periods(rng, "link_fault", (0, 3), 0, 10**12, Fraction(1, 10), 10**9)
    y = F.renewal_periods(KeyedStreams(4), "link_fault", (0, 3), 0, 10**12, Fraction(1, 10), 10**9)
    z = F.renewal_periods(KeyedStreams(4), "link_fault", (0, 4), 0, 10**12, Fraction(1, 10), 10**9)
    assert x == y and x != z


def test_build_faults_targets_and_log():
    topo = fake_topo()
    fs = F.build_faults([
        {"kind": "link_down", "link": [2, 1], "start_s": 1, "stop_s": 2},
        {"kind": "node_down", "node_name": "S4", "start_s": 0.5, "stop_s": 1.5},
        {"kind": "slow_processing", "node": 3, "delta_ns": 7, "start_s": 0, "stop_s": 9},
        {"kind": "slow_processing", "link_names": ["S0", "S1"], "delta_ns": 11, "start_s": 0, "stop_s": 9},
        {"kind": "rate_cut", "on_path": {"flow": 0}, "factor": "0.25", "start_s": 3, "stop_s": 4},
        {"kind": "arq", "link": [3, 4], "loss": 0.2, "start_s": 0, "stop_s": 1},
    ], topo=topo, rng=KeyedStreams(1), end_ns=10 * 10**9,
        resolve_on_path=lambda op, t, want_node: (4, 5))
    s = 10**9
    assert fs.link_is_down(1, 1, 2, int(1.5 * s)) and not fs.link_is_down(1, 1, 2, 2 * s)
    assert fs.link_is_down(3, 3, 4, s) and fs.node_is_down(4, s)        # node 4 down takes its links
    assert not fs.link_down_only(3, s)
    assert fs.extra_processing_ns(3, 5 * s) == 7 and fs.extra_processing_ns(2, 5 * s) == 0
    assert fs.extra_link_ns(0, 5 * s) == 11
    assert fs.rate_changes(4, 10**9) == [(3 * s, 250_000_000), (4 * s, 10**9)]
    assert fs.arq_params(3, s // 2) == (Fraction(1, 5), 3, 100_000) and fs.arq_params(3, 2 * s) is None
    kinds = [e["kind"] for e in fs.log]
    assert sorted(kinds) == sorted(["link_down", "node_down", "slow_processing", "slow_processing",
                                    "rate_cut", "arq"])
    for e in fs.log:
        assert set(e) == {"kind", "link", "node", "start_ns", "stop_ns", "params"}
        assert e["stop_ns"] > e["start_ns"]
        assert e["link"] is None or e["link"][0] < e["link"][1]
    assert [e["start_ns"] for e in fs.log] == sorted(e["start_ns"] for e in fs.log)


def test_a_fault_on_a_link_that_does_not_exist_is_an_error():
    with pytest.raises(ValueError):
        F.build_faults([{"kind": "link_down", "link": [0, 5], "start_s": 0, "stop_s": 1}],
                       topo=fake_topo(), rng=KeyedStreams(1), end_ns=10**9, resolve_on_path=None)


RENEW = {"kind": "link_renewal", "unavailability": "0.2", "mttr_s": "0.5"}
SLOW = {"kind": "slow_processing", "link": [1, 2], "delta_ns": 4_000_000, "start_s": 1, "stop_s": 3}
PHANTOM = {"kind": "slow_processing", "link": [1, 2], "delta_ns": 0, "start_s": 1, "stop_s": 3}


def renewal_log(cfgs):
    fs = F.build_faults(cfgs, topo=fake_topo(), rng=KeyedStreams(11), end_ns=60 * 10**9,
                        resolve_on_path=None)
    return [e for e in fs.log if e["params"].get("model") == "renewal"]


def test_removing_a_preceding_fault_keeps_the_renewal_periods():
    """The counterfactual twin is the run WITHOUT the scored fault. Removing a fault listed
    before a renewal entry must not redraw the renewal periods (blocker: they used to be
    keyed by list position)."""
    full = renewal_log([SLOW, RENEW])
    assert len(full) > 20                                   # plenty of periods to compare
    assert renewal_log([RENEW]) == full                     # twin: the fault removed
    assert renewal_log([PHANTOM, RENEW]) == full            # phantom twin
    assert renewal_log([RENEW, SLOW]) == full               # order does not matter either
    # written differently, same fault: same identity, same periods
    assert renewal_log([{"kind": "link_renewal", "unavailability": 0.2, "mttr_s": 0.5}]) == full
    # a different renewal process draws different periods
    assert renewal_log([dict(RENEW, mttr_s="0.6")]) != full


def test_identical_renewal_entries_are_independent_and_ids_are_stable():
    two = renewal_log([RENEW, RENEW])
    one = renewal_log([RENEW])
    ids = {e["params"]["fault_id"] for e in two}
    assert len(ids) == 2 and any(i.endswith("#1") for i in ids)
    first = [e for e in two if "#" not in e["params"]["fault_id"]]
    assert first == one                                     # the first copy keeps its periods
    second = [(e["link"], e["start_ns"]) for e in two if e["params"]["fault_id"].endswith("#1")]
    assert second and second != [(e["link"], e["start_ns"]) for e in one]
    fid = F.fault_ids([SLOW], 10**9)[0][0]
    assert fid == F.fault_ids([PHANTOM, SLOW], 10**9)[1][0] and len(fid) == 16


def test_detected_view_shifts_failures_only():
    fs = F.build_faults([{"kind": "link_down", "link": [1, 2], "start_s": 1, "stop_s": 2},
                         {"kind": "node_down", "node": 4, "start_s": 1, "stop_s": 1.01},
                         SLOW], topo=fake_topo(), rng=KeyedStreams(1), end_ns=10 * 10**9,
                        resolve_on_path=None)
    assert fs.detected_view(0) is fs
    v = fs.detected_view(50_000_000)                         # 50 ms to notice
    s = 10**9
    assert fs.link_is_down(1, 1, 2, s) and not v.link_is_down(1, 1, 2, s)
    assert not v.link_is_down(1, 1, 2, s + 49_999_999) and v.link_is_down(1, 1, 2, s + 50_000_000)
    assert not v.link_is_down(1, 1, 2, 2 * s)               # recovery seen at once
    assert fs.node_is_down(4, s) and not v.node_is_down(4, s + 5_000_000)   # 10 ms outage: never seen
    assert v.extra_link_ns(1, 2 * s) == 4_000_000 and v.log is fs.log
    with pytest.raises(ValueError):
        fs.detected_view(-1)


def test_intervals_merge():
    iv = F._Intervals()
    iv.add(10, 20)
    iv.add(15, 30)
    iv.add(40, 50)
    assert iv.starts == [10, 40] and iv.stops == [30, 50]
    assert iv.contains(10) and iv.contains(29) and not iv.contains(30) and not iv.contains(35)

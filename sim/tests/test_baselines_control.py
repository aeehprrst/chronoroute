"""Control-byte model: message sizes from the RFC packet layouts, and the analytic count of
flooded copies checked against a brute-force flood on a real (C1) topology (reviewer
must-fix #7: an analytic byte-count test instead of a cross-protocol calibration)."""

import copy
import heapq

import pytest

from chronoroute.baselines import control as ctl, params
from chronoroute.baselines.engine import SchemeEngine
from chronoroute.fwd import config, scenario as sm

FLOWS = [{"src": "London", "dst": "New York"}, {"src": "Chennai", "dst": "London"}]


def engine(faults=()):
    doc = {"seed": 5, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 2, "drain_s": 1,
                                   "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
           "traffic": {"flows": copy.deepcopy(FLOWS), "rate_pps": 10},
           "faults": list(faults), "output": {"trace": "none", "packets_csv": False}}
    sc = sm.build_scenario(config.normalise(doc))
    return SchemeEngine(sc, params.normalise_scheme("ls_h"))


def test_message_sizes_from_rfc_layouts():
    assert ctl.HELLO_BYTES == 40 + 16 + 24 == 80                    # IPv6 + OSPFv3 hdr + Hello, 1 nbr
    assert ctl.BFD_BYTES == 40 + 8 + 24 == 72                       # IPv6 + UDP + BFD mandatory section
    assert ctl.LSACK_BYTES == 40 + 16 + 20                          # one LSA header acknowledged
    assert ctl.router_lsu_bytes(0) == 40 + 16 + 4 + 20 + 4
    assert ctl.router_lsu_bytes(5) - ctl.router_lsu_bytes(4) == 16  # one link description
    assert ctl.te_lsu_bytes(False) == 40 + 16 + 4 + 20 + 4 + 8 + 8 + 8
    assert ctl.te_lsu_bytes(True) - ctl.te_lsu_bytes(False) == 4    # min/max sub-TLV is 12, delay 8
    assert ctl.STAMP_PROBE_BYTES == 2 * (40 + 8 + 44)


def test_flood_transmissions_formula():
    # a 4-cycle (E = 4, N = 4): 2E - (N - 1) = 5 copies
    assert ctl.flood_transmissions([2, 2, 2, 2]) == 5
    assert ctl.flood_transmissions([]) == 0
    assert ctl.flood_transmissions([3]) == 3


def test_ledger_counts_per_medium_and_refuses_nonsense():
    led = ctl.Ledger()
    led.add("isl", "hello", 160, 2)
    led.add("uplink", "snap_table_upload", 30)
    d = led.to_dict()
    assert d["by_medium"]["isl"] == {"messages": 2, "bytes": 160}
    assert d["total_bytes"] == 190 and led.total("uplink") == 30
    with pytest.raises(ValueError):
        led.add("radio", "x", 1)
    with pytest.raises(ValueError):
        led.add("isl", "x", -1)


def brute_flood(truth, k, seg, origin, extra=500_000):
    """Simulate one flood: Dijkstra order of first arrival; every relaying node (satellite or
    the origin) sends on all its up links except the one it first heard on."""
    m = truth.up_mask(k, seg)
    _up, prop = truth.geo(k)
    adj = {}
    for li in range(truth.L):
        if m[li]:
            a, b = int(truth.a[li]), int(truth.b[li])
            adj.setdefault(a, []).append((b, li))
            adj.setdefault(b, []).append((a, li))
    dist = {origin: 0}
    parent = {origin: None}
    heap = [(0, origin)]
    done = set()
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u != origin and u >= truth.n_sats:
            continue
        for v, li in adj.get(u, []):
            nd = d + int(prop[li]) + extra
            if v not in dist or nd < dist[v] or (nd == dist[v] and u < parent[v][0]):
                dist[v] = nd
                parent[v] = (u, li)
                heapq.heappush(heap, (nd, v))
    copies = {"isl": 0, "downlink": 0, "uplink": 0}
    for u in done:
        if u != origin and u >= truth.n_sats:
            continue
        pli = parent[u][1] if parent[u] else None
        for v, li in adj.get(u, []):
            if li == pli:
                continue
            if li < truth.n_isl:
                copies["isl"] += 1
            elif u < truth.n_sats:
                copies["downlink"] += 1
            else:
                copies["uplink"] += 1
    return copies


def test_flood_copies_match_brute_force_on_c1():
    eng = engine()
    tr = eng.truth
    for k in (0, 7, 19):
        for origin in list(range(0, tr.n_sats, 97)) + list(range(tr.n_sats, tr.n)):
            want = brute_flood(tr, k, 0, origin)
            got = tr.flood_copies(k, 0, origin)
            assert (got["isl"][0], got["downlink"][0], got["uplink"][0]) == \
                   (want["isl"], want["downlink"], want["uplink"]), (k, origin)
            # every received copy is acknowledged in the opposite direction
            assert got["isl"][1] == want["isl"]
            assert got["ack_uplink"] == want["downlink"] and got["ack_downlink"] == want["uplink"]


def test_flood_copies_respect_failed_links():
    eng0 = engine()
    tr0 = eng0.truth
    a, b = int(tr0.a[0]), int(tr0.b[0])
    eng = engine([{"kind": "link_down", "link": [a, b], "start_s": 0, "stop_s": 2}])
    tr = eng.truth
    seg = tr.seg(1)
    assert tr.fault_mask(seg)[0] and not tr0.fault_mask(0)[0]
    got = tr.flood_copies(3, seg, a)["isl"][0]
    full = tr0.flood_copies(3, 0, a)["isl"][0]
    assert got == full - 2                      # the dead link carries no copy in either direction
    assert got == brute_flood(tr, 3, seg, a)["isl"]

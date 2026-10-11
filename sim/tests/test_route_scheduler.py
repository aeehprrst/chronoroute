"""Tests for chronoroute.route.scheduler: path -> hop delays -> slack budgets -> T-CRH bytes."""

import math
from datetime import datetime, timezone
from fractions import Fraction
from functools import cache
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from chronoroute import proto
from chronoroute.data import cities, omm, snapshot
from chronoroute.route import dijkstra, scheduler, sids
from chronoroute.topo import geometry, graph, gsl

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
T0 = omm.parse_epoch_ns("2026-10-10T14:00:00")
CITIES = ("Chennai", "London", "New York", "Sydney")


@cache
def scenario():
    fleet = snapshot.load_pinned(PINNED, "supgp")
    reg = sids.SidRegistry.load()                     # committed registry, used read-only
    stations = [gsl.ground_station_from_city(cities.city_by_name(n), reg.ground_station_number(n))
                for n in CITIES]
    times = [T0 + k * 100_000_000 for k in range(3)]
    sc = graph.build_scenario(fleet, "53.2deg-463km", stations, times, registry=reg)
    assert not reg.changed                             # every satellite is already registered
    return sc


def test_exact_slack():
    assert scheduler.exact_slack("1.5") == Fraction(3, 2)
    assert scheduler.exact_slack(1.2) == Fraction(6, 5)          # via repr, not the binary float
    assert scheduler.exact_slack(2) == 2
    for bad in (0, "-1", True):
        with pytest.raises((ValueError, TypeError)):
            scheduler.exact_slack(bad)


def test_cumulative_budgets_are_exact():
    b = scheduler.cumulative_budgets([2_000_001, 5_000_000, 1_999_999], "1.5")
    assert b == [Fraction(6_000_003, 2), Fraction(21_000_003, 2), 13_500_000]
    assert all(isinstance(x, Fraction) for x in b)


@settings(max_examples=200, deadline=None)
@given(st.integers(0, 10**12), st.integers(1, 300_000))
def test_ceil_of_ceil_identity_used_by_the_bundle(num, den):
    """ceil(ceil(B)/u) == ceil(B/u): exporting ceil(B) as integer ns keeps the deltas."""
    b = Fraction(num, den)
    for u in proto.UNIT_NS.values():
        assert math.ceil(Fraction(scheduler.ceil_ns(b), u)) == math.ceil(b / u)


def test_utc_to_gps_matches_proto_and_is_integer_exact():
    dt = datetime(2026, 10, 10, 14, 0, 0, 123456, tzinfo=timezone.utc)
    utc_ns = omm.datetime_to_ns(dt)
    assert scheduler.utc_ns_to_gps_ns(utc_ns) == proto.utc_to_gps_ns(dt)
    assert scheduler.utc_ns_to_gps_ns(utc_ns + 789) == proto.utc_to_gps_ns(dt) + 789
    with pytest.raises(ValueError):
        scheduler.utc_ns_to_gps_ns(omm.parse_epoch_ns("2016-12-31T23:59:59"))


def test_plan_path_chennai_london():
    sc = scenario()
    src, dst = sc.gs_node(sc.gs_index("Chennai")), sc.gs_node(sc.gs_index("London"))
    e = scheduler.plan_path(sc, src, dst, 0)
    assert e.path[0] == src and e.path[-1] == dst
    assert all(n < sc.n_sats for n in e.path[1:-1])              # only satellites relay
    assert e.num_hops == len(e.path) - 1 == len(e.sids_fwd)
    assert e.sids_fwd[-1] == proto.ground_station_sid(sids.SidRegistry.load().ground_station_number("London"))
    assert all(0 < s <= 0xEFFF for s in e.sids_fwd[:-1])
    # SIDs are the registry's, keyed by NORAD id
    reg = sids.SidRegistry.load()
    assert list(e.sids_fwd[:-1]) == [reg.satellite_sid(int(sc.sat_norad[n])) for n in e.path[1:-1]]
    # hop delays are the edge weights: light time + 0.5 ms, and they sum to Dijkstra's cost
    csr = sc.graph.csr_at(0)
    assert list(e.hop_delays_ns) == [csr.edge_weight(u, v) for u, v in zip(e.path[:-1], e.path[1:])]
    assert e.predicted_total_ns == dijkstra.shortest_path(csr, src, dst)[0]
    assert all(p + geometry.PROCESSING_NS == d for p, d in zip(e.prop_ns, e.hop_delays_ns))
    # budgets: S x cumulative predicted delay, exact
    running = 0
    for d, b in zip(e.hop_delays_ns, e.budgets_ns):
        running += d
        assert b == Fraction(3, 2) * running


def test_template_and_packet_header_bytes():
    sc = scenario()
    e = scheduler.plan_path(sc, sc.gs_node(sc.gs_index("New York")), sc.gs_node(sc.gs_index("Sydney")), 1)
    hdr = proto.TcrhHeader.decode(e.template)
    assert hdr.epoch_base == 0 and hdr.segments_left == hdr.num_hops == e.num_hops
    assert hdr.sids_fwd == e.sids_fwd and hdr.unit_code == 1 and hdr.next_header == 17
    assert not hdr.is_sat
    # every encoded deadline offset is at least its budget (spec 5.1: never earlier unless SAT)
    u = proto.UNIT_NS[1]
    for d_k, b in zip(hdr.deadlines(), e.budgets_ns):
        assert d_k * u >= b and d_k * u - b < u                  # ceil: within one unit
    # a packet entering at t gets Epoch_Base = ceil(T_gps / u) mod 2^32 and the same deltas
    t = int(sc.times_ns[1]) + 12_345
    pkt = proto.TcrhHeader.decode(e.header_for_packet(t))
    assert pkt.epoch_base == proto.epoch_base_at_ingress(scheduler.utc_ns_to_gps_ns(t), 1)
    assert pkt.deltas_fwd == hdr.deltas_fwd and pkt.sids_fwd == hdr.sids_fwd


def test_unreachable_flow_returns_none():
    sc = scenario()
    # cut every link at step 2 on a copy of the graph
    g = sc.graph
    dead = graph.TimeVaryingGraph(n_nodes=g.n_nodes, transit=g.transit, times_ns=g.times_ns,
                                  link_a=g.link_a, link_b=g.link_b, link_kind=g.link_kind,
                                  up=np.zeros_like(g.up), prop_ns=g.prop_ns)
    assert scheduler.plan_path(sc, sc.gs_node(0), sc.gs_node(1), 2, csr=dead.csr_at(2)) is None
    with pytest.raises(ValueError):
        scheduler.plan_path(sc, sc.gs_node(0), sc.gs_node(0), 0)

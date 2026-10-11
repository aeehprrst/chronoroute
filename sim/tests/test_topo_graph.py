"""Tests for chronoroute.topo.graph: compact time-varying graph, CSR per step, scenario numbering."""

from functools import cache
from pathlib import Path

import networkx as nx
import numpy as np
import pytest

from chronoroute.data import cities, omm, snapshot
from chronoroute.route import dijkstra, sids
from chronoroute.topo import geometry, graph, gsl

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
T0 = omm.parse_epoch_ns("2026-10-10T14:00:00")
CITIES = ("Chennai", "London", "Tokyo", "Sydney", "New York")


@cache
def scenario():
    fleet = snapshot.load_pinned(PINNED, "supgp")
    reg = sids.SidRegistry.load()
    stations = [gsl.ground_station_from_city(cities.city_by_name(n), reg.ground_station_number(n))
                for n in CITIES]
    return graph.build_scenario(fleet, "53.2deg-463km", stations, [T0, T0 + 100_000_000], registry=reg)


def test_node_numbering_and_transit():
    sc = scenario()
    assert np.all(np.diff(sc.sat_norad) > 0)                     # satellites sorted by NORAD id
    assert sc.graph.n_nodes == sc.n_sats + len(CITIES)
    assert [sc.node_name(sc.gs_node(i)) for i in range(len(CITIES))] == list(CITIES)
    assert sc.graph.transit[:sc.n_sats].all() and not sc.graph.transit[sc.n_sats:].any()
    reg = sids.SidRegistry.load()
    assert sc.node_sid(0) == reg.satellite_sid(int(sc.sat_norad[0]))
    assert sc.node_sid(sc.gs_node(0)) == reg.ground_station_sid("Chennai")


def test_link_arrays_are_consistent():
    sc, g = scenario(), scenario().graph
    assert np.all(g.link_a < g.link_b)
    n_isl = len(sc.isl_a)
    assert np.all(g.link_kind[:n_isl] <= 1) and np.all(g.link_kind[n_isl:] == graph.KIND_GSL)
    assert np.all(g.link_b[n_isl:] >= sc.n_sats) and np.all(g.link_a[n_isl:] < sc.n_sats)
    assert np.array_equal(g.prop_ns[:n_isl], geometry.propagation_ns(sc.isl_dist_km))
    assert g.up.shape == g.prop_ns.shape == (len(g.link_a), 2)
    # ground-link candidates: every pair visible at some step, listed station by station
    assert np.all(sc.gsl_visible.any(axis=1))
    order = np.lexsort((sc.gsl_sat, sc.gsl_gs))
    assert np.array_equal(order, np.arange(len(order)))


def test_csr_is_symmetric_and_weights_are_prop_plus_processing():
    sc = scenario()
    csr = sc.graph.csr_at(1)
    up = sc.graph.up[:, 1]
    assert csr.n_edges == int(up.sum())
    for i in np.flatnonzero(up)[:500]:
        a, b = int(sc.graph.link_a[i]), int(sc.graph.link_b[i])
        w = int(sc.graph.prop_ns[i, 1]) + geometry.PROCESSING_NS
        assert csr.edge_weight(a, b) == csr.edge_weight(b, a) == w
    for u in range(0, csr.n_nodes, 97):                         # rows sorted by neighbour id
        nbr, _ = csr.neighbours(u)
        assert np.all(np.diff(nbr) > 0)


def test_dijkstra_cost_equals_networkx_on_the_real_graph():
    """Oracle: equal cost to the nanosecond for every city pair (ground stations never relay,
    so the oracle graph only keeps the two end stations' ground links)."""
    sc = scenario()
    csr = sc.graph.csr_at(0)
    full = csr.to_networkx()
    for i in range(len(CITIES)):
        for j in range(len(CITIES)):
            if i == j:
                continue
            src, dst = sc.gs_node(i), sc.gs_node(j)
            g = full.copy()
            g.remove_nodes_from([sc.gs_node(k) for k in range(len(CITIES)) if k not in (i, j)])
            cost, path = dijkstra.shortest_path(csr, src, dst)
            assert cost == nx.dijkstra_path_length(g, src, dst, weight="weight")
            assert isinstance(cost, int)
            assert all(sc.n_sats > n for n in path[1:-1])


def test_bad_times_are_refused():
    fleet = snapshot.load_pinned(PINNED, "supgp")
    with pytest.raises(ValueError):
        graph.build_scenario(fleet, "53.2deg-463km", [], [T0, T0], registry=sids.SidRegistry.load())

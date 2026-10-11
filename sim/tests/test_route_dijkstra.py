"""Tests for chronoroute.route.dijkstra: hand-written binary-heap Dijkstra, integer ns,
canonical lowest-id tie-break. networkx is only the cost oracle."""

import networkx as nx
import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from chronoroute.route import dijkstra
from chronoroute.topo.graph import csr_from_edges


def _graph(n, edges, transit=None):
    a = [e[0] for e in edges]
    b = [e[1] for e in edges]
    w = [e[2] for e in edges]
    return csr_from_edges(n, a, b, w, transit)


@st.composite
def random_graphs(draw):
    n = draw(st.integers(2, 14))
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    chosen = draw(st.lists(st.sampled_from(pairs), unique=True, max_size=len(pairs)))
    # small weight range on purpose: many exact ties
    edges = [(i, j, draw(st.integers(1, 4))) for i, j in chosen]
    src = draw(st.integers(0, n - 1))
    dst = draw(st.integers(0, n - 1).filter(lambda x: x != src))
    return n, edges, src, dst


def _canonical_pred_by_brute_force(n, edges, src, dist):
    """The documented rule: pred[v] = lowest u with dist[u] + w(u, v) == dist[v]."""
    pred = {}
    for v in range(n):
        if v == src or dist[v] is None:
            continue
        tight = [u for (x, y, w) in edges for (u, vv) in ((x, y), (y, x))
                 if vv == v and dist[u] is not None and dist[u] + w == dist[v]]
        pred[v] = min(tight)
    return pred


@settings(max_examples=300, deadline=None)
@given(random_graphs())
def test_cost_equals_networkx_and_pred_follows_the_rule(case):
    n, edges, src, dst = case
    csr = _graph(n, edges)
    sp = dijkstra.dijkstra(csr, src)                    # full run (no early stop)
    g = nx.Graph()
    g.add_nodes_from(range(n))
    g.add_weighted_edges_from(edges)
    lengths = nx.single_source_dijkstra_path_length(g, src)
    for v in range(n):
        assert sp.dist[v] == lengths.get(v)             # None <-> unreachable
    want = _canonical_pred_by_brute_force(n, edges, src, sp.dist)
    for v, u in want.items():
        assert sp.pred[v] == u
    # early stop gives the same path and cost for the target
    cost, path = dijkstra.shortest_path(csr, src, dst)
    assert cost == lengths.get(dst)
    if cost is not None:
        assert path == sp.path_to(dst)
        assert path[0] == src and path[-1] == dst
        assert sum(csr.edge_weight(u, v) for u, v in zip(path[:-1], path[1:])) == cost


def test_tie_break_prefers_lower_predecessor_id():
    # two equal-cost routes 0-1-3 and 0-2-3 (cost 2): pred[3] = 1
    csr = _graph(4, [(0, 2, 1), (2, 3, 1), (0, 1, 1), (1, 3, 1)])
    assert dijkstra.shortest_path(csr, 0, 3) == (2, [0, 1, 3])
    # reverse direction: 3 -> 0 also via the lower id
    assert dijkstra.shortest_path(csr, 3, 0) == (2, [3, 1, 0])


def test_ground_stations_do_not_relay():
    # 0 = source station, 4 = destination station, 2 = a third station sitting on a short cut
    edges = [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 4, 1), (1, 3, 10)]
    transit = np.array([False, True, False, True, False])
    csr = _graph(5, edges, transit)
    assert dijkstra.shortest_path(csr, 0, 4) == (12, [0, 1, 3, 4])
    # the non-relaying node itself is still reachable as a destination
    assert dijkstra.shortest_path(csr, 0, 2) == (2, [0, 1, 2])
    # and with everything allowed to relay the short cut is taken
    assert dijkstra.shortest_path(_graph(5, edges), 0, 4) == (4, [0, 1, 2, 3, 4])


def test_unreachable_and_bad_source():
    csr = _graph(4, [(0, 1, 5), (2, 3, 5)])
    assert dijkstra.shortest_path(csr, 0, 3) == (None, None)
    with pytest.raises(ValueError):
        dijkstra.dijkstra(csr, 9)


def test_weights_stay_exact_integers_at_ns_scale():
    # costs around 1e8 ns with differences of 1 ns: floats would also manage, but ints are exact by type
    csr = _graph(3, [(0, 1, 50_000_001), (1, 2, 50_000_000), (0, 2, 100_000_002)])
    cost, path = dijkstra.shortest_path(csr, 0, 2)
    assert (cost, path) == (100_000_001, [0, 1, 2]) and isinstance(cost, int)


def test_csr_refuses_duplicates_self_loops_and_non_positive_weights():
    with pytest.raises(ValueError):
        _graph(3, [(0, 1, 1), (1, 0, 2)])
    with pytest.raises(ValueError):
        _graph(3, [(1, 1, 1)])
    with pytest.raises(ValueError):
        _graph(3, [(0, 1, 0)])

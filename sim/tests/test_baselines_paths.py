"""Shortest-path trees of the control-plane models against networkx (the test oracle), the fixed
tie-break, the ground-station transit rule and the on-demand (O-Q) Dijkstra."""

import random

import networkx as nx
import numpy as np
import pytest

from chronoroute.baselines.paths import BeliefGraph, bfs_hops, lazy_path, tree_to


def random_graph(seed, n=40, extra=60, gs=4):
    rng = random.Random(seed)
    edges = set()
    for v in range(1, n):                       # a random tree keeps it connected
        edges.add((rng.randrange(v), v))
    while len(edges) < n - 1 + extra:
        a, b = rng.sample(range(n), 2)
        edges.add((min(a, b), max(a, b)))
    a = [e[0] for e in sorted(edges)]
    b = [e[1] for e in sorted(edges)]
    w_ab = [rng.randint(1, 20) for _ in a]       # small weights: plenty of exact ties
    w_ba = [rng.randint(1, 20) for _ in a]
    transit = np.ones(n, dtype=bool)
    transit[n - gs:] = False                     # the last nodes are ground stations
    return n, a, b, w_ab, w_ba, transit


def oracle_graph(n, a, b, w_ab, w_ba, transit, ends):
    """networkx digraph where only transit nodes and the two path ends may appear (transit rule)."""
    keep = {x for x in range(n) if transit[x]} | set(ends)
    g = nx.DiGraph()
    g.add_nodes_from(keep)
    for x, y, p, q in zip(a, b, w_ab, w_ba):
        if x in keep and y in keep:
            g.add_edge(x, y, weight=p)
            g.add_edge(y, x, weight=q)
    return g


@pytest.mark.parametrize("seed", range(10))
def test_tree_matches_networkx_distances_with_transit_rule(seed):
    n, a, b, w_ab, w_ba, transit = random_graph(seed)
    g = BeliefGraph(n, a, b, w_ab, w_ba, transit)
    for dest in range(0, n, 3):
        tr = tree_to(g, dest)
        for src in range(n):
            if src == dest:
                assert tr.dist[src] == 0
                continue
            G = oracle_graph(n, a, b, w_ab, w_ba, transit, (src, dest))
            try:
                want = nx.shortest_path_length(G, src, dest, weight="weight")
            except nx.NetworkXNoPath:
                want = None
            assert tr.dist[src] == want, (seed, src, dest)
            if want is not None:
                p = tr.path(src)
                cost = sum(G[u][v]["weight"] for u, v in zip(p[:-1], p[1:]))
                assert cost == want and p[0] == src and p[-1] == dest
                assert all(transit[x] for x in p[1:-1])          # never relays through a station


def test_tie_break_lowest_next_hop_id():
    # 0 -> {1, 2} -> 3 and 4 -> {1, 2} -> 3: all cost 2; the lower next hop (1) wins
    n = 5
    a, b = [0, 0, 1, 2, 1, 2], [1, 2, 3, 3, 4, 4]
    w = [1, 1, 1, 1, 1, 1]
    g = BeliefGraph(n, a, b, w, w, np.ones(n, dtype=bool))
    tr = tree_to(g, 3)
    assert tr.nxt[0] == 1 and tr.nxt[4] == 1 and tr.dist[0] == 2
    assert tr.path(0) == [0, 1, 3]


def test_directed_weights_are_used_per_direction():
    g = BeliefGraph(3, [0, 1], [1, 2], [5, 5], [1, 1], np.ones(3, dtype=bool))
    assert tree_to(g, 2).dist[0] == 10          # forward 0 -> 1 -> 2 uses w_ab
    assert tree_to(g, 0).dist[2] == 2           # backward uses w_ba


def test_bad_weights_refused():
    with pytest.raises(ValueError):
        BeliefGraph(2, [0], [1], [0], [1], np.ones(2, dtype=bool))


@pytest.mark.parametrize("seed", range(5))
def test_lazy_path_equals_tree_cost_and_bfs_matches_networkx(seed):
    n, a, b, w_ab, w_ba, transit = random_graph(seed + 100)
    g = BeliefGraph(n, a, b, w_ab, w_ba, transit)
    nb = [[] for _ in range(n)]
    wmap = {}
    for i, (x, y, p, q) in enumerate(zip(a, b, w_ab, w_ba)):
        nb[x].append((y, i))
        nb[y].append((x, i))
        wmap[(x, y)] = p
        wmap[(y, x)] = q
    tl = transit.tolist()
    for src in range(0, n, 3):
        for dst in range(1, n, 5):
            if src == dst:
                continue
            cost, path = lazy_path(n, src, dst, lambda u: nb[u], lambda u, v, li: wmap[(u, v)], tl)
            assert cost == tree_to(g, dst).dist[src]
            if path is not None:
                assert sum(wmap[(u, v)] for u, v in zip(path[:-1], path[1:])) == cost
                assert all(transit[x] for x in path[1:-1])
    hops = bfs_hops(g, 0)
    for v in range(1, n):
        G = oracle_graph(n, a, b, w_ab, w_ba, transit, (0, v)).to_undirected()
        try:
            want = nx.shortest_path_length(G, v, 0)
        except nx.NetworkXNoPath:
            want = None
        assert hops[v] == want


@pytest.mark.parametrize('seed',range(12))
def test_lazy_path_with_consistent_lower_bound_is_exact_including_ties(seed):
    n,a,b,ab,ba,transit=random_graph(seed+501,n=24,extra=35,gs=3)
    nominal=BeliefGraph(n,a,b,ab,ba,transit)
    rng=random.Random(seed)
    nb=[[] for _ in range(n)];weights={}
    for i,(u,v,x,y) in enumerate(zip(a,b,ab,ba)):
        nb[u].append((v,i));nb[v].append((u,i))
        weights[u,v]=x+rng.randrange(5);weights[v,u]=y+rng.randrange(5)
    for dst in range(0,n,4):
        lower=tree_to(nominal,dst).dist
        for src in range(0,n,3):
            args=(n,src,dst,lambda u:nb[u],lambda u,v,li:weights[u,v],transit)
            assert lazy_path(*args,lower_bound=lower)==lazy_path(*args)


def test_lazy_lower_bound_rejects_inconsistent_input_and_avoids_irrelevant_branches():
    nb=[[(1,0),(2,1)],[(3,2)],[(3,3)],[]]
    weights={(0,1):1,(0,2):1,(1,3):1,(2,3):100}
    calls=[]
    def weight(u,v,li):calls.append((u,v));return weights[u,v]
    args=(4,0,3,lambda u:nb[u],weight,[True]*4)
    reference=lazy_path(*args);normal_calls=len(calls);calls.clear()
    assert lazy_path(*args,lower_bound=[2,1,100,0])==reference
    assert len(calls)<normal_calls
    with pytest.raises(ValueError):lazy_path(*args,lower_bound=[5,1,100,0])
    with pytest.raises(ValueError):lazy_path(*args,lower_bound=[0])
    with pytest.raises(ValueError):lazy_path(*args,lower_bound=[-1,1,100,0])
    assert lazy_path(*args,lower_bound=[None,1,100,0])==(None,None)

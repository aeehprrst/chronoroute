"""
dijkstra.py
-----------
Shortest paths on one step's graph (topo.graph.CsrGraph), written by hand.

Why by hand and not networkx: the route must be EXACTLY reproducible, by
this code, by the ns-3 C++ PathService and by the website's TypeScript
engine. That needs (1) integer weights (nanoseconds), so no float sum can
come out differently, and (2) a written-down rule for which path wins when
two paths cost exactly the same. networkx is used only in the tests, as an
oracle for the cost.

The algorithm: classic Dijkstra with a binary heap (Python's heapq). Heap
entries are (distance, node), so among equal distances the lower node id is
settled first.

The tie-break rule (what every implementation must reproduce):

    pred[v] = the LOWEST node id u among all nodes with
              dist[u] + w(u, v) == dist[v]  (u a node that may relay)

The path to v is v, pred[v], pred[pred[v]], ... back to the source. This rule
depends only on the exact distances, not on the order the heap happens to
pop nodes, so it is easy to state and to test: with positive weights every
such u has dist[u] < dist[v], so it is settled (and has offered itself as
predecessor) before v is, and the "lower id wins" update below catches every
one of them.

Transit: a node with transit[u] == False (a ground station) can be reached,
and can be the source, but is never expanded unless it is the source. So a
path never relays through a third city.
"""

import heapq
from dataclasses import dataclass

INF = float("inf")


@dataclass(frozen=True)
class ShortestPaths:
    """Result of dijkstra(): exact integer distances and canonical predecessors."""

    source: int
    dist: list          # dist[v] in ns, or None if unreachable
    pred: list          # pred[v] node id, or -1 (source / unreachable)

    def path_to(self, target):
        """Node list source .. target, or None when target is unreachable."""
        if self.dist[target] is None:
            return None
        path = [target]
        while path[-1] != self.source:
            path.append(self.pred[path[-1]])
        path.reverse()
        return path


def dijkstra(csr, source, target=None):
    """Shortest paths from source (stops early once target is settled).

    csr is a topo.graph.CsrGraph (integer weights > 0). With a target, the
    distances and predecessors of the target and of every node on its path
    are final; other nodes may be unfinished (that is what stopping early
    means).
    """
    n = csr.n_nodes
    if not 0 <= source < n:
        raise ValueError(f"source {source} is not a node")
    indptr = csr.indptr.tolist()
    indices = csr.indices.tolist()
    weights = csr.weights.tolist()
    transit = csr.transit.tolist()
    dist = [INF] * n
    pred = [-1] * n
    done = [False] * n
    dist[source] = 0
    heap = [(0, source)]
    while heap:
        d, u = heapq.heappop(heap)
        if done[u]:
            continue                      # a stale heap entry (u was improved later)
        done[u] = True
        if u == target:
            break
        if u != source and not transit[u]:
            continue                      # reachable, but may not relay
        for i in range(indptr[u], indptr[u + 1]):
            v = indices[i]
            nd = d + weights[i]
            if nd < dist[v]:
                dist[v] = nd
                pred[v] = u
                heapq.heappush(heap, (nd, v))
            elif nd == dist[v] and u < pred[v]:
                pred[v] = u               # equal cost: the lower predecessor id wins
    return ShortestPaths(source=source,
                         dist=[None if x == INF else x for x in dist],
                         pred=pred)


def shortest_path(csr, source, target):
    """(cost_ns, [nodes]) of the canonical shortest path, or (None, None)."""
    sp = dijkstra(csr, source, target)
    if sp.dist[target] is None:
        return None, None
    return sp.dist[target], sp.path_to(target)


__all__ = ["ShortestPaths", "dijkstra", "shortest_path"]

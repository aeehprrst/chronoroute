"""
paths.py
--------
Shortest paths for the control-plane models, on a "belief" graph: the links
a scheme THINKS are up, with the delays it THINKS they have.

Weights are integer nanoseconds and may differ per direction (a link-state
scheme with delay metrics advertises one delay per direction, RFC 7471 is
"unidirectional"). Everything is exact integer arithmetic, so a result never
depends on float summation order.

    BeliefGraph(n, a, b, w_ab, w_ba, transit)
        the directed graph, stored as REVERSE adjacency (for each node v the
        nodes u that can send to v, with w(u -> v)), because hop-by-hop
        routing asks "from every node, what is my next hop TOWARDS dest":
        one Dijkstra from the destination over reversed edges answers it for
        every node at once (Hypatia computes its forwarding state the same
        way, one shortest-path tree per destination).

    tree_to(g, dest) -> Tree(dist, nxt)
        dist[u] = cost of the best path u -> ... -> dest (None: no path)
        nxt[u]  = u's next hop on it, with the fixed tie-break below

    lazy_path(...)
        forward Dijkstra whose edge weights are computed on demand (the
        queue-aware oracle O-Q asks each link's queue only when it needs it)

Tie-break (what makes the result reproducible): among the next hops v with
w(u->v) + dist[v] == dist[u], the LOWEST node id wins. With positive
weights every such v is settled before u, so this rule depends only on the
exact distances, not on heap order (the same argument as route/dijkstra.py,
which uses "lowest predecessor id" for the forward direction).

Transit: a node with transit False (a ground station) may start or end a
path but never relays one, as in the planner (route/dijkstra.py).
"""

import heapq
from dataclasses import dataclass

import numpy as np

INF = float("inf")


class BeliefGraph:
    """One directed graph (see the module docstring). Edges with weight <= 0 are refused."""

    __slots__ = ("n", "ptr", "src", "w", "transit", "n_edges")

    def __init__(self, n, a, b, w_ab, w_ba, transit):
        a = np.asarray(a, dtype=np.int64)
        b = np.asarray(b, dtype=np.int64)
        w_ab = np.asarray(w_ab, dtype=np.int64)
        w_ba = np.asarray(w_ba, dtype=np.int64)
        if a.size and (np.any(w_ab <= 0) or np.any(w_ba <= 0)):
            raise ValueError("edge weights must be positive integers (ns)")
        # reverse rows: for edge u -> v the row is v, the entry is (u, w(u->v))
        rows = np.concatenate([b, a])          # a->b lands in row b, b->a in row a
        srcs = np.concatenate([a, b])
        ws = np.concatenate([w_ab, w_ba])
        order = np.lexsort((srcs, rows))
        rows, srcs, ws = rows[order], srcs[order], ws[order]
        counts = np.bincount(rows, minlength=n)
        ptr = np.zeros(n + 1, dtype=np.int64)
        np.cumsum(counts, out=ptr[1:])
        self.n = int(n)
        self.ptr = ptr.tolist()
        self.src = srcs.tolist()
        self.w = ws.tolist()
        self.transit = np.asarray(transit, dtype=bool).tolist()
        self.n_edges = len(self.src)

    def senders(self, v):
        """[(u, w(u->v))] of the nodes that can send to v."""
        lo, hi = self.ptr[v], self.ptr[v + 1]
        return list(zip(self.src[lo:hi], self.w[lo:hi]))


@dataclass(frozen=True)
class Tree:
    dest: int
    dist: list          # int ns or None
    nxt: list           # next hop node id, -1 at dest / unreachable

    def path(self, src):
        """Node list src .. dest following the next hops, or None."""
        if self.dist[src] is None:
            return None
        out = [src]
        while out[-1] != self.dest:
            out.append(self.nxt[out[-1]])
            if len(out) > len(self.nxt) + 1:            # cannot happen with positive weights
                raise AssertionError("next-hop pointers form a loop")
        return out


def tree_to(g, dest):
    """Shortest paths from every node TO dest on BeliefGraph g (see the module docstring)."""
    n = g.n
    ptr, srcs, ws, transit = g.ptr, g.src, g.w, g.transit
    dist = [INF] * n
    nxt = [-1] * n
    dist[dest] = 0
    heap = [(0, dest)]
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        d, v = pop(heap)
        if d > dist[v]:
            continue                         # a stale heap entry (v was improved later)
        if v != dest and not transit[v]:
            continue                         # a ground station never relays
        for i in range(ptr[v], ptr[v + 1]):
            u = srcs[i]
            nd = d + ws[i]
            du = dist[u]
            if nd < du:
                dist[u] = nd
                nxt[u] = v
                push(heap, (nd, u))
            elif nd == du and v < nxt[u]:
                nxt[u] = v                    # equal cost: the lower next-hop id wins
    return Tree(dest=dest, dist=[None if x == INF else x for x in dist], nxt=nxt)


def bfs_hops(g, root):
    """Fewest hops from every node to root (same transit rule), None if unreachable."""
    return bfs_tree(g, root)[0]


def bfs_tree(g, root):
    """(hops, nxt): fewest hops from every node to root and the next hop on one such path
    (the lowest-id neighbour one hop closer; same transit rule)."""
    n = g.n
    hops = [None] * n
    nxt = [-1] * n
    hops[root] = 0
    frontier = [root]
    ptr, srcs, transit = g.ptr, g.src, g.transit
    while frontier:
        nxt_frontier = []
        for v in sorted(frontier):
            if v != root and not transit[v]:
                continue
            h = hops[v] + 1
            for i in range(ptr[v], ptr[v + 1]):
                u = srcs[i]
                if hops[u] is None:
                    hops[u] = h
                    nxt[u] = v
                    nxt_frontier.append(u)
                elif hops[u] == h and v < nxt[u]:
                    nxt[u] = v
        frontier = nxt_frontier
    return hops, nxt


def bfs_hops_multi(g, roots):
    """Fewest hops from every node to the NEAREST of several roots (None if none reachable).

    Every root starts at 0 and may send (like the root of bfs_tree); any other node with
    transit False never relays. Equal to min over r of bfs_hops(g, r): a path through
    another root r2 is never shorter than the path that stops at r2.
    """
    n = g.n
    hops = [None] * n
    frontier = []
    for r in roots:
        hops[r] = 0
        frontier.append(r)
    is_root = set(frontier)
    ptr, srcs, transit = g.ptr, g.src, g.transit
    while frontier:
        nxt_frontier = []
        for v in frontier:
            if v not in is_root and not transit[v]:
                continue
            h = hops[v] + 1
            for i in range(ptr[v], ptr[v + 1]):
                u = srcs[i]
                if hops[u] is None:
                    hops[u] = h
                    nxt_frontier.append(u)
        frontier = nxt_frontier
    return hops


def lazy_path(n, src, dst, neighbours, weight, transit):
    """(cost, path) of the cheapest src -> dst path, weights computed on demand; (None, None).

    neighbours(u) -> iterable of (v, link index); weight(u, v, li) -> int > 0, or None when the
    link may not be used. Tie-break: the lowest predecessor id wins (route/dijkstra.py rule).
    """
    dist = {src: 0}
    pred = {}
    done = set()
    heap = [(0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if u in done:
            continue
        done.add(u)
        if u == dst:
            break
        if u != src and not transit[u]:
            continue
        for v, li in neighbours(u):
            if v in done:
                continue
            w = weight(u, v, li)
            if w is None:
                continue
            if w <= 0:
                raise ValueError("edge weights must be positive")
            nd = d + w
            dv = dist.get(v)
            if dv is None or nd < dv:
                dist[v] = nd
                pred[v] = u
                heapq.heappush(heap, (nd, v))
            elif nd == dv and u < pred[v]:
                pred[v] = u
    if dst not in done:
        return None, None
    path = [dst]
    while path[-1] != src:
        path.append(pred[path[-1]])
    path.reverse()
    return dist[dst], path


__all__ = ["BeliefGraph", "Tree", "tree_to", "bfs_hops", "bfs_hops_multi", "bfs_tree", "lazy_path"]

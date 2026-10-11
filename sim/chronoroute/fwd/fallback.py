"""
fallback.py
-----------
The fallback ("geographic") forwarding functions a satellite uses for a
packet in GREEDY mode (spec section 6 steps 4 and 7: SL = 0, the packet is
addressed to SID[0], the destination ground station). All of them:

  * deliver straight to the destination station when this node has an UP
    link to it;
  * otherwise pick a neighbouring SATELLITE (ground stations never relay)
    over a link that is up right now, using positions at the current step
    (each satellite knows its neighbours' positions from the ephemeris it
    carries, and the destination station's coordinates; reviewer item 3
    counts that state);
  * return (next_node, link_index), or (None, reason) when they cannot
    continue; the engine then drops the packet with that reason.

Termination: every function either moves the packet one hop or stops it,
and the engine stops any packet after hop_limit transmissions (IPv6 Hop
Limit, 64 by default). So no packet can circulate for ever.

  greedy_visited  (legacy behaviour, sim/legacy/simulator.greedy_next_hop)
                  the live neighbour closest to the destination among those
                  this packet has not visited yet. The visited set is state
                  carried WITH the packet by the simulator, not in the T-CRH
                  bytes (a real packet would need extra header space for it).
                  Stuck (reason "stuck") when every live neighbour was visited.
  greedy_pure     strict progress, zero state: the live neighbour closest to
                  the destination, but only if it is strictly closer than this
                  node (same step). Stuck at a local minimum. (At a ground
                  station, i.e. the ingress whose first link is down, any live
                  satellite may be taken: a station cannot relay anyway.)
  grid_detour     +Grid detour: the preferred next hop is the Grid-4 neighbour
                  closest to the destination, whatever its link state. If that
                  link is up (and not "slow", see below) and is not where the
                  packet came from, take it. Otherwise route AROUND it: the
                  closest other live neighbour, never straight back to the
                  previous hop (known from the incoming interface, local
                  knowledge, not packet state). On the +Grid this is the
                  square detour: sideways to the perpendicular neighbour, then
                  onward. A link counts as slow when the satellite's OWN
                  transmit queue on it would hold a new packet longer than
                  slow_queue_ns (optional; local knowledge only).

Ties on distance go to the lower node id (deterministic).
"""

import math

REASON_STUCK = "stuck"


def _dist(p, q):
    return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)


class FallbackContext:
    """What a fallback function may look at: links, their state now, positions now."""

    def __init__(self, topo, link_usable, queue_wait=None, slow_queue_ns=None):
        self.topo = topo
        self.link_usable = link_usable          # (li, a, b, t, k) -> bool (truth, faults included)
        self.queue_wait = queue_wait            # (a, b, li, t) -> ns the local queue would hold a packet
        self.slow_queue_ns = slow_queue_ns

    def pos(self, node, k):
        return self.topo.node_ecef_km(node, k)

    def direct(self, node, dest, t, k):
        """(dest, link) if node has a usable link to the destination station right now."""
        for nb, li in self.topo.neighbours[node]:
            if nb == dest and self.link_usable(li, node, nb, t, k):
                return dest, li
        return None

    def slow(self, node, nb, li, t):
        if self.slow_queue_ns is None or self.queue_wait is None:
            return False
        return self.queue_wait(node, nb, li, t) > self.slow_queue_ns


def greedy_visited(ctx, node, dest, t, k, prev, visited):
    hit = ctx.direct(node, dest, t, k)
    if hit:
        return hit
    target = ctx.pos(dest, k)
    S = ctx.topo.n_sats
    best = None
    for nb, li in ctx.topo.neighbours[node]:
        if nb >= S or nb in visited or not ctx.link_usable(li, node, nb, t, k):
            continue
        d = _dist(ctx.pos(nb, k), target)
        if best is None or d < best[0] or (d == best[0] and nb < best[1]):
            best = (d, nb, li)
    return (best[1], best[2]) if best else (None, REASON_STUCK)


def greedy_pure(ctx, node, dest, t, k, prev, visited):
    hit = ctx.direct(node, dest, t, k)
    if hit:
        return hit
    target = ctx.pos(dest, k)
    S = ctx.topo.n_sats
    here = _dist(ctx.pos(node, k), target) if node < S else math.inf
    best = None
    for nb, li in ctx.topo.neighbours[node]:
        if nb >= S or not ctx.link_usable(li, node, nb, t, k):
            continue
        d = _dist(ctx.pos(nb, k), target)
        if d >= here:
            continue                                      # strict progress only
        if best is None or d < best[0] or (d == best[0] and nb < best[1]):
            best = (d, nb, li)
    return (best[1], best[2]) if best else (None, REASON_STUCK)


def grid_detour(ctx, node, dest, t, k, prev, visited):
    hit = ctx.direct(node, dest, t, k)
    if hit:
        return hit
    target = ctx.pos(dest, k)
    S = ctx.topo.n_sats
    ranked = []
    for nb, li in ctx.topo.neighbours[node]:
        if nb >= S:
            continue
        ranked.append((_dist(ctx.pos(nb, k), target), nb, li))
    if not ranked:
        return None, REASON_STUCK
    ranked.sort()
    d0, pref, pref_li = ranked[0]
    if pref != prev and ctx.link_usable(pref_li, node, pref, t, k) and not ctx.slow(node, pref, pref_li, t):
        return pref, pref_li
    for d, nb, li in ranked[1:]:
        if nb == prev:
            continue
        if ctx.link_usable(li, node, nb, t, k) and not ctx.slow(node, nb, li, t):
            return nb, li
    return None, REASON_STUCK


FALLBACKS = {"greedy_visited": greedy_visited, "greedy_pure": greedy_pure, "grid_detour": grid_detour}

__all__ = ["REASON_STUCK", "FallbackContext", "greedy_visited", "greedy_pure", "grid_detour", "FALLBACKS"]

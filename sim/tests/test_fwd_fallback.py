"""Fallback forwarding functions (fwd/fallback.py) on a small hand-made +Grid.

    row 2:  6 - 7 - 8
            |   |   |
    row 1:  3 - 4 - 5 ==== City (node 9, east of 5)
            |   |   |
    row 0:  0 - 1 - 2

Satellite (r, c) sits at x = 1000 c, y = 1000 r (km); the city is at x = 5000, y = 1000.
"""

from types import SimpleNamespace

import numpy as np

from chronoroute.fwd import fallback as FB

CITY = 9


def grid(down=()):
    links = []
    for r in range(3):
        for c in range(3):
            n = 3 * r + c
            if c < 2:
                links.append((n, n + 1))
            if r < 2:
                links.append((n, n + 3))
    links.append((5, CITY))
    nbrs = {n: [] for n in range(10)}
    for li, (a, b) in enumerate(links):
        nbrs[a].append((b, li))
        nbrs[b].append((a, li))
    pos = {3 * r + c: np.array([1000.0 * c, 1000.0 * r, 7000.0]) for r in range(3) for c in range(3)}
    pos[CITY] = np.array([5000.0, 1000.0, 6400.0])
    topo = SimpleNamespace(n_sats=9, neighbours=[sorted(nbrs[n]) for n in range(10)],
                           node_ecef_km=lambda node, k: pos[node])
    dead = {frozenset(x) for x in down}
    usable = lambda li, a, b, t, k: frozenset((a, b)) not in dead
    return FB.FallbackContext(topo, usable)


def test_direct_delivery_when_linked():
    for fn in FB.FALLBACKS.values():
        assert fn(grid(), 5, CITY, 0, 0, -1, set())[0] == CITY
    # the link to the city is down: nobody can deliver directly
    assert FB.greedy_pure(grid(down=[(5, CITY)]), 5, CITY, 0, 0, -1, set())[0] != CITY


def test_greedy_visited_skips_visited_and_gets_stuck():
    ctx = grid()
    assert FB.greedy_visited(ctx, 4, CITY, 0, 0, -1, {4})[0] == 5
    assert FB.greedy_visited(ctx, 4, CITY, 0, 0, -1, {4, 5})[0] in (1, 7)     # next closest
    assert FB.greedy_visited(ctx, 4, CITY, 0, 0, -1, {1, 3, 5, 7}) == (None, FB.REASON_STUCK)


def test_greedy_pure_needs_strict_progress():
    ctx = grid(down=[(4, 5)])
    nxt, _ = FB.greedy_pure(ctx, 4, CITY, 0, 0, -1, None)
    assert nxt is None                                   # 1, 3, 7 are all farther from the city than 4
    assert FB.greedy_pure(grid(), 3, CITY, 0, 0, -1, None)[0] == 4


def test_grid_detour_goes_around_a_dead_link_and_never_turns_back():
    ctx = grid(down=[(4, 5)])
    nxt, _ = FB.grid_detour(ctx, 4, CITY, 0, 0, 3, None)       # came from 3; preferred 5 is dead
    assert nxt in (1, 7)                                        # the square detour, not back to 3
    side = nxt
    nxt2, _ = FB.grid_detour(ctx, side, CITY, 0, 0, 4, None)    # from the side node: onward east
    assert nxt2 == side + 1
    assert FB.grid_detour(ctx, nxt2, CITY, 0, 0, side, None)[0] == 5
    # only the previous hop is left: stuck rather than ping-pong
    dead_end = grid(down=[(4, 5), (4, 1), (4, 7)])
    assert FB.grid_detour(dead_end, 4, CITY, 0, 0, 3, None) == (None, FB.REASON_STUCK)


def test_grid_detour_treats_a_slow_local_queue_as_unusable():
    ctx = grid()
    ctx.queue_wait = lambda a, b, li, t: 10_000_000 if {a, b} == {4, 5} else 0
    ctx.slow_queue_ns = 1_000_000
    assert FB.grid_detour(ctx, 4, CITY, 0, 0, 3, None)[0] in (1, 7)
    ctx.slow_queue_ns = None
    assert FB.grid_detour(ctx, 4, CITY, 0, 0, 3, None)[0] == 5


def test_ties_go_to_the_lower_node_id():
    ctx = grid(down=[(4, 5)])
    # 1 and 7 are equally far from the city (mirror images): 1 wins
    assert FB.greedy_visited(ctx, 4, CITY, 0, 0, -1, {4, 3})[0] == 1

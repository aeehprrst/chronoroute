"""
EXPERIMENT 5 -- Path stretch of the geographic fallback
=======================================================

Question
--------
The fallback is free in terms of state: a satellite forwards to whichever
neighbour is physically closest to the destination, needing no routing table
at all. But greedy forwarding is not optimal. What does that cost?

We measure "stretch": how much longer the greedy path is than the true
shortest path, in hops and in latency. We also count how often greedy gets
stuck in a local minimum, which is the classic weakness of geographic
routing.

This is the honest cost side of the fail-safe mechanism.
"""

import random
import networkx as nx
import matplotlib.pyplot as plt

from common import setup, save, style
from constellation import NUM_SATS, distance

NUM_PAIRS = 400
HOP_LIMIT = 60


def greedy_path(graph, src, dst):
    """
    Walk the graph greedily: always step to the neighbour physically nearest
    the destination. Returns (path, total_latency_ms) or (None, None) if stuck.
    """
    dst_pos = graph.nodes[dst]['pos']
    path = [src]
    visited = {src}
    current = src
    latency = 0.0

    while current != dst and len(path) < HOP_LIMIT:
        best, best_d, best_w = None, float('inf'), None
        for nb in graph.neighbors(current):
            if nb in visited:
                continue
            d = distance(graph.nodes[nb]['pos'], dst_pos)
            if d < best_d:
                best_d, best, best_w = d, nb, graph[current][nb]['weight']

        if best is None:
            return None, None           # stuck in a local minimum
        latency += best_w
        current = best
        visited.add(current)
        path.append(current)

    if current != dst:
        return None, None
    return path, latency


def run():
    print("EXPERIMENT 5: geographic fallback path stretch")
    times, sat_pos, gs_pos, graphs = setup()

    graph = graphs[0]
    rng = random.Random(7)

    hop_stretch, lat_stretch = [], []
    stuck = 0
    optimal = 0

    for _ in range(NUM_PAIRS):
        src = rng.randrange(NUM_SATS)
        dst = rng.randrange(NUM_SATS)
        if src == dst:
            continue

        try:
            opt_path = nx.shortest_path(graph, src, dst, weight='weight')
            opt_lat = nx.shortest_path_length(graph, src, dst, weight='weight')
        except nx.NetworkXNoPath:
            continue

        g_path, g_lat = greedy_path(graph, src, dst)
        if g_path is None:
            stuck += 1
            continue

        hs = (len(g_path) - 1) / (len(opt_path) - 1)
        ls = g_lat / opt_lat
        hop_stretch.append(hs)
        lat_stretch.append(ls)
        if hs <= 1.0001:
            optimal += 1

    n = len(hop_stretch)
    mean_hs = sum(hop_stretch) / n
    mean_ls = sum(lat_stretch) / n
    p95 = sorted(lat_stretch)[int(n * 0.95)]
    worst = max(lat_stretch)

    print(f"  pairs tested          : {n + stuck}")
    print(f"  greedy got stuck      : {stuck} "
          f"({stuck / (n + stuck) * 100:.1f}%)")
    print(f"  already optimal       : {optimal} ({optimal / n * 100:.1f}%)")
    print(f"  mean hop stretch      : {mean_hs:.2f}x")
    print(f"  mean latency stretch  : {mean_ls:.2f}x")
    print(f"  95th percentile       : {p95:.2f}x")
    print(f"  worst case            : {worst:.2f}x")

    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    ax1.hist(lat_stretch, bins=30, color='#2471a3', edgecolor='white')
    ax1.axvline(1.0, color='#27ae60', ls='-', lw=2.4,
                label='optimal (stretch = 1.0)')
    ax1.axvline(mean_ls, color='#c0392b', ls='--', lw=2.2,
                label=f'mean = {mean_ls:.2f}x')
    ax1.axvline(p95, color='#e67e22', ls=':', lw=2.2,
                label=f'95th pct = {p95:.2f}x')
    ax1.set_xlabel('Latency stretch (greedy / shortest path)')
    ax1.set_ylabel('Number of satellite pairs')
    ax1.set_title('Cost of falling back to geographic forwarding')
    ax1.legend(fontsize=9.5)

    ax2.scatter([len(p) for p in [None] * 0], [], s=0)   # keep axes clean
    ax2.scatter(hop_stretch, lat_stretch, alpha=0.4, s=22, color='#8e44ad')
    ax2.plot([1, max(hop_stretch)], [1, max(hop_stretch)], 'k--', lw=1.2,
             alpha=0.6, label='hop stretch = latency stretch')
    ax2.set_xlabel('Hop-count stretch')
    ax2.set_ylabel('Latency stretch')
    ax2.set_title('Hop stretch vs latency stretch')
    ax2.legend(fontsize=9.5)

    fig.suptitle('Experiment 5: what the zero-state fallback costs',
                 fontsize=14, fontweight='bold', y=1.02)
    save(fig, 'exp5_path_stretch.png')

    return {'mean_hop_stretch': mean_hs, 'mean_latency_stretch': mean_ls,
            'p95': p95, 'stuck_rate': stuck / (n + stuck)}


if __name__ == '__main__':
    run()
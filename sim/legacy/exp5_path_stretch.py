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

v0.9 fixes (bug #16)
--------------------
  * SURVIVORSHIP BIAS. v0 averaged the stretch over the pairs greedy
    managed to deliver and reported the failures on a separate line, so the
    headline "mean stretch" improved whenever more pairs failed. Now:
      - the delivery rate is reported first, with a 95% Wilson interval;
      - the conditional stretch is labelled as such (pairs BOTH methods
        deliver);
      - the effective latency stretch counts a lost packet as infinitely
        stretched (plan 5.3), so its percentiles are honest: if greedy fails
        on more than 5% of pairs, the effective 95th percentile is infinite.
  * ONE HOP LIMIT. v0 allowed 60 hops here while the simulator drops a
    packet after 40; now both use simulator.HOP_LIMIT, and the greedy step is
    the simulator's own greedy_next_hop(), so this measures exactly the
    fallback the simulator runs.
  * Pairs are drawn over the whole window, not only from the graph at t=0,
    and over the ACTIVE constellation (constellation.num_sats() at call time).
  * "ALREADY OPTIMAL" MEANS LATENCY. v0 (and the first v0.9 run) called a
    greedy path optimal when it had no more HOPS than the shortest-latency
    path; that included paths up to 1.48x slower, and paths with fewer hops.
    Now the share of delivered pairs whose greedy path is as fast as the
    shortest path (latency stretch 1) is reported as latency-optimal, and
    the hop-count share is reported under its real name.
"""

import math
import random

import matplotlib.pyplot as plt
import networkx as nx

import common
import constellation as C
import simulator
from common import style
from simulator import greedy_next_hop, HOP_LIMIT          # noqa: F401  (HOP_LIMIT re-exported)
from chronoroute.provenance import RunTimer

NAME = 'exp5_path_stretch'

DEFAULTS = {
    'duration_s': common.DURATION_S,
    'step_s': common.STEP_S,
    'num_pairs': 400,
    'seed': 7,
    'quantiles': [0.5, 0.9, 0.95, 0.99],
}

# latency stretch at most 1 + this counts as optimal (float sums of the same
# path in a different order differ by ~1e-16)
LATENCY_OPTIMAL_TOL = 1e-9

LABELS = {
    'constellation': 'MODELLED',
    'pairs': 'MODELLED',            # uniformly random satellite pairs
    'stretch': 'DERIVED',
}


def greedy_path(graph, src, dst, hop_limit=None):
    """
    Walk the graph greedily, exactly as the simulator's fallback does: always
    step to the unvisited neighbour physically nearest the destination.

    Returns (path, total_latency_ms, 'delivered'), or (None, None, reason)
    with reason 'stuck' (a local minimum: no unvisited neighbour) or
    'hop_limit' (simulator.HOP_LIMIT transmissions without arriving).
    """
    if hop_limit is None:
        hop_limit = simulator.HOP_LIMIT     # read at call time: one shared constant
    dst_pos = graph.nodes[dst]['pos']
    path = [src]
    visited = {src}
    current = src
    latency = 0.0

    while current != dst:
        if len(path) - 1 >= hop_limit:
            return None, None, 'hop_limit'
        nxt = greedy_next_hop(graph, current, dst_pos, visited)
        if nxt is None:
            return None, None, 'stuck'      # stuck in a local minimum
        latency += graph[current][nxt]['weight']
        current = nxt
        visited.add(current)
        path.append(current)

    return path, latency, 'delivered'


def effective_quantile(values, p):
    """
    The p-quantile (nearest rank) of values that may contain math.inf for a
    lost packet. If more than (1 - p) of the values are infinite, so is the
    quantile: a loss is never quietly dropped from the statistics.
    """
    xs = sorted(values)
    if not xs:
        return None
    k = max(0, math.ceil(p * len(xs) - 1e-9) - 1)
    return xs[k]


def _finite_or_text(x):
    """For JSON (no infinities): keep numbers, write inf as the string 'inf'."""
    return 'inf' if x == math.inf else x


def run(workers=None, **overrides):
    """A few hundred Dijkstra runs, so it stays in one process (workers unused)."""
    cfg = common.make_config(DEFAULTS, overrides)
    print("EXPERIMENT 5: geographic fallback path stretch")
    limit = simulator.HOP_LIMIT

    with RunTimer() as timer:
        times, sat_pos, gs_pos, graphs = common.setup(cfg['duration_s'], cfg['step_s'])
        rng = random.Random(cfg['seed'])
        n_sats = C.num_sats()

        rows = []
        same_node = unreachable = 0
        for i in range(cfg['num_pairs']):
            g_idx = rng.randrange(len(graphs))
            src = rng.randrange(n_sats)
            dst = rng.randrange(n_sats)
            if src == dst:
                same_node += 1
                continue
            graph = graphs[g_idx]
            try:
                opt_lat, opt_path = nx.single_source_dijkstra(graph, src, dst, weight='weight')
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                unreachable += 1           # no route at all: not greedy's fault
                continue

            g_path, g_lat, outcome = greedy_path(graph, src, dst, limit)
            row = {'pair': i, 'snapshot': g_idx, 't_s': times[g_idx], 'src': src, 'dst': dst,
                   'opt_hops': len(opt_path) - 1, 'opt_latency_ms': opt_lat,
                   'greedy_outcome': outcome, 'greedy_hops': None, 'greedy_latency_ms': None,
                   'hop_stretch': None, 'latency_stretch': None,
                   'effective_latency_stretch': math.inf}
            if g_path is not None:
                ls = g_lat / opt_lat
                assert ls >= 1 - 1e-9, "greedy cannot beat Dijkstra"
                row.update(greedy_hops=len(g_path) - 1, greedy_latency_ms=g_lat,
                           hop_stretch=(len(g_path) - 1) / (len(opt_path) - 1),
                           latency_stretch=ls, effective_latency_stretch=ls)
            rows.append(row)

        n = len(rows)
        delivered = [r for r in rows if r['greedy_outcome'] == 'delivered']
        k = len(delivered)
        stuck = sum(r['greedy_outcome'] == 'stuck' for r in rows)
        hop_out = sum(r['greedy_outcome'] == 'hop_limit' for r in rows)
        rate, rate_lo, rate_hi = common.wilson_ci(k, n)
        lat = [r['latency_stretch'] for r in delivered]
        hop = [r['hop_stretch'] for r in delivered]
        eff = [r['effective_latency_stretch'] for r in rows]
        mean_ls, ls_lo, ls_hi, _ = common.mean_ci(lat)
        mean_hs = sum(hop) / k if k else None
        eff_q = {p: effective_quantile(eff, p) for p in cfg['quantiles']}
        cond_q = {p: effective_quantile(lat, p) for p in cfg['quantiles']}
        latency_optimal = sum(1 for x in lat if x <= 1 + LATENCY_OPTIMAL_TOL)
        few_hops = sum(1 for h in hop if h <= 1.0)       # hop counts: an exact ratio
        latency_optimal_share = latency_optimal / k if k else None
        few_hops_share = few_hops / k if k else None

        print(f"  satellite pairs with a route : {n} (same node {same_node}, "
              f"no route {unreachable})")
        print(f"  greedy delivered              : {k} = {100 * rate:.1f}% "
              f"[95% CI {100 * rate_lo:.1f}-{100 * rate_hi:.1f}]")
        print(f"  greedy stuck / hit hop limit  : {stuck} / {hop_out} "
              f"(hop limit {limit}, shared with the simulator)")
        if k:
            print(f"  latency-optimal (delivered)   : {latency_optimal} "
                  f"({100 * latency_optimal_share:.1f}%)  greedy path as fast as the shortest")
            print(f"  same or fewer hops (delivered): {few_hops} ({100 * few_hops_share:.1f}%)"
                  f"  hop count only; NOT 'optimal' (v0's label)")
            print(f"  conditional mean stretch      : hops {mean_hs:.2f}x, latency "
                  f"{mean_ls:.2f}x  (only the {k} pairs greedy delivers)")
        for p in cfg['quantiles']:
            print(f"  effective latency stretch p{100 * p:g} : {eff_q[p]:.2f}x"
                  f"   (conditional: {cond_q[p] if cond_q[p] is None else round(cond_q[p], 2)}x)")

        summary = [
            {'statistic': 'pairs_tested', 'value': n, 'ci95_lo': None, 'ci95_hi': None},
            {'statistic': 'greedy_delivery_rate', 'value': rate, 'ci95_lo': rate_lo,
             'ci95_hi': rate_hi},
            {'statistic': 'greedy_stuck', 'value': stuck, 'ci95_lo': None, 'ci95_hi': None},
            {'statistic': 'greedy_hop_limit', 'value': hop_out, 'ci95_lo': None,
             'ci95_hi': None},
            {'statistic': 'conditional_mean_latency_stretch', 'value': mean_ls,
             'ci95_lo': ls_lo, 'ci95_hi': ls_hi},
            {'statistic': 'conditional_mean_hop_stretch', 'value': mean_hs, 'ci95_lo': None,
             'ci95_hi': None},
            {'statistic': 'latency_optimal_share_of_delivered', 'value': latency_optimal_share,
             'ci95_lo': None, 'ci95_hi': None},
            {'statistic': 'same_or_fewer_hops_share_of_delivered', 'value': few_hops_share,
             'ci95_lo': None, 'ci95_hi': None},
        ] + [{'statistic': f'effective_latency_stretch_p{100 * p:g}', 'value': eff_q[p],
              'ci95_lo': None, 'ci95_hi': None} for p in cfg['quantiles']] \
          + [{'statistic': f'conditional_latency_stretch_p{100 * p:g}', 'value': cond_q[p],
              'ci95_lo': None, 'ci95_hi': None} for p in cfg['quantiles']]

        # ---------------------------------------------------------- plot
        style()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

        # left: the CDF over ALL pairs. A failed pair is infinitely stretched,
        # so the curve stops at the delivery rate instead of reaching 100%.
        finite = sorted(lat)
        ys = [100.0 * (j + 1) / n for j in range(len(finite))]
        ax1.step(finite, ys, where='post', color='#2471a3', lw=2.2,
                 label='greedy (all pairs; failures = infinite stretch)')
        ax1.axhline(100 * rate, color='#c0392b', ls='--', lw=1.6,
                    label=f'greedy delivers {100 * rate:.1f}% '
                          f'(stuck {stuck}, hop limit {hop_out})')
        ax1.axvline(1.0, color='#27ae60', lw=2.0, label='optimal (stretch = 1.0)')
        for p, sty in [(0.5, ':'), (0.95, '-.')]:
            if p in eff_q and eff_q[p] is not None and eff_q[p] != math.inf:
                ax1.axvline(eff_q[p], color='#e67e22', ls=sty, lw=1.6,
                            label=f'effective p{100 * p:g} = {eff_q[p]:.2f}x')
            elif p in eff_q:
                ax1.plot([], [], color='#e67e22', ls=sty,
                         label=f'effective p{100 * p:g} = infinite (losses)')
        ax1.set_ylim(0, 102)
        ax1.set_xlabel('Latency stretch (greedy / shortest path)')
        ax1.set_ylabel('Pairs with stretch at most x (%)')
        ax1.set_title('Cost of falling back to geographic forwarding')
        ax1.legend(fontsize=8.5, loc='lower right')

        ax2.scatter(hop, lat, alpha=0.4, s=22, color='#8e44ad',
                    label=f'{k} delivered pairs (conditional)')
        if hop:
            top = max(max(hop), max(lat))
            ax2.plot([1, top], [1, top], 'k--', lw=1.2, alpha=0.6,
                     label='hop stretch = latency stretch')
        ax2.set_xlabel('Hop-count stretch')
        ax2.set_ylabel('Latency stretch')
        ax2.set_title('Hop stretch vs latency stretch (delivered pairs only)')
        ax2.legend(fontsize=9)

        fig.suptitle('Experiment 5: what the zero-state fallback costs '
                     '(losses counted, hop limit shared with the simulator)',
                     fontsize=13.5, fontweight='bold', y=1.02)

    pair_fields = ['pair', 'snapshot', 't_s', 'src', 'dst', 'opt_hops', 'opt_latency_ms',
                   'greedy_outcome', 'greedy_hops', 'greedy_latency_ms', 'hop_stretch',
                   'latency_stretch', 'effective_latency_stretch']
    config = {**common.scenario_config(), **cfg, 'hop_limit': limit,
              'pair_rule': 'random.Random(seed): snapshot, src, dst per pair; '
                           'src == dst and unreachable pairs skipped',
              'quantile_rule': 'nearest rank, losses = +inf',
              'latency_optimal_rule': f'latency stretch <= 1 + {LATENCY_OPTIMAL_TOL:g}'}
    out = common.write_results(
        NAME, fig=fig,
        tables=[(f'{NAME}.csv', pair_fields, rows),
                ('exp5_summary.csv', ['statistic', 'value', 'ci95_lo', 'ci95_hi'], summary)],
        config=config, seeds=[cfg['seed']], labels=LABELS,
        extra={'propagation': common.setup_stats(cfg['duration_s'], cfg['step_s']),
               'pairs_same_node': same_node, 'pairs_unreachable': unreachable,
               'effective_latency_stretch': {f'p{100 * p:g}': _finite_or_text(v)
                                             for p, v in eff_q.items()}},
        timer=timer)

    return {'pairs_tested': n, 'delivery_rate': rate, 'stuck': stuck, 'hop_limit_failures': hop_out,
            'hop_limit': limit, 'mean_hop_stretch': mean_hs, 'mean_latency_stretch': mean_ls,
            'effective_quantiles': eff_q, 'stuck_rate': stuck / n if n else None,
            'latency_optimal_share': latency_optimal_share,
            'same_or_fewer_hops_share': few_hops_share,
            'outputs': out}


if __name__ == '__main__':
    run()

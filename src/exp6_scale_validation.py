"""
EXPERIMENT 6 -- Cross-scale validation
======================================
(New at scale-up. This is the experiment that answers "is your Tier 1 result
 an artefact of your small test constellation?")

Question
--------
Every number in Tier 1 came from a 480-satellite shell we invented for speed.
Do the findings survive on constellations that companies are actually building?

We rerun the core measurements on four published designs:

    dev       480 sats   24 x 20    550 km   53.00 deg   (our Tier 1 shell)
    telesat   351 sats   27 x 13   1015 km   98.98 deg   (near-polar, high)
    kuiper   1156 sats   34 x 34    630 km   51.90 deg
    starlink 1584 sats   72 x 22    550 km   53.00 deg

The Telesat shell is deliberately the odd one out: fewer satellites, much
higher, and near-polar rather than inclined. If a conclusion holds on both
Starlink and Telesat, it is a property of the protocol rather than of one
geometry.

What we measure per constellation
---------------------------------
  path length        how many hops a real intercontinental route takes
  latency            end-to-end delay
  header size        T-CRH bytes, which is driven by path length
  optimal slack      does the S = 1.2 finding hold?
  deviation floor    the irreducible rate at very loose deadlines
"""

import random
import collections
import matplotlib.pyplot as plt
import networkx as nx

import scale
import common
from common import save, style, FLOWS
from scheduler import generate_schedules
from simulator import simulate_flow, summarise
from header import tcrh_size, crh16_size, srh_size

PRESET_ORDER = ['telesat', 'dev', 'kuiper', 'starlink']
SLACKS = [1.0, 1.1, 1.15, 1.2, 1.25, 1.3, 1.5, 2.0, 3.0]
NUM_PACKETS = 250
PACKET_INTERVAL_MS = 300


def measure_one(preset):
    """Reconfigure to a preset and take every measurement we care about."""
    n_sats = scale.use_preset(preset, verbose=False)
    scale.install_fast_topology(verbose=False)

    times, sat_pos, gs_pos, graphs = common.setup(verbose=False)

    # ---- path length and latency over all flows and the whole window ----
    hops, lats = [], []
    for flow in FLOWS:
        for g in graphs[::10]:
            try:
                p = nx.shortest_path(g, flow[0], flow[1], weight='weight')
                l = nx.shortest_path_length(g, flow[0], flow[1], weight='weight')
            except nx.NetworkXNoPath:
                continue
            hops.append(len(p) - 1)
            lats.append(l)

    mean_hops = sum(hops) / len(hops)
    mean_lat = sum(lats) / len(lats)

    # ---- does S = 1.2 still win? ----
    flow = FLOWS[0]
    fps, dets = [], []
    for s in SLACKS:
        sch = generate_schedules(times, sat_pos, gs_pos, [flow], slack_factor=s)

        first = min(sch.keys())
        path = sch[first][flow]['path']
        sat_hops = [(a, b) for a, b in zip(path[:-1], path[1:])
                    if isinstance(a, int) and isinstance(b, int)]
        bad = frozenset(sat_hops[len(sat_hops) // 2])

        clean = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                              NUM_PACKETS, PACKET_INTERVAL_MS,
                              rng=random.Random(1))
        deg = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                            NUM_PACKETS, PACKET_INTERVAL_MS,
                            degraded_links={bad: 1.5}, rng=random.Random(1))

        fps.append(summarise(clean)['deviation_rate'] * 100)
        hit = [r for r in deg if r.get('hit_degraded')]
        caught = [r for r in hit if r.get('deviated')]
        dets.append(len(caught) / len(hit) * 100 if hit else 0.0)

    j = [d - f for d, f in zip(dets, fps)]
    best_slack = SLACKS[j.index(max(j))]

    # ---- the irreducible floor: deviations at a very loose deadline ----
    sch_loose = generate_schedules(times, sat_pos, gs_pos, [flow],
                                   slack_factor=5.0)
    loose = simulate_flow(times, graphs, sat_pos, gs_pos, sch_loose, flow,
                          NUM_PACKETS, PACKET_INTERVAL_MS,
                          rng=random.Random(1))
    reasons = collections.Counter(r.get('deviation_reason') for r in loose)
    floor = reasons.get('link_failed', 0) / len(loose) * 100

    h = int(round(mean_hops))
    return {
        'preset': preset,
        'name': scale.PRESETS[preset]['name'],
        'sats': n_sats,
        'mean_hops': mean_hops,
        'max_hops': max(hops),
        'mean_latency_ms': mean_lat,
        'tcrh_bytes': tcrh_size(h),
        'crh_bytes': crh16_size(h),
        'srh_bytes': srh_size(h),
        'best_slack': best_slack,
        'false_positives': fps,
        'detections': dets,
        'floor': floor,
    }


def run():
    print("EXPERIMENT 6: cross-scale validation")

    rows = []
    for preset in PRESET_ORDER:
        print(f"\n  --- {scale.describe(preset)}")
        r = measure_one(preset)
        rows.append(r)
        print(f"      mean {r['mean_hops']:.1f} hops (max {r['max_hops']}), "
              f"{r['mean_latency_ms']:.1f} ms, "
              f"T-CRH {r['tcrh_bytes']} B, "
              f"best S = {r['best_slack']}, floor {r['floor']:.1f}%")

    style()
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    ax1, ax2, ax3, ax4 = axes.flatten()

    # short labels: the full names overlap on a shared x-axis
    names = [f"{r['name'].split()[0]}\n({r['sats']} sats)" for r in rows]
    colours = ['#8e44ad', '#7f8c8d', '#2471a3', '#c0392b']

    # --- 1: path length grows with constellation size ---
    ax1.bar(names, [r['mean_hops'] for r in rows], color=colours, width=0.6)
    for i, r in enumerate(rows):
        ax1.text(i, r['mean_hops'] + 0.3, f"{r['mean_hops']:.1f}",
                 ha='center', fontweight='bold')
    ax1.set_ylabel('Mean hops per intercontinental route')
    ax1.set_title('Denser constellations mean longer paths')
    ax1.tick_params(axis='x', labelsize=9.5)

    # --- 2: which drives header size ---
    width = 0.26
    xs = range(len(rows))
    ax2.bar([x - width for x in xs], [r['crh_bytes'] for r in rows],
            width, label='CRH-16 (RFC 9631)', color='#2471a3')
    ax2.bar(list(xs), [r['tcrh_bytes'] for r in rows],
            width, label='T-CRH (ours)', color='#c0392b')
    ax2.bar([x + width for x in xs], [r['srh_bytes'] for r in rows],
            width, label='SRv6 SRH', color='#7f8c8d')
    ax2.set_xticks(list(xs))
    ax2.set_xticklabels(names, fontsize=9.5)
    ax2.set_ylabel('Routing header size (bytes)')
    ax2.set_title('Header cost scales with path length')
    ax2.legend(fontsize=9)

    # --- 3: does the slack finding hold everywhere? ---
    for r, c in zip(rows, colours):
        ax3.plot(SLACKS, r['false_positives'], 'o-', lw=2, ms=5, color=c,
                 label=f"{r['name'].split()[0]} ({r['sats']} sats)")
    ax3.set_xlabel('Slack factor S')
    ax3.set_ylabel('False deviation rate (%)')
    ax3.set_title('The trade-off has the same shape at every scale')
    ax3.legend(fontsize=9)

    # --- 4: the irreducible floor ---
    bars = ax4.bar(names, [r['floor'] for r in rows], color=colours, width=0.6)
    for b, r in zip(bars, rows):
        ax4.text(b.get_x() + b.get_width() / 2, r['floor'] + 0.4,
                 f"{r['floor']:.1f}%", ha='center', fontweight='bold')
    ax4.set_ylabel('Stale-path deviations at S = 5.0 (%)')
    ax4.set_title('The floor no deadline can fix (see Experiment 7)')
    ax4.tick_params(axis='x', labelsize=9.5)

    fig.suptitle('Experiment 6: validating the Tier 1 findings on four real '
                 'constellation designs',
                 fontsize=14, fontweight='bold', y=0.995)
    save(fig, 'exp6_scale_validation.png')

    print("\n  === Summary table for the report ===")
    print(f"  {'constellation':<26} {'sats':>5} {'hops':>6} {'lat ms':>8} "
          f"{'T-CRH':>7} {'best S':>7} {'floor':>7}")
    for r in rows:
        print(f"  {r['name']:<26} {r['sats']:>5} {r['mean_hops']:>6.1f} "
              f"{r['mean_latency_ms']:>8.1f} {r['tcrh_bytes']:>6}B "
              f"{r['best_slack']:>7} {r['floor']:>6.1f}%")

    slacks_found = {r['best_slack'] for r in rows}
    if len(slacks_found) == 1:
        print(f"\n  VALIDATED: S = {slacks_found.pop()} is optimal on all four "
              f"constellations.")
    else:
        print(f"\n  Optimal S varies across constellations: {sorted(slacks_found)}")

    return rows


if __name__ == '__main__':
    run()
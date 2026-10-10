"""
EXPERIMENT 4 -- Failure resilience
==================================

Question
--------
When inter-satellite links genuinely break, does the Deviation_Flag plus
geographic fallback actually save the traffic?

We inject random ISL failures at increasing rates and compare:

  A. T-CRH WITH the geographic fallback   (our full design)
  B. T-CRH WITHOUT any fallback           (pure deterministic schedule)

B is the strawman that our own original pitch described before we noticed the
problem: a purely deterministic network is brittle, because a single broken
link on the pre-computed path kills the packet.
"""

import random
import matplotlib.pyplot as plt

from common import setup, save, style, FLOWS
from topology import ISL_PAIRS, build_graph
from scheduler import generate_schedules
from simulator import simulate_flow, summarise

FAILURE_RATES = [0.0, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20]
SLACK = 1.2               # the operating point chosen in Experiment 1
NUM_PACKETS = 200
PACKET_INTERVAL_MS = 500
NUM_TRIALS = 5            # repeat with different random failures, then average


def random_failures(rate, rng):
    """Pick a random subset of inter-satellite links to break."""
    n = int(len(ISL_PAIRS) * rate)
    chosen = rng.sample(ISL_PAIRS, n)
    return {frozenset({a, b}) for a, b, _ in chosen}


def run():
    print("EXPERIMENT 4: failure resilience")
    times, sat_pos, gs_pos, graphs = setup()

    schedules = {f: generate_schedules(times, sat_pos, gs_pos, [f],
                                       slack_factor=SLACK) for f in FLOWS}

    with_fb, without_fb, fb_share = [], [], []

    for rate in FAILURE_RATES:
        d_with, d_without, used_fb = [], [], []

        for trial in range(NUM_TRIALS):
            rng = random.Random(1000 + trial)
            failed = random_failures(rate, rng)

            # Apply the failures to the topology. A broken link only ever
            # REMOVES edges, so copying the healthy graph and deleting them is
            # far cheaper than recomputing every distance and elevation from
            # scratch -- which matters a lot at 1584 satellites, where this
            # loop runs 120 x 5 x 7 = 4200 times.
            try:
                from scale import graphs_with_failures
                broken_graphs = graphs_with_failures(graphs, failed)
            except ImportError:
                broken_graphs = [
                    build_graph(sat_pos[i], gs_pos[i], failed_links=failed)
                    for i in range(len(times))
                ]

            for flow in FLOWS:
                sch = schedules[flow]

                a = simulate_flow(times, broken_graphs, sat_pos, gs_pos, sch,
                                  flow, NUM_PACKETS, PACKET_INTERVAL_MS,
                                  failed_links=failed,
                                  rng=random.Random(trial * 7 + 1))
                b = simulate_flow(times, broken_graphs, sat_pos, gs_pos, sch,
                                  flow, NUM_PACKETS, PACKET_INTERVAL_MS,
                                  failed_links=failed, disable_fallback=True,
                                  rng=random.Random(trial * 7 + 1))

                sa, sb = summarise(a), summarise(b)
                d_with.append(sa['delivery_rate'] * 100)
                d_without.append(sb['delivery_rate'] * 100)
                used_fb.append(sa['via_fallback'] / max(sa['total'], 1) * 100)

        with_fb.append(sum(d_with) / len(d_with))
        without_fb.append(sum(d_without) / len(d_without))
        fb_share.append(sum(used_fb) / len(used_fb))

        print(f"  {rate*100:5.1f}% links failed -> "
              f"with fallback {with_fb[-1]:5.1f}%  |  "
              f"without fallback {without_fb[-1]:5.1f}%  |  "
              f"rescued by fallback {fb_share[-1]:5.1f}%")

    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    xs = [r * 100 for r in FAILURE_RATES]

    ax1.plot(xs, with_fb, 'o-', lw=2.6, ms=7, color='#27ae60',
             label='T-CRH + geographic fallback (ours)')
    ax1.plot(xs, without_fb, 's--', lw=2.2, ms=6, color='#c0392b',
             label='T-CRH, pure schedule, no fallback')
    ax1.fill_between(xs, without_fb, with_fb, alpha=0.15, color='#27ae60')
    ax1.set_xlabel('Percentage of inter-satellite links broken (%)')
    ax1.set_ylabel('Packet delivery rate (%)')
    ax1.set_title('The fail-safe is what makes the design usable')
    ax1.legend(fontsize=9.5, loc='lower left')
    ax1.set_ylim(-4, 104)

    mid = len(xs) // 2
    gap = with_fb[mid] - without_fb[mid]
    ax1.annotate(f'+{gap:.0f} percentage points\nrecovered',
                 xy=(xs[mid], (with_fb[mid] + without_fb[mid]) / 2),
                 xytext=(xs[mid] - 1.5, 45), fontsize=9.5,
                 color='#27ae60', fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color='#27ae60', lw=1.4))

    ax2.bar(xs, fb_share, width=1.1, color='#2471a3')
    ax2.set_xlabel('Percentage of inter-satellite links broken (%)')
    ax2.set_ylabel('Packets delivered via fallback (%)')
    ax2.set_title('How often the Deviation_Flag is doing the work')

    fig.suptitle('Experiment 4: resilience to unmodelled link failure',
                 fontsize=14, fontweight='bold', y=1.02)
    save(fig, 'exp4_failure_resilience.png')

    return {'rates': FAILURE_RATES, 'with_fallback': with_fb,
            'without_fallback': without_fb}


if __name__ == '__main__':
    run()
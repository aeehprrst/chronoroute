"""
EXPERIMENT 1 -- Slack factor sweep  (THE HEADLINE RESULT)
========================================================

Question
--------
Each hop's deadline is set to  SLACK * predicted_delay.  What should SLACK be?

The trade-off
-------------
  SLACK too tight -> normal queueing jitter and schedule staleness push
                     healthy packets past their deadline. They deviate to the
                     fallback path for no reason. This is a FALSE POSITIVE.

  SLACK too loose -> a link that has genuinely degraded (solar interference,
                     link-layer retransmission, congestion) stays inside its
                     budget, so nothing notices. This is a MISSED DETECTION.

Note that a degraded link is still UP. A link-state check cannot see it.
The deadline is the ONLY mechanism that can, which is precisely why we put
deadlines in the header.

We measure both sides and look for the knee.
"""

import random
import matplotlib.pyplot as plt

from common import setup, save, style, FLOWS
from scheduler import generate_schedules
from simulator import simulate_flow, summarise

SLACKS = [1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5, 1.75, 2.0, 2.5, 3.0]
DEGRADATIONS = [1.2, 1.5, 2.0, 3.0]      # severity multipliers to test
NUM_PACKETS = 400
PACKET_INTERVAL_MS = 250


def pick_link_on_path(schedules, flow):
    """Choose a middle inter-satellite link from the flow's own path to degrade."""
    first_epoch = min(schedules.keys())
    path = schedules[first_epoch][flow]['path']
    sat_hops = [(a, b) for a, b in zip(path[:-1], path[1:])
                if isinstance(a, int) and isinstance(b, int)]
    a, b = sat_hops[len(sat_hops) // 2]
    return frozenset({a, b})


def run():
    print("EXPERIMENT 1: slack factor sweep")
    times, sat_pos, gs_pos, graphs = setup()

    flow = FLOWS[0]
    false_positive_rate = []
    detection = {m: [] for m in DEGRADATIONS}
    latency_clean = []

    for slack in SLACKS:
        sch = generate_schedules(times, sat_pos, gs_pos, [flow],
                                 slack_factor=slack)
        bad_link = pick_link_on_path(sch, flow)

        # --- healthy network: any deviation is a FALSE POSITIVE ---
        clean = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                              NUM_PACKETS, PACKET_INTERVAL_MS,
                              rng=random.Random(1))
        s = summarise(clean)
        false_positive_rate.append(s['deviation_rate'] * 100)
        latency_clean.append(s['mean_latency_ms'])

        # --- degraded network: deviation is a CORRECT DETECTION ---
        for m in DEGRADATIONS:
            deg = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                                NUM_PACKETS, PACKET_INTERVAL_MS,
                                degraded_links={bad_link: m},
                                rng=random.Random(1))
            hit = [r for r in deg if r.get('hit_degraded')]
            caught = [r for r in hit if r.get('deviated')]
            rate = (len(caught) / len(hit) * 100) if hit else 0.0
            detection[m].append(rate)

        print(f"  slack={slack:<5} false-positives={false_positive_rate[-1]:5.1f}%  "
              f"detect(1.5x)={detection[1.5][-1]:5.1f}%  "
              f"latency={latency_clean[-1]:.2f}ms")

    # ------------------------------------------------------------ plot
    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    ax1.plot(SLACKS, false_positive_rate, 'o-', color='#c0392b', lw=2.2,
             ms=6, label='False positives (healthy network)')
    ax1.plot(SLACKS, detection[1.5], 's-', color='#2471a3', lw=2.2,
             ms=6, label='Detected degradation (1.5x slow link)')
    ax1.set_xlabel('Slack factor S  (deadline = S x predicted delay)')
    ax1.set_ylabel('Percentage of packets (%)')
    ax1.set_title('The deadline tightness trade-off')
    ax1.legend(loc='center right')
    ax1.set_ylim(-4, 104)

    # Pick the operating point the standard way: maximise Youden's J, i.e.
    # (detection rate - false positive rate). This is the same criterion used
    # to choose a threshold on an ROC curve.
    j_scores = [d - fp for d, fp in zip(detection[1.5], false_positive_rate)]
    knee = SLACKS[j_scores.index(max(j_scores))]
    ax1.axvline(knee, color='#27ae60', ls='--', lw=1.8)
    ax1.annotate(f'best operating point\nS = {knee}', xy=(knee, 55),
                 xytext=(knee + 0.45, 60), color='#27ae60',
                 fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color='#27ae60'))

    for m, style_ in zip(DEGRADATIONS, ['o-', 's-', '^-', 'd-']):
        ax2.plot(SLACKS, detection[m], style_, lw=2, ms=5,
                 label=f'{m}x slower link')
    ax2.plot(SLACKS, false_positive_rate, 'k:', lw=2.2,
             label='False positives')
    ax2.set_xlabel('Slack factor S')
    ax2.set_ylabel('Detection rate (%)')
    ax2.set_title('Detection vs degradation severity')
    ax2.legend(fontsize=9)
    ax2.set_ylim(-4, 104)

    fig.suptitle('Experiment 1: choosing the per-hop deadline budget',
                 fontsize=14, fontweight='bold', y=1.02)
    save(fig, 'exp1_slack_sweep.png')

    print(f"\n  RESULT: best operating point S = {knee} "
          f"(max detection - false positives)")
    print(f"  At S={knee}: {false_positive_rate[SLACKS.index(knee)]:.1f}% false "
          f"positives, {detection[2.0][SLACKS.index(knee)]:.1f}% of 2x "
          f"degradations detected.")

    return {'slacks': SLACKS, 'false_positives': false_positive_rate,
            'detection': detection, 'knee': knee}


if __name__ == '__main__':
    run()
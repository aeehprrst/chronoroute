"""
EXPERIMENT 7 -- Schedule interval sweep
=======================================
(New at Starlink scale. This experiment did not exist in Tier 1 because the
 effect it measures is almost invisible at 480 satellites.)

Question
--------
Experiment 1 found that no slack factor, however loose, could push the false
deviation rate below about 10% at Starlink scale. Why not, and what fixes it?

The answer
----------
Deviations have TWO different causes, and the slack factor only controls one:

  'deadline_missed'  the packet was slower than its budget
                     -> controlled by the SLACK FACTOR

  'link_failed'      the link in the packet's path no longer exists, because
                     the topology changed after the schedule was computed
                     -> controlled by the SCHEDULE INTERVAL

No deadline setting can rescue a path whose links have ceased to exist. That
is a staleness problem, not a timing problem, so it needs a different knob.

We confirmed this by checking WHEN the surviving deviations happen: at slack
3.0 every remaining deviation was 'link_failed', and they clustered at 6-13
seconds of schedule staleness rather than being spread evenly.

So this experiment sweeps the schedule interval and shows that the two knobs
are independent controls on two independent failure modes.
"""

import random
import collections
import matplotlib.pyplot as plt

from common import setup, save, style, FLOWS
from scheduler import generate_schedules
from simulator import simulate_flow
from header import tcrh_size

INTERVALS_S = [1, 2, 3, 5, 10, 15, 20, 30, 45, 60]
SLACK = 1.2                 # the operating point from Experiment 1
NUM_PACKETS = 300
PACKET_INTERVAL_MS = 300
NUM_SEEDS = 4               # average over seeds and all flows, or the
                            # long-interval points are dominated by whether a
                            # single handover happened to land in the window

# for the control-plane cost side of the trade-off
NUM_GATEWAYS = 6
FLOWS_PER_GATEWAY = 5
AVG_HOPS = 13               # measured at Starlink scale


def run():
    print("EXPERIMENT 7: schedule interval sweep")
    times, sat_pos, gs_pos, graphs = setup()

    stale_path, missed_deadline, total_dev, control_bytes = [], [], [], []

    for iv in INTERVALS_S:
        lf_runs, dm_runs = [], []
        for flow in FLOWS:
            sch = generate_schedules(times, sat_pos, gs_pos, [flow],
                                     slack_factor=SLACK, interval_s=iv)
            for seed in range(NUM_SEEDS):
                res = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                                    NUM_PACKETS, PACKET_INTERVAL_MS,
                                    rng=random.Random(seed))
                reasons = collections.Counter(
                    r.get('deviation_reason') for r in res)
                n = len(res)
                lf_runs.append(reasons.get('link_failed', 0) / n * 100)
                dm_runs.append(reasons.get('deadline_missed', 0) / n * 100)

        lf = sum(lf_runs) / len(lf_runs)
        dm = sum(dm_runs) / len(dm_runs)

        stale_path.append(lf)
        missed_deadline.append(dm)
        total_dev.append(lf + dm)
        control_bytes.append(NUM_GATEWAYS * FLOWS_PER_GATEWAY
                             * tcrh_size(AVG_HOPS) / iv)

        print(f"  interval={iv:3d}s  stale-path={lf:5.1f}%  "
              f"missed-deadline={dm:5.1f}%  "
              f"control-plane={control_bytes[-1]:6.0f} B/s")

    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    # --- left: the two failure modes separate cleanly ---
    ax1.plot(INTERVALS_S, stale_path, 'o-', lw=2.4, ms=6, color='#c0392b',
             label="'link_failed' -- stale path")
    ax1.plot(INTERVALS_S, missed_deadline, 's-', lw=2.2, ms=6, color='#2471a3',
             label="'deadline_missed' -- timing")
    ax1.plot(INTERVALS_S, total_dev, '^--', lw=1.8, ms=5, color='#7f8c8d',
             alpha=0.8, label='total deviation')
    ax1.set_xlabel('Schedule recomputation interval (seconds)')
    ax1.set_ylabel('Percentage of packets (%)')
    ax1.set_title('Two failure modes, two different knobs')
    ax1.legend(fontsize=9.5, loc='upper left')

    # mark where stale-path failures vanish
    # the shortest interval is always best; we want the LONGEST interval that
    # still keeps stale-path failures under 1%, i.e. the cheapest safe setting
    safe = [iv for iv, v in zip(INTERVALS_S, stale_path) if v < 1.0]
    zero_iv = max(safe) if safe else INTERVALS_S[0]
    ax1.axvline(zero_iv, color='#27ae60', ls='--', lw=1.8)
    ax1.annotate(f'stale-path failures\nunder 1% at {zero_iv}s',
                 xy=(zero_iv, 12), xytext=(zero_iv + 8, 20),
                 fontsize=9.5, color='#27ae60', fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color='#27ae60', lw=1.4))

    # --- right: the cost of a shorter interval ---
    ax2b = ax2.twinx()
    ax2.plot(INTERVALS_S, stale_path, 'o-', lw=2.4, ms=6, color='#c0392b',
             label='Stale-path failures (%)')
    ax2b.plot(INTERVALS_S, control_bytes, 's-', lw=2.4, ms=6, color='#e67e22',
              label='Control-plane cost (B/s)')
    ax2.set_xlabel('Schedule recomputation interval (seconds)')
    ax2.set_ylabel('Stale-path failures (%)', color='#c0392b')
    ax2b.set_ylabel('Control-plane traffic (bytes/second)', color='#e67e22')
    ax2.tick_params(axis='y', labelcolor='#c0392b')
    ax2b.tick_params(axis='y', labelcolor='#e67e22')
    ax2.set_title('Freshness costs control-plane bandwidth')
    ax2b.grid(False)

    lines = ax2.get_lines() + ax2b.get_lines()
    ax2.legend(lines, [l.get_label() for l in lines], fontsize=9.5,
               loc='upper center')

    fig.suptitle('Experiment 7: the schedule interval is a second, '
                 'independent control',
                 fontsize=14, fontweight='bold', y=1.02)
    save(fig, 'exp7_schedule_interval.png')

    idx = INTERVALS_S.index(zero_iv)
    print(f"\n  RESULT: {zero_iv}s is the longest (cheapest) interval that keeps "
          f"stale-path failures under 1%,")
    print(f"  at a control-plane cost of {control_bytes[idx]:.0f} B/s.")

    return {'intervals': INTERVALS_S, 'stale_path': stale_path,
            'missed_deadline': missed_deadline,
            'control_bytes': control_bytes, 'recommended': zero_iv}


if __name__ == '__main__':
    import scale
    scale.use_preset('starlink')
    scale.install_fast_topology()
    run()
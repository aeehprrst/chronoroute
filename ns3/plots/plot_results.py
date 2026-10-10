#!/usr/bin/env python3
"""
plot_results.py
---------------
Turns the two CSV files produced by bottleneck-experiment.cc into the figures
for the assignment.

    python3 plot_results.py            # *_v09.csv -> fig1_bandwidth_v09.png, fig2_bufferbloat_v09.png
    python3 plot_results.py --legacy   # the Assessment 6 CSVs -> fig*_legacy.png

v0.9 (2026-10-10, bug #19): the delay column is FlowMonitor's one-way delay
(delaySum / rxPackets), now named mean_one_way_delay_ms; the Assessment 6 CSVs
call the same number mean_delay_ms. Both are read; neither is an RTT.
"""

import csv
import os
import sys
import matplotlib
matplotlib.use('Agg')          # no GUI needed inside WSL
import matplotlib.pyplot as plt


def read_csv(path):
    """Read a CSV into a dict of columns, converting numbers where possible."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    cols = {}
    for key in rows[0]:
        vals = []
        for r in rows:
            try:
                vals.append(float(r[key]))
            except ValueError:
                vals.append(r[key])
        cols[key] = vals
    return cols


def one_way_delay(d):
    """The mean one-way delay column, under its v0.9 name or the Assessment 6 one."""
    return d['mean_one_way_delay_ms'] if 'mean_one_way_delay_ms' in d else d['mean_delay_ms']


def plot_bandwidth(path='bottleneck_results.csv', out='fig1_bandwidth.png'):
    d = read_csv(path)
    bw = d['bottleneck_mbps']
    gp = d['goodput_mbps']
    drops = d['queue_drops']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    # --- goodput vs capacity ---
    ax1.plot(bw, bw, 'k--', lw=1.5, alpha=0.6, label='link capacity (ideal)')
    ax1.plot(bw, gp, 'o-', lw=2.4, ms=7, color='#c0392b',
             label='measured TCP goodput')
    ax1.set_xlabel('Bottleneck capacity (Mbps)')
    ax1.set_ylabel('Total goodput (Mbps)')
    ax1.set_title('TCP fills the bottleneck but never exceeds it')
    ax1.legend()
    ax1.grid(alpha=0.3)

    # --- drops vs capacity ---
    ax2.bar(bw, drops, width=[max(0.6, b * 0.12) for b in bw], color='#2471a3')
    ax2.set_xlabel('Bottleneck capacity (Mbps)')
    ax2.set_ylabel('Packets dropped at the bottleneck queue')
    ax2.set_title('Drops vanish once capacity exceeds offered load')
    ax2.grid(alpha=0.3, axis='y')

    fig.suptitle('Experiment A: TCP goodput and loss vs bottleneck capacity',
                 fontsize=13, fontweight='bold', y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved {os.path.abspath(out)}")

    util = [g / b * 100 for g, b in zip(gp, bw)]
    print(f"  utilisation range: {min(util):.1f}% to {max(util):.1f}%")


def plot_queue(path='queue_results.csv', out='fig2_bufferbloat.png'):
    d = read_csv(path)
    # queue column is like '50p'
    q = [int(str(v).rstrip('p')) for v in d['queue']]
    drops = d['queue_drops']
    delay = one_way_delay(d)
    gp = d['goodput_mbps']

    fig, ax1 = plt.subplots(figsize=(9, 5.5))
    ax2 = ax1.twinx()

    l1 = ax1.plot(q, drops, 'o-', lw=2.4, ms=7, color='#c0392b',
                  label='packets dropped')
    l2 = ax2.plot(q, delay, 's-', lw=2.4, ms=7, color='#e67e22',
                  label='mean one-way delay')

    ax1.set_xscale('log', base=2)
    ax1.set_xticks(q)
    ax1.set_xticklabels([str(v) for v in q])
    ax1.set_xlabel('Bottleneck queue size (packets)')
    ax1.set_ylabel('Packets dropped', color='#c0392b')
    ax2.set_ylabel('Mean one-way delay (ms)', color='#e67e22')
    ax1.tick_params(axis='y', labelcolor='#c0392b')
    ax2.tick_params(axis='y', labelcolor='#e67e22')
    ax1.grid(alpha=0.3)
    ax2.grid(False)

    lines = l1 + l2
    ax1.legend(lines, [l.get_label() for l in lines], loc='center right')

    ax1.set_title('Experiment B: bufferbloat -- a bigger buffer trades\n'
                  'loss for latency, and goodput barely moves',
                  fontsize=12, fontweight='bold')

    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved {os.path.abspath(out)}")
    print(f"  goodput stayed within "
          f"{min(gp):.2f}-{max(gp):.2f} Mbps while delay went "
          f"{min(delay):.0f} -> {max(delay):.0f} ms")


if __name__ == '__main__':
    # v0.9 files by default; the Assessment 6 figures are never overwritten
    suffix = '' if '--legacy' in sys.argv[1:] else '_v09'
    tag = '_legacy' if suffix == '' else suffix
    print("Plotting results...")
    bw_csv, q_csv = f'bottleneck_results{suffix}.csv', f'queue_results{suffix}.csv'
    if os.path.exists(bw_csv):
        plot_bandwidth(bw_csv, f'fig1_bandwidth{tag}.png')
    else:
        print(f"  {bw_csv} not found -- run the bandwidth sweep first")
    if os.path.exists(q_csv):
        plot_queue(q_csv, f'fig2_bufferbloat{tag}.png')
    else:
        print(f"  {q_csv} not found -- run the queue sweep first")
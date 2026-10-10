#!/usr/bin/env python3
"""
plot_tcrh.py
------------
Plots the T-CRH results written by tcrh-experiment.cc.

    python3 plot_tcrh.py            # v0.9 results  -> fig1_tcrh_size_v09.png, fig2_tcrh_sweep_v09.png
    python3 plot_tcrh.py --legacy   # Assessment 8 CSVs -> fig*_legacy.png (never the original PNGs)

v0.9 (2026-10-10): the sweep is scored on PAIRED packets (bug #21). The same
packets, with the same random jitter, run through a healthy network, a network
with the n3-n4 link slowed, and a null-fault network; a "detection" is a packet
flagged with the fault and not without it. The Assessment 8 figure plotted
every flag in the degraded phase as a detection, which counted jitter false
alarms as detections; its labels now say so (--legacy). See ns3_rescore_v09.md.
"""

import csv
import math
import os
import sys
import matplotlib
matplotlib.use('Agg')          # render to file; no GUI under WSL
import matplotlib.pyplot as plt

IPV6_BASE = 40
REF_HOPS = 10

# chart colours (validated categorical slots 1-3; aqua is below 3:1 contrast,
# so every line also has its own marker and a legend/direct label)
BLUE, ORANGE, AQUA = '#2a78d6', '#eb6834', '#1baf7a'
GREY = '#8a8984'               # the old score: recessive, dashed
INK2 = '#52514e'


def read(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    cols = {}
    for k in rows[0]:
        cols[k] = [float(r[k]) for r in rows]   # float('nan') parses 'nan'
    return cols


def plot_sizes(path='tcrh_sizes_v09.csv', out='fig1_tcrh_size_v09.png'):
    d = read(path)
    hops, crh, tcrh, srh = d['hops'], d['crh16_bytes'], d['tcrh_bytes'], d['srh_bytes']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    ax1.plot(hops, srh, 'o-', lw=2, ms=5, color='#7f8c8d', label='SRv6 SRH')
    ax1.plot(hops, tcrh, 's-', lw=2.6, ms=6, color='#c0392b', label='T-CRH (ours)')
    ax1.plot(hops, crh, '^-', lw=2, ms=5, color='#2471a3', label='CRH-16 (RFC 9631)')
    ax1.set_xlabel('Hops in the path')
    ax1.set_ylabel('Routing header size (bytes)')
    ax1.set_title('What the deadlines cost')
    ax1.legend()
    ax1.grid(alpha=0.3)
    ax1.set_xticks(range(0, 21, 2))

    i = hops.index(REF_HOPS)
    ax1.annotate(f'+{int(tcrh[i]-crh[i])} B at {REF_HOPS} hops\n= the time information',
                 xy=(REF_HOPS, (tcrh[i] + crh[i]) / 2),
                 xytext=(11.5, 130), fontsize=9.5, color='#c0392b',
                 fontweight='bold',
                 arrowprops=dict(arrowstyle='<->', color='#c0392b', lw=1.4))

    payloads = [40, 64, 128, 256, 512, 1024, 1400]
    for label, size, colour, mk in [('SRv6 SRH', srh[i], '#7f8c8d', 'o'),
                                    ('T-CRH', tcrh[i], '#c0392b', 's'),
                                    ('CRH-16', crh[i], '#2471a3', '^')]:
        ys = [size / (IPV6_BASE + size + p) * 100 for p in payloads]
        ax2.plot(payloads, ys, marker=mk, lw=2.2, ms=6, color=colour, label=label)
    ax2.set_xscale('log', base=2)
    ax2.set_xticks(payloads)
    ax2.set_xticklabels([str(p) for p in payloads])
    ax2.set_xlabel('Payload size (bytes)')
    ax2.set_ylabel('Header as % of the packet')
    ax2.set_title(f'Overhead share on a {REF_HOPS}-hop path')
    ax2.legend()
    ax2.grid(alpha=0.3)

    fig.suptitle('T-CRH header cost against the standard it extends',
                 fontsize=13, fontweight='bold', y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved {os.path.abspath(out)}")
    print(f"  at {REF_HOPS} hops: CRH-16 {int(crh[i])}B, T-CRH {int(tcrh[i])}B "
          f"(+{int(tcrh[i]-crh[i])}B), SRv6 {int(srh[i])}B")


def _label_last(ax, xs, ys, text, dy=0.0):
    """Direct label just above the last finite point of a line (ink colour, kept inside the axes)."""
    pts = [(x, y) for x, y in zip(xs, ys) if not math.isnan(y)]
    if pts:
        x, y = pts[-1]
        ax.annotate(text, xy=(x, y), xytext=(0, dy), textcoords='offset points',
                    fontsize=9, color=INK2, va='bottom', ha='right')


def plot_sweep_v09(path='tcrh_sweep_v09.csv', null_path='tcrh_sweep_v09_nullfault.csv',
                   small_path='tcrh_sweep_v09_degraded25.csv', out='fig2_tcrh_sweep_v09.png'):
    d = read(path)
    s = d['slack']
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5.2))

    # ---- left: the paired score for the main fault (and a smaller one) ----
    ax1.fill_between(s, d['fp_ci_lo'], d['fp_ci_hi'], color=ORANGE, alpha=0.15, lw=0)
    ax1.plot(s, d['fp_pct'], 'o-', lw=2, ms=8, color=ORANGE,
             label='False alarms (healthy network)')
    ax1.fill_between(s, d['detect_ci_lo'], d['detect_ci_hi'], color=BLUE, alpha=0.15, lw=0)
    ax1.plot(s, d['detect_attributed_pct'], 's-', lw=2, ms=8, color=BLUE,
             label=f"Detections, n3-n4 slowed 20 -> {d['degraded_ms'][0]:g} ms (paired)")
    if small_path and os.path.exists(small_path):
        e = read(small_path)
        ax1.plot(e['slack'], e['detect_attributed_pct'], 'D-', lw=2, ms=8, color=AQUA,
                 label=f"Detections, slowed 20 -> {e['degraded_ms'][0]:g} ms (paired)")
    ax1.plot(s, d['raw_detect_pct'], '--', lw=1.5, color=GREY,
             label=f"Old score for the {d['degraded_ms'][0]:g} ms fault (every flag)")
    ax1.set_xlabel('Slack factor S  (deadline = S x predicted delay)')
    ax1.set_ylabel('Percentage of packets (%)')
    n = int(d['packets'][0])
    ax1.set_title(f'Paired score, {n} packets per S (bands: 95% CI)')
    ax1.set_ylim(-4, 104)
    ax1.legend(loc='center right', fontsize=8.5)
    ax1.grid(alpha=0.3)

    # ---- right: the null-fault control, where nothing can be detected ----
    if null_path and os.path.exists(null_path):
        z = read(null_path)
        paired = [100.0 * a / p for a, p in zip(z['attributed'], z['packets'])]
        ax2.plot(z['slack'], z['raw_detect_pct'], 'o--', lw=2, ms=8, color=GREY,
                 label='Old score: "detections"')
        ax2.plot(z['slack'], paired, 's-', lw=2, ms=8, color=BLUE,
                 label='Paired score: detections')
        _label_last(ax2, z['slack'], paired, '0 at every S', dy=9)
        ax2.set_title('Null fault (link "slowed" 20 -> 20 ms): nothing to detect')
        ax2.set_xlabel('Slack factor S')
        ax2.set_ylabel('Percentage of packets (%)')
        ax2.set_ylim(-4, 104)
        ax2.legend(loc='upper right', fontsize=8.5)
        ax2.grid(alpha=0.3)
    else:
        ax2.axis('off')

    fig.suptitle('T-CRH deadline detection in ns-3, re-scored on paired packets (v0.9)',
                 fontsize=13, fontweight='bold', y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved {os.path.abspath(out)}")


def plot_sweep_legacy(path='tcrh_sweep.csv', out='fig2_tcrh_sweep_legacy.png'):
    """The Assessment 8 sweep, labelled for what it measured (unpaired phases)."""
    d = read(path)
    s, fp, det = d['slack'], d['false_positive_pct'], d['detection_pct']
    delivered = d['delivered_pct']

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

    ax1.plot(s, fp, 'o-', lw=2.4, ms=7, color='#c0392b',
             label='Flagged, healthy phase (false alarms)')
    ax1.plot(s, det, 's-', lw=2.4, ms=7, color='#2471a3',
             label='Flagged, slow-link phase (NOT paired:\nincludes jitter false alarms)')
    ax1.set_xlabel('Slack factor S  (deadline = S x predicted delay)')
    ax1.set_ylabel('Percentage of packets (%)')
    ax1.set_title('Assessment 8 score (confounded; see ns3_rescore_v09.md)')
    ax1.legend(loc='center right')
    ax1.set_ylim(-4, 104)
    ax1.grid(alpha=0.3)

    ax2.plot(s, delivered, 'o-', lw=2.6, ms=7, color='#27ae60',
             label='Delivered (degraded network)')
    ax2.set_xlabel('Slack factor S')
    ax2.set_ylabel('Packets delivered (%)')
    ax2.set_title('The fail-safe keeps delivery at 100%\nwhatever the deadline setting')
    ax2.set_ylim(-4, 104)
    ax2.legend(loc='lower right')
    ax2.grid(alpha=0.3)

    fig.suptitle('T-CRH deadline detection in ns-3 (Assessment 8: 1 ms truncation, unpaired)',
                 fontsize=13, fontweight='bold', y=1.01)
    fig.tight_layout()
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  saved {os.path.abspath(out)}")


if __name__ == '__main__':
    if '--legacy' in sys.argv[1:]:
        print("Plotting the Assessment 8 T-CRH results (relabelled)...")
        jobs = (('tcrh_sizes.csv',
                 lambda: plot_sizes('tcrh_sizes.csv', 'fig1_tcrh_size_legacy.png')),
                ('tcrh_sweep.csv', plot_sweep_legacy))
    else:
        print("Plotting T-CRH v0.9 results...")
        jobs = (('tcrh_sizes_v09.csv', plot_sizes), ('tcrh_sweep_v09.csv', plot_sweep_v09))
    for f, fn in jobs:
        if os.path.exists(f):
            fn()
        else:
            print(f"  {f} missing -- run the simulation first")

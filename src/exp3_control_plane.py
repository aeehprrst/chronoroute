"""
EXPERIMENT 3 -- Control-plane cost
==================================

Question
--------
How much signalling traffic do we save by putting the route in the packet
instead of uploading tables to satellites?

Three models compared, all recomputing every SCHEDULE_INTERVAL_S seconds:

  1. TABLE UPLOAD (the FSA / Hypatia baseline)
     Every satellite receives a forwarding table entry for every destination,
     every schedule epoch. Cost grows with the number of satellites.

  2. LINK-STATE FLOODING (an OSPF-like reactive baseline)
     Every satellite floods its link state to every other satellite whenever
     the topology changes. Cost grows with satellites x neighbours.

  3. T-CRH (ours)
     Schedules go only to the handful of ground gateways that inject traffic.
     Satellites receive NOTHING. Cost is independent of constellation size.

Point 3 is the interesting one: our cost does not grow with the constellation.
"""

import matplotlib.pyplot as plt

from common import save, style
from header import tcrh_size
from scheduler import SCHEDULE_INTERVAL_S

CONSTELLATION_SIZES = [120, 240, 480, 960, 1584, 3200, 6400]

NUM_GATEWAYS = 6           # our six ground stations
NUM_DESTINATIONS = 6
FLOWS_PER_GATEWAY = 5
AVG_HOPS = 10

FIB_ENTRY_BYTES = 8        # destination ID + outgoing interface + metadata
LSA_BYTES = 32             # one link-state advertisement per neighbour
ISLS_PER_SAT = 4


def table_upload_bytes_per_sec(num_sats):
    """Baseline 1: upload a full FIB to every satellite each epoch."""
    per_epoch = num_sats * NUM_DESTINATIONS * FIB_ENTRY_BYTES
    return per_epoch / SCHEDULE_INTERVAL_S


def link_state_bytes_per_sec(num_sats):
    """
    Baseline 2: OSPF-like flooding. Each satellite originates an LSA per
    neighbour, and each LSA reaches every other node.
    """
    per_epoch = num_sats * ISLS_PER_SAT * LSA_BYTES * num_sats
    return per_epoch / SCHEDULE_INTERVAL_S


def tcrh_bytes_per_sec(num_sats):
    """
    Ours: one schedule entry per flow, delivered only to gateways.
    Independent of num_sats, which is the whole point.
    """
    per_epoch = NUM_GATEWAYS * FLOWS_PER_GATEWAY * tcrh_size(AVG_HOPS)
    return per_epoch / SCHEDULE_INTERVAL_S


def run():
    print("EXPERIMENT 3: control-plane cost")

    table = [table_upload_bytes_per_sec(n) for n in CONSTELLATION_SIZES]
    lstate = [link_state_bytes_per_sec(n) for n in CONSTELLATION_SIZES]
    ours = [tcrh_bytes_per_sec(n) for n in CONSTELLATION_SIZES]

    print(f"  {'sats':>6} {'link-state':>14} {'table upload':>14} {'T-CRH':>10} "
          f"{'saving vs table':>16}")
    for n, l, t, o in zip(CONSTELLATION_SIZES, lstate, table, ours):
        print(f"  {n:>6} {l:>12.0f} B/s {t:>12.0f} B/s {o:>8.0f} B/s "
              f"{t / o:>14.0f}x")

    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    ax1.plot(CONSTELLATION_SIZES, lstate, 'o-', lw=2, ms=6, color='#7f8c8d',
             label='Link-state flooding (OSPF-like)')
    ax1.plot(CONSTELLATION_SIZES, table, 's-', lw=2, ms=6, color='#e67e22',
             label='Table upload (FSA / Hypatia baseline)')
    ax1.plot(CONSTELLATION_SIZES, ours, '^-', lw=2.6, ms=7, color='#c0392b',
             label='T-CRH (ours) -- flat')
    ax1.set_xscale('log', base=2)
    ax1.set_yscale('log')
    ax1.set_xticks(CONSTELLATION_SIZES)
    ax1.set_xticklabels([str(n) for n in CONSTELLATION_SIZES], rotation=45)
    ax1.set_xlabel('Number of satellites in the constellation')
    ax1.set_ylabel('Control-plane traffic (bytes/second, log scale)')
    ax1.set_title('Control-plane cost vs constellation size')
    ax1.legend(fontsize=9.5, loc='upper left')

    # highlight the flatness
    ax1.annotate('independent of\nconstellation size',
                 xy=(CONSTELLATION_SIZES[-2], ours[-2]),
                 xytext=(300, ours[0] * 0.25),
                 fontsize=9.5, color='#c0392b', fontweight='bold',
                 arrowprops=dict(arrowstyle='->', color='#c0392b', lw=1.4))

    # --- right: bar chart at a realistic Starlink-shell size ---
    idx = CONSTELLATION_SIZES.index(1584)
    labels = ['Link-state\nflooding', 'Table\nupload', 'T-CRH\n(ours)']
    vals = [lstate[idx], table[idx], ours[idx]]
    bars = ax2.bar(labels, vals, color=['#7f8c8d', '#e67e22', '#c0392b'],
                   width=0.55)
    ax2.set_yscale('log')
    ax2.set_ylabel('Control-plane traffic (bytes/second, log scale)')
    ax2.set_title('At Starlink shell scale (1584 satellites)')
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, v * 1.35,
                 f'{v:,.0f} B/s', ha='center', fontsize=10, fontweight='bold')
    ax2.set_ylim(top=max(vals) * 8)

    fig.suptitle('Experiment 3: removing the control plane from the satellites',
                 fontsize=14, fontweight='bold', y=1.02)
    save(fig, 'exp3_control_plane.png')

    print(f"\n  At 1584 satellites T-CRH uses {table[idx] / ours[idx]:.0f}x less "
          f"than table upload and {lstate[idx] / ours[idx]:,.0f}x less than "
          f"link-state flooding.")

    return {'sizes': CONSTELLATION_SIZES, 'table': table,
            'link_state': lstate, 'tcrh': ours}


if __name__ == '__main__':
    run()
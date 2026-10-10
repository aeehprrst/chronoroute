"""
EXPERIMENT 2 -- Header overhead
===============================

Question
--------
What do our per-hop deadlines actually cost in bytes, and when is that cost
unacceptable?

This is the honest limitation section of the report. T-CRH is compact next to
SRv6 but it is NOT free next to plain CRH-16, and on tiny packets the cost is
severe.
"""

import matplotlib.pyplot as plt

from common import save, style
from header import (srh_size, crh16_size, tcrh_size, tcrh_size_authenticated,
                    IPV6_BASE_HEADER)

HOP_COUNTS = list(range(2, 21))
PAYLOAD_SIZES = [40, 64, 128, 256, 512, 1024, 1400]
REFERENCE_HOPS = 10


def overhead_percent(header_bytes, payload):
    """Header bytes as a share of the whole packet on the wire."""
    total = IPV6_BASE_HEADER + header_bytes + payload
    return header_bytes / total * 100


def run():
    print("EXPERIMENT 2: header overhead")

    srh = [srh_size(h) for h in HOP_COUNTS]
    crh = [crh16_size(h) for h in HOP_COUNTS]
    tcrh = [tcrh_size(h) for h in HOP_COUNTS]
    tcrh_auth = [tcrh_size_authenticated(h) for h in HOP_COUNTS]

    print(f"  at {REFERENCE_HOPS} hops:  SRv6={srh_size(REFERENCE_HOPS)}B  "
          f"CRH-16={crh16_size(REFERENCE_HOPS)}B  "
          f"T-CRH={tcrh_size(REFERENCE_HOPS)}B  "
          f"T-CRH+HMAC={tcrh_size_authenticated(REFERENCE_HOPS)}B")
    print(f"  cost of adding time = "
          f"{tcrh_size(REFERENCE_HOPS) - crh16_size(REFERENCE_HOPS)} bytes")

    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    # --- left: absolute header size vs hop count ---
    ax1.plot(HOP_COUNTS, srh, 'o-', lw=2, ms=5, color='#7f8c8d',
             label='SRv6 SRH (RFC 8754)')
    ax1.plot(HOP_COUNTS, tcrh_auth, 'd-', lw=2, ms=5, color='#8e44ad',
             label='T-CRH + HMAC (authenticated)')
    ax1.plot(HOP_COUNTS, tcrh, 's-', lw=2.4, ms=6, color='#c0392b',
             label='T-CRH (ours)')
    ax1.plot(HOP_COUNTS, crh, '^-', lw=2, ms=5, color='#2471a3',
             label='CRH-16 (RFC 9631)')
    ax1.set_xlabel('Number of hops in the path')
    ax1.set_ylabel('Routing header size (bytes)')
    ax1.set_title('Header size vs path length')
    ax1.legend(fontsize=9.5)
    ax1.set_xticks(range(2, 21, 2))

    ax1.annotate(f'+{tcrh_size(10) - crh16_size(10)} B\n= the time info',
                 xy=(10, (tcrh_size(10) + crh16_size(10)) / 2),
                 xytext=(11.5, 95), fontsize=9.5, color='#c0392b',
                 fontweight='bold',
                 arrowprops=dict(arrowstyle='<->', color='#c0392b', lw=1.4))

    # --- right: overhead share vs payload size ---
    for label, sizes, colour, mk in [
        ('SRv6 SRH', srh_size(REFERENCE_HOPS), '#7f8c8d', 'o'),
        ('T-CRH + HMAC', tcrh_size_authenticated(REFERENCE_HOPS), '#8e44ad', 'd'),
        ('T-CRH (ours)', tcrh_size(REFERENCE_HOPS), '#c0392b', 's'),
        ('CRH-16', crh16_size(REFERENCE_HOPS), '#2471a3', '^'),
    ]:
        ys = [overhead_percent(sizes, p) for p in PAYLOAD_SIZES]
        ax2.plot(PAYLOAD_SIZES, ys, marker=mk, lw=2.2, ms=6,
                 color=colour, label=label)

    ax2.set_xscale('log', base=2)
    ax2.set_xticks(PAYLOAD_SIZES)
    ax2.set_xticklabels([str(p) for p in PAYLOAD_SIZES])
    ax2.set_xlabel('Payload size (bytes)')
    ax2.set_ylabel('Routing header as % of packet')
    ax2.set_title(f'Overhead share ({REFERENCE_HOPS}-hop path)')
    ax2.legend(fontsize=9.5)
    ax2.axvspan(35, 90, alpha=0.12, color='red')
    ax2.text(52, ax2.get_ylim()[1] * 0.82, 'IoT /\ntelemetry',
             ha='center', fontsize=9, color='#c0392b', fontweight='bold')

    fig.suptitle('Experiment 2: what the per-hop deadlines cost',
                 fontsize=14, fontweight='bold', y=1.02)
    save(fig, 'exp2_header_overhead.png')

    print(f"  on a 40-byte payload, T-CRH is "
          f"{overhead_percent(tcrh_size(10), 40):.1f}% of the packet")
    print(f"  on a 1400-byte payload, T-CRH is "
          f"{overhead_percent(tcrh_size(10), 1400):.1f}% of the packet")

    return {'hops': HOP_COUNTS, 'tcrh': tcrh, 'crh': crh, 'srh': srh}


if __name__ == '__main__':
    run()
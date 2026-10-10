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

v0.9: every size comes from chronoroute.proto.sizes, the one implementation
of the wire format (spec/tcrh-v1.md). v0 used CRH16_FIXED = 8 instead of
RFC 9631's 4-octet fixed part, so every CRH-16 bar was one 8-byte unit too
tall (32 B instead of 24 B at 10 hops) and the "+16 B" annotation is really
"+24 B". We also show the second ingress mode of spec section 8: a gateway
that cannot insert an extension header into someone else's packet (RFC 8200
section 4) must wrap it in a new IPv6 header, which costs 40 B more.
"""

import matplotlib.pyplot as plt

import common
from common import style
from header import HMAC_TLV_BYTES
from chronoroute.proto import sizes
from chronoroute.provenance import RunTimer

NAME = 'exp2_header_overhead'

DEFAULTS = {
    'hop_counts': list(range(2, 21)),
    'payload_sizes': [40, 64, 128, 256, 512, 1024, 1400],
    'reference_hops': 10,
}

LABELS = {
    'header_sizes': 'REAL',        # exact byte counts from the reference encoder
    'payload_sizes': 'MODELLED',   # illustrative packet sizes
}

IPV6_BASE_HEADER = sizes.IPV6_HEADER_BYTES


def tcrh_size_authenticated(num_hops):
    """T-CRH plus an SRv6-style HMAC TLV -- the security/compactness trade-off."""
    return sizes.pad8(sizes.TCRH_FIXED_BYTES + sizes.TCRH_ENTRY_BYTES * num_hops
                      + HMAC_TLV_BYTES)


# header key -> (legend label, size function, colour, marker, line style)
HEADERS = [
    ('srh', 'SRv6 SRH (RFC 8754)', sizes.srh_size, '#7f8c8d', 'o', '-'),
    # an HMAC TLV and an encapsulating IPv6 header are both exactly 40 B,
    # so these two lines coincide; the legend says so rather than hide one
    ('tcrh_hmac', 'T-CRH + HMAC TLV (+40 B: same size as encapsulation)',
     tcrh_size_authenticated, '#8e44ad', 'd', '-'),
    ('tcrh_encap', 'T-CRH, gateway encapsulation (+40 B IPv6)',
     lambda n: sizes.encapsulation_overhead(n, 'encap', 'tcrh'), '#e67e22', 'v', '--'),
    ('tcrh', 'T-CRH (ours, source insertion)', sizes.tcrh_size, '#c0392b', 's', '-'),
    ('crh16', 'CRH-16 (RFC 9631)', sizes.crh16_size, '#2471a3', '^', '-'),
]


def overhead_percent(header_bytes, payload):
    """Header bytes as a share of the whole packet on the wire."""
    total = IPV6_BASE_HEADER + header_bytes + payload
    return header_bytes / total * 100


def run(workers=None, **overrides):
    """Sizes are exact formulas, so there is nothing to parallelise (workers unused)."""
    cfg = common.make_config(DEFAULTS, overrides)
    hops, payloads, ref = cfg['hop_counts'], cfg['payload_sizes'], cfg['reference_hops']
    print("EXPERIMENT 2: header overhead")

    with RunTimer() as timer:
        table = {key: [fn(h) for h in hops] for key, _, fn, *_ in HEADERS}
        at_ref = {key: fn(ref) for key, _, fn, *_ in HEADERS}
        added = at_ref['tcrh'] - at_ref['crh16']

        print(f"  at {ref} hops:  SRv6={at_ref['srh']}B  CRH-16={at_ref['crh16']}B  "
              f"T-CRH={at_ref['tcrh']}B  T-CRH+HMAC={at_ref['tcrh_hmac']}B  "
              f"T-CRH encapsulated={at_ref['tcrh_encap']}B")
        print(f"  cost of adding time = {added} bytes")

        rows = []
        for key, *_ in HEADERS:
            for h, b in zip(hops, table[key]):
                rows.append({'panel': 'size_vs_hops', 'hops': h, 'payload_bytes': None,
                             'header': key, 'header_bytes': b, 'overhead_pct': None})
        for key, *_ in HEADERS:
            for p in payloads:
                rows.append({'panel': 'share_vs_payload', 'hops': ref, 'payload_bytes': p,
                             'header': key, 'header_bytes': at_ref[key],
                             'overhead_pct': overhead_percent(at_ref[key], p)})

        style()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

        # --- left: absolute header size vs hop count ---
        for key, label, _, colour, mk, ls in HEADERS:
            ax1.plot(hops, table[key], marker=mk, ls=ls, lw=2.4 if key == 'tcrh' else 2,
                     ms=5, color=colour, label=label)
        ax1.set_xlabel('Number of hops in the path')
        ax1.set_ylabel('Routing header size (bytes)')
        ax1.set_title('Header size vs path length')
        ax1.legend(fontsize=9)
        ax1.set_xticks(range(hops[0], hops[-1] + 1, 2))

        ax1.annotate(f'+{added} B\n= the time info',
                     xy=(ref, (at_ref['tcrh'] + at_ref['crh16']) / 2),
                     xytext=(ref + 3, 4), fontsize=9.5, color='#c0392b',
                     fontweight='bold',
                     arrowprops=dict(arrowstyle='<->', color='#c0392b', lw=1.4))

        # --- right: overhead share vs payload size ---
        for key, label, _, colour, mk, ls in HEADERS:
            ys = [overhead_percent(at_ref[key], p) for p in payloads]
            ax2.plot(payloads, ys, marker=mk, ls=ls, lw=2.2, ms=6, color=colour,
                     label=label)
        ax2.set_xscale('log', base=2)
        ax2.set_xticks(payloads)
        ax2.set_xticklabels([str(p) for p in payloads], rotation=30)
        ax2.set_xlabel('Payload size (bytes)')
        ax2.set_ylabel('Routing header as % of packet')
        ax2.set_title(f'Overhead share ({ref}-hop path)')
        ax2.legend(fontsize=8)
        ax2.axvspan(35, 90, alpha=0.12, color='red')
        ax2.text(56, ax2.get_ylim()[1] * 0.03, 'IoT /\ntelemetry',
                 ha='center', fontsize=9, color='#c0392b', fontweight='bold')

        fig.suptitle('Experiment 2: what the per-hop deadlines cost '
                     '(sizes from chronoroute.proto.sizes)',
                     fontsize=14, fontweight='bold', y=1.02)

    out = common.write_results(
        NAME, fig=fig,
        tables=[(f'{NAME}.csv', ['panel', 'hops', 'payload_bytes', 'header',
                                 'header_bytes', 'overhead_pct'], rows)],
        config={**cfg, 'ipv6_header_bytes': IPV6_BASE_HEADER,
                'hmac_tlv_bytes': HMAC_TLV_BYTES,
                'size_source': 'chronoroute.proto.sizes (spec/tcrh-v1.md)'},
        seeds=[], labels=LABELS,
        extra={'at_reference_hops': at_ref, 'tcrh_minus_crh16_at_ref': added},
        timer=timer)

    print(f"  on a 40-byte payload, T-CRH is "
          f"{overhead_percent(sizes.tcrh_size(ref), 40):.1f}% of the packet")
    print(f"  on a 1400-byte payload, T-CRH is "
          f"{overhead_percent(sizes.tcrh_size(ref), 1400):.1f}% of the packet")

    return {'hops': hops, 'tcrh': table['tcrh'], 'crh': table['crh16'], 'srh': table['srh'],
            'at_reference_hops': at_ref, 'tcrh_minus_crh16_at_ref': added, 'outputs': out}


if __name__ == '__main__':
    run()

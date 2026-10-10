"""
EXPERIMENT 3 -- Control-plane cost      ** ANALYTIC MODEL (formula) **
==================================

This is NOT a simulation. Every curve is a closed-form formula below; it is
kept runnable so the old figure can be reproduced and compared, and it is
superseded by E3 (a simulated control plane) in the new campaign.

Question
--------
How much signalling traffic do we save by putting the route in the packet
instead of uploading tables to satellites?

Three models compared, all refreshed every REFRESH interval:

  1. TABLE UPLOAD (the FSA / Hypatia baseline)
     Every satellite receives a forwarding table entry for every destination,
     every schedule epoch. Cost grows with the number of satellites.

  2. LINK-STATE FLOODING (an OSPF-like reactive baseline)
     Every satellite floods its link state to every other satellite whenever
     the topology changes. Cost grows with satellites x neighbours.

  3. T-CRH (ours)
     Schedules go only to the handful of ground gateways that inject traffic.
     Satellites receive NOTHING. Cost is independent of constellation size.

What v0.9 fixes (audit, section 2 item 10)
------------------------------------------
  * ONE refresh interval for every scheme. The v0 write-up compared T-CRH
    refreshed every 3 s (Experiment 7's choice) with table upload refreshed
    every 15 s. Here each interval is applied to all schemes alike, and we
    show both 15 s and 3 s.
  * T-CRH is not free per packet: every data packet carries the header.
    Those bytes are shown as their own series ("data plane"), next to -- not
    merged into -- the control-plane bytes (plan 5.3: header bytes and
    control bytes are never added into one "cost"). The packet rate is an
    assumption, so it is labelled MODELLED.
  * The T-CRH header size uses the mean path length MEASURED on the active
    preset's scenario, not a fixed 10 hops.

Still missing (that is why E3 replaces this): FIB/SID-map uploads,
ephemeris distribution and clock sync for the fallback, and table uploads
for more than the six destinations.
"""

import matplotlib.pyplot as plt
import networkx as nx

import common
from common import style
from scheduler import SCHEDULE_INTERVAL_S
from chronoroute.proto import sizes
from chronoroute.provenance import RunTimer

NAME = 'exp3_control_plane'
MODEL_LABEL = 'ANALYTIC MODEL (formula) — superseded by E3 in the new campaign'

DEFAULTS = {
    'constellation_sizes': [120, 240, 480, 960, 1584, 3200, 6400],
    # every scheme is evaluated at each of these intervals (the same for all)
    'refresh_intervals_s': [SCHEDULE_INTERVAL_S, 3],
    'num_gateways': 6,             # our six ground stations
    'num_destinations': 6,
    'flows_per_gateway': 5,
    'packets_per_s_per_flow': 100,  # MODELLED: data rate of one gateway flow
    'fib_entry_bytes': 8,          # destination ID + outgoing interface + metadata
    'lsa_bytes': 32,               # one link-state advertisement per neighbour
    'isls_per_sat': 4,
    'avg_hops': None,              # None = measure on the active preset
    'duration_s': common.DURATION_S,
    'step_s': common.STEP_S,
    'highlight_sats': 1584,        # the Starlink Shell 1 size, for the bar chart
}

LABELS = {
    'model': 'MODELLED',               # closed-form formulas, not a simulation
    'avg_hops': 'DERIVED',             # measured on the preset's scenario
    'header_bytes': 'REAL',            # chronoroute.proto.sizes
    'packet_rate': 'MODELLED',
    'fib_and_lsa_sizes': 'MODELLED',
}

SCHEMES = [
    # key, label, colour, marker, kind
    ('link_state', 'Link-state flooding (OSPF-like)', '#7f8c8d', 'o', 'control_plane'),
    ('table_upload', 'Table upload (FSA / Hypatia baseline)', '#e67e22', 's', 'control_plane'),
    ('tcrh_control', 'T-CRH schedules to gateways (ours)', '#c0392b', '^', 'control_plane'),
    ('tcrh_header_bytes', 'T-CRH header on every packet (data plane)', '#8e44ad', 'd',
     'data_plane'),
]


def table_upload_bytes_per_sec(num_sats, cfg, interval_s):
    """Baseline 1: upload a full FIB to every satellite each epoch."""
    per_epoch = num_sats * cfg['num_destinations'] * cfg['fib_entry_bytes']
    return per_epoch / interval_s


def link_state_bytes_per_sec(num_sats, cfg, interval_s):
    """
    Baseline 2: OSPF-like flooding. Each satellite originates an LSA per
    neighbour, and each LSA reaches every other node.
    """
    per_epoch = num_sats * cfg['isls_per_sat'] * cfg['lsa_bytes'] * num_sats
    return per_epoch / interval_s


def tcrh_bytes_per_sec(num_sats, cfg, interval_s, hops):
    """
    Ours, control plane: one schedule entry per flow, delivered only to
    gateways. Independent of num_sats, which is the whole point.
    """
    per_epoch = cfg['num_gateways'] * cfg['flows_per_gateway'] * sizes.tcrh_size(hops)
    return per_epoch / interval_s


def tcrh_header_bytes_per_sec(num_sats, cfg, interval_s, hops):
    """Ours, data plane: the header every packet carries (independent of the interval)."""
    flows = cfg['num_gateways'] * cfg['flows_per_gateway']
    return flows * cfg['packets_per_s_per_flow'] * sizes.tcrh_size(hops)


def measured_avg_hops(duration_s, step_s):
    """Mean hop count of the scenario's flows at every schedule epoch."""
    times, _, _, graphs = common.setup(duration_s, step_s, verbose=False)
    hops = []
    for i, t in enumerate(times):
        if t % SCHEDULE_INTERVAL_S:
            continue
        for src, dst in common.FLOWS:
            try:
                hops.append(len(nx.shortest_path(graphs[i], src, dst, weight='weight')) - 1)
            except nx.NetworkXNoPath:
                continue
    return sum(hops) / len(hops), len(hops)


def run(workers=None, **overrides):
    """A formula, so nothing to parallelise (workers unused)."""
    cfg = common.make_config(DEFAULTS, overrides)
    print("EXPERIMENT 3: control-plane cost  [" + MODEL_LABEL + "]")
    title = f'Experiment 3 — {MODEL_LABEL}'

    with RunTimer() as timer:
        if cfg['avg_hops'] is None:
            mean_hops, n_paths = measured_avg_hops(cfg['duration_s'], cfg['step_s'])
            hops = max(1, round(mean_hops))
            print(f"  mean path length on preset {common.preset_name()!r}: "
                  f"{mean_hops:.2f} hops over {n_paths} paths -> header for {hops} hops")
        else:
            mean_hops, n_paths, hops = float(cfg['avg_hops']), None, int(cfg['avg_hops'])

        formulas = {
            'link_state': lambda n, iv: link_state_bytes_per_sec(n, cfg, iv),
            'table_upload': lambda n, iv: table_upload_bytes_per_sec(n, cfg, iv),
            'tcrh_control': lambda n, iv: tcrh_bytes_per_sec(n, cfg, iv, hops),
            'tcrh_header_bytes': lambda n, iv: tcrh_header_bytes_per_sec(n, cfg, iv, hops),
        }
        sizes_ = cfg['constellation_sizes']
        intervals = cfg['refresh_intervals_s']
        values = {(key, iv): [formulas[key](n, iv) for n in sizes_]
                  for key, *_ in SCHEMES for iv in intervals}

        rows = []
        for iv in intervals:
            for key, _, _, _, kind in SCHEMES:
                for n, v in zip(sizes_, values[(key, iv)]):
                    rows.append({'model': MODEL_LABEL, 'refresh_interval_s': iv,
                                 'num_sats': n, 'scheme': key, 'kind': kind,
                                 'bytes_per_s': v, 'tcrh_hops': hops})

        for iv in intervals:
            print(f"  -- every scheme refreshed every {iv} s")
            print(f"  {'sats':>6} {'link-state':>14} {'table upload':>14} {'T-CRH ctl':>11} "
                  f"{'T-CRH hdr':>12}")
            for i, n in enumerate(sizes_):
                print(f"  {n:>6} {values[('link_state', iv)][i]:>12.0f} B/s "
                      f"{values[('table_upload', iv)][i]:>12.0f} B/s "
                      f"{values[('tcrh_control', iv)][i]:>7.0f} B/s "
                      f"{values[('tcrh_header_bytes', iv)][i]:>8.0f} B/s")

        style()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.8))
        iv0 = intervals[0]
        for key, label, colour, mk, kind in SCHEMES:
            ax1.plot(sizes_, values[(key, iv0)], marker=mk, lw=2.4, ms=6, color=colour,
                     ls='--' if kind == 'data_plane' else '-', label=label)
        ax1.set_xscale('log', base=2)
        ax1.set_yscale('log')
        ax1.set_xticks(sizes_)
        ax1.set_xticklabels([str(n) for n in sizes_], rotation=45)
        ax1.set_xlabel('Number of satellites in the constellation')
        ax1.set_ylabel('Bytes/second (log scale)')
        ax1.set_title(f'All schemes refreshed every {iv0} s')
        ax1.legend(fontsize=8.5, loc='upper left')

        # --- right: grouped bars at one constellation size, per interval ---
        n_hi = cfg['highlight_sats'] if cfg['highlight_sats'] in sizes_ else sizes_[-1]
        idx = sizes_.index(n_hi)
        width = 0.8 / len(SCHEMES)
        for j, (key, label, colour, _, kind) in enumerate(SCHEMES):
            xs = [i + (j - (len(SCHEMES) - 1) / 2) * width for i in range(len(intervals))]
            vals = [values[(key, iv)][idx] for iv in intervals]
            ax2.bar(xs, vals, width, color=colour, label=label,
                    hatch='//' if kind == 'data_plane' else None)
            for x, v in zip(xs, vals):
                ax2.text(x, v * 1.3, f'{v:,.0f}', ha='center', fontsize=7.5, rotation=90)
        ax2.set_xticks(range(len(intervals)))
        ax2.set_xticklabels([f'refresh every {iv} s' for iv in intervals])
        ax2.set_yscale('log')
        ax2.set_ylabel('Bytes/second (log scale)')
        ax2.set_title(f'At {n_hi} satellites, same interval for every scheme')
        ax2.set_ylim(top=max(values[(k, iv)][idx] for k, *_ in SCHEMES
                             for iv in intervals) * 3000)
        ax2.legend(fontsize=8, loc='upper right')

        fig.suptitle(f'{title}\nT-CRH header {sizes.tcrh_size(hops)} B ({hops} hops, '
                     f'measured on preset {common.preset_name()}); '
                     f'{cfg["num_gateways"] * cfg["flows_per_gateway"]} flows x '
                     f'{cfg["packets_per_s_per_flow"]} packets/s each (assumed)',
                     fontsize=12.5, fontweight='bold', y=1.06)

    config = {**cfg, 'avg_hops_used': hops, 'avg_hops_measured': mean_hops,
              'preset': common.preset_name(), 'model': MODEL_LABEL}
    out = common.write_results(
        NAME, fig=fig,
        tables=[(f'{NAME}.csv', ['model', 'refresh_interval_s', 'num_sats', 'scheme', 'kind',
                                 'bytes_per_s', 'tcrh_hops'], rows)],
        config=config, seeds=[], labels=LABELS,
        extra={'measured_paths': n_paths,
               'propagation': common.setup_stats(cfg['duration_s'], cfg['step_s'])},
        timer=timer)

    for iv in intervals:
        t, l, o = (values[('table_upload', iv)][idx], values[('link_state', iv)][idx],
                   values[('tcrh_control', iv)][idx])
        h = values[('tcrh_header_bytes', iv)][idx]
        print(f"\n  refresh {iv} s, {n_hi} satellites: T-CRH control plane is "
              f"{t / o:.0f}x below table upload and {l / o:,.0f}x below link-state flooding,")
        print(f"  but its per-packet header adds {h:,.0f} B/s of data-plane bytes "
              f"({h / t:.1f}x the table-upload control traffic).")

    return {'sizes': sizes_, 'intervals': intervals, 'hops': hops, 'title': title,
            'values': {f'{k}@{iv}': v for (k, iv), v in values.items()}, 'outputs': out}


if __name__ == '__main__':
    run()

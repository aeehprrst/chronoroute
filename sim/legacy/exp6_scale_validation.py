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
geometry. (The "starlink" preset is the 2020 FCC Shell-1 design, not the
2026 fleet.)

What we measure per constellation
---------------------------------
  path length        how many hops a real intercontinental route takes
  latency            end-to-end delay
  header size        T-CRH bytes (chronoroute.proto.sizes), driven by path length
  operating slack    Experiment 1's sweep with its v0.9 scoring: detection is
                     COUNTERFACTUAL (same packets with and without the fault,
                     common random numbers), a null-fault control must give
                     exactly 0, and the slack is the highest detection with
                     mean FPR <= 1% and mean detection >= 1% (the same
                     function as Experiment 1; Youden J only for
                     continuity). v0 used the confounded metric here too
                     (bug #3).
  deviation floor    stale-path deviations at a very loose deadline (S = 5),
                     which no slack can remove (see Experiment 7)

Every number is a mean over FLOWS (each flow the mean of its seeds) with a
Student-t 95% CI over the flows. The seeds of one flow are not independent:
the stale-path floor, for one, is the same in every seed of a flow, because
it is set by geometry. With three flows the intervals are wide. The per-flow
floors are in the CSV; Experiment 7's 32 windows across an orbit are the
better estimate of the stale-path rate.

This experiment switches the constellation itself; it puts back whatever
preset was active when it started, so nothing that runs after it inherits
the wrong scale.
"""

import dataclasses

import matplotlib.pyplot as plt
import networkx as nx

import common
import constellation as C
import scale
import topology as T
import exp1_slack_sweep as exp1
from common import style
from chronoroute.proto import sizes
from chronoroute.provenance import RunTimer

NAME = 'exp6_scale_validation'
PRESET_ORDER = ['telesat', 'dev', 'kuiper', 'starlink']

DEFAULTS = {
    'presets': PRESET_ORDER,
    'duration_s': common.DURATION_S,
    'step_s': common.STEP_S,
    'slacks': [1.0, 1.1, 1.15, 1.2, 1.25, 1.3, 1.5, 2.0, 3.0],
    'unit_codes': [0, 1],
    'degradation': 1.5,
    'seeds': list(range(1, 11)),
    'flows': list(common.FLOWS),
    'num_packets': 250,
    'packet_interval_ms': 300,
    'floor_slack': 5.0,
    'floor_unit_code': 0,       # 1 ms units: a 255-unit delta never clamps at S = 5
    'fpr_max': 0.01,
}

LABELS = dict(exp1.LABELS)


def floor_summary(floor_runs):
    """
    The stale-path floor with the FLOW as the unit of analysis: the mean of
    each flow's seeds, then a t-CI over the flows (common.cluster_mean_ci).
    v0.9 first treated 30 flow x seed runs as independent, although the rate
    is identical in every seed of a flow (10 copies of {0, 16, 0} % gave
    [2.5, 8.2]; over the 3 flows it is [0, 28.3]).
    """
    stale = [r['stale'] for r in floor_runs]
    flows = [r['flow_index'] for r in floor_runs]
    mean, lo, hi, n_flows = common.cluster_mean_ci(stale, flows, bounds=(0.0, 1.0))
    per_flow = []
    for fi in sorted(set(flows)):
        xs = [r['stale'] for r in floor_runs if r['flow_index'] == fi and r['stale'] is not None]
        per_flow.append(common.pct(sum(xs) / len(xs)) if xs else None)
    return {'mean_pct': common.pct(mean), 'ci95_lo_pct': common.pct(lo),
            'ci95_hi_pct': common.pct(hi), 'n_flows': n_flows,
            'n_runs': sum(x is not None for x in stale), 'per_flow_pct': per_flow}


def measure_one(preset, cfg, workers):
    """Reconfigure to a preset and take every measurement we care about."""
    n_sats = scale.use_preset(preset, verbose=False)
    scale.install_fast_topology(verbose=False)
    times, sat_pos, gs_pos, graphs = common.setup(cfg['duration_s'], cfg['step_s'],
                                                  verbose=False)
    stats = common.setup_stats(cfg['duration_s'], cfg['step_s'])

    # ---- path length and latency over all flows and the whole window ----
    hops, lats = [], []
    for flow in cfg['flows']:
        for g in graphs[::10]:
            try:
                lat, p = nx.single_source_dijkstra(g, flow[0], flow[1], weight='weight')
            except nx.NetworkXNoPath:
                continue
            hops.append(len(p) - 1)
            lats.append(lat)
    mean_hops = sum(hops) / len(hops)
    mean_lat = sum(lats) / len(lats)

    # ---- the operating slack, scored as in Experiment 1 ----
    deg = cfg['degradation']
    factors = [exp1.NULL_FAULT, deg]
    sweep = dict(seeds=cfg['seeds'], flows=cfg['flows'], num_packets=cfg['num_packets'],
                 packet_interval_ms=cfg['packet_interval_ms'], duration_s=cfg['duration_s'],
                 step_s=cfg['step_s'], workers=workers)
    runs = exp1.counterfactual_sweep(slacks=cfg['slacks'], unit_codes=cfg['unit_codes'],
                                     factors=factors, **sweep)
    curves, lookup = exp1.summarise_runs(runs, cfg['slacks'], cfg['unit_codes'], factors)
    ops = exp1.operating_points(lookup, cfg['slacks'], cfg['unit_codes'], deg,
                                100 * cfg['fpr_max'])
    null_attributed = sum(f['attributed'] for r in runs for f in r['faults']
                          if f['degradation'] == exp1.NULL_FAULT)

    # ---- the irreducible floor: stale-path deviations at a very loose deadline ----
    floor_runs = exp1.counterfactual_sweep(slacks=[cfg['floor_slack']],
                                           unit_codes=[cfg['floor_unit_code']],
                                           factors=[exp1.NULL_FAULT], **sweep)
    floor = floor_summary(floor_runs)

    h = int(round(mean_hops))
    row = {
        'preset': preset,
        'name': scale.PRESETS[preset]['name'],
        'sats': n_sats,
        'mean_hops': mean_hops,
        'max_hops': max(hops),
        'mean_latency_ms': mean_lat,
        'header_hops': h,
        'tcrh_bytes': sizes.tcrh_size(h),
        'crh16_bytes': sizes.crh16_size(h),
        'srh_bytes': sizes.srh_size(h),
        'floor_pct': floor['mean_pct'],
        'floor_ci95_lo_pct': floor['ci95_lo_pct'],
        'floor_ci95_hi_pct': floor['ci95_hi_pct'],
        # one value per flow, in cfg['flows'] order (the CI is over these)
        'floor_per_flow_pct': ';'.join('' if v is None else f'{v:.4g}'
                                       for v in floor['per_flow_pct']),
        'n_flows': floor['n_flows'],
        'n_runs': floor['n_runs'],
    }
    for o in ops:
        kind = 'operating_point' if o['criterion'].startswith('max detection') else 'youden'
        row[f"{kind}_S_unit{o['unit_code']}"] = o['slack']
    return row, [{'preset': preset, **c} for c in curves], lookup, stats, null_attributed


def run(workers=None, **overrides):
    cfg = common.make_config(DEFAULTS, overrides)
    print("EXPERIMENT 6: cross-scale validation")

    # remember the constellation we were called with, and put it back after
    saved_cfg = C.config()
    saved_fast = T.build_graph is scale._fast_build_graph

    rows, curves, lookups, stats, null_total = [], [], {}, {}, 0
    try:
        with RunTimer() as timer:
            for preset in cfg['presets']:
                print(f"\n  --- {scale.describe(preset)}")
                row, c, lookup, st, null = measure_one(preset, cfg, workers)
                rows.append(row)
                curves += c
                lookups[preset] = lookup
                stats[preset] = st
                null_total += null
                ops = ', '.join(f"unit {u}: S={row.get(f'operating_point_S_unit{u}')}"
                                for u in cfg['unit_codes'])
                print(f"      mean {row['mean_hops']:.1f} hops (max {row['max_hops']}), "
                      f"{row['mean_latency_ms']:.1f} ms, T-CRH {row['tcrh_bytes']} B, "
                      f"operating slack {ops}, floor {row['floor_pct']:.1f}%")
            fig = plot(rows, lookups, cfg)
    finally:
        scale.apply_config(saved_cfg.planes, saved_cfg.sats_per_plane, saved_cfg.altitude_km,
                           saved_cfg.inclination_deg, verbose=False,
                           phasing_f=saved_cfg.phasing_f)
        if not saved_fast:
            scale.restore_topology()

    if null_total:
        raise RuntimeError(f"null-fault control attributed {null_total} flags; must be 0")

    unit_cols = [f'{k}_S_unit{u}' for u in cfg['unit_codes']
                 for k in ('operating_point', 'youden')]
    fields = ['preset', 'name', 'sats', 'mean_hops', 'max_hops', 'mean_latency_ms',
              'header_hops', 'tcrh_bytes', 'crh16_bytes', 'srh_bytes'] + unit_cols + \
             ['floor_pct', 'floor_ci95_lo_pct', 'floor_ci95_hi_pct', 'floor_per_flow_pct',
              'n_flows', 'n_runs']
    seeds = [common.crn_seed(s, fi) for fi in range(len(cfg['flows'])) for s in cfg['seeds']]
    config = {**common.scenario_config(), **cfg,
              'presets_detail': {p: scale.PRESETS[p] for p in cfg['presets']},
              'restored_constellation': dataclasses.asdict(saved_cfg),
              'scoring': 'as exp1_slack_sweep (counterfactual, CRN, null-fault control)',
              'ci': 'Student-t 95% over flows (each flow the mean of its seeds)',
              'crn_seed_rule': 'seed * 1000 + flow_index'}
    # 'preset' in the scenario is the one we restored, i.e. where we were called from
    out = common.write_results(
        NAME, fig=fig,
        tables=[(f'{NAME}.csv', fields, rows),
                ('exp6_slack_curves.csv', ['preset'] + exp1.CURVE_FIELDS, curves)],
        config=config, seeds=seeds, labels=LABELS,
        extra={'propagation': stats, 'null_fault_attributed': null_total,
               'workers': common.LAST_WORKERS},
        timer=timer)

    print("\n  === Summary table for the report ===")
    print(f"  {'constellation':<26} {'sats':>5} {'hops':>6} {'lat ms':>8} {'T-CRH':>7} "
          + ' '.join(f"{'S u' + str(u):>6}" for u in cfg['unit_codes']) + f" {'floor':>7}")
    for r in rows:
        print(f"  {r['name']:<26} {r['sats']:>5} {r['mean_hops']:>6.1f} "
              f"{r['mean_latency_ms']:>8.1f} {r['tcrh_bytes']:>6}B "
              + ' '.join(f"{str(r[f'operating_point_S_unit{u}']):>6}" for u in cfg['unit_codes'])
              + f" {r['floor_pct']:>6.1f}%")
    for u in cfg['unit_codes']:
        found = {r[f'operating_point_S_unit{u}'] for r in rows}
        if found == {None}:
            print(f"  unit code {u}: no operating point on any constellation tested "
                  f"(no slack has mean FPR <= {100 * cfg['fpr_max']:g}% and a useful detection).")
        elif len(found) == 1:
            print(f"  unit code {u}: the same operating slack S = {found.pop()} "
                  f"on every constellation tested.")
        else:
            print(f"  unit code {u}: the operating slack varies across constellations: "
                  f"{sorted(found, key=lambda s: (s is None, s))}")
    print(f"  null-fault control: {null_total} attributed flags (must be 0)")

    return {'rows': rows, 'null_fault_attributed': null_total, 'outputs': out}


def plot(rows, lookups, cfg):
    style()
    # constrained layout makes room for every title and tick label: without
    # it the floor panel's two-line title was drawn over the 'Header cost'
    # panel's two-line tick labels ('(351 sats)' ...) in the published figure
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), layout='constrained')
    ax1, ax2, ax3, ax4 = axes.flatten()

    # short labels: the full names overlap on a shared x-axis
    names = [f"{r['name'].split()[0]}\n({r['sats']} sats)" for r in rows]
    palette = {'telesat': '#8e44ad', 'dev': '#7f8c8d', 'kuiper': '#2471a3',
               'starlink': '#c0392b'}
    colours = [palette.get(r['preset'], '#34495e') for r in rows]

    # --- 1: path length grows with constellation size ---
    ax1.bar(names, [r['mean_hops'] for r in rows], color=colours, width=0.6)
    for i, r in enumerate(rows):
        ax1.text(i, r['mean_hops'] + 0.15, f"{r['mean_hops']:.1f}", ha='center',
                 fontweight='bold')
    # headroom, so the tallest bar's value label stays inside the frame
    ax1.set_ylim(0, 1.1 * max(r['mean_hops'] for r in rows))
    ax1.set_ylabel('Mean hops per intercontinental route')
    ax1.set_title('Path length per constellation')
    ax1.tick_params(axis='x', labelsize=9.5)

    # --- 2: which drives header size ---
    width = 0.26
    xs = range(len(rows))
    ax2.bar([x - width for x in xs], [r['crh16_bytes'] for r in rows],
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

    # --- 3: does the trade-off hold everywhere? (FPR, both deadline units) ---
    slacks = cfg['slacks']
    for r, c in zip(rows, colours):
        lookup = lookups[r['preset']]
        for u in cfg['unit_codes']:
            ys = [lookup[(u, s, 'fpr_deadline', None)][0] for s in slacks]
            ax3.plot(slacks, ys, 'o-' if u == 1 else 's--', lw=2 if u == 1 else 1.4, ms=4,
                     color=c, label=f"{r['name'].split()[0]}, unit "
                                    f"{exp1.unit_ms(u):g} ms")
    ax3.axhline(100 * cfg['fpr_max'], color='k', ls=':', lw=1)
    ax3.set_xlabel('Slack factor S')
    ax3.set_ylabel('False deviation rate, deadline flags (%)')
    ax3.set_title('False positives vs slack at every scale')
    ax3.legend(fontsize=7.5, ncol=2)

    # --- 4: the irreducible floor ---
    floor = [r['floor_pct'] for r in rows]
    err = [[f - (r['floor_ci95_lo_pct'] if r['floor_ci95_lo_pct'] is not None else f)
            for f, r in zip(floor, rows)],
           [(r['floor_ci95_hi_pct'] if r['floor_ci95_hi_pct'] is not None else f) - f
            for f, r in zip(floor, rows)]]
    bars = ax4.bar(names, floor, color=colours, width=0.6, yerr=err, capsize=4)
    for b, r in zip(bars, rows):
        # a white box, because the error bar runs through the label's position
        ax4.text(b.get_x() + b.get_width() / 2, r['floor_pct'] + 0.2,
                 f"{r['floor_pct']:.1f}%", ha='center', fontweight='bold',
                 bbox=dict(facecolor='white', edgecolor='none', alpha=0.85, pad=1.5))
    ax4.set_ylabel(f"Stale-path deviations at S = {cfg['floor_slack']} (%)")
    ax4.set_title('The floor no deadline can fix (see Experiment 7)\n'
                  f"95% CI over {len(cfg['flows'])} flows: it depends on the flow")
    ax4.tick_params(axis='x', labelsize=9.5)

    n_runs = len(cfg['flows']) * len(cfg['seeds'])
    fig.suptitle('Experiment 6: the Tier 1 findings on four constellation designs\n'
                 f"counterfactual scoring; {n_runs} runs per point "
                 f"({len(cfg['flows'])} flows x {len(cfg['seeds'])} seeds), "
                 f"95% t-CI over flows",
                 fontsize=13.5, fontweight='bold')    # no y=: the layout places it
    return fig


if __name__ == '__main__':
    run()

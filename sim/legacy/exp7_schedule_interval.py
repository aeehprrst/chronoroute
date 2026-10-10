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

v0.9: measuring it so the answer is not noise
---------------------------------------------
v0 used one 120 s window (2% of an orbit; the 60 s interval had just two
schedule epochs) and recommended "3 s" because 3 s happened to score 0.3%
between 2 s and 5 s at 1.1% each: the chooser took max() of the noise.
Seeds did not help, because stale paths come from WHEN handovers happen,
which is geometry, not jitter. Now:

  * WINDOWS ACROSS ONE ORBIT. n_offsets windows start at offsets spread
    evenly over one orbital period (~95.6 min at 550 km), so every orbital
    phase is sampled. A window is the unit of analysis: we report the mean
    over windows and a Student-t 95% CI.
  * WHOLE EPOCHS. Each window lasts 180 s, a multiple of every interval
    tested, so every interval sees whole schedule periods and a uniform
    spread of schedule ages.
  * A CLEAN STALE-PATH MEASURE. In the S = 1.2 run a packet that first
    misses a deadline is already on the fallback and never reaches the dead
    link, so 'link_failed' is under-counted there. The stale-path rate the
    chooser uses therefore comes from a probe run with the deadline
    effectively off (S = 5, 1 ms units) on the same packets. The S = 1.2
    'link_failed' and 'deadline_missed' rates are still plotted.
  * A CHOOSER THAT RESPECTS THE NOISE. Start at the interval with the lowest
    mean stale-path rate and walk to longer intervals while each is
    NON-INFERIOR to it: the upper end of the 95% CI of the paired difference
    (same windows) is at most 0.5 percentage points (the plan's smallest
    effect of interest). Stop at the first that is not; that is the
    longest (cheapest) interval we can defend.
  * THE SIMULATION STEP LIMITS THE ANSWER. The topology only changes at
    step_s (1 s) steps, so an interval of step_s or less is never stale, by
    construction. If the chooser ends there, the honest statement is "no
    interval longer than the simulation step is within the margin", not
    "use 1 s": the chooser marks that result as resolution-limited, and the
    figure and the console say so. A sub-second step would be needed to say
    how short the interval really has to be.
"""

import math

import matplotlib.pyplot as plt

import common
import constellation as C
import simulator as SIM
from common import style
from constellation import build_constellation, ground_station_positions
from topology import build_all_graphs
from scheduler import generate_schedules
from simulator import simulate_flow
from chronoroute import proto
from chronoroute.provenance import RunTimer
import exp3_control_plane as exp3

NAME = 'exp7_schedule_interval'

DEFAULTS = {
    'intervals': [1, 2, 3, 5, 10, 15, 20, 30, 45, 60],
    'window_s': 180,           # a multiple of every interval above
    'n_offsets': 32,           # windows spread evenly over one orbital period
    'step_s': 1,
    'slack': 1.2,              # the v0 operating point (Experiment 1)
    'unit_code': 1,            # 0.1 ms, the provisional v1 default
    'probe_slack': 5.0,        # deadline effectively off: isolates stale paths
    'probe_unit_code': 0,
    'flows': list(common.FLOWS),
    'packet_interval_ms': 300,
    'margin_pp': 0.5,          # non-inferiority margin for the chooser
}

LABELS = {
    'constellation': 'MODELLED',
    'ground_stations': 'REAL',
    'queueing_delay': 'MODELLED',
    'stale_path_rate': 'DERIVED',
    'control_plane_cost': 'MODELLED',   # Experiment 3's formulas
}


# --------------------------------------------------------------- windows

def orbital_period_s():
    """One orbit of the ACTIVE shell (circular, from the SGP4 mean motion)."""
    n_rad_per_min = C.mean_motion_rad_per_min(C.config().altitude_km)
    return 2 * math.pi / n_rad_per_min * 60.0


def window_offsets(n, period_s=None):
    """n window start times (whole seconds) spread evenly over one orbit."""
    if period_s is None:
        period_s = orbital_period_s()
    offsets = [round(j * period_s / n) for j in range(n)]
    if len(set(offsets)) != n:
        raise ValueError("too many windows for one orbit")
    return offsets


def run_window(task):
    """
    One window: propagate [offset, offset + window_s), build its graphs, and
    run every interval and flow on it. Each worker builds its own window and
    frees it afterwards, so a whole orbit is never held in memory.
    """
    (j, offset, window_s, step_s, intervals, flows, slack, unit_code,
     probe_slack, probe_unit, interval_ms) = task
    sats = build_constellation()
    abs_times, sat_pos, stats = common.propagate_window(sats, offset, window_s, step_s)
    # the simulator and scheduler count time from the start of the run, so
    # give them relative times; the GPS clock carries the true offset
    times = [t - offset for t in abs_times]
    gs_pos = ground_station_positions(times)
    graphs = build_all_graphs(times, sat_pos, gs_pos, verbose=False)
    t0 = SIM.T0_GPS_NS + proto.seconds_to_ns(offset)
    num_packets = window_s * 1000 // interval_ms + 1

    per_flow = []
    for iv in intervals:
        for fi, flow in enumerate(flows):
            seed = common.crn_seed(j, fi)
            row = {'window': j, 'offset_s': offset, 'interval_s': iv,
                   'flow': common.flow_label(flow), 'crn_seed': seed}
            for tag, s, u in (('op', slack, unit_code), ('probe', probe_slack, probe_unit)):
                sch = generate_schedules(times, sat_pos, gs_pos, [flow], slack_factor=s,
                                         interval_s=iv, unit_code=u, graphs=graphs)
                res = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                                    num_packets, interval_ms, seed=seed, t0_gps_ns=t0)
                n = len(res)
                lf = sum(r['deviation_reason'] == 'link_failed' for r in res)
                dm = sum(r['deviation_reason'] == 'deadline_missed' for r in res)
                if tag == 'op':
                    entries = [e for ep in sch.values() for e in ep.values()]
                    row.update(packets=n, link_failed=lf / n, deadline_missed=dm / n,
                               schedule_entries=len(entries),
                               mean_header_bytes=(sum(e['header_bytes'] for e in entries)
                                                  / len(entries)) if entries else None)
                else:
                    row.update(stale_probe=lf / n, probe_deadline_missed=dm / n)
            per_flow.append(row)
    return {'window': j, 'offset_s': offset, 'stats': stats, 'rows': per_flow}


# --------------------------------------------------------------- the chooser

def choose_interval(intervals, per_window, margin_pp=0.5, step_s=None):
    """
    per_window[iv] = the stale-path rate (percent) of each window, in the
    same window order for every interval (a paired design).

    best   = the interval with the lowest mean (ties: the shorter)
    chosen = walking up from best, the longest interval before the first
             one whose paired difference to best has a 95% t-CI upper end
             above margin_pp. v0 took max() over everything under 1%.

    step_s is the simulation's topology step. An interval <= step_s cannot
    be stale in the simulation (the topology does not change within it), so
    when the chosen interval is <= step_s the answer is limited by the
    simulation's resolution: resolution_limited is then True, meaning "no
    interval longer than the step is within the margin".
    """
    ivs = sorted(intervals)
    means = {iv: sum(per_window[iv]) / len(per_window[iv]) for iv in ivs}
    best = min(ivs, key=lambda iv: (means[iv], iv))
    tests, chosen, stopped = [], best, False
    for iv in ivs:
        diffs = [a - b for a, b in zip(per_window[iv], per_window[best])]
        mean, lo, hi, n = common.mean_ci(diffs)
        upper = mean if hi is None else hi
        ok = iv == best or upper <= margin_pp
        tests.append({'interval_s': iv, 'mean_pct': means[iv], 'diff_vs_best_pp': mean,
                      'diff_ci95_lo_pp': lo, 'diff_ci95_hi_pp': hi, 'n_windows': n,
                      'non_inferior': ok,
                      'at_or_below_step': step_s is not None and iv <= step_s})
        if iv > best and not stopped:
            if ok:
                chosen = iv
            else:
                stopped = True
    for t in tests:
        t['best'] = t['interval_s'] == best
        t['chosen'] = t['interval_s'] == chosen
    return {'best': best, 'chosen': chosen, 'margin_pp': margin_pp, 'tests': tests,
            'step_s': step_s,
            'resolution_limited': step_s is not None and chosen <= step_s}


# --------------------------------------------------------------- the experiment

def run(workers=None, **overrides):
    cfg = common.make_config(DEFAULTS, overrides)
    print("EXPERIMENT 7: schedule interval sweep")
    intervals = cfg['intervals']
    bad = [iv for iv in intervals if cfg['window_s'] % iv]
    if bad:
        raise ValueError(f"window_s={cfg['window_s']} is not a multiple of intervals {bad}")

    with RunTimer() as timer:
        period = orbital_period_s()
        offsets = window_offsets(cfg['n_offsets'], period)
        print(f"  {len(offsets)} windows of {cfg['window_s']} s spread over one orbit "
              f"({period / 60:.1f} min)")
        tasks = [(j, off, cfg['window_s'], cfg['step_s'], tuple(intervals),
                  tuple(tuple(f) for f in cfg['flows']), cfg['slack'], cfg['unit_code'],
                  cfg['probe_slack'], cfg['probe_unit_code'], cfg['packet_interval_ms'])
                 for j, off in enumerate(offsets)]
        windows = common.pmap(run_window, tasks, workers,
                              common.worker_mb(cfg['window_s'], cfg['step_s']))
        flow_rows = [r for w in windows for r in w['rows']]

        def per_window(key, iv):
            """One number per window: the mean over flows, in percent."""
            out = []
            for w in windows:
                rs = [r for r in w['rows'] if r['interval_s'] == iv]
                out.append(100.0 * sum(r[key] for r in rs) / len(rs))
            return out

        metrics = ['stale_probe', 'link_failed', 'deadline_missed']
        series = {(m, iv): per_window(m, iv) for m in metrics for iv in intervals}
        for iv in intervals:
            series[('total_deviation', iv)] = [a + b for a, b in zip(
                series[('link_failed', iv)], series[('deadline_missed', iv)])]
        stats = {k: common.mean_ci(v, bounds=(0.0, 100.0)) for k, v in series.items()}

        # control-plane cost at each interval, the SAME interval for both schemes
        e3 = exp3.DEFAULTS
        hdr = [r['mean_header_bytes'] for r in flow_rows if r['mean_header_bytes']]
        mean_header = sum(hdr) / len(hdr)
        tcrh_bps = {iv: e3['num_gateways'] * e3['flows_per_gateway'] * mean_header / iv
                    for iv in intervals}
        table_bps = {iv: exp3.table_upload_bytes_per_sec(C.num_sats(), e3, iv)
                     for iv in intervals}

        choice = choose_interval(intervals,
                                 {iv: series[('stale_probe', iv)] for iv in intervals},
                                 cfg['margin_pp'], step_s=cfg['step_s'])
        n_win = len(windows)

        rows = []
        for iv in intervals:
            for m in metrics + ['total_deviation']:
                mean, lo, hi, n = stats[(m, iv)]
                rows.append({'interval_s': iv, 'metric': m, 'unit': 'percent_of_packets',
                             'mean': mean, 'ci95_lo': lo, 'ci95_hi': hi, 'n_windows': n})
            rows.append({'interval_s': iv, 'metric': 'tcrh_control_bytes_per_s',
                         'unit': 'bytes_per_s', 'mean': tcrh_bps[iv], 'ci95_lo': None,
                         'ci95_hi': None, 'n_windows': n_win})
            rows.append({'interval_s': iv, 'metric': 'table_upload_bytes_per_s',
                         'unit': 'bytes_per_s', 'mean': table_bps[iv], 'ci95_lo': None,
                         'ci95_hi': None, 'n_windows': n_win})
            sp, dm = stats[('stale_probe', iv)], stats[('deadline_missed', iv)]
            print(f"  interval={iv:3d}s  stale-path={sp[0]:5.2f}% "
                  f"[{_f(sp[1])}, {_f(sp[2])}]  missed-deadline(S={cfg['slack']})="
                  f"{dm[0]:5.1f}%  control-plane={tcrh_bps[iv]:6.0f} B/s")

        fig = plot(cfg, stats, tcrh_bps, table_bps, choice, n_win, period)

    config = {**common.scenario_config(), **cfg, 'offsets_s': offsets,
              'orbital_period_s': period,
              'crn_seed_rule': 'window_index * 1000 + flow_index',
              'unit_of_analysis': 'window (mean over flows)',
              'chooser': 'walk up from the lowest-mean interval while the 95% t-CI upper '
                         'end of the paired difference is <= margin_pp; a chosen interval '
                         '<= step_s is reported as resolution-limited',
              'control_plane_formulas': 'exp3_control_plane (same interval for both)',
              'exp3_parameters': {k: e3[k] for k in ('num_gateways', 'flows_per_gateway',
                                                     'num_destinations', 'fib_entry_bytes')}}
    seeds = [common.crn_seed(j, fi) for j in range(n_win) for fi in range(len(cfg['flows']))]
    agg = {'samples': sum(w['stats']['samples'] for w in windows),
           'skipped': sum(w['stats']['skipped'] for w in windows)}
    out = common.write_results(
        NAME, fig=fig,
        tables=[(f'{NAME}.csv', ['interval_s', 'metric', 'unit', 'mean', 'ci95_lo', 'ci95_hi',
                                 'n_windows'], rows),
                ('exp7_chooser.csv', ['interval_s', 'mean_pct', 'diff_vs_best_pp',
                                      'diff_ci95_lo_pp', 'diff_ci95_hi_pp', 'n_windows',
                                      'non_inferior', 'at_or_below_step', 'best', 'chosen'],
                 choice['tests']),
                ('exp7_windows.csv', ['window', 'offset_s', 'interval_s', 'flow', 'crn_seed',
                                      'packets', 'link_failed', 'deadline_missed',
                                      'stale_probe', 'probe_deadline_missed',
                                      'schedule_entries', 'mean_header_bytes'], flow_rows)],
        config=config, seeds=seeds, labels=LABELS,
        extra={'propagation': agg, 'mean_header_bytes': mean_header,
               'recommended_interval_s': choice['chosen'], 'best_interval_s': choice['best'],
               'resolution_limited': choice['resolution_limited'],
               'workers': common.LAST_WORKERS},
        timer=timer)

    iv = choice['chosen']
    if choice['resolution_limited']:
        print(f"\n  RESULT: no interval longer than the {cfg['step_s']} s simulation step keeps "
              f"the stale-path rate within {cfg['margin_pp']} pp of the best "
              f"({choice['best']} s) with 95% confidence.")
        print(f"  The chooser lands on {iv} s only because an interval of one simulation "
              f"step is never stale here (resolution-limited, not a measured optimum).")
        print(f"  Cost at {iv} s: {tcrh_bps[iv]:.0f} B/s "
              f"(table upload at the same interval: {table_bps[iv]:.0f} B/s).")
    else:
        print(f"\n  RESULT: {iv}s is the longest interval whose stale-path rate is within "
              f"{cfg['margin_pp']} pp of the best ({choice['best']}s) with 95% confidence,")
        print(f"  at a control-plane cost of {tcrh_bps[iv]:.0f} B/s "
              f"(table upload at the same interval: {table_bps[iv]:.0f} B/s).")

    return {'intervals': intervals,
            'stale_path': [stats[('stale_probe', iv)][0] for iv in intervals],
            'missed_deadline': [stats[('deadline_missed', iv)][0] for iv in intervals],
            'control_bytes': [tcrh_bps[iv] for iv in intervals],
            'recommended': choice['chosen'], 'best': choice['best'],
            'resolution_limited': choice['resolution_limited'], 'outputs': out}


def _f(x):
    return 'n/a' if x is None else f"{x:.2f}"


def plot(cfg, stats, tcrh_bps, table_bps, choice, n_win, period):
    intervals = cfg['intervals']
    style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    def curve(m):
        pts = [stats[(m, iv)] for iv in intervals]
        nan = float('nan')
        return ([p[0] for p in pts], [nan if p[1] is None else p[1] for p in pts],
                [nan if p[2] is None else p[2] for p in pts])

    # --- left: the two failure modes separate cleanly ---
    for m, label, colour, sty in [
            ('stale_probe', 'stale path (probe, deadline off)', '#c0392b', 'o-'),
            ('link_failed', f"'link_failed' at S = {cfg['slack']}", '#e67e22', 'v--'),
            ('deadline_missed', f"'deadline_missed' at S = {cfg['slack']}", '#2471a3', 's-'),
            ('total_deviation', f"total deviation at S = {cfg['slack']}", '#7f8c8d', '^:')]:
        mean, lo, hi = curve(m)
        ax1.plot(intervals, mean, sty, lw=2.2, ms=5, color=colour, label=label)
        ax1.fill_between(intervals, lo, hi, color=colour, alpha=0.15, lw=0)
    if choice['resolution_limited']:
        chosen_label = (f"<= {choice['chosen']} s: no longer interval is within "
                        f"{choice['margin_pp']} pp\n(limited by the {cfg['step_s']} s "
                        f"simulation step)")
    else:
        chosen_label = (f"chosen: {choice['chosen']} s (within {choice['margin_pp']} pp "
                        f"of the best, 95% CI)")
    ax1.axvline(choice['chosen'], color='#27ae60', ls='--', lw=1.8, label=chosen_label)
    ax1.set_xlabel('Schedule recomputation interval (seconds)')
    ax1.set_ylabel('Percentage of packets (%)')
    ax1.set_title('Two failure modes, two different knobs')
    ax1.legend(fontsize=8.5, loc='upper left')

    # --- right: the cost of a shorter interval ---
    ax2b = ax2.twinx()
    mean, lo, hi = curve('stale_probe')
    ax2.plot(intervals, mean, 'o-', lw=2.4, ms=6, color='#c0392b',
             label='Stale-path failures (%)')
    ax2.fill_between(intervals, lo, hi, color='#c0392b', alpha=0.15, lw=0)
    ax2b.plot(intervals, [tcrh_bps[iv] for iv in intervals], 's-', lw=2.4, ms=6,
              color='#e67e22', label='T-CRH control plane (B/s)')
    ax2b.plot(intervals, [table_bps[iv] for iv in intervals], 'd--', lw=1.8, ms=5,
              color='#7f8c8d', label='Table upload, same interval (B/s)')
    ax2b.set_yscale('log')
    ax2.set_xlabel('Schedule recomputation interval (seconds)')
    ax2.set_ylabel('Stale-path failures (%)', color='#c0392b')
    ax2b.set_ylabel('Control-plane traffic (bytes/second, log)', color='#e67e22')
    ax2.tick_params(axis='y', labelcolor='#c0392b')
    ax2b.tick_params(axis='y', labelcolor='#e67e22')
    ax2.set_title('Freshness costs control-plane bandwidth')
    ax2b.grid(False)
    lines = ax2.get_lines() + ax2b.get_lines()
    ax2.legend(lines, [ln.get_label() for ln in lines], fontsize=8.5, loc='upper center')

    fig.suptitle('Experiment 7: the schedule interval is a second, independent control\n'
                 f'{n_win} windows of {cfg["window_s"]} s across one orbit '
                 f'({period / 60:.1f} min); mean and 95% t-CI over windows',
                 fontsize=13, fontweight='bold', y=1.04)
    return fig


if __name__ == '__main__':
    import scale
    scale.use_preset('starlink')
    scale.install_fast_topology()
    common.RESULTS_DIR = common.results_dir_for('starlink')
    run()

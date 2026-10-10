"""
EXPERIMENT 4 -- Failure resilience
==================================

Question
--------
When inter-satellite links genuinely break, does the Deviation_Flag plus
geographic fallback actually save the traffic?

We inject random ISL failures at increasing rates (held for the whole run)
and compare three ways of forwarding the same packets:

  A. ORACLE REROUTE     the source knows the true faulted topology at the
                        moment it sends and runs Dijkstra on it. Nothing
                        real can beat this; it is the ceiling.
  B. T-CRH + FALLBACK   our full design: follow the schedule, and when the
                        next link is down, set the Deviation_Flag and go
                        greedy-geographic.
  C. T-CRH, NO FALLBACK the pure deterministic schedule: a broken link on
                        the pre-computed path kills the packet.

v0 compared only B with C. C is a strawman -- nobody would deploy it -- so
"fallback beats no fallback" says little. The honest question is how much
of the gap to the oracle the zero-state fallback closes, so A is now drawn
next to B and C.

Statistics: each trial draws its own random failure set; the three methods
see the same failures and the same packets (common random numbers). A
trial's number is the mean over the flows, and the plot shows the mean and
Student-t 95% CI over the trials.
"""

import random

import matplotlib.pyplot as plt
import networkx as nx

import common
import topology as T
from common import style
from scheduler import generate_schedules
from simulator import simulate_flow, summarise
from chronoroute import proto
from chronoroute.provenance import RunTimer

NAME = 'exp4_failure_resilience'
FAILURE_SEED_BASE = 1000      # trial t draws its failures with random.Random(1000 + t)

DEFAULTS = {
    'duration_s': common.DURATION_S,
    'step_s': common.STEP_S,
    'failure_rates': [0.0, 0.01, 0.02, 0.05, 0.10, 0.15, 0.20],
    'slack': 1.2,             # the v0 operating point (see Experiment 1 for v0.9's)
    'unit_code': 0,           # 1 ms, as v0
    'num_packets': 200,
    'packet_interval_ms': 500,
    'trials': 10,             # independent failure draws
    'flows': list(common.FLOWS),
}

LABELS = {
    'constellation': 'MODELLED',
    'ground_stations': 'REAL',
    'link_failures': 'MODELLED',    # uniformly random ISLs, static for the run
    'queueing_delay': 'MODELLED',
    'oracle': 'DERIVED',            # Dijkstra on the faulted graph at send time
}

METHODS = [
    # key, label, colour, style
    ('oracle_reroute', 'Oracle reroute (Dijkstra on the faulted graph at send time)',
     '#2c3e50', '^-'),
    ('fallback', 'T-CRH + geographic fallback (ours)', '#27ae60', 'o-'),
    ('no_fallback', 'T-CRH, pure schedule, no fallback', '#c0392b', 's--'),
]


def random_failures(rate, rng):
    """Pick a random subset of the ACTIVE constellation's inter-satellite links to break."""
    pairs = list(T.isl_pairs())          # read at call time: follows preset switches
    n = int(len(pairs) * rate)
    chosen = rng.sample(pairs, n)
    return {frozenset({a, b}) for a, b, _ in chosen}


def oracle_delivery(times, graphs, flow, failed, num_packets, packet_interval_ms):
    """
    For each packet the simulator would send, can a source that knows the
    true faulted topology at send time reach the destination? It runs
    Dijkstra on the graph of that moment with the failed links removed.
    Returns (delivered, total, mean path delay in ms of the delivered).
    """
    src, dst = flow
    hidden = [tuple(link) for link in failed]
    t_first = proto.seconds_to_ns(times[0])
    t_last = proto.seconds_to_ns(times[-1])
    step = proto.seconds_to_ns(times[1] - times[0]) if len(times) > 1 else proto.NS_PER_S
    interval = proto.ms_to_ns(packet_interval_ms)
    per_step = {}
    delivered = total = 0
    delays = []
    for k in range(num_packets):
        send = k * interval
        if send > t_last:                 # same send rule as simulate_flow
            break
        idx = max(0, min((send - t_first) // step, len(graphs) - 1))
        if idx not in per_step:
            view = nx.restricted_view(graphs[idx], [], hidden)
            try:
                per_step[idx] = nx.shortest_path_length(view, src, dst, weight='weight')
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                per_step[idx] = None
        total += 1
        if per_step[idx] is not None:
            delivered += 1
            delays.append(per_step[idx])
    return delivered, total, (sum(delays) / len(delays) if delays else None)


def run_trial(task):
    """One (failure rate, trial): every flow, all three methods, same failures."""
    (rate, trial, flows, slack, unit_code, num_packets, interval_ms,
     duration_s, step_s) = task
    times, sat_pos, gs_pos, graphs = common.setup(duration_s, step_s, verbose=False)
    failed = random_failures(rate, random.Random(FAILURE_SEED_BASE + trial))
    rows = []
    for fi, flow in enumerate(flows):
        # the planner does not know about the failures: schedules come from
        # the healthy topology, exactly as before
        sch = generate_schedules(times, sat_pos, gs_pos, [flow], slack_factor=slack,
                                 unit_code=unit_code, graphs=graphs)
        seed = common.crn_seed(trial, fi)
        # the graphs keep the failed links; failed_links tells every node
        # its own link is down (the simulator's bug-#2 fix makes that safe)
        a = summarise(simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                                    num_packets, interval_ms, failed_links=failed, seed=seed))
        b = summarise(simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                                    num_packets, interval_ms, failed_links=failed,
                                    disable_fallback=True, seed=seed))
        o_del, o_tot, o_ms = oracle_delivery(times, graphs, flow, failed,
                                             num_packets, interval_ms)
        base = {'failure_rate': rate, 'trial': trial, 'flow': common.flow_label(flow),
                'crn_seed': seed, 'failed_links': len(failed)}
        rows.append({**base, 'method': 'fallback', 'delivered': a['delivered'],
                     'total': a['total'], 'via_fallback': a['via_fallback'],
                     'mean_latency_ms': a['mean_latency_ms']})
        rows.append({**base, 'method': 'no_fallback', 'delivered': b['delivered'],
                     'total': b['total'], 'via_fallback': b['via_fallback'],
                     'mean_latency_ms': b['mean_latency_ms']})
        rows.append({**base, 'method': 'oracle_reroute', 'delivered': o_del, 'total': o_tot,
                     'via_fallback': 0, 'mean_latency_ms': o_ms})
    return rows


def run(workers=None, **overrides):
    cfg = common.make_config(DEFAULTS, overrides)
    print("EXPERIMENT 4: failure resilience")
    rates, trials = cfg['failure_rates'], list(range(cfg['trials']))

    with RunTimer() as timer:
        common.setup(cfg['duration_s'], cfg['step_s'])
        tasks = [(r, t, tuple(tuple(f) for f in cfg['flows']), cfg['slack'], cfg['unit_code'],
                  cfg['num_packets'], cfg['packet_interval_ms'], cfg['duration_s'],
                  cfg['step_s']) for r in rates for t in trials]
        per_flow = [row for rows in common.pmap(
            run_trial, tasks, workers, common.worker_mb(cfg['duration_s'], cfg['step_s']))
            for row in rows]

        def trial_means(rate, method, key='delivered'):
            """One number per trial: the mean over flows of key/total."""
            out = []
            for t in trials:
                rs = [r for r in per_flow if r['failure_rate'] == rate and r['trial'] == t
                      and r['method'] == method and r['total']]
                if rs:
                    out.append(sum(r[key] / r['total'] for r in rs) / len(rs))
            return out

        curves, rows = {}, []
        for rate in rates:
            for method, *_ in METHODS:
                curves[(method, rate)] = common.mean_ci(trial_means(rate, method),
                                                        bounds=(0.0, 1.0))
            curves[('fallback_share', rate)] = common.mean_ci(
                trial_means(rate, 'fallback', 'via_fallback'), bounds=(0.0, 1.0))
            for method in [m for m, *_ in METHODS] + ['fallback_share']:
                mean, lo, hi, n = curves[(method, rate)]
                rows.append({'failure_rate_pct': 100 * rate, 'method': method,
                             'mean_pct': common.pct(mean), 'ci95_lo_pct': common.pct(lo),
                             'ci95_hi_pct': common.pct(hi), 'n_trials': n})
            m = {k: common.pct(curves[(k, rate)][0]) for k in
                 ('oracle_reroute', 'fallback', 'no_fallback', 'fallback_share')}
            print(f"  {rate*100:5.1f}% links failed -> oracle {m['oracle_reroute']:5.1f}%  |  "
                  f"with fallback {m['fallback']:5.1f}%  |  "
                  f"without fallback {m['no_fallback']:5.1f}%  |  "
                  f"via fallback {m['fallback_share']:5.1f}%")

        style()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))
        xs = [100 * r for r in rates]

        def series(key):
            pts = [curves[(key, r)] for r in rates]
            return ([common.pct(p[0]) for p in pts],
                    [float('nan') if p[1] is None else 100 * p[1] for p in pts],
                    [float('nan') if p[2] is None else 100 * p[2] for p in pts])

        for key, label, colour, sty in METHODS:
            mean, lo, hi = series(key)
            ax1.plot(xs, mean, sty, lw=2.4, ms=6, color=colour, label=label)
            ax1.fill_between(xs, lo, hi, color=colour, alpha=0.15, lw=0)
        ax1.set_xlabel('Percentage of inter-satellite links broken (%)')
        ax1.set_ylabel('Packet delivery rate (%)')
        ax1.set_title('Delivery under link failure: fallback vs the oracle')
        ax1.legend(fontsize=8.5, loc='lower left')
        ax1.set_ylim(-4, 104)

        mid = len(xs) // 2
        o, f, nf = (series(k)[0][mid] for k in ('oracle_reroute', 'fallback', 'no_fallback'))
        ax1.annotate(f'fallback recovers {f - nf:+.0f} pp over no fallback;\n'
                     f'{o - f:.0f} pp below the oracle',
                     xy=(xs[mid], (f + nf) / 2), xytext=(xs[mid] * 0.35, 30), fontsize=9,
                     color='#27ae60', fontweight='bold',
                     arrowprops=dict(arrowstyle='->', color='#27ae60', lw=1.4))

        share, lo, hi = series('fallback_share')
        err = [[s - l if l == l else 0 for s, l in zip(share, lo)],
               [h - s if h == h else 0 for s, h in zip(share, hi)]]
        ax2.bar(xs, share, width=1.1, color='#2471a3', yerr=err, capsize=3,
                ecolor='#2c3e50')
        ax2.set_xlabel('Percentage of inter-satellite links broken (%)')
        ax2.set_ylabel('Packets delivered via fallback (%)')
        ax2.set_title('How often the Deviation_Flag is doing the work')

        fig.suptitle('Experiment 4: resilience to unmodelled link failure\n'
                     f'mean and 95% t-CI over {len(trials)} failure draws '
                     f'({len(cfg["flows"])} flows each)',
                     fontsize=13, fontweight='bold', y=1.04)

    seeds = [common.crn_seed(t, fi) for t in trials for fi in range(len(cfg['flows']))]
    config = {**common.scenario_config(), **cfg,
              'failure_seed_rule': 'random.Random(1000 + trial)',
              'crn_seed_rule': 'trial * 1000 + flow_index',
              'oracle': 'Dijkstra on the true faulted graph of the send-time step; '
                        'delivered iff a path exists',
              'ci': 'Student-t 95% over trials (mean over flows per trial), '
                    'truncated to [0, 100]%'}
    out = common.write_results(
        NAME, fig=fig,
        tables=[(f'{NAME}.csv', ['failure_rate_pct', 'method', 'mean_pct', 'ci95_lo_pct',
                                 'ci95_hi_pct', 'n_trials'], rows),
                ('exp4_per_flow.csv', ['failure_rate', 'trial', 'flow', 'crn_seed',
                                       'failed_links', 'method', 'delivered', 'total',
                                       'via_fallback', 'mean_latency_ms'], per_flow)],
        config=config, seeds=seeds, labels=LABELS,
        extra={'propagation': common.setup_stats(cfg['duration_s'], cfg['step_s']),
               'workers': common.LAST_WORKERS},
        timer=timer)

    return {'rates': rates,
            'oracle': [common.pct(curves[('oracle_reroute', r)][0]) for r in rates],
            'with_fallback': [common.pct(curves[('fallback', r)][0]) for r in rates],
            'without_fallback': [common.pct(curves[('no_fallback', r)][0]) for r in rates],
            'outputs': out}


if __name__ == '__main__':
    run()

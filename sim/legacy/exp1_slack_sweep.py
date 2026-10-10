"""
EXPERIMENT 1 -- Slack factor sweep  (THE HEADLINE RESULT)
========================================================

Question
--------
Each hop's deadline is set to  SLACK * predicted_delay.  What should SLACK be?

The trade-off
-------------
  SLACK too tight -> normal queueing jitter and schedule staleness push
                     healthy packets past their deadline. They deviate to the
                     fallback path for no reason. This is a FALSE POSITIVE.

  SLACK too loose -> a link that has genuinely degraded (solar interference,
                     link-layer retransmission, congestion) stays inside its
                     budget, so nothing notices. This is a MISSED DETECTION.

Note that a degraded link is still UP. A link-state check cannot see it.
The deadline is the ONLY mechanism that can, which is precisely why we put
deadlines in the header.

How we score it (v0.9: COUNTERFACTUAL, with common random numbers)
-----------------------------------------------------------------
v0 called a packet "detected" if it crossed the slow link and was flagged
at all. But a packet that is late because of jitter somewhere else is
flagged whether the link is slow or not, so v0's detection rate could
never fall below the false-positive rate: a 1.0001x "fault" (no fault at
all) was "detected" 22.4% of the time at S = 1.2 (bug #3).

Now every run sends the SAME packets twice, with the same random draws
(simulator: common random numbers): once on the healthy network and once
with the fault. Only the fault differs, so

  detection  = packets flagged WITH the fault and NOT flagged without it,
               among the packets that actually crossed the degraded link
  FPR        = packets flagged by a DEADLINE check on the healthy network,
               over all its packets (plan 5.3). Deviations because a planned
               link no longer exists (stale schedule) are their own class:
               no slack can fix them; that is Experiment 7.
  null fault = the same scoring with a 1.0x "fault". Its attributed
               detection must be EXACTLY 0; the run stops if it is not.

Every run is one (flow, seed); each run degrades a randomly chosen
inter-satellite link of its flow's path at t=0. The seeds of one flow share
its geometry (the stale-path rate, for instance, is identical in all of
them), so they are NOT independent samples: the FLOW is the unit of
analysis. Each number is the mean over flows of the per-flow mean over
seeds, with a Student-t 95% CI over the flows (n_flows - 1 degrees of
freedom). With three flows those intervals are wide; that is the honest
amount we know. The packet is never the unit of analysis.
We run both deadline units: code 0 (1 ms, as v0) and code 1 (0.1 ms, the
provisional v1 default).

Choosing the operating point
----------------------------
v0 maximised Youden's J (detection - FPR), which happily trades a few
points of false alarms for detection. A false alarm sends a healthy packet
into the fallback, so we now pick the slack the way a detector threshold
is picked (Neyman-Pearson): the HIGHEST detection whose MEAN FPR is at most
1% (the limit is on the mean, not on the upper end of its CI). A slack only
counts if its mean detection is at least as large as that FPR limit:
otherwise the "detector" flags fewer slow-link packets than the false-alarm
budget allows on healthy ones, and the slack is reported as no operating
point at all (v0.9 first drew S = 1.75 with 0.08% detection as one).
Youden's J is still reported, for continuity with v0 only. Experiment 6
uses exactly the same rule (operating_points below).
"""

import random
from collections import Counter

import matplotlib.pyplot as plt

import common
from common import style
from scheduler import generate_schedules, compute_path
from simulator import simulate_flow, attributed_deviations
from chronoroute import proto
from chronoroute.provenance import RunTimer

NAME = 'exp1_slack_sweep'

NULL_FAULT = 1.0             # the control: a "fault" that changes nothing
NEAR_NULL_FAULT = 1.0001     # v0's bug-#3 probe; honest detection ~ 0

DEFAULTS = {
    'duration_s': common.DURATION_S,
    'step_s': common.STEP_S,
    'slacks': [1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.4, 1.5, 1.75, 2.0, 2.5, 3.0],
    'unit_codes': [0, 1],
    'degradations': [NEAR_NULL_FAULT, 1.2, 1.5, 2.0, 3.0],   # severity multipliers
    'reference_degradation': 1.5,    # the one the operating point is chosen on
    'seeds': list(range(1, 11)),
    'flows': list(common.FLOWS),
    'num_packets': 400,
    'packet_interval_ms': 250,
    'fpr_max': 0.01,                 # Neyman-Pearson constraint: FPR <= 1 %
}

LABELS = {
    'constellation': 'MODELLED',     # synthetic Walker shell (preset parameters)
    'ground_stations': 'REAL',       # real city coordinates (WGS84)
    'propagation_delay': 'DERIVED',  # speed of light over the modelled geometry
    'queueing_delay': 'MODELLED',    # exponential, mean simulator.QUEUEING_MEAN_MS
    'link_fault': 'MODELLED',        # a delay multiplier on one live ISL
    'header_bytes': 'REAL',          # every packet carries real T-CRH bytes
}


# --------------------------------------------------------------- one run

def pick_link(graph, flow, rng):
    """
    Choose one inter-satellite link of the flow's shortest path in `graph`
    to degrade (a ground link is not an ISL). The path does not depend on
    the slack, so every slack and unit code degrades the same link.
    """
    path, _ = compute_path(graph, flow[0], flow[1])
    if path is None:
        return None
    isls = [frozenset((a, b)) for a, b in zip(path[:-1], path[1:])
            if isinstance(a, int) and isinstance(b, int)]
    return rng.choice(isls) if isls else None


def crosses(path, link):
    """Did a packet that visited `path` (in order) traverse `link`?"""
    return any(frozenset((a, b)) == link for a, b in zip(path[:-1], path[1:]))


def run_cell(task):
    """
    One run = one (unit code, slack, flow, seed): the healthy network and
    then every fault, all with the same common-random-numbers seed.
    Returns a small dict of per-run numbers (fractions, not percentages).
    """
    (unit_code, slack, flow_index, flow, seed, factors,
     num_packets, interval_ms, duration_s, step_s) = task
    times, sat_pos, gs_pos, graphs = common.setup(duration_s, step_s, verbose=False)
    run_seed = common.crn_seed(seed, flow_index)
    link = pick_link(graphs[0], flow, random.Random(run_seed))

    sch = generate_schedules(times, sat_pos, gs_pos, [flow], slack_factor=slack,
                             unit_code=unit_code, graphs=graphs)
    clean = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                          num_packets, interval_ms, seed=run_seed)
    n = len(clean)
    reasons = Counter(r['deviation_reason'] for r in clean)
    flagged_clean = {r['pid'] for r in clean if r['deviated']}
    crossed = set() if link is None else {
        r['pid'] for r in clean if crosses(r['path_taken'], link)}

    out = {
        'unit_code': unit_code, 'slack': slack, 'flow_index': flow_index,
        'flow': common.flow_label(flow), 'seed': seed, 'crn_seed': run_seed,
        'link': None if link is None else '-'.join(str(x) for x in sorted(link)),
        'packets': n, 'crossed': len(crossed),
        'fpr_deadline': reasons.get('deadline_missed', 0) / n if n else None,
        'stale': reasons.get('link_failed', 0) / n if n else None,
        'flagged': len(flagged_clean) / n if n else None,
        'faults': [],
    }

    for m in factors:
        if link is None:
            out['faults'].append({'degradation': m, 'attributed': 0, 'attributed_crossed': 0,
                                  'attributed_not_crossed': 0, 'detection': None,
                                  'detection_among_unflagged': None,
                                  'v0_confounded_detection': None})
            continue
        faulty = simulate_flow(times, graphs, sat_pos, gs_pos, sch, flow,
                               num_packets, interval_ms,
                               degraded_links={link: m}, seed=run_seed)
        attributed = set(attributed_deviations(clean, faulty))
        hit = {r['pid'] for r in faulty if r['hit_degraded']}

        # Common random numbers make the two runs identical up to the first
        # traversal of the slow link, so these are guaranteed. If they ever
        # fail, the scoring would be wrong, so stop rather than plot it.
        if m == NULL_FAULT and attributed:
            raise RuntimeError(f"null-fault control attributed {len(attributed)} flags "
                               f"({out['flow']}, S={slack}, unit {unit_code}, seed {seed})")
        if m > 1.0 and hit != crossed:
            raise RuntimeError("faulty run crossed the slow link on different packets "
                               "than the healthy run: common random numbers are broken")
        unflagged = crossed - flagged_clean
        out['faults'].append({
            'degradation': m,
            'attributed': len(attributed),
            'attributed_crossed': len(attributed & crossed),
            'attributed_not_crossed': len(attributed - crossed),
            'detection': len(attributed & crossed) / len(crossed) if crossed else None,
            # the same, among the crossing packets the healthy run did not
            # already flag (those cannot be "detected" by construction)
            'detection_among_unflagged': (len(attributed & unflagged) / len(unflagged)
                                          if unflagged else None),
            # v0's metric, kept to show the confound: flagged at all, among
            # the packets that crossed the slow link
            'v0_confounded_detection': (sum(1 for r in faulty if r['hit_degraded']
                                            and r['deviated']) / len(hit)
                                        if hit else None),
        })
    return out


def counterfactual_sweep(*, slacks, unit_codes, factors, seeds, flows, num_packets,
                         packet_interval_ms, duration_s, step_s, workers=None):
    """Every (unit code, slack, flow, seed) run, in a fixed order."""
    tasks = [(u, s, fi, tuple(flow), seed, tuple(factors), num_packets,
              packet_interval_ms, duration_s, step_s)
             for u in unit_codes for s in slacks
             for fi, flow in enumerate(flows) for seed in seeds]
    return common.pmap(run_cell, tasks, workers,
                       per_worker_mb=common.worker_mb(duration_s, step_s))


# --------------------------------------------------------------- statistics

CURVE_FIELDS = ['unit_code', 'unit_ms', 'slack', 'metric', 'degradation',
                'mean_pct', 'ci95_lo_pct', 'ci95_hi_pct', 'n_runs', 'n_flows']


def unit_ms(unit_code):
    return proto.UNIT_NS[unit_code] / 1e6


def summarise_runs(runs, slacks, unit_codes, factors):
    """
    The plotted curves: per (unit code, slack) the false-positive rates,
    and per degradation the detection rates. Each is the mean over FLOWS of
    the per-flow mean over seeds, with a t-CI over the flows
    (common.cluster_mean_ci): the seeds of one flow are not independent.
    Returns (rows, lookup) where lookup[(unit, slack, metric, degradation)]
    = (mean_pct, lo_pct, hi_pct, n_flows). Each CSV row also says how many
    runs (flow x seed) had a defined value.
    """
    rows, lookup = [], {}

    def add(u, s, metric, deg, pairs):
        values = [v for v, _ in pairs]
        mean, lo, hi, n_flows = common.cluster_mean_ci(values, [f for _, f in pairs],
                                                       bounds=(0.0, 1.0))
        entry = (common.pct(mean), common.pct(lo), common.pct(hi), n_flows)
        lookup[(u, s, metric, deg)] = entry
        rows.append({'unit_code': u, 'unit_ms': unit_ms(u), 'slack': s, 'metric': metric,
                     'degradation': deg, 'mean_pct': entry[0], 'ci95_lo_pct': entry[1],
                     'ci95_hi_pct': entry[2],
                     'n_runs': sum(v is not None for v in values), 'n_flows': n_flows})

    for u in unit_codes:
        for s in slacks:
            rs = [r for r in runs if r['unit_code'] == u and r['slack'] == s]
            add(u, s, 'fpr_deadline', None, [(r['fpr_deadline'], r['flow_index']) for r in rs])
            add(u, s, 'stale_path_rate', None, [(r['stale'], r['flow_index']) for r in rs])
            add(u, s, 'flagged_any_rate', None, [(r['flagged'], r['flow_index']) for r in rs])
            for m in factors:
                fs = [(f, r['flow_index']) for r in rs for f in r['faults']
                      if f['degradation'] == m]
                add(u, s, 'detection', m, [(f['detection'], fi) for f, fi in fs])
                add(u, s, 'detection_among_unflagged', m,
                    [(f['detection_among_unflagged'], fi) for f, fi in fs])
                if m != NULL_FAULT:
                    add(u, s, 'v0_confounded_detection', m,
                        [(f['v0_confounded_detection'], fi) for f, fi in fs])
    return rows, lookup


def choose_operating_point(slacks, detection, fpr, fpr_max_pct, min_detection_pct=None):
    """
    Neyman-Pearson: the slack with the highest mean detection among those
    whose MEAN false-positive rate is at most fpr_max_pct. Ties go to the
    lower FPR, then to the larger slack.

    A slack only qualifies if its mean detection is at least
    min_detection_pct (default: the FPR limit itself), and above zero. A
    "detector" that catches 0.08% of slow-link packets while it may raise
    false alarms on 1% of healthy ones is not an operating point; without
    this floor the rule drew any detection above zero as one, and with
    nothing detected the tie-break would "choose" the loosest slack.

    None if no slack qualifies.
    """
    if min_detection_pct is None:
        min_detection_pct = fpr_max_pct
    feasible = [(d, -f, s) for s, d, f in zip(slacks, detection, fpr)
                if d is not None and f is not None and f <= fpr_max_pct
                and d >= min_detection_pct and d > 0]
    if not feasible:
        return None
    return max(feasible)[2]


def youden_point(slacks, detection, fpr):
    """v0's criterion (max detection - FPR), reported for continuity only."""
    scores = [(d - f) if d is not None and f is not None else None
              for d, f in zip(detection, fpr)]
    valid = [x for x in scores if x is not None]
    return slacks[scores.index(max(valid))] if valid else None


def operating_points(lookup, slacks, unit_codes, ref, fpr_max_pct, min_detection_pct=None):
    """
    Both criteria for every unit code, as CSV rows. Experiments 1 and 6 both
    call this, so they always apply the same rule.
    """
    if min_detection_pct is None:
        min_detection_pct = fpr_max_pct
    rows = []
    for u in unit_codes:
        det = [lookup[(u, s, 'detection', ref)][0] for s in slacks]
        fpr = [lookup[(u, s, 'fpr_deadline', None)][0] for s in slacks]
        for criterion, s in [
                (f'max detection at {ref}x subject to mean FPR <= {fpr_max_pct:g}% '
                 f'and mean detection >= {min_detection_pct:g}%',
                 choose_operating_point(slacks, det, fpr, fpr_max_pct, min_detection_pct)),
                ('Youden J = detection - FPR (continuity only)',
                 youden_point(slacks, det, fpr))]:
            i = slacks.index(s) if s is not None else None
            rows.append({
                'unit_code': u, 'unit_ms': unit_ms(u), 'criterion': criterion,
                'reference_degradation': ref, 'slack': s,
                'detection_pct': None if i is None else det[i],
                'detection_ci95_lo_pct': None if i is None
                else lookup[(u, s, 'detection', ref)][1],
                'fpr_deadline_pct': None if i is None else fpr[i],
                'fpr_ci95_hi_pct': None if i is None
                else lookup[(u, s, 'fpr_deadline', None)][2],
            })
    return rows


# --------------------------------------------------------------- plot

def _nan(x):
    return float('nan') if x is None else x


def _curve(lookup, u, slacks, metric, deg):
    pts = [lookup[(u, s, metric, deg)] for s in slacks]
    return ([_nan(p[0]) for p in pts], [_nan(p[1]) for p in pts], [_nan(p[2]) for p in pts])


def _band(ax, xs, curve, colour):
    ax.fill_between(xs, curve[1], curve[2], color=colour, alpha=0.18, lw=0)


def plot(lookup, ops, cfg, factors, n_runs):
    slacks, units, ref = cfg['slacks'], cfg['unit_codes'], cfg['reference_degradation']
    n_flows, n_seeds = len(cfg['flows']), len(cfg['seeds'])
    style()
    fig, axes = plt.subplots(len(units), 2, figsize=(14, 5.4 * len(units)), squeeze=False,
                             layout='constrained')
    limit = 100 * cfg['fpr_max']
    for row, u in enumerate(units):
        ax1, ax2 = axes[row]
        fpr = _curve(lookup, u, slacks, 'fpr_deadline', None)
        det = _curve(lookup, u, slacks, 'detection', ref)
        null = _curve(lookup, u, slacks, 'detection', NULL_FAULT)

        ax1.plot(slacks, fpr[0], 'o-', color='#c0392b', lw=2.2, ms=6,
                 label='False positives (deadline flags, healthy network)')
        _band(ax1, slacks, fpr, '#c0392b')
        ax1.plot(slacks, det[0], 's-', color='#2471a3', lw=2.2, ms=6,
                 label=f'Detected: {ref}x slower link (counterfactual)')
        _band(ax1, slacks, det, '#2471a3')
        ax1.plot(slacks, null[0], 'k--', lw=1.4,
                 label=f'Null-fault control ({NULL_FAULT}x): exactly 0')
        ax1.axhline(limit, color='#c0392b', ls=':', lw=1, alpha=0.7,
                    label=f'limit on the mean FPR: {limit:g}%')

        op = [o for o in ops if o['unit_code'] == u]
        np_s, yj_s = op[0]['slack'], op[1]['slack']
        if np_s is not None:
            ax1.axvline(np_s, color='#27ae60', ls='--', lw=2.0,
                        label=f'Operating point S = {np_s} '
                              f'(max detection, mean FPR <= {limit:g}%)')
        else:
            ax1.text(0.5, 0.55, f'no operating point: no slack with mean FPR <= {limit:g}%\n'
                                f'detects at least {limit:g}% of the {ref}x fault',
                     transform=ax1.transAxes, ha='center', color='#27ae60',
                     fontweight='bold')
        if yj_s is not None:
            ax1.axvline(yj_s, color='#7f8c8d', ls=':', lw=1.4,
                        label=f'Youden J (continuity only): S = {yj_s}')
        ax1.set_xlabel('Slack factor S  (deadline = S x predicted delay)')
        ax1.set_ylabel('Percentage (%)')
        ax1.set_title(f'Deadline unit {unit_ms(u):g} ms (code {u}): the trade-off')
        ax1.legend(loc='upper right', fontsize=8.5)
        ax1.set_ylim(-4, 104)

        markers = ['o-', 's-', '^-', 'd-', 'v-', 'p-']
        for m, mk in zip([f for f in factors if f != NULL_FAULT], markers):
            c = _curve(lookup, u, slacks, 'detection', m)
            line, = ax2.plot(slacks, c[0], mk, lw=2, ms=5, label=f'{m}x slower link')
            _band(ax2, slacks, c, line.get_color())
        ax2.plot(slacks, fpr[0], 'k:', lw=2.2, label='False positives')
        ax2.set_xlabel('Slack factor S')
        ax2.set_ylabel('Detection rate (%)')
        ax2.set_title(f'Detection vs degradation severity (unit {unit_ms(u):g} ms)')
        ax2.legend(fontsize=8.5)
        ax2.set_ylim(-4, 104)

    fig.suptitle('Experiment 1: choosing the per-hop deadline budget\n'
                 f'counterfactual scoring, common random numbers; {n_runs} runs '
                 f'({n_flows} flows x {n_seeds} seeds); mean and 95% t-CI over flows',
                 fontsize=13, fontweight='bold')
    return fig


# --------------------------------------------------------------- the experiment

RUN_FIELDS = ['unit_code', 'slack', 'flow', 'seed', 'crn_seed', 'link', 'packets', 'crossed',
              'fpr_deadline_pct', 'stale_path_pct', 'flagged_any_pct', 'degradation',
              'attributed', 'attributed_crossed', 'attributed_not_crossed', 'detection_pct',
              'detection_among_unflagged_pct', 'v0_confounded_detection_pct']


def run_rows(runs):
    rows = []
    for r in runs:
        for f in r['faults']:
            rows.append({
                'unit_code': r['unit_code'], 'slack': r['slack'], 'flow': r['flow'],
                'seed': r['seed'], 'crn_seed': r['crn_seed'], 'link': r['link'],
                'packets': r['packets'], 'crossed': r['crossed'],
                'fpr_deadline_pct': common.pct(r['fpr_deadline']),
                'stale_path_pct': common.pct(r['stale']),
                'flagged_any_pct': common.pct(r['flagged']),
                'degradation': f['degradation'], 'attributed': f['attributed'],
                'attributed_crossed': f['attributed_crossed'],
                'attributed_not_crossed': f['attributed_not_crossed'],
                'detection_pct': common.pct(f['detection']),
                'detection_among_unflagged_pct': common.pct(f['detection_among_unflagged']),
                'v0_confounded_detection_pct': common.pct(f['v0_confounded_detection']),
            })
    return rows


def run(workers=None, **overrides):
    """
    Run the sweep and write PNG + CSVs + manifest. Any key of DEFAULTS can be
    overridden (the tests use a tiny configuration); workers=None uses as
    many processes as the machine has room for (common.pmap).
    """
    cfg = common.make_config(DEFAULTS, overrides)
    print("EXPERIMENT 1: slack factor sweep (counterfactual scoring)")
    factors = [NULL_FAULT] + [m for m in cfg['degradations'] if m != NULL_FAULT]
    if cfg['reference_degradation'] not in factors:
        raise ValueError("reference_degradation must be one of the degradations")

    with RunTimer() as timer:
        common.setup(cfg['duration_s'], cfg['step_s'])
        runs = counterfactual_sweep(
            slacks=cfg['slacks'], unit_codes=cfg['unit_codes'], factors=factors,
            seeds=cfg['seeds'], flows=cfg['flows'], num_packets=cfg['num_packets'],
            packet_interval_ms=cfg['packet_interval_ms'], duration_s=cfg['duration_s'],
            step_s=cfg['step_s'], workers=workers)
        curves, lookup = summarise_runs(runs, cfg['slacks'], cfg['unit_codes'], factors)
        ref = cfg['reference_degradation']
        ops = operating_points(lookup, cfg['slacks'], cfg['unit_codes'], ref,
                               100 * cfg['fpr_max'])
        null_attributed = sum(f['attributed'] for r in runs for f in r['faults']
                              if f['degradation'] == NULL_FAULT)
        n_runs = len(cfg['flows']) * len(cfg['seeds'])

        for u in cfg['unit_codes']:
            print(f"  -- deadline unit {unit_ms(u):g} ms (code {u}), {n_runs} runs per point, "
                  f"CI over {len(cfg['flows'])} flows")
            for s in cfg['slacks']:
                f = lookup[(u, s, 'fpr_deadline', None)]
                d = lookup[(u, s, 'detection', ref)]
                z = lookup[(u, s, 'detection', NULL_FAULT)]
                print(f"  slack={s:<5} FPR={f[0]:5.1f}%  detect({ref}x)={_fmt(d[0])}%  "
                      f"null-fault={_fmt(z[0])}%")
        fig = plot(lookup, ops, cfg, factors, n_runs)

    seeds = [common.crn_seed(s, fi) for fi in range(len(cfg['flows'])) for s in cfg['seeds']]
    config = {**common.scenario_config(), **cfg,
              'null_fault': NULL_FAULT,
              'crn_seed_rule': 'seed * 1000 + flow_index',
              'degraded_link_rule': 'random ISL of the flow path at t=0, '
                                    'random.Random(crn_seed).choice',
              'detection': 'flagged with the fault and not without it (same CRN seed), '
                           'among packets that crossed the degraded link',
              'fpr': 'deadline-check flags on the healthy network / its packets',
              'ci': 'Student-t 95% over flows (unit of analysis: the flow; each flow is '
                    'the mean of its seeds), truncated to [0, 100]%',
              'operating_point_rule': 'max mean detection at the reference degradation '
                                      'with mean FPR <= fpr_max and mean detection >= '
                                      'fpr_max; none otherwise'}
    extra = {
        'propagation': common.setup_stats(cfg['duration_s'], cfg['step_s']),
        'operating_points': [{k: o[k] for k in ('unit_code', 'criterion', 'slack')}
                             for o in ops],
        'null_fault_attributed': null_attributed,
        'runs': len(runs),
        'workers': common.LAST_WORKERS,
    }
    out = common.write_results(
        NAME, fig=fig,
        tables=[(f'{NAME}.csv', CURVE_FIELDS, curves),
                ('exp1_operating_points.csv', list(ops[0]) if ops else [], ops),
                ('exp1_runs.csv', RUN_FIELDS, run_rows(runs))],
        config=config, seeds=seeds, labels=LABELS, extra=extra, timer=timer)

    for o in ops:
        print(f"  RESULT unit {o['unit_ms']:g} ms: {o['criterion']}: S = {o['slack']}"
              + ('' if o['slack'] is None else
                 f" (detection {_fmt(o['detection_pct'])}%, FPR {_fmt(o['fpr_deadline_pct'])}%)"))
    print(f"  null-fault control: {null_attributed} attributed flags (must be 0)")

    return {'slacks': cfg['slacks'], 'curves': curves, 'operating_points': ops,
            'null_fault_attributed': null_attributed, 'outputs': out}


def _fmt(x):
    return '  n/a' if x is None else f"{x:5.1f}"


if __name__ == '__main__':
    run()

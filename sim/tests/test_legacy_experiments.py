"""
Tests for the legacy experiment scripts (sim/legacy/exp1..exp7, common.py,
run_all.py, run_scaled.py): the numbers must be honest, and every figure
must come with the data behind it and a provenance manifest.

What is checked (bug numbers from the P1 bug table / reviewer critique):
   #3   exp1 and exp6 score detection COUNTERFACTUALLY: the same packets
        (common random numbers) with and without the fault; a null-fault
        control must give EXACTLY 0 attributed detection. v0 counted every
        deviation among packets that crossed the slow link, so a 1.0001x
        "fault" was "detected" at the false-positive rate.
   #16  exp5 counts greedy failures instead of averaging stretch over the
        survivors only, and uses the simulator's HOP_LIMIT (v0: 60 vs 40)
   exp2 CRH-16 sizes come from chronoroute.proto.sizes (24 B at 10 hops)
   exp3 labelled as an analytic model; every scheme at the same refresh
        interval; per-packet header bytes reported
   exp4 an oracle-reroute baseline next to fallback / no fallback, >= 10
        trials, with confidence intervals
   exp7 many start offsets across one orbit; the chooser does not pick the
        max() of noise
   all  every experiment writes PNG + CSV + a valid manifest.json into
        results/legacy-v0.9/<preset>/<expN_name>/, never into the frozen
        results/legacy-v0*/ folders
   stats Student-t critical values without scipy

Every experiment is run end to end on a TINY configuration (a few seconds)
written into a temporary directory, never into the real results/ folder.
"""

import csv
import math
import os
import random
import statistics
import sys
from pathlib import Path

import networkx as nx
import pytest

LEGACY_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'legacy'))
if LEGACY_DIR not in sys.path:
    # the legacy scripts import each other by bare module name
    sys.path.insert(0, LEGACY_DIR)

import common                  # noqa: E402
import constellation as C      # noqa: E402
import scale                   # noqa: E402
import simulator as SIM        # noqa: E402
import topology as T           # noqa: E402
import exp1_slack_sweep as exp1            # noqa: E402
import exp2_header_overhead as exp2        # noqa: E402
import exp3_control_plane as exp3          # noqa: E402
import exp4_failure_resilience as exp4     # noqa: E402
import exp5_path_stretch as exp5           # noqa: E402
import exp6_scale_validation as exp6       # noqa: E402
import exp7_schedule_interval as exp7      # noqa: E402

from chronoroute.provenance import validate_manifest   # noqa: E402

REPO = Path(LEGACY_DIR).resolve().parents[1]
FLOWS = common.FLOWS


# ---------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def _back_to_dev_preset():
    """Presets are process-wide state: every test leaves the default behind."""
    yield
    scale.restore_topology()
    scale.use_preset('dev', verbose=False)


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    """Send every output of the test into a temporary results tree."""
    root = tmp_path / 'legacy-v0.9'
    monkeypatch.setattr(common, 'RESULTS_ROOT', str(root))
    monkeypatch.setattr(common, 'RESULTS_DIR', str(root / 'dev'))
    return root / 'dev'


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def check_outputs(exp_dir, name):
    """PNG + CSV + manifest.json exist, and the manifest is valid and lists them."""
    exp_dir = Path(exp_dir)
    png = exp_dir / f'{name}.png'
    table = exp_dir / f'{name}.csv'
    manifest_path = exp_dir / 'manifest.json'
    assert png.is_file(), f'missing {png}'
    assert png.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    rows = read_csv(table)
    assert rows, f'{table} has no rows'
    manifest = validate_manifest(manifest_path)          # raises if invalid
    listed = {o['path'] for o in manifest['outputs']}
    assert {f'{name}.png', f'{name}.csv'} <= listed
    assert manifest['tool'] == 'legacy-python'
    assert manifest['config']['experiment'] == name
    assert manifest['labels'], 'every manifest carries REAL/DERIVED/MODELLED labels'
    return rows, manifest


def num(x):
    return float(x) if x not in ('', None) else None


# ---------------------------------------------------------------- output location

def test_results_dir_is_legacy_v09_dev_by_default():
    assert Path(common.RESULTS_ROOT).resolve() == REPO / 'results' / 'legacy-v0.9'
    assert Path(common.RESULTS_DIR).resolve() == REPO / 'results' / 'legacy-v0.9' / 'dev'
    assert (Path(common.results_dir_for('starlink')).resolve()
            == REPO / 'results' / 'legacy-v0.9' / 'starlink')


@pytest.mark.parametrize('frozen', ['legacy-v0', 'legacy-v0-starlink'])
def test_refuses_to_write_into_the_frozen_v0_results(monkeypatch, frozen):
    target = REPO / 'results' / frozen
    before = sorted(p.name for p in target.iterdir()) if target.exists() else []
    monkeypatch.setattr(common, 'RESULTS_DIR', str(target))
    with pytest.raises(ValueError):
        common.experiment_dir('exp_should_not_exist')
    after = sorted(p.name for p in target.iterdir()) if target.exists() else []
    assert before == after


def test_run_all_and_run_scaled_write_under_their_preset(out_dir, monkeypatch):
    import run_all
    import run_scaled
    root = out_dir.parent
    run_all.main(only=['exp2_header_overhead'], workers=1)
    check_outputs(root / 'dev' / 'exp2_header_overhead', 'exp2_header_overhead')
    run_scaled.main('telesat', only=['exp2_header_overhead'], workers=1)
    check_outputs(root / 'telesat' / 'exp2_header_overhead', 'exp2_header_overhead')
    assert Path(common.RESULTS_DIR) == root / 'telesat'


# ---------------------------------------------------------------- statistics

@pytest.mark.parametrize('df, expected', [
    (1, 12.7062), (2, 4.3027), (4, 2.7764), (9, 2.2622), (10, 2.2281),
    (29, 2.0452), (30, 2.0423), (60, 2.0003), (120, 1.9799), (1000, 1.9623),
])
def test_t_critical_value_matches_the_t_table(df, expected):
    assert common.t_quantile(0.975, df) == pytest.approx(expected, abs=2e-4)


def test_t_critical_value_tends_to_the_normal():
    assert common.t_quantile(0.975, 10 ** 7) == pytest.approx(1.959964, abs=1e-4)
    assert common.t_quantile(0.95, 5) == pytest.approx(2.0150, abs=2e-4)


def test_mean_ci_uses_student_t():
    mean, lo, hi, n = common.mean_ci([1, 2, 3, 4, 5])
    half = 2.776445 * statistics.stdev([1, 2, 3, 4, 5]) / math.sqrt(5)
    assert (mean, n) == (3, 5)
    assert lo == pytest.approx(3 - half, abs=1e-5)
    assert hi == pytest.approx(3 + half, abs=1e-5)
    assert common.mean_ci([7.0, 7.0, 7.0])[:3] == (7.0, 7.0, 7.0)
    assert common.mean_ci([4.0]) == (4.0, None, None, 1)
    assert common.mean_ci([]) == (None, None, None, 0)


def test_wilson_interval():
    p, lo, hi = common.wilson_ci(0, 50)
    assert p == 0 and lo == 0 and 0 < hi < 0.08
    p, lo, hi = common.wilson_ci(25, 50)
    assert lo < 0.5 < hi


# ---------------------------------------------------------------- scenario helpers

def test_setup_cache_follows_the_active_constellation():
    _, _, _, g_dev = common.setup(duration_s=2, step_s=1, verbose=False)
    assert sum(1 for n in g_dev[0] if isinstance(n, int)) == 480
    # set_config directly (no cache clearing): v0 keyed the cache on
    # (duration, step) only and would hand back the 480-satellite graphs
    C.set_config(C.ConstellationConfig(planes=27, sats_per_plane=13, altitude_km=1015.0,
                                       inclination_deg=98.98))
    _, _, _, g_tel = common.setup(duration_s=2, step_s=1, verbose=False)
    assert sum(1 for n in g_tel[0] if isinstance(n, int)) == 351


def test_propagate_window_matches_constellation_propagate():
    sats = C.build_constellation()
    times, pos = C.propagate(sats, duration_s=7, step_s=1)
    w_times, w_pos, stats = common.propagate_window(sats, start_s=3, duration_s=3, step_s=1)
    assert w_times == [3, 4, 5]
    assert w_pos == pos[3:6]
    assert stats['samples'] == 3 * len(sats) and stats['skipped'] == 0


# ---------------------------------------------------------------- exp1 (bug #3)

EXP1_TINY = dict(duration_s=12, slacks=[1.0, 1.2, 2.0], seeds=[1, 2], flows=FLOWS[:2],
                 num_packets=40, degradations=[1.0001, 1.5])


def test_exp1_defaults_are_a_real_experiment():
    d = exp1.DEFAULTS
    assert len(d['seeds']) >= 10
    assert len(d['flows']) >= 2
    assert set(d['unit_codes']) == {0, 1}
    assert exp1.NULL_FAULT == 1.0
    assert d['fpr_max'] == 0.01


def test_bug3_null_fault_control_is_exactly_zero(out_dir):
    res = exp1.run(workers=1, **EXP1_TINY)
    rows, manifest = check_outputs(out_dir / 'exp1_slack_sweep', 'exp1_slack_sweep')

    null = [r for r in rows if r['metric'] == 'detection' and num(r['degradation']) == 1.0]
    assert len(null) == 2 * 3                      # every unit code x slack
    for r in null:
        assert num(r['mean_pct']) == 0.0
        assert num(r['ci95_lo_pct']) == 0.0 and num(r['ci95_hi_pct']) == 0.0
        assert int(r['n_runs']) == 2 * 2           # seeds x flows

    # the v0 metric on a 1.0001x "fault" is just the false-positive rate:
    # at S = 1.0 almost every healthy packet is late, so v0 "detected" it
    def pick(metric, unit, slack, deg):
        [r] = [r for r in rows if r['metric'] == metric and int(r['unit_code']) == unit
               and num(r['slack']) == slack and num(r['degradation']) == deg]
        return num(r['mean_pct'])

    v0 = pick('v0_confounded_detection', 1, 1.0, 1.0001)
    honest = pick('detection', 1, 1.0, 1.0001)
    assert v0 > 50.0
    assert honest < v0 / 5

    # attributed flags can only come from packets that crossed the slow link
    runs = read_csv(out_dir / 'exp1_slack_sweep' / 'exp1_runs.csv')
    assert runs and all(int(r['attributed_not_crossed']) == 0 for r in runs)
    assert all(int(r['attributed']) == 0 for r in runs if num(r['degradation']) == 1.0)

    assert res['null_fault_attributed'] == 0
    assert set(manifest['seeds']) == {s * 1000 + f for s in (1, 2) for f in (0, 1)}
    assert manifest['config']['unit_codes'] == [0, 1]


def test_exp1_operating_point_is_constrained_not_youden():
    slacks = [1.0, 1.1, 1.2, 1.5]
    detection = [100.0, 95.0, 80.0, 40.0]
    fpr = [60.0, 5.0, 0.8, 0.1]
    # Youden J = detection - FPR is largest at 1.1 (90), but its FPR is 5 %
    assert exp1.youden_point(slacks, detection, fpr) == 1.1
    assert exp1.choose_operating_point(slacks, detection, fpr, fpr_max_pct=1.0) == 1.2
    # nothing meets the constraint -> no operating point, not a silent pick
    assert exp1.choose_operating_point(slacks, detection, [9, 8, 7, 6],
                                       fpr_max_pct=1.0) is None
    # ties in detection go to the lower false-positive rate
    assert exp1.choose_operating_point([1.2, 1.3], [100.0, 100.0], [0.9, 0.2],
                                       fpr_max_pct=1.0) == 1.3
    # slacks that meet the constraint but detect nothing are not an operating
    # point (the tie-break would otherwise "choose" the loosest slack)
    assert exp1.choose_operating_point([1.2, 2.0, 3.0], [40.0, 0.0, 0.0], [5.0, 0.5, 0.0],
                                       fpr_max_pct=1.0) is None


def test_exp1_result_does_not_depend_on_worker_count(out_dir, monkeypatch, tmp_path):
    tiny = dict(EXP1_TINY, slacks=[1.0, 1.5], unit_codes=[1])
    exp1.run(workers=1, **tiny)
    serial = (out_dir / 'exp1_slack_sweep' / 'exp1_slack_sweep.csv').read_bytes()
    other = tmp_path / 'parallel'
    monkeypatch.setattr(common, 'RESULTS_DIR', str(other))
    exp1.run(workers=2, **tiny)
    parallel = (other / 'exp1_slack_sweep' / 'exp1_slack_sweep.csv').read_bytes()
    assert serial == parallel


# ---------------------------------------------------------------- exp2

def test_exp2_uses_proto_sizes(out_dir):
    from chronoroute.proto import sizes
    res = exp2.run()
    rows, _ = check_outputs(out_dir / 'exp2_header_overhead', 'exp2_header_overhead')
    at10 = {r['header']: int(r['header_bytes']) for r in rows
            if r['panel'] == 'size_vs_hops' and int(r['hops']) == 10}
    assert at10['crh16'] == sizes.crh16_size(10) == 24      # v0 drew 32
    assert at10['tcrh'] == sizes.tcrh_size(10) == 48
    assert at10['srh'] == sizes.srh_size(10) == 168
    assert at10['tcrh_encap'] == sizes.encapsulation_overhead(10, 'encap', 'tcrh') == 88
    assert res['tcrh_minus_crh16_at_ref'] == 24             # the "+24 B" annotation


# ---------------------------------------------------------------- exp3

def test_exp3_is_labelled_analytic_and_compares_at_equal_intervals(out_dir):
    res = exp3.run(duration_s=6)
    rows, manifest = check_outputs(out_dir / 'exp3_control_plane', 'exp3_control_plane')
    assert 'ANALYTIC MODEL' in res['title']
    assert all('ANALYTIC MODEL' in r['model'] for r in rows)
    intervals = {num(r['refresh_interval_s']) for r in rows}
    assert len(intervals) >= 2
    for iv in intervals:
        schemes = {r['scheme'] for r in rows if num(r['refresh_interval_s']) == iv}
        assert {'link_state', 'table_upload', 'tcrh_control', 'tcrh_header_bytes'} <= schemes
    header = [r for r in rows if r['scheme'] == 'tcrh_header_bytes']
    assert all(r['kind'] == 'data_plane' for r in header)
    assert all(num(r['bytes_per_s']) > 0 for r in header)
    assert manifest['labels'].get('model') == 'MODELLED'


# ---------------------------------------------------------------- exp4

def test_exp4_has_an_oracle_baseline_and_enough_trials(out_dir):
    assert exp4.DEFAULTS['trials'] >= 10
    exp4.run(workers=1, duration_s=12, failure_rates=[0.0, 0.1], trials=2,
             num_packets=20, flows=FLOWS[:2])
    rows, manifest = check_outputs(out_dir / 'exp4_failure_resilience',
                                   'exp4_failure_resilience')
    methods = {r['method'] for r in rows}
    assert {'oracle_reroute', 'fallback', 'no_fallback'} <= methods
    for r in rows:
        assert int(r['n_trials']) == 2
        assert r['ci95_lo_pct'] != '' and r['ci95_hi_pct'] != ''
    [oracle0] = [r for r in rows if r['method'] == 'oracle_reroute'
                 and num(r['failure_rate_pct']) == 0.0]
    assert num(oracle0['mean_pct']) == 100.0
    assert manifest['seeds']


def test_exp4_samples_the_active_constellations_isls():
    scale.use_preset('telesat', verbose=False)
    failed = exp4.random_failures(0.1, random.Random(3))
    pairs = {frozenset((a, b)) for a, b, _ in T.isl_pairs()}
    assert len(failed) == int(len(pairs) * 0.1)
    assert failed <= pairs


# ---------------------------------------------------------------- exp5 (bug #16)

def _chain(n_hops):
    g = nx.Graph()
    for i in range(n_hops + 1):
        g.add_node(i, pos=(1000.0 * i, 0.0, 0.0))
    for i in range(n_hops):
        g.add_edge(i, i + 1, weight=1.0)
    return g


def test_bug16_exp5_uses_the_simulator_hop_limit():
    limit = SIM.HOP_LIMIT
    path, lat, outcome = exp5.greedy_path(_chain(limit), 0, limit)
    assert outcome == 'delivered' and len(path) == limit + 1 and lat == limit
    path, lat, outcome = exp5.greedy_path(_chain(limit + 1), 0, limit + 1)
    assert outcome == 'hop_limit' and path is None


def test_bug16_exp5_greedy_dead_end_is_reported():
    # 0 -> 1 is geographically closer to 3, but 1 is a dead end;
    # the real route is 0 -> 2 -> 3
    g = nx.Graph()
    for n, x, y in [(0, 0, 0), (1, 950, 0), (2, 0, 900), (3, 1000, 1000)]:
        g.add_node(n, pos=(float(x), float(y), 0.0))
    g.add_edge(0, 1, weight=1.0)
    g.add_edge(0, 2, weight=1.0)
    g.add_edge(2, 3, weight=1.0)
    path, lat, outcome = exp5.greedy_path(g, 0, 3)
    assert outcome == 'stuck' and path is None


def test_effective_quantile_counts_losses_as_infinite():
    inf = math.inf
    assert exp5.effective_quantile([1.0, 2.0, 3.0, inf], 0.5) == 2.0
    assert exp5.effective_quantile([1.0, 2.0, 3.0, inf], 0.75) == 3.0
    assert exp5.effective_quantile([1.0, 2.0, 3.0, inf], 0.95) == inf
    assert exp5.effective_quantile([1.0], 0.99) == 1.0


def test_exp5_reports_delivery_rate_and_effective_stretch(out_dir):
    res = exp5.run(duration_s=4, num_pairs=40)
    rows, _ = check_outputs(out_dir / 'exp5_path_stretch', 'exp5_path_stretch')
    assert len(rows) == res['pairs_tested']
    failed = [r for r in rows if r['greedy_outcome'] != 'delivered']
    assert all(r['effective_latency_stretch'] == 'inf' for r in failed)
    assert all(r['latency_stretch'] == '' for r in failed)
    assert res['delivery_rate'] == pytest.approx(1 - len(failed) / len(rows))
    assert res['hop_limit'] == SIM.HOP_LIMIT
    for r in rows:
        assert int(r['src']) < C.num_sats() and int(r['dst']) < C.num_sats()


# ---------------------------------------------------------------- exp6

def test_exp6_smoke_null_fault_zero_and_preset_restored(out_dir):
    before = C.config()
    exp6.run(workers=1, presets=['telesat', 'dev'], duration_s=8, slacks=[1.0, 2.0],
             seeds=[1, 2], flows=FLOWS[:1], num_packets=20)
    assert C.config() == before
    rows, _ = check_outputs(out_dir / 'exp6_scale_validation', 'exp6_scale_validation')
    assert {r['preset'] for r in rows} == {'telesat', 'dev'}
    curves = read_csv(out_dir / 'exp6_scale_validation' / 'exp6_slack_curves.csv')
    null = [r for r in curves if r['metric'] == 'detection' and num(r['degradation']) == 1.0]
    assert null and all(num(r['mean_pct']) == 0.0 for r in null)


def panel_text_overlaps(fig):
    """
    Every place where one panel's title or axis text is drawn on top of
    ANOTHER panel (its frame, title or axis text), or the figure title on
    top of a panel. Returns a list of (what, what) pairs; empty means clean.
    Axis.get_tightbbox covers the tick labels actually drawn plus the label.
    """
    fig.canvas.draw()                       # runs the layout engine, places the ticks
    r = fig.canvas.get_renderer()
    parts = {}
    for i, ax in enumerate(fig.axes):
        boxes = {'frame': ax.get_window_extent(r), 'x axis': ax.xaxis.get_tightbbox(r),
                 'y axis': ax.yaxis.get_tightbbox(r)}
        if ax.get_title():
            boxes['title'] = ax.title.get_window_extent(r)
        parts[i] = {k: b for k, b in boxes.items() if b is not None}
    hits = []
    for i in parts:
        for j in parts:
            if i == j:
                continue
            for a, ba in parts[i].items():
                if a == 'frame':
                    continue                # a frame is only ever hit, never the hitter
                for b, bb in parts[j].items():
                    if ba.overlaps(bb):
                        hits.append((f'panel {i} {a}', f'panel {j} {b}'))
    if fig._suptitle is not None:
        st = fig._suptitle.get_window_extent(r)
        hits += [('suptitle', f'panel {j} {b}') for j in parts
                 for b, bb in parts[j].items() if st.overlaps(bb)]
    return hits


def test_exp6_figure_panels_do_not_overlap():
    """
    Revision 2 gave the floor panel a two-line title, which was drawn over the
    'Header cost' panel's two-line tick labels ('(351 sats)' ...) in the
    published Starlink figure: the grid had no layout engine. Synthetic numbers
    in the published figure's shape (same presets, labels and titles).
    """
    cfg = dict(exp6.DEFAULTS)
    rows, lookups = [], {}
    for k, p in enumerate(exp6.PRESET_ORDER):
        rows.append({'preset': p, 'name': scale.PRESETS[p]['name'],
                     'sats': scale.PRESETS[p]['planes'] * scale.PRESETS[p]['sats_per_plane'],
                     'mean_hops': 10.0 + k, 'crh16_bytes': 24, 'tcrh_bytes': 48,
                     'srh_bytes': 168 + 16 * k, 'floor_pct': 5.0 * k,
                     'floor_ci95_lo_pct': 0.0, 'floor_ci95_hi_pct': 10.0 * k + 5})
        lookups[p] = {(u, s, 'fpr_deadline', None): (100.0 / s ** 8, None, None)
                      for u in cfg['unit_codes'] for s in cfg['slacks']}
    fig = exp6.plot(rows, lookups, cfg)
    try:
        assert panel_text_overlaps(fig) == []
    finally:
        import matplotlib.pyplot as plt
        plt.close(fig)


# ---------------------------------------------------------------- exp7

def test_exp7_offsets_cover_one_orbit():
    period = exp7.orbital_period_s()
    assert 5600 < period < 5900                     # 550 km shell: ~95.6 min
    offsets = exp7.window_offsets(32)
    assert len(set(offsets)) == 32 and offsets == sorted(offsets)
    assert offsets[0] == 0 and offsets[-1] < period
    assert offsets[-1] >= period * 31 / 32 - 1
    assert exp7.DEFAULTS['n_offsets'] >= 20


def test_exp7_chooser_is_not_max_of_noise():
    intervals = [1, 2, 3, 5]
    per_window = {
        1: [0.0] * 8,
        2: [1.0] * 8,                                  # clearly worse
        3: [0.0] * 7 + [0.4],                          # lucky
        5: [0.0] * 8,                                  # lucky
    }
    # v0 took the max() of every interval under 1 % -> 5 s
    choice = exp7.choose_interval(intervals, per_window, margin_pp=0.5)
    assert choice['best'] == 1
    assert choice['chosen'] == 1


def test_exp7_chooser_takes_the_longest_equivalent_interval():
    intervals = [1, 2, 5, 10]
    rng = random.Random(4)
    base = [rng.uniform(0, 0.2) for _ in range(12)]
    per_window = {1: base, 2: [b + 0.01 for b in base], 5: [b + 0.02 for b in base],
                  10: [b + 3.0 for b in base]}
    choice = exp7.choose_interval(intervals, per_window, margin_pp=0.5)
    assert choice['chosen'] == 5


def test_exp7_smoke(out_dir):
    res = exp7.run(workers=1, n_offsets=2, window_s=10, intervals=[1, 5], flows=FLOWS[:1],
                   packet_interval_ms=500)
    rows, manifest = check_outputs(out_dir / 'exp7_schedule_interval',
                                   'exp7_schedule_interval')
    assert all(int(r['n_windows']) == 2 for r in rows)
    assert res['recommended'] in (1, 5)
    assert len(manifest['config']['offsets_s']) == 2


# ---------------------------------------------------------------- remaining smoke tests

def test_exp1_and_exp4_manifests_record_the_scenario(out_dir):
    exp1.run(workers=1, **dict(EXP1_TINY, slacks=[1.2], unit_codes=[0]))
    _, manifest = check_outputs(out_dir / 'exp1_slack_sweep', 'exp1_slack_sweep')
    cfg = manifest['config']
    assert cfg['preset'] == 'dev'
    assert cfg['constellation']['planes'] == 24
    assert cfg['duration_s'] == 12
    assert 'propagation' in manifest['extra']


# ---------------------------------------------------------------- review round 2
# (P1 review findings on the v0.9 results; each test fails on the code the
#  results were first produced with)

def test_cluster_ci_treats_the_flow_as_the_unit():
    # The stale-path rate is set by a flow's geometry: it is the same in all
    # ten seeds of a flow. Ten copies each of {0, 16, 0} % are three numbers.
    values = [0.0] * 10 + [16.0] * 10 + [0.0] * 10
    flows = [0] * 10 + [1] * 10 + [2] * 10
    naive = common.mean_ci(values, bounds=(0.0, 100.0))
    assert naive[1] == pytest.approx(2.47, abs=0.01)       # what v0.9 first reported
    assert naive[2] == pytest.approx(8.20, abs=0.01)
    mean, lo, hi, n = common.cluster_mean_ci(values, flows, bounds=(0.0, 100.0))
    assert n == 3
    assert mean == pytest.approx(16 / 3)
    assert lo == 0.0
    assert hi == pytest.approx(28.28, abs=0.01)             # t(0.975, 2) = 4.303
    # undefined runs are left out; a flow with nothing left drops out
    assert common.cluster_mean_ci([1.0, None, 3.0, None], [0, 0, 1, 2])[3] == 2
    assert common.cluster_mean_ci([None], [0]) == (None, None, None, 0)


def _synthetic_runs(fprs, stale=0.0, seeds=10):
    """exp1-style run dicts whose rates differ by flow, never by seed."""
    runs = []
    for fi, fpr in enumerate(fprs):
        for seed in range(seeds):
            runs.append({'unit_code': 0, 'slack': 1.2, 'flow_index': fi, 'seed': seed,
                         'fpr_deadline': fpr, 'stale': stale, 'flagged': fpr,
                         'faults': [{'degradation': 1.0, 'detection': 0.0,
                                     'detection_among_unflagged': 0.0,
                                     'v0_confounded_detection': None}]})
    return runs


def test_exp1_curves_use_the_flow_as_the_unit_of_analysis():
    # Starlink exp1, S = 1.2, 1 ms: FPR 0.55 / 12.5 / 0.28 % by flow was
    # reported as 4.44 [2.25, 6.63] from 30 "independent" runs
    runs = _synthetic_runs([0.0055, 0.125, 0.0028])
    rows, lookup = exp1.summarise_runs(runs, [1.2], [0], [1.0])
    mean, lo, hi, n = lookup[(0, 1.2, 'fpr_deadline', None)]
    assert n == 3
    assert mean == pytest.approx(100 * (0.0055 + 0.125 + 0.0028) / 3)
    assert lo == 0.0 and hi > 20.0
    [row] = [r for r in rows if r['metric'] == 'fpr_deadline']
    assert row['n_runs'] == 30 and row['n_flows'] == 3
    assert 'n_flows' in exp1.CURVE_FIELDS


def test_exp1_operating_point_needs_a_useful_detection():
    # dev / Starlink at 0.1 ms: S = 1.75 "detected" 0.08 % / 0.04 % with
    # FPR <= 1 % and was drawn as the operating point; Exp 6 said None
    assert exp1.choose_operating_point([1.5, 1.75, 2.0], [0.0, 0.08, 0.0], [1.6, 0.2, 0.0],
                                       fpr_max_pct=1.0) is None
    assert exp1.choose_operating_point([1.75, 2.0], [0.0836, 0.0], [0.2, 0.0],
                                       fpr_max_pct=1.0) is None
    # Telesat at 0.1 ms in Exp 6: S = 1.5 at 0.08 %
    assert exp1.choose_operating_point([1.3, 1.5, 2.0], [3.0, 0.08, 0.0], [4.0, 0.5, 0.0],
                                       fpr_max_pct=1.0) is None
    # by default a detection must at least reach the FPR limit
    assert exp1.choose_operating_point([1.2, 1.3], [14.4, 2.5], [4.4, 0.7],
                                       fpr_max_pct=1.0) == 1.3
    assert exp1.choose_operating_point([1.3], [2.5], [0.7], fpr_max_pct=1.0,
                                       min_detection_pct=5.0) is None
    # Exp 6 uses the very same rule (one function, one default)
    lookup = {(0, s, 'detection', 1.5): (d, 0.0, 1.0, 3) for s, d in [(1.5, 0.08), (2.0, 0.0)]}
    lookup.update({(0, s, 'fpr_deadline', None): (f, 0.0, 1.0, 3) for s, f in [(1.5, 0.5),
                                                                              (2.0, 0.0)]})
    ops = exp1.operating_points(lookup, [1.5, 2.0], [0], 1.5, 1.0)
    assert ops[0]['slack'] is None
    assert 'mean FPR' in ops[0]['criterion']


def test_exp6_floor_uses_the_flow_as_the_unit():
    floor_runs = [{'flow_index': fi, 'stale': s}
                  for fi, s in enumerate([0.0, 0.16, 0.0]) for _ in range(10)]
    f = exp6.floor_summary(floor_runs)
    assert f['n_flows'] == 3 and f['n_runs'] == 30
    assert f['per_flow_pct'] == pytest.approx([0.0, 16.0, 0.0])
    assert f['mean_pct'] == pytest.approx(16 / 3)
    assert f['ci95_lo_pct'] == 0.0
    assert f['ci95_hi_pct'] == pytest.approx(28.28, abs=0.01)


def test_exp7_chooser_says_when_the_answer_is_the_simulation_step():
    # the 1 s interval is never stale when the topology only changes every
    # 1 s step; recommending it is a statement about the simulator's
    # resolution, not about the constellation
    per_window = {1: [0.0] * 8, 2: [0.85] * 7 + [0.9], 3: [1.65] * 8}
    choice = exp7.choose_interval([1, 2, 3], per_window, margin_pp=0.5, step_s=1)
    assert choice['chosen'] == 1
    assert choice['resolution_limited'] is True
    assert [t['at_or_below_step'] for t in choice['tests']] == [True, False, False]
    finer = exp7.choose_interval([1, 2, 3], per_window, margin_pp=0.5, step_s=0.1)
    assert finer['resolution_limited'] is False


def test_exp5_optimal_share_is_by_latency_not_by_hops(out_dir):
    # v0's "already optimal" counted greedy paths with no more hops than the
    # shortest-latency path, including ones up to 1.48x slower
    res = exp5.run(duration_s=4, num_pairs=60)
    folder = out_dir / 'exp5_path_stretch'
    summary = {r['statistic']: num(r['value']) for r in read_csv(folder / 'exp5_summary.csv')}
    delivered = [r for r in read_csv(folder / 'exp5_path_stretch.csv')
                 if r['greedy_outcome'] == 'delivered']
    assert delivered
    lat_opt = sum(1 for r in delivered if num(r['latency_stretch']) <= 1 + 1e-9)
    few_hops = sum(1 for r in delivered if num(r['hop_stretch']) <= 1.0)
    assert summary['latency_optimal_share_of_delivered'] == pytest.approx(lat_opt / len(delivered))
    assert summary['same_or_fewer_hops_share_of_delivered'] == pytest.approx(
        few_hops / len(delivered))
    assert res['latency_optimal_share'] == pytest.approx(lat_opt / len(delivered))
    assert lat_opt <= few_hops

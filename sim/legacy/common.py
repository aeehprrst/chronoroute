"""
common.py
---------
Shared setup for all the experiments, so each experiment script stays short
and they all use an identical scenario.

Since v0.9 this module also does the bookkeeping that makes a number worth
quoting:

  * WHERE results go: results/legacy-v0.9/<preset>/<expN_name>/. The v0
    figures in results/legacy-v0*/ are frozen evidence of what the old code
    said, so writing there is refused.
  * WHAT is written: the PNG, a CSV of exactly the numbers that are plotted,
    and a manifest.json (chronoroute.provenance) that records the commit,
    config, seeds, library versions and the hash of every output file.
  * HOW sure we are: mean and a Student-t 95% confidence interval over
    independent runs (scipy is not installed, so the t quantile is computed
    here), and a Wilson interval for plain proportions. When runs come in
    clusters that are not independent (the seeds of one flow share its
    geometry), cluster_mean_ci() makes the cluster the unit of analysis.
  * HOW FAST: pmap() spreads independent runs over worker processes. Every
    run is a pure function of its arguments (the simulator uses common random
    numbers), so the numbers do not depend on the worker count.
"""

import csv
import dataclasses
import functools
import math
import multiprocessing
import os
import sys

import matplotlib
matplotlib.use('Agg')        # render to file, no GUI needed inside WSL
import matplotlib.pyplot as plt

from sgp4.api import jday

import constellation as C
from constellation import build_constellation, propagate, ground_station_positions
from topology import build_all_graphs

# sim/legacy/common.py -> the repository is two levels up
REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                          '..', '..'))
FROZEN_RESULTS = os.path.join(REPO_ROOT, 'results')
RESULTS_ROOT = os.path.join(FROZEN_RESULTS, 'legacy-v0.9')
# run_all.py writes the dev preset; run_scaled.py points this at its preset
RESULTS_DIR = os.path.join(RESULTS_ROOT, 'dev')

TOOL = 'legacy-python'

# ----- Scenario used by every experiment -----
DURATION_S = 120
STEP_S = 1

FLOWS = [
    ('GS:Chennai',  'GS:London'),
    ('GS:NewYork',  'GS:Sydney'),
    ('GS:SaoPaulo', 'GS:Tokyo'),
]

_cache = {}


# --------------------------------------------------------------- scenario

def setup(duration_s=DURATION_S, step_s=STEP_S, verbose=True):
    """
    Build the constellation, propagate it, and build every graph.
    Cached, so running several experiments in one process is fast.

    The cache key includes the ACTIVE constellation config: v0 keyed it on
    (duration, step) only, so a preset switch that did not clear the cache
    silently handed back the old constellation's graphs.
    """
    key = (C.config(), duration_s, step_s)
    if key in _cache:
        return _cache[key]

    if verbose:
        print(f"  building constellation and propagating {duration_s}s...")
    sats = build_constellation()
    times, sat_pos = propagate(sats, duration_s=duration_s, step_s=step_s)
    stats = propagation_summary(C.last_propagation_stats())
    gs_pos = ground_station_positions(times)
    if verbose:
        print(f"  building {len(times)} topology graphs...")
    graphs = build_all_graphs(times, sat_pos, gs_pos, verbose=False)

    _cache.clear()           # one scenario at a time: graphs are big at scale
    _cache[key] = (times, sat_pos, gs_pos, graphs)
    _stats[key] = stats
    return _cache[key]


_stats = {}


def setup_stats(duration_s=DURATION_S, step_s=STEP_S):
    """Propagation skip counts of the scenario setup() built (for the manifest)."""
    return _stats.get((C.config(), duration_s, step_s))


def propagation_summary(stats):
    """constellation.PropagationStats (or our dict) as plain JSON for a manifest."""
    if isinstance(stats, dict):
        return dict(stats)
    return {
        'samples': stats.samples,
        'skipped': stats.skipped,
        'skipped_sats': stats.skipped_sats,
        'error_codes': {str(k): v for k, v in sorted(stats.error_codes.items())},
    }


def propagate_window(sats, start_s, duration_s, step_s):
    """
    constellation.propagate() for the window [start_s, start_s + duration_s).

    Experiment 7 needs short windows spread over a whole orbit; propagating
    the whole orbit and slicing it would hold ~6000 steps of positions in
    memory. This is the same computation as constellation.propagate() (same
    Julian date arithmetic, same TEME -> ECEF rotation, same skip rule), only
    starting later; a test checks the two agree exactly.

    Returns (times, positions, stats): times are absolute seconds since the
    epoch, stats is a propagation_summary() dict for this window.
    """
    jd0, fr0 = jday(C.EPOCH_YEAR, C.EPOCH_MONTH, C.EPOCH_DAY, 0, 0, 0)
    times = list(range(start_s, start_s + duration_s, step_s))
    positions = []
    samples = skipped = 0
    skipped_sats, error_codes = set(), {}
    for t in times:
        fr = fr0 + t / 86400.0
        theta = C.gmst_rad(jd0, fr)
        frame = []
        for i, sat in enumerate(sats):
            samples += 1
            error, r, _ = sat['satrec'].sgp4(jd0, fr)
            if error == 0 and not all(math.isfinite(c) for c in r):
                error = C.NON_FINITE_POSITION
            if error != 0:
                skipped += 1
                skipped_sats.add(sat.get('id', i))
                error_codes[str(error)] = error_codes.get(str(error), 0) + 1
                frame.append(None)
                continue
            frame.append(C.teme_to_ecef(r, theta))
        positions.append(frame)
    stats = {'samples': samples, 'skipped': skipped, 'skipped_sats': len(skipped_sats),
             'error_codes': dict(sorted(error_codes.items()))}
    return times, positions, stats


def preset_name():
    """The scale.PRESETS key whose shape is active, or 'custom'."""
    import scale
    cfg = C.config()
    for key, p in scale.PRESETS.items():
        if (cfg.planes, cfg.sats_per_plane) == (p['planes'], p['sats_per_plane']) \
                and cfg.altitude_km == p['altitude_km'] \
                and cfg.inclination_deg == p['inclination_deg'] \
                and cfg.phasing_f == p.get('phasing_f', C.DEFAULT_CONFIG.phasing_f):
            return key
    return 'custom'


def scenario_config():
    """The settings every simulated experiment shares (goes into config)."""
    import scheduler
    import simulator
    return {
        'preset': preset_name(),
        'constellation': dataclasses.asdict(C.config()),
        'epoch_utc': f"{C.EPOCH_YEAR:04d}-{C.EPOCH_MONTH:02d}-{C.EPOCH_DAY:02d}T00:00:00Z",
        'schedule_interval_s': scheduler.SCHEDULE_INTERVAL_S,
        'queueing_mean_ms': simulator.QUEUEING_MEAN_MS,
        'hop_limit': simulator.HOP_LIMIT,
    }


def make_config(defaults, overrides):
    """defaults updated with overrides; an unknown key is a typo, so refuse it."""
    unknown = set(overrides) - set(defaults)
    if unknown:
        raise TypeError(f"unknown setting(s) {sorted(unknown)}; known: {sorted(defaults)}")
    cfg = dict(defaults)
    cfg.update(overrides)
    return cfg


def flow_label(flow):
    return f"{flow[0][3:]}->{flow[1][3:]}"


def crn_seed(seed, flow_index):
    """
    The common-random-numbers seed of one run. Each flow gets its own stream
    (otherwise every flow would draw the same queueing delays hop by hop),
    and the same (seed, flow) gives the same stream in every experiment.
    """
    return seed * 1000 + flow_index


# --------------------------------------------------------------- statistics

def _t_cdf(x, df, steps=2000):
    """
    P(T <= x) for x >= 0: 1/2 plus the integral of the t density from 0 to x,
    by Simpson's rule (the density is smooth, so 2000 steps are accurate to
    far better than the 4 decimals of a printed t table).
    """
    log_c = (math.lgamma((df + 1) / 2) - math.lgamma(df / 2)
             - 0.5 * math.log(df * math.pi))
    power = (df + 1) / 2

    def pdf(t):
        return math.exp(log_c - power * math.log1p(t * t / df))

    h = x / steps
    total = pdf(0.0) + pdf(x)
    for i in range(1, steps):
        total += (4 if i % 2 else 2) * pdf(i * h)
    return 0.5 + total * h / 3


@functools.lru_cache(maxsize=None)
def t_quantile(p, df):
    """
    The p-quantile of Student's t with df degrees of freedom (p >= 0.5).

    scipy is not installed, so we integrate the t density numerically and
    bisect for the quantile. A test checks it against the printed t table.
    Above a million degrees of freedom t is the normal distribution to
    better than 1e-6, so we use the normal quantile there.
    """
    if not 0.5 <= p < 1.0:
        raise ValueError("t_quantile needs 0.5 <= p < 1")
    if df < 1:
        raise ValueError("need at least one degree of freedom")
    if p == 0.5:
        return 0.0
    if df > 10 ** 6:
        df = 10 ** 6
    lo, hi = 0.0, 1.0
    while _t_cdf(hi, df) < p:
        lo, hi = hi, hi * 2
    for _ in range(60):
        mid = (lo + hi) / 2
        if _t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def mean_ci(values, level=0.95, bounds=None):
    """
    (mean, lower, upper, n): the mean of independent run results and its
    Student-t confidence interval. The run is the unit of analysis, never
    the packet. With fewer than two values there is no interval (None).
    None values (a run where the quantity is undefined) are left out.

    bounds=(lo, hi) truncates the interval to the possible range, e.g.
    (0, 1) for a rate: a symmetric t interval around 0.5% can otherwise
    reach below zero, which no rate can.
    """
    xs = [float(v) for v in values if v is not None]
    n = len(xs)
    if n == 0:
        return (None, None, None, 0)
    mean = math.fsum(xs) / n
    if n == 1:
        return (mean, None, None, 1)
    var = math.fsum((x - mean) ** 2 for x in xs) / (n - 1)
    half = t_quantile(0.5 + level / 2, n - 1) * math.sqrt(var / n)
    if half == 0.0:
        return (mean, mean, mean, n)
    lo, hi = mean - half, mean + half
    if bounds is not None:
        lo, hi = max(lo, bounds[0]), min(hi, bounds[1])
    return (mean, lo, hi, n)


def cluster_mean_ci(values, clusters, level=0.95, bounds=None):
    """
    (mean, lower, upper, n_clusters): like mean_ci, but with the CLUSTER as
    the unit of analysis. values[i] belongs to cluster clusters[i] (for us:
    the flow). Each cluster's values are averaged first, then the t interval
    is taken over the cluster means, with n_clusters - 1 degrees of freedom.

    Why: the seeds of one flow are not independent samples of "a flow". The
    stale-path rate, for example, is set by the flow's geometry and is the
    SAME in all ten seeds of a flow, so ten copies of {0, 16, 0} % are three
    numbers, not thirty, and a 30-run t interval ([2.5, 8.2]) is far too
    narrow; over the three flows it is [0, 28.3]. With three flows the
    honest interval is wide; that is the information.

    None values are left out; a cluster with no values left drops out.
    """
    groups = {}
    for v, c in zip(values, clusters, strict=True):
        if v is not None:
            groups.setdefault(c, []).append(float(v))
    means = [math.fsum(g) / len(g) for _, g in sorted(groups.items(), key=lambda kv: str(kv[0]))]
    return mean_ci(means, level=level, bounds=bounds)


def wilson_ci(k, n, z=1.959963984540054):
    """(p, lower, upper): a proportion k/n and its Wilson score interval."""
    if n <= 0:
        return (None, None, None)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    # the bounds are exactly 0 and 1 at k = 0 and k = n; say so rather than
    # print the floating-point residue (6.9e-18)
    lo = 0.0 if k == 0 else max(0.0, centre - half)
    hi = 1.0 if k == n else min(1.0, centre + half)
    return (p, lo, hi)


def pct(x):
    """A fraction as a percentage, keeping None as None."""
    return None if x is None else 100.0 * x


# --------------------------------------------------------------- parallel runs

MAX_WORKERS = 12             # the machine has 20 threads; leave room for the rest
_RESERVED_MB = 1500          # RAM kept free for the parent process and the OS
LAST_WORKERS = None          # how many processes the last pmap() used (for the manifest)


def available_mb():
    """MemAvailable from /proc/meminfo in MiB (None if unknown)."""
    try:
        with open('/proc/meminfo') as fh:
            for line in fh:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def worker_mb(duration_s, step_s, extra_steps=0):
    """
    Rough RAM a worker needs to hold its own copy of the scenario: ~160 MB
    of interpreter and libraries plus ~1.25 kB per satellite per graph
    (the audit measured 0.6 MB per dev graph and 1.9 MB per Starlink graph).
    """
    steps = len(range(0, duration_s, step_s)) + extra_steps
    return 160 + 0.00125 * C.num_sats() * steps


def resolve_workers(workers, n_tasks, per_worker_mb):
    """How many processes to use: asked for (or CR_WORKERS, or MAX_WORKERS),
    capped by the CPU count, the number of tasks and the free RAM."""
    if workers is None:
        workers = int(os.environ.get('CR_WORKERS', MAX_WORKERS))
    workers = max(1, min(int(workers), os.cpu_count() or 1, max(1, n_tasks)))
    free = available_mb()
    if free is not None and per_worker_mb:
        workers = max(1, min(workers, int((free - _RESERVED_MB) // per_worker_mb)))
    return workers


def _worker_state():
    import scale
    import topology
    return {
        'config': C.config(),
        'fast_topology': topology.build_graph is scale._fast_build_graph,
    }


def _init_worker(state):
    """Put a fresh worker on the parent's constellation and topology builder."""
    import scale
    cfg = state['config']
    if C.config() != cfg:
        scale.apply_config(cfg.planes, cfg.sats_per_plane, cfg.altitude_km,
                           cfg.inclination_deg, verbose=False, phasing_f=cfg.phasing_f)
    if state['fast_topology']:
        scale.install_fast_topology(verbose=False)


def pmap(fn, tasks, workers=None, per_worker_mb=None):
    """
    [fn(t) for t in tasks], spread over worker processes.

    fn must be a module-level function and each task a picklable value. The
    workers are started with 'forkserver' (the Python 3.14 default on Linux),
    so they share nothing with this process except what the initializer
    hands them: the constellation config and the topology builder. Each
    worker rebuilds (and caches) whatever scenario its tasks ask for. With
    one worker everything runs here, in order.
    """
    global LAST_WORKERS
    tasks = list(tasks)
    n = resolve_workers(workers, len(tasks), per_worker_mb)
    LAST_WORKERS = n
    if n <= 1:
        return [fn(t) for t in tasks]
    # one BLAS thread per worker: the workers already use every core
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    ctx = multiprocessing.get_context('forkserver')
    with ctx.Pool(n, initializer=_init_worker, initargs=(_worker_state(),)) as pool:
        return pool.map(fn, tasks, chunksize=1)


# --------------------------------------------------------------- outputs

def results_dir_for(preset):
    """Where run_scaled.py <preset> puts its experiments."""
    return os.path.join(RESULTS_ROOT, preset)


def _inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder + os.sep)


def check_output_path(path):
    """
    Refuse to write anywhere under results/ except results/legacy-v0.9/.
    results/legacy-v0 and results/legacy-v0-starlink hold the v0 figures as
    they were graded; overwriting them would destroy the before/after
    comparison. (Paths outside results/, e.g. a test's tmp dir, are fine.)
    """
    if _inside(path, FROZEN_RESULTS) and not _inside(path, os.path.join(
            FROZEN_RESULTS, 'legacy-v0.9')):
        raise ValueError(f"refusing to write into {os.path.realpath(path)}: only "
                         f"results/legacy-v0.9/ may be written; the v0 results are frozen")
    return path


def experiment_dir(name):
    """RESULTS_DIR/<name>, created. Every output of experiment <name> goes here."""
    out = os.path.join(RESULTS_DIR, name)
    check_output_path(out)
    os.makedirs(out, exist_ok=True)
    return os.path.abspath(out)


def save(fig, filename, out_dir=None):
    """Save a figure (into RESULTS_DIR unless out_dir is given) and print where."""
    out_dir = RESULTS_DIR if out_dir is None else out_dir
    check_output_path(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.abspath(os.path.join(out_dir, filename))
    # no timestamp in the PNG metadata, so a re-run gives identical bytes
    fig.savefig(path, dpi=150, bbox_inches='tight', metadata={'Software': None})
    plt.close(fig)
    print(f"  saved -> {path}")
    return path


def _csv_value(v):
    if v is None:
        return ''
    if isinstance(v, float):
        return 'inf' if v == math.inf else repr(v)     # repr: exact round trip
    return v


def write_csv(path, fieldnames, rows):
    """A plain CSV (UTF-8, '\\n' line ends, full float precision)."""
    check_output_path(path)
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator='\n')
        w.writeheader()
        for row in rows:
            w.writerow({k: _csv_value(v) for k, v in row.items()})
    print(f"  saved -> {os.path.abspath(path)}")
    return os.path.abspath(path)


def write_results(name, *, fig, tables, config, seeds, labels, extra=None, timer=None):
    """
    Write everything an experiment produced into experiment_dir(name):

        <name>.png        the figure
        <name>.csv        exactly the plotted numbers (tables[0])
        other tables      e.g. per-run raw results
        manifest.json     provenance: commit, config, seeds, versions, hashes

    tables: list of (filename, fieldnames, rows). Returns the paths.
    """
    from chronoroute import __version__
    from chronoroute.provenance import write_manifest

    out = experiment_dir(name)
    paths = [save(fig, f'{name}.png', out_dir=out)]
    if not tables or tables[0][0] != f'{name}.csv':
        raise ValueError(f"the first table must be {name}.csv (the plotted numbers)")
    csvs = [write_csv(os.path.join(out, fn), fields, rows) for fn, fields, rows in tables]
    paths += csvs
    manifest = write_manifest(
        out, tool=TOOL, tool_version=__version__,
        command=sys.argv if sys.argv and any(sys.argv) else ['python'],
        config={'experiment': name, **config}, seeds=seeds, snapshot=None,
        outputs=paths, labels=labels, extra=extra, timer=timer)
    print(f"  saved -> {manifest}")
    return {'dir': out, 'png': paths[0], 'csv': csvs, 'manifest': str(manifest)}


def style():
    """One consistent look for every graph in the report."""
    plt.rcParams.update({
        'figure.figsize': (9, 5),
        'axes.grid': True,
        'grid.alpha': 0.3,
        'font.size': 11,
        'axes.titlesize': 13,
        'axes.titleweight': 'bold',
        'legend.frameon': True,
        'legend.framealpha': 0.9,
    })

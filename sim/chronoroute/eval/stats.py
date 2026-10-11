"""
stats.py
--------
The statistics of the campaign (master plan 5.4), with numpy and the Python
standard library only (scipy is not installed here).

  * The unit of analysis is the RUN (one scenario, seed, start time): packets
    of one run are not independent. Every interval below resamples or
    averages RUNS, never packets.
  * t intervals (not z) for small n: mean +- t_(1-a/2, n-1) * s / sqrt(n).
  * Paired differences: the same seed with two schemes shares every random
    number (common random numbers), so compare per-run differences.
  * Cluster bootstrap: resample runs with replacement; percentile and BCa
    (bias-corrected and accelerated, Efron 1987; acceleration from the
    jackknife over runs) intervals, 10,000 resamples by default, seeded.
  * Holm-Bonferroni step-down correction for a family of p-values.
  * No survivorship bias: a run whose value is +inf (an effective quantile of a
    run that lost too many packets) is never dropped. It makes the mean and the
    interval infinite (t interval) or every resample holding it infinite
    (bootstrap). NaN values ("undefined in this run") are refused; only
    bootstrap resamples whose ratio is 0/0 are left out, and they are counted.

Special functions are computed here and tested against published values:
the normal quantile by bisection on math.erfc, the Student t distribution
through the regularized incomplete beta function (continued fraction,
modified Lentz method).
"""

import math

import numpy as np

# ---------------------------------------------------------------- normal


def normal_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def normal_ppf(p):
    """Quantile of the standard normal (bisection to the last bit of a double)."""
    if not 0.0 < p < 1.0:
        if p == 0.0:
            return -math.inf
        if p == 1.0:
            return math.inf
        raise ValueError("p must be in [0, 1]")
    lo, hi = -40.0, 40.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if normal_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-15 * max(1.0, abs(mid)):
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------- Student t


def _betacf(a, b, x):
    """Continued fraction of the incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 1000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            return h
    raise ArithmeticError("incomplete beta continued fraction did not converge")


def betainc(a, b, x):
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    if df <= 0:
        raise ValueError("df must be positive")
    x = df / (df + t * t)
    tail = 0.5 * betainc(0.5 * df, 0.5, x)
    return 1.0 - tail if t >= 0 else tail


def t_ppf(p, df):
    """Quantile of Student's t with df degrees of freedom (bisection on t_cdf)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    if p == 0.5:
        return 0.0
    lo, hi = -1.0, 1.0
    while t_cdf(lo, df) > p:
        lo *= 2.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-13 * max(1.0, abs(mid)):
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------- intervals and tests


def _per_run_values(x, what):
    """Per-run values as floats, refusing NaN.

    Why so strict: a NaN per-run value means "undefined in this run" (0/0), and
    silently dropping it, or dropping +inf values (an effective quantile is inf when
    a run lost more packets than the tail), would compute the interval over the
    surviving runs only: survivorship bias. The caller must decide what an
    undefined run means; infinities are kept and reported (n_inf).
    """
    x = np.asarray(x, dtype=float).ravel()
    if np.isnan(x).any():
        raise ValueError(f"{what}: {int(np.isnan(x).sum())} per-run values are NaN (undefined); "
                         "decide what they mean before computing an interval")
    return x


def mean_ci_t(x, conf=0.95):
    """{n, n_inf, mean, sd, lo, hi, half}: t interval of the mean of per-RUN values.

    Every run counts. If any run is +inf (or -inf) the mean is that infinity and so is
    the interval (lo = hi = mean): one infinite run makes the mean infinite, and no
    finite interval covers it. NaN values are refused (_per_run_values).
    """
    x = _per_run_values(x, "mean_ci_t")
    n = int(x.size)
    n_inf = int(np.isinf(x).sum())
    if n == 0:
        return {"n": 0, "n_inf": 0, "mean": None, "sd": None, "lo": None, "hi": None, "half": None}
    if n_inf:
        if np.isposinf(x).any() and np.isneginf(x).any():
            raise ValueError("mean_ci_t: both +inf and -inf among the runs: the mean is undefined")
        m = float(x[np.isinf(x)][0])
        return {"n": n, "n_inf": n_inf, "mean": m, "sd": None, "lo": m, "hi": m, "half": math.inf}
    m = float(x.mean())
    if n == 1:
        return {"n": 1, "n_inf": 0, "mean": m, "sd": None, "lo": None, "hi": None, "half": None}
    sd = float(x.std(ddof=1))
    half = t_ppf(0.5 + conf / 2.0, n - 1) * sd / math.sqrt(n)
    return {"n": n, "n_inf": 0, "mean": m, "sd": sd, "lo": m - half, "hi": m + half, "half": half}


def paired(a, b, conf=0.95):
    """Paired comparison of per-run values a[i], b[i] (same seed i): d = a - b.

    Returns the mean difference with its t interval, the t statistic and the
    two-sided p-value of H0: mean d = 0 (for Holm).
    """
    a = _per_run_values(a, "paired")
    b = _per_run_values(b, "paired")
    if a.shape != b.shape:
        raise ValueError("paired samples need the same runs on both sides")
    both = np.isinf(a) & np.isinf(b)
    if both.any():
        raise ValueError(f"paired: {int(both.sum())} runs are infinite on both sides: their difference "
                         "is undefined (compare those runs separately, e.g. by PDR)")
    d = a - b
    ci = mean_ci_t(d, conf)
    out = {"n": ci["n"], "n_inf": ci["n_inf"], "mean_diff": ci["mean"], "lo": ci["lo"], "hi": ci["hi"],
           "sd": ci["sd"], "t": None, "p": None}
    if ci["n_inf"]:
        return out                                   # an infinite difference: no t test
    if ci["n"] and ci["n"] > 1:
        if ci["sd"] == 0:
            out["t"] = 0.0 if ci["mean"] == 0 else math.copysign(math.inf, ci["mean"])
            out["p"] = 1.0 if ci["mean"] == 0 else 0.0
        else:
            t = ci["mean"] / (ci["sd"] / math.sqrt(ci["n"]))
            out["t"] = t
            out["p"] = 2.0 * (1.0 - t_cdf(abs(t), ci["n"] - 1))
    return out


def holm(pvalues, alpha=0.05):
    """Holm-Bonferroni: adjusted p-values (same order as given) and reject flags."""
    p = np.asarray(pvalues, dtype=float)
    m = p.size
    order = np.argsort(p, kind="stable")
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p[i]))
        adj[i] = running
    return {"adjusted": adj.tolist(), "reject": (adj <= alpha).tolist()}


# ---------------------------------------------------------------- cluster bootstrap

def _stat_mean(arr):
    return float(arr[:, 0].mean())


def _stat_ratio(arr):
    den = arr[:, 1].sum()
    return float(arr[:, 0].sum() / den) if den else float("nan")


STATISTICS = {"mean": _stat_mean, "ratio": _stat_ratio}


def bootstrap_ci(data, statistic="mean", n_boot=10_000, conf=0.95, method="bca", seed=0):
    """Cluster-bootstrap interval of a statistic of per-RUN rows.

    data       (n_runs, m) array, one row per run (1-D = one value per run)
    statistic  "mean" (mean of column 0), "ratio" (sum col 0 / sum col 1, e.g. PDR =
               delivered / sent pooled over the resampled runs), or a function
               (n_runs, m) array -> float
    method     "percentile" or "bca"
    Returns {estimate, lo, hi, method, n_runs, n_inf_runs, n_boot, n_boot_undefined}.

    Infinite values are kept, never dropped (no survivorship bias): a run whose value
    is +inf makes every resample that contains it +inf, so with an infinite run the
    estimate is inf and hi is inf, while lo stays finite only if enough resamples miss
    every infinite run. The only resamples left out are those whose statistic is NaN
    (a "ratio" resample whose denominator sums to 0, i.e. 0/0); they are counted in
    n_boot_undefined. NaN input values are refused. BCa needs a finite jackknife, so
    with infinite runs the percentile interval is returned and the method says why.

    Refused up front (as mean_ci_t and paired refuse them): a column holding both +inf
    and -inf (any resample drawing both would be inf - inf = NaN, and leaving those out
    would silently condition the interval on the resamples that miss one of them; this
    happens when bootstrapping paired differences where one side is infinite in one run
    and the other side in another run), and, for "ratio", an infinite denominator
    (inf / inf is NaN too; a denominator is a count such as packets sent).
    """
    arr = np.asarray(data, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, None]
    if np.isnan(arr).any():
        raise ValueError("bootstrap_ci: NaN per-run values (undefined) must be resolved by the caller")
    mixed = np.isposinf(arr).any(axis=0) & np.isneginf(arr).any(axis=0)
    if mixed.any():
        raise ValueError(f"bootstrap_ci: both +inf and -inf among the runs (column "
                         f"{int(np.flatnonzero(mixed)[0])}): every resample holding both is undefined "
                         "(inf - inf); resolve those runs first (e.g. compare them by PDR)")
    if statistic == "ratio" and np.isinf(arr[:, 1]).any():
        raise ValueError("bootstrap_ci: an infinite denominator in a ratio (inf / inf is undefined)")
    n = arr.shape[0]
    n_inf = int(np.isinf(arr).any(axis=1).sum())
    fn = STATISTICS[statistic] if isinstance(statistic, str) else statistic
    est = fn(arr)
    base = {"n_runs": n, "n_inf_runs": n_inf}
    if n < 2:
        return {"estimate": est, "lo": None, "hi": None, "method": method, **base, "n_boot": 0,
                "n_boot_undefined": 0}
    rng = np.random.Generator(np.random.Philox(seed))
    idx = rng.integers(0, n, size=(n_boot, n))
    with np.errstate(invalid="ignore", divide="ignore"):
        if statistic == "mean":
            boot = arr[idx, 0].mean(axis=1)
        elif statistic == "ratio":
            num = arr[idx, 0].sum(axis=1)
            den = arr[idx, 1].sum(axis=1)
            boot = num / den
        else:
            boot = np.array([fn(arr[row]) for row in idx], dtype=float)
    undefined = int(np.isnan(boot).sum())
    boot = np.sort(boot[~np.isnan(boot)])              # +-inf stay in: they are real outcomes
    base.update(n_boot=int(boot.size), n_boot_undefined=undefined)
    alpha = 1.0 - conf
    if boot.size == 0 or np.all(boot == boot[0]):
        v = est if boot.size == 0 else float(boot[0])
        return {"estimate": est, "lo": v, "hi": v, "method": method, **base}
    if method not in ("percentile", "bca"):
        raise ValueError("method must be percentile or bca")
    probs = [alpha / 2.0, 1.0 - alpha / 2.0]
    if method == "percentile":
        lo, hi = (_quantile_sorted(boot, q) for q in probs)
        return {"estimate": est, "lo": lo, "hi": hi, "method": method, **base}
    if n_inf or not math.isfinite(est):
        lo, hi = (_quantile_sorted(boot, q) for q in probs)
        return {"estimate": est, "lo": lo, "hi": hi, "method": "percentile (bca undefined: infinite runs)",
                **base}
    prop = (np.sum(boot < est) + 0.5 * np.sum(boot == est)) / boot.size
    if prop <= 0.0 or prop >= 1.0:
        lo, hi = (_quantile_sorted(boot, q) for q in probs)
        return {"estimate": est, "lo": lo, "hi": hi, "method": "percentile (bca undefined)", **base}
    z0 = normal_ppf(prop)
    jack = np.array([fn(np.delete(arr, i, axis=0)) for i in range(n)])
    jbar = jack.mean()
    num = np.sum((jbar - jack) ** 3)
    den = 6.0 * np.sum((jbar - jack) ** 2) ** 1.5
    a = float(num / den) if den > 0 else 0.0
    qs = []
    for z in (normal_ppf(alpha / 2.0), normal_ppf(1.0 - alpha / 2.0)):
        qs.append(normal_cdf(z0 + (z0 + z) / (1.0 - a * (z0 + z))))
    lo, hi = (_quantile_sorted(boot, q) for q in qs)
    return {"estimate": est, "lo": lo, "hi": hi, "method": "bca", "z0": z0, "acceleration": a, **base}


def _quantile_sorted(s, q):
    """numpy's default (linear, 'type 7') quantile of a sorted array, safe with +-inf.

    np.quantile interpolates as a + (b - a) * frac, which gives NaN when a = b = inf
    (inf - inf). Here: equal neighbours return that value; otherwise an infinite
    neighbour wins as soon as the position is not exactly on the finite one. Without
    infinities this IS np.quantile (same rounding).
    """
    if np.isfinite(s[0]) and np.isfinite(s[-1]):
        return float(np.quantile(s, q))
    h = (len(s) - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, len(s) - 1)
    frac = h - lo
    a, b = float(s[lo]), float(s[hi])
    if a == b or frac == 0.0:
        return a
    if math.isinf(a) or math.isinf(b):
        return b if math.isinf(b) else a
    return a + (b - a) * frac


__all__ = ["normal_cdf", "normal_ppf", "betainc", "t_cdf", "t_ppf", "mean_ci_t", "paired", "holm",
           "bootstrap_ci", "STATISTICS"]

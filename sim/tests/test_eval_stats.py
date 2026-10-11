"""Statistics with numpy only: special functions against published table values, t intervals,
paired tests, Holm, and the cluster bootstrap (percentile and BCa)."""

import math

import numpy as np
import pytest

from chronoroute.eval import stats


@pytest.mark.parametrize("p,want", [(0.975, 1.959963984540054), (0.5, 0.0), (0.999, 3.090232306167813),
                                    (0.05, -1.6448536269514729)])
def test_normal_quantile(p, want):
    assert stats.normal_ppf(p) == pytest.approx(want, abs=1e-12)
    assert stats.normal_cdf(stats.normal_ppf(p)) == pytest.approx(p, abs=1e-14)


@pytest.mark.parametrize("df,want", [(1, 12.706204736174698), (2, 4.302652729749464), (9, 2.262157162798205),
                                     (29, 2.045229642132703), (100, 1.983971518523552)])
def test_student_t_quantile_975(df, want):
    # values of Student's t table (two-sided 95 %)
    assert stats.t_ppf(0.975, df) == pytest.approx(want, rel=1e-9)
    assert stats.t_cdf(want, df) == pytest.approx(0.975, abs=1e-12)


def test_incomplete_beta_known_values():
    assert stats.betainc(1.0, 1.0, 0.3) == pytest.approx(0.3, abs=1e-14)          # uniform
    assert stats.betainc(2.0, 3.0, 0.4) == pytest.approx(0.5248, abs=1e-12)       # 1 - (1-x)^3 (1+3x) ... exact
    assert stats.betainc(0.5, 0.5, 0.5) == pytest.approx(0.5, abs=1e-12)          # arcsine, symmetric


def test_t_interval_uses_t_not_z():
    x = [10.0, 12.0, 9.0, 11.0, 13.0, 8.0, 10.0, 12.0]
    ci = stats.mean_ci_t(x)
    m, sd = np.mean(x), np.std(x, ddof=1)
    half = 2.364624251592785 * sd / math.sqrt(8)            # t(0.975, 7)
    assert ci["mean"] == pytest.approx(m) and ci["half"] == pytest.approx(half, rel=1e-9)
    assert ci["half"] > 1.96 * sd / math.sqrt(8)            # wider than the z interval for small n
    assert stats.mean_ci_t([3.0])["lo"] is None and stats.mean_ci_t([])["n"] == 0


def test_paired_difference():
    a = [0.991, 0.985, 0.995, 0.990, 0.988]
    b = [0.981, 0.980, 0.990, 0.982, 0.979]
    r = stats.paired(a, b)
    d = np.array(a) - np.array(b)
    t = d.mean() / (d.std(ddof=1) / math.sqrt(5))
    assert r["mean_diff"] == pytest.approx(d.mean()) and r["t"] == pytest.approx(t)
    assert r["p"] == pytest.approx(2 * (1 - stats.t_cdf(t, 4)))
    assert 0 < r["p"] < 0.01 and r["lo"] > 0
    same = stats.paired([1, 2, 3], [1, 2, 3])
    assert same["p"] == 1.0 and same["mean_diff"] == 0
    with pytest.raises(ValueError):
        stats.paired([1, 2], [1, 2, 3])


def _two_sided_p_reference(t, df):
    """P(|T| >= |t|) = I_x(df/2, 1/2), x = df / (df + t^2), to ~50 digits, independently of
    stats.betainc: the hypergeometric series I_x(a, b) = x^a (1-x)^b / (a B(a, b)) *
    sum_n (a+b)_n / (a+1)_n x^n in decimal arithmetic, with B(df/2, 1/2) from exact
    half-integer gamma values (pi from the decimal module's documented series)."""
    from decimal import Decimal, localcontext
    with localcontext() as ctx:
        ctx.prec = 60
        lasts, s, n, na, d, da, term = 0, Decimal(3), 1, 0, 0, 24, Decimal(3)
        while s != lasts:                                  # pi
            lasts = s
            n, na = n + na, na + 8
            d, da = d + da, da + 32
            term = term * n / d
            s += term
        pi = s

        def gamma_half(m):                                 # Gamma(m / 2), m a positive integer
            out = Decimal(1) if m % 2 == 0 else pi.sqrt()
            for k in range(1, m // 2) if m % 2 == 0 else range((m - 1) // 2):
                out *= Decimal(k) if m % 2 == 0 else Decimal(k) + Decimal("0.5")
            return out

        t = Decimal(abs(t))
        x = Decimal(df) / (Decimal(df) + t * t)
        a, b = Decimal(df) / 2, Decimal("0.5")
        beta = gamma_half(df) * gamma_half(1) / gamma_half(df + 1)
        series, term, k = Decimal(0), Decimal(1), 0
        while term > Decimal(10) ** -55 * series or k < 5:
            series += term
            term *= (a + b + k) / (a + 1 + k) * x
            k += 1
        xa = x ** (df // 2) * (x.sqrt() if df % 2 else 1)
        return float(xa * (1 - x).sqrt() / (a * beta) * series)


def test_two_sided_t_p_value_is_accurate_in_the_tail():
    """2 (1 - t_cdf(|t|)) cancelled: exactly 0 for |t| >~ 14 at df 35 (true p 1e-16 .. 1e-90)
    and distorted below ~1e-10. The tail is computed directly now."""
    # published table value: t(0.975, 35) = 2.0301079 (two-sided 5 %)
    assert stats.t_two_sided_p(2.0301079, 35) == pytest.approx(0.05, rel=1e-7)
    assert stats.t_two_sided_p(-2.0301079, 35) == stats.t_two_sided_p(2.0301079, 35)
    # 50-digit references (also confirmed by integrating the t density numerically); abs=0, or
    # approx would accept anything within its default 1e-12 (the old 0 included)
    assert stats.t_two_sided_p(10.0, 35) == pytest.approx(8.4781375877832794e-12, rel=1e-12, abs=0)
    assert stats.t_two_sided_p(40.0, 35) == pytest.approx(8.239044843834235e-31, rel=1e-12, abs=0)
    for df in (1, 2, 4, 9, 35, 100):
        for t in (1.0, 2.5, 4.0, 7.0, 12.0, 20.0, 40.0):             # the series needs x = df/(df+t^2) < 1
            want = _two_sided_p_reference(t, df)
            assert stats.t_two_sided_p(t, df) == pytest.approx(want, rel=1e-12, abs=0), (t, df)
    assert stats.t_two_sided_p(math.inf, 35) == 0.0 and stats.t_two_sided_p(0.0, 35) == 1.0
    # where the old formula was accurate (|t| < 5) the two agree: to 1e-12 relative, up to the
    # old formula's own absolute rounding (1 - t_cdf: 2^-52 at most)
    for df in (4, 35):
        for t in np.linspace(0.0, 4.99, 200):
            old = 2.0 * (1.0 - stats.t_cdf(t, df))
            assert stats.t_two_sided_p(t, df) == pytest.approx(old, rel=1e-12, abs=2.0 ** -52), (t, df)
    # paired() uses it: a strong but noisy difference keeps a tiny, nonzero p
    rng = np.random.default_rng(3)
    d = 1.0 + 0.15 * rng.standard_normal(36)
    r = stats.paired(d, np.zeros(36))
    assert r["t"] > 30 and 0.0 < r["p"] < 1e-25
    assert r["p"] == pytest.approx(_two_sided_p_reference(r["t"], 35), rel=1e-12, abs=0)
    # zero variance (documented convention): identical nonzero differences give p = 0 exactly
    const = stats.paired([2.0, 3.0, 4.0], [1.0, 2.0, 3.0])
    assert const["t"] == math.inf and const["p"] == 0.0


def test_holm_step_down():
    p = [0.01, 0.04, 0.03, 0.005]
    h = stats.holm(p, alpha=0.05)
    # sorted: 0.005*4=0.02, 0.01*3=0.03, 0.03*2=0.06, 0.04*1=0.04 -> cumulative max 0.06
    assert h["adjusted"] == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert h["reject"] == [True, False, False, True]


def test_bootstrap_percentile_and_bca():
    rng = np.random.default_rng(0)
    x = rng.normal(5.0, 1.0, size=40)
    p = stats.bootstrap_ci(x, "mean", n_boot=4000, method="percentile", seed=1)
    b = stats.bootstrap_ci(x, "mean", n_boot=4000, method="bca", seed=1)
    t = stats.mean_ci_t(x)
    for ci in (p, b):
        assert ci["lo"] < x.mean() < ci["hi"]
        assert ci["hi"] - ci["lo"] == pytest.approx(t["hi"] - t["lo"], rel=0.15)
    assert stats.bootstrap_ci(x, "mean", n_boot=500, seed=1) == stats.bootstrap_ci(x, "mean", n_boot=500, seed=1)
    # skewed data: BCa moves the interval towards the long tail more than the percentile one
    y = rng.exponential(1.0, size=30) ** 2
    pb = stats.bootstrap_ci(y, "mean", n_boot=4000, method="percentile", seed=2)
    bb = stats.bootstrap_ci(y, "mean", n_boot=4000, method="bca", seed=2)
    assert bb["hi"] > pb["hi"] and bb["acceleration"] > 0


def test_cluster_bootstrap_of_a_ratio_resamples_runs():
    # PDR pooled over runs = sum delivered / sum sent; runs are resampled whole
    runs = np.array([[990, 1000], [970, 1000], [1000, 1000], [400, 500], [995, 1000]], dtype=float)
    ci = stats.bootstrap_ci(runs, "ratio", n_boot=3000, method="bca", seed=3)
    assert ci["estimate"] == pytest.approx(runs[:, 0].sum() / runs[:, 1].sum())
    assert ci["lo"] < ci["estimate"] < ci["hi"] <= 1.0
    const = stats.bootstrap_ci(np.full(6, 2.0), "mean", n_boot=100)
    assert const["lo"] == const["hi"] == 2.0
    fn = stats.bootstrap_ci(runs, lambda a: float(np.median(a[:, 0] / a[:, 1])), n_boot=500, seed=4,
                            method="percentile")
    assert 0.8 <= fn["lo"] <= fn["hi"] <= 1.0


# ---------------------------------------------------------------- no survivorship bias

def test_infinite_runs_are_never_dropped():
    """An effective quantile is +inf when a run lost more packets than the tail; that run must
    stay in the interval, not vanish from it (the finding: n became 3 and the mean 2.0)."""
    ci = stats.mean_ci_t([1.0, 2.0, math.inf, 3.0])
    assert ci["n"] == 4 and ci["n_inf"] == 1
    assert ci["mean"] == ci["lo"] == ci["hi"] == math.inf
    assert stats.mean_ci_t([1.0, 2.0, 3.0])["n_inf"] == 0
    with pytest.raises(ValueError, match="NaN"):
        stats.mean_ci_t([1.0, float("nan"), 3.0])
    with pytest.raises(ValueError, match="both"):
        stats.mean_ci_t([1.0, math.inf, -math.inf])
    r = stats.paired([1.0, math.inf, 2.0], [0.5, 1.0, 1.0])
    assert r["n"] == 3 and r["n_inf"] == 1 and r["mean_diff"] == math.inf and r["p"] is None
    with pytest.raises(ValueError, match="infinite on both sides"):
        stats.paired([1.0, math.inf], [1.0, math.inf])


def test_bootstrap_keeps_infinite_resamples():
    x = [1.0, 2.0, math.inf, 3.0]
    p = stats.bootstrap_ci(x, n_boot=2000, method="percentile", seed=0)
    assert p["estimate"] == math.inf and p["hi"] == math.inf
    assert p["n_boot"] == 2000 and p["n_inf_runs"] == 1 and p["n_boot_undefined"] == 0
    # (3/4)^4 = 32 % of resamples miss the infinite run, so the lower end stays finite
    assert math.isfinite(p["lo"]) and 1.0 <= p["lo"] <= 3.0
    b = stats.bootstrap_ci(x, n_boot=2000, method="bca", seed=0)
    assert b["method"].startswith("percentile (bca undefined: infinite") and b["hi"] == math.inf
    # almost every resample holds an infinite run: the whole interval is infinite
    many = stats.bootstrap_ci([1.0] + [math.inf] * 5, n_boot=500, method="percentile", seed=1)
    assert many["lo"] == many["hi"] == math.inf
    with pytest.raises(ValueError, match="NaN"):
        stats.bootstrap_ci([1.0, float("nan")], n_boot=10)


def test_bootstrap_refuses_plus_and_minus_infinity_together():
    """Minor finding: with +inf and -inf runs together, every resample holding both was
    inf - inf = NaN and silently left out as 'undefined' (842 of 2000 here), and the estimate
    was NaN. Refused up front now, as mean_ci_t and paired refuse it."""
    inf = math.inf
    for method in ("percentile", "bca"):
        with pytest.raises(ValueError, match=r"both \+inf and -inf"):
            stats.bootstrap_ci([inf, -inf, 1.0, 2.0, 3.0], n_boot=2000, method=method)
    # the case it comes from: paired differences, one side infinite in one run, the other side
    # in another run (paired() refuses only runs infinite on BOTH sides)
    a, b = np.array([inf, 1.0, 2.0, 3.0]), np.array([1.0, inf, 2.0, 2.5])
    with pytest.raises(ValueError, match=r"both \+inf and -inf"):
        stats.bootstrap_ci(a - b, n_boot=100)
    with pytest.raises(ValueError, match=r"both \+inf and -inf"):
        stats.mean_ci_t(a - b)
    with pytest.raises(ValueError, match=r"both \+inf and -inf"):
        stats.bootstrap_ci(np.array([[inf, 1.0], [-inf, 1.0], [1.0, 1.0]]), "ratio", n_boot=100)
    with pytest.raises(ValueError, match="infinite denominator"):
        stats.bootstrap_ci(np.array([[1.0, inf], [1.0, 2.0]]), "ratio", n_boot=100)
    # one sign of infinity is still fine (kept, never dropped), in any column of a 2-D input
    ok = stats.bootstrap_ci([inf, inf, 1.0, 2.0], n_boot=500, method="percentile", seed=2)
    assert ok["estimate"] == inf and ok["n_boot_undefined"] == 0
    neg = stats.bootstrap_ci([-inf, 1.0, 2.0], n_boot=500, method="percentile", seed=2)
    assert neg["estimate"] == -inf and neg["lo"] == -inf and neg["n_boot_undefined"] == 0


def test_bootstrap_refuses_nan_from_a_statistic_function():
    """A function statistic could return NaN (inf - inf across columns) and those resamples were
    silently left out (estimate NaN, n_boot_undefined in the thousands), although only the
    built-in ratio's 0/0 resamples may be left out. Refused now, like the built-in cases."""
    inf = math.inf
    # each column holds one sign of infinity only, so the up-front checks pass
    both = np.array([[inf, 0.0], [0.0, inf], [1.0, 0.0], [2.0, 0.0]])
    with pytest.raises(ValueError, match="statistic function returned NaN for 1 estimate"), \
            np.errstate(invalid="ignore"):
        stats.bootstrap_ci(both, lambda a: float(a[:, 0].mean() - a[:, 1].mean()), n_boot=2000,
                           method="percentile")
    # defined on all runs (min 1 - min 0 = 1), NaN on the resamples drawing only the first run
    first_min = np.array([[inf, inf], [1.0, 0.0]])
    fn = lambda a: float(a[:, 0].min() - a[:, 1].min())
    assert fn(first_min) == 1.0
    for method in ("percentile", "bca"):
        with pytest.raises(ValueError, match="resamples"):
            stats.bootstrap_ci(first_min, fn, n_boot=2000, method=method, seed=0)
    # a function that is always defined is unaffected
    ok = stats.bootstrap_ci(np.array([[1.0, 0.0], [2.0, 0.5], [4.0, 1.0]]), fn, n_boot=200, method="percentile")
    assert ok["estimate"] == 1.0 and ok["n_boot_undefined"] == 0


def test_bootstrap_ratio_counts_undefined_resamples():
    # one run with nothing sent: a resample made only of it is 0/0 (undefined), never 'dropped quietly'
    runs = np.array([[5.0, 10.0], [0.0, 0.0]])
    ci = stats.bootstrap_ci(runs, "ratio", n_boot=1000, method="percentile", seed=5)
    assert ci["n_boot_undefined"] > 0 and ci["n_boot"] + ci["n_boot_undefined"] == 1000
    assert ci["lo"] == ci["hi"] == 0.5


def test_quantile_matches_numpy_without_infinities():
    rng = np.random.default_rng(7)
    s = np.sort(rng.normal(size=999))
    for q in (0.0, 0.025, 0.5, 0.975, 1.0):
        assert stats._quantile_sorted(s, q) == float(np.quantile(s, q))
    t = np.array([1.0, 2.0, math.inf, math.inf])
    assert stats._quantile_sorted(t, 0.5) == math.inf and stats._quantile_sorted(t, 1 / 3) == 2.0
    assert stats._quantile_sorted(t, 0.9) == math.inf                   # np.quantile would give NaN

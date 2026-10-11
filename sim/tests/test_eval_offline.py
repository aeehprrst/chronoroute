"""Offline threshold scoring: deadlines re-computed from ONE flag-and-continue run must equal
DIRECT runs of the other rules packet by packet (3 slack values and 2 deadline units), so a
slack sweep needs no re-simulation."""

import copy

import numpy as np
import pytest

from chronoroute.baselines import params, run as brun
from chronoroute.eval import load, offline
from chronoroute.eval.offline import Rule
from chronoroute.fwd import config

FLOWS = [{"src": "London", "dst": "New York"}, {"src": "Chennai", "dst": "London"},
         {"src": "Singapore", "dst": "Sydney"}, {"src": "Tokyo", "dst": "Los Angeles"}]


def doc(slack="1.5", unit=1, policy="continue"):
    return {"seed": 21,
            "scenario": {"kind": "walker", "preset": "C1", "duration_s": 3, "drain_s": 1, "chunk_steps": 20,
                         "gsl": {"min_elevation_deg": 10}},
            "traffic": {"flows": copy.deepcopy(FLOWS), "rate_pps": 100},
            "schedule": {"slack": slack, "unit_code": unit},
            "forwarding": {"policy": policy, "jitter": {"model": "j1", "mean_ns": 400000}},
            "faults": [{"kind": "slow_processing", "on_path": {"flow": 1, "kind": "node"}, "delta_ns": 3_000_000,
                        "start_s": 1, "stop_s": 2},
                       {"kind": "link_down", "on_path": {"flow": 2}, "start_s": 1.5, "stop_s": 2.5}],
            "output": {"trace": "none"}}


def run(tmp_path, name, d):
    out = tmp_path / name
    brun.run_scheme(config.normalise(d), params.normalise_scheme("chronoroute"), out, write_manifest=False)
    return load.load_run(out)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    return run(tmp_path_factory.mktemp("off"), "base", doc())


def paths_of(r):
    return {k: v["path"] for k, v in r.schedule.items()}


def test_rescoring_with_the_run_rule_reproduces_the_run(base):
    res = offline.rescore(base, Rule(kind="mult", slack="1.5"))
    cmp = offline.compare_with_run(res, base)
    assert cmp["first_late_mismatch"] == 0 and cmp["deadline_mismatch"] == 0, cmp
    assert res.flagged.sum() == (base.first_late >= 1).sum() > 0


@pytest.mark.parametrize("slack,unit", [("1.1", 1), ("1.25", 1), ("2", 1), ("1.5", 0), ("1.1", 2)])
def test_offline_equals_direct_run(tmp_path, base, slack, unit):
    direct = run(tmp_path, f"direct-{slack}-{unit}", doc(slack, unit))
    # the planner's rows did not change with the rule (checked, not assumed)
    assert paths_of(direct) == paths_of(base)
    res = offline.rescore(base, Rule(kind="mult", slack=slack, unit_code=unit))
    cmp = offline.compare_with_run(res, direct)
    assert cmp == {"packets": direct.n, "first_late_mismatch": 0, "deadline_mismatch": 0, "examples": []}
    # not vacuous: the rule really changes which packets are late
    if slack == "1.1":
        assert res.flagged.sum() > (base.first_late >= 1).sum()
    assert np.array_equal(res.flagged, direct.first_late >= 1)


def test_other_budget_rules_are_monotone(base):
    tight = offline.rescore(base, Rule(kind="add", per_hop_ns=100_000))
    loose = offline.rescore(base, Rule(kind="add", per_hop_ns=2_000_000))
    q = offline.rescore(base, Rule(kind="quantile", alpha="0.001", sigma_ns=400_000))
    assert tight.flagged.sum() >= loose.flagged.sum()
    assert np.all(loose.flagged <= tight.flagged)          # a later deadline never adds a flag
    assert q.flagged.sum() <= tight.flagged.sum() + base.n  # computed, finite
    b = Rule(kind="quantile", alpha="0.001", sigma_ns=1000).budgets([1000, 1000])
    assert b[0] == 1000 + 3091 and b[1] == 2000 + 4371     # z(0.999) = 3.0902; ceil(z * 1000 * sqrt(k))


def test_check_plans_and_refusals(tmp_path, base):
    cfg = config.normalise(doc())
    assert offline.check_plans(cfg, base, Rule(kind="mult", slack="1.1")) == []
    greedy = run(tmp_path, "greedy", doc(policy="greedy"))
    with pytest.raises(ValueError, match="flag-and-continue"):
        offline.rescore(greedy, Rule(kind="mult", slack="1.1"))
    with pytest.raises(ValueError):
        Rule(kind="bogus")


def test_instant_plan_reuse_validates_rows_and_refuses_stable(tmp_path, base):
    from chronoroute.fwd.scenario import build_scenario
    cfg = config.normalise(doc())
    with pytest.raises(ValueError, match="instant"):
        offline.check_plans(cfg, base, Rule(slack="1.1"), scenario=object())
    d = doc()
    d["schedule"]["plan_links"] = "instant"
    cfg = config.normalise(d)
    direct = run(tmp_path, "instant", d)
    sc = build_scenario(cfg)
    assert offline.check_plans(cfg, direct, Rule(slack="3"), scenario=sc) == []
    key = next(iter(direct.schedule))
    direct.schedule[key]["path"] = [99999]
    assert key in offline.check_plans(cfg, direct, Rule(slack="3"), scenario=sc)

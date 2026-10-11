"""Detection scoring (reviewer must-fix #1): counterfactual attribution with common random
numbers, the phantom fault (must give exactly 0 even where the naive metric does not), the
event detector, Kaplan-Meier delays and the event ROC."""

import copy

import numpy as np
import pytest

from chronoroute.baselines import params, run as brun
from chronoroute.eval import detection, load, metrics
from chronoroute.eval.offline import Rule
from chronoroute.fwd import config, scenario as sm

S = 1_000_000_000
MS = 1_000_000


def doc(faults=(), **over):
    d = {"seed": 9,
         "scenario": {"kind": "walker", "preset": "C1", "duration_s": 6, "drain_s": 1, "chunk_steps": 20,
                      "gsl": {"min_elevation_deg": 10}},
         "traffic": {"flows": [{"src": "London", "dst": "New York"}, {"src": "Chennai", "dst": "London"}],
                     "rate_pps": 100},
         "schedule": {"slack": "1.5"},
         "forwarding": {"policy": "continue", "jitter": {"model": "j1", "mean_ns": 400000}},
         "faults": copy.deepcopy(list(faults)), "output": {"trace": "none"}}
    d.update(over)
    return d


def run(tmp, name, d, scheme="chronoroute"):
    brun.run_scheme(config.normalise(d), params.normalise_scheme(scheme), tmp / name, write_manifest=False)
    return load.load_run(tmp / name)


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("det")
    sc = sm.build_scenario(config.normalise(doc()))
    a, b = sc.resolve_on_path({"flow": 0, "position": "middle"}, 2 * S, False)
    twin = run(tmp, "twin", doc())
    phantom = run(tmp, "phantom", doc([{"kind": "slow_processing", "link": [a, b], "delta_ns": 0,
                                        "start_s": 2, "stop_s": 5}]))
    phantom_rc = run(tmp, "phantom_rc", doc([{"kind": "rate_cut", "link": [a, b], "factor": 1,
                                              "start_s": 2, "stop_s": 5}]))
    real = run(tmp, "real", doc([{"kind": "slow_processing", "link": [a, b], "delta_ns": 15_000_000,
                                  "start_s": 2, "stop_s": 5}]))
    return {"tmp": tmp, "a": a, "b": b, "twin": twin, "phantom": phantom, "phantom_rc": phantom_rc,
            "real": real}


@pytest.mark.parametrize("which", ["phantom", "phantom_rc"])
def test_phantom_fault_gives_exactly_zero(setup, which):
    fr, tw = setup[which], setup["twin"]
    fault = fr.faults[0]
    for rule in (None, Rule(kind="mult", slack="1.05"), Rule(kind="mult", slack="1.2")):
        f1 = detection.flags_for(fr, rule)
        f0 = detection.flags_for(tw, rule)
        c = detection.counterfactual(fr, tw, f1, f0, fault)
        assert c["true_detections"] == 0 and c["induced_unexposed"] == 0 and c["lost_flags"] == 0
        for k in (1, 3):
            ev = detection.event_detection(fr, tw, f1, f0, fault, k=k, window_ns=S)
            assert ev["detected"] is False
    # ...while the naive metric of the old Exp1 ("an exposed packet carried a flag") is not 0
    f_tight = detection.flags_for(fr, Rule(kind="mult", slack="1.05"))
    exposed, _t = metrics.exposure(fr, fault)
    naive = int((exposed & f_tight.flagged).sum())
    assert exposed.sum() > 0 and naive > 0


def test_real_fault_is_attributed_and_localised(setup):
    fr, tw = setup["real"], setup["twin"]
    fault = fr.faults[0]
    f1, f0 = detection.flags_for(fr), detection.flags_for(tw)
    c = detection.counterfactual(fr, tw, f1, f0, fault)
    assert c["exposed"] > 200 and c["true_detections"] > 0
    assert 0 < c["p_det_packet"] <= 1
    assert c["localised_true_detections"] == c["true_detections"]   # flagged right behind the link
    ev = detection.event_detection(fr, tw, f1, f0, fault, k=3, window_ns=S)
    assert ev["detected"] and 0 <= ev["delay_ns"] < 200 * MS
    # paired runs differ only where the fault acts: unexposed packets keep their exact timing
    exposed, _ = metrics.exposure(fr, fault)
    same = ~exposed & (fr.send_ns < 2 * S - 200 * MS)
    assert np.array_equal(fr.latency_ns[same], tw.latency_ns[same])


def test_pairing_is_checked(setup, tmp_path):
    other = run(tmp_path, "other", doc(seed=10))
    with pytest.raises(ValueError, match="same packets"):
        detection.counterfactual(setup["real"], other, detection.flags_for(setup["real"]),
                                 detection.flags_for(other), setup["real"].faults[0])


def test_twin_must_have_the_same_other_faults(setup, tmp_path):
    """The blocker: the twin is 'the same run without the fault'. Background renewal failures
    must be identical in both (stable stream keys), and the scorer must refuse a twin whose
    other faults differ instead of silently pairing it."""
    a, b = setup["a"], setup["b"]
    renew = {"kind": "link_renewal", "unavailability": "0.01", "mttr_s": "0.3"}
    slow = {"kind": "slow_processing", "link": [a, b], "delta_ns": 15_000_000, "start_s": 2, "stop_s": 5}
    fr = run(tmp_path, "fr", doc([slow, renew]))
    tw = run(tmp_path, "tw", doc([renew]))                                  # the fault removed
    ph = run(tmp_path, "ph", doc([dict(slow, delta_ns=0), renew]))          # the phantom twin
    other = run(tmp_path, "other", doc([dict(renew, unavailability="0.02")]))
    scored = detection.scored_faults(fr, tw)
    assert [f["kind"] for f in scored] == ["slow_processing"]
    assert detection.scored_faults(fr, ph) == scored
    fault = scored[0]
    assert sum(1 for f in fr.faults if f["params"].get("model") == "renewal") > 5
    f1 = detection.flags_for(fr)
    c_removed = detection.counterfactual(fr, tw, f1, detection.flags_for(tw), fault)
    c_phantom = detection.counterfactual(fr, ph, f1, detection.flags_for(ph), fault)
    assert c_removed == c_phantom and c_removed["true_detections"] > 0
    with pytest.raises(ValueError, match="without the scored fault"):
        detection.counterfactual(fr, other, f1, detection.flags_for(other), fault)
    with pytest.raises(ValueError, match="without the scored fault"):
        detection.event_detection(fr, other, f1, detection.flags_for(other), fault)
    with pytest.raises(ValueError, match="not in the fault run"):
        detection.counterfactual(fr, tw, f1, detection.flags_for(tw), dict(fault, start_ns=fault["start_ns"] + 1))


def test_twin_with_another_configuration_is_refused(setup, tmp_path, capsys):
    """Minor finding: a twin with the same packets and the same faults but another jitter,
    slack, policy, carrier detection delay or scheme used to be accepted, and attribution was
    then silently wrong. check_twin now compares run.json engine.config (without the fault list
    and the output options) and the scheme, and names what differs."""
    from chronoroute import cli
    from chronoroute.fwd import command
    fr, tw = setup["real"], setup["twin"]
    fault = fr.faults[0]
    f1 = detection.flags_for(fr)
    proper = detection.counterfactual(fr, tw, f1, detection.flags_for(tw), fault)
    fw = doc()["forwarding"]
    bad = {
        "jitter": (doc(forwarding=dict(fw, jitter={"model": "j1", "mean_ns": 800000})), "chronoroute",
                   "engine.config.forwarding.jitter.mean_ns"),
        "slack": (doc(schedule={"slack": "1.1"}), "chronoroute", "engine.config.schedule.slack"),
        "policy": (doc(forwarding=dict(fw, policy="greedy")), "chronoroute", "engine.config.forwarding.policy"),
        "carrier": (doc(forwarding=dict(fw, carrier_detect_ms=20)), "chronoroute",
                    "engine.config.forwarding.carrier_detect_ms"),
        "scheme": (doc(), "e2e", "scheme.name (chronoroute vs e2e)"),
        "fb1": (doc(), {"name": "chronoroute", "feedback": {"mode": "fb1"}}, "scheme.settings.feedback.mode"),
    }
    for name, (d, scheme, key) in bad.items():
        other = run(tmp_path, name, d, scheme)
        assert np.array_equal(other.send_ns, fr.send_ns)            # items 1 and 2 cannot see it
        assert detection.scored_faults(fr, other) == [fault]
        with pytest.raises(ValueError, match="differ at") as err:
            detection.check_twin(fr, other, fault)
        assert key in str(err.value), (name, str(err.value))
        with pytest.raises(ValueError, match="differ at"):
            detection.counterfactual(fr, other, f1, detection.flags_for(other), fault)
    # the command refuses the pair (exit 2, the reason on stderr) and writes nothing
    out = tmp_path / "score"
    assert cli.main(["eval", "score", str(setup["tmp"] / "real"), "--twin", str(tmp_path / "slack"),
                     "--out", str(out)]) == 2
    assert "engine.config.schedule.slack" in capsys.readouterr().err and not out.exists()
    # what may differ: the output options (a full trace on one side), and a plain `cr run`
    # twin (no scheme block: the default chronoroute scheme, byte-identical to it)
    traced = run(tmp_path, "traced", doc(output={"trace": "full"}))
    assert detection.counterfactual(fr, traced, f1, detection.flags_for(traced), fault) == proper
    command.run_config(config.normalise(doc()), tmp_path / "plain")
    plain = load.load_run(tmp_path / "plain")
    assert "scheme" not in plain.run
    assert detection.counterfactual(fr, plain, f1, detection.flags_for(plain), fault) == proper
    # a run.json without engine.config cannot be checked
    old = dict(tw.run)
    tw.run = dict(old, engine={k: v for k, v in old["engine"].items() if k != "config"})
    try:
        with pytest.raises(ValueError, match="no engine.config"):
            detection.check_twin(fr, tw, fault)
    finally:
        tw.run = old


@pytest.fixture(scope="module")
def unscored_twins(setup, tmp_path_factory):
    """Pairs with no fault to score still need the same counterfactual checks."""
    tmp = tmp_path_factory.mktemp("unscored-twins")
    fw = doc()["forwarding"]
    return {
        "jitter": (run(tmp, "jitter", doc(forwarding=dict(
            fw, jitter={"model": "j1", "mean_ns": 800000}))),
            "engine.config.forwarding.jitter.mean_ns"),
        "slack": (run(tmp, "slack", doc(schedule={"slack": "1.1"})),
                  "engine.config.schedule.slack"),
        "scheme": (run(tmp, "scheme", doc(), "e2e"), "scheme.name"),
        "extra_fault": (setup["real"], "same faults otherwise"),
    }


@pytest.mark.parametrize("command", ["score", "roc"])
@pytest.mark.parametrize("difference", ["jitter", "slack", "scheme", "extra_fault"])
def test_unscored_pair_is_checked(setup, unscored_twins, tmp_path, capsys, command, difference):
    """An empty scored-fault list must not bypass validation and publish a mismatched pair."""
    from chronoroute import cli
    base = setup["twin"]
    other, reason = unscored_twins[difference]
    assert detection.scored_faults(base, other) == []
    out = tmp_path / command
    if command == "score":
        args = ["eval", "score", str(base.dir), "--twin", str(other.dir)]
    else:
        args = ["eval", "roc", "--pairs", f"{base.dir}:{other.dir}", "--slack", "1.2"]
    assert cli.main(args + ["--out", str(out)]) == 2
    assert reason in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize("command", ["score", "roc"])
def test_identical_unscored_pair_is_accepted(setup, tmp_path, command):
    """A valid null comparison has no detections to attribute, but can report false events."""
    from chronoroute import cli
    path = str(setup["twin"].dir)
    if command == "score":
        args = ["eval", "score", path, "--twin", path]
    else:
        args = ["eval", "roc", "--pairs", f"{path}:{path}", "--slack", "1.2"]
    assert cli.main(args + ["--out", str(tmp_path / command)]) == 0


def test_roc_can_filter_out_the_scored_fault(setup, unscored_twins):
    """Selecting no events to score must still accept a valid pair and check its settings."""
    rules = [Rule(kind="mult", slack="1.2")]
    fr, tw = setup["real"], setup["twin"]
    rows = detection.event_roc([(fr, tw)], lambda _run: [], rules)
    baseline = detection.event_roc([(tw, tw)], None, rules)
    assert rows[0]["fault_events"] == 0 and rows[0]["p_det"] is None
    assert rows[0]["false_events_per_hour"] == baseline[0]["false_events_per_hour"]
    assert rows[0]["clean_fpr"] == baseline[0]["clean_fpr"]
    other, _reason = unscored_twins["jitter"]
    with pytest.raises(ValueError, match="differ at"):
        detection.event_roc([(fr, other)], lambda _run: [], rules)


def test_detector_window_and_reset():
    n = 6
    fl = detection.Flags(flagged=np.array([1, 1, 1, 1, 1, 0], dtype=bool), node=np.full(n, 5),
                         time=np.array([0, 100, 250, 260, 270, 0]), a=np.full(n, 4), b=np.full(n, 5))
    assert [e[0] for e in detection.detect_events(fl, 2, 150)] == [100, 260]   # k=2 in (t-150, t]
    assert [e[0] for e in detection.detect_events(fl, 3, 1000)] == [250]       # restarts after firing
    assert detection.detect_events(fl, 2, 50) == [(260, ("link", 4, 5), [2, 3])]


def test_kaplan_meier_hand_computed():
    t, s = detection.kaplan_meier([1, 2, 2, 3, 4], [1, 1, 0, 1, 0])
    assert t.tolist() == [1, 2, 3]
    assert np.allclose(s, [0.8, 0.6, 0.3])
    assert detection.km_median([1, 2, 2, 3, 4], [1, 1, 0, 1, 0]) == 3
    assert detection.km_median([5, 5], [0, 0]) is None                         # all censored


def test_false_events_and_event_roc(setup):
    pairs = [(setup["real"], setup["twin"]), (setup["phantom"], setup["twin"])]
    rules = [Rule(kind="mult", slack=s) for s in ("1.05", "1.3", "2")]
    rows = detection.event_roc(pairs, lambda r: r.faults, rules, k=2, window_ns=S)
    assert [r["rule"] for r in rows] == ["S=1.05", "S=1.3", "S=2"]
    assert all(r["fault_events"] == 2 for r in rows)
    # the phantom event is never detected, so P_det <= 1/2, and the real 15 ms fault is found
    p = [r["p_det"] for r in rows]
    fpr = [r["clean_fpr"] for r in rows]
    assert all(x <= 0.5 for x in p) and max(p) == 0.5
    # a later deadline can only remove flags, so the clean-packet FPR never grows with S
    assert fpr == sorted(fpr, reverse=True) and fpr[0] > fpr[-1]
    assert all(r["false_events_per_hour"] is not None for r in rows)


def test_lq_and_control_plane_detection(setup, tmp_path):
    a, b = setup["a"], setup["b"]
    f = [{"kind": "rate_cut", "link": [a, b], "factor": 0.0002, "start_s": 2, "stop_s": 4}]
    over = {"traffic": {"flows": [{"src": "London", "dst": "New York"}], "rate_pps": 200}}
    fr = run(tmp_path, "lq_f", doc(f, **over), "lq")
    tw = run(tmp_path, "lq_t", doc((), **over), "lq")
    c = detection.counterfactual(fr, tw, detection.lq_flags(fr), detection.lq_flags(tw), fr.faults[0])
    assert c["true_detections"] > 0 and c["localised_true_detections"] == c["true_detections"]
    lf = run(tmp_path, "lsd_f", doc(f, **over), {"name": "ls_d", "ls_d": {"window_s": 1}})
    lt = run(tmp_path, "lsd_t", doc((), **over), {"name": "ls_d", "ls_d": {"window_s": 1}})
    cp = detection.control_plane_detection(lf, lt, lf.faults[0])
    assert cp["detected"] and cp["delay_ns"] >= 50 * MS        # at least the SPF delay after a window end
def test_empty_event_roc_has_undefined_endpoints():
    assert detection.event_roc([], None, [None])[0]["clean_fpr"] is None


def test_plain_run_without_per_hop_records_scores_cleanly(setup, tmp_path):
    """A plain `cr run` folder has no scheme_packets.csv.gz, hence no packet labels. Scored
    against a twin with no fault to score, `cr eval score` used to crash (UnboundLocalError:
    the packet-detector flag and the labels were only defined when per-hop records exist).
    Now it reports the twin's false events and leaves the clean-packet FPRs undefined (None);
    scoring a fault without per-hop records stays a clean refusal (exit 2)."""
    import json
    from chronoroute import cli
    from chronoroute.eval import command as eval_command
    from chronoroute.fwd import command
    plain = tmp_path / "plain"
    command.run_config(config.normalise(doc()), plain)
    assert not load.load_run(plain).has_extras()
    out = tmp_path / "score"
    assert cli.main(["eval", "score", str(plain), "--twin", str(plain), "--out", str(out)]) == 0
    res = json.loads((out / "summary.json").read_text())
    assert "fpr" not in res and "stretch" not in res
    d = res["detection"][0]
    assert d["faults"] == [] and d["fpr"] is None and d["fpr_twin"] is None
    assert d["false_events_twin"]["hours"] == pytest.approx(6 / 3600)
    # a twin WITH per-hop records still gets its FPR; the plain side's stays undefined
    mixed = eval_command.score_run(plain, twin_dir=setup["twin"].dir)["detection"][0]
    assert mixed["fpr"] is None and mixed["fpr_twin"]["clean"] > 0
    # a scored fault needs the per-hop records of the fault run: refused, nothing written
    faulty = tmp_path / "plain_fault"
    slow = {"kind": "slow_processing", "link": [setup["a"], setup["b"]], "delta_ns": 15_000_000,
            "start_s": 2, "stop_s": 5}
    command.run_config(config.normalise(doc([slow])), faulty)
    refused = tmp_path / "refused"
    assert cli.main(["eval", "score", str(faulty), "--twin", str(setup["twin"].dir), "--out", str(refused)]) == 2
    assert not refused.exists()


@pytest.fixture(scope="module")
def ls_twin(tmp_path_factory):
    return run(tmp_path_factory.mktemp("ls-twin"), "lsd", doc(), {"name": "ls_d", "ls_d": {"window_s": 1}})


def test_false_events_per_hour_use_the_warmup_window(setup, ls_twin):
    """With --warmup-s the twin's flags were restricted to packets sent after the warm-up, but
    the hours were the whole sending window, so false events per hour were biased low by
    (T - warm-up) / T. Events and hours now both cover [warm-up, T_end - drain)."""
    from chronoroute.eval import command as eval_command
    tw = setup["twin"]                                 # sends in [0, 6 s)
    warm = 2 * S
    res = eval_command.score_run(tw.dir, twin_dir=tw.dir, warmup_ns=warm, slacks=("1.05",), sensitivity_ks=(1, 3))
    rule = Rule(kind="mult", slack="1.05")
    for d, r in zip(res["detection"], (None, rule)):
        fes = [d["false_events_twin"]] + [s["false_events_twin"] for s in d["sensitivities"]]
        for fe, k in zip(fes, (1, 1, 3)):
            assert fe["hours"] == pytest.approx(4 / 3600)
            assert fe["per_hour"] == pytest.approx(fe["events"] / (4 / 3600))
            # the events are exactly those of packets sent in the same window
            m = metrics.measurement_mask(tw, warm)
            assert fe == detection.false_events_per_hour(tw, detection.flags_for(tw, r), k, S, mask=m,
                                                         warmup_ns=warm)
    assert res["detection"][1]["false_events_twin"]["events"] > 0         # a tight slack flags packets
    # no warm-up: the whole sending window, as before
    full = eval_command.score_run(tw.dir, twin_dir=tw.dir)["detection"][0]["false_events_twin"]
    assert full["hours"] == pytest.approx(6 / 3600)
    # native link-state: control-plane events counted over the same window as the hours
    ls = eval_command.score_run(ls_twin.dir, twin_dir=ls_twin.dir, warmup_ns=warm)["detection"][0]
    fe = ls["false_events_twin"]
    want = sum(warm <= x["t_ns"] < 6 * S and x["kind"] in ("adjacency_down", "metric") for x in ls_twin.detections)
    assert fe["hours"] == pytest.approx(4 / 3600) and fe["events"] == want


def test_event_roc_refuses_pairs_of_different_schemes(setup, unscored_twins, tmp_path):
    """P_det, packet P_det and clean FPR are defined or not by the scheme (O-Q, native LS), and
    event_roc decided that from the LAST pair: a list mixing schemes is refused now."""
    from chronoroute import cli
    e2e = unscored_twins["scheme"][0]
    with pytest.raises(ValueError, match="one scheme"):
        detection.event_roc([(setup["real"], setup["twin"]), (e2e, e2e)], None, [None])
    assert detection.event_roc([(e2e, e2e)], None, [None])[0]["fault_events"] == 0      # one scheme: fine
    out = tmp_path / "roc"
    assert cli.main(["eval", "roc", "--pairs", f"{setup['real'].dir}:{setup['twin'].dir}",
                     f"{e2e.dir}:{e2e.dir}", "--out", str(out)]) == 2
    assert not out.exists()


def test_null_faults_are_always_scored_and_include_null_says_so(capsys):
    """--include-null never changed anything: scored_faults returns every null fault of the
    fault run anyway. The help text said it 'explicitly' scored them; it now says it has no
    effect."""
    from types import SimpleNamespace
    from chronoroute import cli
    null = {"kind": "slow_processing", "link": [1, 2], "start_ns": 0, "stop_ns": S, "params": {"delta_ns": 0}}
    assert detection.is_null_fault(null)
    assert detection.scored_faults(SimpleNamespace(faults=[null]), SimpleNamespace(faults=[])) == [null]
    for sub in ("score", "roc"):
        with pytest.raises(SystemExit):
            cli.main(["eval", sub, "--help"])
        text = " ".join(capsys.readouterr().out.split())
        assert "--include-null no effect: null (phantom) faults are always scored" in text

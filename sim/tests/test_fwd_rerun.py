"""Live-mode re-runs (fwd/rerun.py, the viewer's d and f keys): the same run with ONE more fault,
same seed and same random numbers. A packet that never meets the new fault must come out
byte-identical; only packets whose path (in either run) crosses the faulted link may change."""

import csv
import gzip
import json

import pytest

from chronoroute import provenance
from chronoroute.eval import detection, load
from chronoroute.fwd import command, config, engine, rerun, scenario as sm
from chronoroute.trace import reader

S = 1_000_000_000


def doc():
    return {"seed": 5,
            "scenario": {"kind": "walker", "preset": "C1", "duration_s": 4, "drain_s": 1, "chunk_steps": 20,
                         "gsl": {"min_elevation_deg": 10}},
            "traffic": {"flows": [{"src": "London", "dst": "New York"}, {"src": "Tokyo", "dst": "Los Angeles"}],
                        "rate_pps": 100},
            "forwarding": {"policy": "greedy", "jitter": {"model": "j1", "mean_ns": 300000}},
            # background renewal failures: they must stay identical in the re-run (stable stream keys)
            "faults": [{"kind": "link_renewal", "unavailability": "0.01", "mttr_s": "0.3"}],
            "output": {"trace": "sampled", "sample_every": 2}}


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    out = tmp_path_factory.mktemp("rerun") / "base"
    cfg = config.normalise(doc())
    command.run_config(cfg, out)
    sc = sm.build_scenario(cfg)
    link = sc.resolve_on_path({"flow": 0, "position": "middle"}, 2 * S, False)
    return out, (int(link[0]), int(link[1]))


def rows(d):
    with gzip.open(d / "packets.csv.gz", "rt", encoding="utf-8") as fh:
        return {int(r["pkt"]): r for r in csv.DictReader(fh)}


def crosses(row, link):
    p = row["path"].split()
    return any({p[i], p[i + 1]} == {str(link[0]), str(link[1])} for i in range(len(p) - 1))


@pytest.mark.parametrize("kind", ["rate", "slow", "down"])
def test_rerun_changes_only_packets_that_cross_the_link(base, kind, tmp_path):
    out, link = base
    new = engine.rerun_with_fault(out, flow=0, link=link, start_ns=2 * S, kind=kind, out_dir=tmp_path / kind)
    assert reader.validate_run(new) == []
    provenance.validate_manifest(new / "manifest.json")
    run = json.loads((new / "run.json").read_text())
    assert run["rerun"]["kind"] == kind and run["rerun"]["flow"] == 0
    added = rerun.fault_for(kind, link, 2 * S, 4 * S)
    assert run["engine"]["config"]["faults"][-1] == added
    r0, r1 = rows(out), rows(new)
    assert r0.keys() == r1.keys()
    changed = {k for k in r0 if r0[k] != r1[k]}
    assert changed, "the new fault must change something on a link this flow uses"
    for k in changed:
        assert crosses(r0[k], link) or crosses(r1[k], link), (k, r0[k]["path"], r1[k]["path"])
        assert int(r0[k]["send_ns"]) >= 2 * S - 200_000_000      # nothing long before the fault changes
    # the background renewal failures are identical, so the original IS the counterfactual twin
    # of the re-run for the new fault (check_twin would refuse it otherwise)
    fr, tw = load.load_run(new), load.load_run(out)
    scored = detection.scored_faults(fr, tw)
    assert len(scored) == 1 and scored[0]["kind"] == rerun.KINDS[kind]
    detection.check_twin(fr, tw, scored[0])
    assert sum(1 for f in tw.faults if f["params"].get("model") == "renewal") > 0


def test_rerun_refuses_what_it_cannot_redo(base, tmp_path):
    out, link = base
    with pytest.raises(ValueError, match="kind"):
        rerun.rerun_with_fault(out, flow=0, link=link, start_ns=S, kind="melt", out_dir=tmp_path / "x")
    with pytest.raises(ValueError, match="must start"):
        rerun.rerun_with_fault(out, flow=0, link=link, start_ns=5 * S, out_dir=tmp_path / "y")
    old = tmp_path / "old"
    old.mkdir()
    doc_ = json.loads((out / "run.json").read_text())
    del doc_["engine"]["config"]
    (old / "run.json").write_text(json.dumps(doc_))
    with pytest.raises(ValueError, match="engine.config"):
        rerun.rerun_with_fault(old, flow=0, link=link, start_ns=S)
    doc_["tool"] = "ns-3"
    (old / "run.json").write_text(json.dumps(doc_))
    with pytest.raises(ValueError, match="python-sim"):
        rerun.rerun_with_fault(old, flow=0, link=link, start_ns=S)


def test_chained_reruns_record_every_live_fault(base, tmp_path):
    """Re-running a re-run keeps the faults added before (the viewer re-runs the run on screen).
    run.json "rerun" lists them all (live_faults, oldest first) and names the original, so the
    viewer can say that every one of them is active, not only the newest."""
    out, link = base
    first = rerun.rerun_with_fault(out, flow=0, link=link, start_ns=2 * S, kind="down", out_dir=tmp_path / "r1")
    other = (link[1], link[0])
    second = rerun.rerun_with_fault(first, flow=0, link=other, start_ns=2 * S + 300_000_000, kind="rate",
                                    out_dir=tmp_path / "r2")
    r1 = json.loads((first / "run.json").read_text())["rerun"]
    r2 = json.loads((second / "run.json").read_text())
    assert r1["original"] == str(out) and [x["kind"] for x in r1["live_faults"]] == ["down"]
    rr = r2["rerun"]
    assert rr["of"] == str(first) and rr["original"] == str(out)
    assert [x["kind"] for x in rr["live_faults"]] == ["down", "rate"]
    assert rr["live_faults"][0]["fault"] == rerun.fault_for("down", link, 2 * S, 4 * S)
    assert rr["live_faults"][1]["fault"] == rr["fault"] == rerun.fault_for("rate", other, 2 * S + 300_000_000, 4 * S)
    # both are really in the run: the engine config carries them after the original faults
    added = r2["engine"]["config"]["faults"][-2:]
    assert added == [x["fault"] for x in rr["live_faults"]]
    kinds = [f["kind"] for f in r2["faults"]]
    assert "link_down" in kinds and "rate_cut" in kinds

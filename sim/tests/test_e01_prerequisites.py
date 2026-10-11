"""Required campaign pilot and replay dependencies, before confirmation."""

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from chronoroute.baselines import params, run as brun
from chronoroute.eval import load
from chronoroute.fwd import config
from chronoroute.export import ns3_crosscheck

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "experiments/E01"))
SPEC = importlib.util.spec_from_file_location("e01_prerequisites", REPO / "experiments/E01/prerequisites.py")
pre = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pre)


def test_explicit_send_time_cpp_parser(tmp_path):
    source = tmp_path / "test.cc"
    source.write_text('''#include "probe-times.h"
#include <cassert>
#include <sstream>
int main() {
  std::istringstream good("flow_id,seq,send_ns\\n0,0,2\\n1,0,3\\n0,1,4\\n");
  auto rows = ns3::tcrh::ReadProbeTimes(good, {0,1}, 10);
  assert(rows.at(0).size() == 2 && rows.at(0)[1].second == 4);
  for (auto text : {"bad\\n", "flow_id,seq,send_ns\\n0,1,2\\n", "flow_id,seq,send_ns\\n0,0,10\\n",
                    "flow_id,seq,send_ns\\n0,0,-1\\n", "flow_id,seq,send_ns\\n0,0,2\\n0,1,2\\n",
                    "flow_id,seq,send_ns\\n0,0,2x\\n", "flow_id,seq,send_ns\\n2,0,3\\n"}) {
    bool rejected=false;
    try {std::istringstream bad(text); ns3::tcrh::ReadProbeTimes(bad,{0},10);}
    catch(const std::exception&) {rejected=true;}
    assert(rejected);
  }
}
''')
    binary = tmp_path / "test"
    subprocess.run(["g++", "-std=c++17", "-Wall", "-Werror", "-I", str(REPO / "ns3/contrib/chronoroute/helper"),
                    str(source), "-o", str(binary)], check=True, capture_output=True)
    subprocess.run([str(binary)], check=True)


def test_fixed_prerequisite_matrix_and_uniform_lists():
    jobs = pre.pilot_jobs()
    assert len(jobs) == 30
    assert {j["seed"] for j in jobs if j["experiment"] == "E04"} == {1}
    assert {j["seed"] for j in jobs if j["experiment"] == "E05"} == {2}
    assert {j["seed"] for j in jobs if j["experiment"] == "E16"} == {3}
    times = pre.send_times(3, stochastic=True)
    assert times == pre.send_times(3, stochastic=True)
    for row in times:
        assert len(row) == len(set(row)) == 1200
        assert row == sorted(row) and min(row) >= 0 and max(row) < 12000000000
    cbr = pre.send_times(0, stochastic=False)
    assert np.all(np.diff(cbr[0]) == 10000000)
    assert cbr[0] != cbr[1]


def test_targeted_outage_uses_existing_renewal_stream():
    from chronoroute.fwd.faults import renewal_periods
    from chronoroute.fwd.rng import KeyedStreams
    periods = renewal_periods(KeyedStreams(1), "node_fault", (123,), 3000000000, 27000000000, "0.05", 2000000000)
    assert pre.targeted_faults(1, 123) == [{"kind": "node_down", "node": 123,
              "start_s": a / 1e9, "stop_s": b / 1e9} for a, b in periods]


@pytest.mark.parametrize("enabled", [True, False])
def test_forced_deviation_preserves_pretrigger_packets_across_policies(tmp_path, enabled):
    from chronoroute.fwd.scenario import build_scenario
    d = {"seed": 2, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 9, "drain_s": 1,
                               "gsl": {"min_elevation_deg": 10}},
         "traffic": {"flows": [{"src": "London", "dst": "New York"}]},
         "output": {"invariants": "all", "trace": "none"}}
    sc = build_scenario(config.normalise(d))
    target = sc.resolve_on_path({"flow": 0, "at_s": 4, "position": "middle"}, 4000000000, True)
    if not enabled:
        target = -1
    runs = []
    for policy in ("continue", "greedy", "drop"):
        records = []
        cfg = config.normalise({**d, "forwarding": {"policy": policy}})
        factory = pre.deviation_factory(target, records)
        summary, _ = brun.run_scheme(cfg, params.normalise_scheme({"name": "chronoroute", "outputs": {"stretch_oracle": False}}),
                                  tmp_path / policy, engine_factory=factory, write_manifest=False)
        assert summary["invariants"]["violations"] == 0 and bool(records) == enabled
        assert len({r["pkt"] for r in records}) == len(records)
        assert all(4000000000 <= r["t_ns"] < 8000000000 and r["label"] == "MODELLED" for r in records)
        runs.append(load.load_run(tmp_path / policy))
    m = runs[0].send_ns < 3900000000 if enabled else np.ones(runs[0].n, dtype=bool)
    for r in runs[1:]:
        assert np.array_equal(r.latency_ns[m], runs[0].latency_ns[m])
        assert all(np.array_equal(r.path(i), runs[0].path(i)) for i in np.flatnonzero(m))
        if not enabled:
            assert np.array_equal(r.wire, runs[0].wire)
            assert all(np.array_equal(r.deadline_u[i], runs[0].deadline_u[i]) for i in range(r.n))
    assert bool((runs[-1].outcome == 1).sum() > 0) == enabled


def test_full_replay_compares_losses_packets_and_nanosecond_arrivals():
    from types import SimpleNamespace
    run = SimpleNamespace(n=1, flow=np.array([0]), seq=np.array([0]), send_ns=np.array([1]),
                          outcome=np.array([1]), reason=["buffer_overflow"], latency_ns=np.array([-1]),
                          paths=[[5, 6]], arrival_u=[[1]], deadline_u=[[2]], first_late=np.array([-1]),
                          dev=np.array([False]), dev_hop=np.array([-1]), row_from_ms=np.array([0]), wire=np.array([274]),
                          schedule={(0, 0): {"path": [5, 6, 7]}}, arr_ns=lambda i: np.array([10]))
    row = {"flow_id": 0, "seq": 0, "send_ns": 1, "outcome": "drop_queue", "taken_path": [5, 6],
           "planned_path": [5, 6, 7], "hop_t_ns": [10], "hop_now_u": [1], "hop_deadline_u": [2],
           "first_late_hop": None, "dev": 0, "dev_hop": 0, "latency_ns": None, "row_from_ms": 0, "wire_bytes": 274}
    assert ns3_crosscheck.compare_replays(run, [row])["violations"] == 0
    row["hop_t_ns"] = [11]
    assert ns3_crosscheck.compare_replays(run, [row])["violations"] == 1
    assert ns3_crosscheck.compare_replays(run, [])["violations"] == 1
    assert ns3_crosscheck.compare_replays(run, [row, row])["violations"] > 0


def test_gate_export_and_config_contract(tmp_path):
    cfg = pre.replay_config("C2", 3, stochastic=True, fault=True)
    assert cfg["forwarding"]["processing_ns"] == cfg["schedule"]["planner_processing_ns"] == 0
    assert cfg["scenario"]["drain_s"] == 2 and cfg["faults"][0]["factor"] == 0.0002
    assert len(cfg["traffic"]["flows"][0]["send_times_ns"]) == 1200
    pre.write_sends(tmp_path / "times.csv", [[1, 2], [3]])
    assert (tmp_path / "times.csv").read_text().splitlines()[-1] == "1,0,3"
    assert pre.main(["--help"]) == 0


def test_pilot_configs_cover_every_policy_and_only_one_outage_target(monkeypatch):
    from types import SimpleNamespace
    sc = SimpleNamespace(resolve_on_path=lambda *a: 1, path_at=lambda *a: [10, 1, 2, 11], topo=SimpleNamespace(n_sats=10))
    monkeypatch.setattr(pre, "build_scenario", lambda cfg: sc)
    for job in pre.pilot_jobs():
        if job["experiment"] == "E16":
            continue
        cfg, scheme, intervention = pre.pilot_config(job)
        assert cfg["schedule"]["plan_links"] == "stable" and scheme["outputs"]["stretch_oracle"]
        if job["experiment"] == "E04":
            assert cfg["scenario"]["duration_s"] == 30 and cfg["scenario"]["drain_s"] == 2
            assert all(f["node"] == 1 for f in cfg["faults"])
        else:
            assert not cfg["faults"] and intervention["target"] in (1, 2)


def test_replay_export_and_child_use_actual_small_fixture(tmp_path, monkeypatch):
    from chronoroute import provenance
    cfg = pre.replay_config("C2", 0, stochastic=False, fault=False)
    cfg["scenario"].update(kind="walker", preset="C1", duration_s=1)
    for flow in cfg["traffic"]["flows"]:
        flow["send_times_ns"] = list(range(1000000, 1000000000, 100000000))
    monkeypatch.setattr(pre, "replay_config", lambda *a, **k: cfg)
    out = tmp_path / "replay"
    rows, comparison = pre.run_replay("C2", 0, False, False, out, engines=("python",))
    assert comparison is None and rows[0]["status"] == "ok"
    provenance.validate_manifest(out / "manifest.json")
    assert json.loads((out / "manifest.json").read_text())["wall_seconds"] >= rows[0]["wall_s"]
    records = []
    monkeypatch.setattr(pre, "pilot_config", lambda *a: (cfg, params.normalise_scheme({"name": "chronoroute", "outputs": {"stretch_oracle": False}}),
                                                        {"target": -1, "records": records}))
    assert pre.run_child({"experiment": "E05", "seed": 2, "id": "unit-fixture"}, tmp_path / "child") == 0
    provenance.validate_manifest(tmp_path / "child/manifest.json")


def test_prerequisite_driver_keeps_gate_failure_and_measured_forecast(tmp_path, monkeypatch):
    from chronoroute import provenance
    monkeypatch.setattr(pre.provenance, "git_state", lambda *a, **k: {"dirty": False, "sha": "0" * 40})
    def replay(const, seed, fault, stochastic, out):
        rows = [{"experiment": "E16", "const": const, "scheme": engine, "seed": seed, "fault": fault,
                 "status": "ok", "cpu_s": 1, "wall_s": 1, "command": ["unit-fixture"], "peak_rss_kb": 1,
                 "returncode": 0} for engine in ("python", "ns3")]
        return rows, {"violations": int(not stochastic and fault)}
    monkeypatch.setattr(pre, "run_replay", replay)
    monkeypatch.setattr(pre.e1, "measured_command", lambda *a, **k: {"status": "ok", "cpu_s": 1, "wall_s": 1,
                                  "command": ["unit-fixture"], "peak_rss_kb": 1, "returncode": 0})
    pilot = tmp_path / "e1-pilot"
    pilot.mkdir()
    (pilot / "resource_forecast.json").write_text(json.dumps({"effective_workers": 6, "measured_spent_s": 10, "e1_projected_s": 100}))
    (pilot / "score_inventory.json").write_text(json.dumps([{"cpu_s": 1}]))
    (pilot / "manifest.json").write_text("{}")
    out = tmp_path / "prerequisites"
    assert pre.main(["--out", str(out), "--e1-pilot", str(pilot), "--workers", "2"]) == 1
    provenance.validate_manifest(out / "manifest.json")
    forecast = json.loads((out / "resource_forecast.json").read_text())
    assert not forecast["confirmation_allowed"] and not forecast["deterministic_gate_passed"]

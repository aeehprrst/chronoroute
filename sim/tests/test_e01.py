"""Prospective E1 configuration, inventory, provenance and pilot gate tests."""

import importlib.util
import json
from pathlib import Path

import pytest

from chronoroute import provenance
from chronoroute.fwd import config

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("e01_campaign", REPO / "experiments/E01/campaign.py")
e1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(e1)


def test_prereg_and_complete_e1_design():
    e1.validate_protocol()
    assert len(e1.PAIRS) == 18
    assert len(e1.CONDITIONS) == 18
    assert len(e1.RULES) == 9
    jobs = e1.jobs("confirmatory")
    assert len(jobs) == 9576 and len({j["id"] for j in jobs}) == len(jobs)
    assert {j["seed"] for j in jobs} == set(range(1000, 1036))
    assert len(e1.jobs("pilot")) == 66
    assert all(j["seed"] < 100 for j in e1.jobs("pilot"))
    assert e1.pair_id(1017, "confirmatory") == 17
    assert e1.pair_id(1018, "confirmatory") == 0
    with pytest.raises(ValueError):
        e1.pair_id(99, "confirmatory")


def test_exact_engine_contract_and_shared_targets():
    for const in ("C5", "C2"):
        for scheme in e1.SCHEMES:
            j = next(j for j in e1.jobs("confirmatory") if j["const"] == const and j["scheme"] == scheme and j["condition"] == "delay-1000000-middle")
            doc = e1.document(j, {"middle": [12, 13]})
            cfg = config.normalise(doc["engine"])
            assert cfg["scenario"]["duration_s"] == 12 and cfg["scenario"]["drain_s"] == 2
            assert cfg["forwarding"]["policy"] == "continue"
            assert cfg["forwarding"]["background"]["rho"] == 0.3
            assert cfg["forwarding"]["verify_every"] == 100
            assert cfg["output"]["invariants"] == "all"
            assert cfg["schedule"]["plan_links"] == "instant"
            assert cfg["schedule"]["planner_processing_ns"] == 900000
            assert cfg["faults"][0]["link"] == [12, 13]
            assert doc["scheme"]["outputs"]["stretch_oracle"] is False
            assert doc["campaign"]["prereg_sha256"] == e1.PREREG_HASH
            if scheme == "ls_d":
                assert doc["scheme"]["ls_d"]["window_s"] == 0.2
            if const == "C2":
                assert cfg["scenario"]["preset"] == "C2"
    with pytest.raises(ValueError):
        e1.document({**j, "seed": 0}, {"middle": [12, 13]})


def test_resource_forecast_never_certifies_partial_or_failed_pilot():
    rows = [{"status": "ok", "scheme": s, "const": c, "wall_s": 30, "peak_rss_kb": 400000}
            for s in e1.SCHEMES for c in ("C5", "C2")]
    f = e1.resource_forecast(rows, batch_wall_s=60, batch_process_s=360, spent_s=120)
    assert f["e1_projected_s"] == 9576 * 30 / 6
    assert f["status"] == "blocked" and f["confirmation_allowed"] is False
    rows[0]["status"] = "timeout"
    f = e1.resource_forecast(rows, batch_wall_s=60, batch_process_s=360, spent_s=120)
    assert "failed" in f["reason"]
    with pytest.raises(ValueError):
        e1.resource_forecast([], batch_wall_s=0, batch_process_s=0, spent_s=0)
    for row in rows:
        row.update(cpu_s=15, status="ok")
    f = e1.resource_forecast(rows, batch_wall_s=60, batch_process_s=90, spent_s=120)
    assert f["effective_workers"] == 1.5 and f["e1_projected_s"] == 9576 * 15 / 1.5


def test_selection_uses_pooled_counts_family_balance_and_frozen_order():
    rows = []
    for rule in range(9):
        for seed in range(6):
            for family in ("rate", "delay", "arq"):
                rows.append({"const": "C5", "rule_index": rule, "seed": seed, "family": family,
                             "clean": 1000, "fp": 0 if rule else 20,
                             "tp": 50 if rule in (0, 1, 2) else 20, "crossed": 100})
    selected = e1.select_rule(rows, "C5")
    assert selected["rule_index"] == 1 and selected["fpr"] == 0
    for r in rows:
        r["fp"] = 20
    assert e1.select_rule(rows, "C5")["failed_fpr"] is True
    assert e1.select_rule(rows, "C5")["rule_index"] == 4
    for r in rows:
        if r["family"] == "arq":
            r["crossed"] = 0
    assert "zero crossed" in e1.select_rule(rows, "C5")["candidates"][1]["ineligible_reason"]
    with pytest.raises(ValueError, match="six"):
        e1.select_rule(rows[:-1], "C5")


def test_measured_subprocess_records_success_failure_and_timeout(tmp_path):
    import sys
    ok = e1.measured_command([sys.executable, "-c", "print('real subprocess')"], tmp_path / "ok", timeout=5)
    assert ok["status"] == "ok" and ok["peak_rss_kb"] > 0 and ok["wall_s"] > 0
    assert "real subprocess" in (tmp_path / "ok.log").read_text()
    fail = e1.measured_command([sys.executable, "-c", "raise SystemExit(3)"], tmp_path / "bad", timeout=5)
    assert fail["status"] == "failed" and fail["returncode"] == 3
    slow = e1.measured_command([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path / "slow", timeout=0.1)
    assert slow["status"] == "timeout"


def test_preflight_checks_every_row_and_all_thirds(monkeypatch, tmp_path):
    from types import SimpleNamespace
    sc = SimpleNamespace(flows=[0, 1], plan=lambda f, a, b: SimpleNamespace(path=[100, 1, 2, 3, 101]),
                         resolve_on_path=lambda op, t, node: (1, 2))
    monkeypatch.setattr(e1, "build_scenario", lambda cfg: sc)
    targets = e1.preflight(tmp_path, constellations=("C2",), pairs=(0,))
    assert targets["C2:0"]["last"] == [1, 2]
    doc = json.loads((tmp_path / "preflight.json").read_text())
    assert doc["checks"] == 24 and doc["violations"] == 0
    sc.plan = lambda f, a, b: None
    with pytest.raises(ValueError, match="no path"):
        e1.preflight(tmp_path / "bad", constellations=("C2",), pairs=(0,))


def test_archive_summary_and_manifest_inputs(tmp_path):
    src = tmp_path / "raw"
    src.mkdir()
    (src / "data.txt").write_text("unit fixture")
    e1.archive_raw(src)
    assert (tmp_path / "raw.tar.gz").is_file() and not src.exists()
    e1.write_csv(tmp_path / "rows.csv", [{"a": 1, "b": "x"}])
    assert "a,b" in (tmp_path / "rows.csv").read_text()
    e1.write_csv(tmp_path / "empty.csv", [])
    assert (tmp_path / "empty.csv").is_file()
    assert e1.main(["--help"]) == 0


def test_campaign_metadata_preserves_engine_manifest_and_hashes(tmp_path):
    (tmp_path / "fixture.txt").write_text("unit fixture")
    m = provenance.write_manifest(tmp_path, tool="unit fixture", tool_version="1", command=["unit-fixture"],
                                  config={}, seeds=[0], outputs=[tmp_path / "fixture.txt"])
    before = json.loads(m.read_text())
    input_hash = provenance.file_sha256(tmp_path / "fixture.txt")
    e1.attach_metadata(tmp_path, {"phase": "pilot"}, {"cpu_s": 0.5}, inputs=[tmp_path / "fixture.txt"])
    after = json.loads(m.read_text())
    assert after["outputs"] == before["outputs"] and after["git_sha"] == before["git_sha"]
    assert after["extra"]["campaign"]["phase"] == "pilot"
    assert after["extra"]["measured_command"]["cpu_s"] == 0.5
    assert after["extra"]["inputs"][0]["sha256"] == input_hash
    provenance.validate_manifest(m)


def test_job_and_driver_keep_failed_jobs_manifested(tmp_path, monkeypatch):
    job = e1.jobs("pilot")[0]
    monkeypatch.setattr(e1, "measured_command", lambda *a, **k: {"command": ["unit-fixture"], "wall_s": 1,
                         "cpu_s": 0.8, "peak_rss_kb": 123, "returncode": 2, "status": "failed"})
    row = e1.run_job(job, tmp_path, {"C5:0": {"middle": [1, 2]}})
    assert row["status"] == "failed"
    path = tmp_path / "runs" / job["id"] / "manifest.json"
    provenance.validate_manifest(path)
    assert json.loads(path.read_text())["extra"]["campaign"]["phase"] == "pilot"
    c2 = next(j for j in e1.jobs("pilot") if j["const"] == "C2")
    e1.run_job(c2, tmp_path, {"C2:0": {"middle": [1, 2]}})
    c2m = json.loads((tmp_path / "runs" / c2["id"] / "manifest.json").read_text())
    assert "orbital_elements" not in c2m["labels"]
    monkeypatch.setattr(e1.provenance, "git_state", lambda *a: {"dirty": True})
    with pytest.raises(ValueError, match="commit"):
        e1.main(["--out", str(tmp_path / "must-not-start")])


def test_pilot_analysis_refuses_missing_seeds_and_keeps_failed_scores(tmp_path, monkeypatch):
    monkeypatch.setattr(e1, "measured_command", lambda *a, **k: {"status": "timeout", "wall_s": 1})
    rows = e1.score_pilot(tmp_path, [e1.jobs("pilot")[1]])
    assert rows == []
    assert json.loads((tmp_path / "score_inventory.json").read_text())[0]["status"] == "timeout"
    assert not (tmp_path / "operating_points.json").exists()
    e1.plot_pilot(tmp_path, [{"const": "C5", "scheme": "chronoroute", "wall_s": 1, "status": "ok"}], [])
    assert (tmp_path / "figures/runtime.png").is_file()


def test_driver_manifests_the_partial_matrix_and_refuses_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(e1.provenance, "git_state", lambda *a, **k: {"dirty": False, "sha": "0" * 40})
    monkeypatch.setattr(e1, "preflight", lambda *a: {})
    monkeypatch.setattr(e1, "run_job", lambda j, *a: {**j, "status": "ok", "command": ["unit-fixture"],
                         "cpu_s": 0.01, "wall_s": 0.01, "peak_rss_kb": 100, "returncode": 0})
    monkeypatch.setattr(e1, "score_pilot", lambda *a: [])
    out = tmp_path / "pilot"
    assert e1.main(["--out", str(out), "--workers", "2"]) == 0
    provenance.validate_manifest(out / "manifest.json")
    assert json.loads((out / "manifest.json").read_text())["extra"]["confirmation_started"] is False
    assert json.loads((out / "resource_forecast.json").read_text())["remaining_pilot_jobs"] == 30

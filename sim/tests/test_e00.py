"""E0 gate: reject corrupt inputs and exercise the independent adapters."""

import importlib.util
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from chronoroute import provenance
from chronoroute.trace import pcap

REPO = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("e00_gate", REPO / "experiments/E00/gate.py")
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_fixed_config_matches_preregistration():
    cfg = gate.load_config(REPO / "experiments/E00/config.json")
    assert cfg["orbit_satellites"] == 200
    assert cfg["model"]["walker"]["planes"] == 72
    assert cfg["model"]["gsl"]["policy"] == "sticky_top_k"
    assert cfg["offsets_s"] == list(range(0, 6001, 10))
    assert cfg["campaign"]["prereg_git_sha"] == "b87f08a7cc9431d139bf66372f03133035494b8c"
    assert len(cfg["pairs"]) == 18
    assert not any(s in {"Reykjavik", "Anchorage"} for s, _ in cfg["pairs"])
    assert gate.select_records([SimpleNamespace(norad=i) for i in range(500)], 200)[-1].norad == 499
    with pytest.raises(ValueError):
        gate.select_records([SimpleNamespace(norad=1)], 200)
    with pytest.raises(ValueError):
        gate.select_records([SimpleNamespace(norad=1)] * 2, 2)


def test_config_and_clean_commit_are_required(tmp_path, monkeypatch):
    cfg = json.loads((REPO / "experiments/E00/config.json").read_text())
    cfg["campaign"]["prereg_sha256"] = "0" * 64
    f = tmp_path / "config.json"
    f.write_text(json.dumps(cfg))
    with pytest.raises(ValueError, match="prereg"):
        gate.load_config(f)
    cfg = json.loads((REPO / "experiments/E00/config.json").read_text())
    for key, value in [("shell", "53.0deg-550km"), ("start_utc", "2026-10-11T14:00:00Z"),
                       ("snapshot", "data/latest"), ("orbit_satellites", 2), ("pairs", [])]:
        changed = {**cfg, key: value}
        f.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            gate.load_config(f)
    monkeypatch.setattr(provenance, "git_state", lambda: {"sha": "abc", "dirty": True})
    with pytest.raises(ValueError, match="clean"):
        gate.require_clean()
    monkeypatch.setattr(provenance, "git_state", lambda: {"sha": "abc", "dirty": False})
    assert gate.require_clean() == "abc"


def test_metric_counts_nonfinite_and_real_violations():
    row = gate.metric("test", "C5", "REAL", [0, 10, 10.1, np.nan, np.inf], 10, "m")
    assert row["checked"] == 5 and row["violations"] == 3 and row["worst"] == 10.1
    low = gate.metric("test", "C2", "MODELLED", [80, 79.9], 80, "km", lower=True)
    assert low["violations"] == 1 and low["worst"] == 79.9
    with pytest.raises(ValueError, match="empty"):
        gate.metric("empty", "C5", "REAL", [], 1, "m")


def test_orbit_scores_both_input_paths_and_refuses_shape():
    ref = np.zeros((2, 3, 3))
    js = np.zeros((3, 2, 3))
    js[1, 0, 0] = 0.011
    rows, detail = gate.orbit_metrics("C5", ref, ref, {"pinned": js, "exported": js}, [0, 10, 20])
    assert len(rows) == 4 and len(detail) == 12
    assert sum(r["violations"] for r in rows) == 4
    with pytest.raises(ValueError, match="shape"):
        gate.orbit_metrics("C5", ref, ref, {"pinned": js[:1]}, [0, 10, 20])


def test_certified_height_rejects_a_sub_atmospheric_laser():
    pa = np.array([[7000., 0., 0.], [6400., -100., 0.]])
    pb = np.array([[7000., 100., 0.], [6400., 100., 0.]])
    heights = gate.certified_heights(pa, pb)
    assert heights[0] > 80 and heights[1] < 80


def test_link_gate_detects_corrupt_delay_and_grazing():
    sc = SimpleNamespace(
        sat_pos_km=np.array([[[6400., -100., 0.]], [[6400., 100., 0.]]]),
        ground_stations=(), n_sats=2, isl_a=np.array([0]), isl_b=np.array([1]),
        isl_up=np.array([[True]]), gsl_visible=np.empty((0, 1), bool),
        gsl_sat=np.array([], int), gsl_gs=np.array([], int),
        gsl_up=np.empty((0, 1), bool), gsl_elev_deg=np.empty((0, 1)),
        gsl_params=SimpleNamespace(min_elevation_deg=25, max_links_per_gs=4),
        grid_params=SimpleNamespace(polar_cutoff_deg=70), isl_kind=np.array([0]),
        sat_lat_deg=np.zeros((2, 1)), graph=SimpleNamespace(prop_ns=np.array([[1]])))
    rows = gate.link_metrics(sc, 0, "C2")
    assert next(r for r in rows if r["check"] == "isl_grazing")["violations"] == 1
    assert next(r for r in rows if r["check"] == "link_light_time")["violations"] == 1


def test_golden_cases_and_schedule_modes():
    schedules = [{"constellation": "C2", "pair": "a-b", "sids": [2, 61440],
                  "budgets": [1000000, 2000000], "t_gps_ns": 1000000123}]
    cases = gate.make_cases(schedules)
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        result = gate.python_case(c)
        assert result == c["expected"], c["name"]
        assert gate.wire_line(c).startswith(c["op"] + "\t")
    enc = [c for c in cases if c["name"].startswith("schedule/") and c["op"] == "B"]
    assert {c["nh"] for c in enc} == {17, 41}
    assert {c.get("policy") for c in cases if c["op"] == "P"} >= {"greedy", "drop", "continue"}
    crh = json.loads((REPO / "spec/golden/crh_vectors.json").read_text())
    assert len([c for c in cases if c["name"].startswith("crh-golden/")]) == sum(len(crh[k]) for k in ("encode", "process"))
    with pytest.raises(ValueError):
        gate.python_case({"op": "unknown"})


def test_physics_pipeline_checks_all_samples_and_exports_schedules():
    cfg = {"start_utc": "2026-10-10T14:00:00Z", "offsets_s": [0, 6000],
           "pairs": [["Chennai", "London"]], "orbit_satellites": 2}
    t0 = gate.omm.parse_epoch_ns(cfg["start_utc"].removesuffix("Z"))
    fleet = gate.presets.walker_fleet(gate.presets.WALKER_PRESETS["C2"], t0)
    rows, paths, schedules, records, times = gate.physics_run(cfg, "C2", fleet, "53.0deg-550km")
    assert all(r["violations"] == 0 for r in rows)
    assert len(paths) == 2 and all(p["reachable"] for p in paths)
    assert len(schedules) == 1 and len(records) == 2 and times == [t0, t0 + 6000_000_000_000]


def test_adapter_comparison_never_accepts_missing_or_duplicate_cases():
    cases = [{"id": 0, "name": "x", "expected": {"hex": "abcd"}}]
    assert gate.compare_cases(cases, [{"id": 0, "hex": "abcd"}], "ns3")[0][0]["violations"] == 0
    assert gate.compare_cases(cases, [{"id": 0, "hex": "abce"}], "ns3")[0][0]["violations"] == 1
    for outputs in [[], [{"id": 0, "hex": "abcd"}] * 2, [{"id": 1, "hex": "abcd"}]]:
        with pytest.raises(ValueError):
            gate.compare_cases(cases, outputs, "ns3")


@pytest.fixture(scope="module")
def adapters(tmp_path_factory):
    out = tmp_path_factory.mktemp("e00-adapters")
    commands = []
    paths = gate.prepare_adapters(out, commands)
    cases = gate.make_cases([])
    inp = out / "wire.json"
    t0 = gate.omm.parse_epoch_ns("2026-10-10T14:00:00")
    records = gate.presets.walker_fleet(gate.presets.WALKER_PRESETS["C2"], t0).records[:2]
    orbit = {"constellation": "C2", "records": [dict(r.values) for r in records],
             "omm_min": json.loads(gate.snapshot.omm_min_bytes(records)), "times_ns": [str(t0), str(t0 + 10_000_000_000)]}
    inp.write_text(json.dumps({"cases": cases, "orbits": [orbit]}))
    gate.run_command([str(paths["node"]), str(paths["browser"]), str(inp), str(out / "browser.json")], out, commands)
    protocol = out / "wire.tsv"
    protocol.write_text("\n".join(gate.wire_line(c) for c in cases) + "\n")
    cpp = gate.run_command([str(paths["ns3"]), str(protocol)], out, commands)
    return out, cases, json.loads((out / "browser.json").read_text()), [json.loads(x) for x in cpp.splitlines()], commands


def test_real_browser_and_ns3_adapters_on_every_golden_case(adapters):
    out, cases, browser, cpp, commands = adapters
    assert commands and all(x["returncode"] == 0 for x in commands)
    for producer, data in [("browser", browser["cases"]), ("ns3", cpp)]:
        rows, mismatches = gate.compare_cases(cases, data, producer)
        assert rows[0]["checked"] == len(cases) and rows[0]["violations"] == 0, mismatches
    with pytest.raises(subprocess.CalledProcessError):
        gate.run_command(["/bin/false"], out, commands)
    assert commands[-1]["returncode"] != 0


def test_browser_adapter_propagates_both_input_paths(adapters):
    out, _, browser, _, _ = adapters
    orbit = json.loads((out / "wire.json").read_text())["orbits"][0]
    records = [gate.omm.OmmRecord.from_object(r) for r in gate.omm.parse_omm_json(json.dumps(orbit["records"]))]
    times = list(map(int, orbit["times_ns"]))
    full = gate.SatelliteArray(records).propagate(times, geodetic=False).r_ecef
    ms = np.stack([gate._ms_epoch_ecef_km(records, t) for t in times], axis=1)
    data = browser["orbits"][0]
    rows, _ = gate.orbit_metrics("C2", full, ms, {s: data[s] for s in ("pinned", "exported")}, [0, 10])
    assert all(r["violations"] == 0 for r in rows)


def test_wireshark_actual_bytes_fields_and_expected_rejections(adapters):
    out, cases, _, _, commands = adapters
    frames = gate.write_wire_pcap(cases, out / "wire.pcap")
    assert frames and any(x["reason"] for x in frames)
    rows, details = gate.check_wireshark(out / "wire.pcap", frames, out, commands)
    assert all(r["violations"] == 0 for r in rows), details
    broken = [dict(f) for f in frames]
    broken[0]["hex"] = "ff" + broken[0]["hex"][2:]
    rows, _ = gate.check_wireshark(out / "wire.pcap", broken, out, commands)
    assert sum(r["violations"] for r in rows) > 0


def test_output_writer_figures_and_manifest_validation(tmp_path):
    rows = [gate.metric("demo", "C5", "REAL", [0, 1], 10, "m")]
    detail = [{"constellation": "C5", "input": "pinned", "offset_s": 0,
               "satellite_index": 0, "full_error_m": 1, "ms_error_m": 0.1}]
    files = gate.write_outputs(tmp_path, rows, detail, [], [])
    assert (tmp_path / "summary.csv") in files
    assert {x.suffix for x in files} >= {".csv", ".png", ".json"}
    assert all(x.is_file() for x in files)
    assert gate.gate_exit(rows) == 0
    rows[0]["violations"] = 1
    assert gate.gate_exit(rows) == 1


def test_cli_refuses_dirty_tree_without_creating_results(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "git_state", lambda: {"sha": "abc", "dirty": True})
    out = tmp_path / "run"
    with pytest.raises(ValueError, match="clean"):
        gate.main(["--out", str(out)])
    assert not out.exists()


def test_cli_retains_failed_run_with_valid_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(provenance, "git_state", lambda *args, **kwargs: {"sha": "a" * 40, "dirty": False})
    def broken_adapter(*args):
        raise RuntimeError("adapter intentionally unavailable in test")
    monkeypatch.setattr(gate, "prepare_adapters", broken_adapter)
    out = tmp_path / "failed"
    assert gate.main(["--out", str(out)]) == 1
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["extra"]["status"] == "fail"
    assert manifest["dirty"] is False
    assert "adapter intentionally unavailable" in (out / "error.txt").read_text()
    provenance.validate_manifest(out / "manifest.json")
    with pytest.raises(FileExistsError):
        gate.main(["--out", str(out)])


def test_cli_complete_pipeline_and_manifest(tmp_path, monkeypatch):
    # A small synthetic fixture exercises orchestration; it is not campaign evidence.
    cfg = json.loads((REPO / "experiments/E00/config.json").read_text())
    cfg.update(offsets_s=[0, 6000], orbit_satellites=2, pairs=[["Chennai", "London"]], shell="53.0deg-550km")
    monkeypatch.setattr(gate, "load_config", lambda path: cfg)
    monkeypatch.setattr(provenance, "git_state", lambda *args, **kwargs: {"sha": "a" * 40, "dirty": False})
    t0 = gate.omm.parse_epoch_ns(cfg["start_utc"].removesuffix("Z"))
    fleet = gate.presets.walker_fleet(gate.presets.WALKER_PRESETS["C2"], t0)
    monkeypatch.setattr(gate.snapshot, "load_pinned", lambda *args: fleet)
    out = tmp_path / "complete"
    assert gate.main(["--out", str(out)]) == 0
    manifest = provenance.validate_manifest(out / "manifest.json")
    assert manifest["extra"]["status"] == "pass" and manifest["dirty"] is False
    assert manifest["extra"]["path_checks"] == 4
    assert set(manifest["extra"]["selected_norads"]) == {"C5", "C2"}

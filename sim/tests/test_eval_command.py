"""The `cr eval` commands end to end through the real command line (cli.main): run a scheme
from a run file with a scheme: block, score it against its twin with an offline slack sweep,
and build an event ROC; every result folder carries a valid manifest."""

import csv
import json

from chronoroute import cli, provenance

RUN = """\
seed: 4
scenario:
  kind: walker
  preset: C1
  duration_s: 3
  drain_s: 1
  chunk_steps: 20
  gsl: {min_elevation_deg: 10}
traffic:
  flows:
    - {src: London, dst: New York}
  rate_pps: 100
forwarding:
  policy: continue
  jitter: {model: j1, mean_ns: 400000}
output:
  trace: none
"""

FAULT = """\
faults:
  - kind: slow_processing
    on_path: {flow: 0, position: middle}
    delta_ns: 15000000
    start_s: 1
    stop_s: 2
"""


def test_scheme_score_and_roc(tmp_path, capsys):
    (tmp_path / "twin.yaml").write_text(RUN, encoding="utf-8")
    (tmp_path / "fault.yaml").write_text(RUN + FAULT, encoding="utf-8")
    (tmp_path / "lsh.yaml").write_text(RUN + "scheme:\n  name: ls_h\n  ls: {preset: ospf, bfd: true}\n",
                                       encoding="utf-8")
    assert cli.main(["eval", "scheme", "--config", str(tmp_path / "fault.yaml"), "--out", str(tmp_path / "f")]) == 0
    assert cli.main(["eval", "scheme", "--config", str(tmp_path / "twin.yaml"), "--out", str(tmp_path / "t")]) == 0
    assert cli.main(["eval", "scheme", "--config", str(tmp_path / "lsh.yaml"), "--out", str(tmp_path / "l")]) == 0
    out = capsys.readouterr().out
    assert "ls_h[ospf+bfd]" in out and "control bytes" in out
    for d in ("f", "t", "l"):
        provenance.validate_manifest(tmp_path / d / "manifest.json")
    m = json.loads((tmp_path / "l" / "manifest.json").read_text())
    assert m["config"]["scheme"]["ls"]["preset"] == "ospf" and m["tool"] == "cr eval scheme"
    assert cli.main(["eval", "score", str(tmp_path / "f"), "--twin", str(tmp_path / "t"),
                     "--slack", "1.2", "2", "--k", "2", "--out", str(tmp_path / "score")]) == 0
    doc = json.loads((tmp_path / "score" / "summary.json").read_text())
    assert doc["pdr"]["pdr"] == 1.0 and doc["stretch"]["violations"] == 0
    assert [d["rule"] for d in doc["detection"]] == ["as run", "S=1.2", "S=2"]
    assert doc["detection"][0]["faults"][0]["packet"]["true_detections"] > 0
    rows = list(csv.DictReader(open(tmp_path / "score" / "summary.csv", encoding="utf-8")))
    assert {r["metric"] for r in rows} >= {"pdr", "q0.5_eff", "stretch_min", "clean_fpr", "p_det_packet"}
    provenance.validate_manifest(tmp_path / "score" / "manifest.json")
    assert cli.main(["eval", "roc", "--pairs", f"{tmp_path / 'f'}:{tmp_path / 't'}", "--slack", "1.1", "1.5",
                     "--out", str(tmp_path / "roc")]) == 0
    roc = json.loads((tmp_path / "roc" / "summary.json").read_text())
    assert [r["rule"] for r in roc["rows"]] == ["S=1.1", "S=1.5"]


def test_bad_run_file_is_a_clean_error(tmp_path, capsys):
    (tmp_path / "bad.yaml").write_text(RUN + "scheme:\n  name: nope\n", encoding="utf-8")
    assert cli.main(["eval", "scheme", "--config", str(tmp_path / "bad.yaml"), "--out", str(tmp_path / "x")]) == 2
    assert "scheme.name" in capsys.readouterr().err


def test_all_rules_flow_filter_and_explicit_null_controls(tmp_path):
    run = RUN.replace("flows:\n    - {src: London, dst: New York}",
                      "flows:\n    - {src: London, dst: New York}\n    - {src: New York, dst: London}")
    run += "schedule: {plan_links: instant}\n"
    (tmp_path / "t.yaml").write_text(run)
    (tmp_path / "f.yaml").write_text(run + FAULT.replace("15000000", "0"))
    rules = [{"kind": "mult", "slack": "1.1", "unit_code": 1},
             {"kind": "add", "per_hop_ns": 250000, "unit_code": 1},
             {"kind": "quantile", "alpha": "0.01", "sigma_ns": 400000, "unit_code": 1}]
    (tmp_path / "rules.json").write_text(json.dumps(rules))
    for kind in ("t", "f"):
        assert cli.main(["eval", "scheme", "--config", str(tmp_path / f"{kind}.yaml"), "--out", str(tmp_path / kind)]) == 0
    assert cli.main(["eval", "score", str(tmp_path / "f"), "--twin", str(tmp_path / "t"),
                     "--rules", str(tmp_path / "rules.json"), "--flow", "0", "--include-null", "--check-plans",
                     "--k", "2", "--out", str(tmp_path / "score")]) == 0
    doc = json.loads((tmp_path / "score/summary.json").read_text())
    assert len(doc["detection"]) == 4
    for d in doc["detection"]:
        assert d["faults"][0]["packet"]["true_detections"] == 0
        assert d["faults"][0]["packet"]["exposed"] < 110
        assert d["faults"][0]["event"]["detected"] is False
        assert d["fpr"]["clean"] <= 300 and d["false_events_twin"]["hours"] == 3 / 3600
    assert doc["plan_checks"]["violations"] == 0
    assert cli.main(["eval", "roc", "--pairs", f"{tmp_path / 'f'}:{tmp_path / 't'}", "--rules", str(tmp_path / "rules.json"),
                     "--flow", "0", "--include-null", "--k", "2", "--out", str(tmp_path / "roc")]) == 0
    roc = json.loads((tmp_path / "roc/summary.json").read_text())
    assert len(roc["rows"]) == 3 and all(r["detected"] == 0 for r in roc["rows"])


def test_native_ls_event_roc_has_no_packet_fpr(tmp_path):
    from chronoroute.eval import detection
    from chronoroute.eval.load import load_run
    cfg = RUN + FAULT + "scheme: {name: ls_d, ls_d: {window_s: 0.2, inter_update_s: 1, probe_ms: 100}}\n"
    for kind, text in [("f", cfg), ("t", cfg.replace(FAULT, ""))]:
        (tmp_path / f"{kind}.yaml").write_text(text)
        assert cli.main(["eval", "scheme", "--config", str(tmp_path / f"{kind}.yaml"), "--out", str(tmp_path / kind)]) == 0
    fr, tw = load_run(tmp_path / "f"), load_run(tmp_path / "t")
    rows = detection.event_roc([(fr, tw)], None, [None], k=2, flow=0)
    assert rows[0]["clean_fpr"] is None and rows[0]["p_det_packet"] is None
    assert rows[0]["detected"] == int(detection.control_plane_detection(fr, tw, fr.faults[0])["detected"])

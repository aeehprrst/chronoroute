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

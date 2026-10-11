"""`cr run --config FILE --seed N --out DIR` through the real command line (chronoroute.cli)."""

import json

from chronoroute import cli, provenance
from chronoroute.fwd import command, config
from chronoroute.trace import reader

YAML = """
seed: 1
scenario:
  kind: walker
  preset: C1
  duration_s: 1
  drain_s: 1
  gsl: {min_elevation_deg: 10}
traffic:
  flows:
    - {src: London, dst: New York}
    - {src: Tokyo, dst: Los Angeles}
output:
  trace: full
  pcap: true
  pcap_max_packets: 3
"""


def test_cr_run_end_to_end(tmp_path, capsys):
    cfg = tmp_path / "run.yaml"
    cfg.write_text(YAML, encoding="utf-8")
    out = tmp_path / "out"
    code = cli.main(["run", "--config", str(cfg), "--seed", "5", "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "200 packets sent, 200 delivered" in text and "conservation ok" in text
    for f in ("run.json", "events.jsonl.gz", "packets.csv.gz", "schedule.csv.gz", "summary.json",
              "capture.pcap", "synthetic_omm.json", "manifest.json"):
        assert (out / f).is_file(), f
    m = provenance.validate_manifest(out / "manifest.json")
    assert m["seeds"] == [5] and m["config"]["seed"] == 5
    assert m["command"].startswith("cr run --config")
    assert reader.validate_run(out) == []
    s = json.loads((out / "summary.json").read_text())
    assert s["hop_events_per_s_forwarding"] > 0 and s["peak_rss_mb"] > 0
    # the end-to-end rate is printed and stored next to the forwarding-only one (it is lower:
    # it includes building the scenario, planning and writing)
    assert 0 < s["hop_events_per_s_end_to_end"] < s["hop_events_per_s_forwarding"]
    assert "hop events/s end to end" in text and "(forwarding only)" in text
    # quantiles: of delivered packets (nearest rank) and effective (lost = inf) are both there
    f0 = s["flows"][0]
    assert f0["latency_quantiles_of"].startswith("delivered packets only")
    assert f0["latency_eff_ns_p50"] == f0["latency_ns_p50"]           # nothing was lost here
    # run.json carries the full config, so the run can be repeated (fwd/rerun.py)
    run = json.loads((out / "run.json").read_text())
    assert config.normalise(run["engine"]["config"]) == run["engine"]["config"]
    assert run["engine"]["config"]["seed"] == 5 and run["engine"]["carrier_detect_ns"] == 0


def test_summary_quantiles_nearest_rank_and_effective():
    from chronoroute.fwd.engine import _nearest_rank
    lat = [10, 20, 30, 40]
    assert _nearest_rank(lat, 1, 2, 4) == 20                  # ceil(0.5 * 4) = 2nd
    assert _nearest_rank(lat, 99, 100, 4) == 40
    assert _nearest_rank(lat, 1, 2, 6) == 30                  # 6 sent, 2 lost: ceil(3) = 3rd
    assert _nearest_rank(lat, 99, 100, 6) == "inf"            # rank 6 > 4 delivered
    assert _nearest_rank([], 1, 2, 0) is None and _nearest_rank([], 1, 2, 3) == "inf"


def test_cr_run_reports_a_bad_config(tmp_path, capsys):
    cfg = tmp_path / "bad.json"
    cfg.write_text('{"forwarding": {"policy": "sideways"}}', encoding="utf-8")
    assert cli.main(["run", "--config", str(cfg), "--out", str(tmp_path / "o")]) == 2
    assert "forwarding.policy" in capsys.readouterr().err


def test_cr_run_can_record_scheme_accounting_for_offline_scoring(tmp_path):
    cfg = tmp_path / "scheme.yaml"
    cfg.write_text(YAML + "forwarding: {policy: continue}\nscheme: {name: chronoroute, outputs: {stretch_oracle: false}}\n")
    out = tmp_path / "out"
    assert cli.main(["run", "--scheme", "--config", str(cfg), "--out", str(out)]) == 0
    assert (out / "scheme_packets.csv.gz").is_file() and (out / "control.json").is_file()
    m = provenance.validate_manifest(out / "manifest.json")
    assert m["command"].startswith("cr run --scheme")
    assert m["config"]["scheme"]["outputs"]["stretch_oracle"] is False


def test_labels_come_from_the_shared_table_or_are_pending_modelled():
    from chronoroute import labels
    cfg = config.normalise({"forwarding": {"background": {"model": "fluid", "rho": 0.1},
                                           "jitter": {"model": "j1"}},
                            "faults": [{"kind": "arq", "link": [0, 1], "loss": 0.1, "start_s": 0, "stop_s": 1}]})
    got = command.run_labels(cfg)
    for k, v in got.items():
        if k in labels.TABLE:
            assert labels.TABLE[k] == v
        else:
            assert command.PENDING_LABELS[k] == v == "MODELLED"
    assert got["satellite_positions_sgp4"] == "REAL" and got["fault_slow_link"] == "MODELLED"

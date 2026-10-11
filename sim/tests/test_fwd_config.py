"""Run configuration: the YAML subset reader, defaults, and value checks (docs/sim-config.md)."""

import json

import pytest

from chronoroute.fwd import config
from chronoroute.fwd.config import ConfigError, loads_yaml_subset, normalise

YAML = """
# a comment
seed: 5
scenario:
  kind: walker          # trailing comment
  preset: C1
  duration_s: 2.5
  cities: [London, "New York", 'Sao Paulo']
traffic:
  flows:
    - src: London
      dst: New York
      rate_pps: 10
    - {src: "Sao Paulo", dst: London, send_times_ns: [1, 2, 3]}
forwarding:
  policy: continue
  background: {model: fluid, rho: 0.3}
  slow_queue_ns: null
faults:
- kind: rate_cut
  link: [1, 2]
  factor: "0.25"
  start_s: 1
  stop_s: 2
output:
  pcap: true
"""


def test_yaml_subset_parses_every_supported_form():
    doc = loads_yaml_subset(YAML)
    assert doc["seed"] == 5
    assert doc["scenario"] == {"kind": "walker", "preset": "C1", "duration_s": 2.5,
                               "cities": ["London", "New York", "Sao Paulo"]}
    assert doc["traffic"]["flows"][0] == {"src": "London", "dst": "New York", "rate_pps": 10}
    assert doc["traffic"]["flows"][1] == {"src": "Sao Paulo", "dst": "London", "send_times_ns": [1, 2, 3]}
    assert doc["forwarding"]["background"] == {"model": "fluid", "rho": 0.3}
    assert doc["forwarding"]["slow_queue_ns"] is None
    assert doc["faults"][0]["factor"] == "0.25" and doc["faults"][0]["link"] == [1, 2]
    assert doc["output"]["pcap"] is True


def test_yaml_and_json_give_the_same_config(tmp_path):
    y = tmp_path / "c.yaml"
    y.write_text(YAML, encoding="utf-8")
    j = tmp_path / "c.json"
    j.write_text(json.dumps(loads_yaml_subset(YAML)), encoding="utf-8")
    assert config.load_config(y) == config.load_config(j)


@pytest.mark.parametrize("text", ["a: &x 1", "a: !!int 1", "a: |\n  text", "a:\n\tb: 1", "a: 1\na: 2",
                                  "- 1\nb: 2", "a: [1, 2", "a: 'open"])
def test_unsupported_or_broken_yaml_is_refused(text):
    with pytest.raises(ConfigError):
        loads_yaml_subset(text)


def test_defaults_fill_everything_and_seed_overrides():
    cfg = normalise({}, seed=11)
    assert cfg["seed"] == 11
    assert cfg["scenario"]["kind"] == "real" and cfg["scenario"]["shell"] == "53.2deg-463km"
    assert cfg["traffic"]["flows"] == "science20" and cfg["traffic"]["rate_pps"] == 100
    assert cfg["forwarding"]["processing_ns"] == 500_000 and cfg["forwarding"]["link_rate_bps"] == 10**9
    assert cfg["forwarding"]["buffer_ms"] == 20 and cfg["schedule"]["refresh_ms"] == 1000
    assert cfg["forwarding"]["jitter"] == {"model": "none", "mean_ns": 400_000}


@pytest.mark.parametrize("doc,msg", [
    ({"scenario": {"kidn": "real"}}, "unknown setting"),
    ({"forwarding": {"policy": "sideways"}}, "forwarding.policy"),
    ({"forwarding": {"background": {"rho": 1.0}}}, "rho"),
    ({"scenario": {"duration_s": 0}}, "duration_s"),
    ({"scenario": {"duration_s": "1e-10"}}, "nanoseconds"),
    ({"schedule": {"refresh_ms": 150}}, "multiple"),
    ({"traffic": {"flows": [{"src": "London", "dst": "London"}]}}, "same city"),
    ({"traffic": {"flows": [{"src": "London", "dst": "Paris", "colour": 1}]}}, "unknown keys"),
    ({"traffic": {"flows": [{"src": "A", "dst": "B", "send_times_ns": [3, 2]}]}}, "increasing"),
    ({"faults": [{"kind": "link_down", "link": [1, 2], "start_s": 2, "stop_s": 1}]}, "after start"),
    ({"faults": [{"kind": "link_down", "start_s": 1, "stop_s": 2}]}, "exactly one target"),
    ({"faults": [{"kind": "rate_cut", "link": [1, 2], "factor": 0, "start_s": 1, "stop_s": 2}]}, "factor"),
    ({"faults": [{"kind": "arq", "link": [1, 2], "loss": 1, "start_s": 1, "stop_s": 2}]}, "loss"),
    ({"faults": [{"kind": "link_renewal", "unavailability": 0, "mttr_s": 1}]}, "unavailability"),
    ({"faults": [{"kind": "multiply_delay", "link": [1, 2]}]}, "kind"),
    ({"output": {"trace": "most"}}, "output.trace"),
])
def test_invalid_values_are_refused_with_a_clear_message(doc, msg):
    with pytest.raises(ConfigError, match=msg):
        normalise(doc)


def test_exact_number_reading():
    assert config.seconds_to_ns_exact(0.1, "x") == 100_000_000
    assert config.seconds_to_ns_exact("2.000000001", "x") == 2_000_000_001
    assert config.exact_fraction(0.3, "x").denominator == 10

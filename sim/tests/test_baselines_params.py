"""Scheme settings: defaults, cited presets, and that every mistake is an error (never ignored)."""

import pytest

from chronoroute.baselines import params
from chronoroute.baselines.run import split_run_document
from chronoroute.fwd.config import ConfigError


def test_bare_name_and_defaults():
    s = params.normalise_scheme("ls_h")
    assert s["name"] == "ls_h"
    # olsr_leo preset is the default: 1 s / 3 s, no MinLSInterval
    assert (s["ls"]["hello_s"], s["ls"]["dead_s"], s["ls"]["min_ls_interval_s"]) == ("1", "3", "0")
    assert s["ls"]["spf_delay_ms"] == 50                       # RFC 8405 INITIAL_SPF_DELAY
    assert s["ls_d"]["window_s"] == 30 and s["ls_d"]["inter_update_s"] == 120   # RFC 7471 section 7
    assert s["feedback"]["delay_ms"] == 50                     # master plan P3d


@pytest.mark.parametrize("preset,hello,dead,minls", [("olsr", "2", "6", "0"), ("ospf", "10", "40", "5"),
                                                      ("olsr_leo", "1", "3", "0")])
def test_cited_presets(preset, hello, dead, minls):
    s = params.normalise_scheme({"name": "ls_h", "ls": {"preset": preset}})
    assert (s["ls"]["hello_s"], s["ls"]["dead_s"], s["ls"]["min_ls_interval_s"]) == (hello, dead, minls)
    assert preset in params.LS_PRESETS and params.LS_PRESETS[preset][3]       # a source is written down


def test_preset_values_can_be_overridden_exactly():
    s = params.normalise_scheme({"name": "ls_h", "ls": {"preset": "ospf", "hello_s": 0.5, "dead_s": "1.5"}})
    assert (s["ls"]["hello_s"], s["ls"]["dead_s"]) == ("1/2", "3/2")
    assert params.to_ns(s["ls"]["dead_s"], params.S) == 1_500_000_000


@pytest.mark.parametrize("doc,msg", [
    ({"name": "ls_x"}, "scheme.name"),
    ({"name": "ls_h", "ls": {"hello": 1}}, "unknown setting"),
    ({"name": "ls_h", "typo": 1}, "unknown setting"),
    ({"name": "crh16", "feedback": {"mode": "fb1"}}, "chronoroute scheme only"),
    ({"name": "chronoroute", "feedback": {"penalty": 3}}, "penalty"),
    ({"name": "ls_h", "ls": {"hello_s": 3, "dead_s": 1}}, "dead_s must be >= hello_s"),
    ({"name": "ls_d", "ls_d": {"threshold": 20}}, "fraction"),
    ({"name": "ls_d", "ls_d": {"window_s": 1, "probe_ms": 2000}}, "probe_ms"),
    ({"name": "lq", "lq": {"action": "reroute"}}, "scheme.lq.action"),
    ({"name": "snap", "snap": {"update_s": 0}}, "> 0"),
    ({"name": "snap", "snap": {"count_uploads": "yes"}}, "true or false"),
])
def test_bad_settings_are_errors(doc, msg):
    with pytest.raises(ConfigError, match=msg):
        params.normalise_scheme(doc)


def test_run_document_split_keeps_engine_checks():
    eng, sch = split_run_document({"seed": 1, "scheme": {"name": "o_t"}})
    assert eng == {"seed": 1} and sch == {"name": "o_t"}
    eng, sch = split_run_document({"seed": 1})
    assert sch == "chronoroute"


def test_labels_are_short_and_distinct():
    a = params.scheme_label(params.normalise_scheme({"name": "ls_h", "ls": {"preset": "ospf", "bfd": True}}))
    b = params.scheme_label(params.normalise_scheme({"name": "ls_h"}))
    c = params.scheme_label(params.normalise_scheme({"name": "chronoroute", "feedback": {"mode": "fb1"}}))
    assert a == "ls_h[ospf+bfd]" and b == "ls_h[olsr_leo]" and c.startswith("chronoroute[fb1")
    assert params.DATA_PLANE.keys() == params.HEADER.keys() == set(params.SCHEMES)

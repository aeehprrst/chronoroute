"""Tests for pipeline/fetch_gate.py: when a refresh-data run asks CelesTrak again."""

import importlib.util
import json
from pathlib import Path

import pytest

from chronoroute.data import omm

REPO = Path(__file__).resolve().parents[2]
HOUR = 3600 * 10**9


def load_gate():
    spec = importlib.util.spec_from_file_location("pipeline_fetch_gate", REPO / "pipeline" / "fetch_gate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate()
T0 = omm.parse_epoch_ns("2026-10-20T20:01:54.110372")


def entry(outcome, status=None, detail=""):
    return {"source": "supgp", "url": "https://celestrak.org/x", "requested_utc": omm.format_utc_ns(T0),
            "outcome": outcome, "status": status, "detail": detail}


@pytest.mark.parametrize("outcome,status", [("downloaded", 200), ("not_modified", 403)])
def test_normal_answers_ask(outcome, status):
    assert gate.decide([entry(outcome, status)], T0 + HOUR)[0]


def test_empty_log_asks():
    assert gate.decide([], T0) == (True, "no earlier request logged")


@pytest.mark.parametrize("outcome,status", [("network_error", None), ("stopped", 500), ("stopped", 502),
                                            ("stopped", 503), ("stopped", 504)])
def test_server_side_problems_ask_at_the_next_run(outcome, status):
    ask, reason = gate.decide([entry(outcome, status)], T0 + 4 * HOUR)
    assert ask and "CelesTrak's side" in reason


@pytest.mark.parametrize("outcome,status", [("stopped", 429), ("stopped", 403), ("stopped", 404),
                                            ("stopped", 301), ("bad_response", 200), ("something_new", None)])
def test_other_answers_pause_24_hours_then_ask_once_more(outcome, status):
    log = [entry(outcome, status)]
    ask, reason = gate.decide(log, T0 + 23 * HOUR)
    assert not ask and "not asking again before 2026-10-21T20:01:54.110372Z" in reason
    assert gate.decide(log, T0 + 24 * HOUR)[0]
    assert gate.decide(log, T0 + HOUR, now=True)[0]


def test_only_the_newest_entry_counts():
    assert gate.decide([entry("stopped", 429), entry("downloaded", 200)], T0 + HOUR)[0]
    assert not gate.decide([entry("downloaded", 200), entry("stopped", 429)], T0 + HOUR)[0]


def test_unreadable_time_asks():
    bad = entry("stopped", 403)
    bad["requested_utc"] = "yesterday"
    ask, reason = gate.decide([bad], T0)
    assert ask and "cannot be read" in reason


def test_reason_names_the_answer():
    reason = gate.decide([entry("stopped", 403, "  Your IP\r\nis blocked  ")], T0 + HOUR)[1]
    assert "for supgp: stopped (HTTP 403): Your IP is blocked;" in reason


def write_log(root, *entries):
    root.mkdir(parents=True, exist_ok=True)
    (root / gate.LOG_NAME).write_text("".join(json.dumps(e) + "\n" for e in entries), encoding="utf-8")


def run_main(tmp_path, monkeypatch, *args):
    out = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    code = gate.main(["--out-root", str(tmp_path / "root"), *args])
    return code, out.read_text(encoding="utf-8")


def test_main_never_fails_and_writes_the_decision(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "utc_now_ns", lambda: T0 + HOUR)
    write_log(tmp_path / "root", entry("stopped", 429))
    assert run_main(tmp_path, monkeypatch) == (0, "fetch=false\n")
    assert "::notice title=CelesTrak not asked this run::" in capsys.readouterr().out
    assert run_main(tmp_path, monkeypatch, "--now") == (0, "fetch=false\nfetch=true\n")


def test_main_with_a_server_error_or_no_log_asks(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "utc_now_ns", lambda: T0 + HOUR)
    assert run_main(tmp_path, monkeypatch) == (0, "fetch=true\n")
    write_log(tmp_path / "root", entry("stopped", 500))
    assert run_main(tmp_path, monkeypatch)[1].endswith("fetch=true\n")


def test_main_with_an_unreadable_log_asks(tmp_path, monkeypatch):
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / gate.LOG_NAME).write_text("{not json\n", encoding="utf-8")
    assert run_main(tmp_path, monkeypatch) == (0, "fetch=true\n")

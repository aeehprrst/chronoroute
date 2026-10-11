"""chronoroute.trace/1 writer and reader (trace/writer.py, trace/reader.py, spec/trace-v1.md)."""

import gzip
import hashlib
import json

import pytest

from chronoroute.trace import reader, writer as tw


def run_doc(n_nodes=3, faults=()):
    nodes = [{"node_id": i, "kind": "sat", "sid": i + 1, "norad": 44000 + i, "name": f"S{i}",
              "lat": None, "lon": None} for i in range(n_nodes - 1)]
    nodes.append({"node_id": n_nodes - 1, "kind": "gs", "sid": 0xF000, "norad": None, "name": "City",
                  "lat": 1.5, "lon": -2.25})
    return tw.run_json(tool="python-sim", t0_utc="2026-10-10T14:00:00Z", t0_gps_ns=1475676018000000000,
                       unit_code=1, snapshot_id="x", bundle=None, nodes=nodes,
                       positions={"source": "snapshot", "path": "omm.json"}, faults=list(faults),
                       labels={"tcrh_header_bytes": "REAL"})


def write_run(tmp_path, events, doc=None):
    tw.write_json(tmp_path / "run.json", doc or run_doc())
    w = tw.EventWriter(tmp_path / "events.jsonl.gz")
    for e in events:
        w.event(*e)
    w.close()
    return tmp_path


def test_event_line_is_exact_json_with_fixed_key_order():
    line = tw.event_line(5, "hop", 1, 2, 3, 4, 5, 16, 100, 99, None, "ab")
    assert line == ('{"t":5,"ev":"hop","pkt":1,"flow":2,"node":3,"next":4,"sl":5,"flags":16,'
                    '"deadline_u":100,"now_u":99,"reason":null,"hex":"ab"}\n')
    assert tuple(json.loads(line)) == tw.EVENT_KEYS


def test_writer_reorders_events_known_ahead_and_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for d in (a, b):
        d.mkdir()
        w = tw.EventWriter(d / "events.jsonl.gz")
        w.event(10, "send", 0, 0, 2, 0)
        w.event(30, "drop", 0, 0, 0, reason="buffer_overflow")     # known at t=10, stamped 30
        w.advance(20)
        w.event(20, "send", 1, 0, 2, 0)
        w.advance(31)
        w.close()
    assert hashlib.sha256((a / "events.jsonl.gz").read_bytes()).digest() == \
        hashlib.sha256((b / "events.jsonl.gz").read_bytes()).digest()
    with gzip.open(a / "events.jsonl.gz", "rt") as fh:
        ts = [json.loads(x)["t"] for x in fh]
    assert ts == [10, 20, 30]
    raw = (a / "events.jsonl.gz").read_bytes()
    assert raw[4:8] == b"\x00\x00\x00\x00"                         # gzip mtime 0


def test_writer_refuses_to_write_out_of_order(tmp_path):
    w = tw.EventWriter(tmp_path / "e.jsonl.gz")
    w.event(10, "send", 5, 0, 0)
    w.advance(11)
    w.event(9, "send", 6, 0, 0)
    with pytest.raises(AssertionError):
        w.advance(12)


def test_packet_csv_rows_come_out_in_pkt_order(tmp_path):
    w = tw.PacketCsvWriter(tmp_path / "p.csv.gz")
    for pkt in (2, 0, 3, 1):
        w.row(pkt, f"{pkt}\n")
    w.close()
    with gzip.open(tmp_path / "p.csv.gz", "rt") as fh:
        lines = fh.read().splitlines()
    assert lines[0].startswith("pkt,flow") and lines[1:] == ["0", "1", "2", "3"]


GOOD = [(0, "send", 0, 0, 2, 0, 3, 16, None, 7), (5, "hop", 0, 0, 0, 1, 3, 16, 9, 8),
        (9, "hop", 0, 0, 1, 2, 2, 16, 12, 9), (12, "deliver", 0, 0, 2, None, 0, 16, 15, 10)]


def test_validate_accepts_a_good_run(tmp_path):
    assert reader.validate_run(write_run(tmp_path, GOOD)) == []
    assert [e["ev"] for e in reader.iter_events(tmp_path)] == ["send", "hop", "hop", "deliver"]
    assert list(reader.journeys(tmp_path)) == [0]


@pytest.mark.parametrize("events,problem", [
    (GOOD[1:], "before its send"),
    (GOOD + [(13, "hop", 0, 0, 1)], "after it ended"),
    ([GOOD[0], (0, "teleport", 0, 0, 1)], "unknown event"),
    ([GOOD[0], (1, "hop", 0, 0, 7)], "out of range"),
    ([GOOD[0], (1, "drop", 0, 0, 1)], "needs a reason"),
])
def test_validate_finds_broken_stories(tmp_path, events, problem):
    probs = reader.validate_run(write_run(tmp_path, events))
    assert any(problem in p for p in probs), probs


def test_validate_finds_unsorted_files(tmp_path):
    tw.write_json(tmp_path / "run.json", run_doc())
    raw, gz, fh = tw.open_gzip_text(tmp_path / "events.jsonl.gz")
    fh.write(tw.event_line(5, "send", 0, 0, 0))
    fh.write(tw.event_line(4, "send", 1, 0, 0))
    fh.close(); gz.close(); raw.close()
    assert any("not sorted" in p for p in reader.validate_run(tmp_path))


def test_validate_run_json():
    assert reader.validate_run_json(run_doc()) == []
    bad = run_doc()
    bad["nodes"][0]["node_id"] = 5
    bad["labels"] = {"x": "MAYBE"}
    bad["positions"] = {"source": "web"}
    probs = reader.validate_run_json(bad)
    assert len(probs) == 3
    f = run_doc(faults=[{"kind": "link_down", "link": [0, 1], "node": None, "start_ns": 5, "stop_ns": 5,
                         "params": {}}])
    assert any("start_ns < stop_ns" in p for p in reader.validate_run_json(f))


def test_compact_run_json_is_the_same_json(tmp_path):
    doc = run_doc(faults=[{"kind": "arq", "link": [0, 1], "node": None, "start_ns": 1, "stop_ns": 2,
                           "params": {"loss": "1/5"}}])
    doc["engine"] = {"seed": 3, "nested": {"a": [1, 2]}}
    tw.write_run_json(tmp_path / "run.json", doc)
    text = (tmp_path / "run.json").read_text(encoding="utf-8")
    assert json.loads(text) == doc
    assert sum(1 for line in text.splitlines() if line.startswith("  {\"node_id\"")) == len(doc["nodes"])
    empty = run_doc()
    tw.write_run_json(tmp_path / "r2.json", empty)
    assert json.loads((tmp_path / "r2.json").read_text(encoding="utf-8")) == empty

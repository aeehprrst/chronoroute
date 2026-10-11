"""Cross-check of the simulator v2 against the ns-3 course milestone
(results/course-milestone/c5-463-10s-small-seed1/nofault, docs/course-milestone.md).

The engine rebuilds the same scenario from the pinned snapshot with its own
pipeline (streaming topology, the bundle's stable planner, forwarding from the
header bytes): the real 53.2 deg / 463 km shell, Chennai / London / Singapore,
2026-10-10 14:00:00 UTC, 10 s, 1 s refresh, slack 1.5, unit 0.1 ms, the same
four flows and the same probe send times as ns-3 (read from ns-3's
packets.csv), 200-byte UDP payload, PPP framing, 1 Gb/s, policy continue, no
fault, no jitter, no background, and processing delay 0 (ns-3 forwards the
moment a packet arrives).

Required: for every one of the 4,000 probes the path, the outcome, DEV / Dev
Hop, and at every hop the arrival time (ns), the unit clock and the deadline
are identical; so the latency is identical to the nanosecond. The same holds
in the fault run (a rate cut that builds a queue), every hop's arrival time
in ns included.
"""

import csv
import gzip
from pathlib import Path

import pytest

from chronoroute.fwd import command, config
from chronoroute.trace import reader

REPO = Path(__file__).resolve().parents[2]
NS3_RUN = REPO / "results" / "course-milestone" / "c5-463-10s-small-seed1" / "nofault"
FLOWS = [("Chennai", "London"), ("Singapore", "London"), ("London", "Chennai"), ("London", "Singapore")]


def ns3_packets():
    with gzip.open(NS3_RUN / "packets.csv.gz", "rt", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    out = {}
    for r in rows:
        out[(int(r["flow_id"]), int(r["seq"]))] = r
    return out


@pytest.fixture(scope="module")
def engine_run(tmp_path_factory):
    ns3 = ns3_packets()
    sends = {f: [] for f in range(4)}
    for (f, seq), r in sorted(ns3.items()):
        sends[f].append(int(r["send_ns"]))
    doc = {
        "seed": 1,
        "scenario": {"kind": "real", "cities": ["Chennai", "London", "Singapore"],
                     "start_utc": "2026-10-10T14:00:00Z", "duration_s": 10, "drain_s": 1},
        "traffic": {"flows": [{"src": s, "dst": d, "send_times_ns": sends[i]} for i, (s, d) in enumerate(FLOWS)],
                    "payload_bytes": 200, "l2_overhead_bytes": 2},
        "forwarding": {"policy": "continue", "fallback": "none", "processing_ns": 0},
        "output": {"trace": "full", "invariants": "all", "packets_csv": True},
    }
    cfg = config.normalise(doc)
    out = tmp_path_factory.mktemp("ns3x")
    summary, _ = command.run_config(cfg, out, write_manifest=False)
    return ns3, out, summary


def engine_packets(out):
    with gzip.open(out / "packets.csv.gz", "rt", encoding="utf-8") as fh:
        return {(int(r["flow"]), int(r["seq"])): r for r in csv.DictReader(fh)}


def test_every_probe_identical_to_ns3(engine_run):
    ns3, out, summary = engine_run
    mine = engine_packets(out)
    assert summary["counts"]["sent"] == len(ns3) == 4000
    assert summary["invariants"]["violations"] == 0
    hop_times = {}
    for e in reader.iter_events(out):
        if e["ev"] == "hop":
            hop_times.setdefault(e["pkt"], []).append(e["t"])
    same = 0
    for key, n in ns3.items():
        m = mine[key]
        assert m["send_ns"] == n["send_ns"]
        assert m["path"] == n["taken_path"], key
        assert m["outcome"] == "delivered" and n["outcome"] == "delivered", key
        assert m["latency_ns"] == n["latency_ns"], (key, m["latency_ns"], n["latency_ns"])
        assert m["arrival_u"] == n["hop_now_u"], key
        assert m["deadline_u"] == n["hop_deadline_u"], key
        assert int(m["dev"]) == int(n["dev"]) and (m["dev_hop"] or "0") == n["dev_hop"], key
        assert " ".join(map(str, hop_times[int(m["pkt"])])) == n["hop_t_ns"], key
        same += 1
    assert same == 4000


def test_schedule_matches_the_bundle_paths(engine_run):
    """Each probe's planned path (the schedule row valid at send time) equals ns-3's planned path."""
    ns3, out, _ = engine_run
    with gzip.open(out / "schedule.csv.gz", "rt", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    by = {(int(r["flow_id"]), int(r["valid_from_ms"])): r for r in rows}
    for (f, seq), n in ns3.items():
        row = by[(f, int(n["row_from_ms"]))]
        assert row["path_nodes"] == n["planned_path"]


# ---------------------------------------------------------------------------- fault run
# ns-3 slowed ISL 4478 (STARLINK-35318 <-> STARLINK-35575, nodes 1998-2017) from
# 1 Gb/s to 200 kb/s in both directions for [4 s, 7 s); its queue builds because
# one probe flow offers 232 kb/s. Rate cut = the engine's rate_cut fault with
# factor 0.0002; the FIFO (Lindley) with the rate in force at transmission start
# is what ns-3's PointToPointNetDevice does. No probe is lost (the 100-packet
# DropTail queue never fills in 3 s; the engine's 2.5 MB buffer neither).
NS3_FAULT = REPO / "results" / "course-milestone" / "c5-463-10s-small-seed1" / "fault"


def test_fault_run_identical_to_ns3_including_queueing(tmp_path):
    with gzip.open(NS3_FAULT / "packets.csv.gz", "rt", encoding="utf-8") as fh:
        ns3 = {(int(r["flow_id"]), int(r["seq"])): r for r in csv.DictReader(fh)}
    sends = {f: [] for f in range(4)}
    for (f, seq), r in sorted(ns3.items()):
        sends[f].append(int(r["send_ns"]))
    doc = {
        "seed": 1,
        "scenario": {"kind": "real", "cities": ["Chennai", "London", "Singapore"],
                     "start_utc": "2026-10-10T14:00:00Z", "duration_s": 10, "drain_s": 2},
        "traffic": {"flows": [{"src": s, "dst": d, "send_times_ns": sends[i]} for i, (s, d) in enumerate(FLOWS)],
                    "payload_bytes": 200, "l2_overhead_bytes": 2},
        "forwarding": {"policy": "continue", "fallback": "none", "processing_ns": 0},
        "faults": [{"kind": "rate_cut", "link": [1998, 2017], "factor": "0.0002", "start_s": 4, "stop_s": 7}],
        "output": {"trace": "full", "invariants": "all"},
    }
    summary, _ = command.run_config(config.normalise(doc), tmp_path, write_manifest=False)
    mine = engine_packets(tmp_path)
    hop_times = {}
    for e in reader.iter_events(tmp_path):
        if e["ev"] == "hop":
            hop_times.setdefault(e["pkt"], []).append(e["t"])
    late_ns3 = sum(1 for r in ns3.values() if r["first_late_hop"])
    late_mine = sum(1 for r in mine.values() if r["first_late_hop"])
    assert late_ns3 == 598 and late_mine == 598
    queued = 0
    for key, n in ns3.items():
        m = mine[key]
        assert m["path"] == n["taken_path"], key
        assert m["outcome"] == "delivered" == n["outcome"], key
        assert m["latency_ns"] == n["latency_ns"], (key, m["latency_ns"], n["latency_ns"])
        assert m["arrival_u"] == n["hop_now_u"] and m["deadline_u"] == n["hop_deadline_u"], key
        assert m["first_late_hop"] == n["first_late_hop"], key
        assert int(m["dev"]) == int(n["dev"]) and (m["dev_hop"] or "0") == n["dev_hop"], key
        # every hop's arrival time, to the nanosecond, queueing behind the rate cut included
        assert " ".join(map(str, hop_times[int(m["pkt"])])) == n["hop_t_ns"], key
        queued += n["fault_link"] == "crossed"
    assert queued > 500                          # the comparison really covers the slowed link
    assert summary["faults_logged"] == 1 and summary["invariants"]["violations"] == 0

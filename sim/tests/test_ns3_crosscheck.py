"""
Tests for chronoroute.export.ns3_crosscheck and, when the ns-3 program is
built, for chronoroute-leo itself (ns3/contrib/chronoroute/examples).

A tiny synthetic bundle (4 satellites, 2 ground stations, 3 s) is written in
the documented format (docs/bundle-format.md) with every awkward case on
purpose:

    Alpha(4) -- s0 -- s1 -- s2 -- Beta(5)        rows [0,1) s and [1,2) s
    Alpha(4) -- s3 -- s2 -- Beta(5)              row  [2,3) s
    (flow 1 is the reverse direction)

  * link Alpha-s0 is DOWN in [800, 900) ms: flow 0 is dropped at the ingress,
    flow 1 at s0 (the node holding it finds its next link down);
  * link s2-Beta is DOWN in [1500, 2000) ms and 15 ms long: flow 0 probes
    that left s2 in the last 15 ms before 1500 ms are lost in flight;
    later ones are dropped at s2; flow 1 is dropped at its ingress;
  * the delays change every 100 ms step, and one laser link has no position
    (-1) for a step;
  * the schedule switches paths at 2 s.

The pure-Python tests check the replay against hand-computed numbers. The
integration tests run the ns-3 program on the same bundle and require that
ns-3 and Python agree on every probe, to the nanosecond.
"""

import csv
import glob
import gzip
import json
import math
import os
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path

import pytest

from chronoroute.export import ns3_crosscheck as cc
from chronoroute.proto import sizes, tcrh, timebase
from chronoroute.trace import pcap as pcapw

REPO = Path(__file__).resolve().parents[2]
T0_UNIX_NS = 1791640800000000000     # 2026-10-10T14:00:00Z
T0_GPS_NS = 1475676018000000000      # the same instant on GPS time (UTC + 18 s)
STEP_MS = 100
WINDOW_MS = 3000
N_STEPS = WINDOW_MS // STEP_MS + 1
MS = 1_000_000

SATS = [(0, 101, "90001", "SAT-A"), (1, 102, "90002", "SAT-B"), (2, 103, "90003", "SAT-C"),
        (3, 104, "100004", "SAT-D")]
GS = [(4, 61440, "Alpha", "10.0", "20.0"), (5, 61441, "Beta", "40.0", "60.0")]
SID = {n: s for n, s, *_ in SATS + GS}
ISL = [(0, 1, "intra"), (1, 2, "intra"), (0, 3, "cross"), (2, 3, "cross")]
GSL = [(4, 0), (4, 3), (5, 2), (5, 3)]


def isl_state(link, s):
    """(up, delay_ns) of laser link `link` at step s."""
    if link == 0:
        return 1, 3_000_000 + 1_000 * s
    if link == 1:
        return 1, 2_500_000 - 700 * s
    if link == 2:
        return (0, -1) if s == 11 else (0 if 10 <= s <= 12 else 1, 4_000_000 + 3 * s)
    return 1, 2_000_000


def gsl_state(pair, s):
    """(up, delay_ns) of ground-link pair index `pair` at step s."""
    if pair == 0:
        return (0 if s == 8 else 1), 2_000_000 + 500 * s
    if pair == 1:
        return 1, 2_200_000
    if pair == 2:
        return (0 if 15 <= s <= 19 else 1), 15_000_000
    return 0, 2_100_000


def delay_between(u, v, s):
    for i, (a, b, _k) in enumerate(ISL):
        if {a, b} == {u, v}:
            return isl_state(i, s)
    for i, (g, sat) in enumerate(GSL):
        if {g, sat} == {u, v}:
            return gsl_state(i, s)
    raise KeyError((u, v))


def schedule_rows():
    """(flow, from_ms, to_ms, path) of the synthetic schedule."""
    rows = []
    for frm in (0, 1000, 2000):
        fwd = (4, 0, 1, 2, 5) if frm < 2000 else (4, 3, 2, 5)
        rows.append((0, frm, frm + 1000, fwd))
        rows.append((1, frm, frm + 1000, tuple(reversed(fwd))))
    return rows


def write_synthetic_bundle(d):
    d = Path(d)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "nodes.csv", "w", newline="\n") as fh:
        fh.write("node_id,kind,sid,norad,name,shell,plane,slot,lat,lon\n")
        for n, sid, norad, name in SATS:
            fh.write(f"{n},sat,{sid},{norad},{name},test-shell,0,{n},,\n")
        for n, sid, name, lat, lon in GS:
            fh.write(f"{n},gs,{sid},,{name},,,,{lat},{lon}\n")
    with open(d / "isl.csv", "w", newline="\n") as fh:
        fh.write("link_id,a,b,kind\n")
        for i, (a, b, k) in enumerate(ISL):
            fh.write(f"{i},{a},{b},{k}\n")
    with open(d / "isl_delay.csv", "w", newline="\n") as fh:
        fh.write("t_ms,link_id,up,delay_ns\n")
        for s in range(N_STEPS):
            for i in range(len(ISL)):
                up, dl = isl_state(i, s)
                fh.write(f"{s * STEP_MS},{i},{up},{dl}\n")
    with open(d / "gsl.csv", "w", newline="\n") as fh:
        fh.write("t_ms,gs_node,sat_node,up,delay_ns,elev_mdeg\n")
        for s in range(N_STEPS):
            for i, (g, sat) in enumerate(GSL):
                up, dl = gsl_state(i, s)
                fh.write(f"{s * STEP_MS},{g},{sat},{up},{dl},{40000 if up else 20000}\n")
    with open(d / "positions.csv", "w", newline="\n") as fh:
        fh.write("t_ms,node_id,x_m,y_m,z_m\n")
        for ps in range(WINDOW_MS // 1000 + 1):
            for n in range(6):
                lon = math.radians(20 + 10 * n + ps)
                r = 6_800_000.0 if n < 4 else 6_371_000.0
                fh.write(f"{ps * 1000},{n},{r * math.cos(lon):.3f},{r * math.sin(lon):.3f},{1000.0 * n:.3f}\n")
    with open(d / "schedule.csv", "w", newline="\n") as fh:
        fh.write("flow_id,src_gs,dst_gs,valid_from_ms,valid_to_ms,sids_fwd,cumulative_budgets_ns,"
                 "predicted_hop_delays_ns,tcrh_hex_template,path_nodes\n")
        for flow, frm, to, path in sorted(schedule_rows(), key=lambda r: (r[1], r[0])):
            s = frm // STEP_MS
            pred = [delay_between(u, v, s)[1] + 500_000 for u, v in zip(path, path[1:])]
            budgets, run = [], 0
            for p in pred:
                run += p
                budgets.append(math.ceil(Fraction(3, 2) * run))
            sids = [SID[n] for n in path[1:]]
            hexs = tcrh.build_header(sids, budgets, 0, 1).encode().hex()
            fh.write(f"{flow},{path[0]},{path[-1]},{frm},{to},{' '.join(map(str, sids))},"
                     f"{' '.join(map(str, budgets))},{' '.join(map(str, pred))},{hexs},"
                     f"{' '.join(map(str, path))}\n")
    scenario = {
        "schema": "chronoroute.bundle/1",
        "time": {"t0_utc": "2026-10-10T14:00:00Z", "t0_unix_ns": T0_UNIX_NS, "t0_gps_ns": T0_GPS_NS,
                 "window_ms": WINDOW_MS, "step_ms": STEP_MS, "position_step_ms": 1000,
                 "schedule_refresh_ms": 1000},
        "tcrh": {"spec": "tcrh-v1", "unit_code": 1, "unit_ns": 100000, "slack": "3/2"},
        "note": "synthetic test bundle (tests/test_ns3_crosscheck.py), not real data",
    }
    (d / "scenario.json").write_text(json.dumps(scenario, indent=1) + "\n")
    return d


@pytest.fixture(scope="module")
def bundle_dir(tmp_path_factory):
    return write_synthetic_bundle(tmp_path_factory.mktemp("bundle"))


@pytest.fixture(scope="module")
def rb(bundle_dir):
    return cc.load_replay_bundle(bundle_dir)


# ======================================================================= pure Python

def test_tx_time_matches_ns3_rounding():
    assert cc.tx_time_ns(298, 10**9) == 2384                 # 8 ns per byte at 1 Gb/s
    assert cc.tx_time_ns(298, 200_000) == 11_920_000         # the fault rate
    assert cc.tx_time_ns(1, 3) == 2_666_666_667              # 2666666666.67 rounds to nearest


def test_wire_bytes_counts_ppp_ipv6_tcrh_udp_payload():
    # the ns-3 run printed 290 B for 8 hops and 298 B for 12 hops
    assert cc.wire_bytes(8) == 2 + 40 + sizes.tcrh_size(8) + 8 + 200 == 290
    assert cc.wire_bytes(12) == 298


def test_bundle_loads_and_holds_missing_delay(rb):
    assert rb.n_steps == N_STEPS and rb.n_sats == 4
    assert rb.isl_delay_raw[11, 2] == -1
    assert rb.isl_delay[11, 2] == rb.isl_delay[10, 2] == 4_000_030   # held, as ns-3 keeps it
    assert rb.link(0, 4, 8) == (False, 2_004_000, 2_004_000)
    # every hop budget fits one Delta byte (<= 25.5 ms at 0.1 ms units): no SAT
    # flag, otherwise on-time probes would look late
    assert all(int(r.template_hex[8:10], 16) & tcrh.FLAG_SAT == 0 for r in rb.schedule)


def test_row_and_step_boundaries(rb):
    assert rb.row_at(0, 999_999_999).from_ms == 0
    assert rb.row_at(0, 1_000_000_000).from_ms == 1000        # [from, to)
    assert rb.row_at(0, 3_000_000_000) is None                # after the last row: a gap
    assert rb.step_at(1_499_999_999) == 14
    assert rb.step_at(1_500_000_000) == 15                    # the new state at the tie instant
    assert rb.step_at(10**12) == N_STEPS - 1                  # clamped to the last row


def _hand_walk(path, send_ns, h):
    """Arrival times by hand: transmit at arrival, serialization, then the held delay."""
    ser = 8 * cc.wire_bytes(h)
    t, out = send_ns, []
    for u, v in zip(path, path[1:]):
        t = t + ser + delay_between(u, v, t // (STEP_MS * MS))[1]
        out.append(t)
    return out


def test_on_time_probe_matches_hand_computation(rb):
    send = 10 * MS + 123
    pr = cc.predict_probe(rb, 0, send)
    assert pr.outcome == "delivered" and pr.taken == [4, 0, 1, 2, 5]
    assert pr.hop_t_ns == _hand_walk((4, 0, 1, 2, 5), send, 4)
    assert pr.latency_ns == pr.hop_t_ns[-1] - send
    hdr = tcrh.build_header([101, 102, 103, 61441], rb.row_at(0, send).budgets, T0_GPS_NS + send, 1)
    assert pr.epoch_base == hdr.epoch_base == timebase.epoch_base_at_ingress(T0_GPS_NS + send, 1)
    assert pr.hop_deadline_u == list(hdr.deadlines())
    assert pr.hop_now_u == [timebase.clock_u(T0_GPS_NS + t, 1) for t in pr.hop_t_ns]
    assert pr.first_late_hop is None and pr.dev == 0
    assert pr.prop_ns + 4 * 8 * cc.wire_bytes(4) == pr.latency_ns


def test_ingress_link_down(rb):
    pr = cc.predict_probe(rb, 0, 850 * MS)
    assert (pr.outcome, pr.outcome_node, pr.link_down_hop, pr.taken) == ("drop_link_down", 4, 0, [4])
    # spec 6 step 7 at the ingress: DEV with Dev Hop 0 before the discard
    assert (pr.dev, pr.dev_hop) == (1, 0)


def test_transit_link_down_sets_dev_at_that_hop(rb):
    pr = cc.predict_probe(rb, 0, 1600 * MS)
    assert (pr.outcome, pr.outcome_node, pr.link_down_hop) == ("drop_link_down", 2, 3)
    assert pr.taken == [4, 0, 1, 2] and (pr.dev, pr.dev_hop) == (1, 3)


def test_in_flight_loss_when_link_goes_down(rb):
    # leaves s2 at about 1492.5 ms, needs 15 ms on s2-Beta, which goes down at 1500 ms
    pr = cc.predict_probe(rb, 0, 1485 * MS)
    assert (pr.outcome, pr.outcome_node, pr.taken) == ("drop_iface_down", 5, [4, 0, 1, 2])
    # 45 ms earlier it lands before 1500 ms
    assert cc.predict_probe(rb, 0, 1440 * MS).outcome == "delivered"


def test_schedule_switch_changes_the_path(rb):
    assert cc.predict_probe(rb, 0, 2000 * MS).taken == [4, 3, 2, 5]
    assert cc.predict_probe(rb, 1, 1999 * MS).outcome == "drop_link_down"   # ingress Beta-s2 down
    assert cc.predict_probe(rb, 1, 2000 * MS).taken == [5, 2, 3, 4]


def _pkt(flow, seq, send, outcome="delivered", dev=0, late=None, fault_link="", fault_t=None, lat=50 * MS):
    return {"flow_id": flow, "seq": seq, "send_ns": send, "outcome": outcome, "dev": dev,
            "first_late_hop": late, "fault_link": fault_link, "fault_link_t_ns": fault_t,
            "latency_ns": lat if outcome == "delivered" else None,
            "hop_t_ns": [send + MS, send + 2 * MS, send + 3 * MS], "hop_margin_u": [10, -5, 20]}


def test_margin_summary_counts_only_on_time_delivered_probes():
    def p(margins, outcome="delivered", dev=0):
        return {"outcome": outcome, "dev": dev, "hop_margin_u": margins}
    pk = [p([16, 30, 174]), p([18, 40, 564]), p([20, 17, 361]),       # on time
          p([5, -3, -10], dev=1),                                     # late: left out
          p([9], outcome="drop_link_down")]                           # not delivered: left out
    m = cc.margin_summary(pk, 100_000)
    assert m["probes"] == 3
    assert (m["final_hop_margin_units"]["min"], m["final_hop_margin_units"]["max"]) == (174, 564)
    assert m["final_hop_margin_units"]["p50"] == 361
    assert (m["min_hop_margin_units"]["min"], m["min_hop_margin_units"]["max"]) == (16, 18)
    assert m["min_hop_margin_ms"]["min"] == 1.6 and m["final_hop_margin_ms"]["max"] == 56.4
    assert m["hop_of_min_margin"] == {"1": 2, "2": 1}


def test_flow_summary_phases_and_flags():
    start, stop = 10 * MS, 20 * MS
    pk = [_pkt(0, 0, 1 * MS), _pkt(0, 1, 12 * MS, dev=1, late=2), _pkt(0, 2, 15 * MS),
          _pkt(0, 3, 16 * MS, outcome="drop_queue"), _pkt(0, 4, 25 * MS, lat=70 * MS)]
    (row,) = cc.flow_summary(pk, {0: ("A", "B")}, start, stop, "fault")
    assert (row["sent"], row["delivered"], row["drop_queue"]) == (5, 4, 1)
    assert row["pdr"] == 0.8
    assert (row["delivered_before"], row["delivered_during"], row["delivered_after"]) == (1, 2, 1)
    assert (row["flagged_frac_before"], row["flagged_frac_during"], row["flagged_frac_after"]) == (0.0, 0.5, 0.0)
    assert row["latency_p50_ms"] == 50.0 and row["latency_max_ms"] == 70.0


def test_detection_pairs_the_same_probes():
    start, stop = 10 * MS, 20 * MS
    fault = [_pkt(0, 1, 11 * MS, dev=1, late=2, fault_link="crossed", fault_t=12 * MS),
             _pkt(0, 2, 13 * MS, fault_link="crossed", fault_t=14 * MS),
             _pkt(0, 3, 15 * MS, outcome="drop_queue", fault_link="queue_drop", fault_t=16 * MS),
             _pkt(0, 4, 30 * MS, fault_link="crossed", fault_t=31 * MS)]          # after the fault
    nofault = [_pkt(0, 1, 11 * MS, fault_link="crossed", fault_t=12 * MS),
               _pkt(0, 2, 13 * MS, fault_link="crossed", fault_t=14 * MS),
               _pkt(0, 3, 15 * MS, fault_link="crossed", fault_t=16 * MS)]
    det = cc.detection(fault, nofault, start, stop)
    assert det["probes_crossing_slowed_link"] == 2 and det["flagged_late"] == 1
    assert det["detection_rate"] == 0.5
    assert det["probes_lost_in_its_queue"] == 1
    assert det["baseline_same_probes_no_fault"] == 2 and det["baseline_false_alarm_rate"] == 0.0
    assert det["first_detection_after_fault_start_ms"] == (11 * MS + 2 * MS - start) / MS


def test_pcap_reader_parses_a_ppp_probe_frame(tmp_path):
    hdr = tcrh.build_header([101, 102, 61441], [3 * MS, 6 * MS, 9 * MS], T0_GPS_NS + 5 * MS, 1)
    raw, _first = tcrh.ingress_send(hdr.encode())
    payload = b"CRT1" + (1_000_007).to_bytes(4, "big") + (T0_GPS_NS).to_bytes(8, "big") + bytes(184)
    pkt = pcapw.packet_with_routing_header(raw, src=pcapw.sid_address(61440), dst=pcapw.sid_address(101),
                                           final_dst=pcapw.sid_address(61441), payload=payload)
    path = pcapw.write_pcap(tmp_path / "x.pcap", [pcapw.Frame(T0_GPS_NS + 5 * MS, pkt)], pcapw.LINKTYPE_PPP)
    linktype, nano, frames = cc.read_pcap(path)
    assert (linktype, nano, len(frames)) == (9, True, 1)
    assert frames[0][0] == T0_UNIX_NS + 5 * MS            # pcap time = GPS - 18 s = UTC
    f = cc.parse_probe_frame(frames[0][1], linktype)
    assert (f["sl"], f["num_hops"], f["pid"], f["epoch_base"]) == (2, 3, 1_000_007, hdr.epoch_base)
    gz = tmp_path / "x.pcap.gz"
    gz.write_bytes(gzip.compress(path.read_bytes()))
    assert cc.read_pcap(gz)[2] == frames


# ======================================================================= ns-3 (integration)

def _binary():
    ns3 = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3-dev"))
    found = sorted(glob.glob(str(ns3 / "build/contrib/chronoroute/examples/ns3.*-chronoroute-leo-*")))
    return found[-1] if found else None


needs_ns3 = pytest.mark.skipif(_binary() is None, reason="chronoroute-leo is not built (make ns3-test)")
FAULT_ARGS = ["--faultStartMs=200", "--faultDurationMs=500"]


def _run(bundle_dir, out, *extra):
    out.mkdir(parents=True, exist_ok=True)
    cmd = [_binary(), f"--bundle={bundle_dir}", f"--outDir={out}", *FAULT_ARGS, *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return proc


@pytest.fixture(scope="module")
def ns3_runs(bundle_dir, tmp_path_factory):
    if _binary() is None:
        pytest.skip("chronoroute-leo is not built")
    base = tmp_path_factory.mktemp("ns3")
    out = {}
    for label, extra in (("nofault", []), ("fault", ["--fault=1", "--faultRate=100kbps"])):
        proc = _run(bundle_dir, base / label, *extra)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        out[label] = {"dir": base / label, "stdout": proc.stdout,
                      "packets": cc.read_packets(base / label / "packets.csv"),
                      "info": json.loads((base / label / "run_info.json").read_text())}
    return out


@needs_ns3
def test_ns3_and_python_agree_on_every_probe(rb, ns3_runs):
    pk = ns3_runs["nofault"]["packets"]
    res = cc.crosscheck(rb, pk)
    assert res["probes_compared"] == len(pk) == 2 * 300
    assert res["path_identical"] == res["outcome_identical"] == len(pk)
    assert res["per_hop_time_clock_deadline_identical"] == len(pk)
    assert res["first_late_hop_identical"] == res["link_down_hop_identical"] == len(pk)
    assert res["dev_and_dev_hop_identical_delivered"] == res["delivered_by_both"]
    # DEV / Dev Hop agree for EVERY probe, the ingress link-down drops included
    assert res["dev_and_dev_hop_identical"] == len(pk)
    assert res["ingress_link_down_drops"] > 0
    # no queueing in this run, so ns-3 latency = light time + serialization exactly
    assert res["residual_zero"] == res["delivered_by_both"] > 0
    # every awkward case actually happened (otherwise the test proves little)
    outcomes = {p["outcome"] for p in pk}
    assert outcomes == {"delivered", "drop_link_down", "drop_iface_down"}
    assert {p["link_down_hop"] for p in pk if p["outcome"] == "drop_link_down"} == {0, 3}


@needs_ns3
def test_ns3_link_down_semantics(ns3_runs):
    pk = {(p["flow_id"], p["seq"]): p for p in ns3_runs["nofault"]["packets"]}
    by_send = sorted(ns3_runs["nofault"]["packets"], key=lambda p: p["send_ns"])
    # flow 0 sent while Alpha-s0 is down: dropped at the ingress with DEV and Dev Hop 0 (spec 6 step 7)
    ingress = [p for p in by_send if p["flow_id"] == 0 and 800 * MS <= p["send_ns"] < 900 * MS]
    assert ingress and all(p["outcome"] == "drop_link_down" and p["outcome_node"] == 4
                           and p["taken_path"] == [4] and (p["dev"], p["dev_hop"]) == (1, 0)
                           for p in ingress)
    # flow 0 at s2 while s2-Beta is down: dropped at s2 with DEV and Dev Hop 3 (spec 6 step 7)
    transit = [p for p in by_send if p["flow_id"] == 0 and p["outcome"] == "drop_link_down"
               and p["outcome_node"] == 2]
    assert transit and all(p["dev"] == 1 and p["dev_hop"] == 3 for p in transit)
    # in flight when a link goes down (Alpha-s0 at 800 ms, s2-Beta at 1500 ms):
    # lost at the receiving end, and only probes that left less than one
    # link delay (+ serialization) before the instant
    flight = [p for p in by_send if p["outcome"] == "drop_iface_down"]
    assert {p["outcome_node"] for p in flight} == {0, 4, 2, 5}
    for p in flight:
        left = (p["hop_t_ns"] or [p["send_ns"]])[-1]
        down_at, longest = (800 * MS, 2_100_000) if p["outcome_node"] in (0, 4) else (1500 * MS, 15_010_000)
        assert down_at - longest < left < down_at
    assert len(pk) == 600


@needs_ns3
def test_effective_policy_is_recorded_and_greedy_without_fallback_warns(bundle_dir, ns3_runs, tmp_path):
    for label in ("nofault", "fault"):
        info = ns3_runs[label]["info"]
        assert (info["policy"], info["effective_policy"]) == ("continue", "continue")
        assert "WARNING" not in ns3_runs[label]["stdout"]
    # chronoroute-leo installs no fallback function: "greedy" must not pass for greedy
    proc = _run(bundle_dir, tmp_path / "greedy", "--fault=1", "--faultRate=100kbps", "--policy=greedy")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    info = json.loads((tmp_path / "greedy" / "run_info.json").read_text())
    assert info["policy"] == "greedy"
    assert info["effective_policy"] == "continue (greedy set, no fallback installed)"
    warnings = [line for line in (proc.stdout + proc.stderr).splitlines()
                if "policy greedy but no fallback function installed" in line]
    # printed, but only ONCE per node (each node that forwarded a DEV packet)
    nodes = [line.split("T-CRH node ")[1].split(":")[0] for line in warnings]
    assert warnings and len(nodes) == len(set(nodes)), warnings
    assert info["outcomes"]["delivered"] > 0 and info["late_packets"] > 0


@needs_ns3
def test_drop_causes_name_the_dead_links(rb, ns3_runs):
    causes = cc.drop_causes(rb, ns3_runs["nofault"]["packets"])
    # flow 0's uplink Alpha-s0 and downlink s2-Beta, flow 1's mirror images; never a laser link
    assert set(causes) == {"drop_link_down/gsl-up", "drop_link_down/gsl-down",
                           "drop_iface_down/gsl-up", "drop_iface_down/gsl-down"}
    pk = ns3_runs["nofault"]["packets"]
    assert sum(causes.values()) == sum(p["outcome"] in ("drop_link_down", "drop_iface_down") for p in pk)


@needs_ns3
def test_ns3_fault_is_detected_at_the_far_end(ns3_runs):
    info = ns3_runs["fault"]["info"]
    assert info["all_checks_ok"] and info["fault"]["isl_id"] == 0      # Alpha's first laser link s0-s1
    log = list(csv.DictReader(open(ns3_runs["fault"]["dir"] / "fault_log.csv")))
    assert [(r["t_ns"], r["event"], r["data_rate_bps"]) for r in log] == [
        (str(200 * MS), "slow_start", "100000"), (str(700 * MS), "slow_end", "1000000000")]
    det = cc.detection(ns3_runs["fault"]["packets"], ns3_runs["nofault"]["packets"], 200 * MS, 700 * MS)
    assert det["probes_crossing_slowed_link"] > 0
    assert det["detection_rate"] == 1.0 and det["baseline_false_alarm_rate"] == 0.0
    assert det["false_alarms_no_fault_run_all_probes"] == 0
    # flow 0 crosses s0 -> s1 (hop 2), flow 1 crosses s1 -> s0 (hop 3)
    hops = {(p["flow_id"], p["first_late_hop"]) for p in ns3_runs["fault"]["packets"]
            if p["first_late_hop"] is not None}
    assert hops == {(0, 2), (1, 3)}


@needs_ns3
def test_fault_run_matches_python_away_from_the_slowed_link(rb, ns3_runs):
    res = cc.crosscheck(rb, ns3_runs["fault"]["packets"],
                        exclude=lambda p: p["fault_link"] != "" and 200 * MS <= (p["fault_link_t_ns"] or -1) < 900 * MS)
    assert res["probes_compared"] > 0
    assert res["path_identical"] == res["outcome_identical"] == res["probes_compared"]


@needs_ns3
@pytest.mark.skipif(shutil.which("tshark") is None, reason="tshark not installed")
def test_ns3_capture_passes_check_pcap(rb, ns3_runs):
    for label, want_dev in (("nofault", False), ("fault", True)):
        pcap = ns3_runs[label]["dir"] / "capture.pcap"
        code, summ, text = cc.run_check_pcap(REPO, pcap)
        assert code == 0, text
        assert summ["invalid"] == 0 and summ["T-CRH frames"] > 0
        assert (summ["with DEV"] > 0) == want_dev
        sem = cc.pcap_semantics(pcap, T0_UNIX_NS, 200 * MS, 700 * MS)
        assert sem["non_probe_frames"] == 0
        assert sem["probes_with_sl_not_strictly_decreasing"] == 0 and sem["probes_seen_at_2plus_nodes"] > 0
        assert sem["dev_frames_outside_fault_window"] == 0


@needs_ns3
def test_ns3_is_deterministic(bundle_dir, ns3_runs, tmp_path):
    proc = _run(bundle_dir, tmp_path / "again")
    assert proc.returncode == 0
    assert (tmp_path / "again" / "packets.csv").read_bytes() == \
        (ns3_runs["nofault"]["dir"] / "packets.csv").read_bytes()
    assert (tmp_path / "again" / "capture.pcap").read_bytes() == \
        (ns3_runs["nofault"]["dir"] / "capture.pcap").read_bytes()


@needs_ns3
def test_ns3_anim_slice(bundle_dir, tmp_path):
    proc = _run(bundle_dir, tmp_path / "anim", "--fault=1", "--faultRate=100kbps", "--anim=1",
                "--animMaxSats=3", "--pcap=0", "--animFromMs=0", "--animToMs=1000")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    xml = (tmp_path / "anim" / "anim.xml").read_text()
    assert xml.count("<node ") == 5                       # 3 satellites + 2 stations
    assert "<link " in xml and "ns3::TcrhHeader (T-CRH(" in xml
    assert "DEGRADED 100000 b/s (still UP)" in xml


@needs_ns3
def test_ns3_rejects_a_bundle_whose_template_disagrees(bundle_dir, tmp_path):
    bad = tmp_path / "bad"
    shutil.copytree(bundle_dir, bad)
    sched = (bad / "schedule.csv").read_text().splitlines()
    fields = sched[1].split(",")
    fields[8] = fields[8][:-2] + ("00" if fields[8][-2:] != "00" else "01")
    sched[1] = ",".join(fields)
    (bad / "schedule.csv").write_text("\n".join(sched) + "\n")
    proc = _run(bad, tmp_path / "out")
    assert proc.returncode != 0
    assert "C++ TcrhHeader::Build gives" in proc.stdout + proc.stderr

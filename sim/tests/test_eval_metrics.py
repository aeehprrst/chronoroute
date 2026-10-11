"""Metric definitions (master plan 5.3) on a HAND-MADE run folder whose answers are known:
PDR with loss reasons and the sending window, nearest-rank and effective quantiles (lost =
inf) with the tail rule, the stretch check and its tolerance, fault exposure in both link
directions, packet labels and clean FPR, blackhole time and time-to-mitigation."""

import gzip
import json
import math

import numpy as np
import pytest

from chronoroute.baselines.engine import EXTRAS_COLUMNS
from chronoroute.baselines.run import ExtrasWriter
from chronoroute.eval import load, metrics
from chronoroute.trace.writer import PacketCsvWriter

MS = 1_000_000
FAULT = {"kind": "slow_processing", "link": [3, 4], "node": None, "start_ns": 500 * MS, "stop_ns": 800 * MS,
         "params": {}}

# pkt: flow, send_ms, outcome, reason, latency_ms, path, arrivals_ms, first_late, (l_det, oracle, tol, ok)
PACKETS = [
    (0, 100, "delivered", "", 30, [10, 3, 4, 11], [110, 120, 130], 2, (100, 100, 0, 1)),
    (0, 500, "delivered", "", 31, [10, 3, 4, 11], [510, 520, 530], 2, (99, 100, 0, 1)),
    (0, 600, "delivered", "", 32, [10, 4, 3, 11], [610, 620, 630], -1, (99, 100, 5, 1)),
    (0, 620, "dropped", "in_flight_link_down", None, [10, 3, 4], [630, 640], -1, None),
    (0, 700, "delivered", "", 20, [10, 5, 6, 11], [710, 715, 720], -1, (90, 100, 0, 0)),
    (0, 750, "delivered", "", 21, [10, 5, 6, 11], [760, 765, 771], -1, (100, 100, 0, 1)),
    (0, 790, "delivered", "", 33, [10, 3, 4, 11], [800, 810, 823], -1, (100, 100, 0, 1)),
    (0, 850, "no_route", "no_route", None, [10], [], -1, None),
    (0, 900, "delivered", "", 22, [10, 5, 6, 11], [910, 915, 922], -1, (100, 100, 0, 1)),
    (0, 1200, "delivered", "", 22, [10, 5, 6, 11], [1210, 1215, 1222], -1, (100, 100, 0, 1)),
    (1, 150, "delivered", "", 25, [12, 7, 13], [160, 175], -1, (100, 100, 0, 1)),
    (1, 650, "delivered", "", 25, [12, 7, 13], [660, 675], -1, (100, 100, 0, 1)),
]


def make_run(d):
    d.mkdir(parents=True, exist_ok=True)
    order = sorted(range(len(PACKETS)), key=lambda i: (PACKETS[i][1], PACKETS[i][0]))
    run = {"schema": "chronoroute.trace/1", "tool": "python-sim", "t0_utc": "2026-10-10T14:00:00Z",
           "t0_gps_ns": 0, "unit_code": 1, "snapshot_id": None, "bundle": None, "nodes": [],
           "positions": {"source": "snapshot", "path": "x"}, "faults": [FAULT], "labels": {"x": "MODELLED"},
           "engine": {"end_ns": 2000 * MS, "drain_ns": 1000 * MS, "duration_ns": 1000 * MS,
                      "processing_ns": 500_000, "link_rate_bps": 1_000_000_000, "policy": "continue"},
           "flows": [{"flow_id": 0, "src": "A", "dst": "B", "src_node": 10, "dst_node": 11},
                     {"flow_id": 1, "src": "C", "dst": "D", "src_node": 12, "dst_node": 13}]}
    (d / "run.json").write_text(json.dumps(run), encoding="utf-8")
    pw = PacketCsvWriter(d / "packets.csv.gz")
    ew = ExtrasWriter(d / "scheme_packets.csv.gz")
    seqs = {0: 0, 1: 0}
    for pkt, i in enumerate(order):
        fl, send, outc, reason, lat, path, arr, fl_k, st = PACKETS[i]
        seq = seqs[fl]
        seqs[fl] += 1
        lat_s = "" if lat is None else str(lat * MS)
        pw.row(pkt, ",".join([str(pkt), str(fl), str(seq), str(send * MS), outc, reason,
                              "1" if outc == "delivered" else "0", lat_s, str(len(path) - 1),
                              " ".join(map(str, path)), "1" if fl_k > 0 else "0", str(fl_k) if fl_k > 0 else "",
                              str(fl_k) if fl_k > 0 else "", "", "", "0", "", "0", "300"]) + "\n")
        ld, orc, tol, ok = st if st else ("", "", "", "")
        ew.row(pkt, ",".join([str(pkt), str(fl), " ".join(str(x * MS) for x in arr),
                              " ".join("1000000" for _ in arr), " ".join("-1" for _ in arr), "0",
                              str(ld), str(orc), str(len(path) - 1) if st else "", str(ok), str(tol), "", "0", "0", ""]) + "\n")
    pw.close()
    ew.close()
    return load.load_run(d)


@pytest.fixture
def run(tmp_path):
    return make_run(tmp_path / "hand")


def idx(run, flow, send_ms):
    return int(np.flatnonzero((run.flow == flow) & (run.send_ns == send_ms * MS))[0])


def test_pdr_reasons_and_sending_window(run):
    rows = {r["flow"]: r for r in metrics.pdr_by_flow(run)}
    assert rows[0]["sent"] == 9                      # the packet sent at 1.2 s is after T_end - drain
    assert rows[0]["delivered"] == 7 and rows[0]["pdr"] == pytest.approx(7 / 9)
    assert rows[0]["losses"] == {"in_flight_link_down": 1, "no_route": 1}
    assert rows[1]["pdr"] == 1.0 and rows[1]["losses"] == {}
    tot = metrics.pdr_total(run)
    assert tot["sent"] == 11 and tot["delivered"] == 9
    warm = metrics.pdr_by_flow(run, metrics.measurement_mask(run, warmup_ns=550 * MS))
    assert warm[0]["sent"] == 7                     # 600, 620, 700, 750, 790, 850, 900 ms


def test_effective_and_ordinary_quantiles(run):
    lat = {r["flow"]: r for r in metrics.latency_summary(run, ps=("0.5", "0.95", "0.99"))}[0]
    # delivered latencies (ms): 20 21 22 30 31 32 33; sent 9 (2 lost = +inf at the top)
    assert lat["q0.5"] == 30 * MS                    # nearest rank ceil(0.5 * 7) = 4
    assert lat["q0.5_eff"] == 31 * MS                # ceil(0.5 * 9) = 5
    assert lat["q0.95_eff"] == math.inf              # rank 9 > 7 delivered
    assert lat["q0.99"] is None and lat["q0.99_eff"] is None     # tail rule: needs 1000 packets
    assert metrics.nearest_rank([1, 2, 3], "0.34") == 2 and metrics.nearest_rank([], "0.5") is None


def test_stretch_check_and_tolerance(run):
    st = metrics.stretch(run)
    assert st["n"] == 9 and st["n_path_not_in_send_graph"] == 1
    assert st["violations"] == 1 and st["worst_violation_ns"] == 1   # 99 < 100 with tol 0
    assert st["exact_violations"] == 1                               # the one with tol 5 is allowed
    # headline minimum: only packets with tol 0 in the send graph (the 0.99 is a real violation)
    assert st["min"] == pytest.approx(0.99)
    assert st["min_tol_adjusted"] == pytest.approx(0.99)             # (99 + 5) / 100 = 1.04 is fine
    assert st["min_raw"] == pytest.approx(0.9)                       # raw: includes the off-graph path
    assert st["hop_violations"] == 0                                 # 3 hops vs oracle 3


def test_exposure_both_directions_and_time_window(run):
    ex, t = metrics.exposure(run, FAULT)
    assert ex[idx(run, 0, 500)] and t[idx(run, 0, 500)] == 510 * MS   # at node 3 at 510 ms
    assert ex[idx(run, 0, 600)] and t[idx(run, 0, 600)] == 610 * MS   # reverse direction
    assert ex[idx(run, 0, 620)]                                       # lost on the link: still crossed it
    assert not ex[idx(run, 0, 100)] and not ex[idx(run, 0, 790)]      # before the onset / at the stop
    assert ex.sum() == 3
    node = dict(FAULT, link=None, node=4)
    exn, tn = metrics.exposure(run, node)
    assert exn[idx(run, 0, 500)] and tn[idx(run, 0, 500)] == 520 * MS


def test_labels_and_clean_fpr(run):
    m = metrics.measurement_mask(run)
    lab = metrics.packet_labels(run, m)
    assert lab[idx(run, 0, 1200)] == -1
    assert sorted(np.flatnonzero(lab == 1).tolist()) == sorted(idx(run, 0, s) for s in (500, 600, 620))
    flagged = run.first_late >= 1
    f = metrics.deadline_fpr(lab, flagged, run.hops)
    assert f["clean"] == 8 and f["false_positives"] == 1 and f["fpr"] == pytest.approx(1 / 8)
    assert f["per_hops"][3] == {"clean": 5, "fp": 1}
    # congested label: a hop slower than light + processing + serialization by more than q_th
    lab2 = metrics.packet_labels(run, m, q_th_ns=6 * MS)
    assert lab2[idx(run, 0, 790)] == 3 and lab2[idx(run, 0, 100)] == 3 and lab2[idx(run, 1, 150)] == 3
    lab3 = metrics.packet_labels(run, m, q_th_ns=20 * MS)
    assert (lab3 == 3).sum() == 0


def test_blackhole_and_time_to_mitigation(run):
    bh = metrics.blackhole(run, FAULT)
    assert bh == {"losses": 1, "blackhole_ns": 130 * MS, "first_loss_ns": 130 * MS}
    tt = metrics.time_to_mitigation(run, FAULT, bin_ns=100 * MS, sustain_ns=100 * MS)
    assert tt["affected_flows"] == [0] and tt["packets_affected"] == 3
    assert tt["observed"] and tt["ttm_ns"] == 200 * MS
    never = metrics.time_to_mitigation(run, FAULT, bin_ns=100 * MS, sustain_ns=1000 * MS)
    assert not never["observed"] and never["horizon_ns"] == 300 * MS


def test_fault_index_equals_per_fault_exposure_on_many_faults(tmp_path):
    """The fast all-faults exposure (used for labels) equals the OR of the per-fault one."""
    from chronoroute.baselines import params, run as brun
    from chronoroute.fwd import config
    d = {"seed": 2, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 3, "drain_s": 1,
                                 "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
         "traffic": {"flows": [{"src": "London", "dst": "New York"}, {"src": "Tokyo", "dst": "Los Angeles"}],
                     "rate_pps": 100},
         "faults": [{"kind": "link_renewal", "unavailability": 0.05, "mttr_s": 0.3},
                    {"kind": "node_renewal", "unavailability": 0.02, "mttr_s": 0.3},
                    {"kind": "slow_processing", "on_path": {"flow": 0, "kind": "node"}, "delta_ns": 1000,
                     "start_s": 1, "stop_s": 2}],
         "output": {"trace": "none"}}
    brun.run_scheme(config.normalise(d), params.normalise_scheme("ls_h"), tmp_path / "many", write_manifest=False)
    r = load.load_run(tmp_path / "many")
    assert len(r.faults) > 50
    want = np.zeros(r.n, dtype=bool)
    for f in r.faults:
        want |= metrics.exposure(r, f)[0]
    got = metrics.FaultIndex(r.faults).exposed_any(r)
    assert want.sum() > 0 and np.array_equal(got, want)
    lab = metrics.packet_labels(r)
    assert np.array_equal(lab == 1, got | (lab == 1)) and (lab == 1).sum() >= got.sum()


@pytest.mark.parametrize("kind", ["slow_link", "rate_cut"])
def test_exposure_matches_exactly_the_packets_the_fault_changed(tmp_path, kind):
    """Ground truth at fault boundaries (minor finding): a link fault acts at the TRANSMISSION
    START (after processing and queueing), and a rate cut keeps delaying packets queued behind
    its backlog after it stops. With a fault-free twin (same random numbers) the packets whose
    timing changed are known exactly; exposure must be exactly that set (for the slow link: plus
    the tiny indirect effect of its reordering, checked separately)."""
    from chronoroute.baselines import params, run as brun
    from chronoroute.eval import detection
    from chronoroute.fwd import config, scenario as sm
    d = {"seed": 6, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 5, "drain_s": 1,
                                 "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
         "traffic": {"flows": [{"src": "London", "dst": "New York"}], "rate_pps": 200},
         "forwarding": {"policy": "continue"}, "output": {"trace": "none"}}
    sc = sm.build_scenario(config.normalise(d))
    a, b = sc.resolve_on_path({"flow": 0, "position": "middle"}, 2 * 10**9, False)
    if kind == "slow_link":
        f = {"kind": "slow_processing", "link": [a, b], "delta_ns": 10_000_000, "start_s": 2, "stop_s": 3}
    else:
        f = {"kind": "rate_cut", "link": [a, b], "factor": "0.0002", "start_s": 2, "stop_s": 3}
    scheme = params.normalise_scheme("chronoroute")
    brun.run_scheme(config.normalise(dict(d, faults=[f])), scheme, tmp_path / "f", write_manifest=False)
    brun.run_scheme(config.normalise(d), scheme, tmp_path / "t", write_manifest=False)
    fr, tw = load.load_run(tmp_path / "f"), load.load_run(tmp_path / "t")
    fault = fr.faults[0]
    assert np.array_equal(fr.send_ns, tw.send_ns)
    changed = (fr.latency_ns != tw.latency_ns) | (fr.outcome != tw.outcome)
    exposed, _t = metrics.exposure(fr, fault)
    assert changed.sum() > 50
    if kind == "slow_link":
        # every exposed packet got exactly Delta (+ at most a serialization time or two of
        # downstream FIFO contention); and the only other changes are the INDIRECT ones of this
        # MODELLED fault: a delayed packet is overtaken by the next ones at the stop instant
        # (the transmitter stays free, faults.py), and meeting it downstream costs a packet a
        # serialization time (~2.2 us here) - never a deadline flag.
        diff = fr.latency_ns - tw.latency_ns
        assert np.all(exposed <= changed)
        assert np.all((diff[exposed] >= 10_000_000) & (diff[exposed] <= 10_000_000 + 10_000))
        indirect = changed & ~exposed
        assert indirect.sum() <= 4 and np.all((diff[indirect] > 0) & (diff[indirect] <= 10_000))
        assert not np.any((fr.first_late >= 1)[indirect])
    else:
        assert np.array_equal(exposed, changed), (int((exposed & ~changed).sum()), int((changed & ~exposed).sum()))
        # the drain after the cut is real and is covered: packets that started after stop
        old = dict(fr.extras)
        fr.extras = {k: v for k, v in old.items() if k not in ("tx_ns", "wait_ns")}
        before, _ = metrics.exposure(fr, fault)                 # the old rule: time at the node, no drain
        fr.extras = old
        assert (exposed & ~before).sum() > 0
    # the all-faults index (labels) uses the same instants
    assert np.array_equal(metrics.FaultIndex(fr.faults).exposed_any(fr), exposed)
    c = detection.counterfactual(fr, tw, detection.flags_for(fr), detection.flags_for(tw), fault)
    assert c["induced_unexposed"] == 0                          # nothing flagged that was not exposed


def test_in_flight_loss_without_a_fault_is_stale_not_clean(run):
    """A packet lost in flight on a link no fault had down lost its link to geometry: `stale`
    (a drop on a geometrically dead link), never `clean` (it could not be flagged downstream)."""
    i = idx(run, 0, 620)                                   # in_flight_link_down on 3 -> 4
    assert metrics.packet_labels(run)[i] == 1              # the slow fault on 3-4 was active
    run.run["faults"] = []
    try:
        assert metrics.packet_labels(run)[i] == 2
    finally:
        run.run["faults"] = [FAULT]


@pytest.fixture(scope="module")
def drop_runs(tmp_path_factory):
    """Faults that DROP packets on their element, each with its fault-free twin (same seed):
    C1, London -> New York and Chennai -> London at 300 pps each, policy continue.

      rate_cut  the middle link of flow 0 cut to 0.002 x C for [2, 3) s with ISL background
                load rho 0.3 (fluid): its drop-tail FIFO fills (buffer_overflow)
      arq       ARQ with loss 0.5 on that link for [2, 3) s: some packets fail every try
                (arq_exhausted)
      down      the link down from 2.0001 s: packets already in flight are lost on arrival
    """
    from chronoroute.baselines import params, run as brun
    from chronoroute.fwd import config, scenario as sm
    tmp = tmp_path_factory.mktemp("drops")

    def doc(bg, faults=()):
        fw = {"policy": "continue"}
        if bg:
            fw["background"] = {"model": bg, "rho": "0.3", "links": "isl"}
        return {"seed": 21, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 5, "drain_s": 1,
                                         "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
                "traffic": {"flows": [{"src": "London", "dst": "New York"}, {"src": "Chennai", "dst": "London"}],
                            "rate_pps": 300},
                "schedule": {"slack": "1.3"}, "forwarding": fw, "faults": list(faults),
                "output": {"trace": "none"}}

    a, b = sm.build_scenario(config.normalise(doc(None))).resolve_on_path(
        {"flow": 0, "position": "middle"}, 2 * 10**9, False)
    cases = {"rate_cut": ("fluid", {"kind": "rate_cut", "link": [a, b], "factor": "0.002", "start_s": 2,
                                    "stop_s": 3}),
             "arq": (None, {"kind": "arq", "link": [a, b], "loss": "0.5", "start_s": 2, "stop_s": 3}),
             "down": (None, {"kind": "link_down", "link": [a, b], "start_s": "20001/10000", "stop_s": 3})}
    scheme = params.normalise_scheme("chronoroute")
    out = {}
    for bg in ("fluid", None):
        brun.run_scheme(config.normalise(doc(bg)), scheme, tmp / f"twin-{bg}", write_manifest=False)
    for name, (bg, f) in cases.items():
        brun.run_scheme(config.normalise(doc(bg, [f])), scheme, tmp / name, write_manifest=False)
        out[name] = (load.load_run(tmp / name), load.load_run(tmp / f"twin-{bg}"), {a, b})
    return out


def _changed(fr, tw):
    assert np.array_equal(fr.send_ns, tw.send_ns)
    return (fr.latency_ns != tw.latency_ns) | (fr.outcome != tw.outcome)


def test_fault_drops_are_exposed_and_never_clean(drop_runs):
    """Major finding: a rate cut with background load drops packets at the cut link's
    transmitter (drop-tail). Their path ends at the upstream node, so the old (u, v) hop test
    never matched them: unexposed, labelled clean, in the FPR denominator. Now the engine
    records the link they were lost at (tx_loss_at) and: changed = crossed + lost there,
    exactly; every such drop is exposed and labelled `fault`; the counterfactual reports
    them as lost_at_fault (not in P_det); nothing is flagged without exposure."""
    from chronoroute.eval import detection
    fr, tw, link = drop_runs["rate_cut"]
    fault = fr.faults[0]
    changed = _changed(fr, tw)
    drops = fr.outcome == 1
    assert (tw.outcome == 1).sum() == 0                                  # the twin loses nothing
    assert {fr.reason[i] for i in np.flatnonzero(drops)} == {"buffer_overflow"} and drops.sum() > 100
    for i in np.flatnonzero(drops):                                       # recorded at the cut link
        u, v, t, w = (int(x) for x in fr.extras["tx_loss_at"][i].split(":"))
        assert {u, v} == link and int(fr.paths[i][-1]) == u and w == -1 and 2 * 10**9 <= t
    reached = metrics.exposure(fr, fault)[0]
    crossed = metrics.exposure(fr, fault, "crossed")[0]
    lost = metrics.lost_at_fault(fr, fault)
    assert np.array_equal(changed, reached)                               # exactly the changed packets
    assert np.array_equal(lost, drops) and not (crossed & lost).any()
    assert np.array_equal(changed, crossed | lost)
    lab = metrics.packet_labels(fr)
    assert np.all(lab[drops] == 1)                                        # never clean
    assert np.array_equal(metrics.FaultIndex(fr.faults).exposed_any(fr), reached)
    c = detection.counterfactual(fr, tw, detection.flags_for(fr), detection.flags_for(tw), fault)
    assert c["lost_at_fault"] == int(drops.sum()) and c["exposed"] == int(crossed.sum())
    assert c["exposed"] + c["lost_at_fault"] == c["reached"] == int(changed.sum())
    assert c["induced_unexposed"] == 0 and c["true_detections"] > 0
    # the old rule (no transmitter-loss record) left every one of these drops clean
    old = dict(fr.extras)
    fr.extras = {k: v for k, v in old.items() if k != "tx_loss_at"}
    try:
        before = metrics.exposure(fr, fault)[0]
        assert np.array_equal(changed & ~before, drops)
        assert np.all(metrics.packet_labels(fr)[drops] == 0)
    finally:
        fr.extras = old


def test_arq_give_ups_are_exposed_and_never_clean(drop_runs):
    from chronoroute.eval import detection
    fr, tw, link = drop_runs["arq"]
    fault = fr.faults[0]
    changed = _changed(fr, tw)
    drops = fr.outcome == 1
    assert {fr.reason[i] for i in np.flatnonzero(drops)} == {"arq_exhausted"} and drops.sum() > 5
    for i in np.flatnonzero(drops):
        u, v, t, w = (int(x) for x in fr.extras["tx_loss_at"][i].split(":"))
        assert {u, v} == link and 2 * 10**9 <= t < 3 * 10**9 and w >= 0
    reached = metrics.exposure(fr, fault)[0]
    # every changed packet is reached (a packet whose first try succeeded is reached, unchanged)
    assert not (changed & ~reached).any()
    assert np.array_equal(metrics.lost_at_fault(fr, fault), drops)
    assert np.all(metrics.packet_labels(fr)[drops] == 1)
    c = detection.counterfactual(fr, tw, detection.flags_for(fr), detection.flags_for(tw), fault)
    assert c["lost_at_fault"] == int(drops.sum()) and c["induced_unexposed"] == 0


def test_packets_in_flight_at_a_link_down_onset_are_lost_by_the_fault(drop_runs):
    """A packet transmitted just BEFORE the link goes down is lost on arrival (the engine checks
    the link then): the fault lost it although its transmission started before the onset."""
    fr, tw, link = drop_runs["down"]
    fault = fr.faults[0]
    changed = _changed(fr, tw)
    drops = fr.outcome == 1
    assert {fr.reason[i] for i in np.flatnonzero(drops)} == {"in_flight_link_down"} and drops.sum() >= 1
    for i in np.flatnonzero(drops):
        assert {int(x) for x in fr.paths[i][-2:]} == link
        assert int(fr.extras["tx_ns"][i][-1]) < fault["start_ns"] <= int(fr.extras["arrival_ns"][i][-1])
    assert np.array_equal(metrics.lost_at_fault(fr, fault), drops)
    assert np.all(metrics.packet_labels(fr)[drops] == 1)
    # with the packets that met the dead link as their next hop (fallback), exactly the changed ones
    assert np.array_equal(metrics.touched(fr, fault), changed)
    assert np.array_equal(metrics.FaultIndex(fr.faults).exposed_any(fr), metrics.exposure(fr, fault)[0])
    assert metrics.blackhole(fr, fault)["losses"] == 0       # sent before the onset: not a blackhole


def test_csv_files_round_trip(run, tmp_path):
    with gzip.open(tmp_path / "hand" / "scheme_packets.csv.gz", "rt") as fh:
        assert fh.readline().strip().split(",") == list(EXTRAS_COLUMNS)
    assert run.n == len(PACKETS) and run.paths.length(idx(run, 0, 850)) == 1

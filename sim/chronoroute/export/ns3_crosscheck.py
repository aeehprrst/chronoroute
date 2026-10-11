"""
ns3_crosscheck.py
-----------------
E16-lite: check the ns-3 course-milestone run (ns3/contrib/chronoroute/
examples/chronoroute-leo.cc) against an independent Python prediction made
from the same scenario bundle, and summarise the runs.

What "the Python prediction" is, for one probe (flow f, sent at t):

  * the path is the schedule.csv row of flow f valid at t (rows hold for
    [valid_from, valid_to)), exactly what the ns-3 source shim inserts;
  * the T-CRH is built and processed hop by hop with the golden-tested Python
    reference (chronoroute.proto: build_header, ingress_send, process_at_node,
    link_down_fallback) under deviation policy 'continue';
  * the timing uses the same physics as ns-3: at each hop the packet starts
    to transmit when it arrives (no queue in the prediction), takes
    serialization time wire_bytes * 8 / rate, then the link's light time
    HELD at the 100 ms step in force at the transmit instant (the bundle's
    isl_delay.csv / gsl.csv value; -1 keeps the previous value);
  * a link marked down: the node holding the packet finds it down when it
    arrives there (spec section 6 step 7, policy 'continue' without a
    fallback: discarded), and a packet still in flight when its link goes
    down is lost at the receiving end. The state at time t is the row of step
    floor(t / step); a change exactly at the tie instant is already in force.

So the prediction differs from ns-3 only where ns-3 queues a packet behind
another one (the prediction has no queues). The cross-check reports the
fraction of probes whose path (and outcome) is identical, and the latency
difference ns-3 minus "light time only", which must equal the serialization
time of every hop plus any queueing (reported as a distribution).

Also here: the per-flow summary (PDR, latency p50/p99, fraction flagged
before/during/after the fault), the detection figures (fault run vs the paired
no-fault run), a pcap reader for the ns-3 capture, and the wrapper around
tools/wireshark/check_pcap.sh.

Command line (normally driven by ns3/run_leo.py):

    python -m chronoroute.export.ns3_crosscheck crosscheck BUNDLE PACKETS.csv[.gz]
"""

import argparse
import csv
import gzip
import io
import json
import math
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import numpy as np

from .. import labels as labels_mod
from ..proto import sizes as sizes_mod
from ..proto import tcrh as tcrh_mod
from ..proto import timebase

NS_PER_MS = 1_000_000
PPP_BYTES = 2          # point-to-point header in front of every ns-3 frame
IPV6_BYTES = 40
UDP_BYTES = 8
DEFAULT_PAYLOAD = 200
DEFAULT_RATE_BPS = 1_000_000_000
PID_FLOW_FACTOR = 1_000_000   # probe id in the payload = flow * 10^6 + seq
POLICY = "continue"

# The honesty labels of everything this module reports (the shared table,
# chronoroute/labels.py, so they match the bundle, the fleet report and the website).
LABELS = labels_mod.pick("satellite_positions_sgp4", "orbital_elements", "city_coordinates",
                         "shells_and_planes", "isl_topology_grid4", "gsl_mask_and_assignment",
                         "routes_and_budgets", "tcrh_header_bytes", "link_rate_and_queues",
                         "traffic_probes", "fault_slow_link", "ns3_processing_delay_zero")


# ======================================================================= bundle

@dataclass
class Row:
    """One schedule.csv row."""
    flow: int
    src: int
    dst: int
    from_ms: int
    to_ms: int
    sids: tuple
    budgets: tuple
    predicted: tuple
    template_hex: str
    path: tuple


@dataclass
class ReplayBundle:
    """The parts of a scenario bundle that a replay needs, as numpy arrays."""
    dir: str
    t0_gps_ns: int
    t0_unix_ns: int
    window_ms: int
    step_ms: int
    unit_code: int
    n_sats: int
    node_kind: list
    node_sid: list
    node_name: list
    isl_ab: np.ndarray            # (L, 2) node ids
    isl_up: np.ndarray            # (steps, L) uint8
    isl_delay: np.ndarray         # (steps, L) int64, held: -1 replaced by the previous value
    isl_delay_raw: np.ndarray     # (steps, L) int64 as in the file
    gsl_pairs: list               # [(gs, sat)]
    gsl_up: np.ndarray            # (steps, P) uint8
    gsl_delay: np.ndarray         # (steps, P) int64, held
    schedule: list
    link_of: dict = field(default_factory=dict)     # (u, v) -> ("isl"|"gsl", index), both orders
    rows_of_flow: dict = field(default_factory=dict)

    @property
    def n_steps(self):
        return self.isl_up.shape[0]

    @property
    def unit_ns(self):
        return timebase.unit_ns(self.unit_code)

    def step_at(self, t_ns):
        """The step whose state holds at simulation time t_ns (clamped to the last)."""
        return min(t_ns // (self.step_ms * NS_PER_MS), self.n_steps - 1)

    def row_at(self, flow, t_ns):
        """The schedule row of `flow` valid at t_ns, or None (a gap)."""
        for r in self.rows_of_flow.get(flow, ()):
            if r.from_ms * NS_PER_MS <= t_ns < r.to_ms * NS_PER_MS:
                return r
        return None

    def link(self, u, v, step):
        """(up, held delay ns, raw delay ns) of the link u-v at a step."""
        kind, i = self.link_of[(u, v)]
        if kind == "isl":
            return bool(self.isl_up[step, i]), int(self.isl_delay[step, i]), int(self.isl_delay_raw[step, i])
        return bool(self.gsl_up[step, i]), int(self.gsl_delay[step, i]), int(self.gsl_delay[step, i])


def _scenario_int(doc, *path):
    v = doc
    for key in path:
        v = v[key]
    if not isinstance(v, int):
        raise ValueError(f"scenario.json {'.'.join(path)} must be an integer")
    return v


def _hold(delays):
    """Replace -1 (no position) by the previous step's value, like ns-3 does."""
    out = delays.copy()
    for s in range(out.shape[0]):
        bad = out[s] < 0
        if bad.any():
            out[s, bad] = out[s - 1, bad] if s > 0 else 0
    return out


def _read_int_table(path, ncols):
    """A headed, comma-separated table of integers as an (n, ncols) int64 array."""
    with open(path, encoding="utf-8") as fh:
        fh.readline()
        data = np.loadtxt(fh, delimiter=",", dtype=np.int64, ndmin=2)
    if data.size == 0:
        return np.zeros((0, ncols), dtype=np.int64)
    if data.shape[1] != ncols:
        raise ValueError(f"{path}: expected {ncols} columns")
    return data


def load_replay_bundle(path):
    """Read a bundle directory (docs/bundle-format.md) for replay."""
    d = Path(path)
    doc = json.loads((d / "scenario.json").read_text(encoding="utf-8"))
    if doc.get("schema") != "chronoroute.bundle/1":
        raise ValueError(f"{d}: not a chronoroute.bundle/1")
    window_ms = _scenario_int(doc, "time", "window_ms")
    step_ms = _scenario_int(doc, "time", "step_ms")
    n_steps = window_ms // step_ms + 1

    kinds, sids, names = [], [], []
    with open(d / "nodes.csv", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd)
        for i, r in enumerate(rd):
            if int(r[0]) != i:
                raise ValueError("nodes.csv: node ids must be 0, 1, 2, ...")
            kinds.append(r[1])
            sids.append(int(r[2]))
            names.append(r[4])
    n_sats = kinds.count("sat")

    with open(d / "isl.csv", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd)
        isl_rows = [(int(r[1]), int(r[2])) for r in rd]
    isl_ab = np.array(isl_rows, dtype=np.int64).reshape(-1, 2)
    n_isl = len(isl_rows)

    tab = _read_int_table(d / "isl_delay.csv", 4)
    if tab.shape[0] != n_steps * n_isl:
        raise ValueError("isl_delay.csv: rows != steps x links")
    expect_t = np.repeat(np.arange(n_steps, dtype=np.int64) * step_ms, n_isl)
    expect_l = np.tile(np.arange(n_isl, dtype=np.int64), n_steps)
    if not (np.array_equal(tab[:, 0], expect_t) and np.array_equal(tab[:, 1], expect_l)):
        raise ValueError("isl_delay.csv: rows must be sorted by (t_ms, link_id), every link every step")
    isl_up = tab[:, 2].astype(np.uint8).reshape(n_steps, n_isl)
    isl_delay_raw = tab[:, 3].reshape(n_steps, n_isl)
    del tab

    g = _read_int_table(d / "gsl.csv", 6)
    if g.shape[0] % n_steps:
        raise ValueError("gsl.csv: rows not a multiple of the steps")
    n_pairs = g.shape[0] // n_steps
    pairs = [(int(g[p, 1]), int(g[p, 2])) for p in range(n_pairs)]
    gg = g.reshape(n_steps, n_pairs, 6)
    if not (np.all(gg[:, :, 1] == gg[0:1, :, 1]) and np.all(gg[:, :, 2] == gg[0:1, :, 2])):
        raise ValueError("gsl.csv: every step must list the same pairs")
    gsl_up = gg[:, :, 3].astype(np.uint8)
    gsl_delay = _hold(gg[:, :, 4].copy())

    schedule = []
    with open(d / "schedule.csv", encoding="utf-8") as fh:
        rd = csv.reader(fh)
        next(rd)
        for r in rd:
            ints = lambda s: tuple(int(x) for x in s.split())
            schedule.append(Row(flow=int(r[0]), src=int(r[1]), dst=int(r[2]), from_ms=int(r[3]),
                                to_ms=int(r[4]), sids=ints(r[5]), budgets=ints(r[6]),
                                predicted=ints(r[7]), template_hex=r[8], path=ints(r[9])))

    rb = ReplayBundle(dir=str(d), t0_gps_ns=_scenario_int(doc, "time", "t0_gps_ns"),
                      t0_unix_ns=_scenario_int(doc, "time", "t0_unix_ns"), window_ms=window_ms,
                      step_ms=step_ms, unit_code=_scenario_int(doc, "tcrh", "unit_code"),
                      n_sats=n_sats, node_kind=kinds, node_sid=sids, node_name=names,
                      isl_ab=isl_ab, isl_up=isl_up, isl_delay=_hold(isl_delay_raw),
                      isl_delay_raw=isl_delay_raw, gsl_pairs=pairs, gsl_up=gsl_up,
                      gsl_delay=gsl_delay, schedule=schedule)
    for i, (a, b) in enumerate(isl_rows):
        rb.link_of[(a, b)] = rb.link_of[(b, a)] = ("isl", i)
    for i, (gs, sat) in enumerate(pairs):
        rb.link_of[(gs, sat)] = rb.link_of[(sat, gs)] = ("gsl", i)
    for r in schedule:
        rb.rows_of_flow.setdefault(r.flow, []).append(r)
    return rb


# ======================================================================= physics

def tx_time_ns(nbytes, rate_bps):
    """Serialization time as ns-3 computes it: Seconds(bits / rate), rounded to whole ns.

    ns-3 (DataRate::CalculateBytesTxTime) divides in 64.64 fixed point and
    converts to its ns resolution by rounding; for 1 Gb/s the result is exactly
    8 ns per byte, so there is nothing to round.
    """
    q = Fraction(nbytes * 8 * 10**9, rate_bps)
    return math.floor(q + Fraction(1, 2))


def wire_bytes(num_hops, payload_bytes=DEFAULT_PAYLOAD):
    """Bytes of one probe on a point-to-point link: PPP + IPv6 + T-CRH + UDP + payload."""
    return PPP_BYTES + IPV6_BYTES + sizes_mod.tcrh_size(num_hops) + UDP_BYTES + payload_bytes


@dataclass
class Prediction:
    """What the Python replay says happens to one probe."""
    flow: int
    send_ns: int
    row_from_ms: int | None
    taken: list
    hop_t_ns: list
    hop_now_u: list
    hop_deadline_u: list
    first_late_hop: int | None
    link_down_hop: int | None
    dev: int
    dev_hop: int
    outcome: str
    outcome_node: int
    latency_ns: int | None
    epoch_base: int
    prop_ns: int          # light time of the hops crossed (held values)
    ser_ns: int           # serialization of one hop
    hop_hold_err_ns: list  # |held - linearly interpolated| light time per hop crossed


def _interp_delay(rb, u, v, t_ns):
    """Light time of u-v at t_ns, linearly interpolated between the two rows around it."""
    s = rb.step_at(t_ns)
    _, d0, raw0 = rb.link(u, v, s)
    if s + 1 >= rb.n_steps:
        return Fraction(d0)
    _, d1, raw1 = rb.link(u, v, s + 1)
    if raw0 < 0 or raw1 < 0:
        return Fraction(d0)
    frac = Fraction(t_ns - s * rb.step_ms * NS_PER_MS, rb.step_ms * NS_PER_MS)
    return d0 + (d1 - d0) * frac


def predict_probe(rb, flow, send_ns, *, payload_bytes=DEFAULT_PAYLOAD, rate_bps=DEFAULT_RATE_BPS):
    """Replay one probe through the bundle (see the module docstring)."""
    row = rb.row_at(flow, send_ns)
    if row is None:
        return Prediction(flow, send_ns, None, [], [], [], [], None, None, 0, 0, "no_route",
                          -1, None, 0, 0, 0, [])
    h = len(row.sids)
    ser = tx_time_ns(wire_bytes(h, payload_bytes), rate_bps)
    t_gps = rb.t0_gps_ns + send_ns
    hdr = tcrh_mod.build_header(row.sids, row.budgets, t_gps, rb.unit_code)
    epoch = hdr.epoch_base
    deadlines = hdr.deadlines()
    raw, _first = tcrh_mod.ingress_send(hdr.encode())

    taken = [row.path[0]]
    hop_t, hop_now, hop_dl, hold_err = [], [], [], []
    first_late = link_down = None
    t = send_ns
    prop = 0
    dev = dev_hop = 0
    outcome, outcome_node = None, None
    for i in range(h):
        u, v = row.path[i], row.path[i + 1]
        up, delay, _raw = rb.link(u, v, rb.step_at(t))
        if not up:
            # step 7 at node u (hop index i; the ingress is hop 0): DEV with
            # Dev Hop i, then discarded (no fallback function in this phase).
            # ns-3 reports the same header at the ingress and at transit nodes.
            link_down = i
            fb = tcrh_mod.link_down_fallback(raw)
            dev = fb.out_bytes[tcrh_mod.OFF_FLAGS] & tcrh_mod.FLAG_DEV
            dev_hop = fb.out_bytes[tcrh_mod.OFF_DEV_HOP]
            outcome, outcome_node = "drop_link_down", u
            break
        hold_err.append(abs(Fraction(delay) - _interp_delay(rb, u, v, t)))
        t_arr = t + ser + delay
        if not rb.link(u, v, rb.step_at(t_arr))[0]:
            outcome, outcome_node = "drop_iface_down", v
            break
        t = t_arr
        prop += delay
        taken.append(v)
        now_u = timebase.clock_u(rb.t0_gps_ns + t, rb.unit_code)
        res = tcrh_mod.process_at_node(raw, now_u, POLICY)
        hop_t.append(t)
        hop_now.append(now_u)
        hop_dl.append(deadlines[res.hop_index - 1])
        if res.late:
            first_late = res.hop_index
        raw = res.out_bytes
        dev = raw[tcrh_mod.OFF_FLAGS] & tcrh_mod.FLAG_DEV
        dev_hop = raw[tcrh_mod.OFF_DEV_HOP]
        if res.action == "deliver":
            outcome, outcome_node = "delivered", v
            break
        if res.action != "forward" or res.next_sid != rb.node_sid[row.path[i + 2]]:
            raise AssertionError(f"reference processing disagrees with the schedule: {res}")
    return Prediction(flow=flow, send_ns=send_ns, row_from_ms=row.from_ms, taken=taken,
                      hop_t_ns=hop_t, hop_now_u=hop_now, hop_deadline_u=hop_dl,
                      first_late_hop=first_late, link_down_hop=link_down, dev=dev,
                      dev_hop=dev_hop, outcome=outcome, outcome_node=outcome_node,
                      latency_ns=(t - send_ns) if outcome == "delivered" else None,
                      epoch_base=epoch, prop_ns=prop, ser_ns=ser,
                      hop_hold_err_ns=[float(x) for x in hold_err])


# ======================================================================= ns-3 output

_LIST_COLS = ("planned_path", "taken_path", "hop_t_ns", "hop_now_u", "hop_deadline_u", "hop_margin_u")
_INT_COLS = ("flow_id", "seq", "uid", "send_ns", "num_hops", "epoch_base", "wire_bytes", "dev",
             "dev_hop", "outcome_node", "outcome_t_ns")
_OPT_INT_COLS = ("row_from_ms", "first_late_hop", "link_down_hop", "rx_ns", "latency_ns",
                 "fault_link_t_ns")


def _open_text(path):
    path = str(path)
    if path.endswith(".gz"):
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
    return open(path, encoding="utf-8")


def read_packets(path):
    """packets.csv(.gz) written by chronoroute-leo, as a list of dicts with ints and lists."""
    out = []
    with _open_text(path) as fh:
        for r in csv.DictReader(fh):
            for c in _LIST_COLS:
                r[c] = [int(x) for x in r[c].split()]
            for c in _INT_COLS:
                r[c] = int(r[c])
            for c in _OPT_INT_COLS:
                r[c] = int(r[c]) if r[c] != "" else None
            out.append(r)
    return out


# ======================================================================= cross-check

def _quantiles(values, qs=(0.0, 0.5, 0.99, 1.0)):
    if len(values) == 0:
        return {f"p{int(q * 100)}": None for q in qs}
    a = np.asarray(values, dtype=np.float64)
    return {("min" if q == 0 else "max" if q == 1 else f"p{int(q * 100)}"):
            float(np.quantile(a, q, method="lower")) for q in qs}


def crosscheck(rb, packets, *, payload_bytes=DEFAULT_PAYLOAD, rate_bps=DEFAULT_RATE_BPS,
               exclude=None, max_examples=10):
    """Compare every ns-3 probe with the Python prediction.

    exclude(packet) -> True leaves a packet out (e.g. the slowed link in a fault run).
    Returns a JSON-able dict.
    """
    n = same_path = same_outcome = same_late = same_linkdown = same_hops = 0
    same_dev_delivered = delivered_both = same_dev = 0
    lat_diff, queue_ns, sched_diff, hold_err = [], [], [], []
    ingress_dev_quirk = 0
    examples = []
    for p in packets:
        if exclude is not None and exclude(p):
            continue
        n += 1
        pr = predict_probe(rb, p["flow_id"], p["send_ns"], payload_bytes=payload_bytes,
                           rate_bps=rate_bps)
        ok_path = pr.taken == p["taken_path"]
        ok_out = pr.outcome == p["outcome"] and pr.outcome_node == p["outcome_node"]
        same_path += ok_path
        same_outcome += ok_out
        same_late += pr.first_late_hop == p["first_late_hop"]
        same_linkdown += pr.link_down_hop == p["link_down_hop"]
        same_hops += (pr.hop_t_ns == p["hop_t_ns"] and pr.hop_now_u == p["hop_now_u"]
                      and pr.hop_deadline_u == p["hop_deadline_u"])
        # DEV and Dev Hop for EVERY outcome (delivered, dropped at the ingress or in transit)
        same_dev += (pr.dev, pr.dev_hop) == (p["dev"], p["dev_hop"])
        if p["outcome"] == "drop_link_down" and p["link_down_hop"] == 0:
            ingress_dev_quirk += 1
        if p["outcome"] == "delivered" and pr.outcome == "delivered":
            delivered_both += 1
            same_dev_delivered += (pr.dev, pr.dev_hop) == (p["dev"], p["dev_hop"])
            d = p["latency_ns"] - pr.prop_ns                # ns-3 minus light time only
            lat_diff.append(d)
            links = len(p["taken_path"]) - 1
            queue_ns.append(d - links * pr.ser_ns)          # what is left after serialization
            row = rb.row_at(p["flow_id"], p["send_ns"])
            sched_diff.append(p["latency_ns"] - sum(row.predicted))
            hold_err.extend(pr.hop_hold_err_ns)
        if (not ok_path or not ok_out) and len(examples) < max_examples:
            examples.append({"flow": p["flow_id"], "seq": p["seq"], "send_ns": p["send_ns"],
                             "ns3": [p["taken_path"], p["outcome"], p["outcome_node"]],
                             "python": [pr.taken, pr.outcome, pr.outcome_node]})
    q = np.asarray(queue_ns, dtype=np.int64)
    frac = (lambda k: (k / n) if n else None)
    return {
        "probes_compared": n,
        "path_identical": same_path, "path_identical_frac": frac(same_path),
        "outcome_identical": same_outcome, "outcome_identical_frac": frac(same_outcome),
        "first_late_hop_identical": same_late,
        "link_down_hop_identical": same_linkdown,
        "per_hop_time_clock_deadline_identical": same_hops,
        "delivered_by_both": delivered_both,
        "dev_and_dev_hop_identical": same_dev,
        "dev_and_dev_hop_identical_delivered": same_dev_delivered,
        "ingress_link_down_drops": ingress_dev_quirk,
        "latency_minus_light_time_ns": _quantiles(lat_diff),
        "residual_after_serialization_ns": _quantiles(queue_ns),
        "residual_zero": int((q == 0).sum()) if q.size else 0,
        "residual_positive": int((q > 0).sum()) if q.size else 0,
        "residual_negative": int((q < 0).sum()) if q.size else 0,
        "latency_minus_schedule_prediction_ns": _quantiles(sched_diff),
        "held_vs_interpolated_light_time_ns_per_hop": _quantiles(hold_err),
        "serialization_ns_per_hop": sorted({tx_time_ns(wire_bytes(h, payload_bytes), rate_bps)
                                            for h in {p["num_hops"] for p in packets if p["num_hops"]}}),
        "mismatch_examples": examples,
    }


# ======================================================================= summaries

def _phase_of(send_ns, start_ns, stop_ns):
    return "before" if send_ns < start_ns else "during" if send_ns < stop_ns else "after"


def flow_summary(packets, flows, fault_start_ns, fault_stop_ns, run_label):
    """One row per flow: PDR, latency, drops, fraction flagged per fault phase.

    flows: {flow_id: (src name, dst name)}. "flagged" = the probe reached its
    destination with DEV set by a deadline check (policy continue keeps late
    probes going; probes that lose their link are dropped, so a delivered DEV
    is always a deadline miss). The fraction is over probes DELIVERED in that
    phase (by send time): that is what the receiving end can see.
    """
    rows = []
    for f in sorted(flows):
        ps = [p for p in packets if p["flow_id"] == f]
        lat = [p["latency_ns"] for p in ps if p["outcome"] == "delivered"]
        row = {"run": run_label, "flow_id": f, "src": flows[f][0], "dst": flows[f][1],
               "sent": len(ps), "delivered": len(lat),
               "pdr": round(len(lat) / len(ps), 6) if ps else None,
               "latency_p50_ms": None, "latency_p99_ms": None,
               "latency_min_ms": None, "latency_max_ms": None}
        if lat:
            a = np.asarray(lat, dtype=np.float64) / NS_PER_MS
            row.update(latency_p50_ms=round(float(np.quantile(a, 0.5, method="lower")), 6),
                       latency_p99_ms=round(float(np.quantile(a, 0.99, method="lower")), 6),
                       latency_min_ms=round(float(a.min()), 6),
                       latency_max_ms=round(float(a.max()), 6))
        for o in ("drop_link_down", "drop_iface_down", "drop_queue", "drop_other", "no_route",
                  "send_error", "pending"):
            row[o] = sum(1 for p in ps if p["outcome"] == o)
        for ph in ("before", "during", "after"):
            dl = [p for p in ps if p["outcome"] == "delivered"
                  and _phase_of(p["send_ns"], fault_start_ns, fault_stop_ns) == ph]
            fl = sum(1 for p in dl if p["dev"] == 1)
            row[f"delivered_{ph}"] = len(dl)
            row[f"flagged_{ph}"] = fl
            row[f"flagged_frac_{ph}"] = round(fl / len(dl), 6) if dl else None
        rows.append(row)
    return rows


def margin_summary(packets, unit_ns):
    """How much slack the ON-TIME probes had: deadline minus arrival clock, in units.

    Over delivered probes without DEV (in a no-fault run: all delivered ones):
      final_hop   the margin at the destination (the final, largest deadline)
      min_hop     each probe's smallest margin over its hops, i.e. the tightest
                  deadline on its path, and at which hop it sits
    A fault is only seen if it delays a probe by more than these margins
    (spec section 6 step 2: late = clock past the deadline). Units are the
    header's deadline unit (unit_ns); _ms values are exact multiples of it.
    """
    on_time = [p for p in packets if p["outcome"] == "delivered" and p["dev"] == 0 and p["hop_margin_u"]]
    final = [p["hop_margin_u"][-1] for p in on_time]
    tight = [min(p["hop_margin_u"]) for p in on_time]
    where = {}
    for p in on_time:
        k = p["hop_margin_u"].index(min(p["hop_margin_u"])) + 1        # hop index, first if tied
        where[str(k)] = where.get(str(k), 0) + 1
    to_ms = (lambda q: {k: (None if v is None else v * unit_ns / NS_PER_MS) for k, v in q.items()})
    return {
        "probes": len(on_time), "unit_ns": unit_ns,
        "final_hop_margin_units": _quantiles(final), "final_hop_margin_ms": to_ms(_quantiles(final)),
        "min_hop_margin_units": _quantiles(tight), "min_hop_margin_ms": to_ms(_quantiles(tight)),
        "hop_of_min_margin": dict(sorted(where.items(), key=lambda kv: int(kv[0]))),
        "note": "deadline minus the node's unit clock at arrival, on-time delivered probes only",
    }


def drop_causes(rb, packets):
    """Which kind of link the link-down losses were on.

    For drop_link_down the dead link is (node that held the probe, its next
    planned node); for drop_iface_down it is (last node that sent it, the node
    whose interface was down). Ground links are split into the uplink (the
    source station's first hop) and the downlink (the last hop to the
    destination station). Returns {"<outcome>/<isl|gsl-up|gsl-down>": count}.
    """
    out = {}
    for p in packets:
        if p["outcome"] == "drop_link_down":
            u = p["outcome_node"]
            plan = p["planned_path"]
            v = plan[plan.index(u) + 1]
        elif p["outcome"] == "drop_iface_down":
            u, v = p["taken_path"][-1], p["outcome_node"]
        else:
            continue
        kind = rb.link_of[(u, v)][0]
        if kind == "gsl":
            kind = "gsl-up" if rb.node_kind[u] == "gs" else "gsl-down"
        key = f"{p['outcome']}/{kind}"
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def detection(fault_packets, nofault_packets, fault_start_ns, fault_stop_ns):
    """Detection of the slowed link: fault run vs the paired no-fault run (same seed).

    Probes "on the slowed link during the fault" = fault-run probes that
    crossed the faulted laser link (were carried across it) and reached its
    near end in [start, stop). detection = the share of them that a node
    flagged as late. baseline = the share of the SAME probes (flow, seq) that
    were flagged in the no-fault run, where the link was never slowed: the
    false-alarm rate of the deadline check itself.
    """
    key = lambda p: (p["flow_id"], p["seq"])
    in_window = lambda p: (p["fault_link_t_ns"] is not None
                           and fault_start_ns <= p["fault_link_t_ns"] < fault_stop_ns)
    crossed = [p for p in fault_packets if p["fault_link"] == "crossed" and in_window(p)]
    entered = [p for p in fault_packets if p["fault_link"] and in_window(p)]
    flagged = [p for p in crossed if p["first_late_hop"] is not None]
    base_of = {key(p): p for p in nofault_packets}
    paired = [base_of[key(p)] for p in crossed if key(p) in base_of]
    base_flagged = [p for p in paired if p["first_late_hop"] is not None]
    base_crossed = [p for p in paired if p["fault_link"] == "crossed"]
    # false alarms anywhere: flagged probes in the no-fault run, and flagged
    # probes of the fault run that never touched the slowed link in the window
    fa_nofault = sum(1 for p in nofault_packets if p["first_late_hop"] is not None)
    fa_fault_elsewhere = sum(1 for p in fault_packets
                             if p["first_late_hop"] is not None and not (p["fault_link"] == "crossed"))
    first_flag = min((p["hop_t_ns"][p["first_late_hop"] - 1] for p in flagged), default=None)
    per_flow = {}
    for p in crossed:
        d = per_flow.setdefault(p["flow_id"], {"crossed": 0, "flagged": 0})
        d["crossed"] += 1
        d["flagged"] += p["first_late_hop"] is not None
    margins = [p["hop_margin_u"][p["first_late_hop"] - 1] for p in flagged]
    return {
        "fault_window_ns": [fault_start_ns, fault_stop_ns],
        "probes_entering_slowed_link": len(entered),
        "probes_lost_in_its_queue": sum(1 for p in entered if p["fault_link"] == "queue_drop"),
        "probes_crossing_slowed_link": len(crossed),
        "flagged_late": len(flagged),
        "detection_rate": (len(flagged) / len(crossed)) if crossed else None,
        "baseline_same_probes_no_fault": len(paired),
        "baseline_same_probes_crossed_no_fault": len(base_crossed),
        "baseline_flagged": len(base_flagged),
        "baseline_false_alarm_rate": (len(base_flagged) / len(paired)) if paired else None,
        "false_alarms_no_fault_run_all_probes": fa_nofault,
        "flagged_without_crossing_in_fault_run": fa_fault_elsewhere,
        "first_detection_after_fault_start_ms": (None if first_flag is None
                                                 else (first_flag - fault_start_ns) / NS_PER_MS),
        "late_margin_units_at_detection": _quantiles(margins),
        "per_flow": {str(f): v for f, v in sorted(per_flow.items())},
    }


# ======================================================================= pcap

def read_pcap(path):
    """(linktype, nanosecond?, [(ts_ns, bytes)]) of a classic pcap file (.pcap or .pcap.gz)."""
    data = Path(path).read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    magic = struct.unpack("<I", data[:4])[0]
    if magic == 0xA1B23C4D:
        endian, nano = "<", True
    elif magic == 0xA1B2C3D4:
        endian, nano = "<", False
    elif magic == 0x4D3CB2A1:
        endian, nano = ">", True
    elif magic == 0xD4C3B2A1:
        endian, nano = ">", False
    else:
        raise ValueError(f"{path}: not a pcap file")
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    frames, off = [], 24
    while off + 16 <= len(data):
        sec, frac, incl, _orig = struct.unpack(endian + "IIII", data[off:off + 16])
        off += 16
        frames.append((sec * 10**9 + (frac if nano else frac * 1000), data[off:off + incl]))
        off += incl
    return linktype, nano, frames


def parse_probe_frame(frame, linktype):
    """IPv6 destination, Segments Left, Flags, Dev Hop and probe id of an ns-3 probe frame."""
    if linktype == 9:              # DLT_PPP: 2-byte protocol, 0x0057 = IPv6
        if frame[:2] != b"\x00\x57":
            return None
        ip = frame[2:]
    elif linktype == 101:
        ip = frame
    else:
        raise ValueError(f"link type {linktype} not supported")
    if len(ip) < 40 or ip[0] >> 4 != 6 or ip[6] != 43:
        return None
    rh = ip[40:]
    if len(rh) < 12 or rh[2] != tcrh_mod.ROUTING_TYPE_TCRH:
        return None
    rh_len = (rh[1] + 1) * 8
    udp = rh[rh_len:]
    payload = udp[UDP_BYTES:]
    pid = struct.unpack(">I", payload[4:8])[0] if payload[:4] == b"CRT1" else None
    return {"dst": ip[24:40], "sl": rh[3], "flags": rh[4], "num_hops": rh[5], "dev_hop": rh[6],
            "epoch_base": struct.unpack(">I", rh[8:12])[0], "pid": pid}


def pcap_semantics(path, t0_unix_ns, fault_start_ns=None, fault_stop_ns=None):
    """Checks on the capture that tshark's validity check does not make.

    * every frame is a T-CRH probe frame;
    * along each probe's frames in time order Segments Left strictly
      decreases (the capture nodes are visited in path order);
    * frames carrying DEV: how many fall inside the fault window (capture
      time, simulation clock) and how many outside it.
    """
    linktype, nano, frames = read_pcap(path)
    by_pid, bad, dev_in, dev_out = {}, 0, 0, 0
    for ts, raw in frames:
        f = parse_probe_frame(raw, linktype)
        if f is None or f["pid"] is None:
            bad += 1
            continue
        t_sim = ts - t0_unix_ns
        by_pid.setdefault(f["pid"], []).append((t_sim, f["sl"]))
        if f["flags"] & tcrh_mod.FLAG_DEV:
            inside = (fault_start_ns is not None and fault_start_ns <= t_sim)
            # a probe flagged in the window may still be on its way shortly after it
            inside = inside and t_sim < (fault_stop_ns or 0) + 2_000 * NS_PER_MS
            dev_in += inside
            dev_out += not inside
    not_decreasing = 0
    multi = 0
    for pid, seq in by_pid.items():
        seq.sort()
        if len(seq) > 1:
            multi += 1
        if any(b[1] >= a[1] for a, b in zip(seq, seq[1:])):
            not_decreasing += 1
    return {"linktype": linktype, "nanosecond": nano, "frames": len(frames),
            "non_probe_frames": bad, "probes": len(by_pid), "probes_seen_at_2plus_nodes": multi,
            "probes_with_sl_not_strictly_decreasing": not_decreasing,
            "dev_frames_in_fault_window": dev_in, "dev_frames_outside_fault_window": dev_out}


def run_check_pcap(repo_dir, pcap_path, timebase_arg="utc"):
    """Run tools/wireshark/check_pcap.sh; (exit code, summary dict, full stdout)."""
    script = Path(repo_dir) / "tools" / "wireshark" / "check_pcap.sh"
    proc = subprocess.run(["bash", str(script), "--timebase", timebase_arg, "--quiet", str(pcap_path)],
                          capture_output=True, text=True, check=False)
    summary = {}
    for line in proc.stdout.splitlines():
        if line.startswith("check_pcap:") and "T-CRH frames" in line:
            # "check_pcap: X: N T-CRH frames, I invalid, D with DEV, L late at capture"
            tail = line.rsplit(": ", 1)[1]
            for part in tail.split(", "):
                num, _, what = part.partition(" ")
                summary[what] = int(num)
    return proc.returncode, summary, proc.stdout + proc.stderr


# ======================================================================= CLI

def _cmd_crosscheck(args):
    rb = load_replay_bundle(args.bundle)
    packets = read_packets(args.packets)
    res = crosscheck(rb, packets, payload_bytes=args.payload)
    json.dump(res, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if res["path_identical"] == res["probes_compared"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m chronoroute.export.ns3_crosscheck",
                                 description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crosscheck", help="compare an ns-3 packets.csv with the Python prediction")
    c.add_argument("bundle")
    c.add_argument("packets")
    c.add_argument("--payload", type=int, default=DEFAULT_PAYLOAD)
    c.set_defaults(func=_cmd_crosscheck)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

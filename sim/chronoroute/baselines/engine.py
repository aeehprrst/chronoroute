"""
engine.py
---------
SchemeEngine: one run of ONE scheme on top of the simulator v2 engine
(fwd/engine.py). It is a subclass, so every packet of every scheme goes
through the very same code for what is physics or shared infrastructure:

    send times and packet ids     Engine._sends_in (same keyed draws)
    processing, jitter, node Δ     Engine._transmit
    FIFO queues, rate cuts, ARQ    Engine._enqueue / fwd.queues.LinkQueue
    light time per 100 ms step     Engine geometry cache (fwd.topology)
    losses in flight, node down    the same checks as Engine._on_arrive
    outputs                        Engine._finish (packets.csv, trace/1, counts)

What a scheme changes is only the routing decision and what its control
plane knows (knowledge.py). Three data planes:

  crh      chronoroute, crh16, e2e, lq. The engine's own byte path: SIDs of
           the ground's planned path in a T-CRH, spec section 6 on the bytes.
             chronoroute  unchanged (deadline check at every hop; policy and
                          fallback from the run config), plus FB1 feedback.
             crh16        the same path and fallback, deadline check removed
                          (the hop function is called with the packet's own
                          Epoch_Base as "now", which can never be late), and the
                          wire size of an RFC 9631 CRH-16 header.
             e2e          the same, but the deadline is checked only at the
                          destination (its final deadline D_h = the end-to-end
                          budget); late packets are reported to the ground.
             lq           crh16 plus a local monitor: before using a link the
                          node looks at its OWN transmit queue (and the ARQ
                          retransmissions of its recent packets on that link);
                          above q_th it flags the packet, or detours.
  oracle   o_t, o_q. A source route chosen at send time by an oracle on the
           TRUE network (O-T: topology incl. failures; O-Q: also queues and
           slowness); if a link of it dies on the way, the oracle re-plans
           from where the packet is.
  table    snap, ls_h, ls_d. Hop-by-hop forwarding tables computed from the
           scheme's belief (knowledge.py); no routing header.

The engine's private method names used here (_on_send, _on_arrive, _transmit,
_enqueue, _link_drop, _finish, _lost, _plan_interval, _check_delivery, geo, port,
port_to, queue, _sends_in) are the extension points; a request to the engine owner
asks to keep them stable (docs/baselines.md, "Engine hooks").
"""

import math
import time
from collections import deque

from ..fwd.engine import (Engine, Packet, NOPOS, HOPS_PER_PACKET_INDEX, IPV6, UDP, K_SEND)
from ..fwd.hop import fast_process
from ..fwd.fallback import grid_detour
from ..fwd.queues import ser_ns
from ..proto import sizes
from ..topo import geometry
from . import control as ctl
from .feedback import PenaltyBook, plan_with_penalties, path_isls, intersect_links
from .knowledge import (Truth, OracleTopology, SnapKnowledge, CrhStateUploads, LinkState, LinkStateDelay,
                        arq_expected_ns)
from .params import DATA_PLANE, HEADER, MS, S, to_ns
from .paths import lazy_path

V_MAX_KM_S = 16.0               # bound on the range rate of any two nodes (2 x LEO orbital speed)
C_KM_PER_S = 299_792.458
SCHEDULE_ROW_BYTES = 16          # flow id, valid from / to, row id (MODELLED)
# CRH-FIB entry (SID 2 + interface 2), TLE-sized element set (two 69-character lines plus
# line ends) and station coordinates (3 x 32 bit) are scheme parameters now:
# params.DEFAULTS["crh_state"] (fib_entry_bytes 4, tle_bytes 140, gs_coord_bytes 12).


def step_tolerance_ns(step_ns):
    """Largest change of one link's light time from one step to the next (+2 ns rounding).

    The distance between two nodes changes at most at their relative speed, below
    16 km/s for anything in LEO (two satellites at <= 7.9 km/s each); each held delay
    is rounded to the nearest ns, so two of them can differ by 1 ns more.
    """
    return int(math.ceil(V_MAX_KM_S * step_ns / C_KM_PER_S)) + 2


class SPacket(Packet):
    """Packet with the extra bookkeeping the baselines and the evaluation need."""

    __slots__ = ("arr_ns", "hprop", "hopk", "route", "ridx", "lq", "lq_n", "e2e_late", "drop_next", "hdr",
                 "ld_event", "tx", "qw", "txloss")

    def __init__(self, pkt, flow, seq, send_ns):
        super().__init__(pkt, flow, seq, send_ns)
        self.arr_ns = []          # arrival time at path[1:], aligned with it
        # per transmission (aligned with arr_ns): when it started to leave the upstream node, and
        # how long it waited for the transmitter. A link fault acts at the transmission start
        # (link delta, ARQ, the rate in force), so exposure is judged at that instant.
        self.tx = []
        self.qw = []
        self.hprop = []           # light time of each hop's link at the step of the upstream arrival
        # per arrival, what spec 6 did there (crh data plane; offline re-scoring needs it):
        #   k >= 1   the node ran spec 6 on a non-GREEDY packet with hop index k (deadline check)
        #   -2 - k   the destination of a GREEDY packet ran spec 6 (hop index k, no check: DEV set)
        #   -1       no spec 6 (detour transit node, packet lost on arrival, table schemes)
        self.hopk = []
        self.route = None         # oracle source route (node list) and the index of the current node
        self.ridx = 0
        self.lq = None            # first LQ flag: (hop index, node, next node, t)
        self.lq_n = 0
        self.e2e_late = False
        self.drop_next = -1
        self.hdr = None           # routing-header bytes on the wire (set at the first transmission)
        self.ld_event = None      # (node, dead next node, t): first dead next link met (table / oracle)
        # (node, next node, t, wait) when the packet was LOST AT THE TRANSMITTER of node -> next
        # (buffer_overflow, arq_exhausted, a link end without a position): its path ends at node, so
        # this is the only record of the link it was lost at (Engine._link_drop; eval/metrics.py)
        self.txloss = None


class _VetoFaults:
    """The run's FaultSet, plus a one-decision 'veto': LQ's detour treats one link as unusable
    for the node deciding right now (so the engine's own step 7 / fallback logic runs)."""

    def __init__(self, inner):
        self._inner = inner
        self.veto = None

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def link_is_down(self, li, a, b, t):
        v = self.veto
        if v is not None and v[0] == li and v[1] == a:
            return True
        return self._inner.link_is_down(li, a, b, t)


def _no_deadline(raw, now_u, policy):
    """spec 6 without the deadline check: 'now' = the packet's own Epoch_Base, never late."""
    return fast_process(raw, (raw[8] << 24) | (raw[9] << 16) | (raw[10] << 8) | raw[11], policy)


def _dest_only(raw, now_u, policy):
    """E2E: only the final endpoint (SL = 0 on arrival) checks its deadline (= D_h)."""
    if len(raw) >= 12 and raw[3] == 0:
        return fast_process(raw, now_u, policy)
    return _no_deadline(raw, now_u, policy)


def header_bytes(kind, n_hops, encap, deadline_bytes=8):
    if kind == "none":
        return 0
    if kind == "tcrh":
        h = sizes.tcrh_size(n_hops)
    elif kind == "crh16":
        h = sizes.crh16_size(n_hops)
    elif kind == "e2e":
        h = sizes.pad8(sizes.CRH_FIXED_BYTES + sizes.CRH16_SID_BYTES * n_hops + deadline_bytes)
    else:
        raise ValueError(kind)
    return h + (IPV6 if encap else 0)


class SchemeEngine(Engine):
    """One run of one scheme (module docstring)."""

    def __init__(self, scenario, scheme, *, trace=None, packets_csv=None, pcap_frames=None, extras=None):
        super().__init__(scenario, trace=trace, packets_csv=packets_csv, pcap_frames=pcap_frames)
        self.scheme = scheme
        self.sname = scheme["name"]
        self.plane = DATA_PLANE[self.sname]
        self.hdr_kind = HEADER[self.sname]
        self.extras = extras
        self.ledger = ctl.Ledger()
        self.real_faults = self.faults
        self.truth = Truth(self, self.real_faults)
        self.step_tol = step_tolerance_ns(self._step_ns)
        self.stretch_on = scheme["outputs"]["stretch_oracle"]
        self.kn = None
        self.lq_stats = {"flags": 0, "packets_flagged": 0, "detours": 0}
        self.fb_stats = {"reports": 0, "suppressed": 0, "late_events": 0}
        self.e2e_stats = {"late": 0, "reports": 0}
        self.penalties = None
        self._last_report = {}
        self._late_paths = deque()
        self.oracle_stats = {"replans": 0, "dijkstra": 0}
        self._transit_l = self.truth.transit.tolist()
        self._has_down = bool(self.real_faults.link_down or self.real_faults.node_down)
        n = self.sname
        if n == "crh16":
            self._fp = _no_deadline
        elif n == "e2e":
            self._fp = _dest_only
        elif n == "lq":
            self._fp = _no_deadline
            lq = scheme["lq"]
            self.lq_th = to_ns(lq["q_th_ms"], MS)
            self.lq_detour = lq["action"] == "detour"
            self.lq_win = to_ns(lq["arq_window_ms"], MS)
            self._arq_hist = {}
            if self.lq_detour:
                # the veto changes a DECISION, so it wraps what the nodes see (Engine.seen)
                self.seen = _VetoFaults(self.seen)
                self._link_faults = True
        # satellite state uploads of the crh data plane (reviewer must-fix #3)
        self.crh_up = CrhStateUploads(self, self.truth, scheme, self.ledger) if self.plane == "crh" else None
        self._count_crh = self.crh_up is not None and scheme["crh_state"]["count"]
        if n == "chronoroute" and scheme["feedback"]["mode"] == "fb1":
            fb = scheme["feedback"]
            self.penalties = PenaltyBook(self.sc.refresh_ms * MS, to_ns(fb["hold_s"], S), fb["penalty"])
            self.fb_delay = to_ns(fb["delay_ms"], MS)
            self.fb_min = to_ns(fb["min_interval_ms"], MS)
            self.fb_bytes = fb["report_bytes"]
        if n == "e2e" and scheme["e2e"]["feedback"]:
            e = scheme["e2e"]
            self.penalties = PenaltyBook(self.sc.refresh_ms * MS, to_ns(e["hold_s"], S), e["penalty"])
            self.e2e_delay = to_ns(e["report_delay_ms"], MS)
            self.e2e_window = to_ns(e["window_s"], S)
        if n == "o_t":
            self.kn = OracleTopology(self.truth)
        elif n == "snap":
            self.kn = SnapKnowledge(self, self.truth, scheme, self.ledger)
        elif n == "ls_h":
            self.kn = LinkState(self, self.truth, scheme, self.ledger)
        elif n == "ls_d":
            self.kn = LinkStateDelay(self, self.truth, scheme, self.ledger)
        if self.plane in ("oracle", "table"):
            # instance attributes shadow the class methods; Engine.run reads self._on_arrive
            self._on_arrive = self._arrive_table
            self._on_send = self._send_table

    # ------------------------------------------------------------ packets
    def _plan_interval(self, start_ms, end_ms):
        """Plans (crh data plane only, with FB1 / E2E penalties) and the sends of one interval.

        The same as Engine._plan_interval (same send times, same packet ids in (time, flow)
        order) except that packets are SPackets and the planner may see penalties.
        """
        lo, hi = start_ms * 1_000_000, end_ms * 1_000_000
        sends = []
        t0 = time.perf_counter()
        if self._count_crh:
            # satellite state uploads due by now (they never change a packet: bytes only; done
            # here, once a refresh interval, while the topology of these steps is still cached)
            self.crh_up.advance(lo)
        if self.plane == "crh":
            pen = self.penalties.active(lo) if self.penalties is not None else {}
            csr_cache = {}
            for f in self.sc.flows:
                if pen:
                    e = plan_with_penalties(self.sc, f, start_ms, end_ms, pen)
                else:
                    e = self.sc.plan(f, start_ms, end_ms, csr_cache)
                self.current[f.flow_id] = (e, start_ms)
                self.schedule_rows.append((f.flow_id, start_ms, end_ms, e))
                if e is not None:
                    # the ground hands the row (T-CRH template) to the ingress gateway
                    self.ledger.add("ground", "schedule_row",
                                    IPV6 + UDP + SCHEDULE_ROW_BYTES + len(e.template))
        for f in self.sc.flows:
            for t in self._sends_in(f, lo, hi):
                sends.append((t, f.flow_id))
        self.timing["plan_s"] = self.timing.get("plan_s", 0.0) + time.perf_counter() - t0
        sends.sort()
        seqs = self._flow_seq
        for t, fid in sends:
            p = SPacket(self.npkt, fid, seqs[fid], t)
            seqs[fid] += 1
            self.npkt += 1
            self._push(t, p.pkt, K_SEND, p, 0, 0, None)

    def _wire_ref(self, flow):
        """Packet size without any routing header: the reference size for latency stretch."""
        return self.l2 + IPV6 + UDP + flow.payload_bytes

    def _record_arrival(self, p, t, inport):
        up_t = p.arr_ns[-1] if p.arr_ns else p.send_ns
        k_up = up_t // self._step_ns
        if k_up >= self._n_steps:
            k_up = self._n_steps - 1
        v = self.geo(inport.li, k_up)
        p.hprop.append(v if v >= 0 else (-1 if v == NOPOS else -1 - v))
        p.arr_ns.append(t)
        raw = p.raw
        if raw is None or len(raw) < 12:
            p.hopk.append(-1)
        elif not p.greedy:
            p.hopk.append(raw[5] - raw[3])
        elif inport.nxt == p.dest:
            p.hopk.append(-2 - (raw[5] - raw[3]))
        else:
            p.hopk.append(-1)

    # ------------------------------------------------------------ crh data plane hooks
    def _transmit(self, p, port, t):
        if p.hdr is None:
            # first transmission: the wire carries this scheme's header, not the internal T-CRH
            n_hops = p.raw[5] if p.raw is not None else 0
            if self.plane == "crh":
                h = header_bytes(self.hdr_kind, n_hops, self.encap, self.scheme["e2e"]["deadline_bytes"])
                p.wire += h - (len(p.raw) + (IPV6 if self.encap else 0))
                p.hdr = h
            else:
                p.hdr = 0
        Engine._transmit(self, p, port, t)

    def _enqueue(self, p, port, t_ready):
        if self.sname == "lq" and self.faults.arq:
            self._arq_record(p, port, t_ready)
        res = Engine._enqueue(self, p, port, t_ready)
        if res is not None:                       # an arrival was scheduled: record this transmission
            p.tx.append(res[0])
            p.qw.append(res[0] - t_ready)
        return res

    def _link_drop(self, p, port, t, t_attempt, wait_ns, reason):
        """Record the link the packet was lost at (and when), then the engine finishes it."""
        p.txloss = (port.node, port.nxt, t_attempt, wait_ns)
        Engine._link_drop(self, p, port, t, t_attempt, wait_ns, reason)

    def _arq_record(self, p, port, t):
        """The sender's own retransmission counter (same keyed draws as Engine._enqueue)."""
        arq = self.real_faults.arq_params(port.li, t)
        if arq is None:
            return
        loss, retries, retry_ns = arq
        base = (p.seq * HOPS_PER_PACKET_INDEX + p.hops) * 4
        lossf = float(loss)
        a = retries
        for i in range(retries + 1):
            if self.rng.uniform("arq", (p.flow,), base + i) >= lossf:
                a = i
                break
        g = self.geo(port.li, min(t // self._step_ns, self._n_steps - 1))
        prop = g if g >= 0 else (-1 - g if g != NOPOS else 0)
        dq = self._arq_hist.setdefault((port.node, port.nxt), deque())
        dq.append((t, a * (2 * prop + retry_ns)))

    def _lq_monitor(self, node, port, t):
        """What node sees about its link: own queue wait + recent mean ARQ delay (ns)."""
        x = port.q.queue_delay_estimate(t)
        dq = self._arq_hist.get((node, port.nxt)) if self.faults.arq else None
        if dq:
            while dq and dq[0][0] < t - self.lq_win:
                dq.popleft()
            if dq:
                x += sum(v for _t, v in dq) // len(dq)
        return x

    def _lq_check(self, p, node, t, next_sid):
        port = self.port(node, next_sid)
        if port is None:
            return
        if self._lq_monitor(node, port, t) > self.lq_th:
            self.lq_stats["flags"] += 1
            p.lq_n += 1
            if p.lq is None:
                p.lq = (p.hops, node, port.nxt, t)
                self.lq_stats["packets_flagged"] += 1
            if self.lq_detour:
                self.seen.veto = (port.li, node)
                self.lq_stats["detours"] += 1

    def _on_send(self, p, t):
        """crh data plane: the engine's ingress, plus LQ's look at the first link."""
        if self.sname == "lq":
            entry = self.current.get(p.flow, (None, None))[0]
            if entry is not None:
                tpl = entry.template
                off = 12 + 3 * (tpl[5] - 1)
                self._lq_check(p, self.sc.flows[p.flow].src_node, t, (tpl[off] << 8) | tpl[off + 1])
            Engine._on_send(self, p, t)
            if self.lq_detour:
                self.seen.veto = None
            return
        Engine._on_send(self, p, t)

    def _on_arrive(self, p, t, frm, node, inport):
        """crh data plane: record the hop, LQ / FB1 hooks around the engine's own processing."""
        self._record_arrival(p, t, inport)
        n = self.sname
        if n == "lq":
            raw = p.raw
            if not p.greedy and raw is not None and raw[3] > 0 and not self._lost_on_arrival(node, t, inport):
                off = 12 + 3 * (raw[3] - 1)
                self._lq_check(p, node, t, (raw[off] << 8) | raw[off + 1])
            Engine._on_arrive(self, p, t, frm, node, inport)
            if self.lq_detour:
                self.seen.veto = None
            return
        if self.penalties is not None and n == "chronoroute":
            before = p.first_late
            Engine._on_arrive(self, p, t, frm, node, inport)
            if before is None and p.first_late is not None:
                self._fb1_report(p, t)
            return
        Engine._on_arrive(self, p, t, frm, node, inport)

    def _lost_on_arrival(self, node, t, inport):
        """The engine's own loss-on-arrival rules (node down, link died in flight)."""
        if self._node_faults and node < self.topo.n_sats and self.real_faults.node_is_down(node, t):
            return True
        k = min(t // self._step_ns, self._n_steps - 1)
        return self.geo(inport.li, k) < 0 or (self._link_only_faults and
                                             self.real_faults.link_down_only(inport.li, t))

    def _fb1_report(self, p, t):
        k = p.first_late
        if k < 1 or k >= len(p.path):
            return
        a, b = p.path[k - 1], p.path[k]
        li = self.topo.link_index.get((a, b))
        if li is None:
            return
        self.fb_stats["late_events"] += 1
        last = self._last_report.get((b, li))
        if last is not None and t - last < self.fb_min:
            self.fb_stats["suppressed"] += 1
            return
        self._last_report[(b, li)] = t
        self.fb_stats["reports"] += 1
        self.penalties.report(t + self.fb_delay, [li])
        self.ledger.add("downlink", "fb1_report", self.fb_bytes)
        tr = self.truth
        h = tr.hops_to_ground(tr.step_of(t), tr.seg(t))[b]
        if h and h > 1:
            self.ledger.add("isl", "fb1_report_relay", self.fb_bytes * (h - 1), h - 1)

    # ------------------------------------------------------------ oracle and table data planes
    def _send_table(self, p, t):
        fid = p.flow
        flow = self.sc.flows[fid]
        src = flow.src_node
        self.counts["sent"] += 1
        self.per_flow[fid]["sent"] += 1
        p.path.append(src)
        p.sampled = self.rng.uniform("sample", (fid,), p.seq) < self.sample_p
        p.check = self.inv_level == "all" or (self.inv_level == "sample" and p.seq % self.inv_every == 0)
        if p.check:
            self.inv["checked_packets"] += 1
        tracer = self.trace if (self.trace is not None and (self.trace_all or p.sampled)) else None
        k = min(t // self._step_ns, self._n_steps - 1)
        if self.plane == "oracle":
            route = self._oracle_route(p, src, flow.dst_node, t, k)
            if route is None:
                if tracer:
                    tracer.event(t, "send", p.pkt, fid, src, None, None, None, None, self.clock_u(t), None, None)
                self._finish(p, t, src, "no_route", "no_route")
                return
            p.route, p.ridx = route, 0
            hdr = header_bytes(self.hdr_kind, len(route) - 1, self.encap)
        else:
            hdr = 0
        p.wire = self._wire_ref(flow) + hdr
        p.hdr = hdr
        nxt, why, det = self._decide(p, src, flow.dst_node, t, k, -1)
        if tracer:
            self._trace_decision(tracer, "send", p, src, t, nxt, det, self.clock_u(t))
        if nxt is None:
            if why == "no_fib_entry":
                # the ingress has no table entry for the destination: like a planner gap, the
                # packet is never transmitted (outcome no_route, comparable across schemes)
                self._finish(p, t, src, "no_route", "no_route")
            else:
                self._finish(p, t, src, "dropped", why)
            return
        p.prev = src
        self._transmit(p, self.port_to(src, nxt), t)

    def _arrive_table(self, p, t, frm, node, inport):
        self.hop_events += 1
        self._record_arrival(p, t, inport)
        k = t // self._step_ns
        if k >= self._n_steps:
            k = self._n_steps - 1
        if self._node_faults and node < self.topo.n_sats and self.real_faults.node_is_down(node, t):
            self._lost(p, t, node, "node_down")
            return
        if inport.c != k // self._cs:
            self._port_geo(inport, k)
        if inport.enc[k - inport.k0] < 0 or (self._link_only_faults and
                                              self.real_faults.link_down_only(inport.li, t)):
            self._lost(p, t, node, "in_flight_link_down")
            return
        p.path.append(node)
        now_u = self.clock_u(t)
        p.arr_u.append(now_u)
        dest = self.sc.flows[p.flow].dst_node
        tracer = self.trace if (self.trace is not None and (self.trace_all or p.sampled)) else None
        if node == dest:
            if tracer:
                tracer.event(t, "hop", p.pkt, p.flow, node, None, None, None, None, now_u, None, None)
            self._finish(p, t, node, "delivered")
            return
        if p.route is not None:
            p.ridx += 1
        nxt, why, det = self._decide(p, node, dest, t, k, frm)
        if tracer:
            self._trace_decision(tracer, "hop", p, node, t, nxt, det, now_u)
        if nxt is None:
            self._finish(p, t, node, "dropped", why)
            return
        p.prev = node
        self._transmit(p, self.port_to(node, nxt), t)

    def _lost(self, p, t, node, reason):
        if p.hopk and len(p.hopk) == len(p.path):
            p.hopk[-1] = -1                   # recorded on arrival, but spec 6 never ran here
        p.path.append(node)
        if self.trace is not None and (self.trace_all or p.sampled):
            raw = p.raw
            self.trace.event(t, "hop", p.pkt, p.flow, node, None, raw[3] if raw else None,
                             raw[4] if raw else None, None, self.clock_u(t), None,
                             raw.hex() if (raw and p.sampled) else None)
        self._finish(p, t, node, "dropped", reason)

    def _usable(self, li, a, b, t, k):
        """Oracle: the TRUE state of the link (an oracle knows failures instantly, by definition)."""
        if self.geo(li, k) < 0:
            return False
        return not (self._has_down and self.real_faults.link_is_down(li, a, b, t))

    def _usable_seen(self, li, a, b, t, k):
        """A real node (SNAP): what it has NOTICED, carrier_detect after a failure (Engine.seen)."""
        if self.geo(li, k) < 0:
            return False
        return not (self._has_down and self.seen.link_is_down(li, a, b, t))

    def _decide(self, p, node, dest, t, k, frm):
        """(next node, drop reason, detoured) for the oracle and table data planes.

        next node None = drop with that reason; detoured True = the node met a dead next
        link and took another one (the caller writes the trace: hop, then fallback).
        """
        n = self.sname
        if self.plane == "oracle":
            route = p.route
            nxt = route[p.ridx + 1]
            li = self.topo.link_index.get((node, nxt))
            if li is not None and self._usable(li, node, nxt, t, k):
                return nxt, None, False
            # a link of the route died after the send: the oracle re-plans from here
            self.oracle_stats["replans"] += 1
            if p.ld_event is None:
                p.ld_event = (node, nxt, t)
            route = self._oracle_route(p, node, dest, t, k)
            if route is None:
                p.drop_next = nxt
                return None, "next_link_down", False
            p.route, p.ridx = route, 0
            return route[1], None, False             # a re-plan, not a fallback (no trace event)
        if n == "snap":
            tr = self.kn.tree(dest, t, k)
        else:
            tr = self.kn.tree(dest, node, t, k)
        if tr.dist[node] is None:
            return None, "no_fib_entry", False
        nxt = tr.nxt[node]
        if n == "snap":
            self.kn.advance(t)
            li = self.topo.link_index[(node, nxt)]
            if not self._usable_seen(li, node, nxt, t, k):
                # SNAP's satellite notices its own dead next hop (after carrier_detect, like every
                # scheme): drop, or +Grid detour (one hop)
                if p.ld_event is None:
                    p.ld_event = (node, nxt, t)
                if self.scheme["snap"]["at_dead_next_hop"] == "drop":
                    p.drop_next = nxt
                    return None, "next_link_down", False
                if p.fb_reason is None:
                    p.fb_reason = "next_link_down"
                    self.fb_reasons["next_link_down"] += 1
                got, info = grid_detour(self.fctx, node, dest, t, k, frm, None)
                if got is None:
                    return None, info, True
                return got, None, True
        return nxt, None, False

    def _trace_decision(self, tracer, ev, p, node, t, nxt, detoured, now_u):
        """send/hop event, then (if the node detoured) the fallback event: trace/1 order."""
        tracer.event(t, ev, p.pkt, p.flow, node, None if detoured else nxt, None, None, None, now_u, None, None)
        if detoured:
            tracer.event(t, "fallback", p.pkt, p.flow, node, nxt, None, None, None, None, "next_link_down", None)

    def _oracle_route(self, p, src, dst, t, k):
        flow = self.sc.flows[p.flow]
        ser = ser_ns(self._wire_ref(flow), self.rate_bps)
        self.oracle_stats["dijkstra"] += 1
        if self.sname == "o_t":
            return self.kn.route(src, dst, t, k, self.processing_ns + ser)
        # O-Q: everything the network really does to a packet right now, on every link
        f = self.real_faults
        jit = int(round(self.jitter_mean)) if self.jitter_mean else 0
        base = self.processing_ns + ser + jit

        def weight(u, v, li):
            g = self.geo(li, k)
            if g < 0 or (self._has_down and f.link_is_down(li, u, v, t)):
                return None
            w = g + base
            if f.node_delay:
                w += f.extra_processing_ns(u, t)
            if f.link_delay:
                w += f.extra_link_ns(li, t)
            if f.arq:
                arq = f.arq_params(li, t)
                if arq is not None:
                    w += arq_expected_ns(arq, g)
            return w + int(self.queue(u, v, li).queue_delay_estimate(t))

        # Geometry plus base service is an exact consistent lower bound: faults
        # and queue waits only add nonnegative cost or remove edges. Cache one
        # reverse tree per geometry step/destination, then preserve the forward
        # search's lowest-predecessor tie rule. Keep the original query order for
        # Poisson background, whose lazy stochastic sampler is outside E1.
        # A* weighs fewer links (fewer queues created on demand): summary.json queues.links_used differs (unread).
        lower = None if self.bg_model == "poisson" else self.truth.tree(k, 0, base, dst).dist
        _cost, path = lazy_path(self.topo.n_nodes, src, dst, lambda u: self.topo.neighbours[u], weight,
                                self._transit_l, lower_bound=lower)
        return path

    # ------------------------------------------------------------ finishing
    def _check_delivery(self, p, t):
        if self.plane == "crh":
            Engine._check_delivery(self, p, t)
            return
        flow = self.sc.flows[p.flow]
        gc_ns = geometry.light_time_ns_exact(flow.great_circle_km)
        if t - p.send_ns < gc_ns:
            self._violation("latency >= great-circle / c", p, latency_ns=t - p.send_ns, bound_ns=float(gc_ns))

    def _finish(self, p, t, node, outcome, reason=None):
        Engine._finish(self, p, t, node, outcome, reason)
        if outcome == "delivered" and self.sname == "e2e" and p.first_late is not None:
            p.e2e_late = True
            self.e2e_stats["late"] += 1
            if self.penalties is not None:
                self._e2e_report(p, t)
        if self.extras is not None:
            self.extras.row(p.pkt, self._extras_row(p, t, outcome))

    def _e2e_report(self, p, t):
        e = self.scheme["e2e"]
        arrive = t + self.e2e_delay
        self.e2e_stats["reports"] += 1
        self.ledger.add("ground", "e2e_report", e["report_bytes"])
        if e["localize"] == "path":
            links = path_isls(self.topo, p.path)
        else:
            self._late_paths.append((arrive, list(p.path)))
            while self._late_paths and self._late_paths[0][0] < arrive - self.e2e_window:
                self._late_paths.popleft()
            links = intersect_links([x[1] for x in self._late_paths], self.topo)
        if links:
            self.penalties.report(arrive, links)

    def _oracle_stretch(self, p):
        """(L*, oracle hops, ok, tolerance) for a delivered packet (see eval/metrics.py)."""
        flow = self.sc.flows[p.flow]
        tr = self.truth
        k0 = min(p.send_ns // self._step_ns, self._n_steps - 1)
        ser = ser_ns(self._wire_ref(flow), self.rate_bps)
        extra = self.processing_ns + ser
        star, _path = tr.best_path(k0, p.send_ns, extra, flow.src_node, flow.dst_node)
        hops = tr.fewest_hops(k0, p.send_ns, extra, flow.src_node, flow.dst_node)
        # was every link of the packet's own path in the send-time graph?
        ok = True
        f = self.real_faults
        for u, v in zip(p.path[:-1], p.path[1:]):
            li = self.topo.link_index.get((u, v))
            if li is None or self.geo(li, k0) < 0 or (self._has_down and f.link_is_down(li, u, v, p.send_ns)):
                ok = False
                break
        tol = 0
        prev_t = p.send_ns
        for ta in p.arr_ns:
            k_up = min(prev_t // self._step_ns, self._n_steps - 1)
            tol += (k_up - k0) * self.step_tol
            prev_t = ta
        return star, hops, ok, tol

    def _extras_row(self, p, t, outcome):
        flow = self.sc.flows[p.flow]
        l_det = star = ohops = tol = ""
        ok = ""
        if outcome == "delivered":
            ser = ser_ns(self._wire_ref(flow), self.rate_bps)
            if all(x >= 0 for x in p.hprop):
                l_det = str(sum(p.hprop) + len(p.hprop) * (self.processing_ns + ser))
            if self.stretch_on:
                s_, h_, ok_, tol_ = self._oracle_stretch(p)
                star = "" if s_ is None else str(s_)
                ohops = "" if h_ is None else str(h_)
                ok = "1" if ok_ else "0"
                tol = str(tol_)
        lq = "" if p.lq is None else f"{p.lq[0]}:{p.lq[1]}:{p.lq[2]}:{p.lq[3]}"
        ld = "" if p.ld_event is None else f"{p.ld_event[0]}:{p.ld_event[1]}:{p.ld_event[2]}"
        txl = "" if p.txloss is None else ":".join(map(str, p.txloss))
        n_arr = len(p.arr_ns)                     # an unfinished packet may have one transmission more
        return ",".join((str(p.pkt), str(p.flow), " ".join(map(str, p.arr_ns)), " ".join(map(str, p.hprop)),
                         " ".join(map(str, p.hopk)), "" if p.hdr is None else str(p.hdr), l_det, star, ohops, ok, tol, lq, str(p.lq_n),
                         "1" if p.e2e_late else "0", "" if p.drop_next < 0 else str(p.drop_next), ld,
                         " ".join(map(str, p.tx[:n_arr])), " ".join(map(str, p.qw[:n_arr])), txl)) + "\n"

    # ------------------------------------------------------------ end of run
    def finish_control(self):
        """Bring the control-plane models to the end of the run (bytes of the drain included)."""
        if self.kn is not None and hasattr(self.kn, "advance"):
            self.kn.advance(self.sc.end_ns)
        if self._count_crh:
            self.crh_up.advance(self.sc.end_ns - 1)          # uploads at instants in [0, end_ns)

    def failure_visibility(self):
        """How this run's nodes learn that a link failed (run.json scheme.failure_visibility)."""
        d = {"model": "carrier", "carrier_detect_ns": self.carrier_ns,
             "applies_to": "every scheme's local decisions (spec 6 step 7 and the fallback, SNAP's dead "
                           "next hop, LQ) and the link-state carrier detection; oracles see the truth at once",
             "like_for_like": True}
        if self.sname in ("ls_h", "ls_d") and self.scheme["ls"]["fault_detection"] == "hello":
            d.update(model="hello (silent failure)", like_for_like=False,
                     note="this LS run notices failures only by missing hellos/BFD while the other schemes "
                          "notice the loss of carrier after carrier_detect_ns: a sensitivity run, NOT a "
                          "like-for-like comparison")
        return d

    def state_report(self):
        """What each satellite must hold (never merged with control bytes; reviewer must-fix #3)."""
        tr = self.truth
        n_gs = tr.n - tr.n_sats
        out = {"satellites": tr.n_sats, "ground_stations": n_gs}
        if self.plane == "crh":
            # the same sizes the periodic uploads carry (knowledge.CrhStateUploads)
            out.update(kind="crh-fib + station table + fallback ephemeris", **self.crh_up.state(),
                       note="CRH-FIB: one entry (SID -> interface) per laser partner and per ground station; "
                            "with a fallback, the station table (coordinates) and the element sets of the "
                            "satellite and its laser partners (TLE-sized records). MODELLED sizes; their "
                            "re-uploads are counted as control bytes (crh_fib_refresh, ephemeris_upload)")
        elif self.sname == "snap":
            out.update(kind="forwarding table", table_bytes_per_node=self.kn.initial_state_bytes())
        elif self.sname in ("ls_h", "ls_d"):
            out.update(kind="link-state database", lsdb_bytes_per_node=self.kn.initial_state_bytes())
        else:
            out.update(kind="oracle (no real state)")
        return out

    def control_report(self):
        rep = {"scheme": self.sname, "ledger": self.ledger.to_dict(), "state": self.state_report()}
        if self.kn is not None and hasattr(self.kn, "stats"):
            rep["knowledge"] = dict(self.kn.stats)
        if isinstance(self.kn, SnapKnowledge):
            rep["knowledge"] = dict(self.kn.uploads)
        if self.sname == "lq":
            rep["lq"] = dict(self.lq_stats)
        if self.penalties is not None:
            rep["penalties"] = {"reports": self.penalties.reports,
                                "links_penalised": len(self.penalties.intervals),
                                "first_activation_ns": [[t, li] for t, li in self.penalties.changes[:200]]}
            rep["feedback"] = dict(self.fb_stats) if self.sname == "chronoroute" else dict(self.e2e_stats)
        elif self.sname == "e2e":
            rep["feedback"] = dict(self.e2e_stats)
        if self.plane == "oracle":
            rep["oracle"] = dict(self.oracle_stats)
        if self.crh_up is not None:
            rep["crh_state_uploads"] = dict(self.crh_up.stats, counted=self._count_crh,
                                            periods_ns=dict(self.crh_up.periods),
                                            steady_state_bytes_per_s=dict(self.crh_up.steady))
        rep["failure_visibility"] = self.failure_visibility()
        return rep

    def detections(self):
        """Control-plane detection events (LS-H adjacency down, LS-D metric updates)."""
        if isinstance(self.kn, LinkState):
            return sorted(self.kn.detections)
        return []


EXTRAS_COLUMNS = ("pkt", "flow", "arrival_ns", "hop_prop_ns", "hop_k", "hdr_bytes", "l_det_ns", "oracle_ns",
                  "oracle_hops", "oracle_ok", "tol_ns", "lq_flag", "lq_flags", "e2e_late", "drop_next",
                  "link_down_at", "tx_ns", "wait_ns", "tx_loss_at")

__all__ = ["SchemeEngine", "SPacket", "EXTRAS_COLUMNS", "header_bytes", "step_tolerance_ns", "V_MAX_KM_S"]

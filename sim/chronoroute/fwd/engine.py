"""
engine.py
---------
The ChronoRoute simulator v2: a discrete-event, per-packet engine that
forwards every packet from its T-CRH BYTES (master plan P3a/b).

One run, in order of events (all times integer ns after t0, GPS = t0_gps + t):

  PLAN     every refresh interval (default 1 s) the ground plans every flow
           on the predicted, failure-free topology (scenario.Scenario.plan;
           the bundle's "stable" planner). Packets of the interval are
           created with consecutive packet ids in (send time, flow) order.
  SEND     the source ground station (the ingress) copies the interval's
           T-CRH template, stamps Epoch_Base = ceil(T_gps / u) (spec 4),
           and runs spec 6 steps 5-7 (hop.HopProcessor.ingress / link_down).
  ARRIVE   the packet reaches a node ("hop"): lost if its link went down
           while it was in flight or the node is down; otherwise the node
           runs spec 6 on the bytes (deadline check, policy, SL decrement),
           looks the next SID up in its CRH-FIB, checks that link (step 7:
           a down link is its own deviation class, "next_link_down"), or, for
           a packet in GREEDY mode, asks the fallback function. Every routing
           decision is taken at the arrival instant, with the state of that
           instant (ns-3 forwards at that instant too).
  READY    after the node's processing delay (0.5 ms, MODELLED; optional J1
           jitter; optional slow-processing fault) the packet enters the
           FIFO of its outgoing link (queues.LinkQueue: Lindley recursion,
           drop-tail, optional background). If the processing delay of a
           node can never vary, READY is skipped and the packet is queued at
           once with ready = arrival + delay: same order, same result
           (test_fwd_engine runs both ways and compares the bytes).
           Transmission, ARQ retries and light time (held per 100 ms step,
           like ns-3) give the arrival at the next node.

Every random draw is keyed (rng.KeyedStreams): jitter by (flow, packet,
hop), ARQ by (flow, packet, hop, attempt), background by (link, window),
fault periods by (fault, element), sampling by (flow, packet). Same seed =>
identical files; a run with a fault and its fault-free twin draw identical
numbers.

The engine never forwards from its own copy of the path: the only routing
state a packet carries is its header bytes (plus, for the legacy
greedy_visited fallback, its visited set, which a real packet could not
carry; see fallback.py). test_fwd_engine garbles the planner's Python path
after the template is built and checks that no output changes.

Speed: the common hop (on schedule, next link up, nothing traced) runs
through _on_arrive without further calls except the byte processing and the
queue. Ports (a node's FIB entry joined with its link queue and a cached copy
of the link's geometry) save dictionary look-ups on that path.
"""

import heapq
import math
import resource
import time

from .. import proto
from ..proto import timebase
from ..topo import geometry
from . import config as config_mod, fallback as fallback_mod
from .config import exact_fraction
from .faults import build_faults
from .hop import HopProcessor, fast_process
from .queues import LinkQueue, RateSchedule
from .rng import KeyedStreams

K_PLAN, K_SEND, K_ARRIVE, K_READY = 0, 1, 2, 3
IPV6 = 40
UDP = 8
NS_PER_S = 1_000_000_000
HOPS_PER_PACKET_INDEX = 256          # keyed-draw index = seq * 256 + hop (hop < 256 = hop limit max)
LIGHT_TOL_NS = 0.5                   # prop is round(d / c): at most 0.5 ns below the exact light time
NOPOS = -(1 << 62)                   # encoded geometry of a link with an end whose SGP4 failed

OUTCOMES = ("delivered", "dropped", "no_route", "unfinished")
DROP_REASONS = ("late_strict", "next_link_down", "no_fallback", "no_fib_entry", "node_down",
                "in_flight_link_down", "buffer_overflow", "arq_exhausted", "stuck", "hop_limit",
                "loop", "malformed")


class Packet:
    """One packet in flight. Its routing state is `raw` (the T-CRH bytes) and nothing else;
    the rest is bookkeeping for the outputs (path taken, clocks, deadlines)."""

    __slots__ = ("pkt", "flow", "seq", "send_ns", "raw", "wire", "path", "arr_u", "dl_u", "hops",
                 "greedy", "dest", "first_late", "sampled", "visited", "prev", "fb_reason", "row_from_ms",
                 "check", "frames")

    def __init__(self, pkt, flow, seq, send_ns):
        self.pkt, self.flow, self.seq, self.send_ns = pkt, flow, seq, send_ns
        self.raw = None
        self.wire = 0
        self.path = []
        self.arr_u = []
        self.dl_u = []
        self.hops = 0
        self.greedy = False
        self.dest = -1
        self.first_late = None
        self.sampled = False
        self.visited = None
        self.prev = -1
        self.fb_reason = None
        self.row_from_ms = None
        self.check = False
        self.frames = None


class Port:
    """One outgoing interface: a node's CRH-FIB entry (neighbour, link) joined with the
    link's FIFO and a cached copy of the link's encoded geometry for one chunk."""

    __slots__ = ("node", "nxt", "li", "q", "c", "k0", "enc")

    def __init__(self, node, nxt, li, q):
        self.node, self.nxt, self.li, self.q = node, nxt, li, q
        self.c = -1
        self.k0 = 0
        self.enc = None


class InvariantViolation(AssertionError):
    """A physical or protocol invariant failed (tests run with every check on)."""


class Engine:
    """One run of the simulator for a built scenario.Scenario."""

    def __init__(self, scenario, *, trace=None, packets_csv=None, pcap_frames=None):
        self.sc = scenario
        cfg = scenario.cfg
        self.cfg = cfg
        self.topo = scenario.topo
        self.rng = KeyedStreams(cfg["seed"])
        fw = cfg["forwarding"]
        self.policy = fw["policy"]
        self.hp = HopProcessor(self.policy, mode=fw["hop_mode"], verify_every=fw["verify_every"])
        self.fallback_name = fw["fallback"]
        self.fallback = fallback_mod.FALLBACKS.get(self.fallback_name)
        self.hop_limit = fw["hop_limit"]
        self.processing_ns = fw["processing_ns"]
        self.jitter_mean = fw["jitter"]["mean_ns"] if fw["jitter"]["model"] == "j1" else None
        self.rate_bps = fw["link_rate_bps"]
        # buffer = buffer_ms x C, in bytes, computed exactly (0.5 ms at 1 Gb/s = 62,500 B)
        self.buffer_bytes = int(exact_fraction(fw["buffer_ms"], "buffer_ms") * self.rate_bps / 8000)
        bg = fw["background"]
        self.bg_rho = exact_fraction(bg["rho"], "rho")
        self.bg_model = bg["model"] if self.bg_rho > 0 else "none"
        self.bg_links = bg["links"]
        self.bg_packet = bg["packet_bytes"]
        self.bg_window_ns = bg["window_ms"] * 1_000_000
        self.unit_code = cfg["schedule"]["unit_code"]
        self.unit_ns = timebase.unit_ns(self.unit_code)
        tr = cfg["traffic"]
        self.l2 = tr["l2_overhead_bytes"]
        self.encap = tr["ingress_mode"] == "encap"
        out = cfg["output"]
        self.trace = trace                 # trace.writer.EventWriter or None
        self.trace_all = out["trace"] == "full"
        self.sample_p = 1.0 / out["sample_every"]
        self.csv = packets_csv             # trace.writer.PacketCsvWriter or None
        self.pcap_frames = pcap_frames     # list to append (t_gps, pkt, packet bytes) or None
        self.pcap_max = out["pcap_max_packets"]
        self.pcap_packets = 0
        self.inv_level = out["invariants"]
        self.inv_every = out["invariant_sample_every"]

        self.faults = build_faults(cfg["faults"], topo=self.topo, rng=self.rng, end_ns=scenario.end_ns,
                                   resolve_on_path=scenario.resolve_on_path)
        # Two views of the failures: self.faults is the truth (what loses packets), self.seen
        # is what a node next to a failure KNOWS: the same failures, noticed carrier_detect
        # later (faults.FaultSet.detected_view; the same object when the delay is 0). Every
        # routing decision uses self.seen, every loss self.faults.
        self.carrier_ns = config_mod.carrier_detect_ns(cfg)
        self.seen = self.faults.detected_view(self.carrier_ns)
        self.fctx = fallback_mod.FallbackContext(self.topo, self.link_usable, self.queue_wait,
                                                 fw["slow_queue_ns"])
        self.queues = {}                   # a * n_nodes + b -> LinkQueue (directed link a -> b)
        self._ports = [dict() for _ in range(self.topo.n_nodes)]    # node -> {SID: Port}
        self._geo = {}                     # li -> (chunk index, chunk k0, encoded list), see _geo_load
        self._cs = self.topo.chunk_steps
        self._nn = self.topo.n_nodes
        self._step_ns = scenario.step_ns
        self._n_steps = scenario.n_steps
        self._t0g = scenario.t0_gps_ns
        f = self.faults
        self._link_faults = bool(f.link_down or f.node_down)      # a link can be down by a fault
        self._link_only_faults = bool(f.link_down)
        self._node_faults = bool(f.node_down)
        # constant processing delay everywhere: queue at once, no READY event (same order, same result)
        self._simple_tx = self.jitter_mean is None and not f.node_delay
        self._tx_extras = bool(f.arq or f.link_delay)
        if self.hp.mode == "fast" and not self.hp.verify_every:
            self._fp = fast_process           # called as _fp(raw, now_u, policy)
        else:
            self._fp = lambda raw, now_u, _policy, _hp=self.hp: _hp.process(raw, now_u)

        self.heap = []
        self._seq = 0
        self.npkt = 0
        self._flow_seq = {fl.flow_id: 0 for fl in scenario.flows}
        self._poisson = {}
        self.current = {}                  # flow id -> (ScheduleEntry or None, start_ms)
        self.schedule_rows = []
        self.counts = {"sent": 0, "delivered": 0, "no_route": 0, "dropped": 0, "unfinished": 0,
                       "late": 0, "fallback": 0, "hop_events": 0}
        self.hop_events = 0
        self.drops = {r: 0 for r in DROP_REASONS}
        self.fb_reasons = {"late": 0, "next_link_down": 0}
        self.per_flow = {fl.flow_id: {"sent": 0, "delivered": 0, "no_route": 0, "dropped": 0,
                                      "unfinished": 0, "late": 0, "fallback": 0, "latency_ns": []}
                         for fl in scenario.flows}
        self.inv = {"checked_packets": 0, "checked_hops": 0, "violations": 0, "examples": []}
        self.timing = {}
        self.max_hops_seen = 0

    # ------------------------------------------------------------------ geometry and links
    def _geo_load(self, li, k):
        """Cache the geometry of link li for the chunk holding step k as ONE Python list.

        Entry i is the held light time (ns) at step k0 + i when the link is
        up, and -1 - light time when it is down (NOPOS when an end has no
        position): one list lookup answers both questions on the hot path.
        Cached per link for its latest chunk (shared by both directions).
        """
        ch = self.topo.chunk_of_step(k)
        enc = [x if u else (NOPOS if x < 0 else -1 - x)
               for x, u in zip(ch.prop[li].tolist(), ch.up[li].tolist())]
        e = (ch.k0 // self._cs, ch.k0, enc)
        self._geo[li] = e
        return e

    def geo(self, li, k):
        """Encoded geometry of link li at step k (see _geo_load): >= 0 up (= prop ns), < 0 down."""
        e = self._geo.get(li)
        if e is None or e[0] != k // self._cs:
            e = self._geo_load(li, k)
        return e[2][k - e[1]]

    def _port_geo(self, port, k):
        """Point a port's geometry cache at the chunk holding step k."""
        e = self._geo.get(port.li)
        if e is None or e[0] != k // self._cs:
            e = self._geo_load(port.li, k)
        port.c, port.k0, port.enc = e

    def geo_state(self, li, k):
        """(up, prop_ns) of link li at step k from the geometry (no faults)."""
        v = self.geo(li, k)
        return (True, v) if v >= 0 else (False, -1 - v)

    def link_usable(self, li, a, b, t, k):
        """What node a decides on: the link is up at time t by the geometry of step k, and no
        failure of it (or of b) has been NOTICED by t (self.seen; the truth itself when the
        carrier detection delay is 0, the default)."""
        if self.geo(li, k) < 0:
            return False
        return not (self._link_faults and self.seen.link_is_down(li, a, b, t))

    def queue(self, a, b, li):
        """The FIFO of the directed link a -> b (created on first use)."""
        key = a * self._nn + b
        q = self.queues.get(key)
        if q is None:
            rate = RateSchedule(self.rate_bps, self.faults.rate_changes(li, self.rate_bps))
            model = self.bg_model
            if model != "none" and self.bg_links == "isl" and li >= self.topo.n_isl:
                model = "none"
            q = LinkQueue(rate, self.buffer_bytes, background=model, rho=self.bg_rho,
                          bg_packet_bytes=self.bg_packet, bg_window_ns=self.bg_window_ns,
                          rng=self.rng, key=(a, b))
            self.queues[key] = q
        return q

    def port(self, node, sid):
        """The node's interface towards SID `sid`, or None when the CRH-FIB has no entry."""
        pt = self._ports[node].get(sid)
        if pt is None:
            hit = self.topo.fib[node].get(sid)
            if hit is None:
                return None
            pt = Port(node, hit[0], hit[1], self.queue(node, hit[0], hit[1]))
            self._ports[node][sid] = pt
        return pt

    def port_to(self, node, nxt):
        """The node's interface towards neighbour nxt (fallback decisions name nodes)."""
        return self.port(node, self.topo.sid_of[nxt])

    def queue_wait(self, a, b, li, t):
        return self.queue(a, b, li).queue_delay_estimate(t)

    def clock_u(self, t):
        return ((self._t0g + t) // self.unit_ns) % timebase.MOD32

    def _push(self, t, pkt, kind, p, a, b, x):
        self._seq += 1
        heapq.heappush(self.heap, (t, pkt, self._seq, kind, p, a, b, x))

    def _violation(self, what, p, **info):
        self.inv["violations"] += 1
        if len(self.inv["examples"]) < 10:
            self.inv["examples"].append({"check": what, "pkt": p.pkt, **info})
        if self.inv_level == "all":
            raise InvariantViolation(f"{what}: packet {p.pkt} {info}")

    # ------------------------------------------------------------------ traffic
    def _sends_in(self, flow, lo, hi):
        """Send times of a flow in [lo, hi) (integer ns), CBR / Poisson / explicit."""
        if flow.model == "explicit":
            return [t for t in flow.send_times_ns if lo <= t < hi]
        rate = flow.rate_pps
        if flow.model == "cbr":
            # t_n = offset + floor(n * 1e9 / rate), exact
            num, den = rate.numerator, rate.denominator
            off = flow.start_offset_ns
            if off is None:
                period0 = (NS_PER_S * den) // num
                off = int(self.rng.uniform("flow_offset", (flow.flow_id,), 0) * period0)
            n = max(0, -(-(lo - off) * num // (NS_PER_S * den)) - 1)
            out = []
            while True:
                t = off + (n * NS_PER_S * den) // num
                if t >= hi:
                    break
                if t >= lo:
                    out.append(t)
                n += 1
            return out
        # Poisson: exponential gaps from the keyed stream (traffic, flow), index = send number
        mean = float(NS_PER_S / rate)
        st = self._poisson.get(flow.flow_id)
        if st is None:
            if flow.start_offset_ns is None:
                # "random": the first send is itself an exponential gap after t0 (a Poisson
                # process has no arrival pinned at 0); draw 0 of the stream is that gap
                first = max(1, int(round(self.rng.exponential("traffic", (flow.flow_id,), 0, mean))))
                st = [first, 1]
            else:
                st = [flow.start_offset_ns, 0]
            self._poisson[flow.flow_id] = st
        out = []
        while st[0] < hi:
            if st[0] >= lo:
                out.append(st[0])
            st[0] += max(1, int(round(self.rng.exponential("traffic", (flow.flow_id,), st[1], mean))))
            st[1] += 1
        return out

    def _plan_interval(self, start_ms, end_ms):
        csr_cache = {}
        sends = []
        lo, hi = start_ms * 1_000_000, end_ms * 1_000_000
        t0 = time.perf_counter()
        c0 = self.topo.chunk_seconds
        for f in self.sc.flows:
            e = self.sc.plan(f, start_ms, end_ms, csr_cache)
            self.current[f.flow_id] = (e, start_ms)
            self.schedule_rows.append((f.flow_id, start_ms, end_ms, e))
            for t in self._sends_in(f, lo, hi):
                sends.append((t, f.flow_id))
        self.timing["plan_s"] = self.timing.get("plan_s", 0.0) + time.perf_counter() - t0
        self.timing["plan_chunk_s"] = self.timing.get("plan_chunk_s", 0.0) + self.topo.chunk_seconds - c0
        sends.sort()
        seqs = self._flow_seq
        for t, fid in sends:
            p = Packet(self.npkt, fid, seqs[fid], t)
            seqs[fid] += 1
            self.npkt += 1
            self._push(t, p.pkt, K_SEND, p, 0, 0, None)

    # ------------------------------------------------------------------ finishing
    def _finish(self, p, t, node, outcome, reason=None):
        c = self.counts
        pf = self.per_flow[p.flow]
        if outcome == "delivered":
            c["delivered"] += 1
            pf["delivered"] += 1
            pf["latency_ns"].append(t - p.send_ns)
        elif outcome == "dropped":
            c["dropped"] += 1
            pf["dropped"] += 1
            self.drops[reason] += 1
        else:
            c[outcome] += 1
            pf[outcome] += 1
        if p.first_late is not None:
            c["late"] += 1
            pf["late"] += 1
        if p.greedy:
            c["fallback"] += 1
            pf["fallback"] += 1
        if p.hops > self.max_hops_seen:
            self.max_hops_seen = p.hops
        raw = p.raw
        if self.trace is not None and (self.trace_all or p.sampled) and outcome != "unfinished":
            delivered = outcome == "delivered"
            self.trace.event(t, "deliver" if delivered else "drop", p.pkt, p.flow, node,
                             None, raw[3] if raw else None, raw[4] if raw else None,
                             p.dl_u[-1] if (delivered and p.dl_u and p.dl_u[-1] != "-") else None,
                             p.arr_u[-1] if (delivered and p.arr_u) else None,
                             reason, raw.hex() if (raw and p.sampled) else None)
        if p.check and outcome == "delivered":
            self._check_delivery(p, t)
        if self.csv is not None:
            dev = (raw[4] & proto.FLAG_DEV) if raw else 0
            self.csv.row(p.pkt, ",".join((
                str(p.pkt), str(p.flow), str(p.seq), str(p.send_ns), outcome, reason or "",
                "1" if outcome == "delivered" else "0",
                str(t - p.send_ns) if outcome == "delivered" else "", str(p.hops),
                " ".join(map(str, p.path)), "1" if dev else "0", str(raw[6]) if dev else "",
                "" if p.first_late is None else str(p.first_late),
                " ".join(map(str, p.arr_u)), " ".join(map(str, p.dl_u)),
                "1" if p.greedy else "0", p.fb_reason or "",
                "" if p.row_from_ms is None else str(p.row_from_ms), str(p.wire))) + "\n")

    def _check_delivery(self, p, t):
        flow = self.sc.flows[p.flow]
        gc_ns = geometry.light_time_ns_exact(flow.great_circle_km)
        if t - p.send_ns < gc_ns:
            self._violation("latency >= great-circle / c", p, latency_ns=t - p.send_ns, bound_ns=float(gc_ns))
        if not p.greedy:
            raw = p.raw
            if raw[3] != 0 or p.hops != raw[5] or p.path[-1] != flow.dst_node:
                self._violation("SL reaches 0 exactly at the destination", p, sl=raw[3], hops=p.hops,
                                num_hops=raw[5])

    # ------------------------------------------------------------------ transmission
    def _transmit(self, p, port, t):
        """The node has decided to send over `port`: processing delay, then the link's FIFO."""
        node = port.node
        if p.hops >= self.hop_limit:
            self._finish(p, t, node, "dropped",
                         "loop" if len(set(p.path)) < len(p.path) else "hop_limit")
            return
        if self._simple_tx:
            self._enqueue(p, port, t + self.processing_ns)
            return
        delay = self.processing_ns
        if self.jitter_mean is not None:
            idx = p.seq * HOPS_PER_PACKET_INDEX + p.hops
            delay += int(round(self.rng.exponential("jitter_j1", (p.flow,), idx, self.jitter_mean)))
        if self.faults.node_delay:
            delay += self.faults.extra_processing_ns(node, t)
        if self.jitter_mean is None and node not in self.faults.node_delay:
            self._enqueue(p, port, t + delay)          # this node's delay is constant: no READY needed
        else:
            self._push(t + delay, p.pkt, K_READY, p, node, port.nxt, port)

    def _enqueue(self, p, port, t_ready):
        """The packet enters the FIFO of `port` at t_ready; schedule its arrival downstream.

        Returns (transmission start, end of serialization) when an arrival was scheduled,
        None when the packet was lost here (the baselines record the start per hop)."""
        res = port.q.enqueue(t_ready, p.wire)
        if res is None:
            # drop-tail: the FIFO is full at the instant the packet tries to join it
            self._link_drop(p, port, t_ready, t_ready, -1, "buffer_overflow")
            return None
        start, end = res
        k = start // self._step_ns
        if k >= self._n_steps:
            k = self._n_steps - 1
        if port.c != k // self._cs:
            self._port_geo(port, k)
        prop = port.enc[k - port.k0]
        if prop < 0:
            # down at transmission start (it went down while the packet was being
            # processed or queued): it is sent anyway and lost on arrival if still down
            if prop == NOPOS:
                self._link_drop(p, port, t_ready, start, start - t_ready, "in_flight_link_down")
                return None
            prop = -1 - prop
        if not self._tx_extras and not p.check and p.frames is None:
            # the common case: no ARQ / link-delay fault anywhere, no checks, no capture
            p.hops += 1
            self._seq += 1
            heapq.heappush(self.heap, (end + prop, p.pkt, self._seq, K_ARRIVE, p, port.node, port.nxt, port))
            return res
        li = port.li
        extra = 0
        if self.faults.arq:
            arq = self.faults.arq_params(li, start)
            if arq is not None:
                loss, retries, retry_ns = arq
                lossf = float(loss)
                base = (p.seq * HOPS_PER_PACKET_INDEX + p.hops) * 4
                ok = None
                for a in range(retries + 1):
                    if self.rng.uniform("arq", (p.flow,), base + a) >= lossf:
                        ok = a
                        break
                if ok is None:
                    self._link_drop(p, port, t_ready, start, start - t_ready, "arq_exhausted")
                    return None
                extra += ok * (2 * prop + retry_ns)
        if self.faults.link_delay:
            extra += self.faults.extra_link_ns(li, start)
        t_arr = end + prop + extra
        if p.check:
            self.inv["checked_hops"] += 1
            light = geometry.light_time_ns_exact(math.dist(self.topo.node_ecef_km(port.node, k),
                                                           self.topo.node_ecef_km(port.nxt, k)))
            if prop + LIGHT_TOL_NS < light or t_arr - start < light - LIGHT_TOL_NS:
                self._violation("per-hop delay >= distance / c", p, hop=p.hops, prop_ns=prop,
                                light_ns=float(light))
        if p.frames is not None:
            self._pcap_frame(p, port.nxt, start)
        p.hops += 1
        self._push(t_arr, p.pkt, K_ARRIVE, p, port.node, port.nxt, port)
        return res

    def _link_drop(self, p, port, t, t_attempt, wait_ns, reason):
        """The packet is lost at the TRANSMITTER of `port` (it never leaves port.node).

        t          the instant the drop is stamped with (the packet's ready time, as before)
        t_attempt  when the packet met the link: the FIFO join for buffer_overflow, the
                   transmission start for arq_exhausted and for a link end without a position
        wait_ns    how long it waited for the transmitter (-1: it never got into the FIFO)

        Here it only finishes the packet. It is a separate method so that a subclass can
        record WHICH link the packet was lost at and when (baselines/engine.py writes it to
        scheme_packets.csv.gz as tx_loss_at): the packet's path ends at port.node, so
        without that record the evaluation could not tell that a fault on port.node ->
        port.nxt dropped it (eval/metrics.py exposure).
        """
        self._finish(p, t, port.node, "dropped", reason)

    def _pcap_frame(self, p, nxt, start):
        """A frame of a sampled packet as it starts to leave a node (PPP + IPv6 + T-CRH + UDP)."""
        from ..trace import pcap as pcapw
        raw = p.raw
        if raw[4] & proto.FLAG_GREEDY:
            dst_sid = (raw[12] << 8) | raw[13]           # GREEDY: addressed to SID[0]
        else:
            off = 12 + 3 * raw[3]                         # the SID just looked up (SID[SL])
            dst_sid = (raw[off] << 8) | raw[off + 1]
        flow = self.sc.flows[p.flow]
        payload = pcapw.payload_bytes(p.pkt & 0xFFFFFFFF, self._t0g + p.send_ns)
        payload += bytes(max(0, flow.payload_bytes - len(payload)))
        final = (raw[12] << 8) | raw[13]
        pkt = pcapw.packet_with_routing_header(raw, src=pcapw.HOST_SRC, dst=pcapw.sid_address(dst_sid),
                                               final_dst=pcapw.sid_address(final), payload=payload,
                                               hop_limit=max(0, pcapw.DEFAULT_HOP_LIMIT - p.hops))
        self.pcap_frames.append((self._t0g + start, p.pkt, pkt))

    # ------------------------------------------------------------------ fallback
    def _to_fallback(self, p, node, t, k, reason, frm):
        """The packet is now GREEDY (its bytes already say so): (Port, None) or (None, drop reason).

        Never finishes the packet itself, so the caller can write the hop
        event first and the drop after it (trace order).
        """
        p.greedy = True
        if p.fb_reason is None:
            p.fb_reason = reason
            self.fb_reasons[reason] += 1
        p.dest = self.topo.sid_to_node.get((p.raw[12] << 8) | p.raw[13], -1)
        if self.fallback is None:
            # spec 6 step 7: "a node without a fallback function discards the packet"
            return None, ("next_link_down" if reason == "next_link_down" else "no_fallback")
        if self.fallback_name == "greedy_visited" and p.visited is None:
            p.visited = set(p.path)
        nxt, info = self.fallback(self.fctx, node, p.dest, t, k, frm, p.visited)
        if nxt is None:
            return None, info
        return self.port_to(node, nxt), None

    # ------------------------------------------------------------------ event handlers
    def _on_send(self, p, t):
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
        if self.pcap_frames is not None and p.sampled and self.pcap_packets < self.pcap_max:
            p.frames = True
            self.pcap_packets += 1
        entry, start_ms = self.current.get(fid, (None, None))
        tracer = self.trace if (self.trace is not None and (self.trace_all or p.sampled)) else None
        if entry is None:
            if tracer:
                tracer.event(t, "send", p.pkt, fid, src, None, None, None, None, self.clock_u(t), None, None)
            self._finish(p, t, src, "no_route", "no_route")
            return
        p.row_from_ms = start_ms
        if self.hp.mode == "reference":
            raw = entry.header_for_packet(self.sc.t0_ns + t)      # proto.build_header
        else:
            # the template with this packet's Epoch_Base in bytes 8-11 (docs/bundle-format.md
            # 2.8; equal to proto.build_header, which test_fwd_engine checks via reference mode)
            tpl = entry.template
            epoch = (-(-(self._t0g + t) // self.unit_ns)) % timebase.MOD32
            raw = tpl[:8] + epoch.to_bytes(4, "big") + tpl[12:]
        p.wire = self.l2 + IPV6 + len(raw) + (IPV6 if self.encap else 0) + UDP + flow.payload_bytes
        out, first_sid = self.hp.ingress(raw)
        p.raw = out
        k = t // self._step_ns
        if k >= self._n_steps:
            k = self._n_steps - 1
        port = self.port(src, first_sid)
        if port is None:
            if tracer:
                tracer.event(t, "send", p.pkt, fid, src, None, out[3], out[4], None, self.clock_u(t),
                             None, out.hex() if p.sampled else None)
            self._finish(p, t, src, "dropped", "no_fib_entry")
            return
        if self.link_usable(port.li, src, port.nxt, t, k):
            if tracer:
                tracer.event(t, "send", p.pkt, fid, src, port.nxt, out[3], out[4], None, self.clock_u(t),
                             None, out.hex() if p.sampled else None)
            p.prev = src
            self._transmit(p, port, t)
            return
        # spec 6 step 7 at the ingress: DEV with Dev Hop 0, GREEDY, SL 0
        _act, _sid, out2, _k, _r = self.hp.link_down(out)
        p.raw = out2
        if tracer:
            tracer.event(t, "send", p.pkt, fid, src, None, out2[3], out2[4], None,
                         self.clock_u(t), None, out2.hex() if p.sampled else None)
        port2, why = self._to_fallback(p, src, t, k, "next_link_down", -1)
        if tracer:
            tracer.event(t, "fallback", p.pkt, fid, src, port2.nxt if port2 else None, p.raw[3], p.raw[4],
                         None, None, "next_link_down", p.raw.hex() if p.sampled else None)
        if port2 is None:
            self._finish(p, t, src, "dropped", why)
            return
        p.prev = src
        self._transmit(p, port2, t)

    def _on_arrive(self, p, t, frm, node, inport):
        """A packet reaches a node. The common case (on schedule, next link up, not traced)
        runs straight through; everything else goes to _arrive_rest."""
        self.hop_events += 1
        k = t // self._step_ns
        if k >= self._n_steps:
            k = self._n_steps - 1
        if self._node_faults and node < self.topo.n_sats and self.faults.node_is_down(node, t):
            self._lost(p, t, node, "node_down")
            return
        # lost in flight: the link itself went down before the packet arrived (ns-3 SetDown
        # semantics). The receiver's own state was checked just above; a sender that died
        # after transmitting does not recall the light already on its way.
        if inport.c != k // self._cs:
            self._port_geo(inport, k)
        if inport.enc[k - inport.k0] < 0 or (self._link_only_faults and
                                              self.faults.link_down_only(inport.li, t)):
            self._lost(p, t, node, "in_flight_link_down")
            return
        p.path.append(node)
        if p.greedy and node != p.dest:
            self._greedy_transit(p, t, frm, node, k)
            return
        now_u = ((self._t0g + t) // self.unit_ns) & 0xFFFFFFFF
        raw_in = p.raw
        res = self._fp(raw_in, now_u, self.policy)    # spec 6 on the bytes
        p.arr_u.append(now_u)
        p.dl_u.append(res[5])
        if res[3]:
            p.first_late = res[4]
        if p.check and not p.greedy and res[4] != p.hops:
            self._violation("on-schedule hop index equals hops taken", p, hop_index=res[4], hops=p.hops)
        if res[0] == "forward" and not (self.trace is not None and (self.trace_all or p.sampled)):
            port = self._ports[node].get(res[1]) or self.port(node, res[1])     # CRH-FIB (step 6)
            if port is not None:
                if port.c != k // self._cs:
                    self._port_geo(port, k)
                if port.enc[k - port.k0] >= 0 and not (self._link_faults and
                                                       self.seen.link_is_down(port.li, node, port.nxt, t)):
                    p.raw = res[2]
                    p.prev = node
                    if self._simple_tx and p.hops < self.hop_limit:
                        self._enqueue(p, port, t + self.processing_ns)
                    else:
                        self._transmit(p, port, t)
                    return
        self._arrive_rest(p, t, frm, node, k, now_u, raw_in, res)

    def _lost(self, p, t, node, reason):
        """The packet never got to run spec 6 here (node down, or its link died in flight)."""
        p.path.append(node)
        if self.trace is not None and (self.trace_all or p.sampled):
            self.trace.event(t, "hop", p.pkt, p.flow, node, None, p.raw[3], p.raw[4], None,
                             self.clock_u(t), None, p.raw.hex() if p.sampled else None)
        self._finish(p, t, node, "dropped", reason)

    def _greedy_transit(self, p, t, frm, node, k):
        """A transit satellite of a fallback detour: the packet is addressed to SID[0], so
        this node does not run spec 6, it only applies the fallback function."""
        now_u = self.clock_u(t)
        raw_in = p.raw
        p.arr_u.append(now_u)
        p.dl_u.append("-")
        nxt, info = None, "no_fallback"
        if self.fallback is not None:
            if p.visited is not None:
                p.visited.add(node)
            nxt, info = self.fallback(self.fctx, node, p.dest, t, k, frm, p.visited)
        if self.trace is not None and (self.trace_all or p.sampled):
            self.trace.event(t, "hop", p.pkt, p.flow, node, nxt, raw_in[3], raw_in[4], None, now_u, None,
                             raw_in.hex() if p.sampled else None)
        if nxt is None:
            self._finish(p, t, node, "dropped", info)
            return
        p.prev = node
        self._transmit(p, self.port_to(node, nxt), t)

    def _arrive_rest(self, p, t, frm, node, k, now_u, raw_in, res):
        """Every outcome of spec 6 other than a plain forward over an up link (or a traced packet)."""
        action, next_sid, out, late, khop, deadline, reason = res
        tracer = self.trace if (self.trace is not None and (self.trace_all or p.sampled)) else None
        hexin = raw_in.hex() if (tracer and p.sampled) else None
        # spec/trace-v1.md 3: a sampled packet carries its bytes on EVERY event: the hop as it
        # arrived (hexin), the late event after processing, the fallback event after the switch
        sampled = tracer is not None and p.sampled
        if action == "deliver":
            p.raw = out
            if tracer:
                tracer.event(t, "hop", p.pkt, p.flow, node, None, raw_in[3], raw_in[4], deadline, now_u,
                             None, hexin)
                if late:
                    tracer.event(t, "late", p.pkt, p.flow, node, None, out[3], out[4], deadline, now_u,
                                 None, out.hex() if sampled else None)
            self._finish(p, t, node, "delivered")
            return
        if action in ("drop_late", "drop_malformed", "ignore"):
            if action == "drop_late":
                p.raw = _set_dev(raw_in, khop)
            if tracer:
                tracer.event(t, "hop", p.pkt, p.flow, node, None, raw_in[3], raw_in[4], deadline, now_u,
                             None, hexin)
                if late:
                    tracer.event(t, "late", p.pkt, p.flow, node, None, p.raw[3], p.raw[4], deadline,
                                 now_u, None, p.raw.hex() if sampled else None)
            self._finish(p, t, node, "dropped", "late_strict" if action == "drop_late" else "malformed")
            return
        p.raw = out
        fb = None
        if action == "fallback":                          # late, policy greedy (spec 6 step 4)
            fb = "late"
            port, why = self._to_fallback(p, node, t, k, "late", frm)
        else:                                             # forward: CRH-FIB lookup (step 6)
            port = self.port(node, next_sid)
            why = None
            if port is None:
                why = "no_fib_entry"
            elif not self.link_usable(port.li, node, port.nxt, t, k):
                fb = "next_link_down"                     # step 7: next link down
                _a, _s, out2, _k, _r = self.hp.link_down(out)
                p.raw = out2
                port, why = self._to_fallback(p, node, t, k, "next_link_down", frm)
        if tracer:
            tracer.event(t, "hop", p.pkt, p.flow, node, port.nxt if (port and fb is None) else None,
                         raw_in[3], raw_in[4], deadline, now_u, None, hexin)
            if late:
                tracer.event(t, "late", p.pkt, p.flow, node, None, out[3], out[4], deadline, now_u,
                             None, out.hex() if sampled else None)
            if fb is not None:
                tracer.event(t, "fallback", p.pkt, p.flow, node, port.nxt if port else None, p.raw[3],
                             p.raw[4], None, None, fb, p.raw.hex() if sampled else None)
        if port is None:
            self._finish(p, t, node, "dropped", why)
            return
        p.prev = node
        self._transmit(p, port, t)

    # ------------------------------------------------------------------ main loop
    def run(self):
        sc = self.sc
        r = sc.refresh_ms
        dur_ms = sc.duration_ns // 1_000_000
        for start in range(0, dur_ms, r):
            self._push(start * 1_000_000, -1, K_PLAN, None, start, min(start + r, dur_ms), None)
        end_ns = sc.end_ns
        heap = self.heap
        pop = heapq.heappop
        tracer = self.trace
        on_arrive = self._on_arrive
        t_start = time.perf_counter()
        while heap:
            t, pkt, _s, kind, p, a, b, x = pop(heap)
            if t > end_ns:
                heapq.heappush(heap, (t, pkt, _s, kind, p, a, b, x))
                break
            if tracer is not None:
                tracer.advance(t)
            if kind == K_ARRIVE:
                on_arrive(p, t, a, b, x)
            elif kind == K_READY:
                self._enqueue(p, x, t)
            elif kind == K_SEND:
                self._on_send(p, t)
            else:
                self._plan_interval(a, b)
        # anything left was still on its way at the end of the drain time
        left = {}
        for item in heap:
            if item[3] in (K_ARRIVE, K_READY, K_SEND):
                left[item[4].pkt] = item
        for pkt_id in sorted(left):
            item = left[pkt_id]
            p = item[4]
            if item[3] == K_SEND:
                self.counts["sent"] += 1
                self.per_flow[p.flow]["sent"] += 1
            self._finish(p, item[0], item[6] if item[3] == K_ARRIVE else item[5], "unfinished", "sim_end")
        self.heap = []
        self.timing["loop_s"] = time.perf_counter() - t_start
        self.timing["forward_s"] = self.timing["loop_s"] - self.timing.get("plan_s", 0.0)
        return self.summary()

    # ------------------------------------------------------------------ summary
    def summary(self):
        self.counts["hop_events"] = self.hop_events
        c = dict(self.counts)
        accounted = c["delivered"] + c["dropped"] + c["no_route"] + c["unfinished"]
        conservation = {"sent": c["sent"], "accounted": accounted, "ok": accounted == c["sent"]}
        flows = []
        for f in self.sc.flows:
            pf = self.per_flow[f.flow_id]
            lat = sorted(pf["latency_ns"])
            flows.append({"flow_id": f.flow_id, "src": f.src, "dst": f.dst, "sent": pf["sent"],
                          "delivered": pf["delivered"], "no_route": pf["no_route"], "dropped": pf["dropped"],
                          "unfinished": pf["unfinished"], "late": pf["late"], "fallback": pf["fallback"],
                          "pdr": (pf["delivered"] / pf["sent"]) if pf["sent"] else None,
                          # quantiles OF DELIVERED PACKETS ONLY (nearest rank): lost and route-less
                          # packets do not appear in them, so read them next to pdr...
                          "latency_quantiles_of": "delivered packets only (nearest rank)",
                          "latency_ns_min": lat[0] if lat else None,
                          "latency_ns_p50": _nearest_rank(lat, 1, 2, len(lat)),
                          "latency_ns_p99": _nearest_rank(lat, 99, 100, len(lat)),
                          "latency_ns_max": lat[-1] if lat else None,
                          # ...or use the EFFECTIVE quantiles: over every sent packet, a packet that
                          # was not delivered counting as +inf (eval/metrics.py), "inf" when more
                          # than (1 - p) of the packets were lost
                          "latency_eff_ns_p50": _nearest_rank(lat, 1, 2, pf["sent"]),
                          "latency_eff_ns_p99": _nearest_rank(lat, 99, 100, pf["sent"]),
                          "great_circle_km": round(f.great_circle_km, 3)})
        qstats = {"links_used": len(self.queues), "max_wait_ns": 0, "fg_dropped": 0}
        bg = {"bg_arrived": 0, "bg_dropped": 0, "cftp_skips": 0, "cftp_fallbacks": 0, "fluid_lost_bits": 0}
        for q in self.queues.values():
            s = q.stats()
            qstats["max_wait_ns"] = max(qstats["max_wait_ns"], s["max_wait_ns"])
            qstats["fg_dropped"] += s["fg_dropped"]
            for k in bg:
                bg[k] += s.get(k, 0)
        loop = self.timing.get("loop_s", 0.0)
        fwd = self.timing.get("forward_s", 0.0)
        chunk_fwd = self.topo.chunk_seconds - self.timing.get("plan_chunk_s", 0.0)
        fwd_pure = fwd - chunk_fwd
        rows = self.schedule_rows
        return {
            "counts": c, "drops": {k: v for k, v in self.drops.items() if v},
            "fallback_reasons": self.fb_reasons, "conservation": conservation,
            "flows": flows, "queues": qstats, "background": bg if self.bg_model != "none" else None,
            "invariants": dict(self.inv),
            "hop_processor": {"mode": self.hp.mode, "verify_every": self.hp.verify_every,
                              "verified_calls": self.hp.verified},
            "schedule": {"rows": sum(1 for r in rows if r[3] is not None),
                         "gaps": sum(1 for r in rows if r[3] is None), "plan_calls": self.sc.plan_calls},
            "faults_logged": len(self.faults.log),
            "max_hops": self.max_hops_seen,
            "timing_s": {"loop": round(loop, 3), "plan": round(self.timing.get("plan_s", 0.0), 3),
                         "forward": round(fwd, 3),
                         "topology_pass1": round(self.topo.pass1_seconds, 3),
                         "topology_chunks": round(self.topo.chunk_seconds, 3),
                         "forward_excluding_topology": round(fwd_pure, 3)},
            # forwarding only (planning and topology building excluded): the engine's own speed
            "hop_events_per_s_forwarding": round(c["hop_events"] / fwd_pure, 1) if fwd_pure > 0 else None,
            # the whole event loop (planning and topology included); command.py adds the
            # end-to-end rate over the total wall time (scenario build and output writing too)
            "hop_events_per_s_loop": round(c["hop_events"] / loop, 1) if loop > 0 else None,
            "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1),
            "topology_chunks_built": self.topo.chunks_built,
        }


def _nearest_rank(sorted_values, num, den, n_total):
    """Nearest-rank quantile p = num/den: the value of rank ceil(p * n_total) (exact integers).
    n_total > len(sorted_values): the missing ones are lost packets (+inf); "inf" if the rank
    falls among them, None if there is nothing at all."""
    if n_total == 0:
        return None
    r = max(1, -(-num * n_total // den))
    return sorted_values[r - 1] if r <= len(sorted_values) else "inf"


def _set_dev(raw, k):
    """Bytes with DEV set at hop k (what a strict-drop node saw when it discarded the packet)."""
    if raw[4] & proto.FLAG_DEV:
        return raw
    b = bytearray(raw)
    b[4] |= proto.FLAG_DEV
    b[6] = k
    return bytes(b)


def rerun_with_fault(run_dir, **kw):
    """The viewer's live-mode hook (viz/sources.ENGINE_HOOK): re-run a finished run with one
    extra fault on one link, same seed and random numbers. See fwd/rerun.py (imported here
    lazily: it needs command.py, which imports this module)."""
    from .rerun import rerun_with_fault as impl
    return impl(run_dir, **kw)


__all__ = ["Engine", "Packet", "Port", "InvariantViolation", "OUTCOMES", "DROP_REASONS", "rerun_with_fault"]

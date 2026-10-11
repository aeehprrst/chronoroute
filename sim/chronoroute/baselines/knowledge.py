"""
knowledge.py
------------
What each scheme's control plane BELIEVES about the network at time t, and
the next-hop tables that follow from that belief. This is where the
schemes really differ; the data plane (engine.py) and the physics (fwd/)
are shared.

All times are integer ns after t0. "Truth" is what the engine applies to
packets: the geometry of the current 100 ms step (fwd/topology.py) and the
faults (fwd/faults.py).

  Truth            shared helper: fault timeline (segments between fault
                   change points), true graphs, flood trees, the sat-only
                   components used to count flooded copies.
  OracleTopology   O-T: the true graph at the instant of the decision
                   (geometry + link/node failures), nothing about slowness.
  SnapKnowledge    SNAP (Hypatia-style tables): geometry is predicted
                   perfectly (tables are precomputed per step), failures are
                   known only through telemetry (delay T_tel after the
                   satellite noticed them, carrier_detect after onset) and
                   enter the tables at the next upload (every Delta_up, plus
                   an upload latency). Table active at t was computed at upload
                   U = floor((t - latency) / Delta_up) * Delta_up with the
                   failures that had happened by U - T_tel - carrier_detect.
  LinkState        LS-H: hello link-state. Every node keeps its own view.
                   A link end notices a failed link by loss of carrier after
                   carrier_detect (the engine's forwarding.carrier_detect_ms:
                   the SAME delay after which every other scheme's node
                   notices it, docs/baselines.md 2.3), or, with
                   fault_detection "hello" (a silent failure, sensitivity
                   only), when no hello came for the dead interval (or BFD's
                   detection time); it declares the link alive at the next
                   hello, and notices a geometric loss of carrier after
                   carrier_detect. The end then originates a
                   router-LSA (at most once per MinLSInterval); node X learns
                   it at origination + flood time to X + SPF delay. X uses a
                   link only if BOTH ends' latest LSAs it knows list it (the
                   OSPF two-way check, RFC 2328 16.1). Slowness is invisible.
                   Cost: every node's view is exact, so under churn nodes hold
                   many different views at once; a decision is answered from a
                   SHARED tree whenever that provably gives the node's own
                   answer (LinkState._shortcut, checked against full
                   computations in the tests), and caches are bounded
                   (BoundedCache), so memory stays flat.
  LinkStateDelay   LS-D: LS-H plus RFC 7471-style delay metrics: each link
                   direction is measured over windows of M seconds (probes
                   every probe_ms, average or minimum), and a new value is
                   advertised when it changed by more than theta (accelerated,
                   at most once per min_interval); nodes learn it like any LSA.

Idealisation shared by O-T, SNAP, LS-H and LS-D (it FAVOURS the baselines and
is stated in docs/baselines.md): the delay part of every link metric is the
true light time of the current step, as if metrics were perfectly tuned to
the geometry. LS-D only adds its measured EXCESS delay (queueing, link-delay
faults, ARQ) on top. This isolates what the experiments are about: how fast
each control plane reacts to failures and slowness.
"""

import bisect
import heapq
from collections import OrderedDict
from fractions import Fraction

import numpy as np

from ..fwd.config import exact_fraction
from . import control as ctl, keyed
from .params import LS_PRESETS, MS, S, to_ns
from .paths import BeliefGraph, bfs_hops_multi, bfs_tree, tree_to

NEVER = 1 << 62
KEEP_STEPS = 40              # cached graphs/trees older than this many steps are dropped
GEO, FAULT, METRIC = 0, 1, 2

# periodic re-flooding of every router-LSA: LSRefreshTime = 30 min (RFC 2328 appendix B) for
# EVERY preset. The periodic OLSR TC messages (TC_INTERVAL 5 s, RFC 3626 section 18.2) are NOT
# modelled: flooding them with this OSPF-like byte model (no MPR selection) would charge OLSR
# for copies that MPR flooding never sends, so the byte model favours the OLSR presets instead.
REFRESH_S = {"olsr_leo": 1800, "olsr": 1800, "ospf": 1800}


def ceil_div(a, b):
    return -(-a // b)


class BoundedCache:
    """A cache with an entry limit: the least recently used entry is dropped first.

    Every value cached in this module (a graph, a shortest-path tree, a component table)
    is a pure function of its key, so dropping one only costs a recomputation. Why a limit
    and not only the step-age pruning (KEEP_STEPS): with carrier detection and renewal
    failures on a real shell (1 % of 5,400 laser links failing about 27 times a second), the
    link-state nodes hold thousands of DIFFERENT views within a few seconds, each with its own
    graph (~1 MB) and trees (~0.2 MB each); without a limit an LS-H run grew past 6.6 GB and
    was killed. On a real-shell graph the limits below keep each cache under ~250 MB.
    """

    __slots__ = ("limit", "d")

    def __init__(self, limit):
        self.limit = int(limit)
        self.d = OrderedDict()

    def get(self, key, default=None):
        v = self.d.get(key, default)
        if v is not default:
            self.d.move_to_end(key)
        return v

    def __setitem__(self, key, value):
        self.d[key] = value
        self.d.move_to_end(key)
        while len(self.d) > self.limit:
            self.d.popitem(last=False)

    def __delitem__(self, key):
        del self.d[key]

    def __contains__(self, key):
        return key in self.d

    def __iter__(self):
        return iter(list(self.d))

    def __len__(self):
        return len(self.d)


# =============================================================== truth

class Truth:
    """The true network, as the engine applies it (geometry per step + failures)."""

    def __init__(self, eng, faults):
        self.eng = eng
        self.topo = topo = eng.topo
        self.faults = faults                       # the real fwd.faults.FaultSet
        self.n = topo.n_nodes
        self.n_sats = topo.n_sats
        self.L = topo.n_links
        self.n_isl = topo.n_isl
        self.a = np.asarray(topo.link_a, dtype=np.int64)
        self.b = np.asarray(topo.link_b, dtype=np.int64)
        self.transit = np.asarray(topo.transit, dtype=bool)
        self.proc = int(eng.processing_ns)
        self.step = int(eng._step_ns)
        self.n_steps = int(eng._n_steps)
        pts = set()
        touched = set()
        for li, iv in faults.link_down.items():
            pts.update(iv.starts)
            pts.update(iv.stops)
            touched.add(li)
        for node, iv in faults.node_down.items():
            pts.update(iv.starts)
            pts.update(iv.stops)
            for _nb, li in topo.neighbours[node]:
                touched.add(li)
        self.points = sorted(pts)
        self.touched = sorted(touched)
        self._masks = {}
        self._graphs = BoundedCache(48)
        self._trees = BoundedCache(1024)
        self._comps = BoundedCache(512)
        self._k_seen = 0

    # ------------------------------------------------------------ time
    def step_of(self, t):
        k = t // self.step
        if k < 0:
            return 0
        return k if k < self.n_steps else self.n_steps - 1

    def seg(self, t):
        """Index of the fault segment holding t (the fault state is constant inside one)."""
        return bisect.bisect_right(self.points, t)

    def seg_start(self, seg):
        return self.points[seg - 1] if seg > 0 else -1

    # ------------------------------------------------------------ state
    def fault_mask(self, seg):
        """(L,) bool: link down because of a fault (link_down, or an end satellite down)."""
        m = self._masks.get(seg)
        if m is None:
            m = np.zeros(self.L, dtype=bool)
            t = self.seg_start(seg)
            f = self.faults
            for li in self.touched:
                if f.link_is_down(li, int(self.a[li]), int(self.b[li]), t):
                    m[li] = True
            self._masks[seg] = m
        return m

    def node_down_at(self, node, t):
        return self.faults.node_is_down(node, t)

    def geo(self, k):
        """(up, prop) of every link at step k: geometric up flag and light time ns (-1: no position)."""
        ch = self.topo.chunk_of_step(k)
        i = k - ch.k0
        return ch.up[:, i], ch.prop[:, i]

    def up_mask(self, k, seg):
        up, prop = self.geo(k)
        return up & ~self.fault_mask(seg) & (prop > 0)

    def _prune(self, k):
        if k <= self._k_seen:
            return
        self._k_seen = k
        lo = k - KEEP_STEPS
        for cache in (self._graphs, self._trees, self._comps):
            for key in [x for x in cache if x[0] < lo]:
                del cache[key]

    def graph(self, k, seg, extra):
        """True graph at (step k, fault segment seg), weights = light time + extra (symmetric)."""
        key = (k, seg, extra)
        g = self._graphs.get(key)
        if g is None:
            self._prune(k)
            m = self.up_mask(k, seg)
            _up, prop = self.geo(k)
            w = prop[m] + extra
            g = BeliefGraph(self.n, self.a[m], self.b[m], w, w, self.transit)
            self._graphs[key] = g
        return g

    def any_down(self, path, t):
        """True if a link of the node path is failed at t (link_down, or an end satellite down)."""
        idx = self.topo.link_index
        f = self.faults
        if not (f.link_down or f.node_down):
            return False
        for u, v in zip(path[:-1], path[1:]):
            if f.link_is_down(idx[(u, v)], u, v, t):
                return True
        return False

    def best_path(self, k, t, extra, src, dst):
        """(cost, path src..dst) of a cheapest path on the TRUE graph at (step k, time t).

        Shortcut that is exact: a failure only removes links, so if the cheapest path of the
        failure-free graph of step k has no failed link at t, it is also a cheapest path of
        the faulted graph. Only otherwise is the faulted graph (one per fault segment) used;
        with renewal faults on every ISL this saves most of the shortest-path trees.
        """
        geo = self.tree(k, 0, extra, dst)
        if geo.dist[src] is not None:
            p = geo.path(src)
            if not self.any_down(p, t):
                return geo.dist[src], p
        tr = self.tree(k, self.seg(t), extra, dst)
        if tr.dist[src] is None:
            return None, None
        return tr.dist[src], tr.path(src)

    def fewest_hops(self, k, t, extra, src, dst):
        """Fewest links src -> dst on the true graph at (k, t) (same exact shortcut)."""
        for seg in (0, None):
            s = self.seg(t) if seg is None else 0
            key = (k, s, extra, src, "bfs")
            bt = self._trees.get(key)
            if bt is None:
                bt = bfs_tree(self.graph(k, s, extra), src)
                self._trees[key] = bt
            hops, nxt = bt
            if hops[dst] is None:
                if seg is None:
                    return None
                continue
            p = [dst]
            while p[-1] != src:
                p.append(nxt[p[-1]])
            if seg is None or not self.any_down(p, t):
                return hops[dst]
        return None

    def tree(self, k, seg, extra, root):
        """Shortest paths to root on the true graph (= from root: weights are symmetric)."""
        key = (k, seg, extra, root)
        tr = self._trees.get(key)
        if tr is None:
            tr = tree_to(self.graph(k, seg, extra), root)
            self._trees[key] = tr
        return tr

    def hops_to_ground(self, k, seg):
        """Fewest links from every node to its nearest ground station (relaying reports down,
        and uploads up: an upload to a satellite without a ground link takes 1 uplink + h - 1
        ISL hops). One multi-source BFS from all stations at once; equal to the minimum over
        one BFS per station (tested), since a station never relays."""
        key = (k, seg, "gs_hops")
        h = self._comps.get(key)
        if h is None:
            h = bfs_hops_multi(self.graph(k, seg, 1), range(self.n_sats, self.n))
            self._comps[key] = h
        return h

    def components(self, k, seg):
        """Satellite components of the ISL graph and per-component sums (for flood copy counts)."""
        key = (k, seg, "comp")
        c = self._comps.get(key)
        if c is not None:
            return c
        m = self.up_mask(k, seg)
        S_ = self.n_sats
        isl = np.flatnonzero(m[:self.n_isl])
        gsl = np.flatnonzero(m[self.n_isl:]) + self.n_isl
        adj = [[] for _ in range(S_)]
        for li in isl.tolist():
            a, b = int(self.a[li]), int(self.b[li])
            adj[a].append(b)
            adj[b].append(a)
        label = [-1] * S_
        n_sat, sum_isl, n_gsl = [], [], []
        for s0 in range(S_):
            if label[s0] >= 0:
                continue
            cid = len(n_sat)
            label[s0] = cid
            stack = [s0]
            cnt = deg = 0
            while stack:
                u = stack.pop()
                cnt += 1
                deg += len(adj[u])
                for v in adj[u]:
                    if label[v] < 0:
                        label[v] = cid
                        stack.append(v)
            n_sat.append(cnt)
            sum_isl.append(deg)
            n_gsl.append(0)
        gs_links = {}
        for li in gsl.tolist():
            sat, gs = int(self.a[li]), int(self.b[li])
            n_gsl[label[sat]] += 1
            gs_links.setdefault(gs, []).append(sat)
        deg_all = np.bincount(np.concatenate([self.a[m], self.b[m]]), minlength=self.n).tolist()
        deg_isl = [len(x) for x in adj]
        c = {"label": label, "n_sat": n_sat, "sum_isl": sum_isl, "n_gsl": n_gsl, "gs_links": gs_links,
             "deg": deg_all, "deg_isl": deg_isl}
        self._comps[key] = c
        return c

    def flood_copies(self, k, seg, origin):
        """{medium: (data copies, ack copies)} of one LSA flooded from origin (see control.py).

        Satellites relay floods, ground stations do not (they are stubs, like in the data
        plane). From a satellite of component c: every satellite sends on all its ISLs but
        its parent link, so the ISLs carry sum_isl - (n_sat - 1) copies, and every ground
        link of c carries one copy down. From a ground station g: g sends up on each of its
        links; its neighbours' parent is that ground link. Every received copy is
        acknowledged in the opposite direction (one LSAck per copy).
        """
        c = self.components(k, seg)
        isl = down = up = 0
        if origin < self.n_sats:
            cid = c["label"][origin]
            isl = c["sum_isl"][cid] - (c["n_sat"][cid] - 1)
            down = c["n_gsl"][cid]
        else:
            sats = c["gs_links"].get(origin, [])
            up = len(sats)
            per = {}
            for s in sats:
                per[c["label"][s]] = per.get(c["label"][s], 0) + 1
            for cid, m_c in per.items():
                isl += c["sum_isl"][cid] - (c["n_sat"][cid] - m_c)
                down += c["n_gsl"][cid] - m_c
        return {"isl": (isl, isl), "downlink": (down, 0), "uplink": (up, 0),
                "ack_uplink": down, "ack_downlink": up}

    def count_flood(self, ledger, k, seg, origin, msg_type, lsu_bytes):
        cp = self.flood_copies(k, seg, origin)
        for med in ("isl", "downlink", "uplink"):
            data, _ = cp[med]
            if data:
                ledger.add(med, msg_type, data * lsu_bytes, data)
        acks = {"isl": cp["isl"][1], "uplink": cp["ack_uplink"], "downlink": cp["ack_downlink"]}
        for med, n in acks.items():
            if n:
                ledger.add(med, msg_type + "_ack", n * ctl.LSACK_BYTES, n)


# =============================================================== O-T

class OracleTopology:
    """O-T knowledge: the true graph at the decision instant."""

    def __init__(self, truth):
        self.truth = truth

    def route(self, src, dest, t, k, extra):
        """A cheapest path src -> dest on the true graph at the decision instant (or None)."""
        return self.truth.best_path(k, t, extra, src, dest)[1]


# =============================================================== SNAP

class SnapKnowledge:
    """SNAP: precomputed per-step tables; failures known after telemetry + next upload."""

    def __init__(self, eng, truth, scheme, ledger):
        sn = scheme["snap"]
        self.eng, self.truth, self.ledger = eng, truth, ledger
        self.update_ns = to_ns(sn["update_s"], S, "snap.update_s")
        self.tel_ns = to_ns(sn["telemetry_s"], S, "snap.telemetry_s")
        self.lat_ns = to_ns(sn["upload_latency_ms"], MS, "snap.upload_latency_ms")
        self.entry_bytes = sn["entry_bytes"]
        self.hdr_bytes = sn["upload_header_bytes"]
        self.tel_bytes = sn["telemetry_bytes"]
        self.count_uploads = sn["count_uploads"]
        # telemetry reports what a satellite has NOTICED: a failure carrier_detect after onset
        # (the one failure-visibility model shared by every scheme, docs/baselines.md 2.3)
        self.carrier_ns = int(getattr(eng, "carrier_ns", 0))
        self.extra = truth.proc
        self._trees = BoundedCache(1024)
        # table epochs already accounted (for upload bytes)
        self._t_done = -1
        self._last_key = None
        self._last_nxt = {}                  # dest -> next-hop list of the previous table
        self._msg = set()                    # (node, upload instant) that already paid a message header
        self.uploads = {"tables": 0, "entries_changed": 0}
        # telemetry: every fault change point of a link, reported by its live ends
        self._tel = []
        f = truth.faults
        for li, iv in f.link_down.items():
            for s_, e_ in zip(iv.starts, iv.stops):
                self._tel += [(s_, li, None), (e_, li, None)]
        for node, iv in f.node_down.items():
            for s_, e_ in zip(iv.starts, iv.stops):
                for _nb, li in truth.topo.neighbours[node]:
                    self._tel += [(s_, li, node), (e_, li, node)]
        self._tel.sort()
        self._tel_i = 0

    def upload_instant(self, t):
        x = t - self.lat_ns
        return (x // self.update_ns) * self.update_ns if x >= 0 else None

    def key(self, t, k):
        u = self.upload_instant(t)
        x = None if u is None else u - self.tel_ns - self.carrier_ns
        if x is None or x < 0:
            seg = 0                                    # the table computed before the run: no failures known
        else:
            seg = self.truth.seg(x)
        return (k, seg)

    def tree(self, dest, t, k):
        key = self.key(t, k)
        kk = key + (dest,)
        tr = self._trees.get(kk)
        if tr is None:
            if len(self._trees) > 4096:
                lo = k - KEEP_STEPS
                for x in [x for x in self._trees if x[0] < lo]:
                    del self._trees[x]
            tr = self.truth.tree(key[0], key[1], self.extra, dest)
            self._trees[kk] = tr
        return tr

    def advance(self, t):
        """Account telemetry and table uploads for everything up to t (bytes only)."""
        tr = self.truth
        while self._tel_i < len(self._tel) and self._tel[self._tel_i][0] <= t:
            tc, li, dead = self._tel[self._tel_i]
            self._tel_i += 1
            k = tr.step_of(tc)
            hops = tr.hops_to_ground(k, tr.seg(tc))
            for end in (int(tr.a[li]), int(tr.b[li])):
                if end == dead or end >= tr.n_sats or tr.node_down_at(end, tc):
                    continue
                self.ledger.add("downlink", "snap_telemetry", self.tel_bytes)
                h = hops[end]
                if h:
                    self.ledger.add("isl", "snap_telemetry_relay", self.tel_bytes * (h - 1), h - 1)
        if not self.count_uploads:
            return
        # table epochs: step starts and upload activations, in time order
        t0 = self._t_done + 1
        if t < t0:
            return
        times = set()
        for k in range(tr.step_of(t0), tr.step_of(t) + 1):
            st = k * tr.step
            if t0 <= st <= t:
                times.add(st)
        first_u = ceil_div(t0 - self.lat_ns, self.update_ns) * self.update_ns
        for u in range(max(first_u, 0), t - self.lat_ns + 1, self.update_ns):
            if t0 <= u + self.lat_ns <= t:
                times.add(u + self.lat_ns)
        if self._last_key is None:
            times.add(0)
        for tau in sorted(times):
            key = self.key(tau, tr.step_of(tau))
            if key == self._last_key:
                continue
            u = self.upload_instant(tau)
            self._count_tables(key, -1 if u is None else u)
            self._last_key = key
        self._t_done = t

    def _count_tables(self, key, upload):
        """Bytes to bring every node's table from the previous epoch's to this one's."""
        tr = self.truth
        first = not self._last_nxt
        changed = [0] * tr.n
        for g in range(tr.n_sats, tr.n):
            nxt = tr.tree(key[0], key[1], self.extra, g).nxt
            old = self._last_nxt.get(g)
            if old is None:
                for i in range(tr.n):
                    changed[i] += 1
            else:
                for i, (x, y) in enumerate(zip(nxt, old)):
                    if x != y:
                        changed[i] += 1
            self._last_nxt[g] = nxt
        self.uploads["tables"] += 1
        hops = None
        for node, c in enumerate(changed):
            if not c:
                continue
            self.uploads["entries_changed"] += c
            if first:
                continue                          # the initial tables are state, not run-time traffic
            med = "uplink" if node < tr.n_sats else "ground"
            n_bytes = c * self.entry_bytes
            hdr = 0
            if (node, upload) not in self._msg:
                self._msg.add((node, upload))
                hdr = self.hdr_bytes
            self.ledger.add(med, "snap_table_upload", n_bytes + hdr, 1 if hdr else 0)
            if med == "uplink":
                # a satellite without a ground link of its own gets its table relayed over
                # h - 1 laser hops from the nearest one that has one (as ChronoRoute's uploads)
                if hops is None:
                    u0 = max(upload, 0)
                    hops = tr.hops_to_ground(tr.step_of(u0), tr.seg(u0))
                h = hops[node]
                if h is None:
                    self.uploads["unreachable"] = self.uploads.get("unreachable", 0) + 1
                elif h > 1:
                    self.ledger.add("isl", "snap_table_upload_relay", (n_bytes + hdr) * (h - 1),
                                    (h - 1) if hdr else 0)

    def initial_state_bytes(self):
        """Every node holds one entry per destination station."""
        return (self.truth.n - self.truth.n_sats) * self.entry_bytes


# =============================================================== ChronoRoute satellite state uploads

class CrhStateUploads:
    """What a ChronoRoute-family satellite (crh data plane) must be SENT, besides the schedule
    rows the ground hands to the ingress gateway (reviewer must-fix #3: "Count the FIB/SID-map
    uploads, ephemeris uploads ... split by medium").

    Two periodic uploads to every satellite, each satellite at its own keyed phase in
    [0, period), so a run shorter than the period sees the right fraction of them and two
    runs with the same seed see the same instants:

      crh_fib_refresh   its CRH-FIB: one entry (SID -> interface) per laser partner and per
                        ground station (a station's ground link can come up at any time, so
                        every station SID needs an entry), plus, with a fallback function,
                        the station table (each station's coordinates: greedy forwarding
                        towards SID[0] needs the destination's position). The SID registry
                        is stable and append-only (keyed by NORAD id), so no SID map has to be
                        re-sent beyond this.
      ephemeris_upload  (only with a fallback function) the element sets of the satellite and
                        of its laser partners (TLE-sized records); it propagates their
                        positions on board (SGP4) for the greedy choice.

    Medium: one copy on the UPLINK (ground -> the nearest satellite with a ground link) and
    one on each of the h - 1 laser hops that relay it on (h = fewest links from any station
    at the upload instant, Truth.hops_to_ground). A satellite no station can reach at that
    instant is counted in stats["unreachable"], not charged. Sizes and periods are scheme
    parameters (params.DEFAULTS["crh_state"]); state_report uses the same sizes.
    """

    def __init__(self, eng, truth, scheme, ledger):
        cs = scheme["crh_state"]
        self.truth, self.ledger = truth, ledger
        S_ = truth.n_sats
        self.n_gs = truth.n - S_
        self.fallback = eng.cfg["forwarding"]["fallback"] != "none"
        isl_a, isl_b = truth.a[:truth.n_isl], truth.b[:truth.n_isl]
        self.partners = np.bincount(np.concatenate([isl_a, isl_b]), minlength=truth.n)[:S_].astype(np.int64)
        hdr = int(cs["upload_header_bytes"])
        self.fib_body = (self.partners + self.n_gs) * int(cs["fib_entry_bytes"])
        self.station_table = self.n_gs * int(cs["gs_coord_bytes"]) if self.fallback else 0
        self.eph_body = (1 + self.partners) * int(cs["tle_bytes"]) if self.fallback else None
        seed = eng.cfg["seed"]
        end = int(eng.sc.end_ns)
        kinds = [("crh_fib_refresh", to_ns(cs["fib_refresh_s"], S), "crh_fib_phase",
                  hdr + self.fib_body + self.station_table)]
        if self.fallback:
            kinds.append(("ephemeris_upload", to_ns(cs["ephemeris_upload_s"], S), "crh_eph_phase",
                          hdr + self.eph_body))
        self.periods = {name: period for name, period, _c, _b in kinds}
        inst = []
        for name, period, comp, size in kinds:
            phases = keyed.phases_ns(seed, comp, S_, period).tolist()
            sizes = size.tolist()
            for sat, ph in enumerate(phases):
                t = ph
                while t < end:
                    inst.append((t, name, sat, sizes[sat]))
                    t += period
        inst.sort()
        self._inst = inst
        self._i = 0
        self.stats = {"crh_fib_refresh": 0, "ephemeris_upload": 0, "unreachable": 0}
        # Amortised rate (DERIVED): a run much shorter than the period charges only the few
        # satellites whose phase falls inside it (often none on a small constellation), so the
        # ledger's bytes per second of one short run are very noisy. The steady-state rate is
        # exact: sum over satellites of size / period on the uplink, times (h - 1) on the ISLs,
        # h from the failure-free topology at the first step.
        hops = truth.hops_to_ground(0, 0)
        up = isl = 0.0
        for _name, period, _comp, size in kinds:
            for sat, b in enumerate(size.tolist()):
                h = hops[sat]
                if h is None:
                    continue
                up += b * 1e9 / period
                isl += b * (h - 1) * 1e9 / period
        self.steady = {"uplink": round(up, 3), "isl": round(isl, 3),
                       "note": "DERIVED: sum over satellites of upload size / period (uplink), times "
                               "(h - 1) laser relay hops (isl), h at the first step without failures"}

    def advance(self, t):
        """Charge every upload whose instant is <= t."""
        tr = self.truth
        inst = self._inst
        while self._i < len(inst) and inst[self._i][0] <= t:
            tu, name, sat, size = inst[self._i]
            self._i += 1
            h = tr.hops_to_ground(tr.step_of(tu), tr.seg(tu))[sat]
            if h is None:
                self.stats["unreachable"] += 1
                continue
            self.stats[name] += 1
            self.ledger.add("uplink", name, size)
            if h > 1:
                self.ledger.add("isl", name + "_relay", size * (h - 1), h - 1)

    def state(self):
        """Bytes a satellite holds (means over satellites), the same sizes as the uploads."""
        out = {"crh_fib_bytes_mean": round(float(self.fib_body.mean()), 1),
               "station_table_bytes": int(self.station_table),
               "fallback_ephemeris_bytes_mean": round(float(self.eph_body.mean()), 1) if self.fallback else 0.0}
        return out


# =============================================================== link state

class Change:
    __slots__ = ("cid", "layer", "li", "end", "value", "orig", "K", "kmin", "kmax")

    def __init__(self, cid, layer, li, end, value, orig, K):
        self.cid, self.layer, self.li, self.end, self.value, self.orig, self.K = (
            cid, layer, li, end, value, orig, K)
        finite = [x for x in K if x < NEVER]
        self.kmin = min(finite) if finite else NEVER
        self.kmax = max(finite) if finite else NEVER


def merge_intervals(iv):
    out = []
    for s, e in sorted(iv):
        if e <= s:
            continue
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def hello_detections(lost, phase, H, D):
    """[(t_dead, outage_end, t_next_hello)] for a receiver of hellos sent at phase + n H (n >= 0).

    lost: merged [(s, e)) intervals during which every hello is lost. The receiver
    declares the neighbour dead at r + D, r = the last hello it received, when no hello
    arrives in (r, r + D]; the next received hello (t_next_hello) brings it back. Hello
    propagation time (ms) is ignored against intervals of seconds. Before t = 0 the
    adjacency is up and the last hello was at phase - H.
    """
    ranges = []
    for s, e in lost:
        n0 = max(0, ceil_div(s - phase, H))
        n1 = ceil_div(e - phase, H) - 1                    # hellos with s <= time < e
        if n1 >= n0:
            if ranges and n0 <= ranges[-1][1] + 1:
                ranges[-1][1] = max(ranges[-1][1], n1)
                ranges[-1][2] = max(ranges[-1][2], e)
            else:
                ranges.append([n0, n1, e])
        elif ranges and ranges[-1][2] >= s:
            ranges[-1][2] = max(ranges[-1][2], e)
    out = []
    for n0, n1, end in ranges:
        r = phase + (n0 - 1) * H
        nxt = phase + (n1 + 1) * H
        if nxt - r > D:
            out.append((r + D, end, nxt))
    return out


class LinkState:
    """LS-H (see the module docstring)."""

    name = "ls_h"

    def __init__(self, eng, truth, scheme, ledger):
        ls = scheme["ls"]
        self.eng, self.truth, self.ledger = eng, truth, ledger
        self.preset = ls["preset"]
        self.H = to_ns(ls["hello_s"], S)
        self.D = to_ns(ls["dead_s"], S)
        self.minlsi = to_ns(ls["min_ls_interval_s"], S)
        self.spf = to_ns(ls["spf_delay_ms"], MS)
        self.lsa_hop = int(ls["lsa_hop_ns"]) if ls["lsa_hop_ns"] is not None else truth.proc
        # ONE failure-visibility model for every scheme (docs/baselines.md 2.3): the carrier
        # detection time is the engine's forwarding.carrier_detect_ms, the same delay after
        # which ChronoRoute's step 7, SNAP and LQ notice a failed link. A different LS value
        # would make the comparison unequal, so it is refused rather than used.
        eng_carrier = int(getattr(eng, "carrier_ns", 0))
        if ls["carrier_detect_ms"] is None:
            self.carrier = eng_carrier
        else:
            self.carrier = to_ns(ls["carrier_detect_ms"], MS)
            if self.carrier != eng_carrier:
                raise ValueError(f"scheme.ls.carrier_detect_ms ({self.carrier} ns) differs from the engine's "
                                 f"forwarding.carrier_detect_ms ({eng_carrier} ns): every scheme must notice "
                                 "a failed link after the same delay; set forwarding.carrier_detect_ms instead")
        self.adj = to_ns(ls["adjacency_ms"], MS)
        self.bfd = ls["bfd"]
        self.Hb = to_ns(ls["bfd_interval_ms"], MS)
        self.Db = ls["bfd_mult"] * self.Hb
        self.fault_det = ls["fault_detection"]
        self.refresh_ns = REFRESH_S[self.preset] * S
        seed = eng.cfg["seed"]
        L, n = truth.L, truth.n
        self.hello_phase = keyed.phases_ns(seed, "ls_hello_phase", 2 * L, self.H).tolist()
        self.bfd_phase = keyed.phases_ns(seed, "ls_bfd_phase", 2 * L, self.Hb).tolist() if self.bfd else None
        self.refresh_phase = keyed.phases_ns(seed, "ls_refresh_phase", n, self.refresh_ns).tolist()
        up0, prop0 = truth.geo(0)
        geo0 = (up0 & (prop0 > 0))
        self.listed = {GEO: np.repeat(geo0[:, None], 2, axis=1), FAULT: np.ones((L, 2), dtype=bool)}
        self.listed_orig = {GEO: np.full((L, 2), -1, dtype=np.int64), FAULT: np.full((L, 2), -1, dtype=np.int64)}
        self.excess = np.zeros((L, 2), dtype=np.int64)
        self.excess_orig = np.full((L, 2), -1, dtype=np.int64)
        self.version = 0                      # bumped at every new step (the base of the keys)
        self._key_k = 0
        self.settled_step = set()             # changes settled during the current step
        self._settled_changes = []            # the same, as Change objects (for _fast_tree)
        self._snap = None                     # the shared view at the start of the step (_fast_tree)
        self.pending = []
        self.requests = []
        self._rseq = 0
        self._cid = 0
        self.last_step = 0
        self.last_orig = {}
        self.pending_orig = {}
        self.originated = set()
        self._graphs = BoundedCache(32)           # one per distinct node view (~1 MB on the real shell)
        self._trees = BoundedCache(1024)          # one per (view, destination)
        self._t_done = -1
        self._bytes_step = -1                 # hello/BFD bytes counted for steps <= this
        # periodic re-floods: a heap of (time, node), so each advance costs O(log n), not O(n)
        self._refresh = [(p if p > 0 else self.refresh_ns, node) for node, p in enumerate(self.refresh_phase)]
        heapq.heapify(self._refresh)
        self.detections = []                  # (time, kind, a, b, value): first node that updated
        self.stats = {"lsa_originations": 0, "changes": 0, "graphs_built": 0, "trees_built": 0}
        self._fault_requests()

    # ------------------------------------------------------------ requests
    def _push(self, tau, kind, data):
        self._rseq += 1
        heapq.heappush(self.requests, (tau, self._rseq, kind, data))

    def _fault_requests(self):
        """Detection times of every fault-driven adjacency change, at both ends (precomputed)."""
        tr = self.truth
        f = tr.faults
        end_ns = self.eng.sc.end_ns
        for li in tr.touched:
            a, b = int(tr.a[li]), int(tr.b[li])
            own = f.link_down.get(li)
            own_iv = list(zip(own.starts, own.stops)) if own is not None else []
            for e, (me, other) in enumerate(((a, b), (b, a))):
                if me >= tr.n_sats and other >= tr.n_sats:
                    continue
                o_iv = f.node_down.get(other)
                lost = merge_intervals(own_iv + (list(zip(o_iv.starts, o_iv.stops)) if o_iv else []))
                if not lost:
                    continue
                d = 2 * li + (1 - e)              # direction of the hellos this end receives
                hp = self.hello_phase[d]
                if self.fault_det == "carrier":
                    # an outage shorter than the detection time is never noticed (as in the
                    # engine's view, faults.FaultSet.detected_view)
                    dets = [(s_ + self.carrier, e_) for s_, e_ in lost if s_ + self.carrier < e_]
                elif self.bfd:
                    dets = [(td, end) for td, end, _n in hello_detections(lost, self.bfd_phase[d], self.Hb, self.Db)]
                else:
                    dets = [(td, end) for td, end, _n in hello_detections(lost, hp, self.H, self.D)]
                for td, outage_end in dets:
                    if td >= end_ns or f.node_is_down(me, td):
                        continue
                    base = max(outage_end, td)
                    tu = hp + ceil_div(base - hp, self.H) * self.H + self.adj     # next protocol hello
                    self._push(td, "orig", (FAULT, li, e, False))
                    if tu < end_ns:
                        self._push(tu, "orig", (FAULT, li, e, True))

    def _geo_requests(self, k):
        """Requests for the geometric changes at the boundary into step k."""
        tr = self.truth
        up_p, prop_p = tr.geo(k - 1)
        up_k, prop_k = tr.geo(k)
        a_ok = up_p & (prop_p > 0)
        b_ok = up_k & (prop_k > 0)
        tb = k * tr.step
        for li in np.flatnonzero(a_ok != b_ok).tolist():
            if not b_ok[li]:
                for e in (0, 1):
                    self._push(tb + self.carrier, "orig", (GEO, li, e, False))
            else:
                for e in (0, 1):
                    hp = self.hello_phase[2 * li + (1 - e)]
                    tu = hp + ceil_div(tb - hp, self.H) * self.H + self.adj
                    self._push(tu, "orig", (GEO, li, e, True))

    def _originate(self, node, tau):
        """Origination time of the router-LSA carrying a change detected at tau (MinLSInterval)."""
        po = self.pending_orig.get(node)
        if po is not None and tau <= po:
            return po
        last = self.last_orig.get(node)
        o = tau if (last is None or tau >= last + self.minlsi) else last + self.minlsi
        self.last_orig[node] = o
        self.pending_orig[node] = o
        return o

    def _flood_K(self, origin, o):
        """Knowledge time of every node for an LSA originated by `origin` at o."""
        tr = self.truth
        k, seg = tr.step_of(o), tr.seg(o)
        dist = tr.tree(k, seg, self.lsa_hop, origin).dist
        spf = self.spf
        return [NEVER if d is None else o + d + spf for d in dist], k, seg

    def _apply_request(self, tau, kind, data):
        tr = self.truth
        if kind == "orig":
            layer, li, e, value = data
            node = int(tr.a[li]) if e == 0 else int(tr.b[li])
            o = self._originate(node, tau)
            K, k, seg = self._flood_K(node, o)
            if (node, o) not in self.originated:
                self.originated.add((node, o))
                self.stats["lsa_originations"] += 1
                deg = tr.components(k, seg)["deg"][node]
                tr.count_flood(self.ledger, k, seg, node, "lsa_router", ctl.router_lsu_bytes(deg))
        else:                                                   # "metric" (LS-D)
            li, e, value = data
            node = int(tr.a[li]) if e == 0 else int(tr.b[li])
            o = tau
            K, k, seg = self._flood_K(node, o)
            layer = METRIC
            deg = tr.components(k, seg)["deg"][node]
            tr.count_flood(self.ledger, k, seg, node, "lsa_te_delay", self._te_bytes(deg))
        self._cid += 1
        c = Change(self._cid, layer, li, e, value, o, K)
        self.pending.append(c)
        self.stats["changes"] += 1
        if layer == FAULT and value is False:
            self.detections.append((c.kmin, "adjacency_down", int(tr.a[li]), int(tr.b[li]), e))
        elif layer == METRIC:
            self.detections.append((c.kmin, "metric", int(tr.a[li]), int(tr.b[li]), e, int(value)))

    def _te_bytes(self, degree):
        return ctl.te_lsu_bytes(False) + (degree - 1) * (ctl.TE_TLV_HEADER + ctl.TE_LINK_TYPE_SUBTLV
                                                         + ctl.TE_LINK_ID_SUBTLV + ctl.DELAY_SUBTLV)

    # ------------------------------------------------------------ periodic bytes
    def _count_periodic(self, t):
        tr = self.truth
        # hellos / BFD per step, exactly: hellos of direction d in [t0, t1) are the n with
        # t0 <= phase + nH < t1; counted for the steps that are complete or current
        k_end = tr.step_of(t)
        end_ns = self.eng.sc.end_ns
        for k in range(self._bytes_step + 1, k_end + 1):
            t0, t1 = k * tr.step, min((k + 1) * tr.step, end_ns)     # nothing is sent after the run
            if t0 >= t1:
                continue
            up, prop = tr.geo(k)
            m = np.flatnonzero(up & (prop > 0))
            self._count_timer(m, t0, t1, self.hello_phase, self.H, ctl.HELLO_BYTES, "hello", k)
            if self.bfd:
                self._count_timer(m, t0, t1, self.bfd_phase, self.Hb, ctl.BFD_BYTES, "bfd", k)
        self._bytes_step = max(self._bytes_step, k_end)
        # periodic re-flooding of every node's LSA (TC_INTERVAL / LSRefreshTime)
        heap = self._refresh
        while heap and heap[0][0] <= t:
            tau, node = heapq.heappop(heap)
            heapq.heappush(heap, (tau + self.refresh_ns, node))
            if tr.node_down_at(node, tau):
                continue
            k, seg = tr.step_of(tau), tr.seg(tau)
            deg = tr.components(k, seg)["deg"][node]
            if deg:
                tr.count_flood(self.ledger, k, seg, node, "lsa_refresh", ctl.router_lsu_bytes(deg))

    def _count_timer(self, links, t0, t1, phases, period, size, name, k):
        tr = self.truth
        if links.size == 0:
            return
        ph = np.asarray(phases, dtype=np.int64)
        down_nodes = None
        if tr.faults.node_down:
            down_nodes = {x for x in tr.faults.node_down if tr.node_down_at(x, t0)}
        isl_n = gsl_up = gsl_down = 0
        for d in (0, 1):
            p = ph[2 * links + d]
            cnt = (np.floor_divide(t1 - 1 - p, period) - np.floor_divide(t0 - 1 - p, period))
            cnt = np.where(p <= t1 - 1, cnt, 0)
            if down_nodes:
                senders = tr.a[links] if d == 0 else tr.b[links]
                cnt = np.where(np.isin(senders, list(down_nodes)), 0, cnt)
            is_isl = links < tr.n_isl
            isl_n += int(cnt[is_isl].sum())
            # ground links: a = satellite, b = station; direction 0 = a -> b = down
            if d == 0:
                gsl_down += int(cnt[~is_isl].sum())
            else:
                gsl_up += int(cnt[~is_isl].sum())
        if isl_n:
            self.ledger.add("isl", name, isl_n * size, isl_n)
        if gsl_up:
            self.ledger.add("uplink", name, gsl_up * size, gsl_up)
        if gsl_down:
            self.ledger.add("downlink", name, gsl_down * size, gsl_down)

    # ------------------------------------------------------------ time
    def advance(self, t):
        if t <= self._t_done:
            return
        tr = self.truth
        k = tr.step_of(t)
        if k != self._key_k:
            # a new step: the shared state as it is now becomes the base of this step's keys
            self._key_k = k
            self.version += 1
            self.settled_step = set()
            # ...and a snapshot of it is the reference view S of the exact shortcut (_fast_tree)
            self._snap = {GEO: self.listed[GEO].copy(), FAULT: self.listed[FAULT].copy()}
            self._snap_orig = {GEO: self.listed_orig[GEO].copy(), FAULT: self.listed_orig[FAULT].copy()}
            self._snap_excess = self.excess.copy()
            self._settled_changes = []
        while self.last_step < k:
            self.last_step += 1
            self._geo_requests(self.last_step)
        self._measure(t)
        while self.requests and self.requests[0][0] <= t:
            tau, _s, kind, data = heapq.heappop(self.requests)
            self._apply_request(tau, kind, data)
        keep = []
        for c in self.pending:
            if c.kmax <= t:
                self._settle(c)
                self.settled_step.add(c.cid)
                self._settled_changes.append(c)
            else:
                keep.append(c)
        if len(keep) != len(self.pending):
            self.pending = keep
        self._count_periodic(t)
        self._t_done = t

    def _measure(self, t):
        """LS-D hook (measurement windows); LS-H measures nothing."""

    def _settle(self, c):
        if c.layer == METRIC:
            if c.orig >= self.excess_orig[c.li, c.end]:
                self.excess[c.li, c.end] = c.value
                self.excess_orig[c.li, c.end] = c.orig
            return
        if c.orig >= self.listed_orig[c.layer][c.li, c.end]:
            self.listed[c.layer][c.li, c.end] = c.value
            self.listed_orig[c.layer][c.li, c.end] = c.orig

    # ------------------------------------------------------------ belief
    def key(self, node, t, k):
        """What node believes at t, as a hashable key: (step, base of this step, the changes it
        knows that were not in the base). A change that settles during the step stays in the
        key (it is in settled_step), so nodes that already knew it keep their key and their
        cached trees: settling changes nothing for them."""
        known = [c.cid for c in self.pending if c.K[node] <= t]
        if not known and not self.settled_step:
            return (k, self.version, frozenset())
        return (k, self.version, frozenset(self.settled_step.union(known)))

    def _graph(self, key):
        g = self._graphs.get(key)
        if g is not None:
            return g
        k, _v, ids = key
        tr = self.truth
        if len(self._graphs) > 256:
            lo = k - KEEP_STEPS
            for x in [x for x in self._graphs if x[0] < lo]:
                del self._graphs[x]
        listed = {GEO: self.listed[GEO], FAULT: self.listed[FAULT]}
        excess = self.excess
        known = [c for c in self.pending if c.cid in ids]        # the others are settled already
        if known:
            listed = {GEO: listed[GEO].copy(), FAULT: listed[FAULT].copy()}
            excess = excess.copy()
            orig = {GEO: self.listed_orig[GEO].copy(), FAULT: self.listed_orig[FAULT].copy(),
                    METRIC: self.excess_orig.copy()}
            for c in known:
                if c.orig >= orig[c.layer][c.li, c.end]:
                    orig[c.layer][c.li, c.end] = c.orig
                    if c.layer == METRIC:
                        excess[c.li, c.end] = c.value
                    else:
                        listed[c.layer][c.li, c.end] = c.value
        _up, prop = tr.geo(k)
        m = listed[GEO].all(axis=1) & listed[FAULT].all(axis=1) & (prop > 0)
        base = prop[m] + tr.proc
        g = BeliefGraph(tr.n, tr.a[m], tr.b[m], base + excess[m, 0], base + excess[m, 1], tr.transit)
        self._graphs[key] = g
        self.stats["graphs_built"] += 1
        return g

    def tree(self, dest, node, t, k):
        """A shortest-path tree to dest under node's view at t; the caller uses ONLY the entries
        of `node` (dist[node], nxt[node]): each node decides with its own view."""
        self.advance(t)
        key = self.key(node, t, k)
        tk = key + (dest,)
        tr_ = self._trees.get(tk)
        if tr_ is None:
            fast = self._fast_tree(dest, node, t, k)
            if fast is not None:
                self.stats["fast_answers"] = self.stats.get("fast_answers", 0) + 1
                if self.verify_fast:
                    full = tree_to(self._graph(key), dest)
                    if (full.dist[node], full.nxt[node]) != (fast.dist[node], fast.nxt[node]):
                        raise AssertionError(f"LS shortcut differs at node {node} -> {dest}, t={t}: "
                                             f"{(fast.dist[node], fast.nxt[node])} != "
                                             f"{(full.dist[node], full.nxt[node])}")
                return fast
            if len(self._trees) > 4096:
                lo = k - KEEP_STEPS
                for x in [x for x in self._trees if x[0] < lo]:
                    del self._trees[x]
            tr_ = tree_to(self._graph(key), dest)
            self._trees[tk] = tr_
            self.stats["trees_built"] += 1
        return tr_

    # ------------------------------------------------------------ exact shortcut
    verify_fast = False          # tests: check every shortcut answer against a full computation

    def _snap_tree(self, k, dest):
        """Shortest paths to dest on S, the snapshot of the shared view at the start of step k."""
        key = (k, "snap", self.version, dest)
        tr_ = self._trees.get(key)
        if tr_ is None:
            gkey = (k, "snap", self.version)
            g = self._graphs.get(gkey)
            if g is None:
                tr = self.truth
                _up, prop = tr.geo(k)
                m = self._snap[GEO].all(axis=1) & self._snap[FAULT].all(axis=1) & (prop > 0)
                base = prop[m] + tr.proc
                ex = self._snap_excess
                g = BeliefGraph(tr.n, tr.a[m], tr.b[m], base + ex[m, 0], base + ex[m, 1], tr.transit)
                self._graphs[gkey] = g
                self.stats["graphs_built"] += 1
            tr_ = tree_to(g, dest)
            self._trees[key] = tr_
            self.stats["trees_built"] += 1
        return tr_

    def _fast_tree(self, dest, node, t, k):
        """A tree whose answer for `node` (dist[node], nxt[node]) is EXACTLY node's answer under
        its own view, from one of two shared reference views, else None (full computation).

          S   the snapshot of the shared view at the start of the step (one tree per
              destination and step); node's view = S changed by the changes settled this
              step and the pending changes node already knows;
          S'  the shared view now (every settled change; one tree per destination and set of
              settled changes); node's view = S' changed by the pending changes it knows.
        _shortcut decides whether the reference tree gives node's answer (the proof is there).
        Under 1 % renewal failures on the real shell, nodes otherwise hold a different view
        at nearly every decision while floods are under way.
        """
        if self._snap is None:
            return None
        known = [c for c in self.pending if c.K[node] <= t]
        if any(c.layer == METRIC for c in known):
            return None
        settled = self._settled_changes
        if not any(c.layer == METRIC for c in settled):
            T = self._shortcut(dest, node, k, self._snap_tree(k, dest), self._snap, self._snap_orig,
                               self._snap_excess, settled + known)
            if T is not None:
                return T
        if not settled:
            return None                            # S' is S: nothing new to try
        base_key = (k, self.version, frozenset(self.settled_step))
        tk = base_key + (dest,)
        T = self._trees.get(tk)
        if T is None:
            T = tree_to(self._graph(base_key), dest)
            self._trees[tk] = T
            self.stats["trees_built"] += 1
        return self._shortcut(dest, node, k, T, self.listed, self.listed_orig, self.excess, known)

    def _shortcut(self, dest, node, k, T, flags, origs, excess, delta):
        """T (shortest paths to dest on the reference view R, given by its link flags, their
        originations and excess delays) when it gives EXACTLY node's answer under its own view
        V = R changed by `delta`, else None. Metric changes are never in delta (callers check).

        Compare the links in each graph: Rm = links in R but not in V, A = links in V but not
        in R. With d = distances to dest in R, a potential: w(u->v) + d[v] >= d[u] on every R
        edge a path can use (an edge into a station other than dest is never usable: stations
        do not relay; d = inf where dest is unreachable):
          * if node's R path to dest uses no link of Rm, it still exists in V with cost d[node];
          * if every edge of A also satisfies w(u->v) + d[v] >= d[u], every path in V costs at
            least d[node] (sum the inequality along it), so d_V[node] = d[node], d_V >= d;
          * node's next hop in V is the lowest-id v with w + d_V[v] = d[node]; such a v has
            w + d[v] = d[node] too, so it is an R candidate (lowest id: R's own next hop, still
            a candidate in V since its path survives) or the far end y of an added edge from
            node with a tie; a tie with y below R's next hop is not shortcut.
        So (dist[node], nxt[node]) of T is V's answer: 'removing a link off the shortest path,
        or adding one that shortens nothing, changes nothing'. Checked against a full
        computation at every shortcut answer in test_baselines_knowledge (verify_fast).
        """
        if not delta:
            return T
        tr = self.truth
        # V's flags for every link a change touches (same rule as _graph and _settle: the
        # change with the latest origination wins, the later one in order on a tie)
        cur = {}
        for c in delta:
            key = (c.layer, c.li)
            st = cur.get(key)
            if st is None:
                st = cur[key] = [flags[c.layer][c.li].copy(), origs[c.layer][c.li].copy()]
            if c.orig >= st[1][c.end]:
                st[1][c.end] = c.orig
                st[0][c.end] = c.value
        _up, prop = tr.geo(k)
        removed, added = set(), []
        for li in {li for _layer, li in cur}:
            g_flags = cur[(GEO, li)][0] if (GEO, li) in cur else flags[GEO][li]
            f_flags = cur[(FAULT, li)][0] if (FAULT, li) in cur else flags[FAULT][li]
            in_v = bool(g_flags.all() and f_flags.all() and prop[li] > 0)
            in_r = bool(flags[GEO][li].all() and flags[FAULT][li].all() and prop[li] > 0)
            if in_r and not in_v:
                removed.add(li)
            elif in_v and not in_r:
                added.append(li)
        d = T.dist
        if d[node] is None:
            return T if not added else None
        if removed:
            idx = tr.topo.link_index
            path = T.path(node)
            for u, v in zip(path[:-1], path[1:]):
                if idx[(u, v)] in removed:
                    return None
        transit = tr.transit
        nxt0 = T.nxt[node]
        for li in added:
            a, b = int(tr.a[li]), int(tr.b[li])
            base = int(prop[li]) + tr.proc
            for u, v, w in ((a, b, base + int(excess[li, 0])), (b, a, base + int(excess[li, 1]))):
                if v != dest and not transit[v]:
                    continue                       # into a station that is not dest: never usable
                if u != node and not transit[u]:
                    continue                       # a station only ever starts its own packets
                dv, du = d[v], d[u]
                if dv is None:
                    continue                       # leads nowhere in R (potential inf): cannot beat d
                if du is None or w + dv < du:
                    return None                    # the added edge would shorten some path
                if w + dv == du and u == node and v < nxt0:
                    return None                    # a tie that could change node's next hop
        return T

    def initial_state_bytes(self):
        """A full link-state database: one router-LSA per node (state, not run-time traffic)."""
        tr = self.truth
        up, prop = tr.geo(0)
        m = up & (prop > 0)
        deg = np.bincount(np.concatenate([tr.a[m], tr.b[m]]), minlength=tr.n)
        return int(sum(ctl.LSA_HEADER + ctl.ROUTER_LSA_FIXED + ctl.ROUTER_LSA_PER_LINK * int(d) for d in deg))


class LinkStateDelay(LinkState):
    """LS-D: LS-H plus measured, advertised per-direction excess delay (module docstring)."""

    name = "ls_d"

    def __init__(self, eng, truth, scheme, ledger):
        super().__init__(eng, truth, scheme, ledger)
        d = scheme["ls_d"]
        self.M = to_ns(d["window_s"], S)
        self.probe = to_ns(d["probe_ms"], MS)
        if self.M % self.probe:
            raise ValueError("ls_d.window_s must be a whole number of probe_ms")
        self.per_window = self.M // self.probe
        th = exact_fraction(d["threshold"], "ls_d.threshold")
        self.th_num, self.th_den = th.numerator, th.denominator
        self.variant = d["variant"]
        self.inter = to_ns(d["inter_update_s"], S)
        self.min_iv = to_ns(d["min_interval_s"], S)
        self.win_phase = keyed.phases_ns(eng.cfg["seed"], "lsd_window_phase", 2 * truth.L, self.M).tolist()
        self.cands = {}                        # (li, dir) -> [samples list, advertised, last_adv]
        self._probes = []                      # heap of (probe time, li, dir)
        self._seen_q = set()
        f = truth.faults
        for li in sorted(set(f.link_delay) | set(f.rate_cuts) | set(f.arq)):
            for e in (0, 1):
                self._add_cand(li, e, 0)
        self._te = [(p if p > 0 else self.inter, node) for node, p in
                    enumerate(keyed.phases_ns(eng.cfg["seed"], "lsd_te_phase", truth.n, self.inter).tolist())]
        heapq.heapify(self._te)
        self.stats.update(probes=0, windows=0, advertisements=0, measured_links=0)

    def _add_cand(self, li, e, t):
        """Start measuring link li in direction e from the first probe instant after t.

        Only links that can show an excess delay are measured: links with a link-delay,
        rate-cut or ARQ fault, and links whose transmit queue exists (it has carried a
        probe packet). Every other link has no queue and no fault, so its measured delay
        IS its light time and its advertised excess stays 0 exactly.
        """
        if (li, e) in self.cands:
            return
        ph = self.win_phase[2 * li + e]
        j = max(1, ceil_div(t - ph + 1, self.probe))        # first instant phase + j * probe > t
        self.cands[(li, e)] = [[], 0, 0]
        heapq.heappush(self._probes, (ph + j * self.probe, li, e))
        self.stats["measured_links"] = len(self.cands)

    def _sample(self, li, e, t):
        tr = self.truth
        a, b = int(tr.a[li]), int(tr.b[li])
        if e == 1:
            a, b = b, a
        x = 0
        q = self.eng.queues.get(a * tr.n + b)
        if q is not None:
            x += int(q.queue_delay_estimate(t))
        f = tr.faults
        if f.link_delay:
            x += f.extra_link_ns(li, t)
        if f.arq:
            arq = f.arq_params(li, t)
            if arq is not None:
                _up, prop = tr.geo(tr.step_of(t))
                x += arq_expected_ns(arq, int(prop[li]))
        return x

    def _measure(self, t):
        tr = self.truth
        if len(self.eng.queues) != len(self._seen_q):
            for key in list(self.eng.queues):
                if key in self._seen_q:
                    continue
                self._seen_q.add(key)
                a, b = divmod(key, tr.n)
                li = tr.topo.link_index[(a, b)]
                self._add_cand(li, 0 if a == int(tr.a[li]) else 1, t)
        heap = self._probes
        while heap and heap[0][0] <= t:
            tp, li, e = heapq.heappop(heap)
            st = self.cands[(li, e)]
            st[0].append(self._sample(li, e, tp))
            self.stats["probes"] += 1
            med = "isl" if li < tr.n_isl else ("downlink" if e == 0 else "uplink")
            self.ledger.add(med, "stamp_probe", ctl.STAMP_PROBE_BYTES)
            heapq.heappush(heap, (tp + self.probe, li, e))
            if (tp - self.win_phase[2 * li + e]) % self.M == 0:
                self._window_end(li, e, st, tp)
        # periodic TE LSA re-advertisement of every router (bytes only; RFC 7471 section 7)
        te = self._te
        while te and te[0][0] <= t:
            tau, node = heapq.heappop(te)
            heapq.heappush(te, (tau + self.inter, node))
            if tr.node_down_at(node, tau):
                continue
            k, seg = tr.step_of(tau), tr.seg(tau)
            deg = tr.components(k, seg)["deg"][node]
            if deg:
                tr.count_flood(self.ledger, k, seg, node, "lsa_te_periodic", self._te_bytes(deg))

    def _window_end(self, li, e, st, w):
        samples = st[0]
        st[0] = []
        self.stats["windows"] += 1
        if not samples:
            return
        n = len(samples)
        m = (sum(samples) // n) if self.variant == "avg" else min(samples)
        adv, last = st[1], st[2]
        _up, prop = self.truth.geo(self.truth.step_of(w))
        ref = int(prop[li]) + adv
        if abs(m - adv) * self.th_den > self.th_num * ref:
            tau = max(w, last + self.min_iv)                 # accelerated (RFC 7471 section 5)
        elif w - last >= self.inter and m != adv:
            tau = w                                          # periodic update carries the new value
        else:
            return
        st[1], st[2] = m, tau
        self.stats["advertisements"] += 1
        self._push(tau, "metric", (li, e, m))


def arq_expected_ns(arq, prop_ns):
    """Mean extra delay of link-layer ARQ (loss p, R retries, 2 prop + extra per retry)."""
    loss, retries, retry_ns = arq
    p = Fraction(loss)
    per = 2 * prop_ns + retry_ns
    mean = sum(p ** a * (1 - p) * a * per for a in range(retries + 1))
    return int(mean)


__all__ = ["NEVER", "Truth", "OracleTopology", "SnapKnowledge", "CrhStateUploads", "LinkState",
           "LinkStateDelay", "Change",
           "merge_intervals", "hello_detections", "arq_expected_ns", "REFRESH_S", "LS_PRESETS"]

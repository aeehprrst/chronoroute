"""
metrics.py
----------
The metric definitions of master plan section 5.3 (science report section 6),
computed from one run folder (load.RunData).

PDR (per flow-run)
    delivered / sent among packets sent in the measurement window
    [warm-up, T_end - drain). Packets are only ever sent before T_end - drain
    (the engine's sending window), so in-flight packets are never counted as
    losses; a packet still unfinished after the drain is a loss of its own
    class. Losses are ALWAYS broken down by reason.

Effective quantile Q_p^eff
    over ALL sent packets, a lost packet counting as +inf; nearest rank
    r = ceil(p n). If fewer than r packets were delivered, Q_p^eff = inf
    (no survivorship bias). Tail rule: P99 is reported only with >= 10^3
    packets in the flow-run, P99.9 only with >= 10^4 (else None).

Latency stretch
    L_det / L*, both deterministic (light time + processing + serialization of
    the flow's packet size without any routing header):
      L_det  the packet's own path, each hop's light time taken at the step in
             which the packet was at the hop's upstream node;
      L*     the cheapest path on the TRUE faulted graph at the send instant
             (geometry of the send step, links/satellites failed at that time).
    Claim (tested on every packet): L_det >= L* - tol whenever every link of the
    packet's path existed in that send-time graph, with
      tol = sum over hops of (steps elapsed since the send) x step_tolerance_ns
    (baselines/engine.py: |change of a light time per 100 ms step| <=
    ceil(16 km/s x 0.1 s / c) + 2 ns = 5,340 ns). A packet that never crosses a step
    boundary has tol = 0: stretch >= 1 EXACTLY, in integer ns. Why a tolerance
    at all: the oracle sees the send-time geometry, the packet meets later
    geometry (reviewer should-fix 5: ~1.2 us on a ground link in 50 ms; a 1e-6
    relative tolerance would be ~50 ns and fire falsely). Packets whose path used
    a link absent from the send-time graph (it came up, or was repaired, while
    the packet travelled) are counted separately and excluded from the claim.
    Queueing is reported separately as latency - L_det. Hop stretch: hops / the
    fewest hops on the same send-time graph.

Packet labels (science report 6.6) and clean-packet FPR
    fault    the packet met a faulty element while the fault was active:
             it crossed it (link: its transmission onto the link STARTED in
             the fault interval, which is where the engine applies a link
             fault, after processing and queueing at the upstream node; a
             rate cut also covers the packets that waited behind its backlog
             after it stopped; node: at its arrival there), OR it was LOST
             there: dropped at the link's transmitter (buffer_overflow under a
             rate cut, arq_exhausted under ARQ: scheme_packets tx_loss_at
             says which link and when, because such a path ends at the
             upstream node), lost in flight on a link a fault took down
             (judged at its arrival, when the engine decides the loss), or at
             a dead node; or a link-down fallback / drop happened on a link a
             fault had down;
    stale    a link-down fallback / drop on a link that was down for
             geometric reasons (the planned link no longer exists), including
             a packet lost in flight because its link ceased to exist;
    congested (only with q_th) some hop's excess delay (hop time minus light
             time, processing and serialization) exceeded q_th;
    clean    none of these.
    FPR = clean packets flagged by a DEADLINE check / clean packets.
    Link-down and stale deviations are never deadline false positives, and
    no packet a fault dropped is ever counted as clean (it would sit in the
    FPR denominator without any chance of being flagged, biasing FPR down).

Blackhole time and time-to-mitigation are per fault event (see the functions).
"""

import math
from collections import Counter
from fractions import Fraction

import numpy as np

from ..fwd.queues import ser_ns

TAIL_MIN = {"0.99": 1000, "0.999": 10000}
LABELS = ("clean", "fault", "stale", "congested")
# link fault kinds under which the engine loses a packet IN FLIGHT (Engine._on_arrive checks the
# link at the packet's arrival): a packet transmitted just before the onset is lost by the fault
DOWN_LINK_KINDS = ("link_down",)


# ---------------------------------------------------------------- windows

def send_window(run):
    """[first, last) send times that count: [0, T_end - drain)."""
    eng = run.engine
    end = eng.get("end_ns")
    drain = eng.get("drain_ns")
    if drain is None and end is not None and "duration_ns" in eng:
        drain = end - eng["duration_ns"]
    last = (end - drain) if end is not None else int(run.send_ns.max()) + 1 if run.n else 0
    return 0, last


def measurement_mask(run, warmup_ns=0):
    lo, hi = send_window(run)
    return (run.send_ns >= max(lo, warmup_ns)) & (run.send_ns < hi)


# ---------------------------------------------------------------- delivery

def _loss_reason(run, i):
    o = int(run.outcome[i])
    if o == 2:
        return "no_route"
    if o == 3:
        return "unfinished"
    return run.reason[i] or "dropped"


def pdr_by_flow(run, mask=None):
    """[{flow, sent, delivered, pdr, losses: {reason: n}}] per flow-run."""
    mask = measurement_mask(run) if mask is None else mask
    out = []
    for f in run.flows:
        fid = f["flow_id"]
        sel = mask & (run.flow == fid)
        sent = int(sel.sum())
        dl = int((sel & run.delivered).sum())
        losses = Counter(_loss_reason(run, i) for i in np.flatnonzero(sel & ~run.delivered).tolist())
        out.append({"flow": fid, "src": f.get("src"), "dst": f.get("dst"), "sent": sent, "delivered": dl,
                    "pdr": (dl / sent) if sent else None, "losses": dict(sorted(losses.items()))})
    return out


def pdr_total(run, mask=None):
    mask = measurement_mask(run) if mask is None else mask
    sent = int(mask.sum())
    dl = int((mask & run.delivered).sum())
    losses = Counter(_loss_reason(run, i) for i in np.flatnonzero(mask & ~run.delivered).tolist())
    return {"sent": sent, "delivered": dl, "pdr": (dl / sent) if sent else None, "losses": dict(sorted(losses.items()))}


def nearest_rank(sorted_values, p, n_total=None):
    """Nearest-rank quantile; with n_total > len(values) the missing ones are +inf (lost)."""
    n = len(sorted_values) if n_total is None else n_total
    if n == 0:
        return None
    r = math.ceil(Fraction(str(p)) * n)
    r = max(r, 1)
    if r > len(sorted_values):
        return math.inf
    return int(sorted_values[r - 1])


def latency_summary(run, mask=None, ps=("0.5", "0.95", "0.99", "0.999")):
    """Per flow: ordinary quantiles of delivered packets and effective quantiles (lost = inf)."""
    mask = measurement_mask(run) if mask is None else mask
    rows = []
    for f in run.flows:
        fid = f["flow_id"]
        sel = mask & (run.flow == fid)
        n = int(sel.sum())
        lat = np.sort(run.latency_ns[sel & run.delivered])
        row = {"flow": fid, "sent": n, "delivered": int(lat.size)}
        for p in ps:
            need = TAIL_MIN.get(p, 0)
            ok = n >= need
            row[f"q{p}"] = nearest_rank(lat, p) if (ok and lat.size >= need) else None
            row[f"q{p}_eff"] = nearest_rank(lat, p, n) if ok else None
        rows.append(row)
    return rows


# ---------------------------------------------------------------- stretch

def stretch(run, mask=None):
    """Latency stretch of delivered packets and the >= 1 check (module docstring)."""
    if not run.has_extras():
        raise ValueError("stretch needs scheme_packets.csv.gz")
    mask = measurement_mask(run) if mask is None else mask
    ex = run.extras
    sel = mask & run.delivered & (ex["l_det_ns"] >= 0) & (ex["oracle_ns"] > 0)
    in_graph = sel & (ex["oracle_ok"] == 1)
    l_det = ex["l_det_ns"]
    star = ex["oracle_ns"]
    tol = np.where(ex["tol_ns"] >= 0, ex["tol_ns"], 0)
    viol = in_graph & (l_det < star - tol)
    s = l_det[sel] / star[sel]
    hops_ok = in_graph & (ex["oracle_hops"] > 0)
    hop_s = run.hops[hops_ok] / ex["oracle_hops"][hops_ok]
    hop_viol = hops_ok & (run.hops < ex["oracle_hops"])
    exact = in_graph & (tol == 0)
    s_exact = l_det[exact] / star[exact]
    s_adj = (l_det[in_graph] + tol[in_graph]) / star[in_graph]
    return {
        "n": int(sel.sum()), "n_in_send_graph": int(in_graph.sum()),
        "n_path_not_in_send_graph": int((sel & ~in_graph).sum()),
        "n_no_step_crossing": int(exact.sum()),
        # the headline minimum: packets that stayed in their send step (tol = 0) and whose path
        # was in the send-time graph. Their stretch is >= 1 EXACTLY (in integers) unless an
        # exact violation is reported, so a value below 1 here is a real error.
        "min": float(s_exact.min()) if s_exact.size else None,
        # (L_det + tol) / L* over every packet the claim covers: >= 1 unless a violation
        "min_tol_adjusted": float(s_adj.min()) if s_adj.size else None,
        # RAW L_det / L* over all delivered packets, step-crossing ones included: may be a
        # little below 1 (by at most tol / L*) without anything being wrong, and packets whose
        # path left the send-time graph are in it too. median/mean/max are raw as well.
        "min_raw": float(s.min()) if s.size else None,
        "median": float(np.median(s)) if s.size else None,
        "mean": float(s.mean()) if s.size else None, "max": float(s.max()) if s.size else None,
        "violations": int(viol.sum()),
        "worst_violation_ns": int((star - tol - l_det)[viol].max()) if viol.any() else 0,
        "exact_violations": int((exact & (l_det < star)).sum()),
        "hop_stretch_min": float(hop_s.min()) if hop_s.size else None,
        "hop_stretch_mean": float(hop_s.mean()) if hop_s.size else None,
        "hop_violations": int(hop_viol.sum()),
        "queueing_ns_mean": float((run.latency_ns[sel] - l_det[sel]).mean()) if sel.any() else None,
    }


# ---------------------------------------------------------------- fault exposure

def fault_element(fault):
    if fault.get("link") is not None:
        a, b = fault["link"]
        return ("link", min(a, b), max(a, b))
    return ("node", int(fault["node"]))


def _hop_table(run):
    """Per path position of every packet: (packet, position, time AT the node, time the
    transmission to the next node STARTED, transmitter wait before it).

    The transmission start is where a link fault acts (the engine applies a link delta,
    the ARQ draws and the rate in force at that instant, after processing and queueing),
    so link exposure is judged there. Runs without the tx_ns column (older folders) fall
    back to the time at the node, and their waits are unknown (-1).
    """
    flat, ptr = run.paths.flat, run.paths.ptr
    n = run.n
    pk = np.repeat(np.arange(n, dtype=np.int64), np.diff(ptr))
    pos_in = np.arange(flat.size, dtype=np.int64) - ptr[pk]
    arr = run.extras["arrival_ns"]
    if flat.size and arr.flat.size:
        at_node = np.where(pos_in == 0, run.send_ns[pk], arr.flat[np.maximum(arr.ptr[pk] + pos_in - 1, 0)])
    else:
        at_node = run.send_ns[pk]          # no packet ever arrived anywhere: only sources
    tx_time = at_node.copy()
    wait = np.full(flat.size, -1, dtype=np.int64)
    if "tx_ns" in run.extras and flat.size:
        tx, qw = run.extras["tx_ns"], run.extras["wait_ns"]
        has = pos_in < tx.lengths()[pk]
        j = tx.ptr[pk[has]] + pos_in[has]
        tx_time[has] = tx.flat[j]
        wait[has] = qw.flat[j]
    return pk, pos_in, at_node, tx_time, wait


def _tx_losses(run):
    """(packet, u, v, t, wait) arrays of the packets lost AT THE TRANSMITTER of u -> v.

    scheme_packets.csv.gz column tx_loss_at = "u:v:t:wait" (baselines/engine.py, from
    Engine._link_drop): buffer_overflow (t = when the packet tried to join the full FIFO,
    wait -1), arq_exhausted and a link end without a position (t = the transmission start,
    wait = its transmitter wait). Such a packet never left u, so its path ends at u and the
    path alone cannot say which link it was lost at. Refuse old or incomplete traces with
    buffer_overflow / arq_exhausted drops but no attempted-link record: silently omitting
    those losses would mislabel fault-caused drops as clean. Older folders without these
    drops remain readable.
    """
    col = run.extras.get("tx_loss_at") if run.has_extras() else None
    missing = next((i for i, reason in enumerate(run.reason)
                    if run.outcome[i] == 1 and reason in ("buffer_overflow", "arq_exhausted")
                    and (col is None or i >= len(col) or not col[i])), None)
    if missing is not None:
        raise ValueError("cannot score transmitter losses: tx_loss_at is missing for packet "
                         f"{int(run.pkt[missing])} ({run.reason[missing]}); "
                         "re-run with the current engine to record its attempted link")
    rows = [(i, *(int(x) for x in s.split(":"))) for i, s in enumerate(col) if s] if col else []
    if not rows:
        z = np.zeros(0, dtype=np.int64)
        return z, z, z, z, z
    a = np.array(rows, dtype=np.int64)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4]


def _reason_is(run, reason):
    return np.fromiter((r == reason for r in run.reason), dtype=bool, count=run.n) & (run.outcome == 1)


class _LinkUses:
    """Every time a packet used, or tried to use, a directed link u -> v, as flat arrays.

    crossings     consecutive path nodes (u, v). t = when the transmission onto the link
                  started (tx_ns; older folders: the time at u), wait = how long it waited for
                  the transmitter (-1 unknown), t_arr = its arrival at v. lost = True for the
                  LAST crossing of a packet lost in flight on that link (drop reason
                  in_flight_link_down, decided on arrival at v by Engine._on_arrive).
    transmitter   the packet was dropped at u while trying to use u -> v (_tx_losses). t =
    losses        when it met the link, wait as recorded (-1: the FIFO was full), t_arr = -1,
                  lost = True.

    busy / idle say whether the use found the transmitter busy (it waited, or the FIFO was
    full) or idle (wait 0): a rate cut's backlog has drained at the first idle use after it
    stops (_rate_cut_drain). rows(a, b) gives the uses of the link in either direction.
    """

    def __init__(self, run):
        flat, ptr = run.paths.flat, run.paths.ptr
        e = np.zeros(0, dtype=np.int64)
        if flat.size:
            pk, _pos, at_node, tx_time, wait = _hop_table(run)
            same = np.zeros(flat.size, dtype=bool)
            same[:-1] = pk[1:] == pk[:-1]
            j = np.flatnonzero(same)
            c = (pk[j], flat[j], flat[j + 1], tx_time[j], wait[j], at_node[j + 1])
        else:
            j = e
            c = (e, e, e, e, e, e)
        tl_pk, tl_u, tl_v, tl_t, tl_w = _tx_losses(run)
        # lost in flight = lost ON ARRIVAL at the last node of its path, so its last crossing is
        # the link that lost it. A link end without a position loses the packet at the
        # transmitter instead (tx_loss_at says so; older folders cannot tell, and are read as
        # lost on arrival).
        inflight = _reason_is(run, "in_flight_link_down")
        inflight[tl_pk] = False
        lens = np.diff(ptr)
        last_cross = np.zeros(flat.size, dtype=bool)
        q = np.flatnonzero(inflight & (lens >= 2))
        last_cross[ptr[q + 1] - 2] = True
        c_lost = last_cross[j]
        self.pk = np.concatenate([c[0], tl_pk])
        self.u = np.concatenate([c[1], tl_u])
        self.v = np.concatenate([c[2], tl_v])
        self.t = np.concatenate([c[3], tl_t])
        self.wait = np.concatenate([c[4], tl_w])
        self.t_arr = np.concatenate([c[5], np.full(tl_pk.size, -1, dtype=np.int64)])
        self.lost = np.concatenate([c_lost, np.ones(tl_pk.size, dtype=bool)])
        full = np.concatenate([np.zeros(j.size, dtype=bool), tl_w < 0])
        self.busy = (self.wait > 0) | full
        self.idle = (self.wait == 0) & ~full
        self.has_tx = "tx_ns" in run.extras
        self.M = int(max(self.u.max(), self.v.max())) + 1 if self.u.size else 0
        key = np.minimum(self.u, self.v) * self.M + np.maximum(self.u, self.v)
        self.order = np.argsort(key, kind="stable")
        self.skey = key[self.order]

    def rows(self, a, b):
        """Indices of the uses of link {a, b} (either direction), in the order they were built."""
        a, b = min(a, b), max(a, b)
        if self.skey.size == 0 or b >= self.M:
            return np.zeros(0, dtype=np.int64)
        k = a * self.M + b
        lo, hi = np.searchsorted(self.skey, k, "left"), np.searchsorted(self.skey, k, "right")
        return self.order[lo:hi]


def _link_uses(run):
    """_LinkUses of a run, built once per run (exposure is asked once per fault, and a run with
    renewal failures logs thousands of them). Rebuilt when the run's arrays are replaced."""
    ex = run.extras
    # the very objects it was built from (held, so compared by identity: never a recycled id)
    key = (run.paths, ex, ex.get("tx_ns"), ex.get("tx_loss_at"), ex.get("arrival_ns"), run.reason,
           run.outcome, run.send_ns)
    hit = run.__dict__.get("_link_uses_cache")
    if hit is not None and all(a is b for a, b in zip(hit[0], key)):
        return hit[1]
    uses = _LinkUses(run)
    run.__dict__["_link_uses_cache"] = (key, uses)
    return uses


def _rate_cut_drain(uses, u, v, stop):
    """End of the backlog a rate cut left on direction u -> v: the instant of the first use at
    or after `stop` that found the transmitter idle (wait 0); inf if none.

    Packets that meet the link in [stop, that instant) waited behind work queued during the
    cut (or found its FIFO still full), so the cut still delays (or drops) them. Only
    foreground packets are observed: with Poisson background the queue may empty and refill
    unseen between two of them, so this end is an upper bound (conservative: such packets
    are never counted as clean).
    """
    r = uses.rows(u, v)
    r = r[(uses.u[r] == u) & (uses.v[r] == v) & (uses.t[r] >= stop)]
    if r.size == 0:
        return stop
    order = r[np.argsort(uses.t[r], kind="stable")]
    idle = order[uses.idle[order]]
    if idle.size == 0:
        return np.iinfo(np.int64).max if uses.busy[order].any() else stop
    return int(uses.t[idle[0]])


def _exposure_rows(run, fault, uses=None):
    """(packet, instant, lost) of every use of the faulty element that the fault reached.

    A link: a use whose instant (transmission start, or when a lost packet met the link) is in
    [start, stop); for a rate cut also a use from `stop` until its backlog drained; for a
    link_down fault also a packet lost in flight on the link whose ARRIVAL is in [start, stop)
    (the engine loses it there, even when it was sent just before the onset). A node: an
    arrival in [start, stop); lost = the packet's path ends there with reason node_down.
    """
    el = fault_element(fault)
    start, stop = int(fault["start_ns"]), int(fault["stop_ns"])
    e = np.zeros(0, dtype=np.int64)
    if el[0] == "link":
        U = uses if uses is not None else _link_uses(run)
        r = U.rows(el[1], el[2])
        t = U.t[r]
        ok = (t >= start) & (t < stop)
        when = t.copy()
        if fault.get("kind") == "rate_cut" and U.has_tx:
            for x, y in ((el[1], el[2]), (el[2], el[1])):
                end = _rate_cut_drain(U, x, y, stop)
                if end > stop:
                    ok |= (U.u[r] == x) & (t >= stop) & (t < end)
        if fault.get("kind") in DOWN_LINK_KINDS:
            ta = U.t_arr[r]
            gone = U.lost[r] & (ta >= start) & (ta < stop) & ~ok
            when = np.where(gone, ta, when)
            ok |= gone
        return U.pk[r][ok], when[ok], U.lost[r][ok]
    flat, ptr = run.paths.flat, run.paths.ptr
    if flat.size == 0:
        return e, e, np.zeros(0, dtype=bool)
    pk, pos_in, at_node, _tx, _w = _hop_table(run)
    hit = np.flatnonzero((flat == el[1]) & (pos_in >= 1))
    t = at_node[hit]
    ok = (t >= start) & (t < stop)
    is_last = hit == ptr[pk[hit] + 1] - 1
    lost = is_last & _reason_is(run, "node_down")[pk[hit]]
    return pk[hit][ok], t[ok], lost[ok]


def exposure(run, fault, part="all"):
    """(mask (n,), first instant (n,), -1 = never) of the packets a fault reached.

    part "all"      every packet that met the faulty element while the fault acted on it:
                    crossed it OR was lost on it (the label `fault`, time-to-mitigation);
         "crossed"  packets with a use of the element that did NOT lose them there (they
                    went on, so a checker downstream could flag them: the denominator of
                    the packet-level P_det, detection.counterfactual);
         "lost"     packets the element lost while the fault acted (a full FIFO or ARQ give-up
                    at the link's transmitter, lost in flight on a downed link, or arriving
                    at a dead node). A packet that crossed and was later lost on the same
                    element is in both "crossed" and "lost".

    A link fault acts on a packet at the TRANSMISSION START onto the link (where the engine
    applies a link delta, the ARQ draws and the rate in force: after the node's processing
    and queueing), either direction, in [start, stop). A rate cut also reaches the packets
    that met the link after `stop` while the backlog it built was still draining
    (_rate_cut_drain). Packets dropped at the link's transmitter (buffer_overflow,
    arq_exhausted) are placed on the link by tx_loss_at (their path ends at the upstream
    node). A link_down fault also reaches a packet lost in flight on it at its arrival. A node
    fault reaches a packet that arrives at the node in [start, stop) (its processing delta is
    decided on arrival). Needs per-hop times (scheme_packets.csv.gz).
    """
    if not run.has_extras():
        raise ValueError("exposure needs per-hop times (scheme_packets.csv.gz)")
    if part not in ("all", "crossed", "lost"):
        raise ValueError(f"part must be all, crossed or lost, got {part!r}")
    n = run.n
    p, when, lost = _exposure_rows(run, fault)
    if part == "crossed":
        p, when = p[~lost], when[~lost]
    elif part == "lost":
        p, when = p[lost], when[lost]
    exposed = np.zeros(n, dtype=bool)
    t_cross = np.full(n, -1, dtype=np.int64)
    if p.size == 0:
        return exposed, t_cross
    # first instant per packet
    order = np.lexsort((when, p))
    p, when = p[order], when[order]
    first = np.ones(p.size, dtype=bool)
    first[1:] = p[1:] != p[:-1]
    exposed[p[first]] = True
    t_cross[p[first]] = when[first]
    return exposed, t_cross


def lost_at_fault(run, fault):
    """(n,) bool: packets the faulty element LOST while the fault acted (exposure part "lost")."""
    return exposure(run, fault, "lost")[0]


class FaultIndex:
    """Every fault interval of a run, merged per element, for fast 'was it active at t' tests.

    A renewal fault on every ISL logs one entry per down interval (tens of thousands in a
    long run); looping over them per packet would be far too slow.
    """

    def __init__(self, faults, kinds=None):
        links, nodes, down = {}, {}, {}
        self.rate_cuts = []                 # (a, b, stop) of rate cuts: their drain extends exposure
        for f in faults:
            if kinds is not None and f["kind"] not in kinds:
                continue
            el = fault_element(f)
            target = links if el[0] == "link" else nodes
            iv = (int(f["start_ns"]), int(f["stop_ns"]))
            target.setdefault(el[1:] if el[0] == "link" else el[1], []).append(iv)
            if f["kind"] == "rate_cut" and el[0] == "link":
                self.rate_cuts.append((el[1], el[2], int(f["stop_ns"])))
            if f["kind"] in DOWN_LINK_KINDS and el[0] == "link":
                down.setdefault(el[1:], []).append(iv)
        self.links = {k: self._merge(v) for k, v in links.items()}
        self.nodes = {k: self._merge(v) for k, v in nodes.items()}
        self.down_links = {k: self._merge(v) for k, v in down.items()}

    @staticmethod
    def _merge(iv):
        out = []
        for s, e in sorted(iv):
            if out and s <= out[-1][1]:
                out[-1][1] = max(out[-1][1], e)
            else:
                out.append([s, e])
        return (np.array([s for s, _ in out], dtype=np.int64), np.array([e for _, e in out], dtype=np.int64))

    @staticmethod
    def _active(iv, t):
        starts, stops = iv
        i = np.searchsorted(starts, t, side="right") - 1
        return (i >= 0) & (t < stops[np.maximum(i, 0)])

    def link_active(self, a, b, t):
        iv = self.links.get((min(a, b), max(a, b)))
        return bool(iv is not None and self._active(iv, np.int64(t)))

    def node_active(self, n, t):
        iv = self.nodes.get(int(n))
        return bool(iv is not None and self._active(iv, np.int64(t)))

    def exposed_any(self, run):
        """(n,) bool: the packet met a faulty element while active, exactly as the OR of
        exposure(run, f) over the faults (same instants: transmission start or loss at the
        transmitter for links, arrival for nodes, a rate cut's drain after it stops, and the
        arrival of a packet lost in flight on a downed link)."""
        n = run.n
        out = np.zeros(n, dtype=bool)
        if not self.links:
            # Label scoring still needs complete loss records with an empty or node-only
            # fault log. Link indexes validate them when constructing _LinkUses below.
            _tx_losses(run)
        if run.paths.flat.size == 0 or (not self.links and not self.nodes):
            return out
        if self.links:
            U = _link_uses(run)
            if self.rate_cuts and U.has_tx:
                for a, b, stop in self.rate_cuts:
                    for u, v in ((a, b), (b, a)):
                        end = _rate_cut_drain(U, u, v, stop)
                        if end > stop:
                            r = U.rows(u, v)
                            r = r[(U.u[r] == u) & (U.t[r] >= stop) & (U.t[r] < end)]
                            out[U.pk[r]] = True
            for (a, b), iv in self.links.items():
                r = U.rows(a, b)
                if r.size == 0:
                    continue
                out[U.pk[r[self._active(iv, U.t[r])]]] = True
                div = self.down_links.get((a, b))
                if div is not None:
                    g = r[U.lost[r] & (U.t_arr[r] >= 0)]
                    if g.size:
                        out[U.pk[g[self._active(div, U.t_arr[g])]]] = True
        if self.nodes:
            flat = run.paths.flat
            pk, pos_in, at_node, _tx, _w = _hop_table(run)
            order = np.argsort(flat, kind="stable")
            sf = flat[order]
            for node, iv in self.nodes.items():
                lo, hi = np.searchsorted(sf, node, "left"), np.searchsorted(sf, node, "right")
                e = order[lo:hi]
                e = e[pos_in[e] >= 1]
                if e.size:
                    act = self._active(iv, at_node[e])       # a node fault acts on arrival
                    out[pk[e[act]]] = True
        return out


def _link_down_events(run):
    """(packet, node, failed next node, time) of every link-down fallback start or drop."""
    out = []
    arr = run.extras["arrival_ns"] if run.has_extras() else None
    hk = run.extras.get("hop_k") if run.has_extras() else None
    ld = run.extras.get("link_down_at") if run.has_extras() else None
    cand = [i for i in range(run.n) if run.fallback_reason[i] == "next_link_down"
            or run.reason[i] == "next_link_down" or (ld is not None and ld[i])]
    for i in cand:
        if ld is not None and ld[i]:
            # table / oracle schemes record where and when they met the dead next link
            node, nxt, t = (int(x) for x in ld[i].split(":"))
            out.append((i, node, nxt, t))
            continue
        if run.fallback_reason[i] != "next_link_down" and run.reason[i] != "next_link_down":
            continue
        row = run.schedule.get((int(run.flow[i]), int(run.row_from_ms[i])))
        if row is None or hk is None:
            continue
        ks = hk[i]
        # the node that found its next link down: the last non-detour node before the
        # packet went GREEDY (hop index k >= 1), or the source when that happened at once
        j = 0
        for e, v in enumerate(ks.tolist()):
            if v >= 1:
                j = e + 1
            else:
                break
        if j + 1 >= len(row["path"]):
            continue
        t = run.send_ns[i] if j == 0 else int(arr[i][j - 1])
        out.append((i, int(row["path"][j]), int(row["path"][j + 1]), int(t)))
    return out


def touched(run, fault):
    """Packets that met the faulty element while active (exposure: crossed it or were lost on
    it), OR met it as a dead next link (link-down fallback / drop on that link during the
    fault)."""
    ex, _t = exposure(run, fault)
    ex = ex.copy()
    el = fault_element(fault)
    start, stop = int(fault["start_ns"]), int(fault["stop_ns"])
    for i, a, b, t in _link_down_events(run):
        if not start <= t < stop:
            continue
        if (el[0] == "link" and {a, b} == {el[1], el[2]}) or (el[0] == "node" and b == el[1]):
            ex[i] = True
    return ex


def packet_labels(run, mask=None, q_th_ns=None):
    """Ground-truth class of every packet: 0 clean, 1 fault, 2 stale, 3 congested (LABELS)."""
    if not run.has_extras():
        raise ValueError("packet labels need per-hop times (scheme_packets.csv.gz)")
    lab = np.zeros(run.n, dtype=np.int8)
    lab[FaultIndex(run.faults).exposed_any(run)] = 1
    down = FaultIndex(run.faults, kinds=("link_down", "node_down"))
    for i, a, b, t in _link_down_events(run):
        if lab[i] == 1:
            continue
        hit = down.link_active(a, b, t) or down.node_active(a, t) or down.node_active(b, t)
        lab[i] = 1 if hit else 2
    # lost in flight but not by a fault (exposed_any covers a downed link at the arrival): the
    # link ceased to exist under the packet (geometry), a drop on a geometrically dead link
    lab[(lab == 0) & _reason_is(run, "in_flight_link_down")] = 2
    if q_th_ns is not None:
        eng = run.engine
        proc = int(eng.get("processing_ns", 500_000))
        rate = int(eng.get("link_rate_bps", 1_000_000_000))
        arr = run.extras["arrival_ns"]
        hp = run.extras["hop_prop_ns"]
        lens = arr.lengths()
        if arr.flat.size:
            pk = np.repeat(np.arange(run.n, dtype=np.int64), lens)
            first = np.zeros(arr.flat.size, dtype=bool)
            first[arr.ptr[:-1][lens > 0]] = True
            prev = np.empty_like(arr.flat)
            prev[1:] = arr.flat[:-1]
            prev[first] = run.send_ns[pk[first]]
            uw, inv = np.unique(run.wire, return_inverse=True)
            ser = np.array([ser_ns(int(w), rate) for w in uw], dtype=np.int64)[inv]
            excess = (arr.flat - prev) - (hp.flat + proc + ser[pk])
            congested = np.zeros(run.n, dtype=bool)
            congested[pk[excess > q_th_ns]] = True
            lab[(lab == 0) & congested] = 3
    if mask is not None:
        lab = np.where(mask, lab, -1)
    return lab


def deadline_fpr(labels, flagged, hops=None):
    """Clean-packet FPR = clean & flagged / clean (and per hop count)."""
    clean = labels == 0
    n_clean = int(clean.sum())
    fp = int((clean & flagged).sum())
    out = {"clean": n_clean, "false_positives": fp, "fpr": (fp / n_clean) if n_clean else None}
    if hops is not None:
        per = {}
        for h in sorted(set(hops[clean].tolist())):
            m = clean & (hops == h)
            per[int(h)] = {"clean": int(m.sum()), "fp": int((m & flagged).sum())}
        out["per_hops"] = per
    return out


# ---------------------------------------------------------------- per fault event

def blackhole(run, fault):
    """Packets lost ON the faulty element while it was down, and the blackhole time.

    blackhole_ns = (last such loss attempt) - onset: how long after the failure the
    scheme still sent packets into it (0 if none). Attempt time = when the packet was at
    the upstream node (link) or arrived at the dead satellite (node).
    """
    el = fault_element(fault)
    start, stop = int(fault["start_ns"]), int(fault["stop_ns"])
    lost = []
    events = {i: (a, b, t) for i, a, b, t in _link_down_events(run)} if run.has_extras() else {}
    arr = run.extras.get("arrival_ns") if run.has_extras() else None
    txl = {int(i): (int(u), int(v), int(t)) for i, u, v, t, _w in zip(*_tx_losses(run))}         if run.has_extras() else {}
    for i in np.flatnonzero(run.outcome == 1).tolist():
        r = run.reason[i]
        path = run.paths[i]
        t = None
        if r == "in_flight_link_down" and i in txl:
            # lost at the transmitter (a link end without a position): its path ends upstream
            a, b, ta = txl[i]
            if el[0] == "link" and {a, b} == {el[1], el[2]}:
                t = ta
        elif r == "in_flight_link_down" and len(path) >= 2:
            a, b = int(path[-2]), int(path[-1])
            if el[0] == "link" and {a, b} == {el[1], el[2]} and arr is not None:
                t = run.send_ns[i] if len(path) == 2 else int(arr[i][len(path) - 3])
        elif r == "node_down" and el[0] == "node" and int(path[-1]) == el[1] and arr is not None:
            t = int(arr[i][len(path) - 2])
        elif r in ("next_link_down", "no_fallback", "stuck") and i in events:
            a, b, tt = events[i]
            if (el[0] == "link" and {a, b} == {el[1], el[2]}) or (el[0] == "node" and b == el[1]):
                t = tt
        if t is not None and start <= t < stop:
            lost.append(t)
    return {"losses": len(lost), "blackhole_ns": (max(lost) - start) if lost else 0,
            "first_loss_ns": (min(lost) - start) if lost else None}


def time_to_mitigation(run, fault, *, frac="0.95", bin_ns=100_000_000, sustain_ns=1_000_000_000,
                       flags=None):
    """Onset -> first time from which >= frac of the affected flows' packets avoid the fault,
    sustained for sustain_ns (master plan 5.3).

    Affected flows: flows with a packet that touched this fault (crossed it while active, or
    met it as a dead next link). A packet "avoids" the fault when it is delivered without
    touching it (with `flags`, a crossing packet that was not flagged also counts as fine:
    "or meet their deadlines").
    Packets are grouped by send time into bins of bin_ns; TTM is the start of the first bin
    b >= onset such that every non-empty bin in [b, b + sustain) meets frac, the whole
    window lying before the fault ends. Not reached: censored at stop - onset.
    """
    exposed = touched(run, fault)
    start, stop = int(fault["start_ns"]), int(fault["stop_ns"])
    flows = sorted(set(run.flow[exposed].tolist()))
    out = {"affected_flows": flows, "packets_affected": int(exposed.sum()), "ttm_ns": None,
           "observed": False, "horizon_ns": stop - start}
    if not flows:
        return out
    sel = np.isin(run.flow, flows) & (run.send_ns >= start) & (run.send_ns < stop)
    ok = run.delivered & ~exposed
    if flags is not None:
        ok = ok | (run.delivered & exposed & ~flags)
    q = Fraction(str(frac))
    nb = -(-(stop - start) // bin_ns)
    tot = np.zeros(nb, dtype=np.int64)
    good = np.zeros(nb, dtype=np.int64)
    b = ((run.send_ns[sel] - start) // bin_ns).astype(np.int64)
    np.add.at(tot, b, 1)
    np.add.at(good, b, ok[sel].astype(np.int64))
    span = -(-sustain_ns // bin_ns)
    good_bin = (tot == 0) | (good * q.denominator >= q.numerator * tot)
    for j in range(nb):
        if j + span > nb:
            break
        if good_bin[j:j + span].all() and tot[j:j + span].sum() > 0:
            out["ttm_ns"] = j * bin_ns
            out["observed"] = True
            break
    return out


# ---------------------------------------------------------------- bytes

def control_summary(run):
    """Control bytes per medium (and per second), header bytes, satellite state."""
    out = {}
    eng = run.engine
    secs = (eng.get("end_ns", 0) or 0) / 1e9
    if run.control is not None:
        bm = run.control["ledger"]["by_medium"]
        out["control_bytes"] = {m: v["bytes"] for m, v in bm.items()}
        out["control_bytes_per_s"] = {m: (v["bytes"] / secs if secs else None) for m, v in bm.items()}
        out["state"] = run.control.get("state")
        up = run.control.get("crh_state_uploads")
        if up and up.get("counted"):
            # ChronoRoute's periodic satellite uploads, amortised (exact for any run length; the
            # ledger above holds only the uploads whose instants fell inside this run)
            out["crh_state_upload_bytes_per_s_steady"] = up.get("steady_state_bytes_per_s")
    if run.has_extras():
        hdr = run.extras["hdr_bytes"]
        m = hdr >= 0
        out["header_bytes_per_packet_mean"] = float(hdr[m].mean()) if m.any() else None
        out["header_bytes_on_links"] = int((hdr[m] * run.hops[m]).sum())
    return out


__all__ = ["TAIL_MIN", "LABELS", "DOWN_LINK_KINDS", "send_window", "measurement_mask", "pdr_by_flow", "pdr_total",
           "nearest_rank", "touched", "FaultIndex", "latency_summary", "stretch", "fault_element", "exposure",
           "lost_at_fault", "packet_labels", "deadline_fpr",
           "blackhole", "time_to_mitigation", "control_summary"]

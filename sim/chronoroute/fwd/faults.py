"""
faults.py
---------
Fault models (MODELLED) and their ground-truth log (master plan P3e).

Every fault that is applied is written to the log (run.json "faults", one
entry per fault interval), so detection can always be scored against what
really happened. The ground (the planner) is never told about faults: it
plans on the predicted, failure-free topology.

Kinds (config key `kind`):

  link_down        a link is down in both directions for [start, stop).
  link_renewal     every target link (ISLs by default) alternates up/down:
                   exponential up periods of mean MTBF and down periods of mean
                   MTTR, MTBF = MTTR (1 - U) / U, so the long-run unavailable
                   fraction is U. Started in the stationary state (down with
                   probability U; exponential periods are memoryless, so the
                   remaining time of the first period has the same law).
  node_down        a satellite is down for [start, stop): all its links are
                   down and a packet that reaches it is lost.
  node_renewal     every satellite alternates up/down as in link_renewal.
  slow_processing  "up but slow" (a): Delta ns added to the processing of
                   every packet at a node, or to the transit of every packet
                   over a link (both directions), during [start, stop).
                   The LINK variant is a MODELLED "per-packet extra link
                   latency": Delta is added after serialization, decided at
                   the transmission start, and does NOT occupy the
                   transmitter. There is no physical mechanism behind it (a
                   real link that is slow is slow because it serves packets
                   more slowly, or loses and resends them), and because the
                   transmitter stays free, a packet sent just after the
                   fault stops can overtake one sent just before (reordering
                   at the start and stop instants). It is fine for detection
                   tests (a clean, known Delta), but headline experiments
                   should prefer rate_cut, arq or the NODE variant.
  rate_cut         "up but slow" (b): the link rate drops to f * C in both
                   directions during [start, stop). Queues then build by
                   themselves (with background load, or with foreground load
                   above f * C).
  arq              "up but slow" (c): per-attempt loss p on the link; a lost
                   attempt is retried after 2 * propagation + retry_extra
                   (0.1 ms default), at most max_retries (3) times; after the
                   last failure the packet is lost ("arq_exhausted").
                   Retransmissions do not occupy the transmitter (selective
                   repeat; airtime of a 200-300 byte probe is ~2 us).

There is deliberately NO "multiply the propagation delay" model: light time
is fixed by geometry, and the old model that scaled it was unphysical
(master plan P3e, science report section 0.5).

Random draws come from the keyed streams of rng.py (components link_fault,
node_fault, arq). A renewal process is keyed by its fault IDENTITY (what the
config entry says it does, fault_identity below), never by its position in
the config list, plus the link or node. Why: the counterfactual twin of a
run is "the same run without the scored fault". If streams were keyed by
list position, removing a fault listed BEFORE a renewal entry would shift
that entry's position and redraw every one of its up/down periods, so the
twin would silently have different background failures. With identity keys,
a run with and without some OTHER fault draws exactly the same periods for
this one (test_fwd_faults checks it). Two identical entries in one list are
told apart by their occurrence number among identical entries.

Every log entry carries params.fault_id (the identity hash, plus "#n" for
the n-th identical copy), so a twin's log can be compared entry by entry
with the fault run's (eval/detection.check_twin does).
"""

import bisect
import hashlib
import json
from fractions import Fraction

from .config import exact_fraction, seconds_to_ns_exact


class _Intervals:
    """Sorted, merged [start, stop) intervals with O(log n) membership."""

    __slots__ = ("starts", "stops")

    def __init__(self):
        self.starts, self.stops = [], []

    def add(self, start, stop):
        if stop <= start:
            return
        pairs = sorted(zip(self.starts, self.stops)) + [(start, stop)]
        pairs.sort()
        merged = []
        for s, e in pairs:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        self.starts = [s for s, _ in merged]
        self.stops = [e for _, e in merged]

    def contains(self, t):
        i = bisect.bisect_right(self.starts, t) - 1
        return i >= 0 and t < self.stops[i]


class _Valued:
    """[start, stop) intervals carrying a value; value_at(t) sums the active ones."""

    __slots__ = ("items",)

    def __init__(self):
        self.items = []

    def add(self, start, stop, value):
        self.items.append((start, stop, value))
        self.items.sort()

    def active(self, t):
        return [v for s, e, v in self.items if s <= t < e]


class FaultSet:
    """All faults of a run, resolved to link indices / node ids, plus the ground-truth log."""

    def __init__(self):
        self.link_down = {}         # link index -> _Intervals
        self.node_down = {}         # node -> _Intervals
        self.node_delay = {}        # node -> _Valued(delta_ns)
        self.link_delay = {}        # link index -> _Valued(delta_ns)
        self.rate_cuts = {}         # link index -> [(start, stop, Fraction factor)]
        self.arq = {}               # link index -> _Valued((loss Fraction, max_retries, extra_ns))
        self.log = []

    # ------------------------------------------------------------ queries (hot path)
    def link_is_down(self, li, a, b, t):
        iv = self.link_down.get(li)
        if iv is not None and iv.contains(t):
            return True
        if self.node_down:
            na = self.node_down.get(a)
            if na is not None and na.contains(t):
                return True
            nb = self.node_down.get(b)
            if nb is not None and nb.contains(t):
                return True
        return False

    def link_down_only(self, li, t):
        """The link itself is failed at t (its end satellites may be fine)."""
        iv = self.link_down.get(li)
        return iv is not None and iv.contains(t)

    def node_is_down(self, node, t):
        iv = self.node_down.get(node)
        return iv is not None and iv.contains(t)

    def extra_processing_ns(self, node, t):
        v = self.node_delay.get(node)
        return sum(v.active(t)) if v is not None else 0

    def extra_link_ns(self, li, t):
        v = self.link_delay.get(li)
        return sum(v.active(t)) if v is not None else 0

    def arq_params(self, li, t):
        v = self.arq.get(li)
        if v is None:
            return None
        act = v.active(t)
        return act[0] if act else None

    def rate_changes(self, li, nominal_bps):
        """(t, rate_bps) change points of link li (for queues.RateSchedule); [] if never cut."""
        cuts = self.rate_cuts.get(li)
        if not cuts:
            return []
        points = sorted({s for s, _, _ in cuts} | {e for _, e, _ in cuts})
        out = []
        for t in points:
            f = Fraction(1)
            for s, e, fac in cuts:
                if s <= t < e:
                    f = min(f, fac)
            out.append((t, int(f * nominal_bps)))
        return out

    @property
    def has_node_processing_faults(self):
        return bool(self.node_delay)

    # ------------------------------------------------------------ building
    def _log(self, kind, start, stop, *, link=None, node=None, params=None):
        self.log.append({"kind": kind, "link": list(link) if link is not None else None,
                         "node": node, "start_ns": int(start), "stop_ns": int(stop),
                         "params": params or {}})

    def add_link_down(self, li, ab, start, stop, params=None, kind="link_down"):
        self.link_down.setdefault(li, _Intervals()).add(start, stop)
        self._log(kind, start, stop, link=ab, params=params)

    def add_node_down(self, node, start, stop, params=None, kind="node_down"):
        self.node_down.setdefault(node, _Intervals()).add(start, stop)
        self._log(kind, start, stop, node=node, params=params)

    # ------------------------------------------------------------ what the nodes SEE
    def detected_view(self, delay_ns):
        """The failures as the nodes next to them see them: a FaultSet whose link_down and
        node_down intervals start delay_ns later (loss-of-carrier detection time).

        Why a separate view: a failed link loses packets at once (the truth, self), but
        a node can only route around a failure once it has noticed it. Every scheme's
        local forwarding decision (spec 6 step 7, the fallback's neighbour choice,
        SNAP's dead-next-hop check, LQ) uses this view, and the link-state schemes use
        the same delay for their carrier detection, so all schemes share ONE
        failure-visibility model (docs/baselines.md 2.3). A failure shorter than the
        delay is never seen. Recovery is seen at once (the carrier comes back).
        With delay 0 the view is this FaultSet itself.

        Only the queries a decision makes are shifted (link_is_down, link_down_only);
        the slowness faults are not failures and are shared unchanged. The view is
        never used for losses (node_is_down of the receiving node, a link dying under
        a packet in flight): those are always the truth.
        """
        if delay_ns < 0:
            raise ValueError("a detection delay is never negative")
        if delay_ns == 0:
            return self
        v = FaultSet()
        for li, iv in self.link_down.items():
            for s, e in zip(iv.starts, iv.stops):
                if s + delay_ns < e:
                    v.link_down.setdefault(li, _Intervals()).add(s + delay_ns, e)
        for node, iv in self.node_down.items():
            for s, e in zip(iv.starts, iv.stops):
                if s + delay_ns < e:
                    v.node_down.setdefault(node, _Intervals()).add(s + delay_ns, e)
        v.node_delay, v.link_delay, v.rate_cuts, v.arq = self.node_delay, self.link_delay, self.rate_cuts, self.arq
        v.log = self.log
        return v


def fault_identity(f, start_ns, stop_ns):
    """Canonical text of what one fault config entry does (not where it sits in the list).

    Values are normalised so that equal faults written differently (2 vs 2.0 vs "2"
    seconds, 0.01 vs "1/100") get the same identity: times in integer ns, fractions as
    exact strings, the target as written (an on_path target names the same link in a
    fault run and in its twin, which share the scenario).
    """
    kind = f["kind"]
    d = {"kind": kind, "start_ns": int(start_ns), "stop_ns": int(stop_ns)}
    if kind in ("link_renewal", "node_renewal"):
        d["unavailability"] = str(exact_fraction(f["unavailability"], "unavailability"))
        d["mttr_ns"] = seconds_to_ns_exact(f["mttr_s"], "mttr_s")
        if kind == "link_renewal":
            d["targets"] = f.get("targets", "isl")
    else:
        for k in ("link", "link_names"):
            if k in f:
                d[k] = list(f[k])
        for k in ("node", "node_name"):
            if k in f:
                d[k] = f[k]
        if "on_path" in f:
            op = dict(f["on_path"])
            if "at_s" in op:
                op["at_ns"] = seconds_to_ns_exact(op.pop("at_s"), "on_path.at_s")
            d["on_path"] = op
        if kind == "slow_processing":
            d["delta_ns"] = int(f["delta_ns"])
        elif kind == "rate_cut":
            d["factor"] = str(exact_fraction(f["factor"], "factor"))
        elif kind == "arq":
            d["loss"] = str(exact_fraction(f["loss"], "loss"))
            d["max_retries"] = int(f.get("max_retries", 3))
            d["retry_extra_ns"] = int(f.get("retry_extra_ns", 100_000))
    return json.dumps(d, sort_keys=True, separators=(",", ":"))


def fault_ids(fault_cfgs, end_ns):
    """[(fault_id text, stream entity prefix)] for every config entry, independent of order.

    The id is the first 16 hex digits of sha256(fault_identity); the n-th copy of an
    identical entry gets "#n" (n >= 1) and stream prefix (hi, lo, n). The prefix is
    what keys the entry's random streams (rng entities must be integers).
    """
    seen = {}
    out = []
    for f in fault_cfgs:
        start = seconds_to_ns_exact(f["start_s"], "start_s") if "start_s" in f else 0
        stop = seconds_to_ns_exact(f["stop_s"], "stop_s") if "stop_s" in f else end_ns
        digest = hashlib.sha256(fault_identity(f, start, stop).encode("utf-8")).hexdigest()[:16]
        occ = seen.get(digest, 0)
        seen[digest] = occ + 1
        fid = digest if occ == 0 else f"{digest}#{occ}"
        out.append((fid, (int(digest[:8], 16), int(digest[8:16], 16), occ)))
    return out


def renewal_periods(rng, component, entity, start, stop, u, mttr_ns):
    """Down intervals [(s, e)] of one alternating-renewal element inside [start, stop).

    Exponential up (mean MTBF = MTTR (1-U)/U) and down (mean MTTR) periods,
    starting in the stationary state. Draw i of stream (component, entity)
    is the i-th decision, so the periods never depend on other elements.
    """
    u = Fraction(u)
    mtbf = float(mttr_ns * (1 - u) / u)
    mttr = float(mttr_ns)
    i = 0
    down = rng.uniform(component, entity, i) < float(u)
    i += 1
    t = start
    out = []
    while t < stop:
        mean = mttr if down else mtbf
        d = max(1, int(round(rng.exponential(component, entity, i, mean))))
        i += 1
        if down:
            out.append((t, min(stop, t + d)))
        t += d
        down = not down
    return out


def build_faults(fault_cfgs, *, topo, rng, end_ns, resolve_on_path):
    """FaultSet from the config's fault list.

    topo             fwd.topology.Topology (link table, names)
    rng              rng.KeyedStreams
    end_ns           end of the run (renewal processes stop there)
    resolve_on_path  callable(on_path dict, default_t_ns, want_node) -> (a, b) or node
    """
    fs = FaultSet()
    ids = fault_ids(fault_cfgs, end_ns)
    for idx, f in enumerate(fault_cfgs):
        kind = f["kind"]
        fid, stream = ids[idx]
        start = seconds_to_ns_exact(f["start_s"], "start_s") if "start_s" in f else 0
        stop = seconds_to_ns_exact(f["stop_s"], "stop_s") if "stop_s" in f else end_ns
        if kind == "link_renewal":
            u = exact_fraction(f["unavailability"], "unavailability")
            mttr = seconds_to_ns_exact(f["mttr_s"], "mttr_s")
            targets = f.get("targets", "isl")
            for li in range(topo.n_links):
                is_isl = li < topo.n_isl
                if targets == "isl" and not is_isl or targets == "gsl" and is_isl:
                    continue
                ab = (int(topo.link_a[li]), int(topo.link_b[li]))
                # keyed by the fault's identity (module docstring), never by idx
                for s, e in renewal_periods(rng, "link_fault", stream + (li,), start, stop, u, mttr):
                    fs.add_link_down(li, ab, s, e, {"model": "renewal", "unavailability": str(u),
                                                    "mttr_ns": mttr, "fault_id": fid},
                                     kind="link_down")
            continue
        if kind == "node_renewal":
            u = exact_fraction(f["unavailability"], "unavailability")
            mttr = seconds_to_ns_exact(f["mttr_s"], "mttr_s")
            for node in range(topo.n_sats):
                for s, e in renewal_periods(rng, "node_fault", stream + (node,), start, stop, u, mttr):
                    fs.add_node_down(node, s, e, {"model": "renewal", "unavailability": str(u),
                                                  "mttr_ns": mttr, "fault_id": fid},
                                     kind="node_down")
            continue

        # targeted faults
        node = link = None
        if "node" in f:
            node = int(f["node"])
        elif "node_name" in f:
            node = topo.node_by_name(f["node_name"])
        elif "link" in f:
            link = (int(f["link"][0]), int(f["link"][1]))
        elif "link_names" in f:
            link = (topo.node_by_name(f["link_names"][0]), topo.node_by_name(f["link_names"][1]))
        elif "on_path" in f:
            want_node = kind == "node_down" or (kind == "slow_processing"
                                                and f["on_path"].get("kind") == "node")
            got = resolve_on_path(f["on_path"], start, want_node)
            if want_node:
                node = got
            else:
                link = got
        if node is not None and not 0 <= node < topo.n_nodes:
            raise ValueError(f"faults[{idx}]: node {node} does not exist")
        li = None
        if link is not None:
            li = topo.link_index.get(link)
            if li is None:
                raise ValueError(f"faults[{idx}]: {link} is not a candidate link of this scenario")
            link = (min(link), max(link))
        params = {"fault_id": fid}
        if kind == "link_down":
            fs.add_link_down(li, link, start, stop, params)
        elif kind == "node_down":
            if node >= topo.n_sats:
                raise ValueError(f"faults[{idx}]: node_down applies to satellites only")
            fs.add_node_down(node, start, stop, params)
        elif kind == "slow_processing":
            delta = int(f["delta_ns"])
            params["delta_ns"] = delta
            if node is not None:
                fs.node_delay.setdefault(node, _Valued()).add(start, stop, delta)
                fs._log(kind, start, stop, node=node, params=params)
            else:
                fs.link_delay.setdefault(li, _Valued()).add(start, stop, delta)
                fs._log(kind, start, stop, link=link, params=params)
        elif kind == "rate_cut":
            fac = exact_fraction(f["factor"], "factor")
            params["factor"] = str(fac)
            fs.rate_cuts.setdefault(li, []).append((start, stop, fac))
            fs._log(kind, start, stop, link=link, params=params)
        elif kind == "arq":
            p = exact_fraction(f["loss"], "loss")
            retries = int(f.get("max_retries", 3))
            extra = int(f.get("retry_extra_ns", 100_000))
            params.update(loss=str(p), max_retries=retries, retry_extra_ns=extra)
            fs.arq.setdefault(li, _Valued()).add(start, stop, (p, retries, extra))
            fs._log(kind, start, stop, link=link, params=params)
    fs.log.sort(key=lambda e: (e["start_ns"], e["kind"], e["link"] or [], e["node"] if e["node"] is not None else -1))
    return fs


__all__ = ["FaultSet", "renewal_periods", "build_faults", "fault_identity", "fault_ids"]

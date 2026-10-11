"""
detection.py
------------
Detection scoring that cannot be fooled by false alarms (reviewer must-fix #1).

The old metric counted a flag set downstream of the faulty link by a packet
that crossed it as a detection, even if that packet would have been flagged
anyway (jitter elsewhere). With a per-packet false-flag rate p and n packets
in the window, P(at least one false flag) = 1 - (1 - p)^n, so "P_det(1 s)"
was close to 100 % even with no fault at all. Here:

COUNTERFACTUAL ATTRIBUTION (common random numbers)
    Run each fault scenario twice with the same seed and policy "continue":
    with the fault, and without it (the twin). Every random draw is keyed
    (fwd/rng.py), so the twin sees the same traffic, jitter and background,
    and the same background failures (renewal streams are keyed by the
    fault's identity, not its list position: fwd/faults.py). check_twin
    VERIFIES this before anything is scored: same packets, the twin's
    fault log equals the fault run's minus the scored fault (null faults
    ignored), entry by entry, and the same configuration otherwise (engine
    config and scheme settings; only the output options may differ).
    Packets are paired by packet id. A packet is a TRUE detection when it
        crossed the faulty element after onset   (metrics.exposure, part "crossed")
        AND is flagged in the fault run
        AND is NOT flagged in the twin.
    P_det(packet) = true detections / exposed packets.

PACKETS THE FAULT DROPS
    A fault can also LOSE packets on its element: a rate cut fills the
    drop-tail FIFO (buffer_overflow), ARQ gives up (arq_exhausted), a downed
    link loses packets in flight, a dead node loses what arrives. Such a
    packet never reaches a checker downstream, so it cannot be detected by
    any deadline check; counting it in the denominator would mix losses into
    the detection probability. It is therefore reported SEPARATELY as
    lost_at_fault (packets the fault lost that never got across it), not in
    `exposed`: exposed + lost_at_fault = reached (every packet that crossed
    the element or was lost on it while the fault acted: metrics.exposure,
    part "all"). Its loss is in the PDR (by reason), and its label is
    `fault`, never `clean` (metrics.packet_labels), so it does not dilute the
    clean-packet FPR either. With a fault-free twin, `reached` is exactly the
    set of packets whose outcome or latency changed for a rate cut with
    fluid background (tested); in general it contains every changed packet
    (ARQ also reaches packets whose first try succeeded; with Poisson
    background a rate cut's drain end is an upper bound).

PHANTOM / NULL FAULT
    A fault that changes nothing (slow_processing with delta 0, or rate_cut
    with factor 1) makes the two runs identical draw for draw, so attributed
    detections must be exactly 0 (tested).

EVENT-LEVEL DETECTOR
    A detector raises an EVENT on element e at time t when k flags localised
    to e arrive within the window (t - W, t]; it then starts counting afresh
    for e. Localisation: a deadline flag at hop k blames the link it came in
    on, (path[k-1], path[k]) (which also carries the processing of path[k-1]);
    an LQ flag blames the link it was about to use; an E2E flag is not
    localised (element = its flow; it matches a fault when one of the k
    packets crossed the fault).
    A fault event is DETECTED at time tau when, in the fault run, the detector
    fires on the fault's element at tau in [onset, onset + horizon) and the
    twin's detector did NOT raise the same event, i.e. did not fire on that
    element within one window of tau ([tau - W, tau + W]): an event the network
    would have raised without the fault is not credited to the fault.
    P_det = detected fault events / fault events; detection delay = tau - onset
    per event (never an average of absolute times), undetected events are
    censored at the horizon (Kaplan-Meier); false events per hour = detector
    events in the twin (no fault at all) / its sending duration in hours.
    Event ROC = (false events per hour, P_det) over a threshold sweep.
"""

import json
from collections import Counter, deque
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from . import metrics
from .offline import rescore


@dataclass
class Flags:
    """One flag per packet at most (the first): where, when, and which element it blames."""
    flagged: np.ndarray
    node: np.ndarray
    time: np.ndarray
    a: np.ndarray            # blamed link (a, b); a = -1: not localised
    b: np.ndarray
    localised: bool = True


def _empty(n):
    return (np.zeros(n, dtype=bool), np.full(n, -1, dtype=np.int64), np.full(n, -1, dtype=np.int64),
            np.full(n, -1, dtype=np.int64), np.full(n, -1, dtype=np.int64))


def deadline_flags(run, first_late=None):
    """Flags of the T-CRH deadline checks (the run's own, or re-scored first_late hops)."""
    k = run.first_late if first_late is None else np.asarray(first_late)
    flagged, node, time, a, b = _empty(run.n)
    sel = np.flatnonzero(k >= 1)
    if sel.size:
        ptr = run.paths.ptr
        kk = k[sel]
        node[sel] = run.paths.flat[ptr[sel] + kk]
        a[sel] = run.paths.flat[ptr[sel] + kk - 1]
        b[sel] = node[sel]
        if run.has_extras():
            arr = run.extras["arrival_ns"]
            time[sel] = arr.flat[arr.ptr[sel] + kk - 1]
        flagged[sel] = True
    return Flags(flagged, node, time, a, b, True)


def lq_flags(run):
    """Flags of the LQ local monitor (blames the link the node was about to use)."""
    flagged, node, time, a, b = _empty(run.n)
    for i, s in enumerate(run.extras["lq_flag"]):
        if s:
            hop, nd, nxt, t = (int(x) for x in s.split(":"))
            flagged[i] = True
            node[i], a[i], b[i], time[i] = nd, nd, nxt, t
    return Flags(flagged, node, time, a, b, True)


def e2e_flags(run):
    """Flags of the end-to-end check (at the destination, not localised)."""
    flagged, node, time, a, b = _empty(run.n)
    sel = np.flatnonzero(run.extras["e2e_late"] == 1)
    for i in sel.tolist():
        flagged[i] = True
        node[i] = int(run.paths[i][-1])
        time[i] = int(run.send_ns[i] + run.latency_ns[i])
    return Flags(flagged, node, time, a, b, False)


def flags_for(run, rule=None):
    """The natural flags of a run's scheme; for T-CRH runs optionally re-scored under `rule`."""
    name = run.scheme.get("name", "chronoroute")
    if name == "lq":
        return lq_flags(run)
    if name == "e2e":
        return e2e_flags(run)
    if rule is not None:
        return deadline_flags(run, rescore(run, rule).first_late)
    return deadline_flags(run)


def is_null_fault(f):
    """A logged fault that changes nothing by construction (the phantom control): slow_processing
    with delta 0, rate_cut with factor 1, arq with loss 0. A twin may carry it in place of the
    scored fault (tests show such a run is identical, byte for byte, to the run without it)."""
    p = f.get("params") or {}
    k = f.get("kind")
    if k == "slow_processing":
        return int(p.get("delta_ns", -1)) == 0
    if k == "rate_cut":
        return "factor" in p and Fraction(str(p["factor"])) == 1
    if k == "arq":
        return "loss" in p and Fraction(str(p["loss"])) == 0
    return False


def _fault_key(f):
    """Everything a logged fault says (kind, element, interval, params) as a hashable value."""
    return (f["kind"], tuple(f["link"]) if f.get("link") is not None else None, f.get("node"),
            int(f["start_ns"]), int(f["stop_ns"]), json.dumps(f.get("params") or {}, sort_keys=True))


def scored_faults(fault_run, twin_run):
    """The faults of the fault run that its twin does not have (null faults ignored on both
    sides): what a fault-run / twin pair can score. Background faults present in both runs
    (e.g. renewal failures, which have identical periods in both: fwd/faults.py) are not
    scored."""
    twin = Counter(_fault_key(f) for f in twin_run.faults if not is_null_fault(f))
    out = []
    for f in fault_run.faults:
        key = _fault_key(f)
        if is_null_fault(f):
            out.append(f)                         # a phantom scored against a twin without it
        elif twin.get(key, 0) > 0:
            twin[key] -= 1
        else:
            out.append(f)
    return out


# engine.config sections that only choose what is WRITTEN (trace level, sampling, pcap, the
# packets file, how many packets get invariant checks), never what happens to a packet, so a twin
# may differ in them (e.g. a fault run with a full trace, a twin without one). "faults" is
# compared entry by entry by item 2 of check_twin instead.
NOT_COMPARED = ("faults", "output")


def _differences(a, b, path, out):
    """Append the dotted paths at which two JSON values differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append(f"{path}.{k}")
            else:
                _differences(a[k], b[k], f"{path}.{k}", out)
    elif a != b or type(a) is not type(b):
        out.append(path)
    return out


def _run_settings(run):
    """(engine config without NOT_COMPARED, scheme name, scheme settings) from run.json.

    A run written by plain `cr run` has no "scheme" block: it IS the default chronoroute
    scheme (test_baselines_engine checks that the two are byte-identical), so its settings
    are the defaults."""
    cfg = (run.run.get("engine") or {}).get("config")
    if not isinstance(cfg, dict):
        return None, None, None
    cfg = {k: v for k, v in cfg.items() if k not in NOT_COMPARED}
    sch = run.run.get("scheme")
    if isinstance(sch, dict) and isinstance(sch.get("settings"), dict):
        return cfg, sch.get("name"), sch["settings"]
    from ..baselines.params import normalise_scheme
    return cfg, "chronoroute", json.loads(json.dumps(normalise_scheme("chronoroute")))


def check_twin(fault_run, twin_run, fault=None):
    """Refuse a pair that is not a counterfactual pair for `fault` (common random numbers).

    With no scored fault, the fault logs must match exactly (null faults still ignored).
    This also validates pairs whose scored-fault list is empty before reporting false events.

    1. Same packets: same count, send times and flows (same seed and traffic).
    2. Same faults except the scored one: the twin's fault log must equal the fault
       run's log minus `fault`, entry by entry (kind, element, interval, params, which
       includes each entry's fault_id). Null faults (is_null_fault) are ignored on both
       sides, so a phantom twin (the scored fault replaced by its delta-0 version) is
       accepted. This catches a twin whose background failures differ (for example
       renewal periods redrawn), which item 1 alone cannot see.
    3. Same configuration otherwise: run.json engine.config (all of it except the fault
       list and the output options, NOT_COMPARED) and the scheme (name and every setting)
       must be equal. Items 1 and 2 cannot see a twin built with another jitter, slack,
       policy, carrier detection delay or scheme: it has the same packets and the same
       faults, but its flags differ for reasons that have nothing to do with the fault, and
       attribution would silently be wrong. A run without engine.config (written before it
       existed) cannot be checked and is refused: re-run it with this version.
    """
    if fault_run.n != twin_run.n or not np.array_equal(fault_run.send_ns, twin_run.send_ns) \
            or not np.array_equal(fault_run.flow, twin_run.flow):
        raise ValueError("fault run and twin must have the same packets (same seed and traffic)")
    cf, nf, sf = _run_settings(fault_run)
    ct, nt, st = _run_settings(twin_run)
    if cf is None or ct is None:
        raise ValueError("cannot check the pair: run.json has no engine.config (runs written before "
                         "2026-10-11); re-run both with this version")
    diff = _differences(cf, ct, "engine.config", [])
    if nf != nt:
        diff.append(f"scheme.name ({nf} vs {nt})")
    else:
        _differences(sf, st, "scheme.settings", diff)
    if diff:
        more = f" and {len(diff) - 6} more" if len(diff) > 6 else ""
        raise ValueError("the twin must be the fault run without the scored fault and otherwise the SAME "
                         "configuration, but they differ at: " + ", ".join(diff[:6]) + more)
    want = Counter(_fault_key(f) for f in fault_run.faults if not is_null_fault(f))
    if fault is not None and not is_null_fault(fault):
        key = _fault_key(fault)
        if want.get(key, 0) == 0:
            raise ValueError("the scored fault is not in the fault run's fault log")
        want[key] -= 1
    have = Counter(_fault_key(f) for f in twin_run.faults if not is_null_fault(f))
    want, have = +want, +have
    if want != have:
        extra_f = sum((want - have).values())
        extra_t = sum((have - want).values())
        example = next(iter((want - have) or (have - want)))
        raise ValueError(
            "the twin must be the fault run without the scored fault (same faults otherwise): "
            f"{extra_f} fault entries only in the fault run, {extra_t} only in the twin "
            f"(first: kind {example[0]}, link {example[1]}, node {example[2]}, "
            f"[{example[3]}, {example[4]}) ns)")


_check_pair = check_twin


def _matches(fl, idx, fault, exposed):
    el = metrics.fault_element(fault)
    if not fl.localised or fl.a[idx] < 0:
        return bool(exposed[idx])
    if el[0] == "link":
        return {int(fl.a[idx]), int(fl.b[idx])} == {el[1], el[2]}
    return int(fl.a[idx]) == el[1]


def counterfactual(fault_run, twin_run, fl_fault, fl_twin, fault):
    """Packet-level attributed detection for one fault (module docstring)."""
    check_twin(fault_run, twin_run, fault)
    reached, _t = metrics.exposure(fault_run, fault)                 # crossed it, or lost on it
    exposed, _t = metrics.exposure(fault_run, fault, "crossed")
    lost = reached & ~exposed                                       # lost there, never got across
    f1, f0 = fl_fault.flagged, fl_twin.flagged
    tp = exposed & f1 & ~f0
    loc = np.array([_matches(fl_fault, i, fault, exposed) for i in np.flatnonzero(tp)], dtype=bool)
    n_exp = int(exposed.sum())
    return {"exposed": n_exp, "true_detections": int(tp.sum()),
            "p_det_packet": (int(tp.sum()) / n_exp) if n_exp else None,
            "flagged_anyway": int((exposed & f1 & f0).sum()),
            # packets the fault LOST on its element (module docstring): never in P_det
            "lost_at_fault": int(lost.sum()), "reached": int(reached.sum()),
            "induced_unexposed": int((~reached & f1 & ~f0).sum()),
            "lost_flags": int((f0 & ~f1).sum()),
            "localised_true_detections": int(loc.sum()) if loc.size else 0}


def detect_events(fl, k, window_ns, run=None):
    """Detector events [(t, element, [packet indices])] from flags (module docstring)."""
    idx = np.flatnonzero(fl.flagged)
    order = idx[np.lexsort((idx, fl.time[idx]))]
    hist = {}
    events = []
    for i in order.tolist():
        t = int(fl.time[i])
        if fl.localised and fl.a[i] >= 0:
            a, b = int(fl.a[i]), int(fl.b[i])
            e = ("link", min(a, b), max(a, b))
        else:
            e = ("flow", int(run.flow[i]) if run is not None else -1)
        dq = hist.setdefault(e, deque())
        dq.append((t, i))
        while dq and dq[0][0] <= t - window_ns:
            dq.popleft()
        if len(dq) >= k:
            events.append((t, e, [j for _t, j in dq]))
            dq.clear()
    return events


def _event_matches(ev, fault, exposed, fl):
    """Does a detector event point at this fault? A link fault: the event's link (either
    direction). A node fault: the event's flags blame links LEAVING the node (its slow
    processing delays packets before they cross the next link). Not localised: one of the
    event's packets crossed the fault."""
    el = metrics.fault_element(fault)
    e = ev[1]
    if e[0] == "flow" or not fl.localised:
        return any(exposed[j] for j in ev[2])
    if el[0] == "link":
        return (e[1], e[2]) == (el[1], el[2])
    return all(int(fl.a[j]) == el[1] for j in ev[2])


def event_detection(fault_run, twin_run, fl_fault, fl_twin, fault, k=1, window_ns=1_000_000_000,
                    horizon_ns=None):
    """One fault event: detected?, delay, and the detector events of both runs."""
    check_twin(fault_run, twin_run, fault)
    exposed, _t = metrics.exposure(fault_run, fault)
    onset = int(fault["start_ns"])
    end = onset + (int(fault["stop_ns"]) - onset if horizon_ns is None else int(horizon_ns))
    ev1 = detect_events(fl_fault, k, window_ns, fault_run)
    ev0 = detect_events(fl_twin, k, window_ns, twin_run)
    twin_hits = [ev[0] for ev in ev0 if _event_matches(ev, fault, exposed, fl_twin)]
    for ev in ev1:
        t = ev[0]
        if not onset <= t < end or not _event_matches(ev, fault, exposed, fl_fault):
            continue
        if any(t - window_ns <= th <= t + window_ns for th in twin_hits):
            continue                       # the twin raised the same event (within one window)
        return {"detected": True, "delay_ns": t - onset, "horizon_ns": end - onset,
                "events_fault_run": len(ev1), "events_twin": len(ev0)}
    return {"detected": False, "delay_ns": None, "horizon_ns": end - onset,
            "events_fault_run": len(ev1), "events_twin": len(ev0)}


def false_events_per_hour(run, fl, k=1, window_ns=1_000_000_000, mask=None):
    """Detector events in a run with NO fault (twin or phantom) per hour of sending."""
    if mask is not None:
        fl = Flags(fl.flagged & mask, fl.node, fl.time, fl.a, fl.b, fl.localised)
    lo, hi = metrics.send_window(run)
    hours = (hi - lo) / 3.6e12
    ev = detect_events(fl, k, window_ns, run)
    return {"events": len(ev), "hours": hours, "per_hour": (len(ev) / hours) if hours else None}


def control_plane_detection(fault_run, twin_run, fault, kinds=("adjacency_down", "metric"),
                            window_ns=1_000_000_000):
    """Detection by a link-state control plane: the first node that updated adjacency or metric
    for the faulty element after onset (science report 6.8), unless the twin's control plane
    did the same within one window of it."""
    check_twin(fault_run, twin_run, fault)
    el = metrics.fault_element(fault)
    onset, stop = int(fault["start_ns"]), int(fault["stop_ns"])

    def hits(run):
        out = []
        for d in run.detections:
            if d["kind"] not in kinds:
                continue
            if el[0] == "link" and {d["a"], d["b"]} != {el[1], el[2]}:
                continue
            if el[0] == "node" and el[1] not in (d["a"], d["b"]):
                continue
            out.append(d["t_ns"])
        return sorted(out)

    t0 = hits(twin_run)
    for t in hits(fault_run):
        if onset <= t < stop and not any(t - window_ns <= x <= t + window_ns for x in t0):
            return {"detected": True, "delay_ns": t - onset, "horizon_ns": stop - onset}
    return {"detected": False, "delay_ns": None, "horizon_ns": stop - onset}


def kaplan_meier(durations, observed):
    """Kaplan-Meier estimate for right-censored durations.

    Returns (times, survival): S(t) just after each distinct event time. The CDF of
    detection delay is 1 - S. An event and a censoring at the same time: the event
    is counted first (the censored item was still at risk).
    """
    d = np.asarray(durations, dtype=float)
    o = np.asarray(observed, dtype=bool)
    if d.size == 0:
        return np.zeros(0), np.zeros(0)
    times = np.unique(d[o])
    surv = []
    s = 1.0
    for t in times:
        at_risk = int(np.sum(d >= t))
        events = int(np.sum((d == t) & o))
        if at_risk:
            s *= 1.0 - events / at_risk
        surv.append(s)
    return times, np.array(surv)


def km_median(durations, observed):
    t, s = kaplan_meier(durations, observed)
    for ti, si in zip(t, s):
        if si <= 0.5:
            return float(ti)
    return None


def event_roc(pairs, faults_of, rules, *, k=1, window_ns=1_000_000_000, horizon_ns=None):
    """Event ROC over a threshold sweep (offline re-scoring of T-CRH flag-and-continue runs).

    pairs      [(fault_run, twin_run)] loaded runs (same seed within a pair)
    faults_of  function(fault_run) -> list of fault entries to score, or None: the faults the
               twin does not have (scored_faults; background faults of both runs excluded)
    rules      [offline.Rule]
    Returns one row per rule: P_det over all fault events, false events per hour in the
    twins, packet-level P_det and clean-packet FPR (from the twins: every packet of a
    run without fault and with clean label).
    """
    rows = []
    for rule in rules:
        det = total = 0
        fa_events = 0
        hours = 0.0
        delays, observed = [], []
        tp = expo = 0
        fp = clean = 0
        for fr, tw in pairs:
            actual = scored_faults(fr, tw)
            # Validate the pair's real fault difference even when the caller selects no
            # faults to score. An empty selection need not mean the fault logs are equal.
            for fault in actual or [None]:
                check_twin(fr, tw, fault)
            faults = actual if faults_of is None else list(faults_of(fr))
            f1 = flags_for(fr, rule)
            f0 = flags_for(tw, rule)
            for fault in faults:
                r = event_detection(fr, tw, f1, f0, fault, k, window_ns, horizon_ns)
                total += 1
                det += int(r["detected"])
                delays.append(r["delay_ns"] if r["detected"] else r["horizon_ns"])
                observed.append(r["detected"])
                c = counterfactual(fr, tw, f1, f0, fault)
                tp += c["true_detections"]
                expo += c["exposed"]
            fe = false_events_per_hour(tw, f0, k, window_ns)
            fa_events += fe["events"]
            hours += fe["hours"]
            lab = metrics.packet_labels(tw)
            m = metrics.measurement_mask(tw)
            clean += int(((lab == 0) & m).sum())
            fp += int(((lab == 0) & m & f0.flagged).sum())
        rows.append({"rule": rule.label, "fault_events": total, "detected": det,
                     "p_det": (det / total) if total else None,
                     "false_events_per_hour": (fa_events / hours) if hours else None,
                     "p_det_packet": (tp / expo) if expo else None,
                     "clean_fpr": (fp / clean) if clean else None,
                     "delay_km_median_ns": km_median(delays, observed)})
    return rows


__all__ = ["Flags", "deadline_flags", "lq_flags", "e2e_flags", "flags_for", "is_null_fault", "scored_faults",
           "check_twin", "counterfactual", "detect_events",
           "event_detection", "false_events_per_hour", "control_plane_detection", "kaplan_meier", "km_median",
           "event_roc"]

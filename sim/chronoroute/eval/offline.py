"""
offline.py
----------
Re-score the deadline checks of a finished FLAG-AND-CONTINUE run for any
other deadline rule, without simulating again (master plan E1: "thresholds
scored offline"; reviewer nice-to-have "score every detector offline").

Why this is exact. Under policy "continue" a late packet keeps following its
SIDs: the DEV flag changes two header bits, never the path, the packet size
or any timing. So every packet's path and its arrival time at every node are
the same whatever the deadlines are, and the deadline check of a node is a
pure function of numbers the run recorded:

    D_k   = Epoch_Base + sum of the first k encoded deltas            (spec 5)
    Epoch = ceil(T_ingress_gps / u) mod 2^32                         (spec 4)
    now_k = floor(T_arrival_k_gps / u) mod 2^32
    late  = serial(now_k - D_k) > 0, checked at hop k only while DEV is clear

with the deltas = chronoroute.proto.encode_deltas(B_1..B_h, unit), the SAME
function the planner uses, and B_k from the schedule row's predicted hop
delays P_1..P_h (schedule.csv.gz) by the rule:

    mult      B_k = S * (P_1 + ... + P_k)                 (exact fraction; the engine's rule)
    add       B_k = (P_1 + ... + P_k) + k * a_hop + a_const
    quantile  B_k = (P_1 + ... + P_k) + ceil(z_(1-alpha) * sigma * sqrt(k))
              (sigma: a per-hop delay spread given as a STATIC prior, reviewer
              must-fix #3 asks to say where sigma comes from; z from stats.normal_ppf)

Two conditions are checked, not assumed:
  * the run used policy "continue" (else a late packet changes path: refused);
  * the schedule rows do not depend on the rule. The "stable" planner's
    look-ahead uses the final budget B_h, so a different slack can in rare
    cases plan a different path; check_plans() re-plans every row with the
    new rule and lists the rows that would change (the equivalence test
    compares against direct runs as well).

Needs scheme_packets.csv.gz (arrival time in ns at every node and the hop
index each node checked), which `cr eval scheme` writes.
"""

import math
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from ..proto import encode_deltas
from ..proto.timebase import HALF32, MOD32, unit_ns
from ..route import scheduler
from . import stats

MASK32 = MOD32 - 1


@dataclass(frozen=True)
class Rule:
    """A deadline rule (module docstring). unit_code None = the run's own unit."""
    kind: str = "mult"
    slack: str = "1.5"
    per_hop_ns: int = 0
    const_ns: int = 0
    alpha: str = "0.001"
    sigma_ns: int = 0
    unit_code: int | None = None

    def __post_init__(self):
        if self.kind not in ("mult", "add", "quantile"):
            raise ValueError(f"rule kind must be mult, add or quantile, got {self.kind!r}")
        if self.kind == "mult":
            scheduler.exact_slack(self.slack)
        if self.kind == "quantile":
            a = Fraction(str(self.alpha))
            if not 0 < a < 1:
                raise ValueError("alpha must be in (0, 1)")

    @property
    def label(self):
        u = "" if self.unit_code is None else f" u{self.unit_code}"
        if self.kind == "mult":
            return f"S={self.slack}{u}"
        if self.kind == "add":
            return f"add {self.per_hop_ns}/hop+{self.const_ns}{u}"
        return f"q alpha={self.alpha} sigma={self.sigma_ns}{u}"

    def budgets(self, hop_delays_ns):
        """B_1..B_h (exact Fractions or ints, non-decreasing)."""
        cum = []
        run = 0
        for d in hop_delays_ns:
            run += int(d)
            cum.append(run)
        if self.kind == "mult":
            return scheduler.cumulative_budgets(list(hop_delays_ns), self.slack)
        if self.kind == "add":
            return [c + (k + 1) * int(self.per_hop_ns) + int(self.const_ns) for k, c in enumerate(cum)]
        z = stats.normal_ppf(1.0 - float(Fraction(str(self.alpha))))
        return [c + int(math.ceil(z * self.sigma_ns * math.sqrt(k + 1))) for k, c in enumerate(cum)]


@dataclass
class Rescored:
    rule: Rule
    first_late: np.ndarray        # hop index k of the first late check, -1 none
    flagged: np.ndarray           # first_late >= 1
    deadlines: np.ndarray         # per arrival entry (aligned with extras arrival_ns), -1 where none
    late_entry: np.ndarray        # per packet: index (within its arrivals) of the first late node, -1
    scored: np.ndarray            # packets that had a schedule row (others cannot be flagged)
    ptr: np.ndarray               # offsets of each packet's arrival entries in `deadlines`


def _require(run):
    if not run.has_extras():
        raise ValueError(f"{run.dir}: offline scoring needs scheme_packets.csv.gz (run with `cr eval scheme`)")
    pol = run.engine.get("policy")
    if pol != "continue":
        raise ValueError(f"{run.dir}: offline scoring needs a flag-and-continue run (policy continue), "
                         f"this run used {pol!r}: a late packet changed its path")


def rescore(run, rule):
    """Rescored deadline checks of every packet under `rule` (module docstring)."""
    _require(run)
    unit = run.run["unit_code"] if rule.unit_code is None else int(rule.unit_code)
    u = unit_ns(unit)
    t0g = int(run.run["t0_gps_ns"])
    hk = run.extras["hop_k"]
    arr = run.extras["arrival_ns"]
    if not np.array_equal(hk.ptr, arr.ptr):
        raise ValueError(f"{run.dir}: hop_k and arrival_ns must have one entry per arrival")
    n = run.n
    # rows: cumulative encoded deltas per schedule row, flattened
    keys = sorted(run.schedule)
    row_of = {key: r for r, key in enumerate(keys)}
    roff = np.zeros(len(keys) + 1, dtype=np.int64)
    cums = []
    for r, key in enumerate(keys):
        deltas, _sat = encode_deltas(rule.budgets(run.schedule[key]["hop_delays_ns"]), unit)
        c = np.cumsum(np.asarray(deltas, dtype=np.int64))
        cums.append(c)
        roff[r + 1] = roff[r] + len(c)
    cumflat = np.concatenate(cums) if cums else np.zeros(0, dtype=np.int64)
    prow = np.full(n, -1, dtype=np.int64)
    for i in range(n):
        if run.row_from_ms[i] >= 0:
            prow[i] = row_of.get((int(run.flow[i]), int(run.row_from_ms[i])), -1)
    lens = hk.lengths()
    pk = np.repeat(np.arange(n, dtype=np.int64), lens)
    hkv = hk.flat
    k = np.where(hkv >= 1, hkv, np.where(hkv <= -2, -2 - hkv, 0))
    has_dl = (k >= 1) & (prow[pk] >= 0)
    rel = np.zeros(len(hkv), dtype=np.int64)
    idx = roff[np.maximum(prow[pk], 0)] + np.maximum(k, 1) - 1
    ok_idx = has_dl & (idx < roff[np.maximum(prow[pk], 0) + 1])
    if np.any(has_dl & ~ok_idx):
        raise ValueError(f"{run.dir}: a recorded hop index exceeds its schedule row (wrong row?)")
    rel[has_dl] = cumflat[idx[has_dl]]
    epoch = (-((-(t0g + run.send_ns)) // u)) & MASK32
    deadline = np.where(has_dl, (epoch[pk] + rel) & MASK32, -1)
    now = ((t0g + arr.flat) // u) & MASK32
    check = has_dl & (hkv >= 1)
    diff = ((now - deadline + HALF32) & MASK32) - HALF32
    late = check & (diff > 0)
    # first late entry per packet
    first_entry = np.full(n, -1, dtype=np.int64)
    pos = np.flatnonzero(late)
    if pos.size:
        pkts = pk[pos]
        # positions are in packet order already; the first occurrence of each packet is its first late entry
        first_mask = np.ones(pos.size, dtype=bool)
        first_mask[1:] = pkts[1:] != pkts[:-1]
        sel = pos[first_mask]
        first_entry[pk[sel]] = sel - arr.ptr[pk[sel]]
    first_late = np.full(n, -1, dtype=np.int64)
    m = first_entry >= 0
    if np.any(m):
        first_late[m] = k[arr.ptr[:-1][m] + first_entry[m]]
    return Rescored(rule=rule, first_late=first_late, flagged=first_late >= 1, deadlines=deadline,
                    late_entry=first_entry, scored=prow >= 0, ptr=arr.ptr)


def compare_with_run(res, direct):
    """Mismatches between a re-scored run and a DIRECT run of the same rule (same packets).

    Compared per packet: first_late_hop, and every deadline the direct run recorded
    (packets.csv deadline_u, '-' entries skipped). Returns a dict of counts and examples.
    """
    if direct.n != len(res.first_late):
        raise ValueError("the runs have different packets")
    bad_first = np.flatnonzero(res.first_late != direct.first_late)
    bad_dl = []
    for i in range(direct.n):
        d = direct.deadline_u[i]
        if d.size == 0:
            continue
        # the direct run's deadline_u has one entry per node that ran spec 6 or relayed a
        # detour (every arrival but a final lost one), so it lines up with our first entries
        lo = int(res.ptr[i])
        mine = res.deadlines[lo:lo + d.size]
        sel = d >= 0
        if mine.size != d.size or not np.array_equal(mine[sel], d[sel]):
            bad_dl.append(i)
    return {"packets": int(direct.n), "first_late_mismatch": int(bad_first.size),
            "deadline_mismatch": len(bad_dl), "examples": [int(x) for x in list(bad_first[:5]) + bad_dl[:5]]}


def check_plans(cfg, run, rule, *, scenario=None):
    """Rows whose planned path would change under `rule` (re-plans every row of the run).

    cfg: the run's normalised engine config (manifest "config.run"). Only the multiplicative
    rule changes the planner (it is the planner's own slack); the others leave the rows as
    they are, so they never change a path.
    """
    import copy
    from ..fwd.scenario import build_scenario
    if rule.kind != "mult":
        return []
    c2 = copy.deepcopy(cfg)
    c2["schedule"]["slack"] = str(rule.slack)
    if rule.unit_code is not None:
        c2["schedule"]["unit_code"] = int(rule.unit_code)
    if scenario is not None and cfg["schedule"]["plan_links"] != "instant":
        raise ValueError("scenario reuse requires instant planning: stable look-ahead depends on budgets")
    # With instant planning the Dijkstra graph and tie order do not depend on
    # any budget. A caller can validate all rules against one actual scenario.
    sc = scenario if scenario is not None else build_scenario(c2)
    r = sc.refresh_ms
    dur_ms = sc.duration_ns // 1_000_000
    changed = []
    for (flow, start), row in sorted(run.schedule.items()):
        e = sc.plan(sc.flows[flow], start, min(start + r, dur_ms))
        if e is None or list(e.path) != list(row["path"]):
            changed.append((flow, start))
    return changed


__all__ = ["Rule", "Rescored", "rescore", "compare_with_run", "check_plans"]

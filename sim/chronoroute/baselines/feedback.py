"""
feedback.py
-----------
The ground side of the feedback schemes (master plan P3d and E8):

  FB1   a satellite that finds a packet late reports the suspect link (the
        link the packet arrived on, path[k-1] -> path[k]) to the ground; the
        report takes `delay_ms` (50 ms) one way. At its NEXT refresh the
        ground plans with that link's weight multiplied by the penalty
        (x2, x10) or removed (inf), for `hold_s` seconds; a new report
        extends the hold.
  E2E   the destination station finds the packet late against its single
        end-to-end deadline and reports the packet's path; the ground cannot
        tell which link was slow, so it penalises every satellite-to-
        satellite link of that path ("path"), or only the links shared by
        all late paths reported in the last window ("intersect", the
        simplest multi-flow tomography; when the late paths share no link it
        falls back to "path").

The planner itself is the engine's (fwd/scenario.py "stable" rule +
route/scheduler.plan_path). With penalties the PATH is chosen on the
penalised weights, but the deadlines are always built from the TRUE
predicted hop delays of that path (a penalty is a routing preference, not a
prediction that the link is slower).
"""

import dataclasses

import numpy as np

from .. import proto
from ..route import scheduler
from ..topo import graph as graph_mod, invariants
from ..fwd.scenario import PLAN_MAX_ROUNDS

INF_PENALTY = "inf"


class PenaltyBook:
    """Penalties the ground applies to links, with the time each becomes active."""

    def __init__(self, refresh_ns, hold_ns, factor):
        self.refresh_ns = int(refresh_ns)
        self.hold_ns = int(hold_ns)
        self.factor = factor
        self.intervals = {}                # link index -> [[active_from, active_until], ...]
        self.reports = 0
        self.changes = []                  # (active_from, link) when a link first becomes penalised

    def report(self, arrive_ns, links):
        """Reports reaching the ground at arrive_ns about these link indices."""
        self.reports += 1
        start = -(-arrive_ns // self.refresh_ns) * self.refresh_ns        # the next refresh
        until = start + self.hold_ns
        for li in links:
            iv = self.intervals.setdefault(li, [])
            if iv and iv[-1][0] <= start <= iv[-1][1]:
                iv[-1][1] = max(iv[-1][1], until)                         # extend the hold
            else:
                iv.append([start, until])
                self.changes.append((start, li))

    def active(self, t_ns):
        """{link index: factor} active at plan time t_ns."""
        out = {}
        for li, iv in self.intervals.items():
            for s, e in iv:
                if s <= t_ns < e:
                    out[li] = self.factor
                    break
        return out


def penalised_csr(topo, k0, k1, penalties):
    """topo.csr_stable(k0, k1) with penalised weights (x factor) or removed links (inf)."""
    mask = topo.up_range(k0, k1).all(axis=1)
    ch = topo.chunk_of_step(k0)
    w = ch.prop[:, k0 - ch.k0] + topo.planner_processing_ns
    w = w.astype(np.int64).copy()
    true_w = w.copy()
    mask = mask.copy()
    for li, factor in penalties.items():
        if factor == INF_PENALTY:
            mask[li] = False
        else:
            w[li] = w[li] * int(factor)
    csr = graph_mod.csr_from_edges(topo.n_nodes, topo.link_a[mask], topo.link_b[mask], w[mask], topo.transit)
    return csr, true_w


def _true_entry(e, topo, true_w, slack, unit_code, next_header):
    """The plan entry e (chosen on penalised weights) with budgets from the TRUE hop delays."""
    hop = [int(true_w[topo.link_index[(u, v)]]) for u, v in zip(e.path[:-1], e.path[1:])]
    prop = [d - topo.planner_processing_ns for d in hop]
    budgets = scheduler.cumulative_budgets(hop, slack)
    template = proto.build_header(e.sids_fwd, budgets, 0, unit_code, next_header=next_header).encode()
    return dataclasses.replace(e, hop_delays_ns=tuple(hop), prop_ns=tuple(prop), budgets_ns=tuple(budgets),
                               template=template)


def plan_with_penalties(sc, flow, start_ms, end_ms, penalties):
    """Scenario.plan's "stable" planner on penalised weights (see the module docstring).

    Same widening rule as fwd/scenario.Scenario.plan: plan on the links up from
    valid_from until valid_to + the path's own final budget, widening the look-ahead
    until the path fits (at most PLAN_MAX_ROUNDS rounds).
    """
    if not penalties:
        return sc.plan(flow, start_ms, end_ms)
    sh = sc.cfg["schedule"]
    topo = sc.topo
    step_ms = sc.step_ns // 1_000_000
    step = start_ms // step_ms
    last_step = sc.n_steps - 1

    def one(k1):
        csr, true_w = penalised_csr(topo, step, k1, penalties)
        e = scheduler.plan_path(topo, flow.src_node, flow.dst_node, step, slack=sh["slack"],
                                unit_code=sh["unit_code"], next_header=sc.next_header, csr=csr)
        if e is None:
            return None
        return _true_entry(e, topo, true_w, sh["slack"], sh["unit_code"], sc.next_header)

    if sh["plan_links"] == "instant":
        return one(step)
    horizon_ns = 0
    e = None
    for _ in range(PLAN_MAX_ROUNDS):
        k1 = max(step, invariants.last_step_needed(end_ms, horizon_ns, step_ms, last_step))
        e = one(k1)
        if e is None or e.budgets_ceil_ns[-1] <= horizon_ns:
            break
        horizon_ns = e.budgets_ceil_ns[-1]
    return e


def path_isls(topo, path):
    """Link indices of the satellite-to-satellite links of a node path."""
    S = topo.n_sats
    return [topo.link_index[(u, v)] for u, v in zip(path[:-1], path[1:]) if u < S and v < S]


def intersect_links(late_paths, topo):
    """Links shared by every late path (E2E 'intersect'); falls back to the union when empty."""
    sets = [set(path_isls(topo, p)) for p in late_paths]
    if not sets:
        return []
    common = set.intersection(*sets)
    return sorted(common) if common else sorted(set.union(*sets))


__all__ = ["INF_PENALTY", "PenaltyBook", "penalised_csr", "plan_with_penalties", "path_isls",
           "intersect_links"]

"""
scheduler.py
------------
From a flow (source city -> destination city) at a time t to the T-CRH bytes.

Steps (everything after the path search is exact integer / rational math):

  1. Path: canonical Dijkstra (dijkstra.py) on the graph of the step at t:
     ground station -> satellites -> ground station.
  2. Predicted delay of hop k (k = 1..h, h = number of SIDs = links on the
     path): the edge weight, i.e. light time round(d/c) + 0.5 ms processing,
     integer ns.
  3. Cumulative budget to reach hop k with multiplicative slack S:
         B_k = S * (d_1 + ... + d_k)            (exact Fraction, ns)
     S is read exactly ("1.5" is 3/2, never a binary float).
  4. Header: chronoroute.proto.build_header(SIDs of hops 1..h, B, ingress
     time, unit code). The deltas use the spec's ceil-cumulative encoding
     (section 5.1), so no deadline is ever earlier than its budget unless
     SAT is set. The default unit code is 1 (0.1 ms).

The SIDs: satellites from the stable registry (sids.py, keyed by NORAD id),
ground stations 0xF000 + g (spec section 7).

A schedule TEMPLATE has Epoch_Base = 0; the ingress stamps every packet
with its own Epoch_Base = ceil(T_ingress_gps / u) mod 2^32 (spec section 4).
header_for_packet() does that for a given UTC instant.
"""

import math
from dataclasses import dataclass
from fractions import Fraction

from .. import proto
from ..proto import timebase
from . import dijkstra

DEFAULT_SLACK = "1.5"
DEFAULT_UNIT_CODE = 1                   # 0.1 ms (spec section 3, provisional default)
DEFAULT_NEXT_HEADER = 17                # UDP; the ingress may rewrite byte 0

# Seconds from the Unix epoch (1970-01-01) to the GPS epoch (1980-01-06).
UNIX_TO_GPS_EPOCH_S = 315_964_800
NS = 1_000_000_000
GPS_VALID_FROM_UNIX_NS = 1_483_228_800 * NS     # 2017-01-01T00:00:00Z


def exact_slack(slack):
    """The slack factor S as an exact positive Fraction.

    A string or int is read exactly ("1.5" -> 3/2); a float through its
    shortest repr (1.2 -> 6/5, not 1.1999999999999999556), so the budget is
    the one the experimenter meant.
    """
    if isinstance(slack, bool):
        raise TypeError("slack cannot be a bool")
    if isinstance(slack, float):
        value = Fraction(repr(slack))
    elif isinstance(slack, (int, str, Fraction)):
        value = Fraction(slack)
    else:
        raise TypeError(f"slack must be a str, int, float or Fraction, got {type(slack).__name__}")
    if value <= 0:
        raise ValueError(f"slack must be positive, got {slack}")
    return value


def utc_ns_to_gps_ns(utc_ns):
    """UTC ns since 1970 -> GPS ns since 1980-01-06 (GPS = UTC + 18 s from 2017 on).

    Integer-exact twin of proto.utc_to_gps_ns (which takes a datetime and so
    only keeps microseconds); a test checks they agree.
    """
    if isinstance(utc_ns, bool) or not isinstance(utc_ns, int):
        raise TypeError("utc_ns must be an int")
    if utc_ns < GPS_VALID_FROM_UNIX_NS:
        raise ValueError("GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on")
    return utc_ns - UNIX_TO_GPS_EPOCH_S * NS + timebase.GPS_UTC_OFFSET_S * NS


def cumulative_budgets(hop_delays_ns, slack):
    """B_k = S * (d_1 + ... + d_k) as exact Fractions (ns)."""
    s = exact_slack(slack)
    out, running = [], 0
    for d in hop_delays_ns:
        if isinstance(d, bool) or not isinstance(d, int) or d < 0:
            raise ValueError(f"hop delays must be non-negative int ns, got {d!r}")
        running += d
        out.append(s * running)
    return out


def ceil_ns(budget):
    """ceil(B) as an int. ceil(ceil(B)/u) == ceil(B/u) for integer u, so the
    integer budgets exported to CSV encode to exactly the same deltas."""
    return math.ceil(Fraction(budget))


@dataclass(frozen=True)
class ScheduleEntry:
    """One planned path with its deadlines (a T-CRH template)."""

    src: int                        # node ids
    dst: int
    step: int                       # graph step the path was computed on
    t_ns: int                       # UTC ns of that step
    path: tuple                     # node ids, src first, dst last
    sids_fwd: tuple                 # SIDs of path[1:], forward order
    hop_delays_ns: tuple            # predicted delay of each hop (prop + processing)
    prop_ns: tuple                  # light-time part of each hop
    budgets_ns: tuple               # exact cumulative budgets B_k (Fractions)
    slack: Fraction
    unit_code: int
    next_header: int
    template: bytes                 # T-CRH with Epoch_Base = 0

    @property
    def num_hops(self):
        return len(self.sids_fwd)

    @property
    def predicted_total_ns(self):
        return sum(self.hop_delays_ns)

    @property
    def prop_total_ns(self):
        return sum(self.prop_ns)

    @property
    def budgets_ceil_ns(self):
        return tuple(ceil_ns(b) for b in self.budgets_ns)

    @property
    def header(self):
        return proto.TcrhHeader.decode(self.template)

    def header_for_packet(self, t_ingress_utc_ns):
        """The header bytes of a packet entering at t_ingress_utc_ns (UTC ns)."""
        gps = utc_ns_to_gps_ns(int(t_ingress_utc_ns))
        hdr = proto.build_header(self.sids_fwd, self.budgets_ns, gps, self.unit_code,
                                 next_header=self.next_header)
        return hdr.encode()


def plan_path(scenario, src_node, dst_node, step, *, slack=DEFAULT_SLACK,
              unit_code=DEFAULT_UNIT_CODE, next_header=DEFAULT_NEXT_HEADER, csr=None):
    """Schedule entry for src -> dst on the graph of `step`, or None if unreachable.

    scenario is a topo.graph.Scenario; csr may be passed to reuse a graph
    already built for this step (the bundle plans several flows per step).
    """
    if src_node == dst_node:
        raise ValueError("a flow needs two different end points")
    graph = scenario.graph
    csr = graph.csr_at(step) if csr is None else csr
    sp = dijkstra.dijkstra(csr, src_node, dst_node)
    if sp.dist[dst_node] is None:
        return None
    path = sp.path_to(dst_node)
    hop_delays = [sp.dist[v] - sp.dist[u] for u, v in zip(path[:-1], path[1:])]
    prop = [d - graph.processing_ns for d in hop_delays]
    sids = [scenario.node_sid(v) for v in path[1:]]
    budgets = cumulative_budgets(hop_delays, slack)
    template = proto.build_header(sids, budgets, 0, unit_code, next_header=next_header).encode()
    return ScheduleEntry(src=src_node, dst=dst_node, step=int(step), t_ns=int(graph.times_ns[step]),
                         path=tuple(path), sids_fwd=tuple(sids), hop_delays_ns=tuple(hop_delays),
                         prop_ns=tuple(prop), budgets_ns=tuple(budgets), slack=exact_slack(slack),
                         unit_code=unit_code, next_header=next_header, template=template)


__all__ = [
    "DEFAULT_SLACK", "DEFAULT_UNIT_CODE", "DEFAULT_NEXT_HEADER", "exact_slack", "utc_ns_to_gps_ns",
    "cumulative_budgets", "ceil_ns", "ScheduleEntry", "plan_path",
]

"""
scheduler.py
------------
The ground station side: offline, ephemeris-driven schedule computation.

This is the part that replaces OSPF/BGP. Once every SCHEDULE_INTERVAL_S the
ground station:
    1. looks up where every satellite WILL be (from SGP4, no measurement)
    2. builds the graph for that instant
    3. runs Dijkstra for each flow
    4. writes a T-CRH template with a deadline budget for every hop

The cumulative budget to reach hop k is:   SLACK_FACTOR * predicted delay
of hops 1..k. It is encoded ceil-cumulative in exact integer nanoseconds
(spec/tcrh-v1.md 5.1), so no deadline is ever below the prediction.

SLACK_FACTOR is the single most important knob in the whole project. Too
tight and healthy packets get dropped as "expired". Too loose and a real
link failure goes undetected for a long time. Finding the best value is
Experiment 1.

What the schedule does NOT contain is the time anchor. Epoch_Base is stamped
by the gateway on EVERY packet when it enters the network (ingress_header
below, spec section 4). v0 wrote the schedule epoch into the header, so a
packet sent 14 s after the epoch would have been 14 s "late" at its first
hop; the v0 simulator hid that by re-anchoring the deadlines itself.
"""

import bisect
import dataclasses
from fractions import Fraction

import networkx as nx

from constellation import GROUND_STATIONS
from topology import build_graph, PROCESSING_DELAY_MS
from header import GS_SID_BASE, DEFAULT_UNIT_CODE
from chronoroute import proto

SCHEDULE_INTERVAL_S = 15     # how often ground stations recompute (Starlink-like)


# --------------------------------------------------------------- SID plan / FIB

def node_to_sid(node):
    """
    Map a graph node to its 16-bit segment ID (spec section 7).

      satellite 0..0xEFFF  -> the same number
      'GS:Chennai'         -> 0xF000 + 0, etc.
    """
    if isinstance(node, int):
        if not 0 <= node <= proto.SID_SATELLITE_MAX:
            raise ValueError(f"satellite {node} does not fit the satellite SID block "
                             f"0..0x{proto.SID_SATELLITE_MAX:04X}")
        return node
    name = node.split(':', 1)[1]
    for i, (nm, _, _) in enumerate(GROUND_STATIONS):
        if nm == name:
            return GS_SID_BASE + i
    raise ValueError(f"unknown node {node}")


def sid_to_node(sid):
    """
    The CRH-FIB lookup (spec section 6, step 6): which node owns this SID.
    Raises KeyError for a SID with no entry; a real node would then discard
    the packet with ICMPv6 Parameter Problem, Code 0.
    """
    if 0 <= sid <= proto.SID_SATELLITE_MAX:
        return sid
    g = sid - GS_SID_BASE
    if 0 <= g < len(GROUND_STATIONS):
        return f"GS:{GROUND_STATIONS[g][0]}"
    raise KeyError(f"SID 0x{sid:04X} has no CRH-FIB entry")


# --------------------------------------------------------------- paths and budgets

def compute_path(graph, src, dst):
    """
    Dijkstra over the 'weight' attribute (which is delay in ms).

    Returns (path_nodes, total_predicted_ms) or (None, None) if unreachable.
    """
    try:
        path = nx.shortest_path(graph, src, dst, weight='weight')
        total = nx.shortest_path_length(graph, src, dst, weight='weight')
        return path, total
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None, None


def exact_slack(slack_factor):
    """
    The slack factor as an exact fraction. A float is read through its
    shortest repr, so 1.2 means exactly 6/5 (not the binary
    1.1999999999999999555910790149937), and the ceil in the encoder sees
    the budget the experimenter meant.
    """
    if isinstance(slack_factor, bool):
        raise TypeError("slack_factor cannot be a bool")
    if isinstance(slack_factor, float):
        # float.__repr__ also gives "1.2" for a numpy float64
        s = Fraction(float.__repr__(slack_factor))
    else:
        s = Fraction(slack_factor)
    if s <= 0:
        raise ValueError(f"slack_factor must be positive, got {slack_factor}")
    return s


def build_schedule_entry(graph, src, dst, slack_factor, epoch_base_ms=0,
                         unit_code=DEFAULT_UNIT_CODE, next_header=6):
    """
    Produce one schedule entry: the path plus its per-hop deadline budget.

    epoch_base_ms is only recorded (as 'schedule_epoch_ms'): it is the time
    the schedule was computed for, NOT the header's Epoch_Base. The header
    stored here is a template with Epoch_Base = 0; the gateway stamps every
    packet with its own ingress time (ingress_header).

    Returns a dict, or None if no path exists.
    """
    if src == dst:
        raise ValueError("a flow needs two different end points")
    path, total_predicted = compute_path(graph, src, dst)
    if path is None:
        return None

    # per-hop predicted delay, straight off the graph edges
    per_hop_predicted = []
    for a, b in zip(path[:-1], path[1:]):
        per_hop_predicted.append(graph[a][b]['weight'])

    # cumulative budget to reach hop k = S x predicted delay of hops 1..k,
    # in exact nanoseconds (the edge weights are converted once, to the
    # nearest ns, which is the one sanctioned float -> wire crossing)
    slack = exact_slack(slack_factor)
    cumulative_ns, running = [], 0
    for d in per_hop_predicted:
        running += proto.ms_to_ns(d)
        cumulative_ns.append(slack * running)

    # The T-CRH path vector lists every node AFTER the source, one segment ID
    # per link. Satellites use their own ID; ground stations get an ID from
    # the reserved high block (RFC 9631 SIDs are FIB indices, not addresses).
    sids = [node_to_sid(n) for n in path[1:]]
    assert len(sids) == len(cumulative_ns), "one segment ID per link budget"

    # encode a real header (Epoch_Base 0: a template) so we know its true size
    hdr = proto.build_header(sids, cumulative_ns, 0, unit_code, next_header=next_header)
    raw = hdr.encode()

    return {
        'src': src,
        'dst': dst,
        'path': path,                       # for plots only: never forwarded on
        'sids': tuple(sids),                # forward order, as in the header
        'per_hop_predicted_ms': per_hop_predicted,
        'deltas_ms': [d * float(slack) for d in per_hop_predicted],   # S x per-hop, unrounded
        'cum_budget_ns': tuple(cumulative_ns),    # exact (Fraction) B_1..B_h
        'deltas_u': hdr.deltas_fwd,         # what is on the wire, in units
        'unit_code': unit_code,
        'slack_factor': slack_factor,
        'total_predicted_ms': total_predicted,
        'num_hops': len(path) - 1,
        'header_bytes': len(raw),
        'header_template': raw,             # Epoch_Base = 0; see ingress_header
        'delta_overflow': hdr.is_sat,       # a delta did not fit one byte (SAT)
        'schedule_epoch_ms': epoch_base_ms,
    }


def ingress_header(entry, t_ingress_gps_ns):
    """
    What the gateway does for EACH packet (spec section 4): copy the
    schedule's header template and stamp Epoch_Base = ceil(T_ingress / u)
    mod 2^32 for this packet's own ingress time (GPS, integer ns).

    The deltas are relative to Epoch_Base, so they need no change. Rounding
    the anchor UP can only add slack, never remove it.
    """
    template = proto.TcrhHeader.decode(entry['header_template'])
    epoch = proto.epoch_base_at_ingress(t_ingress_gps_ns, template.unit_code)
    return dataclasses.replace(template, epoch_base=epoch).encode()


# --------------------------------------------------------------- the schedule table

class ScheduleTable(dict):
    """
    dict  schedule_epoch_seconds -> { (src,dst): entry }, exactly as before,
    that also remembers its epochs in sorted order so schedule_for() can use
    a binary search: O(log n) per packet instead of a scan over every epoch.
    Every method that changes the keys forgets the sorted list.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._epochs = None

    def sorted_epochs(self):
        if getattr(self, '_epochs', None) is None:
            self._epochs = sorted(self.keys())
        return self._epochs

    def _forget(self):
        self._epochs = None

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._forget()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._forget()

    def __ior__(self, other):
        result = super().__ior__(other)
        self._forget()
        return result

    def clear(self):
        super().clear()
        self._forget()

    def pop(self, *args):
        result = super().pop(*args)
        self._forget()
        return result

    def popitem(self):
        result = super().popitem()
        self._forget()
        return result

    def setdefault(self, key, default=None):
        result = super().setdefault(key, default)
        self._forget()
        return result

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        self._forget()


def generate_schedules(times, sat_positions, gs_positions, flows,
                       slack_factor, interval_s=SCHEDULE_INTERVAL_S,
                       verbose=False, unit_code=DEFAULT_UNIT_CODE, graphs=None):
    """
    Build the full offline schedule table.

    unit_code : deadline unit of the headers (0 = 1 ms, v0-comparable;
                1 = 0.1 ms, the provisional v1 default)
    graphs    : optional, one prebuilt graph per entry of `times`. When given
                they are used instead of building the topology from the
                positions (tests use small hand-made graphs this way).

    Returns: ScheduleTable (a dict)  schedule_epoch_seconds -> { (src,dst): entry }
    """
    schedules = ScheduleTable()

    for i, t in enumerate(times):
        if t % interval_s != 0:
            continue

        if graphs is not None:
            graph = graphs[i]
        else:
            graph = build_graph(sat_positions[i], gs_positions[i])
        epoch_entries = {}

        for src, dst in flows:
            entry = build_schedule_entry(
                graph, src, dst, slack_factor, epoch_base_ms=t * 1000,
                unit_code=unit_code,
            )
            if entry is not None:
                epoch_entries[(src, dst)] = entry

        schedules[t] = epoch_entries

        if verbose:
            hops = [e['num_hops'] for e in epoch_entries.values()]
            avg = sum(hops) / len(hops) if hops else 0
            print(f"  schedule epoch t={t:4d}s : {len(epoch_entries)} flows, "
                  f"avg {avg:.1f} hops")

    return schedules


def schedule_for(schedules, t):
    """
    Which schedule applies to a packet sent at time t?

    The most recent epoch at or before t. This is where SCHEDULE STALENESS
    comes from: a packet sent at t=14 s uses the schedule computed at t=0,
    by which time every satellite has moved about 106 km.

    O(log n) on a ScheduleTable (what generate_schedules returns); a plain
    dict still works, with the old linear scan.
    """
    if isinstance(schedules, ScheduleTable):
        epochs = schedules.sorted_epochs()
        i = bisect.bisect_right(epochs, t) - 1
        if i < 0:
            return None, None
        return epochs[i], schedules[epochs[i]]
    valid = [e for e in schedules.keys() if e <= t]
    if not valid:
        return None, None
    epoch = max(valid)
    return epoch, schedules[epoch]


# --------------------------------------------------------------- control plane

def control_plane_bytes_tcrh(schedules, num_satellites):
    """
    Control-plane cost of ChronoRoute: schedules go only to the ground
    gateways that inject packets. Satellites receive nothing.
    """
    total = 0
    for entries in schedules.values():
        for e in entries.values():
            total += e['header_bytes']
    return total


def control_plane_bytes_table_upload(schedules, num_satellites,
                                     bytes_per_fib_entry=8,
                                     destinations=None):
    """
    Control-plane cost of the BASELINE (the FSA / Hypatia approach): a
    forwarding table is uploaded to EVERY satellite at every schedule epoch.

    Each satellite needs one FIB entry per destination it might have to reach.
    """
    if destinations is None:
        destinations = 6            # our six ground stations
    epochs = len(schedules)
    return epochs * num_satellites * destinations * bytes_per_fib_entry


if __name__ == '__main__':
    from constellation import build_constellation, propagate, ground_station_positions

    print("Building constellation and propagating...")
    sats = build_constellation()
    times, sp = propagate(sats, duration_s=60, step_s=1)
    gp = ground_station_positions(times)

    flows = [('GS:Chennai', 'GS:London'), ('GS:NewYork', 'GS:Sydney')]

    print("\nGenerating schedules (slack factor 1.3):")
    sch = generate_schedules(times, sp, gp, flows, slack_factor=1.3, verbose=True)

    e = sch[0][('GS:Chennai', 'GS:London')]
    print(f"\nChennai -> London at epoch t=0:")
    print(f"  path            : {e['path']}")
    print(f"  hops            : {e['num_hops']}")
    print(f"  predicted total : {e['total_predicted_ms']:.2f} ms")
    print(f"  per-hop predicted: {[round(x,2) for x in e['per_hop_predicted_ms']]}")
    print(f"  per-hop budget   : {[round(x,2) for x in e['deltas_ms']]}")
    print(f"  encoded deltas   : {list(e['deltas_u'])} (unit code {e['unit_code']})")
    print(f"  header size     : {e['header_bytes']} bytes")
    print(f"  delta overflow  : {e['delta_overflow']}")

    ep, entries = schedule_for(sch, 14)
    print(f"\nA packet sent at t=14s uses the schedule from epoch t={ep}s")
    print(f"  -> staleness = {14 - ep}s, during which satellites moved "
          f"{(14 - ep) * 7.59:.0f} km")

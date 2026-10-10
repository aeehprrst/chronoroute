"""
scheduler.py
------------
The ground station side: offline, ephemeris-driven schedule computation.

This is the part that replaces OSPF/BGP. Once every SCHEDULE_INTERVAL_S the
ground station:
    1. looks up where every satellite WILL be (from SGP4, no measurement)
    2. builds the graph for that instant
    3. runs Dijkstra for each flow
    4. writes a T-CRH with a deadline for every hop

The deadline for hop k is:   predicted_delay(k) * SLACK_FACTOR

SLACK_FACTOR is the single most important knob in the whole project. Too
tight and healthy packets get dropped as "expired". Too loose and a real
link failure goes undetected for a long time. Finding the best value is
Experiment 1.
"""

import networkx as nx

from constellation import GROUND_STATIONS
from topology import build_graph, PROCESSING_DELAY_MS
from header import encode, MAX_DELTA_MS, GS_SID_BASE

SCHEDULE_INTERVAL_S = 15     # how often ground stations recompute (Starlink-like)


def node_to_sid(node):
    """
    Map a graph node to its 16-bit segment ID.

      satellite 0..479  -> 0..479
      'GS:Chennai'      -> 0xF000 + 0, etc.
    """
    if isinstance(node, int):
        return node
    name = node.split(':', 1)[1]
    for i, (nm, _, _) in enumerate(GROUND_STATIONS):
        if nm == name:
            return GS_SID_BASE + i
    raise ValueError(f"unknown node {node}")


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


def build_schedule_entry(graph, src, dst, slack_factor, epoch_base_ms):
    """
    Produce one schedule entry: the path plus its per-hop deadline budget.

    Returns a dict, or None if no path exists.
    """
    path, total_predicted = compute_path(graph, src, dst)
    if path is None:
        return None

    # per-hop predicted delay, straight off the graph edges
    per_hop_predicted = []
    for a, b in zip(path[:-1], path[1:]):
        per_hop_predicted.append(graph[a][b]['weight'])

    # apply the slack factor to get each hop's budget
    deltas = []
    overflow = False
    for d in per_hop_predicted:
        budget = d * slack_factor
        if budget > MAX_DELTA_MS:
            overflow = True          # would not fit in our 1-byte delta field
        deltas.append(min(budget, MAX_DELTA_MS))

    # The T-CRH path vector lists every node AFTER the source, one segment ID
    # per link. Satellites use their own ID; ground stations get an ID from
    # the reserved high block (RFC 9631 SIDs are FIB indices, not addresses).
    sids = [node_to_sid(n) for n in path[1:]]
    assert len(sids) == len(deltas), "one segment ID per link budget"

    # encode a real header so we can report its true byte size
    raw = encode(sids, deltas, epoch_base_ms=epoch_base_ms)

    return {
        'src': src,
        'dst': dst,
        'path': path,
        'per_hop_predicted_ms': per_hop_predicted,
        'deltas_ms': deltas,
        'total_predicted_ms': total_predicted,
        'num_hops': len(path) - 1,
        'header_bytes': len(raw),
        'raw_header': raw,
        'delta_overflow': overflow,
        'epoch_base_ms': epoch_base_ms,
    }


def generate_schedules(times, sat_positions, gs_positions, flows,
                       slack_factor, interval_s=SCHEDULE_INTERVAL_S,
                       verbose=False):
    """
    Build the full offline schedule table.

    Returns: dict  schedule_epoch_seconds -> { (src,dst): entry }
    """
    step_s = times[1] - times[0] if len(times) > 1 else 1
    schedules = {}

    for i, t in enumerate(times):
        if t % interval_s != 0:
            continue

        graph = build_graph(sat_positions[i], gs_positions[i])
        epoch_entries = {}

        for src, dst in flows:
            entry = build_schedule_entry(
                graph, src, dst, slack_factor, epoch_base_ms=t * 1000
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
    """
    valid = [e for e in schedules.keys() if e <= t]
    if not valid:
        return None, None
    epoch = max(valid)
    return epoch, schedules[epoch]


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
    print(f"  per-hop deadline : {[round(x,2) for x in e['deltas_ms']]}")
    print(f"  header size     : {e['header_bytes']} bytes")
    print(f"  delta overflow  : {e['delta_overflow']}")

    ep, entries = schedule_for(sch, 14)
    print(f"\nA packet sent at t=14s uses the schedule from epoch t={ep}s")
    print(f"  -> staleness = {14 - ep}s, during which satellites moved "
          f"{(14 - ep) * 7.59:.0f} km")
"""
simulator.py
------------
The discrete-event packet simulator. This is where the protocol actually runs.

At every hop a satellite does exactly this:

    1. read my deadline out of the T-CRH
    2. is my clock past it?              -> set Deviation_Flag, go greedy
    3. is my next-hop link alive?        -> if not, set Deviation_Flag, go greedy
    4. otherwise forward. No routing table, no shortest-path computation.

The important honesty in this simulator is that the schedule and reality are
computed from DIFFERENT information:

    the DEADLINE   comes from the schedule (satellite positions at the last
                   schedule epoch -- possibly 15 seconds stale)
    the REAL DELAY comes from the satellites' actual positions right now,
                   plus a random queueing delay

That mismatch is exactly what the slack factor has to absorb.
"""

import heapq
import random
from enum import Enum

from constellation import (
    NUM_SATS, distance, propagation_delay_ms, GROUND_STATIONS,
)
from topology import build_graph, PROCESSING_DELAY_MS, gs_name
from header import decode, absolute_deadlines, FLAG_DEVIATION, FLAG_GREEDY_MODE
from scheduler import schedule_for

# ----- Simulator parameters -----
QUEUEING_MEAN_MS = 0.4       # mean random queueing delay per hop (exponential)
HOP_LIMIT = 40               # safety net, mirrors the IPv6 Hop Limit field


class Outcome(Enum):
    DROPPED_NO_FALLBACK = 'dropped_no_fallback'
    ON_SCHEDULE = 'delivered_on_schedule'
    VIA_FALLBACK = 'delivered_via_fallback'
    DROPPED_LOOP = 'dropped_loop'
    DROPPED_HOP_LIMIT = 'dropped_hop_limit'
    DROPPED_NO_NEIGHBOUR = 'dropped_no_neighbour'
    DROPPED_NO_SCHEDULE = 'dropped_no_schedule'


class Packet:
    """One packet in flight, carrying its own T-CRH."""

    __slots__ = ('pid', 'src', 'dst', 'send_time_ms', 'raw_header',
                 'sat_ids', 'deadlines', 'flags', 'hop_index', 'hops_taken',
                 'visited', 'deviation_hop', 'deviation_reason', 'hit_degraded')

    def __init__(self, pid, src, dst, send_time_ms, entry):
        self.pid = pid
        self.src = src
        self.dst = dst
        self.send_time_ms = send_time_ms
        self.raw_header = entry['raw_header']

        parsed = decode(self.raw_header)
        self.sat_ids = parsed['sat_ids']
        # Deadlines are anchored to when the packet is actually SENT, not to
        # the schedule epoch. The schedule gives the per-hop budget; the send
        # time gives the reference point.
        self.deadlines = absolute_deadlines(send_time_ms, parsed['deltas_ms'])

        self.flags = 0
        self.hop_index = 0          # how far along the path vector we are
        self.hops_taken = 0
        self.visited = set()
        self.deviation_hop = None
        self.deviation_reason = None
        self.hit_degraded = False

    @property
    def in_greedy_mode(self):
        return bool(self.flags & FLAG_GREEDY_MODE)

    def trigger_deviation(self, hop, reason):
        """Flip the Deviation_Flag and switch to geographic fallback."""
        if not (self.flags & FLAG_DEVIATION):
            self.flags |= FLAG_DEVIATION
            self.flags |= FLAG_GREEDY_MODE
            self.deviation_hop = hop
            self.deviation_reason = reason


def greedy_next_hop(graph, current, dst_pos, visited):
    """
    Geographic (greedy) forwarding -- our zero-state fallback.

    Forward to whichever live neighbour is physically closest to the
    destination. Needs no routing table: the satellite already knows its
    neighbours' positions from the ephemeris it must carry anyway.

    Returns the chosen neighbour, or None if we are stuck in a local minimum.
    """
    best, best_d = None, float('inf')
    for nb in graph.neighbors(current):
        if nb in visited:
            continue
        pos = graph.nodes[nb]['pos']
        d = distance(pos, dst_pos)
        if d < best_d:
            best_d, best = d, nb
    return best


def simulate_flow(times, graphs, sat_positions, gs_positions, schedules,
                  flow, num_packets, packet_interval_ms,
                  failed_links=None, degraded_links=None, rng=None,
                  strict_drop_on_expiry=False, disable_fallback=False):
    """
    Send num_packets along one flow and record what happened to each.

    Args:
        graphs        : list of pre-built graphs, one per timestep (the truth)
        failed_links   : set of frozenset({a,b}) links that are actually broken
        degraded_links : dict frozenset({a,b}) -> delay multiplier. The link is
                         still UP, so a link-state check cannot see the problem.
                         Only a missed deadline can. This models solar
                         interference, link-layer retransmission, congestion.
        strict_drop_on_expiry : if True, an expired packet is dropped instead
                                of falling back.
        disable_fallback : if True, ANY deviation drops the packet. This is the
                           "no fail-safe" baseline that shows why the
                           geographic fallback earns its place.

    Returns: list of result dicts
    """
    if rng is None:
        rng = random.Random(12345)
    if failed_links is None:
        failed_links = set()
    if degraded_links is None:
        degraded_links = {}

    src, dst = flow
    step_s = times[1] - times[0] if len(times) > 1 else 1
    results = []

    def graph_at(t_ms):
        """The real topology at time t (nearest simulation timestep)."""
        idx = int((t_ms / 1000.0) / step_s)
        return graphs[min(idx, len(graphs) - 1)]

    def dst_position(t_ms):
        idx = int((t_ms / 1000.0) / step_s)
        idx = min(idx, len(times) - 1)
        gi = [gs_name(i) for i in range(len(GROUND_STATIONS))].index(dst)
        return gs_positions[idx][gi]

    for k in range(num_packets):
        send_ms = k * packet_interval_ms
        send_s = send_ms / 1000.0
        if send_s > times[-1]:
            break

        epoch, entries = schedule_for(schedules, int(send_s))
        if entries is None or flow not in entries:
            results.append({'pid': k, 'outcome': Outcome.DROPPED_NO_SCHEDULE})
            continue

        entry = entries[flow]
        pkt = Packet(k, src, dst, send_ms, entry)
        planned_path = entry['path']

        # ---- walk the packet hop by hop ----
        current = src
        now_ms = send_ms
        pkt.visited.add(current)
        outcome = None

        while pkt.hops_taken < HOP_LIMIT:
            graph = graph_at(now_ms)

            if current == dst:
                outcome = (Outcome.VIA_FALLBACK if pkt.in_greedy_mode
                           else Outcome.ON_SCHEDULE)
                break

            # ---------- choose the next hop ----------
            if pkt.in_greedy_mode:
                nxt = greedy_next_hop(graph, current, dst_position(now_ms),
                                      pkt.visited)
                if nxt is None:
                    outcome = Outcome.DROPPED_NO_NEIGHBOUR
                    break
            else:
                # follow the T-CRH path vector
                step = pkt.hops_taken + 1
                if step < len(planned_path):
                    nxt = planned_path[step]
                else:
                    nxt = dst

                # STEP 2: deadline check -- the one comparison a satellite does.
                # pkt.deadlines[h] is the latest acceptable ARRIVAL time at the
                # node reached after h hops. We are at that node right now.
                if pkt.hops_taken < len(pkt.deadlines):
                    deadline = pkt.deadlines[pkt.hops_taken]
                    if now_ms > deadline:
                        if strict_drop_on_expiry:
                            outcome = Outcome.DROPPED_NO_NEIGHBOUR
                            break
                        if disable_fallback:
                            outcome = Outcome.DROPPED_NO_FALLBACK
                            break
                        pkt.trigger_deviation(pkt.hops_taken, 'deadline_missed')
                        continue        # re-decide this hop in greedy mode

                # STEP 3: is the link actually there?
                link_broken = (
                    not graph.has_edge(current, nxt)
                    or frozenset({current, nxt}) in failed_links
                )
                if link_broken:
                    if disable_fallback:
                        outcome = Outcome.DROPPED_NO_FALLBACK
                        break
                    pkt.trigger_deviation(pkt.hops_taken, 'link_failed')
                    continue

            # ---------- actually forward ----------
            if not graph.has_edge(current, nxt) or \
                    frozenset({current, nxt}) in failed_links:
                if disable_fallback:
                    outcome = Outcome.DROPPED_NO_FALLBACK
                    break
                pkt.trigger_deviation(pkt.hops_taken, 'link_failed')
                continue

            real_prop = graph[current][nxt]['weight']          # true delay now
            queueing = rng.expovariate(1.0 / QUEUEING_MEAN_MS)
            # a degraded link is still up, so only the deadline can catch it
            multiplier = degraded_links.get(frozenset({current, nxt}), 1.0)
            hop_delay = (real_prop + queueing) * multiplier
            now_ms += hop_delay
            if multiplier > 1.0:
                pkt.hit_degraded = True

            current = nxt
            pkt.visited.add(current)
            pkt.hops_taken += 1
            pkt.hop_index += 1
        else:
            outcome = Outcome.DROPPED_HOP_LIMIT

        if outcome is None:
            outcome = Outcome.DROPPED_HOP_LIMIT

        results.append({
            'pid': k,
            'outcome': outcome,
            'latency_ms': now_ms - send_ms,
            'predicted_ms': entry['total_predicted_ms'],
            'hops': pkt.hops_taken,
            'planned_hops': entry['num_hops'],
            'deviated': bool(pkt.flags & FLAG_DEVIATION),
            'deviation_reason': pkt.deviation_reason,
            'staleness_s': send_s - epoch,
            'hit_degraded': pkt.hit_degraded,
            'header_bytes': entry['header_bytes'],
        })

    return results


def summarise(results):
    """Turn a list of per-packet results into the numbers we plot."""
    n = len(results)
    if n == 0:
        return {}

    delivered = [r for r in results if r['outcome'] in
                 (Outcome.ON_SCHEDULE, Outcome.VIA_FALLBACK)]
    on_sched = [r for r in results if r['outcome'] == Outcome.ON_SCHEDULE]
    fallback = [r for r in results if r['outcome'] == Outcome.VIA_FALLBACK]
    deviated = [r for r in results if r.get('deviated')]

    lat = [r['latency_ms'] for r in delivered if 'latency_ms' in r]

    return {
        'total': n,
        'delivered': len(delivered),
        'delivery_rate': len(delivered) / n,
        'on_schedule': len(on_sched),
        'on_schedule_rate': len(on_sched) / n,
        'via_fallback': len(fallback),
        'deviation_rate': len(deviated) / n,
        'mean_latency_ms': sum(lat) / len(lat) if lat else 0.0,
        'mean_hops': (sum(r['hops'] for r in delivered) / len(delivered)
                      if delivered else 0.0),
    }


if __name__ == '__main__':
    from constellation import build_constellation, propagate, ground_station_positions
    from topology import build_all_graphs
    from scheduler import generate_schedules

    print("Setting up a 60-second run...")
    sats = build_constellation()
    times, sp = propagate(sats, duration_s=60, step_s=1)
    gp = ground_station_positions(times)
    graphs = build_all_graphs(times, sp, gp, verbose=False)

    flow = ('GS:Chennai', 'GS:London')

    for slack in (1.0, 1.1, 1.3, 2.0):
        sch = generate_schedules(times, sp, gp, [flow], slack_factor=slack)
        res = simulate_flow(times, graphs, sp, gp, sch, flow,
                            num_packets=500, packet_interval_ms=100,
                            rng=random.Random(1))
        s = summarise(res)
        print(f"slack={slack:<4} on-schedule={s['on_schedule_rate']*100:5.1f}%  "
              f"deviated={s['deviation_rate']*100:5.1f}%  "
              f"delivered={s['delivery_rate']*100:5.1f}%  "
              f"latency={s['mean_latency_ms']:.2f}ms  hops={s['mean_hops']:.1f}")
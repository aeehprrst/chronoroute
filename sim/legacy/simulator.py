"""
simulator.py
------------
The discrete-event packet simulator. This is where the protocol actually runs.

Every packet carries real T-CRH BYTES, and every forwarding decision is read
out of those bytes by the reference implementation
(chronoroute.proto.process_at_node, spec/tcrh-v1.md section 6). The planned
path in the schedule is only used by the gateway to BUILD the header. At
every segment endpoint the node does exactly this:

    1. read my deadline out of the T-CRH
    2. is my clock past it?              -> set Deviation_Flag, go greedy
    3. am I the final endpoint?          -> deliver (the check above has
                                            already run, so a late arrival
                                            at the destination is caught too)
    4. decrement Segments Left, read the next SID, look it up in the FIB
    5. is my next-hop link alive?        -> if not, set Deviation_Flag, go greedy
    6. otherwise forward. No routing table, no shortest-path computation.

The important honesty in this simulator is that the schedule and reality are
computed from DIFFERENT information:

    the DEADLINE   comes from the schedule (satellite positions at the last
                   schedule epoch -- possibly 15 seconds stale)
    the REAL DELAY comes from the satellites' actual positions right now,
                   plus a random queueing delay

That mismatch is exactly what the slack factor has to absorb.

TIME BASE. The simulator runs on a relative clock (seconds since the start
of the run). Simulation time 0 is the constellation epoch,
2026-09-10T00:00:00Z (constellation.EPOCH_*), the instant SGP4 propagation
starts from, so the GPS time of simulation time t is

    t_gps_ns = T0_GPS_NS + t_ns,   T0_GPS_NS = GPS time of that epoch

(GPS = UTC + 18 s, spec section 4). The gateway stamps Epoch_Base from the
packet's own ingress time, and every node's unit clock is
clock_u(t_gps_ns) = floor(t_gps_ns / u) mod 2^32. Simulated time is kept
in integer nanoseconds, so every deadline comparison is exact.

COMMON RANDOM NUMBERS. Every random draw (today: the queueing delay of each
hop) is a pure function of (seed, packet id, hop number), not the next value
of one shared stream. Two runs with the same seed, one with a degraded link
and one without, therefore give every packet identical draws until it
crosses the faulty link, and a packet that never crosses it behaves
identically in both. That is what lets the experiments score detection
counterfactually: a true detection is a packet flagged WITH the fault and
not flagged WITHOUT it (attributed_deviations).
"""

import bisect
import hashlib
import math
import random
from collections import Counter
from datetime import datetime, timezone
from enum import Enum

from constellation import (
    GROUND_STATIONS, distance, EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY,
)
from topology import gs_name
from scheduler import ingress_header, sid_to_node, ScheduleTable
from chronoroute import proto

# ----- Simulator parameters -----
QUEUEING_MEAN_MS = 0.4       # mean random queueing delay per hop (exponential)
HOP_LIMIT = 40               # safety net, mirrors the IPv6 Hop Limit field
DEFAULT_SEED = 12345         # used when neither seed nor rng is given (as in v0)

# ----- GPS time base (see TIME BASE above) -----
SIM_EPOCH_UTC = datetime(EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY, tzinfo=timezone.utc)
T0_GPS_NS = proto.utc_to_gps_ns(SIM_EPOCH_UTC)


class Outcome(Enum):
    DROPPED_NO_FALLBACK = 'dropped_no_fallback'
    ON_SCHEDULE = 'delivered_on_schedule'
    VIA_FALLBACK = 'delivered_via_fallback'
    DELIVERED_LATE = 'delivered_late'          # followed the plan but missed a deadline
    DROPPED_LOOP = 'dropped_loop'
    DROPPED_HOP_LIMIT = 'dropped_hop_limit'
    DROPPED_NO_NEIGHBOUR = 'dropped_no_neighbour'    # greedy local minimum
    DROPPED_NO_SCHEDULE = 'dropped_no_schedule'
    DROPPED_DEADLINE_STRICT = 'dropped_deadline_strict'   # late, policy 'drop'
    DROPPED_STUCK = 'dropped_stuck'            # forwarding stopped making progress


DELIVERED_OUTCOMES = (Outcome.ON_SCHEDULE, Outcome.VIA_FALLBACK, Outcome.DELIVERED_LATE)


# --------------------------------------------------------------- randomness

_CRN_PERSON = b'chronoroute-crn'     # domain separation for the hash
_TWO_POW_53 = float(1 << 53)


def crn_uniform(seed, packet_id, hop_index, stream=0):
    """
    A uniform number in (0, 1] that depends ONLY on its arguments.

    It is the top 53 bits of a BLAKE2b hash of (seed, packet id, hop number,
    stream), so it does not matter how many draws other packets made, or in
    which order: the same packet at the same hop always gets the same value.
    `stream` separates independent kinds of draw at the same hop.
    """
    msg = f"{seed}:{packet_id}:{hop_index}:{stream}".encode()
    x = int.from_bytes(hashlib.blake2b(msg, digest_size=8, person=_CRN_PERSON).digest(), 'big')
    return ((x >> 11) + 1) / _TWO_POW_53


def queueing_delay_ms(seed, packet_id, hop_index, mean_ms):
    """Exponential queueing delay with the given mean, from the keyed draw."""
    if mean_ms == 0:
        return 0.0
    return -mean_ms * math.log(crn_uniform(seed, packet_id, hop_index))


# --------------------------------------------------------------- forwarding helpers

def greedy_next_hop(graph, current, dst_pos, visited, failed_links=None):
    """
    Geographic (greedy) forwarding -- our zero-state fallback.

    Forward to whichever live neighbour is physically closest to the
    destination. Needs no routing table: the satellite already knows its
    neighbours' positions from the ephemeris it must carry anyway.

    A link listed in failed_links is skipped even if the graph still has the
    edge: a satellite knows that its own link is down (the same local check
    that sends a packet off its planned path). v0 did not skip it, kept
    choosing the dead link, and looped forever.

    Returns the chosen neighbour, or None if we are stuck in a local minimum.
    """
    best, best_d = None, float('inf')
    for nb in graph.neighbors(current):
        if nb in visited:
            continue
        if failed_links and frozenset((current, nb)) in failed_links:
            continue
        pos = graph.nodes[nb].get('pos')
        if pos is None:
            continue
        d = distance(pos, dst_pos)
        if d < best_d:
            best_d, best = d, nb
    return best


def _link_up(graph, a, b, failed_links):
    """Is the link a-b there right now and not broken?"""
    return graph.has_edge(a, b) and frozenset((a, b)) not in failed_links


def _switch_to_fallback(raw, hop_index):
    """
    The plan is broken at this node for a reason no deadline can show (the
    next link is down): spec section 6 step 7, done by the reference code
    (proto.link_down_fallback). It sets DEV (and Dev Hop = hop_index, unless
    an earlier node already flagged the packet), sets GREEDY, and addresses
    the packet to SID[0] (Segments Left 0). Only the mutable bytes change. At
    the ingress hop_index is 0: the spec defines DEV with Dev Hop 0 as "the
    ingress found its first link down" (section 2).
    """
    res = proto.link_down_fallback(raw)
    if res.action != 'fallback':
        raise RuntimeError(f"the simulator built a malformed T-CRH: {res.reason}")
    # the hop index the bytes imply must be the node we are at
    assert res.hop_index == hop_index, (res.hop_index, hop_index)
    return res.out_bytes


def _resolve_policy(deviation_policy, strict_drop_on_expiry, disable_fallback):
    """The node's deviation policy (spec section 6 step 4) from the old flags."""
    legacy = 'drop' if (strict_drop_on_expiry or disable_fallback) else None
    if deviation_policy is None:
        return legacy or 'greedy'
    if deviation_policy not in proto.POLICIES:
        raise ValueError(f"deviation_policy must be one of {proto.POLICIES}, "
                         f"got {deviation_policy!r}")
    if legacy is not None and deviation_policy != legacy:
        raise ValueError("strict_drop_on_expiry / disable_fallback mean policy 'drop'; "
                         f"they contradict deviation_policy={deviation_policy!r}")
    return deviation_policy


# --------------------------------------------------------------- the simulation

def simulate_flow(times, graphs, sat_positions, gs_positions, schedules,
                  flow, num_packets, packet_interval_ms,
                  failed_links=None, degraded_links=None, rng=None,
                  strict_drop_on_expiry=False, disable_fallback=False,
                  *, seed=None, t0_gps_ns=None, queueing_mean_ms=None,
                  hop_limit=None, deviation_policy=None):
    """
    Send num_packets along one flow and record what happened to each.

    Args:
        graphs        : list of pre-built graphs, one per timestep (the truth)
        sat_positions : unused, kept so old calls still work
        gs_positions  : only consulted when a destination node has no 'pos'
                        in the graph
        failed_links   : set of frozenset({a,b}) links that are actually broken
                         (the graphs may or may not still contain them)
        degraded_links : dict frozenset({a,b}) -> delay multiplier. The link is
                         still UP, so a link-state check cannot see the problem.
                         Only a missed deadline can. This models solar
                         interference, link-layer retransmission, congestion.
        rng            : a random.Random; only used to draw the seed (one
                         64-bit draw), so passing random.Random(1) to two runs
                         gives them common random numbers
        strict_drop_on_expiry : if True, an expired packet is dropped instead
                                of falling back (policy 'drop').
        disable_fallback : if True, ANY deviation drops the packet. This is the
                           "no fail-safe" baseline that shows why the
                           geographic fallback earns its place.

    Keyword-only (new):
        seed             : the common-random-numbers seed (instead of rng)
        t0_gps_ns        : GPS time of simulation time 0 (default T0_GPS_NS)
        queueing_mean_ms : mean exponential queueing delay per hop
                           (default QUEUEING_MEAN_MS; 0 = no jitter)
        hop_limit        : maximum transmissions per packet (default HOP_LIMIT)
        deviation_policy : 'greedy' (default), 'continue' (flag the packet
                           and keep following the SID list: detection only),
                           or 'drop' (same as strict_drop_on_expiry)

    The deadline unit is whatever the schedule's headers say (see
    scheduler.generate_schedules(unit_code=...)).

    Returns: list of per-packet result dicts, in packet-id order. Besides the
    v0 keys (pid, outcome, latency_ms, predicted_ms, hops, planned_hops,
    deviated, deviation_reason, staleness_s, hit_degraded, header_bytes)
    each has: send_ns, dev_hop (the header's Dev Hop: the hop index k at
    which DEV was set, 0 = the ingress), dev_node, path_taken (every node
    the packet was at, source first), arrival_ns (simulation time in ns at
    each of those nodes), epoch_base and unit_code (as stamped at ingress),
    header_in (the bytes the gateway built) and header_out (the bytes as
    delivered, or as received by the node that dropped the packet).
    """
    if seed is not None and rng is not None:
        raise ValueError("give either seed or rng, not both")
    if seed is None:
        seed = rng.getrandbits(64) if rng is not None else DEFAULT_SEED
    if t0_gps_ns is None:
        t0_gps_ns = T0_GPS_NS
    if queueing_mean_ms is None:
        queueing_mean_ms = QUEUEING_MEAN_MS
    if hop_limit is None:
        hop_limit = HOP_LIMIT
    failed_links = set(failed_links) if failed_links else set()
    if degraded_links is None:
        degraded_links = {}
    policy = _resolve_policy(deviation_policy, strict_drop_on_expiry, disable_fallback)

    src, dst = flow
    t_first_ns = proto.seconds_to_ns(times[0])
    t_last_ns = proto.seconds_to_ns(times[-1])
    step_ns = proto.seconds_to_ns(times[1] - times[0]) if len(times) > 1 else proto.NS_PER_S
    interval_ns = proto.ms_to_ns(packet_interval_ms)
    gs_index = {gs_name(i): i for i in range(len(GROUND_STATIONS))}

    # the schedule epochs, sorted once, so each packet's lookup is a binary search
    if isinstance(schedules, ScheduleTable):
        epochs = schedules.sorted_epochs()
    else:
        epochs = sorted(schedules)
    epochs_ns = [proto.seconds_to_ns(e) for e in epochs]

    def step_index(t_ns):
        idx = (t_ns - t_first_ns) // step_ns
        return max(0, min(idx, len(graphs) - 1))

    def graph_at(t_ns):
        """The real topology at time t (the simulation step it falls in)."""
        return graphs[step_index(t_ns)]

    def position_of(node, graph, t_ns):
        pos = graph.nodes[node].get('pos') if node in graph else None
        if pos is None and gs_positions is not None and node in gs_index:
            idx = min(step_index(t_ns), len(gs_positions) - 1)
            pos = gs_positions[idx][gs_index[node]]
        if pos is None:
            raise KeyError(f"greedy forwarding needs a position for {node!r}")
        return pos

    results = []

    for k in range(num_packets):
        send_ns = k * interval_ns
        if send_ns > t_last_ns:
            break
        send_s = send_ns / 1e9

        i = bisect.bisect_right(epochs_ns, send_ns) - 1
        epoch = epochs[i] if i >= 0 else None
        entry = schedules[epoch].get(flow) if i >= 0 else None
        if entry is None:
            results.append({
                'pid': k, 'outcome': Outcome.DROPPED_NO_SCHEDULE, 'send_ns': send_ns,
                'latency_ms': 0.0, 'predicted_ms': None, 'hops': 0, 'planned_hops': None,
                'deviated': False, 'deviation_reason': None, 'dev_hop': None,
                'dev_node': None, 'path_taken': [src], 'arrival_ns': [send_ns],
                'staleness_s': None if epoch is None else send_s - epoch,
                'hit_degraded': False, 'header_bytes': None, 'epoch_base': None,
                'unit_code': None, 'header_in': None, 'header_out': None,
            })
            continue

        # ---- ingress: the gateway stamps THIS packet's Epoch_Base ----
        header_in = ingress_header(entry, t0_gps_ns + send_ns)
        hdr_in = proto.TcrhHeader.decode(header_in)
        unit_code = hdr_in.unit_code
        raw, first_sid = proto.ingress_send(header_in)   # SL = h - 1, next = s_1

        current = src
        target = sid_to_node(first_sid)   # the node the Destination Address names
        greedy = False
        hop_index = 0                     # k of the node holding the packet (0 = ingress)
        now_ns = send_ns
        hops = 0
        visited = {src}
        path_taken = [src]
        arrival_ns = [send_ns]
        reason = dev_node = dev_hop = None
        hit_degraded = False
        outcome = None

        # Every pass through this loop either transmits once (at most
        # hop_limit times), switches the packet to fallback forwarding (at
        # most once: a packet never leaves greedy mode), or ends the packet.
        # So it always terminates; the iteration cap only guards that
        # argument against future edits.
        iterations = 0
        while outcome is None:
            iterations += 1
            if iterations > 2 * hop_limit + 2:
                outcome = Outcome.DROPPED_STUCK
                break
            if hops >= hop_limit:
                outcome = Outcome.DROPPED_HOP_LIMIT
                break
            graph = graph_at(now_ns)

            # ---------- choose the next hop ----------
            if greedy:
                nxt = greedy_next_hop(graph, current, position_of(target, graph, now_ns),
                                      visited, failed_links)
                if nxt is None:
                    outcome = Outcome.DROPPED_NO_NEIGHBOUR
                    break
            else:
                # the FIB gave us the next segment endpoint; is the link there?
                nxt = target
                if not _link_up(graph, current, nxt, failed_links):
                    if disable_fallback:
                        outcome = Outcome.DROPPED_NO_FALLBACK
                        break
                    if reason is None:
                        reason, dev_node, dev_hop = 'link_failed', current, hop_index
                    raw = _switch_to_fallback(raw, hop_index)
                    target = sid_to_node(proto.TcrhHeader.decode(raw).sids_rev[0])
                    greedy = True
                    continue        # re-decide this hop in greedy mode

            if not _link_up(graph, current, nxt, failed_links):
                # nothing can be sent and nothing changed: no progress
                outcome = Outcome.DROPPED_STUCK
                break

            # ---------- actually forward ----------
            real_prop = graph[current][nxt]['weight']          # true delay now
            queueing = queueing_delay_ms(seed, k, hops, queueing_mean_ms)
            # a degraded link is still up, so only the deadline can catch it
            multiplier = degraded_links.get(frozenset((current, nxt)), 1.0)
            if multiplier > 1.0:
                hit_degraded = True
            now_ns += proto.ms_to_ns((real_prop + queueing) * multiplier)

            current = nxt
            hops += 1
            visited.add(current)
            path_taken.append(current)
            arrival_ns.append(now_ns)

            # ---------- arrival ----------
            if greedy and current != target:
                # a satellite in the middle of a fallback detour: the packet
                # is addressed to SID[0], so it just uses the fallback function
                continue

            # this node is named in the Destination Address: run spec section 6
            now_u = proto.clock_u(t0_gps_ns + now_ns, unit_code)
            res = proto.process_at_node(raw, now_u, policy)
            if res.action == 'drop_malformed':
                raise RuntimeError(f"the simulator built a malformed T-CRH: {res.reason}")
            hop_index = res.hop_index
            if res.late:
                reason, dev_node, dev_hop = 'deadline_missed', current, res.hop_index

            if res.action == 'deliver':
                raw = res.out_bytes
                if greedy:
                    outcome = Outcome.VIA_FALLBACK
                elif raw[proto.OFF_FLAGS] & proto.FLAG_DEV:
                    outcome = Outcome.DELIVERED_LATE
                else:
                    outcome = Outcome.ON_SCHEDULE
            elif res.action == 'forward':
                raw = res.out_bytes
                target = sid_to_node(res.next_sid)
            elif res.action == 'fallback':
                raw = res.out_bytes
                target = sid_to_node(res.next_sid)
                greedy = True
            else:                                   # 'drop_late'
                outcome = (Outcome.DROPPED_NO_FALLBACK if disable_fallback
                           else Outcome.DROPPED_DEADLINE_STRICT)

        results.append({
            'pid': k,
            'outcome': outcome,
            'send_ns': send_ns,
            'latency_ms': (now_ns - send_ns) / 1e6,
            'predicted_ms': entry['total_predicted_ms'],
            'hops': hops,
            'planned_hops': hdr_in.num_hops,
            'deviated': reason is not None,
            'deviation_reason': reason,
            'dev_hop': dev_hop,
            'dev_node': dev_node,
            'path_taken': path_taken,
            'arrival_ns': arrival_ns,
            'staleness_s': send_s - epoch,
            'hit_degraded': hit_degraded,
            'header_bytes': len(header_in),
            'epoch_base': hdr_in.epoch_base,
            'unit_code': unit_code,
            'header_in': header_in,
            'header_out': raw,
        })

    return results


# --------------------------------------------------------------- results

def pair_runs(base, faulty):
    """Match two runs of the same flow packet by packet: [(base_rec, faulty_rec)]."""
    by_pid = {r['pid']: r for r in faulty}
    return [(b, by_pid[b['pid']]) for b in base if b['pid'] in by_pid]


def attributed_deviations(base, faulty):
    """
    Counterfactual attribution.

    base and faulty are two runs with the SAME seed, the second with the
    fault injected. Returns the ids of the packets flagged (DEV set) in the
    faulty run and NOT in the base run: the flags the fault caused. A packet
    late because of queueing jitter is late in both runs and is not counted,
    and with no fault (or a phantom fault, multiplier 1.0) the list is empty
    by construction.
    """
    return [b['pid'] for b, f in pair_runs(base, faulty)
            if f.get('deviated') and not b.get('deviated')]


def summarise(results):
    """Turn a list of per-packet results into the numbers we plot."""
    n = len(results)
    if n == 0:
        return {}

    delivered = [r for r in results if r['outcome'] in DELIVERED_OUTCOMES]
    on_sched = [r for r in results if r['outcome'] == Outcome.ON_SCHEDULE]
    fallback = [r for r in results if r['outcome'] == Outcome.VIA_FALLBACK]
    late = [r for r in results if r['outcome'] == Outcome.DELIVERED_LATE]
    deviated = [r for r in results if r.get('deviated')]

    lat = [r['latency_ms'] for r in delivered if 'latency_ms' in r]

    return {
        'total': n,
        'delivered': len(delivered),
        'delivery_rate': len(delivered) / n,
        'on_schedule': len(on_sched),
        'on_schedule_rate': len(on_sched) / n,
        'via_fallback': len(fallback),
        'delivered_late': len(late),
        'deviation_rate': len(deviated) / n,
        'mean_latency_ms': sum(lat) / len(lat) if lat else 0.0,
        'mean_hops': (sum(r['hops'] for r in delivered) / len(delivered)
                      if delivered else 0.0),
        'outcomes': dict(Counter(r['outcome'].value for r in results)),
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

    for unit_code in (0, 1):
        print(f"\ndeadline unit code {unit_code} "
              f"({proto.UNIT_NS[unit_code] / 1e6:g} ms)")
        for slack in (1.0, 1.1, 1.3, 2.0):
            sch = generate_schedules(times, sp, gp, [flow], slack_factor=slack,
                                     unit_code=unit_code)
            res = simulate_flow(times, graphs, sp, gp, sch, flow,
                                num_packets=500, packet_interval_ms=100,
                                rng=random.Random(1))
            s = summarise(res)
            print(f"slack={slack:<4} on-schedule={s['on_schedule_rate']*100:5.1f}%  "
                  f"deviated={s['deviation_rate']*100:5.1f}%  "
                  f"delivered={s['delivery_rate']*100:5.1f}%  "
                  f"latency={s['mean_latency_ms']:.2f}ms  hops={s['mean_hops']:.1f}")

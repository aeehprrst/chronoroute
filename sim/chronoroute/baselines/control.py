"""
control.py
----------
Counting control-plane bytes (master plan 5.3 "Control bytes", reviewer
must-fix #3): every message a scheme's control plane sends is counted, per
MEDIUM and per message type, and kept apart from the per-packet header bytes
and from the state a satellite must hold.

Media (the plan's three, plus the downlink, which is a fourth physical medium
and is not hidden inside another one):

    uplink     ground -> satellite (the scarce one: SNAP tables, state uploads)
    isl        satellite <-> satellite (hellos, BFD, LSA floods, delay probes,
               feedback reports relayed towards the ground)
    downlink   satellite -> ground (telemetry, feedback reports, LS messages on
               a ground link in that direction)
    ground     ground-internal network (schedules to gateways, E2E reports
               from a destination station to the planner)

Message sizes (bytes on the wire, IPv6 header included, link-layer framing
excluded). Packet layouts were counted from the RFC figures on 2026-10-11:

    IPv6 header                       40        RFC 8200 section 3
    UDP header                         8        RFC 768
    OSPFv3 packet header              16        RFC 5340 appendix A.3.1
    OSPFv3 Hello body, 1 neighbour    24        RFC 5340 A.3.2
    Link State Update fixed part       4        RFC 5340 A.3.5 (# LSAs)
    LSA header                        20        RFC 5340 A.4.2 (an LSAck lists LSA headers, A.3.6)
    Router-LSA: fixed 4 + 16 per link           RFC 5340 A.4.3
    BFD control packet                24        RFC 5880 sections 4.1, 6.8.7 (in UDP, RFC 5881)
    Delay sub-TLV 8, min/max sub-TLV 12         RFC 7471 sections 4.1, 4.2 (4-byte TLV header)
    STAMP test packet                 44        RFC 8762 section 4.2.1 (unauthenticated)

So: hello = 40 + 16 + 24 = 80; BFD = 40 + 8 + 24 = 72; one LSU carrying one
router-LSA of a node with d links = 40 + 16 + 4 + 20 + 4 + 16 d; one LSAck =
40 + 16 + 20 = 76; a TE LSA with one link and the delay sub-TLV = LSU
header + 20 + TLV header 4 + link-type 8 + link-id 8 + 8 (or 12 for min/max);
one STAMP probe and its reflection = 2 x (40 + 8 + 44). The byte model is
OSPFv3-like for every LS preset (an OLSR network would flood TC messages
with MPR selection and send fewer copies) and is checked by an analytic
unit test (reviewer must-fix #7: no cross-protocol "calibration").
"""

IPV6 = 40
UDP = 8
OSPF3_HEADER = 16
OSPF3_HELLO_BODY = 24
LSU_FIXED = 4
LSA_HEADER = 20
ROUTER_LSA_FIXED = 4
ROUTER_LSA_PER_LINK = 16
BFD_CONTROL = 24
DELAY_SUBTLV = 8
MINMAX_SUBTLV = 12
TE_TLV_HEADER = 4
TE_LINK_TYPE_SUBTLV = 8
TE_LINK_ID_SUBTLV = 8
STAMP_TEST = 44

HELLO_BYTES = IPV6 + OSPF3_HEADER + OSPF3_HELLO_BODY                       # 80
BFD_BYTES = IPV6 + UDP + BFD_CONTROL                                        # 72
LSACK_BYTES = IPV6 + OSPF3_HEADER + LSA_HEADER                              # 76
STAMP_PROBE_BYTES = 2 * (IPV6 + UDP + STAMP_TEST)                           # 184 (probe + reflection)

MEDIA = ("uplink", "isl", "downlink", "ground")


def router_lsu_bytes(degree):
    """One Link State Update carrying the router-LSA of a node with `degree` links."""
    return IPV6 + OSPF3_HEADER + LSU_FIXED + LSA_HEADER + ROUTER_LSA_FIXED + ROUTER_LSA_PER_LINK * degree


def te_lsu_bytes(minmax=False):
    """One Link State Update carrying a TE LSA with one link and its delay sub-TLV."""
    sub = MINMAX_SUBTLV if minmax else DELAY_SUBTLV
    return (IPV6 + OSPF3_HEADER + LSU_FIXED + LSA_HEADER + TE_TLV_HEADER + TE_LINK_TYPE_SUBTLV
            + TE_LINK_ID_SUBTLV + sub)


def flood_transmissions(degrees):
    """Copies of one flooded LSA: the origin sends on all its links, every other reached
    node on all its links but the one it first heard the LSA on.

    degrees: up-degree of every node the flood reaches (origin included). For a
    connected graph with E links this is 2E - (N - 1): each link carries it once in
    each direction except the N - 1 links of the flooding tree, which carry it once.
    """
    if not degrees:
        return 0
    return sum(degrees) - (len(degrees) - 1)


class Ledger:
    """Control bytes and message counts, per medium and per message type."""

    def __init__(self):
        self.by_type = {}

    def add(self, medium, msg_type, n_bytes, count=1):
        if medium not in MEDIA:
            raise ValueError(f"medium must be one of {MEDIA}, got {medium!r}")
        if n_bytes < 0 or count < 0:
            raise ValueError("bytes and counts are never negative")
        rec = self.by_type.setdefault((medium, msg_type), [0, 0])
        rec[0] += int(count)
        rec[1] += int(n_bytes)

    def total(self, medium=None):
        return sum(v[1] for (m, _t), v in self.by_type.items() if medium is None or m == medium)

    def to_dict(self):
        by_medium = {m: {"messages": 0, "bytes": 0} for m in MEDIA}
        types = []
        for (m, t), (c, b) in sorted(self.by_type.items()):
            by_medium[m]["messages"] += c
            by_medium[m]["bytes"] += b
            types.append({"medium": m, "type": t, "messages": c, "bytes": b})
        return {"by_medium": by_medium, "by_type": types, "total_bytes": self.total()}


__all__ = ["IPV6", "UDP", "HELLO_BYTES", "BFD_BYTES", "LSACK_BYTES", "STAMP_PROBE_BYTES", "MEDIA",
           "router_lsu_bytes", "te_lsu_bytes", "flood_transmissions", "Ledger"]

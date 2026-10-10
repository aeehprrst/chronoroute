"""
header.py
---------
The Temporal Compact Routing Header (T-CRH) -- our contribution.

T-CRH = RFC 9631 Compact Routing Header (CRH-16)  +  a per-hop time deadline.

We encode it into real bytes rather than just holding a Python object, because
the whole overhead argument in the report depends on exact byte counts.

Since P1 this module is a thin legacy wrapper: the bytes are produced and
parsed by the reference implementation, chronoroute.proto, which follows the
normative spec/tcrh-v1.md. Keeping one implementation is what makes the
Python simulator wire-compatible with ns-3 (the v0 code wrote the SIDs in
forward order and never touched Segments Left, so it was not).

Wire format v1 (Routing Type 253, reserved by IANA for experimentation):

     0               1               2               3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +---------------+---------------+---------------+---------------+
    |  Next Header  |  Hdr Ext Len  | Rtg Type =253 | Segments Left |
    +---------------+---------------+---------------+---------------+
    |     Flags     |   Num Hops    |    Dev Hop    |   Reserved    |
    +---------------+---------------+---------------+---------------+
    |            Epoch_Base (GPS time, in deadline units)           |
    +---------------------------------------------------------------+
    |   SID[0] (16 bits)            | Delta[0] (8) |  SID[1] hi ... |
    +---------------------------------------------------------------+
    |                        ... 3 bytes per hop ...                |
    +---------------------------------------------------------------+
                        (zero-padded to an 8-byte boundary)

Per-hop entry = 2-byte segment ID + 1-byte delta deadline. Entries are stored
in REVERSE path order, as in RFC 9631: SID[0] is the final endpoint, so a node
decrements Segments Left and then reads SID[Segments Left].

The deltas are counts of the deadline unit u chosen by the UNIT bits of the
Flags byte: unit code 0 = 1 ms (what v0 used, and still the default here so
old results stay comparable), 1 = 0.1 ms, 2 = 0.25 ms, 3 = 0.125 ms.

WHY a 1-byte delta rather than an absolute timestamp?
    An absolute 32-bit timestamp per hop would cost 6 bytes per hop instead
    of 3. A 1-byte delta caps the per-hop budget at 255 units (255 ms at
    1 ms, 25.5 ms at 0.1 ms), but a real inter-satellite hop needs a few ms.
    So we halve the cost of the path vector in exchange for a limit we do
    not reach. If a budget ever does not fit, the delta is clamped to 255
    and the SAT flag says so.

WHY ceil-cumulative deltas (spec 5.1) instead of rounding each hop?
    v0 rounded every per-hop budget with Python's round() (banker's
    rounding), so a 2.5 ms budget became 2 ms: a deadline EARLIER than the
    time the hop needs, which turns healthy packets into false alarms. Now
    each cumulative budget is rounded UP to the unit, exactly (integer
    nanoseconds), and the deltas are the differences. No deadline is ever
    below its budget, and the rounding error never accumulates.
"""

from fractions import Fraction

from chronoroute import proto
from chronoroute.proto import (                      # noqa: F401  (re-exported)
    TcrhHeader, encode_deltas, epoch_base_at_ingress, ms_to_ns, unit_ns,
    clock_u, serial_diff, is_late, NS_PER_MS,
)

# ----- Header constants -----
ROUTING_TYPE_TCRH = proto.ROUTING_TYPE_TCRH   # 253, IANA-reserved for experimentation
FIXED_BYTES = 8              # NextHdr, HdrExtLen, RtgType, SegLeft, Flags, NumHops, DevHop, Reserved
EPOCH_BYTES = 4              # Epoch_Base
BYTES_PER_HOP = proto.TCRH_ENTRY_BYTES        # 2-byte SID + 1-byte delta deadline
MAX_DELTA = proto.MAX_DELTA                   # what fits in one byte, in deadline units
MAX_DELTA_MS = MAX_DELTA     # v0 name: 255 units = 255 ms at the default unit code 0
DEFAULT_UNIT_CODE = 0        # 1 ms: v0-comparable. Experiments also run unit code 1 (0.1 ms)

# Segment IDs are FIB indices, not literally satellite numbers (RFC 9631 says
# a CRH SID "identifies an entry in the CRH Forwarding Information Base").
# So we can give ground stations IDs too, from a reserved high block.
GS_SID_BASE = proto.SID_GROUND_BASE           # ground station g -> 0xF000 + g

# ----- Flag bits (spec section 3) -----
FLAG_DEVIATION = proto.FLAG_DEV      # set by the first node that finds the plan broken
FLAG_GREEDY_MODE = proto.FLAG_GREEDY  # packet is now in geographic-fallback forwarding
FLAG_SAT = proto.FLAG_SAT            # a delta had to be clamped to 255 when encoding
FLAG_UNIT_MASK = proto.FLAG_UNIT_MASK

# ----- Comparison constants (for the overhead experiment) -----
IPV6_BASE_HEADER = proto.IPV6_HEADER_BYTES    # fixed IPv6 header, 40 bytes
SRH_FIXED = proto.SRH_FIXED_BYTES             # RFC 8754 SRH fixed portion
SRH_BYTES_PER_SEGMENT = proto.SRH_SEGMENT_BYTES   # a full 128-bit IPv6 address per segment
# RFC 9631's figure has a 4-octet fixed part (Next Header, Hdr Ext Len,
# Routing Type, Segments Left) before the SIDs. v0 had 8 here, which made
# every CRH-16 bar in Experiments 2 and 6 one 8-byte unit too tall.
CRH16_FIXED = proto.CRH_FIXED_BYTES           # 4
CRH16_BYTES_PER_SID = proto.CRH16_SID_BYTES   # 16-bit segment ID
HMAC_TLV_BYTES = 40          # SRv6-style HMAC TLV, for the security trade-off


def pad_to_8(n):
    """IPv6 extension headers must be a whole number of 8-byte units."""
    return proto.pad8(n)


# --------------------------------------------------------------- size functions

def tcrh_size(num_hops):
    """On-the-wire size of a T-CRH carrying num_hops entries: pad8(12 + 3n)."""
    return proto.tcrh_size(num_hops)


def crh16_size(num_hops):
    """RFC 9631 CRH-16 with the same number of segments (no time info): pad8(4 + 2n)."""
    return proto.crh16_size(num_hops)


def srh_size(num_hops):
    """RFC 8754 SRv6 SRH with the same number of segments: 8 + 16n."""
    return proto.srh_size(num_hops)


def tcrh_size_authenticated(num_hops):
    """T-CRH plus an HMAC TLV -- the security/compactness trade-off."""
    return pad_to_8(FIXED_BYTES + EPOCH_BYTES
                    + num_hops * BYTES_PER_HOP + HMAC_TLV_BYTES)


# --------------------------------------------------------------- encode / decode

def _units_to_ms(units, unit_code):
    """A count of deadline units as milliseconds (an int whenever it is exact)."""
    ms = Fraction(units * unit_ns(unit_code), NS_PER_MS)
    return ms.numerator if ms.denominator == 1 else float(ms)


def encode(path_sat_ids, deltas_ms, epoch_base_ms, flags=0, next_header=6,
           unit_code=DEFAULT_UNIT_CODE):
    """
    Build the real header bytes.

    Args:
        path_sat_ids  : segment IDs in FORWARD (path) order: first hop first,
                        final endpoint last. They go on the wire reversed.
        deltas_ms     : per-hop time budgets in ms (same length), floats OK.
                        They are summed into cumulative budgets in exact
                        integer nanoseconds and encoded ceil-cumulative
                        (spec 5.1); a delta over 255 units is clamped and
                        sets the SAT flag.
        epoch_base_ms : the ingress time, GPS milliseconds. Stored as
                        Epoch_Base = ceil(time / u) mod 2^32; at the default
                        unit code 0 that is just the millisecond count.
        flags         : extra flag bits: DEV / GREEDY (and SAT). The UNIT
                        bits come from unit_code.
        next_header   : IPv6 Next Header value (6 = TCP)
        unit_code     : deadline unit, 0..3 (0 = 1 ms, v0-compatible)

    Returns: bytes
    """
    sids = list(path_sat_ids)
    budgets = list(deltas_ms)
    if len(sids) != len(budgets):
        raise ValueError("path and deltas must be the same length")
    if flags & FLAG_UNIT_MASK and (flags & FLAG_UNIT_MASK) >> 4 != unit_code:
        raise ValueError("the UNIT bits in flags disagree with unit_code")

    # per-hop budgets -> cumulative budgets from ingress, in exact integer ns
    cumulative_ns, running = [], 0
    for d in budgets:
        d_ns = ms_to_ns(d)
        if d_ns < 0:
            raise ValueError(f"a hop budget cannot be negative, got {d} ms")
        running += d_ns
        cumulative_ns.append(running)

    deltas, sat = encode_deltas(cumulative_ns, unit_code)
    epoch = epoch_base_at_ingress(ms_to_ns(epoch_base_ms), unit_code)
    extra = (flags & ~FLAG_UNIT_MASK) | (FLAG_SAT if sat else 0)
    hdr = TcrhHeader.from_forward(sids, deltas, epoch, unit_code,
                                  next_header=next_header, extra_flags=extra)
    return hdr.encode()


def decode(raw):
    """
    Parse T-CRH bytes back into a dict. The mirror of encode().

    'sat_ids' and 'deltas_ms' are in PATH order (as encode() takes them);
    'sids_wire' / 'deltas_wire' are the reversed order the bytes use.
    """
    hdr, nbytes = TcrhHeader.decode_prefix(raw)
    uc = hdr.unit_code
    return {
        'next_header': hdr.next_header,
        'hdr_ext_len': hdr.hdr_ext_len,
        'segments_left': hdr.segments_left,
        'flags': hdr.flags,
        'num_hops': hdr.num_hops,
        'dev_hop': hdr.dev_hop,
        'unit_code': uc,
        'epoch_base': hdr.epoch_base,                     # deadline units
        'epoch_base_ms': _units_to_ms(hdr.epoch_base, uc),
        'sat_ids': list(hdr.sids_fwd),
        'deltas': list(hdr.deltas_fwd),                   # deadline units
        'deltas_ms': [_units_to_ms(d, uc) for d in hdr.deltas_fwd],
        'sids_wire': list(hdr.sids_rev),
        'deltas_wire': list(hdr.deltas_rev),
        'deadlines_u': list(hdr.deadlines()),             # D_1..D_h, mod 2^32
        'size_bytes': nbytes,
    }


def absolute_deadlines(epoch_base_ms, deltas_ms):
    """
    Turn the per-hop deltas into ARRIVAL deadlines.

    deltas_ms[k] is the time budget for link k (from node k to node k+1).
    So the latest acceptable ARRIVAL time at node k is the epoch plus the
    budgets of all the links BEFORE it:

        arrival_deadline[0] = epoch                      (at the source)
        arrival_deadline[1] = epoch + deltas[0]
        arrival_deadline[2] = epoch + deltas[0] + deltas[1]
        ...

    Returned list has len(deltas_ms) + 1 entries.

    Deadlines are CUMULATIVE, which matters: a packet held up at one hop can
    still make the time back at a later, faster hop instead of being
    condemned by one bad hop.

    This is plain arithmetic for printing and plotting. On the wire the
    deadlines live mod 2^32 (TcrhHeader.deadlines()) and a node compares
    them with is_late(), which is wrap-safe.
    """
    out = [epoch_base_ms]
    running = epoch_base_ms
    for d in deltas_ms:
        running += d
        out.append(running)
    return out


if __name__ == '__main__':
    print("=== T-CRH self-test ===\n")

    path = [368, 367, 366, 365, 345, 120, 121, 122, 199, 200]
    deltas = [7, 8, 8, 7, 9, 6, 7, 8, 8, 7]

    raw = encode(path, deltas, epoch_base_ms=1_000_000)
    print(f"Encoded 10-hop T-CRH: {len(raw)} bytes")
    print(f"Hex: {raw.hex()}\n")

    back = decode(raw)
    assert back['sat_ids'] == path, "sat IDs did not round-trip"
    assert back['deltas_ms'] == deltas, "deltas did not round-trip"
    assert back['num_hops'] == 10
    assert back['sids_wire'] == path[::-1], "SIDs must be on the wire in reverse order"
    print("Round-trip decode: PASS")
    print(f"  segments_left = {back['segments_left']}")
    print(f"  epoch_base_ms = {back['epoch_base_ms']}")

    dl = absolute_deadlines(back['epoch_base_ms'], back['deltas_ms'])
    print(f"  absolute deadlines = {dl}\n")

    golden = encode([2, 3, 7], [6, 7, 8], 1000, next_header=17)
    assert golden.hex() == '1102fd0300030000000003e8000708000307000206000000'
    print("Golden vector v0-3hop (spec section 10, same bytes as ns-3): PASS\n")

    print("=== Header size comparison (this is Experiment 2) ===")
    print(f"{'hops':>5} {'SRv6 SRH':>10} {'CRH-16':>8} {'T-CRH':>8} "
          f"{'T-CRH+HMAC':>11} {'time cost':>10}")
    for h in (3, 5, 10, 15):
        s, c, t, ta = srh_size(h), crh16_size(h), tcrh_size(h), tcrh_size_authenticated(h)
        print(f"{h:>5} {s:>10} {c:>8} {t:>8} {ta:>11} {t - c:>+10}")

    print("\nSanity check against the spec (spec/tcrh-v1.md section 9):")
    print(f"  10-hop SRv6 SRH = {srh_size(10)} bytes  (8 + 16n = 168)")
    print(f"  10-hop CRH-16   = {crh16_size(10)} bytes  (RFC 9631: pad8(4 + 2n) = 24)")
    print(f"  10-hop T-CRH    = {tcrh_size(10)} bytes  (pad8(12 + 3n) = 48)")

"""
header.py
---------
The Temporal Compact Routing Header (T-CRH) -- our contribution.

T-CRH = RFC 9631 Compact Routing Header (CRH-16)  +  a per-hop time deadline.

We encode it into real bytes rather than just holding a Python object, because
the whole overhead argument in the report depends on exact byte counts.

Wire format (Routing Type 253, reserved by IANA for experimentation):

     0               1               2               3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +---------------+---------------+---------------+---------------+
    |  Next Header  |  Hdr Ext Len  | Rtg Type =253 | Segments Left |
    +---------------+---------------+---------------+---------------+
    |     Flags     |   Num Hops    |           Reserved            |
    +---------------+---------------+-------------------------------+
    |                    Epoch_Base (GPS milliseconds)              |
    +---------------------------------------------------------------+
    |   Sat_ID[0] (16 bits)         | Delta[0] (8) | Sat_ID[1] hi.. |
    +---------------------------------------------------------------+
    |                        ... 3 bytes per hop ...                |
    +---------------------------------------------------------------+
                        (zero-padded to an 8-byte boundary)

Per-hop entry = 2-byte satellite ID + 1-byte delta deadline (milliseconds
since the previous hop's deadline). 3 bytes per hop.

WHY a 1-byte delta rather than an absolute timestamp?
    An absolute 32-bit timestamp per hop would cost 6 bytes per hop instead
    of 3. A 1-byte delta caps the per-hop budget at 255 ms, but a real
    inter-satellite hop needs 5-25 ms. So we halve the cost of the path
    vector in exchange for a limit we will never reach.
"""

import struct

# ----- Header constants -----
ROUTING_TYPE_TCRH = 253      # IANA-reserved for experimentation
FIXED_BYTES = 8              # NextHdr, HdrExtLen, RtgType, SegLeft, Flags, NumHops, Reserved(2)
EPOCH_BYTES = 4              # Epoch_Base
BYTES_PER_HOP = 3            # 2-byte sat ID + 1-byte delta deadline
MAX_DELTA_MS = 255           # what fits in one byte

# Segment IDs are FIB indices, not literally satellite numbers (RFC 9631 says
# a CRH SID "identifies an entry in the CRH Forwarding Information Base").
# So we can give ground stations IDs too, from a reserved high block.
GS_SID_BASE = 0xF000         # ground station g -> 0xF000 + g

# ----- Flag bits -----
FLAG_DEVIATION = 0x01        # set by the first node that finds the plan broken
FLAG_GREEDY_MODE = 0x02      # packet is now in geographic-fallback forwarding

# ----- Comparison constants (for the overhead experiment) -----
IPV6_BASE_HEADER = 40        # fixed IPv6 header
SRH_FIXED = 8                # RFC 8754 SRH fixed portion
SRH_BYTES_PER_SEGMENT = 16   # a full 128-bit IPv6 address per segment
CRH16_FIXED = 8              # RFC 9631 CRH fixed portion
CRH16_BYTES_PER_SID = 2      # 16-bit segment ID
HMAC_TLV_BYTES = 40          # SRv6-style HMAC TLV, for the security trade-off


def pad_to_8(n):
    """IPv6 extension headers must be a whole number of 8-byte units."""
    return ((n + 7) // 8) * 8


# --------------------------------------------------------------- size functions

def tcrh_size(num_hops):
    """On-the-wire size of a T-CRH carrying num_hops entries."""
    return pad_to_8(FIXED_BYTES + EPOCH_BYTES + num_hops * BYTES_PER_HOP)


def crh16_size(num_hops):
    """RFC 9631 CRH-16 with the same number of segments (no time info)."""
    return pad_to_8(CRH16_FIXED + num_hops * CRH16_BYTES_PER_SID)


def srh_size(num_hops):
    """RFC 8754 SRv6 SRH with the same number of segments."""
    return pad_to_8(SRH_FIXED + num_hops * SRH_BYTES_PER_SEGMENT)


def tcrh_size_authenticated(num_hops):
    """T-CRH plus an HMAC TLV -- the security/compactness trade-off."""
    return pad_to_8(FIXED_BYTES + EPOCH_BYTES
                    + num_hops * BYTES_PER_HOP + HMAC_TLV_BYTES)


# --------------------------------------------------------------- encode / decode

def encode(path_sat_ids, deltas_ms, epoch_base_ms, flags=0, next_header=6):
    """
    Build the real header bytes.

    Args:
        path_sat_ids  : list of satellite IDs, in forward order
        deltas_ms     : list of per-hop deadline deltas in ms (same length)
        epoch_base_ms : reference time, GPS milliseconds (we store it mod 2^32)
        flags         : initial flag byte
        next_header   : IPv6 Next Header value (6 = TCP)

    Returns: bytes
    """
    if len(path_sat_ids) != len(deltas_ms):
        raise ValueError("path and deltas must be the same length")

    n = len(path_sat_ids)
    body = bytearray()
    body += struct.pack('!I', int(epoch_base_ms) & 0xFFFFFFFF)

    for sid, delta in zip(path_sat_ids, deltas_ms):
        if not (0 <= sid <= 0xFFFF):
            raise ValueError(f"satellite ID {sid} does not fit in 16 bits")
        # a delta that overflows one byte is clamped; the scheduler should
        # never produce one, so we count it as a design violation
        d = min(int(round(delta)), MAX_DELTA_MS)
        body += struct.pack('!HB', sid, d)

    total = FIXED_BYTES + len(body)
    padded = pad_to_8(total)
    body += b'\x00' * (padded - total)

    hdr_ext_len = (padded // 8) - 1      # RFC 8200: length in 8-octet units, minus 1

    header = struct.pack('!BBBBBBH',
                         next_header,
                         hdr_ext_len,
                         ROUTING_TYPE_TCRH,
                         n,          # Segments Left starts at the full hop count
                         flags,
                         n,          # Num Hops
                         0)          # Reserved
    return bytes(header + body)


def decode(raw):
    """Parse T-CRH bytes back into a dict. The mirror of encode()."""
    (next_header, hdr_ext_len, rtg_type, segments_left,
     flags, num_hops, _reserved) = struct.unpack('!BBBBBBH', raw[:8])

    if rtg_type != ROUTING_TYPE_TCRH:
        raise ValueError(f"not a T-CRH (routing type {rtg_type})")

    epoch_base_ms, = struct.unpack('!I', raw[8:12])

    sat_ids, deltas = [], []
    off = 12
    for _ in range(num_hops):
        sid, delta = struct.unpack('!HB', raw[off:off + 3])
        sat_ids.append(sid)
        deltas.append(delta)
        off += 3

    return {
        'next_header': next_header,
        'hdr_ext_len': hdr_ext_len,
        'segments_left': segments_left,
        'flags': flags,
        'num_hops': num_hops,
        'epoch_base_ms': epoch_base_ms,
        'sat_ids': sat_ids,
        'deltas_ms': deltas,
        'size_bytes': len(raw),
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
    print("Round-trip decode: PASS")
    print(f"  segments_left = {back['segments_left']}")
    print(f"  epoch_base_ms = {back['epoch_base_ms']}")

    dl = absolute_deadlines(back['epoch_base_ms'], back['deltas_ms'])
    print(f"  absolute deadlines = {dl}\n")

    print("=== Header size comparison (this is Experiment 2) ===")
    print(f"{'hops':>5} {'SRv6 SRH':>10} {'CRH-16':>8} {'T-CRH':>8} "
          f"{'T-CRH+HMAC':>11} {'time cost':>10}")
    for h in (3, 5, 10, 15):
        s, c, t, ta = srh_size(h), crh16_size(h), tcrh_size(h), tcrh_size_authenticated(h)
        print(f"{h:>5} {s:>10} {c:>8} {t:>8} {ta:>11} {t - c:>+10}")

    print("\nSanity check against the report's claimed numbers:")
    print(f"  10-hop SRv6 SRH = {srh_size(10)} bytes  (report says 168)")
    print(f"  10-hop CRH-16   = {crh16_size(10)} bytes  (report says 28)")
    print(f"  10-hop T-CRH    = {tcrh_size(10)} bytes  (report says 48)")
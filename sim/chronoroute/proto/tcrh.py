"""
tcrh.py
-------
Reference implementation of the Temporal Compact Routing Header, T-CRH v1
(spec/tcrh-v1.md is normative; section numbers below refer to it).

T-CRH = RFC 9631 Compact Routing Header (CRH-16) + a time base + one
deadline byte per hop:

     0               1               2               3
    +---------------+---------------+---------------+---------------+
    |  Next Header  |  Hdr Ext Len  | Rtg Type =253 | Segments Left |  bytes 0-3
    +---------------+---------------+---------------+---------------+
    |     Flags     |   Num Hops    |    Dev Hop    |   Reserved    |  bytes 4-7
    +---------------+---------------+---------------+---------------+
    |                          Epoch_Base                           |  bytes 8-11
    +---------------+---------------+---------------+---------------+
    |        SID[0] (16 bits)       |  Delta[0]     |  SID[1] ...   |  3 B per entry
    +---------------+---------------+---------------+---------------+
                     (zero padding to a multiple of 8 bytes)

Entries are stored in REVERSE path order, as in RFC 9631, so that Segments
Left can be used directly as an index: SID[0] is the final endpoint and
SID[h-1] is the first hop. A node decrements Segments Left FIRST and then
reads SID[Segments Left].

What lives here:
  * TcrhHeader      - an immutable value object with encode() / decode()
  * encode_deltas   - the exact ceil-cumulative delta encoder (section 5.1)
  * build_header    - budgets + ingress time -> header (the ingress node)
  * process_at_node - the per-node algorithm of section 6 as a PURE function
  * ingress_send    - what the ingress does after building the header
                      (steps 5-6, no deadline check)
  * link_down_fallback - section 6 step 7: the planned next link is down

The CRH-FIB lookup (step 6: SID -> neighbour / interface) is deliberately
NOT inside process_at_node: it depends on the simulator's topology. The
caller maps the returned next_sid to a neighbour, and discards the packet
(ICMPv6 Parameter Problem, Code 0) if the SID has no FIB entry.
"""

from dataclasses import dataclass
from fractions import Fraction
import math
import struct

from .sizes import tcrh_size, TCRH_FIXED_BYTES, TCRH_ENTRY_BYTES, TCRH_MAX_HOPS
from .timebase import MOD32, unit_ns, epoch_base_at_ingress, serial_diff, _require_int

# ----- Header constants -----
ROUTING_TYPE_TCRH = 253          # RFC 4727 experimental value
MAX_HOPS = TCRH_MAX_HOPS         # Num Hops is one byte
MAX_DELTA = 255                  # Delta is one unsigned byte
DEFAULT_NEXT_HEADER = 17         # UDP, as in the ns-3 reference

# ----- Byte offsets (also used as ICMPv6 Parameter Problem pointers,
#       relative to the first byte of the routing header) -----
OFF_NEXT_HEADER = 0
OFF_HDR_EXT_LEN = 1
OFF_ROUTING_TYPE = 2
OFF_SEGMENTS_LEFT = 3
OFF_FLAGS = 4
OFF_NUM_HOPS = 5
OFF_DEV_HOP = 6
OFF_RESERVED = 7
OFF_EPOCH_BASE = 8
OFF_ENTRIES = TCRH_FIXED_BYTES   # 12

# ----- Flag bits (section 3) -----
FLAG_DEV = 0x01                  # a node found the packet late; set once, never cleared
FLAG_GREEDY = 0x02               # packet is in fallback (geographic) forwarding
FLAG_SAT = 0x04                  # a Delta was clamped to 255 at encode time
FLAG_UNIT_MASK = 0x30            # deadline unit code, (flags >> 4) & 3
FLAG_UNIT_SHIFT = 4
FLAG_RESERVED_MASK = 0xC8        # zero on transmit, ignored on receipt
FLAG_STATE_MASK = FLAG_DEV | FLAG_GREEDY | FLAG_SAT

# ----- SID allocation (section 7) -----
SID_SATELLITE_MAX = 0xEFFF       # 0x0000 - 0xEFFF: satellites
SID_GROUND_BASE = 0xF000         # ground station g -> 0xF000 + g
SID_GROUND_MAX = 0xFFFE
SID_RESERVED = 0xFFFF

# ----- Deviation policies and processing outcomes (section 6) -----
POLICIES = ("greedy", "continue", "drop")
ACTIONS = ("deliver", "forward", "fallback", "drop_late", "drop_malformed", "ignore")


def ground_station_sid(g):
    """SID of ground station number g (section 7): 0xF000 + g."""
    _require_int("g", g)
    if not 0 <= g <= SID_GROUND_MAX - SID_GROUND_BASE:
        raise ValueError(f"ground station number must be 0..{SID_GROUND_MAX - SID_GROUND_BASE}, got {g}")
    return SID_GROUND_BASE + g


def is_ground_station_sid(sid):
    """True for SIDs in the ground-station block 0xF000 - 0xFFFE."""
    return SID_GROUND_BASE <= sid <= SID_GROUND_MAX


# --------------------------------------------------------------- errors

class TcrhDecodeError(ValueError):
    """
    Raised when bytes are not a valid T-CRH.

    .reason  short machine-readable code (one per subclass)
    .pointer offset, inside the routing header, of the offending field: the
             ICMPv6 Parameter Problem pointer (Code 0, section 6 step 1), or
             None when there is no field to point at (the bytes just stop).
    """
    reason = "malformed"

    def __init__(self, message, pointer=None):
        super().__init__(message)
        self.pointer = pointer


class WrongRoutingType(TcrhDecodeError):
    """Routing Type is not 253: these bytes are not a T-CRH."""
    reason = "wrong_type"


class TruncatedHeader(TcrhDecodeError):
    """Fewer bytes than the fixed part or than Hdr Ext Len announces."""
    reason = "truncated"


class NumHopsZero(TcrhDecodeError):
    """Num Hops is 0 (section 2: 1..255; section 6 step 1c)."""
    reason = "numhops_zero"


class SegmentsLeftTooLarge(TcrhDecodeError):
    """Segments Left > Num Hops (section 6 step 1)."""
    reason = "sl_gt_numhops"


class LengthMismatch(TcrhDecodeError):
    """(Hdr Ext Len + 1) * 8 < pad8(12 + 3 * Num Hops) (section 6 step 1)."""
    reason = "length_mismatch"


class TrailingBytes(TcrhDecodeError):
    """TcrhHeader.decode() got more bytes than Hdr Ext Len announces (use decode_prefix)."""
    reason = "trailing_bytes"


# --------------------------------------------------------------- helpers

def _check_range(name, value, lo, hi):
    _require_int(name, value)
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}, got {value}")


def _as_bytes(raw):
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError(f"expected bytes, got {type(raw).__name__}")
    return bytes(raw)


def _exact_budget(b):
    """A cumulative budget in ns, as an exact int or Fraction (never a float)."""
    if isinstance(b, bool) or not isinstance(b, (int, Fraction)):
        raise TypeError(
            f"budgets must be int or Fraction nanoseconds, got {type(b).__name__}; "
            "convert floats once with timebase.seconds_to_ns() / ms_to_ns()")
    if b < 0:
        raise ValueError(f"a cumulative budget cannot be negative, got {b}")
    return b


# --------------------------------------------------------------- the header

@dataclass(frozen=True)
class TcrhHeader:
    """
    One T-CRH, as values. Frozen: use dataclasses.replace() to derive a
    modified copy (for example a packet further along its path).

    sids_rev / deltas_rev are in WIRE order (reversed path, index = SL).
    Use from_forward() / build_header() to create one from a forward path,
    and .sids_fwd / .deltas_fwd to read it back in path order.

    The Reserved byte and the padding are not stored: encode() writes them as
    zero (section 2, "zero on transmit"). The Flags byte is stored exactly as
    received, reserved bits included, so decode() -> encode() keeps it.
    """
    next_header: int
    segments_left: int
    flags: int
    num_hops: int
    dev_hop: int
    epoch_base: int
    sids_rev: tuple[int, ...]
    deltas_rev: tuple[int, ...]

    def __post_init__(self):
        # accept any iterable for the lists, store tuples so the value is hashable
        object.__setattr__(self, "sids_rev", tuple(self.sids_rev))
        object.__setattr__(self, "deltas_rev", tuple(self.deltas_rev))
        _check_range("next_header", self.next_header, 0, 255)
        _check_range("num_hops", self.num_hops, 1, MAX_HOPS)     # section 2: 1..255
        _check_range("segments_left", self.segments_left, 0, self.num_hops)
        _check_range("flags", self.flags, 0, 255)
        _check_range("dev_hop", self.dev_hop, 0, 255)
        _check_range("epoch_base", self.epoch_base, 0, MOD32 - 1)
        if len(self.sids_rev) != self.num_hops or len(self.deltas_rev) != self.num_hops:
            raise ValueError(
                f"num_hops={self.num_hops} but {len(self.sids_rev)} SIDs and "
                f"{len(self.deltas_rev)} deltas")
        for sid in self.sids_rev:
            _check_range("SID", sid, 0, 0xFFFF)
        for d in self.deltas_rev:
            _check_range("delta", d, 0, MAX_DELTA)

    # ----- construction -----

    @classmethod
    def from_forward(cls, sids_fwd, deltas_fwd, epoch_base, unit_code,
                     next_header=DEFAULT_NEXT_HEADER, extra_flags=0):
        """
        Build a fresh header (Segments Left = Num Hops = h, Dev Hop = 0) from a
        path in FORWARD order: sids_fwd[0] is the first hop after the ingress,
        sids_fwd[-1] the final endpoint; deltas_fwd[k-1] is d_k in units.

        extra_flags may hold DEV / GREEDY / SAT; the UNIT bits come from
        unit_code and the reserved bits must stay zero.
        """
        sids = list(sids_fwd)
        deltas = list(deltas_fwd)
        if len(sids) != len(deltas):
            raise ValueError("every hop needs exactly one delta (sids_fwd and deltas_fwd differ in length)")
        if not 1 <= len(sids) <= MAX_HOPS:
            raise ValueError(f"a T-CRH carries 1..{MAX_HOPS} hops, got {len(sids)}")
        for sid in sids:
            # 0xFFFF is reserved (section 7): never put it in a new path
            _check_range("SID", sid, 0, SID_RESERVED - 1)
        for d in deltas:
            # no silent clamping here: clamping is encode_deltas' job, and it sets SAT
            _check_range("delta", d, 0, MAX_DELTA)
        _check_range("epoch_base", epoch_base, 0, MOD32 - 1)
        unit_ns(unit_code)  # validates 0..3
        _check_range("extra_flags", extra_flags, 0, 255)
        if extra_flags & ~FLAG_STATE_MASK:
            raise ValueError(
                f"extra_flags may only contain DEV/GREEDY/SAT (0x{FLAG_STATE_MASK:02x}), "
                f"got 0x{extra_flags:02x}; the unit goes in unit_code")
        h = len(sids)
        return cls(
            next_header=next_header,
            segments_left=h,
            flags=(unit_code << FLAG_UNIT_SHIFT) | extra_flags,
            num_hops=h,
            dev_hop=0,
            epoch_base=epoch_base,
            sids_rev=tuple(reversed(sids)),
            deltas_rev=tuple(reversed(deltas)),
        )

    # ----- wire format -----

    @property
    def size(self):
        """Bytes on the wire: pad8(12 + 3h)."""
        return tcrh_size(self.num_hops)

    @property
    def hdr_ext_len(self):
        """Hdr Ext Len: 8-octet units not counting the first 8 (RFC 8200 4.4)."""
        return self.size // 8 - 1

    def encode(self):
        """Serialise to bytes (big-endian, zero Reserved byte, zero padding)."""
        out = bytearray(self.size)
        struct.pack_into(
            "!BBBBBBBBI", out, 0,
            self.next_header, self.hdr_ext_len, ROUTING_TYPE_TCRH, self.segments_left,
            self.flags, self.num_hops, self.dev_hop, 0, self.epoch_base)
        off = OFF_ENTRIES
        for sid, delta in zip(self.sids_rev, self.deltas_rev):
            struct.pack_into("!HB", out, off, sid, delta)
            off += TCRH_ENTRY_BYTES
        return bytes(out)

    @classmethod
    def _parse(cls, raw, exact):
        """
        Validate and parse. Checks run in this fixed order, section 6
        step 1 (so every implementation reports the same reason for the same
        bytes); the ICMPv6 pointer is in brackets:
          1. fewer than 8 bytes                              -> truncated
          2. Routing Type != 253                             -> wrong_type (2)
          3. Num Hops == 0                                   -> numhops_zero (5)
          4. Segments Left > Num Hops                        -> sl_gt_numhops (3)
          5. (HdrExtLen + 1) * 8 < pad8(12 + 3 * NumHops)    -> length_mismatch (1)
          6. fewer bytes than (HdrExtLen + 1) * 8            -> truncated
          7. (exact only) more bytes than that               -> trailing_bytes
        A Reserved byte, reserved flag bits or padding that are not zero are
        ignored on receipt (section 2), as is a Hdr Ext Len larger than needed.
        Returns (header, header_length_in_bytes).
        """
        b = _as_bytes(raw)
        if len(b) < 8:
            raise TruncatedHeader(f"T-CRH needs at least 8 bytes, got {len(b)}")
        next_header, hel, rtype, sl, flags, nhops, dev_hop, _reserved = b[:8]
        if rtype != ROUTING_TYPE_TCRH:
            raise WrongRoutingType(f"routing type {rtype} is not T-CRH ({ROUTING_TYPE_TCRH})",
                                   pointer=OFF_ROUTING_TYPE)
        if nhops == 0:
            # section 2: Num Hops is 1..255. A header with no entries has no
            # final endpoint to deliver to or to fall back towards.
            raise NumHopsZero("Num Hops is 0 (a T-CRH carries 1..255 entries)",
                              pointer=OFF_NUM_HOPS)
        if sl > nhops:
            raise SegmentsLeftTooLarge(f"Segments Left {sl} > Num Hops {nhops}",
                                       pointer=OFF_SEGMENTS_LEFT)
        total = (hel + 1) * 8
        need = tcrh_size(nhops)
        if total < need:
            raise LengthMismatch(
                f"Hdr Ext Len {hel} gives {total} bytes, but {nhops} hops need {need}",
                pointer=OFF_HDR_EXT_LEN)
        if len(b) < total:
            raise TruncatedHeader(f"Hdr Ext Len announces {total} bytes, only {len(b)} present")
        if exact and len(b) != total:
            raise TrailingBytes(f"Hdr Ext Len announces {total} bytes, got {len(b)}")
        (epoch_base,) = struct.unpack_from("!I", b, OFF_EPOCH_BASE)
        sids, deltas = [], []
        off = OFF_ENTRIES
        for _ in range(nhops):           # Num Hops lets us stop before the padding
            sid, delta = struct.unpack_from("!HB", b, off)
            sids.append(sid)
            deltas.append(delta)
            off += TCRH_ENTRY_BYTES
        hdr = cls(next_header=next_header, segments_left=sl, flags=flags, num_hops=nhops,
                  dev_hop=dev_hop, epoch_base=epoch_base, sids_rev=sids, deltas_rev=deltas)
        return hdr, total

    @classmethod
    def decode(cls, raw):
        """Parse exactly one T-CRH (len(raw) must equal its Hdr Ext Len size)."""
        return cls._parse(raw, exact=True)[0]

    @classmethod
    def decode_prefix(cls, raw):
        """Parse a T-CRH at the start of raw (payload may follow). Returns (header, nbytes)."""
        return cls._parse(raw, exact=False)

    # ----- path order views -----

    @property
    def sids_fwd(self):
        """SIDs in path order: first hop first, final endpoint last."""
        return tuple(reversed(self.sids_rev))

    @property
    def deltas_fwd(self):
        """Deltas in path order: d_1 .. d_h."""
        return tuple(reversed(self.deltas_rev))

    # ----- flags -----

    @property
    def unit_code(self):
        return (self.flags >> FLAG_UNIT_SHIFT) & 3

    @property
    def unit_ns(self):
        """Length of this header's deadline unit in nanoseconds."""
        return unit_ns(self.unit_code)

    @property
    def is_dev(self):
        return bool(self.flags & FLAG_DEV)

    @property
    def is_greedy(self):
        return bool(self.flags & FLAG_GREEDY)

    @property
    def is_sat(self):
        return bool(self.flags & FLAG_SAT)

    # ----- deadlines (section 5) -----

    def deadline(self, k):
        """
        Cumulative arrival deadline D_k at hop k (1..h), in units, mod 2^32:
        Epoch_Base + d_1 + ... + d_k. In wire order those are the entries
        SL..h-1 for SL = h - k, the ones already consumed on arrival at hop k.
        """
        _check_range("hop index k", k, 1, self.num_hops)
        return (self.epoch_base + sum(self.deltas_rev[self.num_hops - k:])) % MOD32

    def deadlines(self):
        """(D_1, ..., D_h)."""
        out, running = [], self.epoch_base
        for d in self.deltas_fwd:
            running += d
            out.append(running % MOD32)
        return tuple(out)

    def current_hop_index(self):
        """
        k = NumHops - SL: the hop index of the node holding the packet on
        arrival (1..h). 0 means Segments Left is still h, i.e. the ingress.
        """
        return self.num_hops - self.segments_left

    def current_deadline(self):
        """D_k for the node holding the packet on arrival; None at the ingress (k = 0)."""
        k = self.current_hop_index()
        return self.deadline(k) if k >= 1 else None


# --------------------------------------------------------------- encoding deltas

def encode_deltas(cumulative_budgets_ns, unit_code):
    """
    Ceil-cumulative delta encoding, exactly as spec section 5.1.

    cumulative_budgets_ns: B_1 <= ... <= B_h, the time allowed from ingress to
    arrival at hop k, in nanoseconds, as int or fractions.Fraction (exact).
    Returns (deltas_fwd, sat): a tuple of h one-byte deltas and whether any
    delta had to be clamped to 255.

    Because every target is ceil(B_k / u) of the CUMULATIVE budget, rounding
    error never accumulates along the path, and no deadline is earlier than
    its budget unless SAT is set.
    """
    u = unit_ns(unit_code)
    deltas = []
    sat = False
    encoded = 0                                   # E: encoded cumulative sum, units
    for b in cumulative_budgets_ns:
        b = _exact_budget(b)
        target = math.ceil(Fraction(b, u))        # exact ceil(B_k / u)
        d = target - encoded
        if d > MAX_DELTA:
            d = MAX_DELTA
            sat = True
        if d < 0:                                 # cannot happen when B is non-decreasing
            d = 0
        encoded += d
        deltas.append(d)
    return tuple(deltas), sat


def build_header(sids_fwd, cumulative_budgets_ns, t_ingress_gps_ns, unit_code,
                 next_header=DEFAULT_NEXT_HEADER):
    """
    What the ingress does: stamp Epoch_Base = ceil(T_ingress / u) mod 2^32
    for THIS packet (not the schedule epoch), encode the budgets, set SAT if
    a delta saturated. Returns a fresh TcrhHeader (SL = Num Hops).
    """
    sids = list(sids_fwd)
    budgets = list(cumulative_budgets_ns)
    if len(sids) != len(budgets):
        raise ValueError("every hop needs exactly one cumulative budget")
    deltas, sat = encode_deltas(budgets, unit_code)
    epoch = epoch_base_at_ingress(t_ingress_gps_ns, unit_code)
    return TcrhHeader.from_forward(sids, deltas, epoch, unit_code, next_header,
                                   FLAG_SAT if sat else 0)


# --------------------------------------------------------------- processing (section 6)

@dataclass(frozen=True)
class ProcessResult:
    """
    Outcome of process_at_node.

    action       'deliver'        SL was 0: this node is the final endpoint (step 3)
                 'forward'        send towards next_sid via the CRH-FIB (steps 5-6)
                 'fallback'       GREEDY set, SL = 0: send towards next_sid = SID[0]
                                  with the fallback (geographic) function (step 4,
                                  or step 7 from link_down_fallback)
                 'drop_late'      DEV set and policy 'drop' (step 4)
                 'drop_malformed' failed validation (step 1); see reason
                 'ignore'         not a T-CRH and SL = 0 (step 1b, RFC 8200 4.4):
                                  skip this routing header, process the Next
                                  Header; out_bytes are the input, unchanged
    next_sid     SID to look up / head for, or None
    out_bytes    the packet bytes to send on (or deliver), mutable fields
                 updated in place; None when the packet is discarded
    late         True when THIS node's deadline check (step 2) fired and set
                 DEV. It is never True for a packet that already had DEV set:
                 such packets are not checked again (one Dev Hop per packet).
    hop_index    k = NumHops - SL on arrival (0 at the ingress); None if malformed
    deadline_u   D_k for this node, or None (ingress, malformed)
    reason       None for deliver/forward and a late-packet fallback;
                 'link_down' for a step 7 fallback; 'late_strict' for
                 drop_late; 'wrong_type' for ignore; the TcrhDecodeError
                 reason for drop_malformed
    icmp_code    0 when an ICMPv6 Parameter Problem should be sent, else None
    icmp_pointer offset of the offending field inside the routing header
    """
    action: str
    next_sid: int | None = None
    out_bytes: bytes | None = None
    late: bool = False
    hop_index: int | None = None
    deadline_u: int | None = None
    reason: str | None = None
    icmp_code: int | None = None
    icmp_pointer: int | None = None


def _patch(raw, segments_left, flags, dev_hop):
    """
    Rewrite only the mutable fields (SL, Flags, Dev Hop; section 2) in a copy
    of the packet. Every other byte - Reserved, padding, any payload that
    follows the header - is passed through untouched, as a router would.
    """
    out = bytearray(raw)
    out[OFF_SEGMENTS_LEFT] = segments_left
    out[OFF_FLAGS] = flags
    out[OFF_DEV_HOP] = dev_hop
    return bytes(out)


def _malformed(err):
    """Step 1 failed: discard, with ICMPv6 Code 0 when there is a field to point at."""
    return ProcessResult(action="drop_malformed", reason=err.reason,
                         icmp_code=0 if err.pointer is not None else None,
                         icmp_pointer=err.pointer)


def process_at_node(raw, now_u, policy="greedy"):
    """
    Spec section 6, step by step, as a pure function of the packet bytes and
    the node's unit clock now_u (= clock_u(t_gps_ns, unit_code)).

    raw starts with the T-CRH; bytes after the header (the payload) are kept.
    Call it only at the node named in the Destination Address. A packet that
    is in GREEDY mode is addressed to SID[0], so the satellites it crosses on
    the way do not run this function; they use the fallback function directly.
    The CRH-FIB lookup (step 6) is the caller's job: map next_sid to a
    neighbour, and drop with ICMPv6 Parameter Problem Code 0 if it is missing.

    policy is the node's deviation policy: 'greedy', 'continue' or 'drop'.
    """
    if policy not in POLICIES:
        raise ValueError(f"policy must be one of {POLICIES}, got {policy!r}")
    _check_range("now_u", now_u, 0, MOD32 - 1)
    raw = _as_bytes(raw)

    # 1. Validate.
    try:
        hdr, _total = TcrhHeader._parse(raw, exact=False)
    except WrongRoutingType as err:
        # 1b. Not a T-CRH. RFC 8200 section 4.4 for an unrecognised Routing
        # Type: with Segments Left 0, ignore the header and go on to the Next
        # Header; otherwise discard with Parameter Problem -> Routing Type.
        # (WrongRoutingType implies at least 8 bytes, so byte 3 exists.)
        if raw[OFF_SEGMENTS_LEFT] == 0:
            return ProcessResult(action="ignore", out_bytes=raw, reason=err.reason)
        return _malformed(err)
    except TcrhDecodeError as err:
        return _malformed(err)

    sl = hdr.segments_left
    flags = hdr.flags
    dev_hop = hdr.dev_hop
    k = hdr.current_hop_index()
    deadline_u = hdr.current_deadline()          # None when k == 0 (ingress)
    late = False

    # 2. Deadline check: only if DEV is clear and this is not the ingress.
    #    Late means strictly after the deadline unit (serial arithmetic).
    if not flags & FLAG_DEV and sl < hdr.num_hops:
        if serial_diff(now_u, deadline_u) > 0:
            late = True
            flags |= FLAG_DEV
            dev_hop = k

    common = dict(late=late, hop_index=k, deadline_u=deadline_u)

    # 3. Final segment endpoint: deliver (late or not; DEV records the miss).
    if sl == 0:
        return ProcessResult(action="deliver", out_bytes=_patch(raw, sl, flags, dev_hop), **common)

    # 4. Deviation policy, for a packet found late here or earlier.
    if flags & FLAG_DEV:
        if policy == "greedy":
            flags |= FLAG_GREEDY
            return ProcessResult(action="fallback", next_sid=hdr.sids_rev[0],
                                 out_bytes=_patch(raw, 0, flags, dev_hop), **common)
        if policy == "drop":
            return ProcessResult(action="drop_late", reason="late_strict", **common)
        # 'continue': keep following the SID list; DEV records the miss.

    # 5. Decrement first, then index.
    sl -= 1
    next_sid = hdr.sids_rev[sl]
    # 6. (caller) CRH-FIB lookup of next_sid.
    return ProcessResult(action="forward", next_sid=next_sid,
                         out_bytes=_patch(raw, sl, flags, dev_hop), **common)


def link_down_fallback(raw):
    """
    Section 6 step 7, "next link down", as a pure function of the bytes.

    raw is the packet as it leaves step 5 (from ingress_send, or the
    out_bytes of a 'forward' from process_at_node), and the node has just
    found the link to the next SID down. No deadline can show that, so it is
    a deviation of its own: if DEV is clear, set it with Dev Hop = k, the
    hop index of this node (k = NumHops - SL - 1 on these bytes, because
    step 5 already decremented SL; 0 at the ingress). Then set GREEDY and
    SL = 0 and head for SID[0] with the fallback function, under every
    deviation policy ('continue' cannot follow a dead link; 'drop' is about
    late packets). Only SL, Flags and Dev Hop change.

    Returns ProcessResult(action='fallback', next_sid=SID[0], hop_index=k,
    reason='link_down'), or 'drop_malformed' for bytes that fail step 1.
    Raises ValueError for a packet that cannot be in this state: SL ==
    NumHops (step 5 not done) or GREEDY already set (greedy forwarding skips
    dead links itself).
    """
    raw = _as_bytes(raw)
    try:
        hdr, _total = TcrhHeader._parse(raw, exact=False)
    except TcrhDecodeError as err:
        return _malformed(err)
    if hdr.segments_left >= hdr.num_hops:
        raise ValueError("link_down_fallback needs the bytes as they leave step 5 "
                         f"(SL < NumHops), got SL={hdr.segments_left} NumHops={hdr.num_hops}")
    if hdr.is_greedy:
        raise ValueError("a GREEDY packet is already in fallback mode; it skips dead links itself")
    k = hdr.num_hops - hdr.segments_left - 1
    flags, dev_hop = hdr.flags, hdr.dev_hop
    if not flags & FLAG_DEV:
        flags |= FLAG_DEV
        dev_hop = k
    flags |= FLAG_GREEDY
    return ProcessResult(action="fallback", next_sid=hdr.sids_rev[0],
                         out_bytes=_patch(raw, 0, flags, dev_hop), hop_index=k,
                         reason="link_down")


def ingress_send(raw):
    """
    The ingress node's own forwarding of a header it has just built
    (section 6, last paragraph): steps 5-6 without a deadline check.

    raw must start with a fresh T-CRH (SL == Num Hops >= 1).
    Returns (out_bytes, first_sid); first_sid is s_1 = SID[h-1].
    Raises TcrhDecodeError for malformed bytes, ValueError for a header that
    is not fresh.
    """
    raw = _as_bytes(raw)
    hdr, _total = TcrhHeader._parse(raw, exact=False)
    if hdr.num_hops == 0 or hdr.segments_left != hdr.num_hops:
        raise ValueError(
            f"ingress expects a fresh header (SL == NumHops >= 1), got SL={hdr.segments_left} "
            f"NumHops={hdr.num_hops}")
    sl = hdr.segments_left - 1
    return _patch(raw, sl, hdr.flags, hdr.dev_hop), hdr.sids_rev[sl]


__all__ = [
    "ROUTING_TYPE_TCRH", "MAX_HOPS", "MAX_DELTA", "DEFAULT_NEXT_HEADER",
    "OFF_NEXT_HEADER", "OFF_HDR_EXT_LEN", "OFF_ROUTING_TYPE", "OFF_SEGMENTS_LEFT",
    "OFF_FLAGS", "OFF_NUM_HOPS", "OFF_DEV_HOP", "OFF_RESERVED", "OFF_EPOCH_BASE",
    "OFF_ENTRIES", "FLAG_DEV", "FLAG_GREEDY", "FLAG_SAT", "FLAG_UNIT_MASK",
    "FLAG_UNIT_SHIFT", "FLAG_RESERVED_MASK", "FLAG_STATE_MASK",
    "SID_SATELLITE_MAX", "SID_GROUND_BASE", "SID_GROUND_MAX", "SID_RESERVED",
    "POLICIES", "ACTIONS", "ground_station_sid", "is_ground_station_sid",
    "TcrhDecodeError", "WrongRoutingType", "TruncatedHeader", "NumHopsZero",
    "SegmentsLeftTooLarge", "LengthMismatch", "TrailingBytes", "TcrhHeader", "encode_deltas",
    "build_header", "ProcessResult", "process_at_node", "link_down_fallback", "ingress_send",
]

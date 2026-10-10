"""
crh.py
------
The IPv6 Compact Routing Header, CRH-16 and CRH-32 (RFC 9631), which T-CRH
extends. Used as the "no time information" baseline and for size comparisons.
Byte-exact with the ns-3 CrhHeader in ~/ns-3-dev/scratch/crh-experiment.cc.

     0               1               2               3
    +---------------+---------------+---------------+---------------+
    |  Next Header  |  Hdr Ext Len  | Routing Type  | Segments Left |   4 fixed bytes
    +---------------+---------------+---------------+---------------+
    |      SID[0]  |  SID[1]  |  ...   (16 bits each for CRH-16, type 5;
    |                                   32 bits each for CRH-32, type 6)
    +---------------------------------------------------------------+
                  (zero padding to a 64-bit boundary)

Rules (RFC 9631 sections 3 and 5):
  * SIDs are stored in REVERSE path order, so SID[0] is the last hop.
  * A node decrements Segments Left FIRST, then reads SID[Segments Left].
  * Unlike T-CRH there is no SID count. A receiver cannot tell a real SID
    from a zero padding slot, and it never needs to: it only reads
    SID[Segments Left - 1], and the minimum-length check (section 5.1) proves
    that slot is inside the header before it is read. decode() therefore
    returns EVERY SID slot, padding included, exactly like the ns-3 code.
  * The source is itself a CRH node: it builds the header with Segments Left
    = n and runs the same forwarding step (RFC 9631 Appendix A.1), so
    process_at_node() serves the source too.
"""

from dataclasses import dataclass
import struct

from .sizes import pad8, CRH_FIXED_BYTES
from .timebase import _require_int

ROUTING_TYPE_CRH16 = 5
ROUTING_TYPE_CRH32 = 6
SID_BYTES = {ROUTING_TYPE_CRH16: 2, ROUTING_TYPE_CRH32: 4}
_SID_FMT = {ROUTING_TYPE_CRH16: "!H", ROUTING_TYPE_CRH32: "!I"}
DEFAULT_NEXT_HEADER = 17          # UDP, as in the ns-3 reference
MAX_HEADER_BYTES = (255 + 1) * 8  # largest size Hdr Ext Len can describe

OFF_HDR_EXT_LEN = 1
OFF_ROUTING_TYPE = 2
OFF_SEGMENTS_LEFT = 3
OFF_SIDS = CRH_FIXED_BYTES       # 4

# ICMPv6 Parameter Problem codes used by RFC 9631 section 5
ICMP_CODE_ERRONEOUS_FIELD = 0     # SID not in the CRH-FIB, header too big
ICMP_CODE_MIN_LENGTH = 6          # minimum CRH length L > Hdr Ext Len (pointer: Segments Left)


class CrhDecodeError(ValueError):
    """Bytes are not a valid CRH. .reason is a short code, .pointer the ICMPv6 pointer or None."""
    reason = "malformed"

    def __init__(self, message, pointer=None):
        super().__init__(message)
        self.pointer = pointer


class CrhWrongRoutingType(CrhDecodeError):
    reason = "wrong_type"


class CrhTruncated(CrhDecodeError):
    reason = "truncated"


class CrhTrailingBytes(CrhDecodeError):
    reason = "trailing_bytes"


def _check_range(name, value, lo, hi):
    _require_int(name, value)
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}, got {value}")


def _check_type(routing_type):
    if routing_type not in SID_BYTES:
        raise ValueError(f"CRH routing type must be 5 (CRH-16) or 6 (CRH-32), got {routing_type}")


def min_hdr_ext_len(segments_left, routing_type):
    """
    L, the minimum CRH length for this Segments Left, in 8-octet units not
    counting the first 8 octets (RFC 9631 section 5.1, implemented literally):

        CRH-16: SL <= 2 -> 0, else ceil((SL - 2) / 4)
        CRH-32: SL <= 1 -> 0, else ceil((SL - 1) / 2)

    (The first 8 octets hold the 4 fixed bytes plus 2 CRH-16 SIDs or 1
    CRH-32 SID; every further 8 octets hold 4 or 2 more.)
    """
    _check_range("segments_left", segments_left, 0, 255)
    _check_type(routing_type)
    if routing_type == ROUTING_TYPE_CRH16:
        first_word, per_word = 2, 4
    else:
        first_word, per_word = 1, 2
    if segments_left <= first_word:
        return 0
    return -(-(segments_left - first_word) // per_word)


@dataclass(frozen=True)
class CrhHeader:
    """
    One CRH as values. sids_rev is in wire order. A decoded header keeps every
    SID slot (padding slots read as SID 0). segments_left may exceed the
    number of slots: that is exactly the forged header that process_at_node's
    minimum-length check rejects, so it must be representable.
    """
    routing_type: int
    next_header: int
    segments_left: int
    sids_rev: tuple[int, ...]

    def __post_init__(self):
        object.__setattr__(self, "sids_rev", tuple(self.sids_rev))
        _check_type(self.routing_type)
        _check_range("next_header", self.next_header, 0, 255)
        _check_range("segments_left", self.segments_left, 0, 255)
        top = (1 << (8 * SID_BYTES[self.routing_type])) - 1
        for sid in self.sids_rev:
            _check_range("SID", sid, 0, top)
        if self.size > MAX_HEADER_BYTES:
            raise ValueError(f"{len(self.sids_rev)} SIDs do not fit in a {MAX_HEADER_BYTES}-byte header")

    @classmethod
    def from_forward(cls, sids_fwd, routing_type=ROUTING_TYPE_CRH16,
                     next_header=DEFAULT_NEXT_HEADER):
        """Fresh header from a FORWARD-order path; Segments Left = n (as ns-3 SetPath)."""
        sids = list(sids_fwd)
        if not 1 <= len(sids) <= 255:
            raise ValueError(f"a CRH path has 1..255 SIDs (Segments Left is one byte), got {len(sids)}")
        return cls(routing_type=routing_type, next_header=next_header,
                   segments_left=len(sids), sids_rev=tuple(reversed(sids)))

    @property
    def sid_bytes(self):
        return SID_BYTES[self.routing_type]

    @property
    def size(self):
        """pad8(4 + n * SID size)."""
        return pad8(CRH_FIXED_BYTES + self.sid_bytes * len(self.sids_rev))

    @property
    def hdr_ext_len(self):
        return self.size // 8 - 1

    def encode(self):
        out = bytearray(self.size)
        struct.pack_into("!BBBB", out, 0, self.next_header, self.hdr_ext_len,
                         self.routing_type, self.segments_left)
        fmt = _SID_FMT[self.routing_type]
        off = OFF_SIDS
        for sid in self.sids_rev:
            struct.pack_into(fmt, out, off, sid)
            off += self.sid_bytes
        return bytes(out)

    @classmethod
    def _parse(cls, raw, exact):
        if not isinstance(raw, (bytes, bytearray, memoryview)):
            raise TypeError(f"expected bytes, got {type(raw).__name__}")
        b = bytes(raw)
        if len(b) < 8:
            raise CrhTruncated(f"a CRH is at least 8 bytes, got {len(b)}")
        next_header, hel, rtype, sl = b[:4]
        if rtype not in SID_BYTES:
            raise CrhWrongRoutingType(f"routing type {rtype} is not CRH-16 (5) or CRH-32 (6)",
                                      pointer=OFF_ROUTING_TYPE)
        total = (hel + 1) * 8
        if len(b) < total:
            raise CrhTruncated(f"Hdr Ext Len announces {total} bytes, only {len(b)} present")
        if exact and len(b) != total:
            raise CrhTrailingBytes(f"Hdr Ext Len announces {total} bytes, got {len(b)}")
        size = SID_BYTES[rtype]
        fmt = _SID_FMT[rtype]
        # every SID-sized slot, padding included (no count field; see module doc)
        sids = [struct.unpack_from(fmt, b, off)[0] for off in range(OFF_SIDS, total, size)]
        return cls(routing_type=rtype, next_header=next_header, segments_left=sl,
                   sids_rev=sids), total

    @classmethod
    def decode(cls, raw):
        """Parse exactly one CRH (len(raw) must equal its Hdr Ext Len size)."""
        return cls._parse(raw, exact=True)[0]

    @classmethod
    def decode_prefix(cls, raw):
        """Parse a CRH at the start of raw (payload may follow). Returns (header, nbytes)."""
        return cls._parse(raw, exact=False)

    def remaining_sids_fwd(self):
        """
        The SIDs still to visit, in visiting order: SID[SL-1], ..., SID[0].
        For a fresh header that is the whole forward path. Well defined for
        decoded headers too, because padding slots sit above index n-1.
        """
        if self.segments_left > len(self.sids_rev):
            raise ValueError("Segments Left points outside the SID list (malformed header)")
        return tuple(reversed(self.sids_rev[:self.segments_left]))

    def current_sid(self):
        """SID[Segments Left]: the SID a node has just decremented onto (ns-3 GetCurrentSid)."""
        if self.segments_left >= len(self.sids_rev):
            raise ValueError("Segments Left out of range for the SID list")
        return self.sids_rev[self.segments_left]


@dataclass(frozen=True)
class CrhProcessResult:
    """
    action       'deliver' (SL was 0), 'forward' (to next_sid), 'drop_malformed',
                 or 'ignore': not a CRH and SL = 0 (RFC 8200 4.4: skip the routing
                 header, process the Next Header; out_bytes = the input)
    next_sid     SID to look up in the CRH-FIB (caller's job), or None
    out_bytes    packet bytes with Segments Left updated; None when dropped
    reason       None, or 'wrong_type' / 'truncated' / 'min_length'
    icmp_code    ICMPv6 Parameter Problem code to send, or None
    icmp_pointer offset of the offending field inside the routing header
    """
    action: str
    next_sid: int | None = None
    out_bytes: bytes | None = None
    reason: str | None = None
    icmp_code: int | None = None
    icmp_pointer: int | None = None


def process_at_node(raw):
    """
    RFC 9631 section 5 forwarding step, as a pure function of the bytes.
    raw starts with the CRH; anything after it (payload) is passed through.

      0. Segments Left == 0: the packet is for this node -> deliver
         (RFC 8200 section 4.4: ignore the routing header, process Next Header)
      1. L = minimum CRH length; if L > Hdr Ext Len -> discard,
         ICMPv6 Parameter Problem Code 6, pointer to Segments Left
      2. decrement Segments Left
      3. current SID = SID[Segments Left]           (decrement THEN index)
      4. (caller) look the SID up in the CRH-FIB; no entry -> discard, Code 0;
         an entry with a multicast address while SL > 0 -> discard, Code 0
    """
    try:
        hdr, _total = CrhHeader._parse(raw, exact=False)
    except CrhWrongRoutingType as err:
        # RFC 8200 section 4.4, unrecognised Routing Type: with Segments Left
        # 0 the node ignores the header and processes the Next Header; only
        # SL > 0 is a Parameter Problem (Code 0, pointer -> Routing Type).
        # CrhWrongRoutingType implies at least 8 bytes, so byte 3 exists.
        if bytes(raw)[OFF_SEGMENTS_LEFT] == 0:
            return CrhProcessResult(action="ignore", out_bytes=bytes(raw), reason=err.reason)
        return CrhProcessResult(action="drop_malformed", reason=err.reason,
                                icmp_code=ICMP_CODE_ERRONEOUS_FIELD, icmp_pointer=err.pointer)
    except CrhDecodeError as err:
        return CrhProcessResult(
            action="drop_malformed", reason=err.reason,
            icmp_code=ICMP_CODE_ERRONEOUS_FIELD if err.pointer is not None else None,
            icmp_pointer=err.pointer)
    b = bytes(raw)
    if hdr.segments_left == 0:
        return CrhProcessResult(action="deliver", out_bytes=b)
    if min_hdr_ext_len(hdr.segments_left, hdr.routing_type) > hdr.hdr_ext_len:
        return CrhProcessResult(action="drop_malformed", reason="min_length",
                                icmp_code=ICMP_CODE_MIN_LENGTH, icmp_pointer=OFF_SEGMENTS_LEFT)
    sl = hdr.segments_left - 1
    out = bytearray(b)
    out[OFF_SEGMENTS_LEFT] = sl
    return CrhProcessResult(action="forward", next_sid=hdr.sids_rev[sl], out_bytes=bytes(out))


__all__ = [
    "ROUTING_TYPE_CRH16", "ROUTING_TYPE_CRH32", "SID_BYTES", "DEFAULT_NEXT_HEADER",
    "MAX_HEADER_BYTES", "OFF_HDR_EXT_LEN", "OFF_ROUTING_TYPE", "OFF_SEGMENTS_LEFT", "OFF_SIDS",
    "ICMP_CODE_ERRONEOUS_FIELD", "ICMP_CODE_MIN_LENGTH", "CrhDecodeError",
    "CrhWrongRoutingType", "CrhTruncated", "CrhTrailingBytes", "min_hdr_ext_len",
    "CrhHeader", "CrhProcessResult", "process_at_node",
]

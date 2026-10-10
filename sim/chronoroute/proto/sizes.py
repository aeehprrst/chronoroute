"""
sizes.py
--------
On-the-wire sizes of T-CRH and the headers we compare it with
(spec/tcrh-v1.md sections 2, 8 and 9).

Every IPv6 extension header is a whole number of 8-octet units, and its
Hdr Ext Len field counts those units NOT including the first 8 octets
(RFC 8200 section 4.4). So size = (HdrExtLen + 1) * 8.

    T-CRH  (this project)       pad8(12 + 3n)   12 fixed bytes, 3 per hop
    CRH-16 (RFC 9631, type 5)   pad8(4 + 2n)    4 fixed bytes, 2 per SID
    CRH-32 (RFC 9631, type 6)   pad8(4 + 4n)    4 fixed bytes, 4 per SID
    SRv6 SRH (RFC 8754)         8 + 16n         full IPv6 address per segment

The v0 code used an 8-byte CRH fixed part; RFC 9631's figure has 4 octets
(Next Header, Hdr Ext Len, Routing Type, Segments Left) before the SIDs.
"""

IPV6_HEADER_BYTES = 40      # fixed IPv6 header, added by encapsulation mode

TCRH_FIXED_BYTES = 12       # NH, HEL, Type, SL, Flags, NumHops, DevHop, Rsvd, Epoch_Base(4)
TCRH_ENTRY_BYTES = 3        # SID (2) + Delta (1)
TCRH_MAX_HOPS = 255         # Num Hops is one byte

CRH_FIXED_BYTES = 4         # NH, HEL, Type, SL
CRH16_SID_BYTES = 2
CRH32_SID_BYTES = 4

SRH_FIXED_BYTES = 8
SRH_SEGMENT_BYTES = 16

MODES = ("source", "encap")
HEADERS = ("tcrh", "crh16", "crh32", "srh")


def _check_count(n, upper=None):
    if isinstance(n, bool) or not isinstance(n, int):
        raise TypeError(f"segment count must be an int, got {type(n).__name__}")
    if n < 0:
        raise ValueError(f"segment count must be >= 0, got {n}")
    if upper is not None and n > upper:
        raise ValueError(f"segment count must be <= {upper}, got {n}")


def pad8(nbytes):
    """Round a byte count up to the next multiple of 8 (64-bit boundary)."""
    _check_count(nbytes)
    return -(-nbytes // 8) * 8


def hdr_ext_len(size_bytes):
    """Hdr Ext Len for an extension header of `size_bytes` (a multiple of 8, >= 8)."""
    _check_count(size_bytes)
    if size_bytes < 8 or size_bytes % 8:
        raise ValueError(f"extension header size must be a multiple of 8 and >= 8, got {size_bytes}")
    return size_bytes // 8 - 1


def tcrh_size(n):
    """T-CRH with n hops: pad8(12 + 3n). n is limited to 255 by Num Hops."""
    _check_count(n, TCRH_MAX_HOPS)
    return pad8(TCRH_FIXED_BYTES + TCRH_ENTRY_BYTES * n)


def crh16_size(n):
    """RFC 9631 CRH-16 with n SIDs: pad8(4 + 2n)."""
    _check_count(n)
    return pad8(CRH_FIXED_BYTES + CRH16_SID_BYTES * n)


def crh32_size(n):
    """RFC 9631 CRH-32 with n SIDs: pad8(4 + 4n)."""
    _check_count(n)
    return pad8(CRH_FIXED_BYTES + CRH32_SID_BYTES * n)


def srh_size(n):
    """RFC 8754 SRv6 SRH with n segments and no TLVs: 8 + 16n (already 8-aligned)."""
    _check_count(n)
    return SRH_FIXED_BYTES + SRH_SEGMENT_BYTES * n


_SIZE_FN = {"tcrh": tcrh_size, "crh16": crh16_size, "crh32": crh32_size, "srh": srh_size}


def encapsulation_overhead(n, mode="source", header="tcrh"):
    """
    Bytes a routing header adds to each packet (spec section 8).

    mode "source": the sending host inserts the header itself -> size(n).
    mode "encap" : a gateway wraps the packet in a new IPv6 header plus the
                   routing header (like SRv6 H.Encaps)  -> 40 + size(n).
    Experiments that report overhead must say which mode they assume.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if header not in _SIZE_FN:
        raise ValueError(f"header must be one of {HEADERS}, got {header!r}")
    size = _SIZE_FN[header](n)
    return size + (IPV6_HEADER_BYTES if mode == "encap" else 0)


__all__ = [
    "IPV6_HEADER_BYTES", "TCRH_FIXED_BYTES", "TCRH_ENTRY_BYTES", "TCRH_MAX_HOPS",
    "CRH_FIXED_BYTES", "CRH16_SID_BYTES", "CRH32_SID_BYTES", "SRH_FIXED_BYTES",
    "SRH_SEGMENT_BYTES", "MODES", "HEADERS", "pad8", "hdr_ext_len", "tcrh_size",
    "crh16_size", "crh32_size", "srh_size", "encapsulation_overhead",
]

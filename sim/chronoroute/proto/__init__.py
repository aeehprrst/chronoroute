"""
T-CRH wire format (spec/tcrh-v1.md), reference implementation.

Stable public API (import from here, not from the sub-modules):

    from chronoroute.proto import (
        TcrhHeader, build_header, encode_deltas, process_at_node, ingress_send,
        link_down_fallback,
        clock_u, epoch_base_at_ingress, serial_diff, is_late, utc_to_gps_ns,
        tcrh_size, crh16_size, srh_size, CrhHeader, crh_process_at_node,
    )

Sub-modules:
    timebase  deadline units, GPS time, unit clock, serial arithmetic (spec 4)
    tcrh      T-CRH header, delta encoding, per-node processing (spec 2-3, 5-6)
    crh       RFC 9631 CRH-16 / CRH-32 baseline
    sizes     header sizes and per-packet overhead (spec 8-9)

The golden vectors in spec/golden/*.json are the cross-implementation
contract; sim/tests/test_golden_vectors.py checks this package against them.
"""

from .timebase import *  # noqa: F401,F403
from .timebase import __all__ as _timebase_all
from .sizes import *  # noqa: F401,F403
from .sizes import __all__ as _sizes_all
from .tcrh import *  # noqa: F401,F403
from .tcrh import __all__ as _tcrh_all
from . import crh
from .crh import (
    ROUTING_TYPE_CRH16, ROUTING_TYPE_CRH32, CrhHeader, CrhProcessResult,
    CrhDecodeError, CrhWrongRoutingType, CrhTruncated, CrhTrailingBytes,
    min_hdr_ext_len, ICMP_CODE_MIN_LENGTH,
)
from .crh import process_at_node as crh_process_at_node

SPEC_VERSION = "tcrh-v1"

__all__ = sorted(set(_timebase_all) | set(_sizes_all) | set(_tcrh_all) | {
    "crh", "ROUTING_TYPE_CRH16", "ROUTING_TYPE_CRH32", "CrhHeader", "CrhProcessResult",
    "CrhDecodeError", "CrhWrongRoutingType", "CrhTruncated", "CrhTrailingBytes",
    "min_hdr_ext_len", "ICMP_CODE_MIN_LENGTH", "crh_process_at_node", "SPEC_VERSION",
})

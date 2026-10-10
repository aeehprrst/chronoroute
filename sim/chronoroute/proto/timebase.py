"""
timebase.py
-----------
The T-CRH time base (spec/tcrh-v1.md section 4).

Every time quantity that goes on the wire (Epoch_Base and every Delta) is a
count of the deadline unit `u`, chosen by the two UNIT bits in the Flags byte.
Everything in this module works in INTEGER nanoseconds of GPS time, because:

  * the spec says the ceil/floor that produce wire values must be exact
    (section 5.1): a budget of exactly 3.0 units must encode to 3, never 4.
    A float like 3.0000000001 would ceil to 4, so floats are refused here and
    must be converted once, explicitly, with seconds_to_ns() / ms_to_ns();
  * GPS time has no leap seconds, so a nanosecond count is continuous and
    two nodes' clocks can be compared with plain integer arithmetic.

All 32-bit comparisons use serial-number arithmetic so that a deadline just
after the 2^32 wrap still compares correctly with a clock just before it.
"""

from datetime import datetime, timedelta, timezone
from fractions import Fraction
import math

# ----- Deadline units (spec section 3, Flags bits 0x30) -----
# unit code -> unit length in nanoseconds
UNIT_NS = {
    0: 1_000_000,   # 1 ms     (v0-compatible)
    1: 100_000,     # 0.1 ms   (provisional v1 default)
    2: 250_000,     # 0.25 ms
    3: 125_000,     # 0.125 ms
}
DEFAULT_UNIT_CODE = 1

# ----- GPS timescale (spec section 4) -----
# GPS = UTC + 18 s. True since the last leap second (2016-12-31T23:59:60Z);
# before 2017-01-01 the offset was smaller, so we refuse those dates rather
# than silently produce a time that is off by whole seconds.
GPS_UTC_OFFSET_S = 18
GPS_EPOCH_UTC = datetime(1980, 1, 6, tzinfo=timezone.utc)
OFFSET_VALID_FROM_UTC = datetime(2017, 1, 1, tzinfo=timezone.utc)

NS_PER_S = 1_000_000_000
NS_PER_MS = 1_000_000

# ----- 32-bit serial arithmetic -----
MOD32 = 1 << 32
HALF32 = 1 << 31


def _require_int(name, value):
    """Wire arithmetic is integer-only; bool is an int in Python but never a time."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def unit_ns(unit_code):
    """Length of deadline unit `unit_code` in nanoseconds (ValueError if not 0..3)."""
    _require_int("unit_code", unit_code)
    if unit_code not in UNIT_NS:
        raise ValueError(f"unit code must be 0..3, got {unit_code}")
    return UNIT_NS[unit_code]


def u32(x):
    """Reduce an integer to the 32-bit field it is stored in (mod 2^32)."""
    _require_int("value", x)
    return x % MOD32


# --------------------------------------------------------------- conversions

def _exact(value):
    """Exact rational value of int / float / Fraction / Decimal / str input."""
    if isinstance(value, bool):
        raise TypeError("a time cannot be a bool")
    return Fraction(value)


def _round_half_up(q):
    """Nearest integer to the exact rational q, halves rounded up (portable to C)."""
    return math.floor(q + Fraction(1, 2))


def seconds_to_ns(seconds):
    """
    Convert a time in seconds to integer nanoseconds, rounding to the NEAREST ns.

    This is the one sanctioned float -> wire-arithmetic crossing. Rounding to
    the nearest nanosecond (not ceil) is deliberate: float noise such as
    0.1 * 3 = 0.30000000000000004 must land back on the intended value, and
    sub-nanosecond precision is physically meaningless for path budgets.
    The rounding is done on the exact binary value of the float, so every
    implementation that rounds half-up gets the same answer.
    """
    return _round_half_up(_exact(seconds) * NS_PER_S)


def ms_to_ns(ms):
    """Same as seconds_to_ns but the input is in milliseconds."""
    return _round_half_up(_exact(ms) * NS_PER_MS)


def utc_to_gps_ns(dt):
    """
    GPS time, in integer nanoseconds since the GPS epoch (1980-01-06T00:00:00Z),
    of the timezone-aware UTC instant `dt`.

    datetime counts days of exactly 86400 s (it ignores leap seconds), so the
    elapsed UTC count since the GPS epoch is short by the 18 leap seconds
    inserted since 1980; adding GPS_UTC_OFFSET_S gives continuous GPS time.
    datetime has microsecond resolution, so the result is a multiple of 1000.
    """
    if not isinstance(dt, datetime):
        raise TypeError("utc_to_gps_ns needs a datetime")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime is ambiguous; pass a timezone-aware UTC datetime")
    if dt < OFFSET_VALID_FROM_UTC:
        raise ValueError("GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on")
    td = dt - GPS_EPOCH_UTC
    # timedelta is normalised: 0 <= seconds < 86400, 0 <= microseconds < 10^6
    utc_us = (td.days * 86_400 + td.seconds) * 1_000_000 + td.microseconds
    return utc_us * 1_000 + GPS_UTC_OFFSET_S * NS_PER_S


def gps_ns_to_utc(t_gps_ns):
    """Inverse of utc_to_gps_ns (sub-microsecond part truncated toward the past)."""
    _require_int("t_gps_ns", t_gps_ns)
    utc_ns = t_gps_ns - GPS_UTC_OFFSET_S * NS_PER_S
    dt = GPS_EPOCH_UTC + timedelta(microseconds=utc_ns // 1_000)
    if dt < OFFSET_VALID_FROM_UTC:
        raise ValueError("GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on")
    return dt


def sim_to_gps_ns(t0_gps_ns, sim_time_s):
    """
    GPS time of simulation time `sim_time_s` (seconds), for a simulator whose
    time 0 is the GPS instant `t0_gps_ns` (spec section 4: simulators on a
    relative clock add their configured t0_gps to simulation time).
    """
    _require_int("t0_gps_ns", t0_gps_ns)
    return t0_gps_ns + seconds_to_ns(sim_time_s)


# --------------------------------------------------------------- unit clock

def clock_u(t_gps_ns, unit_code):
    """
    A node's unit clock: floor(t_gps / u) mod 2^32 (spec section 4).

    floor, because a node is "in" unit n for the whole interval [n*u, (n+1)*u).
    """
    _require_int("t_gps_ns", t_gps_ns)
    return (t_gps_ns // unit_ns(unit_code)) % MOD32


def epoch_base_at_ingress(t_gps_ns, unit_code):
    """
    Epoch_Base stamped per packet at ingress: ceil(T_ingress / u) mod 2^32.

    ceil, not floor: rounding the anchor UP can only add slack to every
    deadline, never remove it, so quantising the anchor cannot by itself make
    an on-time packet look late.
    """
    _require_int("t_gps_ns", t_gps_ns)
    u = unit_ns(unit_code)
    return (-(-t_gps_ns // u)) % MOD32


# --------------------------------------------------------------- serial arithmetic

def serial_diff(a, b):
    """
    Signed 32-bit serial difference a - b, in [-2^31, 2^31).

    Clocks and deadlines wrap at 2^32 (49.7 days at 1 ms, 4.97 days at
    0.1 ms). A path lasts far less than a second, so the true difference is
    always tiny and the wrapped difference recovers it exactly.
    """
    _require_int("a", a)
    _require_int("b", b)
    return ((a - b + HALF32) % MOD32) - HALF32


def is_late(now_u, deadline_u):
    """
    True when the clock has moved PAST the deadline unit.

    A packet arriving anywhere inside unit deadline_u is on time; it is late
    only from unit deadline_u + 1 on (spec section 6, "Late" means ...).
    """
    return serial_diff(now_u, deadline_u) > 0


__all__ = [
    "UNIT_NS", "DEFAULT_UNIT_CODE", "GPS_UTC_OFFSET_S", "GPS_EPOCH_UTC",
    "OFFSET_VALID_FROM_UTC", "NS_PER_S", "NS_PER_MS", "MOD32", "HALF32",
    "unit_ns", "u32", "seconds_to_ns", "ms_to_ns", "utc_to_gps_ns",
    "gps_ns_to_utc", "sim_to_gps_ns", "clock_u", "epoch_base_at_ingress",
    "serial_diff", "is_late",
]

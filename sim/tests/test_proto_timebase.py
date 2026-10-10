"""Tests for chronoroute.proto.timebase (spec/tcrh-v1.md section 4)."""

from datetime import datetime, timedelta, timezone
from fractions import Fraction

import pytest
from hypothesis import given, strategies as st

from chronoroute.proto import timebase as tb
from chronoroute.proto import (
    UNIT_NS, GPS_UTC_OFFSET_S, MOD32, clock_u, epoch_base_at_ingress, serial_diff,
    is_late, utc_to_gps_ns, gps_ns_to_utc, seconds_to_ns, ms_to_ns, sim_to_gps_ns, unit_ns, u32,
)

UTC = timezone.utc
u32s = st.integers(min_value=0, max_value=MOD32 - 1)


# ----------------------------------------------------------------- constants

def test_unit_table_matches_spec():
    assert UNIT_NS == {0: 1_000_000, 1: 100_000, 2: 250_000, 3: 125_000}
    assert tb.DEFAULT_UNIT_CODE == 1
    assert GPS_UTC_OFFSET_S == 18


@pytest.mark.parametrize("bad", [-1, 4, 255])
def test_unit_ns_rejects_unknown_codes(bad):
    with pytest.raises(ValueError):
        unit_ns(bad)


def test_unit_ns_rejects_non_int():
    with pytest.raises(TypeError):
        unit_ns(1.0)
    with pytest.raises(TypeError):
        unit_ns(True)


def test_u32():
    assert u32(MOD32) == 0
    assert u32(-1) == MOD32 - 1
    assert u32(5) == 5


# ----------------------------------------------------------------- GPS time

def test_gps_time_at_2017_new_year_is_the_known_value():
    # 2017-01-01T00:00:00Z = 13 510 days after the GPS epoch, plus 18 leap seconds:
    # GPS seconds 1 167 264 018 (the published value).
    assert utc_to_gps_ns(datetime(2017, 1, 1, tzinfo=UTC)) == 1_167_264_018 * 10**9


def test_gps_time_is_utc_plus_18_s_and_continuous():
    a = datetime(2026, 10, 10, 13, 58, tzinfo=UTC)
    b = a + timedelta(seconds=1, microseconds=7)
    assert utc_to_gps_ns(b) - utc_to_gps_ns(a) == 1_000_007_000
    # elapsed POSIX seconds since 1980-01-06 + 18
    posix_gps_epoch = 315_964_800
    assert utc_to_gps_ns(a) == (int(a.timestamp()) - posix_gps_epoch + 18) * 10**9


def test_gps_time_accepts_any_aware_timezone():
    ist = timezone(timedelta(hours=5, minutes=30))
    assert utc_to_gps_ns(datetime(2026, 10, 10, 19, 28, tzinfo=ist)) == \
        utc_to_gps_ns(datetime(2026, 10, 10, 13, 58, tzinfo=UTC))


def test_gps_time_rejects_naive_and_pre_2017():
    with pytest.raises(ValueError):
        utc_to_gps_ns(datetime(2026, 10, 10))
    with pytest.raises(ValueError):
        utc_to_gps_ns(datetime(2016, 12, 31, 23, 59, 59, tzinfo=UTC))
    with pytest.raises(TypeError):
        utc_to_gps_ns("2026-10-10")


def test_gps_round_trip():
    dt = datetime(2026, 10, 10, 13, 58, 0, 123456, tzinfo=UTC)
    assert gps_ns_to_utc(utc_to_gps_ns(dt)) == dt
    assert gps_ns_to_utc(utc_to_gps_ns(dt) + 999) == dt      # sub-microsecond truncated


def test_sim_to_gps_ns():
    t0 = utc_to_gps_ns(datetime(2026, 10, 10, tzinfo=UTC))
    assert sim_to_gps_ns(t0, 0.3) == t0 + 300_000_000
    assert sim_to_gps_ns(t0, 0.1 * 3) == t0 + 300_000_000      # float noise absorbed


# ----------------------------------------------------------------- exact conversion

def test_seconds_and_ms_to_ns_round_to_nearest_ns():
    assert 0.1 * 3 != 0.3                                       # the float trap
    assert seconds_to_ns(0.1 * 3) == 300_000_000
    assert ms_to_ns(0.1 * 3) == 300_000
    assert ms_to_ns("2.5") == 2_500_000
    assert seconds_to_ns(Fraction(1, 3)) == 333_333_333
    assert ms_to_ns(Fraction(1, 2_000_000)) == 1                # exactly 0.5 ns: half up
    assert ms_to_ns(Fraction(1, 2_000_001)) == 0


def test_conversion_rejects_bool():
    with pytest.raises(TypeError):
        seconds_to_ns(True)


# ----------------------------------------------------------------- unit clock

def test_clock_u_is_floor():
    assert clock_u(0, 0) == 0
    assert clock_u(999_999, 0) == 0
    assert clock_u(1_000_000, 0) == 1
    assert clock_u(1_000_000_123, 1) == 10_000
    assert clock_u(1_000_000_123, 2) == 4_000
    assert clock_u(1_000_000_123, 3) == 8_000


def test_epoch_base_is_ceil():
    assert epoch_base_at_ingress(0, 1) == 0
    assert epoch_base_at_ingress(1, 1) == 1
    assert epoch_base_at_ingress(100_000, 1) == 1                 # exact multiple: no extra unit
    assert epoch_base_at_ingress(100_001, 1) == 2
    assert epoch_base_at_ingress(1_000_000_123, 2) == 4001


def test_clock_and_epoch_wrap_mod_2_32():
    u = UNIT_NS[1]
    assert clock_u(MOD32 * u, 1) == 0
    assert clock_u(MOD32 * u - 1, 1) == MOD32 - 1
    assert epoch_base_at_ingress(MOD32 * u - 1, 1) == 0           # ceil reaches 2^32 -> 0


def test_clock_rejects_float_time():
    with pytest.raises(TypeError):
        clock_u(1.5e9, 1)
    with pytest.raises(TypeError):
        epoch_base_at_ingress(1.5e9, 1)


@given(st.integers(min_value=0, max_value=2**63), st.integers(min_value=0, max_value=3))
def test_epoch_never_before_ingress_and_within_one_unit(t, uc):
    u = UNIT_NS[uc]
    e = -(-t // u)                         # unreduced ceil
    assert epoch_base_at_ingress(t, uc) == e % MOD32
    assert 0 <= e * u - t < u
    assert clock_u(t, uc) == (t // u) % MOD32
    assert e - t // u in (0, 1)


# ----------------------------------------------------------------- serial arithmetic

def test_serial_diff_examples():
    assert serial_diff(5, 3) == 2
    assert serial_diff(3, 5) == -2
    assert serial_diff(0, MOD32 - 1) == 1
    assert serial_diff(MOD32 - 1, 0) == -1
    assert serial_diff(2**31, 0) == -2**31                       # half range maps to the negative end
    assert serial_diff(2**31 - 1, 0) == 2**31 - 1


def test_regression_bug8_wrap_safe_lateness():
    """Bug #8 (header.py:113): v0 compared raw 32-bit values with no wrap handling,
    so a clock that wrapped to 0 looked EARLIER than a deadline of 2^32-1, and a
    deadline that wrapped to 0 looked already passed."""
    assert is_late(0, MOD32 - 1)          # one unit past the deadline, across the wrap
    assert not is_late(MOD32 - 1, 0)      # one unit before a wrapped deadline


def test_is_late_inside_the_deadline_unit_is_on_time():
    assert not is_late(1006, 1006)
    assert not is_late(1005, 1006)
    assert is_late(1007, 1006)


@given(u32s, u32s)
def test_serial_diff_antisymmetry(a, b):
    d = serial_diff(a, b)
    assert -2**31 <= d < 2**31
    if d != -2**31:
        assert serial_diff(b, a) == -d
    else:
        assert serial_diff(b, a) == -2**31   # the one value with no positive mirror
    assert (b + d) % MOD32 == a


@given(u32s, st.integers(min_value=-2**31 + 1, max_value=2**31 - 1))
def test_serial_diff_recovers_small_offsets_across_the_wrap(a, d):
    assert serial_diff((a + d) % MOD32, a) == d
    assert is_late((a + d) % MOD32, a) == (d > 0)

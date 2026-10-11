"""Tests for chronoroute.orbit.frames: GMST, TEME <-> ECEF, WGS84 geodetic, elevation."""

import math
from datetime import datetime, timezone

import numpy as np
import pytest
from sgp4.api import jday
from sgp4.propagation import gstime

from chronoroute.data.omm import datetime_to_ns
from chronoroute.orbit import frames


def test_gmst_at_2026_09_10_midnight_is_349_04_deg():
    """Acceptance (task): GMST at 2026-09-10T00:00Z = 349.04 deg."""
    jd, fr = frames.jday_from_ns(datetime_to_ns(datetime(2026, 9, 10, tzinfo=timezone.utc)))
    assert round(math.degrees(frames.gmst_rad(jd, fr)), 2) == 349.04


def test_gmst_is_sgp4s_own_gstime():
    times = [datetime(2026, 10, 10, 14, 2, 22, tzinfo=timezone.utc),
             datetime(2000, 1, 1, 12, tzinfo=timezone.utc),
             datetime(2031, 6, 30, 23, 59, 59, 999999, tzinfo=timezone.utc)]
    jd, fr = frames.jday_from_ns([datetime_to_ns(t) for t in times])
    got = frames.gmst_rad(jd, fr)
    for j, f, value in zip(jd, fr, got):
        assert value == gstime(float(j) + float(f))                       # bit-identical
    # and the same angle when the Julian date comes from sgp4's own jday. gstime takes jd + fr
    # as one double (resolution ~40 us at today's dates), so allow 1e-8 rad (~7 cm at 7000 km).
    for t, value in zip(times, got):
        j, f = jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)
        assert abs(value - gstime(j + f)) < 1e-8


def test_jday_from_ns_matches_sgp4_jday():
    t = datetime_to_ns(datetime(2026, 10, 10, 14, 2, 22, tzinfo=timezone.utc))
    assert frames.jday_from_ns(t) == jday(2026, 10, 10, 14, 2, 22)
    jd, fr = frames.jday_from_ns([t, t + 86_400 * 10**9])
    assert jd[1] - jd[0] == 1.0 and fr[0] == fr[1]


def test_teme_to_ecef_is_a_rotation_about_z():
    rng = np.random.default_rng(7)
    r = rng.normal(size=(5, 3, 3)) * 7000
    v = rng.normal(size=(5, 3, 3)) * 7
    gmst = np.array([0.0, 1.0, 4.0])
    r_e, v_e = frames.teme_to_ecef(r, v, gmst)
    assert np.allclose(np.linalg.norm(r_e, axis=-1), np.linalg.norm(r, axis=-1), rtol=0, atol=1e-9)
    assert np.array_equal(r_e[..., 2], r[..., 2])
    assert np.allclose(r_e[:, 0], r[:, 0], atol=1e-12)                 # gmst 0: same position
    # gmst 0: velocity only loses the Earth's rotation, v_e = v - w x r
    w = frames.EARTH_ROTATION_RAD_S
    expected = v[:, 0] - np.cross([0, 0, w], r[:, 0])
    assert np.allclose(v_e[:, 0], expected, atol=1e-12)
    # a point on the x axis seen after the Earth turned 90 deg sits on the -y axis
    r_e, _ = frames.teme_to_ecef(np.array([7000.0, 0, 0]), np.zeros(3), math.pi / 2)
    assert np.allclose(r_e, [0, -7000.0, 0], atol=1e-9)


def test_ecef_to_teme_inverts_teme_to_ecef():
    rng = np.random.default_rng(3)
    r = rng.normal(size=(4, 2, 3)) * 7000
    v = rng.normal(size=(4, 2, 3)) * 7
    gmst = np.array([0.3, 5.9])
    back_r, back_v = frames.ecef_to_teme(*frames.teme_to_ecef(r, v, gmst), gmst)
    assert np.allclose(back_r, r, atol=1e-9) and np.allclose(back_v, v, atol=1e-12)


def test_geodetic_known_points():
    a, b = frames.WGS84_A_KM, frames.WGS84_B_KM
    assert np.allclose(frames.geodetic_to_ecef(0, 0, 0), [a, 0, 0], atol=1e-9)
    assert np.allclose(frames.geodetic_to_ecef(0, 90, 0), [0, a, 0], atol=1e-9)
    assert np.allclose(frames.geodetic_to_ecef(90, 0, 0), [0, 0, b], atol=1e-9)
    assert np.allclose(frames.geodetic_to_ecef(-90, 0, 10), [0, 0, -b - 10], atol=1e-9)
    assert abs(b - 6356.752314245) < 1e-6                                  # WGS84 polar radius


def test_geodetic_round_trip_ground_to_geo():
    rng = np.random.default_rng(11)
    lat = rng.uniform(-90, 90, 2000)
    lon = rng.uniform(-180, 180, 2000)
    h = rng.uniform(-1, 40_000, 2000)
    lat2, lon2, h2 = frames.ecef_to_geodetic(frames.geodetic_to_ecef(lat, lon, h))
    assert np.max(np.abs(lat2 - lat)) < 1e-9
    mask = np.abs(lat) < 89.999                                            # longitude undefined at a pole
    assert np.max(np.abs(((lon2 - lon + 180) % 360) - 180)[mask]) < 1e-9
    assert np.max(np.abs(h2 - h)) < 1e-6                                   # under a millimetre


def test_elevation_angles():
    lat, lon = 13.0, 80.0
    ground = frames.geodetic_to_ecef(lat, lon, 0.0)
    overhead = frames.geodetic_to_ecef(lat, lon, 550.0)                   # straight up the normal
    assert abs(frames.elevation_deg(ground, overhead, lat, lon) - 90.0) < 1e-9
    # a point along the local horizon (perpendicular to the normal) has elevation 0
    up = overhead - ground
    up /= np.linalg.norm(up)
    horizon_dir = np.cross(up, [0, 0, 1.0])
    target = ground + 1000 * horizon_dir / np.linalg.norm(horizon_dir)
    assert abs(frames.elevation_deg(ground, target, lat, lon)) < 1e-9
    below = ground - 500 * up
    assert frames.elevation_deg(ground, below, lat, lon) == pytest.approx(-90.0)

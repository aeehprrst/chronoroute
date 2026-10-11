"""Tests for chronoroute.topo.geometry: the 80 km line-of-sight rule and light time in ns."""

import math

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from chronoroute.orbit import frames
from chronoroute.topo import geometry

R_463 = frames.WGS84_A_KM + 463.0


def _brute_min_height(pa, pb, n=20001):
    """Reference: sample the segment densely and take the lowest geodetic height."""
    t = np.linspace(0.0, 1.0, n)
    pts = np.asarray(pa)[None, :] + t[:, None] * (np.asarray(pb) - np.asarray(pa))[None, :]
    return float(frames.ecef_to_geodetic(pts)[2].min())


def _sat(lat_deg, lon_deg, h_km=463.0):
    return frames.geodetic_to_ecef(lat_deg, lon_deg, h_km)


def test_propagation_ns_rounds_to_nearest_and_matches_c():
    # 299.792458 km is exactly 1 ms of light time
    assert geometry.propagation_ns(299.792458) == 1_000_000
    assert geometry.C_M_PER_S == 299_792_458
    d = np.array([0.0, 1.0, 1000.0, 4514.0])
    out = geometry.propagation_ns(d)
    assert out.dtype == np.int64
    exact = d * 1e12 / 299_792_458
    assert np.all(np.abs(out - exact) <= 0.5)
    assert geometry.propagation_ns(np.nan) == -1          # a failed position never becomes 0 ns


def test_processing_delay_is_the_existing_models_half_millisecond():
    assert geometry.PROCESSING_NS == 500_000


def test_min_height_matches_brute_force_on_grazing_segments():
    """Golden-section search equals dense sampling to better than 1 m."""
    rng = np.random.default_rng(1)
    for _ in range(25):
        lat, lon = rng.uniform(-60, 60), rng.uniform(-180, 180)
        sep = rng.uniform(5, 40)                       # degrees of arc between the satellites
        bearing = rng.uniform(0, 360)
        lat2 = lat + sep * math.cos(math.radians(bearing))
        lon2 = lon + sep * math.sin(math.radians(bearing))
        pa, pb = _sat(lat, lon), _sat(max(-89, min(89, lat2)), lon2)
        got = float(geometry.segment_min_height_km(pa, pb))
        assert got == pytest.approx(_brute_min_height(pa, pb), abs=1e-3)


def test_bounds_are_certified():
    """r_min - a <= true lowest height <= r_min - b, on random segments."""
    rng = np.random.default_rng(2)
    pa = np.array([_sat(rng.uniform(-80, 80), rng.uniform(-180, 180)) for _ in range(200)])
    pb = np.array([_sat(rng.uniform(-80, 80), rng.uniform(-180, 180)) for _ in range(200)])
    r_min, _ = geometry.closest_approach(pa, pb)
    outside = r_min > frames.WGS84_A_KM + 1                 # segments that stay outside the Earth
    exact = geometry.segment_min_height_km(pa[outside], pb[outside])
    assert np.all(geometry.height_lower_bound_km(pa[outside], pb[outside]) <= exact + 1e-9)
    assert np.all(exact <= r_min[outside] - frames.WGS84_B_KM + 1e-9)


def test_segment_clears_decides_like_the_exact_height():
    rng = np.random.default_rng(3)
    pa, pb = [], []
    # many segments with closest approach in or near the ambiguous 21 km band
    for _ in range(400):
        lat, lon = rng.uniform(-85, 85), rng.uniform(-180, 180)
        sep = rng.uniform(30, 45)
        bearing = rng.uniform(0, 360)
        pa.append(_sat(lat, lon))
        pb.append(_sat(np.clip(lat + sep * math.cos(math.radians(bearing)), -89, 89),
                       lon + sep * math.sin(math.radians(bearing))))
    pa, pb = np.array(pa), np.array(pb)
    got = geometry.segment_clears(pa, pb, 80.0)
    r_min, _ = geometry.closest_approach(pa, pb)
    inside_earth = r_min < frames.WGS84_A_KM
    exact = np.where(inside_earth, -1.0, 0.0)
    exact[~inside_earth] = geometry.segment_min_height_km(pa[~inside_earth], pb[~inside_earth])
    assert np.array_equal(got, exact >= 80.0)
    assert got.any() and (~got).any()                       # both outcomes really occur


def test_hypatia_range_at_463_km():
    """The 80 km rule allows about 4,514 km at 463 km (plan section 2 row 7), on a sphere-ish Earth."""
    # two satellites over the equator, separated in longitude
    def ok(sep_deg):
        return bool(geometry.segment_clears(_sat(0.0, 0.0), _sat(0.0, sep_deg), 80.0))
    lo, hi = 10.0, 60.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    length = float(np.linalg.norm(_sat(0.0, lo) - _sat(0.0, 0.0)))
    # at the equator the surface is at radius a, so the limit is 2*sqrt(r^2 - (a+80)^2)
    a = frames.WGS84_A_KM
    expect = 2 * math.sqrt((a + 463.0) ** 2 - (a + 80.0) ** 2)
    assert length == pytest.approx(expect, abs=0.5)
    assert 4_500 < length < 4_530


def test_nan_positions_never_clear():
    pa = np.array([[np.nan, 0.0, 0.0]])
    pb = np.array([[R_463, 0.0, 0.0]])
    assert not geometry.segment_clears(pa, pb, 80.0)[0]


@settings(max_examples=150, deadline=None)
@given(st.floats(-70, 70), st.floats(-180, 180), st.floats(0.5, 30), st.floats(0, 360))
def test_short_links_always_clear(lat, lon, sep, bearing):
    """Any two satellites at 463 km less than 30 deg of arc apart clear 80 km (chord dips < 300 km)."""
    lat2 = max(-89.0, min(89.0, lat + sep * math.cos(math.radians(bearing))))
    lon2 = lon + sep * math.sin(math.radians(bearing))
    assert geometry.segment_clears(_sat(lat, lon), _sat(lat2, lon2), 80.0)

"""Tests for chronoroute.orbit.propagate: vectorised SGP4 (SatrecArray) on the real fleet."""

import json
from datetime import datetime, timezone
from functools import cache
from pathlib import Path

import numpy as np
import pytest
from sgp4.api import Satrec

from chronoroute.data import omm, snapshot
from chronoroute.orbit import frames
from chronoroute.orbit.propagate import (SatelliteArray, argument_of_latitude_deg, as_ns_list,
                                         osculating_raan_deg)

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
HOUR = 3600 * 10**9


@cache
def fleet():
    return snapshot.load_pinned(PINNED, "supgp")


@cache
def sats():
    return SatelliteArray.from_screen(fleet().screen)


def times():
    t0 = fleet().fetched_ns
    return [t0, t0 + HOUR, t0 + 24 * HOUR, t0 - 6 * HOUR + 123_456_789]


@pytest.mark.parametrize("norad", [44714, 100001, 100880, 60929])
def test_vectorised_positions_equal_single_satellite_sgp4_exactly(norad):
    """Acceptance (task): a known satellite agrees with Satrec.sgp4 exactly."""
    state = sats().propagate(times())
    i = sats().index[norad]
    record = fleet().records[i]
    single = Satrec()
    from sgp4 import omm as sgp4_omm
    sgp4_omm.initialize(single, record.sgp4_fields())            # a fresh, independent Satrec
    for k, t in enumerate(times()):
        jd, fr = omm.ns_to_jd(t)
        error, r, v = single.sgp4(jd, fr)
        assert error == state.error[i, k] == 0
        assert tuple(state.r_teme[i, k]) == r and tuple(state.v_teme[i, k]) == v


def test_ecef_is_teme_rotated_by_gmst():
    t = times()
    state = sats().propagate(t)
    jd, fr = frames.jday_from_ns(t)
    for k in range(len(t)):
        theta = frames.gmst_rad(float(jd[k]), float(fr[k]))
        assert state.gmst[k] == theta
        c, s = np.cos(theta), np.sin(theta)
        r = state.r_teme[:, k]
        expected = np.stack([c * r[:, 0] + s * r[:, 1], -s * r[:, 0] + c * r[:, 1], r[:, 2]], -1)
        assert np.allclose(state.r_ecef[:, k], expected, rtol=0, atol=1e-9)


def test_fleet_altitudes_and_speeds_are_physical():
    state = sats().propagate([fleet().fetched_ns])
    assert state.ok.all()
    height = state.height[:, 0]
    assert 150 < np.min(height) and np.max(height) < 700                 # every Starlink is in LEO
    assert 470 < np.median(height) < 490
    speed = np.linalg.norm(state.v_teme[:, 0], axis=1)
    assert 7.4 < np.min(speed) and np.max(speed) < 7.9                   # circular LEO speeds, km/s
    # ECEF speed is lower by up to the Earth's surface speed at that radius
    assert np.all(np.linalg.norm(state.v_ecef[:, 0], axis=1) < speed + 0.6)
    assert np.all(np.abs(state.lat[:, 0]) <= 98)


def test_failed_satellites_are_nan_and_flagged():
    good = fleet().records[0]
    template = omm.parse_omm_json(json.dumps([dict(good.values)]))[0]
    template["ECCENTRICITY"] = omm.JsonNumber("1.2", 1.2)      # SGP4 error 1: e >= 1
    template["NORAD_CAT_ID"] = omm.JsonNumber("999999", 999999)
    bad = omm.OmmRecord.from_object(template)
    array = SatelliteArray([good, bad])
    state = array.propagate([fleet().fetched_ns])
    assert state.error[0, 0] == 0 and state.error[1, 0] != 0
    assert np.isfinite(state.r_ecef[0, 0]).all()
    for field in ("r_teme", "v_teme", "r_ecef", "v_ecef"):
        assert np.isnan(getattr(state, field)[1, 0]).all()
    assert np.isnan(state.height[1, 0]) and not state.ok[1, 0]


def test_ids_are_norad_ids_not_satnums():
    norads = [r.norad for r in fleet().records]
    assert sats().norad.tolist() == norads and max(norads) == 100_880
    assert all(sats().satrec(n).satnum == omm.SATNUM_PLACEHOLDER for n in (44714, 100880))
    sub = sats().subset([100880, 44714])
    assert sub.norad.tolist() == [100880, 44714]
    with pytest.raises(ValueError):
        SatelliteArray([fleet().records[0], fleet().records[0]])


def test_time_inputs():
    t = datetime(2026, 10, 10, 14, 2, 22, tzinfo=timezone.utc)
    assert as_ns_list(t) == [fleet().fetched_ns]
    assert as_ns_list([fleet().fetched_ns, t]) == [fleet().fetched_ns] * 2
    for bad in (1.5e18, datetime(2026, 10, 10), True, []):
        with pytest.raises((TypeError, ValueError)):
            as_ns_list(bad)


def test_argument_of_latitude_and_node_from_a_state_vector():
    # Circular orbit, node at 30 deg, inclination 53 deg, satellite 40 deg past the node.
    raan, inc, u = np.radians([30.0, 53.0, 40.0])
    node = np.array([np.cos(raan), np.sin(raan), 0.0])
    normal = np.array([np.sin(raan) * np.sin(inc), -np.cos(raan) * np.sin(inc), np.cos(inc)])
    in_plane = np.cross(normal, node)
    r = 6900 * (np.cos(u) * node + np.sin(u) * in_plane)
    v = 7.6 * (-np.sin(u) * node + np.cos(u) * in_plane)
    assert argument_of_latitude_deg(r, v) == pytest.approx(40.0, abs=1e-9)
    assert osculating_raan_deg(r, v) == pytest.approx(30.0, abs=1e-9)
    # Flying the other way round, the ascending node is the old descending node (210 deg)
    # and the satellite is 140 deg past it.
    assert osculating_raan_deg(r, -v) == pytest.approx(210.0, abs=1e-9)
    assert argument_of_latitude_deg(r, -v) == pytest.approx(140.0, abs=1e-9)

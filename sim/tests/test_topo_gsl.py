"""Tests for chronoroute.topo.gsl: 25 deg mask (ASSUMED); which satellites are used (MODELLED):
sticky top-4 with hysteresis (default) or top-4 re-picked every step (the original variant)."""

import numpy as np
import pytest

from chronoroute.data import cities
from chronoroute.orbit import frames
from chronoroute.topo import gsl

PER_STEP = gsl.GslParams(25.0, 4, gsl.POLICY_PER_STEP)


def _station(name="Chennai", g=12):
    return gsl.ground_station_from_city(cities.city_by_name(name), g)


def test_defaults_are_the_documented_policy():
    p = gsl.GslParams()
    assert (p.min_elevation_deg, p.max_links_per_gs) == (25.0, 4)
    assert p.as_dict() == {"min_elevation_deg": 25.0, "max_links_per_gs": 4, "policy": "sticky_top_k"}
    assert gsl.POLICIES == ("sticky_top_k", "highest_elevation_top_k")
    assert (gsl.MASK_LABEL, gsl.POLICY_LABEL) == ("ASSUMED", "MODELLED")
    with pytest.raises(ValueError):
        gsl.GslParams(policy="nearest")
    with pytest.raises(ValueError):
        gsl.GslParams(max_links_per_gs=0)


def test_sticky_keeps_a_visible_satellite_and_refills_only_free_beams():
    # 4 satellites, k = 2. Step 0: A (60) and B (50) are the two highest.
    # Step 1: C rises to 70 (higher than both) -> sticky keeps A and B.
    # Step 2: B sets below the mask -> its beam goes to the highest free one (C, not D).
    # Step 3: everything visible again, nothing set -> still A and C.
    elev = np.array([
        [60.0, 55.0, 50.0, 45.0],     # A
        [50.0, 40.0, 20.0, 80.0],     # B
        [30.0, 70.0, 75.0, 30.0],     # C
        [26.0, 26.0, 40.0, 26.0],     # D
    ])
    ids = np.arange(4)
    visible, sticky = gsl.select_links(elev, ids, gsl.GslParams(25.0, 2))
    assert sticky.T.tolist() == [[True, True, False, False], [True, True, False, False],
                                 [True, False, True, False], [True, False, True, False]]
    # the original policy re-picks the two highest at every step instead
    _, per_step = gsl.select_links(elev, ids, gsl.GslParams(25.0, 2, gsl.POLICY_PER_STEP))
    assert per_step.T.tolist() == [[True, True, False, False], [True, False, True, False],
                                   [True, False, True, False], [True, True, False, False]]
    assert not np.any(sticky & ~visible)


def test_sticky_switches_far_less_often_on_random_passes():
    # smooth passes: elevation of satellite i is a bump centred at a random step
    rng = np.random.default_rng(11)
    t = np.arange(400)
    centre = rng.uniform(0, 400, size=60)
    elev = 80.0 - np.abs(t[None, :] - centre[:, None]) * 0.6
    visible, sticky = gsl.select_links(elev, np.arange(60))
    _, per_step = gsl.select_links(elev, np.arange(60), PER_STEP)
    drops = lambda sel: int(np.sum(sel[:, :-1] & ~sel[:, 1:]))
    drops_while_visible = lambda sel: int(np.sum(sel[:, :-1] & ~sel[:, 1:] & visible[:, 1:]))
    assert drops_while_visible(sticky) == 0            # a link only ends when its satellite sets
    assert drops_while_visible(per_step) > 0
    assert drops(sticky) < drops(per_step)
    assert np.all(sticky.sum(axis=0) == np.minimum(4, visible.sum(axis=0)))


def test_station_is_the_city_on_the_ellipsoid():
    gs = _station()
    city = cities.city_by_name("Chennai")
    assert np.allclose(gs.ecef_km, city.ecef_km)
    assert (gs.lat_text, gs.lon_text) == (city.lat_text, city.lon_text)


def test_zenith_satellite_has_elevation_90_and_horizon_0():
    gs = _station()
    above = frames.geodetic_to_ecef(gs.lat_deg, gs.lon_deg, 463.0)
    assert float(gsl.elevation_deg(gs, above)) == pytest.approx(90.0, abs=1e-6)
    # a point far away on the local horizontal plane
    east = np.array([-np.sin(np.radians(gs.lon_deg)), np.cos(np.radians(gs.lon_deg)), 0.0])
    assert float(gsl.elevation_deg(gs, np.asarray(gs.ecef_km) + 1000.0 * east)) == pytest.approx(0.0, abs=1e-9)


def test_selection_top_k_by_elevation_with_node_id_tie_break():
    elev = np.array([
        [30.0, 10.0],
        [80.0, 26.0],
        [25.0, 25.0],      # exactly at the mask counts as visible
        [24.999, 90.0],
        [60.0, np.nan],    # no position: never visible
        [60.0, 30.0],      # same elevation as row 4 at step 0, higher node id
    ])
    node_ids = np.array([10, 11, 12, 13, 14, 15])
    for policy in gsl.POLICIES:                        # the first step is the same for both
        visible, selected = gsl.select_links(elev, node_ids, gsl.GslParams(25.0, 4, policy))
        assert visible[:, 0].tolist() == [True, True, True, False, True, True]
        assert visible[:, 1].tolist() == [False, True, True, True, False, True]
        # step 0: 5 visible -> top 4 = 80, 60 (id 14), 60 (id 15), 30; the 25 deg one is left out
        assert selected[:, 0].tolist() == [True, True, False, False, True, True]
        # step 1: 3 visible -> all of them
        assert selected[:, 1].tolist() == [False, True, True, True, False, True]
        # tie: k=2 -> 80 then the lower id of the two 60s
        _, sel2 = gsl.select_links(elev, node_ids, gsl.GslParams(25.0, 2, policy))
        assert sel2[:, 0].tolist() == [False, True, False, False, True, False]


@pytest.mark.parametrize("policy", gsl.POLICIES)
def test_never_more_than_k_and_only_visible(policy):
    rng = np.random.default_rng(5)
    elev = rng.uniform(-90, 90, size=(300, 50))
    visible, selected = gsl.select_links(elev, np.arange(300), gsl.GslParams(policy=policy))
    assert np.all(selected.sum(axis=0) == np.minimum(4, visible.sum(axis=0)))
    assert not np.any(selected & ~visible)
    assert np.all(elev[selected] >= 25.0)

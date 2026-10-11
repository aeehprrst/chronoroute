"""Synthetic Walker presets and the 20 science pairs (fwd/presets.py)."""

import numpy as np

from chronoroute.data import cities
from chronoroute.fwd import presets
from chronoroute.orbit import elements, planes
from chronoroute.orbit.propagate import SatelliteArray, argument_of_latitude_deg, osculating_raan_deg

T0 = 1791640800000000000     # 2026-10-10T14:00:00Z


def test_science_pairs_are_the_plan_pairs_and_all_cities_exist():
    names = [c.name for c in cities.load_cities()]
    pairs, report = presets.science_pairs(names)
    assert len(presets.SCIENCE_PAIRS_PLAN) == 20 and len(pairs) == 20
    assert report["missing"] == [] and report["name_mapping"] == {"São Paulo": "Sao Paulo"}
    assert ("Chennai", "London") in pairs and ("Sao Paulo", "Tokyo") in pairs
    short = presets.science_pairs([n for n in names if n != "Lima"])[1]
    assert short["used"] == 19 and short["missing"][0]["missing"] == ["Lima"]


def test_walker_elements_follow_the_walker_delta_rule():
    p = presets.WALKER_PRESETS["C1"]
    objs = presets.walker_objects(p, T0)
    assert len(objs) == 480
    o = {(x["NORAD_CAT_ID"] - presets.SYNTHETIC_NORAD_BASE) // 1000 * 100
         + (x["NORAD_CAT_ID"] - presets.SYNTHETIC_NORAD_BASE) % 1000: x for x in objs}
    assert o[0]["RA_OF_ASC_NODE"] == 0.0 and o[100]["RA_OF_ASC_NODE"] == 15.0
    assert o[1]["MEAN_ANOMALY"] == 18.0                                  # 360 / 20
    assert abs(o[100]["MEAN_ANOMALY"] - 0.75) < 1e-12                     # F * 360 / T = 360 / 480
    assert abs(elements.altitude_km([o[0]["MEAN_MOTION"]])[0] - 550.0) < 1e-9


def test_presets_go_through_the_real_pipeline():
    for name, (n_planes, size, shell) in {"C1": (24, 20, "53.0deg-550km"), "C2": (72, 22, "53.0deg-550km"),
                                          "C2b": (72, 22, "53.0deg-480km")}.items():
        fleet = presets.walker_fleet(presets.WALKER_PRESETS[name], T0)
        assert fleet.count == n_planes * size and sum(fleet.excluded.values()) == 0
        geo = planes.build_fleet_geometry(fleet.records, T0, satrecs=fleet.satrecs)
        assert [s.shell_id for s in geo.shells] == [shell]
        assert len(geo.shells[0].planes) == n_planes and {p.size for p in geo.shells[0].planes} == {size}


def test_sgp4_positions_of_a_preset_are_on_the_intended_orbits():
    fleet = presets.walker_fleet(presets.WALKER_PRESETS["C2b"], T0)
    st = SatelliteArray(fleet.records, satrecs=fleet.satrecs).propagate([T0])
    r = np.linalg.norm(st.r_teme[:, 0], axis=1)
    assert np.all(np.abs(r - (6378.137 + 480)) < 25)                    # Kozai vs Brouwer: a few km
    raan = osculating_raan_deg(st.r_teme[:, 0], st.v_teme[:, 0])
    assert np.all(np.abs(((raan - np.repeat(np.arange(72) * 5.0, 22)) + 180) % 360 - 180) < 0.5)
    u = argument_of_latitude_deg(st.r_teme[:22, 0], st.v_teme[:22, 0])
    assert np.all(np.abs(((u - np.arange(22) * 360 / 22) + 180) % 360 - 180) < 0.5)

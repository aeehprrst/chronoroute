"""Tests for chronoroute.orbit.shells (DERIVED shells) on the pinned real fleet and on
synthetic constellations whose answer is known."""

import json
import math
import random
from functools import cache
from pathlib import Path

import numpy as np
import pytest

from chronoroute.data import omm, snapshot
from chronoroute.orbit import elements, shells

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"

# Reference counts: 06_research_live-data.md section 4, measured on the GP file of this
# snapshot on 2026-10-10. (layer, inclination, altitude label km) -> count.
REFERENCE = {
    ("broadband", 53.2, 463): 3098,
    ("broadband", 43.0, 483): 3229,
    ("broadband", 97.3, 466): 1431,      # "97.3 deg 465-466 km"; the mode is at 465.5 km
    ("broadband", 70.0, 572): 326,
    ("broadband", 70.0, 476): 332,
}


@cache
def catalog(source):
    fleet = snapshot.load_pinned(PINNED, source)
    return shells.infer_shells(fleet.records, fleet.fetched_ns)


@cache
def catalog_with(source, **params):
    fleet = snapshot.load_pinned(PINNED, source)
    return shells.infer_shells(fleet.records, fleet.fetched_ns, shells.ShellParams(**params))


def find(cat, layer, inclination, altitude):
    """The one shell of this layer within 0.2 deg / 1.5 km of the given values."""
    hits = [s for s in cat.shells if s.layer == layer and abs(s.inclination_deg - inclination) < 0.2
            and abs(s.altitude_km - altitude) < 1.5]
    assert len(hits) == 1, (layer, inclination, altitude, [s.shell_id for s in cat.shells])
    return hits[0]


# ---------------------------------------------------- acceptance (pinned)

@pytest.mark.parametrize("source", ["gp", "supgp"])
@pytest.mark.parametrize("key", sorted(REFERENCE))
def test_shell_counts_within_2_percent_of_the_reference(source, key):
    """Acceptance (plan P2): shell counts within +-2% of the reference measurement.

    The reference was measured on GP; SupGP (same day, other source) must agree too.
    """
    layer, inc, alt = key
    shell = find(catalog(source), layer, inc, alt if alt != 466 else 465.5)
    assert abs(shell.count - REFERENCE[key]) <= 0.02 * REFERENCE[key], (shell.shell_id, shell.count)


@pytest.mark.parametrize("source", ["gp", "supgp"])
def test_dtc_shells_match_mcdowell_exactly(source):
    """309 and 327 Direct-to-Cell satellites (McDowell's counts, matched by the research)."""
    cat = catalog(source)
    dtc = [s for s in cat.shells if s.layer == "dtc"]
    assert [(round(s.inclination_deg, 1), s.count) for s in dtc] == [(43.0, 327), (53.2, 309)]
    assert all(cat.shell_of[n] == s.shell_id for s in dtc for n in s.norads)


def test_53_deg_group_is_split_by_altitude_mode():
    cat = catalog("gp")
    group = [s for s in cat.shells if s.layer == "broadband" and abs(s.inclination_deg - 53.16) < 0.1]
    assert [round(s.altitude_km) for s in group] == [460, 463, 465, 471]
    main = find(cat, "broadband", 53.2, 463)
    # 460 km and 465 km sit inside the planes of the 463 km sub-shell (measured, not assumed)
    for alt in (460, 465):
        sub = find(cat, "broadband", 53.2, alt)
        assert sub.shares_planes_with == main.shell_id
        assert sub.plane_sharing["excess"] >= 0.5 and sub.count < 0.25 * main.count
    assert find(cat, "broadband", 53.2, 471).shares_planes_with is None


def test_70_deg_lower_shell_merges_two_modes_in_the_same_planes():
    shell = find(catalog("gp"), "broadband", 70.0, 476)
    assert [round(m, 1) for m in shell.modes_km] == [474.5, 477.0]
    pair = [p for p in catalog("gp").mode_pairs if p["merged"]]
    assert len(pair) == 1 and pair[0]["excess"] > 0.8 and pair[0]["size_ratio"] > 0.25


def test_every_satellite_is_in_one_shell_or_in_transit():
    for source in ("gp", "supgp"):
        cat = catalog(source)
        members = [n for s in cat.shells for n in s.norads]
        assert len(members) == len(set(members)) == len(cat.shell_of)
        assert set(cat.shell_of).isdisjoint(cat.in_transit)
        assert len(cat.shell_of) + len(cat.in_transit) == len(cat.altitude_km)
        assert set(cat.in_transit.values()) <= {"no_inclination_group", "outside_shell_bands", "small_group"}
        ids = [s.shell_id for s in cat.shells]
        assert len(ids) == len(set(ids))


def test_in_transit_objects_are_outside_every_band_of_their_group():
    fleet = snapshot.load_pinned(PINNED, "gp")
    cat = catalog("gp")
    by_norad = {r.norad: r for r in fleet.records}
    checked = 0
    for norad, reason in cat.in_transit.items():
        if reason != "outside_shell_bands":
            continue
        record = by_norad[norad]
        layer = "dtc" if record.is_dtc else "broadband"
        for shell in cat.shells:
            if shell.layer == layer and abs(record.inclination - shell.inclination_deg) <= 0.1:
                assert all(abs(cat.altitude_km[norad] - m) > cat.params.band_km for m in shell.modes_km)
                checked += 1
    assert checked > 300
    # STARLINK-1008 (2019, 53.1 deg) has been lowered to ~369 km for disposal: in transit
    assert cat.in_transit[44714] == "outside_shell_bands" and cat.altitude_km[44714] < 400


def test_band_width_sensitivity_stated_in_the_docstring():
    """shells.py says: a 5 km band would move 12 of the 337 satellites of the 70 deg / 476 km
    shell to "in transit" and change every other shell of 300+ satellites by at most 0.5%."""
    wide, narrow = catalog("gp"), catalog_with("gp", band_km=5.0)
    w = {s.shell_id: s.count for s in wide.shells}
    n = {s.shell_id: s.count for s in narrow.shells}
    assert w.keys() == n.keys()
    assert (w["70.0deg-476km"], n["70.0deg-476km"]) == (337, 325)
    for shell_id, count in w.items():
        if shell_id != "70.0deg-476km" and count >= 300:
            assert abs(count - n[shell_id]) <= 0.005 * count, shell_id


def test_parameters_are_recorded():
    cat = catalog("gp")
    assert cat.params.as_dict()["band_km"] == 10.0 and cat.params.inclination_bin_deg == 0.1
    hist = dict(cat.inclination_histogram)
    assert hist[53.2] > 4000 and hist[43.0] > 3000 and hist[97.3] > 1400 and hist[70.0] > 800


# ------------------------------------------------------------- synthetic

EPOCH = "2026-10-10T12:00:00.000000"
REF_NS = omm.parse_epoch_ns(EPOCH)


def mean_motion_for(alt_km):
    a = elements.EARTH_RADIUS_KM + alt_km
    return math.sqrt(elements.MU_KM3_S2 / a**3) * 86_400 / (2 * math.pi)


def synthetic(norad, inc, alt, raan, mean_anomaly, name=None):
    """A valid OMM object (as parse_omm_json would return it)."""
    text = json.dumps({
        "OBJECT_NAME": name or f"TEST-{norad}", "OBJECT_ID": "2026-001A", "EPOCH": EPOCH,
        "MEAN_MOTION": round(mean_motion_for(alt), 8), "ECCENTRICITY": 0.0001,
        "INCLINATION": inc, "RA_OF_ASC_NODE": raan % 360, "ARG_OF_PERICENTER": 90.0,
        "MEAN_ANOMALY": mean_anomaly % 360, "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U",
        "NORAD_CAT_ID": norad, "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 1, "BSTAR": 0.0001,
        "MEAN_MOTION_DOT": 0.0, "MEAN_MOTION_DDOT": 0})
    return omm.parse_omm_json("[" + text + "]")[0]


def walker(first_norad, inc, alt, planes, per_plane, raan0=0.0, alt_jitter=0.0, rng=None):
    out = []
    for p in range(planes):
        for s in range(per_plane):
            a = alt + (rng.uniform(-alt_jitter, alt_jitter) if rng else 0.0)
            out.append(synthetic(first_norad + p * per_plane + s, inc, a, raan0 + 360 * p / planes,
                                 360 * s / per_plane + 180 * p / (planes * per_plane)))
    return out


def records_of(objects):
    return omm.screen_objects(objects, REF_NS).kept


def test_synthetic_walker_shell_and_transit_satellites():
    rng = random.Random(1)
    objects = walker(10_000, 53.0, 550.0, 12, 10, alt_jitter=0.3, rng=rng)
    objects += [synthetic(20_000 + i, 53.0, 300 + 20 * i, 10 * i, 0) for i in range(5)]   # raising
    objects += [synthetic(30_000, 33.0, 550, 0, 0)]                                         # odd inclination
    cat = shells.infer_shells(records_of(objects), REF_NS)
    assert [(s.shell_id, s.count) for s in cat.shells] == [("53.0deg-550km", 120)]
    assert cat.in_transit == {**{20_000 + i: "outside_shell_bands" for i in range(5)},
                              30_000: "no_inclination_group"}


def test_result_does_not_depend_on_input_order():
    objects = walker(10_000, 53.0, 550.0, 12, 10) + walker(40_000, 97.6, 560.0, 6, 20)
    a = shells.infer_shells(records_of(objects), REF_NS)
    shuffled = list(objects)
    random.Random(5).shuffle(shuffled)
    b = shells.infer_shells(records_of(shuffled), REF_NS)
    assert a.shells == b.shells and dict(a.in_transit) == dict(b.in_transit)


def test_merge_rules_on_synthetic_modes():
    # Two comparable groups at 474.5 and 477 km in the SAME 12 planes -> one shell.
    same_planes = walker(10_000, 70.0, 474.5, 12, 10) + walker(11_000, 70.0, 477.0, 12, 8, raan0=0.02)
    cat = shells.infer_shells(records_of(same_planes), REF_NS)
    assert [s.count for s in cat.shells] == [216] and len(cat.shells[0].modes_km) == 2

    # A small group (5%) inside the planes of a big one -> separate sub-shell, marked.
    big = walker(10_000, 53.0, 463.0, 40, 30)
    small = walker(12_000, 53.0, 460.0, 40, 3, raan0=0.05)
    cat = shells.infer_shells(records_of(big + small), REF_NS, shells.ShellParams(min_shell_size=100))
    assert [(round(s.altitude_km), s.count) for s in cat.shells] == [(460, 120), (463, 1200)]
    assert cat.shells[0].shares_planes_with == cat.shells[1].shell_id

    # Comparable groups in DIFFERENT planes (interleaved RAANs) -> two shells, no sharing.
    a = walker(10_000, 53.0, 463.0, 20, 15)
    b = walker(11_000, 53.0, 470.0, 20, 15, raan0=9.0)
    cat = shells.infer_shells(records_of(a + b), REF_NS)
    assert [s.count for s in cat.shells] == [300, 300]
    assert all(s.shares_planes_with is None for s in cat.shells)


def test_dtc_names_form_their_own_layer():
    objects = walker(10_000, 53.0, 550.0, 12, 10)
    objects += [synthetic(50_000 + i, 53.0, 550.0, 3 + 30 * (i // 10), 36 * (i % 10),
                          name=f"STARLINK-{i} [DTC]") for i in range(120)]
    cat = shells.infer_shells(records_of(objects), REF_NS)
    assert [(s.layer, s.shell_id, s.count) for s in cat.shells] == [
        ("broadband", "53.0deg-550km", 120), ("dtc", "dtc-53.0deg-550km", 120)]


def test_plane_sharing_and_circular_coverage():
    assert shells._circular_coverage([10.0], 1.0) == pytest.approx(2 / 360)
    assert shells._circular_coverage([359.5, 0.5], 1.0) == pytest.approx(3 / 360)   # across 0/360
    assert shells._circular_coverage([0, 90, 180, 270], 50) == 1.0
    same = shells.plane_sharing([10.0, 10.1, 50.0], [10.05, 50.2], 0.3)
    assert same["fraction"] == 1.0 and same["excess"] > 0.99
    none = shells.plane_sharing([100.0, 200.0], [10.0, 50.0], 0.3)
    assert none["fraction"] == 0.0 and none["excess"] < 0
    assert np.isclose(shells._nearest_circular_distance([359.9], [0.1])[0], 0.2)

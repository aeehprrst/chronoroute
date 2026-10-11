"""Tests for chronoroute.orbit.planes: RAAN clustering, slots, plane quality, and the
shells -> planes -> satellites API for the topology code."""

import json
import math
import random
from functools import cache
from pathlib import Path

import numpy as np
import pytest

from chronoroute.data import omm, snapshot
from chronoroute.orbit import elements, planes

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"


@cache
def fleet(source):
    return snapshot.load_pinned(PINNED, source)


@cache
def geometry(source):
    f = fleet(source)
    return planes.build_fleet_geometry(f.records, f.fetched_ns, satrecs=f.satrecs)


# ---------------------------------------------------- acceptance (pinned)

@pytest.mark.parametrize("source", ["gp", "supgp"])
@pytest.mark.parametrize("inclination, n_planes", [(53.2, 24), (43.0, 26)])
def test_direct_to_cell_shells_are_24x13_and_26x13(source, inclination, n_planes):
    """Acceptance (plan P2): the DTC shells come out exactly 24 planes x 13 and 26 planes x 13.

    "x 13" is the design: no plane holds more than 13 satellites and 13 is the commonest
    size. Some planes are a satellite or two short today: at 53.2 deg the 24 x 13 = 312
    slots hold 297 satellites (12 more are off-grid, see the fragments test); at 43 deg the
    26 x 13 = 338 slots hold all 327."""
    geo = geometry(source)
    (shell,) = [s for s in geo.shells
                if s.shell.layer == "dtc" and abs(s.shell.inclination_deg - inclination) < 0.1]
    sizes = [p.size for p in shell.planes]
    assert len(shell.planes) == n_planes
    assert max(sizes) == 13 and max(set(sizes), key=sizes.count) == 13
    assert shell.quality["n_planes"] == n_planes
    # the planes are evenly spaced around the equator: 360/24 = 15 deg, 360/26 = 13.85 deg
    spacing = np.diff([p.raan_deg for p in shell.planes] + [shell.planes[0].raan_deg + 360])
    assert np.allclose(spacing, 360 / n_planes, atol=0.3)


@pytest.mark.parametrize("source", ["gp", "supgp"])
def test_97_deg_twin_planes_are_merged(source):
    """The 97.3 deg planes come as twins about 0.85 deg apart. With the general 0.5 deg gap
    they became 61 'planes' of at most 24 (so a Grid-4 cross link joined a satellite to its
    twin); the per-shell 1.0 deg gap gives 36 planes of up to 48, and 45 clusters with the
    fragments, against the research's 'about 42 clusters of 35-48' (06_research_live-data
    section 4). Plane counts are DERIVED."""
    p = planes.PlaneParams()
    assert p.gap_for(97.3) == 1.0 and p.gap_for(97.26) == 1.0
    assert p.gap_for(53.2) == p.gap_for(43.0) == p.gap_for(70.0) == 0.5
    assert p.as_dict()["gap_deg_by_inclination"] == [[97.3, 1.0]]
    shell = geometry(source).shell("97.3deg-466km")
    sizes = [pl.size for pl in shell.planes]
    assert len(shell.planes) == 36 and max(sizes) == 48 and len(shell.fragments) == 9
    assert 42 <= float(np.median(sizes)) <= 44
    # the old rule really did split them: 61 planes, none above 24
    f = fleet(source)
    old = planes.build_fleet_geometry(f.records, f.fetched_ns, satrecs=f.satrecs,
                                      plane_params=planes.PlaneParams(gap_deg_by_inclination=()))
    old_sizes = [pl.size for pl in old.shell("97.3deg-466km").planes]
    assert len(old_sizes) == 61 and max(old_sizes) == 24
    # no other shell changes
    for a, b in zip(geometry(source).shells, old.shells):
        if a.shell_id != "97.3deg-466km":
            assert [pl.norads for pl in a.planes] == [pl.norads for pl in b.planes], a.shell_id


def test_dtc_53_fragments_are_the_early_launches():
    shell = geometry("gp").shell("dtc-53.2deg-360km")
    assert [len(f.norads) for f in shell.fragments] == [6, 1, 5]
    assert sum(p.size for p in shell.planes) + 12 == shell.shell.count == 309
    assert all(f.nearest_plane_id is not None and f.nearest_plane_gap_deg > 5 for f in shell.fragments)
    f = fleet("gp")
    by_norad = {r.norad: r for r in f.records}
    launches = {by_norad[n].values["OBJECT_ID"][:8] for frag in shell.fragments for n in frag.norads}
    assert {"2024-002", "2024-065"} <= launches                       # the first DTC launches


@pytest.mark.parametrize("source", ["gp", "supgp"])
def test_slots_follow_the_argument_of_latitude(source):
    geo = geometry(source)
    for shell in geo.shells:
        raans = [p.raan_deg for p in shell.planes]
        assert raans == sorted(raans)
        for k, plane in enumerate(shell.planes):
            assert plane.plane_id == f"{shell.shell_id}/P{k:02d}" and plane.index == k
            assert list(plane.u_deg) == sorted(plane.u_deg) and all(0 <= u < 360 for u in plane.u_deg)
            for slot, norad in enumerate(plane.norads):
                sat = geo.satellites[norad]
                assert (sat.shell_id, sat.plane_id, sat.slot, sat.status) == \
                       (shell.shell_id, plane.plane_id, slot, "in_plane")


def test_the_topology_api():
    geo = geometry("supgp")
    assert len(geo.satellites) == 11_130
    statuses = geo.status_counts()
    assert set(statuses) == {"in_plane", "off_grid", "in_transit"} and sum(statuses.values()) == 11_130
    for sat in geo.satellites.values():
        if sat.status == "in_plane":
            assert sat.plane_id and sat.slot is not None and sat.routable
        elif sat.status == "off_grid":
            assert sat.shell_id and sat.plane_id is None and sat.slot is None and sat.routable
        else:
            assert sat.shell_id is None and sat.transit_reason and not sat.routable
    lists = geo.shell_planes("dtc-53.2deg-360km")
    assert len(lists) == 24 and all(isinstance(n, int) for plane in lists for n in plane)
    assert set(geo.routable_norads()) == {n for n, s in geo.satellites.items() if s.status != "in_transit"}
    s = geo.satellites[100880]
    assert s.norad == 100880 and s.name.startswith("STARLINK")
    d = s.as_dict()
    assert {"norad", "name", "shell_id", "plane_id", "slot", "routable"} <= set(d)
    json.dumps([sh.as_dict() for sh in geo.shells])                 # everything is JSON-ready


def test_quality_is_reported_for_every_shell():
    geo = geometry("gp")
    for shell in geo.shells:
        q = shell.quality
        assert 0.0 <= q["score"] <= 1.0
        assert q["off_grid"] == sum(len(f.norads) for f in shell.fragments)
        assert sum(p.size for p in shell.planes) + q["off_grid"] == shell.shell.count
    assert geo.shell("dtc-43.0deg-356km").quality["score"] == 1.0
    # the overlapping 53 deg sub-shells are visibly less clean than the DTC grid
    assert geo.shell("53.2deg-471km").quality["score"] < geo.shell("dtc-53.2deg-360km").quality["score"]


def test_463_km_sub_shell_has_about_104_planes_of_about_30():
    """06_research_live-data.md section 4: '463 km: about 104 clusters, median 31 satellites'."""
    q = geometry("supgp").shell("53.2deg-463km").quality
    assert 95 <= q["n_planes"] <= 110 and 27 <= q["plane_size_median"] <= 32


def test_j2_node_drift_agrees_with_sgp4():
    """elements.raan_rate_rad_s (our J2 formula) vs the secular node rate inside SGP4 (nodedot)."""
    f = fleet("supgp")
    sample = f.records[::97]
    ours = elements.raan_rate_rad_s([r.mean_motion for r in sample], [r.eccentricity for r in sample],
                                    [r.inclination for r in sample]) * 60.0          # rad/min
    sgp4_rates = np.array([f.satrecs[r.norad].nodedot for r in sample])
    assert np.max(np.abs(ours / sgp4_rates - 1)) < 2e-3


def test_geometry_is_deterministic():
    f = fleet("gp")
    a = geometry("gp")
    shuffled = list(f.records)
    random.Random(3).shuffle(shuffled)
    b = planes.build_fleet_geometry(shuffled, f.fetched_ns)
    assert [s.plane_lists() for s in a.shells] == [s.plane_lists() for s in b.shells]
    assert dict(a.satellites) == dict(b.satellites)


# ------------------------------------------------------------- synthetic

def test_cluster_raans_on_a_circle():
    assert [list(c) for c in planes.cluster_raans([359.8, 0.1, 0.2, 10.0], 0.5)] == [[3], [0, 1, 2]]
    assert [len(c) for c in planes.cluster_raans([1.0, 1.2, 1.4], 0.5)] == [3]
    assert planes.cluster_raans([], 0.5) == []
    assert [len(c) for c in planes.cluster_raans(np.arange(0, 360, 30.0), 0.5)] == [1] * 12


def _synthetic_walker(planes_n, per_plane, inc=53.0, alt=550.0, f=1):
    epoch = "2026-10-10T12:00:00.000000"
    a = elements.EARTH_RADIUS_KM + alt
    mm = math.sqrt(elements.MU_KM3_S2 / a**3) * 86_400 / (2 * math.pi)
    objects = []
    for p in range(planes_n):
        for s in range(per_plane):
            objects.append({
                "OBJECT_NAME": f"W-{p}-{s}", "OBJECT_ID": "2026-001A", "EPOCH": epoch,
                "MEAN_MOTION": round(mm, 8), "ECCENTRICITY": 0.0001, "INCLINATION": inc,
                "RA_OF_ASC_NODE": 360.0 * p / planes_n, "ARG_OF_PERICENTER": 0.0,
                "MEAN_ANOMALY": (360.0 * s / per_plane + 360.0 * f * p / (planes_n * per_plane)) % 360,
                "EPHEMERIS_TYPE": 0, "CLASSIFICATION_TYPE": "U", "NORAD_CAT_ID": 1000 * (p + 1) + s,
                "ELEMENT_SET_NO": 999, "REV_AT_EPOCH": 1, "BSTAR": 0.0, "MEAN_MOTION_DOT": 0.0,
                "MEAN_MOTION_DDOT": 0})
    parsed = omm.parse_omm_json(json.dumps(objects))
    return omm.screen_objects(parsed, omm.parse_epoch_ns(epoch)).kept, omm.parse_epoch_ns(epoch)


def test_synthetic_walker_planes_and_slots_are_recovered_exactly():
    records, t0 = _synthetic_walker(12, 10)
    geo = planes.build_fleet_geometry(records, t0)
    (shell,) = geo.shells
    assert len(shell.planes) == 12 and [p.size for p in shell.planes] == [10] * 12
    for k, plane in enumerate(shell.planes):
        assert plane.raan_deg == pytest.approx(30.0 * k, abs=0.01)
        assert sorted(plane.norads) == [1000 * (k + 1) + s for s in range(10)]
        # consecutive slots are 36 deg apart along the orbit
        assert np.allclose(np.diff(plane.u_deg), 36.0, atol=0.2)
        assert plane.slot_evenness == pytest.approx(1.0, abs=0.01)
    q = shell.quality
    assert q["score"] == 1.0 and q["off_grid"] == 0 and q["spacing_cv"] < 1e-3
    assert q["separation_ratio"] is None or q["separation_ratio"] > 10

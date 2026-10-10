"""
Regression tests for the geometry / orbit-data bugs in the legacy simulator
(sim/legacy/constellation.py, topology.py, tle.py, scale.py).

Bug numbers refer to the P1 bug table in the planning documents:
   #9  ground stations ignored GMST and used a spherical Earth
   #10 seam ISLs (last plane -> plane 0) ignored the Walker phasing
   #11 ISL range was a flat 5500 km instead of the 80 km grazing rule
   #12 any SGP4 error crashed the whole run
   #13 tle.py dropped the last satellite of a 2-line file; altitude used R=6371
   #15 scale.py preset switching missed names imported by value

Every test here was run against the v0-semester code first and failed there.

Reference values (WGS84 constants, the IAU-82 GMST formula, geodetic
heights) are written out again in this file on purpose, instead of being
imported from the code under test, so a mistake in the code cannot hide
behind the same mistake in the test.
"""

import math
import os
import random
import statistics
import sys
import types

import numpy as np
import pytest
from sgp4.api import Satrec, WGS72, jday

LEGACY_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'legacy'))
if LEGACY_DIR not in sys.path:
    # the legacy scripts import each other by bare module name
    sys.path.insert(0, LEGACY_DIR)

import constellation as C      # noqa: E402
import topology as T           # noqa: E402
import scale                   # noqa: E402
import tle                     # noqa: E402

# ----- independent WGS84 reference values -----
WGS84_A = 6378.137
WGS84_F = 1.0 / 298.257223563
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)
WGS84_B = WGS84_A * (1.0 - WGS84_F)

CHENNAI = (13.0827, 80.2707)


@pytest.fixture(autouse=True)
def _back_to_dev_preset():
    """Presets are process-wide state: every test leaves the default behind."""
    yield
    scale.restore_topology()
    scale.use_preset('dev', verbose=False)


# ---------------------------------------------------------------- helpers

def wgs84_ecef(lat_deg, lon_deg, h_km=0.0):
    """Textbook closed form: geodetic (lat, lon, h) -> ECEF km."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    n = WGS84_A / math.sqrt(1.0 - WGS84_E2 * math.sin(lat) ** 2)
    return ((n + h_km) * math.cos(lat) * math.cos(lon),
            (n + h_km) * math.cos(lat) * math.sin(lon),
            (n * (1.0 - WGS84_E2) + h_km) * math.sin(lat))


def local_up_north(lat_deg, lon_deg):
    """Unit vectors 'up' (ellipsoid normal) and 'north' at a geodetic point."""
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    up = (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon),
          math.sin(lat))
    north = (-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon),
             math.cos(lat))
    return up, north


def gmst_iau82_rad(jd_ut1):
    """IAU-82 Greenwich mean sidereal time (Vallado eq. 3-47)."""
    t = (jd_ut1 - 2451545.0) / 36525.0
    seconds = (67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * t
               + 0.093104 * t * t - 6.2e-6 * t * t * t)
    return math.radians((seconds % 86400.0) / 240.0)


def geodetic_height_np(points):
    """Height above WGS84 for an (..., 3) array. Iterative, numpy."""
    x, y, z = points[..., 0], points[..., 1], points[..., 2]
    p = np.hypot(x, y)
    lat = np.arctan2(z, p * (1.0 - WGS84_E2))
    for _ in range(10):
        s = np.sin(lat)
        n = WGS84_A / np.sqrt(1.0 - WGS84_E2 * s * s)
        lat = np.arctan2(z + WGS84_E2 * n * s, p)
    s, c = np.sin(lat), np.cos(lat)
    return p * c + z * s - WGS84_A * np.sqrt(1.0 - WGS84_E2 * s * s)


def brute_force_min_altitude(pa, pb, samples=2001):
    """Lowest point of the straight segment pa->pb, by dense sampling."""
    pa, pb = np.asarray(pa, float), np.asarray(pb, float)
    t = np.linspace(0.0, 1.0, samples)[:, None]
    return float(geodetic_height_np(pa + t * (pb - pa)).min())


def chord_on_equator(radius_km, length_km):
    """Two points on the equator, radius_km from the centre, length_km apart."""
    half = math.asin(length_km / (2.0 * radius_km))
    return ((radius_km * math.cos(-half), radius_km * math.sin(-half), 0.0),
            (radius_km * math.cos(half), radius_km * math.sin(half), 0.0))


def chord_over_north_pole(radius_km, lowest_point_km):
    """
    Two points radius_km from the centre whose chord passes straight over the
    North Pole, lowest_point_km from the Earth's centre. By symmetry the
    lowest point of that chord is right above the pole, where the ground is
    the POLAR radius (6356.752 km), not the equatorial one.
    """
    half = math.acos(lowest_point_km / radius_km)
    return ((radius_km * math.sin(half), 0.0, radius_km * math.cos(half)),
            (-radius_km * math.sin(half), 0.0, radius_km * math.cos(half)))


def snapshot(duration_s=1, step_s=1):
    sats = C.build_constellation()
    times, sat_pos = C.propagate(sats, duration_s=duration_s, step_s=step_s)
    gs_pos = C.ground_station_positions(times)
    return sats, times, sat_pos, gs_pos


# ======================================================= #9 frames and WGS84

def test_gmst_at_simulation_epoch():
    jd, fr = jday(2026, 9, 10, 0, 0, 0)
    assert math.degrees(C.gmst_rad(jd, fr)) == pytest.approx(349.04, abs=0.01)
    # and it is the standard IAU-82 value, not something hand-rolled
    assert C.gmst_rad(jd, fr) == pytest.approx(gmst_iau82_rad(jd + fr),
                                               abs=1e-9)


def test_chennai_wgs84_ecef_within_one_metre():
    got = C.geodetic_to_ecef(*CHENNAI, 0.0)
    want = wgs84_ecef(*CHENNAI, 0.0)
    assert math.dist(got, want) < 1e-3                      # 1 m
    # hard numbers too, so the closed form above cannot drift unnoticed
    assert math.dist(got, (1050.0667, 6124.2842, 1434.3184)) < 1e-3
    # and the inverse gives the same place back
    lat, lon, h = C.ecef_to_geodetic(got)
    assert (lat, lon) == pytest.approx(CHENNAI, abs=1e-9)
    assert h == pytest.approx(0.0, abs=1e-6)


def test_ground_stations_are_fixed_wgs84_points():
    times = [0, 60, 3600]
    gs = C.ground_station_positions(times)
    for gi, (name, lat, lon) in enumerate(C.GROUND_STATIONS):
        want = wgs84_ecef(lat, lon, 0.0)
        for k in range(len(times)):
            # Earth-fixed frame: a city does not move between timesteps
            assert math.dist(gs[k][gi], want) < 1e-3, name


def test_satellites_are_in_the_same_earth_fixed_frame():
    """propagate() must return SGP4's TEME position rotated by GMST(t)."""
    sats = C.build_constellation()[:3]
    times, pos = C.propagate(sats, duration_s=121, step_s=60)
    jd0, fr0 = jday(C.EPOCH_YEAR, C.EPOCH_MONTH, C.EPOCH_DAY, 0, 0, 0)
    for k, t in enumerate(times):
        fr = fr0 + t / 86400.0
        theta = gmst_iau82_rad(jd0 + fr)
        for i, sat in enumerate(sats):
            err, r, _ = sat['satrec'].sgp4(jd0, fr)
            assert err == 0
            want = (math.cos(theta) * r[0] + math.sin(theta) * r[1],
                    -math.sin(theta) * r[0] + math.cos(theta) * r[1],
                    r[2])
            assert math.dist(pos[k][i], want) < 1e-6


@pytest.mark.parametrize('lat, lon', [CHENNAI, (51.51, -0.13), (-33.87, 151.21)])
def test_elevation_uses_the_ellipsoid_normal(lat, lon):
    gs = wgs84_ecef(lat, lon, 0.0)
    up, north = local_up_north(lat, lon)
    overhead = tuple(g + 550.0 * u for g, u in zip(gs, up))
    assert T.elevation_angle_deg(gs, overhead) == pytest.approx(90.0, abs=1e-6)
    # a point straight north along the local horizon is at 0 deg elevation
    horizon = tuple(g + 1000.0 * n for g, n in zip(gs, north))
    assert T.elevation_angle_deg(gs, horizon) == pytest.approx(0.0, abs=1e-6)


def test_shell_altitude_is_measured_from_wgs84_equator():
    """A '550 km' shell has semi-major axis 6378.137 + 550 km (as in Hypatia)."""
    n_rad_per_s = C.mean_motion_rad_per_min(550.0) / 60.0
    a = (C.MU_EARTH / n_rad_per_s ** 2) ** (1.0 / 3.0)
    assert a == pytest.approx(WGS84_A + 550.0, abs=1e-6)


# ============================================================ #10 seam ISLs

def _cross_lengths(pairs, frames, planes, per_plane):
    seam, normal = [], []
    for frame in frames:
        for a, b, kind in pairs:
            if kind != 'cross':
                continue
            d = math.dist(frame[a], frame[b])
            if a // per_plane == planes - 1 and b // per_plane == 0:
                seam.append(d)
            else:
                normal.append(d)
    return seam, normal


@pytest.mark.parametrize('preset', ['starlink', 'dev', 'kuiper', 'telesat'])
def test_seam_isls_as_short_as_normal_cross_plane(preset):
    scale.use_preset(preset, verbose=False)
    p = scale.PRESETS[preset]
    planes, per_plane = p['planes'], p['sats_per_plane']
    sats = C.build_constellation()
    _, frames = C.propagate(sats, duration_s=1200, step_s=300)

    pairs = T.isl_neighbour_pairs()
    seam, normal = _cross_lengths(pairs, frames, planes, per_plane)
    assert len(seam) == per_plane * len(frames)
    ratio = statistics.median(seam) / statistics.median(normal)
    assert abs(ratio - 1.0) < 0.05, (preset, statistics.median(seam),
                                     statistics.median(normal))

    # every plane-0 satellite is the seam partner of exactly one satellite
    partners = sorted(b for a, b, k in pairs
                      if k == 'cross' and a // per_plane == planes - 1)
    assert partners == list(range(per_plane))


# ===================================================== #11 80 km grazing rule

def test_isl_that_dips_below_80km_is_rejected():
    """5200 km between two 550 km satellites: under 5500 km, but the line
    between them passes only ~44 km above the equator."""
    _, _, sat_pos, gs_pos = snapshot()
    frame = list(sat_pos[0])
    frame[0], frame[1] = chord_on_equator(WGS84_A + 550.0, 5200.0)
    assert brute_force_min_altitude(frame[0], frame[1]) < 50.0
    g = T.build_graph(frame, gs_pos[0])
    assert not g.has_edge(0, 1)


def test_long_isl_that_clears_80km_is_kept():
    """6000 km between two 1015 km satellites clears the Earth by ~380 km;
    the old flat 5500 km limit threw it away."""
    _, _, sat_pos, gs_pos = snapshot()
    frame = list(sat_pos[0])
    frame[0], frame[1] = chord_on_equator(WGS84_A + 1015.0, 6000.0)
    assert brute_force_min_altitude(frame[0], frame[1]) > 300.0
    g = T.build_graph(frame, gs_pos[0])
    assert g.has_edge(0, 1)
    assert g[0][1]['dist_km'] == pytest.approx(6000.0)


def test_grazing_rule_uses_the_ellipsoid_not_a_sphere():
    """Over the pole the ground is 21 km lower than at the equator."""
    r = WGS84_A + 550.0
    ok = chord_over_north_pole(r, WGS84_B + 90.0)     # 90 km over the pole
    low = chord_over_north_pole(r, WGS84_B + 70.0)    # 70 km over the pole
    assert T.segment_min_altitude_km(*ok) == pytest.approx(90.0, abs=1e-6)
    assert T.segment_min_altitude_km(*low) == pytest.approx(70.0, abs=1e-6)
    assert T.isl_clears_earth(*ok)
    assert not T.isl_clears_earth(*low)


def test_segment_min_altitude_matches_brute_force():
    rng = random.Random(2026)
    for _ in range(300):
        # two satellites 300-1500 km up, at most 60 deg apart (seen from the
        # centre), so some chords clear the Earth and some cut through it
        lat = math.asin(rng.uniform(-1.0, 1.0))
        lon = rng.uniform(-math.pi, math.pi)
        pts = []
        for _ in range(2):
            r = rng.uniform(WGS84_A + 300.0, WGS84_A + 1500.0)
            pts.append((r * math.cos(lat) * math.cos(lon),
                        r * math.cos(lat) * math.sin(lon), r * math.sin(lat)))
            lat = max(-1.5, min(1.5, lat + rng.uniform(-0.75, 0.75)))
            lon = lon + rng.uniform(-0.75, 0.75)
        want = brute_force_min_altitude(*pts)
        got = T.segment_min_altitude_km(*pts)
        # sampling can only overestimate the minimum, and only slightly
        assert got <= want + 1e-6
        assert got == pytest.approx(want, abs=0.01)
        if abs(want - T.ISL_MIN_GRAZING_ALT_KM) > 0.05:
            assert T.isl_clears_earth(*pts) == (want >= T.ISL_MIN_GRAZING_ALT_KM)


@pytest.mark.parametrize('preset', ['dev', 'starlink', 'kuiper', 'telesat'])
def test_no_isl_below_80km_over_one_orbit(preset):
    scale.use_preset(preset, verbose=False)
    scale.install_fast_topology(verbose=False)
    period_s = 2.0 * math.pi / C.mean_motion_rad_per_min(
        scale.PRESETS[preset]['altitude_km']) * 60.0
    sats = C.build_constellation()
    times, frames = C.propagate(sats, duration_s=int(period_s) + 1, step_s=30)
    gs = C.ground_station_positions(times)
    assert times[-1] + 30 > period_s
    worst = math.inf
    for k in range(len(times)):
        g = T.build_graph(frames[k], gs[k])
        isl = [(a, b) for a, b, d in g.edges(data=True) if d['kind'] != 'gsl']
        assert isl
        P = np.asarray(frames[k], dtype=float)
        pa = P[[a for a, _ in isl]]
        pb = P[[b for _, b in isl]]
        # Lower bound: the whole Earth lies inside the sphere of radius
        # WGS84_A, so no point of a segment is lower than (its closest
        # approach to the centre) - WGS84_A.
        dvec = pb - pa
        t = np.clip(-np.einsum('ij,ij->i', pa, dvec)
                    / np.einsum('ij,ij->i', dvec, dvec), 0.0, 1.0)
        lower = np.linalg.norm(pa + t[:, None] * dvec, axis=1) - WGS84_A
        # anything the bound cannot clear is measured by dense sampling
        for i in np.flatnonzero(lower < T.ISL_MIN_GRAZING_ALT_KM):
            lower[i] = brute_force_min_altitude(pa[i], pb[i])
        worst = min(worst, float(lower.min()))
    assert worst >= T.ISL_MIN_GRAZING_ALT_KM


@pytest.mark.parametrize('preset', ['dev', 'starlink'])
def test_fast_topology_matches_reference(preset):
    scale.use_preset(preset, verbose=False)
    _, _, sat_pos, gs_pos = snapshot()
    frame = list(sat_pos[0])
    frame[7] = None                           # one satellite SGP4 could not place
    slow = T.build_graph(frame, gs_pos[0])
    scale.install_fast_topology(verbose=False)
    fast = T.build_graph(frame, gs_pos[0])
    assert T.build_graph is not scale._original_build_graph
    assert set(slow.nodes) == set(fast.nodes)
    assert set(map(frozenset, slow.edges)) == set(map(frozenset, fast.edges))
    for a, b, d in slow.edges(data=True):
        assert fast[a][b]['kind'] == d['kind']
        assert fast[a][b]['weight'] == pytest.approx(d['weight'], abs=1e-9)
    assert slow.graph['skipped_sats'] == fast.graph['skipped_sats'] == 1


# =================================================== #12 SGP4 errors skipped

def _satrec(ecc, alt_km, bstar=0.0, satnum=900):
    jd, fr = jday(C.EPOCH_YEAR, C.EPOCH_MONTH, C.EPOCH_DAY, 0, 0, 0)
    n = math.sqrt(C.MU_EARTH / (WGS84_A + alt_km) ** 3) * 60.0
    s = Satrec()
    s.sgp4init(WGS72, 'i', satnum, jd + fr - 2433281.5, bstar, 0.0, 0.0,
               ecc, 0.0, math.radians(53.0), 0.0, n, 0.0)
    return s


def test_sgp4_errors_skip_the_satellite_and_are_counted():
    good = C.build_constellation()[:4]
    hyperbolic = {'id': 4, 'satrec': _satrec(1.2, 500.0)}           # error 1 always
    decaying = {'id': 5, 'satrec': _satrec(0.0, 200.0, bstar=0.5)}  # fine, then decays
    sats = good + [hyperbolic, decaying]

    times, pos = C.propagate(sats, duration_s=3601, step_s=600)      # must not raise
    assert len(pos) == len(times) == 7
    for frame in pos:
        assert len(frame) == len(sats)
        assert all(p is not None for p in frame[:4])
        assert frame[4] is None
    assert pos[0][5] is not None and pos[-1][5] is None

    stats = C.last_propagation_stats()
    skipped_decaying = sum(frame[5] is None for frame in pos)
    assert stats.samples == len(sats) * len(times)
    assert stats.skipped == len(times) + skipped_decaying
    assert stats.skipped_by_sat == {4: len(times), 5: skipped_decaying}
    assert stats.skipped_sats == 2
    assert stats.error_codes[1] >= len(times)
    assert sum(stats.error_codes.values()) == stats.skipped

    # a clean run resets the count
    C.propagate(good, duration_s=2, step_s=1)
    assert C.last_propagation_stats().skipped == 0


def test_graph_tolerates_a_skipped_satellite():
    _, _, sat_pos, gs_pos = snapshot()
    frame = list(sat_pos[0])
    frame[0] = None
    g = T.build_graph(frame, gs_pos[0])
    assert g.has_node(0) and g.degree(0) == 0      # present, but cut off
    assert g.graph['skipped_sats'] == 1
    assert g.has_edge(1, 2)                        # everyone else is untouched


# ======================================================== #13 TLE parsing

TLES = [
    ('STARLINK-1008',
     '1 44714U 19074B   26252.59199772  .00054670  00000+0  56767-3 0  9992',
     '2 44714  53.1486  20.3866 0002669  67.4256 292.7042 15.64120146377369'),
    ('STARLINK-1012',
     '1 44718U 19074F   26253.28470740  .00041827  00000+0  42798-3 0  9999',
     '2 44718  53.1503  17.2318 0003021 322.1033  37.9769 15.64608850377466'),
    ('STARLINK-1017',
     '1 44723U 19074L   26253.09021445  .00047517  00000+0  12297-2 0  9990',
     '2 44723  53.0448  30.9396 0002346 317.1383  42.9437 15.38623909377223'),
]


@pytest.mark.parametrize('with_names', [False, True])
@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_tle_file_keeps_every_satellite(tmp_path, with_names, newline):
    lines = []
    for name, l1, l2 in TLES:
        lines += ([name] if with_names else []) + [l1, l2]
    path = tmp_path / 'three.txt'
    path.write_bytes((newline.join(lines) + newline).encode())
    sats = tle.load_tle_file(str(path))
    assert len(sats) == 3
    assert [s['satrec'].satnum for s in sats] == [44714, 44718, 44723]
    if with_names:
        assert [s['name'] for s in sats] == [t[0] for t in TLES]


def test_tle_file_without_trailing_newline(tmp_path):
    path = tmp_path / 'three.txt'
    path.write_text('\n'.join(l for _, l1, l2 in TLES for l in (l1, l2)))
    assert len(tle.load_tle_file(str(path))) == 3


def test_tle_default_file_is_in_the_repository_data_dir():
    """tle.py moved from src/ to sim/legacy/; its default path must follow."""
    repo = os.path.dirname(os.path.dirname(LEGACY_DIR))
    assert (os.path.normpath(tle.DEFAULT_FILE)
            == os.path.join(repo, 'data', 'starlink.txt'))


def test_tle_altitude_is_above_wgs84_equator():
    sat = {'name': 'x', 'satrec': Satrec.twoline2rv(TLES[0][1], TLES[0][2])}
    n_rad_per_s = sat['satrec'].no_kozai / 60.0
    a = (tle.MU_EARTH / n_rad_per_s ** 2) ** (1.0 / 3.0)
    assert tle.orbital_elements(sat)['altitude_km'] == pytest.approx(
        a - WGS84_A, abs=1e-9)


# =================================================== #15 preset switching

def _by_value_importer():
    """
    Stand-in for exp4_failure_resilience.py / exp5 / simulator.py: a legacy
    module that copied names BY VALUE when it was imported.
    """
    mod = types.ModuleType('_geo_test_by_value_importer')
    mod.__file__ = os.path.join(LEGACY_DIR, '_geo_test_by_value_importer.py')
    exec('from topology import ISL_PAIRS\n'
         'from constellation import NUM_SATS, NUM_PLANES, SATS_PER_PLANE\n',
         mod.__dict__)
    sys.modules[mod.__name__] = mod
    return mod


def test_preset_switch_reaches_names_imported_by_value():
    mod = _by_value_importer()
    try:
        for key in ['starlink', 'telesat', 'dev', 'kuiper']:
            scale.use_preset(key, verbose=False)
            p = scale.PRESETS[key]
            n = p['planes'] * p['sats_per_plane']
            assert C.num_sats() == mod.NUM_SATS == n
            assert mod.NUM_PLANES == p['planes']
            assert mod.SATS_PER_PLANE == p['sats_per_plane']
            # exp4 samples its failed links from this list
            assert list(mod.ISL_PAIRS) == list(T.isl_pairs())
            assert max(max(a, b) for a, b, _ in mod.ISL_PAIRS) == n - 1
    finally:
        del sys.modules[mod.__name__]


def _geometry_fingerprint():
    sats, _, sat_pos, gs_pos = snapshot()
    g = T.build_graph(sat_pos[0], gs_pos[0])
    edges = sorted((tuple(sorted(map(repr, (a, b)))), d['kind'],
                    round(d['weight'], 6)) for a, b, d in g.edges(data=True))
    return len(sats), C.config(), list(T.isl_pairs()), edges


def test_geometry_does_not_depend_on_preset_order():
    scale.use_preset('telesat', verbose=False)
    first = _geometry_fingerprint()

    for key in ['starlink', 'kuiper', 'dev']:
        scale.use_preset(key, verbose=False)
        scale.install_fast_topology(verbose=False)
        _geometry_fingerprint()
    scale.use_preset('telesat', verbose=False)
    assert _geometry_fingerprint() == first

    scale.restore_topology()
    assert _geometry_fingerprint() == first


def test_direct_assignment_of_old_names_is_caught():
    """Rebinding constellation.NUM_SATS by hand used to be silently ignored
    by some modules; now it is refused loudly."""
    old = C.NUM_SATS
    C.NUM_SATS = 5
    try:
        with pytest.raises(RuntimeError):
            C.num_sats()
    finally:
        C.NUM_SATS = old
    assert C.num_sats() == old


def test_preset_switch_leaves_other_packages_alone():
    """scale.py used to patch ANY module whose path contained 'chronoroute',
    which includes every package in ~/chronoroute/venv."""
    fake = types.ModuleType('_geo_test_third_party')
    fake.__file__ = '/home/x/chronoroute/venv/lib/site-packages/fake/__init__.py'
    sentinel = object()
    fake.NUM_SATS = sentinel
    fake.build_graph = sentinel
    sys.modules[fake.__name__] = fake
    try:
        scale.use_preset('starlink', verbose=False)
        scale.install_fast_topology(verbose=False)
        assert fake.NUM_SATS is sentinel
        assert fake.build_graph is sentinel
    finally:
        del sys.modules[fake.__name__]

"""
constellation.py
----------------
Builds a Walker-Delta LEO constellation and propagates every satellite's
position over time using SGP4 (real orbital physics, not a toy circle model).

Also holds the ground stations (cities) that act as source/destination.

Key output: positions[t][sat_id] = (x, y, z) in km, Earth-Centred Earth-Fixed
(ECEF). Satellites AND ground stations are in this one frame, so every
distance, elevation angle and "closest to the destination" comparison in the
simulator compares like with like.

Frames, in plain words:
  - SGP4 gives positions in TEME, an inertial frame that does not spin with
    the Earth.
  - The Earth (and every city on it) spins. Its angle relative to TEME is the
    Greenwich Mean Sidereal Time (GMST). At our epoch, 2026-09-10 00:00 UTC,
    GMST is 349.04 deg -- so treating a city's longitude as if it were
    measured from the TEME x-axis (what v0 did) puts it ~11 deg off.
  - We rotate each satellite from TEME into ECEF by GMST(t). Cities then sit
    still at their WGS84 geodetic coordinates.
  - Ignored on purpose: UT1-UTC (< 0.9 s) and polar motion (~10 m). Together
    they cost at most ~0.4 km of ground position.

Earth model: the WGS84 ellipsoid everywhere (ground stations, elevation
angles, the ISL grazing rule, shell altitudes). Nothing treats the Earth as a
6371 km sphere any more.
"""

import math
from dataclasses import dataclass, field

from sgp4.api import Satrec, WGS72, jday
from sgp4.propagation import gstime

# ----- Earth model: WGS84 ellipsoid -----
WGS84_A_KM = 6378.137                       # equatorial radius
WGS84_F = 1.0 / 298.257223563               # flattening
WGS84_B_KM = WGS84_A_KM * (1.0 - WGS84_F)   # polar radius (6356.752 km)
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)        # first eccentricity squared

# Old name, kept so existing imports keep working. It is the EQUATORIAL
# radius: shell altitudes are measured from it (as Hypatia does), and
# nothing uses it as a spherical Earth.
EARTH_RADIUS_KM = WGS84_A_KM

# ----- Physical constants -----
MU_EARTH = 398600.4418          # km^3 / s^2  (Earth gravitational parameter)
C_KM_PER_MS = 299.792458        # speed of light in km per millisecond
JD_1949_DEC_31 = 2433281.5      # SGP4 epoch reference


# ----- Constellation design -----

@dataclass(frozen=True)
class ConstellationConfig:
    """
    The one source of truth for the constellation shape.

    Every function reads the ACTIVE config at call time (config()), so a
    preset switch reaches everything, whatever style a module used to import
    us. Change it with set_config() (scale.use_preset() does that for you).
    Frozen, so a config can be compared, hashed and used as a cache key.
    """
    planes: int = 24                # P : number of orbital planes
    sats_per_plane: int = 20        # T/P : satellites in each plane
    altitude_km: float = 550.0      # shell altitude above the WGS84 equator
    inclination_deg: float = 53.0   # Starlink-like inclination
    phasing_f: int = 1              # Walker-Delta phasing factor F

    @property
    def num_sats(self):
        return self.planes * self.sats_per_plane


DEFAULT_CONFIG = ConstellationConfig()
_config = DEFAULT_CONFIG

# Old UPPER_CASE names, kept because the experiment scripts import them.
# They are COPIES of the active config, refreshed by set_config(). New code
# should call config() / num_sats() / num_planes() / sats_per_plane() instead,
# which can never go stale.
NUM_PLANES = _config.planes
SATS_PER_PLANE = _config.sats_per_plane
ALTITUDE_KM = _config.altitude_km
INCLINATION_DEG = _config.inclination_deg
PHASING_F = _config.phasing_f
NUM_SATS = _config.num_sats                 # 480

_LEGACY_NAMES = ('NUM_PLANES', 'SATS_PER_PLANE', 'ALTITUDE_KM',
                 'INCLINATION_DEG', 'PHASING_F', 'NUM_SATS')


def _legacy_values(cfg):
    return {
        'NUM_PLANES': cfg.planes,
        'SATS_PER_PLANE': cfg.sats_per_plane,
        'ALTITUDE_KM': cfg.altitude_km,
        'INCLINATION_DEG': cfg.inclination_deg,
        'PHASING_F': cfg.phasing_f,
        'NUM_SATS': cfg.num_sats,
    }


def config():
    """
    The active ConstellationConfig.

    v0 let scale.py rebind constellation.NUM_SATS and friends by hand, and
    some modules silently kept the old value. If anyone still assigns one of
    those names directly, we refuse loudly instead of half-applying it.
    """
    g = globals()
    for name, value in _legacy_values(_config).items():
        if g[name] != value:
            raise RuntimeError(
                f"constellation.{name} was assigned directly ({g[name]!r}, "
                f"active config says {value!r}). Use scale.apply_config() "
                f"or constellation.set_config() to change the constellation.")
    return _config


def set_config(cfg):
    """Make cfg the active constellation (and refresh the old names here)."""
    global _config
    if not isinstance(cfg, ConstellationConfig):
        raise TypeError("set_config() needs a ConstellationConfig")
    if cfg.planes < 1 or cfg.sats_per_plane < 1:
        raise ValueError("need at least one plane and one satellite per plane")
    if not 0 <= cfg.phasing_f < cfg.planes:
        raise ValueError("Walker phasing factor F must be in 0 .. planes-1")
    _config = cfg
    globals().update(_legacy_values(cfg))
    return cfg


def num_sats():
    return config().num_sats


def num_planes():
    return config().planes


def sats_per_plane():
    return config().sats_per_plane


# ----- Simulation epoch -----
EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY = 2026, 9, 10


def mean_motion_rad_per_min(altitude_km):
    """
    Convert an altitude to SGP4's 'no_kozai' mean motion (radians per minute).

    n = sqrt(mu / a^3)  where a is the semi-major axis. The altitude is
    measured from the WGS84 equatorial radius, so a 550 km shell has
    a = 6928.137 km (the same convention as Hypatia and tle.py).
    """
    a = WGS84_A_KM + altitude_km               # circular orbit -> a = r
    n_rad_per_sec = math.sqrt(MU_EARTH / (a ** 3))
    return n_rad_per_sec * 60.0


def build_constellation():
    """
    Create num_sats() SGP4 satellite objects arranged in a Walker-Delta pattern.

    Walker-Delta notation here is  i : T / P / F  (default 53 deg : 480/24/1)
      - plane p gets RAAN  = p * 360/P                  (planes spread over 360 deg)
      - satellite s in plane p gets mean anomaly
            = s * 360/(T/P)  +  p * F * 360/T           (the F term staggers planes)

    Returns: list of dicts, one per satellite.
    """
    cfg = config()
    jd, fr = jday(EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY, 0, 0, 0)
    epoch_days = (jd + fr) - JD_1949_DEC_31

    no_kozai = mean_motion_rad_per_min(cfg.altitude_km)
    inclo = math.radians(cfg.inclination_deg)

    sats = []
    sat_id = 0
    for p in range(cfg.planes):
        raan_deg = p * (360.0 / cfg.planes)
        for s in range(cfg.sats_per_plane):
            ma_deg = (s * (360.0 / cfg.sats_per_plane)
                      + p * cfg.phasing_f * (360.0 / cfg.num_sats)) % 360.0

            satrec = Satrec()
            satrec.sgp4init(
                WGS72,                  # gravity model
                'i',                    # 'i' = improved mode
                sat_id + 1,             # satellite number (must be > 0)
                epoch_days,             # epoch: days since 1949 Dec 31 00:00 UT
                0.0,                    # bstar  (drag term, 0 = ignore drag)
                0.0,                    # ndot
                0.0,                    # nddot
                0.0,                    # eccentricity (0 = circular)
                0.0,                    # argument of perigee
                inclo,                  # inclination (radians)
                math.radians(ma_deg),   # mean anomaly (radians)
                no_kozai,               # mean motion (radians/minute)
                math.radians(raan_deg), # RAAN (radians)
            )

            sats.append({
                'id': sat_id,
                'plane': p,
                'index_in_plane': s,
                'satrec': satrec,
            })
            sat_id += 1

    return sats


# ---------------------------------------------------------------- frames

def gmst_rad(jd, fr=0.0):
    """
    Greenwich Mean Sidereal Time (IAU-82, the one SGP4/TEME is defined with)
    in radians, for the Julian date jd + fr. UTC is used as UT1.
    """
    return gstime(jd + fr)


def teme_to_ecef(r, gmst):
    """
    Rotate a TEME position into the Earth-fixed frame.

    The Earth has turned by `gmst` radians relative to TEME, so we turn the
    position back by the same angle about the polar (z) axis.
    """
    c, s = math.cos(gmst), math.sin(gmst)
    return (c * r[0] + s * r[1],
            -s * r[0] + c * r[1],
            r[2])


@dataclass
class PropagationStats:
    """What propagate() had to skip. Read it with last_propagation_stats()."""
    samples: int = 0                                     # satellite-timesteps tried
    skipped: int = 0                                     # ... that SGP4 could not place
    skipped_by_sat: dict = field(default_factory=dict)   # sat id -> steps skipped
    error_codes: dict = field(default_factory=dict)      # SGP4 error code -> count

    @property
    def skipped_sats(self):
        """How many different satellites were skipped at least once."""
        return len(self.skipped_by_sat)


_last_stats = PropagationStats()


def last_propagation_stats():
    """Skip counts from the most recent propagate() call (for the manifest)."""
    return _last_stats


# SGP4's error code 0 means fine; we use -1 for "said fine, but the position
# is not a finite number", which we treat exactly like an error.
NON_FINITE_POSITION = -1


def propagate(sats, duration_s, step_s):
    """
    Run SGP4 for every satellite at every timestep.

    A satellite SGP4 cannot place at some step (decayed, bad elements; real
    TLE files have dozens) is SKIPPED for that step: its slot holds None and
    the skip is counted in last_propagation_stats(). One bad satellite no
    longer stops the whole run, and nobody gets a made-up position.

    Returns:
        times      : list of simulation times in seconds [0, step, 2*step, ...]
        positions  : positions[t_index][sat_index] = (x, y, z) in km, ECEF,
                     or None if that satellite was skipped at that step
    """
    global _last_stats
    jd0, fr0 = jday(EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY, 0, 0, 0)

    stats = PropagationStats()
    times = list(range(0, duration_s, step_s))
    positions = []

    for t in times:
        # advance the fractional-day part of the Julian date by t seconds
        fr = fr0 + t / 86400.0
        theta = gmst_rad(jd0, fr)          # how far the Earth has turned
        frame = []
        for i, sat in enumerate(sats):
            stats.samples += 1
            error, r, _ = sat['satrec'].sgp4(jd0, fr)   # r in TEME, km
            if error == 0 and not all(math.isfinite(c) for c in r):
                error = NON_FINITE_POSITION
            if error != 0:
                sid = sat.get('id', i)
                stats.skipped += 1
                stats.skipped_by_sat[sid] = stats.skipped_by_sat.get(sid, 0) + 1
                stats.error_codes[error] = stats.error_codes.get(error, 0) + 1
                frame.append(None)
                continue
            frame.append(teme_to_ecef(r, theta))
        positions.append(frame)

    _last_stats = stats
    return times, positions


# ---------------------------------------------------------------- ground stations

# (name, geodetic latitude_deg, longitude_deg) on the WGS84 ellipsoid, height 0
GROUND_STATIONS = [
    ('Chennai',   13.08,   80.27),
    ('London',    51.51,   -0.13),
    ('NewYork',   40.71,  -74.01),
    ('Sydney',   -33.87,  151.21),
    ('SaoPaulo', -23.55,  -46.63),
    ('Tokyo',     35.68,  139.65),
]


def geodetic_to_ecef(lat_deg, lon_deg, h_km=0.0):
    """
    WGS84 geodetic (latitude, longitude, height) -> ECEF (x, y, z) in km.

    N is the radius of curvature in the prime vertical; this is the standard
    closed form, exact to floating-point precision.
    """
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    sin_lat = math.sin(lat)
    n = WGS84_A_KM / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    return ((n + h_km) * math.cos(lat) * math.cos(lon),
            (n + h_km) * math.cos(lat) * math.sin(lon),
            (n * (1.0 - WGS84_E2) + h_km) * sin_lat)


def ecef_to_geodetic(pos):
    """
    ECEF (x, y, z) km -> WGS84 (latitude_deg, longitude_deg, height_km).

    Fixed-point iteration on the latitude; it converges to full double
    precision in a handful of steps for anything from the ground to far
    above LEO. The height formula below stays exact even at the poles.
    For points outside the ellipsoid the height is the straight-line
    distance to the nearest point of the Earth's surface.
    """
    x, y, z = pos
    p = math.hypot(x, y)
    lon = math.atan2(y, x)
    lat = math.atan2(z, p * (1.0 - WGS84_E2))
    for _ in range(30):
        sin_lat = math.sin(lat)
        n = WGS84_A_KM / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        new_lat = math.atan2(z + WGS84_E2 * n * sin_lat, p)
        if abs(new_lat - lat) < 1e-15:
            lat = new_lat
            break
        lat = new_lat
    sin_lat, cos_lat = math.sin(lat), math.cos(lat)
    h = (p * cos_lat + z * sin_lat
         - WGS84_A_KM * math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat))
    return math.degrees(lat), math.degrees(lon), h


def geodetic_up(pos):
    """
    The local 'up' unit vector at an ECEF point: the ellipsoid normal.

    On an ellipsoid this is NOT the direction from the Earth's centre; the
    two differ by up to 0.19 deg (at 45 deg latitude).
    """
    lat_deg, lon_deg, _ = ecef_to_geodetic(pos)
    lat, lon = math.radians(lat_deg), math.radians(lon_deg)
    return (math.cos(lat) * math.cos(lon),
            math.cos(lat) * math.sin(lon),
            math.sin(lat))


def ground_station_positions(times):
    """
    Ground stations in the SAME Earth-fixed frame as the satellites.

    Because propagate() already rotates the satellites into ECEF, a city does
    not move: we place it once from its WGS84 geodetic coordinates. We still
    return one frame per timestep so callers can index it like the
    satellite positions.

    Returns: gs_positions[t_index][gs_index] = (x, y, z) in km
    """
    fixed = [geodetic_to_ecef(lat_deg, lon_deg, 0.0)
             for _, lat_deg, lon_deg in GROUND_STATIONS]
    return [list(fixed) for _ in times]


# ---------------------------------------------------------------- helpers

def distance(a, b):
    """Straight-line distance in km between two (x, y, z) points."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def latitude_of(pos):
    """
    Geocentric latitude in degrees of a position (the angle above the
    equatorial plane seen from the Earth's centre). The same in TEME and
    ECEF, and good enough for the polar ISL cut-off.
    """
    x, y, z = pos
    return math.degrees(math.asin(z / math.sqrt(x * x + y * y + z * z)))


def propagation_delay_ms(a, b):
    """One-way propagation delay in milliseconds between two points."""
    return distance(a, b) / C_KM_PER_MS


if __name__ == '__main__':
    cfg = config()
    sats = build_constellation()
    print(f"Built {len(sats)} satellites "
          f"({cfg.planes} planes x {cfg.sats_per_plane} sats) "
          f"at {cfg.altitude_km} km")

    period_min = 2 * math.pi / mean_motion_rad_per_min(cfg.altitude_km)
    print(f"Orbital period: {period_min:.2f} minutes")

    jd, fr = jday(EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY, 0, 0, 0)
    print(f"GMST at the epoch: {math.degrees(gmst_rad(jd, fr)):.2f} deg")

    times, positions = propagate(sats, duration_s=10, step_s=5)
    print(f"Propagated {len(times)} timesteps, "
          f"{last_propagation_stats().skipped} skipped")

    p0 = positions[0][0]
    lat, lon, alt = ecef_to_geodetic(p0)
    print(f"Sat 0 at t=0: altitude {alt:.1f} km above WGS84, "
          f"latitude {lat:.1f} deg, longitude {lon:.1f} deg")

    # how far does a satellite move in 1 second? (in the Earth-fixed frame,
    # so this includes the ground turning underneath it)
    t2, pos2 = propagate(sats, duration_s=2, step_s=1)
    moved = distance(pos2[0][0], pos2[1][0])
    # NOTE: this is speed relative to the rotating Earth, not orbital speed.
    # The inertial (TEME) orbital speed of a 550 km satellite is about 7.59 km/s.
    print(f"Sat 0 moves {moved:.2f} km per second relative to the rotating Earth "
          f"(not its orbital speed)")

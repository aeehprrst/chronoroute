"""
constellation.py
----------------
Builds a Walker-Delta LEO constellation and propagates every satellite's
position over time using SGP4 (real orbital physics, not a toy circle model).

Also holds the ground stations (cities) that act as source/destination.

Key output: positions[t][sat_id] = (x, y, z) in km, Earth-Centred Inertial (ECI)
"""

import math
from sgp4.api import Satrec, WGS72, jday

# ----- Physical constants -----
EARTH_RADIUS_KM = 6371.0
MU_EARTH = 398600.4418          # km^3 / s^2  (Earth gravitational parameter)
C_KM_PER_MS = 299.792458        # speed of light in km per millisecond
JD_1949_DEC_31 = 2433281.5      # SGP4 epoch reference

# ----- Constellation design (edit these to change the constellation) -----
NUM_PLANES = 24                 # P : number of orbital planes
SATS_PER_PLANE = 20             # T/P : satellites in each plane
ALTITUDE_KM = 550.0             # shell altitude
INCLINATION_DEG = 53.0          # Starlink-like inclination
PHASING_F = 1                   # Walker-Delta phasing factor

NUM_SATS = NUM_PLANES * SATS_PER_PLANE   # 480

# ----- Simulation epoch -----
EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY = 2026, 9, 10


def mean_motion_rad_per_min(altitude_km):
    """
    Convert an altitude to SGP4's 'no_kozai' mean motion (radians per minute).

    n = sqrt(mu / a^3)  where a is the semi-major axis.
    """
    a = EARTH_RADIUS_KM + altitude_km          # circular orbit -> a = r
    n_rad_per_sec = math.sqrt(MU_EARTH / (a ** 3))
    return n_rad_per_sec * 60.0


def build_constellation():
    """
    Create NUM_SATS SGP4 satellite objects arranged in a Walker-Delta pattern.

    Walker-Delta notation here is  53 deg : 480 / 24 / 1
      - plane p gets RAAN  = p * 360/P                  (planes spread over 360 deg)
      - satellite s in plane p gets mean anomaly
            = s * 360/(T/P)  +  p * F * 360/T           (the F term staggers planes)

    Returns: list of dicts, one per satellite.
    """
    jd, fr = jday(EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY, 0, 0, 0)
    epoch_days = (jd + fr) - JD_1949_DEC_31

    no_kozai = mean_motion_rad_per_min(ALTITUDE_KM)
    inclo = math.radians(INCLINATION_DEG)

    sats = []
    sat_id = 0
    for p in range(NUM_PLANES):
        raan_deg = p * (360.0 / NUM_PLANES)
        for s in range(SATS_PER_PLANE):
            ma_deg = (s * (360.0 / SATS_PER_PLANE)
                      + p * PHASING_F * (360.0 / NUM_SATS)) % 360.0

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


def propagate(sats, duration_s, step_s):
    """
    Run SGP4 for every satellite at every timestep.

    Returns:
        times      : list of simulation times in seconds [0, step, 2*step, ...]
        positions  : positions[t_index][sat_id] = (x, y, z) in km
    """
    jd0, fr0 = jday(EPOCH_YEAR, EPOCH_MONTH, EPOCH_DAY, 0, 0, 0)

    times = list(range(0, duration_s, step_s))
    positions = []

    for t in times:
        # advance the fractional-day part of the Julian date by t seconds
        fr = fr0 + t / 86400.0
        frame = []
        for sat in sats:
            error, r, v = sat['satrec'].sgp4(jd0, fr)
            if error != 0:
                raise RuntimeError(f"SGP4 error {error} on sat {sat['id']} at t={t}")
            frame.append(r)          # r = (x, y, z) km in ECI (TEME) frame
        positions.append(frame)

    return times, positions


# ---------------------------------------------------------------- ground stations

# (name, latitude_deg, longitude_deg)
GROUND_STATIONS = [
    ('Chennai',   13.08,   80.27),
    ('London',    51.51,   -0.13),
    ('NewYork',   40.71,  -74.01),
    ('Sydney',   -33.87,  151.21),
    ('SaoPaulo', -23.55,  -46.63),
    ('Tokyo',     35.68,  139.65),
]

EARTH_ROTATION_RATE_DEG_PER_S = 360.0 / 86164.0905   # sidereal day


def ground_station_positions(times):
    """
    Ground stations are fixed on Earth, but our satellite positions are in an
    inertial frame, so from the satellites' point of view the stations rotate.

    We convert each station's (lat, lon) into the same ECI frame at each
    timestep by adding the Earth's rotation.

    Returns: gs_positions[t_index][gs_index] = (x, y, z) in km
    """
    out = []
    for t in times:
        rotation_deg = EARTH_ROTATION_RATE_DEG_PER_S * t
        frame = []
        for _, lat_deg, lon_deg in GROUND_STATIONS:
            lat = math.radians(lat_deg)
            lon = math.radians(lon_deg + rotation_deg)
            r = EARTH_RADIUS_KM
            frame.append((
                r * math.cos(lat) * math.cos(lon),
                r * math.cos(lat) * math.sin(lon),
                r * math.sin(lat),
            ))
        out.append(frame)
    return out


# ---------------------------------------------------------------- helpers

def distance(a, b):
    """Straight-line distance in km between two (x, y, z) points."""
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def latitude_of(pos):
    """Latitude in degrees of an ECI position (good enough for a link cut-off)."""
    x, y, z = pos
    return math.degrees(math.asin(z / math.sqrt(x * x + y * y + z * z)))


def propagation_delay_ms(a, b):
    """One-way propagation delay in milliseconds between two points."""
    return distance(a, b) / C_KM_PER_MS


if __name__ == '__main__':
    sats = build_constellation()
    print(f"Built {len(sats)} satellites "
          f"({NUM_PLANES} planes x {SATS_PER_PLANE} sats) at {ALTITUDE_KM} km")

    period_min = 2 * math.pi / mean_motion_rad_per_min(ALTITUDE_KM)
    print(f"Orbital period: {period_min:.2f} minutes")

    times, positions = propagate(sats, duration_s=10, step_s=5)
    print(f"Propagated {len(times)} timesteps")

    p0 = positions[0][0]
    alt = distance(p0, (0, 0, 0)) - EARTH_RADIUS_KM
    print(f"Sat 0 at t=0: altitude {alt:.1f} km, latitude {latitude_of(p0):.1f} deg")

    # how far does a satellite move in 1 second?
    t2, pos2 = propagate(sats, duration_s=2, step_s=1)
    moved = distance(pos2[0][0], pos2[1][0])
    print(f"Sat 0 moves {moved:.2f} km per second ({moved:.2f} km/s)")
"""
frames.py
---------
Coordinate frames: TEME (what SGP4 outputs) -> ECEF (fixed to the Earth) ->
WGS84 latitude / longitude / height, and back for ground points.

  TEME  "True Equator, Mean Equinox": an inertial-ish frame. SGP4 positions
        are in it. The website draws the globe in it too (the Earth turns
        underneath), so propagate.py returns TEME as well as ECEF.
  ECEF  Earth-centred, Earth-fixed: rotates with the planet. Cities and
        ground stations sit still in it, so distances and elevation angles
        to the ground are computed here.

TEME -> ECEF is one rotation about the z axis by GMST (Greenwich Mean Sidereal
Time), the angle the Earth has turned. We use the GMST formula that SGP4
itself uses (sgp4.propagation.gstime, IAU-82), with UT1 = UTC and no polar
motion. Ignoring UT1-UTC (|dUT1| < 0.9 s) and polar motion costs well under
1 km at satellite altitude; this is a stated simplification (REAL physics,
simplified).
"""

import numpy as np
from sgp4.propagation import gstime

# Earth rotation rate used by Vallado's teme2ecef (rad/s), for the velocity transform.
EARTH_ROTATION_RAD_S = 7.292115146706979e-5

# WGS84 ellipsoid (the GPS / map datum; city coordinates are WGS84).
WGS84_A_KM = 6378.137
WGS84_F = 1.0 / 298.257223563
WGS84_B_KM = WGS84_A_KM * (1.0 - WGS84_F)
WGS84_E2 = WGS84_F * (2.0 - WGS84_F)            # first eccentricity squared


def gmst_rad(jd, fr=0.0):
    """Greenwich Mean Sidereal Time in radians [0, 2*pi), via sgp4's own gstime.

    jd, fr : Julian date split as sgp4 likes it (UT1 taken equal to UTC).
    Accepts scalars or arrays (one GMST per time; it does not depend on the
    satellite, so a Python loop over a few times is cheap and keeps sgp4's
    exact arithmetic).
    """
    jd_arr, fr_arr = np.broadcast_arrays(np.asarray(jd, dtype=float), np.asarray(fr, dtype=float))
    out = np.array([gstime(float(a) + float(b)) for a, b in zip(jd_arr.ravel(), fr_arr.ravel())])
    out = out.reshape(jd_arr.shape)
    return float(out) if out.ndim == 0 else out


def _rotation_z(theta):
    """3x3 rotation matrices R3(theta) (frame rotation about z), shape (..., 3, 3)."""
    c, s = np.cos(theta), np.sin(theta)
    zero, one = np.zeros_like(c), np.ones_like(c)
    return np.stack([np.stack([c, s, zero], -1),
                     np.stack([-s, c, zero], -1),
                     np.stack([zero, zero, one], -1)], -2)


def teme_to_ecef(r_teme, v_teme, gmst):
    """Rotate TEME position/velocity into ECEF.

    r_teme, v_teme : (..., T, 3) km and km/s; the second-to-last axis is time
    gmst           : (T,) radians, one per time step (or a scalar)

    Position: r_ecef = R3(gmst) r_teme. Velocity also loses the Earth's
    rotation: v_ecef = R3(gmst) v_teme - omega x r_ecef.
    """
    r = np.asarray(r_teme, dtype=float)
    v = np.asarray(v_teme, dtype=float)
    theta = np.asarray(gmst, dtype=float)
    rot = _rotation_z(theta)                          # (T, 3, 3) or (3, 3)
    r_ecef = np.einsum("...ij,...j->...i", rot, r)
    v_rot = np.einsum("...ij,...j->...i", rot, v)
    w = EARTH_ROTATION_RAD_S
    v_ecef = v_rot.copy()
    v_ecef[..., 0] += w * r_ecef[..., 1]
    v_ecef[..., 1] -= w * r_ecef[..., 0]
    return r_ecef, v_ecef


def ecef_to_teme(r_ecef, v_ecef, gmst):
    """The inverse of teme_to_ecef (e.g. to place a city in the website's inertial frame)."""
    r = np.asarray(r_ecef, dtype=float)
    v = np.asarray(v_ecef, dtype=float).copy()
    w = EARTH_ROTATION_RAD_S
    v[..., 0] -= w * r[..., 1]
    v[..., 1] += w * r[..., 0]
    rot_t = np.swapaxes(_rotation_z(np.asarray(gmst, dtype=float)), -1, -2)
    return (np.einsum("...ij,...j->...i", rot_t, r),
            np.einsum("...ij,...j->...i", rot_t, v))


def geodetic_to_ecef(lat_deg, lon_deg, height_km=0.0):
    """WGS84 latitude/longitude (degrees) and ellipsoidal height (km) -> ECEF km, shape (..., 3)."""
    lat = np.radians(np.asarray(lat_deg, dtype=float))
    lon = np.radians(np.asarray(lon_deg, dtype=float))
    h = np.asarray(height_km, dtype=float)
    sin_lat = np.sin(lat)
    n = WGS84_A_KM / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)   # prime-vertical radius
    x = (n + h) * np.cos(lat) * np.cos(lon)
    y = (n + h) * np.cos(lat) * np.sin(lon)
    z = (n * (1.0 - WGS84_E2) + h) * sin_lat
    return np.stack(np.broadcast_arrays(x, y, z), -1)


def ecef_to_geodetic(r_ecef, iterations=6):
    """ECEF km (..., 3) -> (lat_deg, lon_deg, height_km) on WGS84.

    Bowring's method: start from a good guess and refine. Six rounds take any
    point from the ground to GEO below a micrometre; a test checks round trips.
    """
    r = np.asarray(r_ecef, dtype=float)
    x, y, z = r[..., 0], r[..., 1], r[..., 2]
    p = np.hypot(x, y)
    lon = np.arctan2(y, x)
    lat = np.arctan2(z, p * (1.0 - WGS84_E2))                      # first guess
    for _ in range(iterations):
        sin_lat = np.sin(lat)
        n = WGS84_A_KM / np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
        lat = np.arctan2(z + WGS84_E2 * n * sin_lat, p)
    sin_lat, cos_lat = np.sin(lat), np.cos(lat)
    # Height formula that stays accurate both near the equator and near the poles.
    height = p * cos_lat + z * sin_lat - WGS84_A_KM * np.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    return np.degrees(lat), np.degrees(lon), height


def elevation_deg(ground_ecef, target_ecef, ground_lat_deg, ground_lon_deg):
    """Elevation angle (degrees above the local WGS84 horizon) of target seen from ground.

    The "up" direction is the ellipsoid normal at the ground point (geodetic
    latitude), which is what an antenna mask angle refers to.
    """
    lat = np.radians(np.asarray(ground_lat_deg, dtype=float))
    lon = np.radians(np.asarray(ground_lon_deg, dtype=float))
    up = np.stack([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], -1)
    d = np.asarray(target_ecef, dtype=float) - np.asarray(ground_ecef, dtype=float)
    dist = np.linalg.norm(d, axis=-1)
    sin_el = np.einsum("...i,...i->...", d, up) / dist
    return np.degrees(np.arcsin(np.clip(sin_el, -1.0, 1.0)))


def jday_from_ns(ns):
    """Integer UTC nanoseconds (an int or a sequence of ints) -> (jd, fr) for sgp4.

    The day number and the fraction of the day are split with integer
    arithmetic, so a time like 14:02:22 keeps full precision in fr.
    Returns floats for an int input and numpy arrays for a sequence.
    """
    scalar = isinstance(ns, (int, np.integer))
    values = [int(ns)] if scalar else [int(x) for x in ns]
    day_ns = 86_400 * 1_000_000_000
    jd = np.array([2440587.5 + (x // day_ns) for x in values], dtype=float)
    fr = np.array([(x % day_ns) / day_ns for x in values], dtype=float)
    return (float(jd[0]), float(fr[0])) if scalar else (jd, fr)


__all__ = [
    "EARTH_ROTATION_RAD_S", "WGS84_A_KM", "WGS84_F", "WGS84_B_KM", "WGS84_E2",
    "gmst_rad", "teme_to_ecef", "ecef_to_teme", "geodetic_to_ecef", "ecef_to_geodetic",
    "elevation_deg", "jday_from_ns",
]

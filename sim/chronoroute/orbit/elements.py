"""
elements.py
-----------
Small formulas on mean orbital elements, used to sort the fleet into shells
and planes (DERIVED quantities).

Why mean elements and not SGP4 positions: a satellite's instantaneous
(osculating) altitude wobbles by several km around the orbit because the Earth
is not a sphere, so grouping by instantaneous altitude would smear the shells.
The mean motion in an element set is already averaged, so the altitude derived
from it is the same all the way round the orbit.

Known limitation (stated wherever it surfaces): the altitude a - R_E derived
from the Kozai mean motion carries a systematic bias of a few km (about +-5 km)
against the true mean altitude. It is the same for every satellite in a shell,
so it does not blur the shells, but quoted altitudes are "mean-element
altitudes", not geodetic heights.
"""

import math

import numpy as np

# Earth constants (WGS84 / EGM96). The altitude rule of the plan is a - 6378.137 km.
MU_KM3_S2 = 398600.4418          # gravitational parameter, km^3/s^2
EARTH_RADIUS_KM = 6378.137       # WGS84 equatorial radius
J2 = 1.08262668e-3               # EGM96 J2 (unnormalised)
SECONDS_PER_DAY = 86_400.0


def mean_motion_rad_s(mean_motion_rev_day):
    """Mean motion in rad/s from revolutions per day (as published in OMM)."""
    return np.asarray(mean_motion_rev_day, dtype=float) * (2.0 * math.pi / SECONDS_PER_DAY)


def semi_major_axis_km(mean_motion_rev_day):
    """Kepler's third law: a = (mu / n^2)^(1/3)."""
    n = mean_motion_rad_s(mean_motion_rev_day)
    return np.cbrt(MU_KM3_S2 / (n * n))


def altitude_km(mean_motion_rev_day):
    """Mean-element altitude a - R_E in km (see the module docstring for its bias)."""
    return semi_major_axis_km(mean_motion_rev_day) - EARTH_RADIUS_KM


def raan_rate_rad_s(mean_motion_rev_day, eccentricity, inclination_deg):
    """Secular drift of the ascending node caused by J2 (the Earth's equatorial bulge).

        dRAAN/dt = -3/2 * n * J2 * (R_E / p)^2 * cos(i),   p = a (1 - e^2)

    This is why planes must be compared at one common instant: a 53 deg shell's
    planes all turn westward by about 4.5 deg per day, and element sets whose
    epochs differ by a few hours would otherwise look like different planes.
    """
    n = mean_motion_rad_s(mean_motion_rev_day)
    a = np.cbrt(MU_KM3_S2 / (n * n))
    e = np.asarray(eccentricity, dtype=float)
    p = a * (1.0 - e * e)
    inc = np.radians(np.asarray(inclination_deg, dtype=float))
    return -1.5 * n * J2 * (EARTH_RADIUS_KM / p) ** 2 * np.cos(inc)


def raan_at_deg(raan_deg, epoch_ns, t_ns, mean_motion_rev_day, eccentricity, inclination_deg):
    """RAAN carried from each element set's epoch to the common instant t_ns (degrees, 0..360).

    epoch_ns and t_ns are integer UTC nanoseconds; the time difference is taken
    in integers first so no precision is lost before converting to seconds.
    """
    epoch_ns = np.asarray(epoch_ns, dtype=np.int64)
    dt_s = (np.int64(t_ns) - epoch_ns).astype(float) / 1e9
    rate = raan_rate_rad_s(mean_motion_rev_day, eccentricity, inclination_deg)
    return np.mod(np.asarray(raan_deg, dtype=float) + np.degrees(rate * dt_s), 360.0)


def circular_difference_deg(a, b):
    """Signed smallest difference a - b on a circle, in (-180, 180]."""
    d = np.mod(np.asarray(a, dtype=float) - np.asarray(b, dtype=float) + 180.0, 360.0) - 180.0
    return np.where(d == -180.0, 180.0, d)


def circular_mean_deg(angles_deg):
    """Mean direction of angles on a circle (degrees, 0..360)."""
    rad = np.radians(np.asarray(angles_deg, dtype=float))
    return float(np.mod(np.degrees(math.atan2(np.sin(rad).mean(), np.cos(rad).mean())), 360.0))

"""
propagate.py
------------
Where is every satellite at time t? Vectorised SGP4 for the whole fleet.

SGP4 is the model the element sets were fitted with, so it is the only right
way to turn them into positions (REAL physics + REAL code: the C++ SGP4 inside
the `sgp4` package). sgp4's SatrecArray runs all satellites x all times in one
C++ call, about 5-6 ms for 10k satellites at one instant.

Outputs, per satellite and time:
  r_teme, v_teme   km, km/s in TEME (inertial; what the website draws)
  r_ecef, v_ecef   km, km/s in ECEF (Earth-fixed; for ground links)
  lat, lon, height WGS84 geodetic (degrees, km)
  error            SGP4 error code (0 = fine). Where it is not 0 every
                   position is NaN, so a failed satellite can never be
                   silently used as if it were at the origin.

Satellites are identified by NORAD_CAT_ID from the OMM JSON (never by sgp4's
satnum, which stops at 339999).
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sgp4.api import SatrecArray

from ..data.omm import datetime_to_ns, make_satrec
from . import frames


def as_ns_list(times):
    """Normalise times to a list of integer UTC nanoseconds.

    Accepts one time or a sequence; each may be an int (UTC ns) or an aware
    datetime. Floats are refused: a float of nanoseconds since 1970 cannot
    hold full precision.
    """
    if isinstance(times, (int, np.integer, datetime)):
        times = [times]
    out = []
    for t in times:
        if isinstance(t, datetime):
            out.append(datetime_to_ns(t))
        elif isinstance(t, (int, np.integer)) and not isinstance(t, bool):
            out.append(int(t))
        else:
            raise TypeError(f"time {t!r} must be an int (UTC ns) or an aware datetime")
    if not out:
        raise ValueError("no times given")
    return out


@dataclass(frozen=True)
class FleetState:
    """Positions of N satellites at T times (arrays are N x T or N x T x 3)."""

    norad: np.ndarray        # (N,) int64, NORAD_CAT_ID
    times_ns: tuple          # (T,) UTC ns
    jd: np.ndarray           # (T,)
    fr: np.ndarray           # (T,)
    gmst: np.ndarray         # (T,) radians
    error: np.ndarray        # (N, T) uint8 SGP4 error code
    r_teme: np.ndarray       # (N, T, 3) km
    v_teme: np.ndarray       # (N, T, 3) km/s
    r_ecef: np.ndarray       # (N, T, 3) km
    v_ecef: np.ndarray       # (N, T, 3) km/s
    lat: np.ndarray          # (N, T) deg, WGS84 geodetic
    lon: np.ndarray          # (N, T) deg
    height: np.ndarray       # (N, T) km above the WGS84 ellipsoid

    @property
    def ok(self):
        """(N, T) True where SGP4 succeeded."""
        return self.error == 0


class SatelliteArray:
    """A fixed set of satellites that can be propagated together.

        sats = SatelliteArray(records)          # records: OmmRecord sequence
        state = sats.propagate([t0_ns, t1_ns])  # FleetState

    records may come from data.omm.screen_objects(); passing its `satrecs`
    reuses the Satrec objects already built during screening.
    """

    def __init__(self, records, satrecs=None):
        self.records = tuple(records)
        if not self.records:
            raise ValueError("no satellites")
        self.norad = np.array([r.norad for r in self.records], dtype=np.int64)
        if len(set(self.norad.tolist())) != len(self.norad):
            raise ValueError("NORAD ids must be unique")
        self.index = {int(n): i for i, n in enumerate(self.norad)}
        if satrecs is None:
            self._satrecs = [make_satrec(r) for r in self.records]
        else:
            self._satrecs = [satrecs[r.norad] if r.norad in satrecs else make_satrec(r)
                             for r in self.records]
        self._array = SatrecArray(self._satrecs)

    @classmethod
    def from_screen(cls, screen):
        """Build from a data.omm.ScreenResult (its kept records and Satrecs)."""
        return cls(screen.kept, satrecs=screen.satrecs)

    def __len__(self):
        return len(self.records)

    def satrec(self, norad):
        """The single-satellite sgp4 Satrec (for cross-checks)."""
        return self._satrecs[self.index[int(norad)]]

    def subset(self, norads):
        """A new SatelliteArray with just these NORAD ids, in the given order."""
        picked = [self.records[self.index[int(n)]] for n in norads]
        sats = {r.norad: self._satrecs[self.index[r.norad]] for r in picked}
        return SatelliteArray(picked, satrecs=sats)

    def propagate(self, times, *, geodetic=True):
        """Propagate every satellite to every time (see the module docstring for outputs)."""
        times_ns = as_ns_list(times)
        jd, fr = frames.jday_from_ns(times_ns)
        error, r, v = self._array.sgp4(jd, fr)
        error = np.asarray(error, dtype=np.uint8)
        r = np.array(r, dtype=float)
        v = np.array(v, dtype=float)
        bad = error != 0
        r[bad] = np.nan
        v[bad] = np.nan
        gmst = np.asarray(frames.gmst_rad(jd, fr), dtype=float)
        r_ecef, v_ecef = frames.teme_to_ecef(r, v, gmst)
        if geodetic:
            lat, lon, height = frames.ecef_to_geodetic(r_ecef)
        else:
            lat = lon = height = np.full(error.shape, np.nan)
        return FleetState(norad=self.norad.copy(), times_ns=tuple(times_ns), jd=jd, fr=fr,
                          gmst=gmst, error=error, r_teme=r, v_teme=v, r_ecef=r_ecef,
                          v_ecef=v_ecef, lat=lat, lon=lon, height=height)


def argument_of_latitude_deg(r, v):
    """Angle from the ascending node to the satellite, measured along its orbit (deg, 0..360).

    Computed from the actual state vector in an inertial frame (TEME):
    h = r x v is the orbit normal, N = z x h points to the ascending node, and
    u is the angle from N to r in the direction of motion. Satellites in one
    orbital plane are put in order by u.
    """
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)
    h = np.cross(r, v)
    node = np.stack([-h[..., 1], h[..., 0], np.zeros(h.shape[:-1])], -1)
    cos_u = np.einsum("...i,...i->...", node, r)
    sin_u = np.einsum("...i,...i->...", h, np.cross(node, r)) / np.linalg.norm(h, axis=-1)
    return np.mod(np.degrees(np.arctan2(sin_u, cos_u)), 360.0)


def osculating_raan_deg(r, v):
    """Right ascension of the ascending node from a TEME state vector (deg, 0..360)."""
    h = np.cross(np.asarray(r, dtype=float), np.asarray(v, dtype=float))
    return np.mod(np.degrees(np.arctan2(h[..., 0], -h[..., 1])), 360.0)

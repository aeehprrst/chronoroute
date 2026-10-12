"""
gsl.py
------
Ground-to-satellite links (GSLs) for city ground stations.

What is REAL and what is not:
  * city coordinates: REAL (Natural Earth, data/static/cities.csv), placed on
    the WGS84 ellipsoid at height 0;
  * the 25 deg elevation mask: ASSUMED (the value in Starlink's filings, as
    used by Hypatia; 30 deg would be Kuiper, 10 deg Telesat);
  * which visible satellites a ground station actually uses: MODELLED. The
    real assignment is not public (a 15 s synchronised re-allocation has been
    measured, arXiv 2310.09242, but is not modelled here).

Visibility (both policies):
  A satellite is VISIBLE from a ground station when its elevation angle above
  the local WGS84 horizon is at least the mask (25 deg). Elevation uses the
  ellipsoid normal ("up" at geodetic latitude), which is what an antenna mask
  refers to. A connected pair is an "up" ground link at that step; its delay
  is the straight-line distance / c, like an ISL. A station connects to at
  most 4 satellites at once (a phased-array terminal / gateway with several
  beams; the existing model's GSL_MAX_SATS).

Which visible satellites are used (the `policy` parameter, MODELLED):

  "sticky_top_k" (the default)
      Hysteresis: a station KEEPS a satellite it is connected to for as long
      as that satellite stays visible. Only a free beam (a satellite set
      below the mask, or fewer than 4 links so far) is given a new satellite:
      the highest elevation not yet used, ties to the lower node id. At the
      first step the station simply takes the 4 highest. A real terminal
      does not drop a working link just because another satellite has risen
      a little higher, and a link that lasts for minutes is what lets the
      ground plan a whole schedule interval on it.

  "highest_elevation_top_k" (the original policy, kept as a labelled variant)
      No hysteresis: at EVERY step the station re-picks its 4 highest
      satellites. A link then disappears as soon as another satellite climbs
      above it, often while it is still 30+ deg up. With a 1 s schedule this
      loses about 2% of the packets at handovers (results/course-milestone,
      first run), so it is only useful to show that effect.

A 25 deg mask also guarantees the physical rule for ground links: the line
of sight leaves the station upwards and rises all the way to the satellite,
so it never dips below the station's horizon (invariants.py checks it).
"""

from dataclasses import asdict, dataclass

import numpy as np

from ..orbit import frames

MASK_LABEL = "ASSUMED"           # the 25 deg value (Starlink filing via Hypatia)
POLICY_LABEL = "MODELLED"        # which visible satellites are used
POLICY_STICKY = "sticky_top_k"
POLICY_PER_STEP = "highest_elevation_top_k"
POLICIES = (POLICY_STICKY, POLICY_PER_STEP)
POLICY_NAME = POLICY_STICKY      # the default


@dataclass(frozen=True)
class GslParams:
    min_elevation_deg: float = 25.0
    max_links_per_gs: int = 4
    policy: str = POLICY_STICKY

    def __post_init__(self):
        if self.policy not in POLICIES:
            raise ValueError(f"unknown ground-link policy {self.policy!r}; use one of {POLICIES}")
        if isinstance(self.max_links_per_gs, bool) or not isinstance(self.max_links_per_gs, int) \
                or self.max_links_per_gs < 1:
            raise ValueError("max_links_per_gs must be a positive integer")

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class GroundStation:
    """One city ground station. g is its registry number: SID = 0xF000 + g."""

    g: int
    name: str
    lat_deg: float
    lon_deg: float
    lat_text: str
    lon_text: str

    @property
    def ecef_km(self):
        return frames.geodetic_to_ecef(self.lat_deg, self.lon_deg, 0.0)


def ground_station_from_city(city, g):
    return GroundStation(g=int(g), name=city.name, lat_deg=city.lat_deg, lon_deg=city.lon_deg,
                         lat_text=city.lat_text, lon_text=city.lon_text)


def elevation_deg(gs, r_ecef_km):
    """Elevation (deg) of every satellite position r_ecef_km (..., 3) seen from gs."""
    return frames.elevation_deg(gs.ecef_km, r_ecef_km, gs.lat_deg, gs.lon_deg)


def _best(candidates, elev_t, node_ids, k):
    """The k candidates with the highest elevation; equal elevation -> lower node id first."""
    if candidates.size <= k:
        return candidates
    order = np.lexsort((node_ids[candidates], -elev_t[candidates]))
    return candidates[order[:k]]


def select_links(elev_deg, node_ids, params=None):
    """The policy above, for one ground station.

    elev_deg  (N, T) elevation of each satellite at each step (NaN = no position)
    node_ids  (N,) node ids of those satellites (the tie-break)
    Returns (visible (N, T) bool, selected (N, T) bool).
    """
    params = params or GslParams()
    elev = np.asarray(elev_deg, dtype=float)
    node_ids = np.asarray(node_ids)
    visible = np.isfinite(elev) & (elev >= params.min_elevation_deg)
    selected = np.zeros_like(visible)
    k = params.max_links_per_gs
    sticky = params.policy == POLICY_STICKY
    kept = np.zeros(elev.shape[0], dtype=bool)
    for t in range(elev.shape[1]):
        vis = visible[:, t]
        # hysteresis: links of the previous step whose satellite is still visible stay up
        kept = (kept & vis) if sticky else np.zeros_like(vis)
        free = k - int(kept.sum())
        new = _best(np.flatnonzero(vis & ~kept), elev[:, t], node_ids, free) if free > 0 else []
        selected[kept, t] = True
        selected[new, t] = True
        kept = selected[:, t].copy()
    return visible, selected


__all__ = [
    "MASK_LABEL", "POLICY_LABEL", "POLICY_STICKY", "POLICY_PER_STEP", "POLICIES", "POLICY_NAME",
    "GslParams", "GroundStation", "ground_station_from_city", "elevation_deg", "select_links",
]

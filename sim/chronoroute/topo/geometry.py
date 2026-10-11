"""
geometry.py
-----------
The two pieces of physics every link needs:

  1. Does the straight line between two points stay high enough above the
     Earth? A laser beam that grazes the atmosphere is useless, so an
     inter-satellite link (ISL) is only allowed while its line of sight stays
     at least 80 km above the WGS84 ellipsoid (the Hypatia rule; 80 km at
     550 km altitude allows links of about 5,016 km, at 463 km about 4,514 km).
  2. How long does light take? Delay = distance / c, in INTEGER nanoseconds,
     because routing costs, deadlines and the ns-3 bundle must be exact and
     identical everywhere (no float sums whose order changes the answer).

Everything is vectorised with numpy: the 463 km shell has ~5,700 candidate
links, and a 60 s scenario at 100 ms steps checks each of them 601 times.

Why the height test is exact and still fast:
  * The Earth's surface lies between two spheres: radius b (polar,
    6356.752 km) and radius a (equatorial, 6378.137 km).
  * Let r_min be the smallest distance from the Earth's centre to any point
    of the segment (closest approach, a closed formula).
  * Every point of the segment is at least r_min from the centre, and the
    surface is never further out than a, so the height is at least
    r_min - a. If r_min - a >= 80 km the link certainly clears.
  * The point at r_min is at most r_min - b above the surface (the surface
    point straight below it is at least b from the centre). If
    r_min - b < 80 km the link certainly fails.
  * Only a link whose r_min falls in the 21 km band in between needs the
    exact answer: a golden-section search on the geodetic height along the
    segment. Height above a convex body is a convex function of position,
    and in that band the segment never enters the Earth, so the height along
    the segment has one minimum and golden-section search finds it.
"""

import numpy as np

from ..orbit import frames

# Speed of light, exact by the SI definition of the metre.
C_M_PER_S = 299_792_458
# Per-hop processing (store-and-forward / switching) delay: the existing
# model's 0.5 ms (sim/legacy/topology.py PROCESSING_DELAY_MS). MODELLED.
PROCESSING_NS = 500_000
# Grazing altitude for laser links (Hypatia's rule, see the module docstring).
MIN_GRAZING_ALT_KM = 80.0

# How many golden-section steps: each keeps 61.8% of the interval, so 80
# steps shrink it to 2e-17 of the segment (far below a millimetre).
GOLDEN_STEPS = 80
_INV_PHI = (np.sqrt(5.0) - 1.0) / 2.0


def propagation_ns(dist_km):
    """Light time over dist_km, rounded to the NEAREST integer nanosecond (int64).

    round(d / c) with halves rounded up: floor(d_km * 1e12 / c + 0.5). One
    fixed formula, so every caller (bundle, router, invariants) gets the same
    integer. Rounding to nearest means the stored value can be up to 0.5 ns
    below the exact light time; the per-hop delay used for routing adds the
    0.5 ms processing delay, so it is always far above distance / c.
    NaN distances (a satellite whose SGP4 failed) give -1.
    """
    d = np.asarray(dist_km, dtype=float)
    out = np.floor(d * 1e12 / C_M_PER_S + 0.5)
    out = np.where(np.isfinite(out), out, -1.0)
    return out.astype(np.int64)


def light_time_ns_exact(dist_km):
    """distance / c in nanoseconds as a float (for invariant checks only)."""
    return np.asarray(dist_km, dtype=float) * 1e12 / C_M_PER_S


def closest_approach(pa, pb):
    """For segments pa->pb (..., 3) km: (r_min_km, t_star).

    t_star in [0, 1] is where the segment comes closest to the Earth's
    centre; r_min_km is that smallest distance.
    """
    pa = np.asarray(pa, dtype=float)
    pb = np.asarray(pb, dtype=float)
    d = pb - pa
    dd = np.einsum("...i,...i->...", d, d)
    num = -np.einsum("...i,...i->...", pa, d)
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(dd > 0.0, num / np.where(dd > 0.0, dd, 1.0), 0.0)
    t = np.clip(t, 0.0, 1.0)
    q = pa + t[..., None] * d
    return np.linalg.norm(q, axis=-1), t


def _height_along(pa, d, t):
    _, _, h = frames.ecef_to_geodetic(pa + t[..., None] * d)
    return h


def segment_min_height_km(pa, pb, steps=GOLDEN_STEPS):
    """Exact lowest height (km above WGS84) of each straight segment pa->pb.

    Golden-section search on the geodetic height along the segment, then the
    two end points are also considered (a short, steep segment can be lowest
    at an end). Vectorised over any leading shape. Only meaningful for
    segments that stay outside the Earth (see the module docstring); callers
    use segment_clears(), which only asks for segments in that case.
    """
    pa = np.asarray(pa, dtype=float)
    pb = np.asarray(pb, dtype=float)
    d = pb - pa
    shape = pa.shape[:-1]
    lo = np.zeros(shape)
    hi = np.ones(shape)
    x1 = hi - _INV_PHI * (hi - lo)
    x2 = lo + _INV_PHI * (hi - lo)
    h1 = _height_along(pa, d, x1)
    h2 = _height_along(pa, d, x2)
    for _ in range(steps):
        left = h1 <= h2                       # the minimum is in [lo, x2]
        hi = np.where(left, x2, hi)
        lo = np.where(left, lo, x1)
        new_x1 = hi - _INV_PHI * (hi - lo)
        new_x2 = lo + _INV_PHI * (hi - lo)
        # keep the point we already know, evaluate only the new one
        x_new = np.where(left, new_x1, new_x2)
        h_new = _height_along(pa, d, x_new)
        x1, h1, x2, h2 = (np.where(left, new_x1, x2), np.where(left, h_new, h2),
                          np.where(left, x1, new_x2), np.where(left, h1, h_new))
    ends = np.minimum(_height_along(pa, d, np.zeros(shape)), _height_along(pa, d, np.ones(shape)))
    return np.minimum(np.minimum(h1, h2), ends)


def segment_clears(pa, pb, min_alt_km=MIN_GRAZING_ALT_KM):
    """True where the whole segment pa->pb stays >= min_alt_km above WGS84.

    Exact (see the module docstring): the two-sphere bounds decide almost
    every segment; the few in the 21 km band between them get the exact
    golden-section height. NaN input (failed SGP4) gives False.
    """
    pa = np.asarray(pa, dtype=float)
    pb = np.asarray(pb, dtype=float)
    shape = np.broadcast_shapes(pa.shape, pb.shape)[:-1]
    pa = np.broadcast_to(pa, shape + (3,)).reshape(-1, 3)      # flat, so one segment works too
    pb = np.broadcast_to(pb, shape + (3,)).reshape(-1, 3)
    r_min, _ = closest_approach(pa, pb)
    finite = np.isfinite(r_min)
    sure_ok = finite & (r_min - frames.WGS84_A_KM >= min_alt_km)
    sure_bad = ~finite | (r_min - frames.WGS84_B_KM < min_alt_km)
    out = sure_ok.copy()
    unsure = ~(sure_ok | sure_bad)
    if np.any(unsure):
        out[unsure] = segment_min_height_km(pa[unsure], pb[unsure]) >= min_alt_km
    return out.reshape(shape)


def height_lower_bound_km(pa, pb):
    """A certified lower bound on the segment's lowest height: r_min - a."""
    r_min, _ = closest_approach(pa, pb)
    return r_min - frames.WGS84_A_KM


__all__ = [
    "C_M_PER_S", "PROCESSING_NS", "MIN_GRAZING_ALT_KM", "propagation_ns",
    "light_time_ns_exact", "closest_approach", "segment_min_height_km",
    "segment_clears", "height_lower_bound_km",
]

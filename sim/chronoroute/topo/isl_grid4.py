"""
isl_grid4.py
------------
Grid-4 laser links (MODELLED) on the REAL fleet's DERIVED planes.

Starlink does not publish which satellites its lasers point at, so this is a
model, labelled MODELLED wherever it surfaces. It is the classic "+Grid"
pattern of the 2018 filing as used by Hypatia: every satellite has at most
four lasers,

  * 2 intra-plane links: to the satellite ahead and the satellite behind it
    in its own orbital plane (neighbours by argument of latitude u; the ring
    is closed, the last slot links back to slot 0);
  * 2 cross-plane links: one into each adjacent plane (the planes just east
    and west of it by ascending node, ring closed), to a satellite at nearly
    the same u.

On a perfect Walker grid "the matching satellite in the next plane" is
obvious. The real 53 deg / 463 km shell is not perfect (104 planes of 15 to
31 satellites, uneven gaps), so the cross-plane partner is chosen by a
ONE-TO-ONE matching between each pair of adjacent planes:

  1. list every (a in plane A, b in plane B) with circular |u_a - u_b| at or
     below a cap (one nominal in-plane spacing, 360 / median plane size);
  2. sort the candidates by (|du|, NORAD a, NORAD b) -- fully deterministic;
  3. walk the list and accept a pair when neither satellite already has a
     partner in that plane pair (greedy matching: the nearest pairs go first).

Because each satellite is matched at most once towards each neighbouring
plane, its degree is at most 2 (intra) + 2 (cross) = 4 by construction, and
invariants.py checks it. A satellite facing a gap in the next plane simply
has no partner there (no long diagonal link is invented).

Pairs are chosen ONCE per run start (the reference instant of the plane
geometry); after that only their up/down state changes, at every time step:

  * cross-plane links are switched off while either end is above |lat| 70 deg
    (the existing model's rule: near the poles neighbouring planes cross and
    the relative motion is too fast to track);
  * any link whose straight line of sight dips below 80 km above WGS84 is
    down at that step (geometry.segment_clears);
  * optional laser range limit (Grid4Params.max_range_km): a link longer
    than this is down at that step. The default is None (no limit), because
    the laser-link model limits laser links only
    by the 80 km rule, and we know no published terminal range that we could
    check. Why the knob exists: on the REAL planes an intra-plane link joins
    slot neighbours however far apart they are, so a plane with a gap
    (missing satellites) gets one long hop; at 463 km the 80 km rule alone
    allows up to about 4,514 km. Bundles and web exports record the value;
  * a link touching a satellite whose SGP4 failed is down.

Satellites flagged OFF-GRID by the plane inference (fragments too small to
be a plane) have no slot, so they get no Grid-4 links; scenarios leave them
out and say how many (ASSUMED: no inter-shell links either).
"""

from dataclasses import asdict, dataclass

import numpy as np

from . import geometry

LABEL = "MODELLED"
MODEL_NAME = "grid4"
INTRA, CROSS = 0, 1
KIND_NAMES = {INTRA: "intra", CROSS: "cross"}
MAX_DEGREE = 4


@dataclass(frozen=True)
class Grid4Params:
    """Every knob of the Grid-4 model (recorded in bundles and web exports)."""

    polar_cutoff_deg: float = 70.0              # cross-plane links off above this |latitude|
    min_grazing_alt_km: float = geometry.MIN_GRAZING_ALT_KM
    cross_max_du_factor: float = 1.0            # cap on |du| for a cross pair, in nominal spacings
    max_range_km: float | None = None           # laser range limit; None = only the 80 km rule

    def __post_init__(self):
        if self.max_range_km is not None and not self.max_range_km > 0:
            raise ValueError(f"max_range_km must be positive or None, got {self.max_range_km!r}")

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Grid4Pairs:
    """The candidate laser links of one shell, chosen at reference_ns.

    a, b      NORAD ids, a < b, rows sorted by (a, b)
    kind      INTRA (0) or CROSS (1)
    du_deg    |u_a - u_b| at the reference instant (circular, degrees)
    """

    shell_id: str
    reference_ns: int
    max_cross_du_deg: float
    a: np.ndarray
    b: np.ndarray
    kind: np.ndarray
    du_deg: np.ndarray

    def __len__(self):
        return len(self.a)

    def degrees(self):
        """NORAD id -> number of Grid-4 links (at most 4)."""
        out = {}
        for n in np.concatenate([self.a, self.b]).tolist():
            out[n] = out.get(n, 0) + 1
        return out

    def counts(self):
        return {"intra": int(np.sum(self.kind == INTRA)), "cross": int(np.sum(self.kind == CROSS))}


def _circular_du(u_a, u_b):
    """|u_a - u_b| on the circle, in [0, 180] degrees."""
    d = np.mod(np.asarray(u_a, dtype=float) - np.asarray(u_b, dtype=float), 360.0)
    return np.minimum(d, 360.0 - d)


def intra_plane_pairs(norads, u_deg):
    """Ring links inside one plane: each satellite to the next one by u.

    norads/u_deg are the plane's satellites (any order); returns a list of
    (norad_a, norad_b, du_deg). One satellite: no link; two: one link (ahead
    and behind are the same satellite, so it is counted once).
    """
    n = len(norads)
    if n < 2:
        return []
    order = sorted(range(n), key=lambda i: (u_deg[i], norads[i]))      # slot order
    ring = [(norads[order[i]], norads[order[(i + 1) % n]],
             float(_circular_du(u_deg[order[i]], u_deg[order[(i + 1) % n]])))
            for i in range(n if n > 2 else 1)]
    return ring


def match_adjacent_planes(norads_a, u_a, norads_b, u_b, max_du_deg):
    """One-to-one greedy matching on nearest u between two planes.

    Returns a list of (norad_from_A, norad_from_B, du_deg). See the module
    docstring for the rule. Deterministic: ties in du are broken by NORAD
    ids, so the same input always gives the same pairs.
    """
    na = np.asarray(norads_a, dtype=np.int64)
    nb = np.asarray(norads_b, dtype=np.int64)
    if na.size == 0 or nb.size == 0:
        return []
    du = _circular_du(np.asarray(u_a, dtype=float)[:, None], np.asarray(u_b, dtype=float)[None, :])
    ia, ib = np.nonzero(du <= max_du_deg)
    if ia.size == 0:
        return []
    cost = du[ia, ib]
    order = np.lexsort((nb[ib], na[ia], cost))          # by cost, then NORAD a, then NORAD b
    used_a, used_b, out = set(), set(), []
    for k in order.tolist():
        x, y = int(ia[k]), int(ib[k])
        if x in used_a or y in used_b:
            continue
        used_a.add(x)
        used_b.add(y)
        out.append((int(na[x]), int(nb[y]), float(cost[k])))
    return out


def nominal_spacing_deg(shell_geometry):
    """360 / median plane size: the in-plane spacing of a full plane (DERIVED)."""
    sizes = [p.size for p in shell_geometry.planes]
    if not sizes:
        return None
    return 360.0 / float(np.median(sizes))


def grid4_pairs(shell_geometry, reference_ns, params=None):
    """Grid-4 candidate links of one shell (orbit.planes.ShellGeometry).

    Uses the planes in node (RAAN) order and the satellites' argument of
    latitude at the geometry's reference instant (plane.u_deg). Build the
    geometry at the run's start time so that the pairs are those of the run
    start (planes.build_fleet_geometry(records, t_start)); reference_ns is
    that instant (UTC ns), recorded with the pairs.
    """
    params = params or Grid4Params()
    planes = list(shell_geometry.planes)
    spacing = nominal_spacing_deg(shell_geometry)
    max_du = params.cross_max_du_factor * spacing if spacing is not None else 0.0
    rows = []
    for plane in planes:
        for a, b, du in intra_plane_pairs(list(plane.norads), list(plane.u_deg)):
            rows.append((min(a, b), max(a, b), INTRA, du))
    n = len(planes)
    adjacent = [(j, j + 1) for j in range(n - 1)]
    if n >= 3:
        adjacent.append((n - 1, 0))                     # close the ring of planes
    for j, k in adjacent:
        pa, pb = planes[j], planes[k]
        for a, b, du in match_adjacent_planes(pa.norads, pa.u_deg, pb.norads, pb.u_deg, max_du):
            rows.append((min(a, b), max(a, b), CROSS, du))
    rows.sort()
    keys = [(r[0], r[1]) for r in rows]
    if len(set(keys)) != len(keys):
        # Cannot happen: a satellite sits in one plane, so an intra pair is never
        # a cross pair, and each pair of adjacent planes is matched only once.
        # A duplicate would mean a broken plane list, so stop rather than
        # silently doubling a link.
        raise ValueError(f"shell {shell_geometry.shell_id}: a Grid-4 pair was produced twice "
                         "(is a satellite listed in two planes?)")
    arr = np.array([(r[0], r[1]) for r in rows], dtype=np.int64).reshape(-1, 2)
    return Grid4Pairs(
        shell_id=shell_geometry.shell_id,
        reference_ns=int(reference_ns),
        max_cross_du_deg=float(max_du),
        a=arr[:, 0].copy(), b=arr[:, 1].copy(),
        kind=np.array([r[2] for r in rows], dtype=np.uint8),
        du_deg=np.array([r[3] for r in rows], dtype=float))


def isl_state(idx_a, idx_b, kind, r_ecef_km, lat_deg, params=None):
    """Up/down and length of every candidate link at every time step.

    idx_a, idx_b  (L,) row indices into the position arrays
    kind          (L,) INTRA / CROSS
    r_ecef_km     (N, T, 3) satellite positions (NaN where SGP4 failed)
    lat_deg       (N, T) geodetic latitude
    Returns (up (L, T) bool, dist_km (L, T) float).
    """
    params = params or Grid4Params()
    idx_a = np.asarray(idx_a)
    idx_b = np.asarray(idx_b)
    pa = r_ecef_km[idx_a]                               # (L, T, 3)
    pb = r_ecef_km[idx_b]
    dist = np.linalg.norm(pb - pa, axis=-1)
    up = geometry.segment_clears(pa, pb, params.min_grazing_alt_km)
    cross = (np.asarray(kind) == CROSS)[:, None]
    polar = (np.abs(lat_deg[idx_a]) > params.polar_cutoff_deg) | \
            (np.abs(lat_deg[idx_b]) > params.polar_cutoff_deg)
    up &= ~(cross & polar)
    up &= np.isfinite(dist)
    if params.max_range_km is not None:
        with np.errstate(invalid="ignore"):         # NaN distances are already down
            up &= dist <= params.max_range_km
    return up, dist


__all__ = [
    "LABEL", "MODEL_NAME", "INTRA", "CROSS", "KIND_NAMES", "MAX_DEGREE", "Grid4Params",
    "Grid4Pairs", "intra_plane_pairs", "match_adjacent_planes", "nominal_spacing_deg",
    "grid4_pairs", "isl_state",
]

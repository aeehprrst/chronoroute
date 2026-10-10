"""
topology.py
-----------
Turns raw satellite positions into a network graph at each moment in time.

This is where the "time-varying graph" idea becomes concrete: we build one
networkx graph per timestep. The graph changes because:
  - cross-plane inter-satellite links (ISLs) are cut near the poles, where
    neighbouring planes converge and relative velocity is too high
  - an ISL whose line of sight would pass too close to the Earth is cut
  - ground-station links (GSLs) hand over as satellites fly past

Node naming:
  satellites    -> integer 0 .. num_sats()-1
  ground stations -> string 'GS:Chennai', 'GS:London', ...

All positions are ECEF km (see constellation.py) and the Earth is the WGS84
ellipsoid.
"""

import functools
import math

import networkx as nx

import constellation as C
from constellation import (
    GROUND_STATIONS, distance, latitude_of, propagation_delay_ms,
    WGS84_A_KM, WGS84_B_KM, ecef_to_geodetic, geodetic_up,
)

# ----- Link parameters -----
# An ISL is usable only if the straight line between the two satellites stays
# at least this high above the Earth's surface (WGS84), so the laser does not
# graze the atmosphere. This replaces v0's flat 5500 km range: at 550 km it
# allows links up to ~5016 km, at 1015 km up to ~7200 km (the Hypatia rule).
ISL_MIN_GRAZING_ALT_KM = 80.0
POLAR_CUTOFF_DEG = 70.0         # cross-plane ISLs disabled above this latitude
GSL_MIN_ELEVATION_DEG = 25.0    # ground station needs this elevation to connect
GSL_MAX_SATS = 4              # candidate satellites per ground station (phased array)

PROCESSING_DELAY_MS = 0.5       # per-hop store-and-forward / switching delay


def gs_name(index):
    return f"GS:{GROUND_STATIONS[index][0]}"


def isl_neighbour_pairs(cfg=None):
    """
    The static '+Grid' ISL pattern: each satellite has 4 potential neighbours.

      2 intra-plane : the satellite ahead and behind it in its own orbit
      2 cross-plane : the matching satellite in the plane left/right

    This returns the *candidate* pairs. Whether each is actually usable at a
    given moment is decided in build_graph().

    Args:
        cfg : a constellation.ConstellationConfig (default: the active one)

    Returns: list of (sat_a, sat_b, kind) where kind is 'intra' or 'cross'
    """
    if cfg is None:
        cfg = C.config()
    P, S, F = cfg.planes, cfg.sats_per_plane, cfg.phasing_f

    pairs = []
    for p in range(P):
        for s in range(S):
            a = p * S + s

            # intra-plane: link to the next satellite in the same ring
            s_next = (s + 1) % S
            b = p * S + s_next
            pairs.append((a, b, 'intra'))

            # cross-plane: link to the matching satellite in the next plane.
            # Walker phasing shifts each plane F*360/T deg further along its
            # orbit, so slot s in plane p+1 is the right partner. At the seam
            # (last plane -> plane 0) we have gone all the way round: plane 0
            # is P*F*360/T = F*360/S deg ahead, i.e. exactly F slots, so the
            # partner is slot s+F. v0 used slot s here, which made every seam
            # link ~3x longer than a normal cross-plane link on Starlink.
            if p + 1 < P:
                c = (p + 1) * S + s
            else:
                c = (s + F) % S
            pairs.append((a, c, 'cross'))

    return pairs


@functools.lru_cache(maxsize=16)
def _isl_pairs_for(cfg):
    return tuple(isl_neighbour_pairs(cfg))


def isl_pairs():
    """
    Candidate ISL pairs for the ACTIVE constellation, read at call time.

    Use this instead of ISL_PAIRS: a module that did
    `from topology import ISL_PAIRS` holds a copy that a preset switch
    cannot always reach. Returns a tuple (cached, so do not try to edit it).
    """
    return _isl_pairs_for(C.config())


# Old name, kept for the experiment scripts. A COPY for the active
# constellation; scale.apply_config() refreshes it. Prefer isl_pairs().
ISL_PAIRS = list(isl_pairs())


# ---------------------------------------------------------------- geometry

def _closest_approach(pa, pb):
    """
    The point of segment pa->pb nearest the Earth's centre, and its distance
    from the centre, in km.
    """
    dx, dy, dz = pb[0] - pa[0], pb[1] - pa[1], pb[2] - pa[2]
    dd = dx * dx + dy * dy + dz * dz
    t = 0.0
    if dd > 0.0:
        t = -(pa[0] * dx + pa[1] * dy + pa[2] * dz) / dd
        t = min(1.0, max(0.0, t))
    q = (pa[0] + t * dx, pa[1] + t * dy, pa[2] + t * dz)
    return q, math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2])


def segment_min_altitude_km(pa, pb):
    """
    Lowest height above the WGS84 surface of the straight line pa->pb.

    The height of a point above a convex surface like the ellipsoid is a
    convex function of the point, so along a straight line it has a single
    minimum and a golden-section search finds it. 80 steps shrink the search
    interval below 1e-16 of the segment, far below a millimetre.
    """
    def height(t):
        p = (pa[0] + t * (pb[0] - pa[0]),
             pa[1] + t * (pb[1] - pa[1]),
             pa[2] + t * (pb[2] - pa[2]))
        return ecef_to_geodetic(p)[2]

    inv_phi = (math.sqrt(5.0) - 1.0) / 2.0
    lo, hi = 0.0, 1.0
    x1 = hi - inv_phi * (hi - lo)
    x2 = lo + inv_phi * (hi - lo)
    h1, h2 = height(x1), height(x2)
    for _ in range(80):
        if h1 <= h2:
            hi, x2, h2 = x2, x1, h1
            x1 = hi - inv_phi * (hi - lo)
            h1 = height(x1)
        else:
            lo, x1, h1 = x1, x2, h2
            x2 = lo + inv_phi * (hi - lo)
            h2 = height(x2)
    # the ends can be the lowest points too (a short, steep segment)
    return min(h1, h2, height(0.0), height(1.0))


def isl_clears_earth(pa, pb, min_alt_km=ISL_MIN_GRAZING_ALT_KM):
    """
    True if the line of sight pa->pb stays at least min_alt_km above WGS84.

    Fast path first: the Earth lies between a sphere of the polar radius and
    a sphere of the equatorial radius, so if the closest approach to the
    centre (r_min) clears the bigger sphere by min_alt_km the link is
    certainly fine, and if it fails even the smaller sphere it is certainly
    blocked. Only the rare segment in between (r_min within that 21 km band)
    needs the exact ellipsoid search.
    """
    _, r_min = _closest_approach(pa, pb)
    if r_min - WGS84_A_KM >= min_alt_km:
        return True
    if r_min - WGS84_B_KM < min_alt_km:
        return False
    return segment_min_altitude_km(pa, pb) >= min_alt_km


def elevation_angle_deg(gs_pos, sat_pos, up=None):
    """
    Elevation of a satellite above the ground station's local horizon.

    'Up' at the ground station is the WGS84 ellipsoid normal (pass it in as
    `up` to save recomputing it). v0 used the direction from the Earth's
    centre, which is only right on a spherical Earth.
    """
    # vector from ground station to satellite
    dx = sat_pos[0] - gs_pos[0]
    dy = sat_pos[1] - gs_pos[1]
    dz = sat_pos[2] - gs_pos[2]
    d = math.sqrt(dx * dx + dy * dy + dz * dz)
    if d == 0:
        return 90.0

    if up is None:
        up = geodetic_up(gs_pos)
    ux, uy, uz = up

    cos_zenith = (dx * ux + dy * uy + dz * uz) / d
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))


# ---------------------------------------------------------------- graphs

def build_graph(sat_positions, gs_positions, failed_links=None):
    """
    Build the network graph for ONE timestep.

    Args:
        sat_positions : list of (x,y,z) ECEF km, indexed by satellite id.
                        None = SGP4 could not place that satellite at this
                        step; it stays in the graph as a node with no links.
        gs_positions  : list of (x,y,z) ECEF km, indexed by ground station index
        failed_links  : optional set of frozenset({a,b}) links to treat as broken
                        (used by the failure-injection experiment)

    Edge attributes:
        weight    : propagation delay in ms  (we route on latency, not hop count)
        dist_km   : physical length
        kind      : 'intra' | 'cross' | 'gsl'

    Graph attribute:
        skipped_sats : how many satellites had no position at this step

    Returns: networkx.Graph
    """
    if failed_links is None:
        failed_links = set()

    n = C.num_sats()
    G = nx.Graph()

    skipped = 0
    for sid in range(n):
        G.add_node(sid, pos=sat_positions[sid], kind='sat')
        if sat_positions[sid] is None:
            skipped += 1
    G.graph['skipped_sats'] = skipped

    # ---- inter-satellite links ----
    for a, b, kind in isl_pairs():
        if frozenset({a, b}) in failed_links:
            continue

        pa, pb = sat_positions[a], sat_positions[b]
        if pa is None or pb is None:
            continue

        # cross-plane links become unusable near the poles: the planes crowd
        # together and the relative velocity makes laser tracking impractical
        if kind == 'cross':
            if (abs(latitude_of(pa)) > POLAR_CUTOFF_DEG
                    or abs(latitude_of(pb)) > POLAR_CUTOFF_DEG):
                continue

        # the laser must not pass through (or graze) the atmosphere
        if not isl_clears_earth(pa, pb):
            continue

        G.add_edge(a, b,
                   weight=propagation_delay_ms(pa, pb) + PROCESSING_DELAY_MS,
                   dist_km=distance(pa, pb),
                   kind=kind)

    # ---- ground station links ----
    for gi in range(len(GROUND_STATIONS)):
        name = gs_name(gi)
        gpos = gs_positions[gi]
        G.add_node(name, pos=gpos, kind='gs')
        up = geodetic_up(gpos)

        # find every satellite currently above the horizon, keep the closest
        visible = []
        for sid in range(n):
            spos = sat_positions[sid]
            if spos is None:
                continue
            if elevation_angle_deg(gpos, spos, up) >= GSL_MIN_ELEVATION_DEG:
                visible.append((distance(gpos, spos), sid))

        visible.sort()
        for d, sid in visible[:GSL_MAX_SATS]:
            G.add_edge(name, sid,
                       weight=propagation_delay_ms(gpos, sat_positions[sid])
                              + PROCESSING_DELAY_MS,
                       dist_km=d,
                       kind='gsl')

    return G


def build_all_graphs(times, sat_positions, gs_positions, verbose=True):
    """Build one graph per timestep. Returns a list of graphs."""
    graphs = []
    for i, t in enumerate(times):
        graphs.append(build_graph(sat_positions[i], gs_positions[i]))
        if verbose and (i % 20 == 0 or i == len(times) - 1):
            g = graphs[-1]
            print(f"  t={t:4d}s  nodes={g.number_of_nodes()}  "
                  f"edges={g.number_of_edges()}")
    return graphs


if __name__ == '__main__':
    from constellation import build_constellation, propagate, ground_station_positions

    print("Building constellation...")
    sats = build_constellation()
    times, sat_pos = propagate(sats, duration_s=20, step_s=10)
    gs_pos = ground_station_positions(times)

    print(f"\nCandidate ISL pairs: {len(isl_pairs())}")

    G = build_graph(sat_pos[0], gs_pos[0])
    print(f"\nGraph at t=0:")
    print(f"  nodes: {G.number_of_nodes()}  edges: {G.number_of_edges()}")

    kinds = {}
    for _, _, data in G.edges(data=True):
        kinds[data['kind']] = kinds.get(data['kind'], 0) + 1
    print(f"  edge types: {kinds}")

    # check connectivity and a sample route
    print(f"  connected: {nx.is_connected(G)}")

    path = nx.shortest_path(G, 'GS:Chennai', 'GS:London', weight='weight')
    latency = nx.shortest_path_length(G, 'GS:Chennai', 'GS:London', weight='weight')
    print(f"\nChennai -> London:")
    print(f"  hops: {len(path) - 1}")
    print(f"  latency: {latency:.2f} ms")
    print(f"  path: {path}")

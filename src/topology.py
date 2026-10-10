"""
topology.py
-----------
Turns raw satellite positions into a network graph at each moment in time.

This is where the "time-varying graph" idea becomes concrete: we build one
networkx graph per timestep. The graph changes because:
  - cross-plane inter-satellite links (ISLs) are cut near the poles, where
    neighbouring planes converge and relative velocity is too high
  - ground-station links (GSLs) hand over as satellites fly past

Node naming:
  satellites    -> integer 0 .. NUM_SATS-1
  ground stations -> string 'GS:Chennai', 'GS:London', ...
"""

import networkx as nx

from constellation import (
    NUM_PLANES, SATS_PER_PLANE, NUM_SATS, GROUND_STATIONS,
    distance, latitude_of, propagation_delay_ms, EARTH_RADIUS_KM,
)

# ----- Link parameters -----
ISL_MAX_RANGE_KM = 5500.0       # max usable laser ISL range
POLAR_CUTOFF_DEG = 70.0         # cross-plane ISLs disabled above this latitude
GSL_MIN_ELEVATION_DEG = 25.0    # ground station needs this elevation to connect
GSL_MAX_SATS = 4              # candidate satellites per ground station (phased array)

PROCESSING_DELAY_MS = 0.5       # per-hop store-and-forward / switching delay


def gs_name(index):
    return f"GS:{GROUND_STATIONS[index][0]}"


def isl_neighbour_pairs():
    """
    The static '+Grid' ISL pattern: each satellite has 4 potential neighbours.

      2 intra-plane : the satellite ahead and behind it in its own orbit
      2 cross-plane : the satellite at the same index in the plane left/right

    This returns the *candidate* pairs. Whether each is actually usable at a
    given moment is decided in build_graph().

    Returns: list of (sat_a, sat_b, kind) where kind is 'intra' or 'cross'
    """
    pairs = []
    for p in range(NUM_PLANES):
        for s in range(SATS_PER_PLANE):
            a = p * SATS_PER_PLANE + s

            # intra-plane: link to the next satellite in the same ring
            s_next = (s + 1) % SATS_PER_PLANE
            b = p * SATS_PER_PLANE + s_next
            pairs.append((a, b, 'intra'))

            # cross-plane: link to same index in the next plane
            p_next = (p + 1) % NUM_PLANES
            c = p_next * SATS_PER_PLANE + s
            pairs.append((a, c, 'cross'))

    return pairs


ISL_PAIRS = isl_neighbour_pairs()


def elevation_angle_deg(gs_pos, sat_pos):
    """
    Elevation of a satellite above the ground station's local horizon.

    We use the dot product between the station's 'up' vector (which for a
    spherical Earth is just its position vector) and the vector to the
    satellite.
    """
    import math
    # vector from ground station to satellite
    dx = sat_pos[0] - gs_pos[0]
    dy = sat_pos[1] - gs_pos[1]
    dz = sat_pos[2] - gs_pos[2]
    d = math.sqrt(dx * dx + dy * dy + dz * dz)
    if d == 0:
        return 90.0

    # 'up' at the ground station = normalised position vector
    gr = math.sqrt(gs_pos[0] ** 2 + gs_pos[1] ** 2 + gs_pos[2] ** 2)
    ux, uy, uz = gs_pos[0] / gr, gs_pos[1] / gr, gs_pos[2] / gr

    cos_zenith = (dx * ux + dy * uy + dz * uz) / d
    cos_zenith = max(-1.0, min(1.0, cos_zenith))
    return 90.0 - math.degrees(math.acos(cos_zenith))


def build_graph(sat_positions, gs_positions, failed_links=None):
    """
    Build the network graph for ONE timestep.

    Args:
        sat_positions : list of (x,y,z), indexed by satellite id
        gs_positions  : list of (x,y,z), indexed by ground station index
        failed_links  : optional set of frozenset({a,b}) links to treat as broken
                        (used by the failure-injection experiment)

    Edge attributes:
        weight    : propagation delay in ms  (we route on latency, not hop count)
        dist_km   : physical length
        kind      : 'intra' | 'cross' | 'gsl'

    Returns: networkx.Graph
    """
    if failed_links is None:
        failed_links = set()

    G = nx.Graph()

    for sid in range(NUM_SATS):
        G.add_node(sid, pos=sat_positions[sid], kind='sat')

    # ---- inter-satellite links ----
    for a, b, kind in ISL_PAIRS:
        if frozenset({a, b}) in failed_links:
            continue

        pa, pb = sat_positions[a], sat_positions[b]
        d = distance(pa, pb)
        if d > ISL_MAX_RANGE_KM:
            continue

        # cross-plane links become unusable near the poles: the planes crowd
        # together and the relative velocity makes laser tracking impractical
        if kind == 'cross':
            if (abs(latitude_of(pa)) > POLAR_CUTOFF_DEG
                    or abs(latitude_of(pb)) > POLAR_CUTOFF_DEG):
                continue

        G.add_edge(a, b,
                   weight=propagation_delay_ms(pa, pb) + PROCESSING_DELAY_MS,
                   dist_km=d,
                   kind=kind)

    # ---- ground station links ----
    for gi in range(len(GROUND_STATIONS)):
        name = gs_name(gi)
        gpos = gs_positions[gi]
        G.add_node(name, pos=gpos, kind='gs')

        # find every satellite currently above the horizon, keep the closest
        visible = []
        for sid in range(NUM_SATS):
            spos = sat_positions[sid]
            if elevation_angle_deg(gpos, spos) >= GSL_MIN_ELEVATION_DEG:
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

    print(f"\nCandidate ISL pairs: {len(ISL_PAIRS)}")

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
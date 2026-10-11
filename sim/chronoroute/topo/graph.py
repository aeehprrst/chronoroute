"""
graph.py
--------
The time-varying network of one scenario, stored compactly.

A scenario is: one shell of the REAL fleet (positions from SGP4), its Grid-4
laser links (MODELLED), some city ground stations with their ground links
(MODELLED policy), and a list of time steps. Instead of one networkx graph
per step (thousands of Python objects per step), everything lives in a few
numpy arrays:

    link_a, link_b   (L,)    end nodes of every CANDIDATE link (a < b)
    link_kind        (L,)    0 intra-plane ISL, 1 cross-plane ISL, 2 ground link
    up               (L, T)  is the link usable at step t
    prop_ns          (L, T)  light time over the link at step t, integer ns

and the graph of one step is built on demand as CSR (compressed sparse rows:
for node u, its neighbours are indices[indptr[u]:indptr[u+1]] with the edge
weights in the same slots). Dijkstra (route/dijkstra.py) reads the CSR.

Edge weight (integer nanoseconds, deterministic):

    weight = round(distance / c) + 500,000 ns processing        (geometry.py)

Node numbering of a scenario: satellites first, sorted by NORAD id
(0 .. S-1), then the ground stations in the order given (S .. S+G-1).
Ground stations may start or end a path but never relay one ("transit"
is False for them): a city is not a satellite relay in this model.
"""

from dataclasses import dataclass, field

import numpy as np

from ..orbit import planes as planes_mod
from ..orbit.propagate import SatelliteArray
from . import geometry, gsl as gsl_mod, isl_grid4

KIND_INTRA = isl_grid4.INTRA          # 0
KIND_CROSS = isl_grid4.CROSS          # 1
KIND_GSL = 2
KIND_NAMES = {KIND_INTRA: "intra", KIND_CROSS: "cross", KIND_GSL: "gsl"}

# Propagate at most this many time steps at once (bounds memory: the 463 km
# shell is ~2,850 satellites, so 200 steps of the full SGP4 output is ~70 MB).
PROPAGATION_CHUNK = 200


# ------------------------------------------------------------------ CSR graph

@dataclass(frozen=True)
class CsrGraph:
    """One undirected weighted graph in CSR form (both directions stored).

    indptr   (V+1,) int64; row u is indices[indptr[u]:indptr[u+1]]
    indices  (E,) int64 neighbour node ids, ascending within a row
    weights  (E,) int64 edge weights in ns
    transit  (V,) bool  False = may start/end a path but not relay one
    """

    indptr: np.ndarray
    indices: np.ndarray
    weights: np.ndarray
    transit: np.ndarray

    @property
    def n_nodes(self):
        return len(self.indptr) - 1

    @property
    def n_edges(self):
        """Undirected edges (each is stored twice)."""
        return len(self.indices) // 2

    def neighbours(self, u):
        lo, hi = self.indptr[u], self.indptr[u + 1]
        return self.indices[lo:hi], self.weights[lo:hi]

    def edge_weight(self, u, v):
        nbr, w = self.neighbours(u)
        hit = np.flatnonzero(nbr == v)
        if hit.size == 0:
            raise KeyError(f"no edge {u}-{v}")
        return int(w[hit[0]])

    def to_networkx(self):
        """A networkx.Graph copy, for tests (networkx is only an oracle here)."""
        import networkx as nx
        g = nx.Graph()
        g.add_nodes_from(range(self.n_nodes))
        for u in range(self.n_nodes):
            nbr, w = self.neighbours(u)
            for v, wt in zip(nbr.tolist(), w.tolist()):
                if u < v:
                    g.add_edge(u, v, weight=wt)
        return g


def csr_from_edges(n_nodes, a, b, w, transit=None):
    """Build an undirected CsrGraph from edge lists (a[i] - b[i] with weight w[i]).

    Duplicate or self edges are refused: the topology never makes them, and a
    silent duplicate would change shortest paths.
    """
    a = np.asarray(a, dtype=np.int64)
    b = np.asarray(b, dtype=np.int64)
    w = np.asarray(w, dtype=np.int64)
    if np.any(a == b):
        raise ValueError("self-loop in edge list")
    if np.any(w <= 0):
        raise ValueError("edge weights must be positive integers (ns)")
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    if len(np.unique(lo * n_nodes + hi)) != len(lo):
        raise ValueError("duplicate edge in edge list")
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    ww = np.concatenate([w, w])
    order = np.lexsort((dst, src))
    src, dst, ww = src[order], dst[order], ww[order]
    counts = np.bincount(src, minlength=n_nodes)
    indptr = np.zeros(n_nodes + 1, dtype=np.int64)
    np.cumsum(counts, out=indptr[1:])
    if transit is None:
        transit = np.ones(n_nodes, dtype=bool)
    return CsrGraph(indptr=indptr, indices=dst, weights=ww, transit=np.asarray(transit, dtype=bool))


# -------------------------------------------------------- time-varying graph

@dataclass(frozen=True)
class TimeVaryingGraph:
    """Candidate links + per-step state (see the module docstring)."""

    n_nodes: int
    transit: np.ndarray
    times_ns: np.ndarray          # (T,) UTC ns
    link_a: np.ndarray            # (L,) int64
    link_b: np.ndarray
    link_kind: np.ndarray         # (L,) uint8
    up: np.ndarray                # (L, T) bool
    prop_ns: np.ndarray           # (L, T) int64 (-1 where a position is missing)
    processing_ns: int = geometry.PROCESSING_NS

    @property
    def n_steps(self):
        return len(self.times_ns)

    def weights_ns(self, k):
        """Edge weight of every link at step k (prop + processing; meaningful where up)."""
        return self.prop_ns[:, k] + self.processing_ns

    def csr_at(self, k):
        mask = self.up[:, k]
        return csr_from_edges(self.n_nodes, self.link_a[mask], self.link_b[mask],
                              self.weights_ns(k)[mask], self.transit)

    def csr_stable(self, k0, k1):
        """Graph of the links that are up at EVERY step k0..k1 (inclusive), weighted at k0.

        This is what a ground planner that knows the predictable topology
        (orbits, handovers) uses for a schedule interval: a path built from
        these links cannot lose a link while the interval's packets are on
        their way. The weights are those of step k0, the planning instant.
        """
        if not 0 <= k0 <= k1 < self.n_steps:
            raise IndexError(f"steps {k0}..{k1} outside 0..{self.n_steps - 1}")
        mask = self.up[:, k0:k1 + 1].all(axis=1)
        return csr_from_edges(self.n_nodes, self.link_a[mask], self.link_b[mask],
                              self.weights_ns(k0)[mask], self.transit)

    def step_index(self, t_ns):
        hit = np.flatnonzero(self.times_ns == t_ns)
        if hit.size == 0:
            raise KeyError(f"no step at {t_ns}")
        return int(hit[0])


# ------------------------------------------------------------------ scenario

@dataclass(frozen=True)
class Scenario:
    """Everything one run needs, built by build_scenario()."""

    fleet: object                       # data.snapshot.Fleet
    shell: object                       # orbit.planes.ShellGeometry (at reference_ns)
    reference_ns: int                   # run start: Grid-4 pairs chosen here
    times_ns: np.ndarray                # (T,)
    sat_norad: np.ndarray               # (S,) node id = index
    sat_name: tuple
    sat_plane: np.ndarray               # (S,) plane index in the shell
    sat_slot: np.ndarray                # (S,)
    sat_sid: np.ndarray                 # (S,)
    ground_stations: tuple              # gsl.GroundStation, node id = S + index
    gs_sid: np.ndarray                  # (G,)
    sat_pos_km: np.ndarray              # (S, T, 3) ECEF km
    sat_lat_deg: np.ndarray             # (S, T)
    grid4: object                       # isl_grid4.Grid4Pairs
    isl_a: np.ndarray                   # (Li,) node ids (a < b)
    isl_b: np.ndarray
    isl_kind: np.ndarray
    isl_up: np.ndarray                  # (Li, T)
    isl_dist_km: np.ndarray             # (Li, T)
    gsl_gs: np.ndarray                  # (Lg,) ground-station index 0..G-1
    gsl_sat: np.ndarray                 # (Lg,) satellite node id
    gsl_visible: np.ndarray             # (Lg, T)
    gsl_up: np.ndarray                  # (Lg, T)
    gsl_dist_km: np.ndarray             # (Lg, T)
    gsl_elev_deg: np.ndarray            # (Lg, T)
    graph: TimeVaryingGraph
    grid_params: object
    gsl_params: object
    excluded: dict = field(default_factory=dict)

    @property
    def n_sats(self):
        return len(self.sat_norad)

    def gs_node(self, index):
        return self.n_sats + index

    def node_name(self, node):
        if node < self.n_sats:
            return self.sat_name[node]
        return self.ground_stations[node - self.n_sats].name

    def node_sid(self, node):
        if node < self.n_sats:
            return int(self.sat_sid[node])
        return int(self.gs_sid[node - self.n_sats])

    def node_ecef_km(self, node, k):
        if node < self.n_sats:
            return self.sat_pos_km[node, k]
        return np.asarray(self.ground_stations[node - self.n_sats].ecef_km)

    def gs_index(self, name):
        for i, gs in enumerate(self.ground_stations):
            if gs.name == name:
                return i
        raise KeyError(name)


def build_scenario(fleet, shell_id, ground_stations, times_ns, *, registry,
                   grid_params=None, gsl_params=None, reference_ns=None):
    """Build the time-varying topology of one shell (see the module docstring).

    fleet            data.snapshot.Fleet (REAL element sets)
    shell_id         e.g. "53.2deg-463km" (orbit.shells ids)
    ground_stations  gsl.GroundStation sequence (their SIDs come from g)
    times_ns         sequence of UTC ns, ascending
    registry         route.sids.SidRegistry; missing satellites are appended
                     IN MEMORY (the caller decides whether to save)
    reference_ns     when the Grid-4 pairs are chosen (default: times_ns[0])
    """
    grid_params = grid_params or isl_grid4.Grid4Params()
    gsl_params = gsl_params or gsl_mod.GslParams()
    times = np.asarray([int(t) for t in times_ns], dtype=np.int64)
    if times.size == 0 or np.any(np.diff(times) <= 0):
        raise ValueError("times_ns must be non-empty and strictly increasing")
    reference_ns = int(times[0]) if reference_ns is None else int(reference_ns)

    geo = planes_mod.build_fleet_geometry(fleet.records, reference_ns, satrecs=fleet.satrecs)
    shell = geo.shell(shell_id)
    plane_of, slot_of = {}, {}
    for plane in shell.planes:
        for slot, n in enumerate(plane.norads):
            plane_of[n] = plane.index
            slot_of[n] = slot
    sat_norad = np.array(sorted(plane_of), dtype=np.int64)
    if sat_norad.size == 0:
        raise ValueError(f"shell {shell_id} has no satellites in planes")
    node_of = {int(n): i for i, n in enumerate(sat_norad)}
    by_norad = {r.norad: r for r in fleet.records}
    records = [by_norad[int(n)] for n in sat_norad]
    registry.ensure_satellites(sat_norad.tolist())
    names = [gs.name for gs in ground_stations]
    if len(set(names)) != len(names):
        raise ValueError("ground stations must be distinct")
    for gs in ground_stations:
        if registry.ground_station_number(gs.name) != gs.g:
            raise ValueError(f"ground station {gs.name}: g={gs.g} disagrees with the SID registry")

    # Grid-4 pairs, chosen once at the run start.
    pairs = isl_grid4.grid4_pairs(shell, reference_ns, grid_params)
    isl_a = np.array([node_of[int(n)] for n in pairs.a], dtype=np.int64)
    isl_b = np.array([node_of[int(n)] for n in pairs.b], dtype=np.int64)
    isl_kind = pairs.kind.copy()

    # Positions: SGP4 for every satellite at every step, in chunks of time.
    sats = SatelliteArray(records, satrecs=fleet.satrecs)
    S, T = len(sat_norad), len(times)
    pos = np.empty((S, T, 3))
    lat = np.empty((S, T))
    for lo in range(0, T, PROPAGATION_CHUNK):
        state = sats.propagate(times[lo:lo + PROPAGATION_CHUNK].tolist())
        pos[:, lo:lo + PROPAGATION_CHUNK] = state.r_ecef
        lat[:, lo:lo + PROPAGATION_CHUNK] = state.lat

    isl_up, isl_dist = isl_grid4.isl_state(isl_a, isl_b, isl_kind, pos, lat, grid_params)

    # Ground links: every (station, satellite) pair that is ever visible.
    node_ids = np.arange(S)
    g_gs, g_sat, g_vis, g_up, g_dist, g_elev = [], [], [], [], [], []
    for i, gs in enumerate(ground_stations):
        elev = gsl_mod.elevation_deg(gs, pos)
        visible, selected = gsl_mod.select_links(elev, node_ids, gsl_params)
        ever = np.flatnonzero(visible.any(axis=1))
        dist = np.linalg.norm(pos[ever] - np.asarray(gs.ecef_km), axis=-1)
        g_gs.append(np.full(ever.size, i, dtype=np.int64))
        g_sat.append(ever.astype(np.int64))
        g_vis.append(visible[ever])
        g_up.append(selected[ever])
        g_dist.append(dist)
        g_elev.append(elev[ever])
    G = len(ground_stations)
    if G:
        gsl_gs, gsl_sat = np.concatenate(g_gs), np.concatenate(g_sat)
        gsl_visible, gsl_up = np.concatenate(g_vis), np.concatenate(g_up)
        gsl_dist, gsl_elev = np.concatenate(g_dist), np.concatenate(g_elev)
    else:
        gsl_gs = gsl_sat = np.zeros(0, dtype=np.int64)
        gsl_visible = gsl_up = np.zeros((0, T), dtype=bool)
        gsl_dist = gsl_elev = np.zeros((0, T))

    transit = np.ones(S + G, dtype=bool)
    transit[S:] = False
    graph = TimeVaryingGraph(
        n_nodes=S + G, transit=transit, times_ns=times,
        link_a=np.concatenate([isl_a, gsl_sat]),
        link_b=np.concatenate([isl_b, S + gsl_gs]),
        link_kind=np.concatenate([isl_kind.astype(np.uint8),
                                  np.full(gsl_gs.size, KIND_GSL, dtype=np.uint8)]),
        up=np.concatenate([isl_up, gsl_up]),
        prop_ns=np.concatenate([geometry.propagation_ns(isl_dist), geometry.propagation_ns(gsl_dist)]))

    excluded = {
        "off_grid": int(sum(len(f.norads) for f in shell.fragments)),
        "note": "off-grid satellites (plane fragments) have no Grid-4 slot and are left out",
    }
    return Scenario(
        fleet=fleet, shell=shell, reference_ns=reference_ns, times_ns=times,
        sat_norad=sat_norad, sat_name=tuple(by_norad[int(n)].name for n in sat_norad),
        sat_plane=np.array([plane_of[int(n)] for n in sat_norad], dtype=np.int64),
        sat_slot=np.array([slot_of[int(n)] for n in sat_norad], dtype=np.int64),
        sat_sid=np.array([registry.satellite_sid(int(n)) for n in sat_norad], dtype=np.int64),
        ground_stations=tuple(ground_stations),
        gs_sid=np.array([registry.ground_station_sid(gs.name) for gs in ground_stations], dtype=np.int64),
        sat_pos_km=pos, sat_lat_deg=lat, grid4=pairs,
        isl_a=isl_a, isl_b=isl_b, isl_kind=isl_kind, isl_up=isl_up, isl_dist_km=isl_dist,
        gsl_gs=gsl_gs, gsl_sat=gsl_sat, gsl_visible=gsl_visible, gsl_up=gsl_up,
        gsl_dist_km=gsl_dist, gsl_elev_deg=gsl_elev, graph=graph,
        grid_params=grid_params, gsl_params=gsl_params, excluded=excluded)


__all__ = [
    "KIND_INTRA", "KIND_CROSS", "KIND_GSL", "KIND_NAMES", "CsrGraph", "csr_from_edges",
    "TimeVaryingGraph", "Scenario", "build_scenario",
]

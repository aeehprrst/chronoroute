"""
topology.py
-----------
The truth topology of a run, every step (default 100 ms), STREAMED in
chunks so that a 600 s run of the real 463 km shell fits in a small, fixed
amount of memory.

It reuses the topology owner's code for every physical decision, so a run
sees exactly the links a bundle (`cr export bundle`) would contain:

    planes / slots       orbit.planes.build_fleet_geometry at the run start
    Grid-4 pairs         topo.isl_grid4.grid4_pairs at the run start
    ISL up / length      topo.isl_grid4.isl_state, step by step
    ground links         topo.gsl.elevation_deg + topo.gsl.select_links
    light time           topo.geometry.propagation_ns (integer ns)
    planning graph       topo.graph.csr_from_edges + route.dijkstra/scheduler

Why two passes:

  * The ground-link policy (sticky_top_k) is causal and keeps state from one
    step to the next, so pass 1 runs it once over the WHOLE window. It keeps
    only the satellites a station can see (elevation >= mask) at some step,
    about a hundred per station instead of ~3,000, and hands that compact
    elevation table to topo.gsl.select_links. That is the same result as the
    full table: invisible satellites are never selected and the tie-break
    uses the node ids passed in. Only (station, satellite) pairs that are
    ever SELECTED become ground-link rows here: a pair that is never up
    cannot carry a packet. (A bundle also lists visible-but-never-selected
    pairs, always down; tests check the two agree on every up link.)
  * Pass 2 propagates one chunk of steps at a time when the engine needs it
    and keeps at most a few chunks: positions (for the geographic fallback),
    ISL up flags and lengths, and ground-link lengths.

SGP4 is therefore run twice per step (once per pass). That costs CPU time
but keeps memory flat: the 600 s real-shell run never holds more than three
chunks of positions.

The state of step k holds for [k*step, (k+1)*step) (docs/bundle-format.md
1.3); after the last step the last step's state holds. Delays are HELD for
the whole step (what the ns-3 course milestone does), not interpolated.

Node numbering is the bundle's: satellites of the shell's planes sorted by
NORAD id (0 .. S-1), then the ground stations in the order given.
"""

import time
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from ..orbit import planes as planes_mod
from ..orbit.propagate import SatelliteArray
from ..topo import geometry, graph as graph_mod, gsl as gsl_mod, isl_grid4

KIND_INTRA = isl_grid4.INTRA
KIND_CROSS = isl_grid4.CROSS
KIND_GSL = graph_mod.KIND_GSL


@dataclass
class Chunk:
    """Steps k0 .. k0+n-1 of the truth geometry."""
    k0: int
    n: int
    up: np.ndarray          # (L, n) bool, geometric up flag (faults are applied by the engine)
    prop: np.ndarray        # (L, n) int64 light time, ns
    pos: np.ndarray         # (S, n, 3) satellite ECEF km


class _Times:
    """times_ns[step] for the scheduler (UTC ns of a step), without storing every step."""

    def __init__(self, t0_ns, step_ns, n_steps):
        self.t0_ns, self.step_ns, self.n = t0_ns, step_ns, n_steps

    def __getitem__(self, k):
        return self.t0_ns + int(k) * self.step_ns

    def __len__(self):
        return self.n


class Topology:
    """Streaming truth topology of one shell plus ground stations (see the module docstring).

    fleet          data.snapshot.Fleet (REAL snapshot or synthetic preset)
    shell_id       shell to use (orbit.shells id)
    stations       topo.gsl.GroundStation sequence (node ids S + index)
    t0_ns          run start, UTC ns (planes, slots and Grid-4 pairs chosen here)
    n_steps        number of steps (step k at t0 + k * step_ns)
    registry       route.sids.SidRegistry (missing satellites appended in memory only)
    """

    def __init__(self, fleet, shell_id, stations, t0_ns, n_steps, step_ns, *, registry,
                 grid_params=None, gsl_params=None, chunk_steps=200, planner_processing_ns=None,
                 keep_chunks=3):
        self.grid_params = grid_params or isl_grid4.Grid4Params()
        self.gsl_params = gsl_params or gsl_mod.GslParams()
        self.t0_ns = int(t0_ns)
        self.step_ns = int(step_ns)
        self.n_steps = int(n_steps)
        self.chunk_steps = int(chunk_steps)
        self.keep_chunks = max(2, int(keep_chunks))
        self.planner_processing_ns = (geometry.PROCESSING_NS if planner_processing_ns is None
                                      else int(planner_processing_ns))
        if self.n_steps < 1:
            raise ValueError("a topology needs at least one step")

        # ---- satellites, planes, slots (exactly as topo.graph.build_scenario)
        geo = planes_mod.build_fleet_geometry(fleet.records, self.t0_ns, satrecs=fleet.satrecs)
        if shell_id is None:
            # a synthetic preset has exactly one shell; take it
            if len(geo.shells) != 1:
                raise ValueError(f"shell_id needed: the fleet has {len(geo.shells)} shells")
            shell_id = geo.shells[0].shell_id
        shell = geo.shell(shell_id)
        self.shell = shell
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
        names = [gs.name for gs in stations]
        if len(set(names)) != len(names):
            raise ValueError("ground stations must be distinct")
        for gs in stations:
            if registry.ground_station_number(gs.name) != gs.g:
                raise ValueError(f"ground station {gs.name}: g={gs.g} disagrees with the SID registry")
        self.fleet = fleet
        self.sat_norad = sat_norad
        self.sat_name = tuple(by_norad[int(n)].name for n in sat_norad)
        self.sat_plane = np.array([plane_of[int(n)] for n in sat_norad], dtype=np.int64)
        self.sat_slot = np.array([slot_of[int(n)] for n in sat_norad], dtype=np.int64)
        self.sat_sid = np.array([registry.satellite_sid(int(n)) for n in sat_norad], dtype=np.int64)
        self.stations = tuple(stations)
        self.gs_sid = np.array([registry.ground_station_sid(gs.name) for gs in stations], dtype=np.int64)
        self.gs_ecef = np.array([np.asarray(gs.ecef_km, dtype=float) for gs in stations]).reshape(-1, 3)
        self.excluded_off_grid = int(sum(len(f.norads) for f in shell.fragments))
        S, G = len(sat_norad), len(stations)
        self.n_sats, self.n_gs, self.n_nodes = S, G, S + G

        self.grid4 = isl_grid4.grid4_pairs(shell, self.t0_ns, self.grid_params)
        self.isl_a = np.array([node_of[int(n)] for n in self.grid4.a], dtype=np.int64)
        self.isl_b = np.array([node_of[int(n)] for n in self.grid4.b], dtype=np.int64)
        self.isl_kind = self.grid4.kind.copy()
        self._sats = SatelliteArray(records, satrecs=fleet.satrecs)

        # ---- pass 1: ground-link selection over the whole window
        t_start = time.perf_counter()
        self._gsl_pass()
        self.pass1_seconds = time.perf_counter() - t_start
        self.chunk_seconds = 0.0

        # ---- the link table: ISL rows, then ground-link rows (ever up)
        Li = len(self.isl_a)
        self.n_isl = Li
        self.link_a = np.concatenate([self.isl_a, self.gsl_sat]).astype(np.int64)
        self.link_b = np.concatenate([self.isl_b, S + self.gsl_gs]).astype(np.int64)
        self.link_kind = np.concatenate([self.isl_kind.astype(np.uint8),
                                         np.full(len(self.gsl_gs), KIND_GSL, dtype=np.uint8)])
        self.n_links = len(self.link_a)
        transit = np.ones(self.n_nodes, dtype=bool)
        transit[S:] = False
        self.transit = transit

        # ---- per-node views used by forwarding (Python lists: fast scalar access)
        self.sid_of = self.sat_sid.tolist() + self.gs_sid.tolist()
        self.sid_to_node = {sid: i for i, sid in enumerate(self.sid_of)}
        if len(self.sid_to_node) != self.n_nodes:
            raise ValueError("two nodes share a SID")
        self.neighbours = [[] for _ in range(self.n_nodes)]      # (neighbour, link index)
        self.fib = [dict() for _ in range(self.n_nodes)]         # SID -> (neighbour, link index)
        for li, (a, b) in enumerate(zip(self.link_a.tolist(), self.link_b.tolist())):
            self.neighbours[a].append((b, li))
            self.neighbours[b].append((a, li))
            self.fib[a][self.sid_of[b]] = (b, li)
            self.fib[b][self.sid_of[a]] = (a, li)
        for lst in self.neighbours:
            lst.sort()
        self.link_index = {}
        for li, (a, b) in enumerate(zip(self.link_a.tolist(), self.link_b.tolist())):
            self.link_index[(a, b)] = li
            self.link_index[(b, a)] = li

        self._chunks = {}
        self.chunks_built = 0
        # what the route scheduler expects of a "scenario" (route/scheduler.plan_path)
        self.graph = SimpleNamespace(times_ns=_Times(self.t0_ns, self.step_ns, self.n_steps),
                                     processing_ns=self.planner_processing_ns)

    # ------------------------------------------------------------------ pass 1
    def _times(self, k0, k1):
        return [self.t0_ns + k * self.step_ns for k in range(k0, k1)]

    def _gsl_pass(self):
        S, T = self.n_sats, self.n_steps
        mask = self.gsl_params.min_elevation_deg
        kept = [dict() for _ in self.stations]          # sat -> {chunk k0: elevation row}
        for k0 in range(0, T, self.chunk_steps):
            k1 = min(T, k0 + self.chunk_steps)
            state = self._sats.propagate(self._times(k0, k1), geodetic=False)
            for g, gs in enumerate(self.stations):
                elev = gsl_mod.elevation_deg(gs, state.r_ecef)            # (S, n)
                with np.errstate(invalid="ignore"):
                    rows = np.flatnonzero((elev >= mask).any(axis=1))
                for s in rows.tolist():
                    kept[g].setdefault(s, {})[k0] = elev[s].copy()
        gsl_gs, gsl_sat, gsl_up = [], [], []
        for g in range(len(self.stations)):
            ever = np.array(sorted(kept[g]), dtype=np.int64)
            if ever.size == 0:
                continue
            table = np.full((ever.size, T), np.nan)
            for r, s in enumerate(ever.tolist()):
                for k0, row in kept[g][s].items():
                    table[r, k0:k0 + row.size] = row
            _visible, selected = gsl_mod.select_links(table, ever, self.gsl_params)
            used = np.flatnonzero(selected.any(axis=1))
            gsl_gs.append(np.full(used.size, g, dtype=np.int64))
            gsl_sat.append(ever[used])
            gsl_up.append(selected[used])
        if gsl_gs:
            self.gsl_gs = np.concatenate(gsl_gs)
            self.gsl_sat = np.concatenate(gsl_sat)
            self.gsl_up = np.concatenate(gsl_up)
        else:
            self.gsl_gs = np.zeros(0, dtype=np.int64)
            self.gsl_sat = np.zeros(0, dtype=np.int64)
            self.gsl_up = np.zeros((0, T), dtype=bool)

    # ------------------------------------------------------------------ pass 2
    def _build_chunk(self, c):
        t_start = time.perf_counter()
        k0 = c * self.chunk_steps
        k1 = min(self.n_steps, k0 + self.chunk_steps)
        state = self._sats.propagate(self._times(k0, k1))
        pos, lat = state.r_ecef, state.lat
        isl_up, isl_dist = isl_grid4.isl_state(self.isl_a, self.isl_b, self.isl_kind, pos, lat,
                                               self.grid_params)
        gs_pos = self.gs_ecef[self.gsl_gs][:, None, :]                       # (Lg, 1, 3)
        gsl_dist = np.linalg.norm(pos[self.gsl_sat] - gs_pos, axis=-1)       # (Lg, n)
        up = np.concatenate([isl_up, self.gsl_up[:, k0:k1]])
        prop = np.concatenate([geometry.propagation_ns(isl_dist), geometry.propagation_ns(gsl_dist)])
        self.chunks_built += 1
        self.chunk_seconds += time.perf_counter() - t_start
        return Chunk(k0=k0, n=k1 - k0, up=up, prop=prop, pos=pos)

    def chunk_of_step(self, k):
        """The chunk holding step k (built on first use; old chunks are dropped)."""
        k = min(max(int(k), 0), self.n_steps - 1)
        c = k // self.chunk_steps
        ch = self._chunks.get(c)
        if ch is None:
            ch = self._build_chunk(c)
            self._chunks[c] = ch
            while len(self._chunks) > self.keep_chunks:
                del self._chunks[min(self._chunks)]
        return ch

    def step_of(self, t_ns):
        """Step index whose state holds at run time t_ns (ns after t0), clamped to the last step."""
        k = t_ns // self.step_ns
        if k < 0:
            return 0
        return k if k < self.n_steps else self.n_steps - 1

    def up_range(self, k0, k1):
        """(L, k1-k0+1) geometric up flags of steps k0..k1 (inclusive), across chunks."""
        cols = []
        k = k0
        while k <= k1:
            ch = self.chunk_of_step(k)
            hi = min(k1, ch.k0 + ch.n - 1)
            cols.append(ch.up[:, k - ch.k0:hi - ch.k0 + 1])
            k = hi + 1
        return np.concatenate(cols, axis=1)

    def link_state(self, li, k):
        """(up, light time ns) of link li at step k (geometry only, no faults)."""
        ch = self.chunk_of_step(k)
        return bool(ch.up[li, k - ch.k0]), int(ch.prop[li, k - ch.k0])

    def node_ecef_km(self, node, k):
        if node >= self.n_sats:
            return self.gs_ecef[node - self.n_sats]
        ch = self.chunk_of_step(k)
        return ch.pos[node, k - ch.k0]

    # ------------------------------------------------------------------ planning graphs
    def csr_stable(self, k0, k1):
        """Graph of links up at EVERY step k0..k1, weighted at k0 (topo.graph.TimeVaryingGraph.csr_stable)."""
        if not 0 <= k0 <= k1 < self.n_steps:
            raise IndexError(f"steps {k0}..{k1} outside 0..{self.n_steps - 1}")
        mask = self.up_range(k0, k1).all(axis=1)
        ch = self.chunk_of_step(k0)
        w = ch.prop[:, k0 - ch.k0] + self.planner_processing_ns
        return graph_mod.csr_from_edges(self.n_nodes, self.link_a[mask], self.link_b[mask], w[mask],
                                        self.transit)

    # ------------------------------------------------------------------ naming
    def node_sid(self, node):
        """SID of a node (the method route/scheduler.plan_path calls)."""
        return self.sid_of[node]

    def node_name(self, node):
        if node < self.n_sats:
            return self.sat_name[node]
        return self.stations[node - self.n_sats].name

    def gs_node(self, index):
        return self.n_sats + index

    def gs_index(self, name):
        for i, gs in enumerate(self.stations):
            if gs.name == name:
                return i
        raise KeyError(name)

    def node_by_name(self, name):
        for i, n in enumerate(self.sat_name):
            if n == name:
                return i
        return self.gs_node(self.gs_index(name))


__all__ = ["Chunk", "Topology", "KIND_INTRA", "KIND_CROSS", "KIND_GSL"]

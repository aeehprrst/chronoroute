"""
scale.py
--------
Scales the Tier 1 simulator up to real published constellation designs, and
makes it fast enough that scaling up is actually practical.

You do NOT need to edit any Tier 1 file. Import this, call use_preset(), and
the whole simulator is reconfigured.

    import scale
    scale.use_preset('starlink')      # 1584 sats, 72 planes x 22
    scale.install_fast_topology()     # numpy-accelerated graph building

Three things happen here:

  1. PRESETS -- real constellation designs from the literature, so your
     results are about a system someone is actually building rather than a
     number you picked.

  2. RUNTIME RECONFIGURATION -- the constellation shape lives in ONE place,
     constellation.config(), and constellation.py / topology.py read it at
     call time (num_sats(), isl_pairs(), ...). apply_config() swaps it.
     Older modules that did `from constellation import NUM_SATS` or
     `from topology import ISL_PAIRS` hold a copy taken at import time;
     apply_config() also refreshes those copies in every loaded legacy
     module, but the safe fix is for them to call the accessors instead.
     (v0 refreshed only some names, so exp4's ISL_PAIRS stayed at the old
     constellation and results depended on the order presets were run.)

  3. SPEED -- at 1584 satellites the ground-station visibility scan does
     1584 x 6 = 9504 elevation calculations per timestep, in pure Python.
     Profiling showed that is 45% of graph-build time. install_fast_topology()
     replaces it with one vectorised numpy operation.
"""

import os
import sys
import numpy as np
import networkx as nx


# ---------------------------------------------------------------- presets

PRESETS = {
    # Our Tier 1 development constellation: small enough to iterate quickly.
    'dev': {
        'name': 'Development shell',
        'planes': 24, 'sats_per_plane': 20,
        'altitude_km': 550.0, 'inclination_deg': 53.0,
        'source': 'scaled-down for fast iteration',
    },

    # Starlink Shell 1, as modelled in the Hypatia paper (IMC 2020).
    'starlink': {
        'name': 'Starlink Shell 1',
        'planes': 72, 'sats_per_plane': 22,
        'altitude_km': 550.0, 'inclination_deg': 53.0,
        'source': 'FCC filing / Hypatia IMC 2020',
    },

    # Amazon Kuiper Shell 1.
    'kuiper': {
        'name': 'Kuiper Shell 1',
        'planes': 34, 'sats_per_plane': 34,
        'altitude_km': 630.0, 'inclination_deg': 51.9,
        'source': 'FCC filing / Hypatia IMC 2020',
    },

    # Telesat Lightspeed polar shell -- deliberately different: far fewer
    # satellites, much higher, near-polar. A good contrast case.
    'telesat': {
        'name': 'Telesat Lightspeed polar',
        'planes': 27, 'sats_per_plane': 13,
        'altitude_km': 1015.0, 'inclination_deg': 98.98,
        'source': 'FCC filing / Hypatia IMC 2020',
    },
}


def describe(preset_key):
    p = PRESETS[preset_key]
    n = p['planes'] * p['sats_per_plane']
    return (f"{p['name']}: {n} satellites "
            f"({p['planes']} planes x {p['sats_per_plane']}), "
            f"{p['altitude_km']:.0f} km, {p['inclination_deg']:.2f} deg "
            f"[{p['source']}]")


# ------------------------------------------------- runtime reconfiguration

# Only modules that live next to this file (sim/legacy/) are ever touched.
# v0 patched any module whose path contained 'chronoroute' -- which is every
# installed package in ~/chronoroute/venv as well.
_LEGACY_DIR = os.path.dirname(os.path.realpath(__file__))


def _legacy_modules(exclude=()):
    """Loaded modules whose source file is in sim/legacy/."""
    for mod in list(sys.modules.values()):
        if mod is None or mod in exclude:
            continue
        path = getattr(mod, '__file__', None)
        if not path:
            continue
        if os.path.dirname(os.path.realpath(path)) == _LEGACY_DIR:
            yield mod


def apply_config(planes, sats_per_plane, altitude_km, inclination_deg,
                 verbose=True, phasing_f=None):
    """
    Reconfigure the whole simulator.

    1. swap the single source of truth, constellation.config()
    2. refresh the old copied names (NUM_SATS, ISL_PAIRS, ...) in every
       loaded legacy module, for scripts that still import them by value
    3. clear common.py's cached scenario, or you get the old graphs
    """
    import constellation as C
    import topology as T

    if phasing_f is None:
        phasing_f = C.DEFAULT_CONFIG.phasing_f
    cfg = C.set_config(C.ConstellationConfig(
        planes=int(planes),
        sats_per_plane=int(sats_per_plane),
        altitude_km=float(altitude_km),
        inclination_deg=float(inclination_deg),
        phasing_f=int(phasing_f),
    ))

    new_values = {
        'NUM_PLANES': cfg.planes,
        'SATS_PER_PLANE': cfg.sats_per_plane,
        'NUM_SATS': cfg.num_sats,
        'ALTITUDE_KM': cfg.altitude_km,
        'INCLINATION_DEG': cfg.inclination_deg,
        'PHASING_F': cfg.phasing_f,
        'ISL_PAIRS': list(T.isl_pairs()),
    }

    patched = []
    for mod in _legacy_modules(exclude=(C,)):
        for name, value in new_values.items():
            if hasattr(mod, name):
                # each module gets its own list, so editing one cannot
                # change another
                setattr(mod, name, list(value) if isinstance(value, list)
                        else value)
                patched.append(f"{mod.__name__}.{name}")

    common = sys.modules.get('common')
    if common is not None and hasattr(common, '_cache'):
        common._cache.clear()

    if verbose:
        print(f"  reconfigured: {cfg.num_sats} satellites, "
              f"{len(T.isl_pairs())} candidate ISLs")
        if patched:
            print(f"  rebound {len(patched)} names across loaded modules")

    return cfg.num_sats


def use_preset(key, verbose=True):
    """Reconfigure to one of the published constellation designs."""
    if key not in PRESETS:
        raise KeyError(f"unknown preset {key!r}. options: {list(PRESETS)}")
    p = PRESETS[key]
    if verbose:
        print(f"  -> {describe(key)}")
    return apply_config(p['planes'], p['sats_per_plane'],
                        p['altitude_km'], p['inclination_deg'],
                        verbose=verbose, phasing_f=p.get('phasing_f'))


apply_preset = use_preset


# --------------------------------------------------- numpy fast topology

# Pairs whose closest approach to the Earth's centre is this close to one of
# the "certainly fine / certainly blocked" thresholds are handed to the exact
# scalar check, so the numpy path makes exactly the same decision as
# topology.build_graph even where float rounding differs in the last digit.
_THRESHOLD_GUARD_KM = 1e-6


def _pair_arrays(pairs):
    a = np.fromiter((p[0] for p in pairs), dtype=np.int64, count=len(pairs))
    b = np.fromiter((p[1] for p in pairs), dtype=np.int64, count=len(pairs))
    is_cross = np.fromiter((p[2] == 'cross' for p in pairs),
                           dtype=bool, count=len(pairs))
    return a, b, is_cross


def _fast_build_graph(sat_positions, gs_positions, failed_links=None):
    """
    A drop-in replacement for topology.build_graph, same signature and same
    output, but the ISL checks and the ground-station visibility scan are
    vectorised.

    The maths is identical to topology.py; we just do all satellites at once
    instead of looping.
    """
    import constellation as C
    import topology as T

    if failed_links is None:
        failed_links = set()

    n = C.num_sats()
    nan3 = (np.nan, np.nan, np.nan)
    P = np.array([p if p is not None else nan3 for p in sat_positions[:n]],
                 dtype=np.float64).reshape(n, 3)                   # (n, 3)
    valid = ~np.isnan(P).any(axis=1)        # False = SGP4 skipped it

    G = nx.Graph()
    for sid in range(n):
        G.add_node(sid, pos=sat_positions[sid], kind='sat')
    G.graph['skipped_sats'] = int(n - valid.sum())

    # ---- inter-satellite links (vectorised distance, latitude, grazing) ----
    pairs = T.isl_pairs()
    A, B, is_cross = _pair_arrays(pairs)
    ok = valid[A] & valid[B]

    Pv = np.where(valid[:, None], P, 1.0)    # placeholder so maths stays finite
    D = Pv[B] - Pv[A]
    d = np.linalg.norm(D, axis=1)                             # all lengths at once

    radius = np.linalg.norm(Pv, axis=1)
    lat = np.degrees(np.arcsin(np.clip(Pv[:, 2] / radius, -1.0, 1.0)))
    polar_block = is_cross & ((np.abs(lat[A]) > T.POLAR_CUTOFF_DEG)
                              | (np.abs(lat[B]) > T.POLAR_CUTOFF_DEG))
    ok &= ~polar_block

    # 80 km grazing rule: closest approach of each segment to the centre
    dd = np.einsum('ij,ij->i', D, D)
    t = -np.einsum('ij,ij->i', Pv[A], D) / np.where(dd > 0.0, dd, 1.0)
    t = np.clip(np.where(dd > 0.0, t, 0.0), 0.0, 1.0)
    r_min = np.linalg.norm(Pv[A] + t[:, None] * D, axis=1)
    alt = T.ISL_MIN_GRAZING_ALT_KM
    surely_clear = r_min - C.WGS84_A_KM >= alt + _THRESHOLD_GUARD_KM
    surely_blocked = r_min - C.WGS84_B_KM < alt - _THRESHOLD_GUARD_KM
    for idx in np.flatnonzero(ok & ~surely_clear & ~surely_blocked):
        surely_clear[idx] = T.isl_clears_earth(sat_positions[int(A[idx])],
                                               sat_positions[int(B[idx])])
    ok &= surely_clear

    weights = d / C.C_KM_PER_MS + T.PROCESSING_DELAY_MS

    for idx in np.flatnonzero(ok):
        a, b = int(A[idx]), int(B[idx])
        if frozenset({a, b}) in failed_links:
            continue
        G.add_edge(a, b, weight=float(weights[idx]),
                   dist_km=float(d[idx]),
                   kind='cross' if is_cross[idx] else 'intra')

    # ---- ground station links (vectorised elevation) ----
    for gi, (gname, _, _) in enumerate(C.GROUND_STATIONS):
        name = f"GS:{gname}"
        gpos = np.asarray(gs_positions[gi], dtype=np.float64)
        G.add_node(name, pos=gs_positions[gi], kind='gs')

        up = np.asarray(C.geodetic_up(gs_positions[gi]))  # ellipsoid normal
        vec = Pv - gpos                                  # (n, 3) GS -> satellite
        dist = np.linalg.norm(vec, axis=1)
        cos_zenith = np.clip((vec @ up) / np.where(dist > 0.0, dist, 1.0),
                             -1.0, 1.0)
        elevation = np.where(dist > 0.0, 90.0 - np.degrees(np.arccos(cos_zenith)),
                             90.0)

        visible = np.flatnonzero(valid & (elevation >= T.GSL_MIN_ELEVATION_DEG))
        if visible.size == 0:
            continue
        # keep the GSL_MAX_SATS closest visible satellites (stable sort, so a
        # tie goes to the lower id, exactly like the pure-Python sort)
        order = np.argsort(dist[visible], kind='stable')
        nearest = visible[order[:T.GSL_MAX_SATS]]

        for sid in nearest:
            sid = int(sid)
            G.add_edge(name, sid,
                       weight=float(dist[sid] / C.C_KM_PER_MS
                                    + T.PROCESSING_DELAY_MS),
                       dist_km=float(dist[sid]),
                       kind='gsl')

    return G


_original_build_graph = None


def install_fast_topology(verbose=True):
    """
    Swap topology.build_graph for the numpy version, everywhere it is used.
    Safe to call more than once.
    """
    global _original_build_graph
    import topology as T

    if _original_build_graph is None:
        _original_build_graph = T.build_graph

    T.build_graph = _fast_build_graph

    # modules that did `from topology import build_graph` hold their own copy
    for mod in _legacy_modules(exclude=(T, sys.modules[__name__])):
        if hasattr(mod, 'build_graph'):
            setattr(mod, 'build_graph', _fast_build_graph)

    if verbose:
        print("  numpy fast topology installed")


def restore_topology():
    """Put the original pure-Python build_graph back (useful for verification)."""
    import topology as T
    if _original_build_graph is not None:
        T.build_graph = _original_build_graph
        for mod in _legacy_modules(exclude=(T, sys.modules[__name__])):
            if hasattr(mod, 'build_graph'):
                setattr(mod, 'build_graph', _original_build_graph)


# ------------------------------------------- fast failure injection

def graphs_with_failures(graphs, failed_links):
    """
    Experiment 4 originally rebuilt every graph from scratch for every failure
    trial. At 1584 satellites that is 120 graphs x 5 trials x 7 rates = 4200
    rebuilds, which dominates the whole run.

    A broken link only ever REMOVES edges, so we can shallow-copy the healthy
    graph and delete them. Copying is far cheaper than recomputing 3168
    distances and 9504 elevations.
    """
    out = []
    for g in graphs:
        h = g.copy()
        for link in failed_links:
            a, b = tuple(link)
            if h.has_edge(a, b):
                h.remove_edge(a, b)
        out.append(h)
    return out


if __name__ == '__main__':
    import time
    import constellation as C
    import topology as T

    print("=== Available presets ===")
    for k in PRESETS:
        print(f"  {k:10s} {describe(k)}")

    print("\n=== Scaling to Starlink Shell 1 ===")
    n = use_preset('starlink')

    sats = C.build_constellation()
    times, sp = C.propagate(sats, duration_s=5, step_s=1)
    gp = C.ground_station_positions(times)

    # --- correctness: the fast graph must match the original exactly ---
    print("\n=== Verifying numpy version against pure Python ===")
    slow = T.build_graph(sp[0], gp[0])
    install_fast_topology(verbose=False)
    fast = T.build_graph(sp[0], gp[0])

    same_nodes = set(slow.nodes()) == set(fast.nodes())
    same_edges = set(map(frozenset, slow.edges())) == set(map(frozenset, fast.edges()))
    max_w_diff = max(
        abs(slow[a][b]['weight'] - fast[a][b]['weight'])
        for a, b in slow.edges()
    )
    print(f"  nodes identical : {same_nodes}")
    print(f"  edges identical : {same_edges}")
    print(f"  max weight diff : {max_w_diff:.2e} ms")
    assert same_nodes and same_edges and max_w_diff < 1e-9, "fast path diverged!"
    print("  VERIFIED -- numpy version is exact")

    # --- speed ---
    print("\n=== Speed comparison (10 graph builds) ===")
    restore_topology()
    t0 = time.time()
    for _ in range(10):
        T.build_graph(sp[0], gp[0])
    slow_t = time.time() - t0

    install_fast_topology(verbose=False)
    t0 = time.time()
    for _ in range(10):
        T.build_graph(sp[0], gp[0])
    fast_t = time.time() - t0

    print(f"  pure Python : {slow_t / 10 * 1000:6.1f} ms per graph")
    print(f"  numpy       : {fast_t / 10 * 1000:6.1f} ms per graph")
    print(f"  speedup     : {slow_t / fast_t:6.1f}x")
    print(f"  120 graphs  : {slow_t * 12:.1f}s -> {fast_t * 12:.1f}s")

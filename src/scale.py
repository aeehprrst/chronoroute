"""
scale.py
--------
Scales the Tier 1 simulator up to real published constellation designs, and
makes it fast enough that scaling up is actually practical.

You do NOT need to edit any Tier 1 file. Import this, call use_preset(), and
every module already loaded is reconfigured in place.

    import scale
    scale.use_preset('starlink')      # 1584 sats, 72 planes x 22
    scale.install_fast_topology()     # numpy-accelerated graph building

Three things happen here:

  1. PRESETS -- real constellation designs from the literature, so your
     results are about a system someone is actually building rather than a
     number you picked.

  2. RUNTIME RECONFIGURATION -- the Tier 1 modules do
     `from constellation import NUM_SATS`, which binds the value at import
     time. Changing constellation.NUM_SATS afterwards would not reach them.
     apply_config() walks every loaded module and rebinds the names, then
     rebuilds the derived ISL pair list.

  3. SPEED -- at 1584 satellites the ground-station visibility scan does
     1584 x 6 = 9504 elevation calculations per timestep, in pure Python.
     Profiling showed that is 45% of graph-build time. install_fast_topology()
     replaces it with one vectorised numpy operation.
"""

import sys
import math
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

_PATCHED_NAMES = ('NUM_PLANES', 'SATS_PER_PLANE', 'NUM_SATS',
                  'ALTITUDE_KM', 'INCLINATION_DEG')


def apply_config(planes, sats_per_plane, altitude_km, inclination_deg,
                 verbose=True):
    """
    Reconfigure the whole simulator in place.

    Because Tier 1 modules use `from constellation import NUM_SATS`, each one
    holds its own copy of the value. We rebind the name in every module that
    has it, then rebuild anything derived from it.
    """
    import constellation as C
    import topology as T

    num_sats = planes * sats_per_plane

    # 1. update the source of truth
    C.NUM_PLANES = planes
    C.SATS_PER_PLANE = sats_per_plane
    C.NUM_SATS = num_sats
    C.ALTITUDE_KM = float(altitude_km)
    C.INCLINATION_DEG = float(inclination_deg)

    new_values = {
        'NUM_PLANES': planes,
        'SATS_PER_PLANE': sats_per_plane,
        'NUM_SATS': num_sats,
        'ALTITUDE_KM': float(altitude_km),
        'INCLINATION_DEG': float(inclination_deg),
    }

    # 2. rebind the copies held by every already-imported module
    patched = []
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or mod is C:
            continue
        if not getattr(mod, '__file__', None):
            continue
        if 'chronoroute' not in str(mod.__file__):
            continue
        for name, value in new_values.items():
            if hasattr(mod, name):
                setattr(mod, name, value)
                patched.append(f"{mod_name}.{name}")

    # 3. rebuild derived state: the ISL pair list depends on the geometry
    T.ISL_PAIRS = T.isl_neighbour_pairs()

    # 4. clear the cached scenario in common.py, or you get the old graphs
    try:
        import common
        common._cache.clear()
    except Exception:
        pass

    if verbose:
        print(f"  reconfigured: {num_sats} satellites, "
              f"{len(T.ISL_PAIRS)} candidate ISLs")
        if patched:
            print(f"  rebound {len(patched)} names across loaded modules")

    return num_sats


def use_preset(key, verbose=True):
    """Reconfigure to one of the published constellation designs."""
    if key not in PRESETS:
        raise KeyError(f"unknown preset {key!r}. options: {list(PRESETS)}")
    p = PRESETS[key]
    if verbose:
        print(f"  -> {describe(key)}")
    return apply_config(p['planes'], p['sats_per_plane'],
                        p['altitude_km'], p['inclination_deg'],
                        verbose=verbose)


# --------------------------------------------------- numpy fast topology

def _fast_build_graph(sat_positions, gs_positions, failed_links=None):
    """
    A drop-in replacement for topology.build_graph, same signature and same
    output, but the ground-station visibility scan is vectorised.

    The maths is identical to elevation_angle_deg(); we just do all 1584
    satellites at once instead of looping.
    """
    import topology as T
    from constellation import (EARTH_RADIUS_KM, C_KM_PER_MS, GROUND_STATIONS)

    if failed_links is None:
        failed_links = set()

    n = T.NUM_SATS
    P = np.asarray(sat_positions[:n], dtype=np.float64)      # (n, 3)

    G = nx.Graph()
    for sid in range(n):
        G.add_node(sid, pos=sat_positions[sid], kind='sat')

    # ---- inter-satellite links (vectorised distance + latitude) ----
    pairs = T.ISL_PAIRS
    A = np.fromiter((p[0] for p in pairs), dtype=np.int32, count=len(pairs))
    B = np.fromiter((p[1] for p in pairs), dtype=np.int32, count=len(pairs))
    is_cross = np.fromiter((p[2] == 'cross' for p in pairs),
                           dtype=bool, count=len(pairs))

    d = np.linalg.norm(P[A] - P[B], axis=1)                  # all lengths at once

    radius = np.linalg.norm(P, axis=1)
    lat = np.degrees(np.arcsin(np.clip(P[:, 2] / radius, -1.0, 1.0)))

    ok = d <= T.ISL_MAX_RANGE_KM
    polar_block = is_cross & ((np.abs(lat[A]) > T.POLAR_CUTOFF_DEG)
                              | (np.abs(lat[B]) > T.POLAR_CUTOFF_DEG))
    ok &= ~polar_block

    weights = d / C_KM_PER_MS + T.PROCESSING_DELAY_MS

    for idx in np.flatnonzero(ok):
        a, b = int(A[idx]), int(B[idx])
        if frozenset({a, b}) in failed_links:
            continue
        G.add_edge(a, b, weight=float(weights[idx]),
                   dist_km=float(d[idx]),
                   kind='cross' if is_cross[idx] else 'intra')

    # ---- ground station links (vectorised elevation) ----
    for gi, (gname, _, _) in enumerate(GROUND_STATIONS):
        name = f"GS:{gname}"
        gpos = np.asarray(gs_positions[gi], dtype=np.float64)
        G.add_node(name, pos=gs_positions[gi], kind='gs')

        vec = P - gpos                                   # (n, 3) GS -> satellite
        dist = np.linalg.norm(vec, axis=1)
        up = gpos / np.linalg.norm(gpos)                 # local vertical
        cos_zenith = np.clip((vec @ up) / dist, -1.0, 1.0)
        elevation = 90.0 - np.degrees(np.arccos(cos_zenith))

        visible = np.flatnonzero(elevation >= T.GSL_MIN_ELEVATION_DEG)
        if visible.size == 0:
            continue
        # keep the GSL_MAX_SATS closest visible satellites
        nearest = visible[np.argsort(dist[visible])[:T.GSL_MAX_SATS]]

        for sid in nearest:
            sid = int(sid)
            G.add_edge(name, sid,
                       weight=float(dist[sid] / C_KM_PER_MS
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
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or mod is T:
            continue
        if not getattr(mod, '__file__', None):
            continue
        if 'chronoroute' not in str(mod.__file__):
            continue
        if hasattr(mod, 'build_graph'):
            setattr(mod, 'build_graph', _fast_build_graph)

    if verbose:
        print("  numpy fast topology installed")


def restore_topology():
    """Put the original pure-Python build_graph back (useful for verification)."""
    import topology as T
    if _original_build_graph is not None:
        T.build_graph = _original_build_graph
        for mod_name, mod in list(sys.modules.items()):
            if mod is None or not getattr(mod, '__file__', None):
                continue
            if 'chronoroute' in str(mod.__file__) and hasattr(mod, 'build_graph'):
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
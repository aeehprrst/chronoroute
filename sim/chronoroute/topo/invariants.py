"""
invariants.py
-------------
Physical sanity checks that every scenario must pass. They are run by the
tests (one full orbit of the 53 deg / 463 km shell) and by `cr export bundle`
(results go into scenario.json), so a bundle cannot silently contain a link
through the Earth or a path faster than light.

Each check returns a plain dict: {"ok": bool, "checked": n, "violations": n,
... a few numbers that show the margin}. They deliberately use a DIFFERENT
method from the code that built the links where they can:

  isl_clearance       every UP laser link at every step stays >= 80 km above
                      WGS84. Certified with the bound r_min - a (no search),
                      falling back to the exact golden-section height only
                      when the bound is not enough. In addition, a dense
                      sampling check (65 points + the closest-approach point,
                      plain ecef_to_geodetic) runs on a subset of steps.
                      It also reports the longest up laser link and, when the
                      model has a laser range limit (max_range_km), counts
                      every up link longer than it as a violation.
  gsl_geometry      every UP ground link: elevation >= mask, recomputed in
                      the local east-north-up frame (not the arcsin formula
                      the selector used); the satellite end is >= 80 km above
                      WGS84; and the line of sight rises from the station
                      (never below the station's own height).
  hop_delay           every UP edge: weight = prop + processing, prop is the
                      rounded light time (|prop - d/c| <= 0.5 ns) and the
                      weight is >= d/c.
  isl_degree          at most 4 Grid-4 links per satellite (candidate pairs,
                      hence also at every step).
  path_latency        every planned path: per hop, predicted delay >= d/c of
                      that hop at that step; end to end, light time >=
                      great-circle distance / c (cities on a sphere of the
                      mean Earth radius, a 0.5% approximation, far inside the
                      >= 7% margin a 463 km detour gives).
  schedule_stability  every schedule row [valid_from, valid_to): every link of
                      its path is up at every 100 ms step from valid_from
                      until valid_to + the path's final budget B_h (the last
                      packet of the interval is then still on time). Required
                      when the bundle planned with plan_links = "stable";
                      otherwise only counted (the "instant" variant breaks it
                      on purpose, at ground-link handovers).
"""

import numpy as np

from ..data import cities as cities_mod
from ..orbit import frames
from . import geometry, isl_grid4

DENSE_SAMPLES = 65
DENSE_CHUNK = 20_000          # segments per batch of the dense check (~250 MB peak)
NS_PER_MS = 1_000_000


def _result(checked, violations, **extra):
    return {"ok": int(violations) == 0, "checked": int(checked), "violations": int(violations), **extra}


def isl_clearance(scenario, dense_every=10):
    """Every up ISL at every step clears min_grazing_alt_km (see module docstring)."""
    min_alt = scenario.grid_params.min_grazing_alt_km
    up = scenario.isl_up
    li, ti = np.nonzero(up)
    pa = scenario.sat_pos_km[scenario.isl_a[li], ti]
    pb = scenario.sat_pos_km[scenario.isl_b[li], ti]
    bound = geometry.height_lower_bound_km(pa, pb)
    lowest = bound.copy()
    unsure = bound < min_alt
    if np.any(unsure):
        lowest[unsure] = geometry.segment_min_height_km(pa[unsure], pb[unsure])
    violations = int(np.sum(lowest < min_alt))
    # Independent dense sampling on every dense_every-th step.
    steps = np.arange(0, scenario.times_ns.size, max(1, dense_every))
    sel = np.isin(ti, steps)
    dense_min = None
    dense_viol = 0
    if np.any(sel):
        a_all, b_all = pa[sel], pb[sel]
        mins = []
        for lo in range(0, len(a_all), DENSE_CHUNK):            # bounded memory
            a, b = a_all[lo:lo + DENSE_CHUNK], b_all[lo:lo + DENSE_CHUNK]
            _, t_star = geometry.closest_approach(a, b)
            ts = np.concatenate([np.linspace(0.0, 1.0, DENSE_SAMPLES)[None, :].repeat(len(a), 0),
                                 t_star[:, None]], axis=1)                  # (M, 66)
            pts = a[:, None, :] + ts[..., None] * (b - a)[:, None, :]
            _, _, h = frames.ecef_to_geodetic(pts)
            mins.append(h.min(axis=1))
        hmin = np.concatenate(mins)
        dense_min = float(hmin.min())
        dense_viol = int(np.sum(hmin < min_alt - 1e-6))
    # Length of every up link, from the positions (not the stored distances).
    length = np.linalg.norm(pb - pa, axis=-1)
    max_range = getattr(scenario.grid_params, "max_range_km", None)
    range_viol = int(np.sum(length > max_range)) if max_range is not None else 0
    return _result(li.size, violations + dense_viol + range_viol,
                   min_height_km=float(lowest.min()) if lowest.size else None,
                   dense_checked=int(np.sum(sel)), dense_min_height_km=dense_min,
                   min_alt_km=min_alt,
                   longest_up_isl_km=float(length.max()) if length.size else None,
                   max_range_km=max_range, range_violations=range_viol)


def _enu_elevation_deg(gs, r):
    """Elevation from the local east-north-up frame: atan2(up, horizontal)."""
    lat, lon = np.radians(gs.lat_deg), np.radians(gs.lon_deg)
    east = np.array([-np.sin(lon), np.cos(lon), 0.0])
    north = np.array([-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)])
    upv = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    d = r - np.asarray(gs.ecef_km)
    e, n, u = d @ east, d @ north, d @ upv
    return np.degrees(np.arctan2(u, np.hypot(e, n)))


def gsl_geometry(scenario):
    """Every up ground link: elevation >= mask, satellite >= 80 km, line of sight rises."""
    mask = scenario.gsl_params.min_elevation_deg
    li, ti = np.nonzero(scenario.gsl_up)
    viol = 0
    min_elev = None
    min_sat_h = None
    for g, gs in enumerate(scenario.ground_stations):
        sel = scenario.gsl_gs[li] == g
        if not np.any(sel):
            continue
        r = scenario.sat_pos_km[scenario.gsl_sat[li[sel]], ti[sel]]
        elev = _enu_elevation_deg(gs, r)
        _, _, h_sat = frames.ecef_to_geodetic(r)
        # line of sight: lowest height along the segment must be the station's own (0 km)
        gse = np.broadcast_to(np.asarray(gs.ecef_km), r.shape)
        ts = np.linspace(0.0, 1.0, 17)[1:]
        pts = gse[:, None, :] + ts[None, :, None] * (r - gse)[:, None, :]
        _, _, h_line = frames.ecef_to_geodetic(pts)
        viol += int(np.sum(elev < mask - 1e-9)) + int(np.sum(h_sat < geometry.MIN_GRAZING_ALT_KM)) \
            + int(np.sum(h_line.min(axis=1) < -1e-6))
        min_elev = float(elev.min()) if min_elev is None else min(min_elev, float(elev.min()))
        min_sat_h = float(h_sat.min()) if min_sat_h is None else min(min_sat_h, float(h_sat.min()))
    return _result(li.size, viol, min_elevation_deg=min_elev, mask_deg=mask,
                   min_satellite_height_km=min_sat_h)


def hop_delay(scenario):
    """Every up edge: prop is round(d/c), weight = prop + processing >= d/c."""
    g = scenario.graph
    dist = np.concatenate([scenario.isl_dist_km, scenario.gsl_dist_km])
    li, ti = np.nonzero(g.up)
    exact = geometry.light_time_ns_exact(dist[li, ti])
    prop = g.prop_ns[li, ti]
    weight = prop + g.processing_ns
    bad = (np.abs(prop - exact) > 0.5 + 1e-6) | (weight < exact) | (prop < 0)
    worst = float(np.max(np.abs(prop - exact))) if li.size else None
    return _result(li.size, int(np.sum(bad)), max_rounding_ns=worst,
                   processing_ns=g.processing_ns)


def isl_degree(scenario):
    """At most 4 Grid-4 links per satellite (and so at every step)."""
    deg = np.bincount(np.concatenate([scenario.isl_a, scenario.isl_b]), minlength=scenario.n_sats)
    up_deg = 0
    if scenario.isl_up.size:
        per_step = np.zeros((scenario.n_sats, scenario.times_ns.size), dtype=np.int64)
        np.add.at(per_step, scenario.isl_a, scenario.isl_up.astype(np.int64))
        np.add.at(per_step, scenario.isl_b, scenario.isl_up.astype(np.int64))
        up_deg = int(per_step.max())
    return _result(scenario.n_sats, int(np.sum(deg > isl_grid4.MAX_DEGREE)),
                   max_degree=int(deg.max()) if deg.size else 0, max_up_degree=up_deg,
                   degree_histogram={str(k): int(v) for k, v in enumerate(np.bincount(deg))})


def path_latency(scenario, entries):
    """Per hop: predicted delay >= d/c; end to end: light time >= great-circle / c."""
    viol = 0
    worst_ratio = None
    for e in entries:
        k = e.step
        for (u, v), d_ns in zip(zip(e.path[:-1], e.path[1:]), e.hop_delays_ns):
            dist = float(np.linalg.norm(scenario.node_ecef_km(v, k) - scenario.node_ecef_km(u, k)))
            if d_ns < geometry.light_time_ns_exact(dist):
                viol += 1
        a = scenario.ground_stations[e.src - scenario.n_sats]
        b = scenario.ground_stations[e.dst - scenario.n_sats]
        gc_ns = geometry.light_time_ns_exact(cities_mod.great_circle_km(a, b))
        ratio = e.prop_total_ns / gc_ns
        worst_ratio = ratio if worst_ratio is None else min(worst_ratio, ratio)
        if e.prop_total_ns < gc_ns:
            viol += 1
    return _result(len(entries), viol, min_light_time_over_great_circle=worst_ratio)


def last_step_needed(valid_to_ms, horizon_ns, step_ms, last_step):
    """Index of the last step a schedule row must find its links up in.

    Packets sent before valid_to may still be travelling until valid_to +
    horizon_ns. Step k holds for [k*step, (k+1)*step), so the last step that
    overlaps [valid_from, valid_to + horizon) is ceil((valid_to + horizon) /
    step) - 1, clamped to the bundle's last step (the state of the last step
    holds after the window). Integer arithmetic only.
    """
    step_ns = step_ms * NS_PER_MS
    end_ns = valid_to_ms * NS_PER_MS + int(horizon_ns)
    return min(int(last_step), -(-end_ns // step_ns) - 1)


def schedule_stability(scenario, rows, step_ms, required):
    """Every path link is up from valid_from until valid_to + final budget (see module docstring).

    rows: (flow_id, valid_from_ms, valid_to_ms, ScheduleEntry). required:
    whether a broken row is a violation (stable planning) or only counted.
    """
    g = scenario.graph
    index = {}
    for i, (a, b) in enumerate(zip(g.link_a.tolist(), g.link_b.tolist())):
        index[(a, b)] = index[(b, a)] = i
    last = g.n_steps - 1
    broken = 0
    examples = []
    for fid, start, end, e in rows:
        k0 = start // step_ms
        k1 = max(k0, last_step_needed(end, e.budgets_ceil_ns[-1], step_ms, last))
        links = [index[(u, v)] for u, v in zip(e.path[:-1], e.path[1:])]
        ok = bool(g.up[links, k0:k1 + 1].all())
        if not ok:
            broken += 1
            if len(examples) < 5:
                examples.append({"flow_id": int(fid), "valid_from_ms": int(start), "valid_to_ms": int(end)})
    return {"ok": broken == 0 or not required, "checked": len(rows),
            "violations": broken if required else 0, "rows_with_a_link_down_in_use": broken,
            "required": bool(required), "examples": examples}


def run_all(scenario, entries=(), dense_every=10, *, rows=None, step_ms=None, stable_required=False):
    """All checks. rows/step_ms (schedule rows with their intervals) enable schedule_stability."""
    out = {
        "isl_clearance": isl_clearance(scenario, dense_every=dense_every),
        "gsl_geometry": gsl_geometry(scenario),
        "hop_delay": hop_delay(scenario),
        "isl_degree": isl_degree(scenario),
        "path_latency": path_latency(scenario, list(entries)),
    }
    if rows is not None:
        out["schedule_stability"] = schedule_stability(scenario, list(rows), step_ms, stable_required)
    out["all_ok"] = all(v["ok"] for v in out.values())
    return out


__all__ = ["isl_clearance", "gsl_geometry", "hop_delay", "isl_degree", "path_latency",
           "last_step_needed", "schedule_stability", "run_all"]

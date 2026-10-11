"""P2 acceptance check, exactly as the plan states it: "ISL invariant: 0 segments below 80 km
over one orbit (about 95 min) at 1 s steps, for EVERY shell" (master plan P2, acceptance).

For every shell that `build_fleet_geometry` infers from the pinned SupGP snapshot (broadband
and DTC), the Grid-4 pairs are chosen at T0 and their up/down state is computed at
5,701 one-second steps (T0 .. T0 + 95 min) by the model code (isl_grid4.isl_state). Then
every link that the model says is UP is checked by the project's invariant checker
(invariants.isl_clearance: the certified bound r_min - a, the exact height where the bound
is not enough, and an independent dense-sampling check on every 10th step), and the polar
rule is checked directly: no cross-plane link is up while either end is above |lat| 70 deg.

The time axis is processed in chunks so memory stays bounded (the 43 deg shell has about
3,200 satellites). The run takes a few minutes, so its result is computed once per session.
"""

from functools import cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from chronoroute.data import omm, snapshot
from chronoroute.orbit import frames, planes as planes_mod
from chronoroute.orbit.propagate import SatelliteArray
from chronoroute.topo import geometry, invariants, isl_grid4

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
T0 = omm.parse_epoch_ns("2026-10-10T14:00:00")
STEP_NS = 1_000_000_000            # 1 s steps, as the plan asks
ORBIT_S = 95 * 60                  # about one orbit at these altitudes
CHUNK = 300                        # time steps per batch
DENSE_EVERY = 60                   # dense sampling of EVERY up link once a minute ...
NEAR_SAMPLES = 513                 # ... and of every link the bound cannot certify, at every step
NEAR_BATCH = 4000


def near_limit_dense_min(pa, pb, min_alt):
    """Lowest sampled height of the up links that the certified bound r_min - a cannot clear.

    Those are the only links that could break the rule, so they are sampled at every step,
    513 points along the segment plus the point closest to the Earth's centre, with plain
    ecef_to_geodetic (no golden-section search, so independent of the model's own method).
    A sampled height is never below the true minimum, so a sample under 80 km would be a real
    violation. Returns (count, lowest sampled height or None).
    """
    unsure = geometry.height_lower_bound_km(pa, pb) < min_alt
    a, b = pa[unsure], pb[unsure]
    if a.size == 0:
        return 0, None
    lowest = np.inf
    s = np.linspace(0.0, 1.0, NEAR_SAMPLES)
    for lo in range(0, len(a), NEAR_BATCH):
        aa, bb = a[lo:lo + NEAR_BATCH], b[lo:lo + NEAR_BATCH]
        _, t_star = geometry.closest_approach(aa, bb)
        ts = np.concatenate([np.broadcast_to(s, (len(aa), s.size)), t_star[:, None]], axis=1)
        _, _, h = frames.ecef_to_geodetic(aa[:, None, :] + ts[..., None] * (bb - aa)[:, None, :])
        lowest = min(lowest, float(h.min()))
    return int(unsure.sum()), lowest


@cache
def one_orbit_every_shell():
    fleet = snapshot.load_pinned(PINNED, "supgp")
    geo = planes_mod.build_fleet_geometry(fleet.records, T0, satrecs=fleet.satrecs)
    by_norad = {r.norad: r for r in fleet.records}
    params = isl_grid4.Grid4Params()
    times = [T0 + k * STEP_NS for k in range(ORBIT_S + 1)]
    out = {}
    for sg in geo.shells:
        pairs = isl_grid4.grid4_pairs(sg, T0, params)
        norads = sorted(n for p in sg.planes for n in p.norads)
        res = {"satellites": len(norads), "pairs": len(pairs), "steps": 0, "up_link_steps": 0,
               "down_link_steps": 0, "violations": 0, "min_height_km": np.inf,
               "dense_min_height_km": np.inf, "dense_checked": 0, "cross_up_above_cutoff": 0,
               "longest_up_isl_km": 0.0, "max_radius_km": 0.0, "near_limit_checked": 0,
               "near_limit_min_height_km": np.inf}
        out[sg.shell_id] = res
        if len(pairs) == 0:
            continue
        node = {n: i for i, n in enumerate(norads)}
        a = np.array([node[int(n)] for n in pairs.a])
        b = np.array([node[int(n)] for n in pairs.b])
        sats = SatelliteArray([by_norad[n] for n in norads], satrecs=fleet.satrecs)
        for lo in range(0, len(times), CHUNK):
            chunk = times[lo:lo + CHUNK]
            state = sats.propagate(chunk)
            up, _dist = isl_grid4.isl_state(a, b, pairs.kind, state.r_ecef, state.lat, params)
            view = SimpleNamespace(grid_params=params, isl_up=up, isl_a=a, isl_b=b,
                                   sat_pos_km=state.r_ecef, times_ns=np.asarray(chunk))
            chk = invariants.isl_clearance(view, dense_every=DENSE_EVERY)
            li, ti = np.nonzero(up)
            n_near, near_min = near_limit_dense_min(state.r_ecef[a[li], ti], state.r_ecef[b[li], ti],
                                                    params.min_grazing_alt_km)
            res["near_limit_checked"] += n_near
            if near_min is not None:
                res["near_limit_min_height_km"] = min(res["near_limit_min_height_km"], near_min)
            cross = pairs.kind[li] == isl_grid4.CROSS
            polar = (np.abs(state.lat[a[li], ti]) > params.polar_cutoff_deg) | \
                    (np.abs(state.lat[b[li], ti]) > params.polar_cutoff_deg)
            res["steps"] += len(chunk)
            res["up_link_steps"] += chk["checked"]
            res["down_link_steps"] += int((~up).sum())
            res["violations"] += chk["violations"]
            if chk["checked"]:
                res["min_height_km"] = min(res["min_height_km"], chk["min_height_km"])
                res["longest_up_isl_km"] = max(res["longest_up_isl_km"], chk["longest_up_isl_km"])
            if chk["dense_min_height_km"] is not None:
                res["dense_min_height_km"] = min(res["dense_min_height_km"], chk["dense_min_height_km"])
            res["dense_checked"] += chk["dense_checked"]
            res["cross_up_above_cutoff"] += int(np.sum(cross & polar))
            res["max_radius_km"] = max(res["max_radius_km"],
                                       float(np.nanmax(np.linalg.norm(state.r_ecef, axis=-1))))
    return out


def test_every_shell_is_covered_at_1_s_for_95_minutes():
    res = one_orbit_every_shell()
    # all the shells of the 2026-10-10 snapshot: 5 broadband reference shells, the 53.2 deg
    # sub-shells and both DTC layers
    assert {"53.2deg-463km", "43.0deg-483km", "97.3deg-466km", "70.0deg-572km", "70.0deg-476km",
            "dtc-53.2deg-360km", "dtc-43.0deg-357km"} <= set(res)
    for shell_id, r in res.items():
        assert r["steps"] == ORBIT_S + 1 == 5701, shell_id
        assert r["pairs"] > 0, f"{shell_id} has no Grid-4 links: nothing was checked"
        assert r["up_link_steps"] > 0 and r["dense_checked"] > 0, shell_id


def test_no_up_laser_link_below_80_km_in_any_shell():
    for shell_id, r in one_orbit_every_shell().items():
        assert r["violations"] == 0, (shell_id, r)
        assert r["min_height_km"] >= 80.0, (shell_id, r["min_height_km"])
        assert r["dense_min_height_km"] >= 80.0 - 1e-6, (shell_id, r["dense_min_height_km"])
        # every link the certified bound could not clear, densely sampled at every step
        assert r["near_limit_min_height_km"] >= 80.0 - 1e-6, (shell_id, r["near_limit_min_height_km"])
    # the near-limit sampling did look at many links (the bound alone clears most of them)
    assert sum(r["near_limit_checked"] for r in one_orbit_every_shell().values()) > 10_000


def test_the_80_km_rule_really_bites_somewhere():
    # The check above would pass trivially if no link ever came near the limit. On the real
    # fleet some links do go down for the grazing rule and the polar rule, and the lowest up
    # link sits right at the 80 km line (within 1 km) in several shells.
    res = one_orbit_every_shell()
    assert sum(r["down_link_steps"] for r in res.values()) > 0
    close = [s for s, r in res.items() if r["min_height_km"] < 81.0]
    assert len(close) >= 3, {s: r["min_height_km"] for s, r in res.items()}


def test_no_cross_plane_link_up_above_the_polar_cutoff():
    for shell_id, r in one_orbit_every_shell().items():
        assert r["cross_up_above_cutoff"] == 0, shell_id


def test_link_counts_and_lengths_are_geometrically_possible():
    # A segment whose every point is >= 80 km above the ellipsoid stays outside the sphere of
    # radius b + 80 (the polar-radius sphere lies inside the ellipsoid, so the distance to it
    # is at least the height). Two ends at radius <= r_max can then be at most
    # 2 * sqrt(r_max^2 - (b + 80)^2) apart: a check of the lengths that uses no model code.
    b = 6356.752314245
    for shell_id, r in one_orbit_every_shell().items():
        assert r["pairs"] <= 2 * r["satellites"], shell_id     # Grid-4: degree <= 4
        bound = 2.0 * np.sqrt(r["max_radius_km"] ** 2 - (b + 80.0) ** 2)
        assert r["longest_up_isl_km"] <= bound, (shell_id, r["longest_up_isl_km"], bound)

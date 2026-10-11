"""Acceptance: physical invariants over ONE ORBIT (95 min at 10 s steps) of the real
53 deg / 463 km shell, with the 10 milestone cities and 5 flows.

  * no ISL below 80 km (any up laser link, any step)
  * ground-link elevation >= 25 deg (and the satellite end >= 80 km, line of sight rising)
  * per-hop delay >= distance / c (and the stored light time is round(d/c))
  * end-to-end light time >= great-circle distance / c
  * Grid-4 degree <= 4

Plus negative tests: each checker really fires on a deliberately broken scenario.

The plan's P2 acceptance check for laser links ("0 segments below 80 km over one orbit at 1 s
steps, for EVERY shell") is test_topo_orbit_all_shells.py; this file covers the cities, ground
links, delays and paths of the milestone shell, at 10 s steps.
"""

import dataclasses
from functools import cache
from pathlib import Path

import numpy as np
import pytest

from chronoroute.data import cities, omm, snapshot
from chronoroute.route import scheduler, sids
from chronoroute.topo import geometry, graph, gsl, invariants

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
T0 = omm.parse_epoch_ns("2026-10-10T14:00:00")
CITIES = ("Chennai", "Mumbai", "London", "New York", "Singapore", "Sydney", "Tokyo",
          "Johannesburg", "Sao Paulo", "Frankfurt")
FLOWS = (("Chennai", "London"), ("New York", "Sydney"), ("Sao Paulo", "Tokyo"),
         ("Mumbai", "Frankfurt"), ("Singapore", "Johannesburg"))
STEP_S = 10
ORBIT_S = 95 * 60
ROUTE_EVERY = 6                 # plan the flows once a minute (every 6th 10 s step)


def test_zero_processing_allows_only_nearest_ns_rounding():
    from types import SimpleNamespace
    dist = np.array([[1.49 * geometry.C_M_PER_S / 1e12]])
    g = SimpleNamespace(up=np.array([[True]]), prop_ns=np.array([[1]]), processing_ns=0)
    sc = SimpleNamespace(graph=g, isl_dist_km=dist, gsl_dist_km=np.zeros((0, 1)))
    assert invariants.hop_delay(sc)["ok"]
    g.prop_ns[0, 0] = 0
    assert not invariants.hop_delay(sc)["ok"]


@cache
def orbit():
    fleet = snapshot.load_pinned(PINNED, "supgp")
    reg = sids.SidRegistry.load()
    stations = [gsl.ground_station_from_city(cities.city_by_name(n), reg.ground_station_number(n))
                for n in CITIES]
    times = [T0 + k * STEP_S * 1_000_000_000 for k in range(ORBIT_S // STEP_S + 1)]
    sc = graph.build_scenario(fleet, "53.2deg-463km", stations, times, registry=reg)
    entries = []
    for step in range(0, len(times), ROUTE_EVERY):
        csr = sc.graph.csr_at(step)
        for a, b in FLOWS:
            e = scheduler.plan_path(sc, sc.gs_node(sc.gs_index(a)), sc.gs_node(sc.gs_index(b)), step, csr=csr)
            if e is not None:
                entries.append(e)
    return sc, entries


def test_one_orbit_covers_95_minutes_at_10_s():
    sc, entries = orbit()
    assert len(sc.times_ns) == 571
    assert (sc.times_ns[-1] - sc.times_ns[0]) == 95 * 60 * 10**9
    assert sc.n_sats == 2847
    # the flows are routable almost all the time on this shell
    assert len(entries) >= 0.95 * len(FLOWS) * len(range(0, 571, ROUTE_EVERY))


def test_no_isl_below_80_km():
    sc, _ = orbit()
    res = invariants.isl_clearance(sc, dense_every=30)
    assert res["ok"], res
    assert res["checked"] > 2_500_000
    assert res["min_height_km"] >= 80.0 and res["dense_min_height_km"] >= 80.0
    # the rule does bite on the real shell: some candidate links are down at some steps
    assert (~sc.isl_up).any()


def test_ground_links_respect_the_25_deg_mask():
    sc, _ = orbit()
    res = invariants.gsl_geometry(sc)
    assert res["ok"], res
    assert res["min_elevation_deg"] >= 25.0
    assert res["min_satellite_height_km"] > 400.0
    # every station has at most 4 links at every step, and a satellite is used only if visible
    per_station = np.zeros((len(sc.ground_stations), len(sc.times_ns)), dtype=int)
    np.add.at(per_station, sc.gsl_gs, sc.gsl_up.astype(int))
    assert per_station.max() <= 4
    assert not np.any(sc.gsl_up & ~sc.gsl_visible)


def test_per_hop_delay_at_least_light_time():
    sc, _ = orbit()
    res = invariants.hop_delay(sc)
    assert res["ok"], res
    assert res["max_rounding_ns"] <= 0.5


def test_degree_at_most_4():
    sc, _ = orbit()
    res = invariants.isl_degree(sc)
    assert res["ok"], res
    assert res["max_degree"] == 4 and res["max_up_degree"] <= 4


def test_end_to_end_latency_at_least_great_circle_bound():
    sc, entries = orbit()
    res = invariants.path_latency(sc, entries)
    assert res["ok"], res
    assert res["min_light_time_over_great_circle"] > 1.0


def test_run_all_reports_all_ok():
    sc, entries = orbit()
    assert invariants.run_all(sc, entries[:20], dense_every=100)["all_ok"]


# ------------------------------------------------------------ the checks really fire

def test_checkers_detect_injected_violations():
    sc, entries = orbit()
    k = 0
    # 1. an ISL between two satellites on opposite sides of the Earth, marked up
    far_a = 0
    far_b = int(np.argmax(np.linalg.norm(sc.sat_pos_km[:, k] - sc.sat_pos_km[far_a, k], axis=1)))
    bad = dataclasses.replace(
        sc, isl_a=np.append(sc.isl_a, far_a), isl_b=np.append(sc.isl_b, far_b),
        isl_kind=np.append(sc.isl_kind, 0),
        isl_up=np.vstack([sc.isl_up, np.ones((1, sc.isl_up.shape[1]), dtype=bool)]),
        isl_dist_km=np.vstack([sc.isl_dist_km, np.zeros((1, sc.isl_up.shape[1]))]))
    assert not invariants.isl_clearance(bad, dense_every=1000)["ok"]
    # ... which also gives that satellite a fifth link somewhere -> degree check (add 1 more to be sure)
    deg = np.bincount(np.concatenate([sc.isl_a, sc.isl_b]), minlength=sc.n_sats)
    full = int(np.flatnonzero(deg == 4)[0])
    others = [int(x) for x in np.flatnonzero(deg == 4)[1:3]]
    bad_deg = dataclasses.replace(sc, isl_a=np.append(sc.isl_a, [full, full]),
                                  isl_b=np.append(sc.isl_b, others),
                                  isl_up=np.vstack([sc.isl_up, np.zeros((2, sc.isl_up.shape[1]), dtype=bool)]))
    assert not invariants.isl_degree(bad_deg)["ok"]
    # 2. a ground link to a satellite below the mask, marked up
    low = np.flatnonzero(sc.gsl_visible[:, k] == False)          # noqa: E712 (numpy array)
    gsl_up = sc.gsl_up.copy()
    gsl_up[low[0], k] = True
    assert not invariants.gsl_geometry(dataclasses.replace(sc, gsl_up=gsl_up))["ok"]
    # 3. a light time 1 ns too small
    prop = sc.graph.prop_ns.copy()
    li = int(np.flatnonzero(sc.graph.up[:, k])[0])
    prop[li, k] -= 2
    bad_graph = dataclasses.replace(sc.graph, prop_ns=prop)
    assert not invariants.hop_delay(dataclasses.replace(sc, graph=bad_graph))["ok"]
    # 4. a path claiming to be faster than light
    e = entries[0]
    fast = dataclasses.replace(e, prop_ns=tuple(1 for _ in e.prop_ns),
                               hop_delays_ns=tuple(1 for _ in e.hop_delays_ns))
    assert not invariants.path_latency(sc, [fast])["ok"]


def test_great_circle_bound_uses_exact_light_speed():
    a, b = cities.city_by_name("Chennai"), cities.city_by_name("London")
    gc = cities.great_circle_km(a, b)
    assert float(geometry.light_time_ns_exact(gc)) == pytest.approx(gc * 1e12 / 299_792_458)

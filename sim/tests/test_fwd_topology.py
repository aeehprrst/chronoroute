"""The streaming truth topology (fwd/topology.py) must equal what the topology owner's
topo.graph.build_scenario (and so `cr export bundle`) computes, link by link and step by step."""

import numpy as np
import pytest

from chronoroute.data import cities, snapshot
from chronoroute.fwd import presets
from chronoroute.fwd.topology import Topology
from chronoroute.route import sids
from chronoroute.topo import graph as gm, gsl

T0 = 1791640800000000000
STEP = 100_000_000


def stations(names, reg):
    by = {c.name: c for c in cities.load_cities()}
    reg.ensure_ground_stations(names)
    return [gsl.ground_station_from_city(by[n], reg.ground_station_number(n)) for n in names]


def compare(fleet, shell_id, names, n_steps, chunk, params=None):
    reg = sids.SidRegistry.load_or_empty(sids.DEFAULT_PATH)
    st = stations(names, reg)
    gp = params or gsl.GslParams()
    topo = Topology(fleet, shell_id, st, T0, n_steps, STEP, registry=reg, chunk_steps=chunk, gsl_params=gp,
                    keep_chunks=2)
    sc = gm.build_scenario(fleet, topo.shell.shell_id, st, [T0 + k * STEP for k in range(n_steps)],
                           registry=reg, gsl_params=gp)
    g = sc.graph
    Li = len(sc.isl_a)
    assert np.array_equal(sc.isl_a, topo.isl_a) and np.array_equal(sc.isl_b, topo.isl_b)
    assert topo.sid_of == [sc.node_sid(n) for n in range(sc.graph.n_nodes)]
    up = topo.up_range(0, n_steps - 1)
    prop = np.stack([topo.chunk_of_step(k).prop[:, k - topo.chunk_of_step(k).k0] for k in range(n_steps)], axis=1)
    assert np.array_equal(up[:Li], g.up[:Li]) and np.array_equal(prop[:Li], g.prop_ns[:Li])
    rows = {(int(a), int(b)): i for i, (a, b) in enumerate(zip(g.link_a[Li:], g.link_b[Li:]))}
    mine = set()
    for j in range(topo.n_links - Li):
        key = (int(topo.link_a[Li + j]), int(topo.link_b[Li + j]))
        mine.add(key)
        i = rows[key]
        assert np.array_equal(up[Li + j], g.up[Li + i])
        assert np.array_equal(prop[Li + j][up[Li + j]], g.prop_ns[Li + i][up[Li + j]])
    for i in np.flatnonzero(g.up[Li:].any(axis=1)):
        assert (int(g.link_a[Li + i]), int(g.link_b[Li + i])) in mine      # every ever-up ground link
    for k0 in range(0, n_steps, 7):
        k1 = min(n_steps - 1, k0 + 12)
        a, b = topo.csr_stable(k0, k1), g.csr_stable(k0, k1)
        for f in ("indptr", "indices", "weights", "transit"):
            assert np.array_equal(getattr(a, f), getattr(b, f))
    assert len(topo._chunks) <= 2
    return topo


def test_real_shell_matches_build_scenario():
    fleet = snapshot.load_pinned(presets.DEFAULT_SNAPSHOT_DIR, "supgp")
    topo = compare(fleet, "53.2deg-463km", ["Chennai", "London", "Singapore", "Sydney"], 101, 30)
    assert topo.n_sats == 2847 and topo.n_isl == 5361


def test_walker_preset_matches_build_scenario():
    fleet = presets.walker_fleet(presets.WALKER_PRESETS["C1"], T0)
    compare(fleet, None, ["London", "New York", "Tokyo"], 61, 16, gsl.GslParams(min_elevation_deg=10.0))


def test_steps_clamp_and_link_state():
    fleet = presets.walker_fleet(presets.WALKER_PRESETS["C1"], T0)
    reg = sids.SidRegistry.load_or_empty(sids.DEFAULT_PATH)
    topo = Topology(fleet, None, stations(["London"], reg), T0, 11, STEP, registry=reg, chunk_steps=4)
    assert topo.step_of(-5) == 0 and topo.step_of(STEP - 1) == 0 and topo.step_of(STEP) == 1
    assert topo.step_of(10**12) == 10
    up, prop = topo.link_state(0, 3)
    assert isinstance(up, bool) and prop > 0
    with pytest.raises(IndexError):
        topo.csr_stable(5, 11)

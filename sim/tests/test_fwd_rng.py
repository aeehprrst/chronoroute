"""Common random numbers: a draw depends only on (seed, component, entity, index)."""

import numpy as np
import pytest

from chronoroute.fwd import rng as rng_mod
from chronoroute.fwd.rng import COMPONENTS, KeyedStreams


def test_same_key_same_value_regardless_of_order_and_other_draws():
    a, b = KeyedStreams(42), KeyedStreams(42)
    order1 = [(c, (e,), i) for c in ("jitter_j1", "arq", "sample") for e in range(3) for i in (0, 5, 4095, 4096, 99999)]
    vals1 = {k: a.uniform(*k) for k in order1}
    for k in reversed(order1):              # another order, with extra unrelated draws in between
        b.uniform("traffic", (9,), 123)
        assert b.uniform(*k) == vals1[k]


def test_values_differ_across_seed_component_entity_index():
    r = KeyedStreams(1)
    base = r.uniform("jitter_j1", (0,), 10)
    assert KeyedStreams(2).uniform("jitter_j1", (0,), 10) != base
    assert r.uniform("arq", (0,), 10) != base
    assert r.uniform("jitter_j1", (1,), 10) != base
    assert r.uniform("jitter_j1", (0,), 11) != base
    assert r.uniform("jitter_j1", (0, 0), 10) != base         # entity tuples are part of the key


def test_blocks_are_the_philox_stream_of_the_documented_key_and_counter():
    r = KeyedStreams(5)
    code, size = COMPONENTS["link_fault"]
    key = np.random.SeedSequence(entropy=5, spawn_key=(code, 3, 77)).generate_state(2, np.uint64)
    for block in (0, 1, 7):
        g = np.random.Generator(np.random.Philox(key=key, counter=np.array([0, 0, block, 0], dtype=np.uint64)))
        expect = g.random(size).tolist()
        assert [r.uniform("link_fault", (3, 77), block * size + i) for i in range(size)] == expect


def test_uniforms_look_uniform_and_exponentials_have_the_mean():
    r = KeyedStreams(3)
    u = np.array([r.uniform("jitter_j1", (0,), i) for i in range(40000)])
    assert 0.0 <= u.min() and u.max() < 1.0
    assert abs(u.mean() - 0.5) < 0.01 and abs(u.var() - 1 / 12) < 0.003
    e = np.array([r.exponential("jitter_j1", (1,), i, 400_000) for i in range(40000)])
    assert abs(e.mean() / 400_000 - 1) < 0.03


def test_component_codes_are_unique_and_unknown_components_refused():
    codes = [c for c, _ in COMPONENTS.values()]
    assert len(codes) == len(set(codes))
    with pytest.raises(KeyError):
        KeyedStreams(1).uniform("weather", (0,), 0)
    with pytest.raises(ValueError):
        KeyedStreams(-1)
    with pytest.raises(ValueError):
        KeyedStreams(1).uniform("arq", (-3,), 0)


def test_pinned_values_do_not_drift():
    """Results must not change silently (numpy is pinned at 2.5.3; a change here means a new result)."""
    r = KeyedStreams(1)
    assert [r.uniform("jitter_j1", (0,), i) for i in range(3)] == \
        [0.008191606672212526, 0.9916754163606523, 0.5451134298336877]
    assert r.uniform("link_fault", (2, 5), 70) == 0.7152052738447713
    assert rng_mod.BLOCK == 4096 and COMPONENTS["jitter_j1"] == (3, 4096)

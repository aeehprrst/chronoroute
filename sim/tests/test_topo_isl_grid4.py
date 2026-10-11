"""Tests for chronoroute.topo.isl_grid4: Grid-4 laser links (MODELLED) on the real fleet's planes."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from chronoroute.data import omm, snapshot
from chronoroute.orbit import frames, planes
from chronoroute.topo import isl_grid4

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
T0 = omm.parse_epoch_ns("2026-10-10T14:00:00")


@cache
def fleet():
    return snapshot.load_pinned(PINNED, "supgp")


@cache
def geometry_at_t0():
    f = fleet()
    return planes.build_fleet_geometry(f.records, T0, satrecs=f.satrecs)


@cache
def pairs_463():
    return isl_grid4.grid4_pairs(geometry_at_t0().shell("53.2deg-463km"), T0)


# ------------------------------------------------------- a synthetic Walker shell

@dataclass(frozen=True)
class _Plane:
    index: int
    norads: tuple
    u_deg: tuple

    @property
    def size(self):
        return len(self.norads)


@dataclass(frozen=True)
class _Shell:
    shell_id: str
    planes: tuple


def walker(n_planes, per_plane, phase_f=1, drop=()):
    """Walker-delta shell; NORAD id = 1000 * plane + slot + 1; u spaced evenly with phasing."""
    total = n_planes * per_plane
    planes_ = []
    for p in range(n_planes):
        norads, us = [], []
        for s in range(per_plane):
            if (p, s) in drop:
                continue
            norads.append(1000 * p + s + 1)
            us.append((360.0 * s / per_plane + 360.0 * phase_f * p / total) % 360.0)
        order = sorted(range(len(us)), key=lambda i: us[i])
        planes_.append(_Plane(p, tuple(norads[i] for i in order), tuple(us[i] for i in order)))
    return _Shell("walker", tuple(planes_))


def test_walker_grid_is_the_classic_plus_grid():
    shell = walker(6, 8, phase_f=1)
    pairs = isl_grid4.grid4_pairs(shell, 0)
    deg = pairs.degrees()
    assert set(deg.values()) == {4}                         # a full Walker grid: every satellite has 4
    assert pairs.counts() == {"intra": 48, "cross": 48}
    assert pairs.max_cross_du_deg == pytest.approx(45.0)    # one nominal spacing, 360/8
    # cross partner of slot s in plane p (p < 5) is slot s in plane p+1 (phase offset 7.5 deg < 22.5)
    cross = {(int(a), int(b)) for a, b, k in zip(pairs.a, pairs.b, pairs.kind) if k == isl_grid4.CROSS}
    for p in range(5):
        for s in range(8):
            assert (1000 * p + s + 1, 1000 * (p + 1) + s + 1) in cross
    # the seam: plane 5 -> plane 0 is F slots shifted (Walker phasing goes all the way round)
    for s in range(8):
        a, b = 5000 + s + 1, ((s + 1) % 8) + 1
        assert (min(a, b), max(a, b)) in cross
    # rows sorted by (a, b), a < b
    assert np.all(pairs.a < pairs.b)
    keys = list(zip(pairs.a.tolist(), pairs.b.tolist()))
    assert keys == sorted(keys) and len(set(keys)) == len(keys)


def test_gap_in_next_plane_leaves_satellite_without_partner():
    """A missing satellite is not replaced by an invented long diagonal link."""
    shell = walker(4, 12, drop={(1, 3)})
    pairs = isl_grid4.grid4_pairs(shell, 0)
    deg = pairs.degrees()
    assert max(deg.values()) <= 4
    assert deg[0 * 1000 + 3 + 1] == 3                       # its partner in plane 1 is missing
    assert all(du <= pairs.max_cross_du_deg + 1e-12 for du in pairs.du_deg[pairs.kind == isl_grid4.CROSS])


def test_tiny_planes_and_tiny_shells():
    assert isl_grid4.intra_plane_pairs([7], [0.0]) == []
    assert isl_grid4.intra_plane_pairs([7, 9], [0.0, 180.0]) == [(7, 9, 180.0)]   # counted once
    two_planes = walker(2, 5)
    pairs = isl_grid4.grid4_pairs(two_planes, 0)
    assert pairs.counts()["cross"] == 5                     # 2 planes: one matching, not two
    assert max(pairs.degrees().values()) == 3


@settings(max_examples=200, deadline=None)
@given(st.lists(st.floats(0, 359.999), min_size=1, max_size=25),
       st.lists(st.floats(0, 359.999), min_size=1, max_size=25),
       st.floats(1, 90))
def test_matching_is_one_to_one_capped_and_greedy_optimal_per_step(u_a, u_b, cap):
    na = list(range(1, len(u_a) + 1))
    nb = list(range(1001, 1001 + len(u_b)))
    out = isl_grid4.match_adjacent_planes(na, u_a, nb, u_b, cap)
    assert len({a for a, _, _ in out}) == len(out) == len({b for _, b, _ in out})
    assert all(du <= cap for _, _, du in out)
    # greedy property: every unmatched in-cap pair has a matched pair at least as good on one side
    matched_a = {a: du for a, _, du in out}
    matched_b = {b: du for _, b, du in out}
    for i, a in enumerate(na):
        for j, b in enumerate(nb):
            d = float(isl_grid4._circular_du(u_a[i], u_b[j]))
            if d <= cap and (a, b) not in {(x, y) for x, y, _ in out}:
                assert (a in matched_a and matched_a[a] <= d) or (b in matched_b and matched_b[b] <= d)
    # deterministic
    assert out == isl_grid4.match_adjacent_planes(na, u_a, nb, u_b, cap)


# ------------------------------------------------------------------ the real shell

def test_real_463_shell_degree_at_most_4_and_counts():
    pairs = pairs_463()
    sg = geometry_at_t0().shell("53.2deg-463km")
    in_planes = sum(p.size for p in sg.planes)
    deg = pairs.degrees()
    assert max(deg.values()) <= isl_grid4.MAX_DEGREE
    assert set(deg) == {n for p in sg.planes for n in p.norads}     # off-grid satellites get no links
    assert pairs.counts()["intra"] == in_planes                       # every plane is a closed ring (>= 3 sats)
    assert 0.8 * in_planes < pairs.counts()["cross"] <= in_planes
    # no inter-shell links (ASSUMED): every endpoint is a member of this shell
    members = set(sg.shell.norads)
    assert set(pairs.a.tolist()) | set(pairs.b.tolist()) <= members
    # pinned numbers for this snapshot and instant (catch silent behaviour changes)
    assert (in_planes, len(pairs)) == (2847, 5361)


def test_real_pairs_are_deterministic():
    again = isl_grid4.grid4_pairs(geometry_at_t0().shell("53.2deg-463km"), T0)
    p = pairs_463()
    assert np.array_equal(p.a, again.a) and np.array_equal(p.b, again.b) and np.array_equal(p.kind, again.kind)


def test_intra_links_follow_slot_order_and_cross_links_join_adjacent_planes():
    sg = geometry_at_t0().shell("53.2deg-463km")
    plane_of = {n: p.index for p in sg.planes for n in p.norads}
    slot_of = {n: s for p in sg.planes for s, n in enumerate(p.norads)}
    size_of = {p.index: p.size for p in sg.planes}
    n_planes = len(sg.planes)
    pairs = pairs_463()
    for a, b, k in zip(pairs.a.tolist(), pairs.b.tolist(), pairs.kind.tolist()):
        pa, pb = plane_of[a], plane_of[b]
        if k == isl_grid4.INTRA:
            assert pa == pb
            assert (slot_of[a] - slot_of[b]) % size_of[pa] in (1, size_of[pa] - 1)
        else:
            assert (pa - pb) % n_planes in (1, n_planes - 1)


def test_isl_state_polar_cutoff_and_grazing():
    """Synthetic positions: a cross link above 70 deg is off; an intra link is not; a link through the Earth is off."""
    pos = np.array([
        [frames.geodetic_to_ecef(75.0, 0.0, 463.0), frames.geodetic_to_ecef(60.0, 0.0, 463.0)],
        [frames.geodetic_to_ecef(75.0, 5.0, 463.0), frames.geodetic_to_ecef(60.0, 5.0, 463.0)],
        [frames.geodetic_to_ecef(0.0, 0.0, 463.0), frames.geodetic_to_ecef(0.0, 0.0, 463.0)],
        [frames.geodetic_to_ecef(0.0, 90.0, 463.0), frames.geodetic_to_ecef(0.0, 90.0, 463.0)],
    ])                                                     # (4 satellites, 2 steps, 3)
    lat = np.array([[75.0, 60.0], [75.0, 60.0], [0.0, 0.0], [0.0, 0.0]])
    up, dist = isl_grid4.isl_state([0, 0, 2], [1, 1, 3], [isl_grid4.CROSS, isl_grid4.INTRA, isl_grid4.INTRA],
                                   pos, lat)
    assert up[0].tolist() == [False, True]                 # cross: off at 75 deg, on at 60 deg
    assert up[1].tolist() == [True, True]                  # intra: the polar rule does not apply
    assert up[2].tolist() == [False, False]                # 90 deg apart: through the Earth
    assert dist.shape == (3, 2)

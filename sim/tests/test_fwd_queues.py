"""Per-link FIFO queues (fwd/queues.py): Lindley recursion, drop-tail, rate cuts, and the two
background models checked against brute force and queueing theory."""

import math
from fractions import Fraction

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from chronoroute.fwd import queues as Q
from chronoroute.fwd.rng import KeyedStreams

C = 1_000_000_000


def brute_fifo(arrivals, sizes, rate_at, buffer):
    """Reference: the FIFO written as plainly as possible (list of packets in the system)."""
    free, system, out = 0, [], []
    for t, size in zip(arrivals, sizes):
        system = [(e, s) for e, s in system if e > t]
        if sum(s for _, s in system) + size > buffer:
            out.append(None)
            continue
        start = max(t, free)
        end = start + Q.ser_ns(size, rate_at(start))
        free = end
        system.append((end, size))
        out.append((start, end))
    return out


def test_serialization_matches_ns3_rounding():
    assert Q.ser_ns(290, C) == 2320                     # 8 ns per byte at 1 Gb/s
    assert Q.ser_ns(290, 200_000) == 11_600_000          # 290 * 8 / 200 kb/s
    assert Q.ser_ns(1, 3) == round(Fraction(8 * 10**9, 3))


@settings(max_examples=200, deadline=None)
@given(gaps=st.lists(st.integers(0, 5000), min_size=1, max_size=60),
       sizes=st.lists(st.integers(40, 1500), min_size=60, max_size=60),
       buffer=st.integers(1500, 6000))
def test_plain_fifo_equals_brute_force(gaps, sizes, buffer):
    arrivals = list(np.cumsum(gaps).tolist())
    sizes = sizes[:len(arrivals)]
    q = Q.LinkQueue(C, buffer)
    got = [q.enqueue(t, s) for t, s in zip(arrivals, sizes)]
    assert got == brute_fifo(arrivals, sizes, lambda t: C, buffer)


def test_rate_cut_uses_the_rate_at_transmission_start():
    sched = Q.RateSchedule(C, [(1_000_000, 200_000), (5_000_000, C)])
    q = Q.LinkQueue(sched, 10**9)
    arrivals = [0, 999_000, 1_000_000, 1_000_001, 6_000_000]
    got = [q.enqueue(t, 290) for t in arrivals]
    assert got == brute_fifo(arrivals, [290] * 5, sched.at, 10**9)
    assert got[1] == (999_000, 999_000 + 2320)          # started before the cut: full speed
    assert got[2][1] - got[2][0] == 11_600_000          # after the cut: 200 kb/s


def test_fluid_without_load_is_the_plain_fifo_and_with_overload_grows_linearly():
    q = Q.LinkQueue(C, 10**9, background="fluid", rho=Fraction(0))
    p = Q.LinkQueue(C, 10**9)
    for t in (0, 100, 3000, 10_000):
        assert q.enqueue(t, 500) == p.enqueue(t, 500)
    # rho = 1/2 on a link cut to C/4: backlog grows at (1/2 - 1/4) C = 250 Mb/s
    sched = Q.RateSchedule(C, [(0, C // 4)])
    f = Q.LinkQueue(sched, 10**12, background="fluid", rho=Fraction(1, 2))
    start, end = f.enqueue(1_000_000_000, 100)           # after 1 s: 250 Mbit = 1 s of work at C/4
    assert end - 1_000_000_000 == 1_000_000_000 + Q.ser_ns(100, C // 4)


def test_fluid_buffer_caps_the_backlog_and_drops_foreground():
    sched = Q.RateSchedule(C, [(0, C // 4)])
    f = Q.LinkQueue(sched, 1_000_000, background="fluid", rho=Fraction(1, 2))   # 1 MB buffer
    assert f.enqueue(1_000_000_000, 100) is None          # buffer full of fluid
    assert f.fluid_lost > 0


def test_poisson_matches_the_m_d_1_mean_wait():
    """PASTA: tiny Poisson probes see the time-average workload; M/D/1: W = rho S / (2 (1 - rho))."""
    rho, P = Fraction(1, 2), 1500
    S = Q.ser_ns(P, C)
    rng = KeyedStreams(11)
    q = Q.LinkQueue(C, 10**9, background="poisson", rho=rho, bg_packet_bytes=P, rng=rng, key=(1, 2),
                    cftp_lookback_ns=10**12)
    g = np.random.default_rng(5)
    t, waits = 0, []
    for _ in range(4000):
        t += int(g.exponential(500_000))                  # probes every 0.5 ms on average
        start, end = q.enqueue(t, 1)
        waits.append(start - t)
    expect = float(rho) * S / (2 * (1 - float(rho)))      # 6 us
    se = np.std(waits) / math.sqrt(len(waits))
    assert abs(np.mean(waits) - expect) < 4 * se + 0.05 * expect, (np.mean(waits), expect)
    assert q.bg_arrived > 0 and q.bg_dropped == 0


def test_poisson_vectorised_batches_equal_the_scalar_loop(monkeypatch):
    def run(force_loop):
        rng = KeyedStreams(3)
        q = Q.LinkQueue(C, 30_000, background="poisson", rho=Fraction(9, 10), bg_packet_bytes=1500,
                        rng=rng, key=(4, 5), cftp_lookback_ns=10**12)
        if force_loop:
            monkeypatch.setattr(q, "_batch", lambda a, F: q._batch_loop(a, F))
        return [q.enqueue(t, 300) for t in range(0, 50_000_000, 777_777)], q.bg_arrived, q.bg_dropped
    assert run(False) == run(True)


def test_poisson_coupling_from_the_past_is_exact():
    """Skipping long idle gaps (CFTP) must give exactly what full simulation gives."""
    def run(lookback):
        rng = KeyedStreams(8)
        q = Q.LinkQueue(C, 2_500_000, background="poisson", rho=Fraction(1, 2), bg_packet_bytes=1500,
                        rng=rng, key=(0, 1), cftp_lookback_ns=lookback)
        times = [0, 5_000_000, 900_000_000, 900_100_000, 3_000_000_000, 3_000_000_500]
        return [q.enqueue(t, 200) for t in times], q.cftp_skips
    full, skips_full = run(10**15)
    fast, skips_fast = run(50_000_000)
    assert skips_full == 0 and skips_fast >= 2
    assert full == fast


def test_poisson_overload_drops_and_never_exceeds_the_buffer():
    rng = KeyedStreams(2)
    sched = Q.RateSchedule(C, [(0, C // 10)])            # rho / f = 5: heavy overload
    buf = 200_000
    q = Q.LinkQueue(sched, buf, background="poisson", rho=Fraction(1, 2), bg_packet_bytes=1500,
                    rng=rng, key=(0, 1))
    ts = list(range(1_000_000, 200_000_000, 1_000_000))
    res = [q.enqueue(t, 200) for t in ts]
    assert any(r is None for r in res) and q.bg_dropped > 0
    max_wait = Q.ser_ns(buf, C // 10)                      # everything ahead fits in the buffer
    waits = [r[0] - t for t, r in zip(ts, res) if r is not None]
    assert waits and max(waits) <= max_wait and max(waits) > max_wait // 2
    assert q._occupancy(200_000_000) <= buf

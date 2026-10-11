"""
keyed.py
--------
The few random numbers the control-plane models need, drawn the same way as
the engine's common random numbers (fwd/rng.py): a value depends only on
(seed, component code, index), never on how many other draws were made.

    hello timer phases     every link direction sends hellos at phase + n * H
    BFD timer phases       the same for BFD control packets
    measurement phases     LS-D measures each link in windows offset by a phase

Why keyed: a ChronoRoute run and an LS-H run with the same seed must see the
same faults and traffic (the engine's streams), and two LS-H runs that differ
only in, say, the dead interval must see the same hello phases, so that the
comparison is paired.

The component codes here (101..) are outside the engine's table
(fwd/rng.COMPONENTS uses 1..8), so no engine stream can coincide with these.
A code is part of the definition of every draw: never renumber one.
"""

import numpy as np

COMPONENTS = {
    "ls_hello_phase": 101,       # index = 2 * link + direction (0: a->b, 1: b->a)
    "ls_bfd_phase": 102,         # same indexing
    "lsd_window_phase": 103,     # index = 2 * link + direction
    "ls_refresh_phase": 104,     # index = node: periodic LSA re-flooding
    "lsd_te_phase": 105,         # index = node: periodic TE (delay) LSA re-advertisement
    "crh_fib_phase": 106,        # index = satellite: CRH-FIB / station table re-upload (crh data plane)
    "crh_eph_phase": 107,        # index = satellite: element-set (ephemeris) re-upload (crh data plane)
}


def uniforms(seed, component, n):
    """The first n uniforms in [0, 1) of stream (seed, component): u[i] belongs to index i."""
    code = COMPONENTS[component]
    ss = np.random.SeedSequence(entropy=int(seed), spawn_key=(code,))
    key = ss.generate_state(2, np.uint64)
    g = np.random.Generator(np.random.Philox(key=key, counter=np.zeros(4, dtype=np.uint64)))
    return g.random(int(n))


def phases_ns(seed, component, n, period_ns):
    """Integer phases in [0, period_ns) for indices 0..n-1 (floor of u * period)."""
    u = uniforms(seed, component, n)
    return np.minimum((u * period_ns).astype(np.int64), int(period_ns) - 1)


__all__ = ["COMPONENTS", "uniforms", "phases_ns"]

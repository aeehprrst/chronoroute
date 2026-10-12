"""
rng.py
------
Common random numbers (CRN): every random draw of the engine is a pure
function of (seed, component, entity, index).

Why: the detection metric scores a fault
run against the SAME run with the fault removed. That comparison is only
fair if both runs use identical random numbers for every packet, hop and
link. With one shared sequential generator this is impossible: a packet that
takes one extra hop in the fault run consumes one extra draw and shifts every
later draw. Here a draw never depends on how many other draws were made, or
in which order, so

    no fault  => the two runs are identical, draw for draw;
    fault     => only what the fault really touches can change.

How (numpy only, no hashing tricks of our own):

  * key    = SeedSequence(entropy=seed, spawn_key=(component, *entity))
             .generate_state(2, uint64)            (cached per stream)
  * block  = index // B (B = the block size of the component); a
             Philox4x64-10 bit generator is created with that key and counter
             (0, 0, block, 0), and B uniforms are drawn from it. numpy's Philox increments counter word 0 (carry
             into word 1), so a block would need 2^128 draws before it could
             reach the next block's counter: blocks never overlap.
  * value  = block[index % B]

Philox is a counter-based generator (Salmon et al., SC'11): its output for a
counter is a bijection keyed by the key, which is exactly "random access by
index". Creating one costs a few microseconds, so draws are made in blocks
and cached.

Components have fixed numeric codes (COMPONENTS) because the code is part of
the key: renaming a component in the code must not change any result, and a
new component must take a NEW code.
"""

import math
from collections import OrderedDict

import numpy as np

# component name -> (code, block size). The code enters the SeedSequence spawn
# key and the block size decides which Philox block an index falls in, so
# BOTH are part of the definition of every draw: never reuse or renumber a
# code, never change a block size (that would silently change results).
# Block sizes follow how each stream is used: per-flow streams are read
# sequentially and long; per-link / per-satellite fault streams need a few
# dozen draws each, and there are thousands of them.
COMPONENTS = {
    "flow_offset": (1, 16),       # start offset of each flow inside its first period
    "traffic": (2, 4096),         # Poisson traffic inter-send times, per flow
    "jitter_j1": (3, 4096),       # J1 exponential per-hop processing jitter, per flow
    "background": (4, 4096),      # Poisson background per (link, window): used via generator()
    "arq": (5, 4096),             # ARQ per-attempt loss draws, per flow
    "link_fault": (6, 64),        # alternating-renewal up/down periods, per (fault, link)
    "node_fault": (7, 64),        # alternating-renewal satellite outages, per (fault, node)
    "sample": (8, 4096),          # which packets are traced in full, per flow
    "experiment_target": (9, 64), # frozen controlled-deviation target, per flow (MODELLED)
}

BLOCK = 4096               # the default block size (per-flow streams)
CACHE_BLOCKS = 256         # blocks kept in memory as lists (at most ~34 MB)


def _check_nonneg_int(name, value):
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return int(value)


class KeyedStreams:
    """Random numbers keyed by (seed, component, entity, index); see the module docstring.

        rng = KeyedStreams(seed=1)
        u = rng.uniform("jitter_j1", (flow,), seq * 256 + hop)    # float in [0, 1)
        g = rng.generator("background", (a, b, window))          # a numpy Generator

    entity is a tuple of non-negative integers (node ids, link ends, flow id,
    window number, ...). The same arguments always give the same value.
    """

    def __init__(self, seed):
        self.seed = _check_nonneg_int("seed", seed)
        self._keys = {}
        self._blocks = OrderedDict()

    def _code(self, component):
        try:
            return COMPONENTS[component][0]
        except KeyError:
            raise KeyError(f"unknown random component {component!r}; add it to rng.COMPONENTS "
                           "with a NEW code") from None

    def key(self, component, entity):
        """The 128-bit Philox key of one stream (2 x uint64), cached."""
        ck = (component, entity)
        key = self._keys.get(ck)
        if key is None:
            spawn = (self._code(component),) + tuple(_check_nonneg_int("entity", e) for e in entity)
            ss = np.random.SeedSequence(entropy=self.seed, spawn_key=spawn)
            key = ss.generate_state(2, np.uint64)
            self._keys[ck] = key
        return key

    def generator(self, component, entity, block=0):
        """A fresh numpy Generator for (component, entity, block): Philox(key, counter=(0,0,block,0))."""
        block = _check_nonneg_int("block", block)
        counter = np.array([0, 0, block, 0], dtype=np.uint64)
        return np.random.Generator(np.random.Philox(key=self.key(component, entity), counter=counter))

    def block(self, component, entity, block):
        """The uniforms in [0, 1) of one block, as a Python list (cached, LRU)."""
        bk = (component, entity, block)
        values = self._blocks.get(bk)
        if values is None:
            size = COMPONENTS[component][1]
            values = self.generator(component, entity, block).random(size).tolist()
            self._blocks[bk] = values
            if len(self._blocks) > CACHE_BLOCKS:
                self._blocks.popitem(last=False)
        else:
            self._blocks.move_to_end(bk)
        return values

    def uniform(self, component, entity, index):
        """The uniform in [0, 1) at `index` of stream (component, entity)."""
        b, i = divmod(index, COMPONENTS[component][1])
        return self.block(component, entity, b)[i]

    def exponential(self, component, entity, index, mean):
        """Exponential with the given mean from the keyed uniform: -mean * ln(1 - U)."""
        u = self.uniform(component, entity, index)
        return -mean * math.log1p(-u)


__all__ = ["COMPONENTS", "BLOCK", "KeyedStreams"]

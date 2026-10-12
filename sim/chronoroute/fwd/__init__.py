"""
The ChronoRoute simulator v2: a discrete-event, per-packet
engine that forwards every packet from its T-CRH bytes.

    config.py     run configuration (YAML subset / JSON), defaults, checks
    presets.py    synthetic Walker presets (C1, C2, C2b) and the 20 science pairs
    topology.py   streaming truth topology (reuses orbit/ and topo/)
    scenario.py   fleet + cities + flows + topology + the ground's planner
    rng.py        common random numbers keyed by (seed, component, entity, index)
    hop.py        spec section 6 on the bytes (fast path == chronoroute.proto)
    queues.py     per-link FIFO (Lindley), drop-tail, fluid / Poisson background
    faults.py     link/node down, renewal processes, up-but-slow models, ground truth
    fallback.py   greedy-with-visited, pure greedy, +Grid detour
    engine.py     the event loop
    command.py    `cr run --config FILE --seed N --out DIR`

The output format is spec/trace-v1.md; the configuration is docs/sim-config.md.
Modules are imported explicitly (`from chronoroute.fwd import engine`).
"""

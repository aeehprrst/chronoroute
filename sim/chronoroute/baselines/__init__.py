"""
The comparison schemes ("baselines") of the ChronoRoute experiments (master
plan P3f, reviewer must-fix #2 and #3). Every scheme is real code that sends
its packets through the SAME engine queues, links and faults as ChronoRoute
(chronoroute.fwd), with the same random numbers; what differs is only how a
scheme decides where a packet goes and what its control plane knows when.

The control planes are TIMING MODELS written in Python, with cited
parameters (docs/baselines.md), not full protocol stacks. They are labelled
MODELLED everywhere they appear.

    params.py     scheme settings, cited presets (OLSR, OSPF, BFD, RFC 7471), checks
    keyed.py      the random phases these models need (hello timers, measurement windows)
    paths.py      shortest-path trees on a "belief" graph (integer ns, fixed tie-break)
    control.py    control-byte ledger per medium and the message size models
    knowledge.py  what each control plane believes about the links at time t
    feedback.py   ground-side penalties (FB1, E2E) and the penalised planner
    engine.py     SchemeEngine: the per-scheme forwarding hooks on top of fwd.engine
    run.py        run one scheme into a result folder (trace/1 + extras + manifest)

Modules are imported explicitly (`from chronoroute.baselines import run`).
"""

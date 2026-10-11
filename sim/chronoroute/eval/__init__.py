"""
The offline evaluation layer of the experiments (master plan 5.3 and 5.4,
reviewer must-fix #1). It reads finished run folders and never re-runs the
simulator, except where a test proves an offline result equal to a direct run.

    load.py       read a run folder into flat numpy arrays (packets, paths, per-hop times)
    metrics.py    PDR with drop reasons, effective quantiles, latency stretch, packet labels,
                  clean-packet FPR, blackhole time, time-to-mitigation, control bytes
    offline.py    re-score deadlines for any slack / unit / budget rule from ONE
                  flag-and-continue run (no re-simulation for a threshold sweep)
    detection.py  counterfactual attribution with common random numbers, the phantom
                  control, the event-level detector, event ROC, Kaplan-Meier delays
    stats.py      t intervals, paired differences, cluster bootstrap (percentile and BCa),
                  Holm correction; numpy and the standard library only
    command.py    `cr eval scheme | score | compare`

Modules are imported explicitly (`from chronoroute.eval import metrics`).
"""

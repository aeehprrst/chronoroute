E16 follows the frozen protocol in experiments/PREREG.md. Its registered
paired sample exceeds the task's minimum. Actual packet records are compared;
the light-time-only predictor is retained separately for legacy analyses.

Run from a clean implementation commit after make check and make ns3-test:
`venv/bin/python -B experiments/E16/run.py --out results/E16/<run> --workers 8`.
Native PhyTxBegin timestamps and explicit transmitter/dead-link attempts feed
the same production metrics as Python, with no Python outcomes borrowed for
ns-3 scoring. Losses and undefined quantiles remain visible. TOST requires both
one-sided tests and the equivalence interval to pass the registered bounds.

Raw traces, bundles and logs stay in the adjacent ignored cache. The committed
aggregate contains the complete inventory, producer-manifest ledger, per-run
metrics, intervals, figures and verdict. C5 public inputs are REAL; C2 orbits
and all network behaviour are MODELLED; statistics are DERIVED. Agreement is
scoped to the registered replay, not other processing or background models.

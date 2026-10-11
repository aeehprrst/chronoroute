E16 Python and ns-3 agreement

C5 uses REAL public orbital inputs; C2 elements and positions are MODELLED. Network behaviour is MODELLED; comparison statistics are DERIVED. Starlink real routing is UNKNOWN; Starlink does not use T-CRH.

Complete registered grid: True. Scoped equivalence: True.
Per-packet violations: 0. Maximum recorded timing difference (ns): 0.

summary.csv retains paired TOST one-sided p-values, 90% equivalence intervals and 95% reporting intervals. Every seed remains in the inventory. Per-run source denominators, loss reasons, clean-label counts and per-flow quantiles are in per_run.csv. Losses have infinite effective latency. No undefined or infinite endpoint is dropped to pass equivalence.

Scope: zero processing delay, no background/jitter, stable planning, source insertion and continue policy; fixed-count conditional-Poisson send-time randomness shared by both engines. This does not establish agreement for other fault models, fallbacks, processing or background traffic.

Raw bundles and engine outputs remain in the adjacent ignored cache. Producer manifests, exact commands and hashes are retained in the compressed ledger.

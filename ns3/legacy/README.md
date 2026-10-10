# ns3/legacy/ -- frozen ns-3 inputs

`v0_tcrh_sweep.csv` is the original Assessment 8 output of the ns-3 T-CRH slack
sweep (the confounded "detection" score retracted in Phase 1, bug #21). It is
byte-for-byte `git show 6314c8a:tcrh_sweep.csv` from the student's own ns-3 tree
(`~/ns-3-dev`, branch `chronoroute`, commit 6314c8a76c21 "Snapshot: ChronoRoute
ns-3 work (Assessments 6-8) on top of ns-3.44"). That commit was never pushed
anywhere, so the file is kept here: `ns3/run_tcrh_sweep.py` (`make ns3-legacy`)
copies it into `results/legacy-v0.9/ns3/tcrh_sweep/` from this folder, after
checking its sha256 (`63cb2ef5...`), and so works on any ns-3.44 tree.

Never edit it. `sim/tests/test_ns3_sweep_runner.py` checks the hash and, where
the original tree exists, that it still equals the commit's file.

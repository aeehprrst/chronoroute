# ChronoRoute: project rules and experiment notes

The pre-registration, [`experiments/PREREG.md`](../experiments/PREREG.md), refers to section 2
(the rules that apply to every change) and section 5 (facts known before the experiments ran)
of this file, so both keep their numbers here. Rules 1 to 8 and the coverage fact are
reproduced unchanged from the version registered with the pre-registration at commit
`b87f08a`; the planning notes and local set-up notes that were around them are not repeated.

## 2. Rules for every change (non-negotiable)

1. **Nothing fake.** Every number shown anywhere (report, website, README) must come from a
   result file in `results/` that has a `manifest.json`. No hand-typed numbers, no formulas
   presented as measurements, no placeholder values.
2. **Label everything** REAL / DERIVED / MODELLED / UNKNOWN using `sim/chronoroute/labels.py`.
   Starlink's laser-link layout, traffic and failures are MODELLED. Starlink's real routing is
   UNKNOWN and Starlink does not use T-CRH; never imply otherwise.
3. **The spec and golden vectors win.** If code disagrees with `spec/tcrh-v1.md` or
   `spec/golden/*.json`, the code is wrong.
4. **Tests first.** Every new function gets tests. Before every commit run:
   `make check` (all Python tests + golden vectors). If you touched `ns3/`, also run
   `make ns3-test`. If you touched `web/`, run `cd web && npm test && npm run check && npm run build`.
5. **Clean provenance.** Commit the code first, then run experiments, so every
   `manifest.json` shows a clean commit (`"dirty": false`). Then commit the results.
6. **Reproducible.** Fixed seeds, deterministic outputs, exact commands recorded in the
   manifest. Experiments use the pinned snapshot `data/pinned/20261010T1358Z-celestrak/`.
7. **Statistics.** At least 30 seeds per main cell; 95% confidence intervals with the t
   distribution or a bootstrap over runs (never over packets, never z with small n);
   report cases where ChronoRoute loses.
8. **Detection is scored counterfactually**: the same seed with and without the fault
   (common random numbers); a detection is a packet flagged with the fault and not flagged
   without it. A null fault must score exactly 0.

## 5. Facts known before the experiments ran

- **High-latitude city pairs have no path on the 53 deg shell.** Reykjavik-Toronto and
  Anchorage-Oslo need satellites above about 60.5 deg latitude, which the 53.2 deg / 463 km
  shell does not provide. Either exclude them for that shell (say so in PREREG) or add the
  polar/70 deg shells.
- **Engine speed:** about 110-190 thousand hop events per second per process (pure Python).
  A 600 s run of the real shell with 20 flows at 100 packets/s takes about 4 minutes and
  0.6 GB, so a campaign runs several processes in parallel within the machine's memory.
- **Background traffic:** the `fluid` model is used for experiments. The `poisson` model is
  exact but about 20 times slower.
- **Offline scoring:** each (scenario, seed, fault) is recorded once with deviation policy
  `continue`, and many slack values are then scored with `cr eval score` instead of
  re-simulating. See [`docs/baselines.md`](baselines.md).
- **Course milestone:** a laser link cut to 200 kb/s (overloaded) is detected in 99.9% of the
  packets that cross it; cuts to 250 kb/s and above are not detected because the extra delay
  stays inside the slack ([`docs/course-milestone.md`](course-milestone.md)).
- **Corrected semester results** ([`docs/results-changelog.md`](results-changelog.md)): false
  alarms at S = 1.2 are 0.7% (1 ms units); 1.5x slowdowns are caught 17% of the time, 2x
  slowdowns 72%.

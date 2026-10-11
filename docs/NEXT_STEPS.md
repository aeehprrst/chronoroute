# ChronoRoute: next steps

This file is the working guide for whoever continues the project (a person or a coding
assistant). Read it fully before changing anything. It lists what exists, the rules every
change must follow, and the remaining tasks in order, each with the checks that prove it is
done.

Repository: <https://github.com/aeehprrst/chronoroute> (local copy: `~/chronoroute` in WSL Ubuntu).

---

## 1. What already exists

| Part | Where | Status |
|---|---|---|
| T-CRH v1 wire format (normative) | `spec/tcrh-v1.md` | Done |
| Golden test vectors (shared by every implementation) | `spec/golden/` | Done; `make golden` checks them |
| Python reference implementation of T-CRH, CRH-16/32, sizes, time base | `sim/chronoroute/proto/` | Done |
| Provenance (`manifest.json` for every result) | `sim/chronoroute/provenance.py` | Done |
| REAL / DERIVED / MODELLED label table | `sim/chronoroute/labels.py` | Done |
| Real orbit data pipeline (CelesTrak rules), snapshots | `pipeline/`, `data/pinned/` | Done |
| Fleet, shells, orbital planes | `sim/chronoroute/data/`, `sim/chronoroute/orbit/` | Done (`cr fleet report`) |
| Laser links (Grid-4, MODELLED), ground links, routing, scheduler | `sim/chronoroute/topo/`, `sim/chronoroute/route/` | Done (`cr route`) |
| ns-3 scenario bundle + website data export | `sim/chronoroute/export/`, `docs/bundle-format.md` | Done |
| Simulator v2 engine (queues, faults, fallbacks, traces) | `sim/chronoroute/fwd/`, `spec/trace-v1.md`, `docs/sim-config.md` | Done (`cr run`); matches the ns-3 course milestone per packet to the nanosecond |
| Baselines + offline evaluation (metrics, counterfactual detection, CIs) | `sim/chronoroute/baselines/`, `sim/chronoroute/eval/`, `docs/baselines.md` | Done (`cr eval scheme | score | roc`); Task 0 review covered by regression tests |
| 3D viewer (PyVista) and ns-3 trace import | `sim/chronoroute/viz/`, `docs/viewer.md` | Done (`cr viz globe`, `cr viz map2d`, `cr trace from-ns3`) |
| ns-3 module: real IPv6 Routing Header type 253, LEO bundle runner | `ns3/contrib/chronoroute/`, `ns3/run_leo.py` | Done |
| Course milestone (ns-3 LEO run on the real 463 km shell) | `docs/course-milestone.md`, `results/course-milestone/` | Done |
| Wireshark dissector | `tools/wireshark/` | Done |
| Corrected semester results | `results/legacy-v0.9/`, `docs/results-changelog.md` | Done |
| Website (Astro + React + three.js): live globe, protocol, route planner | `web/` | Done (live globe, `/protocol`, `/route` with Python parity tests); results pages still to do |
| Website deploy + 4-hourly data refresh (GitHub Pages) | `.github/workflows/pages.yml`, `refresh-data.yml` | Done; public site: <https://aeehprrst.github.io/chronoroute/> |

---

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
9. **Git identity is already set** (Arshpreet Gaba). Do not change it. Commit messages are
   plain and factual. Do not mention AI assistants or tools in commits, code or documents.
10. **Commands inside WSL.** Work in `~/chronoroute`. Python is `venv/bin/python -B`
    (Python 3.14; numpy 2.5.3, networkx, sgp4, matplotlib, pyvista; there is NO scipy, so
    implement small statistics with numpy). Node: `export PATH=$HOME/.local/opt/node/bin:$PATH`.
    ns-3: `~/ns-3-dev` (build with `-j8` at most; WSL has limited RAM).

---

## 3. Remaining tasks, in order

Each task lists what to build, where, and the checks that prove it is done.

### Task 0: fix the open review findings first
**Status: complete.** The findings below are retained as the review record. The initial
checkout already contained the transmitter-loss exposure fix, configuration comparisons,
mixed-infinity refusal, accumulated live-fault display and corrected OLSR reference, with
regression tests for the code fixes. Those tests were verified; the remaining bugs were
reproduced with failing tests before their fixes.

Coverage is in `sim/tests/test_eval_metrics.py` (fluid and Poisson background, ARQ losses,
and refusal of missing attempted-link records), `test_eval_detection.py` (including pairs
with no scored faults), `test_eval_stats.py`, `test_fwd_rerun.py` (including legacy and
partially migrated histories), `test_viz_player.py`, `test_viz_hud.py`, and
`test_baselines_docs.py`. Web regressions are in `web/tests/route-planner-view.test.ts`,
`ci-scripts.test.ts`, `sgp4-parity.test.ts` and `sgp4-gate.test.ts`.
Required checks: `make check`, and `cd web && npm test && npm run check && npm run build`.

### [major] sim: sim/chronoroute/eval/metrics.py: exposure() :262-315, FaultIndex.exposed_any() :364-416, packet_labels() :469-503 (hits need a next node on the path)
- Problem: Packets that the fault itself drops at the faulty link are never exposed and are labelled clean. This covers drop-tail buffer_overflow under a rate cut and arq_exhausted under ARQ. These packets' paths end at the upstream node, so the (u, v) hop test never matches. They enter the clean-packet FPR denominator, which biases FPR downward, and the counterfactual's changed-but-unexposed set. The fixer's claim that exposure equals the changed packets exactly for a rate cut holds only while the buffer never fills: the committed test uses 200 pps with no background. A rate cut with background load is exactly how faults.py says queues build, and the fix to finding 11 now recommends rate_cut and arq for headline experiments.
- Evidence: exposure_check.py and exposure_drops.py, C1 seed 21, 2 flows at 300 pps, ISL background rho=0.3, rate_cut factor 0.002 on a mid-path link for [2, 3) s.
- fluid background: exposed 29, changed 309, changed but unexposed 280. All 280 are (dropped, buffer_overflow), their path ends at an end of the faulty link, and all are labelled clean: 280 of the run's 2971 clean packets.
- Poisson background: 268 such packets.
- ARQ loss 0.3, no background: 2 arq_exhausted drops labelled clean.
- induced_unexposed stays 0 only because a dropped packet cannot be flagged.
- Fix: Record the attempted next hop and attempt time for buffer_overflow and arq_exhausted drops, as link_down_at / drop_next already do for table schemes. Count them as touching the faulty link in exposure() and exposed_any(), so packet_labels gives them 'fault'. In counterfactual(), either count them as exposed or report them separately (lost_at_fault) and document the choice. Add a test with background rho=0.3 and factor 0.002 asserting that changed equals exposed plus packets dropped at the faulty link, and that no fault-caused drop is labelled clean.

### [minor] sim: sim/chronoroute/eval/detection.py:169-199 check_twin (used by counterfactual, event_detection, control_plane_detection, event_roc); eval/command.py score_run
- Problem: check_twin compares only the packets (send_ns, flow) and the fault logs. A twin run with a different jitter, slack, policy, carrier_detect or even a different scheme is accepted, and attribution is then silently wrong. This is the same class of silent mis-pairing as the old blocker, but it needs a wrongly built twin. run.json now stores engine.config and scheme.settings, so the check is cheap.
- Evidence: crn_check.py, C1 seed 11, proper twin attributed 298:
- jitter mean 800 us: accepted, attributed 276, lost_flags 61.
- slack 1.1: accepted, attributed 200, lost_flags 294.
- policy greedy, carrier_detect_ms 20, scheme e2e: all accepted.
- `cr eval score /tmp/cr-sb/verify-sim/crn/fr --twin /tmp/cr-sb/verify-sim/crn/tw_slack --out ...` completes with no warning.
- Fix: In check_twin, require run.json engine.config (with the faults removed) and scheme.settings to be equal between the fault run and the twin. Refuse on any difference, optionally with an explicit override flag. Add a test that refuses twins differing only in jitter, slack and scheme.

### [minor] sim: sim/chronoroute/eval/stats.py:234-307 bootstrap_ci
- Problem: With +inf and -inf runs together, inf - inf resamples become NaN and are silently left out as 'undefined', and the estimate is NaN. The docstring says only 0/0 ratio resamples are left out. mean_ci_t and paired refuse the same input. The case is reachable by bootstrapping paired differences where one side is inf in one run and the other side is inf in another.
- Evidence: stats_check.py: bootstrap_ci([inf, -inf, 1, 2, 3], method='percentile') returns {'estimate': nan, 'lo': -inf, 'hi': inf, 'n_boot': 1158, 'n_boot_undefined': 842}. mean_ci_t raises 'both +inf and -inf among the runs'.
- Fix: Refuse mixed-sign infinities up front, as mean_ci_t does, or at least keep inf - inf resamples out of n_boot_undefined and say why. Add a test.

### [minor] sim: sim/chronoroute/viz/player.py:700-727 _go_live (live-mode message)
- Problem: Re-runs chain: each key press re-runs the run currently shown, so faults accumulate. The HUD message names only the newest fault, so the viewer may believe only that link is degraded or failed.
- Evidence: live_check.py: f, then f again after the path moved, then d produced the folder base--rerun-down-164-163-...--rerun-down-164-144-...--rerun-rate-164-144-..., which carries three faults. The message says only 'WALKER-C1-P08-S04 - WALKER-C1-P07-S04 degraded (rate cut)'.
- Fix: Show all faults added by live mode (from the chain of run.json 'rerun' entries or engine.config faults minus the original's) in the message and HUD. Alternatively, always re-run from the original recorded run and say so.

### [minor] sim: docs/baselines.md:405
- Problem: A stale cross-reference: 'OLSR is modelled with OSPF-like flooding (see 2.3)'. Section 2.3 is now 'Failure visibility'; the OLSR flooding note is in section 2.4 (line 184).
- Evidence: The headings list §2.3 at line 151 as 'Failure visibility: one model for every scheme'; the OLSR byte-model idealisation is at line 184 under §2.4.
- Fix: Change the reference to §2.4.

### [minor] web: web/src/components/route/RoutePlanner.tsx:490-497 (new row 'Final deadline in the header, D_h − E (rounded up to whole N ms units)')
- Problem: The row added for fix #7 always says the deadline is 'rounded up to whole units'. When a delta saturates (SAT set: each Δ is clamped to 255 units), D_h − E is far below ceil(B_h/u), so the label is false and contradicts the B_h row just above it. The only hint is a note under the hop table saying SAT is set.
- Evidence: Browser on the preview of the built site, slack field set to 30: 'Final cumulative budget B8 (slack S = 30) | 1092.91938 ms after ingress' next to 'Final deadline in the header, D8 − E (rounded up to whole 0.1 ms units) | 2040 units = 204.0 ms after Epoch_Base'. Every Δ is 255, and ceil(B8/u) would be 10930 units. tcrh.ts has MAX_DELTA = 255, and the slack input accepts any decimal.
- Fix: When plan.sat is true, change the label, e.g. 'D_h − E (SAT: deltas clamped to 255 units; ceil(B_h/u) would be N units)'. Otherwise keep 'rounded up'.

### [minor] web: web/tests/ci-scripts.test.ts:35-43 (run() passes ...process.env) with .github/workflows/pages.yml:103-108 (MAX_SNAPSHOTS set in the step that runs npm test)
- Problem: The CI-script test passes its own environment on to the script, including MAX_SNAPSHOTS (and CR_BUILD_DATA / CR_TEST if set). In pages.yml, build-tested-data.sh runs `npm test` inside a step that sets MAX_SNAPSHOTS, so the test sees the workflow's value. The fallback test needs 3 candidates. If MAX_SNAPSHOTS in pages.yml is ever changed to 1 or 2, that test fails for every candidate snapshot and nothing deploys, with a confusing error.
- Evidence: `MAX_SNAPSHOTS=2 npx vitest run tests/ci-scripts.test.ts` -> 1 failed, 7 passed (failing: 'falls back past a snapshot that fails the build and one that fails the tests'). With the current value "3" it passes.
- Fix: In run(), drop MAX_SNAPSHOTS, CR_BUILD_DATA and CR_TEST from the inherited environment, or set MAX_SNAPSHOTS: '3' explicitly in the fallback test.

### [minor] web: web/tests/sgp4-parity.test.ts:21-23 (readParity() = reference file only); web/src/pages/route.astro:67 ('Positions themselves are compared separately')
- Problem: The SGP4 tolerance check (satellite.js vs python-sgp4, 10 m / 1 m) runs only on the reference 1358Z file and its embedded omm_min. Satellite positions in the browser come from the served omm.min.json. omm.test.ts checks that file against the raw download field by field, but its satellite.js positions are never compared with the positions Python computed for the served snapshot. The served parity file already exports those positions (frame.ecef_km and ecef_ms_epoch_km). A satellite.js problem with a newer element set would not block a deploy.
- Evidence: sgp4-parity.test.ts: `const doc = readParity();` and `ommRowsToRecords(JSON.parse(doc.omm_min))`. The test name reports 2,847 satellites (1358Z); the served 2035Z shell has 2,848. route-parity.test.ts uses Python's positions for both runs, so only the browser's own positions go unchecked.
- Fix: Run the same SGP4 check for both runs: the reference file, and SERVED_PARITY_FILE with the served public/data omm.min.json. Optionally say on the route page that the position check covers the served snapshot too.

**Done when:** every item above has a test and a fix, and `make check` and `cd web && npm test` pass.

### Task 1: Pre-registration (`experiments/PREREG.md`)
Write down, before running the main experiments: research questions, hypotheses, metrics
(definitions as in `docs/baselines.md` / `sim/chronoroute/eval/`), constellations (C5 real
463 km shell from the pinned snapshot; C2 72x22 @ 550 km as the literature reference),
the 20 city pairs, fault models and parameter grids, seeds (pilots 0-99, confirmatory 1000+),
analysis method, and what would count as ChronoRoute "losing". Commit it alone; its commit
hash goes into every confirmatory manifest.
**Done when:** the file is committed and referenced by the experiment configs.

### Task 2: E0 correctness gate (`experiments/E00/`)
Orbit cross-check (python-sgp4 vs satellite.js on 200 satellites x many times), physics
invariants over a full orbit (no link below 80 km, delay >= distance/c, latency >=
great-circle/c), header bytes identical in Python, ns-3, the website engine and Wireshark.
**Done when:** `results/E00/<run>/` has summary CSV + manifest, 0 violations.

### Task 3: E1 detection of up-but-slow links (`experiments/E01/`) — the main experiment
On C5 (and C2), UDP probes on the city pairs; one fault per run on an on-path laser link
(rate cut with background load, added delay, ARQ retransmissions; several magnitudes;
first/middle/last third of the path). Record with deviation policy `continue`, then score
offline for many slack values and budget rules. Compare against: hello link-state (LS-H),
delay-aware link-state (LS-D), end-to-end check (E2E), local queue monitor (LQ), CRH-16
(no deadlines) and the oracle (O-Q).
**Outputs:** ROC curves (detection vs false-alarm rate), detection at FPR <= 1%, detection
delay from fault onset, by fault size and position; CSVs + manifests + figures.
**Done when:** every cell has >= 30 seeds with CIs; the null fault scores 0.

### Task 4: E2 header overhead (`experiments/E02/`)
Sizes for 1-40 hops: T-CRH, CRH-16, CRH-32, SRv6 SRH, plus encapsulation mode (+40 B), and
the measured on-wire sizes from the ns-3 course-milestone pcap. Percent of a 1400 B packet.

### Task 5: E4 hard failures (`experiments/E04/`)
Links fail and recover (failure probability U, repair time MTTR), satellite outages.
Delivery rate, blackhole time per failure, effective P99 latency (lost = infinite) for
ChronoRoute variants vs O-T, SNAP (Hypatia-style tables), LS-H (+BFD), CRH-16.

### Task 6: E5 fallback policies (`experiments/E05/`)
Trigger deviation at random on-path nodes; compare greedy-with-visited, pure greedy, +Grid
detour, continue, drop: stuck rate, latency stretch (>= 1), extra hops.

### Task 7: E16 Python vs ns-3 agreement (`experiments/E16/`)
Extend `sim/chronoroute/export/ns3_crosscheck.py`: deterministic replay must be identical
per packet; with randomness, 30 runs each side and equivalence (TOST) on PDR, FPR, P50/P99.

### Task 8: Website results pages (`web/`)
`/experiments` and one page per experiment, reading ONLY `results/*/summary.csv` and
`manifest.json` (the build must fail if a chart has no manifest). Each page: question,
pre-registered hypothesis, verdict, charts with CI bands, data table, "Download CSV" (the
same file), a "How this was made" panel from the manifest, limitations, and cases where
ChronoRoute loses. Functionality only; visual design comes last.

### Task 9: Report draft (`docs/report/`)
IEEE-style report: introduction, background (RFC 8200, RFC 9631, SRv6, LEO routing, Hypatia),
design (T-CRH), implementation (Python, ns-3, website), methodology (REAL vs MODELLED),
results (from the CSVs only), discussion, limitations, related work (CGREB, SRTSN, CRH-20,
STARGLIDER, gray failures, IOAM/STAMP, IETF TVR), conclusion. Plus `docs/claims.md`: every
claim with the result file that supports it.

### Task 10: Viva kit (`docs/viva/`)
A 9-minute demo script (fleet report, 3D viewer, slowed link, Wireshark, ns-3 NetAnim, website),
offline backups (pinned snapshot, recorded videos), likely questions with answers.

### Task 11 (last): website design upgrade
Only after everything above is done and the public site works.

---

## 4. Command cheat sheet


```bash
cd ~/chronoroute
make check                      # all Python tests + golden vectors (run before every commit)
make ns3-test                   # build ns-3 and run the chronoroute test suite
make course-milestone           # re-run the ns-3 LEO milestone
venv/bin/cr fleet report data/pinned/20261010T1358Z-celestrak
venv/bin/cr route --from Chennai --to London
venv/bin/cr run --config <file> --seed 1 --out <dir>   # simulator v2 (docs/sim-config.md)
venv/bin/cr eval roc ...        # offline scoring and ROC (docs/baselines.md)
GALLIUM_DRIVER=d3d12 venv/bin/cr viz globe --snapshot data/pinned/20261010T1358Z-celestrak   # 3D viewer
git push origin main            # publish (GitHub login is already set up)
```

---

## 5. Facts to know before running experiments

- **High-latitude city pairs have no path on the 53 deg shell.** Reykjavik-Toronto and
  Anchorage-Oslo need satellites above about 60.5 deg latitude, which the 53.2 deg / 463 km
  shell does not provide. Either exclude them for that shell (say so in PREREG) or add the
  polar/70 deg shells.
- **Engine speed:** about 110-190 thousand hop events per second per process (pure Python).
  A 600 s run of the real shell with 20 flows at 100 packets/s takes about 4 minutes and
  0.6 GB. Use several processes in parallel (at most about 10; WSL has about 7.6 GB RAM unless
  `.wslconfig` raises it). Plan the E1 grid so the whole campaign fits in a few hours.
- **Background traffic:** use the `fluid` model for experiments. The `poisson` model is exact
  but about 20 times slower.
- **Offline scoring:** record each (scenario, seed, fault) once with deviation policy
  `continue`, then score many slack values with `cr eval score` instead of re-simulating.
  See `docs/baselines.md`.
- **Known result so far (course milestone):** a laser link cut to 200 kb/s (overloaded) is
  detected in 99.9% of the packets that cross it; cuts to 250 kb/s and above are not detected
  because the extra delay stays inside the slack. E1 must map this boundary properly and
  compare it with the local queue monitor (LQ), which can see the queue directly.
- **Corrected semester results** (`docs/results-changelog.md`): false alarms at S = 1.2 are
  0.7% (1 ms units); 1.5x slowdowns are caught 17% of the time, 2x slowdowns 72%.

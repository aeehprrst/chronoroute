# Results changelog: legacy v0 → v0.9 ("corrected")

Date: 2026-10-10, revised 2026-10-11 after the Phase 1 review (see "Revision 2" and
"Revision 3" below). Part of Phase 1 ("Foundations") of the project.

This file lists every headline number from the old ChronoRoute results next to the
number the bug-fixed code gives now, and says *why* it changed. It is written so
that each change can be checked: what was wrong, what the fix was, and how
much it moved the answer.

**Short version.** The protocol mechanism still works:
- a packet that meets its deadlines is never flagged;
- a slowed link is caught only when it is slowed a lot;
- a fault that does nothing is now "detected" exactly 0 % of the time.

But several headline claims were artefacts of bugs and have to go:
- "S = 1.2 is optimal";
- "100 % of 2× slowdowns detected";
- "S = 1.30 in ns-3 confirms it";
- "3 s schedule interval";
- "deviation floor grows with scale".

See [section 2](#2-what-got-weaker-what-got-stronger) and the
[claims to retire](#12-claims-to-retire) list.

**Revision 2 (2026-10-11, Phase 1 review).** What changed in this file, and in the code and results
behind it:
- **Confidence intervals in Exp 1 and Exp 6 now use the flow as the unit of analysis.** The ten
  seeds of a flow share its geometry (the stale-path rate is identical in all of them), so the
  30 flow × seed runs are not independent. Each flow is averaged over its seeds and the t
  interval is taken over the 3 flows (2 degrees of freedom). Means are unchanged (except where
  a run had no defined value); the intervals are much wider. Re-run: Exp 1 (dev, Starlink) and
  Exp 6.
- **An operating point now needs a useful detection**: mean detection at least as large as the
  1 % false-positive limit. The 0.1 ms "S = 1.75" (0.04-0.08 % detection) and Exp 6's Telesat
  0.1 ms "S = 1.5" (0.08 %) are now "none", the same rule in Exp 1 and Exp 6. The limit is on
  the **mean** FPR, and the figures and this file now say so.
- **Exp 7's 1 s "recommendation" is limited by the simulation's 1 s topology step**, and the
  chooser, the figure and this file now say so (re-run).
- **Exp 5's "already optimal" counted hop counts, not latency.** Both shares are now reported
  (re-run).
- **ns-3:** the fixed program still picked S = 1.30 by Youden J. It now applies the same rule
  as Exp 1 (it prints S = 1.5 for the 25 ms fault and "no operating point" for the 5 ms
  fault). The headline ns-3 numbers are now means over RngRun 1-5 with a t interval. The
  programs moved into this repository (`ns3/scratch/`) and `make ns3-legacy` regenerates every
  ns-3 file; no CSV changed.
- Wording: like-for-like old-vs-new false-positive comparisons; the oracle reroute is an upper
  bound, not a "simple baseline"; the Exp 1 detection drop is attributed to all the fixes
  together; the two detection denominators (Python vs ns-3) are stated.

**Revision 3 (2026-10-11, re-verification). No number changed.**
- **Exp 6 figure re-drawn.** Revision 2's two-line title on the floor panel was drawn over
  the "Header cost" panel's tick labels ("(351 sats)" ...). The figure now uses matplotlib's
  constrained layout, the floor values have a white box so the error bars do not cross
  them, and the path-length panel has headroom for its value labels. Re-run:
  `run_scaled.py starlink exp6_scale_validation`. Both CSVs are byte-identical to revision
  2; only the PNG and the manifest changed.
- **`make ns3-legacy` now works on any ns-3.44 tree.** It used to read the Assessment 8 CSV
  with `git show 6314c8a:tcrh_sweep.csv`. That commit exists only in the author's own
  `~/ns-3-dev`, so on a fresh tree the script crashed after the sweeps had already written
  into the output folder. The CSV is now stored in `ns3/legacy/v0_tcrh_sweep.csv` (same
  bytes, sha256 pinned). The script checks everything first and writes into a staging
  folder, so a failed run changes nothing. `README.md` has a "fresh ns-3 tree" recipe.
  Re-run: every CSV, PNG and log is byte-identical; only the manifest changed (its note on
  where `v0_tcrh_sweep.csv` comes from).

---

## 0. Where the numbers come from

| | Old (v0) | New (v0.9) |
|---|---|---|
| Code | git tag `v0-semester` (`src/`) | `sim/legacy/` on top of commit `d5e034a`, plus the uncommitted Phase 1 fixes (every manifest says `dirty: true`). ns-3 programs: `ns3/scratch/` in this repository |
| Dev run | `python run_all.py`: Exp 1–5 (15.1 s wall when re-run today) | `cd sim/legacy && ../../venv/bin/python -B run_all.py`: **86.9 s** wall |
| Starlink run | `python run_scaled.py starlink`: Exp 1–7 (63.0 s wall when re-run today) | `../../venv/bin/python -B run_scaled.py starlink`: **357.1 s** wall |
| Outputs | 7 PNGs per folder, no data | `results/legacy-v0.9/{dev,starlink}/<exp>/`: PNG + CSV of the plotted numbers + `manifest.json` |
| Statistics | 1 flow, 1 seed, no error bars | means with 95 % Student-t confidence intervals (written `[lo, hi]` below) over the **independent unit** of each experiment: the flow in Exp 1 and Exp 6 (3 flows, each the mean of 10 seeds), the failure draw in Exp 4, the window in Exp 7, the RngRun in ns-3 (5 runs) |

**How the old numbers were checked.**
- The tagged v0 code was re-run in a scratch folder (`/tmp/cr-p1/runner/chronoroute-v0`).
- All 12 old figures regenerated **byte-identical** to `results/legacy-v0/` and
  `results/legacy-v0-starlink/`: 5 dev and 7 Starlink.
- So the old printouts quoted below are exactly the numbers behind the frozen PNGs.
- They also match the semester project notes (not published; cited as "H:line").
- The "Starlink guide" printout cited by the code audit of the semester version is not on
  disk. Where that audit (not published; cited as "A:line") quotes it, the v0 re-run
  reproduces the same numbers.

Quirks of the old run:
- In v0 the dev `results/` folder held copies of the Starlink Exp 2, 3, 6 and 7 figures
  (byte-identical files).
- Exp 6 and Exp 7 only exist as Starlink runs, then and now. Exp 6 includes the dev
  shell as one of its four rows.

**Validation.**
- All 13 output folders were checked with `chronoroute.provenance.validate_manifest`:
  5 dev, 7 Starlink and 1 copied ns-3 folder.
- Each one passes: the schema checks out, `config_sha256` and `run_id` recompute, and
  every output's sha256 and size match.
- Every folder has at least one PNG, at least one CSV and a `manifest.json`, and no
  file in a folder is missing from its manifest.
- `dirty` is `true` everywhere, because the Phase 1 code is not committed yet. See
  [section 13](#13-known-limitations-of-this-re-run).

The test suite was green before the runs (`venv/bin/python -B -m pytest sim/tests` →
`330 passed`). After the revision-2 fixes: `355 passed`.

---

## 1. The bug fixes that move numbers

Bug numbers are from the Phase 1 bug list of the project plan (not published). Bug #21
came from a later design review. Fixes that change no plotted
number (#8, #11, #12, #14, #17, #19) are listed for completeness.

| # | Fix | What it moves |
|---|---|---|
| 1 | The deadline is now also checked at the destination; new outcome `DELIVERED_LATE` (counts as delivered) | slightly more flags; Exp 1/4/6/7 |
| 2 | Greedy fallback skips failed links; no infinite loop | lets Exp 4 pass `failed_links` on unpruned graphs |
| 3 | **Counterfactual detection**: same packets, same random draws, with and without the fault. A detection = flagged with the fault and NOT without it. Null fault (1.0×) must score exactly 0 | **Exp 1 and Exp 6 detection** (big) |
| 4 | Header bytes match ns-3 (reversed SIDs, decrement-then-index); forwarding reads only the bytes | wire compatibility; no number by itself |
| 5 | `CRH16_FIXED` 8 → 4 bytes | **Exp 2 and Exp 6 CRH-16 bars** (−8 B) |
| 6 | **Ceil-cumulative deltas**: no budget is ever rounded down; deadline units 1 ms (code 0) or 0.1 ms (code 1) | **false-positive rates** (big) |
| 7 | Epoch_Base stamped per packet at ingress, rounded up to the unit | about +1 unit of slack on every deadline |
| 8 | Wrap-safe 32-bit compare | no number today |
| 9 | Ground stations placed with GMST and WGS84; ellipsoid "up"; shell altitude measured from 6378.137 km | **latency, which satellites the cities see, stale-path rates** |
| 10 | Seam ISLs include the phasing offset (Starlink seam median 1617 → 519 km) | path lengths and stretch near the seam |
| 11 | 80 km grazing rule instead of a 5500 km range | none: identical link set on all four presets |
| 12 | SGP4 errors skip the satellite | none here: 0 satellites skipped (all 10 manifests that propagate) |
| 13 | `tle.py` keeps the last satellite of 2-line files; altitude above 6378.137 km | TLE validation altitudes ([section 11](#11-physics-and-validation-numbers-quoted-in-the-semester-notes)) |
| 14 | Strict drop gets its own outcome `DROPPED_DEADLINE_STRICT` | label only |
| 15 | One `ConstellationConfig`; no stale by-value copies; cache keyed on config | run-order independence (Exp 4/5/6) |
| 16 | Exp 5 uses the simulator's 40-hop limit (was 60) and counts losses | **Exp 5 delivery and stretch** (big) |
| 18–21 | ns-3 fixes: µs arithmetic, renamed RTT column, real path trace, **paired detection score** | **ns-3 slack sweep** |
| — | Common random numbers, multi-flow multi-seed runs, confidence intervals, CSV and manifests | every experiment |
| — | Exp 3: one refresh interval for all schemes; measured hop count; per-packet header bytes shown | Exp 3 |
| — | Exp 4: oracle-reroute baseline added | Exp 4 |
| — | Exp 7: 32 windows across a full orbit, not one 120 s window; new chooser | Exp 7 |

**One thing to understand before reading Exp 1.** At 1 ms units, the rounding is
now *up*:
- ceil-cumulative deltas (#6) never round a budget down;
- the anchor is rounded up as well (#7).

Together these add up to about 2 ms of extra slack on top of S × prediction. So at
1 ms units, "S = 1.2" really means "1.2 × prediction plus up to ~2 ms".

At 0.1 ms units the rounding is ten times smaller, so S means what it says. The
0.1 ms curves are the honest picture of the slack trade-off. The 1 ms curves look
better than they are.

---

## 2. What got weaker, what got stronger

**Weaker (or retracted)**
1. **Detection of a slow link is much worse than claimed.**
   - Old: "S = 1.2, 23.2 % false positives, 100 % of 2× slowdowns detected" (H:303).
   - Now at S = 1.2 (1 ms units): 4.7 % of healthy packets flagged, counting every flag as v0
     did (0.7 % are deadline flags, the rest stale paths), but only 17 % of 1.5× and 72 % of
     2× slowdowns are detected (dev).
   - On Starlink, with the mean deadline false-positive rate held at ≤ 1 % (operating point
     S = 1.3), only 2.5 % of 1.5× and 23 % of 2× slowdowns are detected.
   - At 0.1 ms units no slack detects at least 1 % of 1.5× slowdowns with a mean FPR ≤ 1 %:
     no operating point.
2. **"S = 1.2 is optimal" is not a property of the protocol.** The best slack depends
   on:
   - the scoring rule;
   - the deadline unit;
   - the constellation (1.15 / 1.2 / 1.25 / 1.3 for Telesat / dev / Kuiper / Starlink
     at 1 ms units; none at 0.1 ms on any of the four).
3. **The ns-3 "S = 1.30" result is retracted.**
   - The old ns-3 score reported 100 / 57 / 8 / 12 % "detection" at S = 1.0–1.3 with
     **no fault at all**.
   - The "Python 1.2 vs ns-3 1.30 cross-validation" (H:391-396, H:661-662) compared two
     confounded numbers.
   - The fixed ns-3 program first still printed S = 1.30, chosen by Youden J at 7 % false
     alarms. With the Exp 1 rule (false alarms ≤ 1 %) it prints S = 1.5 for this 25 ms fault
     and no operating point for a 5 ms fault.
4. **The "deviation floor grows with scale" finding (1.2 % → 8.0 %) was a one-flow
   artefact.**
   - It measured a single flow in a single 120 s window.
   - Over three flows it is 5.3 % (dev; per flow 0 / 16 / 0 %) and 21.1 % (Starlink;
     17.2 / 16.8 / 29.2 %). With the flow as the unit, the 95 % intervals are [0, 28.3] and
     [3.6, 38.6]: three flows cannot show that the floor went up, only that it depends on the
     flow and the window.
   - A probe that undoes only the GMST fix gives back v0's 1.2 % exactly
     ([section 8](#8-experiment-6--cross-scale-validation-starlink-run-all-four-presets)).
   - The orbit-averaged number to quote is Exp 7's: 11.3 % [10.3, 12.3] at a 15 s interval.
5. **"A 3 s schedule interval removes stale paths" is wrong.**
   - Over a whole orbit, 3 s still leaves 1.65 % [1.46, 1.84] stale paths, and 2 s 0.85 %.
   - No interval longer than the simulation's 1 s topology step keeps stale paths within
     0.5 pp of zero. The chooser lands on 1 s only because a 1 s interval can never be stale
     in a simulation that moves the topology in 1 s steps: "≤ 1 s" is a limit of the
     simulation's resolution, not a measured optimum. (The v0 curve was noisy: 2 s → 1.1 %
     but 3 s → 0.3 %.)
6. **The geographic fallback fails more often than reported.**
   - With the simulator's 40-hop limit it fails to deliver 15.0 % (dev) and 37.3 %
     (Starlink) of satellite pairs.
   - Old figures: 6.0 % and 20.8 % "stuck".
7. **The fail-safe is far below an oracle upper bound.**
   - The new oracle reroute delivers 100 % at every failure rate. It is an upper bound, not a
     realistic baseline: it knows the exact set of failed links instantly, from anywhere, and
     only checks that a path exists at send time (the packet is not simulated in flight).
   - The fallback delivers 85.1 % (dev) and 70.5 % (Starlink) at 20 % failed links.
   - A realistic reroute baseline (replanning after a detection delay) is still to come.
8. **Exp 3's "flat 96 B/s" now comes with its data-plane bill.** At an assumed
   100 packets/s per flow, the T-CRH header on every packet costs 144,000–168,000 B/s.
   That is 28–33× the table-upload traffic at 15 s.
9. **Physics numbers shifted slightly**, because of the WGS84 altitude convention and
   correct city placement:
   - period 95.50 → 95.65 min;
   - Chennai→London at t = 0 on the dev shell: 34.05 → 37.66 ms.

**Stronger**
1. **Detection is now provably not inflated.**
   - The null-fault control attributes exactly 0 flags in every run: dev, Starlink,
     all four Exp 6 presets, and ns-3.
   - The old v0 metric, run on the new code with a 1.0001× "fault", still reports
     7.6 % (dev, 1 ms) and 15.5 % (dev, 0.1 ms) "detection" at S = 1.2. This shows
     what the counterfactual score removes.
2. **Fewer false alarms at 1 ms units.**
   - Like for like (every flag on the healthy network, stale paths included, as v0 counted):
     at S = 1.2, 23.2 % → 4.7 % (dev) and 32.2 % → 22.6 % (Starlink).
   - Deadline flags alone, which v0 never reported separately: 0.7 % (dev) and 4.4 %
     (Starlink). The rest are stale-path deviations (about 4 % dev, 18 % Starlink), which
     no slack can remove: that is Exp 7's knob. So on Starlink the like-for-like gain is
     much smaller than the deadline-only number suggests.
   - This comes from #6 (no budget rounded down) plus the extra rounding-up slack
     explained in section 1.
3. **The "deadline costs little on a healthy network" side improved.** Exp 4's
   no-fallback delivery with 0 % failed links rose from 72.4 % to 95.5 % (dev) and
   from 51.9 % to 77.4 % (Starlink): fewer false deviations.
4. **Header sizes are now right and shared with ns-3.**
   - CRH-16 is 24 B at 10 hops (not 32), so time costs +24 B.
   - The T-CRH bytes are the same as ns-3's (golden vectors).
5. **ns-3 under paired scoring** (means over RngRun 1-5, 1000 packets per S each).
   - S = 1.3 still catches the large 25 ms slowdown on every packet (100 % in every run),
     with 6.0 % [5.2, 6.7] false alarms.
   - S = 1.5 detection, 59.2 % [58.2, 60.1], matches theory (59.5 %).
6. **Exp 7's curve is now smooth and monotonic** with tight confidence intervals over 32
   windows. T-CRH control traffic is 46× below table upload at any equal interval.
7. **Everything is reproducible.**
   - Old figures regenerate byte-identical from the tag.
   - Every new number has a CSV and a manifest.

---

## 3. Experiment 1 — slack factor sweep

Files:
- `results/legacy-v0.9/{dev,starlink}/exp1_slack_sweep/`
- `exp1_slack_sweep.csv`: curves with confidence intervals
- `exp1_operating_points.csv`
- `exp1_runs.csv`: one row per run

**What changed in the method**

| | v0 | v0.9 |
|---|---|---|
| Runs | 1 flow (Chennai→London), 1 seed, 400 packets | 3 flows × 10 seeds × 400 packets, both deadline units |
| Fault | middle ISL of the t = 0 path | a random ISL of each run's t = 0 path |
| "False positive" | every deviation on the healthy network, stale paths included | **deadline flags only** on the healthy network. Stale paths are a separate column (they are Exp 7's knob) |
| "Detection" | flagged at all, among packets that crossed the slow link (bug #3) | flagged **with** the fault and **not without** it, among **all** packets that crossed it (also those the healthy run already flagged; `detection_among_unflagged` leaves those out, as ns-3 does) |
| Operating point | max (detection − FP) (Youden J) | **highest mean detection with mean FPR ≤ 1 %, counted only if that detection is ≥ 1 %**; otherwise none. Youden J is reported for continuity only |
| Confidence interval | none | Student-t over the 3 flows (each the mean of its 10 seeds), so 2 degrees of freedom: wide |

**Old vs new, dev shell** (detection = 1.5× slower link, among all packets that crossed it;
95 % intervals over the 3 flows)

| S | v0 FP | v0 detection | **new FPR, 1 ms** | **new detection, 1 ms** | **new FPR, 0.1 ms** | **new detection, 0.1 ms** |
|---|---|---|---|---|---|---|
| 1.0 | 88.2 % | 100.0 % | 95.3 % | 2.5 % | 100.0 % | 0.0 % |
| 1.1 | 73.0 % | 100.0 % | 5.6 % | 74.9 % [32.2, 100] | 41.7 % | 60.8 % |
| 1.2 | **23.2 %** | 94.0 % | **0.7 %** [0.4, 1.0] | **17.2 %** [0, 35.3] | 14.4 % [1.7, 27.0] | 33.6 % [0, 75.8] |
| 1.3 | 12.5 % | 14.2 % | 0.2 % | 4.4 % | 6.8 % | 14.3 % |
| 1.5 | 4.8 % | 4.8 % | 0.0 % | 0.3 % | 1.6 % | 1.9 % |
| 2.0 | 1.2 % | 1.2 % | 0.0 % | 0.0 % | 0.0 % | 0.0 % |

**Old vs new, Starlink**

| S | v0 FP | v0 detection | **new FPR, 1 ms** | **new detection, 1 ms** | **new FPR, 0.1 ms** | **new detection, 0.1 ms** |
|---|---|---|---|---|---|---|
| 1.0 | 100.0 % | 100.0 % | 93.7 % | 1.7 % | 96.3 % | 0.0 % |
| 1.1 | 44.5 % | 100.0 % | 23.8 % | 47.9 % [31.3, 64.4] | 54.7 % | 39.3 % |
| 1.2 | **32.2 %** | 99.6 % | **4.4 %** [0, 21.8] | **14.4 %** [0, 50.0] | 22.8 % [0, 63.3] | 26.2 % [0, 71.7] |
| 1.3 | 21.8 % | 25.8 % | 0.7 % [0, 2.9] | 2.5 % [0, 10.6] | 8.9 % | 8.5 % |
| 1.5 | 13.8 % | 14.6 % | 0.0 % | 0.1 % | 1.6 % | 0.9 % |
| 2.0 | 10.0 % | 10.0 % | 0.0 % | 0.0 % | 0.0 % | 0.0 % |

The v0 "FP" column counted every flag, stale paths included; the new FPR columns count
deadline flags only. The like-for-like v0.9 numbers (every flag) are in the headline table
below. The Starlink 1 ms detection at S = 1.0 moved from 2.1 % to 1.7 % in revision 2 because
it is now the mean of the per-flow means (some runs have no packet crossing the slow link).

**Headline numbers**

| Claim | Old (source) | New |
|---|---|---|
| Best S, dev | 1.2 (H:303) | **1 ms: S = 1.2** (detection 17.2 %, mean FPR 0.7 %). **0.1 ms: none**: the only slacks with mean FPR ≤ 1 % detect at most 0.08 % (S = 1.75), below the 1 % minimum. Youden J: 1.1 (1 ms), 1.15 (0.1 ms) |
| Best S, Starlink | 1.2 (H:313) | **1 ms: S = 1.3** (detection 2.5 %, mean FPR 0.7 %; the FPR interval reaches 2.9 %). **0.1 ms: none** (at most 0.04 %). Youden J: 1.1 (1 ms), 1.2 (0.1 ms) |
| FP at S = 1.2, dev | 23.2 % (H:303), every flag | **like for like (every flag, stale paths included): 4.7 %** (1 ms) / 17.7 % (0.1 ms). Deadline flags only: 0.7 % / 14.4 % |
| FP at S = 1.2, Starlink | 32.2 % (H:313), every flag | **like for like: 22.6 %** (1 ms) / 38.8 % (0.1 ms). Deadline flags only: 4.4 % / 22.8 % |
| 2× slowdowns detected at S = 1.2, dev | 100 % (H:303) | **71.8 % [9.0, 100]** (1 ms) / 72.4 % (0.1 ms) |
| 2× slowdowns detected at S = 1.2, Starlink | 100 % (H:313) | **51.6 % [0.8, 100]** (1 ms) / 51.0 % (0.1 ms). At the S = 1.3 operating point: 22.7 % [0, 62.1] |
| "Detection" of a 1.0001× (no) fault at S = 1.2, dev | 22.4 % (A:81, audit bench) | **0.0 %** (counterfactual). The old metric on the new code: 7.6 % (1 ms), 15.5 % (0.1 ms) |
| Null-fault (1.0×) attributed flags | not measured | **0** in every run (the run aborts otherwise) |

**Why it changed**
- **False positives fell at 1 ms units** mainly because of #6. v0 rounded each hop's
  budget to the nearest ms with banker's rounding, so many budgets ended up *below*
  S × prediction. At Starlink, 74.8 % of hops were rounded down at S = 1.2 (A:87).
  Now nothing is rounded down, and the rounded-up anchor (#7) adds slack too.
- **The 0.1 ms columns show the honest jitter-driven rate:** 14.4 % (dev) and 22.8 %
  (Starlink) at S = 1.2.
- **#1 (checking the deadline at the destination)** pushes the rate up a little. We did
  not measure it separately.
- **Detection fell for two kinds of reason.**
  - (a) The code and scenario fixes together: #6 (budgets are no longer secretly tighter
    than S × prediction, so a 1.5× link hides inside the budget more often), #7 (the anchor
    is rounded up), #9 and #10 (geometry), and the new scenario (3 flows instead of 1, a
    random ISL instead of the middle one).
  - (b) #3: flags that jitter would have caused anyway no longer count.
  - Example at dev S = 1.2 (1 ms): the old metric on the new code gives 24.8 %, the
    counterfactual 17.2 %. So (a), all of those changes together, explains most of the
    drop from v0's 94 % at S = 1.2. We did not run an ablation that changes only #6, so
    we cannot say how much of (a) is #6 alone.
  - (b) explains all of it at loose slack. There v0's "detection" simply equalled its
    false-positive rate (e.g. 4.8 % = 4.8 % at S = 1.5).
- **Why the detection curves are hump-shaped.** At very tight slack (S = 1.0)
  "detection" is near 0, because almost every packet is already flagged without the
  fault, so the fault adds nothing. `exp1_slack_sweep.csv` also has
  `detection_among_unflagged`, the rate among packets the healthy run did not flag.
  That is the ns-3 definition (section 10). At tight slack the two differ a lot: at
  S = 1.1 (1 ms) it is 84.3 % (dev) and 73.2 % (Starlink) against 74.9 % and 47.9 % in the
  tables above. Compare ns-3 detection with `detection_among_unflagged`, not with
  `detection`.
- **Averaging over three flows and ten seeds** replaces one flow and one seed. With the
  flow as the unit of analysis the confidence intervals are very wide (often ±20-50
  percentage points), because the result depends on the flow and on which link is
  degraded. Three flows show the direction of an effect, not its size.

---

## 4. Experiment 2 — header overhead (dev and Starlink; analytic, identical CSVs)

Files: `results/legacy-v0.9/{dev,starlink}/exp2_header_overhead/`.

| Quantity | Old (v0 printout / PNG) | New | Why |
|---|---|---|---|
| CRH-16 at 10 hops | 32 B | **24 B** | #5 (fixed part is 4 B, RFC 9631) |
| CRH-16 at 13 hops | 40 B | **32 B** | #5 |
| T-CRH at 10 / 13 hops | 48 / 56 B (H:304, H:314) | 48 / 56 B | unchanged; now from `chronoroute.proto.sizes`, byte-identical with ns-3 |
| Cost of adding time (T-CRH − CRH-16, 10 hops) | "+16 B" (PNG annotation, printout) | **+24 B** | #5 (the semester notes already say +24 at H:415-420 and H:377) |
| SRv6 SRH at 10 hops | 168 B | 168 B | — |
| T-CRH + HMAC at 10 hops | 88 B | 88 B | — |
| T-CRH with gateway encapsulation (+40 B IPv6) | — | **88 B** (new series) | critique #4: inserting at a gateway needs IPv6-in-IPv6 |
| T-CRH share of a 40 B payload packet | 37.5 % | 37.5 % | — |
| CRH-16 share of a 40 B payload packet | 28.6 % | **23.1 %** | #5 |
| T-CRH share of a 1400 B payload packet | 3.2 % | 3.2 % | — |
| Self-test text "CRH-16 = 28" | 28 | 24 | #17 |

---

## 5. Experiment 3 — control-plane cost (analytic model, still not a simulation)

Files: `results/legacy-v0.9/{dev,starlink}/exp3_control_plane/`. The figure and every
CSV row are now labelled "ANALYTIC MODEL (formula) — superseded by E3".

| Quantity | Old | New, dev run | New, Starlink run | Why |
|---|---|---|---|---|
| T-CRH header used in the formula | 48 B (fixed 10 hops) | 48 B (measured 9.50 hops) | **56 B** (measured 13.25 hops) | hops now measured on the active preset |
| T-CRH control traffic, 15 s refresh | 96 B/s (H:305, H:315) | 96 B/s | **112 B/s** | same |
| Saving vs table upload at 480 sats | 16× (H:305) | 16× | 14× | same |
| Saving vs table upload at 1584 sats | 53× (H:315) | 53× | **45×** | same |
| Saving vs link-state flooding at 1584 | 223,027× (H:315) | 223,027× | **191,166×** | same |
| Saving at 6400 sats | 213× (H:604-606) | 213× | 183× | same |
| "9× cheaper" (T-CRH at 3 s vs table upload at 15 s) | 560 vs 5,069 B/s (H:357-360) | **retired**: at the *same* 3 s interval, 480 vs 25,344 B/s = 53× | 560 vs 25,344 B/s = **45×** | one interval for every scheme |
| Per-packet T-CRH header bytes (30 flows × 100 packets/s, assumed) | not shown | **144,000 B/s** = 28.4× table upload at 15 s | **168,000 B/s** = 33.1× | header bytes shown as their own "data plane" series |

**What it means.**
- The *control-plane* ratio is a formula and barely moved. It is still "flat by
  construction" (A:95-102).
- The link-state baseline is still an N² re-flood strawman (H:626-628).
- The honest new information is that the bytes T-CRH saves in the control plane, it
  spends many times over in the data plane.

---

## 6. Experiment 4 — failure resilience

Files: `results/legacy-v0.9/{dev,starlink}/exp4_failure_resilience/`.

**Method changes:**
- 10 random failure draws, each with 3 flows; mean and t-CI over draws (was 5 pooled
  trials).
- Within a draw, all three methods see the same failures and packets.
- New **oracle reroute**: Dijkstra on the true, faulted graph at send time. This is an
  **upper bound**, not a realistic baseline: it has global, instantaneous knowledge of
  every failed link and only checks that a path exists when the packet is sent.
- Unit 1 ms, S = 1.2, as in v0.

**Dev (480 sats)**: delivery rate.

| ISLs failed | v0 with fallback | v0 without | **oracle** | **with fallback** | **without** | via fallback (v0 → new) |
|---|---|---|---|---|---|---|
| 0 % | 100.0 % | 72.4 % | 100 % | 100.0 % | **95.5 %** [95.2, 95.7] | 28.1 → 4.5 % |
| 1 % | 100.0 % | 68.9 % | 100 % | 100.0 % | 90.3 % | 31.6 → 9.7 % |
| 2 % | 100.0 % | 64.3 % | 100 % | 100.0 % | 81.2 % | 36.3 → 18.9 % |
| 5 % | 96.4 % | 36.3 % | 100 % | 96.7 % [89.1, 100] | 62.1 % | 59.9 → 34.6 % |
| 10 % | 96.4 % | 25.1 % | 100 % | 100.0 % | 38.6 % | 71.6 → 61.4 % |
| 15 % | 93.5 % | 19.1 % | 100 % | 97.7 % | 33.9 % | 74.1 → 63.8 % |
| 20 % | **87.4 %** (H:306) | **13.4 %** | **100 %** | **85.1 %** [71.7, 98.5] | **26.5 %** [8.9, 44.0] | 73.8 → 58.7 % |

**Starlink (1584 sats)**

| ISLs failed | v0 with fallback | v0 without | **oracle** | **with fallback** | **without** | via fallback (v0 → new) |
|---|---|---|---|---|---|---|
| 0 % | 96.7 % | 51.9 % | 100 % | 99.8 % | **77.4 %** [77.0, 77.8] | 43.9 → 22.4 % |
| 1 % | 96.6 % | 45.2 % | 100 % | 98.9 % | 67.6 % | 50.2 → 31.3 % |
| 2 % | 94.6 % | 39.3 % | 100 % | 98.9 % | 63.4 % | 54.4 → 35.5 % |
| 5 % | 95.4 % | 23.0 % | 100 % | 94.8 % | 40.8 % | 71.9 → 54.0 % |
| 10 % | 91.9 % | 13.7 % | 100 % | 87.9 % | 19.5 % | 78.0 → 68.4 % |
| 15 % | 81.6 % | 11.7 % | 100 % | 79.8 % | 13.4 % | 69.9 → 66.4 % |
| 20 % | **69.1 %** (H:316) | **7.3 %** | **100 %** | **70.5 %** [60.2, 80.7] | **10.2 %** [1.5, 18.8] | 61.9 → 60.3 % |

**Why it changed**
- **No-fallback delivery rose at low failure rates.** Healthy packets are falsely
  flagged far less often (#6). In v0, 28 % (dev) and 44 % (Starlink) of packets on an
  *intact* network went through the fallback.
- **The remaining 22 % on Starlink at 0 % failures** are mostly stale-path deviations
  (the 15 s schedule; see Exp 6/7), not deadline flags.
- **With-fallback delivery at 20 % failed links is about the same:** 85 vs 87 % on dev,
  70.5 vs 69.1 % on Starlink. The confidence intervals are now visible, and they are
  wide (±13 pp on dev).
- **The oracle upper bound reaches 100 % at every rate.** The fallback is a safety net,
  not close to optimal: 15 pp (dev) and 30 pp (Starlink) below that bound at 20 %. How
  a realistic reroute (replanning after a detection delay) compares is still open.
- **#2** let Exp 4 pass `failed_links` on unpruned graphs without hanging.
- **#15:** the ISL list is read at call time (`topology.isl_pairs()`), so the failure
  draws always come from the active constellation's links.

---

## 7. Experiment 5 — fallback path stretch

Files: `results/legacy-v0.9/{dev,starlink}/exp5_path_stretch/`.

| Quantity | Old dev | **New dev** | Old Starlink | **New Starlink** |
|---|---|---|---|---|
| Satellite pairs tested | 398 | 399 | 400 | 400 |
| **Not delivered by greedy** | 6.0 % "stuck" (H:307) | **15.0 %**: 2.8 % local minimum + 12.3 % hit the 40-hop limit | 20.8 % (H:317) | **37.3 %**: 1.0 % local minimum + 36.3 % hit the 40-hop limit |
| Delivery rate (Wilson 95 % CI) | 94.0 % | 85.0 % [81.1, 88.1] | 79.2 % | 62.7 % [57.9, 67.3] |
| "Already optimal" as v0 counted it = no more hops than the shortest-latency path (of delivered) | 46.0 % (H:307) | 48.4 % | 32.2 % | 41.0 % |
| **Latency-optimal**: greedy path as fast as the shortest path (of delivered) | not measured | **9.7 %** | not measured | **7.2 %** |
| Mean latency stretch, **delivered pairs only** | 1.77× (H:307) | 1.56× [1.48, 1.65] | 1.64× (H:317) | 1.45× [1.37, 1.53] |
| Mean hop stretch, delivered only | 1.64× | 1.44× | 1.49× | 1.31× |
| 95th percentile, delivered only | 4.25× | 3.33× | 2.84× | 2.38× |
| Worst case, delivered only | 7.44× (H:458) | 4.97× | 18.32× (H:458) | 7.30× |
| **Effective** latency stretch (a loss counts as infinite): median | — | 1.37× | — | 1.74× |
| Effective stretch: 90th / 95th / 99th percentile | — | infinite | — | infinite |

**Why it changed:**
- **#16, the hop limit.** v0's Exp 5 used its own 60-hop limit, while the simulator
  uses 40. It now uses the simulator's constant and greedy function. Pairs that needed
  41–59 greedy hops were "delivered with a big stretch" in v0 and are now losses.
- **Losses are now counted.** That is also why the delivered-only stretch went *down*:
  the worst detours are now in the loss column. This is the survivorship bias the
  audit flagged (A:27); we did not separately measure how much each part contributes.
- **Pairs are drawn across the whole 120 s window**, not only the t = 0 graph.
- **The seam (#10) and frame (#9) fixes** change the mesh the greedy walk sees.
- **"Already optimal" was a hop count** (revision 2). It counted a greedy path as optimal
  when it had no more hops than the shortest-latency path, which includes paths with fewer
  hops and paths up to 1.20× (dev) / 1.48× (Starlink) slower. Only 9.7 % / 7.2 % of
  delivered greedy paths are as fast as the shortest path.

**The honest negative result gets stronger.** Greedy geographic forwarding fails for
more than a third of Starlink satellite pairs within a 40-hop budget. GPSR-style
perimeter routing (H:503-505) is now more important, not less.

---

## 8. Experiment 6 — cross-scale validation (Starlink run, all four presets)

Files: `results/legacy-v0.9/starlink/exp6_scale_validation/`.

**Method:**
- Experiment 1's counterfactual scoring is applied to each preset: 3 flows × 10 seeds,
  both units.
- Stale-path floor = link_failed deviations at S = 5, 1 ms, averaged over the 3 flows.
  v0 used Chennai→London only.
- Means and 95 % intervals over the 3 flows (each the mean of its 10 seeds).

| Constellation | Mean hops (old → new) | Max hops | Latency ms | T-CRH | CRH-16 bar | Best S, old | **Best S, new (1 ms / 0.1 ms)** | Youden J, new (1 ms / 0.1 ms) | **Stale-path floor** (old → new) |
|---|---|---|---|---|---|---|---|---|---|
| Telesat (351) | 9.7 → 10.0 | 15 → 14 | 71.6 → 71.2 | 48 B | 32 → 24 B | 1.1 | **1.15 / none** | 1.1 / 1.1 | 0.0 % → 0.0 % (0 / 0 / 0) |
| Dev (480) | 9.7 → 9.5 | 12 → 12 | 60.6 → 60.4 | 48 B | 32 → 24 B | 1.2 | **1.2 / none** | 1.1 / 1.15 | 1.2 % → **5.3 %** [0, 28.3] (0 / 16 / 0) |
| Kuiper (1156) | 14.5 → 14.5 | 18 → 18 | 63.5 → 63.5 | 56 B | 40 → 32 B | 1.1 | **1.25 / none** | 1.1 / 1.2 | 4.0 % → **6.5 %** [0, 21.7] (1.2 / 13.2 / 5.2) |
| Starlink (1584) | 13.3 → 13.3 | 20 → 20 | 61.9 → 62.0 | 56 B | 40 → 32 B | 1.2 | **1.3 / none** | 1.1 / 1.2 | 8.0 % → **21.1 %** [3.6, 38.6] (17.2 / 16.8 / 29.2) |

Old values: H:336-341 and the re-run v0 printout. "None" means no slack in this sweep has a
mean FPR ≤ 1 % and a mean detection of at least 1 % (revision 2; the first v0.9 run listed
Telesat 0.1 ms as "1.5", where detection was 0.08 %). Exp 1 and Exp 6 use the same rule. The
per-flow floors are in brackets after the interval, in the order Chennai→London,
New York→Sydney, São Paulo→Tokyo.

**Why it changed**
- **Best S.** The v0 band "1.1–1.2" (H:318, H:343-346) came from Youden J on the
  confounded metric. With honest scoring:
  - Youden J gives 1.1 everywhere at 1 ms;
  - the mean FPR ≤ 1 % rule gives 1.15–1.3 at 1 ms and nothing usable at 0.1 ms.

  So the "narrow band" is a property of the scoring rule and the deadline unit, not
  of the protocol. (With three flows, the per-preset curves behind these choices have wide
  intervals: the choices are point estimates.)
- **CRH-16 bars:** #5.
- **Hops and latency:** small shifts from the frame and seam fixes (#9, #10).
- **The floor: correct city placement (#9) plus three flows instead of one.** This
  attribution was checked with a probe (`/tmp/cr-p1/runner/floor_probe.py`).
  - The probe runs the v0.9 code twice per flow, at S = 5 with 3 seeds:
    once with the true GMST, and once with the GMST at the epoch removed (v0's
    geometry).
  - Results:

    | Flow | True GMST | v0 geometry |
    |---|---|---|
    | Dev Chennai→London | 0.0 % | **1.2 %** (= v0's dev floor) |
    | Dev New York→Sydney | 16.0 % | 4.0 % |
    | Dev São Paulo→Tokyo | 0.0 % | 8.0 % |
    | Starlink Chennai→London | 17.2 % | 9.2 % (v0: 8.0 %) |
    | Starlink New York→Sydney | 16.8 % | 35.6 % |
    | Starlink São Paulo→Tokyo | 29.2 % | 0.0 % |

  - So the floor is set by which ground-satellite handovers happen during *this
    particular* 120 s window for *this particular* flow. It is not a scale effect.
  - It is the same in every seed of a flow, so the first v0.9 interval, which treated the
    30 flow × seed runs as independent ([2.5, 8.2] dev, [18.9, 23.3] Starlink), was far too
    narrow. Over the 3 flows it is [0, 28.3] and [3.6, 38.6]: the old-vs-new difference
    (1.2 → 5.3 %, 8.0 → 21.1 %) cannot be called real on three flows.
  - The orbit-averaged number to quote is Exp 7's: 11.3 % [10.3, 12.3] at the 15 s
    interval on Starlink.

---

## 9. Experiment 7 — schedule interval (Starlink)

Files: `results/legacy-v0.9/starlink/exp7_schedule_interval/`.

**Method:**
- 32 windows of 180 s spread over one orbit (95.6 min); mean and t-CI over windows.
  v0 used one 120 s window from t = 0.
- Stale-path rate comes from a probe run with deadlines effectively off (S = 5).
- Deadline misses: S = 1.2 at 0.1 ms units.
- Chooser: the longest interval whose stale-path rate is within 0.5 pp of the best,
  with 95 % confidence. If that is the simulation step itself (1 s), the result is
  reported as resolution-limited (revision 2).

| Interval | Stale paths, old | **Stale paths, new** | Control plane, old → new | Missed deadline at S = 1.2, old (1 ms) → new (0.1 ms) |
|---|---|---|---|---|
| 1 s | 0.0 % | **0.00 %** [0, 0] | 1680 → 1646 B/s | 49.4 % → 29.2 % |
| 2 s | 1.1 % | 0.85 % [0.72, 0.97] | 840 → 823 | 47.6 → 29.0 % |
| **3 s** | **0.3 %** (H:353) | **1.65 %** [1.46, 1.84] | 560 → 549 | 47.8 → 28.8 % |
| 5 s | 1.1 % | 3.54 % [3.28, 3.80] | 336 → 329 | 46.8 → 28.5 % |
| 10 s | 4.6 % | 7.76 % | 168 → 165 | 40.9 → 27.5 % |
| 15 s | 8.9 % (H:354) | 11.29 % [10.27, 12.30] | 112 → 110 | 38.2 → 26.9 % |
| 20 s | 6.9 % | 15.94 % | 84 → 82 | 35.5 → 26.2 % |
| 30 s | 18.4 % | 22.53 % | 56 → 55 | 30.3 → 25.1 % |
| 45 s | 21.1 % | 34.61 % | 37 → 37 | 28.1 → 23.9 % |
| 60 s | 20.8 % (H:355) | 45.17 % [42.22, 48.12] | 28 → 27 | 26.1 → 23.4 % |
| **Recommended** | **3 s at 560 B/s** (H:319, H:357-360) | **None longer than the 1 s simulation step**: every interval above 1 s is more than 0.5 pp worse. "≤ 1 s" (1646 B/s at 1 s; table upload at the same 1 s costs 76,032 B/s, 46×) is a limit of the simulation's resolution, not a measured optimum | | |

**Why it changed**
- **The old curve was noise from one window** (A:103-107): 2 s → 1.1 % but
  3 s → 0.3 %, and v0's chooser took the longest "safe" interval. Averaged over an
  orbit the curve rises smoothly, and no interval above 1 s is within 0.5 pp of zero.
- **Long intervals got much worse** (60 s: 20.8 → 45.2 %). The v0 window was 120 s,
  so the 60 s interval had only two epochs. Averaged over the orbit, a 60 s-old path is
  stale far more often. Correct city placement (#9) also changes which handovers
  happen.
- **Missed deadlines are lower** because of #6, and because the new column uses
  0.1 ms units. About a quarter of healthy packets still miss an S = 1.2 deadline
  here, so S = 1.2 at 0.1 ms is not a usable operating point (see Exp 1).
- **The control plane is slightly lower** because it now uses the measured mean
  header (54.9 B) instead of a fixed 56 B.
- **The 1 s "choice" is set by the simulation, not by the data.** The topology only
  changes at 1 s steps, so a 1 s interval is never stale here (all 96 window × flow rows
  are 0), and any longer interval with a non-zero rate fails the 0.5 pp test against
  exactly 0. What the data do say: already at 2 s, 0.85 % [0.72, 0.97] of packets meet a
  stale path. How short the interval must really be needs a sub-second topology step (the
  new campaign).

---

## 10. ns-3 numbers (re-scored; program `ns3/scratch/tcrh-experiment.cc`)

All files, with a manifest, are in `results/legacy-v0.9/ns3/tcrh_sweep/`:
- `tcrh_sweep_v09*.csv`, `tcrh_sweep_v09_runs1-5_summary.csv` and `ns3_rescore_v09.md`;
- `fig1_tcrh_size_v09.png`, `fig2_tcrh_sweep_v09.png`;
- the old `v0_tcrh_sweep.csv`.

Since revision 2 the programs are in this repository (`ns3/scratch/`, linked into the ns-3
tree by `tools/ns3-sync.sh`), and `make ns3-legacy` regenerates every file and the manifest
(byte-identical CSVs). The manifest records this repository's commit; the ns-3 base
(ns-3.44 at 43dce67 plus the Assessment 6-8 snapshot 6314c8a) is recorded separately in it.
Since revision 3 this works on any clean ns-3.44 tree (recipe in `README.md`, "A fresh ns-3
tree"). The old `v0_tcrh_sweep.csv` now comes from `ns3/legacy/` in this repository, not from
commit 6314c8a, which exists only in the author's own ns-3 tree.

**Slack sweep, fault = link n3–n4 slowed 20 → 45 ms.** New numbers: mean over RngRun 1–5
(1000 packets per S each) with a Student-t 95 % interval over the five runs. Detection here
is taken over the packets the healthy network did **not** flag (Python's
`detection_among_unflagged`, not its `detection`).

| S | Old false alarms (60 pkts) | Old "detection" | **New false alarms** | **New detection (paired, among unflagged)** |
|---|---|---|---|---|
| 1.0 | 100 % | 100 % | 100 % | undefined (every packet already flagged) |
| 1.1 | 60.0 % | 100 % | 70.2 % [68.0, 72.3] | 100 % in every run |
| 1.2 | 18.3 % | 100 % | 21.6 % [20.2, 23.0] | 100 % in every run |
| **1.3** | **5.0 %** (H:387) | **100 %** | **6.0 %** [5.2, 6.7] | **100 %** in every run |
| 1.5 | 1.7 % | 53.3 % | 0.64 % [0.07, 1.21] | 59.2 % [58.2, 60.1] (theory 59.5 %) |
| 1.75 | 0 % | 0 % | 0.06 % [0, 0.17] | 0.3 % [0.05, 0.55] |
| 2.0–3.0 | 0 % | 0 % | ≤ 0.02 % | 0 % |

**Operating point.** With the Exp 1 rule (false alarms ≤ 1 %, detection ≥ 1 %) the program
prints S = 1.5 for this 25 ms fault (RngRun 1: detection 57.9 %, false alarms 0.7 %) and
"No operating point" for the 5 ms fault and for the null fault. It prints Youden J (S = 1.30)
only as "for continuity with Assessment 8, NOT a recommendation". Note that the rule limits
the mean: at S = 1.5 one of the five runs had 1.4 % false alarms.

**Supporting runs**
- **RngRun 1 alone** (`tcrh_sweep_v09.csv`): S = 1.3 gives 7.0 % false alarms, with a
  per-packet Wilson interval [5.6, 8.8]. That interval describes one run only (it does not
  contain run 5's 5.5 %); the five-run interval above is the one to quote.
- **Smaller fault (20 → 25 ms):** detection is 99.3 % at S = 1.1, 27.1 % [24.1, 30.3]
  at 1.2, 2.3 % [1.5, 3.4] at 1.3, and 0 % at ≥ 1.5.
- **Null fault, new paired score (20 → 20 ms):** 0 detections at every S, and the
  null-fault network reproduces the healthy one packet for packet.
- **Null fault, OLD program:** it reports 100 / 56.7 / 8.3 / 11.7 % "detection" at
  S = 1.0 / 1.1 / 1.2 / 1.3, and still prints "Best operating point: S = 1.30". This
  is bug #21. (Regenerated by the original program, kept as
  `ns3/scratch/tcrh-experiment-a8.cc`.)

**Why it changed**
- **#21 (paired score).** The old program counted every flag in the degraded phase
  as a detection, including jitter flags on packets that were never paired with a
  healthy twin.
- **#18 (exact arithmetic).** Flooring the clock to whole ms let packets up to
  0.999 ms late pass. Fixing this raised tight-slack false alarms (S = 1.1:
  60 → 72 %).
- **Still 100 % detection at S ≤ 1.3** because the toy fault adds 25 ms to one 20 ms
  hop: every unflagged packet is pushed past its deadline. With a 5 ms fault, S = 1.3
  catches 2.3 %.
- **There is no single best S.** The rule picks S = 1.5 for a 25 ms fault and nothing
  for a 5 ms fault.

**Other ns-3 outputs**
- T-CRH and CRH-16 header sizes: identical (`tcrh_sizes_v09.csv` = `tcrh_sizes.csv`).
  CRH-16 24 B, T-CRH 48 B, SRv6 168 B at 10 SIDs (H:366, H:377).
- CRH forwarding test (#20): the path check now records the node that actually
  received each packet, so a mis-wired path can fail. Latencies are exact instead of
  floored: 10 → 10.2208 ms and 25 → 25.584 ms (H:367-368).
- Dumbbell/bufferbloat (#19): every number is unchanged. The column is renamed
  `mean_one_way_delay_ms`: the 192 → 377 ms figures (H:402-404) are **one-way delay,
  not RTT**.

---

## 11. Physics and validation numbers quoted in the semester notes

| Quantity | Old (H:line) | New | Why |
|---|---|---|---|
| Orbital period at "550 km" | 95.50 min (H:229) | **95.65 min** | altitude now measured above the WGS84 equatorial radius: a = 6378.137 + 550 instead of 6371 + 550 (#9, geo convention) |
| Orbital speed | 7.59 km/s (H:230) | 7.585 km/s (√(μ/a)), still 7.59 rounded | same. Note: `constellation.py`'s self-test now prints "7.29 km/s", because positions are Earth-fixed and it measures speed over the rotating ground. Do not quote that line as orbital speed |
| Chennai→London at t = 0, dev shell | 6 hops, 34.05 ms (H:231) | **6 hops, 37.66 ms** | #9: cities are now where they really are relative to the satellites. GMST at the epoch is 349.04°; the geo owner measured that v0 had Chennai 1186 km and London 759 km off |
| Chennai→London at t = 0, Starlink | — | 7 hops, 35.55 ms | — |
| Great-circle light floor | 27.4 ms (H:231) | unchanged | city coordinates unchanged |
| numpy fast path | 2.3×, max difference 8.88e-16 ms (H:256-257) | **1.9×, max difference 0.00e+00 ms** (`scale.py` self-check) | numpy path now mirrors the pure-Python build exactly (80 km rule, ellipsoid "up") |
| STARLINK-1007 altitude | 550.6 km propagated (H:264); 554.4 km from mean motion (v0 printout) | **543.4 km** propagated; **547.2 km** from mean motion | #13: altitude above 6378.137, not 6371 |
| Real-fleet shell (±40 km of 550 km, 53°) | 157 satellites, mean 535.7 km, 95.21 min (H:268-270) | **134 satellites, mean 532.5 km, 95.29 min** | same altitude convention (fewer satellites fall in the band) |

---

## 12. Claims to retire

Each claim has a suggested replacement in plain words.

1. **"Optimal S = 1.2"** (H:303, H:313, H:328, H:357) and **"S = 1.2 still optimal at
   Starlink"**.
   → "With the mean deadline false-alarm rate held at ≤ 1 %, the best slack is S = 1.2
   (dev) or S = 1.3 (Starlink) at 1 ms units. There it catches 17 % / 2.5 % of 1.5×
   slowdowns, with very wide intervals over three flows. At 0.1 ms units no slack is
   useful under that constraint."
2. **"100 % of 2× degradations detected"** (H:303, H:313).
   → "72 % (dev) / 52 % (Starlink) of 2× slowdowns at S = 1.2, 1 ms units."
3. **"23.2 % / 32.2 % false positives at S = 1.2"** (H:303, H:313). Those mixed
   stale-path deviations with rounded-down budgets.
   → Like for like (every flag): 4.7 % (dev) and 22.6 % (Starlink) at S = 1.2, 1 ms.
   Better, quote the deadline FPR (0.7 % / 4.4 %) and the stale-path rate separately.
4. **ns-3 "S = 1.30: 5 % false alarms, 100 % detection" as the recommended slack**
   (H:387). Also:
   - **"two independent implementations landing one step apart"** (H:391-396,
     H:579-583);
   - **"narrow 1.1–1.3 band across two simulators"** (H:661-662).

   → "Under paired scoring, ns-3 detects a 25 ms slowdown at S ≤ 1.3 with 6 % false
   alarms (mean of 5 runs), but only 2.3 % of a 5 ms slowdown. With false alarms ≤ 1 %
   the choice is S = 1.5 for the 25 ms fault and nothing for the 5 ms fault: the slack
   must be chosen per fault size."
5. **"Optimum in a narrow 1.1–1.2 band across four constellations"** (H:318,
   H:343-346).
6. **"CRH-16 = 32 B at 10 hops; time costs +16 B"** (v0 Exp 2 figure and printout) and
   the self-test text "CRH-16 = 28".
   → 24 B and +24 B.
7. **"Deviation floor 1.2 % → 8.0 % as scale grows — a new failure mode"** (H:329,
   H:597-601).
   → "Stale-path deviations depend on the flow and the time window; three flows cannot
   show a scale effect. Orbit-averaged on Starlink: 11.3 % at a 15 s interval, 1.65 % at
   3 s."
8. **"Recompute every 3 s: removes stale-path failures at 560 B/s, 9× cheaper than
   table upload"** (H:319, H:357-360).
   → "At 3 s, 1.65 % of packets still hit a stale path, and 0.85 % at 2 s. In a
   simulation with 1 s topology steps no longer interval is within 0.5 pp of zero; how
   short it must be needs a finer simulation. T-CRH control traffic is 46× below table
   upload at the same interval."
9. **"Flat 96 B/s; 16× / 53× / 213× less than table upload; 223,000× less than
   link-state"** (H:305, H:315, H:604-606) **when quoted without** these three caveats:
   - it is an analytic formula;
   - the per-packet header costs 144–168 kB/s at an assumed 100 packets/s per flow;
   - Starlink paths need the 56 B header (45× at 1584 satellites).
10. **"87.4 % delivery at 20 % failure vs 13.4 % without the fail-safe — the fail-safe
    is what makes the design usable"** (H:306, H:316).
    → "85 % (dev) / 70 % (Starlink) at 20 % failed links, vs 26 % / 10 % without any
    reaction and 100 % for an oracle with instant global knowledge of the failures (an
    upper bound)."
11. **"1.77× mean stretch, 6.0 % stuck" and "20.8 % stuck at Starlink"** (H:307, H:317,
    H:331, H:456-460, H:589).
    → "Greedy fails to deliver 15 % (dev) / 37 % (Starlink) of satellite pairs within
    40 hops. When it delivers, it costs 1.56× / 1.45× latency."
12. **"Orbital period 95.50 min" and "Chennai→London 34.05 ms over 6 hops"** as
    validation checks (H:229-232, H:575-577).
    → 95.65 min and 37.66 ms over 6 hops at t = 0 on the dev shell.
13. **"Python and ns-3 headers are byte-exact"** for the *old* Python code. It was not
    wire-compatible (SID order, #4). It is now: both print
    `1102fd0300030000000003e8000708000307000206000000`.
14. **"46 % of greedy paths are already optimal"** (H:307) and the v0.9 first-run "48.4 % /
    41.0 % already optimal". That was a hop count.
    → "9.7 % (dev) / 7.2 % (Starlink) of the paths greedy delivers are as fast as the
    shortest path; 48 % / 41 % have no more hops than it."
15. **"S = 1.75 at 0.1 ms units"** and **"Telesat S = 1.5 at 0.1 ms"** (first v0.9 run,
    0.04-0.08 % detection) and the narrow v0.9 intervals on the stale-path floor
    ("5.3 % [2.5, 8.2]", "21.1 % [18.9, 23.3]").
    → "No operating point at 0.1 ms units on any constellation." Floors: see claim 7.

---

## 13. Known limitations of this re-run

- **`dirty: true` in every manifest.** The plan's acceptance check wants `dirty: false`.
  That needs the Phase 1 code committed and these two commands re-run (about 7.4 min
  in total). The numbers will not change; only the recorded commit will.
- **The ns-3 manifest** now records this repository's commit (dirty until the Phase 1
  code is committed) and the ns-3 base separately; `make ns3-legacy` reproduces every
  file. The edits to the three scratch programs also still need a commit in
  `~/ns-3-dev` if that tree is to be kept in step; this repository is now their source.
- **Scope of these runs.** These are still the legacy experiments:
  - a synthetic 2020 FCC Starlink shell, not the 2026 fleet;
  - a 120 s scenario window (except Exp 7);
  - "slow link" modelled as a delay multiplier;
  - i.i.d. exponential queueing;
  - no event-level detector: detection is scored per packet. The plan's "event-level
    detection on matched packets" for bug #3 (an event detector such as k flags at one hop
    within W, false events per hour from the null-fault arm, an event ROC) is deferred to
    experiment E1 of the new campaign. Bug #3 is closed here by the counterfactual
    per-packet score plus the null-fault control.

  Read them as corrected v0 results, not as the new campaign (E1–E16).
- **Exp 1/6 confidence intervals are wide** (often ±20-50 pp), because the flow is the
  unit of analysis and there are only three flows; the outcome also depends on which ISL is
  degraded. More flows (not more seeds) would narrow them.
- **The FPR limit is on the mean.** At the chosen Starlink point (S = 1.3, 1 ms) the mean
  FPR is 0.7 % but its interval over flows reaches 2.9 %.
- **Exp 3 is still a formula.** Exp 4's "with fallback" values are not monotone in the
  failure rate (e.g. dev 96.7 % at 5 % vs 100 % at 10 %). The failure draws are
  nested and the confidence intervals overlap.
- **The Exp 6 floor attribution probe** used 3 seeds per flow (not 10) and only
  removed the epoch GMST. It does not undo the ellipsoid or seam fixes.
- **Not every contribution was isolated.** The size of each individual fix's
  contribution was not measured, except where stated: the old metric on new code in
  Exp 1, and the GMST probe in Exp 6.
- **Reproducing v0's Starlink run needs a source path containing "chronoroute".**
  v0's `scale.py` only rebinds modules under such a path. From another folder it
  silently keeps the dev ISL list and crashes in Exp 1.

---

## 14. Reproduce

```
cd ~/chronoroute && venv/bin/python -B -m pytest sim/tests           # 361 passed (revision 3)
cd ~/chronoroute/sim/legacy
../../venv/bin/python -B run_all.py                 # dev, Exp 1-5   (86.9 s here)
../../venv/bin/python -B run_scaled.py starlink     # Exp 1-7        (357.1 s here)
cd ~/chronoroute && make ns3-legacy                 # ns-3 sweep, every file (~45 s + build)
venv/bin/python -B ns3/contrib/chronoroute/test/scratch_regressions.py   # ns-3 bugs #18-#21
```

Revision 2 re-ran only the affected experiments: `run_all.py exp1_slack_sweep
exp5_path_stretch` (84 s) and `run_scaled.py starlink exp1_slack_sweep exp5_path_stretch
exp7_schedule_interval exp6_scale_validation` (359 s). The other folders are from the first
v0.9 run; nothing they depend on changed. Revision 3 re-ran only `run_scaled.py starlink
exp6_scale_validation` (95 s; figure layout only, CSVs byte-identical) and `make ns3-legacy`
(43 s; every file byte-identical except the manifest).

Every folder's `manifest.json` lists the command, config, seeds, library versions and
the sha256 of each output. Check one with:

```
venv/bin/python -B -c "from chronoroute.provenance import validate_manifest as v; v('results/legacy-v0.9/dev/exp1_slack_sweep')"
```

---

## 15. 2026-10-12 review of the campaign report

An independent review of the campaign report (`docs/report/README.md`) found that every
copied number was correct but several interpretations were too soft or wrong. No experiment
was rerun for these corrections apart from the E0 and E2 re-runs listed first, which were
made before the review closed. Every number in the report still comes from a manifested
result file through the claims ledger (`docs/claims.md`, `docs/report/claims.json`).

**E0 re-run (`results/E00/20261011T214507Z` replaces `results/E00/20261011T100448Z`).**
- The old `path_great_circle` check counted 0.5 ms of processing per link on the path side,
  so it was far weaker than the preregistered great-circle light-time bound. It now compares
  propagation only. Smallest margin: C5 3091493.1 ns → 1591493.1 ns, C2 6509144.1 ns →
  3641655.5 ns; still 0 violations.
- `gsl_elevation` now checks every visible ground-link candidate (C5 64908 → 238195 checks,
  C2 64908 → 173144). New row `gsl_visibility_complete` (16227 checks per shell).
- `wire_capture_bytes` now compares the frame bytes as tshark itself reads them; before,
  Python re-read its own pcap. New row `wire_golden_fixed` compares the 70 golden vectors with
  their fixed expected values.
- The report now says which rows are external references (orbit rows, browser, ns-3,
  Wireshark fields, fixed golden vectors) and which are self-consistency or model invariants
  (`wire_python`, the geometry rows); that `isl_polar_cutoff` cannot fail on these shells
  (highest latitude about 53.3 degrees against the 70 degree cutoff); and that the 138.07 km
  grazing figure is a certified lower bound, not the exact minimum height.
- Ledger labels of the E0 violation counts were DERIVED; they now equal the CSV row's own
  label (REAL or MODELLED), as for the other columns of that row.

**E2 re-run (`results/E02/20261011T214624Z-confirmatory` replaces
`results/E02/20261011T175659Z-confirmatory`).** Same numbers, repository-relative paths, and
the frame table is now `capture_frames.csv.gz`. The report table gains the 5 and 7 entry rows,
where CRH-32 is smaller than T-CRH, and the text states the full crossover from `verdict.json`:
CRH-32 smaller at 1, 2, 3, 5 and 7 entries; equal at 4, 6, 8-11, 13 and 15; larger at 12, 14
and 16-40.

**E1 interpretation (numbers unchanged).**
- The report used "boundary" for the rate cut that the preregistration calls *nominal*
  (factor 0.3, run at the first, middle and last path thirds). It now uses the registered name.
- A one-line verdict was added: the E1 hypothesis is not supported for the nominal rate cut and
  the added-delay family, and is supported only for the strong rate cut (0.2) and some ARQ
  cells. The selected rule (S = 1.5) detects 0 of 36 runs at `rate-0.3-middle` in both shells,
  9 of 36 at C5 `rate-0.3-first`, and at most 3 of 36 at any added delay in C5 (0 in C2),
  including 4 ms. A new table shows its detection for every registered condition next to LQ.
- Why: S = 1.5 leaves several milliseconds of spare time mid-path. Looser rules see these
  faults only above the registered false-alarm limit: S = 1.1 detects the 4 ms delay in every
  run and S = 1.25 in about half, at pooled clean FPR 0.175 and 0.044 in C5.
- Wins, ties and losses per comparator are now stated. Wins against LS-H and CRH-16 hold by
  construction (they detect nothing); E2E is never significantly better but runs with no clean
  false flags, so it is not false-alarm matched; LQ never loses significantly to ChronoRoute and
  wins at every nominal rate-cut cell and most ARQ cells. All registered material losses and
  point disadvantages in `verdict.json` are against LQ or LS-D.
- **LS-D comparator flaw.** The LS-D model used for the registered run reads the exact injected
  fault delay and the expected ARQ delay, re-advertises any nonzero change and is scored
  against a twin full of queue-noise advertisements (about 23183 false events per hour in C5).
  In C2 its detection is identical for 0.25 ms and 4 ms delays. The report keeps the registered LS-D
  numbers but states that the LS-D material losses and the ChronoRoute wins against LS-D are not
  valid evidence about slowness detection; the LQ losses are robust.
- Intervals: the representative contrast table showed bootstrap intervals for detection
  differences. The paired Student-t interval, which the preregistration makes primary for
  scheme differences, is now shown first and labelled; the run-bootstrap interval is labelled
  (it stays primary for restricted delay). Zero-width t intervals for all-0/all-1 endpoints
  are explained.
- p-values recorded as exactly 0 (zero-variance differences or numerical cancellation) are no
  longer printed; the report says they are below the numerical resolution of the computation.

**E4 interpretation (numbers unchanged).**
- The blackhole claim is qualified: the frozen metric does not count losses of fallback
  packets to the hop limit or loops. The report now shows the counted blackhole losses, packets
  sent and delivered and PDR. Example: C2 `link-B` visited fallback has blackhole 0 with 0
  counted losses but loses 1068 packets (1038 at the hop limit), PDR 0.995056, against LS-H's
  0.998704.
- The paired blackhole difference against continue now shows the paired t interval
  [-1.921, -0.571] s and labels the earlier interval [-1.866, -0.692] s as run-bootstrap.
- The tail sentence was wrong: the registered hypothesis was *no material effective-tail
  penalty relative to SNAP or LS-H*, not a tail advantage. It is not supported against LS-H:
  the paired tail-failure indicator (visited minus LS-H) excludes zero in C5 `link-B`
  0.167 [0.039, 0.295], `node-A` 0.111 [0.003, 0.219] and `node-B` 0.139 [0.020, 0.258]. The
  empty list of tail material losses is empty by construction (the rule needs a finite ratio).
- TTM is censored for every visited-fallback outage by construction; this is now stated.
- Recovery disclosure: the simulations ran at commit `b805d2d`; the first collection crashed
  writing the new tail-failure columns, and the tables were re-collected at `a18cffb`
  without rerunning any simulation (`recovery.json`, `runtime.json`).

**E16 interpretation (numbers unchanged).** The report said per-packet records matched
"losses"; no packet was lost in any run on either engine (PDR 1 and FPR 0 everywhere). The PDR
and FPR equivalence results are therefore at the boundary and uninformative, and the TOST is
degenerate (all paired differences exactly 0) because both engines replay the same send lists,
a common-random-numbers design declared in the preregistration. The agreement covers delivery,
queueing and deadline flags, not loss paths. `docs/course-milestone.md` now notes the four
`packets.csv` columns (`tx_ns`, `wait_ns`, `tx_loss_at`, `link_down_at`) that the current ns-3
program appends; the original 26 columns are unchanged.

**Abstract, discussion, limitations and conclusion** were rewritten to match the points above.

**Related work and references.** The report wrongly marked CRH-20, SRTSN, gray failure, IOAM
and TVR as unverified. They are now cited from primary sources: the Deterministic Routing
Header draft (draft-pb-6man-deterministic-crh-00, the "CRH-20" of the task guide),
draft-stein-srtsn-01, Huang et al. (HotOS 2017), RFC 9197 and RFC 9657, each with a sentence
on how T-CRH differs (T-CRH carries cumulative deadlines to *detect* deviation; the drafts use
per-hop timing to *schedule*). References are in IEEE style with authors and dates. CGREB could
not be identified and stays marked UNVERIFIED.

**Checking test.** `sim/tests/test_report_claims.py` now also checks that every table cell's
CSV row agrees with the row's shell, condition, scheme, comparator, endpoint, check, label and
unit cells and with its column (catching a correct value in the wrong cell), that interval
parts appear in order, that ledger labels equal a CSV row's own label, that no p-value of zero
is displayed, that backticks hold only identifiers, that only the reviewed releases are cited,
and that every reference is a verified primary source.

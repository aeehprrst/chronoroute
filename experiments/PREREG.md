# ChronoRoute campaign preregistration

Status: prospective protocol for E0, E1, E2, E4, E5 and E16. No main
experiment is authorised by this document until the correctness and pilot gates
below pass. Existing course-milestone results are prior validation, not
confirmatory evidence for these hypotheses.

The normative references are [T-CRH v1](../spec/tcrh-v1.md), its
[golden vectors](../spec/golden/), [simulation configuration](../docs/sim-config.md),
[baseline definitions](../docs/baselines.md), and the implementations in
[`eval/`](../sim/chronoroute/eval/). The rules in
[NEXT_STEPS section 2](../docs/NEXT_STEPS.md) apply throughout.

All grids, thresholds, sample sizes, equivalence margins and resource budgets
below are **prospective choices**, not measured results. Runtime extrapolations
are explicitly **MODELLED**. Empirical claims, including pilot timings and all
subsequent figures, must be generated from files under `results/` with a
`manifest.json`; neither this document nor a plot may substitute invented data.

## 1. Questions and falsifiable hypotheses

| Experiment | Research question | Preregistered hypothesis and failure condition |
|---|---|---|
| E0 | Do geometry, physics and all wire implementations agree? | No invariant or wire-byte violations; position differences stay within the existing parity tolerances. Any violation blocks the campaign. |
| E1 | Can deadlines detect an up-but-slow ISL without excessive false alarms, and where do they fail relative to local and conventional monitors? | At a pilot-selected operating point with clean-packet FPR at most 1%, ChronoRoute detects nominal/strong faults more often than LS-H and CRH-16, and has shorter censored detection delay than LS-D. Small faults inside the budget may remain undetected. LQ may beat ChronoRoute; this is a primary comparison, not an excluded case. |
| E2 | What wire cost buys per-hop time checking? | T-CRH costs more than CRH-16 and less than SRv6 SRH over the registered segment counts. Relative to CRH-32 it trades a larger fixed part for a smaller per-entry part; enumerate the crossover and padding ties rather than assert a universal saving. Encapsulation adds the outer IPv6 header. This is exact code/byte accounting, not a statistical latency claim. |
| E4 | Does local fallback preserve delivery under repairable link and satellite outages? | ChronoRoute with greedy-with-visited improves PDR and blackhole time relative to continue and CRH-16, without a material effective-tail penalty relative to SNAP or LS-H+BFD. O-T is a privileged reference, not an implementable competitor. |
| E5 | Does loop avoidance improve fallback completion, and does a Grid detour justify its cost? | Greedy-with-visited reduces stuck/loop losses relative to pure greedy; Grid detour reduces those losses further or improves stretch, but may add hops. Continue/drop can win on cost or delivered-packet latency and must remain visible. |
| E16 | Are the Python and ns-3 implementations interchangeable within the registered scope? | Deterministic replay agrees per packet exactly. Stochastic run-level PDR, FPR and latency pass the equivalence tests in section 7. Failure to establish equivalence is not evidence of equivalence. |

The main inferential question is E1. E0 and deterministic E16 are validity gates;
E2 is an exact accounting exercise. E4 and E5 are separate policy experiments,
not evidence that detection alone provides mitigation.

## 2. Provenance, labels and frozen configuration contract

Commit this file alone before any pilot or main campaign run. Every subsequent
experiment config must contain an outer campaign metadata block (removed before
passing the engine's strictly validated config to `cr eval scheme`):

```yaml
campaign:
  prereg_path: experiments/PREREG.md
  prereg_git_sha: REQUIRED_FULL_COMMIT_SHA
  prereg_sha256: REQUIRED_FILE_SHA256
  phase: pilot_or_confirmatory
  experiment: E00_or_E01_or_E02_or_E04_or_E05_or_E16
  cell_id: REQUIRED_CANONICAL_CELL_ID
  pair_id: REQUIRED_PAIR_ID
  seed: REQUIRED_INTEGER
```

These strings describe a required future launcher contract, not a currently
accepted `cr run` schema. Generate actual configs in the corresponding
`experiments/E*/` task after resolving the standalone preregistration commit;
refuse unresolved placeholders. Copy these fields into each manifest's `extra`
metadata. Also record the clean implementation commit, complete normalised
engine/scheme config and its hash, exact command, master seed and RNG stream
identities, input snapshot hashes, twin manifest/hash, output hashes, host,
versions, wall time and peak RSS. Derived analyses must manifest their input
manifests, analysis command, resampling seed and frozen operating-point file.
Do not rely on the current branch HEAD to identify the preregistration later.

Commit and test all launchers, fault generators, E5 hooks, ns-3 extensions and
analysis functions before using them. `make check` precedes every commit;
changes under `ns3/` additionally require `make ns3-test`, and changes under
`web/` require its tests, check and build. Run only from a clean tracked tree;
experiment outputs go in ignored run folders until collected and committed.
Every successful, failed, timed-out and excluded job remains in the campaign
inventory, with its reason. A failed job never becomes a silently missing seed.

Use `labels.pick()` and the shared notes in
[`labels.py`](../sim/chronoroute/labels.py), rather than inventing manifest keys:

| Component | Label and interpretation |
|---|---|
| Pinned CelesTrak elements, city coordinates, SGP4 positions on those elements | REAL: public inputs and real physics/code, not measured network behaviour |
| Inferred shells/planes, planned routes and budgets | DERIVED |
| C2 circular Walker constellation and its positions | MODELLED; do not inherit the REAL position label of C5 |
| Grid-4 ISLs, GSL assignment/mask, processing, rates, queues, probes, faults, fallback and control-plane timing | MODELLED; the elevation mask is an ASSUMED parameter recorded as MODELLED |
| Generated header bytes and extracted capture bytes | REAL output of the implementations; size calculations are DERIVED accounting |
| Runtime forecasts and extrapolations | MODELLED; pilot wall times are actual host observations with manifests |
| Starlink's operational routing and actual laser-link layout | UNKNOWN in prose; not an additional schema label |

Starlink does not use T-CRH. None of these experiments measures Starlink's
operational routing, traffic, failure rate or internal control plane.

## 3. Shared scenarios, city blocks and seeds

### Constellations and geometry

* **C5:** `kind: real`, `source: supgp`, `shell: 53.2deg-463km`, snapshot
  `data/pinned/20261010T1358Z-celestrak/`. Verify its `SHA256SUMS`; never refresh
  it during the campaign. Shell/plane assignment uses the repository algorithm.
* **C2:** `kind: walker`, `preset: C2`: 72 planes by 22 satellites, circular
  altitude 550 km, inclination 53 degrees, phasing 39, generated by
  `fwd/presets.py`. This is the MODELLED literature reference, not CelesTrak data.
* Both start at `2026-10-10T14:00:00Z`, use 100 ms geometry steps, 200-step
  streaming chunks, Grid-4 with the repository's 80 km grazing constraint,
  70-degree cross-plane cutoff and no additional maximum range. GSLs use a
  25-degree minimum elevation, at most four links per station, `sticky_top_k`.

### Pair population and exclusions

These are the ordered science pairs, with exclusions fixed before outcomes.
Direction matters; each selected pair generates the named forward flow and a
reverse flow. `Sao Paulo` is the spelling in `data/static/cities.csv`.

| Original order | Pair | Confirmatory pair ID |
|---|---|---|
| 1 | Mumbai → Dubai | 0 |
| 2 | Cairo → Moscow | 1 |
| 3 | Reykjavik → Toronto | Excluded |
| 4 | London → New York | 2 |
| 5 | Singapore → Sydney | 3 |
| 6 | Nairobi → Frankfurt | 4 |
| 7 | Lagos → Sao Paulo | 5 |
| 8 | Honolulu → Tokyo | 6 |
| 9 | Anchorage → Oslo | Excluded |
| 10 | Delhi → Paris | 7 |
| 11 | Seoul → Vancouver | 8 |
| 12 | Chennai → London | 9 |
| 13 | Perth → Johannesburg | 10 |
| 14 | Tokyo → Los Angeles | 11 |
| 15 | Johannesburg → London | 12 |
| 16 | Mexico City → Paris | 13 |
| 17 | Lima → Madrid | 14 |
| 18 | Santiago → Auckland | 15 |
| 19 | New York → Sydney | 16 |
| 20 | Sao Paulo → Tokyo | 17 |

Reykjavik–Toronto and Anchorage–Oslo are excluded because of the 53-degree
shell coverage limitation documented in NEXT_STEPS section 5. Exclude them in
both C5 and C2 to keep the same comparison population. Do not add polar shells.
Check retained pairs' geometric route availability before simulation, and
record the check. Do not remove later `no_route` packets or unfavourable pairs.
If an on-path target cannot be resolved, record a failed design cell and amend
the protocol before confirmation; do not search seeds until a desired path occurs.

**Pilots:** only seeds 0–99; the fixed matrix below uses 0–5. No pilot outcome
enters confirmatory estimates. **Confirmation:** seeds 1000–1035 inclusive,
36 seeds per main constellation × fault/profile × scheme cell. Pair ID is
`(seed - 1000) % 18`; thus each cell has two independent runs per pair. The two
directions are correlated observations inside a run, not independent samples.
The target fault is on forward flow 0. The primary detection endpoint uses that
flow; reverse-flow detection and all-flow delivery are secondary. For packet
monitors, filter flags/exposure to flow 0 before both packet and event scoring;
LS control-plane events remain network events on the same target element.

Cities are fixed, balanced blocks within a cell, **not 18 additional main
cells**. There are no powered per-city claims from two replicates. Report their
descriptive outcomes and the equal-pair campaign average. Faults, schemes,
policies and twins share master seeds, packet IDs, send times and keyed draws.
Use keyed streams for target selection and renewal intervals as well. Never
seed a generator from Python's process-randomised `hash()`.

### Common engine settings

Unless overridden below: two CBR UDP flows at 100 packets/s each; payload
200 bytes; random initial phase; source insertion; PPP overhead 2 bytes;
1 Gb/s nominal links; drop-tail capacity from `buffer_ms: 20` at nominal rate;
1 s schedule refresh; unit code 1 (0.1 ms); Hop Limit 64; actual and planner
processing 500,000 ns; no jitter; `stable` planned links; carrier detection
0 ms shared by every scheme. Recovery is immediately visible as in the engine.
No Poisson **background** in the main campaign. Use fluid background where
specified, with offered rate `rho * nominal C`, not `rho * cut C`.

Use fast byte forwarding, `verify_every: 100`, packet CSVs and scheme extras,
sampled traces every 100 packets and all invariant checks. Preserve
`tx_ns`, `wait_ns`, `tx_loss_at`, arrivals, paths, schedule rows, flags and
control ledgers. E1 disables only `scheme.outputs.stretch_oracle` because
stretch is not its endpoint; E4/E5 enable it. Keep SNAP upload counting and
CRH satellite-state uploads enabled; no cost-free control-plane shortcuts.

## 4. E0 and E2: exact gates and byte accounting

**E0 orbit gate:** sort the used C5 satellite IDs by catalogue number and
select indices `floor(i * (N-1) / 199)`, `i = 0..199`, for shell size N;
record the IDs. Compare
python-sgp4 and satellite.js at offsets 0 through 6000 s inclusive in 10 s
steps. Compare both ordinary ECEF and the reference epoch convention with the
existing parity tolerances: 10 m and 1 m, respectively. These tolerances are
acceptance criteria, not claims about orbit accuracy. Check both pinned-input
and exported browser-input paths. Exercise C2 geometry through the same exporter.

**E0 physics gate:** over that full-orbit-length window for both constellations,
check every active candidate link at each sample: laser segment grazing height
at least 80 km, visibility masks, finite nonnegative distances/delays and
propagation delay no smaller than distance/c except the documented nearest-ns
rounding allowance (at most half a nanosecond). Every sampled end-to-end path
must respect the surface great-circle/c lower bound with an explicit sum of
rounding allowances. Never apply that end-to-end bound to a single ISL.
Record counts and worst residuals, not just a pass word.

**E0 wire gate:** all golden vectors plus schedule headers from both
constellations must produce identical bytes and hop decisions in Python,
ns-3, the website protocol engine and Wireshark's extracted fields/raw bytes.
Test source and encapsulation modes, padding, saturation, equality at deadline,
wraparound and DEV/DevHop handling. Byte mismatch or any unexplained physics
violation stops confirmation; fix, test, commit and rerun the gate cleanly.

**E2:** enumerate segment counts `n = 1..40`, treating n as the number of
encoded entries (not the number of vertices including ingress). Use
`proto/sizes.py` to emit a manifested CSV:

* T-CRH `pad8(12 + 3n)`; CRH-16 `pad8(4 + 2n)`;
  CRH-32 `pad8(4 + 4n)`; SRv6 SRH without TLVs `8 + 16n`.
* Source overhead is the routing header; encapsulation overhead adds 40 bytes.
* Report `100 * added_bytes / 1400` as percent of a **1400-byte reference
  packet before insertion**. Also report the final-packet fraction
  `100 * added_bytes / (1400 + added_bytes)` with its different denominator.
* Extract actual header and frame lengths from the manifested course-milestone
  pcap, recording input manifest/hash, interface/L2 bytes, IPv6, UDP and payload
  separately. Check `(HdrExtLen + 1) * 8` and predicted complete wire length.
  A T-CRH pcap does not constitute a measurement of the other protocols.

These are DERIVED sizes checked against REAL encoder/capture output. Do not
invent confidence intervals for exact byte counts or regenerate the expensive
course milestone just to obtain the already available capture.

## 5. E1: detection grid and operating point

Send for 12 s, drain for 2 s, no warm-up exclusion; fault interval `[4, 8)` s.
Each CBR flow therefore has enough scheduled probes for the registered P99
minimum, although E1's primary endpoint is detection. Use `policy: continue`,
fluid ISL background `rho: 0.3`, J1 exponential processing jitter of mean
400,000 ns and planner processing 900,000 ns (actual base processing plus
the specified jitter mean). Use `plan_links: instant` here to separate deadline
scoring from the stable planner's budget-dependent look-ahead. This controlled
detection experiment is distinct from stable planning in E4/E5.

One bidirectional faulty laser link per run, resolved on the forward planned
path at 4 s. Position `first`, `middle`, `last` means the middle candidate of
that nearly equal third, exactly `Scenario.resolve_on_path`, not the first or
last ground link. Save the resolved physical link and freeze it across schemes.

| Family | Middle-third magnitudes | Nominal magnitude also at first/last thirds | Fixed semantics |
|---|---|---|---|
| Rate cut | factor 0.2, 0.3, 0.6 | 0.3 | Fraction of nominal capacity; background stays at 0.3 of nominal, so the grid crosses the fluid overload boundary |
| Added delay | 250,000; 1,000,000; 4,000,000 ns | 1,000,000 ns | `slow_processing` on the link, as applied by the engine; link remains up |
| ARQ | loss probability 0.01, 0.1, 0.3 | 0.1 | `max_retries: 3`, `retry_extra_ns: 500000`, engine's keyed ARQ model |

This is a sparse, prespecified grid: five conditions per family, **15 fault
conditions**, not a full magnitude × position factorial. No conclusions about
unrun magnitude/position interactions. Also run three middle-third null
controls: rate factor 1, delay 0 and ARQ loss 0. Every null must give exactly
zero attributed packets and events at every registered ChronoRoute rule and
at the other schemes' native detector settings.

Seven schemes in every condition: ChronoRoute, LS-H, LS-D, E2E, LQ, CRH-16
and O-Q. Use `baselines/params.py` defaults except these explicit choices:

* ChronoRoute feedback FB0; no ground response to its flags.
* LS-H: `olsr_leo` (hello 1 s, hold 3 s, minimum LSA interval 0, SPF delay
  50 ms), shared carrier visibility. A slow link never loses carrier.
* LS-D: the same LS settings, average delay window 0.2 s, relative threshold
  0.2, probe interval 100 ms, inter-update and minimum announcement intervals
  1 s. This favours a LEO-tuned competitor; it is MODELLED, not an RFC default.
* E2E: one destination deadline at S = 1.5, reporting delay 50 ms,
  `feedback: false`; report its lack of localisation. LQ: queue threshold
  1 ms, ARQ window 100 ms, `action: flag`. These operating points are fixed.
* CRH-16: no time detector. O-Q has privileged queue/fault knowledge and is
  a routing/delivery bound, not a source of deployable detector flags; a run
  that avoids the link has undefined exposure-conditioned detection.

ChronoRoute offline rule grid, always through `encode_deltas` with unit code 1:

| Rule | Budgets for hop k, cumulative nominal prediction P_k | Grid |
|---|---|---|
| Multiplicative | S P_k | S = 1.1, 1.25, 1.5, 2, 3 |
| Additive | P_k + k a | a = 250,000 or 1,000,000 ns; constant addition 0 |
| Quantile | P_k + ceil(z_(1-alpha) sigma sqrt(k)) | alpha = 0.01 or 0.001; static sigma = 400,000 ns |

The quantile spread is a MODELLED prior from the specified exponential J1
distribution, not a fitted value. This normal-quantile budget is a candidate
rule, not an assertion that accumulated jitter is exactly normal. Preserve SAT
cases, encoded clamping and serial-time arithmetic; never replace bytes by
unrounded floating deadlines. `offline.check_plans` must pass for every rule
and twin. A changed path requires a clean direct rerun, charged to reserve,
or a preregistration amendment before confirmation, never silent rescoring.
Do not apply ChronoRoute's offline rescorer to E2E or LQ as if it retuned them.

Pilot selection is per constellation, **one rule across all pairs and faults**:
among rules whose pilot clean-packet FPR is at most 1%, choose the largest mean
counterfactual packet detection over the three nominal middle-third faults.
Compute pilot FPR from summed clean/false-positive counts, and each family's
packet detection from summed TP/crossed counts across its six pilot seeds;
then equally average the three family rates. A zero total crossed count makes
that rule's pilot selection score ineligible, with the reason recorded.
Tie-break by lower FPR, then the rule order in the table. If none qualifies,
retain S = 3 for a documented failed-FPR outcome; do not conceal the failure.
Freeze the selection and pilot input hashes before reading seed 1000+ outputs.
Confirmation reports this operating point with a 95% FPR interval, all nine
prespecified rule curves, and whether the selected point actually meets 1%.
Never choose the best confirmatory rule after inspecting its detection rate.

Primary confirmatory E1 detection probability is the mean of the 36 per-run
event-detected indicators, including zero for an undetected registered fault
even when no probe crosses it. The packet-detection curve is a secondary
exposure-conditioned ratio of summed TP to summed crossed counts, with a
run-cluster bootstrap and zero-exposure runs retained in the resampling pool.
Report the distribution of run-level ratios and every undefined denominator.

For event detection use k = 2, W = 1 s, horizon 4 s; also show k = 1 and 4
as registered descriptive sensitivities. Display packet ROC against clean
FPR for packet detectors, and event ROC against false events/hour for all
detectors, including LS installation events. LS has no clean-packet deadline
FPR; do not assign it an artificial zero FPR to place it on a packet ROC.
For the primary LS comparisons use event detection/delay on the common event
scale. CRH-16 is explicitly the no-detector control.

## 6. E4 and E5: failure and fallback grids

### E4 targeted repairable failures

Send for 30 s and drain for 2 s; no background or jitter. Use S = 1.5 and the
common stable planner. Resolve a middle-third ISL, or a middle-third satellite,
on forward flow 0 at 3 s. The same target and renewal history are shared across
schemes. During `[3, 27)` s, generate alternating exponential up/down intervals,
starting in the stationary state: down probability U, mean down time MTTR,
mean up time `MTTR * (1-U) / U`. Truncate intervals at the experiment boundary.

| Target | Profile A | Profile B |
|---|---|---|
| One bidirectional on-path ISL | U = 0.01, MTTR = 0.5 s | U = 0.05, MTTR = 2 s |
| One on-path satellite (all its incident links affected) | U = 0.01, MTTR = 0.5 s | U = 0.05, MTTR = 2 s |

There are four profiles, not a factorial separation of U and MTTR. U denotes
the target's stationary unavailability, not a fleet-wide fraction of failed
links. Runs with no realised outage remain in PDR estimates, with zero event
count; no artificial failure is inserted to improve exposure.

**Implementation dependency:** the existing `link_renewal`/`node_renewal`
config affects a whole population. For this bounded campaign, a tested launcher
must use the existing `renewal_periods` keyed generator and compile intervals
for the selected target into explicit `link_down`/`node_down` faults. Record
the selected target, stream and complete intervals. Do not mislabel these as
global churn, or substitute global renewal in the runtime estimate. Population
churn is outside this campaign and needs its own resource plan.

Six schemes: ChronoRoute greedy-with-visited, ChronoRoute continue with
`fallback: none`, O-T, SNAP, LS-H+BFD and CRH-16 continue with `fallback: none`.
Thus the continue controls measure source routing without local repair; this
comparison does not isolate deadline policy from fallback availability.
Use shared carrier detection
0 ms, LS `olsr_leo`, BFD 100 ms × 3 and SPF delay 50 ms; carrier-visible
failures may be detected before BFD, so this is not a BFD-only experiment.
SNAP update 1 s, telemetry 10 s, upload latency 0, drop at dead next hop;
uploads counted. CRH-16 has no deadline, but the same failure visibility.
Retain the default CRH-FIB/ephemeris refresh accounting (14,400 s periods),
actual short-run uploads and their separately labelled steady-state rate.

Primary: all-flow PDR, effective P99, and per-outage blackhole time. Secondary:
per-direction PDR, TTM, lost reasons, stretch, control bytes by medium, header
bytes and satellite state. Aggregate outage endpoints within each run first;
bootstrap runs, never individual outages. Show no-outage run counts separately.
For the primary tail contrast, the run value is the arithmetic mean of its
two per-flow effective P99s, infinite if either is infinite. Blackhole is the
mean over realised outages in the run; it is undefined for a no-outage run.
Its paired analysis therefore conditions on the common realised-outage seeds,
reports that smaller sample size explicitly and makes no unconditional
blackhole claim. Do not turn an undefined TTM into a successful zero.

### E5 controlled deviation

Send for 12 s, drain for 2 s, stable planner, no jitter/background, S = 1.5.
On the forward planned path at 4 s choose one satellite uniformly using a
dedicated keyed stream, before policy outcomes; freeze its ID across policies.
During `[4, 8)` s trigger deviation once per forward packet on its first visit
to that node. There are no link failures in this experiment.

**Implementation dependency:** add and test an explicitly MODELLED experiment
hook that records this intervention and invokes the ordinary late-deviation
policy at the selected node without adding service delay or changing geometry.
It sets DEV/DevHop consistently with the protocol and does not trigger again
on a revisit. It is a controlled policy intervention, not a real deadline
alarm and not an FPR observation. Verify identical pre-trigger paths/times
across policies and retain packets that never reach the trigger separately.
Do not claim this hook already exists, or substitute an unrecorded delay.

Five policies: greedy + `greedy_visited`; greedy + `greedy_pure`; greedy +
`grid_detour`; continue; drop. Keep Hop Limit 64 and common link visibility.
The visited set is MODELLED packet state unavailable in the current wire
header; include its state cost and do not describe it as free wire support.
The Grid policy is the repository implementation, not an idealised global
shortest-path repair.

Primary stuck rate is triggered packets ending in `stuck`, `loop`,
`hop_limit` or `no_fallback`, divided by all triggered packets. Also show
each reason, strict-drop rate, triggered-packet PDR and unconditional PDR;
drop cannot win by being called zero-stuck while discarding all packets.
Delivered-packet extra hops = actual transmissions minus send-time oracle
fewest hops (`oracle_hops`); report negative values if geometry changes allow
them. Stretch is the existing time-weighted metric in section 8. Report
triggered-packet effective latency alongside delivered-only stretch so losses
cannot disappear through survivorship conditioning.

## 7. E16: deterministic replay and stochastic equivalence

Use both constellations and two conditions: no fault, and a middle-third ISL
rate cut to factor 0.0002 during `[4, 8)` s. Duration 12 s, drain 2 s, two
directions, 200-byte payload, no background/jitter, source mode, continue,
stable planner, S = 1.5. Set actual and planner processing to **0** on both
engines, matching the ns-3 course model; do not generalise to nonzero processing
or to fluid background. Match nominal rate, byte queue capacity, scheduling,
geometry step, failure/tie ordering, header serialization and drain rules.
In particular do not compare ns-3's default packet-count queue against Python's
nominal-rate byte buffer: configure the same byte capacity explicitly.

Deterministic gate: identical explicit CBR send times, exported schedule and
truth topology for each engine. Compare every packet ID, send/outcome/drop
reason, complete path, header decisions and arrival times to the nanosecond;
compare absent arrivals consistently for lost packets. Zero mismatches is
required, extending `export/ns3_crosscheck.py` to include queues and losses
instead of treating its current light-time predictor as a full replay.

Stochastic comparison: 36 runs per constellation × condition **on each
engine**, seeds 1000–1035, same pair blocks. Generate exactly 1200 send times
per direction as sorted independent uniform integer-nanosecond times in
`[0, 12 s)` (conditional Poisson traffic with fixed count); reject duplicate
times by deterministic keyed redraw. Replay the identical list on both
engines. This supplies run-to-run randomness without requiring unmatched
background or processing models. Any ns-3 explicit-send or byte-queue support
must be tested and committed first. No independent resampling of packet traces.

TOST uses paired run differences at alpha = 0.05: both one-sided t tests must
reject, equivalently the paired 90% CI must lie strictly inside the bounds.
Additionally report ordinary paired 95% CIs. Prespecified equivalence margins:

* PDR: ±0.01 absolute (one percentage point).
* Clean-packet FPR: ±0.005 absolute (half a percentage point).
* P50 and effective P99: ratio inside `[1/1.05, 1.05]`, tested on paired
  log ratios with symmetric bounds `±log(1.05)`.

Use one run's all-flow PDR/FPR and the mean of its two per-flow log-quantile
ratios for latency. Undefined FPR, insufficient tail counts or infinite
effective quantiles preclude a latency/FPR equivalence verdict for that cell;
report the reason and paired loss counts, do not drop those runs to pass TOST.
If differences are all exactly zero, their degenerate CI establishes
equivalence only when strictly inside the chosen bounds. All four endpoints
must pass in both conditions and constellations to claim scoped equivalence
(an intersection-union decision, not a search for one passing endpoint).

## 8. Exact metric definitions and analysis

Implementations are `eval/metrics.py`, `detection.py`, `offline.py` and
`stats.py`. A future change to any definition requires a prospective amendment
and regression tests, not a retrospective reinterpretation.

* **Measurement window:** select by send time in `[max(0, warmup),
  end_ns - drain_ns)`; warmup is 0 throughout this campaign. Allow in-flight
  packets the full drain. `unfinished` after drain is a loss, not a deletion.
* **PDR:** delivered/sent; report `no_route`, `unfinished` and each drop reason.
  Primary aggregate PDR is the mean run-level proportion, which gives equal
  weight to each city block. Pooled delivered/sent is secondary, with a
  run-cluster ratio bootstrap, never a binomial packet CI.
* **Latency:** delivery time minus send time; nearest rank `ceil(p*n)`.
  Ordinary quantiles condition on delivery. Effective quantiles give each
  lost packet +infinity; if delivered count is less than the required rank,
  the quantile is infinite. P99 needs at least 1000 observations per flow-run
  (sent for effective, delivered for delivered-only); P99.9 needs 10,000 and
  is not a planned endpoint here. Record both counts and eligibility.
* **Stretch:** `L_det/L*`, with `L_det` the sum of held per-hop light time,
  base processing and serialization **without the routing header**; `L*`
  uses the same weights on the true faulted graph at send time. Queueing
  residual is actual latency minus `L_det`. A path outside the send-time
  graph is counted and excluded from the lower-bound claim. The exact
  same-step minimum must be at least 1. For step-crossing packets test
  `L_det >= L* - tol`, with `tol = 5340 ns * sum(hop upstream steps elapsed
  since send)` at the registered 100 ms step. Report raw, exact-domain and
  tolerance-adjusted minima; do not call every raw value below 1 a violation.
* **Truth labels:** fault, stale, congested, clean, in that priority order,
  using `packet_labels`. Primary `q_th_ns` is null, so ordinary delay variation
  stays in the clean denominator. A link exposure is judged by transmission
  start, node exposure by arrival. Include lost-in-flight, dead-next-link and
  transmitter loss records; a fault-caused `buffer_overflow` or
  `arq_exhausted` packet is **fault**, never clean. Rate-cut exposure includes
  its directional backlog drain until the first idle transmitter observation.
  Refuse traces missing required `tx_loss_at`, never reconstruct an attempted
  next hop from a truncated path.
* **Counterfactual packet detection:** first verify the twin with
  `check_twin`: identical packets, engine configuration except scored faults
  and output options, and identical scheme/settings. For each scored fault,
  `TP = crossed & flagged_fault & ~flagged_twin`; `P_det = TP / n_crossed`.
  `crossed` means the packet reached a downstream checker after traversing
  the element. `lost_at_fault = reached & ~crossed` is separate and
  `reached = crossed union lost_at_fault`. Include these losses in PDR and
  label counts, not the exposure-conditioned detection denominator. An empty
  denominator is undefined, not perfect or zero detection. Also report
  localisation correctness and changed-but-unreached counts as diagnostics.
* **Clean FPR:** clean packets with a deadline flag / clean packets.
  Geometric stale or link-down deviations are not deadline false positives.
  Use the corresponding natural flag for LQ/E2E and label it as that monitor's
  clean false-flag rate. LS control events use the separate event scale.
* **Event detection:** fire on element e when k flags blaming e arrive in
  `(t-W, t]`, then reset that element's count. A deadline blames its incoming
  link, LQ its egress link, E2E is unlocalised. Attribute a fault event only
  if firing time tau is in `[onset, onset+horizon)` and the twin has no
  matching element event in `[tau-W, tau+W]`. LS uses first installation of
  adjacency/metric change. False events/hour = twin events / sending hours,
  not divided by packet count or flow-hours. Pool counts/exposure time with
  a run-cluster bootstrap and show event counts and clean-packet FPR together.
* **Detection delay:** tau minus onset; undetected events are right-censored
  at the horizon. Kaplan-Meier CDF and median, undefined median if the CDF
  never reaches 0.5. For a scalar paired delay comparison use restricted mean
  detection delay through the fixed 4 s horizon (integral of KM survival),
  with paired run-cluster bootstrap; implement/test that analysis first.
  Because every undetected E1 event is censored at that same horizon, this
  restricted mean also equals the mean of per-run `delay if detected else
  4 s`. Use those paired run values for the t-test p-value and retain the
  bootstrap interval as the primary restricted-delay interval.
  Never average absolute timestamps or discard undetected events.
* **Blackhole:** per hard-failure interval, last lost-on-element attempt
  time minus onset, 0 if there was no such loss; always show the loss count.
  Attempt time follows `metrics.blackhole`: upstream presence for ordinary
  in-flight link losses, explicit transmitter/dead-next-hop event when
  recorded, or arrival at a dead node. It is not universally transmission
  start and it is not a count of every downstream loss caused indirectly.
* **TTM:** for affected flows that touched a fault, 100 ms send-time bins;
  first bin start at/after onset with at least 95% delivered without touching
  the fault in every nonempty bin over the next 1 s, wholly before recovery.
  Otherwise censored at fault duration. No affected flows means undefined,
  not instantaneous mitigation. Primary `flags` argument is null.
* **Cost:** report ledger bytes separately for uplink, ISL, downlink and
  ground, and bytes/s divided by engine `end_ns` **including drain**, as
  `control_summary` does. Report mean nonnegative routing-header bytes,
  sum(header bytes × actual hops), satellite state bytes, realised state
  uploads and separately DERIVED steady-state upload rate. Header overhead
  never disappears into the header-free stretch metric.

The independent sampling unit is a complete run/seed. Primary means and
scheme differences use paired Student-t 95% intervals from `eval/stats.py`.
Use seeded 10,000-resample run bootstraps for pooled ratios and censored
endpoints; for paired comparisons resample the same run indices on both
sides. A city-block sensitivity bootstrap resamples the two runs within
each of the 18 fixed blocks, preserving equal block weights. Analysis seed
is 91000, with deterministic endpoint-specific keyed streams. Show
unadjusted CIs and Holm-adjusted two-sided p-values for superiority claims.

Multiplicity families are fixed as follows: E1 event-detection differences
against LS-H, LS-D, E2E, LQ and CRH-16 across both constellations and 15
conditions (150 comparisons); its analogous restricted-delay comparisons
are a separate 150-comparison family. E1 packet comparisons among actual
packet detectors are secondary. E4 PDR, blackhole and effective-tail
comparisons of greedy-with-visited against the other five schemes across
four profiles and both constellations form separate families per endpoint
(40 comparisons each). E5 comparisons of visited versus pure and Grid versus
visited form separate endpoint families across both constellations. An
undefined contrast stays listed and is not evidence of superiority.

Never remove +infinity to obtain finite means/CIs. Report infinite-tail run
fractions and paired finite/infinite categories. Undefined `infinity-infinity`
contrasts and mixed-sign infinities do not enter t/bootstrap arithmetic; use
paired PDR and tail-failure indicators instead and state the latency contrast
is undefined. Refuse NaNs. Only genuine zero-denominator ratio resamples may
be undefined, with their count reported. Packet/outage counts are not degrees
of freedom. Missing/failed runs mean a cell is incomplete, not a smaller
silently accepted sample.

## 9. What counts as losing

Use the selected pilot rule, all registered conditions, and equal city weights.
Report every point-estimate disadvantage as well as its interval; a non-significant
result is inconclusive, not a ChronoRoute win. The following are explicit losses:

* E0 or deterministic E16 has any unexplained violation: validity failure;
  no main routing/detection claim is accepted until fixed and rerun.
* E1 selected operating point exceeds 1% confirmatory FPR: it fails the
  registered operating constraint, even if detection is high. Report whether
  its entire 95% interval is above the limit, straddles it or is below it.
* E1 a practical comparator has at least 0.05 greater event-detection
  probability, or at least 0.1 s smaller restricted mean detection delay,
  with a multiplicity-adjusted significant difference: a material detection
  loss in that cell. All smaller/non-significant disadvantages still appear.
  LQ is practical; O-Q is privileged and is reported separately.
* E4 any practical comparator beats greedy-with-visited by at least 0.01
  absolute PDR, 0.1 s blackhole time, or 5% effective P99, with the adjusted
  comparison supporting that direction: a material policy loss. A finite
  comparator tail versus ChronoRoute's infinite tail is reported directly
  with paired loss/tail indicators, not converted to an omitted ratio.
* E5 visited fails to reduce stuck/loop losses, or has greater extra hops or
  stretch without a completion benefit: the predicted policy advantage is
  unsupported; an adjusted significant disadvantage is a policy loss.
* E2 T-CRH's CRH-16 overhead penalty is a real cost, even if its other size
  hypotheses pass. Any incorrect size or capture claim is a correctness loss.
* Stochastic E16 fails any required equivalence endpoint: interchangeability
  is unestablished in that cell, even if a usual difference test is insignificant.

Do not claim a universal winner from selected cities, only strong faults, only
delivered packets or only successful seeds. Summaries must include small-fault
blind spots, fault losses before a checker, local-monitor advantages, control
and header costs, and unestablished comparisons.

## 10. Pilot matrix, process budget and runtime estimate

### Evidence already available

The existing manifested host is an Intel Core i9-13900H, 20 logical cores,
8,131,350,528 bytes of WSL RAM, recorded in both course manifests below.
These are actual recorded host observations, not a fresh hardware benchmark.

| Existing result and manifest | Recorded ns-3 program time, no-fault / fault |
|---|---|
| [`c5-463-10s-small-seed1/*/run_info.json`](../results/course-milestone/c5-463-10s-small-seed1/nofault/run_info.json), [`manifest.json`](../results/course-milestone/c5-463-10s-small-seed1/manifest.json) | 1.51388 / 1.55917 s |
| [`c5-463-60s-seed1/*/run_info.json`](../results/course-milestone/c5-463-60s-seed1/nofault/run_info.json), [`manifest.json`](../results/course-milestone/c5-463-60s-seed1/manifest.json) | 15.8884 / 16.4643 s |

The matching `fault/run_info.json` is beside each linked no-fault file. The
recorded small run has four flows and the larger run ten, as their configs/
run outputs specify. These times are the `wall_s.total` values; do not confuse
them with the manifests' whole-driver wall times. Both manifests are clean
and their indexed run-info hashes were checked when writing this protocol.
They demonstrate the existing replay scale but **do not measure Python
LS-H, O-Q, multiprocess speedup or the new grids**. Unmanifested speed figures
in working notes are not timing evidence for this estimate.

### Fixed pilot work

Reserve seeds 0–99; use this initial 96-job matrix (same city-index rule with
`seed % 18` for pilots):

* E1 ChronoRoute: seeds 0–5, both constellations, no fault plus each of the
  three nominal middle-third faults: 48 jobs. These freeze the deadline rule.
* E1 cost checks: seed 0, both constellations, LS-H/LS-D/O-Q, each of the three
  nominal middle-third faults: 18 jobs.
* E4 cost checks: seed 1, both constellations, all six schemes, satellite
  profile B: 12 jobs.
* E5 cost checks: seed 2, both constellations, all five policies: 10 jobs.
* E16 cost checks: seed 3, both constellations, both conditions and engines:
  eight jobs.

E0 runs before this matrix. Measure serial time, peak RSS and batches under
the intended worker count; every pilot gets a manifest. The matrix samples
expensive algorithms but is not an empirical power calculation. The sample
size is a compute-constrained design; always show achievable CI width.

### MODELLED campaign budget (not measured performance)

Use **eight single-thread worker processes**, maximum **ten total active
compute processes**, including any analysis workers; no nested pools. Set
BLAS/OpenMP thread counts to one. Build ns-3 beforehand with at most eight
jobs and do not compile alongside experiments. Model usable throughput as
six concurrent serial-process equivalents (75% efficiency for eight workers).
Require measured memory headroom: if eight workers do not fit, reduce workers
and recompute the estimate before confirmation. Never solve RAM pressure by
disabling baseline accounting or by dropping losing runs.

| Work | Planned jobs | MODELLED mean serial seconds/job | Process-seconds |
|---|---:|---:|---:|
| E1 faults: 2 constellations × 15 conditions × 36 seeds × 7 schemes | 7560 | 8 | 60480 |
| E1 shared fault-free twins: 2 × 36 × 7 | 504 | 8 | 4032 |
| E1 three null controls: 2 × 36 × 7 × 3 | 1512 | 8 | 12096 |
| E4 four profiles: 2 × 4 × 36 × 6 | 1728 | 12 | 20736 |
| E4 shared no-fault controls: 2 × 36 × 6 | 432 | 12 | 5184 |
| E5 five policies: 2 × 36 × 5 | 360 | 8 | 2880 |
| E5 shared untriggered controls: 2 × 36 | 72 | 8 | 576 |
| E16 stochastic: 2 engines × 2 constellations × 2 conditions × 36 | 288 | 5 | 1440 |
| Pilot matrix, aggregate allowance | 96 | aggregate | 3600 |
| E0, E2 and deterministic E16, aggregate allowance | gate work | aggregate | 1200 |
| Offline scoring, bootstrap, manifests and figures, aggregate allowance | analysis | aggregate | 3600 |
| **Total** | | | **115824** |

Fault-free twins can be reused only within exactly matching engine/scheme
configs, as verified by `check_twin`; reuse never crosses a different rule's
direct simulation, duration, policy, jitter, background or scheme. E5's
untriggered control is shareable across policies only after tests prove
identical paths, bytes and timings without the intervention; it is not a
counterfactual detector twin under different policy settings. If that proof
fails, charge separate controls to reserve. Do not count offline rules as
additional simulated jobs, and do not omit ARQ/queue losses to save time.

MODELLED elapsed campaign time is `115824 / 6 + 600 = 19904 s`, approximately
**5.53 hours**, including a 600 s serial setup/collection allowance. This
leaves **1696 s (about 28 minutes)** to the six-hour ceiling. These are
arithmetic projections from the proposed workload and explicitly assumed
cost coefficients, not measured Python performance or a guarantee. They
include pilots, confirmation, gates and analysis; environment installation,
implementation, compilation and development tests are outside campaign
compute. Reuse the existing E2 capture rather than rerun the course milestone.

**Resource gate:** before seed 1000 runs, replace the assumed per-family costs
by manifested pilot measurements, retaining a conservative slow-scheme
allowance and measured batch throughput. Save the forecast and all inputs
under `results/` with a manifest. Confirmation may start only if pilots already
spent plus the projected remaining campaign and reserve fit about six hours.
Recompute using fewer workers if needed; do not assume ten workers imply a
tenfold speedup. If the budget fails, commit a prospective amendment with a
smaller scientific scope (still at least 30 seeds in every main cell) before
any confirmatory outcome is inspected. This preregistration does not silently
authorise such a change.

Track campaign wall time and queued work. Per-job timeouts are 60 s for
E1/E5/E16 and 120 s for E4; a timeout is a recorded failure, not a zero-valued
observation. Stop new launches with at least the applicable timeout remaining
before six hours; gate/analysis jobs also have deadlines within that ceiling.
Preserve incomplete cells and publish no completed-campaign claim from them.
No optional full factorial, global churn, extra city shell,
Poisson background or post-hoc sweep is included in this budget.

## 11. Freeze, outputs and amendments

Before confirmation: E0 and deterministic E16 pass; implementations/configs
are committed cleanly; pilot rule selections and measured resource forecast
are manifested and frozen; every scheduled cell has its 36 named seeds and
the preregistration commit/file hash. No experiments are run as part of
writing this file.

Each experiment writes `results/E*/<campaign>/summary.csv`, manifests, run
inventory, per-run metrics, paired contrasts and standalone figures. All
tables/plots are generated from those files. Include denominator counts,
censoring, infinite tails, failed cells, exclusions and losses beside verdicts.
Keep pilot and confirmatory results in separate directories. Commit code
before runs and results afterwards. Record any prospective amendment as a
new commit, its reason, changed cells and whether confirmatory outputs were
already seen; never overwrite this protocol to match observed results.

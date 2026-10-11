# ChronoRoute: Temporal Source Routing and Local Deviation Detection in Modelled LEO Networks

Arshpreet Gaba — VIT Vellore, Computer Networks project

IEEE-style Markdown report draft. Bibliographic identifiers, experiment names and metric
names are identifiers, not measurements. Every numeric quantity in the body links to its
entry in the [claims ledger](../claims.md); exact selectors and formatting are also in
[claims.json](claims.json). All empirical result tables below are drawn from CSV artifacts.
Configuration choices are identified separately and copied from manifested result metadata.

## Abstract

ChronoRoute augments compact IPv6 source routes with cumulative hop deadlines. A late arrival
signals a departure from the planned timing, while a separate fallback policy determines
what happens next. The project evaluates implementation correctness, slow-link detection,
header overhead, hard failures, fallback policies and agreement between Python and ns-3.
The experiments use public orbital elements and explicitly model topology, traffic, queues
and failures. The correctness gate passes. At its registered false-alarm limit, the selected
deadline rule detects strong rate-cut overload and some ARQ faults, but it largely misses
the nominal rate cut and added delays up to the largest registered one; the main detection
hypothesis is therefore not supported for those fault families. The local queue monitor
(LQ) beats it wherever a queue builds. The delay-aware link-state comparator (LS-D) also
appears to beat it, but that comparison is invalid because the LS-D model reads the injected
fault delay directly. Visited fallback improves delivery and shortens the counted blackhole
time, but the blackhole metric does not count the fallback's own hop-limit and loop losses,
and the registered no-tail-penalty hypothesis fails against LS-H. The Grid detour shows no
additional benefit. Python and ns-3 agree packet for packet in a replay in which no packet
was lost. These results support a tested research prototype, not an operational Starlink
routing claim.

**Index Terms—** LEO satellite networks, IPv6, source routing, deadlines, fault detection,
common random numbers, reproducible simulation.

## I. Introduction

Predicted orbital motion makes routes attractive candidates for advance computation. A
route can still fail after insertion because a link disappears, service slows or local
queueing differs from the plan. ChronoRoute asks whether a compact per-hop timing contract
can reveal those departures while retaining a ground-computed route.

The contribution is an explicit experimental header, a shared simulator and evaluation
pipeline, and a manifested comparison against practical monitors and privileged oracles.
The contribution is not a claim that deadlines dominate conventional routing. Detection
and mitigation are evaluated separately: an alarm cannot restore a packet already lost at
the faulty transmitter, and a fallback policy can create a loss on a healthy route.

Starlink names the public orbital inputs. Starlink does not use T-CRH. Its operational
routing is UNKNOWN, and none of the network outcomes here measures its deployed network.

## II. Background

### A. IPv6 source routing

The IPv6 specification defines extension-header and routing-header processing [R1]. The
Compact Routing Header provides compact segment identifiers mapped through local forwarding
state [R2]. The CRH RFC is Experimental, not an Internet Standards Track
specification. The Segment Routing Header uses an IPv6 segment list [R3]. These RFCs supply
background and baselines; the project-specific deadline fields are not part of their
specified semantics. The experimental type is used within a closed domain under the
experimental-value guidance [R4].

### B. Predictable geometry and changing network state

Hypatia provides simulation and visualization infrastructure for moving LEO networks [R7].
This motivates the repository's precomputed snapshot-table comparator, SNAP; SNAP is a
project timing model inspired by that approach, not a reproduction of Hypatia's complete
stack or an evaluation of that paper's reported performance. The IETF time-variant routing
use cases include satellite constellations whose topology changes predictably [R13].

### C. Slowness and monitoring

A link can retain carrier while imposing extra service delay, a form of the gray failures
described for cloud systems [R11]. Hello-based adjacency monitoring and delay monitoring
therefore answer different questions. OSPF traffic engineering metric extensions cover
distributing performance information [R5]; the repository supplies its own MODELLED
measurement and installation timing. STAMP provides an active measurement protocol [R6],
and in-situ OAM records telemetry inside data packets [R12]. The project does not claim
that its simplified monitors implement every standardized behavior.

## III. Design

### A. Temporal compact route

The normative [T-CRH specification](../../spec/tcrh-v1.md) defines a compact segment list,
an ingress epoch, cumulative deadline increments, a deadline-unit selector, and deviation,
fallback and saturation flags. Entries follow the compact header's reverse traversal order.
An arrival is compared against the cumulative deadline for the hop just completed, using
serial arithmetic. Equality is on time. The ingress anchor and cumulative budgets round
up; saturation is explicit and can change the encoded budget.

In symbolic form the encoded deadline is `D_k = E + sum(Delta_i, i <= k)` in header units.
This is a definition, not a measured arrival time. The fields and golden vectors are
normative; this draft does not replace their byte layout or parser validation rules.

### B. Deviation and fallback

A late arrival sets the deviation flag and records its first location. A dead next link
can also reveal a broken plan. Continue preserves the scheduled forwarding decisions;
drop discards the packet; geographic policies try another direction. Greedy-with-visited
adds modelled loop avoidance, and Grid detour uses the modelled constellation structure.
The visited set is simulator state, not a standardized field in the compact header.

### C. Deployment boundary

The source creates the header; encapsulation accounts for an outer IPv6 header. The design
does not authorize arbitrary in-transit extension-header insertion. Clock synchronization,
malicious deadline manipulation, authentication of mutable fields and interaction with
security associations remain deployment concerns. No operational scalability or security
claim follows from a valid encoder.

## IV. Implementation

The Python reference implements wire processing, geometry, schedules, event-driven queues,
keyed fault randomness, fallback and offline scoring. Baselines forward packets through the
same engine. Their control planes are MODELLED timing and accounting mechanisms, rather
than complete OSPF, OLSR or STAMP protocol stacks. O-Q observes queues and O-T observes truth;
they are privileged bounds, not implementable competitors with comparable information.

The ns-3 module processes the actual experimental IPv6 header and replays exported topology,
routes and send-time lists. The browser implements the protocol and planner, with shared
parity gates; Wireshark extracts fields and raw bytes for the correctness check. The website
results pages read summary CSVs and their manifests, verify hashes, retain unavailable
endpoints and offer byte-identical CSV downloads. A missing manifest prevents a build.

The evidence pipeline records the committed implementation, dirty status, command,
configuration, seeds, snapshot, host and output hashes. Collector commits identify the
analysis/collection program; producer manifests and commands preserve the simulation chain.
The [ledger](../claims.md) distinguishes empirical evidence from implementation contracts.

## V. Methodology

### A. Preregistration and evidence labels

The [frozen preregistration](https://github.com/aeehprrst/chronoroute/blob/b87f08a7cc9431d139bf66372f03133035494b8c/experiments/PREREG.md)
sets the hypotheses, grids, outcomes, operating-point selection and losing criteria before
confirmation. The following table follows the shared [label definitions](../../sim/chronoroute/labels.py).

| Label | Quantity or component | Meaning and boundary |
| --- | --- | --- |
| REAL | C5 CelesTrak elements, catalogue identifiers, city coordinates | Public input data; not measurements of internal link state. |
| REAL | SGP4 positions on those public elements; emitted and captured header bytes | Real physics/code and implementation output under the repository convention; not measured spacecraft position accuracy or deployed T-CRH traffic. |
| DERIVED | Inferred shells and planes, routes, budgets, size accounting and statistics | Computed outputs; inference and analysis depend on chosen algorithms. |
| MODELLED | C2 Walker elements and positions | Synthetic reference; the C5 position label does not transfer to it. |
| MODELLED | Grid-4 topology, GSL assignment/mask, service, queues, probe traffic, faults and control-plane timing | Assumptions rather than operational observations; literature-sourced choices remain model parameters. |
| MODELLED | Fallback and visited state | Algorithmic behavior in the engine, with no demonstrated operational packet-state mechanism. |
| UNKNOWN | Starlink routing, actual laser layout, internal traffic and failure processes | Not inferred from the orbital snapshot; Starlink does not use T-CRH. |

### B. Registered hypotheses

The expectations below paraphrase the frozen preregistration; its wording governs.

| Experiment | Prospective expectation | Falsification or losing case |
| --- | --- | --- |
| E0 | No invariant or wire-byte violation; positions stay within the existing parity tolerances. | Any violation blocks the campaign until it is fixed and the gate is rerun. |
| E1 | At a pilot-selected operating point within the clean-FPR limit, ChronoRoute detects nominal/strong faults more often than LS-H and CRH-16 and has shorter censored detection delay than LS-D. LQ may beat it; that is a primary comparison. | The operating constraint fails, or a practical comparator (LQ included) has a material adjusted advantage. Small faults inside the budget may remain undetected. |
| E2 | T-CRH costs more than CRH-16 and less than SRv6 SRH over the registered counts; against CRH-32 the crossover and padding ties are enumerated. | Wrong accounting/capture bytes or an unsupported universal saving. |
| E4 | Greedy-with-visited improves PDR and blackhole time relative to continue and CRH-16, without a material effective-tail penalty relative to SNAP or LS-H+BFD. | A practical comparator has a material adjusted delivery, blackhole or tail advantage; a finite comparator tail against an infinite ChronoRoute tail is reported with paired loss/tail indicators. |
| E5 | Visited reduces stuck/loop losses relative to pure greedy; Grid reduces them further or improves stretch, possibly with extra hops. | No reduction, or extra hops/stretch without a completion benefit; continue/drop may win on cost. |
| E16 | Deterministic replay agrees per packet exactly, and stochastic run-level PDR, FPR and latency pass the registered equivalence tests. | Any unexplained packet mismatch or failure to establish a required equivalence. |

The exact prospective thresholds and multiplicity families remain in the frozen protocol;
no result-dependent replacement of them is made in this draft. Point losses and unavailable
comparisons are reported even when the formal material-loss rule is not met.

### C. Population and sampling

C5 uses the pinned public orbital inputs in the inferred shell [53.2deg-463km](../claims.md#q-c5-shell),
as classified and selected in the result manifest. C2 uses [72](../claims.md#q-c2-planes) planes
with [22](../claims.md#q-c2-per-plane) satellites per plane at [550](../claims.md#q-c2-altitude) km: these are MODELLED configuration choices.
The city population is the retained ordered pairs in the preregistration and the correctness
manifest. Reykjavik–Toronto and Anchorage–Oslo are excluded for shell-coverage reasons in
both constellations. Retained no-route packets remain losses; coverage is not silently
conditioned on later successful routes.

Main stochastic cells use [36](../claims.md#q-samples) independent run seeds, with confirmatory identifiers
[1000](../claims.md#q-seeds)–[1035](../claims.md#q-last-seed); paired schemes share keyed randomness and send times. Directions and packets within
a run are correlated observations, not extra independent samples. The fixed city blocks
have limited replication; city-specific summaries are descriptive. Pilot results select
the deadline rule and inform resources, and do not enter confirmatory estimates.

The frozen multiplicative slack is [1.5](../claims.md#q-selected-slack), with deadline unit code [1](../claims.md#q-selected-unit), as recorded
in the operating-point file. It was chosen on pilot seeds only and frozen before any
confirmatory output was read. The grid varies rate reduction, extra delay and ARQ by magnitude
and route position, with fluid background load in the detection campaign. The preregistration
calls the rate-cut magnitude that is also run at the first and last path thirds the nominal
rate cut (`rate-0.3-first`, `rate-0.3-middle`, `rate-0.3-last`); because the fluid background
uses the same capacity fraction, it leaves the faulty link at exactly full load. The strong
rate cut (`rate-0.2-middle`) overloads the link. Separate repairable link/node outage profiles
test mitigation. Fallback experiments force a checker decision on the planned path without
adding a service fault; continue is consequently a meaningful healthy-route control.

### D. Outcomes and inference

PDR is delivered divided by sent in the registered send window. Effective latency assigns
every loss positive infinity; ordinary delivered-only latency answers a different question.
Tail eligibility is governed by the evaluation code and retained in the results. Undefined
exposure and trigger denominators are not zeros. Infinite contrasts are not made finite by
dropping seeds.

Counterfactual detection requires a crossing, a fault-run flag and no corresponding twin
flag, after checking identical non-fault configuration and packet identity. Fault losses
before a downstream checker are labelled fault and retained as `lost_at_fault`, separately
from the crossing-conditioned detection denominator. Null faults must have no attributed
packet or event. Event delay is measured from onset; non-detection is censored at the fixed
horizon. Restricted mean delay retains that censoring rather than averaging detected cases
alone. Clean FPR counts deadline false flags on clean packets; LS control events and
unlocalised E2E alarms must not be recast as comparable packet-localisation outcomes.

The preregistration makes paired Student-t intervals primary for run-level means and scheme
differences. Pooled ratios and the censored restricted-delay endpoint use seeded run-cluster
bootstrap intervals with [10000](../claims.md#q-bootstrap) resamples, and the preregistration keeps the bootstrap interval as
the primary interval for restricted delay. Every table header below names its interval type.
A binary endpoint that is identical in every run (all zero or all one) gives a zero-width
t interval; that reflects deterministic behaviour under the sampled settings, not certainty.
Paired comparisons resample shared run indices; Holm correction applies within frozen
endpoint families. Point disadvantages remain visible even without adjusted significance.
Exact correctness and byte counts have no sampling CI.
The source columns retain the interval coverage: E16 uses `lo95`/`hi95` for ordinary
reporting bounds and `lo90`/`hi90` for the TOST equivalence decision. Other displayed bounds
use the reporting coverage fixed by the preregistered analysis.
Some recorded p-values are exactly zero in the result files. Some come from paired
differences with zero variance, where the analysis assigns zero; the others come from
numerical cancellation when the true p-value is far below any threshold. This report says
that such a p-value is below the numerical resolution of the computation, never that it is
zero; no significance classification depends on the difference.
Proportions and bounds below are copied without clipping: a t interval may extend outside
the physical probability range.

Stretch divides held per-hop light time, processing and header-free serialization by the
send-time faulted graph's matching shortest-path cost. Exact-domain and tolerance-adjusted
lower-bound checks are separate from raw ratios. A path outside that graph is counted and
excluded from the lower-bound claim; a raw step-crossing ratio below unity is not silently
clamped. Header overhead remains an independent cost.

Blackhole time runs from outage onset to the last loss attempt that the frozen metric
attributes to the outage element: losses at a dead next link, packets with no fallback,
stuck packets, in-flight losses and arrivals at a dead node. A fallback packet that later
dies at the hop limit or in a loop is not attributed, so a blackhole time must be read with
its loss count and PDR. It is conditional on realised-outage runs and must show its
denominator. Engine equivalence uses paired TOST at alpha [0.05](../claims.md#q-tost-alpha), with registered absolute PDR/FPR
margins and log-ratio latency margins. All required endpoints must pass; an ordinary
nonsignificant difference is insufficient.

## VI. Results

All network outcomes in this section are MODELLED and their statistics DERIVED. REAL refers
to implementation bytes or to the stated orbital inputs, not to deployed network behavior.
The displayed cells are representative evidence, not the whole grid; the ledger links the
full tables and all recorded disadvantage lists.

### A. E0: correctness gate

This report uses the re-run gate in `results/E00/20261011T214507Z`. The first run,
`results/E00/20261011T100448Z`, is superseded because its great-circle path check counted
processing time on the path side, which made that lower-bound check much weaker than the
preregistered one. The re-run compares propagation time only, checks every visible
ground-link candidate, adds a visibility-completeness check and fixed
golden-vector expectations, and compares capture bytes as tshark itself reads them.

| Check | Population | Label | Kind of check | Checked | Violations | Worst recorded value | Limit | Unit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| orbit_pinned_full | C5 | REAL | external reference: two SGP4 implementations | [120200](../claims.md#q-gate-orbit-checked) | [0](../claims.md#q-gate-orbit-violations) | [7.841126](../claims.md#q-gate-orbit-worst) | [10](../claims.md#q-gate-orbit-limit) | m |
| orbit_pinned_ms_epoch | C5 | REAL | external reference: two SGP4 implementations | [120200](../claims.md#q-gate-epoch-checked) | [0](../claims.md#q-gate-epoch-violations) | [0.298997](../claims.md#q-gate-epoch-worst) | [1](../claims.md#q-gate-epoch-limit) | m |
| isl_grazing | C5 | MODELLED | model invariant; certified lower bound | [3206936](../claims.md#q-gate-physics-checked) | [0](../claims.md#q-gate-physics-violations) | [138.072646](../claims.md#q-gate-physics-worst) | [80](../claims.md#q-gate-physics-limit) | km |
| isl_polar_cutoff | C5 | MODELLED | model invariant; cannot fail on this shell | [1510914](../claims.md#q-gate-polar-checked) | [0](../claims.md#q-gate-polar-violations) | [53.313782](../claims.md#q-gate-polar-worst) | [70.0](../claims.md#q-gate-polar-limit) | degrees |
| gsl_elevation | C5 | MODELLED | model invariant | [238195](../claims.md#q-gate-elev-c5-checked) | [0](../claims.md#q-gate-elev-c5-violations) | [25.000174](../claims.md#q-gate-elev-c5-worst) | [25.0](../claims.md#q-gate-elev-c5-limit) | degrees |
| gsl_elevation | C2 | MODELLED | model invariant | [173144](../claims.md#q-gate-elev-c2-checked) | [0](../claims.md#q-gate-elev-c2-violations) | [25.000021](../claims.md#q-gate-elev-c2-worst) | [25.0](../claims.md#q-gate-elev-c2-limit) | degrees |
| gsl_visibility_complete | C5 | MODELLED | model invariant | [16227](../claims.md#q-gate-vis-c5-checked) | [0](../claims.md#q-gate-vis-c5-violations) | [0](../claims.md#q-gate-vis-c5-worst) | [0](../claims.md#q-gate-vis-c5-limit) | satellites |
| gsl_visibility_complete | C2 | MODELLED | model invariant | [16227](../claims.md#q-gate-vis-c2-checked) | [0](../claims.md#q-gate-vis-c2-violations) | [0](../claims.md#q-gate-vis-c2-worst) | [0](../claims.md#q-gate-vis-c2-limit) | satellites |
| path_great_circle | C5 | DERIVED | physical lower bound on own paths | [10818](../claims.md#q-gate-path-c5-checked) | [0](../claims.md#q-gate-path-c5-violations) | [1591493.1](../claims.md#q-gate-path-c5-worst) | [0](../claims.md#q-gate-path-c5-limit) | ns |
| path_great_circle | C2 | DERIVED | physical lower bound on own paths | [10818](../claims.md#q-gate-path-c2-checked) | [0](../claims.md#q-gate-path-c2-violations) | [3641655.5](../claims.md#q-gate-path-c2-worst) | [0](../claims.md#q-gate-path-c2-limit) | ns |
| wire_python | C5+C2+golden | REAL | mostly self-consistency | [5866](../claims.md#q-gate-python-checked) | [0](../claims.md#q-gate-python-violations) | [0](../claims.md#q-gate-python-worst) | [0](../claims.md#q-gate-python-limit) | mismatch |
| wire_golden_fixed | golden | REAL | external reference: fixed expected values | [70](../claims.md#q-gate-golden-checked) | [0](../claims.md#q-gate-golden-violations) | [0](../claims.md#q-gate-golden-worst) | [0](../claims.md#q-gate-golden-limit) | mismatch |
| wire_browser | C5+C2+golden | REAL | external reference: independent implementation | [5866](../claims.md#q-gate-browser-checked) | [0](../claims.md#q-gate-browser-violations) | [0](../claims.md#q-gate-browser-worst) | [0](../claims.md#q-gate-browser-limit) | mismatch |
| `wire_ns3` | C5+C2+golden | REAL | external reference: independent implementation | [5866](../claims.md#q-gate-ns3-checked) | [0](../claims.md#q-gate-ns3-violations) | [0](../claims.md#q-gate-ns3-worst) | [0](../claims.md#q-gate-ns3-limit) | mismatch |
| wire_capture_bytes | C5+C2+golden | REAL | external reading: frame bytes as tshark reads them | [10765](../claims.md#q-gate-capture-checked) | [0](../claims.md#q-gate-capture-violations) | [0](../claims.md#q-gate-capture-worst) | [0](../claims.md#q-gate-capture-limit) | mismatch |
| wire_wireshark_fields | C5+C2+golden | REAL | external reference: dissector fields | [10765](../claims.md#q-gate-wireshark-checked) | [0](../claims.md#q-gate-wireshark-violations) | [0](../claims.md#q-gate-wireshark-worst) | [0](../claims.md#q-gate-wireshark-limit) | mismatch |

The rows are not equally strong evidence. The orbit rows compare two independent SGP4
implementations, and the browser, ns-3, dissector-field and fixed golden-vector rows compare
the Python encoder with independent implementations or fixed expected values: these are
external references. `wire_capture_bytes` checks the frame bytes as tshark itself reads them
from the capture. `wire_python` mostly compares Python output with expectations that Python
produced, so it is a self-consistency check. The geometry rows are invariants checked on the
project's own model output; they show internal consistency, not agreement with an outside
reference. The polar-cutoff check cannot fail on these shells: the highest satellite latitude
in C5 is [53.313782](../claims.md#q-gate-polar-worst) degrees, far below the [70.0](../claims.md#q-gate-polar-limit)-degree cutoff, so its pass carries no information.
The grazing value [138.072646](../claims.md#q-gate-physics-worst) km is a certified spherical lower bound on the minimum laser-segment
height, not the exact minimum. The path rows give the smallest margin by which a sampled
end-to-end latency exceeded the surface great-circle light time, comparing propagation only.
Orbit discrepancies are in metres and wire values are mismatch counts. The full summary also
includes C2 orbits, exported-orbit checks, light-time rounding and ground-link degree, all
without recorded violations. These are acceptance checks, not measurements of orbit
prediction accuracy or proof of continuous-time safety.

### B. E1: slow-link detection

**Hypothesis verdict.** The registered E1 hypothesis is not supported for the nominal rate
cut and the added-delay family; it is supported only for the strong rate cut and some ARQ cells.

The selected rule (multiplicative slack [1.5](../claims.md#q-selected-slack) with the registered event threshold) meets the
recorded pooled clean-FPR constraint in both constellations. The table shows the
`chronoroute` rows of the pooled FPR file with run-cluster bootstrap intervals. The selected
cell-level FPR estimates also remain below the registered limit; the full sensitivity sweep
is not substituted for the frozen operating point.

| Constellation | Pooled clean FPR [run-cluster bootstrap CI] |
| --- | --- |
| C5 | [0.005862](../claims.md#q-fpr-c5-mean) [[0.004974](../claims.md#q-fpr-c5-lo), [0.006786](../claims.md#q-fpr-c5-hi)] |
| C2 | [0.004134](../claims.md#q-fpr-c2-mean) [[0.003261](../claims.md#q-fpr-c2-lo), [0.005039](../claims.md#q-fpr-c2-hi)] |

The next table gives the event-detection probability (the mean of the per-run detected
indicators) of the selected rule (`chronoroute`) and of the local queue monitor (`lq`) for
every registered fault condition in both shells.

| Condition identifier | C5 `chronoroute` detection | C2 `chronoroute` detection | C5 `lq` detection | C2 `lq` detection |
| --- | --- | --- | --- | --- |
| `rate-0.2-middle` | [1.000](../claims.md#q-ov-c5-cr-rate-0p2-middle) | [1.000](../claims.md#q-ov-c2-cr-rate-0p2-middle) | [1.000](../claims.md#q-ov-c5-lq-rate-0p2-middle) | [1.000](../claims.md#q-ov-c2-lq-rate-0p2-middle) |
| `rate-0.3-first` | [0.250](../claims.md#q-ov-c5-cr-rate-0p3-first) | [0.000](../claims.md#q-ov-c2-cr-rate-0p3-first) | [1.000](../claims.md#q-ov-c5-lq-rate-0p3-first) | [1.000](../claims.md#q-ov-c2-lq-rate-0p3-first) |
| `rate-0.3-middle` | [0.000](../claims.md#q-ov-c5-cr-rate-0p3-middle) | [0.000](../claims.md#q-ov-c2-cr-rate-0p3-middle) | [1.000](../claims.md#q-ov-c5-lq-rate-0p3-middle) | [1.000](../claims.md#q-ov-c2-lq-rate-0p3-middle) |
| `rate-0.3-last` | [0.000](../claims.md#q-ov-c5-cr-rate-0p3-last) | [0.000](../claims.md#q-ov-c2-cr-rate-0p3-last) | [1.000](../claims.md#q-ov-c5-lq-rate-0p3-last) | [1.000](../claims.md#q-ov-c2-lq-rate-0p3-last) |
| `rate-0.6-middle` | [0.000](../claims.md#q-ov-c5-cr-rate-0p6-middle) | [0.000](../claims.md#q-ov-c2-cr-rate-0p6-middle) | [0.000](../claims.md#q-ov-c5-lq-rate-0p6-middle) | [0.000](../claims.md#q-ov-c2-lq-rate-0p6-middle) |
| `delay-250000-middle` | [0.000](../claims.md#q-ov-c5-cr-delay-250000-middle) | [0.000](../claims.md#q-ov-c2-cr-delay-250000-middle) | [0.000](../claims.md#q-ov-c5-lq-delay-250000-middle) | [0.000](../claims.md#q-ov-c2-lq-delay-250000-middle) |
| `delay-1000000-first` | [0.083](../claims.md#q-ov-c5-cr-delay-1000000-first) | [0.000](../claims.md#q-ov-c2-cr-delay-1000000-first) | [0.000](../claims.md#q-ov-c5-lq-delay-1000000-first) | [0.000](../claims.md#q-ov-c2-lq-delay-1000000-first) |
| `delay-1000000-middle` | [0.000](../claims.md#q-ov-c5-cr-delay-1000000-middle) | [0.000](../claims.md#q-ov-c2-cr-delay-1000000-middle) | [0.000](../claims.md#q-ov-c5-lq-delay-1000000-middle) | [0.000](../claims.md#q-ov-c2-lq-delay-1000000-middle) |
| `delay-1000000-last` | [0.000](../claims.md#q-ov-c5-cr-delay-1000000-last) | [0.000](../claims.md#q-ov-c2-cr-delay-1000000-last) | [0.000](../claims.md#q-ov-c5-lq-delay-1000000-last) | [0.000](../claims.md#q-ov-c2-lq-delay-1000000-last) |
| `delay-4000000-middle` | [0.056](../claims.md#q-ov-c5-cr-delay-4000000-middle) | [0.000](../claims.md#q-ov-c2-cr-delay-4000000-middle) | [0.000](../claims.md#q-ov-c5-lq-delay-4000000-middle) | [0.000](../claims.md#q-ov-c2-lq-delay-4000000-middle) |
| `arq-0.01-middle` | [0.194](../claims.md#q-ov-c5-cr-arq-0p01-middle) | [0.194](../claims.md#q-ov-c2-cr-arq-0p01-middle) | [0.611](../claims.md#q-ov-c5-lq-arq-0p01-middle) | [0.333](../claims.md#q-ov-c2-lq-arq-0p01-middle) |
| `arq-0.1-first` | [0.750](../claims.md#q-ov-c5-cr-arq-0p1-first) | [0.917](../claims.md#q-ov-c2-cr-arq-0p1-first) | [0.861](../claims.md#q-ov-c5-lq-arq-0p1-first) | [1.000](../claims.md#q-ov-c2-lq-arq-0p1-first) |
| `arq-0.1-middle` | [0.417](../claims.md#q-ov-c5-cr-arq-0p1-middle) | [0.389](../claims.md#q-ov-c2-cr-arq-0p1-middle) | [0.861](../claims.md#q-ov-c5-lq-arq-0p1-middle) | [1.000](../claims.md#q-ov-c2-lq-arq-0p1-middle) |
| `arq-0.1-last` | [0.417](../claims.md#q-ov-c5-cr-arq-0p1-last) | [0.389](../claims.md#q-ov-c2-cr-arq-0p1-last) | [0.889](../claims.md#q-ov-c5-lq-arq-0p1-last) | [1.000](../claims.md#q-ov-c2-lq-arq-0p1-last) |
| `arq-0.3-middle` | [0.639](../claims.md#q-ov-c5-cr-arq-0p3-middle) | [0.639](../claims.md#q-ov-c2-cr-arq-0p3-middle) | [1.000](../claims.md#q-ov-c5-lq-arq-0p3-middle) | [1.000](../claims.md#q-ov-c2-lq-arq-0p3-middle) |

At the registered limit the selected rule detects the strong rate cut in every run of both
shells. It never detects the nominal rate cut at the middle or last position in either
shell; at the first position it detects it in [0.250](../claims.md#q-ov-c5-cr-rate-0p3-first) of C5 runs and [0.000](../claims.md#q-ov-c2-cr-rate-0p3-first) of C2 runs. Across the
added-delay family, including the largest registered delay (`delay-4000000-middle`), it
detects at most a few C5 runs ([0.083](../claims.md#q-ov-c5-cr-delay-1000000-first) at `delay-1000000-first`, [0.056](../claims.md#q-ov-c5-cr-delay-4000000-middle) at
`delay-4000000-middle`) and no C2 run at any magnitude or position. ARQ faults are detected
in part of the runs. LQ detects every nominal and strong rate-cut run and most ARQ runs, but
no added delay, because an added delay does not build a queue.

**Why the selected rule misses these faults.** A multiplicative slack of [1.5](../claims.md#q-selected-slack) gives each hop
a cumulative deadline at that multiple of its planned elapsed time. Mid-path this leaves
several milliseconds of spare time, and both the slowly growing queue of the nominal rate
cut (the link sits exactly at full load, so the queue reaches only a few milliseconds) and
every registered added delay fit inside it in almost every run. Looser rules see these faults but break the
registered false-alarm limit. With slack [1.1](../claims.md#q-loose-slack-a), the `delay-4000000-middle` fault is detected in
[1.000](../claims.md#q-loose-c5-a-delay) of C5 runs and [1.000](../claims.md#q-loose-c2-a-delay) of C2 runs, but the pooled clean FPR is [0.175355](../claims.md#q-loose-c5-a-fpr) in C5 and
[0.138429](../claims.md#q-loose-c2-a-fpr) in C2. With slack [1.25](../claims.md#q-loose-slack-b), it is detected in [0.444](../claims.md#q-loose-c5-b-delay) and [0.500](../claims.md#q-loose-c2-b-delay) of runs at pooled
clean FPR [0.043918](../claims.md#q-loose-c5-b-fpr) and [0.033133](../claims.md#q-loose-c2-b-fpr), still above the limit. The frozen rule sits on the low-false-alarm
side of that trade-off, and the blind spots are its price.

The following rows give the strong (`rate-0.2-middle`) and nominal (`rate-0.3-middle`)
middle rate cuts for each scheme. Restricted delay uses the full censoring horizon for missed
events, so a small value represents earlier detection.

| Shell | Condition identifier | Scheme | Event detection [t CI] | Restricted delay, s [run-bootstrap CI] |
| --- | --- | --- | --- | --- |
| C5 | `rate-0.2-middle` | chronoroute | [1.000000](../claims.md#q-detect-strong-cr-mean) [[1.000000](../claims.md#q-detect-strong-cr-lo), [1.000000](../claims.md#q-detect-strong-cr-hi)] | [0.073503](../claims.md#q-delay-strong-cr-mean) [[0.067389](../claims.md#q-delay-strong-cr-lo), [0.079866](../claims.md#q-delay-strong-cr-hi)] |
| C5 | `rate-0.2-middle` | ls_h | [0.000000](../claims.md#q-detect-strong-lsh-mean) [[0.000000](../claims.md#q-detect-strong-lsh-lo), [0.000000](../claims.md#q-detect-strong-lsh-hi)] | [4.000000](../claims.md#q-delay-strong-lsh-mean) [[4.000000](../claims.md#q-delay-strong-lsh-lo), [4.000000](../claims.md#q-delay-strong-lsh-hi)] |
| C5 | `rate-0.2-middle` | ls_d | [0.583333](../claims.md#q-detect-strong-lsd-mean) [[0.414158](../claims.md#q-detect-strong-lsd-lo), [0.752509](../claims.md#q-detect-strong-lsd-hi)] | [1.875936](../claims.md#q-delay-strong-lsd-mean) [[1.268400](../claims.md#q-delay-strong-lsd-lo), [2.487899](../claims.md#q-delay-strong-lsd-hi)] |
| C5 | `rate-0.2-middle` | `e2e` | [1.000000](../claims.md#q-detect-strong-e2e-mean) [[1.000000](../claims.md#q-detect-strong-e2e-lo), [1.000000](../claims.md#q-detect-strong-e2e-hi)] | [0.141239](../claims.md#q-delay-strong-e2e-mean) [[0.125608](../claims.md#q-delay-strong-e2e-lo), [0.158152](../claims.md#q-delay-strong-e2e-hi)] |
| C5 | `rate-0.2-middle` | lq | [1.000000](../claims.md#q-detect-strong-lq-mean) [[1.000000](../claims.md#q-detect-strong-lq-lo), [1.000000](../claims.md#q-detect-strong-lq-hi)] | [0.016681](../claims.md#q-delay-strong-lq-mean) [[0.015631](../claims.md#q-delay-strong-lq-lo), [0.017749](../claims.md#q-delay-strong-lq-hi)] |
| C5 | `rate-0.2-middle` | crh16 | [0.000000](../claims.md#q-detect-strong-crh-mean) [[0.000000](../claims.md#q-detect-strong-crh-lo), [0.000000](../claims.md#q-detect-strong-crh-hi)] | [4.000000](../claims.md#q-delay-strong-crh-mean) [[4.000000](../claims.md#q-delay-strong-crh-lo), [4.000000](../claims.md#q-delay-strong-crh-hi)] |
| C5 | `rate-0.3-middle` | chronoroute | [0.000000](../claims.md#q-detect-nominal-cr-mean) [[0.000000](../claims.md#q-detect-nominal-cr-lo), [0.000000](../claims.md#q-detect-nominal-cr-hi)] | [4.000000](../claims.md#q-delay-nominal-cr-mean) [[4.000000](../claims.md#q-delay-nominal-cr-lo), [4.000000](../claims.md#q-delay-nominal-cr-hi)] |
| C5 | `rate-0.3-middle` | ls_d | [0.611111](../claims.md#q-detect-nominal-lsd-mean) [[0.443826](../claims.md#q-detect-nominal-lsd-lo), [0.778396](../claims.md#q-detect-nominal-lsd-hi)] | [1.859900](../claims.md#q-delay-nominal-lsd-mean) [[1.256761](../claims.md#q-delay-nominal-lsd-lo), [2.472051](../claims.md#q-delay-nominal-lsd-hi)] |
| C5 | `rate-0.3-middle` | lq | [1.000000](../claims.md#q-detect-nominal-lq-mean) [[1.000000](../claims.md#q-detect-nominal-lq-lo), [1.000000](../claims.md#q-detect-nominal-lq-hi)] | [1.323159](../claims.md#q-delay-nominal-lq-mean) [[1.297016](../claims.md#q-delay-nominal-lq-lo), [1.346450](../claims.md#q-delay-nominal-lq-hi)] |
| C2 | `rate-0.3-middle` | chronoroute | [0.000000](../claims.md#q-detect-c2-nominal-cr-mean) [[0.000000](../claims.md#q-detect-c2-nominal-cr-lo), [0.000000](../claims.md#q-detect-c2-nominal-cr-hi)] | [4.000000](../claims.md#q-delay-c2-nominal-cr-mean) [[4.000000](../claims.md#q-delay-c2-nominal-cr-lo), [4.000000](../claims.md#q-delay-c2-nominal-cr-hi)] |
| C2 | `rate-0.3-middle` | ls_d | [0.611111](../claims.md#q-detect-c2-nominal-lsd-mean) [[0.443826](../claims.md#q-detect-c2-nominal-lsd-lo), [0.778396](../claims.md#q-detect-c2-nominal-lsd-hi)] | [1.656031](../claims.md#q-delay-c2-nominal-lsd-mean) [[1.054845](../claims.md#q-delay-c2-nominal-lsd-lo), [2.274892](../claims.md#q-delay-c2-nominal-lsd-hi)] |
| C2 | `rate-0.3-middle` | lq | [1.000000](../claims.md#q-detect-c2-nominal-lq-mean) [[1.000000](../claims.md#q-detect-c2-nominal-lq-lo), [1.000000](../claims.md#q-detect-c2-nominal-lq-hi)] | [1.367539](../claims.md#q-delay-c2-nominal-lq-mean) [[1.355871](../claims.md#q-delay-c2-nominal-lq-lo), [1.378908](../claims.md#q-delay-c2-nominal-lq-hi)] |

**Wins, ties and losses per comparator.** The recorded paired contrasts (ChronoRoute minus
comparator, over every registered fault condition in both shells) give this picture for
event detection:

* *LS-H and CRH-16* (identical here): ChronoRoute never loses. It wins significantly at the
  strong rate cut and at every ARQ condition except the smallest loss, has small
  non-significant point wins in a few other cells and ties elsewhere. These wins hold by
  construction: LS-H and CRH-16 have no slowness detector and detect nothing in any cell.
* *E2E*: ChronoRoute is never significantly worse and is significantly better in a few ARQ
  cells. E2E raises no clean false flags at its fixed operating point, so this is not a
  false-alarm-matched comparison, and E2E does not localise the faulty hop.
* *LQ*: ChronoRoute never wins significantly. It loses significantly at every nominal
  rate-cut cell in both shells and at most ARQ cells, and these are registered material
  losses. LQ uses only its own local queue and ARQ state and has a low clean false-flag rate
  ([0.001208](../claims.md#q-lq-c5-fpr) in C5, [0.001360](../claims.md#q-lq-c2-fpr) in C2), so these losses are robust. Its ARQ monitor has one minor
  modelling advantage: it records the retry count at enqueue time.
* *LS-D*: registered material losses at most nominal rate-cut cells, every added-delay cell
  and the smallest ARQ loss, and significant ChronoRoute wins at the strong rate cut. None of
  these is valid evidence about slowness detection, for the reason below.

The recorded verdict lists every registered material loss and every point disadvantage; all
of them are against LQ or LS-D, on both the detection and the restricted-delay endpoints.
This report shows representative rows only.

#### The LS-D comparator flaw

The LS-D model used for the registered results does not measure delay. Its link metric is the modelled queue estimate plus
the exact injected fault delay plus the expected ARQ delay computed from the configured loss
probability: ground truth, with no measurement noise (`sim/chronoroute/baselines/knowledge.py`).
With the registered update interval, its periodic branch re-advertises any nonzero change,
so the registered relative threshold never matters. A run counts as detected on any metric
installation for the faulty link unless the twin run made any advertisement on that link
within the matching window (`sim/chronoroute/eval/detection.py`). LS-D's outcome therefore
hardly depends on the fault: in C2 it detects the smallest added delay (`delay-250000-middle`)
in [0.638889](../claims.md#q-lsd-c2-delay-small) of runs, exactly as often as the largest (`delay-4000000-middle`, [0.638889](../claims.md#q-lsd-c2-delay-large)). Its detection
ceiling is set by twin runs that block matches with tiny queue-noise advertisements, which
also give it [23183.3](../claims.md#q-lsd-c5-false-events) false events per hour in C5 and [16125.0](../claims.md#q-lsd-c2-false-events) in C2, against [558.3](../claims.md#q-cr-c5-false-events) and [391.7](../claims.md#q-cr-c2-false-events) for the
selected deadline rule. The LS-D numbers stay in the tables as registered, but the LS-D
material losses and the ChronoRoute wins against LS-D are not valid evidence about slowness
detection. The LQ losses do not share this flaw.

Representative adjusted comparisons follow. Negative detection differences and positive
restricted-delay differences favour the comparator. The t interval is the preregistered
primary interval for detection differences; for restricted delay the preregistration keeps
the run-bootstrap interval primary, so both are shown. Rows against `ls_d` are kept as
registered but are not valid evidence (see above).

| Shell | Condition identifier | Comparator | Endpoint | ChronoRoute minus comparator | Paired t CI | Run-bootstrap CI | Holm-adjusted p |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C5 | `rate-0.3-middle` | lq | `detected` | [-1.000000](../claims.md#q-pc-c5-rate-0p3-middle-lq-det-mean) | [[-1.000000](../claims.md#q-pc-c5-rate-0p3-middle-lq-det-lo), [-1.000000](../claims.md#q-pc-c5-rate-0p3-middle-lq-det-hi)] | [[-1.000000](../claims.md#q-pc-c5-rate-0p3-middle-lq-det-blo), [-1.000000](../claims.md#q-pc-c5-rate-0p3-middle-lq-det-bhi)] | below numerical resolution |
| C2 | `rate-0.3-middle` | lq | `detected` | [-1.000000](../claims.md#q-pc-c2-rate-0p3-middle-lq-det-mean) | [[-1.000000](../claims.md#q-pc-c2-rate-0p3-middle-lq-det-lo), [-1.000000](../claims.md#q-pc-c2-rate-0p3-middle-lq-det-hi)] | [[-1.000000](../claims.md#q-pc-c2-rate-0p3-middle-lq-det-blo), [-1.000000](../claims.md#q-pc-c2-rate-0p3-middle-lq-det-bhi)] | below numerical resolution |
| C5 | `rate-0.3-middle` | lq | `restricted_s` | [2.676841](../claims.md#q-pc-c5-rate-0p3-middle-lq-rs-mean) | [[2.650932](../claims.md#q-pc-c5-rate-0p3-middle-lq-rs-lo), [2.702749](../claims.md#q-pc-c5-rate-0p3-middle-lq-rs-hi)] | [[2.653613](../claims.md#q-pc-c5-rate-0p3-middle-lq-rs-blo), [2.703192](../claims.md#q-pc-c5-rate-0p3-middle-lq-rs-bhi)] | below numerical resolution |
| C5 | `arq-0.1-middle` | lq | `detected` | [-0.444444](../claims.md#q-pc-c5-arq-0p1-middle-lq-det-mean) | [[-0.614957](../claims.md#q-pc-c5-arq-0p1-middle-lq-det-lo), [-0.273931](../claims.md#q-pc-c5-arq-0p1-middle-lq-det-hi)] | [[-0.611111](../claims.md#q-pc-c5-arq-0p1-middle-lq-det-blo), [-0.277778](../claims.md#q-pc-c5-arq-0p1-middle-lq-det-bhi)] | [0.000757](../claims.md#q-pc-c5-arq-0p1-middle-lq-det-p) |
| C5 | `arq-0.1-first` | ls_h | `detected` | [0.750000](../claims.md#q-pc-c5-arq-0p1-first-lsh-det-mean) | [[0.601411](../claims.md#q-pc-c5-arq-0p1-first-lsh-det-lo), [0.898589](../claims.md#q-pc-c5-arq-0p1-first-lsh-det-hi)] | [[0.611111](../claims.md#q-pc-c5-arq-0p1-first-lsh-det-blo), [0.888889](../claims.md#q-pc-c5-arq-0p1-first-lsh-det-bhi)] | [6.2e-10](../claims.md#q-pc-c5-arq-0p1-first-lsh-det-p) |
| C5 | `arq-0.1-first` | `e2e` | `detected` | [0.611111](../claims.md#q-pc-c5-arq-0p1-first-e2e-det-mean) | [[0.443826](../claims.md#q-pc-c5-arq-0p1-first-e2e-det-lo), [0.778396](../claims.md#q-pc-c5-arq-0p1-first-e2e-det-hi)] | [[0.444444](../claims.md#q-pc-c5-arq-0p1-first-e2e-det-blo), [0.777778](../claims.md#q-pc-c5-arq-0p1-first-e2e-det-bhi)] | [1.43e-06](../claims.md#q-pc-c5-arq-0p1-first-e2e-det-p) |
| C5 | `rate-0.2-middle` | ls_d | `detected` | [0.416667](../claims.md#q-pc-c5-rate-0p2-middle-lsd-det-mean) | [[0.247491](../claims.md#q-pc-c5-rate-0p2-middle-lsd-det-lo), [0.585842](../claims.md#q-pc-c5-rate-0p2-middle-lsd-det-hi)] | [[0.250000](../claims.md#q-pc-c5-rate-0p2-middle-lsd-det-blo), [0.583333](../claims.md#q-pc-c5-rate-0p2-middle-lsd-det-bhi)] | [0.00178](../claims.md#q-pc-c5-rate-0p2-middle-lsd-det-p) |
| C5 | `rate-0.3-middle` | ls_d | `detected` | [-0.611111](../claims.md#q-pc-c5-rate-0p3-middle-lsd-det-mean) | [[-0.778396](../claims.md#q-pc-c5-rate-0p3-middle-lsd-det-lo), [-0.443826](../claims.md#q-pc-c5-rate-0p3-middle-lsd-det-hi)] | [[-0.750694](../claims.md#q-pc-c5-rate-0p3-middle-lsd-det-blo), [-0.444444](../claims.md#q-pc-c5-rate-0p3-middle-lsd-det-bhi)] | [1.43e-06](../claims.md#q-pc-c5-rate-0p3-middle-lsd-det-p) |
| C5 | `delay-1000000-middle` | ls_d | `detected` | [-0.555556](../claims.md#q-pc-c5-delay-1000000-middle-lsd-det-mean) | [[-0.726069](../claims.md#q-pc-c5-delay-1000000-middle-lsd-det-lo), [-0.385043](../claims.md#q-pc-c5-delay-1000000-middle-lsd-det-hi)] | [[-0.722222](../claims.md#q-pc-c5-delay-1000000-middle-lsd-det-blo), [-0.388889](../claims.md#q-pc-c5-delay-1000000-middle-lsd-det-bhi)] | [1.47e-05](../claims.md#q-pc-c5-delay-1000000-middle-lsd-det-p) |
| C5 | `delay-1000000-middle` | ls_d | `restricted_s` | [2.071903](../claims.md#q-pc-c5-delay-1000000-middle-lsd-rs-mean) | [[1.414851](../claims.md#q-pc-c5-delay-1000000-middle-lsd-rs-lo), [2.728956](../claims.md#q-pc-c5-delay-1000000-middle-lsd-rs-hi)] | [[1.433494](../claims.md#q-pc-c5-delay-1000000-middle-lsd-rs-blo), [2.694815](../claims.md#q-pc-c5-delay-1000000-middle-lsd-rs-bhi)] | [2.64e-05](../claims.md#q-pc-c5-delay-1000000-middle-lsd-rs-p) |

The zero-width intervals in the first rows come from runs in which every paired difference
is identical, as explained in Section V-D. LS-H and CRH-16 do not provide an up-but-slow
detector here. E2E can detect strong degradation without localising its responsible hop.
LQ is a practical comparator with privileged *local* queue visibility, whereas O-Q is an
oracle and has no defined detector endpoint in this campaign; it is a delivery bound, not a
failed alarm. The full summary preserves its empty detection fields. Losses before a checker
limit deadline attribution.

The selected-rule null controls illustrate the attribution gate for the `chronoroute` rows;
the complete run metrics and the recorded verdict also cover both constellations, the other
rules and native monitors. No null attribution violation is recorded.

| Shell | Condition identifier | Attributed packets | Event detection probability |
| --- | --- | --- | --- |
| C5 | `rate-1-middle` | [0](../claims.md#q-null-rate-packets) | [0](../claims.md#q-null-rate-events) |
| C5 | `delay-0-middle` | [0](../claims.md#q-null-delay-packets) | [0](../claims.md#q-null-delay-events) |
| C5 | `arq-0-middle` | [0](../claims.md#q-null-arq-packets) | [0](../claims.md#q-null-arq-events) |

### C. E2: header cost

The table gives exact added bytes for source insertion (mode `source`) at selected encoded
entry counts, including two counts at which CRH-32 is smaller than T-CRH. Entry counts
are read from the `tcrh` rows.

| Encoded entries | T-CRH, bytes | CRH-16, bytes | CRH-32, bytes | SRv6 SRH, bytes |
| --- | --- | --- | --- | --- |
| [4](../claims.md#q-size-entries-4) | [24](../claims.md#q-size-4-tcrh) | [16](../claims.md#q-size-4-crh16) | [24](../claims.md#q-size-4-crh32) | [72](../claims.md#q-size-4-srh) |
| [5](../claims.md#q-size-entries-5) | [32](../claims.md#q-size-5-tcrh) | [16](../claims.md#q-size-5-crh16) | [24](../claims.md#q-size-5-crh32) | [88](../claims.md#q-size-5-srh) |
| [7](../claims.md#q-size-entries-7) | [40](../claims.md#q-size-7-tcrh) | [24](../claims.md#q-size-7-crh16) | [32](../claims.md#q-size-7-crh32) | [120](../claims.md#q-size-7-srh) |
| [8](../claims.md#q-size-entries-8) | [40](../claims.md#q-size-8-tcrh) | [24](../claims.md#q-size-8-crh16) | [40](../claims.md#q-size-8-crh32) | [136](../claims.md#q-size-8-srh) |
| [12](../claims.md#q-size-entries-12) | [48](../claims.md#q-size-12-tcrh) | [32](../claims.md#q-size-12-crh16) | [56](../claims.md#q-size-12-crh32) | [200](../claims.md#q-size-12-srh) |
| [40](../claims.md#q-size-entries-40) | [136](../claims.md#q-size-40-tcrh) | [88](../claims.md#q-size-40-crh16) | [168](../claims.md#q-size-40-crh32) | [648](../claims.md#q-size-40-srh) |

These are exact DERIVED source-insertion byte counts, not latency measurements. T-CRH costs
more than CRH-16 at every registered count and less than SRv6 SRH. Against CRH-32 there is no
universal saving; the crossover recorded in the verdict file is as follows. CRH-32 is smaller
than T-CRH at one, two, three, five and seven entries. The two are equal at four, six, eight,
nine, ten, eleven, thirteen and fifteen entries. CRH-32 is larger at twelve and fourteen
entries and at every count from sixteen to forty. Padding to whole eight-byte units causes
the alternation at small counts. Encapsulation adds an outer-header cost recorded separately
in the same summary. Percentage accounting uses a [1400](../claims.md#q-reference)-byte pre-insertion reference; final-packet
fractions use a different denominator.

The REAL capture summary records [83117](../claims.md#q-capture-frames) frames with [8](../claims.md#q-capture-entries) encoded entries and
[40](../claims.md#q-capture-header) header bytes. Captured packet/frame accounting corroborates T-CRH output only;
other protocols' table entries are accounting comparisons, not measured captures.

### D. E4: hard failures

The E4 simulations ran at commit `b805d2d`, as recorded in the producer manifests
(`inputs/producer-manifests.jsonl.gz`). The first collection of their results crashed while
writing the new tail-failure columns, so the tables used here were re-collected at commit
`a18cffb` without rerunning any simulation (`recovery.json`, `runtime.json`).

The table shows the registered high node-outage profile `node-B`. PDR includes all seeds;
blackhole means condition on realised-outage seeds and are shown with the counted blackhole
losses. Effective tails count losses as infinite.

| Shell | Scheme | PDR [t CI] | Blackhole, s [run-bootstrap CI] | Counted blackhole losses | Outage-run n | Effective tail, s [t CI] | Infinite-tail runs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| C5 | greedy_visited | [0.997014](../claims.md#q-hard-c5-greedy-visited-pdr-mean) [[0.994370](../claims.md#q-hard-c5-greedy-visited-pdr-lo), [0.999658](../claims.md#q-hard-c5-greedy-visited-pdr-hi)] | [0.271175](../claims.md#q-hard-c5-greedy-visited-blackhole) [[0.001365](../claims.md#q-hard-c5-greedy-visited-blackhole-lo), [0.685624](../claims.md#q-hard-c5-greedy-visited-blackhole-hi)] | [33](../claims.md#q-hard-c5-greedy-visited-bh-losses) | [16](../claims.md#q-hard-c5-greedy-visited-blackhole-n) | [inf](../claims.md#q-hard-c5-greedy-visited-tail) [[inf](../claims.md#q-hard-c5-greedy-visited-tail-lo), [inf](../claims.md#q-hard-c5-greedy-visited-tail-hi)] | [5](../claims.md#q-hard-c5-greedy-visited-tail-n) |
| C5 | continue | [0.968079](../claims.md#q-hard-c5-continue-pdr-mean) [[0.948134](../claims.md#q-hard-c5-continue-pdr-lo), [0.988023](../claims.md#q-hard-c5-continue-pdr-hi)] | [1.517442](../claims.md#q-hard-c5-continue-blackhole) [[0.945244](../claims.md#q-hard-c5-continue-blackhole-lo), [2.138184](../claims.md#q-hard-c5-continue-blackhole-hi)] | [6895](../claims.md#q-hard-c5-continue-bh-losses) | [16](../claims.md#q-hard-c5-continue-blackhole-n) | [inf](../claims.md#q-hard-c5-continue-tail) [[inf](../claims.md#q-hard-c5-continue-tail-lo), [inf](../claims.md#q-hard-c5-continue-tail-hi)] | [14](../claims.md#q-hard-c5-continue-tail-n) |
| C5 | crh16 | [0.968079](../claims.md#q-hard-c5-crh16-pdr-mean) [[0.948134](../claims.md#q-hard-c5-crh16-pdr-lo), [0.988023](../claims.md#q-hard-c5-crh16-pdr-hi)] | [1.517441](../claims.md#q-hard-c5-crh16-blackhole) [[0.945235](../claims.md#q-hard-c5-crh16-blackhole-lo), [2.149786](../claims.md#q-hard-c5-crh16-blackhole-hi)] | [6895](../claims.md#q-hard-c5-crh16-bh-losses) | [16](../claims.md#q-hard-c5-crh16-blackhole-n) | [inf](../claims.md#q-hard-c5-crh16-tail) [[inf](../claims.md#q-hard-c5-crh16-tail-lo), [inf](../claims.md#q-hard-c5-crh16-tail-hi)] | [14](../claims.md#q-hard-c5-crh16-tail-n) |
| C5 | snap | [0.971671](../claims.md#q-hard-c5-snap-pdr-mean) [[0.956147](../claims.md#q-hard-c5-snap-pdr-lo), [0.987195](../claims.md#q-hard-c5-snap-pdr-hi)] | [1.398185](../claims.md#q-hard-c5-snap-blackhole) [[0.911054](../claims.md#q-hard-c5-snap-blackhole-lo), [1.912758](../claims.md#q-hard-c5-snap-blackhole-hi)] | [6110](../claims.md#q-hard-c5-snap-bh-losses) | [16](../claims.md#q-hard-c5-snap-blackhole-n) | [inf](../claims.md#q-hard-c5-snap-tail) [[inf](../claims.md#q-hard-c5-snap-tail-lo), [inf](../claims.md#q-hard-c5-snap-tail-hi)] | [14](../claims.md#q-hard-c5-snap-tail-n) |
| C5 | ls_h | [0.998907](../claims.md#q-hard-c5-ls-h-pdr-mean) [[0.998408](../claims.md#q-hard-c5-ls-h-pdr-lo), [0.999407](../claims.md#q-hard-c5-ls-h-pdr-hi)] | [0.048497](../claims.md#q-hard-c5-ls-h-blackhole) [[0.045544](../claims.md#q-hard-c5-ls-h-blackhole-lo), [0.050768](../claims.md#q-hard-c5-ls-h-blackhole-hi)] | [236](../claims.md#q-hard-c5-ls-h-bh-losses) | [16](../claims.md#q-hard-c5-ls-h-blackhole-n) | [0.052314](../claims.md#q-hard-c5-ls-h-tail) [[0.044426](../claims.md#q-hard-c5-ls-h-tail-lo), [0.060203](../claims.md#q-hard-c5-ls-h-tail-hi)] | [0](../claims.md#q-hard-c5-ls-h-tail-n) |
| C5 | o_t | [0.999921](../claims.md#q-hard-c5-o-t-pdr-mean) [[0.999876](../claims.md#q-hard-c5-o-t-pdr-lo), [0.999967](../claims.md#q-hard-c5-o-t-pdr-hi)] | [0.001506](../claims.md#q-hard-c5-o-t-blackhole) [[0.000790](../claims.md#q-hard-c5-o-t-blackhole-lo), [0.002263](../claims.md#q-hard-c5-o-t-blackhole-hi)] | [17](../claims.md#q-hard-c5-o-t-bh-losses) | [16](../claims.md#q-hard-c5-o-t-blackhole-n) | [0.052211](../claims.md#q-hard-c5-o-t-tail) [[0.044297](../claims.md#q-hard-c5-o-t-tail-lo), [0.060124](../claims.md#q-hard-c5-o-t-tail-hi)] | [0](../claims.md#q-hard-c5-o-t-tail-n) |
| C2 | greedy_visited | [0.998616](../claims.md#q-hard-c2-greedy-visited-pdr-mean) [[0.996655](../claims.md#q-hard-c2-greedy-visited-pdr-lo), [1.000576](../claims.md#q-hard-c2-greedy-visited-pdr-hi)] | [0.001975](../claims.md#q-hard-c2-greedy-visited-blackhole) [[0.001102](../claims.md#q-hard-c2-greedy-visited-blackhole-lo), [0.002903](../claims.md#q-hard-c2-greedy-visited-blackhole-hi)] | [16](../claims.md#q-hard-c2-greedy-visited-bh-losses) | [19](../claims.md#q-hard-c2-greedy-visited-blackhole-n) | [inf](../claims.md#q-hard-c2-greedy-visited-tail) [[inf](../claims.md#q-hard-c2-greedy-visited-tail-lo), [inf](../claims.md#q-hard-c2-greedy-visited-tail-hi)] | [2](../claims.md#q-hard-c2-greedy-visited-tail-n) |
| C2 | continue | [0.963056](../claims.md#q-hard-c2-continue-pdr-mean) [[0.940907](../claims.md#q-hard-c2-continue-pdr-lo), [0.985204](../claims.md#q-hard-c2-continue-pdr-hi)] | [1.844305](../claims.md#q-hard-c2-continue-blackhole) [[1.049177](../claims.md#q-hard-c2-continue-blackhole-lo), [2.772433](../claims.md#q-hard-c2-continue-blackhole-hi)] | [7980](../claims.md#q-hard-c2-continue-bh-losses) | [19](../claims.md#q-hard-c2-continue-blackhole-n) | [inf](../claims.md#q-hard-c2-continue-tail) [[inf](../claims.md#q-hard-c2-continue-tail-lo), [inf](../claims.md#q-hard-c2-continue-tail-hi)] | [15](../claims.md#q-hard-c2-continue-tail-n) |
| C2 | crh16 | [0.963056](../claims.md#q-hard-c2-crh16-pdr-mean) [[0.940907](../claims.md#q-hard-c2-crh16-pdr-lo), [0.985204](../claims.md#q-hard-c2-crh16-pdr-hi)] | [1.844304](../claims.md#q-hard-c2-crh16-blackhole) [[1.057380](../claims.md#q-hard-c2-crh16-blackhole-lo), [2.757956](../claims.md#q-hard-c2-crh16-blackhole-hi)] | [7980](../claims.md#q-hard-c2-crh16-bh-losses) | [19](../claims.md#q-hard-c2-crh16-blackhole-n) | [inf](../claims.md#q-hard-c2-crh16-tail) [[inf](../claims.md#q-hard-c2-crh16-tail-lo), [inf](../claims.md#q-hard-c2-crh16-tail-hi)] | [15](../claims.md#q-hard-c2-crh16-tail-n) |
| C2 | snap | [0.962995](../claims.md#q-hard-c2-snap-pdr-mean) [[0.940828](../claims.md#q-hard-c2-snap-pdr-lo), [0.985163](../claims.md#q-hard-c2-snap-pdr-hi)] | [1.844303](../claims.md#q-hard-c2-snap-blackhole) [[1.047838](../claims.md#q-hard-c2-snap-blackhole-lo), [2.772548](../claims.md#q-hard-c2-snap-blackhole-hi)] | [7980](../claims.md#q-hard-c2-snap-bh-losses) | [19](../claims.md#q-hard-c2-snap-blackhole-n) | [inf](../claims.md#q-hard-c2-snap-tail) [[inf](../claims.md#q-hard-c2-snap-tail-lo), [inf](../claims.md#q-hard-c2-snap-tail-hi)] | [15](../claims.md#q-hard-c2-snap-tail-n) |
| C2 | ls_h | [0.998954](../claims.md#q-hard-c2-ls-h-pdr-mean) [[0.998586](../claims.md#q-hard-c2-ls-h-pdr-lo), [0.999321](../claims.md#q-hard-c2-ls-h-pdr-hi)] | [0.051252](../claims.md#q-hard-c2-ls-h-blackhole) [[0.049944](../claims.md#q-hard-c2-ls-h-blackhole-lo), [0.052539](../claims.md#q-hard-c2-ls-h-blackhole-hi)] | [226](../claims.md#q-hard-c2-ls-h-bh-losses) | [19](../claims.md#q-hard-c2-ls-h-blackhole-n) | [0.042408](../claims.md#q-hard-c2-ls-h-tail) [[0.037630](../claims.md#q-hard-c2-ls-h-tail-lo), [0.047187](../claims.md#q-hard-c2-ls-h-tail-hi)] | [0](../claims.md#q-hard-c2-ls-h-tail-n) |
| C2 | o_t | [0.999926](../claims.md#q-hard-c2-o-t-pdr-mean) [[0.999887](../claims.md#q-hard-c2-o-t-pdr-lo), [0.999965](../claims.md#q-hard-c2-o-t-pdr-hi)] | [0.001975](../claims.md#q-hard-c2-o-t-blackhole) [[0.001095](../claims.md#q-hard-c2-o-t-blackhole-lo), [0.002918](../claims.md#q-hard-c2-o-t-blackhole-hi)] | [16](../claims.md#q-hard-c2-o-t-bh-losses) | [19](../claims.md#q-hard-c2-o-t-blackhole-n) | [0.042389](../claims.md#q-hard-c2-o-t-tail) [[0.037605](../claims.md#q-hard-c2-o-t-tail-lo), [0.047174](../claims.md#q-hard-c2-o-t-tail-hi)] | [0](../claims.md#q-hard-c2-o-t-tail-n) |

Visited fallback improves point delivery relative to continue and CRH-16, and its counted
blackhole time is shorter. In C5, its paired blackhole difference against continue is
[-1.246267](../claims.md#q-hard-paired-blackhole-mean) s with paired t interval [[-1.921325](../claims.md#q-hard-paired-blackhole-t-lo), [-0.571209](../claims.md#q-hard-paired-blackhole-t-hi)] s (run-bootstrap interval
[[-1.865710](../claims.md#q-hard-paired-blackhole-boot-lo), [-0.691545](../claims.md#q-hard-paired-blackhole-boot-hi)] s) over [16](../claims.md#q-hard-paired-blackhole-n) common realised-outage runs, with Holm-adjusted p
[0.027790](../claims.md#q-hard-paired-blackhole-p). The corresponding delivery comparison has adjusted p [0.104921](../claims.md#q-hard-paired-pdr-p), so its point
improvement alone does not establish adjusted significance.

**The blackhole advantage needs a qualification.** The frozen metric does not count a
fallback packet that later dies at the hop limit or in a loop, and visited fallback moves
losses into exactly that class. The next table shows the blackhole time next to the counted
losses, the packets sent and delivered, PDR and the TTM censoring for two profiles.

| Shell | Condition identifier | Scheme | Blackhole mean, s | Counted blackhole losses | Packets sent | Packets delivered | PDR | Outages with censored TTM | Realised outages |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| C2 | `link-B` | greedy_visited | [0.000000](../claims.md#q-scope-c2-link-b-gv-bh) | [0](../claims.md#q-scope-c2-link-b-gv-losses) | [216000](../claims.md#q-scope-c2-link-b-gv-sent) | [214932](../claims.md#q-scope-c2-link-b-gv-delivered) | [0.995056](../claims.md#q-scope-c2-link-b-gv-pdr) | [26](../claims.md#q-scope-c2-link-b-gv-ttm) | [26](../claims.md#q-scope-c2-link-b-gv-outages) |
| C2 | `link-B` | ls_h | [0.045837](../claims.md#q-scope-c2-link-b-lsh-bh) | [250](../claims.md#q-scope-c2-link-b-lsh-losses) | [216000](../claims.md#q-scope-c2-link-b-lsh-sent) | [215720](../claims.md#q-scope-c2-link-b-lsh-delivered) | [0.998704](../claims.md#q-scope-c2-link-b-lsh-pdr) | [12](../claims.md#q-scope-c2-link-b-lsh-ttm) | [26](../claims.md#q-scope-c2-link-b-lsh-outages) |
| C5 | `node-B` | greedy_visited | [0.271175](../claims.md#q-scope-c5-node-b-gv-bh) | [33](../claims.md#q-hard-c5-greedy-visited-bh-losses) | [216000](../claims.md#q-scope-c5-node-b-gv-sent) | [215355](../claims.md#q-scope-c5-node-b-gv-delivered) | [0.997014](../claims.md#q-scope-c5-node-b-gv-pdr) | [23](../claims.md#q-scope-c5-node-b-gv-ttm) | [23](../claims.md#q-scope-c5-node-b-gv-outages) |
| C5 | `node-B` | ls_h | [0.048497](../claims.md#q-scope-c5-node-b-lsh-bh) | [236](../claims.md#q-hard-c5-ls-h-bh-losses) | [216000](../claims.md#q-scope-c5-node-b-lsh-sent) | [215764](../claims.md#q-scope-c5-node-b-lsh-delivered) | [0.998907](../claims.md#q-scope-c5-node-b-lsh-pdr) | [12](../claims.md#q-scope-c5-node-b-lsh-ttm) | [23](../claims.md#q-scope-c5-node-b-lsh-outages) |

In C2 `link-B`, visited fallback records a zero blackhole time with zero counted losses, yet
it delivers fewer packets than LS-H, which has a small positive blackhole time. The per-run
loss reasons show that almost all of its losses are hop-limit drops of fallback packets; the
same holds for most of its `node-B` losses in C5. A zero blackhole time therefore means that
no loss was counted, not that no packet was lost, and the shorter blackhole time is not by
itself evidence of fewer lost packets. TTM, a registered secondary endpoint, is censored for
every realised outage under visited fallback: fallback packets still meet the failed element
before turning away, so the condition of delivery without touching the fault never holds.
LS-H observes mitigation in many outages. The TTM comparison therefore cannot support visited
fallback.

**Tail hypothesis.** The registered hypothesis was that visited fallback has no material
effective-tail penalty relative to SNAP or LS-H+BFD. Against LS-H it is not supported.
Visited fallback has infinite-tail runs where LS-H has none, so the effective-latency contrast
is undefined; the material-loss rule needs a finite ratio and can never fire for tails here,
so the empty list of tail material losses is empty by construction, not evidence of no
penalty. The registered fallback is the paired tail-failure indicator (a run scores one when
its effective tail is infinite). For endpoint `effective_p99_s`, visited fallback minus LS-H:

| Shell | Condition identifier | Comparator | Tail-failure indicator difference | Paired t CI |
| --- | --- | --- | --- | --- |
| C5 | `link-A` | ls_h | [0.083333](../claims.md#q-tailind-c5-link-a-mean) | [[-0.011509](../claims.md#q-tailind-c5-link-a-lo), [0.178175](../claims.md#q-tailind-c5-link-a-hi)] |
| C5 | `link-B` | ls_h | [0.166667](../claims.md#q-tailind-c5-link-b-mean) | [[0.038782](../claims.md#q-tailind-c5-link-b-lo), [0.294551](../claims.md#q-tailind-c5-link-b-hi)] |
| C5 | `node-A` | ls_h | [0.111111](../claims.md#q-tailind-c5-node-a-mean) | [[0.003269](../claims.md#q-tailind-c5-node-a-lo), [0.218953](../claims.md#q-tailind-c5-node-a-hi)] |
| C5 | `node-B` | ls_h | [0.138889](../claims.md#q-tailind-c5-node-b-mean) | [[0.020217](../claims.md#q-tailind-c5-node-b-lo), [0.257561](../claims.md#q-tailind-c5-node-b-hi)] |
| C2 | `link-A` | ls_h | [0.055556](../claims.md#q-tailind-c2-link-a-mean) | [[-0.023047](../claims.md#q-tailind-c2-link-a-lo), [0.134158](../claims.md#q-tailind-c2-link-a-hi)] |
| C2 | `link-B` | ls_h | [0.055556](../claims.md#q-tailind-c2-link-b-mean) | [[-0.023047](../claims.md#q-tailind-c2-link-b-lo), [0.134158](../claims.md#q-tailind-c2-link-b-hi)] |
| C2 | `node-A` | ls_h | [0.027778](../claims.md#q-tailind-c2-node-a-mean) | [[-0.028614](../claims.md#q-tailind-c2-node-a-lo), [0.084170](../claims.md#q-tailind-c2-node-a-hi)] |
| C2 | `node-B` | ls_h | [0.055556](../claims.md#q-tailind-c2-node-b-mean) | [[-0.023047](../claims.md#q-tailind-c2-node-b-lo), [0.134158](../claims.md#q-tailind-c2-node-b-hi)] |

In C5 the difference excludes zero at `link-B`, `node-A` and `node-B`: visited fallback
produces infinite tails in more runs than LS-H. In C2 the point differences are smaller and
the intervals include zero. Against SNAP the same indicator favours visited fallback in every
profile of both shells, so the tail penalty is specific to LS-H. O-T does still better but
is privileged.

### E. E5: fallback policies

These results condition on the injected checker decision (condition `trigger`). They do not
estimate how often an actual deadline false alarm would occur.

| Shell | Policy | Triggered completion [t CI] | Triggered stuck/loop rate [t CI] |
| --- | --- | --- | --- |
| C5 | greedy_pure | [0.611111](../claims.md#q-fallback-c5-greedy-pure-pdr-mean) [[0.443826](../claims.md#q-fallback-c5-greedy-pure-pdr-lo), [0.778396](../claims.md#q-fallback-c5-greedy-pure-pdr-hi)] | [0.388889](../claims.md#q-fallback-c5-greedy-pure-stuck-mean) [[0.221604](../claims.md#q-fallback-c5-greedy-pure-stuck-lo), [0.556174](../claims.md#q-fallback-c5-greedy-pure-stuck-hi)] |
| C5 | greedy_visited | [0.833333](../claims.md#q-fallback-c5-greedy-visited-pdr-mean) [[0.705449](../claims.md#q-fallback-c5-greedy-visited-pdr-lo), [0.961218](../claims.md#q-fallback-c5-greedy-visited-pdr-hi)] | [0.166667](../claims.md#q-fallback-c5-greedy-visited-stuck-mean) [[0.038782](../claims.md#q-fallback-c5-greedy-visited-stuck-lo), [0.294551](../claims.md#q-fallback-c5-greedy-visited-stuck-hi)] |
| C5 | grid_detour | [0.777778](../claims.md#q-fallback-c5-grid-detour-pdr-mean) [[0.635116](../claims.md#q-fallback-c5-grid-detour-pdr-lo), [0.920439](../claims.md#q-fallback-c5-grid-detour-pdr-hi)] | [0.222222](../claims.md#q-fallback-c5-grid-detour-stuck-mean) [[0.079561](../claims.md#q-fallback-c5-grid-detour-stuck-lo), [0.364884](../claims.md#q-fallback-c5-grid-detour-stuck-hi)] |
| C5 | continue | [1.000000](../claims.md#q-fallback-c5-continue-pdr-mean) [[1.000000](../claims.md#q-fallback-c5-continue-pdr-lo), [1.000000](../claims.md#q-fallback-c5-continue-pdr-hi)] | [0.000000](../claims.md#q-fallback-c5-continue-stuck-mean) [[0.000000](../claims.md#q-fallback-c5-continue-stuck-lo), [0.000000](../claims.md#q-fallback-c5-continue-stuck-hi)] |
| C5 | drop | [0.000000](../claims.md#q-fallback-c5-drop-pdr-mean) [[0.000000](../claims.md#q-fallback-c5-drop-pdr-lo), [0.000000](../claims.md#q-fallback-c5-drop-pdr-hi)] | [0.000000](../claims.md#q-fallback-c5-drop-stuck-mean) [[0.000000](../claims.md#q-fallback-c5-drop-stuck-lo), [0.000000](../claims.md#q-fallback-c5-drop-stuck-hi)] |
| C2 | greedy_pure | [0.694444](../claims.md#q-fallback-c2-greedy-pure-pdr-mean) [[0.536375](../claims.md#q-fallback-c2-greedy-pure-pdr-lo), [0.852514](../claims.md#q-fallback-c2-greedy-pure-pdr-hi)] | [0.305556](../claims.md#q-fallback-c2-greedy-pure-stuck-mean) [[0.147486](../claims.md#q-fallback-c2-greedy-pure-stuck-lo), [0.463625](../claims.md#q-fallback-c2-greedy-pure-stuck-hi)] |
| C2 | greedy_visited | [1.000000](../claims.md#q-fallback-c2-greedy-visited-pdr-mean) [[1.000000](../claims.md#q-fallback-c2-greedy-visited-pdr-lo), [1.000000](../claims.md#q-fallback-c2-greedy-visited-pdr-hi)] | [0.000000](../claims.md#q-fallback-c2-greedy-visited-stuck-mean) [[0.000000](../claims.md#q-fallback-c2-greedy-visited-stuck-lo), [0.000000](../claims.md#q-fallback-c2-greedy-visited-stuck-hi)] |
| C2 | grid_detour | [1.000000](../claims.md#q-fallback-c2-grid-detour-pdr-mean) [[1.000000](../claims.md#q-fallback-c2-grid-detour-pdr-lo), [1.000000](../claims.md#q-fallback-c2-grid-detour-pdr-hi)] | [0.000000](../claims.md#q-fallback-c2-grid-detour-stuck-mean) [[0.000000](../claims.md#q-fallback-c2-grid-detour-stuck-lo), [0.000000](../claims.md#q-fallback-c2-grid-detour-stuck-hi)] |
| C2 | continue | [1.000000](../claims.md#q-fallback-c2-continue-pdr-mean) [[1.000000](../claims.md#q-fallback-c2-continue-pdr-lo), [1.000000](../claims.md#q-fallback-c2-continue-pdr-hi)] | [0.000000](../claims.md#q-fallback-c2-continue-stuck-mean) [[0.000000](../claims.md#q-fallback-c2-continue-stuck-lo), [0.000000](../claims.md#q-fallback-c2-continue-stuck-hi)] |
| C2 | drop | [0.000000](../claims.md#q-fallback-c2-drop-pdr-mean) [[0.000000](../claims.md#q-fallback-c2-drop-pdr-lo), [0.000000](../claims.md#q-fallback-c2-drop-pdr-hi)] | [0.000000](../claims.md#q-fallback-c2-drop-stuck-mean) [[0.000000](../claims.md#q-fallback-c2-drop-stuck-lo), [0.000000](../claims.md#q-fallback-c2-drop-stuck-hi)] |

The paired policy comparisons below use endpoint `stuck_rate`.

| Shell | Comparison | Stuck-rate difference [paired t CI] | Holm-adjusted p |
| --- | --- | --- | --- |
| C5 | greedy_visited minus greedy_pure | [-0.222222](../claims.md#q-policy-c5-greedy-visited-mean) [[-0.364884](../claims.md#q-policy-c5-greedy-visited-lo), [-0.079561](../claims.md#q-policy-c5-greedy-visited-hi)] | [0.003228](../claims.md#q-policy-c5-greedy-visited-p) |
| C5 | grid_detour minus greedy_visited | [0.055556](../claims.md#q-policy-c5-grid-detour-mean) [[-0.023047](../claims.md#q-policy-c5-grid-detour-lo), [0.134158](../claims.md#q-policy-c5-grid-detour-hi)] | [0.320406](../claims.md#q-policy-c5-grid-detour-p) |
| C2 | greedy_visited minus greedy_pure | [-0.305556](../claims.md#q-policy-c2-greedy-visited-mean) [[-0.463625](../claims.md#q-policy-c2-greedy-visited-lo), [-0.147486](../claims.md#q-policy-c2-greedy-visited-hi)] | [0.000777](../claims.md#q-policy-c2-greedy-visited-p) |
| C2 | grid_detour minus greedy_visited | [0.000000](../claims.md#q-policy-c2-grid-detour-mean) [[0.000000](../claims.md#q-policy-c2-grid-detour-lo), [0.000000](../claims.md#q-policy-c2-grid-detour-hi)] | [1.000000](../claims.md#q-policy-c2-grid-detour-p) |

Visited fallback reduces stuck losses relative to pure greedy in the adjusted paired
comparisons. Grid does not establish additional reduction: its C5 point result is worse and
its C2 result ties visited. Continue retains the healthy planned route and wins on C5
completion in this intervention; drop deliberately sacrifices completion. This exposes the
cost of reacting to a deviation that does not correspond to a service fault.

Stretch and extra-hop means are undefined in some cells; the source reports retain those
missing endpoints. A delivered-only cost cannot be presented as an all-packet latency
benefit. Raw, exact-domain and tolerance-adjusted stretch diagnostics remain separate, and
no raw value is raised to unity to improve the result.

### F. E16: Python and ns-3 agreement

The comparison is a common-random-numbers design, declared in the preregistration: both
engines replay the same pre-generated send-time lists, and nothing else in the model is
random. Per-packet identity is therefore the expected outcome, and every per-packet
comparison record shows zero mismatches. No packet was lost in any run on either engine: PDR
is exactly one and the clean false-flag rate exactly zero everywhere. The PDR and FPR
equivalence results therefore sit at the boundary of the possible range and carry no
information about loss behaviour. The TOST is degenerate: every paired difference is exactly
zero, and the recorded p-values come from the zero-variance branch of the analysis, not from
a t distribution.

The table shows the fault condition (condition `fault`), with paired differences for
delivery/FPR and ratios for latency. Endpoint identifiers `p50` and `p99` are the registered
latency quantiles. Reporting intervals below are the ordinary intervals; TOST also retains
its own equivalence intervals and both one-sided p-values in the CSV.

| Shell | Endpoint identifier | Paired difference or latency ratio | Reporting CI | Registered equivalence bounds | Paired runs |
| --- | --- | --- | --- | --- | --- |
| C5 | pdr | [0.000000](../claims.md#q-agree-c5-pdr-estimate) | [0.000000](../claims.md#q-agree-c5-pdr-lo) to [0.000000](../claims.md#q-agree-c5-pdr-hi) | [-0.010000](../claims.md#q-agree-c5-pdr-lower) to [0.010000](../claims.md#q-agree-c5-pdr-upper) | [36](../claims.md#q-agree-c5-pdr-n) |
| C5 | fpr | [0.000000](../claims.md#q-agree-c5-fpr-estimate) | [0.000000](../claims.md#q-agree-c5-fpr-lo) to [0.000000](../claims.md#q-agree-c5-fpr-hi) | [-0.005000](../claims.md#q-agree-c5-fpr-lower) to [0.005000](../claims.md#q-agree-c5-fpr-upper) | [36](../claims.md#q-agree-c5-fpr-n) |
| C5 | p50 | [1.000000](../claims.md#q-agree-c5-p50-estimate) | [1.000000](../claims.md#q-agree-c5-p50-lo) to [1.000000](../claims.md#q-agree-c5-p50-hi) | [0.952381](../claims.md#q-agree-c5-p50-lower) to [1.050000](../claims.md#q-agree-c5-p50-upper) | [36](../claims.md#q-agree-c5-p50-n) |
| C5 | p99 | [1.000000](../claims.md#q-agree-c5-p99-estimate) | [1.000000](../claims.md#q-agree-c5-p99-lo) to [1.000000](../claims.md#q-agree-c5-p99-hi) | [0.952381](../claims.md#q-agree-c5-p99-lower) to [1.050000](../claims.md#q-agree-c5-p99-upper) | [36](../claims.md#q-agree-c5-p99-n) |
| C2 | pdr | [0.000000](../claims.md#q-agree-c2-pdr-estimate) | [0.000000](../claims.md#q-agree-c2-pdr-lo) to [0.000000](../claims.md#q-agree-c2-pdr-hi) | [-0.010000](../claims.md#q-agree-c2-pdr-lower) to [0.010000](../claims.md#q-agree-c2-pdr-upper) | [36](../claims.md#q-agree-c2-pdr-n) |
| C2 | fpr | [0.000000](../claims.md#q-agree-c2-fpr-estimate) | [0.000000](../claims.md#q-agree-c2-fpr-lo) to [0.000000](../claims.md#q-agree-c2-fpr-hi) | [-0.005000](../claims.md#q-agree-c2-fpr-lower) to [0.005000](../claims.md#q-agree-c2-fpr-upper) | [36](../claims.md#q-agree-c2-fpr-n) |
| C2 | p50 | [1.000000](../claims.md#q-agree-c2-p50-estimate) | [1.000000](../claims.md#q-agree-c2-p50-lo) to [1.000000](../claims.md#q-agree-c2-p50-hi) | [0.952381](../claims.md#q-agree-c2-p50-lower) to [1.050000](../claims.md#q-agree-c2-p50-upper) | [36](../claims.md#q-agree-c2-p50-n) |
| C2 | p99 | [1.000000](../claims.md#q-agree-c2-p99-estimate) | [1.000000](../claims.md#q-agree-c2-p99-lo) to [1.000000](../claims.md#q-agree-c2-p99-hi) | [0.952381](../claims.md#q-agree-c2-p99-lower) to [1.050000](../claims.md#q-agree-c2-p99-upper) | [36](../claims.md#q-agree-c2-p99-n) |

All required endpoints pass the recorded equivalence decision in both the no-fault and
fault conditions, but for the reasons above that pass adds little beyond the per-packet
replay. What the replay does establish is agreement on delivery, queueing (the fault
condition builds long queues behind the rate cut) and deadline flags (many packets arrive
late and are flagged), packet by packet and to the nanosecond. It does not cover loss paths,
because none occurred. The equality is scoped to the implemented model: shared explicit send
lists, no background/jitter, zero processing delay, stable planning, source insertion and
continue policy. It does not validate independent engine randomness, loss handling, ARQ,
other fallback policies or an operational constellation.

## VII. Discussion

Temporal information buys a local test of the planned arrival schedule, not an omniscient
fault detector. The main experiment shows the price of that design at the registered
false-alarm limit. The frozen slack leaves several milliseconds of spare time mid-path, so
the nominal rate cut and the registered added delays mostly stay inside the budget and are
missed, while strong overload and heavier ARQ loss are caught. Looser rules close these blind spots
only by raising clean false alarms far above the limit. LQ sees the queue directly and beats
the deadline check wherever a queue builds; it is the honest benchmark here. The apparent
LS-D advantage is an artefact of a comparator that reads the injected fault delay, and the
wins against LS-H and CRH-16 hold by construction because those schemes cannot detect
slowness at all. The E1 hypothesis is therefore supported only for the strong rate cut and
some ARQ cells.

Detection and mitigation must remain separate conclusions. Hard-failure fallback preserves
delivery and shortens the counted blackhole time, but part of that gain is losses that the
metric does not count (hop-limit and loop drops of fallback packets), its time-to-mitigation
is censored by construction, and it has infinite effective tails in more runs than LS-H, so
the registered no-tail-penalty hypothesis fails against LS-H. Under the healthy-route
intervention, taking a detour can reduce completion and increase cost. The visited policy has
evidence for its specific loop-avoidance purpose; an extra Grid mechanism is not
automatically a better policy. The richer header also has a definite CRH-16 wire cost, and
CRH-32 is smaller than T-CRH at some small entry counts.

Engine agreement is exact within a replay that shares its send lists and loses no packet;
it supports the implementation of delivery, queueing and deadline checking, not the
stochastic equivalence of independent engines. The report accepts the favorable correctness
and agreement evidence while retaining the negative detection and policy comparisons. No
universal ranking follows from a selected scenario, finite delivered latency, an oracle's
information or an undefined comparison.

## VIII. Limitations

**External validity.** Orbital inputs are public, but laser partners, ground assignment,
rates, buffers, traffic and faults are chosen models. Neither this campaign nor agreement
between simulators identifies deployed Starlink routing. The shell excludes high-latitude
pairs, and the short registered scenarios do not represent global demand, long-term churn,
weather, handover engineering or failure-rate measurements.

**Detection operating point.** The frozen rule was chosen on pilot seeds only and meets the
false-alarm limit, but at that limit it mostly misses the nominal rate cut and the
registered added delays. Looser rules detect these faults only above the limit. A different budget rule
or a mixed local-queue and deadline design may do better; none was tested in confirmation.

**Comparator validity.** The LS-D model reads the exact injected fault delay and the expected
ARQ delay, re-advertises any nonzero change and is scored against a twin full of queue-noise
advertisements, so its registered results, including its material losses against
ChronoRoute and ChronoRoute's wins against it, are not valid evidence about slowness
detection. The wins against LS-H and CRH-16 hold by construction. E2E runs with no clean false
flags, so its comparison is not false-alarm matched. Only the LQ comparison is a fair,
practical benchmark, and ChronoRoute loses it.

**Metric scope.** The frozen blackhole metric excludes losses of fallback packets to the hop
limit or loops, so a short or zero blackhole time can coexist with more lost packets. TTM is
censored by construction for visited fallback. The material-loss rule cannot fire for
infinite tails, so an empty tail-loss list is not evidence of no penalty.

**Statistical scope.** Balanced city blocks have limited repeats; they do not support powered
per-city claims. Degenerate intervals can reflect deterministic behavior under the sampled
settings rather than universal certainty, and binary endpoints that are identical in every
run give zero-width t intervals. Some recorded p-values are below the numerical resolution of
the computation and are not reported as numbers. Missing endpoints, censored non-detection,
infinite latency and no-outage seeds have distinct meanings. The full tables retain them.
The absence of an adjusted material loss does not establish superiority or equivalence. One
city pair's path has only two laser links, so its middle and last fault positions are the
same link.

**Correctness gate.** Several E0 rows are self-consistency or model-invariant checks rather
than comparisons with an external reference, and the polar-cutoff check cannot fail on these
shells. The grazing figure is a lower bound, not the exact minimum height.

**Baseline idealisations.** Some table schemes know current light time perfectly; flooding
and SPF omit parts of full protocol behavior; OLSR uses an OSPF-like accounting model. Shared
carrier visibility improves fairness but does not study silent failures equally across
schemes. O-T and O-Q have privileged truth. These are comparison assumptions, not measured
operator implementations.

**Fault mechanism.** The added-link-delay intervention imposes a delay after serialization
without keeping the transmitter busy. It can permit packet overtaking at the interval
boundaries. It isolates a known timing perturbation rather than modelling the physical
mechanism of a slower transmitter; rate cuts and ARQ have distinct queue/service semantics.

**Implementation and deployment.** The visited set lacks a specified wire mechanism. Clock
errors, synchronization, state dissemination, security and hardware forwarding costs remain
untested deployment requirements. Header size is accounted separately from header-free
stretch. Quantisation, saturation and changing geometry can affect deadlines and raw stretch.

**Replay and reproducibility.** Engine agreement uses identical send-time lists and a narrow
service model, and no packet was lost in it, so loss handling is not cross-checked between
engines. Committed producer ledgers preserve commands and hashes, while bulky raw traces
remain in the ignored local caches; reproducing them requires rerunning the recorded
commands. A clean manifest is provenance evidence, not independent validation of realism.
No new experiment was run to write this report.

**Literature coverage.** One topic named in the project guide, CGREB, could not be
identified as a paper or standard; it is marked UNVERIFIED below and provides no evidence.

## IX. Related Work

Compact source routing [R2] and SRv6 [R3] establish wire-format context. T-CRH's additional
claim is a cumulative local timing contract, evaluated with its own cost and failure cases,
not a replacement for the RFCs' deployment analysis.

The closest prior art is the Deterministic Routing Header draft [R9], which the project guide
calls CRH-20. It extends a compact routing header with a per-segment resource field that can
carry, for example, a planned residence time for each hop. T-CRH differs in purpose: it
carries cumulative per-hop deadlines anchored to a per-packet epoch and uses them only to
detect deviation (a flag plus a fallback); it does not schedule or reserve anything.

Segment Routed Time Sensitive Networking (SRTSN) [R10] carries per-router local deadlines in
the segment-routing stack, so that each router knows by when a time-sensitive packet must
leave. Its deadlines drive scheduling; T-CRH's deadlines are cumulative from the ingress
epoch and are only checked on arrival.

Gray failures [R11] are failures that some observers see and others do not, such as a link
that stays up but becomes slow. E1's up-but-slow faults are an instance; T-CRH tries to make
such deviation visible on the data path, and E1 shows where it fails to.

In-situ OAM [R12] records telemetry such as per-node timestamps inside packets for later
analysis. T-CRH instead carries the plan and checks it hop by hop; it records no per-hop
telemetry, and no telemetry-cost comparison is made. STAMP [R6] supplies active measurement
context, while OSPF TE extensions [R5] concern distribution of performance information; the
experiment's baseline models and their favorable idealisations are separate from those
standards.

The IETF time-variant routing (TVR) use cases [R13] include satellite constellations whose
topology changes on a known schedule. T-CRH adds per-hop timing to a source route computed
from such predictions; no TVR mechanism is implemented or compared. Hypatia [R7] establishes a
relevant LEO simulation methodology; the project compares its own SNAP timing model rather
than claiming performance against the original framework.

STARGLIDER [R8] is directly relevant prior work: it delegates path computation to ground
stations and supplies local rerouting and packet validation with routing-oblivious
satellites. Ground computation plus local recovery is therefore not a novelty claim for
ChronoRoute. This draft evaluates its temporal-check mechanism and modelled fallback,
without implementing STARGLIDER as a comparator or asserting performance superiority.

The project guide also names CGREB. No matching paper or standard could be identified, so it
is UNVERIFIED: no authors, venue, algorithm or comparative result is asserted for it.

## X. Conclusion

ChronoRoute demonstrates a tested temporal compact route and an auditable evaluation
pipeline. The correctness gate passes, and Python and ns-3 agree packet for packet in a
loss-free replay. The deadline check detects strong rate-cut overload and some ARQ faults,
but at the registered false-alarm limit it largely misses the nominal rate cut and added
delays up to the largest registered one, and the local queue monitor beats it; the LS-D comparison is
invalid and supports no conclusion either way. Fallback improves delivery, but its shorter
blackhole time partly reflects uncounted fallback losses, and it has a tail penalty against
LS-H. The header costs more than CRH-16, and the Grid detour adds no established benefit. The
useful conclusion is a conditional mechanism with measured trade-offs in MODELLED networks,
with deployment and broader literature claims still open.

## References

Each reference was checked against its primary source. RFC numbers, Internet-Draft names,
reference labels and bibliographic dates identify documents; they are not experimental
measurements and are outside the measurement ledger. Repository design and code links are
implementation evidence, not additional scholarly references.

[R1] S. Deering and R. Hinden, “Internet Protocol, Version 6 (IPv6) Specification,” RFC 8200,
Jul. 2017. [Online]. Available: https://www.rfc-editor.org/rfc/rfc8200

[R2] R. Bonica, Y. Kamite, A. Alston, D. Henriques, and L. Jalil, “The IPv6 Compact Routing
Header (CRH),” RFC 9631 (Experimental), Aug. 2024. [Online]. Available:
https://www.rfc-editor.org/rfc/rfc9631

[R3] C. Filsfils, Ed., D. Dukes, Ed., S. Previdi, J. Leddy, S. Matsushima, and D. Voyer, “IPv6
Segment Routing Header (SRH),” RFC 8754, Mar. 2020. [Online]. Available:
https://www.rfc-editor.org/rfc/rfc8754

[R4] B. Fenner, “Experimental Values in IPv4, IPv6, ICMPv4, ICMPv6, UDP, and TCP Headers,”
RFC 4727, Nov. 2006. [Online]. Available: https://www.rfc-editor.org/rfc/rfc4727

[R5] S. Giacalone, D. Ward, J. Drake, A. Atlas, and S. Previdi, “OSPF Traffic Engineering (TE)
Metric Extensions,” RFC 7471, Mar. 2015. [Online]. Available:
https://www.rfc-editor.org/rfc/rfc7471

[R6] G. Mirsky, G. Jun, H. Nydell, and R. Foote, “Simple Two-Way Active Measurement Protocol,”
RFC 8762, Mar. 2020. [Online]. Available: https://www.rfc-editor.org/rfc/rfc8762

[R7] S. Kassing, D. Bhattacherjee, A. B. Águas, J. E. Saethre, and A. Singla, “Exploring the
‘Internet from space’ with Hypatia,” in *Proc. ACM Internet Measurement Conf. (IMC)*, 2020.
[Online]. Available: https://bdebopam.github.io/papers/imc2020-hypatia.pdf

[R8] S. Vissicchio and M. Handley, “Reliable Low-Delay Routing In Space with
Routing-Oblivious LEO Satellites,” arXiv:2401.11490, Jan. 2024 (STARGLIDER). [Online]. Available:
https://arxiv.org/abs/2401.11490

[R9] S. Peng and R. Bonica, “Deterministic Routing Header,” Internet-Draft
draft-pb-6man-deterministic-crh-00, Mar. 2024, work in progress. [Online]. Available:
https://datatracker.ietf.org/doc/draft-pb-6man-deterministic-crh/00/

[R10] Y. Stein, “Segment Routed Time Sensitive Networking,” Internet-Draft
draft-stein-srtsn-01, Aug. 2021, work in progress. [Online]. Available:
https://datatracker.ietf.org/doc/draft-stein-srtsn/01/

[R11] P. Huang, C. Guo, L. Zhou, J. R. Lorch, Y. Dang, M. Chintalapati, and R. Yao, “Gray
Failure: The Achilles' Heel of Cloud-Scale Systems,” in *Proc. 16th Workshop on Hot Topics
in Operating Systems (HotOS)*, 2017, pp. 150–155, doi: 10.1145/3102980.3103005.

[R12] F. Brockners, Ed., S. Bhandari, Ed., and T. Mizrahi, Ed., “Data Fields for In Situ
Operations, Administration, and Maintenance (IOAM),” RFC 9197, May 2022. [Online]. Available:
https://www.rfc-editor.org/rfc/rfc9197

[R13] E. Birrane, III, N. Kuhn, Y. Qu, R. Taylor, and L. Zhang, “Time-Variant Routing (TVR) Use
Cases,” RFC 9657, Oct. 2024. [Online]. Available: https://www.rfc-editor.org/rfc/rfc9657

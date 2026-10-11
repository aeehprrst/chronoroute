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
and failures. The selected detector meets its recorded false-positive constraint, detects
strong overload, and has important blind spots: local queue and delay-aware link-state
monitors beat it in registered conditions. Fallback improves some delivery outcomes, but
finite-tail baselines can outperform it and the Grid detour does not establish an additional
completion advantage. Engine agreement is strong within the replayed scope. These results
support a tested research prototype, not an operational Starlink routing claim.

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
stack or an evaluation of that paper's reported performance.

### C. Slowness and monitoring

A link can retain carrier while imposing extra service delay. Hello-based adjacency
monitoring and delay monitoring therefore answer different questions. OSPF traffic
engineering metric extensions cover distributing performance information [R5]; the
repository supplies its own MODELLED measurement and installation timing. STAMP provides
an active measurement protocol [R6]. The project does not claim that its simplified
monitors implement every standardized behavior.

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

| Experiment | Prospective expectation | Falsification or losing case |
| --- | --- | --- |
| E0 | Geometry, physics and wire checks satisfy the recorded tolerances. | Any unexplained violation blocks validity. |
| E1 | A pilot-selected rule under the false-alarm cap detects nominal/strong faults more often than LS-H/CRH-16 and faster than LS-D. | The operating constraint fails, or a practical monitor has a material adjusted advantage; small in-budget faults may be missed. |
| E2 | T-CRH buys timing at a CRH-16 cost, saves bytes against SRv6 SRH, and trades off with CRH-32 depending on padding. | Wrong accounting/capture bytes or an unsupported universal saving. |
| E4 | Visited fallback improves delivery and blackholing over continue/CRH-16 without a material effective-tail penalty against SNAP/LS-H. | A practical comparator has a material adjusted delivery, blackhole or tail advantage; undefined tail comparisons cannot establish success. |
| E5 | Visited improves loop avoidance over pure greedy; Grid adds completion or stretch benefit, potentially at extra hop cost. | No additional reduction, or extra cost without completion benefit; continue/drop may win on cost. |
| E16 | Deterministic replay agrees per packet and required stochastic endpoints pass equivalence. | Any unexplained packet mismatch or failure to establish required equivalence. |

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
in the operating-point file. The grid varies rate reduction, extra delay and ARQ by magnitude
and route position, with fluid background load in the detection campaign. Separate
repairable link/node outage profiles test mitigation. Fallback
experiments force a checker decision on the planned path without adding a service fault;
continue is consequently a meaningful healthy-route control.

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

Run-level estimates use Student-t intervals or seeded run-cluster bootstrap intervals,
with [10000](../claims.md#q-bootstrap) resamples where specified. Paired comparisons resample shared run indices;
Holm correction applies within frozen endpoint families. Point disadvantages remain visible
even without adjusted significance. Exact correctness and byte counts have no sampling CI.
The source columns retain the interval coverage: E16 uses `lo95`/`hi95` for ordinary
reporting bounds and `lo90`/`hi90` for the TOST equivalence decision. Other displayed bounds
use the reporting coverage fixed by the preregistered analysis.
Recorded p-values that display as zero are numerical outputs of the analysis, not proof
that the alternative is certain or that the null event is physically impossible.
Proportions and bounds below are copied without clipping: a t interval may extend outside
the physical probability range.

Stretch divides held per-hop light time, processing and header-free serialization by the
send-time faulted graph's matching shortest-path cost. Exact-domain and tolerance-adjusted
lower-bound checks are separate from raw ratios. A path outside that graph is counted and
excluded from the lower-bound claim; a raw step-crossing ratio below unity is not silently
clamped. Header overhead remains an independent cost.

Blackhole time runs from outage onset to the last on-element loss attempt; it is conditional
on realised-outage runs and must show its denominator. Engine equivalence uses paired TOST
at alpha [0.05](../claims.md#q-tost-alpha), with registered absolute PDR/FPR margins and log-ratio latency margins.
All required endpoints must pass; an ordinary nonsignificant difference is insufficient.

## VI. Results

All network outcomes in this section are MODELLED and their statistics DERIVED. REAL refers
to implementation bytes or to the stated orbital inputs, not to deployed network behavior.
The displayed cells are representative evidence, not the whole grid; the ledger links the
full tables and all recorded disadvantage lists.

### A. E0: correctness gate

| Check | Population | Label | Checked | Violations | Worst recorded quantity |
| --- | --- | --- | --- | --- | --- |
| orbit_pinned_full | C5 | REAL | [120200](../claims.md#q-gate-orbit-checked) | [0](../claims.md#q-gate-orbit-violations) | [7.841126](../claims.md#q-gate-orbit-worst) |
| orbit_pinned_ms_epoch | C5 | REAL | [120200](../claims.md#q-gate-epoch-checked) | [0](../claims.md#q-gate-epoch-violations) | [0.298997](../claims.md#q-gate-epoch-worst) |
| isl_grazing | C5 | MODELLED | [3206936](../claims.md#q-gate-physics-checked) | [0](../claims.md#q-gate-physics-violations) | [138.072646](../claims.md#q-gate-physics-worst) |
| wire_browser | C5+C2+golden | REAL | [5866](../claims.md#q-gate-browser-checked) | [0](../claims.md#q-gate-browser-violations) | [0.000000](../claims.md#q-gate-browser-worst) |
| `wire_ns3` | C5+C2+golden | REAL | [5866](../claims.md#q-gate-ns3-checked) | [0](../claims.md#q-gate-ns3-violations) | [0.000000](../claims.md#q-gate-ns3-worst) |
| wire_wireshark_fields | C5+C2+golden | REAL | [10765](../claims.md#q-gate-wireshark-checked) | [0](../claims.md#q-gate-wireshark-violations) | [0.000000](../claims.md#q-gate-wireshark-worst) |


The orbit discrepancy rows are in metres; grazing is a minimum height in kilometres;
wire worst quantities are mismatch counts. The full summary includes C2, exported-orbit
checks, light-time rounding, GSL visibility and great-circle lower bounds, all without
recorded violations. These are acceptance checks, not measurements of orbit prediction
accuracy or proof of continuous-time safety.

### B. E1: slow-link detection

The selected rule meets the recorded pooled clean-FPR constraint in both constellations.
The bounds here are bootstrap intervals over runs. The selected cell-level FPR estimates
also remain below the registered constraint; the full sensitivity sweep is not substituted
for the frozen operating point.

| Constellation | Pooled clean FPR [recorded CI] |
| --- | --- |
| C5 | [0.005862](../claims.md#q-fpr-c5-mean) [[0.004974](../claims.md#q-fpr-c5-lo), [0.006786](../claims.md#q-fpr-c5-hi)] |
| C2 | [0.004134](../claims.md#q-fpr-c2-mean) [[0.003261](../claims.md#q-fpr-c2-lo), [0.005039](../claims.md#q-fpr-c2-hi)] |


Strong and boundary rate cuts are the registered middle-path conditions identified by
`rate-0.2-middle` and `rate-0.3-middle` in the source CSV. Restricted delay uses the full
censoring horizon for missed events, so a small value represents earlier detection.

| Shell | Fault | Scheme | Event detection [recorded t CI] | Restricted delay, s [run-bootstrap CI] |
| --- | --- | --- | --- | --- |
| C5 | Strong middle rate cut | chronoroute | [1.000000](../claims.md#q-detect-strong-cr-mean) [[1.000000](../claims.md#q-detect-strong-cr-lo), [1.000000](../claims.md#q-detect-strong-cr-hi)] | [0.073503](../claims.md#q-delay-strong-cr-mean) [[0.067389](../claims.md#q-delay-strong-cr-lo), [0.079866](../claims.md#q-delay-strong-cr-hi)] |
| C5 | Strong middle rate cut | ls_h | [0.000000](../claims.md#q-detect-strong-lsh-mean) [[0.000000](../claims.md#q-detect-strong-lsh-lo), [0.000000](../claims.md#q-detect-strong-lsh-hi)] | [4.000000](../claims.md#q-delay-strong-lsh-mean) [[4.000000](../claims.md#q-delay-strong-lsh-lo), [4.000000](../claims.md#q-delay-strong-lsh-hi)] |
| C5 | Strong middle rate cut | ls_d | [0.583333](../claims.md#q-detect-strong-lsd-mean) [[0.414158](../claims.md#q-detect-strong-lsd-lo), [0.752509](../claims.md#q-detect-strong-lsd-hi)] | [1.875936](../claims.md#q-delay-strong-lsd-mean) [[1.268400](../claims.md#q-delay-strong-lsd-lo), [2.487899](../claims.md#q-delay-strong-lsd-hi)] |
| C5 | Strong middle rate cut | `e2e` | [1.000000](../claims.md#q-detect-strong-e2e-mean) [[1.000000](../claims.md#q-detect-strong-e2e-lo), [1.000000](../claims.md#q-detect-strong-e2e-hi)] | [0.141239](../claims.md#q-delay-strong-e2e-mean) [[0.125608](../claims.md#q-delay-strong-e2e-lo), [0.158152](../claims.md#q-delay-strong-e2e-hi)] |
| C5 | Strong middle rate cut | lq | [1.000000](../claims.md#q-detect-strong-lq-mean) [[1.000000](../claims.md#q-detect-strong-lq-lo), [1.000000](../claims.md#q-detect-strong-lq-hi)] | [0.016681](../claims.md#q-delay-strong-lq-mean) [[0.015631](../claims.md#q-delay-strong-lq-lo), [0.017749](../claims.md#q-delay-strong-lq-hi)] |
| C5 | Strong middle rate cut | crh16 | [0.000000](../claims.md#q-detect-strong-crh-mean) [[0.000000](../claims.md#q-detect-strong-crh-lo), [0.000000](../claims.md#q-detect-strong-crh-hi)] | [4.000000](../claims.md#q-delay-strong-crh-mean) [[4.000000](../claims.md#q-delay-strong-crh-lo), [4.000000](../claims.md#q-delay-strong-crh-hi)] |
| C5 | Boundary middle rate cut | chronoroute | [0.000000](../claims.md#q-detect-boundary-cr-mean) [[0.000000](../claims.md#q-detect-boundary-cr-lo), [0.000000](../claims.md#q-detect-boundary-cr-hi)] | [4.000000](../claims.md#q-delay-boundary-cr-mean) [[4.000000](../claims.md#q-delay-boundary-cr-lo), [4.000000](../claims.md#q-delay-boundary-cr-hi)] |
| C5 | Boundary middle rate cut | ls_d | [0.611111](../claims.md#q-detect-boundary-lsd-mean) [[0.443826](../claims.md#q-detect-boundary-lsd-lo), [0.778396](../claims.md#q-detect-boundary-lsd-hi)] | [1.859900](../claims.md#q-delay-boundary-lsd-mean) [[1.256761](../claims.md#q-delay-boundary-lsd-lo), [2.472051](../claims.md#q-delay-boundary-lsd-hi)] |
| C5 | Boundary middle rate cut | lq | [1.000000](../claims.md#q-detect-boundary-lq-mean) [[1.000000](../claims.md#q-detect-boundary-lq-lo), [1.000000](../claims.md#q-detect-boundary-lq-hi)] | [1.323159](../claims.md#q-delay-boundary-lq-mean) [[1.297016](../claims.md#q-delay-boundary-lq-lo), [1.346450](../claims.md#q-delay-boundary-lq-hi)] |
| C2 | Boundary middle rate cut | chronoroute | [0.000000](../claims.md#q-detect-c2-boundary-cr-mean) [[0.000000](../claims.md#q-detect-c2-boundary-cr-lo), [0.000000](../claims.md#q-detect-c2-boundary-cr-hi)] | [4.000000](../claims.md#q-delay-c2-boundary-cr-mean) [[4.000000](../claims.md#q-delay-c2-boundary-cr-lo), [4.000000](../claims.md#q-delay-c2-boundary-cr-hi)] |
| C2 | Boundary middle rate cut | ls_d | [0.611111](../claims.md#q-detect-c2-boundary-lsd-mean) [[0.443826](../claims.md#q-detect-c2-boundary-lsd-lo), [0.778396](../claims.md#q-detect-c2-boundary-lsd-hi)] | [1.656031](../claims.md#q-delay-c2-boundary-lsd-mean) [[1.054845](../claims.md#q-delay-c2-boundary-lsd-lo), [2.274892](../claims.md#q-delay-c2-boundary-lsd-hi)] |
| C2 | Boundary middle rate cut | lq | [1.000000](../claims.md#q-detect-c2-boundary-lq-mean) [[1.000000](../claims.md#q-detect-c2-boundary-lq-lo), [1.000000](../claims.md#q-detect-c2-boundary-lq-hi)] | [1.367539](../claims.md#q-delay-c2-boundary-lq-mean) [[1.355871](../claims.md#q-delay-c2-boundary-lq-lo), [1.378908](../claims.md#q-delay-c2-boundary-lq-hi)] |


The mechanism detects strong overload but is blind at the boundary condition where LQ
still detects queue growth and LS-D detects a metric change. Added-delay cells likewise
favor LS-D. This is a registered material loss, not an inconclusive claim based on
visually separate marginal intervals. Representative adjusted comparisons follow; negative
detection differences and positive restricted-delay differences favor the comparator.

| C5 condition identifier | Comparator | Endpoint | ChronoRoute minus comparator [bootstrap CI] | Holm-adjusted p |
| --- | --- | --- | --- | --- |
| `rate-0.3-middle` | ls_d | detected | [-0.611111](../claims.md#q-loss-boundary-mean) [[-0.750694](../claims.md#q-loss-boundary-lo), [-0.444444](../claims.md#q-loss-boundary-hi)] | [1.43e-06](../claims.md#q-loss-boundary-p) |
| `rate-0.3-middle` | lq | detected | [-1.000000](../claims.md#q-loss-boundary-lq-mean) [[-1.000000](../claims.md#q-loss-boundary-lq-lo), [-1.000000](../claims.md#q-loss-boundary-lq-hi)] | [0](../claims.md#q-loss-boundary-lq-p) |
| `delay-1000000-middle` | ls_d | detected | [-0.555556](../claims.md#q-loss-delay-mean) [[-0.722222](../claims.md#q-loss-delay-lo), [-0.388889](../claims.md#q-loss-delay-hi)] | [1.47e-05](../claims.md#q-loss-delay-p) |
| `delay-1000000-middle` | ls_d | restricted_s | [2.071903](../claims.md#q-loss-delay-time-mean) [[1.433494](../claims.md#q-loss-delay-time-lo), [2.694815](../claims.md#q-loss-delay-time-hi)] | [2.64e-05](../claims.md#q-loss-delay-time-p) |


LS-H and CRH-16 do not provide an up-but-slow detector here. E2E can detect strong degradation
without localising its responsible hop. LQ is a practical comparator with privileged *local*
queue visibility, whereas O-Q is an oracle and has no defined detector endpoint in this
campaign; it is a delivery bound, not a failed alarm. The full summary preserves its empty
detection fields. ARQ results vary, and losses before a checker limit deadline attribution.

The selected-rule null controls illustrate the attribution gate; the complete run metrics
and the recorded verdict also cover both constellations, the other rules and native monitors.
No null attribution violation is recorded.

| C5 selected-rule null family | Attributed packets | Event detection probability |
| --- | --- | --- |
| rate | [0](../claims.md#q-null-rate-packets) | [0](../claims.md#q-null-rate-events) |
| delay | [0](../claims.md#q-null-delay-packets) | [0](../claims.md#q-null-delay-events) |
| arq | [0](../claims.md#q-null-arq-packets) | [0](../claims.md#q-null-arq-events) |


### C. E2: header cost

| Encoded entries | T-CRH, bytes | CRH-16, bytes | CRH-32, bytes | SRv6 SRH, bytes |
| --- | --- | --- | --- | --- |
| [4](../claims.md#q-size-entries-4) | [24](../claims.md#q-size-4-tcrh) | [16](../claims.md#q-size-4-crh16) | [24](../claims.md#q-size-4-crh32) | [72](../claims.md#q-size-4-srh) |
| [8](../claims.md#q-size-entries-8) | [40](../claims.md#q-size-8-tcrh) | [24](../claims.md#q-size-8-crh16) | [40](../claims.md#q-size-8-crh32) | [136](../claims.md#q-size-8-srh) |
| [12](../claims.md#q-size-entries-12) | [48](../claims.md#q-size-12-tcrh) | [32](../claims.md#q-size-12-crh16) | [56](../claims.md#q-size-12-crh32) | [200](../claims.md#q-size-12-srh) |
| [40](../claims.md#q-size-entries-40) | [136](../claims.md#q-size-40-tcrh) | [88](../claims.md#q-size-40-crh16) | [168](../claims.md#q-size-40-crh32) | [648](../claims.md#q-size-40-srh) |


These are exact DERIVED source-insertion byte counts, not latency measurements. T-CRH costs
more than CRH-16 throughout the registered table and less than SRv6 SRH; CRH-32 comparisons
change with entry count and padding, so there is no universal saving. Encapsulation adds an
outer-header cost recorded separately in the same summary. Percentage accounting uses a
[1400](../claims.md#q-reference)-byte pre-insertion reference; final-packet fractions use a different denominator.

The REAL capture summary records [83117](../claims.md#q-capture-frames) frames with [8](../claims.md#q-capture-entries) encoded entries and
[40](../claims.md#q-capture-header) header bytes. Captured packet/frame accounting corroborates T-CRH output only;
other protocols' table entries are accounting comparisons, not measured captures.

### D. E4: hard failures

The table shows the registered high node-outage profile `node-B`. PDR includes all seeds;
blackhole means condition on realised-outage seeds. Effective tails count losses as infinite.

| Shell | Scheme | PDR [recorded t CI] | Blackhole, s [run-bootstrap CI] | Outage-run n | Effective tail, s [recorded t CI] | Infinite-tail runs |
| --- | --- | --- | --- | --- | --- | --- |
| C5 | greedy_visited | [0.997014](../claims.md#q-hard-c5-greedy-visited-pdr-mean) [[0.994370](../claims.md#q-hard-c5-greedy-visited-pdr-lo), [0.999658](../claims.md#q-hard-c5-greedy-visited-pdr-hi)] | [0.271175](../claims.md#q-hard-c5-greedy-visited-blackhole) [[0.001365](../claims.md#q-hard-c5-greedy-visited-blackhole-lo), [0.685624](../claims.md#q-hard-c5-greedy-visited-blackhole-hi)] | [16](../claims.md#q-hard-c5-greedy-visited-blackhole-n) | [inf](../claims.md#q-hard-c5-greedy-visited-tail) [[inf](../claims.md#q-hard-c5-greedy-visited-tail-lo), [inf](../claims.md#q-hard-c5-greedy-visited-tail-hi)] | [5](../claims.md#q-hard-c5-greedy-visited-tail-n) |
| C5 | continue | [0.968079](../claims.md#q-hard-c5-continue-pdr-mean) [[0.948134](../claims.md#q-hard-c5-continue-pdr-lo), [0.988023](../claims.md#q-hard-c5-continue-pdr-hi)] | [1.517442](../claims.md#q-hard-c5-continue-blackhole) [[0.945244](../claims.md#q-hard-c5-continue-blackhole-lo), [2.138184](../claims.md#q-hard-c5-continue-blackhole-hi)] | [16](../claims.md#q-hard-c5-continue-blackhole-n) | [inf](../claims.md#q-hard-c5-continue-tail) [[inf](../claims.md#q-hard-c5-continue-tail-lo), [inf](../claims.md#q-hard-c5-continue-tail-hi)] | [14](../claims.md#q-hard-c5-continue-tail-n) |
| C5 | crh16 | [0.968079](../claims.md#q-hard-c5-crh16-pdr-mean) [[0.948134](../claims.md#q-hard-c5-crh16-pdr-lo), [0.988023](../claims.md#q-hard-c5-crh16-pdr-hi)] | [1.517441](../claims.md#q-hard-c5-crh16-blackhole) [[0.945235](../claims.md#q-hard-c5-crh16-blackhole-lo), [2.149786](../claims.md#q-hard-c5-crh16-blackhole-hi)] | [16](../claims.md#q-hard-c5-crh16-blackhole-n) | [inf](../claims.md#q-hard-c5-crh16-tail) [[inf](../claims.md#q-hard-c5-crh16-tail-lo), [inf](../claims.md#q-hard-c5-crh16-tail-hi)] | [14](../claims.md#q-hard-c5-crh16-tail-n) |
| C5 | snap | [0.971671](../claims.md#q-hard-c5-snap-pdr-mean) [[0.956147](../claims.md#q-hard-c5-snap-pdr-lo), [0.987195](../claims.md#q-hard-c5-snap-pdr-hi)] | [1.398185](../claims.md#q-hard-c5-snap-blackhole) [[0.911054](../claims.md#q-hard-c5-snap-blackhole-lo), [1.912758](../claims.md#q-hard-c5-snap-blackhole-hi)] | [16](../claims.md#q-hard-c5-snap-blackhole-n) | [inf](../claims.md#q-hard-c5-snap-tail) [[inf](../claims.md#q-hard-c5-snap-tail-lo), [inf](../claims.md#q-hard-c5-snap-tail-hi)] | [14](../claims.md#q-hard-c5-snap-tail-n) |
| C5 | ls_h | [0.998907](../claims.md#q-hard-c5-ls-h-pdr-mean) [[0.998408](../claims.md#q-hard-c5-ls-h-pdr-lo), [0.999407](../claims.md#q-hard-c5-ls-h-pdr-hi)] | [0.048497](../claims.md#q-hard-c5-ls-h-blackhole) [[0.045544](../claims.md#q-hard-c5-ls-h-blackhole-lo), [0.050768](../claims.md#q-hard-c5-ls-h-blackhole-hi)] | [16](../claims.md#q-hard-c5-ls-h-blackhole-n) | [0.052314](../claims.md#q-hard-c5-ls-h-tail) [[0.044426](../claims.md#q-hard-c5-ls-h-tail-lo), [0.060203](../claims.md#q-hard-c5-ls-h-tail-hi)] | [0](../claims.md#q-hard-c5-ls-h-tail-n) |
| C5 | o_t | [0.999921](../claims.md#q-hard-c5-o-t-pdr-mean) [[0.999876](../claims.md#q-hard-c5-o-t-pdr-lo), [0.999967](../claims.md#q-hard-c5-o-t-pdr-hi)] | [0.001506](../claims.md#q-hard-c5-o-t-blackhole) [[0.000790](../claims.md#q-hard-c5-o-t-blackhole-lo), [0.002263](../claims.md#q-hard-c5-o-t-blackhole-hi)] | [16](../claims.md#q-hard-c5-o-t-blackhole-n) | [0.052211](../claims.md#q-hard-c5-o-t-tail) [[0.044297](../claims.md#q-hard-c5-o-t-tail-lo), [0.060124](../claims.md#q-hard-c5-o-t-tail-hi)] | [0](../claims.md#q-hard-c5-o-t-tail-n) |
| C2 | greedy_visited | [0.998616](../claims.md#q-hard-c2-greedy-visited-pdr-mean) [[0.996655](../claims.md#q-hard-c2-greedy-visited-pdr-lo), [1.000576](../claims.md#q-hard-c2-greedy-visited-pdr-hi)] | [0.001975](../claims.md#q-hard-c2-greedy-visited-blackhole) [[0.001102](../claims.md#q-hard-c2-greedy-visited-blackhole-lo), [0.002903](../claims.md#q-hard-c2-greedy-visited-blackhole-hi)] | [19](../claims.md#q-hard-c2-greedy-visited-blackhole-n) | [inf](../claims.md#q-hard-c2-greedy-visited-tail) [[inf](../claims.md#q-hard-c2-greedy-visited-tail-lo), [inf](../claims.md#q-hard-c2-greedy-visited-tail-hi)] | [2](../claims.md#q-hard-c2-greedy-visited-tail-n) |
| C2 | continue | [0.963056](../claims.md#q-hard-c2-continue-pdr-mean) [[0.940907](../claims.md#q-hard-c2-continue-pdr-lo), [0.985204](../claims.md#q-hard-c2-continue-pdr-hi)] | [1.844305](../claims.md#q-hard-c2-continue-blackhole) [[1.049177](../claims.md#q-hard-c2-continue-blackhole-lo), [2.772433](../claims.md#q-hard-c2-continue-blackhole-hi)] | [19](../claims.md#q-hard-c2-continue-blackhole-n) | [inf](../claims.md#q-hard-c2-continue-tail) [[inf](../claims.md#q-hard-c2-continue-tail-lo), [inf](../claims.md#q-hard-c2-continue-tail-hi)] | [15](../claims.md#q-hard-c2-continue-tail-n) |
| C2 | crh16 | [0.963056](../claims.md#q-hard-c2-crh16-pdr-mean) [[0.940907](../claims.md#q-hard-c2-crh16-pdr-lo), [0.985204](../claims.md#q-hard-c2-crh16-pdr-hi)] | [1.844304](../claims.md#q-hard-c2-crh16-blackhole) [[1.057380](../claims.md#q-hard-c2-crh16-blackhole-lo), [2.757956](../claims.md#q-hard-c2-crh16-blackhole-hi)] | [19](../claims.md#q-hard-c2-crh16-blackhole-n) | [inf](../claims.md#q-hard-c2-crh16-tail) [[inf](../claims.md#q-hard-c2-crh16-tail-lo), [inf](../claims.md#q-hard-c2-crh16-tail-hi)] | [15](../claims.md#q-hard-c2-crh16-tail-n) |
| C2 | snap | [0.962995](../claims.md#q-hard-c2-snap-pdr-mean) [[0.940828](../claims.md#q-hard-c2-snap-pdr-lo), [0.985163](../claims.md#q-hard-c2-snap-pdr-hi)] | [1.844303](../claims.md#q-hard-c2-snap-blackhole) [[1.047838](../claims.md#q-hard-c2-snap-blackhole-lo), [2.772548](../claims.md#q-hard-c2-snap-blackhole-hi)] | [19](../claims.md#q-hard-c2-snap-blackhole-n) | [inf](../claims.md#q-hard-c2-snap-tail) [[inf](../claims.md#q-hard-c2-snap-tail-lo), [inf](../claims.md#q-hard-c2-snap-tail-hi)] | [15](../claims.md#q-hard-c2-snap-tail-n) |
| C2 | ls_h | [0.998954](../claims.md#q-hard-c2-ls-h-pdr-mean) [[0.998586](../claims.md#q-hard-c2-ls-h-pdr-lo), [0.999321](../claims.md#q-hard-c2-ls-h-pdr-hi)] | [0.051252](../claims.md#q-hard-c2-ls-h-blackhole) [[0.049944](../claims.md#q-hard-c2-ls-h-blackhole-lo), [0.052539](../claims.md#q-hard-c2-ls-h-blackhole-hi)] | [19](../claims.md#q-hard-c2-ls-h-blackhole-n) | [0.042408](../claims.md#q-hard-c2-ls-h-tail) [[0.037630](../claims.md#q-hard-c2-ls-h-tail-lo), [0.047187](../claims.md#q-hard-c2-ls-h-tail-hi)] | [0](../claims.md#q-hard-c2-ls-h-tail-n) |
| C2 | o_t | [0.999926](../claims.md#q-hard-c2-o-t-pdr-mean) [[0.999887](../claims.md#q-hard-c2-o-t-pdr-lo), [0.999965](../claims.md#q-hard-c2-o-t-pdr-hi)] | [0.001975](../claims.md#q-hard-c2-o-t-blackhole) [[0.001095](../claims.md#q-hard-c2-o-t-blackhole-lo), [0.002918](../claims.md#q-hard-c2-o-t-blackhole-hi)] | [19](../claims.md#q-hard-c2-o-t-blackhole-n) | [0.042389](../claims.md#q-hard-c2-o-t-tail) [[0.037605](../claims.md#q-hard-c2-o-t-tail-lo), [0.047174](../claims.md#q-hard-c2-o-t-tail-hi)] | [0](../claims.md#q-hard-c2-o-t-tail-n) |


Visited fallback improves point delivery relative to continue and CRH-16 and shortens
blackholing. In C5, its paired blackhole difference against continue is [-1.246267](../claims.md#q-hard-paired-blackhole-mean) [[-1.865710](../claims.md#q-hard-paired-blackhole-lo), [-0.691545](../claims.md#q-hard-paired-blackhole-hi)] s with
Holm-adjusted p [0.027790](../claims.md#q-hard-paired-blackhole-p). The corresponding delivery comparison has adjusted p [0.104921](../claims.md#q-hard-paired-pdr-p),
so its point improvement alone does not establish adjusted significance.

The unfavorable comparison is also clear: LS-H has a finite effective tail while visited
fallback has infinite-tail runs in this profile. O-T does still better but is privileged.
The paired latency contrast is explicitly undefined when infinities prevent arithmetic;
paired PDR and tail-failure indicators are retained. The recorded adjusted analysis finds
no material policy loss under its joint effect/significance rule; this is not evidence of
noninferiority and does not establish the hypothesized universal tail advantage.

### E. E5: fallback policies

These results condition on the injected checker decision. They do not estimate how often
an actual deadline false alarm would occur.

| Shell | Policy | Triggered completion [recorded t CI] | Triggered stuck/loop rate [recorded t CI] |
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

The following fault-condition table uses paired differences for delivery/FPR and ratios
for latency. Endpoint identifiers `p50` and `p99` are the registered latency quantiles.
Reporting intervals below are the ordinary intervals; TOST also retains its own equivalence
intervals and both one-sided p-values in the CSV.

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
fault conditions. Per-packet comparison records separately document matching decisions,
paths, losses and timing, including deterministic replay; matching aggregate endpoints
alone would not prove packet agreement. The equality is scoped to the implemented model:
shared explicit send lists, no background/jitter, zero processing delay, stable planning,
source insertion and continue policy. It does not validate independent engine randomness,
ARQ, other fallback policies or an operational constellation.

## VII. Discussion

Temporal information buys a local test of the planned arrival schedule, not an omniscient
fault detector. The observed overload boundary is consistent with the design: delay inside
the encoded budget need not trigger a flag. LQ can observe the queue before the downstream
deadline fails, and LS-D can advertise performance information without waiting for the same
per-hop timing budget. Increasing sensitivity trades blind spots for clean false alarms.

Detection and mitigation must remain separate conclusions. Hard-failure fallback can
preserve delivery while still producing worse effective tails than LS-H. Under the healthy
route intervention, taking a detour can reduce completion and increase cost. The visited
policy has evidence for its specific loop-avoidance purpose; an extra Grid mechanism is
not automatically a better policy. The richer header also has a definite CRH-16 wire cost.

The report accepts the favorable correctness and agreement evidence while retaining the
negative detection and policy comparisons. No universal ranking follows from a selected
scenario, finite delivered latency, an oracle's information or an undefined comparison.

## VIII. Limitations

**External validity.** Orbital inputs are public, but laser partners, ground assignment,
rates, buffers, traffic and faults are chosen models. Neither this campaign nor agreement
between simulators identifies deployed Starlink routing. The shell excludes high-latitude
pairs, and the short registered scenarios do not represent global demand, long-term churn,
weather, handover engineering or failure-rate measurements.

**Statistical scope.** Balanced city blocks have limited repeats; they do not support powered
per-city claims. Degenerate intervals can reflect deterministic behavior under the sampled
settings rather than universal certainty. Missing endpoints, censored non-detection,
infinite latency and no-outage seeds have distinct meanings. The full tables retain them.
The absence of an adjusted material loss does not establish superiority or equivalence.

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
service model. Committed producer ledgers preserve commands and hashes, while bulky raw
traces remain in the ignored local caches; reproducing them requires rerunning the recorded
commands. A clean manifest is provenance evidence, not independent validation of realism.
No new experiment was run to write this report.

**Literature coverage.** Some requested related-work labels cannot be resolved from the
repository to a verified paper or standard. They are explicitly marked below and provide
no novelty or performance evidence in this draft.

## IX. Related Work

Compact source routing [R2] and SRv6 [R3] establish wire-format context. T-CRH's additional
claim is a cumulative local timing contract, evaluated with its own cost and failure cases,
not a replacement for the RFCs' deployment analysis. Hypatia [R7] establishes a
relevant LEO simulation methodology; the project compares its own SNAP timing model rather
than claiming performance against the original framework. STAMP [R6] supplies active
measurement context, while OSPF TE extensions [R5] concern distribution of performance
information. The experiment's baseline models and their favorable idealisations are
separate from those standards.

STARGLIDER [R8] is directly relevant prior work: it delegates path computation to ground
stations and supplies local rerouting and packet validation with routing-oblivious
satellites. Ground computation plus local recovery is therefore not a novelty claim for
ChronoRoute. This draft evaluates its temporal-check mechanism and modelled fallback,
without implementing STARGLIDER as a comparator or asserting performance superiority.

The remaining requested topics below are named in [the task guide](../NEXT_STEPS.md), but
cannot be attached to a verified repository-named paper or RFC within the allowed citation
set. They provide no comparison evidence in this draft.

| Named topic | Verification status | Permitted conclusion in this draft |
| --- | --- | --- |
| CGREB | UNVERIFIED: no uniquely identified paper in the repository. | No authors, venue, algorithm or comparative result asserted. |
| SRTSN | A primary Internet-Draft was identified, but a repository-named paper/RFC remains UNVERIFIED. | The draft is outside the permitted RFC/paper citation set; no scheduling-novelty claim is made. |
| CRH-20 | UNVERIFIED: no identified paper or specification. | Not treated as the RFC-defined CRH-16/CRH-32 baseline. |
| Gray failures | UNVERIFIED as a specific cited paper; used here only as a description of up-but-slow behavior. | The current slow-link experiment defines its own fault models. |
| IOAM | UNVERIFIED as a particular repository-named RFC or paper. | No telemetry-cost or feature-equivalence claim. |
| IETF TVR | UNVERIFIED as a particular document or evaluated protocol. | Predictable topology is relevant context; no tested TVR comparison. |

These gaps prevent a complete novelty argument. Resolving them requires identifying and
checking the intended sources before expanding this section; a guessed citation would not
repair the gap.

## X. Conclusion

ChronoRoute demonstrates a tested temporal compact route and an auditable evaluation
pipeline. The results support correctness within sampled gates and close engine agreement
within the replay scope. They also show specific detection blind spots, practical-monitor
advantages, header costs, infinite tails under hard failures and unsupported additional
benefit from Grid detour. The useful conclusion is a conditional mechanism with measured
tradeoffs in MODELLED networks, with deployment and broader literature claims still open.

## References

Only RFCs and papers already named in repository documentation are cited. Titles
and supporting passages were checked against the linked primary sources. RFC numbers,
reference labels and bibliographic dates identify documents; they are not experimental
measurements and are outside the measurement ledger. Repository design and code links are
implementation evidence, not additional scholarly references.

[R1] RFC Editor, “Internet Protocol, Version 6 (IPv6) Specification,” RFC 8200.
[Primary text](https://www.rfc-editor.org/rfc/rfc8200).
Already named in `README.md` and `spec/tcrh-v1.md`; extension-header processing verified.

[R2] RFC Editor, “The IPv6 Compact Routing Header (CRH),” RFC 9631.
[Primary text](https://www.rfc-editor.org/rfc/rfc9631).
Already named in `README.md` and `spec/tcrh-v1.md`; CRH processing and mutability verified.

[R3] RFC Editor, “IPv6 Segment Routing Header (SRH),” RFC 8754.
[Primary text](https://www.rfc-editor.org/rfc/rfc8754).
Already named in `spec/tcrh-v1.md`; segment-list format verified.

[R4] RFC Editor, “Experimental Values In IPv4, IPv6, ICMPv4, ICMPv6, UDP, and TCP Headers,” RFC 4727.
[Primary text](https://www.rfc-editor.org/rfc/rfc4727).
Already named in `spec/tcrh-v1.md`; experimental scope verified.

[R5] RFC Editor, “OSPF Traffic Engineering (TE) Metric Extensions,” RFC 7471.
[Primary text](https://www.rfc-editor.org/rfc/rfc7471).
Already named in `docs/baselines.md`; performance-information distribution verified;
measurement and route-selection mechanisms are outside that RFC's scope.

[R6] RFC Editor, “Simple Two-Way Active Measurement Protocol,” RFC 8762.
[Primary text](https://www.rfc-editor.org/rfc/rfc8762).
Already named in `docs/baselines.md`; active measurement scope verified.

[R7] S. Kassing, D. Bhattacherjee, A. B. Águas, J. E. Saethre and A. Singla,
“Exploring the ‘Internet from space’ with Hypatia,” ACM Internet Measurement Conference, 2020.
[Author-hosted paper](https://bdebopam.github.io/papers/imc2020-hypatia.pdf).
Hypatia is already named in `docs/baselines.md` and `docs/sim-config.md`; title, authors,
venue and simulation/visualization scope verified. No performance number is borrowed.

[R8] S. Vissicchio and M. Handley, “Reliable Low-Delay Routing In Space with
Routing-Oblivious LEO Satellites,” arXiv:2401.11490v1, 2024.
[Author-submitted paper](https://arxiv.org/html/2401.11490v1).
STARGLIDER is already named in `docs/NEXT_STEPS.md`; the primary paper verifies the
system name, authors, ground path computation, local rerouting and validation scope.
This citation identifies the preprint; no unverified publication venue or measured
performance comparison is asserted.

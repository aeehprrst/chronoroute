# Baselines and offline evaluation

Status: version 1.0 (2026-10-11). Code: `sim/chronoroute/baselines/` (the comparison schemes) and
`sim/chronoroute/eval/` (metrics, detection scoring, offline re-scoring, statistics). Commands:
`cr eval scheme | score | roc`. Tests: `sim/tests/test_baselines_*.py`, `sim/tests/test_eval_*.py`.

Every baseline here is **real code that sends every packet through the same engine** as
ChronoRoute (`sim/chronoroute/fwd/`): the same send times and packet ids, the same queues, rate
cuts, ARQ, light-time steps, losses in flight and the same random numbers. What differs is
only how a scheme picks the next hop and what its control plane knows, and when. Every control
plane is a **timing model in Python with cited parameters** (labelled `MODELLED`), not a full
protocol stack (master plan P3f: "full protocol stacks are ns-3's job").

## 1. Running a scheme

A run file is an engine config (`docs/sim-config.md`) plus an optional `scheme:` block:

```yaml
seed: 1
scenario: {kind: walker, preset: C1, duration_s: 60}
traffic: {flows: science20, rate_pps: 100}
forwarding: {policy: continue}
faults:
  - {kind: link_down, on_path: {flow: 0}, start_s: 20, stop_s: 40}
scheme:
  name: ls_h
  ls: {preset: ospf, bfd: true}
```

```
cr eval scheme --config run.yaml --out results/x/ls_h-seed1      # one scheme, one seed
cr eval scheme --config run.yaml --scheme snap --out ...          # same file, another scheme
cr eval score results/x/fault --twin results/x/nofault --slack 1.1 1.3 2 --k 2 --out results/x/score
cr eval roc --pairs F1:T1 F2:T2 --slack 1.0 1.05 1.1 1.2 1.5 2 --out results/x/roc
```

`scheme.name` is one of `chronoroute, crh16, e2e, lq, o_t, o_q, snap, ls_h, ls_d`. Unknown keys are
errors. Same seed = byte-identical outputs (tested).

## 2. The schemes

| Scheme | Data plane | Knows | Reacts to a dead link | Reacts to up-but-slow | Header on the wire |
|---|---|---|---|---|---|
| `chronoroute` | engine byte path (T-CRH) | ground schedule | locally after `carrier_detect` (spec 6 step 7) + fallback | deadline at the next node; FB1 reroutes | T-CRH `pad8(12+3n)` |
| `crh16` | same, no deadline check | ground schedule | same as ChronoRoute | never | CRH-16 `pad8(4+2n)` (RFC 9631) |
| `e2e` | same, check at the destination only | ground schedule | same as ChronoRoute | at the destination; reroutes at next refresh | CRH-16 + 8 B deadline/time stamp |
| `lq` | same as crh16 + local monitor | own queue and ARQ counters | same as ChronoRoute | upstream node, when its queue wait > q_th | CRH-16 |
| `o_t` | source route chosen at send time | TRUE topology incl. failures, instantly | 0 s (re-plans from where the packet is) | never | CRH-16 |
| `o_q` | source route chosen at send time | also every queue and slowness | 0 s | 0 s (upper bound) | CRH-16 |
| `snap` | hop-by-hop tables | predicted geometry; failures after telemetry + upload | tables after `carrier_detect + telemetry + wait for upload (+ latency)`; meanwhile, from `carrier_detect` on, drop or +Grid detour | never | none |
| `ls_h` | hop-by-hop tables | carrier loss, LSA flooding, SPF | after `carrier_detect` + flood + SPF (silent-failure option: dead interval or BFD instead of `carrier_detect`) | never | none |
| `ls_d` | hop-by-hop tables | ls_h + RFC 7471 delay metrics | as ls_h | after a measurement window + flood + SPF, if the change > threshold | none |

### 2.1 Parameters and where they come from

| Setting | Value(s) | Source |
|---|---|---|
| OLSR hello / hold | 2 s / 6 s (`ls.preset: olsr`) | RFC 3626 §18.2 HELLO_INTERVAL = 2 s, §18.3 NEIGHB_HOLD_TIME = 3 × REFRESH_INTERVAL = 6 s |
| OLSR, LEO-tuned | 1 s / 3 s (`olsr_leo`, default) | the RFC 3626 1:3 ratio with a faster hello: the plan's "best LEO setting" (fairness rule 1); a modelling choice, not an RFC default |
| OLSR TC after a link failure | sent at once (no MinLSInterval) | RFC 3626 §9.3: "a TC-message SHOULD be transmitted after an interval shorter than TC_INTERVAL" |
| OSPF hello / dead | 10 s / 40 s (`ospf`) | RFC 2328 App. C.3: HelloInterval "Sample value for a local area network: 10 seconds"; RouterDeadInterval "some multiple of the HelloInterval (say 4)" |
| OSPF MinLSInterval | 5 s | RFC 2328 App. B |
| LSA refresh | 30 min (every preset) | RFC 2328 App. B LSRefreshTime |
| BFD | 3 × 100 ms (`ls.bfd: true`) | RFC 5880 §6.8.4: detection time = Detect Mult × agreed transmit interval; 100 ms × 3 is a typical setting, not an RFC default |
| SPF delay | 50 ms | RFC 8405 §6 INITIAL_SPF_DELAY default (the back-off to 200 ms / 5 s under churn is not modelled: favours LS) |
| LS-D window M | {1, 5, 30} s, default 30 s | RFC 7471 §7: "the default measurement interval for all sub-TLVs should be 30 seconds"; values are averages (§3) |
| LS-D threshold θ | {0.1, 0.2, 0.5}, default 0.2 | RFC 7471 §5 "accelerated advertisement thresholds" (no numeric default in the RFC) |
| LS-D inter-update | 120 s; at most 1 announcement / s | RFC 7471 §7 ("default value should be set to 120 seconds", "minimum announcement periodicity is 1 announcement per second") |
| LS-D variant | `avg` or `min` | RFC 7471 §4.1.5 average delay; §4.2 min/max; §1: a propagation-delay measurement "SHOULD NOT include queuing delays" |
| SNAP Δ_up / telemetry | {0.1, 1, 15} s / {1, 10, 60} s | master plan P3f, science report §4 (Hypatia-style per-step tables) |
| FB1 | 50 ms one way, ×{2, 10, ∞}, hold {10, 60} s | master plan P3d, E8 |
| LQ threshold q_th | {1, 2, 5} ms | reviewer must-fix #2; science report E9 truth label |
| Failure detection (every scheme) | `forwarding.carrier_detect_ms`, default 0 (immediate) | MODELLED: a laser or radio receiver notices loss of signal within its own frame time; one value for every scheme (§2.3), swept as a sensitivity |
| ChronoRoute CRH-FIB + station table re-upload | every 4 h (`crh_state.fib_refresh_s`) | master plan §3 data cadence "CelesTrak: SupGP (every 4 h)": the planner's data, and so what the ground can re-send, changes every 4 h (MODELLED choice) |
| ChronoRoute element-set re-upload (fallback) | every 4 h (`crh_state.ephemeris_upload_s`) | same cadence; each satellite gets its own and its laser partners' element sets (MODELLED) |

### 2.2 How each control plane is timed

**O-T, O-Q (oracles).** At send time the oracle picks a cheapest path on the TRUE network
(`knowledge.Truth`): the geometry of the current 100 ms step minus every link or satellite
failed at that instant. O-T weights are light time + processing + serialization of the flow's
packet; O-Q adds every node/link slowness active now, the expected ARQ delay and the current
wait of every transmit queue (it asks each queue when its Dijkstra reaches it). If a link of the
route dies on the way, the oracle re-plans from the current node.

**SNAP (Hypatia-style tables).** Geometry is predictable, so tables are precomputed for every
100 ms step and every destination station (one shortest-path tree per destination, like
Hypatia's forwarding state). Failures are not predictable: a failure at `t_c` reaches the ground
after `telemetry_s`; tables computed at upload instant `U` (every `update_s`) use the failures
that happened by `U − telemetry_s`, and are active from `U + upload_latency_ms`. Closed form
(tested): a link that fails at `t_c` is routed around from `ceil((t_c + T_tel) / Δ_up) · Δ_up
+ latency`. Meanwhile a satellite whose next hop is dead drops the packet or takes one +Grid
detour hop (`fwd.fallback.grid_detour`), after which the next satellite uses its own table.

**LS-H (hello link state).** Every node has its own view.
* A failure (`link_down` fault, or a satellite down) is noticed by each end by loss of carrier,
  `forwarding.carrier_detect_ms` after it starts (`ls.fault_detection: carrier`, the default):
  the same instant at which ChronoRoute's step 7, SNAP and LQ notice it (§2.3). The link is
  declared alive again at the next hello.
* Silent-failure option (`ls.fault_detection: hello`, a sensitivity analysis, NOT like-for-like:
  the other schemes still notice the carrier loss, and `run.json` `scheme.failure_visibility`
  says so): each end notices the failure only when no hello has arrived for the dead interval:
  with hellos at `phase + n·H`, the end declares the neighbour dead at `r + D` (r = last hello
  received) if no hello arrives in `(r, r + D]`. Hello phases are keyed random numbers
  (`baselines/keyed.py`), so two LS runs with the same seed see the same timers. With BFD the
  same rule runs with 100 ms / 300 ms.
* A geometric change (a link out of range, a ground-link handover) is a loss of carrier: both
  ends notice it after `carrier_detect_ms` (0); a new link comes up at the next hello.
* The end originates a router-LSA (at most once per MinLSInterval; changes within it are batched
  into the deferred LSA). Node X learns it at `origination + flood time to X + SPF delay`, the
  flood time being the cheapest path over the links that are really up (light time + per-hop LSA
  processing, default the 0.5 ms forwarding processing).
* X uses a link only when the latest LSAs it knows from **both** ends list it (the OSPF two-way
  check, RFC 2328 §16.1): one end's "down" removes it, "up" needs both.
* Slowness is invisible. During flooding different nodes hold different views, so transient
  micro-loops can happen (they end by the IPv6 hop limit).
* Closed forms (tested): with carrier detection the upstream node of a failed link stops using
  it at `onset + carrier_detect + SPF` (its own LSA needs no flooding); with silent failures
  (olsr_leo, olsr, ospf, BFD) at `r + D + SPF`, i.e. the blackhole lasts
  `D − (onset − r) + SPF ∈ (D − H + SPF, D + SPF]`.

**LS-D (delay-aware link state).** LS-H plus per-direction delay metrics. A link direction is
measured when it can show an excess delay: it has a link-delay, rate-cut or ARQ fault, or its
transmit queue exists (it has carried a probe packet). Every other link has no queue and no
fault, so its measured delay is exactly its light time. Probes every `probe_ms` (STAMP, RFC 8762)
sample `queue wait + link-delay fault + expected ARQ delay`; at the end of each window of `M`
seconds the measured excess is the mean (`avg`) or the minimum (`min`) of the samples. It is
advertised when `|new − advertised| > θ · (light time + advertised)` (accelerated, not more than
once per `min_interval_s`) or when the inter-update period has passed, and nodes learn it like
any LSA. A slow-processing fault at a NODE is not part of a link measurement and stays invisible.

**ChronoRoute, CRH-16, E2E, LQ.** These use the engine's own forwarding on the T-CRH bytes and
the ground's planned paths (`fwd/scenario.py`). CRH-16 calls the spec 6 function with the
packet's own Epoch_Base as "now", which can never be late, so its paths and fallbacks are
exactly ChronoRoute's (tested); E2E does the same except at the destination, where it checks the
final deadline `D_h` (the end-to-end budget). LQ looks, before a node uses its next link, at its
own transmit queue (`queue_delay_estimate`) plus the mean ARQ retransmission delay of the packets
it sent on that link in the last `arq_window_ms` (computed from the same keyed draws the engine
uses); above `q_th` it flags the packet, or (`action: detour`) treats the link as unusable for this
one decision, so the engine's own step 7 and fallback function take over.

**Feedback (FB1, E2E).** A FB1 report names the link the late packet arrived on
(`path[k−1] → path[k]`); an E2E report names the packet's path (`localize: path`: all its
satellite-to-satellite links; `intersect`: only the links shared by all late paths reported in
the last `window_s`). A report reaches the ground `delay_ms` later; from the next refresh on, the
planner chooses paths with that link's weight × penalty (or without it, `inf`) for `hold_s`
seconds (a new report extends the hold). The deadlines of a penalised path are still computed
from its TRUE predicted delays (`baselines/feedback.py`). Tested closed form: with a 1 s refresh
and the first late packet just after 2 s, the reroute starts at 3 s.

### 2.3 Failure visibility: one model for every scheme

A failed link loses packets at once (the truth, `Engine.faults`), but a node can only route
around a failure once it has NOTICED it. Every scheme notices a failure of one of its own links
(a `link_down` fault, or the neighbour satellite down) by loss of carrier after the same delay,
`forwarding.carrier_detect_ms` (default 0, MODELLED), through the engine's view `Engine.seen`
(`fwd/faults.FaultSet.detected_view`):

* ChronoRoute, CRH-16, E2E, LQ: spec 6 step 7 (next link down) and the fallback's neighbour choice;
* SNAP: its satellite's dead-next-hop check (drop or +Grid detour), and its telemetry reports a
  failure from the moment it was noticed;
* LS-H / LS-D: the link end's carrier detection (`ls.fault_detection: carrier`, default; a
  different `ls.carrier_detect_ms` is refused), then its LSA and SPF delay.

The ORACLES (O-T, O-Q) see the true state at once: that is what makes them upper bounds. Packets
sent onto a failed link before it is noticed are lost in flight, for every scheme alike. A
failure shorter than the delay is never noticed; a recovery is noticed at once (the carrier
returns). Geometric link changes are predictable: ChronoRoute and SNAP plan with the predicted
geometry, while LS learns them as loss of carrier (the same delay) and hellos.
The silent-failure option of LS (`ls.fault_detection: hello`: dead interval or BFD) is a
sensitivity analysis only: `run.json` `scheme.failure_visibility.like_for_like` is false and
says why, and the scheme label ends in `silent`. Every scheme run carries the label
`failure_detection_model: MODELLED`. Closed forms tested (`test_one_failure_visibility_model_for_every_scheme`):
losses on a failed link stop at `onset + carrier_detect` for ChronoRoute and SNAP (detour), at
`onset + carrier_detect + 50 ms` (SPF) for LS-H.

### 2.4 Idealisations (they favour the baselines; state them with results)

* O-T, SNAP, LS-H and LS-D know the true light time of every link at the current step (perfectly
  tuned metrics). LS-D only adds its measured excess on top. This isolates what the experiments
  are about: how fast a control plane reacts to failures and slowness.
* No SPF back-off under churn, no LSA retransmissions, hello propagation time ignored (ms
  against seconds).
* OLSR presets use the same OSPF-like flooding byte model (no MPR selection) and do not pay for
  periodic TC messages (TC_INTERVAL 5 s): their control bytes are underestimated.
* A node cut off from a flood is treated as learning the change when the flood completes
  elsewhere.
* For table schemes, a destination with no table entry at the ingress counts as `no_route`
  (the packet is never transmitted), like a planner gap.

## 3. Control bytes, header bytes and state (kept apart)

`control.json` counts every message per **medium** and per message type: `uplink` (ground →
satellite), `isl`, `downlink` (satellite → ground; a fourth medium, not hidden in another),
`ground` (ground-internal). Sizes are counted from the RFC packet figures (`baselines/control.py`):
hello 80 B (IPv6 40 + OSPFv3 header 16 + Hello 24, RFC 5340 A.3.1-A.3.2), BFD 72 B (IPv6 + UDP +
24, RFC 5880 §6.8.7), one router-LSA flood copy `40+16+4+20+4+16·d` B (A.3.5, A.4.2, A.4.3),
LSAck 76 B per received copy, TE-delay LSA (RFC 7471 §4.1: 8-byte delay sub-TLV, §4.2: 12-byte
min/max), STAMP probe + reflection 2 × (40 + 8 + 44) B (RFC 8762 §4.2.1). A flooded LSA is
counted on every link it crosses: satellites relay floods, ground stations do not, so a flood
from a satellite of component c costs `Σ deg_isl − (n_sat − 1)` ISL copies plus one copy down
each ground link (checked against a brute-force flood on C1). SNAP: diff-encoded table entries
(6 B: destination SID, next-hop SID, valid-from step) plus a 56 B message header per satellite
per upload, on the uplink to the nearest satellite with a ground link and on each of the h − 1
laser hops relaying it on (`snap_table_upload_relay`; h = fewest links from any station at the
upload instant); telemetry 64 B from each live end of a failed link (downlink + ISL relay hops to
the nearest station). ChronoRoute / CRH-16 / E2E / LQ (reviewer must-fix #3: "Count the
FIB/SID-map uploads, ephemeris uploads ..."):
* one schedule row per (flow, refresh) to the ingress gateway on the ground network;
* `crh_fib_refresh`: every satellite is sent its CRH-FIB, one 4 B entry (SID → interface) per
  laser partner and per ground station (any station's ground link can come up), plus, with a
  fallback function, the station table (12 B coordinates per station), with a 56 B header,
  every `crh_state.fib_refresh_s` (4 h);
* `ephemeris_upload` (only with a fallback function): the element sets of the satellite and of
  its laser partners (140 B TLE-sized records each) + 56 B, every `crh_state.ephemeris_upload_s`
  (4 h);
* both at keyed phases per satellite (so a run shorter than the period is charged the right
  fraction of satellites, and paired runs see the same instants), on the uplink plus h − 1 laser
  relay hops (`*_relay` on `isl`), exactly as SNAP's uploads. The SID registry is stable and
  append-only (keyed by NORAD id), so no SID map is re-sent beyond the station table. The
  quantile budgets use a static per-hop σ prior (`eval/offline.py`), so there is no σ telemetry
  to count; a measured-σ planner would have to add it. `crh_state.count: false` turns the
  charge off (the state report stays). A run much shorter than the period charges only the
  satellites whose phase falls inside it (often none on C1), so `control.json` also gives the
  exact amortised rate `crh_state_uploads.steady_state_bytes_per_s` (DERIVED: Σ size / period on
  the uplink, × (h − 1) on the ISLs, h at the first step), and `cr eval score` reports it as
  `crh_state_upload_bytes_per_s_steady`;
* FB1 reports 64 B down; E2E reports 64 B on the ground.

Header bytes (`hdr_bytes` per packet) and satellite state (`control.json` → `state`: CRH-FIB,
station table and fallback ephemeris for ChronoRoute, with the same sizes as the uploads; table
size for SNAP; LSDB size for LS) are reported separately and never added to control bytes
(master plan 5.3; reviewer must-fix #3).

## 4. Outputs of a scheme run

The folder is a normal trace/1 run (`spec/trace-v1.md`), plus:

| File | Content |
|---|---|
| `scheme_packets.csv.gz` | per packet: `arrival_ns` at every node after the source, `hop_prop_ns` (light time of each hop at the step in which the packet was at its upstream node), `hop_k` (what spec 6 did at each arrival: `k ≥ 1` a deadline check at hop k; `−2−k` the destination of a detoured packet; `−1` nothing), `hdr_bytes`, `l_det_ns`, `oracle_ns` (L*), `oracle_hops`, `oracle_ok`, `tol_ns`, `lq_flag` (`hop:node:next:t`), `lq_flags`, `e2e_late`, `drop_next` (dead next hop of a packet dropped there), `link_down_at` (`node:next:t`, first dead next link a table / oracle packet met), `tx_ns` (per hop, aligned with `arrival_ns`: when the transmission onto the hop's link started), `wait_ns` (how long it waited for the transmitter) and `tx_loss_at` (`node:next:t:wait` of a packet lost AT THE TRANSMITTER of `node → next`: `buffer_overflow` with t = when it tried to join the full FIFO and wait −1, `arq_exhausted` or a link end without a position with t = the transmission start; such a path ends at `node`, so this is the only record of the link) |
| `scheme_events.csv.gz` | control-plane detections: `adjacency_down` (LS) and `metric` (LS-D), time = when the first node installed it |
| `control.json` | control bytes per medium/type, state, scheme statistics, FB1/E2E penalties, `crh_state_uploads` (crh data plane: uploads charged, unreachable satellites, periods), `failure_visibility` |
| `run.json` → `scheme` | name, label, settings, data plane, header on the wire, the stretch step tolerance, `failure_visibility` (§2.3); `engine.config` holds the full engine config (so `fwd/rerun.py` can repeat the run) |

For `crh16`, `e2e` and `lq` the trace `hex` field shows the engine's internal T-CRH bytes
(`run.json` says so: `trace_hex_is_internal_tcrh`); their wire size is the scheme's own header.
Table schemes have `sl`, `flags` and `hex` null (no routing header). Pcap capture is written only
for the `chronoroute` scheme.

## 5. Evaluation layer (master plan 5.3, reviewer must-fix #1)

**PDR (per flow-run).** Delivered / sent among packets sent in `[warm-up, T_end − drain)`; the
engine only sends in that window, so in-flight packets are never counted as losses; losses are
always split by reason (`no_route`, `unfinished`, and every engine drop reason).

**Quantiles.** Nearest rank `r = ceil(p·n)`. Effective quantile: over all sent packets with a
lost packet = +∞; if fewer than r were delivered the result is ∞. Tail rule: P99 only with
≥ 10³ packets in the flow-run, P99.9 only with ≥ 10⁴.

**Latency stretch** = `L_det / L*`.
* `L_det` = Σ over the packet's hops of (light time of the link at the step in which the packet
  was at its upstream node + processing + serialization of the flow's packet WITHOUT any routing
  header). Header size is reported as header bytes, not as stretch.
* `L*` = the cheapest path on the TRUE faulted graph at the send instant (geometry of the send
  step, links and satellites failed at that time), same weights.
* Reported minimums: `min` is over the packets that stayed in their send step (`tol = 0`) and
  whose path was in the send-time graph, so it is ≥ 1 EXACTLY unless an exact violation is
  reported; `min_tol_adjusted` = min `(L_det + tol) / L*` over every packet the claim covers;
  `min_raw` (and `median`, `mean`, `max`) are raw `L_det / L*` over all delivered packets and may
  be a little below 1 for step-crossing packets without anything being wrong.
* Claim, checked for every delivered packet: `L_det ≥ L* − tol`, where `tol = Σ_hops (steps
  elapsed since the send at the hop's upstream node) × 5,340 ns`. Why: a light time changes by
  at most `16 km/s × 0.1 s / c = 5,337 ns` per 100 ms step (two LEO satellites approach at
  < 16 km/s; distance and its rate are the same in every frame), rounded up, plus 2 ns for the
  nearest-ns rounding of two held delays. A packet that stays in its send step has `tol = 0`:
  stretch ≥ 1 exactly, in integers. A relative tolerance of 10⁻⁶ (~50 ns) would fire falsely
  (reviewer should-fix 5: ~1.2 µs on a ground link in 50 ms). Packets whose path used a link
  that was not in the send-time graph (it came up or was repaired on the way) are counted
  (`n_path_not_in_send_graph`) and excluded from the claim. O-T has stretch exactly 1 whenever
  `tol = 0` (tested). Queueing = latency − `L_det`. Hop stretch uses the fewest hops on the same
  graph.

**Packet labels and FPR.** `fault`: met a faulty element while it was active, by crossing it
(a link: the TRANSMISSION onto it started in the fault interval, `tx_ns`, which is where the
engine applies a link delta, the ARQ draws and the rate in force, after processing and queueing
at the upstream node; a rate cut also covers the packets that started after it stopped while its
backlog was draining, up to the first packet on that link direction that found the transmitter
idle; a node: at its arrival) or by being LOST on it (dropped at the link's transmitter,
`tx_loss_at`: a drop-tail `buffer_overflow` under a rate cut, `arq_exhausted` under ARQ; lost in
flight on a link a fault took down, judged at its arrival, when the engine decides the loss; or
arriving at a dead node), or met a link a fault had down as its dead next link; `stale`: met a
geometrically dead next link, or was lost in flight because its link ceased to exist;
`congested` (with `q_th`): some hop exceeded light + processing + serialization by more than
`q_th`; else `clean`. FPR = clean packets flagged by a DEADLINE check / clean packets (link-down
and stale deviations are never deadline false positives). A packet a fault dropped is never
`clean`: it could not be flagged downstream, so in the clean denominator it would bias the FPR
down (C1, a rate cut to 0.002 with ISL background ρ = 0.3 dropped 280 packets at the cut link
that were labelled clean before this rule; `test_fault_drops_are_exposed_and_never_clean`).

**Counterfactual detection.** Run every fault scenario twice with the same seed and policy
`continue`: with the fault and without it (the twin). Every random draw is keyed, so the twin
has the same traffic, jitter and background, and the same background failures (renewal periods
are keyed by each fault's identity, not its list position: docs/sim-config.md §6). The pair is
CHECKED before scoring (`detection.check_twin`): same packets (count, send times, flows) and the
twin's fault log equal to the fault run's minus the scored fault, entry by entry (null faults
ignored, so a phantom twin is accepted); a twin whose other faults differ is refused; and the
same configuration otherwise: `run.json` `engine.config` without its fault list and output
options, and the scheme (name and every setting), must be equal, so a twin built with another
jitter, slack, policy, carrier-detection delay or scheme is refused with the differing keys named
(it has the same packets and faults, but its flags differ for reasons unrelated to the fault).
`cr eval score --twin` and `cr eval roc` score only the faults the twin does not have
(`detection.scored_faults`), and exit with an error on a refused pair. Packets are paired by id. A
packet is a true detection when it crossed the faulty element after onset (and went on: exposure
part `crossed`), is flagged in the fault run and is not flagged in the twin. **Packets the fault
dropped** on its element (full FIFO, ARQ give-up, lost in flight on a downed link, arriving at a
dead node) never reach a checker, so they cannot be detected by any deadline check: they are
reported separately as `lost_at_fault`, not in `exposed` (the P_det denominator), with `exposed +
lost_at_fault = reached` (every packet that crossed the element or was lost on it). With a
fault-free twin, `reached` is exactly the set of packets whose outcome or latency changed for a
rate cut with fluid ISL background ρ = 0.3 (tested); in general it contains every changed packet
(ARQ also reaches packets whose first try succeeded; with Poisson background the drain end is an
upper bound). Their loss is in the PDR, by reason. **Phantom control:** a fault that changes nothing (`slow_processing`
with `delta_ns: 0`, `rate_cut` with `factor: 1`) gives exactly 0 attributed detections and 0
detected events, at every slack (tested) — while the old metric ("an exposed packet carried a
flag") is not 0 there.

**Event detector and ROC.** The detector fires on element e when k flags blaming e arrive within
`(t − W, t]`, then counts afresh. A deadline flag at hop k blames `(path[k−1], path[k])`; an LQ
flag the link it was about to use; an E2E flag is not localised (it matches a fault when one of
the flagged packets crossed it). A fault event is detected at τ if the fault run fires on its
element at τ ∈ [onset, onset + horizon) and the twin does not fire on that element within
`[τ − W, τ + W]` (the same event would have happened anyway). False events per hour = detector
events of the twin / sending hours. Event ROC = (false events / h, P_det) over a threshold
sweep. LS schemes: `control_plane_detection` uses the first node that installed an adjacency
or metric change.

**Detection delay** = τ − onset per event; undetected events are censored at the horizon and
summarised with a Kaplan-Meier CDF (`kaplan_meier`, `km_median`). Absolute timestamps are never
averaged.

**Time-to-mitigation.** Affected flows: flows with a packet that touched the fault. Packets of
those flows are binned by send time (100 ms); TTM = the first bin start b ≥ onset such that every
non-empty bin in `[b, b + 1 s)` has ≥ 95 % of packets delivered without touching the fault (the
window must end before the fault does; otherwise censored at the fault's duration). When no
packet touched the fault at all (e.g. O-Q avoided it from the start) there is nothing to mitigate:
`affected_flows` is empty and TTM is reported as undefined (null), not as 0.
**Blackhole** = last packet lost ON the faulty element (attempt time) − onset.

**Offline threshold scoring** (`eval/offline.py`). Under policy `continue` a deadline flag never
changes a packet's path or timing, so from ONE flag-and-continue run the deadline checks of any
rule can be recomputed exactly: `D_k = Epoch + Σ encoded deltas` with the deltas from
`chronoroute.proto.encode_deltas` (the planner's own function) on budgets built from the schedule
row's predicted hop delays (multiplicative S, additive, or quantile `P_k + ceil(z_(1−α)·σ·√k)`
with a static per-hop σ prior), in any unit (arrival times are kept in ns). Equivalence with
DIRECT runs is tested packet by packet (first late hop and every recorded deadline) for S = 1.1,
1.25, 2 and for units 1 ms and 0.25 ms. Two conditions are checked, not assumed: the run used
policy `continue` (else refused), and the planner's rows do not depend on the rule
(`check_plans` re-plans every row; the "stable" planner's look-ahead uses the final budget).

**Statistics** (`eval/stats.py`, numpy only). The unit is the RUN. t intervals (not z) with
Student t quantiles from the regularized incomplete beta function; paired differences (same
seed = common random numbers) with t interval and p-value; cluster bootstrap over runs,
percentile or BCa (jackknife acceleration), 10,000 resamples, seeded; `"ratio"` statistic for
pooled proportions such as PDR; Holm-Bonferroni step-down adjusted p-values. Special functions
are checked against published values in the tests. No survivorship bias: a per-run value of
+inf (an effective quantile of a run that lost too many packets) is never dropped; it makes the
t interval infinite (`n_inf` counts such runs) and every bootstrap resample that contains it
infinite (so `hi` is inf and `lo` is finite only if enough resamples miss it). NaN per-run
values are refused; only bootstrap resamples whose ratio is 0/0 are left out, and counted
(`n_boot_undefined`). Runs holding both +inf and −inf in one column are refused by the t
interval, the paired test and the bootstrap alike (a resample with both is inf − inf, undefined),
as is an infinite ratio denominator.

## 6. Engine hooks

`baselines/engine.py` subclasses `fwd.engine.Engine` and relies on these methods and attributes
of it: `_on_send`, `_on_arrive`, `_transmit`, `_enqueue` (returns `(transmission start, end)`
when an arrival was scheduled, else None), `_link_drop` (a packet lost at a link's transmitter:
which link, when, its wait; it only finishes the packet in the engine), `_finish`, `_lost`, `_plan_interval`,
`_check_delivery`, `_sends_in`, `_push`, `geo`, `port`, `port_to`, `queue`, `_port_geo`,
`_fp`, `faults` (the truth: losses), `seen` (what nodes have noticed: decisions), `carrier_ns`,
`current`, `schedule_rows`, `counts`, `per_flow`, `fb_reasons`. A test checks that the
`chronoroute` scheme is byte-identical to `cr run`, so any change of these semantics is caught.

## 7. Cost

Shortest-path trees are pure Python (5-8 ms each on the real 463 km shell). Measured on the
real shell, science20 flows, 10 s (+2 s drain), 1 % ISL renewal faults (MTTR 2 s), seed 1, one
process, 4 GB address-space cap (wall time / peak RSS, 2026-10-11, after the fixes of this
version): chronoroute 28 s / 292 MB (incl. the stretch oracle and the satellite uploads), o_t
37 s / 303 MB, snap 34 s / 465 MB (all destination tables every step, for upload bytes), ls_h
557 s / 578 MB. Earlier measurements: o_q 140 s (one queue-aware Dijkstra per packet), ls_d
62 s (before the carrier default). Runs on C1 take about a second. `outputs.stretch_oracle:
false` and `snap.count_uploads: false` skip the two optional costs.

**Why LS-H is slow under churn.** With the shared carrier detection (§2.3) every one of the
~27 laser-link failures per second (1 % of ~5,400 links) and every repair is noticed and flooded
(before, with the hello default, most 2 s outages were never noticed), and every node keeps its
own exact view, so while floods are under way the nodes hold thousands of different views. Two
measures keep this exact and bounded: (1) a decision is answered from a SHARED tree (the step's
snapshot, or the current settled view) whenever that provably gives the node's own answer
(`LinkState._shortcut`; the proof is in its docstring and every shortcut answer is checked
against a full computation in `test_ls_shortcut_gives_every_node_its_own_answer`); it took the
run above from 951 s to 557 s with identical outputs (same deliveries, drops and control bytes);
(2) every cache is bounded (`BoundedCache`): without that the same run grew past 6.6 GB and was
killed by the out-of-memory killer. A real-shell LS-H campaign at this churn therefore costs
about 45 s per simulated second; C1/C2 or lower churn are cheap.

## 8. Limitations

* Control planes are timing models; ns-3 is where protocol stacks run.
* LS-D measures only links that can show an excess (faulty or carrying probes); with Poisson
  background an unused link's random queue is not sampled.
* LQ evaluates the ARQ fault window at the packet's ready time, the engine at its transmission
  start (they differ only when a queue wait spans the fault boundary).
* O-T/O-Q keep the CRH-16 header size of the first route after a re-plan.
* The rate-cut drain is seen through foreground packets only: with Poisson background the queue
  may empty and refill between two probes unseen, so the drain end is an upper bound (such
  packets are labelled `fault`, never `clean`).
* ChronoRoute's uploads assume a satellite that no station can reach at the upload instant
  simply waits (counted in `crh_state_uploads.unreachable`, not charged).
* There is no silent-failure detector for the non-LS schemes: a silent failure can only be
  studied as the LS sensitivity option (§2.3).
* The E2E `intersect` localisation is the simplest tomography (intersection of late paths).
* OLSR is modelled with OSPF-like flooding (see §2.4); DRA, GPSR and LS-TVR are deferred
  (reviewer "cut or defer").

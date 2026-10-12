# Simulator v2: `cr run` and its configuration

```
cr run --config FILE [--seed N] --out DIR
```

runs one simulation of ChronoRoute and writes the run folder described in
[`spec/trace-v1.md`](../spec/trace-v1.md): `run.json`, `events.jsonl.gz`, `packets.csv.gz`,
`schedule.csv.gz`, `summary.json`, optional `capture.pcap`, and `manifest.json`. The exit
code is 0 when packet conservation holds and no invariant check failed, 1 otherwise, 2 for
a bad configuration.

The code is `sim/chronoroute/fwd/` (engine, queues, faults, fallbacks, RNG, topology,
scenario, presets, config); tests are `sim/tests/test_fwd_*.py`.

## 1. What a run does

1. **Scenario.** (a) A shell of the REAL fleet from a pinned snapshot (default
   `data/pinned/20261010T1358Z-celestrak`, SupGP, shell `53.2deg-463km`: 3,119 members, of
   which the 2,847 in its 104 planes are used, 272 off-grid satellites left out), or (b) a
   synthetic Walker preset (C1, C2, C2b), generated as OMM element sets and pushed through the
   same pipeline. Cities from `data/static/cities.csv`.
2. **Truth topology every step** (100 ms): Grid-4 laser links and ground links exactly as
   `cr export bundle` builds them (the code is reused: `orbit/planes`, `topo/isl_grid4`,
   `topo/gsl`, `topo/geometry`). It is streamed in chunks (`chunk_steps`), so memory stays flat
   for long runs. Faults are applied on top of it.
3. **Predicted schedule** every `refresh_ms` (1 s): the ground plans each flow with the
   bundle's planner (`stable`: only links that stay up until the interval's last packet meets
   its final deadline), `route/scheduler.plan_path` (canonical Dijkstra, integer ns), budgets
   `B_k = slack x sum of (light time + planner_processing_ns)`, T-CRH template. The ground
   does not know about faults.
4. **Forwarding from the header bytes.** The ingress stamps Epoch_Base per packet and runs
   spec §6 steps 5-7; every node runs spec §6 on the bytes (deadline check, policy, SL
   decrement, CRH-FIB lookup, next-link-down check) or, for a packet in GREEDY mode, the
   fallback function. `hop_mode: fast` uses a byte-level implementation proved identical to
   `chronoroute.proto` (test_fwd_hop.py, plus `verify_every`); `reference` calls
   `chronoroute.proto` at every hop.
5. **Links.** Per-direction FIFO with the Lindley recursion, serialization `size x 8 / C`
   (ns-3 rounding), drop-tail buffer, optional background load, held light time, fault
   effects.
6. **Common random numbers**: every draw is keyed by (seed, component, entity, index), so a
   fault run and its fault-free twin use identical numbers (rng.py).

What is modelled (labels in every `run.json` and manifest): link rate, buffers, processing
delay, jitter, background traffic, traffic, faults, the fallback functions: MODELLED.
Positions: REAL (SGP4 on REAL elements) for the real fleet, MODELLED for synthetic presets.
Shells/planes, routes, budgets: DERIVED. Header bytes: REAL code output.

## 2. File format

JSON, or the plain YAML subset below (`sim/chronoroute/fwd/config.py`; the project has no
YAML library, so anchors, tags, multi-line strings and multiple documents are refused):

```yaml
# comment
seed: 1
scenario:
  kind: walker            # comments after values are fine
  cities: [London, "New York"]
traffic:
  flows:
    - src: London
      dst: New York
    - {src: Tokyo, dst: Sydney, rate_pps: 50}
faults:
- kind: rate_cut
  link: [1998, 2017]
  factor: "0.0002"
  start_s: 4
  stop_s: 7
```

Every key must be known (a typo is an error); omitted keys take the defaults below.
Seconds may be given as numbers or decimal strings and must be whole nanoseconds
(`"4.000000001"`); factors, loads and probabilities are read exactly from their decimal text
(`0.3` is 3/10).

## 3. `scenario`

| Key | Default | Meaning |
|---|---|---|
| `kind` | `real` | `real` (snapshot shell) or `walker` (synthetic preset) |
| `snapshot` | `data/pinned/20261010T1358Z-celestrak` | pinned folder (repo-relative or absolute), verified against its SHA256SUMS |
| `source` | `supgp` | `supgp` or `gp` |
| `shell` | `53.2deg-463km` | shell id (`cr fleet report` lists them) |
| `preset` | `C1` | Walker preset (§3.1) when `kind: walker` |
| `start_utc` | `2026-10-10T14:00:00Z` | t0 (planes, slots and Grid-4 pairs are chosen here) |
| `duration_s` | 60 | packets are sent in `[0, duration)` |
| `drain_s` | 5 | extra time for packets in flight; whatever is still on its way at `duration + drain` is `unfinished` |
| `step_ms` | 100 | truth topology step |
| `chunk_steps` | 200 | steps per streamed topology chunk |
| `cities` | null | ground stations; null = the cities of the flows (in order of first use) |
| `gsl.min_elevation_deg` | 25 | elevation mask (ASSUMED value of the Starlink filing) |
| `gsl.max_links_per_gs` | 4 | links per station |
| `gsl.policy` | `sticky_top_k` | ground-link policy (`topo/gsl.py`) |
| `isl.polar_cutoff_deg` | 70 | cross-plane links off above this latitude |
| `isl.max_range_km` | null | optional laser range limit |

### 3.1 Walker presets (MODELLED)

| Preset | Planes x per plane | Altitude | Inclination | Phasing F |
|---|---|---|---|---|
| C1 | 24 x 20 (480) | 550 km | 53 deg | 1 |
| C2 | 72 x 22 (1,584) | 550 km | 53 deg | 39 (Hypatia `D:550:53:1584/72/39`) |
| C2b | 72 x 22 (1,584) | 480 km | 53 deg | 39 |

Circular orbits, RAAN `360 p / P`, mean anomaly `360 s / S + 360 F p / T`, catalogue numbers
9,000,000 + 1000 p + s (never written to the SID registry).

## 4. `traffic`

| Key | Default | Meaning |
|---|---|---|
| `flows` | `science20` | the 20 fixed science pairs (all 20 exist in `cities.csv`; "São Paulo" is spelled "Sao Paulo" there), or a list of flows (below) |
| `rate_pps` | 100 | packets per second per flow |
| `payload_bytes` | 200 | UDP payload |
| `model` | `cbr` | `cbr` (constant rate) or `poisson` (exponential gaps, keyed RNG) |
| `start_offset` | `random` | offset of the first packet in ns, or `random` (uniform in the first period, keyed RNG) |
| `ingress_mode` | `source` | `source` (the host inserts the T-CRH, Next Header 17) or `encap` (gateway encapsulation: +40 B outer IPv6, Next Header 41; spec §8) |
| `l2_overhead_bytes` | 2 | link-layer bytes per frame (PPP, as ns-3) |

A flow is `{src, dst}` plus any of `rate_pps`, `model`, `start_offset`, `payload_bytes`, or
`send_times_ns: [..]` (explicit send times in ns after t0, strictly increasing; used to replay
ns-3 probes exactly). Wire size of a packet = `l2 + 40 + T-CRH + (40 if encap) + 8 + payload`.

Note on the real 463 km shell: with a 25 deg mask it covers latitudes up to about 60.5 deg, so
Reykjavik-Toronto and Anchorage-Oslo have no path (their packets are `no_route`).

## 5. `schedule` and `forwarding`

| Key | Default | Meaning |
|---|---|---|
| `schedule.refresh_ms` | 1000 | Delta_r, a multiple of `step_ms` |
| `schedule.slack` | `"1.5"` | multiplicative slack S (exact) |
| `schedule.unit_code` | 1 | deadline unit (0.1 ms) |
| `schedule.plan_links` | `stable` | `stable` or `instant` (docs/bundle-format.md §1.4) |
| `schedule.planner_processing_ns` | 500000 | per-hop processing the PLANNER assumes in its budgets |
| `forwarding.policy` | `greedy` | deviation policy, spec §6 step 4: `greedy`, `continue` (flag and keep the SIDs; for offline scoring), `drop` |
| `forwarding.fallback` | `greedy_visited` | `greedy_visited` (legacy), `greedy_pure`, `grid_detour`, `none` (`fwd/fallback.py`) |
| `forwarding.hop_limit` | 64 | IPv6 Hop Limit: a packet is dropped (`hop_limit` / `loop`) after this many transmissions |
| `forwarding.processing_ns` | 500000 | per-hop processing actually applied at every transmitting node (ns-3 cross-check: 0) |
| `forwarding.jitter.model` | `none` | `j1`: exponential processing jitter per hop (legacy J1) |
| `forwarding.jitter.mean_ns` | 400000 | J1 mean |
| `forwarding.link_rate_bps` | 1000000000 | C |
| `forwarding.buffer_ms` | 20 | drop-tail buffer = `buffer_ms x C` bytes per link direction |
| `forwarding.background.model` | `none` | `fluid` or `poisson` (§5.1) |
| `forwarding.background.rho` | 0 | offered background load per link, fraction of C |
| `forwarding.background.packet_bytes` | 1500 | Poisson background packet size |
| `forwarding.background.window_ms` | 10 | Poisson background generation window (part of the RNG key) |
| `forwarding.background.links` | `all` | `all` or `isl` |
| `forwarding.hop_mode` | `fast` | `fast` (byte path proved equal to chronoroute.proto) or `reference` (chronoroute.proto every hop) |
| `forwarding.verify_every` | 0 | with `fast`: re-run every N-th header operation through chronoroute.proto and stop on a difference |
| `forwarding.slow_queue_ns` | null | `grid_detour` treats a link as slow (avoids it) when its own transmit queue would hold a packet longer than this |
| `forwarding.carrier_detect_ms` | 0 | how long a node takes to NOTICE that one of its links failed (loss of carrier: a `link_down` fault, or the neighbour satellite down). Every routing decision (spec §6 step 7, the fallback's neighbour choice, and in `cr eval scheme` SNAP's dead-next-hop check, LQ and the link-state carrier detection) sees a failure only this long after it starts; packets sent onto the link meanwhile are lost in flight. A failure shorter than this is never noticed; a recovery is noticed at once. MODELLED; 0 = immediate. One value for every scheme (docs/baselines.md §2.3) |

### 5.1 Background cross-traffic (MODELLED)

* `fluid`: an exact solution of a fluid FIFO: background is a constant stream of `rho x C`
  into the same queue (backlog kept as integers, buffer-capped, excess fluid counted as
  lost). It captures overload and slow drain (e.g. a rate cut below `rho`), but adds no
  queueing to a sparse probe when the link is not overloaded.
* `poisson`: exact packet-level M/D/1 cross-traffic: Poisson arrivals of fixed-size packets
  into the same FIFO and buffer, generated per link and window from keyed streams (so a fault
  run and its twin see the same background). Vectorised between foreground packets; long
  idle gaps skipped exactly by coupling from the past. Costs about `rho x C / packet_bytes`
  background packets per used link-second (41,667 at rho = 0.5, 1500 B, 1 Gb/s), so it is
  meant for smaller runs and for validation (the M/D/1 mean wait is checked in
  test_fwd_queues.py).

## 6. `faults` (MODELLED, ground truth in `run.json`)

| `kind` | Keys | Effect |
|---|---|---|
| `link_down` | target, `start_s`, `stop_s` | link down in both directions |
| `link_renewal` | `unavailability` U, `mttr_s`, `targets` (`isl` / `gsl` / `all`), optional `start_s`/`stop_s` | every target link alternates exponential up (MTBF = MTTR (1-U)/U) and down (MTTR) periods, stationary start |
| `node_down` | node target, `start_s`, `stop_s` | satellite outage: its links are down, packets reaching it are lost |
| `node_renewal` | `unavailability`, `mttr_s` | every satellite alternates as above |
| `slow_processing` | node or link target, `delta_ns`, `start_s`, `stop_s` | up but slow (a): Delta added to processing at the node, or to the transit of the link (see the note below) |
| `rate_cut` | link target, `factor` f, `start_s`, `stop_s` | up but slow (b): link rate f x C (queues build by themselves) |
| `arq` | link target, `loss` p, `max_retries` (3), `retry_extra_ns` (100000), `start_s`, `stop_s` | up but slow (c): each lost attempt adds 2 x propagation + retry_extra; drop after the last |

There is no "multiply the propagation delay" model: light time is fixed by geometry.

**The link variant of `slow_processing` is a MODELLED "per-packet extra link latency".** Delta is
added after serialization, decided at the transmission start, and the transmitter is NOT kept
busy, so there is no physical mechanism behind it and packets can overtake each other at the
fault's start and stop (one sent just after the stop arrives before one sent just before it).
It is useful as a clean, known Delta for detection tests; headline experiments should prefer
`rate_cut`, `arq` or the NODE variant of `slow_processing`, which have a mechanism (a slower
transmitter, retransmissions, a slower processor).

**Fault identity.** Each entry is identified by what it does (kind, interval, target and
parameters, normalised: `2`, `2.0` and `"2"` seconds are the same), not by its position in the
list. The random up/down periods of `link_renewal` / `node_renewal` are keyed by that identity,
so removing or adding OTHER faults never redraws them: the counterfactual twin of a run (the
same run without one fault) has exactly the same background failures. Two identical entries
are told apart by their order among identical entries. `run.json` logs the identity as
`params.fault_id` (spec/trace-v1.md §1.3).

Targets: `link: [a, b]` (node ids), `link_names: [name_a, name_b]`, `node: id`,
`node_name: name`, or `on_path: {flow, at_s, position, kind}`: a link (or, with
`kind: node`, a satellite) on the flow's planned path at `at_s` (default: the fault start).
`position` is `first`, `middle` (default) or `last` third of the candidate hops (the middle
hop of that third), or a hop number; `kind` is `isl` (laser links only, default), `any`, or
`node`.

## 7. `output`

| Key | Default | Meaning |
|---|---|---|
| `trace` | `sampled` | `full`, `sampled`, `none` (spec/trace-v1.md §4) |
| `sample_every` | 100 | one packet in N (per flow, keyed) is sampled: full story in `sampled` traces, header hex, pcap |
| `pcap` | false | write `capture.pcap` for sampled packets |
| `pcap_max_packets` | 20 | at most this many packets in the capture |
| `packets_csv` | true | write `packets.csv.gz` |
| `invariants` | `sample` | `all` (every packet; a violation stops the run), `sample` (one packet in `invariant_sample_every` per flow, violations counted), `off` |
| `invariant_sample_every` | 100 | |

Invariants checked: per hop, light time used >= distance / c at that step (rounding
tolerance 0.5 ns) and hop delay >= distance / c; end to end, latency >= great-circle / c; an
on-schedule packet's hop index equals the hops it has taken and SL reaches 0 exactly at the
destination; packet conservation (sent = delivered + dropped + no_route + unfinished) on
every run. Forwarding reads only the header bytes (test: garbling the planner's Python path
and SIDs after the template is built changes no output).

**Reading `summary.json`.** Per flow, `latency_ns_p50` / `latency_ns_p99` are nearest-rank
quantiles OF DELIVERED PACKETS ONLY (`latency_quantiles_of` says so): lost and route-less packets
do not appear in them, so read them next to `pdr`, or use `latency_eff_ns_p50` /
`latency_eff_ns_p99`, the effective quantiles over every sent packet with a lost one counting as
+inf (`"inf"` when more than 1 - p of the packets were not delivered; eval/metrics.py has the
measurement-window version). Speed: `hop_events_per_s_forwarding` counts forwarding only
(planning and topology building excluded: the engine's own speed); `hop_events_per_s_loop` the
whole event loop; `hop_events_per_s_end_to_end` the whole command (scenario build and output
writing too: what a user waits for). For example, the 600 s real-shell run did 109k hop
events/s forwarding but about 65k/s end to end (16.2 M hop events in 247.7 s).

**Re-running with one more fault.** `chronoroute.fwd.rerun.rerun_with_fault(run_dir, flow=,
link=(a, b), start_ns=, kind="rate" | "slow" | "down")` repeats a run from its `run.json`
(`engine.config`: the complete normalised config, same seed) with one extra fault on one link,
writing a new run folder with its manifest. Every random number is the same, so only packets
that meet the new fault change (`test_fwd_rerun.py`). The viewer's live mode (`d`, `f`) uses it.
Re-running a re-run keeps the faults added before; `run.json` `rerun.live_faults` lists them all
(oldest first) and `rerun.original` names the recorded run the chain started from.

## 8. Examples

```bash
# the real shell, 20 science pairs x 100 pps, 600 s: about 4 minutes and 0.6 GB on the
# WSL laptop (i9-13900H); my.yaml holds only "scenario: {kind: real, duration_s: 600}"
cr run --config my.yaml --seed 1 --out /tmp/cr-sb/run600

# the tiny synthetic preset with a slow link on flow 0's path, flag-and-continue
cat > c1.yaml <<'EOF'
scenario: {kind: walker, preset: C1, duration_s: 30, gsl: {min_elevation_deg: 10}}
traffic: {flows: [{src: London, dst: New York}, {src: Tokyo, dst: Los Angeles}]}
forwarding: {policy: continue, jitter: {model: j1}}
faults:
- {kind: slow_processing, on_path: {flow: 0, position: middle}, delta_ns: 2000000, start_s: 10, stop_s: 20}
EOF
cr run --config c1.yaml --seed 3 --out /tmp/cr-sb/c1
```

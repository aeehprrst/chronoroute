# chronoroute.trace/1: run trace format

Status: version 1.1 (2026-10-11). Shared by the Python simulator v2 (`cr run`, writer
`sim/chronoroute/trace/writer.py`), the ns-3 converter and the viewer. The reader and
validator is `sim/chronoroute/trace/reader.py` (`validate_run(dir)` returns every problem it
finds; an empty list means the folder follows this document).

A run is a folder:

```
<run>/run.json            what the run is (one JSON object)
<run>/events.jsonl.gz     what happened (one JSON object per line, gzip)
```

The simulator also writes engine outputs next to them (§5); they are not part of trace/1.

All times are **integer nanoseconds**. Event times `t` are nanoseconds after `t0` (the run's
time 0); the GPS instant of an event is `t0_gps_ns + t` (spec/tcrh-v1.md §4: GPS = UTC + 18 s).
No floating-point value appears in `events.jsonl.gz`.

## 1. run.json

One JSON object. These keys are required, in this order (writers keep the order; readers
must not depend on it):

| Key | Type | Meaning |
|---|---|---|
| `schema` | string | `"chronoroute.trace/1"` |
| `tool` | string | `"python-sim"` or `"ns-3"` |
| `t0_utc` | string | t0 as ISO 8601 UTC ending in `Z` |
| `t0_gps_ns` | int | t0 on the GPS timescale, ns since 1980-01-06T00:00:00 |
| `unit_code` | int | T-CRH deadline unit code 0..3 of the run (spec §3); every `deadline_u` / `now_u` is in this unit |
| `snapshot_id` | string or null | the orbit snapshot (e.g. `20261010T1358Z-celestrak`, or `synthetic-walker-C1`) |
| `bundle` | string or null | the ns-3 bundle directory the run replayed (null for `python-sim` runs built from a snapshot) |
| `nodes` | list | every node, index = node id (§1.1) |
| `positions` | object | where node positions come from (§1.2) |
| `faults` | list | the ground-truth fault log (§1.3) |
| `labels` | object | honesty labels `{name: "REAL" \| "DERIVED" \| "MODELLED"}` |

Writers may add further keys; readers ignore what they do not know. `python-sim` adds:

* `engine`: `version`, `seed`, `config_sha256`, `shell`, `step_ns` (topology step),
  `duration_ns` (sending window), `end_ns` (end of drain), `drain_ns`, `processing_ns`,
  `link_rate_bps`, `l2_overhead_bytes`, `policy`, `fallback`, `slack`, `refresh_ms`,
  `carrier_detect_ns` (how long a node takes to notice a failed link, shared by every scheme:
  docs/baselines.md 2.3), `trace_level` (`full` / `sampled`), `sample_every`, and `config`: the
  run's complete normalised configuration (docs/sim-config.md), so the run can be repeated
  exactly (`fwd/rerun.py`, the viewer's live mode);
* `flows`: `[{flow_id, src, dst, src_node, dst_node, rate_pps, model, payload_bytes,
  great_circle_km}]` (`rate_pps` is an exact decimal or fraction string);
* `scheme` (runs of `cr eval scheme`, docs/baselines.md 4): `name`, `label`, `settings`,
  `data_plane` (`crh`, `oracle`, `table`), `header_on_wire`, `trace_hex_is_internal_tcrh`,
  `step_tolerance_ns`, `failure_visibility` (the failure-detection model and whether the run is
  like-for-like with the other schemes);
* `rerun` (a live-mode re-run, `fwd/rerun.py`): `of` (the run folder that was re-run), `flow`,
  `kind` (`rate`, `slow`, `down`) and `fault` (the config entry that was added); `original` (the
  recorded run the chain of re-runs started from) and `live_faults` (every fault live mode has
  added, oldest first, each `{"kind", "fault"}`: re-running a re-run keeps the faults added before,
  so all of them are active in this run).

### 1.1 nodes

`nodes[i]` describes node id `i` and has exactly these keys:

| Key | Satellite | Ground station |
|---|---|---|
| `node_id` | `i` | `i` |
| `kind` | `"sat"` | `"gs"` |
| `sid` | T-CRH SID (registry, 1..0xEFFF) | 0xF000 + g |
| `norad` | NORAD catalogue number; **null** for synthetic satellites | null |
| `name` | CelesTrak `OBJECT_NAME` (or `WALKER-<preset>-Ppp-Sss`) | city name |
| `lat`, `lon` | null | WGS84 degrees (from `data/static/cities.csv`) |

Numbering is the bundle's (docs/bundle-format.md §2.3): satellites of the shell's planes
sorted by NORAD id (0..S-1), then the ground stations (S..S+G-1).

### 1.2 positions

`{"source": "snapshot" | "bundle", "path": string}`.

* `"snapshot"`: `path` names an OMM JSON file (a JSON array of CelesTrak-style element sets).
  Satellite positions at event time `t` are SGP4 on those elements at UTC `t0 + t`, converted
  TEME -> ECEF as in `sim/chronoroute/orbit` (the engine uses exactly that code). A path that
  starts with `data/` is relative to the repository root (e.g.
  `data/pinned/20261010T1358Z-celestrak/starlink_supgp.json`); any other path is relative to the
  run folder (synthetic presets write `synthetic_omm.json` there). Satellites are matched by
  `NORAD_CAT_ID` = `nodes[i].norad`, or, for synthetic satellites (norad null), by
  `OBJECT_NAME` = `nodes[i].name`.
* `"bundle"`: `path` is a scenario bundle directory (docs/bundle-format.md), or any folder that
  holds at least its `positions.csv` (and, for the laser links, `isl.csv`); positions come from
  `positions.csv` (SGP4 samples every `position_step_ms`, 1 s; a reader interpolates between
  them and must say so). The path is resolved like a snapshot path: absolute as is, starting
  with `data/` relative to the repository root, anything else relative to the run folder
  (`cr trace from-ns3` copies the bundle files into `<run>/bundle/` and writes `"bundle"`).
  The run-level `bundle` key is resolved the same way.

The engine holds link delays constant for each topology step (`engine.step_ns`, 100 ms):
the delay of a hop is the light time at the start of the step in which the packet starts
to transmit (ns-3 does the same; docs/course-milestone.md §2.2).

### 1.3 faults (ground truth)

One entry per fault interval actually applied, sorted by `start_ns`:

| Key | Type | Meaning |
|---|---|---|
| `kind` | string | `link_down`, `node_down`, `slow_processing`, `rate_cut`, `arq` (docs/sim-config.md §6) |
| `link` | `[a, b]` or null | node ids, a < b (both directions are affected) |
| `node` | int or null | node id |
| `start_ns`, `stop_ns` | int | the fault holds for `[start_ns, stop_ns)` after t0 |
| `params` | object | kind-specific: `delta_ns`, `factor` (exact string), `loss`, `max_retries`, `retry_extra_ns`, `model` (`renewal`), `unavailability`, `mttr_ns`, and `fault_id` |

`fault_id` names the config entry the interval came from by WHAT it does, not where it sits
in the list: the first 16 hex digits of the SHA-256 of the entry's canonical form (kind,
interval in ns, target, parameters; `fwd/faults.py` `fault_identity`), plus `#n` for the n-th
identical copy. The random streams of a renewal process are keyed by the same identity, so a
run and its counterfactual twin (the same run without one fault) log identical entries for
every other fault, which `eval/detection.check_twin` verifies.

The ground (the planner) never sees these faults.

## 2. events.jsonl.gz

UTF-8 text, one JSON object per line, LF line ends, gzip-compressed (`python-sim` writes the
gzip header with mtime 0 and no file name, so identical runs give identical bytes). Every
line has exactly these keys in this order:

| Key | Type | Meaning |
|---|---|---|
| `t` | int | ns after t0 |
| `ev` | string | `send`, `hop`, `late`, `fallback`, `drop`, `deliver` (§3) |
| `pkt` | int | packet id: 0, 1, 2, ... in order of send time (ties: by flow id) |
| `flow` | int | flow id (`run.json` `flows`) |
| `node` | int | node where the event happens |
| `next` | int or null | next node chosen (`send`, `hop`, `fallback`) |
| `sl` | int or null | Segments Left (byte 3 of the T-CRH) |
| `flags` | int or null | Flags byte (byte 4): DEV 0x01, GREEDY 0x02, SAT 0x04, unit 0x30 |
| `deadline_u` | int or null | the node's arrival deadline D_k in units (spec §5), when it checked one |
| `now_u` | int or null | the node's unit clock `floor((t0_gps_ns + t) / u) mod 2^32` |
| `reason` | string or null | why (`drop`, `fallback`) |
| `hex` | string or null | the T-CRH bytes in lowercase hex, only on sampled packets (§4) |

**Order.** Lines are sorted by `(t, pkt)`; events of one packet at the same `t` appear in
the order they happened (`hop`, then `late`, then `fallback` / `drop` / `deliver`).

**Per packet.** A packet's events start with exactly one `send` and end with at most one
`drop` or `deliver`. A packet that was still on its way at `end_ns` has no final event (it
is `unfinished` in the engine outputs). Times of one packet never decrease.

## 3. Events

| `ev` | Emitted when | `node` | `next` | `sl`, `flags`, `hex` | `deadline_u`, `now_u` | `reason` |
|---|---|---|---|---|---|---|
| `send` | the ingress station builds the header (Epoch_Base = ceil(T_gps / u)) and does spec §6 steps 5-7 | source station | first hop by SID forwarding (null if the packet is dropped at the ingress, or switched to fallback there: see `fallback`) | bytes as transmitted (or as dropped) | null, clock at send | null |
| `hop` | the packet ARRIVES at a node | that node | next node chosen: by SID forwarding, or by the fallback function on a detour transit node; null on delivery, on a drop, and when the packet switched to fallback at this node (see `fallback`) | bytes as they arrived | D_k if the node ran spec §6 (it is named by the Destination Address), else null; arrival clock | null |
| `late` | this node's deadline check fired (spec §6 step 2: DEV set, Dev Hop = k) | that node | null | bytes after processing | D_k, arrival clock | null |
| `fallback` | the packet switched to GREEDY mode here | that node | first node chosen by the fallback function (null if none) | bytes after the switch (DEV and GREEDY set, SL 0) | null | `late` (policy greedy, step 4) or `next_link_down` (step 7) |
| `drop` | the packet is discarded | where | null | bytes as last seen | null | §3.1 |
| `deliver` | the final endpoint processes SL = 0 (step 3) | destination station | null | bytes as delivered | D_h, arrival clock | null |

A packet in GREEDY mode is addressed to SID[0]; the satellites it crosses on a detour do
not run spec §6 (their `hop` events have `deadline_u` null). DEV, once set, is never cleared
(spec §3), so the `flags` of later events show the deviation.

Schemes of `cr eval scheme` without a T-CRH on the wire (`run.json` `scheme.data_plane` =
`oracle` or `table`) write `sl`, `flags` and `hex` null on every event. A SNAP satellite that
detours around its own dead next hop writes a `fallback` event with reason `next_link_down`
whose `next` is the detour neighbour (after the `hop` event with `next` null), like a T-CRH
packet switching to fallback. For `crh16`, `e2e` and `lq` the bytes are the engine's internal
T-CRH (`scheme.trace_hex_is_internal_tcrh`); their wire header is the scheme's own.

### 3.1 Drop reasons

| `reason` | Meaning |
|---|---|
| `no_route` | the planner had no path for the flow in this refresh interval (the packet is never sent) |
| `late_strict` | late, deviation policy `drop` (spec §6 step 4) |
| `next_link_down` | the next link is down (spec §6 step 7) and no fallback function is configured |
| `no_fallback` | late under policy `greedy` and no fallback function is configured |
| `no_fib_entry` | the next SID is not in the node's CRH-FIB (spec §6 step 6) |
| `node_down` | the packet reached a satellite that is down |
| `in_flight_link_down` | the link itself went down before the packet arrived (ns-3 SetDown semantics) |
| `buffer_overflow` | drop-tail: the link's buffer was full when the packet entered |
| `arq_exhausted` | ARQ fault: every attempt (1 + max_retries) was lost |
| `stuck` | the fallback function found no usable neighbour (local minimum / all visited) |
| `hop_limit` | the IPv6 Hop Limit (64 by default) ran out |
| `loop` | as `hop_limit`, and the packet had visited a node twice |
| `malformed` | the node could not parse the T-CRH (never produced by the engine itself) |

## 4. Sampling

`python-sim` writes one of three trace levels (docs/sim-config.md `output.trace`):

* `full`: every event of every packet (`hex` still only on sampled packets);
* `sampled` (default): every event of the sampled packets only, so each traced packet is a
  complete story;
* `none`: no `events.jsonl.gz`.

A packet is sampled when the keyed uniform `rng("sample", flow, seq) < 1 / sample_every`
(sim/chronoroute/fwd/rng.py): the same packets are sampled in a fault run and its fault-free
twin, and every flow is sampled at the same rate.

**Bytes rule.** A sampled packet carries `hex` on EVERY one of its events, `send` included
(the bytes the event's row of §3 names: as transmitted, as arrived, after processing, after
the switch, as dropped, as delivered); any other packet carries `hex` on none. A packet that
never had a header (no route, or a scheme without a routing header) has `hex` null throughout.
`validate_run` checks this: hex on a packet's `send` means hex on all its events, no hex on
its `send` means none on any. `cr trace from-ns3` follows the same rule with its own sample of
probes (`--hex-every`, `--hex-first`, `--hex-late`).

## 5. Engine outputs (python-sim; not part of trace/1)

| File | Content |
|---|---|
| `packets.csv.gz` | one row per packet, sorted by `pkt`: `pkt, flow, seq, send_ns, outcome` (`delivered`, `dropped`, `no_route`, `unfinished`), `reason, delivered` (0/1), `latency_ns, hops` (links crossed), `path` (node ids, space separated), `dev` (0/1, from the final bytes), `dev_hop, first_late_hop` (hop index k of the node whose deadline check fired), `arrival_u` (unit clock at every node after the source), `deadline_u` (D_k at every node that checked one; `-` on detour transit nodes), `greedy` (0/1), `fallback_reason, row_from_ms` (schedule row used), `wire_bytes` |
| `schedule.csv.gz` | every (flow, refresh interval): `flow_id, src, dst, valid_from_ms, valid_to_ms, path_nodes, sids_fwd, cumulative_budgets_ns, predicted_hop_delays_ns, tcrh_hex_template` (empty path = no route) |
| `summary.json` | counts, drops by reason, conservation, per-flow PDR and latency quantiles (`latency_ns_p50` / `_p99`: nearest rank OF DELIVERED packets only; `latency_eff_ns_p50` / `_p99`: effective, over every sent packet with a lost one counting as +inf, `"inf"` when too many were lost), invariant checks, speed (`hop_events_per_s_forwarding`: forwarding only; `hop_events_per_s_loop`: the event loop incl. planning; `hop_events_per_s_end_to_end`: over the whole command) and peak memory |
| `capture.pcap` | (optional) PPP / IPv6 frames of sampled packets as they start to leave each node (nanosecond pcap, `sim/chronoroute/trace/pcap.py`; readable with `tools/wireshark/tcrh.lua`) |
| `synthetic_omm.json` | (Walker presets) the generated element sets |
| `manifest.json` | provenance (`sim/chronoroute/provenance.py`) |

## 6. Changes

* 1.0 (2026-10-11): first version.
* 1.1 (2026-10-11): `params.fault_id` replaces `fault_index` (stable fault identity); the bytes
  rule of §4 (python-sim now writes `hex` on `late` and `fallback` events of sampled packets, as
  §3 always said and as `cr trace from-ns3` did); `engine.config`, `engine.carrier_detect_ns`,
  `scheme`, `rerun` keys; how a `bundle` positions path is resolved; table schemes and SNAP
  detours in §3; summary.json quantile and speed keys. The schema string stays
  `chronoroute.trace/1`: every 1.0 reader reads 1.1 files.

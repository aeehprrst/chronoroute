# Scenario bundle and website topology files: formats

This document defines the files that the topology and routing code writes for other tools:

* the **ns-3 scenario bundle**, written by `cr export bundle` (`sim/chronoroute/export/bundle.py`);
* the **website topology files** `shells.json` and `isl_grid4.json`, written by `cr export web`
  (`sim/chronoroute/export/web.py`);
* the **SID registry** `data/static/sid_registry.json` (`sim/chronoroute/route/sids.py`).

The wire format of T-CRH is defined by [`spec/tcrh-v1.md`](../spec/tcrh-v1.md). Where this
document mentions a header, the spec governs.

## Honesty labels

| What | Label | Basis |
|---|---|---|
| Orbital elements | REAL | CelesTrak SupGP (or GP); see the snapshot's README |
| Satellite positions | REAL | SGP4 (python-sgp4 2.27) on the REAL element sets; TEME to ECEF via GMST (UT1 = UTC, no polar motion) |
| City coordinates | REAL | Natural Earth, `data/static/cities.csv` |
| Shells and orbital planes | DERIVED | Inferred from the element sets (`orbit/shells.py`, `orbit/planes.py`) |
| Laser links (ISLs), Grid-4 | MODELLED | Starlink's real laser topology is not public |
| Ground-link elevation mask, 25° | ASSUMED | The value in Starlink's filings, as used by Hypatia |
| Ground-link assignment (sticky top 4, §1.2) | MODELLED | The real assignment is not public |
| Processing delay, 0.5 ms per hop | MODELLED | The existing model's value (`sim/legacy/topology.py`) |
| Routes, budgets, deadlines | DERIVED | Computed by our code from the above |
| T-CRH header bytes | REAL code output | `chronoroute.proto`. Starlink does not use T-CRH. |

The manifests can only hold REAL, DERIVED and MODELLED, so the ASSUMED mask is filed there
under `gsl_mask_and_assignment: MODELLED`. `scenario.json` has a `label_notes` entry that
explains this. Every producer (bundle, website files, fleet report, course results, golden
pcaps) takes its label keys and values from one table, `sim/chronoroute/labels.py`, so the same
thing carries the same label everywhere (`sim/tests/test_labels.py` checks it).

## 1. The models behind the files

### 1.1 Grid-4 laser links (MODELLED)

Each satellite has at most four laser links:

* **Two intra-plane links**, to the satellites before and after it in its own orbital plane.
  The neighbours are taken by argument of latitude `u`, and the ring is closed. A plane of 2
  satellites has one link; a plane of 1 has none.
* **Two cross-plane links**, one into each adjacent plane. Planes are ordered by ascending
  node (RAAN), and the last plane is adjacent to the first. Partners come from a one-to-one
  greedy matching on nearest `u`:
  1. List every pair (a in plane A, b in plane B) whose circular `|u_a − u_b|` is at most
     `max_cross_du_deg`. That cap is one nominal in-plane spacing, `360° / median plane size`
     of the shell.
  2. Sort the pairs by (`|du|`, NORAD a, NORAD b).
  3. Accept each pair whose two satellites are both still unmatched in this plane pair.

  A satellite facing a gap in the next plane gets no partner there, so no long diagonal link
  is invented.

The degree is therefore at most 4. Satellites that the plane inference marks **off-grid**
(plane fragments) have no slot, so they get no links and are left out of bundles; their number
is in `scenario.json`. There are **no links between shells** (ASSUMED). In particular, the 460
and 465 km sub-shells, whose satellites fly inside the 463 km planes, are not linked to the
463 km shell.

**Pairs** are chosen once, at the run start (`time.grid4_pairs_chosen_at_utc`). The website
files use the snapshot's `fetched_utc` instead. After that only the up/down state changes,
evaluated at every step:

* A **cross-plane** link is down while either end is above |geodetic latitude| 70°.
* **Any** link is down while its straight line of sight comes closer than 80 km to the WGS84
  ellipsoid (exact test: `topo/geometry.py`).
* **Optional laser range** (`--isl-max-range-km`, `Grid4Params.max_range_km`, default none):
  any link longer than this is down at that step.
* A link touching a satellite whose SGP4 propagation failed is down.

**Long intra-plane links.** An intra-plane link joins slot neighbours however far apart they
are, so a plane with missing satellites gets one long hop. Without a range limit only the
80 km rule bounds it (about 4,514 km at 463 km). The default keeps the plan's model (master
plan §2 row 7: the 80 km rule is the only geometry limit; we know no published terminal range
that we could check). The value is recorded in `scenario.json` (`models.isl.max_range_km`) and
`isl_grid4.json` (`model.max_range_km`; `null` = no limit). What a limit would remove in the
60 s milestone scenario (3,206,936 up link-steps over 5,361 pairs; measured with
`/tmp/cr-sa/fixer/topo_variants.py`, all removed links are intra-plane):

| Range limit | Up link-steps removed | Pairs affected |
|---|---|---|
| 2,000 or 2,500 km | 130,417 (4.07 %) | 217 |
| 3,000 to 4,000 km | 27,045 (0.84 %) | 45 |
| 4,500 km | 0 | 0 |

The lengths cluster near one, two and three nominal in-plane spacings (about 1.4, 2.8 and
4.1 thousand km), so the steps in the table are gaps of one or two missing satellites. Of the
84 laser links that the milestone paths use, the longest is 4,094.6 km; 4 are longer than
2,500 km and 1 is longer than 3,000 km. Over one orbit at 1 s steps the longest up link per
shell is 4,116 km (53.2°/463 km) and up to 5,219 km (70°/572 km)
(`sim/tests/test_topo_orbit_all_shells.py`).

### 1.2 Ground links

1. A satellite is **visible** from a ground station when its elevation is at least 25°. The
   elevation is measured above the local WGS84 horizon, using the ellipsoid normal.
2. The station connects to at most **4** visible satellites. Which ones is the policy
   (`--gsl-policy`, MODELLED):
   * **`sticky_top_k` (default).** Hysteresis: a station keeps a satellite for as long as it
     stays visible. Only a free beam (its satellite set below 25°, or fewer than 4 links so far)
     is given a new satellite: the highest elevation not yet used, ties to the lower node id.
     At the first step the station takes the 4 highest. A link therefore ends only when its
     satellite sets.
   * **`highest_elevation_top_k`** (the Sprint A policy, kept as a labelled variant): the 4
     highest are re-picked at every step, so a link vanishes whenever another satellite climbs
     above it, often while it is still 30° or more up. In the 60 s milestone window this ends 39
     ground links while their satellite is still visible (sticky: 0; 5 links end, all at the
     mask).

Those connected pairs are the "up" ground links. Ground stations sit on the ellipsoid at
height 0. Ground stations never relay traffic: a path starts at one city and ends at another,
and never passes through a third.

### 1.3 Delays and edge weights

```
delay_ns  = floor(distance_km * 1e12 / 299792458 + 0.5)      # light time, nearest ns (halves up)
weight_ns = delay_ns + 500000                                 # + 0.5 ms processing per hop
```

`delay_ns` is the physical channel delay; the router minimises `weight_ns`. `delay_ns` is −1 if
a position is missing. A link that is down still carries its geometric `delay_ns`.

**Between steps:** the up/down state of step `t` holds for `[t, t + step_ms)`. For a channel
delay at an instant between two rows, linear interpolation of `delay_ns` between those rows
is recommended. Python's router uses the value at the step itself.

### 1.4 Routing and deadlines

* **Which links a schedule row may use** (`--plan-links`):
  * **`stable` (default).** Orbits and ground-link handovers are predictable, so the ground
    plans the interval `[valid_from, valid_to)` only on links that are up at **every** 100 ms
    step from `valid_from` until `valid_to + B_h`, where `B_h` is the path's own final budget:
    the last packet of the interval then still finds every link of its path up when it
    arrives. `B_h` depends on the path, so the planner starts with the interval alone and
    widens the look-ahead to the path's `B_h` until the path fits (each round can only
    lengthen it; it settles in a few rounds). Weights are those of the step at `valid_from`.
    A planned path never loses a link while its packets use it, so any deviation the network
    sees is a real surprise (a fault): what T-CRH is meant to detect.
  * **`instant`** (the Sprint A rule, kept as a labelled variant): the links up at
    `valid_from` only. A link may go down inside the interval and its packets are lost.
  The `schedule_stability` invariant (§2.10) checks every row; with `stable` a broken row
  refuses the bundle.

  | 60 s milestone window | `stable` | `instant` |
  |---|---|---|
  | `sticky_top_k` ground links | 0 of 600 rows lose a link in use | 0 of 600 (by luck of this window) |
  | `highest_elevation_top_k` | 0 of 600 | 26 of 600 (the Sprint A bundle, byte-identical) |
* **Path.** Dijkstra on that graph (`route/dijkstra.py`), with integer ns weights and a binary
  heap. On equal cost the predecessor with the lowest node id wins:
  `pred[v] = min{u : dist[u] + w(u,v) == dist[v]}`. This rule does not depend on the order in
  which the heap pops nodes, so the C++ and TypeScript ports can reproduce it.
* **Predicted hop delay.** `d_k` = the edge weight of hop k (light time + 0.5 ms).
* **Cumulative budget.** `B_k = S × (d_1 + … + d_k)`, kept as an exact rational. S comes from
  its decimal text, so `1.5` is exactly 3/2. The default is S = 1.5.
* **Header.** `chronoroute.proto.build_header(sids_fwd, B, t_ingress_gps_ns, unit_code)`, with
  the ceil-cumulative deltas of spec §5.1. The default unit code is 1 (0.1 ms).
* **SIDs.** Satellites take theirs from the SID registry, keyed by NORAD id (§4). Ground
  station g has SID `0xF000 + g`.

## 2. The ns-3 scenario bundle

### 2.1 Making one

```
cr export bundle --snapshot data/pinned/20261010T1358Z-celestrak --shell 53.2deg-463km \
  --cities "Chennai,Mumbai,London,New York,Singapore,Sydney,Tokyo,Johannesburg,Sao Paulo,Frankfurt" \
  --start 2026-10-10T14:00:00Z --duration-s 60 \
  --flow "Chennai->London" --flow "New York->Sydney" --flow "Sao Paulo->Tokyo" \
  --flow "Mumbai->Frankfurt" --flow "Singapore->Johannesburg" --reverse \
  --out /tmp/cr-sa/bundles/c5-463-60s
```

| Option | Default | Meaning |
|---|---|---|
| `--step-ms` | 100 | Step for link states and delays |
| `--position-step-ms` | 1000 | Step for `positions.csv` |
| `--refresh-ms` | 1000 | Schedule refresh interval |
| `--slack` | 1.5 | Multiplicative slack S |
| `--unit-code` | 1 | T-CRH deadline unit code |
| `--reverse` | off | Adds every flow's reverse direction after the forward flows (for ACKs) |
| `--gsl-policy` | `sticky_top_k` | Ground-link assignment (§1.2); `highest_elevation_top_k` is the Sprint A variant |
| `--plan-links` | `stable` | Links a schedule row may use (§1.4); `instant` is the Sprint A variant |
| `--isl-max-range-km` | none | Laser range limit (§1.1); without it only the 80 km rule limits a link |

`ns3/run_leo.py --recipe c5-463-60s` (or `c5-463-10s-small`) rebuilds the milestone bundles
with exactly these commands, so the course results can be reproduced from git alone.
`--gsl-policy highest_elevation_top_k --plan-links instant` reproduces the Sprint A bundle
byte for byte (all six CSV files compared by sha256).

The command refuses to write a bundle that fails an invariant (§2.10). After writing, it
re-reads the whole bundle with `check_bundle()`.

### 2.2 Files

| File | Rows | Content |
|---|---|---|
| `nodes.csv` | one per node | Satellites, then ground stations |
| `isl.csv` | one per candidate laser link | Grid-4 pairs |
| `isl_delay.csv` | links × steps | Up flag and light time of every laser link at every step |
| `gsl.csv` | pairs × steps | Every (ground station, satellite) pair that is visible at some step of the window |
| `positions.csv` | nodes × position steps | ECEF positions |
| `schedule.csv` | flows × refresh intervals (minus gaps) | Planned paths and T-CRH templates |
| `scenario.json` | — | What the bundle is (§2.9) |
| `manifest.json` | — | Provenance (`spec/schemas/manifest.schema.json`), with the sha256 and size of every file above |

### 2.3 Common rules

* UTF-8, LF line ends, one header row, fields separated by commas.
* No field ever contains a comma, a quote or a newline (the writer refuses such names), so no
  CSV quoting is used. A plain `split(',')` parses every line.
* A list inside a field (`sids_fwd`, `cumulative_budgets_ns`, `predicted_hop_delays_ns`,
  `path_nodes`) is space-separated decimal integers.
* Every number is a decimal integer except `lat`/`lon` (copied verbatim from `cities.csv`) and
  `x_m`/`y_m`/`z_m` (metres printed from integer millimetres, always 3 decimals).
* `t_ms` is milliseconds after t0 (`scenario.json` → `time.t0_utc`), from 0 to `window_ms`
  inclusive.
* Node ids are `0 … S−1` for satellites (sorted by NORAD id), then `S … S+G−1` for ground
  stations, in the order of `--cities`.
* Rows are sorted as stated per file, and the same inputs give byte-identical files. Only
  `manifest.json` contains time stamps.

### 2.4 `nodes.csv`

Sorted by `node_id`.

| Column | Satellite | Ground station |
|---|---|---|
| `node_id` | 0 … S−1 | S … S+G−1 |
| `kind` | `sat` | `gs` |
| `sid` | Registry SID, 1 … 0xEFFF | `0xF000 + g` (decimal, e.g. 61452 for Chennai) |
| `norad` | NORAD catalogue number (5 or 6 digits) | empty |
| `name` | CelesTrak `OBJECT_NAME` (e.g. `STARLINK-2385`) | City name |
| `shell` | Shell id (e.g. `53.2deg-463km`) | empty |
| `plane` | Plane index in the shell (RAAN order at t0) | empty |
| `slot` | Slot in the plane (ascending `u` at t0) | empty |
| `lat`, `lon` | empty | WGS84 degrees, verbatim from `cities.csv` |

### 2.5 `isl.csv` and `isl_delay.csv`

`isl.csv` is sorted by `link_id`, which is the same as sorting by (a, b).

| Column | Meaning |
|---|---|
| `link_id` | 0 … L−1 |
| `a`, `b` | Node ids, a < b |
| `kind` | `intra` or `cross` |

`isl_delay.csv` has one row per link per step and is sorted by (`t_ms`, `link_id`).

| Column | Meaning |
|---|---|
| `t_ms` | Step time, 0, 100, …, `window_ms` |
| `link_id` | As in `isl.csv` |
| `up` | 1 = usable for `[t_ms, t_ms + step_ms)`, 0 = down (polar cutoff, 80 km rule or no position) |
| `delay_ns` | Light time at `t_ms` (§1.3), even when down; −1 = no position |

### 2.6 `gsl.csv`

There is one row per step for every (ground station, satellite) pair that is visible (elevation
at least 25°) at some step in the window. Sorted by (`t_ms`, `gs_node`, `sat_node`).

| Column | Meaning |
|---|---|
| `t_ms` | Step time |
| `gs_node` | Ground station node id |
| `sat_node` | Satellite node id |
| `up` | 1 = this pair is one of the station's at most 4 links at this step (§1.2) |
| `delay_ns` | Light time at `t_ms` |
| `elev_mdeg` | Elevation in millidegrees (integer); −999999 = no position |

A row with `up = 1` always has `elev_mdeg >= 25000`. Handovers are the changes of `up` from one
step to the next.

### 2.7 `positions.csv`

There is one row per node every `position_step_ms`, including the ground stations (constant).
Sorted by (`t_ms`, `node_id`). Columns: `t_ms, node_id, x_m, y_m, z_m`, in Earth-fixed (ECEF)
coordinates and metres. Parse the values as float64: float32 resolves only about 0.5 m at 7,000 km.

### 2.8 `schedule.csv`

There is one row per (flow, refresh interval) that has a path. Sorted by (`valid_from_ms`,
`flow_id`).

| Column | Meaning |
|---|---|
| `flow_id` | Index into `scenario.json` → `flows`. With `--reverse`, the reverse flows follow the forward flows. |
| `src_gs`, `dst_gs` | Node ids of the two ground stations |
| `valid_from_ms`, `valid_to_ms` | The path holds for `[from, to)`. It was computed at step `from`, on the links that stay up until `to` + its final budget (`stable`, §1.4) or on the links up at `from` (`instant`). |
| `sids_fwd` | SIDs of hops 1…h in forward order. The last one is the destination station's SID. The ingress station's own SID is not included. |
| `cumulative_budgets_ns` | `ceil(B_k)` for k = 1…h, integer ns. `ceil(ceil(B)/u) = ceil(B/u)`, so these integers encode to exactly the template's deltas. |
| `predicted_hop_delays_ns` | `d_k` = light time + 500000 ns per hop |
| `tcrh_hex_template` | The full T-CRH in lowercase hex, with Segments Left = Num Hops = h, Epoch_Base = 0, Next Header = 17, Flags = unit code (plus SAT if a delta was clamped) |
| `path_nodes` | Node ids of the whole path, from `src_gs` to `dst_gs` |

**At the ingress, per packet** (spec §4): copy the template and set bytes 8–11 to
`Epoch_Base = ceil((t0_gps_ns + t_ns) / unit_ns) mod 2^32`. Here `t_ns` is the packet's
ingress time after t0, `t0_gps_ns` comes from `scenario.json`, and `unit_ns` = 100000 for unit
code 1. Set byte 0 (Next Header) to the real transport protocol. Nothing else changes.

**Gaps.** A (flow, interval) with no path has no row. It is listed under `schedule_gaps` in
`scenario.json`.

### 2.9 `scenario.json`

Indented JSON with these top-level keys, in this order:

| Key | Content |
|---|---|
| `schema` | `"chronoroute.bundle/1"` |
| `labels`, `label_notes` | The honesty-labels table above, in machine form |
| `snapshot` | `id`, `layout`, `source`, `fetched_utc`, `sha256_raw`, `sha256` (of `SHA256SUMS` for a pinned folder), `sha256_of`, `attribution` |
| `shell` | `shell_id`, `layer`, `inclination_deg`, `altitude_km`, `members`, `in_planes`, `off_grid_left_out`, `n_planes`, `plane_quality`, `shares_planes_with` |
| `time` | `t0_utc`, `t0_unix_ns`, `t0_gps_ns`, `window_ms`, `step_ms`, `position_step_ms`, `schedule_refresh_ms`, `grid4_pairs_chosen_at_utc` |
| `models` | `isl` (Grid-4 parameters incl. `max_range_km`, and the actual `max_cross_du_deg`), `gsl` (mask, k, policy, labels), `planning` (`plan_links` and its rule), `delay` (c, processing, formulas) |
| `tcrh` | `spec`, `unit_code`, `unit_ns`, `slack` (exact, e.g. `"3/2"`), `next_header`, `template_epoch_base`, the budget rule, the SID sources, the ns-3 SID address plan (`fd00::<sid>/128`), the routing rule |
| `counts` | `nodes`, `satellites`, `ground_stations`, `isl_links`, `isl_intra`, `isl_cross`, `gsl_pairs`, `steps`, `position_steps`, `flows`, `schedule_rows`, `schedule_gaps` |
| `flows` | `[{flow_id, src, dst, src_gs, dst_gs, src_sid, dst_sid, great_circle_km}]` |
| `schedule_gaps` | `[{flow_id, valid_from_ms, valid_to_ms}]` |
| `invariants` | Results of §2.10 |
| `files` | `{file: {columns: [...]}}` |

### 2.10 Invariants checked before writing (`topo/invariants.py`)

| Check | Rule |
|---|---|
| `isl_clearance` | Every up ISL at every step stays at least 80 km above WGS84. This is certified by the bound `r_min − a`, or by the exact height. A second, independent check samples 66 points per segment every 10th step. It reports the longest up ISL, and with a range limit every longer up link is a violation. |
| `gsl_geometry` | Every up ground link has elevation ≥ 25°, recomputed in the local ENU frame. The satellite is at least 80 km up, and the line of sight never dips below the station. |
| `hop_delay` | Every up edge has `|delay_ns − d/c| ≤ 0.5 ns` and `weight_ns ≥ d/c`. |
| `isl_degree` | No satellite has more than 4 Grid-4 links. |
| `path_latency` | On every scheduled path, each hop's predicted delay is at least d/c at that step. The end-to-end light time is at least great-circle distance / c. |
| `schedule_stability` | Every link of every schedule row's path is up at every step from `valid_from` until `valid_to` + the path's final budget. A violation with `plan_links = stable`; only counted with `instant`. |

The P2 acceptance check "0 laser links below 80 km over one orbit (about 95 min) at 1 s steps,
for every shell" is the test `sim/tests/test_topo_orbit_all_shells.py`: every shell of the
pinned snapshot (broadband and DTC, 10 shells), 5,701 steps, the same checker plus dense
sampling at every step of every link the bound cannot certify, and the polar rule (about
2 minutes). `sim/tests/test_topo_invariants.py` covers one orbit of the 463 km shell at 10 s
steps with cities and flows (ground links, delays, paths).

### 2.11 Milestone bundles

Built from snapshot `20261010T1358Z-celestrak` (SupGP), shell `53.2deg-463km`, starting at
2026-10-10T14:00:00Z. Measured on the WSL machine on 2026-10-11 (20 cores, 7.6 GiB RAM); the
run's `manifest.json` records the details.

| Bundle (`ns3/run_leo.py --recipe`) | Window | Cities | Flows | Size | Wall time | Peak RSS |
|---|---|---|---|---|---|---|
| `c5-463-60s` | 60 s | 10 | 5 + 5 reverse | 78.2 MB (`isl_delay.csv` 65.5 MB) | 16.8–17.5 s | 0.79 GB |
| `c5-463-10s-small` | 10 s | 3 (Chennai, London, Singapore) | 2 + 2 reverse | 12.4 MB | 3.0 s | 0.3 GB |

Both use the defaults `sticky_top_k` ground links and `stable` planning: 0 schedule gaps, and
0 of 600 (60 s) and 0 of 40 (10 s) schedule rows lose a link while in use.

Both bundles contain the shell's 2,847 in-plane satellites (272 off-grid satellites are left
out) and 5,361 Grid-4 pairs (2,847 intra, 2,514 cross).

### 2.12 Reading a bundle

* **Python:** `chronoroute.export.bundle.read_csv(path)` returns the header and the rows.
  `check_bundle(dir)` re-validates a bundle against its `scenario.json`. It re-builds every
  T-CRH template with `proto.build_header` from `sids_fwd` and `cumulative_budgets_ns`.
* **C++ (ns-3):** read each line with `std::getline` and split on `,`; split the list fields on
  space. Use 64-bit integers for `delay_ns`, the budgets and `t0_gps_ns`, and `double` for the
  positions.

## 3. Website topology files

`cr export web <website snapshot dir>` writes two extra files into the snapshot folder, next
to the contract's `manifest.json` and `omm.min.json` (see `web/DATA_CONTRACT.md` in the website
repo). If you pass a pinned folder with `--out-root <public/data>`, it first writes the website
snapshot with the data owner's `write_web_snapshot`, and changes `latest.json` only when you
add `--update-latest`.

```
public/data/snapshots/<snapshot_id>/
  manifest.json            (website contract; not modified)
  omm.min.json             (website contract; not modified)
  shells.json              shells and planes (DERIVED)
  isl_grid4.json           Grid-4 pairs per shell (MODELLED)
  provenance-topo/manifest.json   provenance of the two files above (write_manifest;
                                   outputs listed as ../shells.json, ../isl_grid4.json)
```

Both files follow the contract's rules:

* compact UTF-8 JSON plus a newline;
* a `schema` string;
* no "generated at" time stamp, so the same snapshot always gives byte-identical files;
* satellites identified only by `NORAD_CAT_ID`, as JSON numbers (six digits occur).

Both describe the snapshot's `fetched_utc`, which they call `reference_utc`.

### 3.1 `shells.json` (schema `chronoroute.web-shells/1`)

```json
{"schema":"chronoroute.web-shells/1","snapshot_id":"20261010T1358Z-supgp",
 "reference_utc":"2026-10-10T14:02:22Z","label":"DERIVED","note":"...",
 "parameters":{"shells":{...},"planes":{...}},
 "shells":[{"shell_id":"53.2deg-463km","layer":"broadband","inclination_deg":53.1581,
            "altitude_km":462.78,"count":3119,"n_planes":104,"off_grid":272,"quality":0.9128,
            "shares_planes_with":null,
            "planes":[[norad, ...], ...],
            "off_grid_norads":[norad, ...]}, ...],
 "in_transit":[norad, ...]}
```

| Field | Meaning |
|---|---|
| `planes` | One list per plane, in RAAN order. Each list holds NORAD ids in slot order: ascending argument of latitude at `reference_utc`. |
| `off_grid_norads` | Shell members that are in no plane |
| `in_transit` | Satellites outside every shell band; excluded from routing |
| `quality` | The data owner's plane-quality score |

### 3.2 `isl_grid4.json` (schema `chronoroute.web-isl-grid4/1`)

```json
{"schema":"chronoroute.web-isl-grid4/1","snapshot_id":"...","reference_utc":"...",
 "label":"MODELLED","note":"...",
 "model":{"name":"grid4","polar_cutoff_deg":70.0,"min_grazing_alt_km":80.0,
          "cross_max_du_factor":1.0,"max_range_km":null,"max_degree":4,"inter_shell_links":false},
 "rules":{"pairs":"...","cross_polar_cutoff":"...","grazing":"...","range":"..."},
 "shells":[{"shell_id":"53.2deg-463km","layer":"broadband","max_cross_du_deg":12.413793,
            "intra":[[a,b], ...],"cross":[[a,b], ...]}, ...]}
```

Pairs are `[a, b]` NORAD ids with a < b, sorted. They are fixed for the snapshot. **The website
decides per frame** whether to draw each pair as up, with the same rules as Python (§1.1):

* a cross pair is down while |latitude| of either end is above `polar_cutoff_deg`;
* any pair is down while its line of sight comes closer than `min_grazing_alt_km` to WGS84;
* when `max_range_km` is not `null`, any pair is down while it is longer than that.

Every pair must carry the MODELLED badge. Measured sizes for the 2026-10-10 snapshot:
`shells.json` 70.9 KB, `isl_grid4.json` 245.9 KB, uncompressed.

## 4. SID registry (`data/static/sid_registry.json`)

The registry is stable and append-only, as spec §7 requires. Each satellite keeps its SID for
life, so forwarding tables never have to be renumbered. The file is written one entry per line
so that `git diff` shows exactly what was appended:

```
{
"schema": "chronoroute.sid-registry/1",
"description": "...",
"satellite_sid_first": 1,
"satellite_sid_max": 61439,
"ground_station_sid_base": 61440,
"satellites": [
[1,44714],
...
],
"ground_stations": [
[0,"Addis Ababa"],
...
]
}
```

| Part | Rule |
|---|---|
| `satellites` | `[sid, NORAD id]`. SIDs run 1, 2, 3, … in allocation order; a batch of new satellites is numbered in NORAD order. |
| SID 0 | Never used: its address `fd00::` would be the Subnet-Router anycast address of `fd00::/64` (RFC 4291 §2.6.1). |
| `ground_stations` | `[g, city name]`, with SID = `0xF000 + g`. g runs 0, 1, 2, …; new names are numbered in name order. |
| Rejected | Gaps, duplicates, and any save that would drop or renumber an entry already on disk |

The first population used `cr export sids data/pinned/20261010T1358Z-celestrak
data/pinned/20261010T2035Z-celestrak`. That registered 11,130 satellites (every NORAD id in
GP or SupGP of both snapshots) and the 60 cities of `cities.csv`. Later, `cr route`,
`cr export bundle` and `cr export sids` append any NORAD id they meet that is not yet in the
file.

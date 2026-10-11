# Course milestone: LEO topology and a time-varying schedule in ns-3

This is the write-up of the ns-3 milestone for the Computer Networks report. It covers what was
built, what was run, the measured results, how to reproduce every number, and what the
simulation does **not** model.

**Summary.**
- **What was run:** ChronoRoute ran in ns-3.44 on the **real** Starlink 53.2° / 463 km sub-shell,
  which has 2,847 satellites from the 10 Oct 2026 CelesTrak snapshot, plus 10 cities.
- **What changes during the run:** link delays and up/down states change every 100 ms. The
  routing schedule changes every second. The ground plans each second only on links that stay
  up until that second's last packet has arrived (orbits and ground-link handovers are
  predictable), and a city keeps a satellite while it is visible.
- **How T-CRH travels:** inside real IPv6 Routing Type 253 headers.
- **Result without a fault:** all **60,000 of 60,000** probes were delivered, and ns-3 and an
  independent Python replay of the same scenario agree on every one of them: the path, the
  outcome, DEV / Dev Hop, and the arrival time, clock and deadline at every hop, to the
  nanosecond.
- **Result with a fault:** one laser link was slowed from **1 Gb/s to 200 kb/s** for 20 s while
  staying up. The probe traffic on it is 232 kb/s per direction, so the link was **1.16×
  overloaded** and its 100-packet queue filled, holding probes for up to **≈1.16 s**.
  - Probes that crossed it were flagged late (DEV) in **99.92 %** of cases (3,645 of 3,648).
  - The same probes in a paired run without the fault were flagged **0 %** of the time.
  - The same fault at **1 Mb/s, 500 kb/s and 250 kb/s flagged 0 %** (0 of 4,000 each,
    `sensitivity.json`): while the link stays faster than its load no queue builds, and the
    extra transmission time (2.3–9.3 ms per probe) stays inside the probes' deadline slack at
    that hop (10.9–14.2 ms).
  - **What this does not show.** A queue this long is also visible to the satellite in front
    of the slowed link, from its own device queue. So 99.92 % is not evidence that deadlines
    beat a local-queue detector; that comparison (reviewer must-fix #2) is still to be run.
- **Cost:** one 60 s run of the full sub-shell takes about 17 s and 194 MiB of memory.

Results: `results/course-milestone/c5-463-60s-seed1/` (main) and
`results/course-milestone/c5-463-10s-small-seed1/` (the small development bundle). Each folder has
a `manifest.json`: commit, configuration (including the `cr export bundle` command and the
sha256 of every bundle file), seed, snapshot sha256, and the sha256 of every output file and
program.

## 1. Setup

### 1.1 Real data, and what is modelled

| Part | Label | Where it comes from |
|---|---|---|
| Orbital elements | REAL | CelesTrak SupGP snapshot `20261010T1358Z-celestrak` (fetched 2026-10-10 14:02:22 UTC), `data/pinned/`, checked by its SHA256SUMS |
| Satellite positions | REAL | SGP4 (python-sgp4 2.27) on those elements, Earth-fixed frame |
| City coordinates | REAL | Natural Earth (`data/static/cities.csv`) |
| Shell and planes | DERIVED | Shell `53.2deg-463km`: 3,119 members, 2,847 in 104 orbital planes (272 off-grid satellites left out) |
| Laser links (Grid-4) | MODELLED | 5,361 candidate links. Starlink's real laser topology is not public. No range limit besides the 80 km grazing rule (`docs/bundle-format.md` §1.1) |
| Ground links | MODELLED | 25° elevation mask (ASSUMED); each city uses up to 4 satellites and keeps one while it is visible (`sticky_top_k`) |
| Routes, budgets, deadlines | DERIVED | Dijkstra every 1 s on the links that stay up until the second's last packet meets its final deadline (`plan_links = stable`); budget = 1.5 × (light time + 0.5 ms) per hop |
| T-CRH header bytes | REAL | Real output of the spec v1 encoder (Python and C++ agree byte for byte). Starlink does not use T-CRH |
| Link rate 1 Gb/s, DropTail queues of 100 packets | MODELLED | Chosen for the experiment |
| Probe traffic, the slow-link fault | MODELLED | Chosen for the experiment |
| Processing delay inside ns-3 | MODELLED | Zero: a node forwards the moment a packet arrives |

The label keys and values come from one shared table, `sim/chronoroute/labels.py`, the same as
in the bundle, the fleet report and the website files.

### 1.2 The scenario

- **Start time:** t0 = 2026-10-10 14:00:00 UTC (GPS time is UTC + 18 s).
- **Window:** 60 s in 601 steps of 100 ms. Positions are sampled every 1 s.
- **Cities (10):** Chennai, Mumbai, London, New York, Singapore, Sydney, Tokyo, Johannesburg,
  Sao Paulo, Frankfurt.
- **Flows (10):** Chennai→London, New York→Sydney, Sao Paulo→Tokyo, Mumbai→Frankfurt and
  Singapore→Johannesburg, plus the reverse of each.
- **Bundles:** `ns3/run_leo.py --recipe c5-463-60s` (and `c5-463-10s-small`) rebuilds the
  scenario bundle with `cr export bundle` from the pinned snapshot in git (`docs/bundle-format.md`
  §2.1); the builder is deterministic, so the bundle is byte-identical on every machine.
  - `c5-463-60s`: the main bundle (78.2 MB).
  - `c5-463-10s-small`: 10 s, 3 cities (Chennai, London, Singapore), 4 flows, used to develop.
- **Schedule:** a new path and a new set of deadlines for every flow every second. That is
  600 schedule rows for the main bundle; no row's path loses a link while it is in use
  (`schedule_stability` invariant: 0 of 600).

## 2. What the ns-3 program does

The program is `ns3/contrib/chronoroute/examples/chronoroute-leo.cc`. The bundle reader and
network builder is `helper/leo-bundle-helper.{h,cc}`.

### 2.1 Nodes and links

- **Nodes.** Every bundle node becomes an ns-3 node with an IPv6 stack and T-CRH support:
  2,857 nodes (2,847 satellites and 10 cities).
  - The T-CRH extension, CRH-FIB, address plan and source shim are the module's
    `ipv6-extension-tcrh`, `crh-fib`, `tcrh-address-plan` and `tcrh-source-shim`. SID `s` has
    the address `fd00::s`.
  - The ns-3 node id equals the bundle node id, and the program checks this.
- **Links.** Each laser link is one **stock `ns3::PointToPointChannel` link**, so NetAnim draws
  it. Each (city, satellite) pair that is ever visible in the window gets its own link,
  created in advance (205 pairs).
  - Every link runs at 1 Gb/s with a DropTail queue of 100 packets per direction.
  - There is no queue disc and no flow control, so a full queue drops at the device.

### 2.2 Time-varying links (every 100 ms)

- **Order of events.** One event per step updates every link. These events are scheduled before
  any packet, so a packet event at exactly a step boundary already sees the new state.
- **Delay.** The channel's `Delay` is set to that step's light time and **held** for the whole
  step.
  - The bundle recommends linear interpolation. Holding the value instead costs at most
    1.80 µs per hop in this run (median under 1 ns). That figure is the measured
    held-versus-interpolated difference over every hop of every delivered packet.
  - Python replays the same held values, so the cross-check is still exact.
- **Link down (SetDown semantics).** When the bundle marks a link down, the IPv6 interface at
  **both ends** is set down. What happens next depends on where the packet is:
  - **The node holding the packet sees the dead link.** This is spec §6 step 7: the node sets
    DEV with Dev Hop = itself (0 at the source city), then, with no fallback function in this
    phase, discards the packet. The ingress shim and transit nodes report it the same way.
  - **The packet is already in flight.** It is lost at the receiving interface.
  - **When the link comes back up,** the interface returns with its address-plan address.
  - In this run no scheduled path met a dead link (the planner avoids links that go down
    during their interval), so these cases happen only in the tests
    (`sim/tests/test_ns3_crosscheck.py`).

### 2.3 Time-varying schedule

- **Which path a probe gets.** The source city's shim inserts the T-CRH of the schedule row valid
  **at send time**.
- **Epoch_Base** is stamped per packet at that instant: `ceil((t0_gps + t_send) / 0.1 ms)`.
- **Template check.** The C++ encoder rebuilds every schedule row's T-CRH template, and the
  program refuses a bundle unless all of them match Python's bytes exactly.

### 2.4 Traffic

- **Probes:** UDP, 100 per second per flow, 200-byte payload (290–338 bytes on the wire,
  depending on the number of hops).
- **Start times:** each flow starts at a random offset inside the first 10 ms, drawn by ns-3's
  random number generator with seed 1.
- **Payload contents:** `CRT1`, a probe id (flow × 10⁶ + sequence number) and the send time.

### 2.5 The fault ("up but slow")

- **Which link.** The rule takes the laser links on the Chennai→London path at t = 20 s and picks
  the one most used by all scheduled paths during the fault. The result was **ISL 4478,
  STARLINK-35318 ↔ STARLINK-35575** (an intra-plane link). Chennai→London and London→Chennai
  cross it, one flow in each direction.
- **What happens to it.** From t = 20 s to t = 40 s its data rate drops from 1 Gb/s to
  **200 kb/s** in both directions. The link stays up.
- **How big that fault is.** One probe flow puts 290-byte frames on this link 100 times a
  second: **232 kb/s**. At 200 kb/s the link is 1.16× overloaded, so its queue grows until the
  100-packet DropTail queue is full; a probe at the back then waits 100 × 290 × 8 bit /
  200 kb/s = **1.16 s**.
- **Why 200 kb/s and not 1 Mb/s (measured, not assumed).** The same fault at 1 Mb/s, 500 kb/s and
  250 kb/s is in `sensitivity.json` (one extra ns-3 run each, same link, same 20 s): **0 of
  4,000** crossing probes were flagged at each rate, and none was lost. While the link stays
  faster than its load, no queue builds and each probe only takes longer to transmit: 2.3 ms at
  1 Mb/s, 9.3 ms at 250 kb/s. The probes reach the far end of this link with 10.9–14.2 ms of
  slack before their deadline (measured in the no-fault run), so they stay on time. Detection
  here needs a link that is slower than its load.
- **Ground truth.** The fault is logged in `fault/fault_log.csv`.
- **Paired run.** The same links and probes are also run without the fault (`nofault/`).
- **Deviation policy is `continue`.** A late packet is flagged and keeps its path; the greedy
  fallback is a later phase. `run_info.json` records the policy each node really applied
  (`effective_policy`: `continue` at every node).

### 2.6 Why on-time packets are never flagged

The schedule's deadlines include 0.5 ms of processing per hop and a slack factor of 1.5, and
ns-3 forwards with zero processing delay. Measured in the no-fault run (`margins.json`,
`crosscheck_nofault.json`):

- On-time probes arrive **3.5–11.9 ms before the planner's predicted arrival time** (the sum of
  the predicted hop delays).
- The deadline is 1.5 × that prediction, so the margin to the **final** deadline is much
  larger: **18.3–56.6 ms** (median 35.9 ms).
- The tightest deadline on every path is at the **first hop** (all 60,000 probes): a margin of
  **1.6–2.4 ms** (median 1.9 ms). Further down a path the slack accumulates; at the far end of
  the slowed link it is 10.9–14.2 ms.

A probe is flagged only when something delays it by more than the margin at that hop, which no
on-time probe came close to.

## 3. Results (main bundle, 60 s, full sub-shell)

### 3.1 Cost (WSL2, i9-13900H, 7.6 GiB RAM)

| Run | Nodes / links built | Wall time | Peak memory (RSS) |
|---|---|---|---|
| No fault, all 10 flows | 2,857 / 5,361 laser + 205 ground | 17.2 s (load 0.8 s, build 0.7 s, simulate 15.0 s) | 194 MiB |
| Fault, all 10 flows | the same | 18.7 s | 194 MiB |
| Fault-rate sensitivity (3 runs) | the same | 17.2–17.8 s each | 194 MiB |
| NetAnim slice | 202 / 348 laser + 26 ground | 1.2 s | 80 MiB |
| Bundle from its recipe (`cr export bundle`) | | 16.8 s | 0.79 GB |
| Driver total (bundle, 6 ns-3 runs, Python analysis) | | 189 s | 1.34 GB (the Python analysis) |

Wall times are from the driver; ns-3 peak memory is the program's own high-water mark (VmHWM).
Both vary by a few percent between repeats (the previous identical run took 16.6 s for the fault
run). The bundle's and the driver's peak memory were measured with `/usr/bin/time` on identical
runs.

The full sub-shell fits easily, so the window did not have to be reduced. The topology changed
2,282,353 times (delay writes), with 195 link-down and 5 link-up events, none of them on a
scheduled path while it was in use.

### 3.2 No fault: delivery and latency per flow

| Flow | Delivered / sent | PDR | Latency p50 | Latency p99 |
|---|---|---|---|---|
| Chennai → London | 6,000 / 6,000 | 1.000 | 31.42 ms | 31.59 ms |
| New York → Sydney | 6,000 / 6,000 | 1.000 | 76.60 ms | 77.00 ms |
| Sao Paulo → Tokyo | 6,000 / 6,000 | 1.000 | 68.92 ms | 69.20 ms |
| Mumbai → Frankfurt | 6,000 / 6,000 | 1.000 | 27.29 ms | 27.52 ms |
| Singapore → Johannesburg | 6,000 / 6,000 | 1.000 | 46.08 ms | 46.66 ms |
| London → Chennai | 6,000 / 6,000 | 1.000 | 31.42 ms | 31.59 ms |
| Sydney → New York | 6,000 / 6,000 | 1.000 | 76.60 ms | 77.00 ms |
| Tokyo → Sao Paulo | 6,000 / 6,000 | 1.000 | 68.91 ms | 69.20 ms |
| Frankfurt → Mumbai | 6,000 / 6,000 | 1.000 | 27.29 ms | 27.52 ms |
| Johannesburg → Singapore | 6,000 / 6,000 | 1.000 | 46.08 ms | 46.66 ms |

- **No flags.** Not one of the 60,000 probes was flagged late.
- **No losses** (`loss_causes.json` is empty for both runs).
- **Why there are no handover losses.** The planner uses only links that stay up for the whole
  interval plus the path's final deadline, and a city keeps a satellite while it is visible.
  An earlier version of this milestone re-picked each city's 4 highest satellites every 100 ms
  and planned on the links up at the start of each second. That variant is still available
  (`--gsl-policy highest_elevation_top_k --plan-links instant`, which rebuilds that bundle byte
  for byte); with it 26 of the 600 schedule rows lose a link while in use
  (`docs/bundle-format.md` §1.4). Re-run with the current programs (outside `results/`, as a
  check): 58,810 of 60,000 delivered; 1,190 lost (1.98 %) at ground-link handovers (560 at the
  source city's uplink, 623 at the destination's downlink, 7 in flight). Python predicts
  exactly the same losses, including DEV with Dev Hop 0 on all 560 drops at the source.

### 3.3 With the fault: per flow, and detection

Only the two flows whose paths use ISL 4478 change; the other eight are identical to the
no-fault run. "Flagged" is the share of probes delivered with DEV set, grouped by **send time**.

| Flow | PDR | Latency p99 | Lost in the slow queue | Flagged before / during / after |
|---|---|---|---|---|
| Chennai → London | 0.971 | 1,202 ms | 177 | 0.001 / 0.9995 / 0 |
| London → Chennai | 0.971 | 1,202 ms | 176 | 0 / 0.998 / 0 |

- **"Before" is not zero:** two probes were sent just before 20 s (at 19.990 s and 19.9996 s) but
  reached the link after it slowed.

**Detection** (`detection.json`; window = when a probe reached the link, 20–40 s):

| Quantity | Value |
|---|---|
| Size of the fault | 1 Gb/s → 200 kb/s for 20 s, link up; load 232 kb/s per direction (1.16× overload) |
| Probes that entered the slowed link | 4,000 |
| Lost in its DropTail queue | 352 (plus 1 that reached the link just after 40 s, while the queue was still full) |
| Crossed it | 3,648 |
| Crossed it and were flagged late | **3,645 (99.92 %)** |
| The same 3,648 probes in the no-fault run, flagged | **0 (0 %)** |
| Flagged anywhere in the no-fault run (60,000 probes) | 0 |
| Flagged in the fault run without crossing the link | 0 |
| First flag after the fault started | 16.9 ms |
| How late at detection (median, in 0.1 ms units) | 11,494 units = 1.15 s (queueing delay) |
| Same fault at 1 Mb/s / 500 kb/s / 250 kb/s (`sensitivity.json`) | 0 / 0 / 0 of 4,000 flagged, 0 lost |

- **Where lateness is detected.** The program also checks that every late probe was caught at
  the **far end** of the slowed link: Dev Hop is that node's hop index (hop 4 on
  Chennai→London, hop 5 on London→Chennai).
- **The three probes that were not flagged** (all London→Chennai) reached the link 1.8 ms and
  11.8 ms after it slowed down, while its queue was still short, and 8.0 ms before it
  recovered (the queue then drained at 1 Gb/s). Their extra delay stayed inside their 10.9 ms+
  of slack.
- **This fault is not hidden from the satellite in front of it.** A 100-packet queue that
  stays full for 20 s can be seen by the near-end node in its own device queue, without any
  deadline. The detection rate therefore shows that the deadline check works end to end, not
  that it finds faults a local-queue monitor would miss. The milder faults that would test that
  (250 kb/s and up) were not detected by deadlines either.

### 3.4 E16-lite: ns-3 against an independent Python prediction

**What the prediction is.** For each probe (`sim/chronoroute/export/ns3_crosscheck.py`):
- it takes the schedule row valid at send time;
- it builds and processes the T-CRH hop by hop with the golden-tested Python reference
  (`chronoroute.proto`);
- it computes the timing from the same held link delays plus serialization (bytes × 8 ns at
  1 Gb/s);
- it applies the same link-down rules (DEV with Dev Hop = the holding node, also at the source).

The prediction has no queues.

| Check (no-fault run) | Result |
|---|---|
| Probes compared | 60,000 |
| Path identical | **60,000 (100 %)** |
| Outcome (delivered / lost where) identical | 60,000 (100 %) |
| DEV and Dev Hop identical, every outcome | 60,000 (100 %) |
| Arrival time, unit clock and deadline at every hop identical | 60,000 (100 %) |
| ns-3 latency − Python light time | 16.2–64.9 µs. This is exactly serialization: (number of links) × 2,320–2,704 ns |
| Left over after subtracting serialization (queueing) | **0 ns for all 60,000 delivered probes** |
| ns-3 latency − the schedule's own prediction | −3.5 to −11.9 ms: the 0.5 ms per hop of processing that ns-3 does not model |

- **Fault run:** the same comparison, leaving out the probes that met the slowed link between
  20 s and 41 s, gives 55,800 of 55,800 identical (DEV and Dev Hop included).
- **NetAnim slice:** with only its own flow and 200 satellites, it reproduces the full fault run
  exactly (path and latency) for all 600 of its probes, the slowed link included, because no
  other flow uses that direction of the link.

### 3.5 Wireshark check (`tools/wireshark/check_pcap.sh`, tshark 4.6.4)

- **Where the capture comes from.** It is taken at 4 nodes on the Chennai→London path: the
  Chennai station, both ends of the slowed link, and the last satellite before London.
  - One file per run, recorded when each frame starts to leave the node.
  - Point-to-point framing, nanosecond time stamps in UTC.

| | No fault | Fault |
|---|---|---|
| T-CRH frames | 42,000 | 41,117 |
| Invalid frames | **0** | **0** |
| Frames with DEV | 0 | 5,469, all between 20 s and 42 s |
| T-CRH copies quoted in ICMPv6 errors (counted apart, never as T-CRH frames) | 0 | 0 |
| Probes seen at 2 or more nodes with Segments Left not strictly decreasing | 0 of 12,000 | 0 of 11,647 |

**Why "late at capture" is not zero.** The tool's "late at capture" count (9,073 in the fault
capture) is not a fault: the frame is captured when it leaves a node, after any time in that
node's queue. At the near end of the slowed link a frame can therefore already be past its next
deadline while DEV is still clear. DEV is set by the next node, on arrival.

To see one probe as tshark prints it: `tshark -r results/course-milestone/c5-463-60s-seed1/fault/capture.pcap.gz
-X lua_script:tools/wireshark/tcrh.lua -Y "tcrh.flags.dev == 1" -T fields -e frame.time_epoch
-e ipv6.dst -e ipv6.routing.segleft -e tcrh.flags -e tcrh.dev_hop -e tcrh.margin_ms`.

### 3.6 NetAnim slice (`anim/anim.xml`)

- **What it shows.** 200 satellites around the Chennai→London paths, plus the two cities, on a
  world map:
  - X = ((longitude − 40.1° + 540) mod 360) × 10, Y = (90 − latitude) × 10;
  - 374 point-to-point links drawn (348 laser, 26 ground);
  - positions updated every 1 s.
- **Packets.** 4,800 packet transmissions between 18 s and 24 s, each with its metadata
  (`T-CRH(nh=17 sl=… flags=0x11 … devHop=4 …)`); 1,608 of them carry DEV.
- **The fault.** The slowed link gets the description "DEGRADED 200000 b/s (still UP)" at 20 s.
- **Red node.** The far-end satellite, where the deviation is detected, turns red at 20.017 s.
- **To view it:** `QT_QPA_PLATFORM=xcb ~/netanim/build/netanim`, then File → Open. The XML was
  checked with an XML parser, but the NetAnim GUI itself was not opened for this write-up.

### 3.7 Small bundle (10 s, 3 cities, 4 flows)

- **Fault:** ISL 4478 slowed to 200 kb/s from 4 s to 7 s (crossed by Chennai→London and
  London→Chennai).
- **Cross-check:** 4,000 of 4,000 probes identical; residual 0 ns.
- **Detection:** 598 of 600 = 99.7 %, baseline 0 %; 0 lost in the queue (3 s is too short to
  fill it at a 1.16× overload). At 1 Mb/s, 500 kb/s and 250 kb/s: 0 of 600 flagged.
- **Wireshark:** 0 invalid frames.
- **NetAnim slice:** identical to the full run for all 600 of its probes.
- **Losses:** none; all 4,000 no-fault probes delivered.

## 4. How to reproduce

Run inside WSL from `~/chronoroute`.

```bash
# build (never more than 8 jobs on this machine)
cd ~/ns-3-dev && ./ns3 build -j8

# the whole milestone from git: bundle from its recipe, build check, 6 ns-3 runs, analysis, manifest
cd ~/chronoroute
venv/bin/python -B ns3/run_leo.py --recipe c5-463-60s          # about 3 minutes
venv/bin/python -B ns3/run_leo.py --recipe c5-463-10s-small    # about 20 s
# (bundles go to $CR_BUNDLE_ROOT or /tmp/cr-bundles; --bundle DIR runs on an existing bundle)

# tests: Python replay, and ns-3 against Python on a synthetic bundle with every awkward case
venv/bin/python -B -m pytest sim/tests/test_ns3_crosscheck.py
make ns3-test

# one ns-3 run by hand (it checks itself and exits 1 on failure)
~/ns-3-dev/build/contrib/chronoroute/examples/ns3.44-chronoroute-leo-default \
    --bundle=/tmp/cr-bundles/c5-463-60s --outDir=/tmp/cr-sa/course/x --fault=1

# re-check a capture
tools/wireshark/check_pcap.sh results/course-milestone/c5-463-60s-seed1/fault/capture.pcap.gz
```

The runs are deterministic: rebuilt bundles are byte-identical (the manifest records each
bundle file's sha256), and repeated runs give byte-identical `packets.csv`, `capture.pcap`,
`fault_log.csv`, `anim.xml` and analysis files (checked by rebuilding and rerunning the small
bundle from its recipe; for the 60 s bundle two runs printed identical analysis results).

Note for reruns with the current ns-3 program: for the E16 engine comparison the program now
appends four columns to `packets.csv` (`tx_ns`, `wait_ns`, `tx_loss_at`, `link_down_at`). The
committed milestone files were written before that change and have the original 26 columns.
A rerun therefore gives a wider `packets.csv`; its first 26 columns are byte-identical to the
committed files, so compare those columns (or drop the four new ones) when checking a rerun.

### Output files (per run folder)

| File | What it holds |
|---|---|
| `nofault/`, `fault/`, `anim/packets.csv.gz` | One row per probe. Columns: planned and taken path, arrival time / clock / deadline / margin at every hop, first late hop, link-down hop, DEV, Dev Hop, outcome (`delivered`, `drop_link_down`, `drop_iface_down`, `drop_queue`), latency, whether it used the slowed link, fault phase (26 columns in the committed files; the current program also writes `tx_ns`, `wait_ns`, `tx_loss_at` and `link_down_at`, see above) |
| `sensitivity/<rate>/slowed_link_probes.csv.gz` | The same columns, only for the probes that met the slowed link (the other rows equal the no-fault run's) |
| `*/capture.pcap.gz` | The T-CRH capture (Wireshark opens `.pcap.gz` directly) |
| `*/fault_log.csv` | The fault as applied (ground truth); only a header in `nofault/` |
| `*/run_info.json`, `*/ns3.log` | Counts, timings, peak memory, the effective deviation policy, the program's self-checks |
| `anim/anim.xml` | The NetAnim slice |
| `flow_summary.csv` | The tables in §3.2 and §3.3 |
| `detection.json`, `sensitivity.json` | §3.3 and the fault-rate sensitivity |
| `margins.json` | §2.6 |
| `loss_causes.json` | Link-down losses by kind of link (empty here) |
| `crosscheck_nofault.json`, `crosscheck_fault.json` | §3.4 |
| `pcap_check.json` | §3.5 |
| `run.log`, `manifest.json` | Everything the driver printed, and the provenance |

## 5. Limitations (read before quoting a number)

**Physics and network model**
- **Delays are held for each 100 ms step**, not interpolated. The difference is at most 1.80 µs
  per hop in this run.
- **Zero processing delay in ns-3.** The schedule's 0.5 ms per hop of processing therefore acts
  as extra slack: deadlines are looser in ns-3 than the planner assumed (§2.6).
- **Link rate, queues and traffic are MODELLED.** The probe load is tiny for 1 Gb/s, so there
  is no congestion at all except on the faulted link.
- **One fault link, one seed.** The main fault is one magnitude (200 kb/s for 20 s); three
  milder magnitudes were run as a sensitivity. There are no confidence intervals because there
  is only one run per condition.
- **Long laser hops.** Intra-plane links span gaps in the real planes up to the 80 km grazing
  limit; the longest laser link on a milestone path is 4,095 km. A range limit is available
  but not applied (`docs/bundle-format.md` §1.1).

**ChronoRoute behaviour**
- **No handover losses, by construction.** The planner knows the predictable topology
  (§3.2). Losses from real surprises, such as a link that fails without warning, are not
  modelled in this milestone.
- **No greedy fallback (policy `continue`).** A packet whose next link is down is dropped. A
  packet in GREEDY mode was never produced.
- **Detection is measured on probes that crossed the link.** A probe that is lost in the slow
  queue can never be flagged, so the 352 queue losses are reported separately.
- **No local-queue baseline yet** (§3.3). This fault is visible to the near-end node's queue.

**Representation in ns-3**
- **Ground links are separate point-to-point links per (city, satellite) pair**, switched on and
  off. They are not a shared radio channel. NetAnim cannot draw handovers, so link state changes
  appear only as link descriptions.
- **Grid-4 laser links, the 25° mask and the ground-link choice are MODELLED.** Starlink's
  real topology and assignment are not public.
- **No processing of other extension headers or of TCP** in this milestone: UDP probes only.

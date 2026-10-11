# The in-tool viewer (`cr viz`)

The viewer shows a run the way it happened: the **real** Starlink satellites over a textured
Earth, the **modelled** laser links, and one packet hopping along its T-CRH path in slow
motion. At the hop where a deadline is missed the satellite flashes red, the HUD says by how
much, and (if the run used a fallback) the rest of the path turns magenta.

* `cr viz globe`: the 3D viewer (PyVista / VTK), in a desktop window or off-screen (PNG, MP4).
* `cr viz map2d`: the 2D fallback (matplotlib), for machines without a working OpenGL window.
* `cr trace from-ns3`: turns an ns-3 course-milestone run into the same trace format, so the
  ns-3 run plays on the same globe.

Code: `sim/chronoroute/viz/` (`sources.py` data, `player.py` clocks and keys, `hud.py` text,
`globe.py` 3D, `map2d.py` 2D, `record.py` MP4, `command.py` commands) and
`sim/chronoroute/trace/ns3_import.py`. Tests: `sim/tests/test_viz_*.py`,
`sim/tests/test_ns3_import.py`.

## 1. Launching

Run inside WSL from `~/chronoroute` (keep the terminal open: WSL closes WSLg windows when the
last shell exits).

```bash
# the ns-3 milestone (small run) on the globe: convert once, then view
venv/bin/cr trace from-ns3 results/course-milestone/c5-463-10s-small-seed1 --out /tmp/cr-viz/small-fault
venv/bin/cr viz globe --trace /tmp/cr-viz/small-fault

# a python-sim run (cr run ... --out DIR writes a trace folder)
venv/bin/cr viz globe --trace DIR --follow "Chennai->London"

# today's fleet only (no packets); one shell with its Grid-4 links
venv/bin/cr viz globe --snapshot data/pinned/20261010T1358Z-celestrak
venv/bin/cr viz globe --snapshot data/pinned/20261010T1358Z-celestrak --shell 53.2deg-463km

# off-screen: a 1920x1080 MP4 (plays the first packet, then the recorded deadline miss), a PNG
venv/bin/cr viz globe --trace /tmp/cr-viz/small-fault --record /tmp/cr-viz/rec/globe.mp4 --seconds 20
venv/bin/cr viz globe --trace /tmp/cr-viz/small-fault --screenshot /tmp/cr-viz/miss.png --at 10.3

# the 2D fallback: a window, or a PNG / MP4
venv/bin/cr viz map2d --trace /tmp/cr-viz/small-fault
venv/bin/cr viz map2d --trace /tmp/cr-viz/small-fault --out /tmp/cr-viz/map.png --at 10.3
```

### GPU under WSLg (`GALLIUM_DRIVER=d3d12`)

WSLg's default OpenGL driver is **llvmpipe**, a software renderer. Mesa's `d3d12` driver puts
OpenGL on the Windows GPU (here: "D3D12 (Intel(R) Iris(R) Xe Graphics)", OpenGL 4.1). `cr viz
globe` sets `GALLIUM_DRIVER=d3d12` by itself when `/dev/dxg` exists and you have not set
`GALLIUM_DRIVER` or `LIBGL_ALWAYS_SOFTWARE`; it prints what it chose. To choose yourself:

```bash
export GALLIUM_DRIVER=d3d12          # GPU (recommended)
venv/bin/cr viz globe ... --software # force llvmpipe (if the GPU window is black or crashes)
```

The HUD's bottom line always names the renderer VTK really got, for example
`renderer: D3D12 (Intel(R) Iris(R) Xe Graphics), OpenGL 4.1` or
`renderer: llvmpipe (LLVM 21.1.8, 256 bits) (software), OpenGL 4.5`, so a software fallback is
never hidden.

Without a display (`DISPLAY` and `WAYLAND_DISPLAY` unset) the window cannot open; use
`--record`, `--screenshot` or `cr viz map2d --out`. Off-screen rendering needs no display.

### Options

| Option | Meaning |
|---|---|
| `--trace DIR` / `--snapshot DIR` | a `chronoroute.trace/1` run folder, or a pinned snapshot (fleet view) |
| `--follow FLOW` | the flow to show: its id or `"Src->Dst"`. Default: the flow of the first deadline miss |
| `--shell ID` | snapshot view: one shell and its Grid-4 links (default: the whole fleet) |
| `--cities "A,B"` | extra labelled cities |
| `--start ISO` | orbit clock start (default: the first packet, or the snapshot's fetch time) |
| `--orbit-speed X` | orbit clock speed (default x60) |
| `--slowmo X` | packet slow motion (default x100: 1 ms of packet time takes 100 ms) |
| `--lite auto\|on\|off` | laser links only near the packet's path (auto: above 3,000 satellites) |
| `--autoplay` | play packets by themselves (always on when recording) |
| `--record OUT.mp4 --seconds N [--fps 30]` | off-screen MP4 at `--size` (default 1920x1080) |
| `--screenshot OUT.png --at S` | one off-screen frame after S seconds of autoplay |
| `--bench N` | time N off-screen frames and print the result (section 5) |

## 2. Keys

| Key | What it does |
|---|---|
| `space` | next packet of the followed flow |
| `m` | next packet of the flow that missed a deadline |
| `d` | degrade the selected link: a rate cut (see below) |
| `f` | fail the selected link: link down (see below) |
| `[` / `]` | move the selected link one hop back / forward along the packet's path |
| `l` | link-state view on/off: every laser link green (up) or red (down), as a link-state protocol sees them. An up-but-slow link stays **green** |
| `+` / `-` | faster / slower: the packet clock while a packet is shown, else the orbit clock |
| `r` | replay the current packet |
| right-click | pick a satellite: name, NORAD id, SID, its element set and epoch age at the orbit clock, position |

Mouse: left-drag rotates, wheel zooms (VTK's trackball camera). `cr viz map2d` has the same
keys (`=` also works for `+`), without the right-click pick.

**`d`, `f` and live mode.** If the simulator offers its re-run hook (`chronoroute.fwd.engine.rerun_with_fault`,
looked up at run time) and the trace comes from `python-sim`, the viewer is **live**: `d` re-runs
the whole run with the selected link degraded (a rate cut to 0.0002 x C, i.e. 200 kb/s at 1 Gb/s:
the course milestone's fault), `f` with it failed (link down), from the instant on screen (the send
time of the packet being shown) to the end of the sending window. The re-run uses the run's own
config and seed from `run.json` (`engine.config`), so every random number is the same (common
random numbers, `fwd/rerun.py`): a packet that never meets the new fault is identical in both
runs. The viewer switches to the new run (written next to the original, named
`<run>--rerun-<kind>-<a>-<b>-t<start_ns>`, with its own manifest), keeps the followed flow and the
selected link, and plays the first packet of the flow whose story changed (preferring one that
was late, took a fallback or was dropped); the HUD says how many packets of the flow changed. A
key always re-runs the run ON SCREEN, so after a first live key the next one ADDS a fault to the
previous ones: they are all active. The message then names every one of them, and the HUD keeps
the list on screen for as long as the re-run is shown (globe: orange text on the right; 2D map:
the side panel), from `run.json` `rerun.live_faults`. To start again from the recorded run, open
it again. When extending an older re-run that lacks the complete list, the engine recovers the
earlier faults from its parent `run.json` files, including a partial list whose claimed original
is itself a re-run. Current complete lists remain usable if ancestor folders have moved. If a
required history is missing or cyclic, live mode reports the error and keeps the recorded run
on screen. A re-run is a full run of every flow,
so it takes as long as the original (seconds on C1, minutes on
the real shell). Otherwise (no hook, an ns-3 trace, or the re-run failed) the viewer is
**replay-only** and says why on the HUD: `d` and `f` then jump to the first packet of the flow that
crossed the **recorded** faulted link while the fault was active (preferring one that was flagged
late). It never pretends that a new fault was simulated. On a link without a recorded fault it
says so and names the faulted link.

## 3. What you see

| On screen | What it is | Label |
|---|---|---|
| Satellite positions | SGP4 on the pinned CelesTrak element sets, at exactly the orbit clock (or the bundle's 1 s SGP4 samples, interpolated: section 4) | REAL (a synthetic Walker run: MODELLED, and the label line says so) |
| City markers | Natural Earth coordinates (`data/static/cities.csv`) | REAL |
| Earth | NASA Blue Marble (2004 composite) on the WGS84 ellipsoid, Earth-fixed; clouds and season do not follow the date (`viz/assets/CREDITS.md`) | imagery |
| Laser links (blue lines) | Grid-4 pairs of the run (bundle `isl.csv`, or recomputed with `topo/isl_grid4.py` at t0), up/down by the topology model's rules | MODELLED |
| Path (thick line) | the hops the packet really took (yellow = travelled, dim = still to come, magenta = after a fallback) | from the trace |
| Orange tube | the selected link (`d`), usually the run's faulted link | ground truth of a MODELLED fault |
| Hop table | per hop: SID, satellite name, deadline, arrival, margin (below) | REAL header bytes / DERIVED deadlines |
| Header hex | the trace's T-CRH bytes, Segments Left (byte 3) and Flags (byte 4) in colour | REAL code output |
| Queues, link rates, faults | whatever the run modelled | MODELLED |

The label line at the bottom reads, for example,
`Positions REAL (snapshot 20261010T1358Z-celestrak, SGP4) | ISLs MODELLED (Grid-4) | Queues MODELLED`.
For a trace positioned from a bundle (ns-3) it says how the positions on screen were computed at
that moment: `SGP4 samples at 1 s from the bundle, interpolated` inside the bundle's window (with
`HELD outside the bundle window` when a sample is held), and `SGP4 evaluated directly (outside the
bundle's sample window)` once the orbit clock has left it (`hud.positions_note`).
The values are the run's own `labels` (keys and values of the shared table
`sim/chronoroute/labels.py`). Nothing is assumed: a synthetic Walker run shows
`Positions MODELLED (synthetic Walker preset ...)`, and a label the run does not give shows as
`NOT LABELLED`.

**Hop table units** (spec/tcrh-v1.md sections 4-6). `arrival` is the arrival time minus the
send time, exact. `deadline` is the instant after which the packet counts as late at that hop:
a node is late when its clock is past the deadline unit D_k, i.e. from (D_k + 1) x u on.
`margin` is D_k - now_u in units (serial arithmetic) times the unit: exactly the comparison
the node made. So "arrival > deadline" and "margin < 0" always agree; a late row is red.

**Header bytes.** The HUD shows the bytes of the most recent event that has them, and says
which moment they are from: "leaving the source", "as it arrived" (a `hop` event: Segments
Left counts down h - 1, h - 2, ... over the hops, h = number of hops), "after the deadline
check" (a `late` event: DEV just set), "as delivered". At a node that set DEV the HUD keeps the
bytes AS THEY ARRIVED and adds "this node set DEV: leaves with Flags=0x.." from the `late` event
(which carries the bytes after processing, spec/trace-v1.md section 3), so it shows both what the
node saw and what it did. Traces store bytes only for sampled packets; for
the others the HUD shows SL and Flags from the events and says the bytes were not sampled.

### Two clocks

* **Orbit clock** (UTC): drives the satellite positions, x60 by default.
* **Packet clock**: the trace time of the packet being shown, in slow motion (x100 by default).

While a packet is shown the orbit clock is **frozen** at its send time. A LEO satellite moves
about 7.6 m per millisecond, so during a 40-70 ms trip the constellation moves well under 1 km,
far below a pixel. Between two arrivals the packet waits at the node for whatever the run put
there (serialization, queueing, processing) and then flies the straight line at the speed of
light. A segment never takes more than 2.5 s on screen; when one is shortened (the ns-3 fault's
1.16 s queues) the HUD says `FAST-FORWARD` with its real length.

### Lite mode

Above 3,000 satellites (`--lite auto`), laser links are drawn only within two link hops of the
packet's path, and none while no packet is shown. The snapshot view of the whole fleet (11,130
satellites) is in Lite mode; `--shell 53.2deg-463km` (2,847 satellites in planes, 5,361
Grid-4 pairs) is not.

## 4. Data sources

* **Trace folder** (`chronoroute.trace/1`, [spec/trace-v1.md](../spec/trace-v1.md)): `run.json` +
  `events.jsonl.gz`. Laser links come from the bundle the run replayed (`isl.csv`), else from
  the bundle copy its positions point at, else Grid-4 recomputed from the snapshot at t0 with
  the same code the simulator uses (a test checks that the two give the same 5,361 pairs).
  The viewer checks it strictly and refuses, with the reason, anything that would draw
  something false: a wrong schema, t0_gps_ns not equal to t0_utc + 18 s, events not sorted by
  (t, pkt), an unknown node, a malformed field. Softer problems (a packet whose hops do not
  chain, unknown extra keys) are listed, not hidden.
* **Positions.** `positions.source = snapshot`: SGP4 at exactly the instant drawn (the path may
  name a pinned folder, a raw element file inside one, or a plain OMM file such as a synthetic
  run's `synthetic_omm.json`). `positions.source = bundle`: the bundle's `positions.csv`
  (1 s samples of the same SGP4), between samples a cubic Hermite curve with second-order
  difference tangents. Measured against SGP4 on the small milestone bundle (all 2,847
  satellites, at quarter and half seconds): at most 17 mm, where straight lines would be off
  by up to 1.0 m; the test bound is 5 cm. Outside the bundle's window SGP4 from the snapshot
  takes over (or the last sample is held, and the HUD says so).
* **ns-3 runs.** `cr trace from-ns3 RUN_DIR --out DIR [--variant fault|nofault|anim]` reads
  `packets.csv.gz`, `run_info.json`, `fault_log.csv` and the run's bundle (checked file by file
  against the run manifest's sha256; `--rebuild-bundle DIR` rebuilds it from its recorded
  recipe, byte for byte). Times, paths, clocks, deadlines, margins, DEV and outcomes are copied;
  the header bytes are rebuilt from the bundle's templates with the golden-tested reference, and
  every value that packets.csv also records is compared (the import stops at the first
  difference). Packet ids are the ns-3 probe uids, checked to be the rank of (send time, flow
  id) as the spec requires. The output folder holds `run.json`, `events.jsonl.gz`, `bundle/`
  (byte-identical copies of the bundle's `positions.csv`, `nodes.csv`, `isl.csv`,
  `scenario.json`; run.json's positions point there, so the trace does not depend on the
  `/tmp` bundle) and `manifest.json`. Header bytes are kept for every 100th probe, the first 10
  probes of each flow and the first 10 late probes of each flow (`--hex-every`, `--hex-first`,
  `--hex-late`). Only runs whose effective deviation policy is `continue` are accepted (the
  milestone runs are): the importer does not guess what a fallback would have done.

  Measured: the small run (4,000 probes, 48,598 events) converts in about 1.2 s; the 60 s run
  (60,000 probes, 977,256 events, 3,645 late, 353 queue drops) in 27 s with 0.91 GB peak
  memory, and loads in the viewer in 8.6 s (0.51 GB). Both pass the simulator's own trace
  validator (`trace/reader.validate_run`).

## 5. Speed (measured)

`cr viz globe --snapshot data/pinned/20261010T1358Z-celestrak --shell 53.2deg-463km --bench 60`:
the 463 km shell (2,847 satellites, 5,336 laser links up in the measured frame), the orbit
clock running so every frame has new SGP4 positions, a new link state and a new scene.
Off-screen, because no window can be opened in an automated run. WSL2 on an i9-13900H with
Intel Iris Xe, 2026-10-11; other jobs were using the machine (load average 1.4 to 6.5), so
each cell is the range of the medians of 3 runs of 60 frames:

| Renderer | Size | Animation: update + render per frame | Animation frame rate | Recording: update + render + read-back |
|---|---|---|---|---|
| D3D12 (Iris Xe) | 1920x1080 | 32-55 ms | **18-31 fps** | 58-114 ms (9-17 fps) |
| D3D12 (Iris Xe) | 1440x810 (WSLg's window size) | 35-48 ms | **21-29 fps** | 67-105 ms |
| llvmpipe (software) | 1920x1080 | 113-120 ms | 8.4-8.8 fps | 125-132 ms |
| llvmpipe (software) | 1440x810 | 86-92 ms | 10.8-11.6 fps | 97-106 ms |

"Update" (SGP4 for 2,847 satellites, the Grid-4 up/down rule for 5,361 pairs, the scene and
HUD) is 5-14 ms of that. On the GPU the split between update and render varies from run to
run (the driver may finish the previous frame during the next update), so only the sum is
quoted. An on-screen window also presents its frames through WSLg, which a headless run
cannot measure, so these numbers are an upper bound for the window.

## 6. Limitations

* The Earth image is a 2004 composite: no day/night terminator, clouds or season.
* Packets are drawn on straight lines between nodes at positions frozen at the send time.
* Text uses the DejaVu fonts that ship inside matplotlib; VTK's built-in fonts lack `|`.
* The 2D map shows sub-satellite points: long links look bent and altitude is not visible.
* Live mode re-runs the WHOLE run (every flow: common random numbers need the same traffic), so
  on the real shell a key press waits minutes and the viewer is blocked meanwhile. Traces written
  before `run.json` carried `engine.config` cannot be re-run (the re-run fails, the HUD says so and
  shows the recorded fault instead).
* The interactive window was not opened during automated testing (key bindings are tested on a
  never-shown window; everything drawn is tested off-screen).

# The 9-minute demo

Run `tools/viva-prepare.sh --site` first (see `README.md`). All paths below assume WSL, the
repository in `~/chronoroute` and the prepared files in `~/cr-viva`. Commands are typed in the
WSL terminal from `~/chronoroute`. Every step has a fallback in `backup-plan.md`.

## Setup (before the examiner arrives)

```bash
cd ~/chronoroute
export GALLIUM_DRIVER=d3d12          # the laptop GPU for the 3D viewer (WSLg)
venv/bin/cr --help >/dev/null && echo ok
```

* Wireshark (Windows): Edit > Configuration Profiles > **ChronoRoute**. File > Open
  `\\wsl.localhost\ubuntu\home\aeehprrst\cr-viva\wireshark\small-fault.pcap`. Leave it open.
* NetAnim (WSL): `QT_QPA_PLATFORM=xcb ~/netanim/build/netanim &`, then File > Open
  `/home/aeehprrst/cr-viva/netanim/anim-60s.xml`. Leave it open.
* Browser tabs: the home page, `/network/`, `/experiments/e1/`, `/route/`.

## 0:00 - 0:45  The problem and the idea (website home page)

Say: satellites move at 7.6 km/s, but their orbits are predictable, so a ground station can
plan a route in advance. A planned route cannot see a laser link that is still **up** but has
become **slow**; hello-based routing only notices links that go **down**. ChronoRoute puts a
deadline for every hop into the packet's IPv6 Routing Header, so the packet itself shows when
the plan has broken.

Point at the decoded header on the home page: Routing Type 253, Segments Left, Epoch_Base, the
SID + delta entries.

## 0:45 - 1:45  Real data

```bash
venv/bin/cr fleet report data/pinned/20261010T1358Z-celestrak --out ~/cr-viva/fleet-live
```

Say: this is the real Starlink fleet from a CelesTrak snapshot (11,130 satellites), split
into shells and orbital planes from the data. We use the 53 degree / 463 km shell. Positions
are REAL (SGP4); the laser-link layout is MODELLED because Starlink does not publish it.

## 1:45 - 2:45  A route and its header

```bash
venv/bin/cr route --from Chennai --to London
```

Point at: the 9 satellites, light time per hop, budget = 1.5 x (light time + 0.5 ms), the
cumulative deadlines, and the 48-byte T-CRH in hex at the bottom (Next Header 17, Hdr Ext Len 5,
Routing Type 253 = `fd`, Segments Left 10).

## 2:45 - 4:15  A slowed link, in the 3D viewer

```bash
venv/bin/cr viz globe --trace ~/cr-viva/ns3-small-fault
```

Press **m** (next deadline miss). Say: this is a packet from the ns-3 run. The orange link was
slowed from 1 Gb/s to 200 kb/s and stays up. At STARLINK-35318, the satellite after the slow
link, the packet arrives 0.5 ms after its deadline, so that node sets DEV and writes its hop
number into Dev Hop (HUD on the left, header bytes at the bottom). Press **l** to show the
link-state view: the slow link is still green, so link-state routing does not see it.

**Live version (optional, about 3 s per key):**

```bash
venv/bin/cr viz globe --trace ~/cr-viva/live
```

Press **space** to show a packet, **[** / **]** to pick a link on its path, **d** to slow that
link from this moment on. The simulator re-runs with the same random numbers and the viewer
jumps to a packet that is now late.

## 4:15 - 5:15  Wireshark

In Wireshark (already open), type the display filter `tcrh.flags.dev == 1` and press Enter:
898 of the 7,000 frames. Click one, expand **Routing Header for IPv6 (Experiment 1) >
ChronoRoute T-CRH** and point at
Segments Left, Flags (DEV), Dev Hop, Epoch_Base, the per-hop deadlines and the margin
(negative = late). Say: the dissector is our Lua code; it computes every deadline from the
bytes, exactly as the satellites do.

## 5:15 - 6:15  ns-3 and NetAnim

```bash
venv/bin/python -B ns3/run_leo.py --recipe c5-463-10s-small --no-build --out-root ~/cr-viva/ns3-run
```

(about 25 s). Point at: 2,850 nodes, 5,361 laser links, real IPv6 Routing Type 253 packets,
the `[ok]` self-checks, "the fault made probes late", "every late probe crossed the slowed link
and was caught at its far end", PASS.

Switch to NetAnim, drag the time slider to about 18 s and press Play: packets carry
`T-CRH(...)` metadata; the far-end satellite of the slowed link turns red at 20.017 s.

## 6:15 - 8:15  The website

1. `/network/`: press **Play**. One real ns-3 packet hop by hop: deadline, arrival, margin,
   the late hop in red, the header bytes changing (Segments Left, Flags, Dev Hop). Toggle
   "Same packet, no fault".
2. `/experiments/e1/`: the pre-registered hypothesis and the verdict. Say it plainly: the
   strong rate cut is caught in every run; the nominal rate cut and delays up to 4 ms are not
   caught at the 1% false-alarm limit; a local queue monitor detects more. One comparator
   (LS-D) turned out to be flawed and is reported as such.
3. `/route/`: change the city pair; the browser computes the same header bytes as Python.

## 8:15 - 9:00  Close

Say: the Network-layer change is small (12 + 3 bytes per hop), it is implemented and checked
in four places, and the results are honest: deadlines are a cheap in-band detector for strong
slow-downs and dead links, best combined with local queue monitoring. Starlink does not use
T-CRH; this is a research prototype on real orbit data.

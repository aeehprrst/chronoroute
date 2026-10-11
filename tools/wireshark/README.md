# ChronoRoute in Wireshark (plan phase P6)

Open any capture that carries ChronoRoute packets and read every T-CRH field by name.
tshark can also check every frame for you.

| File | What it is |
|---|---|
| `tcrh.lua` | Dissector for the T-CRH, IPv6 Routing Header **type 253** (spec: `spec/tcrh-v1.md`). Lua 5.4. Tested on tshark 4.6.4 (WSL) and 4.6.9 (Windows); it should work on any 4.4+ release, but none was tested. |
| `profiles/ChronoRoute/` | Wireshark profile: columns SL, Cur SID, T-CRH flags, Margin; DEV frames in red. |
| `check_pcap.sh` | `check_pcap.sh <pcap>`: checks every T-CRH frame and prints one line per frame. |
| `tests/strict_load.lua` | Test helper. It loads `tcrh.lua` with a strict `_ENV` to prove it leaks no globals. |
| `tests/whole_header_probe.lua` | Test helper. It hands `tcrh.lua` a whole header (byte 0 on), which tests the dissector's fallback branch. |

The pcaps come from `sim/chronoroute/trace/pcap.py` (Python, no dependencies). ns-3 point-to-point captures decode the same way.
Tests: `sim/tests/test_wireshark_dissector.py` (with tshark) and `sim/tests/test_trace_pcap.py` (pure Python).

## Quick start (WSL / Linux, nothing installed)

```bash
cd ~/chronoroute
venv/bin/python -B -m chronoroute.trace.pcap golden /tmp/cr-sa/golden    # golden pcaps + manifest.json

# decode with the dissector loaded for this run only
tshark -r /tmp/cr-sa/golden/tcrh_walk_ppp.pcap -X lua_script:tools/wireshark/tcrh.lua

# the automatic check: must print nothing for a valid capture
tshark -r /tmp/cr-sa/golden/tcrh_walk_ppp.pcap -X lua_script:tools/wireshark/tcrh.lua -Y "tcrh.valid == 0"

# per-frame table + validity verdict (exit 0 = all valid)
tools/wireshark/check_pcap.sh /tmp/cr-sa/golden/tcrh_walk_ppp.pcap
```

`check_pcap.sh` output for the demo walk. It is the golden 10-hop path at a real GPS time.
Its link delays are MODELLED: hop 6 is 3x slow, so the packet arrives late there, sets DEV and falls back to greedy forwarding towards SID[0].

```
frame   ipv6.dst                     SL   flags  cur_sid  margin_ms   valid
1       fd00::4b1                    9    0x10   1201     0.5         yes
...
6       fd00::5c8                    4    0x10   1480     -6.4        yes
7       fd00::f003                   0    0x13   61443    -6.4        yes
check_pcap: .../tcrh_walk_ppp.pcap: 7 T-CRH frames, 0 invalid, 1 with DEV, 2 late at capture, 0 quoted in ICMPv6 errors (not counted)
```

A frame whose only T-CRH is a copy quoted inside an ICMPv6 error (for example the Parameter Problem a node sends back
to the source) is listed with `quoted` in the valid column and counted on its own. It never counts as a T-CRH frame,
as DEV, as late or as invalid: the copy shows an older packet, often the malformed one that caused the error.

Exit status: 0 means every T-CRH frame is valid. 1 means some frame is invalid; those frames are listed on stderr.
2 means a usage error, or tshark is missing or failed. 3 means the file has no T-CRH frame (probably the wrong file).
`--timebase utc|off|offset:NS` sets how capture timestamps are read (see *Margin* below). `--quiet` prints only the summary line.

## Install

Wireshark loads every `.lua` file in the personal Lua plugin folder at start-up.
If Wireshark is already open, use **Analyze ▸ Reload Lua Plugins** (Ctrl+Shift+L).

### Windows (Wireshark 4.6.9 GUI)

The folders below are what `tshark -G folders` reports on this machine.

| | Folder |
|---|---|
| Lua plugin | `%APPDATA%\Wireshark\plugins\tcrh.lua` |
| Profile | `%APPDATA%\Wireshark\profiles\ChronoRoute\` (the two files `preferences` and `colorfilters`) |

In PowerShell:

```powershell
$src = "\\wsl.localhost\ubuntu\home\aeehprrst\chronoroute\tools\wireshark"
New-Item -ItemType Directory -Force "$env:APPDATA\Wireshark\plugins", "$env:APPDATA\Wireshark\profiles\ChronoRoute" | Out-Null
Copy-Item "$src\tcrh.lua" "$env:APPDATA\Wireshark\plugins\"
Copy-Item "$src\profiles\ChronoRoute\*" "$env:APPDATA\Wireshark\profiles\ChronoRoute\"
```

To switch to the profile, click the profile name at the bottom right of the status bar, or use **Edit ▸ Configuration Profiles**, and pick **ChronoRoute**.
To open a capture stored in WSL, use **File ▸ Open** with `\\wsl.localhost\ubuntu\tmp\cr-sa\golden\tcrh_walk_ppp.pcap`.
Do not pipe pcap bytes through Windows PowerShell 5.1: it turns them into text.

### Linux / WSL (tshark 4.6.4)

```bash
mkdir -p ~/.local/lib/wireshark/plugins ~/.config/wireshark/profiles/ChronoRoute
cp tools/wireshark/tcrh.lua ~/.local/lib/wireshark/plugins/
cp tools/wireshark/profiles/ChronoRoute/* ~/.config/wireshark/profiles/ChronoRoute/
tshark -G plugins | grep tcrh          # tcrh.lua  Lua script  ~/.local/lib/wireshark/plugins/tcrh.lua
tshark -C ChronoRoute -r <pcap>        # ChronoRoute columns in tshark's one-line output
```

If you install the plugin and also pass `-X lua_script:.../tcrh.lua`, the second copy does not load.
It prints `tcrh.lua: a T-CRH dissector is already registered; not loading a second copy` on stderr, and the frame is decoded once.

### What was checked, and how

- **Linux plugin folder.** A test copies `tcrh.lua` into `~/.local/lib/wireshark/plugins`, using a temporary HOME. It then confirms that `tshark -G plugins` lists the file and that frames decode without `-X`.
- **Profile.** It was loaded with `tshark -C ChronoRoute`, with `WIRESHARK_CONFIG_DIR` pointing to a temporary folder.
- **Windows.** Windows `tshark.exe` 4.6.9 was run with `-X lua_script:` and the same temporary profile folder. It gave the same fields and colours as Linux 4.6.4.
- **Not exercised by any test:** copying into your real `%APPDATA%` and clicking through the GUI. The tests never write to your Wireshark configuration.

## Fields (`tcrh.*`)

`tshark -T fields -e <name>`, display filters and custom columns all accept these names.
The table lists every T-CRH field; values in [brackets] are computed by the dissector, not read from the header.

| Field | Type | Meaning |
|---|---|---|
| `tcrh.valid` | uint8 | [1 = header passes spec §6 step 1, 0 = malformed]. |
| `tcrh.reason` | string | [why it is malformed: `truncated`, `numhops_zero`, `sl_gt_numhops`, `length_mismatch` (`wrong_type` only if handed a whole non-253 header)]. These are the golden vectors' `expect_reason` names. |
| `tcrh.input_offset` | uint8 | [4 = Wireshark gave the dissector the bytes from Flags on (4.6 does); 0 = it gave the whole header]. |
| `tcrh.flags` | uint8 hex | Flags byte. |
| `tcrh.flags.dev` / `.greedy` / `.sat` | bool | DEV 0x01, GREEDY 0x02, SAT 0x04. |
| `tcrh.flags.unit` | uint8 | UNIT code 0-3 (0x30): 1, 0.1, 0.25, 0.125 ms. |
| `tcrh.flags.reserved` | uint8 hex | Reserved flag bits (0xC8). |
| `tcrh.num_hops`, `tcrh.dev_hop`, `tcrh.reserved` | uint8 | Bytes 5, 6, 7. |
| `tcrh.epoch_base` | uint32 | Epoch_Base in units (GPS time mod 2^32). |
| `tcrh.unit_ns`, `tcrh.unit_ms`, `tcrh.epoch_base_ms` | | [The unit, and Epoch_Base in ms]. |
| `tcrh.entry` | subtree | One per entry, in **wire order**: index 0 is SID[0], the final endpoint. |
| `tcrh.entry.index`, `tcrh.entry.hop` | uint8 | [i, and hop k = Num Hops - i]. |
| `tcrh.sid`, `tcrh.delta` | uint16, uint8 | SID[i], Delta[i] (units). |
| `tcrh.delta_ms` | double | [Delta in ms]. |
| `tcrh.deadline`, `tcrh.deadline_ms` | uint32, double | [Cumulative deadline D_k = Epoch_Base + Σ Delta[i..h-1] mod 2^32, in units and ms]. |
| `tcrh.padding` | bytes | Padding after the last entry. |
| `tcrh.final_sid` | uint16 | [SID[0]]. |
| `tcrh.current_hop` | uint8 | [k = Num Hops - SL; 0 means the ingress has not sent it yet]. |
| `tcrh.current_sid` | uint16 | [SID[SL]: the node this frame is heading to]. Absent while SL = Num Hops. |
| `tcrh.current_deadline`, `tcrh.current_deadline_ms` | uint32, double | [D_k of that node]. |
| `tcrh.capture_clock` | uint32 | [The node unit clock at capture time, floor(t_gps / u) mod 2^32]. |
| `tcrh.margin`, `tcrh.margin_ms` | int32, double | [D_k - capture clock, in whole units / ms; negative = late]. |
| `tcrh.late` | uint8 | [1 if `serial_diff(clock, D_k) > 0`: exactly the spec §6 step 2 test]. |
| `tcrh.quoted` | uint8 | [1 if this T-CRH is a copy inside an ICMPv6 error message]. A quoted header gets no capture clock, margin or late verdict, no DEV/GREEDY/SAT/late expert notes, and does not touch the Info column. It is recognised by `pinfo.in_error_pkt` or by an ICMPv6 error type (0-127) decoded earlier in the frame; either one alone is enough (tested). |

Segments Left, Hdr Ext Len and Next Header stay in Wireshark's own fields: `ipv6.routing.segleft`, `ipv6.routing.len` and `ipv6.routing.nxt`.

### Expert infos (filterable by name)

| Name | Severity | When |
|---|---|---|
| `tcrh.malformed.truncated` / `.numhops_zero` / `.sl_gt_numhops` / `.length_mismatch` / `.wrong_type` | Error | The header fails spec §6 step 1. The checks run in the spec's order. |
| `tcrh.dev` | Note | DEV is set. The text names the Dev Hop; Dev Hop 0 means the ingress found its first link down. |
| `tcrh.greedy` | Note | GREEDY is set. |
| `tcrh.sat` | Note | SAT is set: a Delta was clamped to 255. |
| `tcrh.late_at_capture` | Warning | The capture time is past the current deadline. |
| `tcrh.reserved_nonzero`, `tcrh.padding_nonzero` | Note | Accepted and passed on unchanged (spec §6 step 1). |
| `tcrh.dev_hop_inconsistent` | Warning | Dev Hop is nonzero while DEV is clear, or Dev Hop > Num Hops. |
| `tcrh.timebase_mismatch` | Note | The margin is over 120 s: the capture clock is not the ChronoRoute clock, so no late verdict is given. |
| `tcrh.segleft_unknown` | Warning | Segments Left could not be found. This should not happen. |
| `tcrh.quoted_in_icmpv6` | Note | The header is a copy quoted inside an ICMPv6 error message (see `tcrh.quoted`). |

`tshark -r x.pcap -X lua_script:tools/wireshark/tcrh.lua -q -z expert` counts them.

## Margin and the capture clock

T-CRH times are GPS time in deadline units (spec §4). pcap timestamps count from the Unix epoch.

The margin is `D_k - floor(t_gps / u)` in whole units. A margin of 0 means the frame arrived inside the deadline unit, which is on time.
`chronoroute.trace.pcap` stamps every hop frame with its **arrival time at the node in its Destination Address**. The margin is therefore exactly what that node's deadline check sees. The tests compare it frame by frame with `chronoroute.proto.process_at_node`.

The preference `tcrh.timebase` (Edit ▸ Preferences ▸ Protocols ▸ TCRH, or `-o tcrh.timebase:<value>`) sets how timestamps are read:

| Value | How the GPS time is computed | Use it for |
|---|---|---|
| `utc` (default) | GPS ns = timestamp ns + (18 − 315964800) s | Python pcaps (`gps_to_pcap_ns`) and real captures |
| `offset` | GPS ns = timestamp ns + `tcrh.offset_ns` | Simulation-time captures. Set `tcrh.offset_ns` to the run's `t0_gps_ns`. |
| `off` | No margin is computed | |

Example: `-o tcrh.timebase:offset -o tcrh.offset_ns:1475675893123456000`. With `check_pcap.sh`, use `--timebase offset:1475675893123456000`.

## Facts measured on Wireshark 4.6.4 (WSL) and 4.6.9 (Windows)

- **The dissector table is `ipv6.routing.type`** (FT_UINT8). `tshark -G decodes` lists `ipv6.routing.type 253 tcrh`.
- **The sub-dissector's buffer starts at Flags**, after the 4 common bytes. Its length is `(HdrExtLen+1)*8 - 4`. This matches `call_dissector_with_data(..., tvb_new_subset_length(tvb, offset, type_len))` in `packet-ipv6.c`.
  `ipv6.routing.segleft` sits at `tvb:offset() - 1`. `tcrh.lua` matches it by offset, so encapsulated packets carrying two routing headers work.
  If a future version passes the whole header, the dissector notices and reads bytes 0-3 itself (`tcrh.input_offset` = 0).
- **A truncated header still reaches the dissector**, with a shorter buffer. It gets `valid = 0, reason = truncated`, and Wireshark adds its own "Malformed Packet".
- **`pinfo.abs_ts` is a double and loses nanoseconds**: it read `.123456717` for `.123456789`. The margin uses `frame.time_epoch` (NSTime, integer seconds and nanoseconds) instead.
- **`Dissector.get()` returns nil for an unknown name** in 4.6. Older versions raise an error, which is why the double-load guard uses `pcall`.
- **Each Lua script gets its own global environment.** Wireshark's `loadfile()` ignores an environment argument, so `tests/strict_load.lua` uses `load()` instead.
- **UDP/TCP checksums.** Our checksums use the **final** destination (RFC 8200 §8.1), which is the address of SID[0].
  Wireshark cannot map a SID to an address, so with `udp.check_checksum:TRUE` (off by default) it reports frames with SL > 0 as *Bad*. Frames with SL = 0 are *Good*; that is tested.
- **CRH-16/32 (types 5/6) are decoded natively** (`ipv6.routing.crh16.*`). Wireshark 4.6's CRH loop stops at the first SID 0, and it reads one SID past a list that fills the header exactly.
  Such frames (no zero padding slot) show all their SIDs and then "Malformed Packet". A fresh CRH header (SL = number of SIDs) with no padding slot fails the same way.
  The golden CRH pcap therefore holds the on-the-wire hops (SL = n−1 … 0). The test pins this quirk, so a Wireshark fix will be noticed.
- **The `colorfilters` brackets are `[background][foreground]`.** Wireshark's own `@UDP@udp@[56026,61166,65535][4718,10030,11796]` is dark text on light blue.
  `tshark --color` writes colours only to a 24-bit terminal or into `-T psml`/`pdml`. The tests read the PSML.

## Golden pcaps

`python -B -m chronoroute.trace.pcap golden OUT_DIR` writes:

| File | Frames |
|---|---|
| `tcrh_encode_raw.pcap`, `tcrh_encode_ppp.pcap` | One per `encode` vector. Frame n+1 is vector n. The header is `expect_hex` byte for byte, with SL = Num Hops, sent from the host to the ingress (`fd00::f000`). |
| `tcrh_vectors_raw.pcap` | Every `process` / `link_down` input and expected output. This includes the **malformed-on-purpose** inputs. |
| `crh_encode_raw.pcap` | CRH-16/32 vectors walked hop by hop (native Wireshark decode). |
| `tcrh_walk_raw.pcap`, `tcrh_walk_ppp.pcap` | The demo walk (see Quick start). |
| `frames.json` | Frame number → vector or step name, for each file. |
| `manifest.json` | Provenance. Labels from the shared table `sim/chronoroute/labels.py`: `tcrh_header_bytes` REAL (the real output of the real encoder, master plan §2 row 17); `pcap_addresses`, `pcap_timestamps`, `walk_link_delays` MODELLED. |

The address plan is a project convention, labelled MODELLED: SID s → `fd00::s`, hosts in `fd00:0:0:ffff::/64`. The upper layer follows the routing header's Next Header: UDP for 17, TCP for 6, inner IPv6 + UDP for 41, nothing for 59.
The payload is `CRT1` + packet id (u32) + send time in GPS ns (u64).

## Not done here / limitations

- Old ns-3 scratch runs carry the header as a UDP:7777 payload over IPv4. The plan's interim decoder for that was **not** added: it is not part of this task and would claim a UDP port.
- The plan's check "`hops.csv` equals the trace events" needs the P3 trace format (`chronoroute.trace/1`), which does not exist yet.
- The margin has whole-unit resolution (0.1 ms by default), the same resolution as the deadline check it mirrors.
- `tcrh.current_sid` assumes the frame is addressed to SID[SL], as a T-CRH node forwards it. A capture taken before a node's own processing (SL not yet decremented) is shown from the point of view of SID[SL].

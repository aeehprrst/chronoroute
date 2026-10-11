# ns-3 module `chronoroute`

The ns-3.44 implementation of **T-CRH v1**, the Temporal Compact Routing Header (IPv6
Routing Type 253), and of the **CRH-16/32** baseline from RFC 9631 (Routing Types 5 and 6).
`spec/tcrh-v1.md` is normative. Every header class is tested byte for byte against the same
golden vectors as the Python reference, `chronoroute.proto`.

Since phase P5a, T-CRH is a **genuine IPv6 Routing Header processed by ns-3's own IPv6 stack**:
the sending host inserts it between the IPv6 header and UDP/TCP (IPv6 Next Header 43), every
segment endpoint rewrites the IPv6 Destination Address and decrements Segments Left, and
Wireshark/tshark see Routing Header Type 253 in the pcaps. It is not data inside UDP.

Licence: **GPL-2.0-only**, the same as ns-3. This differs from the rest of the
repository, so never copy GPLv3 code into this folder.

## Files

| File | What it is |
|---|---|
| `model/tcrh-timebase.h` | Unit codes, `UnitNs`, `SerialDiff`, `IsLate`, `ClockU`, `EpochBaseAtIngress`, and the simulator clock (`SimToGpsNs`, `NodeClockU`). All integer arithmetic. |
| `model/tcrh-header.{h,cc}` | `TcrhHeader` (alias `TcrhRoutingHeader`), **derived from `ns3::Ipv6ExtensionRoutingHeader`**. Spec v1: Dev Hop byte, flags, unit code, exact `EncodeDeltas` (spec 5.1) and `Build`. Next Header, Hdr Ext Len, Routing Type and Segments Left live in the ns-3 base class, so ns-3 code holding a base pointer reads the same values. `Deserialize` validates and never reads past the end of the buffer; it keeps the Reserved byte, the padding and an over-long Hdr Ext Len exactly as received. |
| `model/crh-header.{h,cc}` | `CrhHeader` for CRH-16 (type 5) and CRH-32 (type 6), also derived from `Ipv6ExtensionRoutingHeader`, plus `CrhProcessAtNode` (RFC 9631 section 5). |
| `model/tcrh-process.{h,cc}` | `tcrh::ProcessAtNode` (raw bytes) and `tcrh::ProcessHeader`: spec section 6 as pure functions, the same as Python `process_at_node`. Also `IngressSend` and `LinkDownFallback` (spec 6 step 7). The IPv6 extension below calls these; they are what the golden vectors test. |
| `model/tcrh-address-plan.{h,cc}` | Address plan v1 (below): `SidAddress`, `SidFromAddress`, `LinkPrefix`, `LinkAddress`. |
| `model/crh-fib.{h,cc}` | `CrhFib`, a node's CRH-FIB (RFC 9631): SID -> (new Destination Address, interface, on-link next hop), plus the node's own SID. |
| `model/ipv6-extension-tcrh.{h,cc}` | `Ipv6ExtensionTcrh` (Routing Type 253) and `Ipv6ExtensionCrh16` / `Ipv6ExtensionCrh32` (types 5, 6), all `ns3::Ipv6ExtensionRouting`. Their `Process()` runs at a segment endpoint inside ns-3's `Ipv6L3Protocol::LocalDeliver`. Also `TcrhHopEvent` (trace record + CSV), `TcrhCounters`, `tcrh::SendSegment` and `tcrh::RoutingTableFallback`. |
| `model/tcrh-source-shim.{h,cc}` | `TcrhSourceShim`: source insertion (spec section 8) for UDP and TCP, by replacing their IPv6 "down target". |
| `helper/tcrh-helper.{h,cc}` | `TcrhHelper`: configures nodes, registers the extensions, assigns addresses by hand, builds point-to-point links with CRH-FIB entries, static routes for ordinary IPv6, installs shims. |
| `examples/tcrh-wire-check.cc` | 5-node chain + 1 node without T-CRH, UDP probes, a link slowed mid-run, a pcap per device, a per-packet summary and self-checks. |
| `helper/leo-bundle-helper.{h,cc}` | `Bundle::Load` (reads and checks a `cr export bundle` scenario, `docs/bundle-format.md`) and `LeoNetwork` (one node per bundle node, one point-to-point link per laser link and per ever-visible ground pair, link delay and up/down every 100 ms). |
| `examples/chronoroute-leo.cc` | The course milestone: the real 463 km sub-shell from a bundle, UDP probes on the time-varying schedule, an optional "up but slow" laser link, packets.csv, pcap, NetAnim slice, `run_info.json` and self-checks. Driven by `ns3/run_leo.py`; results and write-up in `results/course-milestone/` and `docs/course-milestone.md`. |
| `test/chronoroute-test-suite.cc` | The `chronoroute` test suite: golden vectors (time base, encode, process, link-down, CRH) and the path walk. |
| `test/tcrh-ipv6-test.{h,cc}` | Phase P5a test cases, added to the same suite: real ns-3 networks (list below). |
| `test/golden-vectors.h` | The five vector structs, shared by both test files; includes the generated `.inc`. |
| `test/golden-vectors.inc` | **Generated** from `spec/golden/*.json` by `tools/golden_to_inc.py`, because ns-3 has no JSON library. Never edit it by hand. |
| `test/scratch_regressions.py` | Regression checks for bugs #18-#21 (and the operating-point rule) in the Assessment 6-8 programs, `ns3/scratch/` in this repository. |

## How a T-CRH packet travels through ns-3.44

```
S (0xF000)          T1 (1)              T2 (2)              T3 (3)              D (0xF001)
UDP -> shim         Ipv6ExtensionTcrh   Ipv6ExtensionTcrh   Ipv6ExtensionTcrh   Ipv6ExtensionTcrh
build T-CRH,        step 2-6:           step 2-6            step 2-6            step 2-3: deadline,
SL 4 -> 3,          deadline, SL 3->2,                                          SL 0: deliver to UDP
DA = fd00::1        DA = fd00::2        DA = fd00::3        DA = fd00::f001
Hop Limit 64        63                  62                  61
```

1. **Source insertion** (`TcrhSourceShim`). UDP and TCP hand every IPv6 packet to a replaceable
   callback (`IpL4Protocol::SetDownTarget6`, normally `Ipv6::Send`). The shim sits in between.
   For a (destination address, destination port) with a route it builds the header with
   `TcrhHeader::Build` — **Epoch_Base = ceil((T0GpsNs + now) / u) mod 2^32, stamped per packet
   at send time** — and Next Header 17 or 6, runs the golden-tested ingress step
   (`tcrh::IngressSend`: no deadline check, SL = h - 1), looks the first SID up in the CRH-FIB,
   and sends the packet to that SID's address with IPv6 Next Header 43. Other packets pass
   through untouched. The transport checksum was computed with the final destination, as
   RFC 8200 section 8.1 requires, so `AddRoute` insists that the last SID's address is the
   transport destination. `AddCrh16Route` inserts a CRH-16 instead (the "same path, no
   deadline" baseline).
2. **Only the node named in the Destination Address looks at the header** (RFC 8200 4.4).
   ns-3's `Ipv6L3Protocol::Receive` gives the packet to `LocalDeliver` when the Destination
   Address is one of the node's addresses; `LocalDeliver` walks the extension headers and
   ns-3's `Ipv6ExtensionRouting` dispatches Routing Type 253 to `Ipv6ExtensionTcrh::Process`.
3. **`Process()`** runs spec section 6 through `tcrh::ProcessAtNode` with this node's unit
   clock, `floor((T0GpsNs + Simulator::Now()) / u) mod 2^32` (u from the packet's UNIT bits).
   For `forward` it looks the SID up in the CRH-FIB, rewrites the Destination Address, and
   sends the packet with the **public** `Ipv6L3Protocol::Send` and a ready-made `Ipv6Route`,
   Hop Limit - 1 (as `SocketIpv6HopLimitTag`) and the same Traffic Class. It then returns
   `stopProcessing = true, isDropped = false`, so a transit node never delivers the payload to
   UDP/TCP.
4. At the final endpoint (SL 0) it returns the header length and ns-3 continues with the Next
   Header (UDP/TCP), exactly like any other extension header.

### Processing details

| Situation (spec section 6) | What the node does |
|---|---|
| Step 1 fails (malformed) | Discard; ICMPv6 Parameter Problem, Code 0, when the spec gives a pointer. **Pointer = 40 + routing-header offset + field offset** (counted from the start of the invoking packet, RFC 4443 3.4): 41 Hdr Ext Len, 43 Segments Left, 45 Num Hops. Truncated headers: no ICMPv6. ns-3 drop reason `DROP_MALFORMED_HEADER`. |
| Late (step 2) | DEV, Dev Hop = k. Then the node's policy (attribute `Policy`): `greedy` hands the packet (DEV, GREEDY, SL 0, Destination Address = SID[0]'s address, Hop Limit - 1) to the fallback callback (`SetFallback`); **with no fallback installed, greedy behaves like `continue`** and counts it (`TcrhCounters::greedyNoFallback`, event reason `greedy_no_fallback`); the node then prints one `WARNING` line on stderr (once per node), and `EffectivePolicyName()` returns `continue (greedy set, no fallback installed)` so a run record cannot call such a run "greedy" (`chronoroute-leo` writes it to `run_info.json` as `effective_policy`, `tcrh-wire-check` prints it); `continue` keeps the SID list; `drop` discards (`drop_late`, ns-3 reason `DROP_ROUTE_ERROR`). |
| Next SID not in the CRH-FIB (step 6) | Discard; ICMPv6 Parameter Problem, Code 0, Pointer at the current SID (RFC 9631 section 5): 40 + 12 + 3 x SL. |
| Next link down (step 7) | DEV (if clear) with Dev Hop k (0 at the ingress), GREEDY, SL 0, to the fallback; discard if there is none (`drop_link_down`). The trace event of a discarded packet still reports that marked header (flags DEV\|GREEDY, Dev Hop k, SL 0), at the ingress shim exactly as at a transit node. "Down" = IPv6 interface down or device link down. |
| Hop Limit <= 1 when forwarding | Discard; ICMPv6 Time Exceeded (Code 0). |
| Packet already has DEV | No second deadline check (one Dev Hop per packet); the policy still applies. |

`tcrh::RoutingTableFallback` is a ready-made fallback: it sends the packet to its new
Destination Address (SID[0]) with the node's ordinary IPv6 routing table. It stands in for
greedy geographic forwarding until the ChronoRoute routing protocol exists (plan P5c), so
results that use it must label it **MODELLED**.

Trace source `Hop` on each extension (and `Ingress` on the shim) fires once per packet with a
`TcrhHopEvent`: time, node, node SID, packet uid, routing type, action, reason, Next Header,
Hop Limit, source/destination in/out, Num Hops, SL in/out, flags in/out, Dev Hop, Epoch_Base,
hop index k, deadline D_k, the node's clock, late, next SID. `TcrhHopEventCsv()` turns one into
a CSV line (header: `TcrhHopEventCsvHeader()`), for the future `chronoroute.trace/1` writer.

## Address plan v1 (ns-3)

Spec section 7 leaves the exact mapping to each simulator; this is the ns-3 one
(`model/tcrh-address-plan.h`). Record it in every run manifest.

| What | Address | Where |
|---|---|---|
| SID address of SID s | `fd00::s` = `fd00:0:0:0:0:0:HHHH:LLLL` (/128) — e.g. SID 2 -> `fd00::2`, ground station 1 (0xF001) -> `fd00::f001` | loopback (interface 0) |
| End e (1 or 2) of point-to-point link L | `fd01:0:HHHH:LLLL::e/64` — e.g. link 3 -> `fd01:0:0:3::1`, `::2` | the link's interfaces |

T-CRH packets always carry SID addresses as Destination Address. The link addresses exist
because ns-3 needs a global address on an interface to source packets the node itself sends
there (ICMPv6 errors), and they are the on-link next hops of the CRH-FIB and static routes.
`fd00::/8`, not `2001:db8::/32`: ns-3.44 silently drops the documentation prefix when forwarding.

`TcrhHelper` configures every node (`ConfigureIpv6`): `Ipv6::IpForward = true`,
`Ipv6::StrongEndSystemModel = false` (so the SID address on the loopback is accepted on every
interface), `Icmpv6L4Protocol::DAD = false` (addresses usable at once, no Neighbor
Solicitations in the pcaps). Addresses are added with `Ipv6::AddAddress`, never with
`Ipv6AddressHelper` (its allocator is O(n^2) in the number of addresses, and it installs a
default FqCoDel queue disc). **Consequence: no queue disc is installed** on these devices
(checked by a test); each point-to-point device keeps its own DropTail queue (100 packets by
default). Install a queue disc explicitly when an experiment needs one, and report it.

## ns-3.44 quirks and what this module does about them

| Quirk (ns-3.44 source) | Handling |
|---|---|
| ns-3's Type 0 code leaves `stopProcessing` false after forwarding, so every segment endpoint also delivers the payload to L4 (`ipv6-extension.cc:1194-1197`) | We set `stopProcessing = true`, `isDropped = false`. Tested: transit `LocalDeliver` to UDP/TCP = 0 (a mutation that restores the ns-3 behaviour makes the test fail). |
| `SendRealOut` is private (`ipv6-l3-protocol.h:505, :612`) | Forward with the public `Ipv6L3Protocol::Send` + `Ipv6Route` + `SocketIpv6HopLimitTag`/`SocketIpv6TclassTag`. Side effects: the `SendOutgoing` trace fires at every hop, and the IPv6 header is rebuilt, so a Flow Label set by the source would be lost. (ns-3 never sets one: its `Ipv6Header` defaults to Flow Label 1, which is what the pcaps show at every hop.) No core patch. |
| The Routing Type is read from the start of the packet, not from the header's offset (`ipv6-extension.cc:887-893`) | The shim always puts the routing header first. `Process()` drops a routing header that is not first (`drop_unsupported`, reason `routing_header_not_first`) instead of misreading it. |
| `Process()` returns the header length as `uint8_t` | The final endpoint can step over at most 248 bytes: T-CRH paths have at most **78 hops** (CRH-16: 122 SIDs) in ns-3. The shim refuses longer paths; `Process()` drops such a header (`drop_unsupported`). Real LEO paths are far shorter. |
| Unknown Routing Type with SL 0: ns-3 returns the raw Hdr Ext Len instead of a byte count (`ipv6-extension.cc:926`) | The helper registers types 253, 5 and 6 on **every** T-CRH node. A test pins what happens at a node *without* them: UDP receives 230 misaligned bytes instead of 208, the checksum fails, nothing is delivered. |
| Unknown Routing Type with SL != 0: ICMPv6 Parameter Problem Code 0, but with **Pointer = offset + 1 = 1** (`ipv6-extension.cc:916-924`) | RFC 8200 asks for the Routing Type counted from the start of the invoking packet (42). This is ns-3's own code (the node has no T-CRH); a test pins the value 1. |
| Fragmenting a packet with a non-Type-0 routing header asserts (`ipv6-extension.cc:600-602`) | Our headers derive from `Ipv6ExtensionRoutingHeader`, as the demux needs, but the fragment code still casts to the Type 0 class. The shim aborts with an explanation if a packet would exceed the MTU; routers never fragment (ICMPv6 Packet Too Big). Keep UDP payloads and `TcpSocket::SegmentSize` below MTU - 40 - header - transport header. |
| Strong end-system model on by default; `IpForward` off by default; `2001:db8::/32` dropped | Handled by `ConfigureIpv6` and the address plan. |

## Tests (`chronoroute` suite)

Golden vectors (Phase 1, unchanged and still byte-exact) plus, in `test/tcrh-ipv6-test.cc`, real
networks of the topology `S - T1 - T2 - T3 - D` with `X` (no T-CRH) hanging off T1, 10 Mb/s and
2 ms links, 200-byte UDP probes, 2.5 ms per-hop budgets at u = 0.1 ms:

| Test case | Checks |
|---|---|
| headers are `Ipv6ExtensionRoutingHeader`s | demux has 253/5/6 (and ns-3's Type 0); every golden vector decodes through the header object `GetExtensionRoutingHeaderPtr()` returns, ns-3's non-virtual base accessors agree; address plan worked by hand |
| on-time path | D receives all 20 in order; transit sockets and `LocalDeliver`(UDP) at T1-T3 = 0; at each hop DA = that node's SID address, Routing Type 253, SL 3/2/1/0, **Hop Limit 64/63/62/61**; Epoch_Base = ceil(t/u) at send time; every node's clock and D_k to the unit (22<=25, 44<=50, 66<=75, 88<=100); no queue disc |
| slowed link, 4 variants (continue, greedy without fallback, greedy + routing-table fallback, drop) | exactly the 10 probes inside the slow window are late, only at T3, clock 86 > 75, **Dev Hop 3**; flags 0x11 (continue) or 0x13 (greedy, SL 0, DA = D); greedy without fallback counted, and its `EffectivePolicyName()` is `continue (greedy set, no fallback installed)`; drop loses exactly those 10; D delivers the rest with Dev Hop 3 and no second DEV |
| deadline wrap | t0 10 ms before the unit clock wraps 2^32: Epoch_Base and D_3 wrap; on time stays on time (9 units early), slowed is late (11 units) with Dev Hop 3 |
| node without T-CRH | SL != 0: X drops (`DROP_MALFORMED_HEADER`), S receives ICMPv6 Parameter Problem Code 0 Pointer 1 quoting DA = X, SL 3; X as final endpoint with SL 0: the misalignment quirk above |
| malformed packets at a real node | every malformed golden vector with type 253 injected at T1: discarded with the vector's reason, ICMPv6 code and Pointer = 40 + the vector's pointer (or no ICMPv6); SID missing from the CRH-FIB: Code 0, Pointer 55; Hop Limit 1: Time Exceeded |
| next link down | transit: fallback gets DEV, GREEDY, Dev Hop 2, SL 0, DA = SID[0], Hop Limit 62; without fallback: counted drop whose trace shows flags 0x13, Dev Hop 2, SL 0; ingress: Dev Hop 0, with and without a fallback (the drop's trace shows flags 0x13, Dev Hop 0, SL 0, target SID[0]) |
| TCP and CRH-16 | 20 000-byte TCP transfer over T-CRH (Next Header 6), ACKs as plain IPv6, no TCP at transit nodes; CRH-16 probes: SL 3/2/1/0, Routing Type 5 on the wire, L4 only at D |

## Build, test, run (inside WSL)

```
tools/ns3-sync.sh                      # regenerate the .inc, link the module and the scratch
                                       # programs, configure if needed
cd ~/ns-3-dev && ./ns3 build -j8       # never more than 8 jobs: WSL has 7.6 GiB of RAM
./test.py --no-build -s chronoroute    # or: ./build/utils/ns3.44-test-runner-default --test-name=chronoroute --verbose
```

`make ns3-test` from the repository root runs all three steps.

Tests and examples must be enabled in the ns-3 tree. On a tree that was never configured,
`tools/ns3-sync.sh` runs `./ns3 configure --enable-tests --enable-examples` (the build profile
stays "default"). **A tree configured before `examples/` existed** does not know the example
yet: run `./ns3 configure --enable-tests --enable-examples` once.

### The example

```
mkdir -p /tmp/wire
./ns3 run "tcrh-wire-check --outDir=/tmp/wire"            # policy greedy + routing-table fallback
./ns3 run "tcrh-wire-check --policy=continue --pcap=0"    # also: --policy=drop, --fallback=none
tshark -r /tmp/wire/tcrh-wire-check-2-2.pcap -V -Y ipv6.routing    # T2 -> T3
```

It prints the address plan, T1's CRH-FIB, one line per probe (send/receive time, flags and Dev
Hop at D, and every hop's clock against its deadline in 0.1 ms units after Epoch_Base), the
ICMPv6 messages S received, per-node counters, and self-checks; it exits with status 1 if any
check fails. It also writes `tcrh-wire-check-hops.csv` (every `TcrhHopEvent`) and one pcap per
device, `tcrh-wire-check-<node>-<device>.pcap` (DLT_PPP; node ids S 0, T1 1, T2 2, T3 3, D 4,
X 5; device 0 is the loopback, so links start at device 1). pcap time stamps are simulation
time (they start at 1970-01-01); the GPS time of simulation time 0 is `--t0GpsNs`.

Wireshark 4.6 decodes Type 253 as "Experiment 1" (Next Header, Hdr Ext Len, Segments Left, and
the rest as Type-Specific Data: Flags, Num Hops, Dev Hop, Reserved, Epoch_Base, entries); the
Lua dissector (phase P6) decodes the rest. It decodes CRH-16 (flow C of the example) natively.

Labels: link rates, delays and the slow-down are **MODELLED**; the header bytes are the spec v1
wire format (golden-tested); t0 defaults to the GPS time of the pinned CelesTrak snapshot,
2026-10-10T13:58:00Z = 1475675898000000000 GPS ns.

### How the module gets into ns-3

`~/ns-3-dev/contrib/chronoroute` is a symlink to this folder, and ns-3.44's CMake follows it.
This was checked on 2026-10-10:

- The contrib scan uses `IS_DIRECTORY`, which is true for a link to a directory.
- `./ns3 configure` lists `chronoroute`.
- The stub headers in `build/include/ns3/` `#include` the real files by absolute path, so an
  edit here is picked up by the next build without a copy step.

`tools/ns3-sync.sh --copy` makes a plain copy instead, for trees that cannot see the repository.

The legacy programs that produced the v0.9 ns-3 numbers live in `ns3/scratch/` (and their plot
scripts in `ns3/plots/`); `tools/ns3-sync.sh` links them into `~/ns-3-dev/scratch/` and
`~/ns-3-dev/`. It only replaces a file that is already there if it has the same bytes as the
repository copy (or is what an earlier `--copy` sync wrote), so an edit made in `~/ns-3-dev`
is never lost. `ns3/scratch/tcrh-experiment-a8.cc` is the original Assessment 8 program,
kept only to regenerate the old-code evidence file.

Scratch programs are linked against every module. So a scratch class must not reuse the TypeId
names of this module (`ns3::TcrhHeader`, `ns3::CrhHeader`, `ns3::CrhFib`,
`ns3::Ipv6ExtensionTcrh`, `ns3::Ipv6ExtensionCrh`, `ns3::Ipv6ExtensionCrh16`,
`ns3::Ipv6ExtensionCrh32`, `ns3::TcrhSourceShim`); if it does, ns-3 aborts at start-up with
"Trying to allocate twice the same uid". The Assessment 7/8 programs use
`ns3::CrhExperimentHeader` and `ns3::TcrhV0Header` (and the kept original, `ns3::TcrhA8Header`).

## Not done yet (later phases)

- Greedy **geographic** fallback and the ChronoRoute routing protocol (P5c); today the
  fallback is a callback, with `tcrh::RoutingTableFallback` as a MODELLED stand-in.
- Encapsulation at the gateway (spec section 8, Next Header 41) and its decapsulation.
- LEO substrate (moving satellites, distance-based delays, ground links: P5b), schedules from
  Python's bundle, the `chronoroute.trace/1` writer, FlowMonitor (its IPv6 classifier ignores
  packets whose Next Header is 43).
- Reverse-path T-CRH for TCP ACKs (today ACKs are plain IPv6 unless the receiver also has a
  shim with a route back).

# ns-3 module `chronoroute`

The ns-3.44 implementation of **T-CRH v1**, the Temporal Compact Routing Header (IPv6
Routing Type 253). It also contains the **CRH-16/32** baseline from RFC 9631.
`spec/tcrh-v1.md` is normative. Every class here is tested byte for byte against
the same golden vectors as the Python reference, `chronoroute.proto`.

Licence: **GPL-2.0-only**, the same as ns-3. This differs from the rest of the
repository, so never copy GPLv3 code into this folder.

| File | What it is |
|---|---|
| `model/tcrh-timebase.h` | Unit codes, `UnitNs`, `SerialDiff`, `IsLate`, `ClockU`, `EpochBaseAtIngress`, and the simulator clock (`SimToGpsNs`, `NodeClockU`). All integer arithmetic. |
| `model/tcrh-header.{h,cc}` | `TcrhHeader` (an `ns3::Header`). Implements spec v1: Dev Hop byte, flags, unit code, exact `EncodeDeltas` (spec 5.1) and `Build`. `Deserialize` validates the header and never reads past the end of the buffer. It keeps the Reserved byte, the padding and an over-long Hdr Ext Len exactly as received. |
| `model/tcrh-process.{h,cc}` | `tcrh::ProcessAtNode` (raw bytes) and `tcrh::ProcessHeader` (header object): spec section 6, the same as Python `process_at_node` (including `IGNORE` for an unrecognised routing type with SL 0). Also `IngressSend` and `LinkDownFallback` (spec 6 step 7, Python `link_down_fallback`). |
| `model/crh-header.{h,cc}` | `CrhHeader` for CRH-16 (type 5) and CRH-32 (type 6), plus `CrhProcessAtNode` (RFC 9631 section 5). |
| `test/chronoroute-test-suite.cc` | The `chronoroute` test suite. |
| `test/golden-vectors.inc` | **Generated** from `spec/golden/*.json` by `tools/golden_to_inc.py`, because ns-3 has no JSON library. Never edit it by hand. |
| `test/scratch_regressions.py` | Regression checks for bugs #18-#21 (and the operating-point rule) in the Assessment 6-8 programs, `ns3/scratch/` in this repository. |

## Build and test (inside WSL)

```
tools/ns3-sync.sh                      # regenerate the .inc, link the module and the scratch
                                       # programs, configure if needed
cd ~/ns-3-dev && ./ns3 build -j8       # never more than 8 jobs: WSL has 7.6 GiB of RAM
./test.py --no-build -s chronoroute    # or: ./ns3 run "test-runner --suite=chronoroute"
```

`make ns3-test` from the repository root runs all three steps.

Tests must be enabled in the ns-3 tree. On a tree that was never configured, `tools/ns3-sync.sh`
runs `./ns3 configure --enable-tests --enable-examples` (the build profile stays "default");
on a configured tree it keeps the cached settings and warns if tests are off (then run
`./ns3 configure --enable-tests`).

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
names `ns3::TcrhHeader` or `ns3::CrhHeader`; if it does, ns-3 aborts at start-up with "Trying
to allocate twice the same uid". The Assessment 7/8 programs now use `ns3::CrhExperimentHeader`
and `ns3::TcrhV0Header` (and the kept original, `ns3::TcrhA8Header`).

## Later phases

`TcrhHeader` is an `ns3::Header` for now. The comment in `tcrh-header.h` explains how to
derive it from `ns3::Ipv6ExtensionRoutingHeader` in P5, so that it becomes a real IPv6
extension that ns-3 can fragment and Wireshark can see.

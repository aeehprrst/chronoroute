# ChronoRoute

ChronoRoute is a student research project on routing in low-Earth-orbit (LEO) satellite
constellations. Routes are computed on the ground from orbit predictions and carried in each
packet as an IPv6 source route: a Routing Header of type 253 called **T-CRH** (Temporal
Compact Routing Header, an extension of the RFC 9631 Compact Routing Header) that also holds a
cumulative arrival deadline for every hop. A node that receives the packet after its deadline
learns that reality has drifted from the prediction (a link is down or just slow), sets a
deviation flag and switches the packet to greedy geographic forwarding. We measure how well
this detects such problems, and what it costs, in a Python simulator and an ns-3 module.

Author: Arshpreet Gaba (VIT Vellore, Computer Networks project).
ChronoRoute is not affiliated with SpaceX. "Starlink" names the public orbit data only.

## Status

**Phase 1, "Foundations", of the rebuild plan (started 2026-10-10, in progress).** Its
goals:

- fix the wire format in a normative spec, [`spec/tcrh-v1.md`](spec/tcrh-v1.md), with golden
  test vectors in `spec/golden/`;
- fix the known bugs in the semester code (git tag `v0-semester`, now in `sim/legacy/`), each
  with a regression test written first;
- start the new Python package `chronoroute` (in `sim/chronoroute/`) with the protocol code
  and the provenance (manifest) writer;
- set up the ns-3 module skeleton and CI.

The figures in `results/legacy-v0/` and `results/legacy-v0-starlink/` come from the semester
code, which had known bugs. They are kept unchanged so the old and corrected results can be
compared. Do not quote numbers from them. The corrected re-runs are in
[`results/legacy-v0.9/`](results/legacy-v0.9/), and
[`docs/results-changelog.md`](docs/results-changelog.md) lists every number that changed, and
why, with the claims to retire.

## Repository layout

| Path | What is in it |
|---|---|
| `spec/tcrh-v1.md` | T-CRH v1 wire format and processing rules (**normative**) |
| `spec/golden/` | Golden test vectors that every implementation must match |
| `spec/schemas/` | JSON Schemas, e.g. `manifest.schema.json` for run manifests (the package ships an identical copy in `sim/chronoroute/schemas/`) |
| `sim/chronoroute/` | The Python package `chronoroute` (protocol code, provenance, CLI `cr`) |
| `sim/legacy/` | Semester experiments 1-7, kept runnable and being bug-fixed |
| `sim/tests/` | pytest test suite |
| `ns3/contrib/` | The ns-3 module source (symlinked into `~/ns-3-dev/contrib` by `make ns3-sync`, or copied with `make ns3-sync ARGS=--copy`) |
| `ns3/scratch/`, `ns3/plots/` | The legacy ns-3 programs (Assessments 6-8, with the Phase 1 fixes) and their plot scripts; `make ns3-sync` links them into `~/ns-3-dev` |
| `ns3/run_tcrh_sweep.py` | Regenerates every file in `results/legacy-v0.9/ns3/tcrh_sweep/` (`make ns3-legacy`) |
| `ns3/legacy/` | The original Assessment 8 sweep CSV, frozen (its only other copy is an unpushed commit in the author's ns-3 tree) |
| `ns3/patches/` | The one local change to ns-3.44 itself (the `ns3` script, for Python 3.14) |
| `tools/` | Helper scripts: `ns3-sync.sh`, `golden_to_inc.py` (golden vectors to C++) |
| `data/pinned/` | Frozen orbit snapshots used by experiments; never edit them |
| `data/starlink.txt` | Older Starlink TLE set (September 2026) used by the legacy code |
| `results/` | Experiment outputs, each folder with a `manifest.json` |
| `docs/` | Documentation index, see [`docs/README.md`](docs/README.md) |
| `Makefile` | Common tasks (`make help` lists them) |

## Quickstart (inside WSL Ubuntu)

You need Python 3.12 or newer (the project uses 3.14), `git` and `make`.

```bash
cd ~/chronoroute
python3 -m venv venv                  # once
venv/bin/pip install -e ".[test]"     # installs chronoroute + pinned numpy/networkx/sgp4/matplotlib
make test                             # runs pytest on sim/tests
```

`pip install -e` is an "editable" install: the package points at the source files, so edits
take effect without reinstalling. The Makefile uses `venv/bin/python` by default. Use
`make test PYTHON=python` to choose another interpreter.

| Command | What it does |
|---|---|
| `make test` | Run the Python tests |
| `make golden` | Regenerate `spec/golden/`, fail if the result differs from git or the ns-3 `.inc` is stale |
| `make check` | `test` + `golden` (what CI runs) |
| `make legacy-dev` | Re-run legacy experiments 1-5 on the 480-satellite dev shell |
| `make legacy-starlink` | Re-run legacy experiments 1-7 on the 1584-satellite Starlink Shell-1 design |
| `make ns3-sync` | Symlink the ns-3 module, scratch programs and plot scripts into `~/ns-3-dev` (`tools/ns3-sync.sh`; `ARGS=--copy` copies instead) |
| `make ns3-test` | Build ns-3 with at most 8 jobs and run the `chronoroute` test suite |
| `make ns3-legacy` | Re-run the legacy ns-3 T-CRH slack sweep into `results/legacy-v0.9/ns3/tcrh_sweep/` |

ns-3 lives in a separate tree, `~/ns-3-dev` (ns-3.44, branch `chronoroute`). Override it with
`make ns3-test NS3_DIR=/path/to/ns-3`. Builds use `-j8` at most because WSL has only 7.6 GiB
of RAM. The test suite name can be changed with `NS3_SUITES=...`. The ns-3 tests must be
enabled: on a tree that was never configured, `make ns3-sync` runs
`./ns3 configure --enable-tests --enable-examples` (build profile "default"); on an existing
tree, check that `./ns3 show config` lists tests as ON, or run `./ns3 configure --enable-tests`.

### A fresh ns-3 tree

Everything ChronoRoute needs from ns-3 is in this repository, so any clean ns-3.44 checkout
works:

```bash
git clone https://github.com/nsnam/ns-3-dev-git.git ~/ns-3-dev
cd ~/ns-3-dev
git checkout -b chronoroute ns-3.44       # tag ns-3.44 = commit 43dce6710b8d
git apply ~/chronoroute/ns3/patches/ns3-script-python3.14.patch   # the ./ns3 script, for Python 3.14
cd ~/chronoroute
make ns3-sync      # links the module and programs in, runs ./ns3 configure --enable-tests --enable-examples
make ns3-test      # builds ns-3 (-j8; the first build is long) and runs the chronoroute test suite
make ns3-legacy    # builds the two sweep programs, regenerates results/legacy-v0.9/ns3/tcrh_sweep/
```

Use another folder with `NS3_DIR=...` on every `make` line. The patch is the only change
to ns-3 itself. `make ns3-legacy` checks everything it can before it starts and writes into a
staging folder, so a failed run leaves `results/legacy-v0.9/ns3/tcrh_sweep/` as it was.

## Running the legacy experiments

```bash
make legacy-dev          # experiments 1-5, synthetic 480-satellite Walker shell
make legacy-starlink     # experiments 1-7, synthetic 72 x 22 Walker shell at 550 km
```

Both are synthetic Walker constellations. The "starlink" preset is the 2020 FCC Shell-1
design, not today's fleet. The corrected ("v0.9") re-runs write their figures, CSV files and a
`manifest.json` under `results/legacy-v0.9/`. The original semester figures stay in
`results/legacy-v0/` (dev) and `results/legacy-v0-starlink/` (Starlink preset).

## Provenance and the REAL / DERIVED / MODELLED rule

Every result folder has a `manifest.json` written by `chronoroute.provenance.write_manifest`
and checked against [`spec/schemas/manifest.schema.json`](spec/schemas/manifest.schema.json).
It records:

- the git commit, and whether the working tree was dirty;
- the command line, the full config and its sha256, and the seeds;
- the orbit snapshot used;
- the Python and library versions, and the host CPU and RAM;
- start and end times;
- the sha256 of every output file;
- a label for each input.

`chronoroute.provenance.validate_manifest` re-checks a manifest, including that no output file
has been edited since the run.

Every input or quantity is labelled with one of three words:

- **REAL**: public or measured data, real physics, or the real output of our code (e.g.
  satellite orbits from CelesTrak, propagation delay, the header bytes we produce).
- **DERIVED**: computed by our code from REAL inputs (e.g. shells and orbital planes inferred
  from the orbit data, routes).
- **MODELLED**: chosen by us because the truth is not public (e.g. the laser inter-satellite
  link topology, traffic, failures, queueing).

The rules:

- Nothing MODELLED is ever presented as the real Starlink network.
- Every number on a chart traces back to a manifest.
- A chart without a manifest does not get published.

## Protocol specification

The normative T-CRH v1 specification is [`spec/tcrh-v1.md`](spec/tcrh-v1.md). It covers the
wire format, deadline units, time base, ceil-cumulative deadline encoding, per-node processing
and SID allocation. If an implementation disagrees with a golden vector in `spec/golden/`, the
implementation is wrong. `make golden` checks that the vectors can be regenerated exactly.

## Credits

- **Orbit data courtesy of CelesTrak** ([celestrak.org](https://celestrak.org)). The snapshot
  in `data/pinned/20261010T1358Z-celestrak/` has CelesTrak GP data (from 18 SDS via
  CelesTrak), supplemental SupGP data (derived by CelesTrak from SpaceX ephemerides) and
  SATCAT records. `data/starlink.txt` is an earlier CelesTrak TLE download.
- SGP4 propagation: the [`sgp4`](https://pypi.org/project/sgp4/) Python package.
- Graphs and plots: NetworkX, NumPy, Matplotlib.
- Network simulator: [ns-3](https://www.nsnam.org/) (version 3.44).
- Standards built on: RFC 8200 (IPv6), RFC 9631 (Compact Routing Header).

## License

- **Code:** MIT licence ([`LICENSE`](LICENSE), also declared in `pyproject.toml`).
- **ns-3 code** (`ns3/`: the module in `ns3/contrib/` and the programs in `ns3/scratch/`):
  **GPL-2.0-only**, because it builds on ns-3, which is GPL-2.0-only.
- **Third-party data** keeps its source's terms. See Credits above.

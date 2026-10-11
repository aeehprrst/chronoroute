# E0 correctness gate

This deterministic gate implements the prospective criteria in
[PREREG.md §4](../PREREG.md). The configuration pins that document's commit
and file hash, the CelesTrak snapshot, the C5 shell, the start time and the
eligible city population. Changed coverage or dirty code is refused.

After testing and committing the implementation, run from the repository root:

```sh
OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 venv/bin/python -B experiments/E00/gate.py \
  --out results/E00/$(date -u +%Y%m%dT%H%M%SZ)
```

Prerequisites are the repository's Python environment and web dependencies,
the configured Node installation, tshark with Lua, a C++ compiler and the
built ChronoRoute libraries in `~/ns-3-dev/build`. The launcher compiles only
its own adapters into the result directory. It uses one process at a time;
no packet simulation, network download or source-tree rebuild is performed.

## Checks and interpretation

The following numbers are preregistered coverage and acceptance criteria,
not measurements. Actual counts and extrema are written to `summary.csv`.

* Orbit agreement: catalogue-order samples of 200 satellites per constellation,
  at 601 instants spanning 0–6000 seconds. The production satellite.js browser
  propagation and ECEF conversion run on both raw records and compact exported
  OMM rows. Python references use full epochs and millisecond-truncated epochs;
  the maximum permitted differences are 10 m and 1 m, respectively.
* Physics: all active ISLs and all visible GSL candidates at every sample,
  finite positions, the 80 km ISL grazing floor, nearest-nanosecond propagation
  rounding (at most 0.5 ns), selected GSL elevation and degree limits, and the
  cross-plane polar mask. A spherical lower-bound certificate proves most ISLs
  safe; uncertified segments are checked against WGS84. The reported grazing
  minimum is a certified lower bound, not the exact minimum over every segment.
* Paths: shortest paths for every eligible pair at every sample must exceed
  surface great-circle light time, allowing at most 0.5 ns per rounded link.
  Unreachable samples remain in `paths.csv.gz` and the manifest's separate
  count; they do not become latency observations. Each shell's orbital periods
  are checked against the sampled time span.
* Wire agreement: every T-CRH and CRH golden vector plus real scheduler-produced
  headers from both constellations. Python, the linked ns-3 library and the
  production browser engine must agree on bytes and forwarding results.
  Source and encapsulation headers, equality/late policies, wrap, SAT, padding
  and DEV/DevHop are covered. Captured bytes and Wireshark's native/Lua fields
  must match the corpus, including intentional malformed inputs and ignored
  reserved bytes. Wireshark decodes headers; it does not simulate forwarding.

Wireshark intentionally suppresses timing verdicts beyond its 120-second
plausibility window; those golden vectors must still agree on raw bytes,
deadlines and the absence of a verdict. Its documented native CRH decoder
cannot list SIDs when Segments Left indexes outside the header and reports
malformed packets on some unpadded lists. Raw bytes and fixed fields remain
checked, with SID lists checked wherever the native decoder defines them.
These limitations are also recorded in the manifest.

Geometry and paths use the production exporter pipeline at the registered
10-second check instants. This is a sampled full-orbit gate, not a continuous
proof or the later packet experiments' 100 ms topology timeline. Every visible
GSL candidate is checked, so propagation validation does not depend on which
sticky links a finer timeline would retain.

C5 elements and their SGP4 positions are **REAL** public inputs/physics/code;
C2 elements and positions are **MODELLED**. Grid-4 links, GSL policy and
processing delays are **MODELLED**; inferred shells, routes and budgets are
**DERIVED**. Header/capture bytes are **REAL** implementation output. Summary
rows and per-constellation manifest metadata preserve these distinctions.
Actual Starlink routing and laser topology are **UNKNOWN**; Starlink does not
use T-CRH.

## Evidence and failure handling

Each run retains the input corpus, selected satellite IDs, compiled adapters,
subprocess commands/logs, compressed browser positions, capture, detailed
orbit/path tables, summary CSV, generated figures and a hash-validated
`manifest.json`. No random seeds are needed for this deterministic gate.
An exception creates a failed manifested run with its traceback; any violation
or incomplete execution exits unsuccessfully. Existing result folders are
never overwritten. Fixes require tests and a new clean commit before rerunning.

Regression coverage is in `sim/tests/test_e00.py`; run `make check` before each
commit, including the later results commit.

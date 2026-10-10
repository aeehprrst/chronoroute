# ChronoRoute documentation

An index of the project documents. Start with the [repository README](../README.md) for
setup and the `make` targets.

## Specification (normative)

| Document | What it is |
|---|---|
| [`spec/tcrh-v1.md`](../spec/tcrh-v1.md) | T-CRH v1: wire format, flags, time base, deadline encoding, node processing, SID plan. The single source of truth for every implementation. |
| [`spec/golden/`](../spec/golden/README.md) | Golden test vectors. Any implementation that disagrees with them is wrong. `make golden` checks that they regenerate byte-for-byte and that the ns-3 copy (`golden-vectors.inc`) is up to date. |
| [`spec/schemas/manifest.schema.json`](../spec/schemas/manifest.schema.json) | Format of the `manifest.json` that sits next to every set of results (written by `chronoroute.provenance`). |

## Results

| Document | What it is |
|---|---|
| [`docs/results-changelog.md`](results-changelog.md) | Every legacy number that changed in the corrected "v0.9" re-run, with the reason (bug number), and the claims to retire. |
| `results/legacy-v0/`, `results/legacy-v0-starlink/` | Original semester figures, kept unchanged for comparison. Known to contain bugs; do not quote them. |
| [`results/legacy-v0.9/`](../results/legacy-v0.9/) | Corrected re-runs of the legacy experiments (`dev/`, `starlink/`) and the re-scored ns-3 sweep (`ns3/tcrh_sweep/`), each folder with a `manifest.json`. |

## Data

| Document | What it is |
|---|---|
| [`data/pinned/20261010T1358Z-celestrak/README.md`](../data/pinned/20261010T1358Z-celestrak/README.md) | The frozen CelesTrak Starlink snapshot of 2026-10-10: source URLs, download times, checksums. Orbit data courtesy of CelesTrak. |

## Planning documents

The planning documents are not in this repository. They are on the author's Windows machine,
in `Downloads\CHRONOROUTE\planning-2026-10-10\`:

| File | Contents |
|---|---|
| `00_ChronoRoute_Build_Plan.html` | The build plan, as a web page |
| `01_master_plan_draft.md` | Master plan: phases P0-P11, the 20-bug table (Phase 1), experiment matrix, verification system |
| `02_reviewer_critique.md` | Reviewer critique and the must-fix items |
| `03_research_codebase-machine.md` | Audit of the semester code and the machine, with benchmark evidence for every bug |
| `04_research_ns3-internals.md` ... `09_research_science-design.md` | Background research: ns-3 internals, prior art, live data, web stack, visualisation, science design |

The project handoff notes from the semester version are in
`Downloads\CHRONOROUTE\ChronoRoute_Project_Handoff.md` on the same machine.

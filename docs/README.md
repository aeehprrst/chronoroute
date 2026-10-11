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
| [`docs/NEXT_STEPS.md`](NEXT_STEPS.md) | **Start here to continue the project:** what exists, the rules for every change, and the remaining tasks in order with their checks. |
| [`docs/course-milestone.md`](course-milestone.md) | Course milestone: ns-3 LEO topology with a time-varying schedule on the real 463 km Starlink shell, real IPv6 Routing Type 253 packets, Python cross-check, how to reproduce. |
| [`docs/bundle-format.md`](bundle-format.md) | The scenario bundle (nodes, laser and ground links, delays every 100 ms, positions, schedules) that the Python tools export and ns-3 reads, plus the website data files. |
| [`docs/results-changelog.md`](results-changelog.md) | Every legacy number that changed in the corrected "v0.9" re-run, with the reason (bug number), and the claims to retire. |
| [`docs/report/README.md`](report/README.md) | IEEE-style report draft from the reviewed experiment results, including methods, limitations and verified references. |
| [`docs/claims.md`](claims.md) | Source ledger for report quantities and qualitative claims, with exact result paths and manifests. |
| `results/legacy-v0/`, `results/legacy-v0-starlink/` | Original semester figures, kept unchanged for comparison. Known to contain bugs; do not quote them. |
| [`results/legacy-v0.9/`](../results/legacy-v0.9/) | Corrected re-runs of the legacy experiments (`dev/`, `starlink/`) and the re-scored ns-3 sweep (`ns3/tcrh_sweep/`), each folder with a `manifest.json`. |

## Data

| Document | What it is |
|---|---|
| [`data/pinned/20261010T1358Z-celestrak/README.md`](../data/pinned/20261010T1358Z-celestrak/README.md) | The frozen CelesTrak Starlink snapshot of 2026-10-10: source URLs, download times, checksums. Orbit data courtesy of CelesTrak. |
| [`data/pinned/20261010T2035Z-celestrak/`](../data/pinned/20261010T2035Z-celestrak/) | Second snapshot (2026-10-10 20:35 UTC), fetched by `pipeline/fetch.py`. Every request is logged in `data/pinned/fetch_log.jsonl`. |
| [`data/static/cities.csv`](../data/static/cities.csv) | 60 cities from Natural Earth (public domain); source in `CITIES_SOURCE.md`. |
| [`pipeline/README.md`](../pipeline/README.md) | How orbit data is fetched (CelesTrak rules), validated and slimmed for the website. |

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

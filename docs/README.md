# ChronoRoute documentation

An index of the project documents. Start with the [repository README](../README.md) for
setup and the `make` targets.

## Specification (normative)

| Document | What it is |
|---|---|
| [`spec/tcrh-v1.md`](../spec/tcrh-v1.md) | T-CRH v1: wire format, flags, time base, deadline encoding, node processing, SID plan. The single source of truth for every implementation. |
| [`spec/golden/`](../spec/golden/README.md) | Golden test vectors. Any implementation that disagrees with them is wrong. `make golden` checks that they regenerate byte-for-byte and that the ns-3 copy (`golden-vectors.inc`) is up to date. |
| [`spec/trace-v1.md`](../spec/trace-v1.md) | The run trace format shared by the Python simulator, the ns-3 converter and the viewer. |
| [`spec/schemas/manifest.schema.json`](../spec/schemas/manifest.schema.json) | Format of the `manifest.json` that sits next to every set of results (written by `chronoroute.provenance`). |

## Experiments and results

| Document | What it is |
|---|---|
| [`experiments/PREREG.md`](../experiments/PREREG.md) | The pre-registration of experiments E0, E1, E2, E4, E5 and E16: questions, hypotheses, grids, statistics and decision rules, fixed before the experiments ran. |
| `experiments/E00/` ... `experiments/E16/` | One folder per experiment, with a README, the configuration and the code that runs and analyses it. |
| [`docs/NEXT_STEPS.md`](NEXT_STEPS.md) | The project rules (nothing fake, labels, tests, clean provenance, statistics, counterfactual scoring) and the facts the pre-registration refers to. |
| [`docs/report/README.md`](report/README.md) | IEEE-style report from the experiment results, including methods, limitations and verified references. |
| [`docs/claims.md`](claims.md) | Source ledger for report quantities and qualitative claims, with exact result paths and manifests. |
| [`docs/course-milestone.md`](course-milestone.md) | Course milestone: ns-3 LEO topology with a time-varying schedule on the real 463 km Starlink shell, real IPv6 Routing Type 253 packets, Python cross-check, how to reproduce. |
| [`docs/results-changelog.md`](results-changelog.md) | Every legacy number that changed in the corrected "v0.9" re-run, with the reason (bug number), and the claims to retire. |
| `results/legacy-v0/`, `results/legacy-v0-starlink/` | Original semester figures, kept unchanged for comparison. Known to contain bugs; do not quote them. |
| [`results/legacy-v0.9/`](../results/legacy-v0.9/) | Corrected re-runs of the legacy experiments (`dev/`, `starlink/`) and the re-scored ns-3 sweep (`ns3/tcrh_sweep/`), each folder with a `manifest.json`. |

## Tools

| Document | What it is |
|---|---|
| [`docs/sim-config.md`](sim-config.md) | The Python simulator (`cr run`) and its configuration file. |
| [`docs/baselines.md`](baselines.md) | The comparison schemes and the offline evaluation: metrics, detection scoring, re-scoring and statistics. |
| [`docs/viewer.md`](viewer.md) | The 3D and 2D viewer (`cr viz`) for simulator and ns-3 runs. |
| [`docs/bundle-format.md`](bundle-format.md) | The scenario bundle (nodes, laser and ground links, delays every 100 ms, positions, schedules) that the Python tools export and ns-3 reads, plus the website data files. |
| [`ns3/contrib/chronoroute/README.md`](../ns3/contrib/chronoroute/README.md) | The ns-3.44 module: T-CRH and CRH-16/32 headers, routing, helpers and tests. |
| [`tools/wireshark/README.md`](../tools/wireshark/README.md) | The Wireshark dissector for T-CRH and the automatic capture check. |
| [`web/README.md`](../web/README.md) | The public website: pages, data, tests and deployment. |

## Data

| Document | What it is |
|---|---|
| [`data/pinned/20261010T1358Z-celestrak/README.md`](../data/pinned/20261010T1358Z-celestrak/README.md) | The frozen CelesTrak Starlink snapshot of 2026-10-10: source URLs, download times, checksums. Orbit data courtesy of CelesTrak. |
| [`data/pinned/20261010T2035Z-celestrak/`](../data/pinned/20261010T2035Z-celestrak/) | Second snapshot (2026-10-10 20:35 UTC), fetched by `pipeline/fetch.py`. Every request is logged in `data/pinned/fetch_log.jsonl`. |
| [`data/static/cities.csv`](../data/static/cities.csv) | 60 cities from Natural Earth (public domain); source in `CITIES_SOURCE.md`. |
| [`pipeline/README.md`](../pipeline/README.md) | How orbit data is fetched (CelesTrak rules), validated and slimmed for the website. |

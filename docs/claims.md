# Report claim ledger

This ledger covers the [IEEE-style report draft](report/README.md). The companion
[claims.json](report/claims.json) contains exact machine-checkable CSV selectors or JSON
metadata paths and rendering formats. Quantitative result statements use CSV files only;
configuration choices come from saved result metadata, including manifests. No value is
estimated by reading a plot. Rounding below is display formatting, not new analysis.

The report body links every quantity to its unique anchor below. RFC numbers, experiment,
constellation and metric names, code identifiers and bibliography dates are identifiers,
not measurements. Statistical confidence level is carried by the named source columns.
A REAL implementation byte is not deployed network traffic. MODELLED outcomes may have
DERIVED statistics; neither label makes them operational observations.

## Reviewed evidence releases

| Experiment | Results directory | Manifest |
| --- | --- | --- |
| E0 | `results/E00/20261011T100448Z` | [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json) |
| E1 | `results/E01/20261011T154940Z-confirmatory-resumed` | [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json) |
| E2 | `results/E02/20261011T175659Z-confirmatory` | [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json) |
| E4 | `results/E04/20261011T185503Z-collected` | [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json) |
| E5 | `results/E05/20261011T185503Z-confirmatory` | [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json) |
| E16 | `results/E16/20261011T194240Z-confirmatory` | [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json) |

Only the named reviewed releases are used. Earlier pilots select settings but do not
supply confirmatory estimates. Output hashes and sizes, clean producer/collector commits,
unique selectors and report displays are enforced by `sim/tests/test_report_claims.py`.
The check is an evidence-consistency test, not an experiment or a replacement for the
producer's validity checks. Every original result artifact remains unchanged.

## Quantitative claims

Each entry gives the exact displayed value, label, file path, selector or metadata path,
and its manifest. Repeated uses of a linked quantity share the same anchor.

<a id="q-seeds"></a>

**q-seeds: 1000 — MODELLED.** JSON path `["config", "paired_seeds", 0]`; recorded configuration choice, not a measured network outcome. Source: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-last-seed"></a>

**q-last-seed: 1035 — MODELLED.** JSON path `["config", "paired_seeds", -1]`; recorded configuration choice, not a measured network outcome. Source: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-samples"></a>

**q-samples: 36 — MODELLED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `n`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `raw`.

<a id="q-c2-planes"></a>

**q-c2-planes: 72 — MODELLED.** JSON path `["config", "model", "walker", "planes"]`; recorded configuration choice, not a measured network outcome. Source: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-c2-per-plane"></a>

**q-c2-per-plane: 22 — MODELLED.** JSON path `["config", "model", "walker", "per_plane"]`; recorded configuration choice, not a measured network outcome. Source: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-c2-altitude"></a>

**q-c2-altitude: 550 — MODELLED.** JSON path `["config", "model", "walker", "altitude_km"]`; recorded configuration choice, not a measured network outcome. Source: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `.0f`.

<a id="q-tost-alpha"></a>

**q-tost-alpha: 0.05 — MODELLED.** JSON path `["config", "alpha"]`; recorded configuration choice, not a measured network outcome. Source: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.2f`.

<a id="q-bootstrap"></a>

**q-bootstrap: 10000 — MODELLED.** JSON path `["config", "bootstrap_resamples"]`; recorded configuration choice, not a measured network outcome. Source: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `raw`.

<a id="q-selected-slack"></a>

**q-selected-slack: 1.5 — MODELLED.** JSON path `["C5", "rule", "slack"]`; recorded configuration choice, not a measured network outcome. Source: [results/E01/20261011T154940Z-confirmatory-resumed/operating_points.json](../results/E01/20261011T154940Z-confirmatory-resumed/operating_points.json); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `raw`.

<a id="q-selected-unit"></a>

**q-selected-unit: 1 — MODELLED.** JSON path `["C5", "rule", "unit_code"]`; recorded configuration choice, not a measured network outcome. Source: [results/E01/20261011T154940Z-confirmatory-resumed/operating_points.json](../results/E01/20261011T154940Z-confirmatory-resumed/operating_points.json); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `raw`.

<a id="q-fpr-c5-mean"></a>

**q-fpr-c5-mean: 0.005862 — DERIVED.** CSV row `{"const": "C5", "scheme": "chronoroute"}`, column `fpr`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv](../results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-fpr-c5-lo"></a>

**q-fpr-c5-lo: 0.004974 — DERIVED.** CSV row `{"const": "C5", "scheme": "chronoroute"}`, column `lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv](../results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-fpr-c5-hi"></a>

**q-fpr-c5-hi: 0.006786 — DERIVED.** CSV row `{"const": "C5", "scheme": "chronoroute"}`, column `hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv](../results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-fpr-c2-mean"></a>

**q-fpr-c2-mean: 0.004134 — DERIVED.** CSV row `{"const": "C2", "scheme": "chronoroute"}`, column `fpr`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv](../results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-fpr-c2-lo"></a>

**q-fpr-c2-lo: 0.003261 — DERIVED.** CSV row `{"const": "C2", "scheme": "chronoroute"}`, column `lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv](../results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-fpr-c2-hi"></a>

**q-fpr-c2-hi: 0.005039 — DERIVED.** CSV row `{"const": "C2", "scheme": "chronoroute"}`, column `hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv](../results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-gate-orbit-checked"></a>

**q-gate-orbit-checked: 120200 — REAL.** CSV row `{"check": "orbit_pinned_full", "constellation": "C5"}`, column `checked`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-orbit-violations"></a>

**q-gate-orbit-violations: 0 — DERIVED.** CSV row `{"check": "orbit_pinned_full", "constellation": "C5"}`, column `violations`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-orbit-worst"></a>

**q-gate-orbit-worst: 7.841126 — REAL.** CSV row `{"check": "orbit_pinned_full", "constellation": "C5"}`, column `worst`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `.6f`.

<a id="q-gate-epoch-checked"></a>

**q-gate-epoch-checked: 120200 — REAL.** CSV row `{"check": "orbit_pinned_ms_epoch", "constellation": "C5"}`, column `checked`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-epoch-violations"></a>

**q-gate-epoch-violations: 0 — DERIVED.** CSV row `{"check": "orbit_pinned_ms_epoch", "constellation": "C5"}`, column `violations`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-epoch-worst"></a>

**q-gate-epoch-worst: 0.298997 — REAL.** CSV row `{"check": "orbit_pinned_ms_epoch", "constellation": "C5"}`, column `worst`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `.6f`.

<a id="q-gate-physics-checked"></a>

**q-gate-physics-checked: 3206936 — MODELLED.** CSV row `{"check": "isl_grazing", "constellation": "C5"}`, column `checked`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-physics-violations"></a>

**q-gate-physics-violations: 0 — DERIVED.** CSV row `{"check": "isl_grazing", "constellation": "C5"}`, column `violations`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-physics-worst"></a>

**q-gate-physics-worst: 138.072646 — MODELLED.** CSV row `{"check": "isl_grazing", "constellation": "C5"}`, column `worst`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `.6f`.

<a id="q-gate-browser-checked"></a>

**q-gate-browser-checked: 5866 — REAL.** CSV row `{"check": "wire_browser", "constellation": "C5+C2+golden"}`, column `checked`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-browser-violations"></a>

**q-gate-browser-violations: 0 — DERIVED.** CSV row `{"check": "wire_browser", "constellation": "C5+C2+golden"}`, column `violations`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-browser-worst"></a>

**q-gate-browser-worst: 0.000000 — REAL.** CSV row `{"check": "wire_browser", "constellation": "C5+C2+golden"}`, column `worst`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `.6f`.

<a id="q-gate-ns3-checked"></a>

**q-gate-ns3-checked: 5866 — REAL.** CSV row `{"check": "wire_ns3", "constellation": "C5+C2+golden"}`, column `checked`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-ns3-violations"></a>

**q-gate-ns3-violations: 0 — DERIVED.** CSV row `{"check": "wire_ns3", "constellation": "C5+C2+golden"}`, column `violations`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-ns3-worst"></a>

**q-gate-ns3-worst: 0.000000 — REAL.** CSV row `{"check": "wire_ns3", "constellation": "C5+C2+golden"}`, column `worst`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `.6f`.

<a id="q-gate-wireshark-checked"></a>

**q-gate-wireshark-checked: 10765 — REAL.** CSV row `{"check": "wire_wireshark_fields", "constellation": "C5+C2+golden"}`, column `checked`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-wireshark-violations"></a>

**q-gate-wireshark-violations: 0 — DERIVED.** CSV row `{"check": "wire_wireshark_fields", "constellation": "C5+C2+golden"}`, column `violations`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

<a id="q-gate-wireshark-worst"></a>

**q-gate-wireshark-worst: 0.000000 — REAL.** CSV row `{"check": "wire_wireshark_fields", "constellation": "C5+C2+golden"}`, column `worst`. Source: [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `.6f`.

<a id="q-null-rate-packets"></a>

**q-null-rate-packets: 0 — DERIVED.** CSV row `{"condition": "rate-1-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `tp`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `raw`.

<a id="q-null-rate-events"></a>

**q-null-rate-events: 0 — DERIVED.** CSV row `{"condition": "rate-1-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.0f`.

<a id="q-null-delay-packets"></a>

**q-null-delay-packets: 0 — DERIVED.** CSV row `{"condition": "delay-0-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `tp`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `raw`.

<a id="q-null-delay-events"></a>

**q-null-delay-events: 0 — DERIVED.** CSV row `{"condition": "delay-0-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.0f`.

<a id="q-null-arq-packets"></a>

**q-null-arq-packets: 0 — DERIVED.** CSV row `{"condition": "arq-0-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `tp`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `raw`.

<a id="q-null-arq-events"></a>

**q-null-arq-events: 0 — DERIVED.** CSV row `{"condition": "arq-0-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.0f`.

<a id="q-detect-strong-cr-mean"></a>

**q-detect-strong-cr-mean: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-cr-lo"></a>

**q-detect-strong-cr-lo: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-cr-hi"></a>

**q-detect-strong-cr-hi: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-cr-mean"></a>

**q-delay-strong-cr-mean: 0.073503 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-cr-lo"></a>

**q-delay-strong-cr-lo: 0.067389 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-cr-hi"></a>

**q-delay-strong-cr-hi: 0.079866 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lsh-mean"></a>

**q-detect-strong-lsh-mean: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_h", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lsh-lo"></a>

**q-detect-strong-lsh-lo: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_h", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lsh-hi"></a>

**q-detect-strong-lsh-hi: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_h", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lsh-mean"></a>

**q-delay-strong-lsh-mean: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_h", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lsh-lo"></a>

**q-delay-strong-lsh-lo: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_h", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lsh-hi"></a>

**q-delay-strong-lsh-hi: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_h", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lsd-mean"></a>

**q-detect-strong-lsd-mean: 0.583333 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lsd-lo"></a>

**q-detect-strong-lsd-lo: 0.414158 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lsd-hi"></a>

**q-detect-strong-lsd-hi: 0.752509 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lsd-mean"></a>

**q-delay-strong-lsd-mean: 1.875936 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lsd-lo"></a>

**q-delay-strong-lsd-lo: 1.268400 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lsd-hi"></a>

**q-delay-strong-lsd-hi: 2.487899 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-e2e-mean"></a>

**q-detect-strong-e2e-mean: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "e2e", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-e2e-lo"></a>

**q-detect-strong-e2e-lo: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "e2e", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-e2e-hi"></a>

**q-detect-strong-e2e-hi: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "e2e", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-e2e-mean"></a>

**q-delay-strong-e2e-mean: 0.141239 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "e2e", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-e2e-lo"></a>

**q-delay-strong-e2e-lo: 0.125608 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "e2e", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-e2e-hi"></a>

**q-delay-strong-e2e-hi: 0.158152 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "e2e", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lq-mean"></a>

**q-detect-strong-lq-mean: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lq-lo"></a>

**q-detect-strong-lq-lo: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-lq-hi"></a>

**q-detect-strong-lq-hi: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lq-mean"></a>

**q-delay-strong-lq-mean: 0.016681 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lq-lo"></a>

**q-delay-strong-lq-lo: 0.015631 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-lq-hi"></a>

**q-delay-strong-lq-hi: 0.017749 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-crh-mean"></a>

**q-detect-strong-crh-mean: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "crh16", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-crh-lo"></a>

**q-detect-strong-crh-lo: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "crh16", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-strong-crh-hi"></a>

**q-detect-strong-crh-hi: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "crh16", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-crh-mean"></a>

**q-delay-strong-crh-mean: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "crh16", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-crh-lo"></a>

**q-delay-strong-crh-lo: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "crh16", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-strong-crh-hi"></a>

**q-delay-strong-crh-hi: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.2-middle", "const": "C5", "k": "2", "scheme": "crh16", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-cr-mean"></a>

**q-detect-boundary-cr-mean: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-cr-lo"></a>

**q-detect-boundary-cr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-cr-hi"></a>

**q-detect-boundary-cr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-cr-mean"></a>

**q-delay-boundary-cr-mean: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-cr-lo"></a>

**q-delay-boundary-cr-lo: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-cr-hi"></a>

**q-delay-boundary-cr-hi: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-lsd-mean"></a>

**q-detect-boundary-lsd-mean: 0.611111 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-lsd-lo"></a>

**q-detect-boundary-lsd-lo: 0.443826 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-lsd-hi"></a>

**q-detect-boundary-lsd-hi: 0.778396 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-lsd-mean"></a>

**q-delay-boundary-lsd-mean: 1.859900 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-lsd-lo"></a>

**q-delay-boundary-lsd-lo: 1.256761 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-lsd-hi"></a>

**q-delay-boundary-lsd-hi: 2.472051 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-lq-mean"></a>

**q-detect-boundary-lq-mean: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-lq-lo"></a>

**q-detect-boundary-lq-lo: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-boundary-lq-hi"></a>

**q-detect-boundary-lq-hi: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-lq-mean"></a>

**q-delay-boundary-lq-mean: 1.323159 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-lq-lo"></a>

**q-delay-boundary-lq-lo: 1.297016 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-boundary-lq-hi"></a>

**q-delay-boundary-lq-hi: 1.346450 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C5", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-cr-mean"></a>

**q-detect-c2-boundary-cr-mean: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-cr-lo"></a>

**q-detect-c2-boundary-cr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-cr-hi"></a>

**q-detect-c2-boundary-cr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-cr-mean"></a>

**q-delay-c2-boundary-cr-mean: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-cr-lo"></a>

**q-delay-c2-boundary-cr-lo: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-cr-hi"></a>

**q-delay-c2-boundary-cr-hi: 4.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "chronoroute", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-lsd-mean"></a>

**q-detect-c2-boundary-lsd-mean: 0.611111 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-lsd-lo"></a>

**q-detect-c2-boundary-lsd-lo: 0.443826 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-lsd-hi"></a>

**q-detect-c2-boundary-lsd-hi: 0.778396 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-lsd-mean"></a>

**q-delay-c2-boundary-lsd-mean: 1.656031 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-lsd-lo"></a>

**q-delay-c2-boundary-lsd-lo: 1.054845 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-lsd-hi"></a>

**q-delay-c2-boundary-lsd-hi: 2.274892 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "ls_d", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-lq-mean"></a>

**q-detect-c2-boundary-lq-mean: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_mean`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-lq-lo"></a>

**q-detect-c2-boundary-lq-lo: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-detect-c2-boundary-lq-hi"></a>

**q-detect-c2-boundary-lq-hi: 1.000000 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "lq", "selected": "True"}`, column `event_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-lq-mean"></a>

**q-delay-c2-boundary-lq-mean: 1.367539 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_mean_s`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-lq-lo"></a>

**q-delay-c2-boundary-lq-lo: 1.355871 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_boot_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-delay-c2-boundary-lq-hi"></a>

**q-delay-c2-boundary-lq-hi: 1.378908 — DERIVED.** CSV row `{"condition": "rate-0.3-middle", "const": "C2", "k": "2", "scheme": "lq", "selected": "True"}`, column `restricted_boot_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-boundary-mean"></a>

**q-loss-boundary-mean: -0.611111 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `mean_diff`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-boundary-lo"></a>

**q-loss-boundary-lo: -0.750694 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `bootstrap_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-boundary-hi"></a>

**q-loss-boundary-hi: -0.444444 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `bootstrap_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-boundary-p"></a>

**q-loss-boundary-p: 1.43e-06 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `adjusted_p`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.3g`.

<a id="q-loss-boundary-lq-mean"></a>

**q-loss-boundary-lq-mean: -1.000000 — DERIVED.** CSV row `{"comparator": "lq", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `mean_diff`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-boundary-lq-lo"></a>

**q-loss-boundary-lq-lo: -1.000000 — DERIVED.** CSV row `{"comparator": "lq", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `bootstrap_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-boundary-lq-hi"></a>

**q-loss-boundary-lq-hi: -1.000000 — DERIVED.** CSV row `{"comparator": "lq", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `bootstrap_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-boundary-lq-p"></a>

**q-loss-boundary-lq-p: 0 — DERIVED.** CSV row `{"comparator": "lq", "condition": "rate-0.3-middle", "const": "C5", "endpoint": "detected"}`, column `adjusted_p`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.3g`.

<a id="q-loss-delay-mean"></a>

**q-loss-delay-mean: -0.555556 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "detected"}`, column `mean_diff`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-delay-lo"></a>

**q-loss-delay-lo: -0.722222 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "detected"}`, column `bootstrap_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-delay-hi"></a>

**q-loss-delay-hi: -0.388889 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "detected"}`, column `bootstrap_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-delay-p"></a>

**q-loss-delay-p: 1.47e-05 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "detected"}`, column `adjusted_p`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.3g`.

<a id="q-loss-delay-time-mean"></a>

**q-loss-delay-time-mean: 2.071903 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "restricted_s"}`, column `mean_diff`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-delay-time-lo"></a>

**q-loss-delay-time-lo: 1.433494 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "restricted_s"}`, column `bootstrap_lo`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-delay-time-hi"></a>

**q-loss-delay-time-hi: 2.694815 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "restricted_s"}`, column `bootstrap_hi`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.6f`.

<a id="q-loss-delay-time-p"></a>

**q-loss-delay-time-p: 2.64e-05 — DERIVED.** CSV row `{"comparator": "ls_d", "condition": "delay-1000000-middle", "const": "C5", "endpoint": "restricted_s"}`, column `adjusted_p`. Source: [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). Display format: `.3g`.

<a id="q-size-entries-4"></a>

**q-size-entries-4: 4 — DERIVED.** CSV row `{"entries": "4", "mode": "source", "protocol": "tcrh"}`, column `entries`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-4-tcrh"></a>

**q-size-4-tcrh: 24 — DERIVED.** CSV row `{"entries": "4", "mode": "source", "protocol": "tcrh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-4-crh16"></a>

**q-size-4-crh16: 16 — DERIVED.** CSV row `{"entries": "4", "mode": "source", "protocol": "crh16"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-4-crh32"></a>

**q-size-4-crh32: 24 — DERIVED.** CSV row `{"entries": "4", "mode": "source", "protocol": "crh32"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-4-srh"></a>

**q-size-4-srh: 72 — DERIVED.** CSV row `{"entries": "4", "mode": "source", "protocol": "srh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-entries-8"></a>

**q-size-entries-8: 8 — DERIVED.** CSV row `{"entries": "8", "mode": "source", "protocol": "tcrh"}`, column `entries`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-8-tcrh"></a>

**q-size-8-tcrh: 40 — DERIVED.** CSV row `{"entries": "8", "mode": "source", "protocol": "tcrh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-8-crh16"></a>

**q-size-8-crh16: 24 — DERIVED.** CSV row `{"entries": "8", "mode": "source", "protocol": "crh16"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-8-crh32"></a>

**q-size-8-crh32: 40 — DERIVED.** CSV row `{"entries": "8", "mode": "source", "protocol": "crh32"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-8-srh"></a>

**q-size-8-srh: 136 — DERIVED.** CSV row `{"entries": "8", "mode": "source", "protocol": "srh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-entries-12"></a>

**q-size-entries-12: 12 — DERIVED.** CSV row `{"entries": "12", "mode": "source", "protocol": "tcrh"}`, column `entries`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-12-tcrh"></a>

**q-size-12-tcrh: 48 — DERIVED.** CSV row `{"entries": "12", "mode": "source", "protocol": "tcrh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-12-crh16"></a>

**q-size-12-crh16: 32 — DERIVED.** CSV row `{"entries": "12", "mode": "source", "protocol": "crh16"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-12-crh32"></a>

**q-size-12-crh32: 56 — DERIVED.** CSV row `{"entries": "12", "mode": "source", "protocol": "crh32"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-12-srh"></a>

**q-size-12-srh: 200 — DERIVED.** CSV row `{"entries": "12", "mode": "source", "protocol": "srh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-entries-40"></a>

**q-size-entries-40: 40 — DERIVED.** CSV row `{"entries": "40", "mode": "source", "protocol": "tcrh"}`, column `entries`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-40-tcrh"></a>

**q-size-40-tcrh: 136 — DERIVED.** CSV row `{"entries": "40", "mode": "source", "protocol": "tcrh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-40-crh16"></a>

**q-size-40-crh16: 88 — DERIVED.** CSV row `{"entries": "40", "mode": "source", "protocol": "crh16"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-40-crh32"></a>

**q-size-40-crh32: 168 — DERIVED.** CSV row `{"entries": "40", "mode": "source", "protocol": "crh32"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-size-40-srh"></a>

**q-size-40-srh: 648 — DERIVED.** CSV row `{"entries": "40", "mode": "source", "protocol": "srh"}`, column `added_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-capture-entries"></a>

**q-capture-entries: 8 — REAL.** CSV row `{"label": "REAL"}`, column `entries`. Source: [results/E02/20261011T175659Z-confirmatory/capture_summary.csv](../results/E02/20261011T175659Z-confirmatory/capture_summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-capture-header"></a>

**q-capture-header: 40 — REAL.** CSV row `{"label": "REAL"}`, column `header_bytes`. Source: [results/E02/20261011T175659Z-confirmatory/capture_summary.csv](../results/E02/20261011T175659Z-confirmatory/capture_summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-capture-frames"></a>

**q-capture-frames: 83117 — REAL.** CSV row `{"label": "REAL"}`, column `frames`. Source: [results/E02/20261011T175659Z-confirmatory/capture_summary.csv](../results/E02/20261011T175659Z-confirmatory/capture_summary.csv); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-reference"></a>

**q-reference: 1400 — MODELLED.** JSON path `["config", "reference_packet_bytes"]`; recorded configuration choice, not a measured network outcome. Source: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json); manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-hard-c5-greedy-visited-pdr-mean"></a>

**q-hard-c5-greedy-visited-pdr-mean: 0.997014 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-pdr-lo"></a>

**q-hard-c5-greedy-visited-pdr-lo: 0.994370 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-pdr-hi"></a>

**q-hard-c5-greedy-visited-pdr-hi: 0.999658 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-blackhole"></a>

**q-hard-c5-greedy-visited-blackhole: 0.271175 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-blackhole-n"></a>

**q-hard-c5-greedy-visited-blackhole-n: 16 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-greedy-visited-tail"></a>

**q-hard-c5-greedy-visited-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-tail-n"></a>

**q-hard-c5-greedy-visited-tail-n: 5 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-continue-pdr-mean"></a>

**q-hard-c5-continue-pdr-mean: 0.968079 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-pdr-lo"></a>

**q-hard-c5-continue-pdr-lo: 0.948134 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-pdr-hi"></a>

**q-hard-c5-continue-pdr-hi: 0.988023 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-blackhole"></a>

**q-hard-c5-continue-blackhole: 1.517442 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-blackhole-n"></a>

**q-hard-c5-continue-blackhole-n: 16 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-continue-tail"></a>

**q-hard-c5-continue-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-tail-n"></a>

**q-hard-c5-continue-tail-n: 14 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-crh16-pdr-mean"></a>

**q-hard-c5-crh16-pdr-mean: 0.968079 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-pdr-lo"></a>

**q-hard-c5-crh16-pdr-lo: 0.948134 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-pdr-hi"></a>

**q-hard-c5-crh16-pdr-hi: 0.988023 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-blackhole"></a>

**q-hard-c5-crh16-blackhole: 1.517441 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-blackhole-n"></a>

**q-hard-c5-crh16-blackhole-n: 16 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-crh16-tail"></a>

**q-hard-c5-crh16-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-tail-n"></a>

**q-hard-c5-crh16-tail-n: 14 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-snap-pdr-mean"></a>

**q-hard-c5-snap-pdr-mean: 0.971671 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-pdr-lo"></a>

**q-hard-c5-snap-pdr-lo: 0.956147 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-pdr-hi"></a>

**q-hard-c5-snap-pdr-hi: 0.987195 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-blackhole"></a>

**q-hard-c5-snap-blackhole: 1.398185 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-blackhole-n"></a>

**q-hard-c5-snap-blackhole-n: 16 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-snap-tail"></a>

**q-hard-c5-snap-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-tail-n"></a>

**q-hard-c5-snap-tail-n: 14 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-ls-h-pdr-mean"></a>

**q-hard-c5-ls-h-pdr-mean: 0.998907 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-pdr-lo"></a>

**q-hard-c5-ls-h-pdr-lo: 0.998408 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-pdr-hi"></a>

**q-hard-c5-ls-h-pdr-hi: 0.999407 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-blackhole"></a>

**q-hard-c5-ls-h-blackhole: 0.048497 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-blackhole-n"></a>

**q-hard-c5-ls-h-blackhole-n: 16 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-ls-h-tail"></a>

**q-hard-c5-ls-h-tail: 0.052314 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-tail-n"></a>

**q-hard-c5-ls-h-tail-n: 0 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-o-t-pdr-mean"></a>

**q-hard-c5-o-t-pdr-mean: 0.999921 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-pdr-lo"></a>

**q-hard-c5-o-t-pdr-lo: 0.999876 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-pdr-hi"></a>

**q-hard-c5-o-t-pdr-hi: 0.999967 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-blackhole"></a>

**q-hard-c5-o-t-blackhole: 0.001506 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-blackhole-n"></a>

**q-hard-c5-o-t-blackhole-n: 16 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c5-o-t-tail"></a>

**q-hard-c5-o-t-tail: 0.052211 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-tail-n"></a>

**q-hard-c5-o-t-tail-n: 0 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-greedy-visited-pdr-mean"></a>

**q-hard-c2-greedy-visited-pdr-mean: 0.998616 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-pdr-lo"></a>

**q-hard-c2-greedy-visited-pdr-lo: 0.996655 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-pdr-hi"></a>

**q-hard-c2-greedy-visited-pdr-hi: 1.000576 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-blackhole"></a>

**q-hard-c2-greedy-visited-blackhole: 0.001975 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-blackhole-n"></a>

**q-hard-c2-greedy-visited-blackhole-n: 19 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-greedy-visited-tail"></a>

**q-hard-c2-greedy-visited-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-tail-n"></a>

**q-hard-c2-greedy-visited-tail-n: 2 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-continue-pdr-mean"></a>

**q-hard-c2-continue-pdr-mean: 0.963056 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-pdr-lo"></a>

**q-hard-c2-continue-pdr-lo: 0.940907 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-pdr-hi"></a>

**q-hard-c2-continue-pdr-hi: 0.985204 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-blackhole"></a>

**q-hard-c2-continue-blackhole: 1.844305 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-blackhole-n"></a>

**q-hard-c2-continue-blackhole-n: 19 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-continue-tail"></a>

**q-hard-c2-continue-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-tail-n"></a>

**q-hard-c2-continue-tail-n: 15 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-crh16-pdr-mean"></a>

**q-hard-c2-crh16-pdr-mean: 0.963056 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-pdr-lo"></a>

**q-hard-c2-crh16-pdr-lo: 0.940907 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-pdr-hi"></a>

**q-hard-c2-crh16-pdr-hi: 0.985204 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-blackhole"></a>

**q-hard-c2-crh16-blackhole: 1.844304 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-blackhole-n"></a>

**q-hard-c2-crh16-blackhole-n: 19 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-crh16-tail"></a>

**q-hard-c2-crh16-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-tail-n"></a>

**q-hard-c2-crh16-tail-n: 15 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-snap-pdr-mean"></a>

**q-hard-c2-snap-pdr-mean: 0.962995 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-pdr-lo"></a>

**q-hard-c2-snap-pdr-lo: 0.940828 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-pdr-hi"></a>

**q-hard-c2-snap-pdr-hi: 0.985163 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-blackhole"></a>

**q-hard-c2-snap-blackhole: 1.844303 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-blackhole-n"></a>

**q-hard-c2-snap-blackhole-n: 19 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-snap-tail"></a>

**q-hard-c2-snap-tail: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-tail-n"></a>

**q-hard-c2-snap-tail-n: 15 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-ls-h-pdr-mean"></a>

**q-hard-c2-ls-h-pdr-mean: 0.998954 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-pdr-lo"></a>

**q-hard-c2-ls-h-pdr-lo: 0.998586 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-pdr-hi"></a>

**q-hard-c2-ls-h-pdr-hi: 0.999321 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-blackhole"></a>

**q-hard-c2-ls-h-blackhole: 0.051252 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-blackhole-n"></a>

**q-hard-c2-ls-h-blackhole-n: 19 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-ls-h-tail"></a>

**q-hard-c2-ls-h-tail: 0.042408 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-tail-n"></a>

**q-hard-c2-ls-h-tail-n: 0 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-o-t-pdr-mean"></a>

**q-hard-c2-o-t-pdr-mean: 0.999926 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `pdr_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-pdr-lo"></a>

**q-hard-c2-o-t-pdr-lo: 0.999887 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `pdr_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-pdr-hi"></a>

**q-hard-c2-o-t-pdr-hi: 0.999965 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `pdr_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-blackhole"></a>

**q-hard-c2-o-t-blackhole: 0.001975 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `blackhole_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-blackhole-n"></a>

**q-hard-c2-o-t-blackhole-n: 19 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `blackhole_n`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-c2-o-t-tail"></a>

**q-hard-c2-o-t-tail: 0.042389 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `effective_p99_mean`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-tail-n"></a>

**q-hard-c2-o-t-tail-n: 0 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `infinite_tail_runs`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `raw`.

<a id="q-hard-paired-blackhole-mean"></a>

**q-hard-paired-blackhole-mean: -1.246267 — DERIVED.** CSV row `{"comparator": "continue", "condition": "node-B", "const": "C5", "endpoint": "blackhole_s"}`, column `mean_diff`. Source: [results/E04/20261011T185503Z-collected/paired_contrasts.csv](../results/E04/20261011T185503Z-collected/paired_contrasts.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-paired-blackhole-lo"></a>

**q-hard-paired-blackhole-lo: -1.865710 — DERIVED.** CSV row `{"comparator": "continue", "condition": "node-B", "const": "C5", "endpoint": "blackhole_s"}`, column `bootstrap_lo`. Source: [results/E04/20261011T185503Z-collected/paired_contrasts.csv](../results/E04/20261011T185503Z-collected/paired_contrasts.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-paired-blackhole-hi"></a>

**q-hard-paired-blackhole-hi: -0.691545 — DERIVED.** CSV row `{"comparator": "continue", "condition": "node-B", "const": "C5", "endpoint": "blackhole_s"}`, column `bootstrap_hi`. Source: [results/E04/20261011T185503Z-collected/paired_contrasts.csv](../results/E04/20261011T185503Z-collected/paired_contrasts.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-paired-blackhole-p"></a>

**q-hard-paired-blackhole-p: 0.027790 — DERIVED.** CSV row `{"comparator": "continue", "condition": "node-B", "const": "C5", "endpoint": "blackhole_s"}`, column `adjusted_p`. Source: [results/E04/20261011T185503Z-collected/paired_contrasts.csv](../results/E04/20261011T185503Z-collected/paired_contrasts.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-paired-pdr-p"></a>

**q-hard-paired-pdr-p: 0.104921 — DERIVED.** CSV row `{"comparator": "continue", "condition": "node-B", "const": "C5", "endpoint": "pdr"}`, column `adjusted_p`. Source: [results/E04/20261011T185503Z-collected/paired_contrasts.csv](../results/E04/20261011T185503Z-collected/paired_contrasts.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-pure-pdr-mean"></a>

**q-fallback-c5-greedy-pure-pdr-mean: 0.611111 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_pure"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-pure-pdr-lo"></a>

**q-fallback-c5-greedy-pure-pdr-lo: 0.443826 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_pure"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-pure-pdr-hi"></a>

**q-fallback-c5-greedy-pure-pdr-hi: 0.778396 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_pure"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-pure-stuck-mean"></a>

**q-fallback-c5-greedy-pure-stuck-mean: 0.388889 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_pure"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-pure-stuck-lo"></a>

**q-fallback-c5-greedy-pure-stuck-lo: 0.221604 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_pure"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-pure-stuck-hi"></a>

**q-fallback-c5-greedy-pure-stuck-hi: 0.556174 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_pure"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-visited-pdr-mean"></a>

**q-fallback-c5-greedy-visited-pdr-mean: 0.833333 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_visited"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-visited-pdr-lo"></a>

**q-fallback-c5-greedy-visited-pdr-lo: 0.705449 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_visited"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-visited-pdr-hi"></a>

**q-fallback-c5-greedy-visited-pdr-hi: 0.961218 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_visited"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-visited-stuck-mean"></a>

**q-fallback-c5-greedy-visited-stuck-mean: 0.166667 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_visited"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-visited-stuck-lo"></a>

**q-fallback-c5-greedy-visited-stuck-lo: 0.038782 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_visited"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-greedy-visited-stuck-hi"></a>

**q-fallback-c5-greedy-visited-stuck-hi: 0.294551 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "greedy_visited"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-grid-detour-pdr-mean"></a>

**q-fallback-c5-grid-detour-pdr-mean: 0.777778 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "grid_detour"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-grid-detour-pdr-lo"></a>

**q-fallback-c5-grid-detour-pdr-lo: 0.635116 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "grid_detour"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-grid-detour-pdr-hi"></a>

**q-fallback-c5-grid-detour-pdr-hi: 0.920439 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "grid_detour"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-grid-detour-stuck-mean"></a>

**q-fallback-c5-grid-detour-stuck-mean: 0.222222 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "grid_detour"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-grid-detour-stuck-lo"></a>

**q-fallback-c5-grid-detour-stuck-lo: 0.079561 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "grid_detour"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-grid-detour-stuck-hi"></a>

**q-fallback-c5-grid-detour-stuck-hi: 0.364884 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "grid_detour"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-continue-pdr-mean"></a>

**q-fallback-c5-continue-pdr-mean: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "continue"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-continue-pdr-lo"></a>

**q-fallback-c5-continue-pdr-lo: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "continue"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-continue-pdr-hi"></a>

**q-fallback-c5-continue-pdr-hi: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "continue"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-continue-stuck-mean"></a>

**q-fallback-c5-continue-stuck-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "continue"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-continue-stuck-lo"></a>

**q-fallback-c5-continue-stuck-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "continue"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-continue-stuck-hi"></a>

**q-fallback-c5-continue-stuck-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "continue"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-drop-pdr-mean"></a>

**q-fallback-c5-drop-pdr-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "drop"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-drop-pdr-lo"></a>

**q-fallback-c5-drop-pdr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "drop"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-drop-pdr-hi"></a>

**q-fallback-c5-drop-pdr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "drop"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-drop-stuck-mean"></a>

**q-fallback-c5-drop-stuck-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "drop"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-drop-stuck-lo"></a>

**q-fallback-c5-drop-stuck-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "drop"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c5-drop-stuck-hi"></a>

**q-fallback-c5-drop-stuck-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C5", "scheme": "drop"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-pure-pdr-mean"></a>

**q-fallback-c2-greedy-pure-pdr-mean: 0.694444 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_pure"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-pure-pdr-lo"></a>

**q-fallback-c2-greedy-pure-pdr-lo: 0.536375 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_pure"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-pure-pdr-hi"></a>

**q-fallback-c2-greedy-pure-pdr-hi: 0.852514 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_pure"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-pure-stuck-mean"></a>

**q-fallback-c2-greedy-pure-stuck-mean: 0.305556 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_pure"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-pure-stuck-lo"></a>

**q-fallback-c2-greedy-pure-stuck-lo: 0.147486 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_pure"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-pure-stuck-hi"></a>

**q-fallback-c2-greedy-pure-stuck-hi: 0.463625 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_pure"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-visited-pdr-mean"></a>

**q-fallback-c2-greedy-visited-pdr-mean: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_visited"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-visited-pdr-lo"></a>

**q-fallback-c2-greedy-visited-pdr-lo: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_visited"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-visited-pdr-hi"></a>

**q-fallback-c2-greedy-visited-pdr-hi: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_visited"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-visited-stuck-mean"></a>

**q-fallback-c2-greedy-visited-stuck-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_visited"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-visited-stuck-lo"></a>

**q-fallback-c2-greedy-visited-stuck-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_visited"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-greedy-visited-stuck-hi"></a>

**q-fallback-c2-greedy-visited-stuck-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "greedy_visited"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-grid-detour-pdr-mean"></a>

**q-fallback-c2-grid-detour-pdr-mean: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "grid_detour"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-grid-detour-pdr-lo"></a>

**q-fallback-c2-grid-detour-pdr-lo: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "grid_detour"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-grid-detour-pdr-hi"></a>

**q-fallback-c2-grid-detour-pdr-hi: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "grid_detour"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-grid-detour-stuck-mean"></a>

**q-fallback-c2-grid-detour-stuck-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "grid_detour"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-grid-detour-stuck-lo"></a>

**q-fallback-c2-grid-detour-stuck-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "grid_detour"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-grid-detour-stuck-hi"></a>

**q-fallback-c2-grid-detour-stuck-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "grid_detour"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-continue-pdr-mean"></a>

**q-fallback-c2-continue-pdr-mean: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "continue"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-continue-pdr-lo"></a>

**q-fallback-c2-continue-pdr-lo: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "continue"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-continue-pdr-hi"></a>

**q-fallback-c2-continue-pdr-hi: 1.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "continue"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-continue-stuck-mean"></a>

**q-fallback-c2-continue-stuck-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "continue"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-continue-stuck-lo"></a>

**q-fallback-c2-continue-stuck-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "continue"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-continue-stuck-hi"></a>

**q-fallback-c2-continue-stuck-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "continue"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-drop-pdr-mean"></a>

**q-fallback-c2-drop-pdr-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "drop"}`, column `triggered_pdr_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-drop-pdr-lo"></a>

**q-fallback-c2-drop-pdr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "drop"}`, column `triggered_pdr_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-drop-pdr-hi"></a>

**q-fallback-c2-drop-pdr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "drop"}`, column `triggered_pdr_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-drop-stuck-mean"></a>

**q-fallback-c2-drop-stuck-mean: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "drop"}`, column `stuck_rate_mean`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-drop-stuck-lo"></a>

**q-fallback-c2-drop-stuck-lo: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "drop"}`, column `stuck_rate_lo`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-fallback-c2-drop-stuck-hi"></a>

**q-fallback-c2-drop-stuck-hi: 0.000000 — DERIVED.** CSV row `{"condition": "trigger", "const": "C2", "scheme": "drop"}`, column `stuck_rate_hi`. Source: [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-greedy-visited-mean"></a>

**q-policy-c5-greedy-visited-mean: -0.222222 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C5", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `mean_diff`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-greedy-visited-lo"></a>

**q-policy-c5-greedy-visited-lo: -0.364884 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C5", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `lo`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-greedy-visited-hi"></a>

**q-policy-c5-greedy-visited-hi: -0.079561 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C5", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `hi`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-greedy-visited-p"></a>

**q-policy-c5-greedy-visited-p: 0.003228 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C5", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `adjusted_p`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-grid-detour-mean"></a>

**q-policy-c5-grid-detour-mean: 0.055556 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C5", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `mean_diff`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-grid-detour-lo"></a>

**q-policy-c5-grid-detour-lo: -0.023047 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C5", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `lo`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-grid-detour-hi"></a>

**q-policy-c5-grid-detour-hi: 0.134158 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C5", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `hi`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c5-grid-detour-p"></a>

**q-policy-c5-grid-detour-p: 0.320406 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C5", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `adjusted_p`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-greedy-visited-mean"></a>

**q-policy-c2-greedy-visited-mean: -0.305556 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C2", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `mean_diff`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-greedy-visited-lo"></a>

**q-policy-c2-greedy-visited-lo: -0.463625 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C2", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `lo`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-greedy-visited-hi"></a>

**q-policy-c2-greedy-visited-hi: -0.147486 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C2", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `hi`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-greedy-visited-p"></a>

**q-policy-c2-greedy-visited-p: 0.000777 — DERIVED.** CSV row `{"comparator": "greedy_pure", "const": "C2", "endpoint": "stuck_rate", "primary": "greedy_visited"}`, column `adjusted_p`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-grid-detour-mean"></a>

**q-policy-c2-grid-detour-mean: 0.000000 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C2", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `mean_diff`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-grid-detour-lo"></a>

**q-policy-c2-grid-detour-lo: 0.000000 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C2", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `lo`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-grid-detour-hi"></a>

**q-policy-c2-grid-detour-hi: 0.000000 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C2", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `hi`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-policy-c2-grid-detour-p"></a>

**q-policy-c2-grid-detour-p: 1.000000 — DERIVED.** CSV row `{"comparator": "greedy_visited", "const": "C2", "endpoint": "stuck_rate", "primary": "grid_detour"}`, column `adjusted_p`. Source: [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-pdr-estimate"></a>

**q-agree-c5-pdr-estimate: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "pdr"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-pdr-lo"></a>

**q-agree-c5-pdr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "pdr"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-pdr-hi"></a>

**q-agree-c5-pdr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "pdr"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-pdr-lower"></a>

**q-agree-c5-pdr-lower: -0.010000 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "pdr"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-pdr-upper"></a>

**q-agree-c5-pdr-upper: 0.010000 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "pdr"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-pdr-n"></a>

**q-agree-c5-pdr-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "pdr"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-agree-c5-fpr-estimate"></a>

**q-agree-c5-fpr-estimate: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "fpr"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-fpr-lo"></a>

**q-agree-c5-fpr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "fpr"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-fpr-hi"></a>

**q-agree-c5-fpr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "fpr"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-fpr-lower"></a>

**q-agree-c5-fpr-lower: -0.005000 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "fpr"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-fpr-upper"></a>

**q-agree-c5-fpr-upper: 0.005000 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "fpr"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-fpr-n"></a>

**q-agree-c5-fpr-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "fpr"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-agree-c5-p50-estimate"></a>

**q-agree-c5-p50-estimate: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p50"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p50-lo"></a>

**q-agree-c5-p50-lo: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p50"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p50-hi"></a>

**q-agree-c5-p50-hi: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p50"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p50-lower"></a>

**q-agree-c5-p50-lower: 0.952381 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p50"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p50-upper"></a>

**q-agree-c5-p50-upper: 1.050000 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p50"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p50-n"></a>

**q-agree-c5-p50-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p50"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-agree-c5-p99-estimate"></a>

**q-agree-c5-p99-estimate: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p99"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p99-lo"></a>

**q-agree-c5-p99-lo: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p99"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p99-hi"></a>

**q-agree-c5-p99-hi: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p99"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p99-lower"></a>

**q-agree-c5-p99-lower: 0.952381 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p99"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p99-upper"></a>

**q-agree-c5-p99-upper: 1.050000 — MODELLED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p99"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c5-p99-n"></a>

**q-agree-c5-p99-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C5", "endpoint": "p99"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-agree-c2-pdr-estimate"></a>

**q-agree-c2-pdr-estimate: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "pdr"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-pdr-lo"></a>

**q-agree-c2-pdr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "pdr"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-pdr-hi"></a>

**q-agree-c2-pdr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "pdr"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-pdr-lower"></a>

**q-agree-c2-pdr-lower: -0.010000 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "pdr"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-pdr-upper"></a>

**q-agree-c2-pdr-upper: 0.010000 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "pdr"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-pdr-n"></a>

**q-agree-c2-pdr-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "pdr"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-agree-c2-fpr-estimate"></a>

**q-agree-c2-fpr-estimate: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "fpr"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-fpr-lo"></a>

**q-agree-c2-fpr-lo: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "fpr"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-fpr-hi"></a>

**q-agree-c2-fpr-hi: 0.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "fpr"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-fpr-lower"></a>

**q-agree-c2-fpr-lower: -0.005000 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "fpr"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-fpr-upper"></a>

**q-agree-c2-fpr-upper: 0.005000 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "fpr"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-fpr-n"></a>

**q-agree-c2-fpr-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "fpr"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-agree-c2-p50-estimate"></a>

**q-agree-c2-p50-estimate: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p50"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p50-lo"></a>

**q-agree-c2-p50-lo: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p50"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p50-hi"></a>

**q-agree-c2-p50-hi: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p50"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p50-lower"></a>

**q-agree-c2-p50-lower: 0.952381 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p50"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p50-upper"></a>

**q-agree-c2-p50-upper: 1.050000 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p50"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p50-n"></a>

**q-agree-c2-p50-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p50"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-agree-c2-p99-estimate"></a>

**q-agree-c2-p99-estimate: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p99"}`, column `estimate`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p99-lo"></a>

**q-agree-c2-p99-lo: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p99"}`, column `lo95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p99-hi"></a>

**q-agree-c2-p99-hi: 1.000000 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p99"}`, column `hi95`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p99-lower"></a>

**q-agree-c2-p99-lower: 0.952381 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p99"}`, column `lower_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p99-upper"></a>

**q-agree-c2-p99-upper: 1.050000 — MODELLED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p99"}`, column `upper_bound`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `.6f`.

<a id="q-agree-c2-p99-n"></a>

**q-agree-c2-p99-n: 36 — DERIVED.** CSV row `{"condition": "fault", "const": "C2", "endpoint": "p99"}`, column `n`. Source: [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). Display format: `raw`.

<a id="q-hard-c5-greedy-visited-blackhole-lo"></a>

**q-hard-c5-greedy-visited-blackhole-lo: 0.001365 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-blackhole-hi"></a>

**q-hard-c5-greedy-visited-blackhole-hi: 0.685624 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-tail-lo"></a>

**q-hard-c5-greedy-visited-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-greedy-visited-tail-hi"></a>

**q-hard-c5-greedy-visited-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "greedy_visited"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-blackhole-lo"></a>

**q-hard-c5-continue-blackhole-lo: 0.945244 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-blackhole-hi"></a>

**q-hard-c5-continue-blackhole-hi: 2.138184 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-tail-lo"></a>

**q-hard-c5-continue-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-continue-tail-hi"></a>

**q-hard-c5-continue-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "continue"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-blackhole-lo"></a>

**q-hard-c5-crh16-blackhole-lo: 0.945235 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-blackhole-hi"></a>

**q-hard-c5-crh16-blackhole-hi: 2.149786 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-tail-lo"></a>

**q-hard-c5-crh16-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-crh16-tail-hi"></a>

**q-hard-c5-crh16-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "crh16"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-blackhole-lo"></a>

**q-hard-c5-snap-blackhole-lo: 0.911054 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-blackhole-hi"></a>

**q-hard-c5-snap-blackhole-hi: 1.912758 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-tail-lo"></a>

**q-hard-c5-snap-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-snap-tail-hi"></a>

**q-hard-c5-snap-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "snap"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-blackhole-lo"></a>

**q-hard-c5-ls-h-blackhole-lo: 0.045544 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-blackhole-hi"></a>

**q-hard-c5-ls-h-blackhole-hi: 0.050768 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-tail-lo"></a>

**q-hard-c5-ls-h-tail-lo: 0.044426 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-ls-h-tail-hi"></a>

**q-hard-c5-ls-h-tail-hi: 0.060203 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "ls_h"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-blackhole-lo"></a>

**q-hard-c5-o-t-blackhole-lo: 0.000790 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-blackhole-hi"></a>

**q-hard-c5-o-t-blackhole-hi: 0.002263 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-tail-lo"></a>

**q-hard-c5-o-t-tail-lo: 0.044297 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c5-o-t-tail-hi"></a>

**q-hard-c5-o-t-tail-hi: 0.060124 — DERIVED.** CSV row `{"condition": "node-B", "const": "C5", "scheme": "o_t"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-blackhole-lo"></a>

**q-hard-c2-greedy-visited-blackhole-lo: 0.001102 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-blackhole-hi"></a>

**q-hard-c2-greedy-visited-blackhole-hi: 0.002903 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-tail-lo"></a>

**q-hard-c2-greedy-visited-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-greedy-visited-tail-hi"></a>

**q-hard-c2-greedy-visited-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "greedy_visited"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-blackhole-lo"></a>

**q-hard-c2-continue-blackhole-lo: 1.049177 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-blackhole-hi"></a>

**q-hard-c2-continue-blackhole-hi: 2.772433 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-tail-lo"></a>

**q-hard-c2-continue-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-continue-tail-hi"></a>

**q-hard-c2-continue-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "continue"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-blackhole-lo"></a>

**q-hard-c2-crh16-blackhole-lo: 1.057380 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-blackhole-hi"></a>

**q-hard-c2-crh16-blackhole-hi: 2.757956 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-tail-lo"></a>

**q-hard-c2-crh16-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-crh16-tail-hi"></a>

**q-hard-c2-crh16-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "crh16"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-blackhole-lo"></a>

**q-hard-c2-snap-blackhole-lo: 1.047838 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-blackhole-hi"></a>

**q-hard-c2-snap-blackhole-hi: 2.772548 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-tail-lo"></a>

**q-hard-c2-snap-tail-lo: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-snap-tail-hi"></a>

**q-hard-c2-snap-tail-hi: inf — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "snap"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-blackhole-lo"></a>

**q-hard-c2-ls-h-blackhole-lo: 0.049944 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-blackhole-hi"></a>

**q-hard-c2-ls-h-blackhole-hi: 0.052539 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-tail-lo"></a>

**q-hard-c2-ls-h-tail-lo: 0.037630 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-ls-h-tail-hi"></a>

**q-hard-c2-ls-h-tail-hi: 0.047187 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "ls_h"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-blackhole-lo"></a>

**q-hard-c2-o-t-blackhole-lo: 0.001095 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `blackhole_boot_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-blackhole-hi"></a>

**q-hard-c2-o-t-blackhole-hi: 0.002918 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `blackhole_boot_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-tail-lo"></a>

**q-hard-c2-o-t-tail-lo: 0.037605 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `effective_p99_lo`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-hard-c2-o-t-tail-hi"></a>

**q-hard-c2-o-t-tail-hi: 0.047174 — DERIVED.** CSV row `{"condition": "node-B", "const": "C2", "scheme": "o_t"}`, column `effective_p99_hi`. Source: [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). Display format: `.6f`.

<a id="q-c5-shell"></a>

**q-c5-shell: 53.2deg-463km — DERIVED.** Recorded shell classification, JSON path `["config", "shell"]`. Source and manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). Display format: `raw`.

## Qualitative empirical claims and interpretation boundaries

| Claim in report | Supporting result file(s) and fields | Interpretation boundary |
| --- | --- | --- |
| E0 recorded gate passes, including C2, geometry, browser, ns-3 and Wireshark | [results/E00/20261011T100448Z/summary.csv](../results/E00/20261011T100448Z/summary.csv); All rows: `violations`; the `checked`, `worst`, `limit`, `unit` and `bound` columns define coverage and acceptance. Manifest: [results/E00/20261011T100448Z/manifest.json](../results/E00/20261011T100448Z/manifest.json). | Finite samples; neither orbital truth nor continuous-time proof. |
| The selected E1 pooled operating constraint passes in both shells | [results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv](../results/E01/20261011T154940Z-confirmatory-resumed/population_fpr.csv); `scheme=chronoroute`; `meets_1pct=True`, `interval_position=below`. Manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). | Fault-clean pooling with twins counted once; not a packet-iid interval. |
| Selected E1 cell FPR remains below its registered limit | [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); `scheme=chronoroute, selected=True, k=2`; all `fpr` values. Manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). | Sensitivity rules are separate from the frozen operating point. |
| Strong overload is detected and boundary overload can be missed | [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); Selected ChronoRoute, `k=2`; `rate-0.2-middle` versus `rate-0.3-middle`; `event_mean`. Manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). | Effect is conditional on registered rate/background and shell. |
| LS-D and LQ have material detection advantages | [results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv](../results/E01/20261011T154940Z-confirmatory-resumed/paired_contrasts.csv); `material_loss=True` on `detected` and `restricted_s`; all point disadvantages remain listed. Manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). | Frozen paired families and joint effect/significance criteria; no universal ranking. |
| LS-H/CRH-16 lack an up-but-slow detector; E2E does not localise; O-Q alarm endpoints are undefined | [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); Native scheme rows, `event_mean`, `packet_pdet`, `localised_tp`, empty O-Q detector fields. Manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). | Interpret with `docs/baselines.md`; O-Q is a delivery oracle. |
| The complete null gate has no attributed packet/event violations | [results/E01/20261011T154940Z-confirmatory-resumed/run_metrics.csv](../results/E01/20261011T154940Z-confirmatory-resumed/run_metrics.csv); Null conditions `rate-1-middle`, `delay-0-middle`, `arq-0-middle`, all rules/seeds/schemes; `tp` and `detected`. Manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). | No event/packet attribution is distinct from the native false-flag counts. |
| Fault losses can prevent reaching a checker and remain in delivery | [results/E01/20261011T154940Z-confirmatory-resumed/summary.csv](../results/E01/20261011T154940Z-confirmatory-resumed/summary.csv); `lost_at_fault`, `crossed`, `reached`, `sent`, `delivered`. Manifest: [results/E01/20261011T154940Z-confirmatory-resumed/manifest.json](../results/E01/20261011T154940Z-confirmatory-resumed/manifest.json). | Crossing-conditioned detection is not recovery or detection of already-lost packets. |
| T-CRH costs more than CRH-16 and less than SRH over the registered range | [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); Match `entries` and `mode`; compare `added_bytes` by `protocol`. Manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). | DERIVED exact sizes; no throughput or latency inference. |
| CRH-32 ties and crossover depend on count and padding | [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); Match `entries, mode`; `added_bytes` for `tcrh` and `crh32`. Manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). | No universal wire saving. |
| Encapsulation adds an outer-header cost; percentage denominators differ | [results/E02/20261011T175659Z-confirmatory/summary.csv](../results/E02/20261011T175659Z-confirmatory/summary.csv); Same `entries,protocol`, differing `mode`; `header_bytes`, `added_bytes`, `reference_bytes`, `reference_percent`, `final_percent`. Manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). | Configuration and exact accounting, not empirical payload distribution. |
| Captures corroborate T-CRH only | [results/E02/20261011T175659Z-confirmatory/capture_summary.csv](../results/E02/20261011T175659Z-confirmatory/capture_summary.csv); `entries`, `header_bytes`, `frame_bytes`, `frames`, `label`. Manifest: [results/E02/20261011T175659Z-confirmatory/manifest.json](../results/E02/20261011T175659Z-confirmatory/manifest.json). | Other protocols are not measured in those captures; input-capture hashes are in the manifest. |
| Visited improves node-profile point PDR and blackholing relative to continue/CRH-16 | [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); `condition=node-B`, matched shell/scheme; `pdr_mean`, `blackhole_mean`. Manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). | Blackhole conditions on realised outages; point PDR improvement is not adjusted significance. |
| C5 blackhole improvement against continue is adjusted significant; PDR improvement is not | [results/E04/20261011T185503Z-collected/paired_contrasts.csv](../results/E04/20261011T185503Z-collected/paired_contrasts.csv); `const=C5, condition=node-B, primary=greedy_visited, comparator=continue`; `adjusted_p`. Manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). | Use respective frozen endpoint families, not marginal CI overlap. |
| Visited can have infinite tails while LS-H has finite tails | [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); `condition=node-B`; `effective_p99_mean`, `infinite_tail_runs`, matched `greedy_visited` and `ls_h`. Manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). | Losses are not discarded to obtain a finite latency. |
| No recorded material E4 policy loss is not proof of noninferiority | [results/E04/20261011T185503Z-collected/paired_contrasts.csv](../results/E04/20261011T185503Z-collected/paired_contrasts.csv); All `material_loss=False`; undefined infinite-latency contrasts preserve `reason` and paired categories. Manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). | The material-loss rule is a joint effect/significance rule, not an equivalence test. |
| Visited reduces E5 stuck losses; Grid adds no established reduction | [results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv](../results/E05/20261011T185503Z-confirmatory/paired_contrasts.csv); `endpoint=stuck_rate`; `mean_diff`, bounds and `adjusted_p`, both fixed comparisons and shells. Manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). | C5 Grid point disadvantage; C2 tie; no universal policy improvement. |
| Continue wins C5 intervention completion and drop sacrifices completion | [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); `condition=trigger, const=C5`; `triggered_pdr_mean` by scheme. Manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). | A checker intervention on a healthy planned route is not a service-fault experiment. |
| Some stretch/hop costs are undefined and must remain unavailable | [results/E05/20261011T185503Z-confirmatory/summary.csv](../results/E05/20261011T185503Z-confirmatory/summary.csv); `triggered_stretch_mean_mean`, `triggered_extra_hops_mean_mean`; blank cells. Manifest: [results/E05/20261011T185503Z-confirmatory/manifest.json](../results/E05/20261011T185503Z-confirmatory/manifest.json). | No imputation or delivered-only all-packet claim. |
| Exact/tolerance stretch diagnostics are not raw-ratio clamping | [results/E04/20261011T185503Z-collected/summary.csv](../results/E04/20261011T185503Z-collected/summary.csv); `stretch_violations`, `stretch_min_exact`, `stretch_min_adjusted`, `stretch_min_raw`, `stretch_outside_graph`. Manifest: [results/E04/20261011T185503Z-collected/manifest.json](../results/E04/20261011T185503Z-collected/manifest.json). | Also checked in E5 summary; paths outside the send-time graph have separate coverage. |
| E16 passes every recorded stochastic equivalence endpoint | [results/E16/20261011T194240Z-confirmatory/summary.csv](../results/E16/20261011T194240Z-confirmatory/summary.csv); All rows `complete=True`, `equivalent=True`; `undefined_runs`, `infinite_runs`, both conditions and shells. Manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). | Paired replay scope only; not independent-resampling validation. |
| E16 per-packet comparison records agree, including deterministic replay | [results/E16/20261011T194240Z-confirmatory/comparisons.json](../results/E16/20261011T194240Z-confirmatory/comparisons.json); Every comparison: `violations`, `mismatched_packets`, `max_abs_time_error_ns`; deterministic gate recorded in `verdict.json`. Manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). | Qualitative implementation-validity evidence; no JSON-derived numerical results table in the report. |
| E16 scope excludes background, processing jitter and alternative fallback | [results/E16/20261011T194240Z-confirmatory/producer-manifests.jsonl.gz](../results/E16/20261011T194240Z-confirmatory/producer-manifests.jsonl.gz); Recorded producer engine configs and commands; scope also stated in manifested `REPORT.md`. Manifest: [results/E16/20261011T194240Z-confirmatory/manifest.json](../results/E16/20261011T194240Z-confirmatory/manifest.json). | Shared explicit-send randomness; not coverage of all engine features. |

## Design, methods, labels and literature claims

Non-empirical statements are not presented as results. They have direct contract/code
sources as well as the corresponding manifested implementation evidence:

| Claim class | Direct source and result corroboration | Boundary |
| --- | --- | --- |
| Header layout, cumulative deadlines, ordering, equality, rounding, saturation, serial arithmetic, source insertion | `spec/tcrh-v1.md`, `spec/golden/`; E0 `summary.csv` and `manifest.json` above. | Protocol definitions, not measurements or a new standardized RFC. |
| Queue and fault behavior, common engine, twin checks, event detection, censoring, blackhole, stretch and cost | `docs/sim-config.md`, `docs/baselines.md`, `sim/chronoroute/eval/`; E1/E4/E5 summaries, per-run records and manifests above. | Definition/model claims; no operator behavior inferred. |
| More sensitive deadline rules trade detection against false flags | E1 `campaign_roc.csv`, `operating_points.json`, `summary.csv` and the E1 manifest above. | Registered sensitivity sweep, not an operating point selected after confirmation. |
| Fluid background and the added-link-delay mechanism | `docs/sim-config.md`, `experiments/PREREG.md`; E1 `run_metrics.csv`, `inventory.csv`, producer records in `inputs/`, and its manifest above. | Added delay does not hold the transmitter busy and can permit overtaking; it is not a physical rate-cut model. |
| Frozen hypotheses, multiplicity, populations, exclusions, city blocking, run-level sampling | `experiments/PREREG.md` at the hash recorded in each result manifest; E0 manifest `config.pairs`, E1 `inventory.csv`, E4/E5 `inventory.csv`, E16 `inventory.csv`. | Registered design, not a powered claim for every city. |
| REAL/DERIVED/MODELLED labels and synthetic-position exception | `sim/chronoroute/labels.py`, frozen PREREG; each result `manifest.json` `labels` and `extra.synthetic_positions`. | REAL code/physics convention is not position-accuracy or network telemetry validation. |
| Starlink does not use T-CRH; operational routing and topology UNKNOWN | `README.md`, `sim/chronoroute/labels.py`; all named manifests identify project inputs/models. | Scope boundary, not an inference from packet simulations. |
| Browser parity, ns-3 wire handling and Wireshark extraction | E0 `summary.csv`, E16 `comparisons.json`, matching manifests; `web/tests/`, `sim/tests/`, `ns3/contrib/chronoroute/`. | Correctness under the tested inputs, not hardware deployment. |
| Website requires a manifested CSV, exact downloads and no unavailable-value clipping | `web/src/lib/experiments/`, `web/tests/experiments.test.ts`; the above result summaries/manifests are its inputs. | Implementation contract checked by build/tests, not an empirical performance result. |
| Producer/collector provenance and local raw-cache limitation | Each `manifest.json`; E1 `inputs/`, E4/E5/E16 `producer-manifests.jsonl.gz`. | Clean hashes preserve recorded provenance, not raw-trace availability or external realism. |
| RFC, Hypatia and STARGLIDER background, including CRH Experimental status | Primary texts linked in report references; original occurrences are identified beside each citation. | Verified bibliographic/conceptual evidence, not numerical experiment evidence. |
| CGREB, SRTSN paper/RFC, CRH-20, gray-failure paper, IOAM document and IETF TVR document | Names in `docs/NEXT_STEPS.md`; no unique verified entry in the repository. | UNVERIFIED as a specific allowed citation; SRTSN has an identified Internet-Draft outside the permitted set. No invented paper or technical/performance/novelty claim. |
| Deployment, security, synchronization and external validity remain unestablished | Normative spec and `docs/baselines.md` limitations; scoped E0/E16 evidence and MODELLED manifest labels. | Absence of evidence, not measured failure or a claim that deployment is impossible. |

The narrative interpretations in the abstract, discussion and conclusion are bounded by
these rows. Representative report tables do not replace the full registered grid, all
point disadvantages or the unavailable contrasts in their cited CSVs.

"""Keep the report's displayed quantities tied to clean, hashed result artifacts."""
import csv
import hashlib
import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def test_report_quantities_match_manifested_sources():
    report = (ROOT / "docs/report/README.md").read_text()
    ledger = json.loads((ROOT / "docs/report/claims.json").read_text())
    claims = (ROOT / "docs/claims.md").read_text()
    links = re.findall(r"\[([^\[\]\n]+)\]\(\.\./claims\.md#(q-[a-z0-9-]+)\)", report)
    assert links, "The report must contain independently checkable quantities"
    assert set(ledger) == {key for _, key in links}
    for key, item in ledger.items():
        source = ROOT / item["source"]
        assert source.is_relative_to(ROOT / "results")
        manifest_path = ROOT / item["manifest"]
        manifest = json.loads(manifest_path.read_text())
        assert manifest["dirty"] is False
        assert re.fullmatch(r"[a-f0-9]{40}", manifest["git_sha"])
        if source != manifest_path:
            output = [o for o in manifest["outputs"] if o["path"] == source.relative_to(manifest_path.parent).as_posix()]
            assert len(output) == 1, key
            data = source.read_bytes()
            assert hashlib.sha256(data).hexdigest() == output[0]["sha256"], key
            assert len(data) == output[0]["size_bytes"], key
        if "selector" in item:
            with source.open(newline="") as handle:
                rows = [r for r in csv.DictReader(handle) if all(r[k] == v for k, v in item["selector"].items())]
            assert len(rows) == 1, (key, item["selector"])
            value = rows[0][item["column"]]
        else:
            value = json.loads(source.read_text())
            for part in item["pointer"]:
                value = value[part]
        if item["format"] == "raw":
            expected = str(value)
        else:
            expected = format(float(value), item["format"])
        assert item["display"] == expected, key
        assert {display for display, linked_key in links if linked_key == key} == {expected}, key
        assert f'<a id="{key}"></a>' in claims
        assert f'**{key}: {expected} — {item["label"]}.**' in claims
        assert item["source"] in claims
        assert item["label"] in {"REAL", "DERIVED", "MODELLED"}


def test_report_has_no_unledgered_numeric_measurements():
    report = (ROOT / "docs/report/README.md").read_text().split("## References")[0]
    report = re.sub(r"\[[^\[\]\n]+\]\(\.\./claims\.md#q-[a-z0-9-]+\)", "QUANTITY", report)
    report = re.sub(r"\[([^\[\]]+)\]\([^\)]+\)", r"\1", report)
    report = re.sub(r"`[^`]+`", "IDENTIFIER", report)
    report = re.sub(r"\[(?:R|W)\d+\]", "REFERENCE", report)
    report = re.sub(r"\b(?:IPv6|SRv6|ns-3|C[25]|E(?:0|1|2|4|5|16)|E2E|crh16|p(?:50|99)|CRH-(?:16|20|32)|SGP4|Grid-4)\b", "IDENTIFIER", report)
    assert not re.search(r"\d", report), "Link all numeric quantities to the claims ledger"


@pytest.mark.parametrize("section", [
    "Abstract", "I. Introduction", "II. Background", "III. Design",
    "IV. Implementation", "V. Methodology", "VI. Results", "VII. Discussion",
    "VIII. Limitations", "IX. Related Work", "X. Conclusion", "References",
])
def test_report_contains_required_sections(section):
    assert f"## {section}" in (ROOT / "docs/report/README.md").read_text()


def test_report_distinguishes_model_scope_and_unverified_literature():
    report = (ROOT / "docs/report/README.md").read_text()
    for label in ("REAL", "DERIVED", "MODELLED", "UNKNOWN"):
        assert f"| {label} |" in report
    assert "Starlink does not use T-CRH" in report
    assert "UNVERIFIED" in report
    for name in ("CGREB", "SRTSN", "CRH-20", "STARGLIDER", "IOAM", "TVR"):
        assert name in report
    assert "infinite" in report and "Holm" in report


def test_report_aggregate_verdicts_include_all_registered_cells():
    # These assertions protect the narrative, beyond checking the copied table cells.
    releases = {
        "E00": "20261011T100448Z",
        "E01": "20261011T154940Z-confirmatory-resumed",
        "E04": "20261011T185503Z-collected",
        "E05": "20261011T185503Z-confirmatory",
        "E16": "20261011T194240Z-confirmatory",
    }
    summaries = {}
    for experiment, run in releases.items():
        with (ROOT / "results" / experiment / run / "summary.csv").open(newline="") as handle:
            summaries[experiment] = list(csv.DictReader(handle))
    assert all(int(r["violations"]) == 0 for r in summaries["E00"])
    selected = [r for r in summaries["E01"] if r["scheme"] == "chronoroute" and r["selected"] == "True" and r["k"] == "2"]
    assert selected and all(float(r["fpr"]) <= .01 for r in selected)
    for condition in ("rate-1-middle", "delay-0-middle", "arq-0-middle"):
        rows = [r for r in summaries["E01"] if r["condition"] == condition]
        assert rows and all(not r["tp"] or int(r["tp"]) == 0 for r in rows)
        assert all(not r["event_mean"] or float(r["event_mean"]) == 0 for r in rows)
    for experiment in ("E04", "E05"):
        with (ROOT / "results" / experiment / releases[experiment] / "paired_contrasts.csv").open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert all(r["material_loss"] == "False" for r in rows)
        if experiment == "E05":
            visited = [r for r in rows if r["endpoint"] == "stuck_rate" and r["primary"] == "greedy_visited"]
            grid = [r for r in rows if r["endpoint"] == "stuck_rate" and r["primary"] == "grid_detour"]
            assert visited and all(float(r["mean_diff"]) < 0 and float(r["adjusted_p"]) < .05 for r in visited)
            assert grid and all(float(r["mean_diff"]) >= 0 for r in grid)
    assert all(r["complete"] == "True" and r["equivalent"] == "True" for r in summaries["E16"])
    assert {(r["const"], r["condition"], r["endpoint"]) for r in summaries["E16"]} == {
        (const, condition, endpoint) for const in ("C5", "C2")
        for condition in ("none", "fault") for endpoint in ("pdr", "fpr", "p50", "p99")
    }


def test_report_citations_are_resolved_and_already_named_in_repository_docs():
    report = (ROOT / "docs/report/README.md").read_text()
    body, references = report.split("## References", 1)
    assert set(re.findall(r"\[R\d+\]", body)) == set(re.findall(r"^\[R\d+\]", references, re.M))
    existing = "\n".join((ROOT / name).read_text() for name in (
        "README.md", "spec/tcrh-v1.md", "docs/baselines.md", "docs/NEXT_STEPS.md",
    ))
    for number in re.findall(r"RFC (\d+)", references):
        assert f"RFC {number}" in existing
    for system in ("Hypatia", "STARGLIDER"):
        assert system in existing and system in references
    assert "CRH RFC is Experimental" in body

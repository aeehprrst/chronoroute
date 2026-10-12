"""Keep the report's displayed quantities tied to clean, hashed result artifacts.

Set CHRONOROUTE_REPORT_ROOT to check a copy of the repository (for example a scratch copy
of docs/ with links to results/); it defaults to this checkout.
"""
import csv
import functools
import hashlib
import json
import os
import re
from pathlib import Path

import pytest


ROOT = Path(os.environ.get("CHRONOROUTE_REPORT_ROOT") or Path(__file__).resolve().parents[2])
LINK = re.compile(r"\[([^\[\]\n]+)\]\(\.\./claims\.md#(q-[a-z0-9-]+)\)")


def _report():
    return (ROOT / "docs/report/README.md").read_text()


def _ledger():
    return json.loads((ROOT / "docs/report/claims.json").read_text())


@functools.lru_cache(maxsize=None)
def _csv_rows(path):
    with Path(path).open(newline="") as handle:
        return tuple(csv.DictReader(handle))


def _csv_row(item):
    rows = [r for r in _csv_rows(str(ROOT / item["source"])) if all(r[k] == v for k, v in item["selector"].items())]
    assert len(rows) == 1, (item["selector"], len(rows))
    return rows[0]


def test_report_quantities_match_manifested_sources():
    report = _report()
    ledger = _ledger()
    claims = (ROOT / "docs/claims.md").read_text()
    links = LINK.findall(report)
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
        row = None
        if "selector" in item:
            row = _csv_row(item)
            value = row[item["column"]]
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
        if row is not None and row.get("label"):
            # A CSV row that carries its own evidence label decides the ledger label.
            assert item["label"] == row["label"], key
        if item.get("column") in ("p", "adjusted_p", "p_lower", "p_upper"):
            # A p-value recorded as zero is below the numerical resolution; never print it.
            assert float(value) > 0, key


def test_report_has_no_unledgered_numeric_measurements():
    report = _report().split("## References")[0]
    report = re.sub(r"\[[^\[\]\n]+\]\(\.\./claims\.md#q-[a-z0-9-]+\)", "QUANTITY", report)
    report = re.sub(r"\[([^\[\]]+)\]\([^\)]+\)", r"\1", report)
    report = re.sub(r"`[^`]+`", "IDENTIFIER", report)
    report = re.sub(r"\[(?:R|W)\d+\]", "REFERENCE", report)
    report = re.sub(r"\b(?:IPv6|SRv6|ns-3|C[25]|E(?:0|1|2|4|5|16)|E2E|crh16|p(?:50|99)|CRH-(?:16|20|32)|SGP4|Grid-4)\b", "IDENTIFIER", report)
    assert not re.search(r"\d", report), "Link all numeric quantities to the claims ledger"


# Backtick spans may hold identifiers only. A span containing a digit must look like a path
# or file name, a commit id, a registered condition id or a field name, never a bare number.
IDENTIFIER_SPANS = [
    re.compile(r"[\w.+-]*/[\w./+-]*"),                                     # repository paths
    re.compile(r"[\w.-]+\.(?:csv|json|jsonl|md|py|gz|pcap|png|tsv|mjs)(?:\.gz)?"),  # file names
    re.compile(r"(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}"),     # commit ids
    re.compile(r"(?:rate|delay|arq)-\d+(?:\.\d+)?-(?:first|middle|last)"),  # condition ids
    re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*"),                          # field names
]


def test_backticks_hold_identifiers_not_numbers():
    body = _report().split("## References")[0]
    bad = []
    for span in re.findall(r"`([^`]+)`", body):
        if re.search(r"\d", span) and not any(p.fullmatch(span) for p in IDENTIFIER_SPANS):
            bad.append(span)
    assert not bad, f"numbers hidden in backticks: {bad}"


# ---------------------------------------------------------------------------------------
# Table cells: a correct value must also sit in the right row, column and label.

IDENT_COLUMNS = [  # header (lower case) -> CSV field(s) the row cell must equal
    (re.compile(r"(shell|constellation|population)"), ("const", "constellation")),
    (re.compile(r"check"), ("check",)),
    (re.compile(r"(scheme|policy)"), ("scheme",)),
    (re.compile(r"condition identifier"), ("condition",)),
    (re.compile(r"comparator"), ("comparator",)),
    (re.compile(r"comparison"), ("primary minus comparator",)),
    (re.compile(r"endpoint( identifier)?"), ("endpoint",)),
    (re.compile(r"label"), ("label",)),
    (re.compile(r"unit"), ("unit",)),
    (re.compile(r"encoded entries"), ("entries",)),
]
VALUE_COLUMNS = [  # header pattern (searched, first match wins) -> allowed CSV columns
    (r"restricted delay", {"restricted_mean_s", "restricted_boot_lo", "restricted_boot_hi"}),
    (r"tail-failure", {"tail_failure_mean_diff"}),
    (r"^paired t ci$", {"lo", "hi", "tail_failure_lo", "tail_failure_hi"}),
    (r"^run-bootstrap ci$", {"bootstrap_lo", "bootstrap_hi"}),
    (r"stuck-rate difference", {"mean_diff", "lo", "hi"}),
    (r"minus comparator", {"mean_diff"}),
    (r"holm", {"adjusted_p"}),
    (r"pooled clean fpr", {"fpr", "lo", "hi"}),
    (r"detection", {"event_mean", "event_lo", "event_hi"}),
    (r"attributed packets", {"tp"}),
    (r"^pdr", {"pdr_mean", "pdr_lo", "pdr_hi"}),
    (r"^blackhole", {"blackhole_mean", "blackhole_boot_lo", "blackhole_boot_hi"}),
    (r"counted blackhole losses", {"blackhole_losses"}),
    (r"outage-run n", {"blackhole_n"}),
    (r"effective tail", {"effective_p99_mean", "effective_p99_lo", "effective_p99_hi"}),
    (r"infinite-tail runs", {"infinite_tail_runs"}),
    (r"packets sent", {"sent"}),
    (r"packets delivered", {"delivered"}),
    (r"censored ttm", {"ttm_censored"}),
    (r"realised outages", {"outages"}),
    (r"triggered completion", {"triggered_pdr_mean", "triggered_pdr_lo", "triggered_pdr_hi"}),
    (r"stuck/loop rate", {"stuck_rate_mean", "stuck_rate_lo", "stuck_rate_hi"}),
    (r"^checked$", {"checked"}),
    (r"^violations$", {"violations"}),
    (r"^worst", {"worst"}),
    (r"^limit$", {"limit"}),
    (r"encoded entries", {"entries"}),
    (r"bytes", {"added_bytes"}),
    (r"paired difference or latency ratio", {"estimate"}),
    (r"reporting ci", {"lo95", "hi95"}),
    (r"equivalence bounds", {"lower_bound", "upper_bound"}),
    (r"paired runs", {"n"}),
]
HEADER_VALUES = {"T-CRH": ("protocol", "tcrh"), "CRH-16": ("protocol", "crh16"),
                 "CRH-32": ("protocol", "crh32"), "SRv6 SRH": ("protocol", "srh"),
                 "C5": ("const", "C5"), "C2": ("const", "C2")}
# Selector fields that identify a row; each must be shown by the row, its column header or
# the paragraph introducing the table.
IDENTIFYING = ("const", "constellation", "check", "scheme", "condition", "comparator",
               "primary", "endpoint", "protocol", "entries", "mode")


def _plain(cell):
    return re.sub(r"[`*]", "", cell).strip()


def _role(column):
    if column in ("lo", "lo95", "lo90", "lower_bound") or column.endswith("_lo"):
        return "lo"
    if column in ("hi", "hi95", "hi90", "upper_bound") or column.endswith("_hi"):
        return "hi"
    return "estimate"


def _tables(text):
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and re.fullmatch(r"\|( *-+ *\|)+", lines[i + 1].strip()):
            start = i
            caption = []
            j = start - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            while j >= 0 and lines[j].strip() and not lines[j].startswith(("|", "#")):
                caption.insert(0, lines[j])
                j -= 1
            header = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            yield " ".join(caption), header, rows
        else:
            i += 1


def _table_problems(report, ledger):
    problems = []
    body = report.split("## References")[0]
    for caption, header, rows in _tables(body):
        if not any(LINK.search(cell) for row in rows for cell in row):
            continue
        ident = {}
        values = {}
        for index, name in enumerate(header):
            low = _plain(name).lower()
            for pattern, fields in IDENT_COLUMNS:
                if pattern.fullmatch(low):
                    ident[index] = fields
            for pattern, allowed in VALUE_COLUMNS:
                if re.search(pattern, low):
                    values[index] = allowed
                    break
        for row in rows:
            if len(row) != len(header):
                problems.append(f"malformed row {row}")
                continue
            for index, cell in enumerate(row):
                links = LINK.findall(cell)
                if not links:
                    continue
                if index not in values:
                    problems.append(f"no column rule for header {header[index]!r}")
                    continue
                roles = []
                for display, key in links:
                    item = ledger.get(key)
                    if item is None or "selector" not in item:
                        problems.append(f"{key}: table cells must cite CSV rows")
                        continue
                    if item["column"] not in values[index]:
                        problems.append(f"{key}: column {item['column']} under header {header[index]!r}")
                    roles.append(_role(item["column"]))
                    csv_row = _csv_row(item)
                    covered = set()
                    for col, fields in ident.items():
                        shown_links = LINK.findall(row[col])
                        shown = shown_links[0][0] if shown_links else _plain(row[col])
                        if fields == ("primary minus comparator",):
                            parts = [p.strip() for p in shown.split(" minus ")]
                            for field, part in zip(("primary", "comparator"), parts):
                                covered.add(field)
                                if csv_row.get(field) != part:
                                    problems.append(f"{key}: row says {field}={part}, CSV has {csv_row.get(field)}")
                            continue
                        present = [f for f in fields if f in csv_row]
                        if not present:
                            problems.append(f"{key}: CSV has no field for column {header[col]!r}")
                            continue
                        covered.update(present)
                        if csv_row[present[0]] != shown:
                            problems.append(f"{key}: row says {present[0]}={shown}, CSV has {csv_row[present[0]]}")
                    head = _plain(header[index])
                    for token, (field, wanted) in HEADER_VALUES.items():
                        if re.search(rf"(?<![\w-]){re.escape(token)}(?![\w-])", head):
                            covered.add(field)
                            if csv_row.get(field) != wanted:
                                problems.append(f"{key}: header {head!r} wants {field}={wanted}, CSV has {csv_row.get(field)}")
                    for token in re.findall(r"`([^`]+)`", header[index]):
                        if token not in {csv_row.get(f) for f in IDENTIFYING}:
                            problems.append(f"{key}: header token {token} not in its CSV row")
                        covered.update(f for f in IDENTIFYING if csv_row.get(f) == token)
                    for field, wanted in item["selector"].items():
                        if field in IDENTIFYING and field not in covered and wanted not in caption:
                            problems.append(f"{key}: {field}={wanted} is not shown by its row, column or caption")
                expected_roles = {1: None, 2: ["lo", "hi"], 3: ["estimate", "lo", "hi"]}.get(len(roles), "bad")
                if expected_roles == "bad" or (expected_roles and roles != expected_roles):
                    problems.append(f"cell {cell!r}: interval parts out of order {roles}")
    return problems


def test_report_table_cells_match_their_rows_columns_and_labels():
    problems = _table_problems(_report(), _ledger())
    assert not problems, "\n".join(problems[:20])


@pytest.mark.parametrize("section", [
    "Abstract", "I. Introduction", "II. Background", "III. Design",
    "IV. Implementation", "V. Methodology", "VI. Results", "VII. Discussion",
    "VIII. Limitations", "IX. Related Work", "X. Conclusion", "References",
])
def test_report_contains_required_sections(section):
    assert f"## {section}" in _report()


def test_report_distinguishes_model_scope_and_unverified_literature():
    report = _report()
    for label in ("REAL", "DERIVED", "MODELLED", "UNKNOWN"):
        assert f"| {label} |" in report
    assert "Starlink does not use T-CRH" in report
    assert "UNVERIFIED" in report
    for name in ("CGREB", "SRTSN", "CRH-20", "STARGLIDER", "IOAM", "TVR"):
        assert name in report
    assert "infinite" in report and "Holm" in report
    assert "LS-D comparator flaw" in report
    assert "boundary middle rate cut" not in report.lower()


RELEASES = {
    "E00": "20261011T214507Z",
    "E01": "20261011T154940Z-confirmatory-resumed",
    "E02": "20261011T214624Z-confirmatory",
    "E04": "20261011T185503Z-collected",
    "E05": "20261011T185503Z-confirmatory",
    "E16": "20261011T194240Z-confirmatory",
}


def _rows(experiment, name):
    with (ROOT / "results" / experiment / RELEASES[experiment] / name).open(newline="") as handle:
        return list(csv.DictReader(handle))


def test_report_cites_only_the_reviewed_releases():
    ledger = _ledger()
    for item in ledger.values():
        experiment = item["source"].split("/")[1]
        assert item["source"].startswith(f"results/{experiment}/{RELEASES[experiment]}/"), item["source"]
    assert "20261011T175659Z" not in _report()


def test_report_aggregate_verdicts_include_all_registered_cells():
    # These assertions protect the narrative, beyond checking the copied table cells.
    e0 = _rows("E00", "summary.csv")
    assert all(int(r["violations"]) == 0 for r in e0)
    polar = [r for r in e0 if r["check"] == "isl_polar_cutoff"]
    assert polar and all(float(r["worst"]) < float(r["limit"]) - 10 for r in polar)  # cannot fail
    e1 = _rows("E01", "summary.csv")
    selected = [r for r in e1 if r["scheme"] == "chronoroute" and r["selected"] == "True" and r["k"] == "2"]
    assert selected and all(float(r["fpr"]) <= .01 for r in selected)
    for condition in ("rate-1-middle", "delay-0-middle", "arq-0-middle"):
        rows = [r for r in e1 if r["condition"] == condition]
        assert rows and all(not r["tp"] or int(r["tp"]) == 0 for r in rows)
        assert all(not r["event_mean"] or float(r["event_mean"]) == 0 for r in rows)
    sel = {(r["const"], r["condition"]): float(r["event_mean"]) for r in selected}
    for const in ("C5", "C2"):
        assert sel[(const, "rate-0.2-middle")] == 1          # strong cut always detected
        assert sel[(const, "rate-0.3-middle")] == 0          # nominal cut missed mid-path
        assert sel[(const, "rate-0.3-last")] == 0
    assert all(v == 0 for (c, cond), v in sel.items() if c == "C2" and cond.startswith("delay-"))
    assert all(v < .1 for (c, cond), v in sel.items() if cond.startswith("delay-"))
    for row in e1:  # LS-H and CRH-16 detect nothing: their losses are by construction
        if row["scheme"] in ("ls_h", "crh16") and row["k"] == "2" and row["event_mean"]:
            assert float(row["event_mean"]) == 0
    contrasts = [r for r in _rows("E01", "paired_contrasts.csv") if r["endpoint"] == "detected"]
    significant = [r for r in contrasts if float(r["adjusted_p"]) < .05]
    assert not [r for r in significant if r["comparator"] == "lq" and float(r["mean_diff"]) > 0]
    assert not [r for r in significant if r["comparator"] in ("e2e", "ls_h", "crh16") and float(r["mean_diff"]) < 0]
    assert all(r["condition"].startswith("rate-0.3-") for r in significant
               if r["comparator"] == "lq" and r["condition"].startswith("rate-"))
    verdict = json.loads((ROOT / "results/E01" / RELEASES["E01"] / "verdict.json").read_text())
    assert {m["comparator"] for m in verdict["material_losses"]} == {"lq", "ls_d"}
    assert {m["comparator"] for m in verdict["point_disadvantages"]} <= {"lq", "ls_d"}
    e2 = json.loads((ROOT / "results/E02" / RELEASES["E02"] / "verdict.json").read_text())
    assert e2["crh32_smaller_entries"] == [1, 2, 3, 5, 7]
    assert e2["crh32_ties"] == [4, 6, 8, 9, 10, 11, 13, 15]
    assert e2["crh32_larger_entries"] == [12, 14] + list(range(16, 41))
    assert e2["tcrh_more_than_crh16"] and e2["tcrh_less_than_srh"]
    for experiment in ("E04", "E05"):
        rows = _rows(experiment, "paired_contrasts.csv")
        assert all(r["material_loss"] == "False" for r in rows)
        if experiment == "E04":
            tails = {(r["const"], r["condition"], r["comparator"]): r for r in rows if r["endpoint"] == "effective_p99_s"}
            for profile in ("link-B", "node-A", "node-B"):
                assert float(tails[("C5", profile, "ls_h")]["tail_failure_lo"]) > 0
            assert all(float(r["tail_failure_hi"]) < 0 for (c, p, comp), r in tails.items() if comp == "snap")
            assert all(not r["mean_diff"] for r in tails.values())  # undefined, so no material-loss ratio
        if experiment == "E05":
            visited = [r for r in rows if r["endpoint"] == "stuck_rate" and r["primary"] == "greedy_visited"]
            grid = [r for r in rows if r["endpoint"] == "stuck_rate" and r["primary"] == "grid_detour"]
            assert visited and all(float(r["mean_diff"]) < 0 and float(r["adjusted_p"]) < .05 for r in visited)
            assert grid and all(float(r["mean_diff"]) >= 0 for r in grid)
    e4 = _rows("E04", "summary.csv")
    visited = [r for r in e4 if r["scheme"] == "greedy_visited" and int(r["outages"]) > 0]
    assert visited and all(r["ttm_censored"] == r["outages"] for r in visited)  # TTM censored by construction
    c2b = {r["scheme"]: r for r in e4 if r["const"] == "C2" and r["condition"] == "link-B"}
    assert c2b["greedy_visited"]["blackhole_losses"] == "0"
    assert int(c2b["greedy_visited"]["delivered"]) < int(c2b["ls_h"]["delivered"])
    e16 = _rows("E16", "summary.csv")
    assert all(r["complete"] == "True" and r["equivalent"] == "True" for r in e16)
    assert {(r["const"], r["condition"], r["endpoint"]) for r in e16} == {
        (const, condition, endpoint) for const in ("C5", "C2")
        for condition in ("none", "fault") for endpoint in ("pdr", "fpr", "p50", "p99")
    }
    assert all(r["lo90"] == r["hi90"] == r["estimate"] for r in e16)  # degenerate: zero variance
    runs = _rows("E16", "per_run.csv")
    assert runs and all(r["sent"] == r["delivered"] and r["losses_json"] == "{}" and float(r["fpr"]) == 0 for r in runs)


# Every reference must be one of these primary sources, cited with its real title.
VERIFIED_REFERENCES = {
    "RFC 8200": "Internet Protocol, Version 6 (IPv6) Specification",
    "RFC 9631": "The IPv6 Compact Routing Header (CRH)",
    "RFC 8754": "IPv6 Segment Routing Header (SRH)",
    "RFC 4727": "Experimental Values in IPv4, IPv6, ICMPv4, ICMPv6, UDP, and TCP Headers",
    "RFC 7471": "OSPF Traffic Engineering (TE) Metric Extensions",
    "RFC 8762": "Simple Two-Way Active Measurement Protocol",
    "RFC 9197": "Data Fields for In Situ Operations, Administration, and Maintenance (IOAM)",
    "RFC 9657": "Time-Variant Routing (TVR) Use Cases",
    "draft-pb-6man-deterministic-crh-00": "Deterministic Routing Header",
    "draft-stein-srtsn-01": "Segment Routed Time Sensitive Networking",
    "10.1145/3102980.3103005": "Gray Failure: The Achilles' Heel of Cloud-Scale Systems",
    "arXiv:2401.11490": "Reliable Low-Delay Routing In Space with",
    "imc2020-hypatia": "Exploring the",
}


def test_report_citations_are_resolved_and_verified():
    report = _report()
    body, references = report.split("## References", 1)
    assert set(re.findall(r"\[R\d+\]", body)) == set(re.findall(r"^\[R\d+\]", references, re.M))
    entries = re.split(r"\n(?=\[R\d+\] )", references.strip())[1:]
    assert entries
    for entry in entries:
        text = " ".join(entry.split())
        found = [ident for ident in VERIFIED_REFERENCES if ident in text]
        assert len(found) == 1, entry
        assert VERIFIED_REFERENCES[found[0]] in text, entry
    for number in re.findall(r"RFC (\d+)", references):
        assert f"RFC {number}" in VERIFIED_REFERENCES
    existing = "\n".join((ROOT / name).read_text() for name in (
        "README.md", "spec/tcrh-v1.md", "docs/baselines.md", "web/src/pages/methodology.astro",
    ))
    for system in ("Hypatia", "STARGLIDER"):
        assert system in existing and system in references
    assert "CRH RFC is Experimental" in body

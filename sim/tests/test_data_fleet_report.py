"""Tests for `cr fleet report` (chronoroute.data.fleet_report) and the `cr` sub-command framework."""

import json
import types
from pathlib import Path

import pytest

from chronoroute import cli, provenance
from chronoroute.data import fleet_figures, snapshot

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"


@pytest.fixture(scope="module")
def report_run(tmp_path_factory):
    out = tmp_path_factory.mktemp("fleet")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(["fleet", "report", str(PINNED), "--out", str(out)])
    return code, buf.getvalue(), out


def test_report_runs_and_writes_json_with_a_valid_manifest(report_run):
    code, text, out = report_run
    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == sorted(
        ["fleet_report.json", "manifest.json", "planes.json", *fleet_figures.FILES])
    for name in fleet_figures.FILES:
        assert (out / name).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", name
    manifest = provenance.validate_manifest(out)                 # schema + output hashes
    assert sorted(o["path"] for o in manifest["outputs"]) == sorted(
        ["fleet_report.json", "planes.json", *fleet_figures.FILES])
    assert manifest["tool"] == "cr fleet report"
    assert manifest["snapshot"]["id"] == "20261010T1358Z-celestrak"
    assert manifest["labels"]["shells_and_planes"] == "DERIVED"
    assert manifest["labels"]["orbital_elements"] == "REAL"
    # SGP4 positions: REAL physics + REAL code (master plan section 2, row 2), as in every other output
    assert manifest["labels"]["satellite_positions_sgp4"] == "REAL"
    assert manifest["seeds"] == []


def test_report_contents(report_run):
    _, _, out = report_run
    report = json.loads((out / "fleet_report.json").read_text())
    assert report["schema"] == "chronoroute.fleet-report/1"
    snap = report["snapshot"]
    assert snap["source"] == "CelesTrak SupGP" and snap["other_source"] == "CelesTrak GP"
    assert snap["fetched_utc"] == "2026-10-10T14:02:22Z"
    counts = report["counts"]
    assert counts["raw"] == counts["kept"] == 11_130
    assert counts["other_source"]["kept"] == 11_098 and counts["other_source"]["excluded"]["stale_epoch"] == 5
    assert report["six_digit_ids"]["count"] == 472 and report["six_digit_ids"]["max"] == 100_880
    age = report["epoch_age"]
    assert 3.0 < age["p50_h"] < 3.6                             # research: SupGP median 3.3 h
    assert age["epoch_max"] == "2026-10-10T12:06:42.000019Z"
    ids = [s["shell_id"] for s in report["shells"]]
    assert "53.2deg-463km" in ids and "dtc-53.2deg-360km" in ids
    status = counts["status"]
    assert sum(status.values()) == 11_130 and status["in_transit"] == report["in_transit"]["count"]
    # every satellite appears once in planes.json
    planes = json.loads((out / "planes.json").read_text())
    assert len(planes["satellites"]) == 11_130
    assert planes["label"].startswith("DERIVED")


def test_gp_vs_supgp_disagreement_matches_the_research_measurement(report_run):
    """06_research_live-data.md section 6 measured p50 5.4 km, p90 24.3 km, p95 37.0 km, p99 134 km
    (at 14:00:00Z). We propagate both to the SupGP fetch time, 14:02:22Z."""
    _, _, out = report_run
    cmp_ = json.loads((out / "fleet_report.json").read_text())["gp_vs_supgp"]
    assert cmp_["pairs"] == 11_098 and cmp_["failed"] == 0
    assert cmp_["supgp_only"] == 32 and cmp_["gp_only"] == 0
    d = cmp_["distance"]
    assert abs(d["p50_km"] - 5.4) < 0.2 and abs(d["p90_km"] - 24.3) < 0.5
    assert abs(d["p95_km"] - 37.0) < 1.0 and abs(d["p99_km"] - 134) < 3
    assert cmp_["along_track"]["p50_km"] <= d["p50_km"]
    assert "not a measured error" in cmp_["label"]


def test_printout_names_labels_and_key_numbers(report_run):
    _, text, _ = report_run
    assert "CelesTrak SupGP  [REAL]" in text
    assert "11,130 raw -> 11,130 kept" in text
    assert "6-digit ids  472" in text
    assert "Shells and planes [DERIVED, inferred]" in text
    # the acceptance counts depend on the altitude band: both band values are printed
    assert "altitude band +-10 km" in text and "+-5km" in text
    assert "97.3 deg: 1 deg: twin planes merged" in text


def test_figures_are_deterministic_and_drawn_from_the_json(report_run, tmp_path):
    """The figures are made from the report's own JSON: drawing them again from the written
    files (and the same distances) gives byte-identical PNGs."""
    _, _, out = report_run
    report = json.loads((out / "fleet_report.json").read_text())
    planes = json.loads((out / "planes.json").read_text())
    distances = [0.5 + 0.01 * i for i in range(1000)]
    for d in ("a", "b", "c"):
        (tmp_path / d).mkdir()
    a = fleet_figures.write_figures(tmp_path / "a", report, planes, distances)
    b = fleet_figures.write_figures(tmp_path / "b", report, planes, distances)
    assert [p.name for p in a] == list(fleet_figures.FILES)
    assert all(pa.read_bytes() == pb.read_bytes() for pa, pb in zip(a, b))
    # the three figures that need no distances are the ones the report run wrote
    for name in fleet_figures.FILES[:3]:
        assert (tmp_path / "a" / name).read_bytes() == (out / name).read_bytes(), name
    # without distances (a website snapshot has one source) the GP-SupGP figure is skipped
    assert [p.name for p in fleet_figures.write_figures(tmp_path / "c", report, planes, None)] == \
        list(fleet_figures.FILES[:3])


def test_band_sensitivity_is_reported(report_run):
    """The 70 deg / 476 km shell passes the +-2% check (reference 332) only with the 10 km band;
    the report must show both counts (data owner's deviation 1, review finding)."""
    _, text, out = report_run
    report = json.loads((out / "fleet_report.json").read_text())
    band = report["band_sensitivity"]
    assert (band["band_km"], band["alternative_band_km"]) == (10.0, 5.0)
    assert band["counts"]["53.2deg-463km"]["band"] >= band["counts"]["53.2deg-463km"]["alternative"]
    line = next(line for line in text.splitlines() if line.strip().startswith("70.0deg-476km"))
    sats, narrow = line.split()[4:6]
    assert (int(sats), int(narrow)) == (band["counts"]["70.0deg-476km"]["band"],
                                        band["counts"]["70.0deg-476km"]["alternative"])
    assert "GP vs SupGP disagreement [DERIVED; not an error measurement]" in text
    assert "dtc-53.2deg-360km" in text and "in transit" in text
    assert "SATCAT OPS_STATUS_CODE [REAL]" in text


def test_report_on_a_website_snapshot(tmp_path):
    fleet = snapshot.load_pinned(PINNED, "supgp")
    written = snapshot.write_web_snapshot(fleet, tmp_path / "web", pipeline="chronoroute-pipeline test")
    out = tmp_path / "out"
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        assert cli.main(["fleet", "report", str(written["snapshot_dir"]), "--out", str(out)]) == 0
    report = json.loads((out / "fleet_report.json").read_text())
    assert report["snapshot"]["layout"] == "web" and report["gp_vs_supgp"] is None
    assert report["counts"]["kept"] == 11_130
    assert provenance.validate_manifest(out)["snapshot"]["sha256_of"] == "omm.min.json"
    assert "not available" in buf.getvalue()


def test_gp_source_can_be_chosen(tmp_path):
    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["fleet", "report", str(PINNED), "--source", "gp", "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "fleet_report.json").read_text())
    assert report["snapshot"]["source"] == "CelesTrak GP" and report["counts"]["kept"] == 11_098


# ------------------------------------------------------------ CLI framework

def test_cr_without_a_command_prints_help(capsys):
    assert cli.main([]) == 2
    assert "<group>" in capsys.readouterr().out
    assert cli.main(["fleet"]) == 2
    assert "report" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["no-such-group"])


def test_other_owners_can_register_commands(monkeypatch, capsys):
    calls = []

    def register(registry):
        parser = registry.command("demo", "hello", help="say hello", func=lambda a: calls.append(a.who) or 0)
        parser.add_argument("who")

    module = types.ModuleType("demo_cmds")
    module.register = register
    broken = types.ModuleType("broken_cmds")

    def explode(registry):
        raise RuntimeError("boom")
    broken.register = explode
    monkeypatch.setitem(__import__("sys").modules, "demo_cmds", module)
    monkeypatch.setitem(__import__("sys").modules, "broken_cmds", broken)
    monkeypatch.setattr(cli, "COMMAND_MODULES", cli.COMMAND_MODULES + ("demo_cmds", "broken_cmds"))
    assert cli.main(["demo", "hello", "world"]) == 0
    assert calls == ["world"]
    assert "broken_cmds are unavailable (RuntimeError: boom)" in capsys.readouterr().err
    # a broken module does not take the other commands down with it
    parser, registry, failures = cli.build_parser()
    assert registry.group_parser("fleet") is not None and registry.group_parser("demo") is not None
    assert list(failures) == ["broken_cmds"]

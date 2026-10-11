"""Tests for chronoroute.export.web (`cr export web`): shells.json + isl_grid4.json
next to a website snapshot's omm.min.json (web/DATA_CONTRACT.md style)."""

import json
from pathlib import Path

import pytest

from chronoroute import cli, provenance
from chronoroute.data import snapshot
from chronoroute.export import web
from chronoroute.orbit import planes
from chronoroute.topo import isl_grid4

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    root = tmp_path_factory.mktemp("webdata")
    code = cli.main(["export", "web", str(PINNED), "--out-root", str(root),
                     "--snapshot-id", "20261010T1358Z-supgp"])
    assert code == 0
    return root / "snapshots" / "20261010T1358Z-supgp"


def test_snapshot_folder_still_satisfies_the_website_contract(exported):
    assert snapshot.check_web_snapshot(exported) == []
    assert (exported / web.SHELLS_FILE).is_file() and (exported / web.ISL_FILE).is_file()
    # the contract's own manifest.json is untouched; our provenance sits in a sub-folder
    assert json.loads((exported / "manifest.json").read_text())["schema"] == snapshot.WEB_SCHEMA
    m = provenance.validate_manifest(exported / web.PROVENANCE_DIR)
    assert sorted(o["path"] for o in m["outputs"]) == ["../isl_grid4.json", "../shells.json"]
    assert m["labels"] == web.LABELS


def test_files_are_byte_identical_on_rerun(exported):
    before = {f: (exported / f).read_bytes() for f in (web.SHELLS_FILE, web.ISL_FILE)}
    fleet = snapshot.load_web_snapshot(exported)
    web.export_web(fleet, exported, command=["pytest"])
    for f, data in before.items():
        assert (exported / f).read_bytes() == data, f


def test_shells_json_content(exported):
    doc = json.loads((exported / web.SHELLS_FILE).read_text())
    assert doc["schema"] == web.SHELLS_SCHEMA and doc["label"] == "DERIVED"
    assert doc["snapshot_id"] == "20261010T1358Z-supgp"
    assert doc["reference_utc"] == "2026-10-10T14:02:22Z"      # the HTTP Date of the SupGP file
    ids = [s["shell_id"] for s in doc["shells"]]
    assert "53.2deg-463km" in ids and "dtc-53.2deg-360km" in ids
    s463 = doc["shells"][ids.index("53.2deg-463km")]
    assert s463["n_planes"] == len(s463["planes"]) == 104
    assert sum(len(p) for p in s463["planes"]) + s463["off_grid"] == s463["count"]
    # six-digit NORAD ids appear as plain numbers
    every = [n for s in doc["shells"] for p in s["planes"] for n in p]
    assert any(n >= 100_000 for n in every) and all(isinstance(n, int) for n in every)
    assert len(every) == len(set(every))                          # a satellite is in one plane only
    assert set(doc["in_transit"]).isdisjoint(every)


def test_isl_json_pairs_equal_the_model(exported):
    doc = json.loads((exported / web.ISL_FILE).read_text())
    assert doc["schema"] == web.ISL_SCHEMA and doc["label"] == "MODELLED"
    assert doc["model"]["polar_cutoff_deg"] == 70.0 and doc["model"]["min_grazing_alt_km"] == 80.0
    assert doc["model"]["max_degree"] == 4 and doc["model"]["inter_shell_links"] is False
    fleet = snapshot.load_web_snapshot(exported)
    geo = planes.build_fleet_geometry(fleet.records, fleet.fetched_ns, satrecs=fleet.satrecs)
    for entry in doc["shells"]:
        pairs = isl_grid4.grid4_pairs(geo.shell(entry["shell_id"]), geo.reference_ns)
        want_intra = [[int(a), int(b)] for a, b, k in zip(pairs.a, pairs.b, pairs.kind) if k == isl_grid4.INTRA]
        want_cross = [[int(a), int(b)] for a, b, k in zip(pairs.a, pairs.b, pairs.kind) if k == isl_grid4.CROSS]
        assert entry["intra"] == want_intra and entry["cross"] == want_cross
        degree = {}
        for a, b in entry["intra"] + entry["cross"]:
            assert a < b
            degree[a] = degree.get(a, 0) + 1
            degree[b] = degree.get(b, 0) + 1
        assert max(degree.values()) <= 4


def test_pinned_input_needs_out_root(capsys):
    assert cli.main(["export", "web", str(PINNED)]) == 2

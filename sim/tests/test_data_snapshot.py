"""Tests for chronoroute.data.snapshot and pipeline/slim.py + validate.py: loading the pinned
download folder, and writing the WEBSITE DATA CONTRACT (web/DATA_CONTRACT.md) exactly.

The contract's rules are restated here as constants (this repository must not depend on
the website team's working tree). If the contract changes, change both.
"""

import importlib.util
import json
import shutil
from functools import cache
from pathlib import Path

import pytest

from chronoroute.data import omm, snapshot

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"

# --- web/DATA_CONTRACT.md, restated -----------------------------------------
CONTRACT_MANIFEST_KEYS = [   # the order the website's own converter writes
    "schema", "snapshot_id", "source", "source_url", "fetched_utc", "http_date", "count",
    "count_raw", "epoch_min", "epoch_median", "epoch_max", "max_epoch_age_days", "raw_file",
    "sha256_raw", "excluded", "sgp4_check", "attribution", "pipeline", "files"]
CONTRACT_REQUIRED = ["snapshot_id", "source", "source_url", "fetched_utc", "http_date", "count",
                     "epoch_min", "epoch_median", "epoch_max", "sha256_raw", "attribution", "pipeline"]
CONTRACT_FIELDS = ["OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY", "INCLINATION",
                   "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY", "EPHEMERIS_TYPE",
                   "CLASSIFICATION_TYPE", "NORAD_CAT_ID", "ELEMENT_SET_NO", "REV_AT_EPOCH", "BSTAR",
                   "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT", "RMS", "DATA_SOURCE"]
SUPGP_ATTRIBUTION = ("Orbit data courtesy of CelesTrak (celestrak.org); "
                     "SupGP elements derived from SpaceX ephemerides.")
SUPGP_URL = "https://celestrak.org/NORAD/elements/supplemental/sup-gp.php?FILE=starlink&FORMAT=json"
PIPELINE_ID = "chronoroute-pipeline test"


@cache
def supgp():
    return snapshot.load_pinned(PINNED, "supgp")


@cache
def gp():
    return snapshot.load_pinned(PINNED, "gp")


def load_script(name):
    spec = importlib.util.spec_from_file_location(f"pipeline_{name}", REPO / "pipeline" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def web(tmp_path_factory):
    out = tmp_path_factory.mktemp("web")
    written = snapshot.write_web_snapshot(supgp(), out, pipeline=PIPELINE_ID)
    return out, written


# ------------------------------------------------------------ pinned folder

def test_http_date_is_the_fetch_time():
    raw, ns = snapshot.read_http_date(PINNED / "supgp_headers.txt")
    assert raw == "Sat, 10 Oct 2026 14:02:22 GMT"
    assert omm.format_utc_ns(ns) == "2026-10-10T14:02:22Z"
    assert supgp().fetched_utc == "2026-10-10T14:02:22Z" and gp().fetched_utc == "2026-10-10T13:58:54Z"


def test_headers_without_date_are_refused(tmp_path):
    (tmp_path / "h.txt").write_text("HTTP/1.1 200 OK\nServer: x\n\n")
    with pytest.raises(ValueError, match="no Date"):
        snapshot.read_http_date(tmp_path / "h.txt")


def test_edited_raw_file_is_refused(tmp_path):
    copy = tmp_path / PINNED.name
    copy.mkdir()
    for name in ("SHA256SUMS", "supgp_headers.txt"):
        shutil.copy(PINNED / name, copy / name)
    data = bytearray((PINNED / "starlink_supgp.json").read_bytes())
    data[100] ^= 1
    (copy / "starlink_supgp.json").write_bytes(bytes(data))
    with pytest.raises(ValueError, match="sha256 mismatch"):
        snapshot.load_pinned(copy, "supgp")


def test_pinned_sources_and_counts():
    assert snapshot.available_sources(PINNED) == ["supgp", "gp"]
    assert snapshot.detect_layout(PINNED) == "pinned"
    assert supgp().count == 11_130 and supgp().count_raw == 11_130
    assert gp().count == 11_098 and gp().count_raw == 11_103 and gp().excluded["stale_epoch"] == 5
    assert supgp().sha256_raw == snapshot.read_sha256sums(PINNED / "SHA256SUMS")["starlink_supgp.json"]


def test_validate_pinned_accepts_both_real_files():
    for source in ("supgp", "gp"):
        report = snapshot.validate_pinned(PINNED, source)
        assert report["ok"], report["problems"]
    assert snapshot.validate_pinned(PINNED, "gp")["warnings"] == ["5 excluded as stale_epoch"]


def test_validate_pinned_rejects_a_tiny_file(tmp_path):
    objects = json.loads((PINNED / "starlink_supgp.json").read_bytes())[:3]
    (tmp_path / "starlink_supgp.json").write_text(json.dumps(objects))
    shutil.copy(PINNED / "supgp_headers.txt", tmp_path)
    report = snapshot.validate_pinned(tmp_path, "supgp")
    assert not report["ok"] and any("expected 10000..13000" in p for p in report["problems"])
    (tmp_path / "starlink_supgp.json").write_text("{not json")
    report = snapshot.validate_pinned(tmp_path, "supgp")
    assert not report["ok"] and "not valid JSON" in report["problems"][0]


# --------------------------------------------------------- website contract

def test_web_manifest_has_exactly_the_contract_keys(web):
    out, written = web
    manifest = json.loads(written["manifest"].read_text(encoding="utf-8"))
    assert list(manifest) == CONTRACT_MANIFEST_KEYS
    assert all(manifest[k] not in (None, "") for k in CONTRACT_REQUIRED)
    assert manifest["schema"] == "chronoroute.web-snapshot/1"
    assert manifest["snapshot_id"] == "20261010T1402Z-supgp"           # named after fetched_utc
    assert manifest["source"] == "CelesTrak SupGP" and manifest["source_url"] == SUPGP_URL
    assert manifest["fetched_utc"] == "2026-10-10T14:02:22Z"
    assert manifest["http_date"] == "Sat, 10 Oct 2026 14:02:22 GMT"
    assert manifest["count"] == manifest["count_raw"] == 11_130
    assert manifest["epoch_min"] == "2026-10-08T17:33:41.999990Z"
    assert manifest["epoch_median"] == "2026-10-10T10:41:42.000000Z"
    assert manifest["epoch_max"] == "2026-10-10T12:06:42.000019Z"
    assert manifest["max_epoch_age_days"] == 3 and manifest["raw_file"] == "starlink_supgp.json"
    assert manifest["sha256_raw"] == "283b44b5b716f3d2e7791182f7d369800138daa25c2e940a3a8a14fa015985e2"
    assert manifest["excluded"] == {"stale_epoch": 0, "sgp4_error": 0, "invalid": 0, "duplicate": 0}
    assert list(manifest["excluded"]) == ["stale_epoch", "sgp4_error", "invalid", "duplicate"]
    assert manifest["sgp4_check"] == {"library": "python-sgp4", "version": "2.27",
                                      "at_utc": "2026-10-10T14:02:22Z"}
    assert manifest["attribution"] == SUPGP_ATTRIBUTION
    assert manifest["pipeline"] == PIPELINE_ID and manifest["files"] == {"omm": "omm.min.json"}
    # JSON.stringify(manifest, null, 2) + "\n" layout
    assert written["manifest"].read_text(encoding="utf-8") == json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def test_latest_json_points_at_the_snapshot(web):
    out, written = web
    assert json.loads((out / "latest.json").read_text()) == {
        "snapshot_id": "20261010T1402Z-supgp", "path": "snapshots/20261010T1402Z-supgp/"}
    assert snapshot.check_web_snapshot(written["snapshot_dir"], latest_path=out / "latest.json") == []


def test_omm_min_rows_are_the_source_values_verbatim(web):
    _, written = web
    data = written["omm"].read_bytes()
    assert data.endswith(b"]}\n") and b" " not in data.split(b'"rows"')[0]
    table = omm.loads_keep_numbers(data)
    assert table["fields"] == CONTRACT_FIELDS
    source = {int(o["NORAD_CAT_ID"].value): o
              for o in omm.parse_omm_json((PINNED / "starlink_supgp.json").read_bytes())}
    rows = table["rows"]
    assert len(rows) == 11_130
    norads = [int(row[CONTRACT_FIELDS.index("NORAD_CAT_ID")].value) for row in rows]
    assert norads == sorted(set(norads))                                 # sorted, no duplicates
    for row in rows:
        src = source[int(row[11].value)]
        for name, cell in zip(CONTRACT_FIELDS, row):
            if name not in src:
                assert cell is None                                       # only for RMS / DATA_SOURCE
            elif isinstance(cell, omm.JsonNumber):
                assert cell.text == src[name].text                       # the exact characters
            else:
                assert cell == src[name] and isinstance(cell, str)
    # e.g. CelesTrak's "9.9687e-5" is kept as written, not re-printed as 9.9687e-05 or 0.000099687
    assert b"9.9687e-5" in data


def test_contract_validator_accepts_ours_and_catches_breakage(web, tmp_path):
    _, written = web
    good = written["snapshot_dir"]
    assert snapshot.check_web_snapshot(good) == []

    def broken(edit_manifest=None, edit_table=None):
        target = tmp_path / f"case{len(list(tmp_path.iterdir()))}"
        shutil.copytree(good, target)
        if edit_manifest:
            m = json.loads((target / "manifest.json").read_text())
            edit_manifest(m)
            (target / "manifest.json").write_text(json.dumps(m))
        if edit_table:
            t = json.loads((target / "omm.min.json").read_text())
            edit_table(t)
            (target / "omm.min.json").write_text(json.dumps(t))
        return snapshot.check_web_snapshot(target)

    assert any("count_raw" in p for p in broken(lambda m: m.update(count_raw=1)))
    assert any("sha256_raw" in p for p in broken(lambda m: m.update(sha256_raw="ABC")))
    assert any("fetched_utc" in p for p in broken(lambda m: m.update(fetched_utc="2026-10-10 14:02")))
    assert any("epoch_min <=" in p for p in broken(lambda m: m.update(epoch_min="2027-01-01T00:00:00Z")))
    assert any("schema" in p for p in broken(lambda m: m.update(schema="other/2")))
    assert any("pipeline" in p for p in broken(lambda m: m.pop("pipeline")))
    assert any("excluded.sgp4_error" in p for p in broken(lambda m: m["excluded"].pop("sgp4_error")))
    assert any("fields must be exactly" in p for p in broken(edit_table=lambda t: t["fields"].reverse()))
    assert any("sorted" in p for p in broken(edit_table=lambda t: t["rows"].reverse()))
    assert any("rows but the manifest" in p for p in broken(edit_table=lambda t: t["rows"].pop()))
    assert any("must have" in p for p in broken(edit_table=lambda t: t["rows"][0].pop()))


def test_writing_is_deterministic(tmp_path):
    a = snapshot.write_web_snapshot(supgp(), tmp_path / "a", pipeline=PIPELINE_ID)
    b = snapshot.write_web_snapshot(supgp(), tmp_path / "b", pipeline=PIPELINE_ID)
    for key in ("omm", "manifest", "latest"):
        assert a[key].read_bytes() == b[key].read_bytes()


def test_gp_snapshot_counts_its_exclusions(tmp_path):
    written = snapshot.write_web_snapshot(gp(), tmp_path, pipeline=PIPELINE_ID, update_latest=False)
    m = written["manifest_dict"]
    assert m["snapshot_id"] == "20261010T1358Z-gp" and m["source"] == "CelesTrak GP"
    assert m["count"] == 11_098 and m["count_raw"] == 11_103 and m["excluded"]["stale_epoch"] == 5
    assert not (tmp_path / "latest.json").exists()
    assert snapshot.check_web_snapshot(written["snapshot_dir"]) == []


def test_web_snapshot_loads_back_into_the_same_fleet(web):
    _, written = web
    back = snapshot.load_snapshot(written["snapshot_dir"])
    assert back.layout == "web" and back.snapshot_id == "20261010T1402Z-supgp"
    assert back.fetched_ns == supgp().fetched_ns and back.count == supgp().count
    assert [(r.norad, dict(r.values)) for r in back.records] == \
           [(r.norad, {k: v for k, v in r.values.items()}) for r in supgp().records]


def test_snapshot_id_override_and_bad_ids(tmp_path):
    written = snapshot.write_web_snapshot(supgp(), tmp_path, snapshot_id="20261010T1358Z-supgp",
                                          pipeline=PIPELINE_ID)
    assert written["manifest_dict"]["snapshot_id"] == "20261010T1358Z-supgp"
    with pytest.raises(ValueError):
        snapshot.write_web_snapshot(supgp(), tmp_path, snapshot_id="../escape", pipeline=PIPELINE_ID)


def test_pipeline_identifier_names_the_commit():
    ident = snapshot.pipeline_identifier()
    assert ident.startswith("chronoroute-pipeline ")


# ------------------------------------------------------------ the scripts

def test_slim_and_validate_scripts(tmp_path, capsys):
    slim = load_script("slim")
    validate = load_script("validate")
    assert slim.main([str(PINNED), "--out", str(tmp_path), "--snapshot-id", "20261010T1358Z-supgp"]) == 0
    out = capsys.readouterr().out
    assert "11,130 of 11,130 element sets kept" in out
    snap_dir = tmp_path / "snapshots" / "20261010T1358Z-supgp"
    assert validate.main(["--web", str(snap_dir), "--latest", str(tmp_path / "latest.json")]) == 0
    assert validate.main([str(PINNED)]) == 0
    out = capsys.readouterr().out
    assert "6-digit NORAD ids: 472" in out and "6-digit NORAD ids: 446" in out
    (snap_dir / "omm.min.json").write_text('{"fields": [], "rows": []}')
    assert validate.main(["--web", str(snap_dir)]) == 1

"""Tests for chronoroute.export.bundle (`cr export bundle`): the ns-3 scenario bundle."""

import json
import shutil
from functools import cache
from pathlib import Path

import numpy as np
import pytest

from chronoroute import cli, proto, provenance
from chronoroute.data import omm, snapshot
from chronoroute.export import bundle
from chronoroute.route import scheduler, sids

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
T0 = omm.parse_epoch_ns("2026-10-10T14:00:00")


def small_config(**kw):
    base = dict(shell_id="53.2deg-463km", cities=("Chennai", "London", "Singapore"), t0_ns=T0,
                window_ms=2000, flows=(("Chennai", "London"), ("London", "Chennai"), ("Singapore", "London")))
    base.update(kw)
    return bundle.BundleConfig(**base)


@cache
def fleet():
    return snapshot.load_pinned(PINNED, "supgp")


@cache
def built():
    reg = sids.SidRegistry.load()
    b = bundle.build_bundle(fleet(), small_config(), reg)
    assert not reg.changed
    return b


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    out = tmp_path_factory.mktemp("bundle")
    paths = bundle.write_bundle(built(), out, command=["pytest", "bundle"])
    return out, paths


def test_files_columns_and_self_check(written):
    out, paths = written
    assert set(paths) == set(bundle.DATA_FILES) | {"manifest.json"}
    assert bundle.check_bundle(out) == []
    for name, cols in bundle.COLUMNS.items():
        header, _ = bundle.read_csv(out / name)
        assert header == cols
    doc = json.loads((out / "scenario.json").read_text())
    assert doc["schema"] == "chronoroute.bundle/1"
    assert doc["labels"]["isl_topology_grid4"] == "MODELLED"
    assert doc["labels"]["satellite_positions_sgp4"] == "REAL"
    assert doc["counts"]["steps"] == 21 and doc["counts"]["position_steps"] == 3
    assert doc["counts"]["schedule_rows"] + doc["counts"]["schedule_gaps"] == 3 * 2
    assert doc["invariants"]["all_ok"] is True
    assert doc["time"]["t0_gps_ns"] == scheduler.utc_ns_to_gps_ns(T0)
    assert doc["tcrh"]["unit_code"] == 1 and doc["tcrh"]["slack"] == "3/2"


def test_manifest_is_valid_and_lists_every_file(written):
    out, _ = written
    m = provenance.validate_manifest(out)
    assert sorted(o["path"] for o in m["outputs"]) == sorted(bundle.DATA_FILES)
    assert m["labels"] == bundle.LABELS
    assert m["snapshot"]["id"] == PINNED.name
    assert m["tool"] == "cr export bundle"


def test_byte_identical_rerun(written, tmp_path):
    out, _ = written
    reg = sids.SidRegistry.load()
    again = bundle.build_bundle(fleet(), small_config(), reg)
    bundle.write_bundle(again, tmp_path, command=["pytest", "bundle"])
    for name in bundle.DATA_FILES:
        assert (tmp_path / name).read_bytes() == (out / name).read_bytes(), name


def test_csv_values_match_the_scenario(written):
    out, _ = written
    b = built()
    sc = b.scenario
    _, rows = bundle.read_csv(out / "isl_delay.csv")
    n_isl = len(sc.isl_a)
    arr = np.array(rows, dtype=np.int64)
    assert np.array_equal(arr[:, 0].reshape(-1, n_isl)[:, 0], np.arange(21) * 100)
    assert np.array_equal(arr[:, 2].reshape(-1, n_isl).T, sc.isl_up.astype(np.int64))
    assert np.array_equal(arr[:, 3].reshape(-1, n_isl).T, sc.graph.prop_ns[:n_isl])
    _, rows = bundle.read_csv(out / "gsl.csv")
    g = np.array(rows, dtype=np.int64)
    n_g = len(sc.gsl_gs)
    assert np.array_equal(g[:, 1].reshape(-1, n_g)[0], sc.n_sats + sc.gsl_gs)
    assert np.array_equal(g[:, 3].reshape(-1, n_g).T, sc.gsl_up.astype(np.int64))
    assert np.all(g[g[:, 3] == 1, 5] >= 25_000)                 # up ground links: elevation >= 25 deg
    # positions: metres with exactly 3 decimals, within 0.5 mm of the SGP4 ECEF
    _, rows = bundle.read_csv(out / "positions.csv")
    first = [r for r in rows if r[0] == "1000"]
    assert all(len(r[2].split(".")[1]) == 3 for r in first)
    xyz = np.array([[float(r[2]), float(r[3]), float(r[4])] for r in first[:sc.n_sats]])
    assert np.max(np.abs(xyz - sc.sat_pos_km[:, 10] * 1000.0)) <= 0.0005 + 1e-6
    # nodes: SIDs from the registry, ground stations at the end with their city text
    _, rows = bundle.read_csv(out / "nodes.csv")
    reg = sids.SidRegistry.load()
    assert int(rows[0][2]) == reg.satellite_sid(int(rows[0][3]))
    gs_rows = [r for r in rows if r[1] == "gs"]
    assert [r[4] for r in gs_rows] == ["Chennai", "London", "Singapore"]
    assert int(gs_rows[0][2]) == proto.ground_station_sid(reg.ground_station_number("Chennai"))


def test_schedule_rows_decode_to_the_planned_headers(written):
    out, _ = written
    b = built()
    _, rows = bundle.read_csv(out / "schedule.csv")
    by_key = {(fid, start): e for fid, start, _, e in b.entries}
    for r in rows:
        e = by_key[(int(r[0]), int(r[3]))]
        hdr = proto.TcrhHeader.decode(bytes.fromhex(r[8]))
        assert hdr.epoch_base == 0 and list(hdr.sids_fwd) == [int(x) for x in r[5].split()]
        assert [int(x) for x in r[6].split()] == list(e.budgets_ceil_ns)
        assert [int(x) for x in r[7].split()] == list(e.hop_delays_ns)
        assert int(r[4]) - int(r[3]) == 1000
        # what the ingress would send at valid_from: Epoch_Base stamped, deltas unchanged
        t = T0 + int(r[3]) * 1_000_000
        pkt = proto.TcrhHeader.decode(e.header_for_packet(t))
        assert pkt.deltas_fwd == hdr.deltas_fwd


@pytest.mark.parametrize("name, corrupt", [
    ("isl_delay.csv", lambda lines: lines[:5] + [lines[6], lines[5]] + lines[7:]),          # rows swapped
    ("isl_delay.csv", lambda lines: lines[:-1]),                                             # row missing
    ("gsl.csv", lambda lines: lines[:3] + [lines[3].replace(",1,", ",2,", 1)] + lines[4:]
     if ",1," in lines[3] else lines[:3] + [lines[3].replace(",0,", ",2,", 1)] + lines[4:]),  # bad up flag
    ("positions.csv", lambda lines: lines[:2] + [lines[2].rsplit(".", 1)[0] + ".5"] + lines[3:]),
    ("schedule.csv", lambda lines: lines[:1] + [lines[1].replace("fd", "fe", 1)] + lines[2:]),  # bytes edited
])
def test_check_bundle_catches_corruption(written, tmp_path, name, corrupt):
    out, _ = written
    copy = tmp_path / "copy"
    shutil.copytree(out, copy)
    path = copy / name
    lines = path.read_text().rstrip("\n").split("\n")
    path.write_text("\n".join(corrupt(lines)) + "\n")
    assert bundle.check_bundle(copy) != []


def test_config_validation():
    with pytest.raises(ValueError):
        small_config(window_ms=2050).validate()                 # not a multiple of the step
    with pytest.raises(ValueError):
        small_config(flows=(("Chennai", "Tokyo"),)).validate()  # Tokyo not in the city list
    with pytest.raises(ValueError):
        small_config(flows=(("Chennai", "Chennai"),)).validate()


def test_60_s_milestone_bundle_fits_in_300_mb(tmp_path):
    """Size model from a measured 1 s bundle with the 10 milestone cities: isl_delay.csv (most of
    the bytes) grows exactly with the number of steps; ground-link pairs grow with the window, so
    gsl.csv gets a generous x10. The real 60 s bundle is built by `cr export bundle` (report)."""
    reg = sids.SidRegistry.load()
    cities10 = ("Chennai", "Mumbai", "London", "New York", "Singapore", "Sydney", "Tokyo",
                "Johannesburg", "Sao Paulo", "Frankfurt")
    b = bundle.build_bundle(fleet(), small_config(cities=cities10, window_ms=1000, flows=()), reg)
    bundle.write_bundle(b, tmp_path, command=["pytest"])
    steps = b.scenario.times_ns.size                             # 11
    size = {f: (tmp_path / f).stat().st_size for f in bundle.DATA_FILES}
    estimate = (size["isl_delay.csv"] / steps * 601 + 10 * size["gsl.csv"] / steps * 601
                + size["positions.csv"] / 2 * 61 + size["nodes.csv"] + size["isl.csv"])
    assert estimate < 300e6


def test_cli_export_bundle(tmp_path, capsys):
    reg = tmp_path / "reg.json"
    shutil.copy(sids.DEFAULT_PATH, reg)
    out = tmp_path / "b"
    code = cli.main(["export", "bundle", "--snapshot", str(PINNED), "--cities", "Chennai,London",
                     "--start", "2026-10-10T14:00:00Z", "--duration-ms", "1000", "--flow", "Chennai->London",
                     "--reverse", "--registry", str(reg), "--out", str(out)])
    text = capsys.readouterr().out
    assert code == 0
    assert "check_bundle: OK" in text and "invariants all ok: True" in text
    doc = json.loads((out / "scenario.json").read_text())
    assert [(f["src"], f["dst"]) for f in doc["flows"]] == [("Chennai", "London"), ("London", "Chennai")]
    assert reg.read_bytes() == sids.DEFAULT_PATH.read_bytes()   # nothing new to register

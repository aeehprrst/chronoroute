"""Tests for `cr route --from A --to B` (chronoroute.route.command)."""

import re
import shutil
from pathlib import Path

import pytest

from chronoroute import cli, proto
from chronoroute.data import omm
from chronoroute.route import command, scheduler, sids

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"


def _run(capsys, tmp_path, *extra):
    reg = tmp_path / "reg.json"
    shutil.copy(sids.DEFAULT_PATH, reg)
    code = cli.main(["route", "--from", "Chennai", "--to", "London", "--snapshot", str(PINNED),
                     "--registry", str(reg), *extra])
    out = capsys.readouterr().out
    return code, out, reg


def test_route_printout_has_labels_names_and_valid_header(capsys, tmp_path):
    code, out, reg = _run(capsys, tmp_path, "--at", "2026-10-10T14:00:00Z")
    assert code == 0
    # honesty labels in the printout
    for label in ("positions  REAL", "[DERIVED]", "MODELLED (Grid-4)", "ASSUMED", "hypothetical path",
                  "does not use T-CRH"):
        assert label in out, label
    # real satellite names and NORAD ids
    assert re.search(r"STARLINK-\d+\s+\d{5,6}\s+0x[0-9A-F]{4}", out)
    assert "Chennai (ground)" in out and "London (ground)" in out
    # the hex line decodes to a T-CRH whose last SID is London's and whose Epoch_Base is GPS-based
    hex_line = re.search(r"^\s+([0-9a-f]{16,})$", out, re.M).group(1)
    hdr = proto.TcrhHeader.decode(bytes.fromhex(hex_line))
    assert hdr.sids_fwd[-1] == sids.SidRegistry.load(reg).ground_station_sid("London")
    t = omm.parse_epoch_ns("2026-10-10T14:00:00")
    assert hdr.epoch_base == proto.epoch_base_at_ingress(scheduler.utc_ns_to_gps_ns(t), 1)
    assert "great circle 8,210.0 km" in out and "light time / bound" in out
    # the registry already had every satellite: nothing was appended
    assert reg.read_bytes() == sids.DEFAULT_PATH.read_bytes()


def test_route_defaults_to_snapshot_fetch_time_and_slack_option(capsys, tmp_path):
    code, out, _ = _run(capsys, tmp_path, "--slack", "2")
    assert code == 0
    assert "at 2026-10-10T14:02:22Z" in out          # the SupGP HTTP Date of the pinned folder
    assert "slack S = 2," in out


def test_parse_utc_requires_z():
    assert command.parse_utc("2026-10-10T14:00:00Z") == omm.parse_epoch_ns("2026-10-10T14:00:00")
    with pytest.raises(ValueError):
        command.parse_utc("2026-10-10T14:00:00")


def test_unknown_city_is_an_error(tmp_path):
    with pytest.raises(ValueError):
        cli.main(["route", "--from", "Atlantis", "--to", "London", "--snapshot", str(PINNED),
                  "--registry", str(tmp_path / "r.json")])

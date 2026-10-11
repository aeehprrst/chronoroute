"""Tests for chronoroute.route.sids: the stable, append-only SID registry (spec section 7)."""

import json
from pathlib import Path

import pytest

from chronoroute.data import cities, snapshot
from chronoroute.proto import tcrh
from chronoroute.route import sids

REPO = Path(__file__).resolve().parents[2]
PINNED = sorted((REPO / "data" / "pinned").glob("*-celestrak"))


def test_committed_registry_is_valid_and_covers_the_pinned_fleets():
    reg = sids.SidRegistry.load()
    assert reg.path == sids.DEFAULT_PATH
    for folder in PINNED:
        for source in snapshot.available_sources(folder):
            for r in snapshot.load_pinned(folder, source).records:
                assert r.norad in reg, (folder.name, source, r.norad)
    for city in cities.load_cities():
        assert tcrh.SID_GROUND_BASE <= reg.ground_station_sid(city.name) <= tcrh.SID_GROUND_MAX
    sat = reg.satellites()
    assert [s for s, _ in sat] == list(range(1, len(sat) + 1))
    assert len({n for _, n in sat}) == len(sat)
    assert all(1 <= s <= 0xEFFF for s, _ in sat)
    # the file is in its own canonical form (re-serialising changes nothing)
    assert reg.to_bytes() == sids.DEFAULT_PATH.read_bytes()


def test_committed_registry_spot_values_never_change():
    """Pinned values: if one of these fails, a SID was re-assigned (forbidden: append-only)."""
    reg = sids.SidRegistry.load()
    assert reg.satellite_sid(44714) == 1                  # lowest NORAD id of the first snapshot
    assert reg.satellite_sid(100001) == 10659             # a six-digit NORAD id
    assert reg.ground_station_number("Addis Ababa") == 0
    assert reg.ground_station_sid("Chennai") == 0xF00C
    assert reg.ground_station_sid("London") == 0xF01E


def test_committed_registry_is_reproducible_with_cr_export_sids(tmp_path, capsys):
    """Re-running the documented first population gives a prefix of the committed file
    (later appends may follow it, but the first entries never change)."""
    from chronoroute import cli
    path = tmp_path / "reg.json"
    old = [REPO / "data" / "pinned" / "20261010T1358Z-celestrak",
           REPO / "data" / "pinned" / "20261010T2035Z-celestrak"]
    assert cli.main(["export", "sids", *map(str, old), "--registry", str(path)]) == 0
    fresh, committed = sids.SidRegistry.load(path), sids.SidRegistry.load()
    assert committed.satellites()[:fresh.n_satellites] == fresh.satellites()
    assert committed.ground_stations()[:fresh.n_ground_stations] == fresh.ground_stations()
    assert fresh.n_satellites == 11_130 and fresh.n_ground_stations == 60
    assert "11130 new" in capsys.readouterr().out


def test_sid_zero_is_never_used():
    reg = sids.SidRegistry()
    reg.ensure_satellites([5, 3])
    assert reg.satellites() == [(1, 3), (2, 5)]


def test_append_only_and_deterministic(tmp_path):
    path = tmp_path / "reg.json"
    reg = sids.SidRegistry(path=path)
    assert reg.ensure_satellites([300, 100, 200, 100]) == [100, 200, 300]
    assert reg.ensure_ground_stations(["Tokyo", "Chennai"]) == ["Chennai", "Tokyo"]
    reg.save()
    before = reg.satellites()
    again = sids.SidRegistry.load(path)
    assert again.ensure_satellites([150, 100, 999999]) == [150, 999999]
    assert again.satellites()[:3] == before                   # old entries untouched
    assert again.satellite_sid(150) == 4 and again.satellite_sid(999999) == 5
    again.save()
    assert sids.SidRegistry.load(path).satellites() == again.satellites()
    # nothing new -> nothing changes
    third = sids.SidRegistry.load(path)
    assert third.ensure_satellites([100, 200]) == [] and not third.changed


def test_save_refuses_to_drop_or_renumber(tmp_path):
    path = tmp_path / "reg.json"
    reg = sids.SidRegistry(path=path)
    reg.ensure_satellites([1, 2, 3])
    reg.save()
    shorter = sids.SidRegistry(satellites=[(1, 1), (2, 2)], path=path)
    with pytest.raises(sids.RegistryError):
        shorter.save()
    other = sids.SidRegistry(satellites=[(1, 2), (2, 1), (3, 3)], path=path)
    with pytest.raises(sids.RegistryError):
        other.save()


@pytest.mark.parametrize("sats", [
    [(2, 44714)],                       # must start at 1
    [(1, 44714), (3, 44718)],           # no gaps
    [(1, 44714), (2, 44714)],           # NORAD twice
    [(1, -5)],                          # not a NORAD id
])
def test_malformed_registries_are_refused(sats):
    with pytest.raises(sids.RegistryError):
        sids.SidRegistry(satellites=sats)


def test_ground_station_numbers_are_dense_and_refuse_duplicates(tmp_path):
    with pytest.raises(sids.RegistryError):
        sids.SidRegistry(ground_stations=[(0, "A"), (2, "B")])
    with pytest.raises(sids.RegistryError):
        sids.SidRegistry(ground_stations=[(0, "A"), (1, "A")])
    path = tmp_path / "r.json"
    path.write_text(json.dumps({"schema": "something/else", "satellites": [], "ground_stations": []}))
    with pytest.raises(sids.RegistryError):
        sids.SidRegistry.load(path)

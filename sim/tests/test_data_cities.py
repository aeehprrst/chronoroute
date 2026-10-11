"""Tests for data/static/cities.csv, chronoroute.data.cities and pipeline/cities_natural_earth.py."""

import importlib.util
import math
import struct
from pathlib import Path

import pytest

from chronoroute.data import cities

REPO = Path(__file__).resolve().parents[2]
CSV = REPO / "data" / "static" / "cities.csv"

REQUIRED = ["Chennai", "Mumbai", "Delhi", "Bengaluru", "London", "Paris", "Frankfurt", "Madrid",
            "Moscow", "Cairo", "Lagos", "Nairobi", "Johannesburg", "Dubai", "Singapore", "Tokyo",
            "Seoul", "Sydney", "Perth", "Auckland", "Honolulu", "Los Angeles", "Vancouver",
            "New York", "Toronto", "Mexico City", "Sao Paulo", "Lima", "Santiago", "Reykjavik",
            "Anchorage", "Oslo"]


def load_extractor():
    path = REPO / "pipeline" / "cities_natural_earth.py"
    spec = importlib.util.spec_from_file_location("pipeline_cities", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_list_has_every_required_city_once():
    all_cities = cities.load_cities()
    names = [c.name for c in all_cities]
    assert 55 <= len(all_cities) <= 65 and len(set(names)) == len(names)
    assert set(REQUIRED) <= set(names)
    assert names == sorted(names)


def test_file_layout():
    data = CSV.read_bytes()
    assert data.startswith(b"name,lat,lon,country,iso_a2,ne_id\n")
    assert b"\r" not in data and data.endswith(b"\n")


def test_hemispheres_and_countries_are_right():
    """Cheap guards against a swapped sign or a same-name city in the wrong country."""
    c = {city.name: city for city in cities.load_cities()}
    south = {"Sydney", "Perth", "Auckland", "Johannesburg", "Sao Paulo", "Lima", "Santiago",
             "Cape Town", "Buenos Aires", "Melbourne", "Jakarta", "Rio de Janeiro", "Nairobi", "Kinshasa"}
    west = {"Los Angeles", "Vancouver", "New York", "Toronto", "Mexico City", "Sao Paulo", "Lima",
            "Santiago", "Reykjavik", "Anchorage", "Honolulu", "London", "Madrid", "Casablanca",
            "Buenos Aires", "Bogota", "Rio de Janeiro", "Chicago", "Miami", "San Francisco", "Dallas"}
    for name, city in c.items():
        assert (city.lat_deg < 0) == (name in south), name
        assert (city.lon_deg < 0) == (name in west), name
    expected_iso = {"Chennai": "IN", "Delhi": "IN", "London": "GB", "Perth": "AU", "Santiago": "CL",
                    "Vancouver": "CA", "Sydney": "AU", "Lima": "PE", "Los Angeles": "US", "Reykjavik": "IS"}
    for name, iso in expected_iso.items():
        assert c[name].iso_a2 == iso


def test_distances_between_neighbouring_capitals_are_plausible():
    c = {city.name: city for city in cities.load_cities()}
    # Published great-circle distances (rounded): London-Paris ~344 km, Delhi-Mumbai ~1,150 km,
    # Sydney-Melbourne ~713 km. A wrong row would be off by hundreds of km.
    assert 330 < cities.great_circle_km(c["London"], c["Paris"]) < 360
    assert 1100 < cities.great_circle_km(c["Delhi"], c["Mumbai"]) < 1200
    assert 690 < cities.great_circle_km(c["Sydney"], c["Melbourne"]) < 730


def test_ecef_is_on_the_ellipsoid():
    for city in cities.load_cities():
        r = math.dist((0, 0, 0), city.ecef_km)
        assert 6356.7 < r < 6378.2, city.name


def test_text_coordinates_are_kept():
    chennai = cities.city_by_name("Chennai")
    assert (chennai.lat_text, chennai.lon_text) == ("13.091934", "80.278053")
    assert chennai.ne_id == "1159151431"
    with pytest.raises(KeyError):
        cities.city_by_name("Atlantis")


@pytest.mark.parametrize("bad_row, message", [
    ("X,91.0,0.0,Nowhere,NW,1", "out of range"),
    ("X,0.0,181.0,Nowhere,NW,1", "out of range"),
    ("X,0.0,0.0,Nowhere,nw,1", "2-letter"),
    (",0.0,0.0,Nowhere,NW,1", "empty name"),
])
def test_loader_refuses_bad_rows(tmp_path, bad_row, message):
    path = tmp_path / "c.csv"
    path.write_text("name,lat,lon,country,iso_a2,ne_id\n" + bad_row + "\n")
    with pytest.raises(ValueError, match=message):
        cities.load_cities(path)


def test_loader_refuses_duplicates_and_wrong_header(tmp_path):
    path = tmp_path / "c.csv"
    path.write_text("name,lat,lon,country,iso_a2,ne_id\nA,1,1,X,XX,1\nA,2,2,X,XX,2\n")
    with pytest.raises(ValueError, match="duplicate"):
        cities.load_cities(path)
    path.write_text("name,lat,lon\nA,1,1\n")
    with pytest.raises(ValueError, match="header"):
        cities.load_cities(path)


def test_source_file_records_licence_and_checksums():
    text = (REPO / "data" / "static" / "CITIES_SOURCE.md").read_text(encoding="utf-8")
    assert "Public domain" in text and "Natural Earth" in text and "5.1.2" in text
    assert "cd149186f03d2603e0410da399b980a4357d0ac32d3a2305a49ed3dffcc41d7b" in text
    assert "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip" in text


# ------------------------------------------------- the extractor (synthetic .dbf)

def write_dbf(path, fields, rows, deleted=()):
    """A minimal dBASE III table: fields = [(name, width)], all character fields."""
    record_len = 1 + sum(w for _, w in fields)
    header_len = 32 + 32 * len(fields) + 1
    out = bytearray(struct.pack("<B3BIHH20x", 3, 126, 10, 10, len(rows), header_len, record_len))
    for name, width in fields:
        out += struct.pack("<11sc4xBB14x", name.encode(), b"C", width, 0)
    out += b"\r"
    for i, row in enumerate(rows):
        out += b"*" if i in deleted else b" "
        for (name, width), value in zip(fields, row):
            out += value.encode("utf-8").ljust(width, b" ")
    out += b"\x1a"
    path.write_bytes(bytes(out))


def test_dbf_reader_and_unique_matching(tmp_path):
    ext = load_extractor()
    fields = [("NAME", 12), ("NAMEASCII", 12), ("ISO_A2", 3), ("ADM0NAME", 16),
              ("LATITUDE", 11), ("LONGITUDE", 12), ("NE_ID", 10)]
    rows = [("London", "London", "GB", "United Kingdom", "51.501941", "-0.118668", "1"),
            ("London", "London", "CA", "Canada", "42.969999", "-81.249987", "2"),
            ("Ghost", "Ghost", "GB", "United Kingdom", "1.0", "1.0", "3")]
    path = tmp_path / "t.dbf"
    write_dbf(path, fields, rows, deleted={2})
    got = list(ext.read_dbf(path, ("NAME", "ISO_A2", "LATITUDE")))
    assert got == [{"NAME": "London", "ISO_A2": "GB", "LATITUDE": "51.501941"},
                   {"NAME": "London", "ISO_A2": "CA", "LATITUDE": "42.969999"}]   # deleted row skipped
    with pytest.raises(ValueError, match="no field"):
        list(ext.read_dbf(path, ("POP_MAX",)))
    # The real list cannot be built from this tiny table: every missing city is an error.
    with pytest.raises(ValueError, match="Chennai: 0 Natural Earth rows"):
        ext.build_rows(path)


def test_extractor_csv_format_matches_the_committed_file():
    ext = load_extractor()
    rows = [{"name": c.name, "lat": c.lat_text, "lon": c.lon_text, "country": c.country,
             "iso_a2": c.iso_a2, "ne_id": c.ne_id} for c in cities.load_cities()]
    assert ext.csv_bytes(rows) == CSV.read_bytes()
    assert {c.name for c in cities.load_cities()} == {name for name, _, _ in ext.CITIES}

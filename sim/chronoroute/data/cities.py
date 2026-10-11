"""
cities.py
---------
The curated city list, data/static/cities.csv (REAL coordinates from Natural
Earth, public domain; see data/static/CITIES_SOURCE.md).

    from chronoroute.data.cities import load_cities, city_by_name
    chennai = city_by_name("Chennai")
    chennai.ecef_km        # (x, y, z) on the WGS84 ellipsoid, height 0

Coordinates are WGS84 geodetic latitude/longitude in degrees. They are kept
as the exact text from the file (lat_text / lon_text) as well as floats, so
anything that republishes them can copy them verbatim.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..orbit import frames

# sim/chronoroute/data/cities.py -> repo root is three levels up.
DEFAULT_PATH = Path(__file__).resolve().parents[3] / "data" / "static" / "cities.csv"
COLUMNS = ("name", "lat", "lon", "country", "iso_a2", "ne_id")
LABEL = "REAL"          # city coordinates are public map data


@dataclass(frozen=True)
class City:
    name: str
    lat_deg: float
    lon_deg: float
    country: str
    iso_a2: str
    ne_id: str
    lat_text: str
    lon_text: str

    @property
    def ecef_km(self):
        """Earth-fixed position on the WGS84 ellipsoid (height 0), km."""
        return tuple(float(x) for x in frames.geodetic_to_ecef(self.lat_deg, self.lon_deg, 0.0))


def load_cities(path=None):
    """Read and check cities.csv; returns a tuple of City sorted by name.

    Refuses: wrong header, a latitude outside -90..90, a longitude outside
    -180..180, an empty name, a duplicate name, a malformed country code.
    """
    path = Path(path) if path is not None else DEFAULT_PATH
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"{path}: header must be {','.join(COLUMNS)}")
        cities, seen = [], set()
        for lineno, row in enumerate(reader, 2):
            name = row["name"].strip()
            if not name:
                raise ValueError(f"{path}:{lineno}: empty name")
            if name in seen:
                raise ValueError(f"{path}:{lineno}: duplicate city {name!r}")
            seen.add(name)
            lat, lon = float(row["lat"]), float(row["lon"])
            if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                raise ValueError(f"{path}:{lineno}: {name}: coordinates out of range")
            iso = row["iso_a2"]
            if len(iso) != 2 or not iso.isalpha() or not iso.isupper():
                raise ValueError(f"{path}:{lineno}: {name}: iso_a2 {iso!r} is not a 2-letter code")
            cities.append(City(name, lat, lon, row["country"], iso, row["ne_id"], row["lat"], row["lon"]))
    return tuple(sorted(cities, key=lambda c: c.name))


def city_by_name(name, path=None):
    for city in load_cities(path):
        if city.name == name:
            return city
    raise KeyError(name)


def great_circle_km(a, b):
    """Distance along the surface between two cities on a sphere of the WGS84 mean radius.

    A sphere is good to about 0.5%, enough for the sanity checks and the
    fibre-baseline estimates it is used for.
    """
    r = 6371.0088                                   # IUGG mean Earth radius, km
    lat1, lon1, lat2, lon2 = np.radians([a.lat_deg, a.lon_deg, b.lat_deg, b.lon_deg])
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return float(2 * r * np.arcsin(np.sqrt(h)))

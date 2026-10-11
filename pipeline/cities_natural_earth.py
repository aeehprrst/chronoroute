#!/usr/bin/env python3
"""
cities_natural_earth.py -- rebuild data/static/cities.csv from Natural Earth.

    curl -fLo /tmp/cr-sa/ne/ne_10m_populated_places.zip \\
        https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip
    (unzip it into an empty folder)
    venv/bin/python -B pipeline/cities_natural_earth.py /tmp/cr-sa/ne-x/ne_10m_populated_places.dbf

Natural Earth "populated places" (1:10m, version 5.1.2) is in the public
domain. The script reads its .dbf table with the small reader below (no GIS
library needed), picks the curated cities in CITIES, and writes
data/static/cities.csv with the coordinates copied verbatim from the table:

    name,lat,lon,country,iso_a2,ne_id

Each city is matched on Natural Earth's ASCII name AND its ISO country code,
because many names exist more than once (London in Canada, Perth in Scotland,
Santiago in five countries, ...). A city that does not match exactly once is
an error, so the list can never silently pick the wrong place.

Labels: city coordinates are REAL (public-domain map data); what a city does
in a simulation (traffic, users) is MODELLED elsewhere.
"""

import argparse
import csv
import io
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "data" / "static" / "cities.csv"

# (name written to cities.csv, Natural Earth NAMEASCII, ISO 3166-1 alpha-2)
# The first 32 are the cities the project brief requires; the rest add
# coverage of every continent and of the large population centres.
CITIES = (
    ("Chennai", "Chennai", "IN"), ("Mumbai", "Mumbai", "IN"), ("Delhi", "Delhi", "IN"),
    ("Bengaluru", "Bengaluru", "IN"), ("London", "London", "GB"), ("Paris", "Paris", "FR"),
    ("Frankfurt", "Frankfurt", "DE"), ("Madrid", "Madrid", "ES"), ("Moscow", "Moscow", "RU"),
    ("Cairo", "Cairo", "EG"), ("Lagos", "Lagos", "NG"), ("Nairobi", "Nairobi", "KE"),
    ("Johannesburg", "Johannesburg", "ZA"), ("Dubai", "Dubai", "AE"),
    ("Singapore", "Singapore", "SG"), ("Tokyo", "Tokyo", "JP"), ("Seoul", "Seoul", "KR"),
    ("Sydney", "Sydney", "AU"), ("Perth", "Perth", "AU"), ("Auckland", "Auckland", "NZ"),
    ("Honolulu", "Honolulu", "US"), ("Los Angeles", "Los Angeles", "US"),
    ("Vancouver", "Vancouver", "CA"), ("New York", "New York", "US"), ("Toronto", "Toronto", "CA"),
    ("Mexico City", "Mexico City", "MX"), ("Sao Paulo", "Sao Paulo", "BR"), ("Lima", "Lima", "PE"),
    ("Santiago", "Santiago", "CL"), ("Reykjavik", "Reykjavik", "IS"),
    ("Anchorage", "Anchorage", "US"), ("Oslo", "Oslo", "NO"),
    # wider coverage
    ("Kolkata", "Kolkata", "IN"), ("Hyderabad", "Hyderabad", "IN"), ("Karachi", "Karachi", "PK"),
    ("Dhaka", "Dhaka", "BD"), ("Bangkok", "Bangkok", "TH"), ("Jakarta", "Jakarta", "ID"),
    ("Manila", "Manila", "PH"), ("Hong Kong", "Hong Kong", "HK"), ("Shanghai", "Shanghai", "CN"),
    ("Beijing", "Beijing", "CN"), ("Istanbul", "Istanbul", "TR"), ("Rome", "Rome", "IT"),
    ("Berlin", "Berlin", "DE"), ("Stockholm", "Stockholm", "SE"), ("Tehran", "Tehran", "IR"),
    ("Riyadh", "Riyadh", "SA"), ("Addis Ababa", "Addis Ababa", "ET"),
    ("Kinshasa", "Kinshasa", "CD"), ("Casablanca", "Casablanca", "MA"),
    ("Cape Town", "Cape Town", "ZA"), ("Buenos Aires", "Buenos Aires", "AR"),
    ("Bogota", "Bogota", "CO"), ("Rio de Janeiro", "Rio de Janeiro", "BR"),
    ("Chicago", "Chicago", "US"), ("Miami", "Miami", "US"), ("San Francisco", "San Francisco", "US"),
    ("Melbourne", "Melbourne", "AU"), ("Dallas", "Dallas", "US"),
)
FIELDS = ("name", "lat", "lon", "country", "iso_a2", "ne_id")


def read_dbf(path, wanted_fields):
    """Yield dicts of the wanted fields from a dBASE III table (.dbf).

    Layout: a 32-byte header (record count at byte 4, header length at 8,
    record length at 10), then 32-byte field descriptors ending with 0x0D,
    then fixed-width text records whose first byte is '*' when deleted.
    Natural Earth's .cpg file says the text is UTF-8.
    """
    with open(path, "rb") as fh:
        head = fh.read(32)
        n_records, header_len, record_len = struct.unpack("<IHH", head[4:12])
        fields, offset = [], 1
        while True:
            desc = fh.read(32)
            if not desc or desc[0] == 0x0D:
                break
            name = desc[:11].split(b"\0")[0].decode("ascii")
            length = desc[16]
            fields.append((name, offset, length))
            offset += length
        if offset != record_len:
            raise ValueError(f"{path}: field widths add up to {offset}, record length is {record_len}")
        missing = set(wanted_fields) - {f[0] for f in fields}
        if missing:
            raise ValueError(f"{path}: no field(s) {sorted(missing)}")
        picked = [f for f in fields if f[0] in wanted_fields]
        fh.seek(header_len)
        for _ in range(n_records):
            record = fh.read(record_len)
            if len(record) != record_len:
                raise ValueError(f"{path}: truncated record")
            if record[:1] == b"*":
                continue
            yield {name: record[start:start + length].decode("utf-8").strip()
                   for name, start, length in picked}


def build_rows(dbf_path):
    wanted = ("NAME", "NAMEASCII", "ISO_A2", "ADM0NAME", "LATITUDE", "LONGITUDE", "NE_ID")
    index = {}
    for row in read_dbf(dbf_path, wanted):
        index.setdefault((row["NAMEASCII"], row["ISO_A2"]), []).append(row)
    rows, errors = [], []
    for name, ascii_name, iso in CITIES:
        matches = index.get((ascii_name, iso), [])
        if len(matches) != 1:
            errors.append(f"{name}: {len(matches)} Natural Earth rows for ({ascii_name!r}, {iso})")
            continue
        m = matches[0]
        rows.append({"name": name, "lat": m["LATITUDE"], "lon": m["LONGITUDE"],
                     "country": m["ADM0NAME"], "iso_a2": iso, "ne_id": m["NE_ID"]})
    if errors:
        raise ValueError("; ".join(errors))
    return sorted(rows, key=lambda r: r["name"])


def csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dbf", help="ne_10m_populated_places.dbf from the Natural Earth zip")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--check", action="store_true",
                        help="do not write; fail if the output would differ from the existing file")
    args = parser.parse_args(argv)
    data = csv_bytes(build_rows(args.dbf))
    out = Path(args.out)
    if args.check:
        same = out.is_file() and out.read_bytes() == data
        print(f"cities: {out} {'is up to date' if same else 'DIFFERS from the Natural Earth extract'}")
        return 0 if same else 1
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"cities: wrote {len(CITIES)} cities to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

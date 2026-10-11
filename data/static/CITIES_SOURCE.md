# Source of `cities.csv`

`cities.csv` lists 60 real cities (the 32 the project brief requires, plus 28 for coverage of
every continent) with their coordinates. The coordinates are **REAL** public map data; what a
city does in a simulation (users, traffic) is **MODELLED** elsewhere.

| | |
|---|---|
| Dataset | Natural Earth, *Populated Places*, 1:10m, version 5.1.2 (`ne_10m_populated_places.VERSION.txt`) |
| Download URL | https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip |
| Downloaded | 2026-10-10 19:51 UTC (HTTP `Last-Modified: Fri, 13 May 2022 23:11:17 GMT`) |
| Zip | 2,811,199 bytes, sha256 `cd149186f03d2603e0410da399b980a4357d0ac32d3a2305a49ed3dffcc41d7b` |
| Table read | `ne_10m_populated_places.dbf`, sha256 `eff834a8727e06f28fc52b04393c462d074aecf9a7acd1b870e766240a995b6c` (7,342 places) |
| Licence | **Public domain**, per the Natural Earth terms of use (https://www.naturalearthdata.com/about/terms-of-use/), as checked in the planning research on 2026-10-10 (`06_research_live-data.md` section 5). Attribution is optional; we give it anyway. The zip's own README does not state a licence. |
| Attribution | Made with Natural Earth (naturalearthdata.com). |

## Columns

| Column | Meaning | Natural Earth field |
|---|---|---|
| `name` | Name used by ChronoRoute (ASCII) | our label; matched on `NAMEASCII` |
| `lat`, `lon` | WGS84 latitude / longitude in degrees, copied verbatim (6 decimals) | `LATITUDE`, `LONGITUDE` |
| `country` | Country or territory name | `ADM0NAME` |
| `iso_a2` | ISO 3166-1 alpha-2 code | `ISO_A2` |
| `ne_id` | Natural Earth feature id, to find the source row again | `NE_ID` |

Natural Earth gives one point per populated place (near the centre of the city), not the city's
area, and its own coordinates have the precision of a 1:10m map (a few hundred metres to a few
km). That is far below anything that matters for satellite links (hundreds of km).

## How the file was made (reproducible)

```bash
mkdir -p /tmp/cr-sa/ne-dl /tmp/cr-sa/ne-x
curl -fL -o /tmp/cr-sa/ne-dl/ne_10m_populated_places.zip \
    https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places.zip
# unzip into an empty folder (/tmp/cr-sa/ne-x), then:
venv/bin/python -B -I pipeline/cities_natural_earth.py /tmp/cr-sa/ne-x/ne_10m_populated_places.dbf
venv/bin/python -B -I pipeline/cities_natural_earth.py /tmp/cr-sa/ne-x/ne_10m_populated_places.dbf --check
```

`pipeline/cities_natural_earth.py` holds the curated list. Each city is matched on Natural
Earth's ASCII name **and** ISO country code, and must match exactly one row (there are, for
example, five places called Santiago and a London in Canada). "Delhi" is Natural Earth's
*Delhi* (NE_ID 1159151405), not the separate *New Delhi* point 8 km away.

The Natural Earth zip itself is not stored in the repository (2.8 MB, and the extract above is
all we use).

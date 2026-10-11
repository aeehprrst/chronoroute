# Website data contract

The website reads its data only from its own `public/data/` directory (served at
`https://aeehprrst.github.io/chronoroute/data/`). This file defines those files. The same
definitions exist as TypeScript types and runtime validators (`src/lib/data-types.ts`,
`src/lib/data.ts` for the snapshot; `src/lib/route/topology.ts`, `cities.ts`, `sids.ts` for the
route planner's files) and as Python validators (`sim/chronoroute/data/snapshot.py`
`check_web_snapshot`). `tests/data-contract.test.ts` checks the published files against them.
If you change one, change all of them in the same commit.

## Producers

* **The Python pipeline (always, in CI and for normal development):** `npm run data`, which
  runs `scripts/build-data.sh`:
  1. `cr export web <pinned snapshot> --out-root public/data --update-latest`
     (`sim/chronoroute/export/web.py`, with the data owner's `write_web_snapshot`): the
     snapshot files, `latest.json`, `shells.json` and `isl_grid4.json`;
  2. `pipeline/validate.py --web`: the snapshot folder against this contract;
  3. verbatim copies of `data/static/cities.csv`, `data/static/sid_registry.json` and
     `data/static/CITIES_SOURCE.md` into `public/data/static/`;
  4. `tools/web_parity.py`, twice: the Python side of the route parity test on the reference
     snapshot (`.parity/`) and on the snapshot published in step 1 (`.parity/served/`); not
     served, see "Parity" below.

  The manifest says `"pipeline": "chronoroute-pipeline <git commit>"` (plus ` dirty` when the
  working tree had local changes). CI's `refresh-data.yml` runs the same script on a fresh
  CelesTrak download (`pipeline/fetch.py --sources supgp`); `pages.yml` runs it through
  `scripts/build-tested-data.sh` on the newest snapshot available that passes the data build and
  every test (falling back to at most two older ones).
* **Offline fallback, local development only:** `npm run data:offline-fallback`
  (`scripts/dev-data.mjs`) converts `../data/pinned/20261010T1358Z-celestrak/` into the three
  snapshot files only (no topology files, no `static/`). Its manifest says
  `"pipeline": "dev-data.mjs (development)"`, the site then shows a "development snapshot" note,
  and the route planner says it cannot start. CI never uses it (the data contract test fails in
  CI on a development snapshot).

`public/data/` is generated and git-ignored: nothing in it is ever committed.

## Layout

```
public/data/
  latest.json
  snapshots/<snapshot_id>/manifest.json
  snapshots/<snapshot_id>/omm.min.json
  snapshots/<snapshot_id>/shells.json                    (Python pipeline)
  snapshots/<snapshot_id>/isl_grid4.json                 (Python pipeline)
  snapshots/<snapshot_id>/provenance-topo/manifest.json  (provenance of the two files above)
  static/cities.csv                                      (verbatim copy of data/static/cities.csv)
  static/sid_registry.json                               (verbatim copy of data/static/sid_registry.json)
  static/CITIES_SOURCE.md                                (where the city list comes from)
  parity.json                                            (optional: summary of the CI parity check)
```

Only `latest.json` decides which snapshot the site uses.

## Labels

The labels are the project's shared table `sim/chronoroute/labels.py` (`TABLE`), mirrored in
`src/lib/label-keys.ts`; `tests/label-keys.test.ts` fails if the two differ. The keys this data
carries:

| What | Key | Label |
|---|---|---|
| Orbital elements (`omm.min.json`) | `orbital_elements` | REAL |
| Satellite names and NORAD ids | `catalogue_names_and_ids` | REAL |
| Satellite positions computed with SGP4 from them (in the browser) | `satellite_positions_sgp4` | REAL (REAL physics + REAL code on REAL elements) |
| City coordinates (`static/cities.csv`) | `city_coordinates` | REAL |
| Shells and orbital planes (`shells.json`) | `shells_and_planes` | DERIVED |
| Grid-4 laser links (`isl_grid4.json`) | `isl_topology_grid4` | MODELLED |
| Ground links: 25° mask (ASSUMED, filed under MODELLED), which satellites a city uses | `gsl_mask_and_assignment` | MODELLED |
| 0.5 ms processing per hop | `processing_delay` | MODELLED |
| Routes, budgets, deadlines computed by the route planner | `routes_and_budgets` | DERIVED |
| T-CRH bytes from the site's engine | `tcrh_header_bytes` | REAL (real encoder output) |
| pcap addresses (SID s -> `fd00::s`) and time stamps | `pcap_addresses`, `pcap_timestamps` | MODELLED |

Starlink's real routing is **UNKNOWN** (the site's fourth label) and is never shown; Starlink does
not use T-CRH.

## `latest.json`

```json
{ "snapshot_id": "20261010T2035Z-supgp", "path": "snapshots/20261010T2035Z-supgp/" }
```

| Key | Type | Rule |
|---|---|---|
| `snapshot_id` | string | Must equal `snapshot_id` in the manifest it points to. |
| `path` | string | `snapshots/<id>/`, relative to `public/data/`, with the trailing slash. |

## `snapshots/<id>/manifest.json`

**Required** are the fields of the project brief: `snapshot_id`, `source`, `source_url`,
`fetched_utc`, `http_date`, `count`, `epoch_min`, `epoch_median`, `epoch_max`, `sha256_raw`,
`excluded.stale_epoch`, `excluded.sgp4_error`, `attribution`, `pipeline`. A manifest with only
these fields is valid.

**Optional** (both producers write all of them). When present they are checked; when absent,
`parseManifest()` fills in these defaults:

| Optional key | Default when absent |
|---|---|
| `schema` | `"chronoroute.web-snapshot/1"` (any other value is rejected) |
| `excluded.invalid`, `excluded.duplicate` | `0` |
| `count_raw` | `count` + the sum of all `excluded` counts |
| `max_epoch_age_days` | `3` (the brief's stale-epoch rule) |
| `raw_file` | none (`null`) |
| `sgp4_check` | none (`null`) |
| `files` | `{ "omm": "omm.min.json" }` |

| Key | Type | Meaning |
|---|---|---|
| `schema` | string | Always `"chronoroute.web-snapshot/1"`. Bump on any incompatible change. |
| `snapshot_id` | string | The Python pipeline names a snapshot `<YYYYMMDDTHHMMZ of fetched_utc>-<source>`, e.g. `20261010T2035Z-supgp` for a SupGP file downloaded at 20:35:57 UTC. (The offline fallback uses the pinned folder's time instead, e.g. `20261010T1358Z-supgp` for a file downloaded at 14:02:22; the site then says so under the ID.) |
| `source` | string | Human name of the source, e.g. `"CelesTrak SupGP"`. |
| `source_url` | string | The exact URL that was downloaded. |
| `fetched_utc` | string | Download time, ISO 8601 UTC ending in `Z`, **taken from the HTTP `Date` header** of the response (never from the local clock at conversion time). |
| `http_date` | string | The raw HTTP `Date` header value. |
| `count` | integer | Number of rows in `omm.min.json`. |
| `count_raw` | integer | Number of objects in the raw download. `count + sum(excluded) == count_raw`. |
| `epoch_min`, `epoch_median`, `epoch_max` | string | Oldest, median and newest `EPOCH` of the kept element sets, ISO 8601 UTC with `Z` appended to the source string (full source precision kept). For an even count the median is the lower middle value, so it is always a real epoch from the data. |
| `max_epoch_age_days` | number | The stale threshold used (3). |
| `raw_file` | string | File name of the raw download, e.g. `starlink_supgp.json`. |
| `sha256_raw` | string | sha256 of the raw downloaded bytes, 64 lowercase hex digits. The producer must fail if the pinned folder's `SHA256SUMS` disagrees. |
| `excluded` | object | Counts of left-out objects: `stale_epoch`, `sgp4_error` (required), `invalid`, `duplicate` (optional, default 0). All integers, zero when none. |
| `sgp4_check` | object | `{ "library", "version", "at_utc" }`: the SGP4 check described below (`python-sgp4` for the Python pipeline, `satellite.js` for the fallback). |
| `attribution` | string | Shown on the site verbatim. For CelesTrak SupGP: `Orbit data courtesy of CelesTrak (celestrak.org); SupGP elements derived from SpaceX ephemerides.` |
| `pipeline` | string | `"chronoroute-pipeline <commit>"` (Python) or `"dev-data.mjs (development)"` (fallback). |
| `files` | object | `{ "omm": "omm.min.json" }`. `shells.json` and `isl_grid4.json` have fixed names and are not listed here. |

The manifest deliberately has no "generated at" time stamp, so the same input always gives
byte-identical output.

### Exclusion rules (applied in this order; each object is counted once)

1. **`invalid`**: a required field is missing or has the wrong type; `EPOCH` is not
   `YYYY-MM-DDTHH:MM:SS[.ffffff]`; `NORAD_CAT_ID` is not a positive integer;
   `EPHEMERIS_TYPE` is not `0` (SGP4); `CLASSIFICATION_TYPE` is not `"U"` or `"C"`.
2. **`stale_epoch`**: `fetched_utc - EPOCH > max_epoch_age_days` (3 days). `EPOCH` has no zone
   in CelesTrak JSON and is read as UTC.
3. **`sgp4_error`**: the SGP4 library cannot initialise the element set, or propagation to
   `fetched_utc` gives no finite position.
4. **`duplicate`**: a second element set for a `NORAD_CAT_ID` already kept; the one with the
   newest `EPOCH` is kept.

## `snapshots/<id>/omm.min.json`

A column-oriented copy of the kept OMM objects, to save space:

```json
{
  "fields": ["OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "..."],
  "rows": [["STARLINK-1008", "2019-074B", "2026-10-10T10:26:41.999971", 15.66510296, "..."]]
}
```

* `fields` is exactly, in this order: `OBJECT_NAME, OBJECT_ID, EPOCH, MEAN_MOTION,
  ECCENTRICITY, INCLINATION, RA_OF_ASC_NODE, ARG_OF_PERICENTER, MEAN_ANOMALY, EPHEMERIS_TYPE,
  CLASSIFICATION_TYPE, NORAD_CAT_ID, ELEMENT_SET_NO, REV_AT_EPOCH, BSTAR, MEAN_MOTION_DOT,
  MEAN_MOTION_DDOT, RMS, DATA_SOURCE` (CelesTrak's key order).
* Values are copied **verbatim** from the source JSON (the Python writer copies the exact number
  text). `null` appears only for an optional field (`RMS`, `DATA_SOURCE`) that the source object
  did not have.
* Rows are sorted by `NORAD_CAT_ID` ascending, with no duplicates.
* `NORAD_CAT_ID` can have six digits (e.g. `100001`). Never assume five.

To use a row, rebuild the object (`fields[i] -> row[i]`, dropping `null`s) and pass it to
`satellite.js` `json2satrec()`. `ommRowsToRecords()` in `src/lib/data.ts` does this and
validates the shape; `loadLatestSnapshot()` loads the snapshot in the browser.

## `snapshots/<id>/shells.json` and `isl_grid4.json`

Written by `cr export web`; the full format is in the repository's
[`docs/bundle-format.md` section 3](../docs/bundle-format.md). In short:

* `shells.json` (schema `chronoroute.web-shells/1`, **DERIVED**): every shell with its orbital
  planes, each a list of NORAD ids in slot order, chosen at `reference_utc`.
* `isl_grid4.json` (schema `chronoroute.web-isl-grid4/1`, **MODELLED**): per shell, the Grid-4
  laser-link pairs `[a, b]` (NORAD ids, a < b, sorted), fixed for the snapshot, and the model
  parameters (`polar_cutoff_deg` 70, `min_grazing_alt_km` 80, `max_range_km` null).
* Both name the same `snapshot_id` as the manifest and have `reference_utc` equal to its
  `fetched_utc`; `buildShellNetwork()` refuses files that disagree.

The route planner decides **at the instant the reader picks** whether each pair is up, with the
Python rules: a cross-plane pair is down while |latitude| of either end is above
`polar_cutoff_deg`; any pair is down while its line of sight comes closer than
`min_grazing_alt_km` to WGS84; any pair is down when a position is missing.

## `static/cities.csv` and `static/sid_registry.json`

Byte-for-byte copies of the repository's `data/static/` files (checked by
`tests/data-contract.test.ts`):

* `cities.csv`: `name,lat,lon,country,iso_a2,ne_id`, 60 cities, Natural Earth (public domain,
  see `CITIES_SOURCE.md`). Read with the rules of `chronoroute.data.cities.load_cities`
  (`src/lib/route/cities.ts`).
* `sid_registry.json` (schema `chronoroute.sid-registry/1`): the stable, append-only T-CRH SID
  registry (spec section 7; format in `docs/bundle-format.md` section 4). Satellites the
  committed registry does not yet know get the SIDs Python's `ensure_satellites` would give them,
  marked provisional on the page (`src/lib/route/sids.ts`).

## `parity.json` (optional)

Written by CI (`PARITY_SUMMARY_OUT=public/data/parity.json npm test`) only after the route
parity gate passed (`tests/route-parity.test.ts`); type, validator and badge wording in
`src/lib/route/parity-summary.ts`:

```json
{"schema": "chronoroute.web-parity-summary/2", "rule": "<what blocks a deploy>",
 "runs": [{"role": "reference" | "served", "snapshot_id": "<pinned folder id>",
           "web_snapshot_id": "<website snapshot id>" | null, "t_utc": "...Z", "shell_id": "...",
           "pairs": 20, "reachable": 19, "identical_paths": 19, "ties": 0, "mismatches": 0,
           "pairs_with_diagnostics": 0}],
 "commit": "<git sha, CI only>"}
```

`reachable` counts the pairs for which Python found a path; `identical_paths` the pairs with the
same path on both sides; `ties` the pairs with a different path of equal cost (within 1 ns),
whose bytes were compared on Python's path. The page says "identical" only when
`identical_paths == reachable` and `ties == 0` in every run, and names ties otherwise. A file
that does not validate (other schema, numbers that do not add up) is not shown; without it, the
page says no summary was published.

## Parity (not served)

`tools/web_parity.py` writes a parity file (schema `chronoroute.web-parity/1`) and a provenance
`manifest.json`: for 20 canonical city pairs at a pinned snapshot's `fetched_utc`, the raw
download's `sha256_raw`, Python's positions frame (ECEF km of every satellite of the 53.2°/463 km
shell, and of every city of those pairs), the shell's OMM rows, the two topology documents, the
city list, the SID registry, and per pair the path, its cost, the per-hop delays, the T-CRH
template and per-packet header, the whole packet and a one-packet pcap. `scripts/build-data.sh`
writes two:

* `web/.parity/parity.json`: the reference run, always `data/pinned/20261010T1358Z-celestrak`;
* `web/.parity/served/parity.json`: the served run, on the snapshot published in `public/data`.

`tests/route-parity.test.ts` runs the TypeScript planner on Python's positions (satellites and
cities): for the reference run with the inputs embedded in the parity file, for the served run
with the published files (`snapshots/<id>/shells.json`, `isl_grid4.json`, `omm.min.json`,
`static/cities.csv`, `static/sid_registry.json`), after checking that the served
`manifest.json` has the same `sha256_raw`, `fetched_utc` and `source`. It blocks a deploy only
when a path cost differs by more than 1 ns or a template/header/packet/pcap byte differs (rule in
`tests/parity-gate.ts`, itself tested by `tests/parity-gate.test.ts`).
`tests/sgp4-parity.test.ts` compares the two SGP4 implementations with a tolerance (10 m; 1 m
once EPOCH is cut to milliseconds).

# pipeline/ -- real orbit data in, checked snapshots out

Scripts that fetch the real Starlink element sets from CelesTrak, check them, and publish the
website's copy. They run inside WSL with the project venv (`venv/bin/python -B ...`), and in CI
with `python`. The logic they share lives in the `chronoroute` package
(`sim/chronoroute/data/omm.py`, `snapshot.py`), so the simulator, the CLI and these scripts all
apply the same rules.

| Script | What it does |
|---|---|
| `fetch.py` | Downloads SupGP (primary) and GP (cross-check) Starlink OMM JSON from CelesTrak into a new `data/pinned/<YYYYMMDDTHHMMZ>-celestrak/` folder (raw bytes, response headers, `SHA256SUMS`, `README.md`), following CelesTrak's usage policy exactly (below). Every request is logged in `data/pinned/fetch_log.jsonl`. |
| `validate.py` | Checks a pinned folder (object count 10,000-13,000, NORAD ids unique after screening, required fields, EPOCH parsed as UTC, stale/SGP4/duplicate exclusions counted, raw file matches `SHA256SUMS`), or with `--web` a website snapshot against `web/DATA_CONTRACT.md`. |
| `slim.py` | Writes the website data contract: `<out>/snapshots/<id>/manifest.json` + `omm.min.json` and `<out>/latest.json`. Re-running on the same input gives byte-identical files. |
| `cities_natural_earth.py` | Rebuilds `data/static/cities.csv` from the public-domain Natural Earth populated-places table (see `data/static/CITIES_SOURCE.md`). |

## CelesTrak rules (and where they are enforced)

| Rule | In `fetch.py` |
|---|---|
| One request per group per update cycle (about 2 h), per IP, across all formats | A source is not requested again within `--min-interval-hours` (2 h, cannot be lowered) of the last request for it, taken from `fetch_log.jsonl` and from the `Date` headers of earlier folders. Each run requests each source at most once. |
| Always send `FORMAT=` (the default became CSV on 2026-05-09) | `check_url()` refuses a URL without `FORMAT=` |
| `HTTP 403` with "has not updated" in the body = not modified | Logged as `not_modified`; nothing is written; the previous snapshot stays current |
| Any other non-200 (or a redirect, or a network error): stop, alert, never retry | The run stops at once (no further sources), exit code 2, message on stdout and in the log |
| Identify yourself | `User-Agent: ChronoRoute research project (github.com/aeehprrst/chronoroute)`, `Accept-Encoding: gzip` |
| Record what was received | HTTP `Date` (the fetch time), byte count (wire and decoded), sha256 of the decoded bytes, all response headers |

The tests (`sim/tests/test_data_fetch.py`) never contact CelesTrak: they replace the HTTP call.

## Exclusion rules (website contract, applied in this order)

1. `invalid`: required field missing or wrong type, bad EPOCH, NORAD id not a positive integer,
   `EPHEMERIS_TYPE` not 0, `CLASSIFICATION_TYPE` not U/C.
2. `stale_epoch`: EPOCH more than 3 days before the fetch time (HTTP Date).
3. `sgp4_error`: sgp4 cannot initialise the element set or propagate it to the fetch time.
4. `duplicate`: a second element set for the same NORAD id (the newest EPOCH is kept).

Objects are keyed by `NORAD_CAT_ID` from the JSON, never by sgp4's `satnum` (capped at
339,999); 6-digit ids such as 100001 are normal since 2026-07.

## Typical run

```bash
venv/bin/python -B pipeline/fetch.py                                   # -> data/pinned/<id>/
venv/bin/python -B pipeline/validate.py data/pinned/<id>
venv/bin/python -B pipeline/slim.py data/pinned/<id> --out <web>/public/data
venv/bin/cr fleet report data/pinned/<id> --out /tmp/cr-sa/fleet
```

Labels: the element sets are **REAL** (public data, attributed to CelesTrak; SupGP is derived
by CelesTrak from SpaceX ephemerides, GP comes from 18 SDS). Shells, planes and positions
computed from them are **DERIVED**.

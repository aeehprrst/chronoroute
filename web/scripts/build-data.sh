#!/usr/bin/env bash
# build-data.sh -- write the website's data folder (web/public/data) with the project's
# Python pipeline, and the Python side of the route parity check (web/.parity).
#
#   web/scripts/build-data.sh [PINNED_SNAPSHOT_DIR]          (npm run data)
#
# PINNED_SNAPSHOT_DIR: a data/pinned/<YYYYMMDDTHHMMZ>-celestrak folder (default: the newest one
# in data/pinned). PYTHON: the interpreter with the chronoroute package (default: the repo's
# venv/bin/python; CI sets PYTHON=python after `pip install -e .`).
#
# Steps, all deterministic (the same inputs give byte-identical files):
#   1. cr export web: manifest.json + omm.min.json (data contract), latest.json,
#      shells.json (DERIVED planes) and isl_grid4.json (MODELLED laser-link pairs);
#   2. pipeline/validate.py --web: the snapshot folder against web/DATA_CONTRACT.md;
#   3. verbatim copies of data/static/cities.csv and data/static/sid_registry.json
#      (the route planner's cities and SIDs) into public/data/static/;
#   4. tools/web_parity.py, twice: Python reference routes for the 20 canonical pairs
#      a. on the experiments' pinned snapshot (always 20261010T1358Z-celestrak, whatever step 1
#         used) -> .parity/parity.json: the fixed reference run;
#      b. on the snapshot published in step 1 -> .parity/served/parity.json: the served run, so
#         the vitest gate (tests/route-parity.test.ts) also checks the files actually served.
#
# The development fallback scripts/dev-data.mjs is NOT used here and never by CI.
set -euo pipefail

WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$WEB/.." && pwd)"
PYTHON="${PYTHON:-$REPO/venv/bin/python}"
export PYTHONDONTWRITEBYTECODE=1

if [ "$#" -ge 1 ]; then
  SNAP="$1"
else
  SNAP="$(bash "$WEB/scripts/newest-snapshot.sh" "$REPO/data/pinned")"
fi
if [ -z "${SNAP:-}" ] || [ ! -d "$SNAP" ]; then
  echo "build-data: no pinned snapshot folder (looked for data/pinned/*-celestrak)" >&2
  exit 2
fi
SNAP="$(cd "$SNAP" && pwd)"

# Guard the wipe below: only ever delete the data folder of THIS website.
grep -q '"name": "chronoroute-web"' "$WEB/package.json" || { echo "build-data: $WEB is not the website folder" >&2; exit 2; }
OUT="$WEB/public/data"
rm -rf -- "$OUT" "$WEB/.parity"
mkdir -p "$OUT/static"

echo "build-data: snapshot $SNAP"
(cd "$REPO" && "$PYTHON" -B -m chronoroute.cli export web "$SNAP" --out-root "$OUT" --update-latest)

ID="$("$PYTHON" -B -c 'import json, sys; print(json.load(open(sys.argv[1]))["snapshot_id"])' "$OUT/latest.json")"
(cd "$REPO" && "$PYTHON" -B pipeline/validate.py --web "$OUT/snapshots/$ID" --latest "$OUT/latest.json")
test -s "$OUT/snapshots/$ID/shells.json" && test -s "$OUT/snapshots/$ID/isl_grid4.json"

install -m 644 "$REPO/data/static/cities.csv" "$REPO/data/static/sid_registry.json" "$REPO/data/static/CITIES_SOURCE.md" "$OUT/static/"

(cd "$REPO" && "$PYTHON" -B tools/web_parity.py --out "$WEB/.parity")
(cd "$REPO" && "$PYTHON" -B tools/web_parity.py --snapshot "$SNAP" --out "$WEB/.parity/served")
# Where the published snapshot's raw download lives (it may be outside data/pinned, e.g. a fresh
# download kept by CI); src/lib/orbit/test-data.ts looks there for the raw file. Not served.
"$PYTHON" -B -c 'import json, sys; json.dump({"pinned_dir": sys.argv[1]}, open(sys.argv[2], "w"))' \
  "$SNAP" "$WEB/.parity/source.json"
echo "build-data: done ($OUT, $WEB/.parity, $WEB/.parity/served)"

#!/usr/bin/env bash
# newest-snapshot.sh [--all] ROOT [ROOT ...] -- print the newest pinned snapshot folder, found in
# the roots, that holds a SupGP download (the website's source). With --all: every such folder,
# one per line, newest first (scripts/build-tested-data.sh falls back along this list).
#
# Snapshot folders are named <YYYYMMDDTHHMMZ>-celestrak (pipeline/fetch.py), so the newest is
# the last one by folder name. Rejected downloads (<id>.rejected) and fetch.py's staging folders
# (.<id>.*) never match. A folder without starlink_supgp.json + supgp_headers.txt (e.g. a run in
# which only GP had changed) is skipped, because `cr export web` builds the site from SupGP.
# Used by the GitHub workflows to choose between the committed data/pinned/ folders and the
# downloads kept in the Actions cache.
set -euo pipefail
shopt -s nullglob
all=0
if [ "${1:-}" = "--all" ]; then
  all=1
  shift
fi
candidates=()
for root in "$@"; do
  for dir in "$root"/*-celestrak; do
    if [ -f "$dir/starlink_supgp.json" ] && [ -f "$dir/supgp_headers.txt" ]; then
      candidates+=("$dir")
    fi
  done
done
if [ "${#candidates[@]}" -eq 0 ]; then
  echo "newest-snapshot: no <YYYYMMDDTHHMMZ>-celestrak folder with a SupGP download in: $*" >&2
  exit 2
fi
# Sort by folder name (the time stamp), not by the root it lives in; newest first.
sorted="$(printf '%s\n' "${candidates[@]}" | awk -F/ '{print $NF "\t" $0}' | sort -r | cut -f2)"
if [ "$all" -eq 1 ]; then
  printf '%s\n' "$sorted"
else
  printf '%s\n' "${sorted%%$'\n'*}"   # the first line
fi

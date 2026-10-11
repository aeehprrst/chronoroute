#!/usr/bin/env bash
# build-tested-data.sh ROOT [ROOT ...] -- the website data for a deploy (.github/workflows/pages.yml):
# the NEWEST snapshot in the roots that passes the data build and every vitest test, falling
# back to older ones.
#
# Why a fallback: pages.yml builds the newest snapshot available, committed (data/pinned) or
# downloaded by refresh-data.yml (kept in the Actions cache). A download can pass fetch.py's
# validation and still fail a later step (cr export web, validate.py --web, or a vitest test
# such as the served-snapshot parity gate). Deploying it would be wrong; but failing every
# pages.yml run, including pure code pushes, until CelesTrak publishes something newer would
# freeze the site, because refresh-data.yml never downloads unchanged data again. So we try the
# newest snapshot first and, if it fails, the next newest, up to MAX_SNAPSHOTS (default 3).
# A fallback is reported as a GitHub warning (and in the job summary); the page shows the data's
# age, with a "stale" badge after 24 hours. If no candidate passes (for example a code defect,
# which fails on every snapshot), the script exits 1 and nothing is deployed.
#
# For each candidate: scripts/build-data.sh SNAPSHOT (which wipes and rewrites public/data and
# .parity), then `npm test` in web/ (the deploy gate). `npm ci` must have run before.
# Environment: MAX_SNAPSHOTS; PARITY_SUMMARY_OUT (passed through to the tests).
# Test hooks (tests/ci-scripts.test.ts only): CR_BUILD_DATA and CR_TEST name executables that
# replace the two steps; each gets the snapshot folder as its only argument.
set -euo pipefail

WEB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAX="${MAX_SNAPSHOTS:-3}"
if ! [[ "$MAX" =~ ^[1-9][0-9]*$ ]]; then
  echo "build-tested-data: MAX_SNAPSHOTS must be a positive integer, got '$MAX'" >&2
  exit 2
fi

build_data() {
  if [ -n "${CR_BUILD_DATA:-}" ]; then "$CR_BUILD_DATA" "$1"; else bash "$WEB/scripts/build-data.sh" "$1"; fi
}
run_tests() {
  if [ -n "${CR_TEST:-}" ]; then "$CR_TEST" "$1"; else (cd "$WEB" && npm test); fi
}
note() {
  # A line for the GitHub job summary (ignored outside GitHub Actions).
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then printf '%s\n' "$1" >> "$GITHUB_STEP_SUMMARY"; fi
}

list="$(bash "$WEB/scripts/newest-snapshot.sh" --all "$@")"
mapfile -t candidates <<< "$list"
total="${#candidates[@]}"
n=$(( total < MAX ? total : MAX ))
echo "build-tested-data: $total snapshot(s) with a SupGP download; trying at most $n, newest first"

failed=()
for (( i = 0; i < n; i++ )); do
  snap="${candidates[$i]}"
  name="$(basename "$snap")"
  echo "::group::Snapshot $((i + 1))/$n: $name"
  ok=0
  if build_data "$snap" && run_tests "$snap"; then ok=1; fi
  echo "::endgroup::"
  if [ "$ok" -eq 1 ]; then
    echo "build-tested-data: using $name ($snap)"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
      echo "snapshot=$snap" >> "$GITHUB_OUTPUT"
      echo "fallback=$([ "$i" -gt 0 ] && echo true || echo false)" >> "$GITHUB_OUTPUT"
    fi
    if [ "$i" -gt 0 ]; then
      echo "::warning title=Older orbit snapshot deployed::$name was used because newer snapshot(s) failed: ${failed[*]}"
      note "**Older orbit snapshot deployed:** \`$name\`; newer snapshot(s) failed the data build or the tests: ${failed[*]}"
    else
      note "Orbit snapshot deployed: \`$name\` (the newest available)."
    fi
    exit 0
  fi
  failed+=("$name")
  echo "::warning title=Snapshot rejected::$name failed the data build or the tests (see the group above)"
done

echo "::error title=No deployable snapshot::none of the $n newest snapshot(s) passed: ${failed[*]}"
note "**Nothing deployed:** none of the $n newest snapshot(s) passed the data build and tests: ${failed[*]}"
exit 1

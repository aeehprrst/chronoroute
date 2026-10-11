#!/usr/bin/env python3
"""
validate.py -- check orbit snapshots before anything uses them.

    venv/bin/python -B pipeline/validate.py data/pinned/20261010T1358Z-celestrak
    venv/bin/python -B pipeline/validate.py data/pinned/<id> --source gp
    venv/bin/python -B pipeline/validate.py --web public/data/snapshots/<id> [--latest public/data/latest.json]

Pinned download folder (default): screens the raw OMM file with the website
contract's rules (invalid -> stale_epoch -> sgp4_error -> duplicate, see
chronoroute/data/omm.py), checks the raw file against SHA256SUMS, the object
count (10,000..13,000) and that NORAD ids are unique after screening, and
prints the counts. EPOCH has no "Z" and is read as UTC.

--web: checks a website snapshot folder against web/DATA_CONTRACT.md
(manifest fields and types, count + excluded == count_raw, omm.min.json field
order, rows sorted by NORAD id without duplicates, row count == count).

Exit code 0 = valid, 1 = problems found.
"""

import argparse
import sys
from pathlib import Path

from chronoroute.data import snapshot


def check_pinned(folder, source):
    report = snapshot.validate_pinned(folder, source)
    print(f"validate: {folder} [{source}]")
    if report["counts"]:
        c = report["counts"]
        print(f"  objects {c['raw']:,} raw -> {c['kept']:,} kept; excluded {c['excluded']}")
        fleet = report["fleet"]
        print(f"  fetched {fleet.fetched_utc} (HTTP Date {fleet.http_date}); sha256 {fleet.sha256_raw}")
        ep = fleet.epoch_summary()
        print(f"  epochs {ep['epoch_min']} .. {ep['epoch_max']} (median {ep['epoch_median']})")
        six = sum(r.norad >= 100_000 for r in fleet.records)
        print(f"  6-digit NORAD ids: {six}")
    for w in report["warnings"]:
        print(f"  warning: {w}")
    for p in report["problems"]:
        print(f"  PROBLEM: {p}")
    print("  OK" if report["ok"] else "  FAILED")
    return report["ok"]


def check_web(folder, latest):
    problems = snapshot.check_web_snapshot(folder, latest_path=latest)
    print(f"validate: website snapshot {folder}")
    for p in problems:
        print(f"  PROBLEM: {p}")
    print("  OK" if not problems else "  FAILED")
    return not problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", help="pinned download folder, or a website snapshot folder with --web")
    parser.add_argument("--source", choices=list(snapshot.OMM_SOURCES), default=None,
                        help="pinned folder: which file (default: every OMM file present)")
    parser.add_argument("--web", action="store_true", help="the folder is a website snapshot")
    parser.add_argument("--latest", default=None, help="with --web: latest.json to cross-check")
    args = parser.parse_args(argv)
    folder = Path(args.folder)
    if args.web:
        return 0 if check_web(folder, args.latest) else 1
    sources = [args.source] if args.source else snapshot.available_sources(folder)
    if not sources:
        print(f"validate: {folder}: no OMM file with its headers file", file=sys.stderr)
        return 1
    ok = all([check_pinned(folder, s) for s in sources])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

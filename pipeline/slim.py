#!/usr/bin/env python3
"""
slim.py -- turn a pinned CelesTrak download into the website's snapshot files.

    venv/bin/python -B pipeline/slim.py data/pinned/<id> --out <web>/public/data
    venv/bin/python -B pipeline/slim.py data/pinned/<id> --out DIR --snapshot-id 20261010T1358Z-supgp

Writes, in the format of web/DATA_CONTRACT.md (the WEBSITE DATA CONTRACT):

  <out>/snapshots/<snapshot_id>/manifest.json   provenance + counts (no time stamp
                                                of its own: same input, same bytes)
  <out>/snapshots/<snapshot_id>/omm.min.json    {"fields": [...], "rows": [[...]]}
  <out>/latest.json                             pointer to this snapshot (unless --no-latest)

snapshot_id defaults to "<YYYYMMDDTHHMMZ of the HTTP Date>-<source>", e.g.
20261010T1402Z-supgp. omm.min.json keeps CelesTrak's numbers exactly as they
were written in the raw file (e.g. 9.9687e-5 stays 9.9687e-5), rows sorted by
NORAD_CAT_ID. The manifest's "pipeline" is "chronoroute-pipeline <git commit>"
("dirty" appended when the working tree has local changes).

The written folder is checked with the contract validator before the script
reports success (exit 1 if it fails).
"""

import argparse
import sys

from chronoroute.data import snapshot


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", help="pinned download folder, e.g. data/pinned/20261010T1358Z-celestrak")
    parser.add_argument("--out", required=True, help="the website data directory (public/data)")
    parser.add_argument("--source", choices=list(snapshot.OMM_SOURCES), default="supgp")
    parser.add_argument("--snapshot-id", default=None, help="override the snapshot id")
    parser.add_argument("--no-latest", action="store_true", help="do not write latest.json")
    args = parser.parse_args(argv)

    fleet = snapshot.load_pinned(args.folder, args.source)
    written = snapshot.write_web_snapshot(fleet, args.out, snapshot_id=args.snapshot_id,
                                          update_latest=not args.no_latest)
    m = written["manifest_dict"]
    print(f"slim: {m['snapshot_id']}: {m['count']:,} of {m['count_raw']:,} element sets kept,"
          f" excluded {m['excluded']}")
    print(f"slim: epochs {m['epoch_min']} .. {m['epoch_max']} (median {m['epoch_median']}),"
          f" fetched {m['fetched_utc']}")
    print(f"slim: wrote {written['omm']} ({written['omm'].stat().st_size:,} bytes) and {written['manifest']}"
          + (f" and {written['latest']}" if "latest" in written else ""))
    problems = snapshot.check_web_snapshot(written["snapshot_dir"], latest_path=written.get("latest"))
    for p in problems:
        print(f"slim: PROBLEM: {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

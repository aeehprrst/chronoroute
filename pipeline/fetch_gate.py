#!/usr/bin/env python3
"""
fetch_gate.py -- should this refresh-data run ask CelesTrak at all?

    python -B pipeline/fetch_gate.py --out-root ~/celestrak-pinned [--now]

It reads the newest entry of fetch.py's request log (fetch_log.jsonl) and prints its decision.
Under GitHub Actions it also writes fetch=true or fetch=false to $GITHUB_OUTPUT. It exits 0
whatever the log says: CelesTrak's last answer decides whether we ask, never whether the run
fails. The rule:

  * Nothing logged yet, a download, or HTTP 403 "has not updated": ask. fetch.py's own 2-hour
    rule still applies.
  * No answer at all (network error, timeout) or an HTTP 5xx: the problem was on the way or on
    CelesTrak's side, not in our request. Ask again (the next scheduled run is 4 hours later).
  * Any other answer (a 4xx such as 429 or a 403 refusal, a redirect, a 200 that could not be
    used, or an outcome this script does not know): our request may be what is wrong, so wait
    PAUSE_HOURS after it and then ask once more. --now asks at once (the workflow's "fetch_now"
    input, for a human who has looked).

fetch.py still sends at most one request per source per run and never retries. With one
scheduled run every 4 hours that is at most 6 error answers a day after a server error, and 1 a
day otherwise: far below the 50 error answers in 2 hours after which CelesTrak blocks an address.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from chronoroute.data import omm

LOG_NAME = "fetch_log.jsonl"
PAUSE_HOURS = 24
NS_PER_HOUR = 3600 * 10**9


def utc_now_ns():
    return omm.datetime_to_ns(datetime.now(timezone.utc))


def read_entries(out_root):
    path = Path(out_root) / LOG_NAME
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def requested_ns(entry):
    """The entry's request time in UTC nanoseconds, or None if it cannot be read."""
    try:
        return omm.parse_epoch_ns(str(entry.get("requested_utc", "")).removesuffix("Z"))
    except ValueError:
        return None


def describe(entry):
    status = entry.get("status")
    text = f"last request {entry.get('requested_utc', '?')} for {entry.get('source', '?')}: {entry.get('outcome')}"
    if status:
        text += f" (HTTP {status})"
    detail = " ".join(str(entry.get("detail") or "").split())
    return text + (f": {detail[:200]}" if detail else "")


def decide(entries, now_ns, *, now=False):
    """(ask, reason) for the newest log entry."""
    if not entries:
        return True, "no earlier request logged"
    last = entries[-1]
    outcome, status = last.get("outcome"), last.get("status")
    said = describe(last)
    if outcome in ("downloaded", "not_modified"):
        return True, said
    if outcome == "network_error" or (outcome == "stopped" and isinstance(status, int) and 500 <= status <= 599):
        return True, f"{said}; a problem on the way or on CelesTrak's side, so asking again"
    if now:
        return True, f"{said}; --now given, asking again"
    then = requested_ns(last)
    if then is None:
        return True, f"{said}; its time cannot be read, so asking again"
    until = then + PAUSE_HOURS * NS_PER_HOUR
    if now_ns >= until:
        return True, f"{said}; {PAUSE_HOURS} hours have passed, asking once more"
    return False, f"{said}; not asking again before {omm.format_utc_ns(until)}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1].strip())
    parser.add_argument("--out-root", required=True, help="the folder fetch.py writes to (holds fetch_log.jsonl)")
    parser.add_argument("--now", action="store_true", help="ask even inside the pause after an error answer")
    args = parser.parse_args(argv)
    try:
        entries = read_entries(args.out_root)
    except (OSError, ValueError) as exc:
        ask, reason = True, f"request log unreadable ({exc}); fetch.py will report it"
    else:
        ask, reason = decide(entries, utc_now_ns(), now=args.now)
    print(f"fetch_gate: {'ask CelesTrak' if ask else 'do not ask CelesTrak this run'} -- {reason}")
    if not ask:
        print(f"::notice title=CelesTrak not asked this run::{reason}. The site keeps its current data.")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"fetch={'true' if ask else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

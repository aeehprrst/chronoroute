#!/usr/bin/env python3
"""
fetch.py -- download Starlink element sets from CelesTrak, following its rules.

    venv/bin/python -B pipeline/fetch.py                     # SupGP + GP into data/pinned/
    venv/bin/python -B pipeline/fetch.py --sources supgp     # SupGP only
    venv/bin/python -B pipeline/fetch.py --dry-run           # say what would be requested

CelesTrak's usage policy (celestrak.org/usage-policy.php, 06_research_live-data.md
section 1), and how this script keeps it:

  * One request per group per update cycle, per IP. CelesTrak refreshes about
    every 2 hours, so a source is never requested again within
    --min-interval-hours (2 h) of the last request for it. "Last request"
    comes from fetch_log.jsonl (every request is logged, whatever its answer)
    and from the Date headers saved in earlier snapshot folders.
  * FORMAT is always given (the default changed to CSV on 2026-05-09).
  * HTTP 403 whose body says "has not updated" means "not modified": nothing
    is written and the previous snapshot stays the latest.
  * Any other non-200 answer (or a network error, or a redirect) STOPS the
    run: no retry, no further requests, exit code 2, and a message for a
    human. More than 50 error answers in 2 hours get an IP firewalled.

Every request sends a project User-Agent and Accept-Encoding: gzip. For each
download we keep the exact bytes, the response headers (the Date header is the
fetch time), the byte count and the sha256. A run that downloads anything
writes one new folder data/pinned/<YYYYMMDDTHHMMZ>-celestrak/ (named after the
first download's HTTP Date) with the raw files, *_headers.txt, SHA256SUMS and
a README. The folder is checked (chronoroute.data.snapshot.validate_pinned,
the same check as pipeline/validate.py) before it is kept; a folder that
fails is renamed <id>.rejected and the script exits with code 3.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from chronoroute.data import omm, snapshot

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT_ROOT = REPO / "data" / "pinned"
USER_AGENT = "ChronoRoute research project (github.com/aeehprrst/chronoroute)"
NOT_UPDATED_MARKER = b"has not updated"
LOG_NAME = "fetch_log.jsonl"
DEFAULT_SOURCES = ("supgp", "gp")
MIN_INTERVAL_HOURS = 2.0
TIMEOUT_S = 120

EXIT_OK = 0
EXIT_STOPPED = 2          # a non-200 answer or network error: a human must look
EXIT_REJECTED = 3         # downloaded, but the data failed validation


@dataclass
class HttpResponse:
    status: int
    reason: str
    version: str                      # "HTTP/1.1"
    headers: list                     # [(name, value), ...] in received order
    body: bytes                       # as received (maybe gzip-compressed)

    def header(self, name):
        for key, value in self.headers:
            if key.lower() == name.lower():
                return value
        return None


class NetworkError(Exception):
    """No HTTP answer at all (DNS, connection, timeout, ...)."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # CelesTrak counts 301s as errors. Following one silently would hide it, so
    # a redirect becomes an HTTPError and therefore a stop.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_get(url, headers, timeout):
    """The real HTTP GET. Returns HttpResponse for any status; raises NetworkError otherwise."""
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with opener.open(request, timeout=timeout) as resp:
            version = "HTTP/1.1" if getattr(resp, "version", 11) == 11 else "HTTP/1.0"
            return HttpResponse(resp.status, resp.reason, version, list(resp.headers.items()), resp.read())
    except urllib.error.HTTPError as err:
        body = err.read() if err.fp is not None else b""
        return HttpResponse(err.code, str(err.reason), "HTTP/1.1", list(err.headers.items()) if err.headers else [], body)
    except (urllib.error.URLError, OSError) as exc:
        raise NetworkError(str(exc)) from None


def utc_now_ns():
    return omm.datetime_to_ns(datetime.now(timezone.utc))


# ------------------------------------------------------------- request log

def read_log(out_root):
    path = Path(out_root) / LOG_NAME
    if not path.is_file():
        return []
    entries = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(json.loads(line))
    return entries


def append_log(out_root, entry):
    path = Path(out_root) / LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def last_request_ns(out_root, source):
    """Latest known request time for a source: request log, then saved header Dates."""
    times = []
    for entry in read_log(out_root):
        if entry.get("source") == source and entry.get("requested_utc"):
            times.append(omm.parse_epoch_ns(entry["requested_utc"].rstrip("Z")))
    headers_name = snapshot.SOURCES[source].headers_file
    root = Path(out_root)
    if root.is_dir():
        for folder in sorted(root.iterdir()):
            path = folder / headers_name
            if folder.is_dir() and path.is_file():
                try:
                    times.append(snapshot.read_http_date(path)[1])
                except ValueError:
                    continue
    return max(times) if times else None


# ------------------------------------------------------------- one request

@dataclass
class Download:
    source: str
    response: HttpResponse
    raw: bytes                        # decompressed body
    http_date: str
    fetched_ns: int
    sha256: str


@dataclass
class FetchResult:
    downloads: list = field(default_factory=list)
    not_modified: list = field(default_factory=list)
    skipped: list = field(default_factory=list)       # (source, reason) not requested
    stopped: str | None = None                        # why the run stopped, if it did
    snapshot_dir: Path | None = None
    rejected_dir: Path | None = None
    problems: list = field(default_factory=list)

    @property
    def exit_code(self):
        if self.stopped:
            return EXIT_STOPPED
        if self.rejected_dir is not None:
            return EXIT_REJECTED
        return EXIT_OK


def request_headers():
    return {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}


def check_url(url):
    """Every CelesTrak URL we use must name its FORMAT explicitly."""
    if not re.search(r"[?&]FORMAT=[A-Za-z0-9-]+", url):
        raise ValueError(f"URL without FORMAT=: {url}")
    return url


def decode_body(response):
    encoding = (response.header("Content-Encoding") or "").strip().lower()
    if encoding in ("", "identity"):
        return response.body
    if encoding == "gzip":
        return gzip.decompress(response.body)
    raise ValueError(f"unexpected Content-Encoding {encoding!r} (we only accept gzip)")


def readable_body(response):
    """The body of an error answer as text bytes. We ask for gzip, so even the short
    403 "has not updated" message may arrive compressed; undo that before reading it."""
    try:
        return decode_body(response)
    except (ValueError, OSError, EOFError):
        return response.body


def header_block(response):
    """The saved headers file: status line, headers, blank line (like curl -D)."""
    lines = [f"{response.version} {response.status} {response.reason}".rstrip()]
    lines += [f"{name}: {value}" for name, value in response.headers]
    return ("\n".join(lines) + "\n\n").encode("utf-8")


# ------------------------------------------------------------------- run

def fetch(sources=DEFAULT_SOURCES, out_root=DEFAULT_OUT_ROOT, *, http_get=urllib_get,
          now_ns=utc_now_ns, min_interval_hours=MIN_INTERVAL_HOURS, timeout=TIMEOUT_S,
          dry_run=False, log=print, validate=None):
    """Request each source at most once, then store and validate what came back."""
    out_root = Path(out_root)
    result = FetchResult()
    min_interval_ns = int(min_interval_hours * 3600) * omm.NS_PER_S
    for source in sources:
        info = snapshot.SOURCES[source]
        url = check_url(info.url)
        last = last_request_ns(out_root, source)
        now = now_ns()
        if last is not None and now - last < min_interval_ns:
            why = (f"last request {omm.format_utc_ns(last)} is less than "
                   f"{min_interval_hours:g} h ago; CelesTrak allows one request per update")
            result.skipped.append((source, why))
            log(f"fetch: {source}: skipped ({why})")
            continue
        if dry_run:
            result.skipped.append((source, "dry run"))
            log(f"fetch: {source}: would GET {url}")
            continue
        entry = {"source": source, "url": url, "requested_utc": omm.format_utc_ns(now)}
        try:
            response = http_get(url, request_headers(), timeout)
        except NetworkError as exc:
            entry.update(status=None, outcome="network_error", detail=str(exc))
            append_log(out_root, entry)
            result.stopped = f"{source}: network error: {exc}"
            break
        entry.update(status=response.status, http_date=response.header("Date"),
                     wire_bytes=len(response.body))
        if response.status == 200:
            try:
                raw = decode_body(response)
                http_date = response.header("Date")
                if not http_date:
                    raise ValueError("no Date header: the fetch time must come from it")
                fetched_ns = omm.datetime_to_ns(parsedate_to_datetime(http_date))
            except (ValueError, OSError, EOFError, TypeError) as exc:
                entry.update(outcome="bad_response", detail=str(exc))
                append_log(out_root, entry)
                result.stopped = f"{source}: HTTP 200 but unusable: {exc}"
                break
            sha = hashlib.sha256(raw).hexdigest()
            entry.update(outcome="downloaded", bytes=len(raw), sha256=sha)
            append_log(out_root, entry)
            result.downloads.append(Download(source, response, raw, http_date, fetched_ns, sha))
            log(f"fetch: {source}: HTTP 200, {len(raw):,} bytes ({len(response.body):,} on the wire),"
                f" Date {http_date}, sha256 {sha}")
        elif response.status == 403 and NOT_UPDATED_MARKER in readable_body(response):
            entry.update(outcome="not_modified", detail=readable_body(response)[:300].decode("utf-8", "replace"))
            append_log(out_root, entry)
            result.not_modified.append(source)
            log(f"fetch: {source}: not modified since our last download (HTTP 403 'has not updated');"
                " keeping the previous snapshot")
        else:
            detail = readable_body(response)[:300].decode("utf-8", "replace")
            entry.update(outcome="stopped", detail=detail)
            append_log(out_root, entry)
            result.stopped = f"{source}: HTTP {response.status} {response.reason}: {detail.strip()}"
            break

    if result.stopped:
        log(f"fetch: STOPPED -- {result.stopped}")
        log("fetch: no retry (CelesTrak policy: stop on any non-200 and tell a human).")
    if result.downloads:
        store(result, out_root, log=log, validate=validate)
    return result


def store(result, out_root, *, log=print, validate=None):
    """Write the downloads into a new pinned folder, validate it, keep or reject it."""
    validate = validate or snapshot.validate_pinned
    first = result.downloads[0]
    snap_id = f"{snapshot.snapshot_stamp(first.fetched_ns)}-celestrak"
    final = Path(out_root) / snap_id
    if final.exists():
        raise FileExistsError(f"{final} already exists; refusing to overwrite a pinned snapshot")
    Path(out_root).mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{snap_id}.", dir=out_root))
    sums, rows = [], []
    for item in result.downloads:
        info = snapshot.SOURCES[item.source]
        (staging / info.raw_file).write_bytes(item.raw)
        (staging / info.headers_file).write_bytes(header_block(item.response))
        sums.append(f"{item.sha256} *{info.raw_file}")
        when = omm.format_utc_ns(item.fetched_ns).replace("T", " ").rstrip("Z")
        rows.append(f"| {info.raw_file} | {info.url} | {when} | {len(item.raw):,} | `{item.sha256}` |")
    (staging / snapshot.SHA256SUMS).write_text("\n".join(sums) + "\n", encoding="utf-8")
    readme = [
        f"# Starlink orbit snapshot {snap_id}", "",
        "Downloaded by `pipeline/fetch.py` (one request per source, CelesTrak usage policy).",
        "CelesTrak keeps no history, so this copy is the record of the fleet at this time. Keep it unchanged.", "",
        "| File | Source URL | HTTP Date (UTC) | Bytes | sha256 |", "|---|---|---|---|---|", *rows, "",
        "`*_headers.txt` are the raw HTTP response headers. Checksums are in `SHA256SUMS`.",
        "Orbit data courtesy of CelesTrak (celestrak.org); SupGP elements are derived by CelesTrak",
        "from SpaceX ephemerides, GP elements come from 18 SDS via CelesTrak.", "",
    ]
    if result.not_modified:
        readme.insert(-1, f"Not modified at this run (HTTP 403 'has not updated'): {', '.join(result.not_modified)}.")
    (staging / "README.md").write_text("\n".join(readme), encoding="utf-8")
    for path in staging.iterdir():
        os.chmod(path, 0o644)
    os.chmod(staging, 0o755)

    problems = []
    for item in result.downloads:
        if item.source in snapshot.OMM_SOURCES:
            report = validate(staging, item.source)
            problems += [f"{item.source}: {p}" for p in report["problems"]]
    if problems:
        rejected = Path(out_root) / f"{snap_id}.rejected"
        os.replace(staging, rejected)
        result.rejected_dir, result.problems = rejected, problems
        log(f"fetch: REJECTED -- {rejected}: " + "; ".join(problems))
    else:
        os.replace(staging, final)
        result.snapshot_dir = final
        log(f"fetch: wrote {final}")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES),
                        help="comma-separated: supgp, gp, satcat (default: supgp,gp)")
    parser.add_argument("--out-root", default=str(DEFAULT_OUT_ROOT), help="default: data/pinned")
    parser.add_argument("--min-interval-hours", type=float, default=MIN_INTERVAL_HOURS)
    parser.add_argument("--timeout", type=float, default=TIMEOUT_S)
    parser.add_argument("--dry-run", action="store_true", help="only print what would be requested")
    args = parser.parse_args(argv)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    unknown = [s for s in sources if s not in snapshot.SOURCES]
    if unknown or len(set(sources)) != len(sources):
        parser.error(f"bad --sources {args.sources!r}")
    if args.min_interval_hours < MIN_INTERVAL_HOURS:
        parser.error(f"--min-interval-hours below {MIN_INTERVAL_HOURS} would break CelesTrak's policy")
    result = fetch(sources, args.out_root, min_interval_hours=args.min_interval_hours,
                   timeout=args.timeout, dry_run=args.dry_run)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())

"""Tests for pipeline/fetch.py: CelesTrak's rules, with the HTTP call replaced.

No test here contacts CelesTrak (or any host other than a local test server on
127.0.0.1 for the redirect check).
"""

import gzip
import hashlib
import http.server
import importlib.util
import json
import threading
from pathlib import Path

import pytest

from chronoroute.data import omm, snapshot

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"
SUPGP_DATE = "Sat, 10 Oct 2026 14:02:22 GMT"
GP_DATE = "Sat, 10 Oct 2026 13:58:54 GMT"
NOT_UPDATED = (b"GP data has not updated since your last successful download of GROUP=starlink at "
               b"2026-10-10 13:58:55 UTC.\r\nData is updated once every 2 hours.")


def load_fetch():
    spec = importlib.util.spec_from_file_location("pipeline_fetch", REPO / "pipeline" / "fetch.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load_fetch()


def ns(text):
    return omm.parse_epoch_ns(text)


class FakeHttp:
    """Replays scripted answers (one per call) and records every request."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def ok(body, date, gzipped=True):
    headers = [("Content-Type", "application/json; charset=UTF-8"), ("Date", date)]
    if gzipped:
        headers.insert(1, ("Content-Encoding", "gzip"))
        body = gzip.compress(body)
    return fetch.HttpResponse(200, "OK", "HTTP/1.1", headers, body)


def status(code, reason, body=b"", date=SUPGP_DATE):
    return fetch.HttpResponse(code, reason, "HTTP/1.1", [("Date", date)], body)


def run(http, out_root, now, sources=("supgp", "gp"), **kw):
    lines = []
    result = fetch.fetch(sources, out_root, http_get=http, now_ns=lambda: now, log=lines.append, **kw)
    return result, lines


def log_entries(out_root):
    return [json.loads(line) for line in (out_root / fetch.LOG_NAME).read_text().splitlines()]


# ------------------------------------------------------------------ 200 OK

def test_successful_run_stores_raw_bytes_headers_and_checksums(tmp_path):
    supgp_raw = (PINNED / "starlink_supgp.json").read_bytes()
    gp_raw = (PINNED / "starlink_gp.json").read_bytes()
    http = FakeHttp(ok(supgp_raw, SUPGP_DATE), ok(gp_raw, GP_DATE, gzipped=False))
    result, lines = run(http, tmp_path, ns("2026-10-10T14:03:00"))
    assert result.exit_code == 0 and result.stopped is None
    # exactly one request per source, each with FORMAT=json and our identity
    assert [c["url"] for c in http.calls] == [snapshot.SOURCES["supgp"].url, snapshot.SOURCES["gp"].url]
    for call in http.calls:
        assert "FORMAT=json" in call["url"]
        assert call["headers"]["User-Agent"] == "ChronoRoute research project (github.com/aeehprrst/chronoroute)"
        assert call["headers"]["Accept-Encoding"] == "gzip"
    folder = tmp_path / "20261010T1402Z-celestrak"          # named after the first HTTP Date
    assert result.snapshot_dir == folder
    assert (folder / "starlink_supgp.json").read_bytes() == supgp_raw      # decompressed, exact
    assert (folder / "starlink_gp.json").read_bytes() == gp_raw
    sums = snapshot.read_sha256sums(folder / "SHA256SUMS")
    assert sums == {"starlink_supgp.json": hashlib.sha256(supgp_raw).hexdigest(),
                    "starlink_gp.json": hashlib.sha256(gp_raw).hexdigest()}
    assert snapshot.read_http_date(folder / "supgp_headers.txt") == (SUPGP_DATE, ns("2026-10-10T14:02:22"))
    assert (folder / "supgp_headers.txt").read_text().startswith("HTTP/1.1 200 OK\n")
    assert "Content-Encoding: gzip" in (folder / "supgp_headers.txt").read_text()
    assert "starlink_supgp.json" in (folder / "README.md").read_text()
    # the folder is a valid pinned snapshot for the rest of the project
    assert snapshot.load_pinned(folder, "supgp").count == 11_130
    entries = log_entries(tmp_path)
    assert [e["outcome"] for e in entries] == ["downloaded", "downloaded"]
    assert entries[0]["bytes"] == len(supgp_raw) and entries[0]["wire_bytes"] < len(supgp_raw)
    assert entries[0]["sha256"] == hashlib.sha256(supgp_raw).hexdigest()
    assert entries[0]["http_date"] == SUPGP_DATE


# ------------------------------------------------------ 403 "not updated"

def test_not_updated_403_keeps_the_previous_snapshot(tmp_path):
    previous = tmp_path / "20261010T1358Z-celestrak"
    previous.mkdir()
    (previous / "marker").write_text("old")
    http = FakeHttp(status(403, "Forbidden", NOT_UPDATED), status(403, "Forbidden", NOT_UPDATED))
    result, lines = run(http, tmp_path, ns("2026-10-10T20:00:00"))
    assert result.exit_code == 0 and result.not_modified == ["supgp", "gp"]
    assert len(http.calls) == 2                                   # one each, no retry
    assert sorted(p.name for p in tmp_path.iterdir()) == ["20261010T1358Z-celestrak", fetch.LOG_NAME]
    assert (previous / "marker").read_text() == "old"
    assert [e["outcome"] for e in log_entries(tmp_path)] == ["not_modified", "not_modified"]


def test_gzip_compressed_not_updated_message_is_recognised(tmp_path):
    """We send Accept-Encoding: gzip, so the short 403 message may come back compressed."""
    answer = fetch.HttpResponse(403, "Forbidden", "HTTP/1.1",
                                [("Content-Encoding", "gzip"), ("Date", SUPGP_DATE)], gzip.compress(NOT_UPDATED))
    result, _ = run(FakeHttp(answer), tmp_path, ns("2026-10-10T20:00:00"), sources=("supgp",))
    assert result.exit_code == 0 and result.not_modified == ["supgp"]
    assert "has not updated" in log_entries(tmp_path)[0]["detail"]


# ---------------------------------------------- any other non-200: stop

@pytest.mark.parametrize("answer", [
    status(403, "Forbidden", b"Access denied"),                 # 403 without the marker
    status(404, "Not Found"),
    status(500, "Internal Server Error"),
    status(301, "Moved Permanently"),
])
def test_other_non_200_stops_the_run_without_retry(tmp_path, answer):
    http = FakeHttp(answer, ok(b"[]", GP_DATE))
    result, lines = run(http, tmp_path, ns("2026-10-10T20:00:00"))
    assert result.exit_code == fetch.EXIT_STOPPED
    assert len(http.calls) == 1                                   # gp was never requested
    assert result.downloads == [] and result.snapshot_dir is None
    assert [p.name for p in tmp_path.iterdir()] == [fetch.LOG_NAME]
    assert log_entries(tmp_path)[0]["outcome"] == "stopped"
    assert any("STOPPED" in line for line in lines) and any("no retry" in line for line in lines)


def test_network_error_stops_the_run(tmp_path):
    http = FakeHttp(fetch.NetworkError("timed out"))
    result, _ = run(http, tmp_path, ns("2026-10-10T20:00:00"))
    assert result.exit_code == fetch.EXIT_STOPPED and len(http.calls) == 1
    assert log_entries(tmp_path)[0]["outcome"] == "network_error"


def test_200_without_date_header_stops(tmp_path):
    response = fetch.HttpResponse(200, "OK", "HTTP/1.1", [("Content-Type", "application/json")], b"[]")
    result, _ = run(FakeHttp(response), tmp_path, ns("2026-10-10T20:00:00"), sources=("supgp",))
    assert result.exit_code == fetch.EXIT_STOPPED and "Date" in result.stopped


def test_a_stop_after_a_download_still_stores_what_arrived(tmp_path):
    supgp_raw = (PINNED / "starlink_supgp.json").read_bytes()
    http = FakeHttp(ok(supgp_raw, SUPGP_DATE), status(500, "Internal Server Error"))
    result, _ = run(http, tmp_path, ns("2026-10-10T14:03:00"))
    assert result.exit_code == fetch.EXIT_STOPPED                  # a human must still look
    assert (result.snapshot_dir / "starlink_supgp.json").read_bytes() == supgp_raw
    assert not (result.snapshot_dir / "starlink_gp.json").exists()


# --------------------------------------------- one request per update cycle

def test_recent_download_in_a_pinned_folder_blocks_a_new_request(tmp_path):
    folder = tmp_path / "20261010T1358Z-celestrak"
    folder.mkdir()
    (folder / "supgp_headers.txt").write_text(f"HTTP/1.1 200 OK\nDate: {SUPGP_DATE}\n\n")
    http = FakeHttp(status(403, "Forbidden", NOT_UPDATED))
    result, lines = run(http, tmp_path, ns("2026-10-10T15:00:00"))       # 58 min later
    assert [s for s, _ in result.skipped] == ["supgp"]
    assert [c["url"] for c in http.calls] == [snapshot.SOURCES["gp"].url]   # gp had no recent request


def test_logged_403_also_counts_as_a_request(tmp_path):
    first = FakeHttp(status(403, "Forbidden", NOT_UPDATED))
    run(first, tmp_path, ns("2026-10-10T16:00:00"), sources=("supgp",))
    again = FakeHttp()
    result, _ = run(again, tmp_path, ns("2026-10-10T17:59:59"), sources=("supgp",))
    assert again.calls == [] and result.skipped[0][0] == "supgp"
    later = FakeHttp(status(403, "Forbidden", NOT_UPDATED))
    run(later, tmp_path, ns("2026-10-10T18:00:00"), sources=("supgp",))     # exactly 2 h later
    assert len(later.calls) == 1


def test_dry_run_requests_nothing(tmp_path):
    http = FakeHttp()
    result, lines = run(http, tmp_path, ns("2026-10-10T20:00:00"), dry_run=True)
    assert http.calls == [] and len(result.skipped) == 2
    assert not (tmp_path / fetch.LOG_NAME).exists()


def test_cli_refuses_a_shorter_interval():
    with pytest.raises(SystemExit) as info:
        fetch.main(["--min-interval-hours", "1"])
    assert info.value.code == 2
    with pytest.raises(SystemExit):
        fetch.main(["--sources", "supgp,supgp"])


def test_every_url_names_its_format():
    for info in snapshot.SOURCES.values():
        fetch.check_url(info.url)
    with pytest.raises(ValueError):
        fetch.check_url("https://celestrak.org/NORAD/elements/gp.php?GROUP=starlink")


# ------------------------------------------------------------- validation

def test_download_failing_validation_is_rejected(tmp_path):
    tiny = json.dumps(json.loads((PINNED / "starlink_supgp.json").read_bytes())[:5]).encode()
    result, lines = run(FakeHttp(ok(tiny, SUPGP_DATE)), tmp_path, ns("2026-10-10T14:03:00"),
                        sources=("supgp",))
    assert result.exit_code == fetch.EXIT_REJECTED
    assert result.rejected_dir == tmp_path / "20261010T1402Z-celestrak.rejected"
    assert not (tmp_path / "20261010T1402Z-celestrak").exists()
    assert any("expected 10000..13000" in p for p in result.problems)


def test_existing_snapshot_folder_is_never_overwritten(tmp_path):
    (tmp_path / "20261010T1402Z-celestrak").mkdir()
    raw = (PINNED / "starlink_supgp.json").read_bytes()
    with pytest.raises(FileExistsError):
        run(FakeHttp(ok(raw, SUPGP_DATE)), tmp_path, ns("2026-10-10T16:03:00"), sources=("supgp",))


def test_unexpected_content_encoding_stops(tmp_path):
    response = fetch.HttpResponse(200, "OK", "HTTP/1.1", [("Content-Encoding", "br"), ("Date", SUPGP_DATE)], b"x")
    result, _ = run(FakeHttp(response), tmp_path, ns("2026-10-10T20:00:00"), sources=("supgp",))
    assert result.exit_code == fetch.EXIT_STOPPED and "Content-Encoding" in result.stopped


# ----------------------------------------- the real HTTP function (local only)

class _Redirector(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_GET(self):
        _Redirector.seen.append(dict(self.headers))
        self.send_response(301)
        self.send_header("Location", "/elsewhere")
        self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch):
    # The local test server must be reached directly, whatever proxy the machine has set.
    for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)


def test_real_http_function_does_not_follow_redirects():
    """CelesTrak counts 301s as errors, so urllib_get must report one, not follow it."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_address[1]}/x?FORMAT=json"
        response = fetch.urllib_get(url, fetch.request_headers(), 10)
    finally:
        server.shutdown()
        server.server_close()
    assert response.status == 301
    assert len(_Redirector.seen) == 1                       # /elsewhere was never requested
    assert _Redirector.seen[0]["User-Agent"] == fetch.USER_AGENT


def test_real_http_function_reports_connection_failure():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Redirector)
    port = server.server_address[1]
    server.server_close()                                   # nothing listens on this port now
    with pytest.raises(fetch.NetworkError):
        fetch.urllib_get(f"http://127.0.0.1:{port}/?FORMAT=json", fetch.request_headers(), 5)

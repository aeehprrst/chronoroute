"""
writer.py
---------
Writers for the "chronoroute.trace/1" run folder (spec/trace-v1.md is the
format; this module and reader.py implement it):

    <run>/run.json            what the run is: nodes, time base, faults (ground truth), labels
    <run>/events.jsonl.gz     one JSON object per line, sorted by (t, pkt), then emission order
    <run>/packets.csv.gz      one row per packet, sorted by pkt (engine output, not part of trace/1)

Determinism: the gzip streams are written with mtime 0 and no file name, and
every line is formatted by fixed code (fixed key order, integers only, no
floats), so the same run gives byte-identical files and the same sha256.

Ordering: the engine processes events in time order, but some events are
known slightly ahead of their time stamp (a packet whose next step is
already decided). The writer therefore keeps a small heap and writes an
event only once the engine's clock has passed its time stamp (advance()),
so the file is always sorted by (t, pkt, emission sequence).
"""

import gzip
import heapq
import io
import json
from pathlib import Path

SCHEMA = "chronoroute.trace/1"
EVENTS = ("send", "hop", "late", "fallback", "drop", "deliver")
EVENT_KEYS = ("t", "ev", "pkt", "flow", "node", "next", "sl", "flags", "deadline_u", "now_u",
              "reason", "hex")


def _j(v):
    """JSON text of an int, str or None (the only value types an event holds)."""
    if v is None:
        return "null"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    return json.dumps(v)


def event_line(t, ev, pkt, flow, node, nxt=None, sl=None, flags=None, deadline_u=None, now_u=None,
               reason=None, hex=None):
    """One events.jsonl line (with the trailing newline)."""
    return (f'{{"t":{t},"ev":"{ev}","pkt":{pkt},"flow":{flow},"node":{node},"next":{_j(nxt)},'
            f'"sl":{_j(sl)},"flags":{_j(flags)},"deadline_u":{_j(deadline_u)},"now_u":{_j(now_u)},'
            f'"reason":{_j(reason)},"hex":{_j(hex)}}}\n')


def open_gzip_text(path, compresslevel=1):
    """A deterministic gzip text stream (mtime 0, no stored file name).

    Level 1 by default: a 600 s run writes ~10^6 CSV rows, and level 6 cost about
    12 us per row there (more than the forwarding of the packet), for files
    only ~25% smaller.
    """
    raw = open(path, "wb")
    gz = gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=compresslevel, mtime=0)
    return raw, gz, io.TextIOWrapper(gz, encoding="utf-8", newline="\n")


class EventWriter:
    """events.jsonl.gz with a reorder heap (see the module docstring)."""

    def __init__(self, path):
        self.path = Path(path)
        self._raw, self._gz, self._fh = open_gzip_text(self.path)
        self._heap = []
        self._seq = 0
        self.count = 0
        self._last = (-1, -1)

    def emit(self, t, pkt, line):
        heapq.heappush(self._heap, (t, pkt, self._seq, line))
        self._seq += 1

    def event(self, t, ev, pkt, flow, node, nxt=None, sl=None, flags=None, deadline_u=None,
              now_u=None, reason=None, hex=None):
        self.emit(t, pkt, event_line(t, ev, pkt, flow, node, nxt, sl, flags, deadline_u, now_u,
                                     reason, hex))

    def advance(self, now):
        """Write every buffered event with t < now (no later event can come before them)."""
        heap = self._heap
        while heap and heap[0][0] < now:
            t, pkt, _s, line = heapq.heappop(heap)
            if (t, pkt) < self._last:
                raise AssertionError(f"trace out of order: {(t, pkt)} after {self._last}")
            self._last = (t, pkt)
            self._fh.write(line)
            self.count += 1

    def close(self):
        self.advance(float("inf"))
        self._fh.close()
        self._gz.close()
        self._raw.close()

    def abort(self):
        """Close the file after a failed run (buffered events are not written)."""
        self._heap = []
        _close_quietly(self._fh, self._gz, self._raw)


class PacketCsvWriter:
    """packets.csv.gz, rows in pkt order (packets finish out of order; a heap holds the early ones)."""

    COLUMNS = ("pkt", "flow", "seq", "send_ns", "outcome", "reason", "delivered", "latency_ns", "hops",
               "path", "dev", "dev_hop", "first_late_hop", "arrival_u", "deadline_u", "greedy",
               "fallback_reason", "row_from_ms", "wire_bytes")

    def __init__(self, path):
        self.path = Path(path)
        self._raw, self._gz, self._fh = open_gzip_text(self.path)
        self._fh.write(",".join(self.COLUMNS) + "\n")
        self._heap = []
        self._next = 0
        self.count = 0

    def row(self, pkt, text):
        heapq.heappush(self._heap, (pkt, text))
        heap = self._heap
        while heap and heap[0][0] == self._next:
            self._fh.write(heapq.heappop(heap)[1])
            self._next += 1
            self.count += 1

    def close(self):
        while self._heap:                   # only if some packet ids never finished (should not happen)
            self._fh.write(heapq.heappop(self._heap)[1])
            self.count += 1
        self._fh.close()
        self._gz.close()
        self._raw.close()

    def abort(self):
        """Close the file after a failed run."""
        self._heap = []
        _close_quietly(self._fh, self._gz, self._raw)


def _close_quietly(*streams):
    for s in streams:
        try:
            s.close()
        except (OSError, ValueError):
            pass


def write_json(path, doc):
    """Indented, key-order-preserving JSON plus a newline (deterministic)."""
    Path(path).write_text(json.dumps(doc, indent=1, ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")


def write_run_json(path, doc):
    """run.json with one node and one fault per line (a real-shell run has ~3,000 nodes).

    The text is still plain JSON (json.loads reads it); only the layout differs
    from write_json, so the file stays small and diffs line by line.
    """
    lines = ["{"]
    items = list(doc.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if k in ("nodes", "faults"):
            if not v:
                lines.append(f' {json.dumps(k)}: []{comma}')
                continue
            lines.append(f' {json.dumps(k)}: [')
            for j, item in enumerate(v):
                sep = "," if j < len(v) - 1 else ""
                lines.append("  " + json.dumps(item, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + sep)
            lines.append(f" ]{comma}")
        else:
            body = json.dumps(v, indent=1, ensure_ascii=False, allow_nan=False).replace("\n", "\n ")
            lines.append(f" {json.dumps(k)}: {body}{comma}")
    lines.append("}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_json(*, tool, t0_utc, t0_gps_ns, unit_code, snapshot_id, bundle, nodes, positions, faults,
             labels, extra=None):
    """The run.json document in the order of spec/trace-v1.md."""
    doc = {"schema": SCHEMA, "tool": tool, "t0_utc": t0_utc, "t0_gps_ns": int(t0_gps_ns),
           "unit_code": int(unit_code), "snapshot_id": snapshot_id, "bundle": bundle,
           "nodes": nodes, "positions": positions, "faults": faults, "labels": labels}
    if extra:
        doc.update(extra)
    return doc


__all__ = ["SCHEMA", "EVENTS", "EVENT_KEYS", "event_line", "open_gzip_text", "EventWriter",
           "PacketCsvWriter", "write_json", "write_run_json", "run_json"]

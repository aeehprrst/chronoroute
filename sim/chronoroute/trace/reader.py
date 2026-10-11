"""
reader.py
---------
Read and check a "chronoroute.trace/1" run folder (spec/trace-v1.md).

    run = read_run(run_dir)                 # the run.json dict
    for e in iter_events(run_dir): ...      # event dicts, file order
    problems = validate_run(run_dir)        # [] when the folder follows the spec

validate_run checks everything the spec promises a consumer (the viewer,
the ns-3 converter, analysis scripts): run.json keys and types, node ids,
fault entries, then every event line: exact key set and order, value types,
event kinds, known nodes, sort order by (t, pkt), and per packet that the
story is consistent (one send first, exactly one final drop or deliver,
nothing after it, hop times never decreasing, and the sampling rule of
spec section 4: hex on every event of a sampled packet, on none of another).
"""

import gzip
import json
from pathlib import Path

from .writer import EVENT_KEYS, EVENTS, SCHEMA

RUN_KEYS = ("schema", "tool", "t0_utc", "t0_gps_ns", "unit_code", "snapshot_id", "bundle", "nodes",
            "positions", "faults", "labels")
NODE_KEYS = ("node_id", "kind", "sid", "norad", "name", "lat", "lon")
FAULT_KEYS = ("kind", "link", "node", "start_ns", "stop_ns", "params")
LABEL_VALUES = ("REAL", "DERIVED", "MODELLED")


def read_run(run_dir):
    return json.loads((Path(run_dir) / "run.json").read_text(encoding="utf-8"))


def iter_events(run_dir):
    with gzip.open(Path(run_dir) / "events.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            yield json.loads(line)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _opt_int(v):
    return v is None or _is_int(v)


def validate_run_json(doc):
    problems = []
    if not isinstance(doc, dict):
        return ["run.json is not an object"]
    for k in RUN_KEYS:
        if k not in doc:
            problems.append(f"run.json: missing {k}")
    if problems:
        return problems
    if doc["schema"] != SCHEMA:
        problems.append(f"run.json: schema must be {SCHEMA!r}")
    if doc["tool"] not in ("python-sim", "ns-3"):
        problems.append("run.json: tool must be python-sim or ns-3")
    if not isinstance(doc["t0_utc"], str) or not doc["t0_utc"].endswith("Z"):
        problems.append("run.json: t0_utc must be ISO UTC ending in Z")
    for k in ("t0_gps_ns", "unit_code"):
        if not _is_int(doc[k]):
            problems.append(f"run.json: {k} must be an integer")
    if _is_int(doc["unit_code"]) and not 0 <= doc["unit_code"] <= 3:
        problems.append("run.json: unit_code must be 0..3")
    for k in ("snapshot_id", "bundle"):
        if doc[k] is not None and not isinstance(doc[k], str):
            problems.append(f"run.json: {k} must be a string or null")
    nodes = doc["nodes"]
    if not isinstance(nodes, list) or not nodes:
        problems.append("run.json: nodes must be a non-empty list")
        nodes = []
    for i, n in enumerate(nodes):
        if not isinstance(n, dict) or set(n) != set(NODE_KEYS):
            problems.append(f"run.json: nodes[{i}] must have exactly {NODE_KEYS}")
            continue
        if n["node_id"] != i:
            problems.append(f"run.json: nodes[{i}].node_id must be {i}")
        if n["kind"] not in ("sat", "gs"):
            problems.append(f"run.json: nodes[{i}].kind must be sat or gs")
        if not _is_int(n["sid"]) or not 0 <= n["sid"] <= 0xFFFE:
            problems.append(f"run.json: nodes[{i}].sid must be 0..0xFFFE")
        if not _opt_int(n["norad"]):
            problems.append(f"run.json: nodes[{i}].norad must be an integer or null")
        if not isinstance(n["name"], str):
            problems.append(f"run.json: nodes[{i}].name must be a string")
        for k in ("lat", "lon"):
            if n[k] is not None and (isinstance(n[k], bool) or not isinstance(n[k], (int, float))):
                problems.append(f"run.json: nodes[{i}].{k} must be a number or null")
        if n["kind"] == "gs" and (n["lat"] is None or n["lon"] is None):
            problems.append(f"run.json: ground station nodes[{i}] needs lat and lon")
    pos = doc["positions"]
    if not isinstance(pos, dict) or set(pos) != {"source", "path"} \
            or pos.get("source") not in ("snapshot", "bundle") or not isinstance(pos.get("path"), str):
        problems.append("run.json: positions must be {source: snapshot|bundle, path: str}")
    if not isinstance(doc["faults"], list):
        problems.append("run.json: faults must be a list")
    else:
        for i, f in enumerate(doc["faults"]):
            if not isinstance(f, dict) or set(f) != set(FAULT_KEYS):
                problems.append(f"run.json: faults[{i}] must have exactly {FAULT_KEYS}")
                continue
            if not isinstance(f["kind"], str):
                problems.append(f"run.json: faults[{i}].kind must be a string")
            if f["link"] is not None and not (isinstance(f["link"], list) and len(f["link"]) == 2
                                              and all(_is_int(x) for x in f["link"])):
                problems.append(f"run.json: faults[{i}].link must be [a, b] or null")
            if not _opt_int(f["node"]):
                problems.append(f"run.json: faults[{i}].node must be an integer or null")
            if not (_is_int(f["start_ns"]) and _is_int(f["stop_ns"]) and f["stop_ns"] > f["start_ns"]):
                problems.append(f"run.json: faults[{i}] needs integer start_ns < stop_ns")
            if not isinstance(f["params"], dict):
                problems.append(f"run.json: faults[{i}].params must be an object")
    if not isinstance(doc["labels"], dict) or not doc["labels"] \
            or any(v not in LABEL_VALUES for v in doc["labels"].values()):
        problems.append("run.json: labels must be a non-empty {name: REAL|DERIVED|MODELLED}")
    return problems


def validate_run(run_dir, *, max_problems=20):
    """Every problem found (empty list = the folder follows spec/trace-v1.md)."""
    run_dir = Path(run_dir)
    try:
        doc = read_run(run_dir)
    except (OSError, ValueError) as exc:
        return [f"cannot read run.json: {exc}"]
    problems = validate_run_json(doc)
    if problems:
        return problems
    n_nodes = len(doc["nodes"])
    last = None
    state = {}                       # pkt -> "open" | "closed"
    last_t = {}
    sampled = {}                     # pkt -> its send event carried hex (spec 4: then every event does)
    try:
        for lineno, e in enumerate(iter_events(run_dir), 1):
            if len(problems) >= max_problems:
                break
            if not isinstance(e, dict) or tuple(e) != EVENT_KEYS:
                problems.append(f"events line {lineno}: keys must be exactly {EVENT_KEYS} in that order")
                continue
            if e["ev"] not in EVENTS:
                problems.append(f"events line {lineno}: unknown event {e['ev']!r}")
            for k in ("t", "pkt", "flow", "node"):
                if not _is_int(e[k]):
                    problems.append(f"events line {lineno}: {k} must be an integer")
            for k in ("next", "sl", "flags", "deadline_u", "now_u"):
                if not _opt_int(e[k]):
                    problems.append(f"events line {lineno}: {k} must be an integer or null")
            for k in ("reason", "hex"):
                if e[k] is not None and not isinstance(e[k], str):
                    problems.append(f"events line {lineno}: {k} must be a string or null")
            if not all(_is_int(e[k]) for k in ("t", "pkt", "node")):
                continue
            if not 0 <= e["node"] < n_nodes or (e["next"] is not None and not 0 <= e["next"] < n_nodes):
                problems.append(f"events line {lineno}: node id out of range")
            key = (e["t"], e["pkt"])
            if last is not None and key < last:
                problems.append(f"events line {lineno}: not sorted by (t, pkt)")
            last = key
            p = e["pkt"]
            st = state.get(p)
            if e["ev"] == "send":
                if st is not None:
                    problems.append(f"events line {lineno}: packet {p} sent twice")
                state[p] = "open"
                sampled[p] = e["hex"] is not None
            else:
                # a sampled packet (hex on its send) carries its bytes on EVERY event; a packet
                # without a header (no route, or a scheme without a routing header) on none
                if p in sampled and sampled[p] != (e["hex"] is not None):
                    if sampled[p]:
                        problems.append(f"events line {lineno}: packet {p} is sampled (hex on its send) "
                                        f"but its {e['ev']} event has no hex (spec 4)")
                    else:
                        problems.append(f"events line {lineno}: packet {p} has hex on a {e['ev']} event "
                                        "but not on its send (spec 4)")
                if st is None:
                    problems.append(f"events line {lineno}: packet {p} has an event before its send")
                elif st == "closed":
                    problems.append(f"events line {lineno}: packet {p} has an event after it ended")
                if e["ev"] in ("drop", "deliver"):
                    state[p] = "closed"
            if p in last_t and e["t"] < last_t[p]:
                problems.append(f"events line {lineno}: packet {p} goes back in time")
            last_t[p] = e["t"]
            if e["ev"] == "drop" and not e["reason"]:
                problems.append(f"events line {lineno}: a drop needs a reason")
    except (OSError, ValueError, EOFError) as exc:
        problems.append(f"cannot read events.jsonl.gz: {exc}")
    return problems


def journeys(run_dir):
    """{pkt: [event, ...]} for every packet in the trace (handy for tests and plots)."""
    out = {}
    for e in iter_events(run_dir):
        out.setdefault(e["pkt"], []).append(e)
    return out


__all__ = ["RUN_KEYS", "NODE_KEYS", "FAULT_KEYS", "read_run", "iter_events", "validate_run_json",
           "validate_run", "journeys"]

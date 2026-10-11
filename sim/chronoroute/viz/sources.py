"""
sources.py
----------
Everything the viewer reads, without any graphics, so it can be tested on its own.

Three kinds of input (docs/viewer.md):

  1. a chronoroute.trace/1 run folder (spec/trace-v1.md): run.json + events.jsonl.gz,
     written by the Python engine or by `cr trace from-ns3` (trace/ns3_import.py);
  2. a pinned snapshot folder only (data/pinned/<id>/): the fleet view, no packets;
  3. node positions, from one of two places:
       * the snapshot, through SGP4 (orbit.propagate.SatelliteArray) at exactly the
         instant being drawn (REAL physics + REAL code), or
       * a scenario bundle's positions.csv (1 s samples of the same SGP4 output),
         interpolated between samples (cubic Hermite, see BundlePositions).

Why the trace is checked so strictly here: the viewer's job is to show what a run
REALLY did. A trace that is out of order, names a node that does not exist, or
whose t0 disagrees with its own GPS time would draw something false, so it is
refused with a message saying exactly what is wrong (TraceFormatError). Softer
problems (an unknown extra key, a packet whose hops do not chain) are collected in
Trace.problems and shown, never silently dropped.

Times: trace times `t` are integer nanoseconds since t0. The orbit clock is UTC
nanoseconds since 1970 (t0_unix_ns + t). GPS = UTC + 18 s (proto.timebase).
"""

import csv
import gzip
import importlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import numpy as np

from .. import labels as labels_mod
from ..data import omm
from ..orbit import frames
from ..proto import timebase
from ..route import scheduler
from ..topo import isl_grid4

REPO = Path(__file__).resolve().parents[3]
PINNED_DIR = REPO / "data" / "pinned"

TRACE_SCHEMA = "chronoroute.trace/1"
TRACE_TOOLS = ("python-sim", "ns-3")
RUN_FILE = "run.json"
EVENTS_FILE = "events.jsonl.gz"
EVENT_TYPES = ("send", "hop", "late", "fallback", "drop", "deliver")
EVENT_KEYS = ("t", "ev", "pkt", "flow", "node", "next", "sl", "flags", "deadline_u", "now_u",
              "reason", "hex")
RUN_KEYS = ("schema", "tool", "t0_utc", "t0_gps_ns", "unit_code", "snapshot_id", "bundle",
            "nodes", "positions", "faults", "labels")
NODE_KINDS = ("sat", "gs")
POSITION_SOURCES = ("snapshot", "bundle")

NS_PER_MS = 1_000_000
NS_PER_S = 1_000_000_000
C_KM_PER_NS = 299_792.458 / NS_PER_S          # light, km per ns

# Above this many satellites the globe draws laser links only near the packet path
# (task P4: "Lite mode for > 3,000 satellites").
LITE_THRESHOLD = 3000

# The engine's re-run hook for live mode (key `d`). The viewer looks it up at run
# time and falls back to replay-only (and says so) when it is not there.
ENGINE_HOOK = ("chronoroute.fwd.engine", "rerun_with_fault")


class TraceFormatError(ValueError):
    """The run folder is not a valid chronoroute.trace/1 trace."""


# ----------------------------------------------------------------------- small helpers

def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _opt_int(value):
    return value is None or _is_int(value)


def parse_utc_z(text):
    """'2026-10-10T14:00:00Z' -> integer UTC ns since 1970 (exact)."""
    if not isinstance(text, str) or not text.endswith("Z"):
        raise ValueError(f"UTC time {text!r} must be ISO 8601 ending in Z")
    return omm.parse_epoch_ns(text[:-1])


def resolve_path(text, run_dir=None):
    """A path from run.json (spec/trace-v1.md 1.2): absolute as is; 'data/...' relative to the
    repository root; anything else relative to the run folder."""
    if text is None:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    if path.parts and path.parts[0] == "data":
        return REPO / path
    return (Path(run_dir) if run_dir is not None else REPO) / path


def resolve_snapshot_dir(snapshot_id):
    """data/pinned/<id> for a snapshot id, or None when this checkout does not have it."""
    if not snapshot_id:
        return None
    folder = PINNED_DIR / snapshot_id
    return folder if (folder / "SHA256SUMS").is_file() else None


# ----------------------------------------------------------------------- trace model

@dataclass(frozen=True)
class NodeInfo:
    node_id: int
    kind: str                 # "sat" or "gs"
    sid: int
    norad: int | None
    name: str
    lat: float | None
    lon: float | None


class Event(NamedTuple):
    """One line of events.jsonl.gz (spec/trace-v1.md). Missing optional keys are None."""
    t: int
    ev: str
    pkt: int
    flow: int
    node: int
    next: int | None
    sl: int | None
    flags: int | None
    deadline_u: int | None
    now_u: int | None
    reason: str | None
    hex: str | None


@dataclass(frozen=True)
class Fault:
    kind: str
    link: tuple | None        # (a, b) node ids, or None
    node: int | None
    start_ns: int
    stop_ns: int
    params: dict

    def active(self, t_ns):
        return self.start_ns <= t_ns < self.stop_ns

    def touches(self, a, b):
        return self.link is not None and {a, b} == set(self.link)


@dataclass
class PacketTrack:
    """All events of one packet, in trace order, plus what the viewer derives from them."""

    pkt: int
    flow: int
    events: list = field(default_factory=list)

    @property
    def send(self):
        return self.events[0] if self.events and self.events[0].ev == "send" else None

    @property
    def t_start(self):
        return self.events[0].t

    @property
    def t_end(self):
        return self.events[-1].t

    @property
    def arrivals(self):
        """The 'hop' events: the packet arrived at event.node at event.t."""
        return [e for e in self.events if e.ev == "hop"]

    @property
    def outcome(self):
        """The final 'deliver' or 'drop' event, or None (still in flight when the trace ends)."""
        for e in reversed(self.events):
            if e.ev in ("deliver", "drop"):
                return e
        return None

    @property
    def path(self):
        """Nodes the packet really visited: the sender, then every arrival in order."""
        out = [self.events[0].node] if self.events else []
        for e in self.arrivals:
            if not out or out[-1] != e.node:
                out.append(e.node)
        out_end = self.outcome
        if out_end is not None and out_end.ev == "deliver" and out[-1] != out_end.node:
            out.append(out_end.node)
        return out

    @property
    def latency_ns(self):
        end = self.outcome
        if end is None or end.ev != "deliver" or self.send is None:
            return None
        return end.t - self.send.t

    @property
    def late_events(self):
        return [e for e in self.events if e.ev == "late"]

    @property
    def fallback_events(self):
        return [e for e in self.events if e.ev == "fallback"]

    @property
    def is_late(self):
        return bool(self.late_events)

    def first_hex(self):
        """The first event that carries header bytes (the send event when sampled), or None."""
        for e in self.events:
            if e.hex:
                return e
        return None

    def links(self):
        """Consecutive (u, v) node pairs of the travelled path."""
        p = self.path
        return list(zip(p[:-1], p[1:]))


@dataclass
class Trace:
    run_dir: Path
    run: dict
    nodes: dict                  # node_id -> NodeInfo
    node_ids: list               # in run.json order
    events: list
    packets: dict                # pkt -> PacketTrack (in order of first event)
    faults: list
    labels: dict
    t0_utc: str
    t0_unix_ns: int
    t0_gps_ns: int
    unit_code: int
    problems: list = field(default_factory=list)
    sat_norad: dict = field(default_factory=dict)    # node id -> NORAD (filled by positions_for_trace)

    @property
    def tool(self):
        return self.run["tool"]

    @property
    def snapshot_id(self):
        return self.run.get("snapshot_id")

    @property
    def unit_ns(self):
        return timebase.unit_ns(self.unit_code)

    def flows(self):
        return sorted({p.flow for p in self.packets.values()})

    def packets_of_flow(self, flow):
        return sorted((p for p in self.packets.values() if p.flow == flow),
                      key=lambda p: (p.t_start, p.pkt))

    def flow_label(self, flow):
        """'Chennai -> London': from run.json 'flows' when the producer wrote one (python-sim
        does, as an extra key), else from the first packet's two ends."""
        for f in self.run.get("flows") or ():
            if isinstance(f, dict) and f.get("flow_id") == flow and f.get("src") and f.get("dst"):
                return f"{f['src']} -> {f['dst']}"
        pkts = self.packets_of_flow(flow)
        if not pkts:
            return f"flow {flow}"
        first = pkts[0]
        src = self.nodes[first.events[0].node].name
        dst_node = None
        for p in pkts:
            if p.outcome is not None and p.outcome.ev == "deliver":
                dst_node = p.outcome.node
                break
        dst = self.nodes[dst_node].name if dst_node is not None else "?"
        return f"{src} -> {dst}"

    def sid_to_node(self):
        return {n.sid: n.node_id for n in self.nodes.values()}

    def sat_ids(self):
        return [i for i in self.node_ids if self.nodes[i].kind == "sat"]

    def gs_ids(self):
        return [i for i in self.node_ids if self.nodes[i].kind == "gs"]

    def utc_ns(self, t_ns):
        return self.t0_unix_ns + int(t_ns)


def _fail(where, message):
    raise TraceFormatError(f"{where}: {message}")


def _parse_nodes(raw, where):
    if not isinstance(raw, list) or not raw:
        _fail(where, "'nodes' must be a non-empty list")
    nodes, order, sids = {}, [], set()
    for i, n in enumerate(raw):
        w = f"{where}: nodes[{i}]"
        if not isinstance(n, dict):
            _fail(w, "must be an object")
        for key in ("node_id", "kind", "sid", "norad", "name", "lat", "lon"):
            if key not in n:
                _fail(w, f"missing key {key!r}")
        if not _is_int(n["node_id"]) or n["node_id"] < 0:
            _fail(w, "node_id must be a non-negative integer")
        if n["node_id"] in nodes:
            _fail(w, f"duplicate node_id {n['node_id']}")
        if n["kind"] not in NODE_KINDS:
            _fail(w, f"kind must be one of {NODE_KINDS}")
        if not _is_int(n["sid"]) or not 0 <= n["sid"] <= 0xFFFE:
            _fail(w, "sid must be an integer 0..0xFFFE")
        if n["sid"] in sids:
            _fail(w, f"duplicate sid {n['sid']}")
        if not isinstance(n["name"], str) or not n["name"]:
            _fail(w, "name must be a non-empty string")
        if n["kind"] == "sat":
            # null is allowed (a synthetic Walker run): positions are then matched by name
            if n["norad"] is not None and (not _is_int(n["norad"]) or n["norad"] <= 0):
                _fail(w, "a satellite's norad must be a positive integer or null")
        else:
            for key, lim in (("lat", 90.0), ("lon", 180.0)):
                v = n[key]
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not -lim <= v <= lim:
                    _fail(w, f"a ground station needs {key} in [-{lim}, {lim}]")
        sids.add(n["sid"])
        nodes[n["node_id"]] = NodeInfo(n["node_id"], n["kind"], n["sid"], n["norad"], n["name"],
                                       None if n["lat"] is None else float(n["lat"]),
                                       None if n["lon"] is None else float(n["lon"]))
        order.append(n["node_id"])
    return nodes, order


def _parse_faults(raw, nodes, where):
    if not isinstance(raw, list):
        _fail(where, "'faults' must be a list")
    out = []
    for i, f in enumerate(raw):
        w = f"{where}: faults[{i}]"
        if not isinstance(f, dict):
            _fail(w, "must be an object")
        for key in ("kind", "link", "node", "start_ns", "stop_ns", "params"):
            if key not in f:
                _fail(w, f"missing key {key!r}")
        if not isinstance(f["kind"], str) or not f["kind"]:
            _fail(w, "kind must be a non-empty string")
        link = f["link"]
        if link is not None:
            if (not isinstance(link, list) or len(link) != 2 or not all(_is_int(x) for x in link)
                    or any(x not in nodes for x in link)):
                _fail(w, "link must be null or [a, b] with two known node ids")
            link = (link[0], link[1])
        if f["node"] is not None and f["node"] not in nodes:
            _fail(w, "node must be null or a known node id")
        if not _is_int(f["start_ns"]) or not _is_int(f["stop_ns"]) or f["stop_ns"] < f["start_ns"]:
            _fail(w, "start_ns / stop_ns must be integers with start <= stop")
        if not isinstance(f["params"], dict):
            _fail(w, "params must be an object")
        out.append(Fault(f["kind"], link, f["node"], f["start_ns"], f["stop_ns"], dict(f["params"])))
    return out


def read_run_json(run_dir):
    """Read and check run.json; returns (dict, nodes, node_order, faults, t0_unix_ns)."""
    run_dir = Path(run_dir)
    path = run_dir / RUN_FILE
    if not path.is_file():
        raise TraceFormatError(f"{run_dir}: no {RUN_FILE} (not a chronoroute.trace/1 run folder)")
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TraceFormatError(f"{path}: not JSON ({exc})") from None
    where = str(path)
    if not isinstance(run, dict):
        _fail(where, "must be a JSON object")
    missing = [k for k in RUN_KEYS if k not in run]
    if missing:
        _fail(where, f"missing keys {missing}")
    if run["schema"] != TRACE_SCHEMA:
        _fail(where, f"schema is {run['schema']!r}, expected {TRACE_SCHEMA!r}")
    if run["tool"] not in TRACE_TOOLS:
        _fail(where, f"tool must be one of {TRACE_TOOLS}")
    try:
        t0_unix_ns = parse_utc_z(run["t0_utc"])
    except ValueError as exc:
        _fail(where, f"t0_utc: {exc}")
    if not _is_int(run["t0_gps_ns"]):
        _fail(where, "t0_gps_ns must be an integer")
    # One timebase (spec/tcrh-v1.md section 4): the GPS time must be the UTC time + 18 s.
    if scheduler.utc_ns_to_gps_ns(t0_unix_ns) != run["t0_gps_ns"]:
        _fail(where, f"t0_gps_ns {run['t0_gps_ns']} is not t0_utc {run['t0_utc']} in GPS time "
                     f"({scheduler.utc_ns_to_gps_ns(t0_unix_ns)})")
    if not _is_int(run["unit_code"]) or not 0 <= run["unit_code"] <= 3:
        _fail(where, "unit_code must be 0..3")
    for key in ("snapshot_id", "bundle"):
        if run[key] is not None and not isinstance(run[key], str):
            _fail(where, f"{key} must be a string or null")
    nodes, order = _parse_nodes(run["nodes"], where)
    pos = run["positions"]
    if not isinstance(pos, dict) or pos.get("source") not in POSITION_SOURCES \
            or not isinstance(pos.get("path"), str):
        _fail(where, f"positions must be {{'source': one of {POSITION_SOURCES}, 'path': str}}")
    faults = _parse_faults(run["faults"], nodes, where)
    if not isinstance(run["labels"], dict):
        _fail(where, "labels must be an object")
    return run, nodes, order, faults, t0_unix_ns


def _parse_event(obj, lineno, nodes, problems):
    where = f"{EVENTS_FILE}:{lineno}"
    if not isinstance(obj, dict):
        _fail(where, "not a JSON object")
    for key in ("t", "ev", "pkt", "flow", "node"):
        if key not in obj:
            _fail(where, f"missing key {key!r}")
    extra = set(obj) - set(EVENT_KEYS)
    if extra and len(problems) < 50:
        problems.append(f"{where}: unknown keys {sorted(extra)} ignored")
    if obj["ev"] not in EVENT_TYPES:
        _fail(where, f"ev {obj['ev']!r} is not one of {EVENT_TYPES}")
    for key in ("t", "pkt", "flow", "node"):
        if not _is_int(obj[key]):
            _fail(where, f"{key} must be an integer")
    if obj["t"] < 0:
        _fail(where, "t must be >= 0 (ns since t0)")
    if obj["node"] not in nodes:
        _fail(where, f"node {obj['node']} is not in run.json nodes")
    nxt = obj.get("next")
    if nxt is not None and (not _is_int(nxt) or nxt not in nodes):
        _fail(where, f"next {nxt!r} is not null or a node in run.json")
    for key in ("sl", "flags"):
        v = obj.get(key)
        if not _opt_int(v) or (v is not None and not 0 <= v <= 255):
            _fail(where, f"{key} must be null or 0..255")
    for key in ("deadline_u", "now_u"):
        v = obj.get(key)
        if not _opt_int(v) or (v is not None and not 0 <= v < 2 ** 32):
            _fail(where, f"{key} must be null or a 32-bit unsigned integer")
    reason = obj.get("reason")
    if reason is not None and not isinstance(reason, str):
        _fail(where, "reason must be null or a string")
    hx = obj.get("hex")
    if hx is not None:
        if not isinstance(hx, str) or len(hx) % 2 or len(hx) < 16:
            _fail(where, "hex must be null or an even-length hex string of at least 8 bytes")
        try:
            bytes.fromhex(hx)
        except ValueError:
            _fail(where, "hex is not hexadecimal")
    return Event(obj["t"], obj["ev"], obj["pkt"], obj["flow"], obj["node"], nxt, obj.get("sl"),
                 obj.get("flags"), obj.get("deadline_u"), obj.get("now_u"), reason, hx)


def _check_packet(track, problems):
    """Soft consistency checks of one packet (reported, not fatal)."""
    ev = track.events
    if ev[0].ev != "send":
        problems.append(f"packet {track.pkt}: first event is {ev[0].ev!r}, not 'send'")
    if any(e.flow != track.flow for e in ev):
        problems.append(f"packet {track.pkt}: events disagree on the flow id")
    ends = [e for e in ev if e.ev in ("deliver", "drop")]
    if len(ends) > 1:
        problems.append(f"packet {track.pkt}: {len(ends)} final events")
    elif ends and ends[0] is not ev[-1]:
        problems.append(f"packet {track.pkt}: events after its final '{ends[0].ev}'")
    # Every arrival should be at the node the previous hop said it would send to.
    expected = ev[0].next if ev[0].ev == "send" else None
    for e in ev[1:]:
        if e.ev == "hop":
            if expected is not None and e.node != expected:
                problems.append(f"packet {track.pkt}: arrived at node {e.node} at t={e.t} but the "
                                f"previous hop sent it to {expected}")
                break
            expected = e.next
        elif e.ev == "fallback" and e.next is not None:
            expected = e.next


def load_trace(run_dir, *, max_events=None):
    """Read and check a chronoroute.trace/1 run folder (see the module docstring)."""
    run_dir = Path(run_dir)
    run, nodes, order, faults, t0_unix_ns = read_run_json(run_dir)
    path = run_dir / EVENTS_FILE
    if not path.is_file():
        raise TraceFormatError(f"{run_dir}: no {EVENTS_FILE}")
    problems = []
    events, packets = [], {}
    last_key = None
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                raise TraceFormatError(f"{EVENTS_FILE}:{lineno}: not JSON ({exc})") from None
            e = _parse_event(obj, lineno, nodes, problems)
            key = (e.t, e.pkt)
            if last_key is not None and key < last_key:
                raise TraceFormatError(f"{EVENTS_FILE}:{lineno}: events are not sorted by (t, pkt): "
                                       f"{key} after {last_key}")
            last_key = key
            events.append(e)
            track = packets.get(e.pkt)
            if track is None:
                track = packets[e.pkt] = PacketTrack(e.pkt, e.flow)
            track.events.append(e)
            if max_events is not None and len(events) >= max_events:
                problems.append(f"stopped after {max_events} events (max_events)")
                break
    for track in packets.values():
        _check_packet(track, problems)
    labels = dict(run["labels"])
    return Trace(run_dir=run_dir, run=run, nodes=nodes, node_ids=order, events=events,
                 packets=packets, faults=faults, labels=labels, t0_utc=run["t0_utc"],
                 t0_unix_ns=t0_unix_ns, t0_gps_ns=run["t0_gps_ns"], unit_code=run["unit_code"],
                 problems=problems)


# ----------------------------------------------------------------------- snapshot

@dataclass(frozen=True)
class ElementInfo:
    """The REAL element set of one satellite, for the pick panel."""
    norad: int
    name: str
    epoch: str
    epoch_ns: int
    inclination_deg: float
    raan_deg: float
    eccentricity: float
    mean_motion_rev_day: float
    source: str


class _OmmFileFleet:
    """A plain OMM JSON array (e.g. a python-sim run's synthetic_omm.json) in Fleet's shape."""

    def __init__(self, path, snapshot_id=None):
        from ..data import snapshot
        self.path = Path(path)
        self.folder = self.path.parent
        self.records = omm.records_from_objects(omm.parse_omm_json(self.path.read_bytes()))
        self.satrecs = {r.norad: omm.make_satrec(r) for r in self.records}
        self.snapshot_id = snapshot_id or self.path.stem
        self.fetched_ns = None
        self.source = snapshot.SourceInfo(key="file", name=f"OMM file {self.path.name}", url="",
                                          raw_file=self.path.name, headers_file="", attribution="")


class SnapshotFleet:
    """Element sets loaded once (records, Satrecs) for SGP4 positions and the pick panel.

    path may be a pinned snapshot folder, a raw element file inside one (what a
    python-sim run.json names: data/pinned/<id>/starlink_supgp.json picks SupGP,
    starlink_gp.json picks GP), or a plain OMM JSON file (a synthetic Walker run's
    synthetic_omm.json).
    """

    def __init__(self, path, source="supgp", snapshot_id=None):
        from ..data import snapshot
        path = Path(path)
        if path.is_file():
            by_file = {snapshot.SOURCES[k].raw_file: k for k in snapshot.OMM_SOURCES}
            if path.name in by_file and (path.parent / snapshot.SHA256SUMS).is_file():
                self.folder = path.parent
                self.fleet = snapshot.load_pinned(self.folder, by_file[path.name])
            else:
                self.fleet = _OmmFileFleet(path, snapshot_id)
                self.folder = self.fleet.folder
        else:
            self.folder = path
            self.fleet = snapshot.load_snapshot(self.folder, source)
        self.by_norad = {r.norad: r for r in self.fleet.records}

    @property
    def snapshot_id(self):
        return self.fleet.snapshot_id

    @property
    def source_name(self):
        return self.fleet.source.name

    @property
    def pinned_folder(self):
        """The data/pinned/<id> folder (for manifests), or None for a plain OMM file."""
        return self.folder if (Path(self.folder) / "SHA256SUMS").is_file() else None

    def norad_by_name(self, name):
        hits = [r.norad for r in self.fleet.records if r.name == name]
        return hits[0] if len(hits) == 1 else None

    def elements(self, norad):
        r = self.by_norad.get(int(norad))
        if r is None:
            return None
        return ElementInfo(r.norad, r.name, r.epoch + "Z", r.epoch_ns, r.inclination, r.raan,
                           r.eccentricity, r.mean_motion, self.fleet.source.name)

    def satellite_array(self, norads):
        from ..orbit.propagate import SatelliteArray
        missing = [int(n) for n in norads if int(n) not in self.by_norad]
        if missing:
            raise KeyError(f"snapshot {self.snapshot_id} has no element set for NORAD {missing[:5]}"
                           f"{' ...' if len(missing) > 5 else ''} ({len(missing)} missing)")
        return SatelliteArray([self.by_norad[int(n)] for n in norads], satrecs=self.fleet.satrecs)


class SnapshotPositions:
    """SGP4 at exactly the requested instant (no interpolation): REAL physics + REAL code."""

    kind = "snapshot"

    def __init__(self, snapshot_fleet, norads):
        self.snapshot = snapshot_fleet
        self.norads = [int(n) for n in norads]
        self.sats = snapshot_fleet.satellite_array(self.norads)
        self.failed = 0

    def sat_ecef_km(self, utc_ns):
        state = self.sats.propagate([int(utc_ns)], geodetic=False)
        self.failed = int((~state.ok[:, 0]).sum())
        return state.r_ecef[:, 0, :]

    def describe(self):
        return f"snapshot {self.snapshot.snapshot_id}, SGP4"


def _hermite(p0, p1, m0, m1, s):
    """Cubic Hermite between p0 and p1 with tangents m0, m1 (per unit s), s in [0, 1]."""
    s2, s3 = s * s, s * s * s
    return ((2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * m0
            + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * m1)


class BundlePositions:
    """positions.csv of a scenario bundle (docs/bundle-format.md section 2.7), interpolated.

    Samples are every position_step_ms (1 s). Between samples the position is a
    cubic Hermite curve whose tangents are second-order differences of the samples
    (Catmull-Rom inside the window): smooth (no kink at a sample) and close to SGP4.
    Measured on the milestone's small bundle, all 2,847 satellites, at quarter and
    half seconds: at most 17 mm from SGP4, where straight lines between the samples
    would be off by up to 1.0 m (sim/tests/test_viz_sources.py checks < 5 cm).
    Outside the window the first/last sample is held and `clamped` is set, so the
    HUD can say so.
    """

    kind = "bundle"

    def __init__(self, positions_csv, sat_node_ids, t0_unix_ns):
        self.path = Path(positions_csv)
        self.t0_unix_ns = int(t0_unix_ns)
        index = {int(n): i for i, n in enumerate(sat_node_ids)}
        times, rows = [], {}
        with open(self.path, encoding="utf-8") as fh:
            header = fh.readline().strip().split(",")
            if header != ["t_ms", "node_id", "x_m", "y_m", "z_m"]:
                raise ValueError(f"{self.path}: header {header} is not t_ms,node_id,x_m,y_m,z_m")
            for line in fh:
                t_ms, node, x, y, z = line.rstrip("\n").split(",")
                node = int(node)
                if node not in index:
                    continue
                t_ms = int(t_ms)
                if not times or times[-1] != t_ms:
                    times.append(t_ms)
                    rows[t_ms] = np.full((len(index), 3), np.nan)
                rows[t_ms][index[node]] = (float(x) / 1000.0, float(y) / 1000.0, float(z) / 1000.0)
        if len(times) < 2:
            raise ValueError(f"{self.path}: need at least two position samples")
        steps = np.diff(times)
        if np.any(steps != steps[0]):
            raise ValueError(f"{self.path}: position samples are not evenly spaced")
        self.t_ms = np.array(times, dtype=np.int64)
        self.step_ms = int(steps[0])
        self.pos = np.stack([rows[t] for t in times])            # (T, N, 3) km
        missing = int(np.isnan(self.pos[0, :, 0]).sum())
        if missing:
            raise ValueError(f"{self.path}: {missing} satellites have no row at t_ms={times[0]}")
        self.clamped = False
        self.failed = 0

    @property
    def window_ns(self):
        return (int(self.t_ms[0]) * NS_PER_MS, int(self.t_ms[-1]) * NS_PER_MS)

    def covers(self, utc_ns):
        lo, hi = self.window_ns
        return lo <= utc_ns - self.t0_unix_ns <= hi

    def sat_ecef_km(self, utc_ns):
        t = (int(utc_ns) - self.t0_unix_ns) / NS_PER_MS               # ms after t0
        T = len(self.t_ms)
        x = (t - self.t_ms[0]) / self.step_ms                           # in samples
        self.clamped = x < 0 or x > T - 1
        if x <= 0:
            return self.pos[0].copy()
        if x >= T - 1:
            return self.pos[-1].copy()
        k = int(math.floor(x))
        s = x - k
        return _hermite(self.pos[k], self.pos[k + 1], self._tangent(k), self._tangent(k + 1), s)

    def _tangent(self, k):
        """Velocity at sample k in km per sample step, to second order everywhere.

        Central difference inside; at the two ends the second-order one-sided formula
        (a plain one-sided difference there would leave half of the chord's sag, about
        0.5 m, in the first and last second of the window: measured).
        """
        p, T = self.pos, len(self.pos)
        if 0 < k < T - 1:
            return (p[k + 1] - p[k - 1]) / 2
        if T < 3:
            return p[1] - p[0]
        if k == 0:
            return (-3 * p[0] + 4 * p[1] - p[2]) / 2
        return (3 * p[T - 1] - 4 * p[T - 2] + p[T - 3]) / 2

    def describe(self):
        return f"bundle {self.path.parent.name}/positions.csv, interpolated"


class NodePositions:
    """ECEF km of every node of a run at a UTC instant (satellites move, ground stations do not).

    `primary` gives the satellites; `fallback` (optional) is used when the instant is
    outside the primary's window (a bundle covers only its run window, but the orbit
    clock may run on: then SGP4 from the snapshot takes over, which is what the
    bundle's samples were computed with in the first place).
    """

    def __init__(self, node_ids, kinds, gs_ecef, primary, fallback=None):
        self.node_ids = list(node_ids)
        self.index = {n: i for i, n in enumerate(self.node_ids)}
        self.kinds = list(kinds)
        self.sat_rows = np.array([i for i, k in enumerate(self.kinds) if k == "sat"], dtype=np.int64)
        self.gs_rows = np.array([i for i, k in enumerate(self.kinds) if k == "gs"], dtype=np.int64)
        self.gs_ecef = np.asarray(gs_ecef, dtype=float).reshape(-1, 3)
        self.primary = primary
        self.fallback = fallback
        self.last_source = None

    def ecef_km(self, utc_ns):
        out = np.zeros((len(self.node_ids), 3))
        src = self.primary
        if (self.fallback is not None and isinstance(self.primary, BundlePositions)
                and not self.primary.covers(utc_ns)):
            src = self.fallback
        if len(self.sat_rows):
            out[self.sat_rows] = src.sat_ecef_km(utc_ns)
        if len(self.gs_rows):
            out[self.gs_rows] = self.gs_ecef
        self.last_source = src
        return out

    def describe(self):
        src = self.last_source or self.primary
        text = src.describe()
        if isinstance(src, BundlePositions) and src.clamped:
            text += " (held: outside the bundle window)"
        return text

    @property
    def failed(self):
        src = self.last_source or self.primary
        return getattr(src, "failed", 0)


def gs_ecef_of(nodes):
    """Ground stations on the WGS84 ellipsoid (height 0), as the bundle places them."""
    return [tuple(frames.geodetic_to_ecef(n.lat, n.lon, 0.0)) for n in nodes]


def sat_norads(trace, snapshot):
    """NORAD id of every satellite node: run.json's, or (null there) the element set with that name."""
    out = []
    for i in trace.sat_ids():
        n = trace.nodes[i]
        norad = n.norad
        if norad is None and snapshot is not None:
            norad = snapshot.norad_by_name(n.name)
        if norad is None:
            raise TraceFormatError(f"satellite node {i} ({n.name}) has no NORAD id and no element set "
                                   "with its name")
        out.append(int(norad))
    return out


def positions_for_trace(trace, snapshot=None):
    """NodePositions for a trace, from its run.json 'positions' entry (module docstring).

    snapshot: an already loaded SnapshotFleet (or None to load the run's own one:
    the 'positions' path when its source is 'snapshot', else data/pinned/<snapshot_id>).
    """
    sat_ids = trace.sat_ids()
    gs = [trace.nodes[i] for i in trace.gs_ids()]
    kinds = [trace.nodes[i].kind for i in trace.node_ids]
    gs_ecef = gs_ecef_of(gs)
    if snapshot is None:
        target = resolve_snapshot_dir(trace.snapshot_id)
        if trace.run["positions"]["source"] == "snapshot":
            p = resolve_path(trace.run["positions"]["path"], trace.run_dir)
            if p is not None and p.exists():
                target = p
        snapshot = (SnapshotFleet(target, snapshot_id=trace.snapshot_id)
                    if target is not None and Path(target).exists() else None)
    if any(trace.nodes[i].norad is None for i in sat_ids) and snapshot is None:
        raise FileNotFoundError("satellite nodes without NORAD ids need the run's element file")
    norads = sat_norads(trace, snapshot) if snapshot is not None else \
        [trace.nodes[i].norad for i in sat_ids]
    trace.sat_norad = dict(zip(sat_ids, norads))
    src = trace.run["positions"]["source"]
    if src == "bundle":
        path = resolve_path(trace.run["positions"]["path"], trace.run_dir)
        if path.is_dir():
            path = path / "positions.csv"
        if not path.is_file():
            if snapshot is None:
                raise FileNotFoundError(f"positions file {path} not found and no snapshot to "
                                        "compute positions from")
            primary = SnapshotPositions(snapshot, norads)
            fallback = None
        else:
            primary = BundlePositions(path, sat_ids, trace.t0_unix_ns)
            fallback = SnapshotPositions(snapshot, norads) if snapshot is not None else None
    else:
        if snapshot is None:
            raise FileNotFoundError(f"snapshot {trace.snapshot_id!r} not found: pass --snapshot DIR")
        primary = SnapshotPositions(snapshot, norads)
        fallback = None
    return NodePositions(trace.node_ids, kinds, gs_ecef, primary, fallback), snapshot


# ----------------------------------------------------------------------- laser links

@dataclass
class IslSet:
    """Candidate laser links as rows into a node list (MODELLED Grid-4)."""
    a: np.ndarray             # (L,) row index of one end
    b: np.ndarray
    kind: np.ndarray          # 0 intra, 1 cross
    source: str               # where the pairs came from (shown in the HUD / docs)
    params: object            # isl_grid4.Grid4Params used for the up/down rule

    def __len__(self):
        return len(self.a)


def grid4_params_from_scenario(scenario):
    isl = scenario.get("models", {}).get("isl", {})
    return isl_grid4.Grid4Params(
        polar_cutoff_deg=float(isl.get("polar_cutoff_deg", 70.0)),
        min_grazing_alt_km=float(isl.get("min_grazing_alt_km", 80.0)),
        cross_max_du_factor=float(isl.get("cross_max_du_factor", 1.0)),
        max_range_km=isl.get("max_range_km"))


def isl_from_bundle(bundle_dir, row_of_node):
    """isl.csv of a bundle (docs/bundle-format.md section 2.5): exactly the run's candidate links."""
    bundle_dir = Path(bundle_dir)
    a, b, kind = [], [], []
    with open(bundle_dir / "isl.csv", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        if header != ["link_id", "a", "b", "kind"]:
            raise ValueError(f"{bundle_dir}/isl.csv: unexpected header {header}")
        for _link, x, y, k in reader:
            x, y = int(x), int(y)
            if x in row_of_node and y in row_of_node:
                a.append(row_of_node[x])
                b.append(row_of_node[y])
                kind.append(0 if k == "intra" else 1)
    params = isl_grid4.Grid4Params()
    scen = bundle_dir / "scenario.json"
    if scen.is_file():
        params = grid4_params_from_scenario(json.loads(scen.read_text(encoding="utf-8")))
    return IslSet(np.array(a, dtype=np.int64), np.array(b, dtype=np.int64),
                  np.array(kind, dtype=np.uint8), f"bundle {bundle_dir.name}/isl.csv", params)


def isl_from_snapshot(snapshot, reference_ns, row_of_norad, shell_id=None):
    """Grid-4 pairs recomputed with topo.isl_grid4 at reference_ns (the run start).

    shell_id None: the shell holding most of the given satellites.
    Pairs with an end outside row_of_norad are left out.
    """
    from ..orbit import planes
    geo = planes.build_fleet_geometry(snapshot.fleet.records, int(reference_ns),
                                      satrecs=snapshot.fleet.satrecs)
    if shell_id is None:
        wanted = set(row_of_norad)
        best, best_n = None, 0
        for sg in geo.shells:
            n = sum(1 for p in sg.planes for x in p.norads if x in wanted)
            if n > best_n:
                best, best_n = sg.shell_id, n
        if best is None:
            return IslSet(np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.uint8),
                          "no shell matches these satellites", isl_grid4.Grid4Params())
        shell_id = best
    params = isl_grid4.Grid4Params()
    pairs = isl_grid4.grid4_pairs(geo.shell(shell_id), int(reference_ns), params)
    keep = [(row_of_norad[int(x)], row_of_norad[int(y)], int(k))
            for x, y, k in zip(pairs.a, pairs.b, pairs.kind)
            if int(x) in row_of_norad and int(y) in row_of_norad]
    arr = np.array(keep, dtype=np.int64).reshape(-1, 3)
    return IslSet(arr[:, 0].copy(), arr[:, 1].copy(), arr[:, 2].astype(np.uint8),
                  f"Grid-4 of shell {shell_id} recomputed at {omm.format_utc_ns(int(reference_ns))}",
                  params)


def isl_up(isl, node_pos_km):
    """(L,) bool: is each candidate link up for these positions (the topology model's rule)."""
    if len(isl) == 0:
        return np.zeros(0, dtype=bool)
    pos = node_pos_km[:, None, :]
    _lat, _lon, _h = frames.ecef_to_geodetic(node_pos_km)
    up, _dist = isl_grid4.isl_state(isl.a, isl.b, isl.kind, pos, _lat[:, None], isl.params)
    return up[:, 0]


def links_near_path(isl, path_rows, depth=2):
    """Lite mode: indices of the links whose both ends are within `depth` link hops of the path."""
    if len(isl) == 0 or not path_rows:
        return np.zeros(0, dtype=np.int64)
    near = set(int(r) for r in path_rows)
    frontier = set(near)
    adj = {}
    for i, (x, y) in enumerate(zip(isl.a.tolist(), isl.b.tolist())):
        adj.setdefault(x, []).append(y)
        adj.setdefault(y, []).append(x)
    for _ in range(depth):
        nxt = set()
        for r in frontier:
            nxt.update(adj.get(r, ()))
        nxt -= near
        near |= nxt
        frontier = nxt
    mask = np.fromiter(((x in near and y in near) for x, y in zip(isl.a.tolist(), isl.b.tolist())),
                       dtype=bool, count=len(isl))
    return np.flatnonzero(mask)


# ----------------------------------------------------------------------- what a view needs

DEFAULT_CITIES = ("Chennai", "Mumbai", "London", "New York", "Singapore", "Sydney", "Tokyo",
                  "Johannesburg", "Sao Paulo", "Frankfurt")


@dataclass
class ViewerData:
    """Everything the 3D globe and the 2D map draw, independent of the drawing library."""

    mode: str                    # "trace" or "snapshot"
    trace: object                # Trace or None
    snapshot: object             # SnapshotFleet or None
    node_ids: list
    kinds: list                  # "sat" / "gs" per row
    names: list
    sids: list                   # int or None per row
    norads: list                 # int or None per row
    positions: NodePositions
    isl: IslSet
    start_utc_ns: int
    t0_unix_ns: int
    labels: dict
    snapshot_id: str | None
    cities: list                 # [(name, lat, lon)] drawn as labelled markers
    shell_id: str | None = None
    notes: list = field(default_factory=list)

    @property
    def row_of_node(self):
        return {n: i for i, n in enumerate(self.node_ids)}

    @property
    def sat_rows(self):
        return [i for i, k in enumerate(self.kinds) if k == "sat"]

    @property
    def n_sats(self):
        return sum(1 for k in self.kinds if k == "sat")

    @property
    def faults(self):
        return self.trace.faults if self.trace is not None else []


def _city_rows(names):
    from ..data import cities as cities_mod
    by_name = {c.name: c for c in cities_mod.load_cities()}
    out = []
    for n in names:
        if n not in by_name:
            raise KeyError(f"unknown city {n!r} (data/static/cities.csv)")
        c = by_name[n]
        out.append((c.name, c.lat_deg, c.lon_deg))
    return out


def load_viewer_data(*, trace_dir=None, snapshot_dir=None, shell=None, cities=None,
                     start_utc_ns=None):
    """Load a trace (with its positions and laser links) or a snapshot-only fleet view."""
    if trace_dir is None and snapshot_dir is None:
        raise ValueError("give a trace folder or a snapshot folder")
    notes = []
    if trace_dir is not None:
        trace = load_trace(trace_dir)
        snap = SnapshotFleet(snapshot_dir) if snapshot_dir is not None else None
        positions, snap = positions_for_trace(trace, snap)
        rows = {n: i for i, n in enumerate(trace.node_ids)}
        # Laser links: the bundle the run replayed, or the bundle copy its positions point at
        # (what cr trace from-ns3 writes), or Grid-4 recomputed from the snapshot at t0.
        bundle = None
        candidates = [trace.run.get("bundle")]
        if trace.run["positions"]["source"] == "bundle":
            candidates.append(trace.run["positions"]["path"])
        for cand in candidates:
            p = resolve_path(cand, trace.run_dir) if cand else None
            if p is not None and (p / "isl.csv").is_file():
                bundle = p
                break
        engine_info = trace.run.get("engine") if isinstance(trace.run.get("engine"), dict) else {}
        if bundle is not None:
            isl = isl_from_bundle(bundle, rows)
        elif snap is not None:
            # Same code and instant as the run (Grid-4 pairs are chosen at t0).
            row_of_norad = {trace.sat_norad[n]: rows[n] for n in trace.sat_ids()}
            isl = isl_from_snapshot(snap, trace.t0_unix_ns, row_of_norad, engine_info.get("shell"))
        else:
            isl = IslSet(np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.uint8),
                         "not available (no bundle isl.csv and no snapshot)", isl_grid4.Grid4Params())
            notes.append("laser links not drawn: no bundle isl.csv and no snapshot")
        city_names = [trace.nodes[n].name for n in trace.gs_ids()]
        extra = [c for c in (cities or ()) if c not in city_names]
        city_rows = [(trace.nodes[n].name, trace.nodes[n].lat, trace.nodes[n].lon)
                     for n in trace.gs_ids()] + _city_rows(extra)
        first = min((p.t_start for p in trace.packets.values()), default=0)
        start = trace.t0_unix_ns + first if start_utc_ns is None else int(start_utc_ns)
        return ViewerData(
            mode="trace", trace=trace, snapshot=snap, node_ids=list(trace.node_ids),
            kinds=[trace.nodes[n].kind for n in trace.node_ids],
            names=[trace.nodes[n].name for n in trace.node_ids],
            sids=[trace.nodes[n].sid for n in trace.node_ids],
            norads=[trace.sat_norad.get(n) for n in trace.node_ids], positions=positions, isl=isl,
            start_utc_ns=start, t0_unix_ns=trace.t0_unix_ns, labels=dict(trace.labels),
            snapshot_id=trace.snapshot_id, cities=city_rows, notes=notes + list(trace.problems[:5]))

    snap = SnapshotFleet(snapshot_dir)
    start = snap.fleet.fetched_ns if start_utc_ns is None else int(start_utc_ns)
    records = list(snap.fleet.records)
    shell_id = None
    if shell and shell != "all":
        from ..orbit import planes
        geo = planes.build_fleet_geometry(records, start, satrecs=snap.fleet.satrecs)
        sg = geo.shell(shell)
        # The satellites in planes: the Grid-4 set that bundles and traces of this
        # shell use. Off-grid members (plane fragments) have no laser-link slot.
        members = sorted(n for p in sg.planes for n in p.norads)
        off_grid = sg.shell.count - len(members)
        if off_grid:
            notes.append(f"{off_grid} off-grid members of {shell} not drawn (no Grid-4 slot, as in bundles)")
        records = [snap.by_norad[n] for n in members]
        shell_id = shell
    norads = [r.norad for r in records]
    sids = [None] * len(norads)
    try:
        from ..route import sids as sids_mod
        reg = sids_mod.SidRegistry.load()
        sids = [reg.satellite_sid(n) if n in reg else None for n in norads]
    except (OSError, ValueError, KeyError):
        notes.append("SID registry not readable: SIDs not shown")
    positions = NodePositions(list(range(len(norads))), ["sat"] * len(norads), [],
                              SnapshotPositions(snap, norads))
    row_of_norad = {n: i for i, n in enumerate(norads)}
    if shell_id is not None:
        isl = isl_from_snapshot(snap, start, row_of_norad, shell_id)
    else:
        isl = IslSet(np.zeros(0, np.int64), np.zeros(0, np.int64), np.zeros(0, np.uint8),
                     "whole fleet: pass --shell to draw one shell's Grid-4 links",
                     isl_grid4.Grid4Params())
    labels = labels_mod.pick("satellite_positions_sgp4", "orbital_elements", "isl_topology_grid4",
                             "link_rate_and_queues", "city_coordinates")
    return ViewerData(
        mode="snapshot", trace=None, snapshot=snap, node_ids=list(range(len(norads))),
        kinds=["sat"] * len(norads), names=[r.name for r in records], sids=sids, norads=norads,
        positions=positions, isl=isl, start_utc_ns=start, t0_unix_ns=start, labels=labels,
        snapshot_id=snap.snapshot_id, cities=_city_rows(cities or DEFAULT_CITIES),
        shell_id=shell_id, notes=notes)


# ----------------------------------------------------------------------- engine (live mode)

def engine_api():
    """The engine's re-run hook (ENGINE_HOOK), or None: the viewer is then replay-only."""
    module, name = ENGINE_HOOK
    try:
        mod = importlib.import_module(module)
    except ImportError:
        return None
    hook = getattr(mod, name, None)
    return hook if callable(hook) else None


__all__ = [
    "TRACE_SCHEMA", "EVENT_TYPES", "EVENT_KEYS", "RUN_KEYS", "LITE_THRESHOLD", "C_KM_PER_NS",
    "TraceFormatError", "NodeInfo", "Event", "Fault", "PacketTrack", "Trace", "read_run_json",
    "load_trace", "parse_utc_z", "resolve_path", "resolve_snapshot_dir",
    "ElementInfo", "SnapshotFleet", "SnapshotPositions", "BundlePositions", "NodePositions",
    "gs_ecef_of", "positions_for_trace", "IslSet", "isl_from_bundle", "isl_from_snapshot",
    "isl_up", "links_near_path", "engine_api",
]

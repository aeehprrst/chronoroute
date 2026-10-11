"""
load.py
-------
Read a finished run folder (spec/trace-v1.md section 5 engine outputs, plus
the baseline extras of baselines/run.py) into flat numpy arrays.

Variable-length per-packet lists (the path, the arrival clocks, ...) are kept
as one flat array plus an offsets array ("CSR"): packet i's values are
flat[ptr[i]:ptr[i+1]]. A 600 s run has ~10^6 packets and ~10^7 hops; Python
lists of lists would need gigabytes, these arrays need tens of megabytes.

    run = load_run(dir)
    run.n, run.send_ns, run.delivered, run.path(i), run.arr_ns(i), ...

Missing optional files are allowed (a plain `cr run` folder has no
scheme_packets.csv.gz); a function that needs them says so.
"""

import csv
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

OUTCOME_CODES = {"delivered": 0, "dropped": 1, "no_route": 2, "unfinished": 3}


def _ints(text):
    return [int(x) for x in text.split()] if text else []


class Ragged:
    """Variable-length integer lists as (flat, ptr)."""

    __slots__ = ("flat", "ptr")

    def __init__(self, lists_text, dash=-1):
        lengths = np.zeros(len(lists_text) + 1, dtype=np.int64)
        tokens = []
        for i, s in enumerate(lists_text):
            if s:
                parts = s.split()
                lengths[i + 1] = len(parts)
                tokens.extend(parts)
        np.cumsum(lengths, out=lengths)
        self.ptr = lengths
        if tokens:
            self.flat = np.array([dash if t == "-" else int(t) for t in tokens], dtype=np.int64)
        else:
            self.flat = np.zeros(0, dtype=np.int64)

    def __getitem__(self, i):
        return self.flat[self.ptr[i]:self.ptr[i + 1]]

    def length(self, i):
        return int(self.ptr[i + 1] - self.ptr[i])

    def lengths(self):
        return np.diff(self.ptr)


@dataclass
class RunData:
    dir: Path
    run: dict
    n: int
    pkt: np.ndarray
    flow: np.ndarray
    seq: np.ndarray
    send_ns: np.ndarray
    outcome: np.ndarray          # OUTCOME_CODES
    reason: list                 # drop reason text per packet ('' if none)
    latency_ns: np.ndarray       # -1 when not delivered
    hops: np.ndarray
    paths: Ragged
    dev: np.ndarray
    dev_hop: np.ndarray          # -1 none
    first_late: np.ndarray       # -1 none
    arrival_u: Ragged
    deadline_u: Ragged           # -1 where the node did not check ('-')
    greedy: np.ndarray
    fallback_reason: list
    row_from_ms: np.ndarray      # -1 none
    wire: np.ndarray
    extras: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=dict)
    control: dict | None = None
    detections: list = field(default_factory=list)

    # ------------------------------------------------------------ convenience
    @property
    def engine(self):
        return self.run.get("engine", {})

    @property
    def faults(self):
        return self.run.get("faults", [])

    @property
    def flows(self):
        return self.run.get("flows", [])

    @property
    def delivered(self):
        return self.outcome == 0

    @property
    def scheme(self):
        return self.run.get("scheme", {"name": "chronoroute"})

    def path(self, i):
        return self.paths[i]

    def has_extras(self):
        return bool(self.extras)

    def arr_ns(self, i):
        """Arrival times (ns) at path[1:], aligned with it (needs scheme_packets.csv.gz)."""
        return self.extras["arrival_ns"][i]

    def node_times(self, i):
        """(nodes, times): path nodes and the time the packet was at each (send time for the source)."""
        nodes = self.paths[i]
        times = np.empty(len(nodes), dtype=np.int64)
        times[0] = self.send_ns[i]
        if len(nodes) > 1:
            times[1:] = self.extras["arrival_ns"][i]
        return nodes, times


def _read_csv_gz(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        rd = csv.reader(fh)
        header = next(rd)
        cols = {h: [] for h in header}
        names = list(header)
        width = len(names)
        for row in rd:
            if len(row) < width:
                row = row + [""] * (width - len(row))       # trailing empty fields
            for h, v in zip(names, row):
                cols[h].append(v)
    return cols


def _int_col(values, missing=-1):
    return np.array([int(v) if v != "" else missing for v in values], dtype=np.int64)


def read_schedule(path):
    """{(flow, valid_from_ms): row} with path, sids, budgets and predicted hop delays (ints)."""
    out = {}
    if not Path(path).is_file():
        return out
    cols = _read_csv_gz(path)
    for i in range(len(cols["flow_id"])):
        if not cols["path_nodes"][i]:
            continue
        key = (int(cols["flow_id"][i]), int(cols["valid_from_ms"][i]))
        out[key] = {"path": _ints(cols["path_nodes"][i]), "sids": _ints(cols["sids_fwd"][i]),
                    "budgets_ceil_ns": _ints(cols["cumulative_budgets_ns"][i]),
                    "hop_delays_ns": _ints(cols["predicted_hop_delays_ns"][i]),
                    "template": bytes.fromhex(cols["tcrh_hex_template"][i]),
                    "valid_to_ms": int(cols["valid_to_ms"][i])}
    return out


def read_detections(path):
    out = []
    if not Path(path).is_file():
        return out
    cols = _read_csv_gz(path)
    for i in range(len(cols["t_ns"])):
        out.append({"t_ns": int(cols["t_ns"][i]), "kind": cols["kind"][i], "a": int(cols["a"][i]),
                    "b": int(cols["b"][i]), "end": int(cols["end"][i]),
                    "value": int(cols["value"][i]) if cols["value"][i] != "" else None})
    return out


def load_run(run_dir):
    """RunData of a run folder (packets.csv.gz is required)."""
    d = Path(run_dir)
    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
    cols = _read_csv_gz(d / "packets.csv.gz")
    n = len(cols["pkt"])
    pkt = _int_col(cols["pkt"])
    if n and not np.array_equal(pkt, np.arange(n)):
        raise ValueError(f"{d}: packets.csv.gz rows must be packets 0..n-1 in order")
    rd = RunData(
        dir=d, run=run, n=n, pkt=pkt, flow=_int_col(cols["flow"]), seq=_int_col(cols["seq"]),
        send_ns=_int_col(cols["send_ns"]),
        outcome=np.array([OUTCOME_CODES[o] for o in cols["outcome"]], dtype=np.int8),
        reason=cols["reason"], latency_ns=_int_col(cols["latency_ns"]), hops=_int_col(cols["hops"]),
        paths=Ragged(cols["path"]), dev=_int_col(cols["dev"]), dev_hop=_int_col(cols["dev_hop"]),
        first_late=_int_col(cols["first_late_hop"]), arrival_u=Ragged(cols["arrival_u"]),
        deadline_u=Ragged(cols["deadline_u"]), greedy=_int_col(cols["greedy"]),
        fallback_reason=cols["fallback_reason"], row_from_ms=_int_col(cols["row_from_ms"]),
        wire=_int_col(cols["wire_bytes"]))
    ex = d / "scheme_packets.csv.gz"
    if ex.is_file():
        c = _read_csv_gz(ex)
        if len(c["pkt"]) != n:
            raise ValueError(f"{d}: scheme_packets.csv.gz and packets.csv.gz disagree on the packet count")
        rd.extras = {
            "arrival_ns": Ragged(c["arrival_ns"]), "hop_prop_ns": Ragged(c["hop_prop_ns"]),
            "hop_k": Ragged(c["hop_k"]), "hdr_bytes": _int_col(c["hdr_bytes"]),
            "l_det_ns": _int_col(c["l_det_ns"]), "oracle_ns": _int_col(c["oracle_ns"]),
            "oracle_hops": _int_col(c["oracle_hops"]), "oracle_ok": _int_col(c["oracle_ok"]),
            "tol_ns": _int_col(c["tol_ns"]), "lq_flag": c["lq_flag"], "lq_flags": _int_col(c["lq_flags"]),
            "e2e_late": _int_col(c["e2e_late"]), "drop_next": _int_col(c["drop_next"]),
            "link_down_at": c.get("link_down_at", [""] * n),
        }
        if "tx_ns" in c:
            # transmission start and transmitter wait of every hop, aligned with arrival_ns
            rd.extras["tx_ns"] = Ragged(c["tx_ns"])
            rd.extras["wait_ns"] = Ragged(c["wait_ns"])
        if "tx_loss_at" in c:
            # node:next:t:wait of a packet lost AT THE TRANSMITTER of node -> next (buffer_overflow,
            # arq_exhausted, a link end without a position); empty otherwise. Its path ends at node.
            rd.extras["tx_loss_at"] = c["tx_loss_at"]
    rd.schedule = read_schedule(d / "schedule.csv.gz")
    if (d / "control.json").is_file():
        rd.control = json.loads((d / "control.json").read_text(encoding="utf-8"))
    rd.detections = read_detections(d / "scheme_events.csv.gz")
    return rd


__all__ = ["OUTCOME_CODES", "Ragged", "RunData", "load_run", "read_schedule", "read_detections"]

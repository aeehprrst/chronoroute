"""
config.py
---------
The run configuration of `cr run --config FILE` (documented key by key in
docs/sim-config.md).

A config file is JSON, or YAML restricted to the plain subset below (the
project has no YAML library, so this module reads that subset itself):

    # comments
    key: value                  scalars: null ~ true false, integers, floats,
    nested:                              'single' / "double" quoted strings,
      key: value                         anything else is a plain string
    list:
      - item
      - key: value              (a list of mappings)
        other: value
    inline: [1, 2, "three"]     flow lists and flow mappings {a: 1, b: [2, 3]}

Anchors, tags, multi-line strings and multiple documents are refused with an
error, never guessed.

The loaded document is merged onto DEFAULTS: every key must be known (a typo
is an error, not a silently ignored setting) and every value is checked. The
merged, normalised dict is what the engine reads and what the manifest
records, so a run can always be repeated from its manifest.
"""

import copy
import json
import re
from fractions import Fraction
from pathlib import Path

from ..proto import timebase
from ..route import scheduler

POLICIES = ("greedy", "continue", "drop")
FALLBACKS = ("greedy_visited", "greedy_pure", "grid_detour", "none")
BACKGROUND_MODELS = ("none", "fluid", "poisson")
JITTER_MODELS = ("none", "j1")
TRACE_LEVELS = ("full", "sampled", "none")
INVARIANT_LEVELS = ("all", "sample", "off")
HOP_MODES = ("fast", "reference")
INGRESS_MODES = ("source", "encap")
SCENARIO_KINDS = ("real", "walker")
FAULT_KINDS = ("link_down", "link_renewal", "node_down", "node_renewal", "slow_processing",
               "rate_cut", "arq")

DEFAULTS = {
    "seed": 1,
    "scenario": {
        "kind": "real",
        "snapshot": "data/pinned/20261010T1358Z-celestrak",
        "source": "supgp",
        "shell": "53.2deg-463km",
        "preset": "C1",
        "start_utc": "2026-10-10T14:00:00Z",
        "duration_s": 60,
        "drain_s": 5,
        "step_ms": 100,
        "chunk_steps": 200,
        "cities": None,
        "gsl": {"min_elevation_deg": 25.0, "max_links_per_gs": 4, "policy": "sticky_top_k"},
        "isl": {"polar_cutoff_deg": 70.0, "max_range_km": None},
    },
    "traffic": {
        "flows": "science20",
        "rate_pps": 100,
        "payload_bytes": 200,
        "model": "cbr",
        "start_offset": "random",
        "ingress_mode": "source",
        "l2_overhead_bytes": 2,
    },
    "schedule": {
        "refresh_ms": 1000,
        "slack": "1.5",
        "unit_code": 1,
        "plan_links": "stable",
        "planner_processing_ns": 500_000,
    },
    "forwarding": {
        "policy": "greedy",
        "fallback": "greedy_visited",
        "hop_limit": 64,
        "processing_ns": 500_000,
        "jitter": {"model": "none", "mean_ns": 400_000},
        "link_rate_bps": 1_000_000_000,
        "buffer_ms": 20,
        "background": {"model": "none", "rho": 0.0, "packet_bytes": 1500, "window_ms": 10,
                       "links": "all"},
        "hop_mode": "fast",
        "verify_every": 0,
        "slow_queue_ns": None,
        # time for a node to notice that one of its links failed (loss of carrier); every
        # scheme's local decisions and the link-state schemes share it (docs/baselines.md 2.3)
        "carrier_detect_ms": 0,
    },
    "faults": [],
    "output": {
        "trace": "sampled",
        "sample_every": 100,
        "pcap": False,
        "pcap_max_packets": 20,
        "packets_csv": True,
        "invariants": "sample",
        "invariant_sample_every": 100,
    },
}

FLOW_KEYS = {"src", "dst", "rate_pps", "model", "start_offset", "send_times_ns", "payload_bytes"}
FAULT_KEYS = {
    "link_down": {"kind", "link", "link_names", "on_path", "start_s", "stop_s"},
    "link_renewal": {"kind", "unavailability", "mttr_s", "targets", "start_s", "stop_s"},
    "node_down": {"kind", "node", "node_name", "on_path", "start_s", "stop_s"},
    "node_renewal": {"kind", "unavailability", "mttr_s", "start_s", "stop_s"},
    "slow_processing": {"kind", "node", "node_name", "link", "link_names", "on_path", "delta_ns",
                        "start_s", "stop_s"},
    "rate_cut": {"kind", "link", "link_names", "on_path", "factor", "start_s", "stop_s"},
    "arq": {"kind", "link", "link_names", "on_path", "loss", "max_retries", "retry_extra_ns",
            "start_s", "stop_s"},
}
ON_PATH_KEYS = {"flow", "at_s", "position", "kind"}


class ConfigError(ValueError):
    """The configuration is invalid (unknown key, wrong type or value)."""


# =============================================================== YAML subset

_PLAIN_INT = re.compile(r"[-+]?[0-9]+")
_PLAIN_FLOAT = re.compile(r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][-+]?[0-9]+)?")


def _scalar(text, where):
    t = text.strip()
    if t == "":
        return None
    if t[0] in "&*!|>%@`":
        raise ConfigError(f"{where}: YAML feature {t[0]!r} is not supported (plain subset only)")
    if t[0] in "'\"":
        return _quoted(t, where)
    if t in ("null", "~", "Null", "NULL"):
        return None
    if t in ("true", "True", "TRUE"):
        return True
    if t in ("false", "False", "FALSE"):
        return False
    if _PLAIN_INT.fullmatch(t):
        return int(t)
    if _PLAIN_FLOAT.fullmatch(t):
        return float(t)
    return t


def _quoted(t, where):
    q = t[0]
    if len(t) < 2 or t[-1] != q:
        raise ConfigError(f"{where}: unterminated string {t!r}")
    body = t[1:-1]
    if q == "'":
        return body.replace("''", "'")
    try:
        return json.loads(t)
    except ValueError as exc:
        raise ConfigError(f"{where}: bad double-quoted string {t!r}: {exc}") from None


def _strip_comment(line):
    """Remove a trailing # comment that is outside quotes."""
    out, q = [], None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            break
        out.append(ch)
    return "".join(out).rstrip()


class _Flow:
    """Recursive-descent parser for flow collections: [a, b], {k: v}."""

    def __init__(self, text, where):
        self.s, self.i, self.where = text, 0, where

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self):
        self.ws()
        if self.i >= len(self.s):
            raise ConfigError(f"{self.where}: unexpected end of flow collection")
        ch = self.s[self.i]
        if ch == "[":
            return self.seq()
        if ch == "{":
            return self.map()
        if ch in "'\"":
            j = self.i + 1
            while j < len(self.s):
                if self.s[j] == ch:
                    if ch == "'" and j + 1 < len(self.s) and self.s[j + 1] == "'":
                        j += 2
                        continue
                    if ch == '"' and self.s[j - 1] == "\\":
                        j += 1
                        continue
                    break
                j += 1
            tok = self.s[self.i:j + 1]
            self.i = j + 1
            return _quoted(tok, self.where)
        j = self.i
        while j < len(self.s) and self.s[j] not in ",]}:":
            j += 1
        tok = self.s[self.i:j]
        self.i = j
        return _scalar(tok, self.where)

    def seq(self):
        self.i += 1
        out = []
        self.ws()
        if self.s[self.i:self.i + 1] == "]":
            self.i += 1
            return out
        while True:
            out.append(self.value())
            self.ws()
            ch = self.s[self.i:self.i + 1]
            self.i += 1
            if ch == "]":
                return out
            if ch != ",":
                raise ConfigError(f"{self.where}: expected ',' or ']' in a flow list")

    def map(self):
        self.i += 1
        out = {}
        self.ws()
        if self.s[self.i:self.i + 1] == "}":
            self.i += 1
            return out
        while True:
            key = self.value()
            self.ws()
            if self.s[self.i:self.i + 1] != ":":
                raise ConfigError(f"{self.where}: expected ':' in a flow mapping")
            self.i += 1
            out[str(key)] = self.value()
            self.ws()
            ch = self.s[self.i:self.i + 1]
            self.i += 1
            if ch == "}":
                return out
            if ch != ",":
                raise ConfigError(f"{self.where}: expected ',' or '}}' in a flow mapping")


def _inline(text, where):
    t = text.strip()
    if t.startswith("[") or t.startswith("{"):
        p = _Flow(t, where)
        v = p.value()
        p.ws()
        if p.i != len(t):
            raise ConfigError(f"{where}: trailing text after a flow collection")
        return v
    return _scalar(t, where)


def _split_key(text, where):
    """'key: value' -> (key, value text); the colon must be followed by a space or end."""
    m = re.match(r"""\s*("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^:#]+?)\s*:(?:\s+|$)(.*)$""", text)
    if not m:
        return None
    key = m.group(1)
    if key[0] in "'\"":
        key = _quoted(key, where)
    return key, m.group(2)


def loads_yaml_subset(text, source="<config>"):
    """Parse the plain YAML subset described in the module docstring."""
    if "\t" in text.replace("\t#", ""):
        for n, line in enumerate(text.splitlines(), 1):
            if line[:len(line) - len(line.lstrip())].count("\t"):
                raise ConfigError(f"{source}:{n}: tabs are not allowed for indentation")
    lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        if raw.strip() in ("---", "..."):
            if lines:
                raise ConfigError(f"{source}:{n}: only one YAML document is supported")
            continue
        line = _strip_comment(raw)
        if line.strip():
            lines.append((n, len(line) - len(line.lstrip(" ")), line.strip()))
    if not lines:
        return {}
    value, pos = _block(lines, 0, lines[0][1], source)
    if pos != len(lines):
        n = lines[pos][0]
        raise ConfigError(f"{source}:{n}: unexpected indentation")
    return value


def _block(lines, pos, indent, source):
    n, ind, text = lines[pos]
    if text.startswith("- ") or text == "-":
        return _seq_block(lines, pos, indent, source)
    return _map_block(lines, pos, indent, source)


def _value_after(lines, pos, indent, rest, n, source):
    """The value of 'key:' whose inline text is rest; may be a nested block."""
    where = f"{source}:{n}"
    if rest.strip() != "":
        return _inline(rest, where), pos + 1
    if pos + 1 < len(lines) and lines[pos + 1][1] > indent:
        return _block(lines, pos + 1, lines[pos + 1][1], source)
    if pos + 1 < len(lines) and lines[pos + 1][1] == indent and lines[pos + 1][2].startswith("-"):
        # "key:\n- item" (list at the same indentation as its key, allowed by YAML)
        return _seq_block(lines, pos + 1, indent, source)
    return None, pos + 1


def _map_block(lines, pos, indent, source):
    out = {}
    while pos < len(lines):
        n, ind, text = lines[pos]
        if ind < indent:
            break
        if ind > indent:
            raise ConfigError(f"{source}:{n}: unexpected indentation")
        if text.startswith("-"):
            break
        kv = _split_key(text, f"{source}:{n}")
        if kv is None:
            raise ConfigError(f"{source}:{n}: expected 'key: value'")
        key, rest = kv
        if key in out:
            raise ConfigError(f"{source}:{n}: key {key!r} appears twice")
        out[key], pos = _value_after(lines, pos, indent, rest, n, source)
    return out, pos


def _seq_block(lines, pos, indent, source):
    out = []
    while pos < len(lines):
        n, ind, text = lines[pos]
        if ind < indent or not (text.startswith("- ") or text == "-"):
            if ind > indent:
                raise ConfigError(f"{source}:{n}: unexpected indentation")
            break
        if ind > indent:
            raise ConfigError(f"{source}:{n}: unexpected indentation")
        item = text[1:].strip()
        if item == "":
            if pos + 1 < len(lines) and lines[pos + 1][1] > indent:
                v, pos = _block(lines, pos + 1, lines[pos + 1][1], source)
            else:
                v, pos = None, pos + 1
            out.append(v)
            continue
        kv = None if item[0] in "[{'\"" else _split_key(item, f"{source}:{n}")
        if kv is None:
            out.append(_inline(item, f"{source}:{n}"))
            pos += 1
            continue
        # "- key: value" starts a mapping whose other keys sit at the column of "key"
        item_indent = ind + (len(text) - len(item))
        sub = [(n, item_indent, item)]
        j = pos + 1
        while j < len(lines) and lines[j][1] > ind:
            sub.append(lines[j])
            j += 1
        v, used = _map_block(sub, 0, item_indent, source)
        if used != len(sub):
            raise ConfigError(f"{source}:{sub[used][0]}: unexpected indentation")
        out.append(v)
        pos = j
    return out, pos


def load_document(path):
    """Read a config file: JSON if it parses as JSON (or ends in .json), else the YAML subset."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        try:
            return json.loads(text)
        except ValueError as exc:
            raise ConfigError(f"{path}: invalid JSON: {exc}") from None
    return loads_yaml_subset(text, str(path))


# =============================================================== validation

def _merge(defaults, user, where):
    if user is None:
        return copy.deepcopy(defaults)
    if not isinstance(user, dict):
        raise ConfigError(f"{where} must be a mapping")
    out = copy.deepcopy(defaults)
    for key, value in user.items():
        if key not in defaults:
            raise ConfigError(f"unknown setting {where}.{key} (known: {', '.join(sorted(defaults))})")
        if isinstance(defaults[key], dict) and key not in ("cities",):
            out[key] = _merge(defaults[key], value, f"{where}.{key}")
        else:
            out[key] = copy.deepcopy(value)
    return out


def _int(value, where, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where} must be an integer, got {value!r}")
    if lo is not None and value < lo:
        raise ConfigError(f"{where} must be >= {lo}, got {value}")
    if hi is not None and value > hi:
        raise ConfigError(f"{where} must be <= {hi}, got {value}")
    return value


def _num(value, where, lo=None, hi=None, lo_open=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{where} must be a number, got {value!r}")
    if lo is not None and (value < lo or (lo_open and value == lo)):
        raise ConfigError(f"{where} must be {'>' if lo_open else '>='} {lo}, got {value}")
    if hi is not None and value > hi:
        raise ConfigError(f"{where} must be <= {hi}, got {value}")
    return value


def _choice(value, choices, where):
    if value not in choices:
        raise ConfigError(f"{where} must be one of {choices}, got {value!r}")
    return value


def seconds_to_ns_exact(value, where):
    """Seconds (int, float or decimal string) -> integer ns, read exactly (0.1 is 1e8 ns)."""
    if isinstance(value, bool):
        raise ConfigError(f"{where} must be a number of seconds")
    try:
        frac = Fraction(repr(value)) if isinstance(value, float) else Fraction(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{where} must be a number of seconds, got {value!r}") from None
    ns = frac * 1_000_000_000
    if ns.denominator != 1:
        raise ConfigError(f"{where} = {value} s is not a whole number of nanoseconds")
    return int(ns)


def exact_fraction(value, where):
    """A probability / factor / load read exactly from its decimal text."""
    if isinstance(value, bool):
        raise ConfigError(f"{where} must be a number")
    try:
        return Fraction(repr(value)) if isinstance(value, float) else Fraction(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{where} must be a number, got {value!r}") from None


def normalise(doc, *, seed=None):
    """Merge a loaded document onto DEFAULTS and check every value. Returns the config dict."""
    if not isinstance(doc, dict):
        raise ConfigError("a config file must hold a mapping at the top level")
    cfg = _merge(DEFAULTS, doc, "config")
    if seed is not None:
        cfg["seed"] = seed
    _int(cfg["seed"], "seed", 0)

    sc = cfg["scenario"]
    _choice(sc["kind"], SCENARIO_KINDS, "scenario.kind")
    if sc["kind"] == "walker":
        from .presets import WALKER_PRESETS
        _choice(sc["preset"], tuple(WALKER_PRESETS), "scenario.preset")
    if not isinstance(sc["start_utc"], str) or not sc["start_utc"].endswith("Z"):
        raise ConfigError("scenario.start_utc must be ISO 8601 UTC ending in Z")
    seconds_to_ns_exact(sc["duration_s"], "scenario.duration_s")
    seconds_to_ns_exact(sc["drain_s"], "scenario.drain_s")
    if seconds_to_ns_exact(sc["duration_s"], "scenario.duration_s") <= 0:
        raise ConfigError("scenario.duration_s must be positive")
    _int(sc["step_ms"], "scenario.step_ms", 1)
    _int(sc["chunk_steps"], "scenario.chunk_steps", 2)
    if sc["cities"] is not None and (not isinstance(sc["cities"], list)
                                     or not all(isinstance(c, str) for c in sc["cities"])):
        raise ConfigError("scenario.cities must be a list of city names or null")
    _num(sc["gsl"]["min_elevation_deg"], "scenario.gsl.min_elevation_deg", 0, 90)
    _int(sc["gsl"]["max_links_per_gs"], "scenario.gsl.max_links_per_gs", 1)
    _num(sc["isl"]["polar_cutoff_deg"], "scenario.isl.polar_cutoff_deg", 0, 90)
    if sc["isl"]["max_range_km"] is not None:
        _num(sc["isl"]["max_range_km"], "scenario.isl.max_range_km", 0, lo_open=True)

    tr = cfg["traffic"]
    _num(tr["rate_pps"], "traffic.rate_pps", 0, lo_open=True)
    _int(tr["payload_bytes"], "traffic.payload_bytes", 0, 65000)
    _choice(tr["model"], ("cbr", "poisson"), "traffic.model")
    _choice(tr["ingress_mode"], INGRESS_MODES, "traffic.ingress_mode")
    _int(tr["l2_overhead_bytes"], "traffic.l2_overhead_bytes", 0, 64)
    if tr["start_offset"] != "random":
        _int(tr["start_offset"], "traffic.start_offset", 0)
    if tr["flows"] != "science20":
        if not isinstance(tr["flows"], list) or not tr["flows"]:
            raise ConfigError("traffic.flows must be 'science20' or a non-empty list of flows")
        for i, f in enumerate(tr["flows"]):
            w = f"traffic.flows[{i}]"
            if not isinstance(f, dict):
                raise ConfigError(f"{w} must be a mapping with src and dst")
            unknown = set(f) - FLOW_KEYS
            if unknown:
                raise ConfigError(f"{w}: unknown keys {sorted(unknown)} (known: {sorted(FLOW_KEYS)})")
            for k in ("src", "dst"):
                if not isinstance(f.get(k), str):
                    raise ConfigError(f"{w}.{k} must be a city name")
            if f["src"] == f["dst"]:
                raise ConfigError(f"{w}: src and dst are the same city")
            if "rate_pps" in f:
                _num(f["rate_pps"], f"{w}.rate_pps", 0, lo_open=True)
            if "model" in f:
                _choice(f["model"], ("cbr", "poisson"), f"{w}.model")
            if "payload_bytes" in f:
                _int(f["payload_bytes"], f"{w}.payload_bytes", 0, 65000)
            if "start_offset" in f and f["start_offset"] != "random":
                _int(f["start_offset"], f"{w}.start_offset", 0)
            if "send_times_ns" in f:
                st = f["send_times_ns"]
                if not isinstance(st, list) or any(isinstance(x, bool) or not isinstance(x, int) or x < 0
                                                   for x in st):
                    raise ConfigError(f"{w}.send_times_ns must be a list of non-negative integers")
                if any(b <= a for a, b in zip(st, st[1:])):
                    raise ConfigError(f"{w}.send_times_ns must be strictly increasing")

    sh = cfg["schedule"]
    _int(sh["refresh_ms"], "schedule.refresh_ms", 1)
    if sh["refresh_ms"] % sc["step_ms"]:
        raise ConfigError("schedule.refresh_ms must be a multiple of scenario.step_ms")
    try:
        scheduler.exact_slack(sh["slack"])
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"schedule.slack: {exc}") from None
    sh["slack"] = str(sh["slack"]) if not isinstance(sh["slack"], str) else sh["slack"]
    _int(sh["unit_code"], "schedule.unit_code", 0, 3)
    timebase.unit_ns(sh["unit_code"])
    _choice(sh["plan_links"], ("stable", "instant"), "schedule.plan_links")
    _int(sh["planner_processing_ns"], "schedule.planner_processing_ns", 0)

    fw = cfg["forwarding"]
    _choice(fw["policy"], POLICIES, "forwarding.policy")
    _choice(fw["fallback"], FALLBACKS, "forwarding.fallback")
    _int(fw["hop_limit"], "forwarding.hop_limit", 1, 255)
    _int(fw["processing_ns"], "forwarding.processing_ns", 0)
    _choice(fw["jitter"]["model"], JITTER_MODELS, "forwarding.jitter.model")
    _int(fw["jitter"]["mean_ns"], "forwarding.jitter.mean_ns", 0)
    _int(fw["link_rate_bps"], "forwarding.link_rate_bps", 1)
    _num(fw["buffer_ms"], "forwarding.buffer_ms", 0, lo_open=True)
    bg = fw["background"]
    _choice(bg["model"], BACKGROUND_MODELS, "forwarding.background.model")
    rho = exact_fraction(bg["rho"], "forwarding.background.rho")
    if not 0 <= rho < 1:
        raise ConfigError("forwarding.background.rho must be in [0, 1)")
    _int(bg["packet_bytes"], "forwarding.background.packet_bytes", 1, 65000)
    _int(bg["window_ms"], "forwarding.background.window_ms", 1)
    _choice(bg["links"], ("all", "isl"), "forwarding.background.links")
    _choice(fw["hop_mode"], HOP_MODES, "forwarding.hop_mode")
    _int(fw["verify_every"], "forwarding.verify_every", 0)
    if fw["slow_queue_ns"] is not None:
        _int(fw["slow_queue_ns"], "forwarding.slow_queue_ns", 0)
    carrier_detect_ns(cfg)

    if not isinstance(cfg["faults"], list):
        raise ConfigError("faults must be a list")
    for i, f in enumerate(cfg["faults"]):
        _check_fault(f, f"faults[{i}]")

    out = cfg["output"]
    _choice(out["trace"], TRACE_LEVELS, "output.trace")
    _int(out["sample_every"], "output.sample_every", 1)
    if not isinstance(out["pcap"], bool):
        raise ConfigError("output.pcap must be true or false")
    _int(out["pcap_max_packets"], "output.pcap_max_packets", 0)
    if not isinstance(out["packets_csv"], bool):
        raise ConfigError("output.packets_csv must be true or false")
    _choice(out["invariants"], INVARIANT_LEVELS, "output.invariants")
    _int(out["invariant_sample_every"], "output.invariant_sample_every", 1)
    return cfg


def _check_fault(f, w):
    if not isinstance(f, dict) or "kind" not in f:
        raise ConfigError(f"{w} must be a mapping with a kind")
    kind = _choice(f["kind"], FAULT_KINDS, f"{w}.kind")
    unknown = set(f) - FAULT_KEYS[kind]
    if unknown:
        raise ConfigError(f"{w}: unknown keys {sorted(unknown)} for kind {kind} "
                          f"(known: {sorted(FAULT_KEYS[kind])})")
    for k in ("start_s", "stop_s"):
        if k in f:
            seconds_to_ns_exact(f[k], f"{w}.{k}")
    if kind in ("link_down", "node_down", "slow_processing", "rate_cut", "arq"):
        for k in ("start_s", "stop_s"):
            if k not in f:
                raise ConfigError(f"{w}.{k} is required for {kind}")
        if seconds_to_ns_exact(f["stop_s"], f"{w}.stop_s") <= seconds_to_ns_exact(f["start_s"], f"{w}.start_s"):
            raise ConfigError(f"{w}: stop_s must be after start_s")
        targets = [k for k in ("link", "link_names", "node", "node_name", "on_path") if k in f]
        if len(targets) != 1:
            raise ConfigError(f"{w}: give exactly one target (link, link_names, node, node_name or on_path)")
        if "link" in f:
            if (not isinstance(f["link"], list) or len(f["link"]) != 2
                    or any(isinstance(x, bool) or not isinstance(x, int) for x in f["link"])):
                raise ConfigError(f"{w}.link must be [node_a, node_b]")
        if "link_names" in f:
            if not isinstance(f["link_names"], list) or len(f["link_names"]) != 2 \
                    or not all(isinstance(x, str) for x in f["link_names"]):
                raise ConfigError(f"{w}.link_names must be [name_a, name_b]")
        if "node" in f:
            _int(f["node"], f"{w}.node", 0)
        if "on_path" in f:
            op = f["on_path"]
            if not isinstance(op, dict) or set(op) - ON_PATH_KEYS or "flow" not in op:
                raise ConfigError(f"{w}.on_path must be a mapping with flow (and at_s, position, kind)")
            _int(op["flow"], f"{w}.on_path.flow", 0)
            if "at_s" in op:
                seconds_to_ns_exact(op["at_s"], f"{w}.on_path.at_s")
            pos = op.get("position", "middle")
            if not (pos in ("first", "middle", "last") or (isinstance(pos, int) and not isinstance(pos, bool))):
                raise ConfigError(f"{w}.on_path.position must be first, middle, last or a hop number")
            if op.get("kind", "isl") not in ("isl", "any", "node"):
                raise ConfigError(f"{w}.on_path.kind must be isl, any or node")
    if kind in ("link_down", "rate_cut", "arq") and ("node" in f or "node_name" in f):
        raise ConfigError(f"{w}: {kind} needs a link target")
    if kind == "node_down" and ("link" in f or "link_names" in f):
        raise ConfigError(f"{w}: node_down needs a node target")
    if kind in ("link_renewal", "node_renewal"):
        u = exact_fraction(f.get("unavailability"), f"{w}.unavailability")
        if not 0 < u < 1:
            raise ConfigError(f"{w}.unavailability must be in (0, 1)")
        if seconds_to_ns_exact(f.get("mttr_s"), f"{w}.mttr_s") <= 0:
            raise ConfigError(f"{w}.mttr_s must be positive")
        if kind == "link_renewal":
            _choice(f.get("targets", "isl"), ("isl", "gsl", "all"), f"{w}.targets")
    if kind == "slow_processing":
        _int(f.get("delta_ns"), f"{w}.delta_ns", 0)
    if kind == "rate_cut":
        fac = exact_fraction(f.get("factor"), f"{w}.factor")
        if not 0 < fac <= 1:
            raise ConfigError(f"{w}.factor must be in (0, 1]")
    if kind == "arq":
        p = exact_fraction(f.get("loss"), f"{w}.loss")
        if not 0 <= p < 1:
            raise ConfigError(f"{w}.loss must be in [0, 1)")
        _int(f.get("max_retries", 3), f"{w}.max_retries", 0, 3)
        _int(f.get("retry_extra_ns", 100_000), f"{w}.retry_extra_ns", 0)


def carrier_detect_ns(cfg):
    """forwarding.carrier_detect_ms as integer ns (read exactly; >= 0)."""
    v = cfg["forwarding"]["carrier_detect_ms"]
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise ConfigError(f"forwarding.carrier_detect_ms must be a number, got {v!r}")
    ns = exact_fraction(v, "forwarding.carrier_detect_ms") * 1_000_000
    if ns < 0 or ns.denominator != 1:
        raise ConfigError("forwarding.carrier_detect_ms must be >= 0 and a whole number of ns")
    return int(ns)


def load_config(path, *, seed=None):
    """Read, merge onto DEFAULTS and check a config file."""
    return normalise(load_document(path), seed=seed)


__all__ = ["DEFAULTS", "POLICIES", "FALLBACKS", "BACKGROUND_MODELS", "JITTER_MODELS", "TRACE_LEVELS",
           "INVARIANT_LEVELS", "HOP_MODES", "INGRESS_MODES", "FAULT_KINDS", "ConfigError",
           "loads_yaml_subset", "load_document", "normalise", "load_config", "seconds_to_ns_exact",
           "exact_fraction", "carrier_detect_ns"]

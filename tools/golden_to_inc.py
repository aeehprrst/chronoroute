#!/usr/bin/env python3
"""
golden_to_inc.py
----------------
Turn the shared golden vectors into C++ for the ns-3 test suite:

    spec/golden/tcrh_vectors.json  \
    spec/golden/crh_vectors.json   /  ->  ns3/contrib/chronoroute/test/golden-vectors.inc

ns-3 has no JSON library, so the vectors are compiled in. The .inc holds only
data (C++20 designated initializers); the struct types live in
test/chronoroute-test-suite.cc. Designated initializers make the compiler
reject a field that is misspelt or out of order, and every field this script
does not write is value-initialised (false / 0 / empty / nullptr), which is
how a JSON null or an absent key reaches C++.

Usage (from the repository root, inside WSL):
    venv/bin/python -B tools/golden_to_inc.py           # (re)write the .inc
    venv/bin/python -B tools/golden_to_inc.py --check   # exit 1 if it is stale

Output is deterministic (no timestamps; the JSON files' SHA-256 is recorded),
so regenerating from unchanged vectors gives a byte-identical file.

A key this script does not know is an error, not something to skip: a new
expectation in the vectors must get a C++ check, not be silently ignored.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TCRH_JSON = REPO / "spec" / "golden" / "tcrh_vectors.json"
CRH_JSON = REPO / "spec" / "golden" / "crh_vectors.json"
OUT_INC = REPO / "ns3" / "contrib" / "chronoroute" / "test" / "golden-vectors.inc"

U32_MAX = (1 << 32) - 1
U64_MAX = (1 << 64) - 1

# JSON key -> (C++ field, kind). Kinds: str, hexstr, u32, u64str (decimal
# string, 64-bit), bool, list_u32, list_u64, policy. A trailing "?" means the
# value may be null; the C++ struct then has has<Field> = true when present.
TCRH_ENCODE_FIELDS = {
    "name": ("name", "str"),
    "note": ("note", "str"),
    "sids_fwd": ("sidsFwd", "list_u32"),
    "deltas_fwd": ("deltasFwd", "list_u32", "opt"),
    "cumulative_budgets_ns": ("cumulativeBudgetsNs", "list_u64", "opt"),
    "epoch_base": ("epochBase", "u32", "opt"),
    "t_ingress_gps_ns": ("tIngressGpsNs", "u64str", "opt"),
    "unit_code": ("unitCode", "u32"),
    "next_header": ("nextHeader", "u32"),
    "flags": ("flags", "u32"),
    "expect_hex": ("expectHex", "hexstr"),
    "expect_deadlines_u": ("expectDeadlinesU", "list_u32"),
    "expect_sat": ("expectSat", "bool"),
    "expect_epoch_base": ("expectEpochBase", "u32"),
    "expect_deltas_fwd": ("expectDeltasFwd", "list_u32"),
    "expect_flags": ("expectFlags", "u32"),
    "expect_size": ("expectSize", "u32"),
}
TCRH_ENCODE_ONE_OF = (("deltas_fwd", "cumulative_budgets_ns"), ("epoch_base", "t_ingress_gps_ns"))

TCRH_PROCESS_FIELDS = {
    "name": ("name", "str"),
    "note": ("note", "str"),
    "hex_in": ("hexIn", "hexstr"),
    "now_u": ("nowU", "u32"),
    "policy": ("policy", "str"),
    "expect_action": ("expectAction", "str"),
    "expect_next_sid": ("expectNextSid", "u32", "null"),
    "expect_hex_out": ("expectHexOut", "hexstr", "nullstr"),
    "expect_late": ("expectLate", "bool"),
    "expect_hop_index": ("expectHopIndex", "u32", "null"),
    "expect_deadline_u": ("expectDeadlineU", "u32", "null"),
    "expect_reason": ("expectReason", "str", "nullstr"),
    "expect_icmp_code": ("expectIcmpCode", "u32", "null"),
    "expect_icmp_pointer": ("expectIcmpPointer", "u32", "null"),
}

# spec section 6 step 7 (next link down): bytes as they leave step 5 in, the
# fallback packet out
TCRH_LINK_DOWN_FIELDS = {
    "name": ("name", "str"),
    "note": ("note", "str"),
    "hex_in": ("hexIn", "hexstr"),
    "expect_action": ("expectAction", "str"),
    "expect_next_sid": ("expectNextSid", "u32", "null"),
    "expect_hex_out": ("expectHexOut", "hexstr", "nullstr"),
    "expect_hop_index": ("expectHopIndex", "u32", "null"),
    "expect_reason": ("expectReason", "str", "nullstr"),
    "expect_icmp_code": ("expectIcmpCode", "u32", "null"),
    "expect_icmp_pointer": ("expectIcmpPointer", "u32", "null"),
}

CRH_ENCODE_FIELDS = {
    "name": ("name", "str"),
    "note": ("note", "str"),
    "routing_type": ("routingType", "u32"),
    "sids_fwd": ("sidsFwd", "list_u32"),
    "next_header": ("nextHeader", "u32"),
    "expect_hex": ("expectHex", "hexstr"),
    "expect_size": ("expectSize", "u32"),
    "expect_hdr_ext_len": ("expectHdrExtLen", "u32"),
    "expect_decoded_sids_rev": ("expectDecodedSidsRev", "list_u32"),
}

CRH_PROCESS_FIELDS = {
    "name": ("name", "str"),
    "note": ("note", "str"),
    "hex_in": ("hexIn", "hexstr"),
    "expect_action": ("expectAction", "str"),
    "expect_next_sid": ("expectNextSid", "u32", "null"),
    "expect_hex_out": ("expectHexOut", "hexstr", "nullstr"),
    "expect_reason": ("expectReason", "str", "nullstr"),
    "expect_icmp_code": ("expectIcmpCode", "u32", "null"),
    "expect_icmp_pointer": ("expectIcmpPointer", "u32", "null"),
}


class VectorError(ValueError):
    """The JSON does not have the shape this generator (and the C++ test) expects."""


def c_string(s):
    """A C++ string literal. Non-ASCII and control bytes become 3-digit octal escapes."""
    out = []
    for byte in s.encode("utf-8"):
        ch = chr(byte)
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif 0x20 <= byte < 0x7F:
            out.append(ch)
        else:
            out.append("\\%03o" % byte)
    return '"' + "".join(out) + '"'


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _u32(where, v):
    if not _is_int(v) or not 0 <= v <= U32_MAX:
        raise VectorError(f"{where}: expected an integer 0..2^32-1, got {v!r}")
    return f"{v}U"


def _u64(where, v):
    if not _is_int(v) or not 0 <= v <= U64_MAX:
        raise VectorError(f"{where}: expected an integer 0..2^64-1, got {v!r}")
    return f"{v}ULL"


def render_value(where, kind, value):
    if kind == "str":
        if not isinstance(value, str):
            raise VectorError(f"{where}: expected a string, got {value!r}")
        return c_string(value)
    if kind == "hexstr":
        if not isinstance(value, str) or not re.fullmatch(r"(?:[0-9a-f]{2})*", value):
            raise VectorError(f"{where}: expected lowercase hex with an even length, got {value!r}")
        return c_string(value)
    if kind == "u32":
        return _u32(where, value)
    if kind == "u64str":
        # GPS nanoseconds exceed 2^53, so the JSON carries them as decimal strings
        if not isinstance(value, str) or not re.fullmatch(r"0|[1-9][0-9]*", value):
            raise VectorError(f"{where}: expected a decimal string, got {value!r}")
        return _u64(where, int(value))
    if kind == "bool":
        if not isinstance(value, bool):
            raise VectorError(f"{where}: expected true/false, got {value!r}")
        return "true" if value else "false"
    if kind in ("list_u32", "list_u64"):
        if not isinstance(value, list):
            raise VectorError(f"{where}: expected a list, got {value!r}")
        conv = _u32 if kind == "list_u32" else _u64
        items = [conv(f"{where}[{i}]", x) for i, x in enumerate(value)]
        return "{" + ", ".join(items) + "}"
    raise AssertionError(f"unknown kind {kind}")


def render_vector(section, vec, fields, one_of=()):
    """One designated-initializer line for one vector."""
    if not isinstance(vec, dict):
        raise VectorError(f"{section}: every vector must be an object")
    name = vec.get("name", "?")
    where = f"{section}[{name}]"
    unknown = sorted(set(vec) - set(fields))
    if unknown:
        raise VectorError(f"{where}: unknown key(s) {unknown}: add a C++ check before using them")
    for a, b in one_of:
        if (a in vec) == (b in vec):
            raise VectorError(f"{where}: exactly one of {a!r} / {b!r} must be present")
    parts = []
    for key, spec in fields.items():  # dict order = C++ declaration order
        cxx, kind = spec[0], spec[1]
        mode = spec[2] if len(spec) > 2 else "required"
        if key not in vec:
            if mode == "opt":
                continue  # has<Field> stays false
            raise VectorError(f"{where}: missing key {key!r}")
        value = vec[key]
        if value is None:
            if mode in ("null", "nullstr"):
                continue  # has<Field> false, or a nullptr string
            raise VectorError(f"{where}: {key!r} must not be null")
        if mode in ("opt", "null"):
            parts.append(f".has{cxx[0].upper()}{cxx[1:]} = true")
        parts.append(f".{cxx} = {render_value(f'{where}.{key}', kind, value)}")
    return "    {" + ", ".join(parts) + "},"


def load(path, spec_name, sections=("encode", "process")):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("spec") != spec_name:
        raise VectorError(f"{path.name}: expected top-level spec {spec_name!r}")
    unknown = sorted(set(data) - {"spec", *sections})
    if unknown:
        raise VectorError(f"{path.name}: unknown section(s) {unknown}: add a C++ check first")
    for section in sections:
        if not isinstance(data.get(section), list) or not data[section]:
            raise VectorError(f"{path.name}: {section!r} must be a non-empty list")
        names = [v.get("name") for v in data[section]]
        if len(set(names)) != len(names):
            raise VectorError(f"{path.name}: duplicate vector names in {section!r}")
    return data


def generate():
    tcrh = load(TCRH_JSON, "tcrh-v1", ("encode", "process", "link_down"))
    crh = load(CRH_JSON, "rfc9631")
    sha_t = hashlib.sha256(TCRH_JSON.read_bytes()).hexdigest()
    sha_c = hashlib.sha256(CRH_JSON.read_bytes()).hexdigest()

    lines = [
        "// GENERATED by tools/golden_to_inc.py -- DO NOT EDIT.",
        "// Regenerate: venv/bin/python -B tools/golden_to_inc.py  (or tools/ns3-sync.sh)",
        f"// spec/golden/tcrh_vectors.json sha256 {sha_t}",
        f"// spec/golden/crh_vectors.json  sha256 {sha_c}",
        "// SPDX-License-Identifier: GPL-2.0-only",
        "// Included by chronoroute-test-suite.cc, which defines the five vector structs.",
        "",
    ]

    def block(ctype, var, section, vectors, fields, one_of=()):
        lines.append(f"static const {ctype} {var}[] = {{")
        for v in vectors:
            lines.append(render_vector(section, v, fields, one_of))
        lines.append("};")
        lines.append(f"static constexpr size_t {var}Count = {len(vectors)};")
        lines.append("")

    block("TcrhEncodeVector", "kTcrhEncodeVectors", "tcrh.encode", tcrh["encode"],
          TCRH_ENCODE_FIELDS, TCRH_ENCODE_ONE_OF)
    block("TcrhProcessVector", "kTcrhProcessVectors", "tcrh.process", tcrh["process"],
          TCRH_PROCESS_FIELDS)
    block("TcrhLinkDownVector", "kTcrhLinkDownVectors", "tcrh.link_down", tcrh["link_down"],
          TCRH_LINK_DOWN_FIELDS)
    block("CrhEncodeVector", "kCrhEncodeVectors", "crh.encode", crh["encode"], CRH_ENCODE_FIELDS)
    block("CrhProcessVector", "kCrhProcessVectors", "crh.process", crh["process"],
          CRH_PROCESS_FIELDS)
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the .inc is stale; write nothing")
    ap.add_argument("--out", type=Path, default=OUT_INC, help="output path (default: the module's test/)")
    args = ap.parse_args(argv)
    try:
        text = generate()
    except (VectorError, json.JSONDecodeError, OSError) as err:
        print(f"golden_to_inc: {err}", file=sys.stderr)
        return 2
    current = args.out.read_text(encoding="utf-8") if args.out.exists() else None
    if args.check:
        if current != text:
            print(f"golden_to_inc: {args.out} is stale; run tools/golden_to_inc.py", file=sys.stderr)
            return 1
        print(f"golden_to_inc: up to date: {args.out.name}")
        return 0
    if current == text:
        print(f"golden_to_inc: unchanged: {args.out}")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8", newline="\n")
    print(f"golden_to_inc: wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

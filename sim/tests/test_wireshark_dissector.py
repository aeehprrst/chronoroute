"""
tools/wireshark/tcrh.lua seen through tshark.

The pcaps come from chronoroute.trace.pcap (tested on its own in
test_trace_pcap.py). Every expected value comes from the golden vectors
(spec/golden/tcrh_vectors.json) or from the reference implementation
chronoroute.proto, never from the dissector itself.

These tests need tshark. Where it is missing (CI without Wireshark) the whole
module is SKIPPED, not failed. On the project machine (tshark 4.6.4 in WSL)
they must run: `make test` shows them as passed, not skipped.

tshark runs with HOME / XDG_CONFIG_HOME / WIRESHARK_CONFIG_DIR pointed at an
empty temporary directory, so a personal Wireshark configuration (or an
installed copy of tcrh.lua) cannot change the result.
"""

import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

import chronoroute.proto as P
from chronoroute.trace import pcap as W

TSHARK = shutil.which("tshark")
pytestmark = pytest.mark.skipif(
    TSHARK is None, reason="tshark is not installed; the Wireshark dissector tests need it")

REPO = Path(__file__).resolve().parents[2]
WS_DIR = REPO / "tools" / "wireshark"
LUA = WS_DIR / "tcrh.lua"
CHECK_PCAP = WS_DIR / "check_pcap.sh"
STRICT_LOAD = WS_DIR / "tests" / "strict_load.lua"
PROFILE = WS_DIR / "profiles" / "ChronoRoute"

TCRH = W.load_golden("tcrh_vectors.json")
CRH = W.load_golden("crh_vectors.json")
ENCODE = TCRH["encode"]
AGG = "|"          # occurrence separator: never appears in a value we read
MS = 10**6


# --------------------------------------------------------------------- tshark

@pytest.fixture(scope="module")
def env(tmp_path_factory):
    """Environment with an empty, private Wireshark configuration."""
    home = tmp_path_factory.mktemp("wireshark-home")
    (home / "config").mkdir()
    e = dict(os.environ)
    e.update(HOME=str(home), XDG_CONFIG_HOME=str(home / "xdg"),
             WIRESHARK_CONFIG_DIR=str(home / "config"))
    e.pop("CR_LUA_UNDER_TEST", None)
    return e


def tshark(env, args, *, lua=True, allow_stderr=False, extra_lua=()):
    cmd = [TSHARK, "-n"] + (["-X", f"lua_script:{LUA}"] if lua else [])
    for script in extra_lua:                     # loaded after tcrh.lua, in order
        cmd += ["-X", f"lua_script:{script}"]
    cmd += [str(a) for a in args]
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, f"{cmd}\n{p.stderr}"
    if not allow_stderr:
        # Lua load errors and bad field names end up here
        assert p.stderr == "", p.stderr
    return p


def fields(env, pcap, names, *, dfilter=None, prefs=(), lua=True, extra_lua=()):
    args = ["-r", pcap]
    for pref in prefs:
        args += ["-o", pref]
    if dfilter:
        args += ["-Y", dfilter]
    args += ["-T", "fields", "-E", "separator=/t", "-E", "occurrence=a", "-E", f"aggregator={AGG}"]
    for n in names:
        args += ["-e", n]
    rows = []
    for line in tshark(env, args, lua=lua, extra_lua=extra_lua).stdout.splitlines():
        cols = line.split("\t")
        assert len(cols) == len(names), line
        rows.append(dict(zip(names, cols)))
    return rows


def frames_matching(env, pcap, dfilter, *, prefs=()):
    rows = fields(env, pcap, ["frame.number"], dfilter=dfilter, prefs=prefs)
    return [int(r["frame.number"]) for r in rows]


def lst(s):
    return [] if s == "" else s.split(AGG)


def ints(s):
    return [int(x) for x in lst(s)]


def ms(units, unit_ns):
    """Exact milliseconds of `units` deadline units."""
    return Fraction(units * unit_ns, MS)


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    out = tmp_path_factory.mktemp("golden-pcaps")
    return out, W.write_golden_pcaps(out)


# ------------------------------------------------- registration and input bytes

def test_registered_in_the_ipv6_routing_type_table(env):
    tables = tshark(env, ["-G", "dissector-tables"], lua=False).stdout
    assert re.search(r"^ipv6\.routing\.type\tIPv6 Routing Type\tFT_UINT8", tables, re.M)
    decodes = tshark(env, ["-G", "decodes"]).stdout
    assert re.search(r"^ipv6\.routing\.type\t253\ttcrh$", decodes, re.M)
    # the native CRH decoders are still in place for types 5 and 6
    assert re.search(r"^ipv6\.routing\.type\t5\tipv6\.routing\.type\.crh$", decodes, re.M)


def test_dissector_input_starts_after_the_four_common_bytes(env, golden):
    """
    Measured, not assumed: Wireshark 4.6 hands the sub-dissector the routing
    header from byte 4 (Flags) on. tcrh.lua detects which case it is in and
    reports it in tcrh.input_offset (4 = starts at Flags, 0 = whole header).
    """
    out, _ = golden
    for name in ("tcrh_encode_raw.pcap", "tcrh_encode_ppp.pcap", "tcrh_walk_ppp.pcap"):
        rows = fields(env, out / name, ["tcrh.input_offset"])
        assert rows and {r["tcrh.input_offset"] for r in rows} == {"4"}, name


def test_whole_header_input_is_handled_too(env, tmp_path):
    """
    The defensive branch: if a Wireshark version handed over the whole routing
    header (from Next Header on), tcrh.lua reads bytes 0-3 itself. A test
    probe passes complete headers from a UDP payload to the dissector.
    """
    probe = WS_DIR / "tests" / "whole_header_probe.lua"
    cases = [bytes.fromhex(v["expect_hex"]) for v in ENCODE[:4]]
    cases += [bytes.fromhex(TCRH["process"][0]["hex_in"]),                  # SL 2 of 3
              bytes.fromhex(next(v for v in TCRH["process"]
                                 if v["name"] == "malformed-sl-gt-numhops")["hex_in"])]
    src = dst = W.sid_address(1)
    frames = [W.Frame(10**9 + i, W.ipv6_packet(src, dst, 17, W.udp_datagram(src, dst, rh, 50254, 50254)))
              for i, rh in enumerate(cases)]
    path = W.write_pcap(tmp_path / "whole.pcap", frames, W.LINKTYPE_RAW)
    rows = fields(env, path, ["tcrh.input_offset", "tcrh.valid", "tcrh.reason", "tcrh.sid",
                              "tcrh.deadline", "tcrh.current_sid", "tcrh.current_hop"],
                  prefs=(), lua=True, extra_lua=[probe])
    assert len(rows) == len(cases)
    for rh, r in zip(cases, rows):
        assert r["tcrh.input_offset"] == "0"
        reason = _reference_reason(rh)
        assert r["tcrh.valid"] == ("0" if reason else "1") and r["tcrh.reason"] == (reason or "")
        if reason:
            continue
        hdr = P.TcrhHeader.decode(rh)
        assert ints(r["tcrh.sid"]) == list(hdr.sids_rev)
        assert ints(r["tcrh.deadline"]) == list(reversed(hdr.deadlines()))
        assert int(r["tcrh.current_hop"]) == hdr.current_hop_index()
        if hdr.segments_left < hdr.num_hops:
            assert int(r["tcrh.current_sid"]) == hdr.sids_rev[hdr.segments_left]


# ------------------------------------------------------ every encode vector

ENCODE_FIELDS = [
    "frame.number", "ipv6.routing.type", "ipv6.routing.len", "ipv6.routing.segleft",
    "tcrh.valid", "tcrh.reason", "tcrh.flags", "tcrh.flags.dev", "tcrh.flags.greedy",
    "tcrh.flags.sat", "tcrh.flags.unit", "tcrh.flags.reserved", "tcrh.num_hops", "tcrh.dev_hop",
    "tcrh.reserved", "tcrh.epoch_base", "tcrh.unit_ns", "tcrh.unit_ms", "tcrh.epoch_base_ms",
    "tcrh.entry.index", "tcrh.entry.hop", "tcrh.sid", "tcrh.delta", "tcrh.delta_ms",
    "tcrh.deadline", "tcrh.deadline_ms", "tcrh.padding", "tcrh.final_sid", "tcrh.current_hop",
    "tcrh.current_sid", "tcrh.current_deadline", "tcrh.margin", "tcrh.late",
    "_ws.malformed", "_ws.lua.error", "_ws.expert.message",
    "udp.length", "tcp.len", "ipv6.dst",
]


@pytest.fixture(scope="module")
def encode_rows(env, golden):
    out, _ = golden
    return {lt: fields(env, out / f"tcrh_encode_{lt}.pcap", ENCODE_FIELDS) for lt in ("raw", "ppp")}


@pytest.mark.parametrize("linktype", ["raw", "ppp"])
@pytest.mark.parametrize("i", range(len(ENCODE)), ids=[v["name"] for v in ENCODE])
def test_encode_vector_fields(encode_rows, linktype, i):
    v = ENCODE[i]
    r = encode_rows[linktype][i]
    h = len(v["sids_fwd"])
    u = P.unit_ns(v["unit_code"])
    flags = v["expect_flags"]
    deadlines_rev = list(reversed(v["expect_deadlines_u"]))
    deltas_rev = list(reversed(v["expect_deltas_fwd"]))

    assert int(r["frame.number"]) == i + 1
    # Wireshark's own common fields
    assert r["ipv6.routing.type"] == "253"
    assert int(r["ipv6.routing.len"]) == v["expect_size"] // 8 - 1
    assert int(r["ipv6.routing.segleft"]) == h                 # a fresh header
    # validity
    assert r["tcrh.valid"] == "1" and r["tcrh.reason"] == ""
    # flags, named bits
    assert int(r["tcrh.flags"], 16) == flags
    assert r["tcrh.flags.dev"] == str(bool(flags & 0x01))
    assert r["tcrh.flags.greedy"] == str(bool(flags & 0x02))
    assert r["tcrh.flags.sat"] == str(v["expect_sat"])
    assert int(r["tcrh.flags.unit"]) == v["unit_code"]
    assert int(r["tcrh.flags.reserved"], 16) == 0
    # fixed part
    assert int(r["tcrh.num_hops"]) == h
    assert int(r["tcrh.dev_hop"]) == 0 and int(r["tcrh.reserved"], 16) == 0
    assert int(r["tcrh.epoch_base"]) == v["expect_epoch_base"]
    assert int(r["tcrh.unit_ns"]) == u
    assert Fraction(r["tcrh.unit_ms"]) == ms(1, u)
    assert Fraction(r["tcrh.epoch_base_ms"]) == ms(v["expect_epoch_base"], u)
    # entries in wire order: SID[0] is the final endpoint
    assert ints(r["tcrh.entry.index"]) == list(range(h))
    assert ints(r["tcrh.entry.hop"]) == list(range(h, 0, -1))
    assert ints(r["tcrh.sid"]) == list(reversed(v["sids_fwd"]))
    assert ints(r["tcrh.delta"]) == deltas_rev
    assert [Fraction(x) for x in lst(r["tcrh.delta_ms"])] == [ms(d, u) for d in deltas_rev]
    assert ints(r["tcrh.deadline"]) == deadlines_rev
    assert [Fraction(x) for x in lst(r["tcrh.deadline_ms"])] == [ms(d, u) for d in deadlines_rev]
    pad = v["expect_size"] - 12 - 3 * h
    assert r["tcrh.padding"] == "00" * pad
    assert int(r["tcrh.final_sid"]) == v["sids_fwd"][-1]
    # SL = Num Hops: the packet is still at the ingress, no current SID or deadline yet
    assert int(r["tcrh.current_hop"]) == 0
    assert r["tcrh.current_sid"] == r["tcrh.current_deadline"] == r["tcrh.margin"] == ""
    assert r["tcrh.late"] == ""
    # nothing broke, nothing left undecoded
    assert r["_ws.malformed"] == "" and r["_ws.lua.error"] == ""
    messages = lst(r["_ws.expert.message"])
    assert not any("Undecoded" in m or "Malformed" in m for m in messages), messages
    assert any(m.startswith("SAT set") for m in messages) == v["expect_sat"]
    # the transport after the header decodes too
    nh = v["next_header"]
    if nh == 17:
        assert r["udp.length"] == str(8 + W.PAYLOAD_BYTES) and r["tcp.len"] == ""
    elif nh == 6:
        assert r["tcp.len"] == str(W.PAYLOAD_BYTES) and r["udp.length"] == ""
    elif nh == 41:
        assert len(lst(r["ipv6.dst"])) == 2 and r["udp.length"] == str(8 + W.PAYLOAD_BYTES)
    else:
        assert nh == 59 and r["udp.length"] == r["tcp.len"] == ""


def test_raw_and_ppp_decode_identically(encode_rows):
    assert encode_rows["raw"] == encode_rows["ppp"]


@pytest.mark.parametrize("name", ["tcrh_encode_raw.pcap", "tcrh_encode_ppp.pcap",
                                  "tcrh_walk_raw.pcap", "tcrh_walk_ppp.pcap"])
def test_valid_captures_have_no_invalid_frame(env, golden, name):
    """The plan's acceptance check: -Y 'tcrh.valid == 0' prints nothing."""
    out, index = golden
    p = tshark(env, ["-r", out / name, "-Y", "tcrh.valid == 0", "-T", "fields", "-e", "frame.number"])
    assert p.stdout == ""
    # ...and every frame does carry a decoded, valid T-CRH (the filter is not vacuous)
    assert len(frames_matching(env, out / name, "tcrh.valid == 1")) == len(index[name])
    assert frames_matching(env, out / name, "_ws.lua.error || _ws.malformed") == []


# ------------------------------------------- process / link_down vectors

VECTOR_FIELDS = [
    "frame.number", "ipv6.routing.type", "ipv6.routing.segleft", "tcrh.valid", "tcrh.reason",
    "tcrh.flags", "tcrh.dev_hop", "tcrh.current_hop", "tcrh.current_sid", "tcrh.current_deadline",
    "tcrh.capture_clock", "tcrh.margin", "tcrh.late", "_ws.expert.message", "_ws.lua.error",
]


def _vectors_by_frame():
    """frame number -> (section, vector, 'in'/'out', bytes) for tcrh_vectors_raw.pcap."""
    out, n = {}, 0
    for section in ("process", "link_down"):
        for v in TCRH[section]:
            n += 1
            out[n] = (section, v, "in", bytes.fromhex(v["hex_in"]))
            if v.get("expect_hex_out"):
                n += 1
                out[n] = (section, v, "out", bytes.fromhex(v["expect_hex_out"]))
    return out


def _reference_reason(raw):
    """What chronoroute.proto says about these bytes: None (valid) or the step-1 reason."""
    try:
        P.TcrhHeader.decode_prefix(raw)
    except P.TcrhDecodeError as err:
        return err.reason
    return None


@pytest.fixture(scope="module")
def vector_rows(env, golden):
    out, index = golden
    rows = fields(env, out / "tcrh_vectors_raw.pcap", VECTOR_FIELDS)
    assert len(rows) == len(index["tcrh_vectors_raw.pcap"]) == len(_vectors_by_frame())
    return rows


def test_process_vectors_validity_and_position(vector_rows):
    frames = _vectors_by_frame()
    checked_late = 0
    for r in vector_rows:
        section, v, which, raw = frames[int(r["frame.number"])]
        where = f"{section}/{v['name']}/{which}"
        assert r["_ws.lua.error"] == "", where
        if len(raw) >= 3 and raw[2] != 253:
            # not a T-CRH (the wrong-type vectors carry a CRH-16): Wireshark's own decoder
            assert r["ipv6.routing.type"] == str(raw[2]) and r["tcrh.valid"] == "", where
            continue
        reason = _reference_reason(raw)
        if section == "process" and which == "in" and v["expect_action"] == "drop_malformed":
            assert reason == v["expect_reason"], where          # reference agrees with golden
        assert r["tcrh.valid"] == ("0" if reason else "1"), where
        assert r["tcrh.reason"] == (reason or ""), where
        if reason:
            assert r["tcrh.current_sid"] == r["tcrh.current_hop"] == "", where
            continue
        hdr = P.TcrhHeader.decode_prefix(raw)[0]
        assert int(r["tcrh.flags"], 16) == hdr.flags and int(r["tcrh.dev_hop"]) == hdr.dev_hop, where
        k = hdr.current_hop_index()
        assert int(r["tcrh.current_hop"]) == k, where
        if k == 0:
            assert r["tcrh.current_sid"] == r["tcrh.current_deadline"] == "", where
            continue
        assert int(r["tcrh.current_sid"]) == hdr.sids_rev[hdr.segments_left], where
        assert int(r["tcrh.current_deadline"]) == hdr.deadline(k), where
        messages = lst(r["_ws.expert.message"])
        assert any(m.startswith("DEV set by") for m in messages) == hdr.is_dev, where
        assert any(m.startswith("GREEDY set") for m in messages) == hdr.is_greedy, where
        if section == "process" and which == "in":
            # the input frame is stamped at unit now_u: the dissector sees the node's clock
            assert k == v["expect_hop_index"] and hdr.deadline(k) == v["expect_deadline_u"], where
            assert int(r["tcrh.capture_clock"]) == v["now_u"], where
            assert int(r["tcrh.margin"]) == P.serial_diff(hdr.deadline(k), v["now_u"]), where
            late = P.serial_diff(v["now_u"], hdr.deadline(k)) > 0
            if abs(P.serial_diff(hdr.deadline(k), v["now_u"])) * hdr.unit_ns > 120 * 10**9:
                # half-range wrap vectors: margin of 2^31 units, flagged as implausible
                assert r["tcrh.late"] == "", where
                assert any("implausible" in m for m in messages), where
                continue
            assert r["tcrh.late"] == ("1" if late else "0"), where
            if not hdr.is_dev:
                # this node's own deadline check (spec 6 step 2) == the golden expect_late
                assert late == v["expect_late"], where
                checked_late += 1
    assert checked_late >= 15


MALFORMED_REASONS = ("truncated", "numhops_zero", "sl_gt_numhops", "length_mismatch")


@pytest.mark.parametrize("reason", MALFORMED_REASONS)
def test_malformed_frames_get_valid_0_and_expert_info(env, golden, reason):
    out, _ = golden
    pcap = out / "tcrh_vectors_raw.pcap"
    want = sorted(n for n, (_s, _v, _w, raw) in _vectors_by_frame().items()
                  if len(raw) < 3 or raw[2] == 253 and _reference_reason(raw) == reason)
    assert want, reason
    assert frames_matching(env, pcap, f"tcrh.malformed.{reason}") == want
    assert frames_matching(env, pcap, f'tcrh.reason == "{reason}"') == want
    # every malformed frame is also caught by the validity filter
    assert set(want) <= set(frames_matching(env, pcap, "tcrh.valid == 0"))


def test_validity_filter_lists_exactly_the_malformed_frames(env, golden):
    out, _ = golden
    want = sorted(n for n, (_s, _v, _w, raw) in _vectors_by_frame().items()
                  if (len(raw) < 3 or raw[2] == 253) and _reference_reason(raw) is not None)
    assert frames_matching(env, out / "tcrh_vectors_raw.pcap", "tcrh.valid == 0") == want
    assert frames_matching(env, out / "tcrh_vectors_raw.pcap", "_ws.lua.error") == []


def test_nonzero_reserved_bits_are_accepted_with_a_note(vector_rows):
    frames = _vectors_by_frame()
    for r in vector_rows:
        _s, v, which, _raw = frames[int(r["frame.number"])]
        if v["name"] == "reserved-bits-ignored":
            assert r["tcrh.valid"] == "1"
            messages = lst(r["_ws.expert.message"])
            assert any(m.startswith("Reserved flag bits 0x88") for m in messages), messages
            assert any(m.startswith("Reserved byte is not zero") for m in messages), messages
            assert any(m.startswith("Padding is not zero") for m in messages), messages


# ------------------------------------------------------------- process walks

WALK_FIELDS = [
    "frame.number", "ipv6.dst", "ipv6.routing.segleft", "tcrh.valid", "tcrh.flags",
    "tcrh.flags.dev", "tcrh.dev_hop", "tcrh.current_hop", "tcrh.current_sid",
    "tcrh.current_deadline", "tcrh.current_deadline_ms", "tcrh.capture_clock", "tcrh.margin",
    "tcrh.margin_ms", "tcrh.late",
]

V0 = next(v for v in ENCODE if v["name"] == "v0-3hop")
UC3 = next(v for v in ENCODE if v["name"] == "unit-code-3")


def _per_hop(budgets):
    return [b - a for a, b in zip([0] + budgets[:-1], budgets)]


def _walks():
    v0 = bytes.fromhex(V0["expect_hex"])
    uc3 = bytes.fromhex(UC3["expect_hex"])
    return {
        "demo-greedy-late-hop6": W.demo_walk(TCRH),
        "v0-continue-late-hop2": W.process_walk(v0, 1000 * MS, [5 * MS, 9 * MS, 3 * MS], policy="continue"),
        "v0-ingress-link-down": W.process_walk(v0, 1000 * MS, [9 * MS], link_down_at={0}),
        "v0-drop-late-hop1": W.process_walk(v0, 1000 * MS, [7 * MS], policy="drop"),
        # arriving exactly at every cumulative budget is on time (D_k >= B_k)
        "uc3-exact-budgets": W.process_walk(uc3, int(UC3["t_ingress_gps_ns"]),
                                            _per_hop(UC3["cumulative_budgets_ns"])),
    }


@pytest.fixture(scope="module")
def walk_pcaps(tmp_path_factory):
    out = tmp_path_factory.mktemp("walks")
    made = {}
    for name, walk in _walks().items():
        for lt, code in W.LINKTYPES.items():
            path = W.write_pcap(out / f"{name}_{lt}.pcap", W.walk_frames(walk), code)
            made[(name, lt)] = (walk, path)
    return made


@pytest.mark.parametrize("linktype", ["raw", "ppp"])
@pytest.mark.parametrize("name", list(_walks()))
def test_walk_frames_match_the_reference(env, walk_pcaps, name, linktype):
    walk, path = walk_pcaps[(name, linktype)]
    rows = fields(env, path, WALK_FIELDS)
    assert len(rows) == len(walk.frames)
    for wf, arrival, r in zip(walk.frames, walk.arrivals, rows):
        rh = wf.routing_header
        hdr = P.TcrhHeader.decode_prefix(rh)[0]
        u = hdr.unit_ns
        assert r["tcrh.valid"] == "1"
        assert r["ipv6.dst"] == str(W.ipaddress.IPv6Address(W.sid_address(wf.to_sid)))
        assert int(r["ipv6.routing.segleft"]) == hdr.segments_left
        assert int(r["tcrh.flags"], 16) == hdr.flags and int(r["tcrh.dev_hop"]) == hdr.dev_hop
        assert int(r["tcrh.current_sid"]) == wf.to_sid
        # the receiving node's deadline, from the reference processing
        dk = arrival.result.deadline_u
        assert int(r["tcrh.current_hop"]) == arrival.result.hop_index
        assert int(r["tcrh.current_deadline"]) == dk
        assert Fraction(r["tcrh.current_deadline_ms"]) == ms(dk, u)
        # the frame is stamped at the arrival time, so the dissector sees the node's clock
        assert int(r["tcrh.capture_clock"]) == arrival.now_u
        margin = P.serial_diff(dk, arrival.now_u)
        assert int(r["tcrh.margin"]) == margin
        assert Fraction(r["tcrh.margin_ms"]) == ms(margin, u)
        assert r["tcrh.late"] == ("1" if P.is_late(arrival.now_u, dk) else "0")
        if not hdr.is_dev:
            # the node's own check (spec 6 step 2) agrees with what the capture shows
            assert (r["tcrh.late"] == "1") == arrival.result.late


def test_walk_expert_counts(env, walk_pcaps):
    walk, path = walk_pcaps[("demo-greedy-late-hop6", "ppp")]
    dev_frames = [i + 1 for i, wf in enumerate(walk.frames) if wf.routing_header[4] & P.FLAG_DEV]
    late_frames = [i + 1 for i, (wf, a) in enumerate(zip(walk.frames, walk.arrivals))
                   if P.is_late(a.now_u, a.result.deadline_u)]
    assert dev_frames == [len(walk.frames)] and late_frames == [W.DEMO_SLOW_HOP, len(walk.frames)]
    assert frames_matching(env, path, "tcrh.dev") == dev_frames
    assert frames_matching(env, path, "tcrh.flags.dev == 1") == dev_frames
    assert frames_matching(env, path, "tcrh.late_at_capture") == late_frames
    assert frames_matching(env, path, "tcrh.greedy") == dev_frames
    expert = tshark(env, ["-r", path, "-q", "-z", "expert"]).stdout
    # the count of DEV notes equals the number of frames the walk sent with DEV set
    m = re.search(r"^\s+(\d+)\s+Sequence\s+TCRH\s+DEV set by hop (\d+) ", expert, re.M)
    assert m and int(m.group(1)) == len(dev_frames) and int(m.group(2)) == W.DEMO_SLOW_HOP, expert


def test_ingress_link_down_reports_dev_hop_0(env, walk_pcaps):
    _walk, path = walk_pcaps[("v0-ingress-link-down", "raw")]
    rows = fields(env, path, ["tcrh.dev_hop", "tcrh.flags", "_ws.expert.message"])
    assert len(rows) == 1 and rows[0]["tcrh.dev_hop"] == "0" and rows[0]["tcrh.flags"] == "0x03"
    assert "DEV set by the ingress (its first link was down)" in rows[0]["_ws.expert.message"]


# ------------------------------------------------------------ timebase preference

def test_timebase_off_removes_the_margin(env, walk_pcaps):
    _walk, path = walk_pcaps[("demo-greedy-late-hop6", "raw")]
    rows = fields(env, path, ["tcrh.current_sid", "tcrh.margin", "tcrh.late"],
                  prefs=["tcrh.timebase:off"])
    assert rows and all(r["tcrh.current_sid"] and r["tcrh.margin"] == r["tcrh.late"] == "" for r in rows)


def test_offset_timebase_for_simulation_time_captures(env, tmp_path):
    """
    An ns-3-style capture stamps SIMULATION time (seconds since 0, shown as
    1970). With tcrh.timebase = offset and tcrh.offset_ns = t0_gps_ns the
    dissector recovers exactly the same margins as for the GPS-stamped file.
    """
    walk = W.demo_walk(TCRH)
    t0 = walk.t_ingress_gps_ns - 5 * 10**9            # simulation started 5 s before the ingress
    sim_frames = [W.Frame(f.t_gps_ns - t0 - W.GPS_TO_PCAP_NS, f.packet, f.name)
                  for f in W.walk_frames(walk)]      # pcap stamp = t_gps - t0
    path = W.write_pcap(tmp_path / "sim.pcap", sim_frames, W.LINKTYPE_PPP)
    rows = fields(env, path, ["frame.time_epoch", "tcrh.margin", "tcrh.late"],
                  prefs=["tcrh.timebase:offset", f"tcrh.offset_ns:{t0}"])
    for a, r in zip(walk.arrivals, rows):
        assert Fraction(r["frame.time_epoch"]) == Fraction(a.t_gps_ns - t0, 10**9)
        assert int(r["tcrh.margin"]) == P.serial_diff(a.result.deadline_u, a.now_u)
    # read as UTC the clock is decades off: margins are flagged, nobody is called late
    utc = fields(env, path, ["tcrh.late", "_ws.expert.message"])
    assert all(r["tcrh.late"] == "" and "implausible" in r["_ws.expert.message"] for r in utc)


# ------------------------------------------------------------ UDP / TCP checksums

def test_wireshark_verifies_our_checksums_when_it_can(env, golden, tmp_path):
    """
    Wireshark checks a UDP/TCP checksum against the CURRENT Destination
    Address; it cannot know a T-CRH's final destination. Our checksums use the
    final destination (RFC 8200 8.1), so Wireshark agrees exactly when the two
    are the same (Segments Left = 0) and disagrees otherwise. Measured on 4.6.4.
    """
    out, _ = golden
    rows = fields(env, out / "tcrh_walk_raw.pcap", ["ipv6.routing.segleft", "udp.checksum.status"],
                  prefs=["udp.check_checksum:TRUE"])
    assert {(r["ipv6.routing.segleft"] == "0", r["udp.checksum.status"]) for r in rows} == {
        (True, "1"), (False, "0")}                    # 1 = Good, 0 = Bad
    # the encapsulated packet's own UDP (no routing header) always verifies
    enc = fields(env, out / "tcrh_encode_raw.pcap", ["udp.checksum.status"],
                 dfilter="ipv6.routing.nxt == 41", prefs=["udp.check_checksum:TRUE"])
    assert [r["udp.checksum.status"] for r in enc] == ["1"]
    # a TCP segment that has reached its final endpoint (SL = 0) verifies too
    v = next(x for x in ENCODE if x["next_header"] == 6)
    rh = bytearray(bytes.fromhex(v["expect_hex"]))
    rh[3] = 0
    final = W.sid_address(v["sids_fwd"][-1])
    pkt = W.packet_with_routing_header(bytes(rh), src=W.HOST_SRC, dst=final, final_dst=final,
                                       payload=b"tcp payload")
    path = W.write_pcap(tmp_path / "tcp.pcap", [W.Frame(10**9, pkt)], W.LINKTYPE_RAW)
    tcp = fields(env, path, ["tcp.checksum.status", "tcrh.valid"], prefs=["tcp.check_checksum:TRUE"])
    assert tcp == [{"tcp.checksum.status": "1", "tcrh.valid": "1"}]


# --------------------------------------------------------- CRH-16 / CRH-32 native

def test_crh_is_still_decoded_natively(env, golden):
    """
    Types 5 and 6 belong to Wireshark's own CRH decoder (tcrh.lua does not
    touch them). Known Wireshark 4.6 quirk, pinned here so a fix is noticed:
    its SID loop stops at the first SID 0 and reads one SID past a list that
    fills the header exactly (no zero padding slot), which raises a
    "Malformed Packet" exception after all SIDs are shown.
    """
    out, index = golden
    rows = fields(env, out / "crh_encode_raw.pcap", [
        "ipv6.routing.type", "ipv6.routing.segleft", "ipv6.routing.crh16.current_sid",
        "ipv6.routing.crh16.sid", "ipv6.routing.crh32.current_sid", "ipv6.routing.crh32.sid",
        "tcrh.valid", "_ws.malformed", "_ws.lua.error"])
    by_name = {v["name"]: v for v in CRH["encode"]}
    assert len(rows) == len(index["crh_encode_raw.pcap"])
    for name, r in zip(index["crh_encode_raw.pcap"], rows):
        vname, sl = name.rsplit("/sl", 1)
        v = by_name[vname]
        slots = v["expect_decoded_sids_rev"]
        kind = "crh16" if v["routing_type"] == 5 else "crh32"
        assert r["ipv6.routing.type"] == str(v["routing_type"]) and r["ipv6.routing.segleft"] == sl
        assert int(r[f"ipv6.routing.{kind}.current_sid"]) == slots[int(sl)], name
        listed = slots[:slots.index(0)] if 0 in slots else slots
        assert ints(r[f"ipv6.routing.{kind}.sid"]) == listed, name
        assert r["tcrh.valid"] == "" and r["_ws.lua.error"] == ""
        assert (r["_ws.malformed"] != "") == (0 not in slots), name


# ------------------------------------------------------------------ hygiene

def test_no_globals_leak_and_no_undefined_globals(env, golden, tmp_path):
    out, _ = golden
    strict = dict(env, CR_LUA_UNDER_TEST=str(LUA))
    for name in ("tcrh_encode_ppp.pcap", "tcrh_vectors_raw.pcap", "tcrh_walk_raw.pcap"):
        p = tshark(strict, ["-X", f"lua_script:{STRICT_LOAD}", "-r", out / name, "-V"],
                   lua=False, allow_stderr=True)
        assert p.stderr.splitlines() == [f"STRICT_LOADED {LUA}"], p.stderr
        assert "ChronoRoute T-CRH" in p.stdout            # it really dissected under the proxy
    # control: the probe does notice a leaking script
    leaky = tmp_path / "leaky.lua"
    leaky.write_text("leak_canary = 1\nlocal function f() return undefined_name end\nf()\n")
    p = tshark(dict(env, CR_LUA_UNDER_TEST=str(leaky)),
               ["-X", f"lua_script:{STRICT_LOAD}", "-r", out / "tcrh_walk_raw.pcap", "-c", "1"],
               lua=False, allow_stderr=True)
    assert "LEAK leak_canary" in p.stderr and "UNDEFINED undefined_name" in p.stderr


def test_lua_source_is_plain_local_lua54():
    text = LUA.read_text(encoding="utf-8")
    assert "\r" not in text
    # no Lua 5.1/5.2-only calls that 5.4 removed
    for gone in ("setfenv", "getfenv", "unpack(", "loadstring", "bit32.", "module("):
        assert gone not in text.replace("table.unpack(", ""), gone


# ------------------------------------------------- install, profile, check_pcap

def test_linux_plugin_folder_install(env, golden, tmp_path):
    """README's Linux install: copy tcrh.lua to ~/.local/lib/wireshark/plugins."""
    out, _ = golden
    home = tmp_path / "home"
    plugins = home / ".local" / "lib" / "wireshark" / "plugins"
    plugins.mkdir(parents=True)
    shutil.copy(LUA, plugins / "tcrh.lua")
    e = dict(env, HOME=str(home), XDG_CONFIG_HOME=str(home / "xdg"))
    listing = tshark(e, ["-G", "plugins"], lua=False).stdout
    assert re.search(rf"^tcrh\.lua\s.*Lua script\s+{re.escape(str(plugins / 'tcrh.lua'))}$", listing, re.M)
    rows = fields(e, out / "tcrh_walk_ppp.pcap", ["tcrh.valid", "tcrh.current_sid"], lua=False)
    assert len(rows) == 7 and {r["tcrh.valid"] for r in rows} == {"1"}
    # installed AND passed with -X: the second copy steps aside instead of failing
    p = tshark(e, ["-r", out / "tcrh_walk_ppp.pcap", "-T", "fields", "-e", "tcrh.valid"],
               allow_stderr=True)
    assert p.stdout.split() == ["1"] * 7
    assert p.stderr.strip() == "tcrh.lua: a T-CRH dissector is already registered; not loading a second copy"


def test_chronoroute_profile_columns_and_colours(env, golden):
    out, _ = golden
    colorfilters = (PROFILE / "colorfilters").read_text(encoding="utf-8")
    assert "@tcrh.flags.dev == 1@[52428,0,0]" in colorfilters           # red background
    config = Path(env["WIRESHARK_CONFIG_DIR"])
    shutil.copytree(PROFILE, config / "profiles" / "ChronoRoute", dirs_exist_ok=True)

    def psml(pcap):
        p = tshark(env, ["-C", "ChronoRoute", "-r", pcap, "--color", "-T", "psml"])
        root = ET.fromstring(p.stdout)
        heads = [s.text for s in root.find("structure")]
        packets = [(pk.get("background"), pk.get("foreground"),
                    dict(zip(heads, [s.text or "" for s in pk.findall("section")])))
                   for pk in root.findall("packet")]
        return heads, packets

    heads, packets = psml(out / "tcrh_walk_ppp.pcap")
    assert heads == ["No.", "Time", "Source", "Destination", "SL", "Cur SID", "T-CRH flags",
                     "Margin (ms)", "Protocol", "Length", "Info"]
    walk = W.demo_walk(TCRH)
    for (bg, fg, cols), wf in zip(packets, walk.frames):
        rh = wf.routing_header
        assert cols["SL"] == str(rh[3]) and cols["Cur SID"] == str(wf.to_sid)
        assert cols["T-CRH flags"] == f"0x{rh[4]:02x}"
        if rh[4] & P.FLAG_DEV:
            assert (bg, fg) == ("#cc0000", "#ffffff")                  # DEV: white on red
        else:
            assert bg != "#cc0000"
    assert sum(bg == "#cc0000" for bg, _fg, _c in packets) == 1
    # malformed frames get their own colour
    _heads, vec = psml(out / "tcrh_vectors_raw.pcap")
    bad = set(frames_matching(env, out / "tcrh_vectors_raw.pcap", "tcrh.valid == 0"))
    for bg, fg, cols in vec:
        if int(cols["No."]) in bad:
            assert (bg, fg) == ("#000000", "#ffff00")


def run_check(env, *args):
    return subprocess.run(["bash", str(CHECK_PCAP), *map(str, args)], env=env,
                          capture_output=True, text=True, timeout=300)


def test_check_pcap_on_a_valid_ppp_capture(env, golden):
    out, _ = golden
    p = run_check(env, out / "tcrh_walk_ppp.pcap")
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert lines[0].split() == ["frame", "ipv6.dst", "SL", "flags", "cur_sid", "margin_ms", "valid"]
    walk = W.demo_walk(TCRH)
    for line, wf, a in zip(lines[1:], walk.frames, walk.arrivals):
        frame, dst, sl, flags, sid, margin, valid = line.split()
        assert dst == str(W.ipaddress.IPv6Address(W.sid_address(wf.to_sid)))
        assert (int(sl), int(flags, 16), int(sid)) == (wf.routing_header[3], wf.routing_header[4], wf.to_sid)
        u = P.unit_ns((wf.routing_header[4] >> 4) & 3)
        assert Fraction(margin) == ms(P.serial_diff(a.result.deadline_u, a.now_u), u)
        assert valid == "yes"
    assert lines[-1] == (f"check_pcap: {out / 'tcrh_walk_ppp.pcap'}: 7 T-CRH frames, 0 invalid, "
                         "1 with DEV, 2 late at capture, 0 quoted in ICMPv6 errors (not counted)")


def test_check_pcap_reports_invalid_frames(env, golden):
    out, _ = golden
    p = run_check(env, "--quiet", out / "tcrh_vectors_raw.pcap")
    assert p.returncode == 1
    listed = sorted(int(m) for m in re.findall(r"^  frame (\d+): ", p.stderr, re.M))
    assert listed == frames_matching(env, out / "tcrh_vectors_raw.pcap", "tcrh.valid == 0")
    reasons = set(re.findall(r"^  frame \d+: (\w+)$", p.stderr, re.M))
    assert reasons == set(MALFORMED_REASONS)


def test_check_pcap_warns_about_zero_udp_checksums(env, tmp_path):
    """ns-3 with checksums disabled writes UDP checksum 0, which IPv6 forbids: a warning, not invalid."""
    frames = []
    for f in W.walk_frames(W.demo_walk(TCRH)):
        p = bytearray(f.packet)
        csum = 40 + (p[41] + 1) * 8 + 6           # IPv6 header + T-CRH + UDP checksum offset
        p[csum:csum + 2] = b"\x00\x00"
        frames.append(W.Frame(f.t_gps_ns, bytes(p), f.name))
    path = W.write_pcap(tmp_path / "zero.pcap", frames, W.LINKTYPE_PPP)
    p = run_check(env, "--quiet", path)
    assert p.returncode == 0, p.stderr
    assert "warning: 7 frames have a zero UDP checksum" in p.stderr
    clean = run_check(env, "--quiet", W.write_pcap(tmp_path / "ok.pcap", W.walk_frames(W.demo_walk(TCRH)),
                                                   W.LINKTYPE_PPP))
    assert clean.returncode == 0 and clean.stderr == ""


# ------------------------------------------------- T-CRH quoted in ICMPv6 errors

def _quoted_capture(tmp_path, linktype):
    """
    The demo walk's frames, plus three ICMPv6 errors sent back to the host, each
    quoting a packet (RFC 4443): a Parameter Problem quoting the LATE frame at the
    slow hop, a Time Exceeded quoting the last frame (DEV set), and a Parameter
    Problem quoting a MALFORMED header (Segments Left > Num Hops, the kind of
    header that makes a node send that error). Returns (path, walk, numbers of
    the three ICMPv6 frames).
    """
    walk = W.demo_walk(TCRH)
    frames = list(W.walk_frames(walk))
    late = frames[W.DEMO_SLOW_HOP - 1]
    last = frames[-1]
    rejecter = W.sid_address(walk.frames[W.DEMO_SLOW_HOP - 1].to_sid)
    bad_rh = bytearray(walk.frames[0].routing_header)
    bad_rh[3] = bad_rh[5] + 1                                     # SL > Num Hops
    bad = W.packet_with_routing_header(bytes(bad_rh), src=W.HOST_SRC, dst=W.sid_address(0x5c8),
                                       final_dst=W.sid_address(0xF003), payload=W.payload_bytes(9, 1))
    errors = [
        W.Frame(late.t_gps_ns + 1 * MS, W.icmpv6_error_packet(late.packet, src=rejecter, dst=W.HOST_SRC,
                                                              pointer=43), "param-problem-late"),
        W.Frame(last.t_gps_ns + 1 * MS, W.icmpv6_error_packet(last.packet, src=rejecter, dst=W.HOST_SRC,
                                                              icmp_type=W.ICMPV6_TIME_EXCEEDED),
                "time-exceeded-dev"),
        W.Frame(last.t_gps_ns + 2 * MS, W.icmpv6_error_packet(bad, src=rejecter, dst=W.HOST_SRC, pointer=43),
                "param-problem-malformed"),
    ]
    all_frames = sorted(frames + errors, key=lambda f: f.t_gps_ns)
    numbers = [all_frames.index(e) + 1 for e in errors]
    path = W.write_pcap(tmp_path / f"quoted_{linktype}.pcap", all_frames, W.LINKTYPES[linktype])
    return path, walk, numbers


@pytest.mark.parametrize("linktype", ["raw", "ppp"])
def test_quoted_tcrh_gets_no_margin_and_no_late_verdict(env, tmp_path, linktype):
    path, walk, icmp = _quoted_capture(tmp_path, linktype)
    rows = fields(env, path, ["frame.number", "icmpv6.type", "icmpv6.checksum.status", "tcrh.quoted",
                              "tcrh.valid", "tcrh.margin", "tcrh.late", "tcrh.flags.dev"])
    by_no = {int(r["frame.number"]): r for r in rows}
    assert len(rows) == len(walk.frames) + 3
    for no, r in by_no.items():
        if no in icmp:
            assert r["tcrh.quoted"] == "1", r
            assert r["tcrh.margin"] == "" and r["tcrh.late"] == "", r      # no timing verdict
            assert r["icmpv6.checksum.status"] == "1", r                    # 1 = Good: Wireshark verified it
        else:
            assert r["tcrh.quoted"] == "0" and r["tcrh.margin"] != "" and r["icmpv6.type"] == "", r
    assert [by_no[n]["icmpv6.type"] for n in icmp] == ["4", "3", "4"]
    assert by_no[icmp[2]]["tcrh.valid"] == "0"            # the quoted header IS malformed ...
    # ... and the expert notes count real headers only: DEV and late notes ignore the copies
    assert frames_matching(env, path, "tcrh.dev") == [n for n in by_no if n not in icmp
                                                      and by_no[n]["tcrh.flags.dev"] == "True"]
    assert frames_matching(env, path, "tcrh.late_at_capture") == [
        n for n in by_no if n not in icmp and by_no[n]["tcrh.late"] == "1"]
    assert frames_matching(env, path, "tcrh.quoted_in_icmpv6") == icmp
    # the ICMPv6 frames keep their own Info column
    info = fields(env, path, ["frame.number", "_ws.col.info"], dfilter="icmpv6")
    assert all("T-CRH" not in r["_ws.col.info"] for r in info) and len(info) == 3


def test_check_pcap_counts_quoted_headers_apart(env, tmp_path):
    path, walk, icmp = _quoted_capture(tmp_path, "ppp")
    p = run_check(env, path)
    assert p.returncode == 0, p.stderr                    # a quoted malformed header is not invalid
    lines = p.stdout.splitlines()
    quoted = [line.split() for line in lines[1:-1] if line.split()[-1] == "quoted"]
    assert [int(q[0]) for q in quoted] == icmp and all(q[5] == "-" for q in quoted)
    assert lines[-1] == (f"check_pcap: {path}: 7 T-CRH frames, 0 invalid, 1 with DEV, 2 late at capture, "
                         "3 quoted in ICMPv6 errors (not counted)")
    # the same counts as the capture without the ICMPv6 errors
    clean = run_check(env, "--quiet", W.write_pcap(tmp_path / "clean.pcap", W.walk_frames(walk), W.LINKTYPE_PPP))
    assert clean.stdout.split(": ", 2)[2].startswith("7 T-CRH frames, 0 invalid, 1 with DEV, 2 late at capture")


def test_check_pcap_exit_codes(env, golden, tmp_path):
    out, _ = golden
    assert run_check(env, out / "crh_encode_raw.pcap").returncode == 3      # no T-CRH at all
    usage = run_check(env)
    assert usage.returncode == 2 and "check_pcap.sh [--timebase" in usage.stderr
    assert run_check(env, tmp_path / "missing.pcap").returncode == 2
    assert run_check(env, "--timebase", "nonsense", out / "tcrh_walk_raw.pcap").returncode == 2
    off = run_check(env, "--timebase", "off", out / "tcrh_walk_raw.pcap")
    assert off.returncode == 0 and "0 late at capture" in off.stdout
    notpcap = tmp_path / "not.pcap"
    notpcap.write_bytes(b"this is not a capture")
    assert run_check(env, notpcap).returncode == 2

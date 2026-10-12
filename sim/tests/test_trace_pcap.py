"""
chronoroute.trace.pcap: the pcap writer. Pure Python, no tshark.

Everything is checked against an INDEPENDENT minimal pcap/IPv6 reader written
below, against the golden vectors, and against chronoroute.proto (the
reference processing). sim/tests/test_wireshark_dissector.py then shows the
same files to tshark.
"""

import ipaddress
import json
import struct
from datetime import datetime, timezone

import pytest
from hypothesis import given, settings, strategies as st

import chronoroute.proto as P
from chronoroute import provenance as prov
from chronoroute.trace import pcap as W

TCRH = W.load_golden("tcrh_vectors.json")
CRH = W.load_golden("crh_vectors.json")
ENC = {v["name"]: v for v in TCRH["encode"]}
PROC = {v["name"]: v for v in TCRH["process"]}


# ------------------------------------------------- an independent pcap reader

def read_pcap(path):
    """(header dict, [(sec, frac, incl, orig, frame bytes)]) - written from the format, not from W."""
    data = path.read_bytes()
    magic_le = struct.unpack_from("<I", data, 0)[0]
    assert magic_le in (0xA1B23C4D, 0xA1B2C3D4), hex(magic_le)
    vmaj, vmin, zone, sigfigs, snaplen, linktype = struct.unpack_from("<HHiIII", data, 4)
    hdr = dict(magic=magic_le, version=(vmaj, vmin), zone=zone, sigfigs=sigfigs,
               snaplen=snaplen, linktype=linktype)
    recs, off = [], 24
    while off < len(data):
        sec, frac, incl, orig = struct.unpack_from("<IIII", data, off)
        off += 16
        recs.append((sec, frac, incl, orig, data[off:off + incl]))
        off += incl
    assert off == len(data)
    return hdr, recs


def ipv6_of(frame, linktype):
    if linktype == W.LINKTYPE_PPP:
        assert frame[:2] == b"\x00\x57"           # PPP protocol field: IPv6
        return frame[2:]
    assert linktype == W.LINKTYPE_RAW
    return frame


def parse_ipv6(pkt):
    first, plen, nh, hlim = struct.unpack_from("!IHBB", pkt, 0)
    assert first >> 28 == 6
    assert plen == len(pkt) - 40
    return dict(nh=nh, hlim=hlim, src=pkt[8:24], dst=pkt[24:40], payload=pkt[40:])


def ones_sum_ok(pseudo, segment):
    """A correct checksum makes the one's complement sum of everything 0xFFFF."""
    data = pseudo + segment + (b"\x00" if (len(pseudo) + len(segment)) % 2 else b"")
    s = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return s == 0xFFFF


def pseudo(src, dst, length, nh):
    return src + dst + struct.pack("!I3xB", length, nh)


# ---------------------------------------------------------------- checksums

def test_internet_checksum_rfc1071_example():
    # RFC 1071 section 3 worked example: the words sum to 0xDDF2 (after folding),
    # so the checksum is its complement 0x220D.
    assert W.internet_checksum(bytes.fromhex("0001f203f4f5f6f7")) == 0x220D
    # an odd length is padded with one zero byte
    assert W.internet_checksum(b"\x01") == W.internet_checksum(b"\x01\x00") == 0xFEFF
    assert W.internet_checksum(b"") == 0xFFFF


def test_udp_checksum_uses_the_final_destination():
    src, final = W.sid_address(0xF000), W.sid_address(7)
    udp = W.udp_datagram(src, final, b"hello")
    assert struct.unpack("!HHH", udp[:6]) == (W.DEFAULT_PORT, W.DEFAULT_PORT, 13)
    assert ones_sum_ok(pseudo(src, final, len(udp), 17), udp)
    # the checksum depends on the final destination, not on any hop's address
    other = W.udp_datagram(src, W.sid_address(3), b"hello")
    assert other[6:8] != udp[6:8]
    # and the packet built around it keeps one checksum whatever the current DA is
    rh = bytes.fromhex(ENC["v0-3hop"]["expect_hex"])
    a = W.packet_with_routing_header(rh, src=src, dst=W.sid_address(2), final_dst=final, payload=b"x")
    b = W.packet_with_routing_header(rh, src=src, dst=W.sid_address(3), final_dst=final, payload=b"x")
    assert a[40:] == b[40:] and a[24:40] != b[24:40]


def test_udp_zero_checksum_is_sent_as_ffff():
    src, final = W.sid_address(1), W.sid_address(2)
    # choose the last two payload bytes so that the computed checksum is 0
    base = W.udp_datagram(src, final, b"ab\x00\x00")
    c0 = struct.unpack("!H", base[6:8])[0]
    payload = b"ab" + struct.pack("!H", c0)
    udp = W.udp_datagram(src, final, payload)
    assert W.internet_checksum(pseudo(src, final, len(udp), 17) + udp[:6] + b"\0\0" + udp[8:]) == 0
    assert udp[6:8] == b"\xff\xff"               # RFC 768 / RFC 8200 8.1: never 0 over IPv6


def test_tcp_segment_checksum_and_fields():
    src, final = W.sid_address(5), W.sid_address(6)
    seg = W.tcp_segment(src, final, b"payload!", seq=7)
    sport, dport, seq, ack, off, flags, win = struct.unpack_from("!HHIIBBH", seg, 0)
    assert (sport, dport, seq, ack, off >> 4, flags, win) == (
        W.DEFAULT_PORT, W.DEFAULT_PORT, 7, 0, 5, 0x18, 65535)
    assert ones_sum_ok(pseudo(src, final, len(seg), 6), seg)


def test_ipv6_packet_header():
    pkt = W.ipv6_packet("fd00::1", "fd00::2", 43, b"abcd", hop_limit=9, traffic_class=0xB8,
                        flow_label=0x12345)
    first, plen, nh, hlim = struct.unpack_from("!IHBB", pkt, 0)
    assert (first >> 28, (first >> 20) & 0xFF, first & 0xFFFFF) == (6, 0xB8, 0x12345)
    assert (plen, nh, hlim) == (4, 43, 9)
    assert pkt[8:24] == ipaddress.IPv6Address("fd00::1").packed
    assert pkt[24:40] == ipaddress.IPv6Address("fd00::2").packed and pkt[40:] == b"abcd"
    with pytest.raises(ValueError):
        W.ipv6_packet("fd00::1", "fd00::2", 43, bytes(70000))
    with pytest.raises(ValueError):
        W.ipv6_packet("fd00::1", "fd00::2", 43, b"", flow_label=1 << 20)


def test_icmpv6_error_quotes_the_invoking_packet():
    src, host = W.sid_address(3), W.HOST_SRC
    rh = bytes.fromhex(ENC["v0-3hop"]["expect_hex"])
    invoking = W.packet_with_routing_header(rh, src=host, dst=src, final_dst=W.sid_address(7), payload=b"x")
    pkt = W.icmpv6_error_packet(invoking, src=src, dst=host, pointer=43)
    ip = parse_ipv6(pkt)
    assert (ip["nh"], ip["src"], ip["dst"]) == (58, W._addr(src), W._addr(host))
    body = ip["payload"]
    assert struct.unpack("!BBHI", body[:8])[0:2] == (4, 0) and struct.unpack("!I", body[4:8])[0] == 43
    assert body[8:] == invoking                               # quoted whole: it is short
    assert ones_sum_ok(pseudo(ip["src"], ip["dst"], len(body), 58), body)   # RFC 4443 2.3
    # a long invoking packet is cut so the error fits the IPv6 minimum MTU (RFC 4443 2.4)
    big = W.icmpv6_error_packet(bytes(3000), src=src, dst=host, icmp_type=W.ICMPV6_TIME_EXCEEDED)
    assert len(big) == W.IPV6_MIN_MTU and big[40] == 3
    with pytest.raises(ValueError):
        W.icmpv6_error_packet(invoking, src=src, dst=host, icmp_type=128)   # an echo is not an error


def test_sid_addresses():
    assert ipaddress.IPv6Address(W.sid_address(3)) == ipaddress.IPv6Address("fd00::3")
    assert ipaddress.IPv6Address(W.sid_address(0xF005)) == ipaddress.IPv6Address("fd00::f005")
    assert ipaddress.IPv6Address(W.sid_address(0x12345678)) == ipaddress.IPv6Address("fd00::1234:5678")
    for bad in (-1, 1 << 32):
        with pytest.raises(ValueError):
            W.sid_address(bad)
    with pytest.raises(TypeError):
        W.sid_address(True)


# ---------------------------------------------------------------- timestamps

def test_gps_to_pcap_clock():
    # GPS epoch = 1980-01-06T00:00:00Z = Unix 315964800, and GPS runs 18 s ahead of UTC
    assert W.gps_to_pcap_ns(0) == (315964800 - 18) * 10**9
    dt = datetime(2026, 10, 10, 13, 58, 0, 123456, tzinfo=timezone.utc)
    t_gps = P.utc_to_gps_ns(dt)
    unix_ns = (int(dt.replace(microsecond=0).timestamp()) * 10**6 + dt.microsecond) * 1000
    assert W.gps_to_pcap_ns(t_gps) == unix_ns          # real UTC after 2017
    assert W.pcap_to_gps_ns(W.gps_to_pcap_ns(t_gps)) == t_gps
    with pytest.raises(ValueError):
        W.gps_to_pcap_ns(-(10**19))
    with pytest.raises(TypeError):
        W.gps_to_pcap_ns(1.5)


@pytest.mark.parametrize("linktype", [W.LINKTYPE_RAW, W.LINKTYPE_PPP])
@pytest.mark.parametrize("nanosecond", [True, False])
def test_pcap_layout(tmp_path, linktype, nanosecond):
    pkt = W.ipv6_packet("fd00::1", "fd00::2", 59, b"")
    t = 1_475_675_898_123_456_789
    path = tmp_path / "x.pcap"
    with open(path, "wb") as fh:
        w = W.PcapWriter(fh, linktype, nanosecond=nanosecond)
        w.write(pkt, t_gps_ns=t)
        w.write(pkt, t_gps_ns=t + 1500)
    hdr, recs = read_pcap(path)
    assert hdr == dict(magic=0xA1B23C4D if nanosecond else 0xA1B2C3D4, version=(2, 4), zone=0,
                       sigfigs=0, snaplen=W.DEFAULT_SNAPLEN, linktype=linktype)
    unix = W.gps_to_pcap_ns(t)
    for (sec, frac, incl, orig, frame), dt in zip(recs, (0, 1500)):
        assert sec == (unix + dt) // 10**9
        assert frac == ((unix + dt) % 10**9 if nanosecond else ((unix + dt) % 10**9) // 1000)
        assert incl == orig == len(frame)
        assert ipv6_of(frame, linktype) == pkt


def test_writer_rejects_bad_input(tmp_path):
    with open(tmp_path / "x.pcap", "wb") as fh:
        with pytest.raises(ValueError):
            W.PcapWriter(fh, 1)                        # Ethernet is not supported
        w = W.PcapWriter(fh, W.LINKTYPE_RAW, snaplen=64)
        with pytest.raises(ValueError):
            w.write(b"\x45" + bytes(39), t_gps_ns=0)   # IPv4
        with pytest.raises(ValueError):                # never truncate silently
            w.write(W.ipv6_packet("fd00::1", "fd00::2", 59, bytes(40)), t_gps_ns=0)


# --------------------------------------------------------- golden encode frames

def test_golden_encode_frames_carry_the_golden_bytes(tmp_path):
    frames = W.golden_encode_frames(TCRH)
    assert [f.name for f in frames] == [v["name"] for v in TCRH["encode"]]
    path = W.write_pcap(tmp_path / "g.pcap", frames, W.LINKTYPE_PPP)
    hdr, recs = read_pcap(path)
    assert hdr["linktype"] == W.LINKTYPE_PPP and len(recs) == len(TCRH["encode"])
    for pid, (v, rec) in enumerate(zip(TCRH["encode"], recs)):
        ip = parse_ipv6(ipv6_of(rec[4], W.LINKTYPE_PPP))
        size = v["expect_size"]
        rh = ip["payload"][:size]
        assert ip["nh"] == 43 and rh.hex() == v["expect_hex"]
        assert ip["src"] == W.HOST_SRC.packed and ip["dst"] == W.sid_address(W.DEFAULT_INGRESS_SID)
        final = W.sid_address(v["sids_fwd"][-1])
        upper = ip["payload"][size:]
        body = W.payload_bytes(pid, W.encode_vector_time_gps_ns(v))
        if v["next_header"] == 17:
            assert ones_sum_ok(pseudo(ip["src"], final, len(upper), 17), upper)
            assert upper[8:] == body
        elif v["next_header"] == 6:
            assert ones_sum_ok(pseudo(ip["src"], final, len(upper), 6), upper)
            assert upper[20:] == body
        elif v["next_header"] == 41:
            inner = parse_ipv6(upper)
            assert inner["nh"] == 17
            assert ones_sum_ok(pseudo(inner["src"], inner["dst"], len(inner["payload"]), 17),
                               inner["payload"])
        else:
            assert v["next_header"] == 59 and upper == b""
        # the stamp is the ingress instant: clock_u(stamp) never passes Epoch_Base
        t = rec[0] * 10**9 + rec[1]
        assert P.clock_u(W.pcap_to_gps_ns(t), v["unit_code"]) in (
            v["expect_epoch_base"], (v["expect_epoch_base"] - 1) % 2**32)
    # every next-header kind of the vectors is covered
    assert {v["next_header"] for v in TCRH["encode"]} == {6, 17, 41, 59}


def test_golden_pcaps_are_deterministic(tmp_path):
    a = W.write_golden_pcaps(tmp_path / "a")
    b = W.write_golden_pcaps(tmp_path / "b")
    assert a == b
    for name in a:
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    index = json.loads((tmp_path / "a" / "frames.json").read_text())
    assert index == a and len(index["tcrh_encode_raw.pcap"]) == len(TCRH["encode"])


def test_golden_vector_frames_include_malformed_inputs():
    frames = W.golden_vector_frames(TCRH)
    names = [f.name for f in frames]
    expected = []
    for section in ("process", "link_down"):
        for v in TCRH[section]:
            expected.append(f"{section}/{v['name']}/in")
            if v.get("expect_hex_out"):
                expected.append(f"{section}/{v['name']}/out")
    assert names == expected
    by_name = dict(zip(names, frames))
    for section in ("process", "link_down"):
        for v in TCRH[section]:
            ip = parse_ipv6(by_name[f"{section}/{v['name']}/in"].packet)
            raw = bytes.fromhex(v["hex_in"])
            assert ip["payload"][:len(raw)] == raw
            if "now_u" in v and len(raw) > 4:
                unit = P.unit_ns((raw[4] >> 4) & 3)
                assert by_name[f"{section}/{v['name']}/in"].t_gps_ns == v["now_u"] * unit
    # a truncated header has nothing after it
    trunc = parse_ipv6(by_name["process/malformed-truncated/in"].packet)
    assert trunc["payload"].hex() == PROC["malformed-truncated"]["hex_in"]


def test_crh_frames_walk_each_vector_on_the_wire():
    frames = W.crh_encode_frames(CRH)
    seen = {}
    for f in frames:
        name, sl = f.name.rsplit("/sl", 1)
        ip = parse_ipv6(f.packet)
        rh_len = (ip["payload"][1] + 1) * 8
        hdr = P.CrhHeader.decode(ip["payload"][:rh_len])
        assert hdr.segments_left == int(sl)
        assert ip["dst"] == W.sid_address(hdr.sids_rev[hdr.segments_left])
        seen.setdefault(name, []).append(int(sl))
    for v in CRH["encode"]:
        n = len(v["sids_fwd"])
        assert seen[v["name"]] == list(range(n - 1, -1, -1))


# ---------------------------------------------------------------- the walk

V0 = bytes.fromhex(ENC["v0-3hop"]["expect_hex"])     # SIDs 2 -> 3 -> 7, D = 1006, 1013, 1021 ms
MS = 10**6
T0 = 1000 * MS                                       # Epoch_Base 1000 at 1 ms units


def _sl_flags_devhop(rh):
    return rh[3], rh[4], rh[6]


def test_walk_on_time():
    w = W.process_walk(V0, T0, [5 * MS, 6 * MS, 7 * MS])
    assert [(f.from_sid, f.to_sid, f.event) for f in w.frames] == [
        (None, 2, "ingress"), (2, 3, "forward"), (3, 7, "forward")]
    assert [_sl_flags_devhop(f.routing_header) for f in w.frames] == [(2, 0, 0), (1, 0, 0), (0, 0, 0)]
    assert [f.t_gps_ns for f in w.frames] == [1005 * MS, 1011 * MS, 1018 * MS]
    assert [a.now_u for a in w.arrivals] == [1005, 1011, 1018]
    assert w.outcome == "deliver" and not any(a.result.late for a in w.arrivals)


def test_walk_late_at_hop1_matches_the_golden_process_vector():
    # one unit late at hop 1 under the greedy policy (vector late-by-one-unit-hop1-greedy)
    w = W.process_walk(V0, T0, [7 * MS, 4 * MS])
    v = PROC["late-by-one-unit-hop1-greedy"]
    assert w.frames[0].routing_header.hex() == v["hex_in"]
    assert w.arrivals[0].now_u == v["now_u"]
    assert w.frames[1].routing_header.hex() == v["expect_hex_out"]
    assert (w.frames[1].to_sid, w.frames[1].event) == (7, "fallback_late")
    assert w.outcome == "deliver" and w.arrivals[0].result.late


def test_walk_policies():
    late_hop2 = [5 * MS, 9 * MS, 3 * MS]            # arrive at SID 3 at 1014 > 1013
    g = W.process_walk(V0, T0, late_hop2, policy="greedy")
    assert [_sl_flags_devhop(f.routing_header) for f in g.frames] == [(2, 0, 0), (1, 0, 0), (0, 3, 2)]
    assert g.frames[-1].event == "fallback_late" and g.outcome == "deliver"
    c = W.process_walk(V0, T0, late_hop2, policy="continue")
    assert [_sl_flags_devhop(f.routing_header) for f in c.frames] == [(2, 0, 0), (1, 0, 0), (0, 1, 2)]
    assert c.frames[-1].event == "forward" and c.outcome == "deliver"
    d = W.process_walk(V0, T0, [7 * MS], policy="drop")
    assert len(d.frames) == 1 and d.outcome == "drop_late"


def test_walk_link_down():
    ingress = W.process_walk(V0, T0, [9 * MS], link_down_at={0})
    assert len(ingress.frames) == 1
    f = ingress.frames[0]
    assert (f.to_sid, f.event, _sl_flags_devhop(f.routing_header)) == (7, "fallback_link_down", (0, 3, 0))
    assert f.routing_header.hex() == TCRH["link_down"][0]["expect_hex_out"]   # ingress-link-down
    hop1 = W.process_walk(V0, T0, [5 * MS, 9 * MS], link_down_at=[1])
    assert _sl_flags_devhop(hop1.frames[1].routing_header) == (0, 3, 1)
    assert hop1.outcome == "deliver"


def test_walk_rejects_inconsistent_input():
    with pytest.raises(ValueError):                 # not a fresh header
        W.process_walk(bytes.fromhex(PROC["on-time-hop1"]["hex_in"]), T0, [MS] * 3)
    with pytest.raises(ValueError):                 # Epoch_Base was not stamped at this time
        W.process_walk(V0, T0 + 5 * MS, [MS] * 3)
    with pytest.raises(ValueError):                 # too few delays
        W.process_walk(V0, T0, [MS])
    with pytest.raises(ValueError):
        W.process_walk(V0, T0, [MS] * 3, policy="teleport")
    with pytest.raises(ValueError):                 # the final endpoint has no next link
        W.process_walk(V0, T0, [MS] * 3, link_down_at=[3])
    with pytest.raises(ValueError):
        W.process_walk(V0, T0, [-1, MS, MS])


def test_demo_walk_real_time_vector():
    w = W.demo_walk(TCRH)
    v = ENC[W.DEMO_VECTOR]
    hdr = P.TcrhHeader.decode(bytes.fromhex(v["expect_hex"]))
    assert len(w.frames) == W.DEMO_SLOW_HOP + 1
    late = [a for a in w.arrivals if a.result.late]
    assert [a.result.hop_index for a in late] == [W.DEMO_SLOW_HOP]
    assert w.frames[-1].to_sid == hdr.sids_rev[0] and w.frames[-1].event == "fallback_late"
    assert w.outcome == "deliver"
    # hops 1-5 arrive before their deadlines: every margin is positive
    for a in w.arrivals[:W.DEMO_SLOW_HOP - 1]:
        assert P.serial_diff(a.result.deadline_u, a.now_u) > 0
    frames = W.walk_frames(w)
    for wf, fr in zip(w.frames, frames):
        ip = parse_ipv6(fr.packet)
        assert ip["dst"] == W.sid_address(wf.to_sid)
        assert ip["payload"][:len(wf.routing_header)] == wf.routing_header
        upper = ip["payload"][len(wf.routing_header):]
        assert ones_sum_ok(pseudo(ip["src"], W.sid_address(hdr.sids_rev[0]), len(upper), 17), upper)


# ---------------------------------------------------------------- CLI

def test_cli_writes_pcaps_and_a_valid_manifest(tmp_path, capsys):
    out = tmp_path / "golden"
    assert W.main(["golden", str(out)]) == 0
    manifest = out / "manifest.json"
    prov.validate_manifest(manifest)                # schema + every output's sha256
    m = json.loads(manifest.read_text())
    assert m["tool"] == "chronoroute.trace.pcap"
    assert set(m["labels"].values()) <= set(prov.LABELS)
    # the shared label table: header bytes are the real encoder's output (REAL), the rest MODELLED
    assert m["labels"] == {"tcrh_header_bytes": "REAL", "pcap_addresses": "MODELLED",
                           "pcap_timestamps": "MODELLED", "walk_link_delays": "MODELLED"}
    names = {o["path"] for o in m["outputs"]}
    assert {"tcrh_encode_raw.pcap", "tcrh_encode_ppp.pcap", "tcrh_vectors_raw.pcap",
            "crh_encode_raw.pcap", "tcrh_walk_raw.pcap", "tcrh_walk_ppp.pcap",
            "frames.json"} == names
    assert "manifest.json" in capsys.readouterr().out


# ---------------------------------------------------------------- property

@settings(max_examples=60, deadline=None)
@given(
    sids=st.lists(st.integers(0, 0xFFFE), min_size=1, max_size=40),
    data=st.data(),
    unit_code=st.integers(0, 3),
    epoch=st.integers(0, 2**32 - 1),
    nh=st.sampled_from([6, 17, 41, 59]),
    payload=st.binary(max_size=64),
)
def test_any_header_round_trips(sids, data, unit_code, epoch, nh, payload):
    deltas = data.draw(st.lists(st.integers(0, 255), min_size=len(sids), max_size=len(sids)))
    hdr = P.TcrhHeader.from_forward(sids, deltas, epoch, unit_code, next_header=nh)
    rh = hdr.encode()
    src, final = W.HOST_SRC.packed, W.sid_address(sids[-1])
    pkt = W.packet_with_routing_header(rh, src=src, dst=W.sid_address(sids[0]), final_dst=final,
                                       payload=payload)
    ip = parse_ipv6(pkt)
    assert ip["payload"][:len(rh)] == rh
    assert P.TcrhHeader.decode_prefix(ip["payload"])[0] == hdr
    upper = ip["payload"][len(rh):]
    if nh in (6, 17):
        assert ones_sum_ok(pseudo(src, final, len(upper), nh), upper)
    elif nh == 59:
        assert upper == b""

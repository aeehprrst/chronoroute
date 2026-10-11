"""
pcap writer: IPv6 packets that carry a T-CRH (or a CRH), for Wireshark and tshark.

Why this exists: the header bytes that the Python reference, ns-3 and the
website produce must be readable field by field in Wireshark
(tools/wireshark/tcrh.lua), and tshark must be able to check every frame
automatically (sim/tests/test_wireshark_dissector.py,
tools/wireshark/check_pcap.sh). No third-party packages are needed: a pcap
file is a 24-byte file header followed by (16-byte record header + frame) for
every packet.

File format
-----------
* Classic pcap, version 2.4, little-endian. Nanosecond timestamps (magic
  0xA1B23C4D) by default; microsecond files (0xA1B2C3D4) on request.
* LINKTYPE_RAW (101): every frame is a bare IPv6 packet.
  LINKTYPE_PPP (9): every frame is the 2-byte PPP protocol field 0x0057 (IPv6)
  followed by the IPv6 packet. That is exactly what ns-3's
  PointToPointNetDevice writes, so Python and ns-3 captures can be compared
  byte for byte and read by the same tools.

Packets
-------
IPv6 header (Next Header 43) + the routing header bytes, unchanged + the upper
layer named by the routing header's own Next Header byte:
    17 UDP   UDP header + payload
     6 TCP   20-byte TCP header (PSH|ACK) + payload
    41 IPv6  an inner IPv6 packet carrying UDP (encapsulation mode, spec 8)
    59 none  nothing
UDP and TCP checksums use the pseudo-header of RFC 8200 section 8.1 with the
FINAL destination. For a T-CRH that is the address of SID[0] (the final
segment endpoint), not the address currently in the Destination field. Only
the routing header's mutable fields and the Destination Address change in
flight, so one checksum stays correct at every hop.

Reading such a capture: Wireshark cannot know the final destination of a
type-253 header (the header holds SIDs, not addresses). If you switch on its
UDP checksum validation (off by default), it checks against the CURRENT
Destination Address and calls frames with Segments Left > 0 "bad". Frames
with Segments Left = 0 validate (sim/tests/test_wireshark_dissector.py checks
both facts).

Clock
-----
ChronoRoute times are GPS nanoseconds since the GPS epoch 1980-01-06 (spec
section 4: GPS = UTC + 18 s). pcap timestamps count from the Unix epoch, so a
frame at GPS time t is stamped
    t_pcap_ns = t_gps_ns + (315964800 - 18) s
For instants after 2017-01-01 that is real UTC. The golden vectors also use
small synthetic Epoch_Base values (instants in 1980); they get the same fixed
shift, which tcrh.lua undoes exactly ("utc" timebase), so the margin column
is exact either way.

Addresses (MODELLED: a project convention until the address plan is fixed)
---------
SID s -> fd00::s (the low 16 bits are the SID; 32 for CRH-32), so a
Destination Address of fd00::3 reads as "SID 3" in Wireshark. This is the same
mapping as the ns-3 module's tcrh::SidAddress (ns3/contrib/chronoroute/model/
tcrh-address-plan.h), so Python and ns-3 frames carry the same addresses.
Hosts that are not SIDs live in fd00:0:0:ffff::/64, outside the SID space
fd00::/96. Every function takes `sid_to_addr` for another plan.

Command line
------------
    python -B -m chronoroute.trace.pcap golden OUT_DIR
writes every golden pcap, a frames.json index (frame number -> vector name)
and a manifest.json (chronoroute.provenance) into OUT_DIR.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

import chronoroute
from chronoroute import proto as P
from chronoroute.proto import timebase as TB

# ----------------------------------------------------------------- constants

LINKTYPE_PPP = 9                 # ns-3 point-to-point devices (2-byte PPP protocol field)
LINKTYPE_RAW = 101               # bare IP packets
LINKTYPES = {"raw": LINKTYPE_RAW, "ppp": LINKTYPE_PPP}
PPP_PROTO_IPV6 = 0x0057

MAGIC_NS = 0xA1B23C4D            # nanosecond-resolution pcap
MAGIC_US = 0xA1B2C3D4            # classic microsecond-resolution pcap
PCAP_VERSION = (2, 4)
DEFAULT_SNAPLEN = 262144         # Wireshark's default; our frames are far smaller

IPPROTO_TCP = 6
IPPROTO_UDP = 17
IPPROTO_IPV6 = 41
IPPROTO_ROUTING = 43
IPPROTO_NONE = 59
IPPROTO_ICMPV6 = 58
UPPER_LAYERS = (IPPROTO_UDP, IPPROTO_TCP, IPPROTO_IPV6, IPPROTO_NONE)
ICMPV6_PARAMETER_PROBLEM = 4
ICMPV6_TIME_EXCEEDED = 3
IPV6_MIN_MTU = 1280              # an ICMPv6 error quotes at most this much (RFC 4443 2.4)

IPV6_HEADER_BYTES = 40
DEFAULT_HOP_LIMIT = 64
# UDP/TCP port on both ends. It is unassigned, so Wireshark shows the payload as
# plain data instead of guessing some other protocol.
DEFAULT_PORT = 50253
TCP_FLAGS_PSH_ACK = 0x18
TCP_WINDOW = 65535

# Payload of every generated packet: "CRT1" + packet id (u32) + send time in GPS
# ns (u64), 16 bytes, so a frame can be matched with the run that produced it.
PAYLOAD_MAGIC = b"CRT1"
PAYLOAD_BYTES = 16

GPS_EPOCH_UNIX_S = 315964800     # 1980-01-06T00:00:00Z in Unix seconds
GPS_TO_PCAP_NS = (GPS_EPOCH_UNIX_S - TB.GPS_UTC_OFFSET_S) * TB.NS_PER_S
PCAP_MAX_SECONDS = (1 << 32) - 1 # ts_sec is an unsigned 32-bit field

SID_PREFIX = ipaddress.IPv6Address("fd00::")
ADDRESS_PLAN = "SID s -> fd00::s (the low 16 bits, 32 for CRH-32, are the SID)"
HOST_SRC = ipaddress.IPv6Address("fd00:0:0:ffff::1")     # the sending host / user terminal
INNER_SRC = ipaddress.IPv6Address("fd00:0:0:ffff::11")   # hosts of an encapsulated packet
INNER_DST = ipaddress.IPv6Address("fd00:0:0:ffff::12")
# The node a fresh header (Segments Left = Num Hops) is handed to: it acts as
# the ingress (spec 6, process vector ingress-sl-equals-numhops). Ground station 0.
DEFAULT_INGRESS_SID = P.SID_GROUND_BASE

GOLDEN_DIR = Path(__file__).resolve().parents[3] / "spec" / "golden"


# ------------------------------------------------------------------ helpers

def _require_int(name, value):
    # bool is an int in Python, but never a valid field value
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int, got {type(value).__name__}")


def _check_range(name, value, lo, hi):
    _require_int(name, value)
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be in {lo}..{hi}, got {value}")


def _addr(a):
    """16 address bytes from bytes, an ipaddress.IPv6Address or text."""
    if isinstance(a, (bytes, bytearray)):
        if len(a) != 16:
            raise ValueError(f"an IPv6 address is 16 bytes, got {len(a)}")
        return bytes(a)
    if isinstance(a, ipaddress.IPv6Address):
        return a.packed
    if isinstance(a, str):
        return ipaddress.IPv6Address(a).packed
    raise TypeError(f"expected an IPv6 address, got {type(a).__name__}")


def sid_address(sid):
    """
    Address of SID `sid` in the default plan: fd00::<sid> (16 bytes). T-CRH and
    CRH-16 SIDs are 16 bits; CRH-32 SIDs (32 bits) use the low 32 bits.
    """
    _check_range("SID", sid, 0, 0xFFFFFFFF)
    return (int(SID_PREFIX) | sid).to_bytes(16, "big")


def gps_to_pcap_ns(t_gps_ns):
    """GPS ns (spec 4) -> pcap timestamp in ns since the Unix epoch (see module doc)."""
    _require_int("t_gps_ns", t_gps_ns)
    t = t_gps_ns + GPS_TO_PCAP_NS
    if not 0 <= t <= PCAP_MAX_SECONDS * TB.NS_PER_S + (TB.NS_PER_S - 1):
        raise ValueError(f"GPS time {t_gps_ns} ns does not fit a pcap timestamp")
    return t


def pcap_to_gps_ns(t_pcap_ns):
    """Inverse of gps_to_pcap_ns."""
    _require_int("t_pcap_ns", t_pcap_ns)
    return t_pcap_ns - GPS_TO_PCAP_NS


def payload_bytes(pid, t_send_gps_ns):
    """The 16-byte payload: b"CRT1" + pid (u32) + send time GPS ns (u64)."""
    _check_range("pid", pid, 0, 0xFFFFFFFF)
    _check_range("t_send_gps_ns", t_send_gps_ns, 0, (1 << 64) - 1)
    return PAYLOAD_MAGIC + struct.pack("!IQ", pid, t_send_gps_ns)


# ---------------------------------------------------------------- checksums

def internet_checksum(data):
    """
    RFC 1071 Internet checksum: one's complement of the one's complement sum
    of 16-bit big-endian words (an odd byte is padded with a zero).
    Returns 0..0xFFFF; UDP turns 0 into 0xFFFF itself (see udp_datagram).
    """
    data = bytes(data)
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:                       # fold the carries back in
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def pseudo_header(src, final_dst, upper_length, next_header):
    """RFC 8200 8.1: source, FINAL destination, 32-bit length, 3 zero bytes, Next Header."""
    _check_range("upper_length", upper_length, 0, 0xFFFFFFFF)
    _check_range("next_header", next_header, 0, 255)
    return _addr(src) + _addr(final_dst) + struct.pack("!I3xB", upper_length, next_header)


def udp_datagram(src, final_dst, payload, sport=DEFAULT_PORT, dport=DEFAULT_PORT):
    """
    UDP header + payload with the checksum over the IPv6 pseudo-header that
    names the FINAL destination (RFC 8200 8.1). Over IPv6 the UDP checksum
    is mandatory, and a computed 0 is sent as 0xFFFF (RFC 768, RFC 8200 8.1).
    """
    _check_range("sport", sport, 0, 0xFFFF)
    _check_range("dport", dport, 0, 0xFFFF)
    payload = bytes(payload)
    length = 8 + len(payload)
    if length > 0xFFFF:
        raise ValueError(f"UDP datagram of {length} bytes is too long")
    header = struct.pack("!HHHH", sport, dport, length, 0)
    csum = internet_checksum(pseudo_header(src, final_dst, length, IPPROTO_UDP) + header + payload)
    return struct.pack("!HHHH", sport, dport, length, csum or 0xFFFF) + payload


def tcp_segment(src, final_dst, payload, sport=DEFAULT_PORT, dport=DEFAULT_PORT, seq=0, ack=0):
    """A 20-byte TCP header (PSH|ACK, no options) + payload, checksum as in udp_datagram."""
    _check_range("sport", sport, 0, 0xFFFF)
    _check_range("dport", dport, 0, 0xFFFF)
    _check_range("seq", seq, 0, 0xFFFFFFFF)
    _check_range("ack", ack, 0, 0xFFFFFFFF)
    payload = bytes(payload)
    offset_byte = 5 << 4                     # data offset: 5 words, no options
    header = struct.pack("!HHIIBBHHH", sport, dport, seq, ack, offset_byte,
                         TCP_FLAGS_PSH_ACK, TCP_WINDOW, 0, 0)
    segment = header + payload
    csum = internet_checksum(pseudo_header(src, final_dst, len(segment), IPPROTO_TCP) + segment)
    return header[:16] + struct.pack("!H", csum) + header[18:] + payload


def ipv6_packet(src, dst, next_header, payload, hop_limit=DEFAULT_HOP_LIMIT,
                traffic_class=0, flow_label=0):
    """40-byte IPv6 header + payload (no jumbograms: payload <= 65535 bytes)."""
    _check_range("next_header", next_header, 0, 255)
    _check_range("hop_limit", hop_limit, 0, 255)
    _check_range("traffic_class", traffic_class, 0, 255)
    _check_range("flow_label", flow_label, 0, 0xFFFFF)
    payload = bytes(payload)
    if len(payload) > 0xFFFF:
        raise ValueError(f"IPv6 payload of {len(payload)} bytes needs a jumbogram")
    first_word = (6 << 28) | (traffic_class << 20) | flow_label
    return (struct.pack("!IHBB", first_word, len(payload), next_header, hop_limit)
            + _addr(src) + _addr(dst) + payload)


def icmpv6_error_packet(invoking_packet, *, src, dst, icmp_type=ICMPV6_PARAMETER_PROBLEM, code=0,
                        pointer=0, hop_limit=DEFAULT_HOP_LIMIT):
    """
    An ICMPv6 error message (RFC 4443) that carries back the packet that caused it.

    Type 1-4 errors have a 4-byte field after the checksum (the Pointer for a
    Parameter Problem, unused 0 otherwise) and then "as much of the invoking
    packet as possible without the ICMPv6 packet exceeding the minimum IPv6
    MTU" (1280 bytes). The checksum covers the pseudo-header with Next Header
    58 (RFC 4443 2.3). Used to test that tools treat the T-CRH quoted inside
    such a message as a copy, not as a live header.
    """
    _check_range("icmp_type", icmp_type, 0, 127)          # error messages only
    _check_range("code", code, 0, 255)
    _check_range("pointer", pointer, 0, 0xFFFFFFFF)
    quoted = bytes(invoking_packet)[:IPV6_MIN_MTU - 40 - 8]
    body = struct.pack("!BBHI", icmp_type, code, 0, pointer) + quoted
    csum = internet_checksum(pseudo_header(src, dst, len(body), IPPROTO_ICMPV6) + body)
    return ipv6_packet(src, dst, IPPROTO_ICMPV6, body[:2] + struct.pack("!H", csum) + body[4:], hop_limit)


# --------------------------------------------------- routing-header packets

def tcrh_sids(rh):
    """
    (SL, sids_rev) of a well-formed T-CRH at the start of `rh`, or None if the
    bytes are not one (malformed on purpose, or another routing type).
    sids_rev is in wire order: SID[0] is the final endpoint.
    """
    rh = bytes(rh)
    if len(rh) < 3 or rh[2] != P.ROUTING_TYPE_TCRH:
        return None
    try:
        hdr, _n = P.TcrhHeader.decode_prefix(rh)
    except P.TcrhDecodeError:
        return None
    return hdr.segments_left, hdr.sids_rev


def packet_with_routing_header(rh, *, src, dst, final_dst=None, payload=b"",
                               sport=DEFAULT_PORT, dport=DEFAULT_PORT,
                               hop_limit=DEFAULT_HOP_LIMIT, seq=0):
    """
    One IPv6 packet: header (Next Header 43) + routing-header bytes + upper layer.

    rh holds the packet bytes from the routing header on. If it is exactly one
    header long ((Hdr Ext Len + 1) * 8 bytes), the upper layer named by its
    Next Header byte is built and appended (see module doc); UDP/TCP need
    final_dst, the address of the final segment endpoint. Bytes that are
    shorter (truncated on purpose) or longer (they bring their own payload,
    as some golden process vectors do) are used as the whole IPv6 payload,
    unchanged.
    """
    rh = bytes(rh)
    complete = len(rh) >= 2 and len(rh) == (rh[1] + 1) * 8
    if not complete:
        return ipv6_packet(src, dst, IPPROTO_ROUTING, rh, hop_limit)
    nh = rh[0]
    if nh in (IPPROTO_UDP, IPPROTO_TCP) and final_dst is None:
        raise ValueError("a UDP/TCP checksum needs final_dst (RFC 8200 8.1)")
    if nh == IPPROTO_UDP:
        upper = udp_datagram(src, final_dst, payload, sport, dport)
    elif nh == IPPROTO_TCP:
        upper = tcp_segment(src, final_dst, payload, sport, dport, seq=seq)
    elif nh == IPPROTO_IPV6:
        # Encapsulation (spec 8): the inner packet is a normal IPv6/UDP packet
        # between the two hosts, with its own (routing-header free) checksum.
        upper = ipv6_packet(INNER_SRC, INNER_DST, IPPROTO_UDP,
                            udp_datagram(INNER_SRC, INNER_DST, payload, sport, dport), hop_limit)
    elif nh == IPPROTO_NONE:
        upper = b""
    else:
        raise ValueError(f"no upper-layer builder for Next Header {nh} (have {UPPER_LAYERS})")
    return ipv6_packet(src, dst, IPPROTO_ROUTING, rh + upper, hop_limit)


# --------------------------------------------------------------- the writer

@dataclass(frozen=True)
class Frame:
    """One packet to write: GPS time stamp, the IPv6 packet, and a label for indexes."""
    t_gps_ns: int
    packet: bytes
    name: str = ""


class PcapWriter:
    """
    Writes a classic pcap stream. Usage:

        with open("x.pcap", "wb") as fh:
            w = PcapWriter(fh, LINKTYPE_PPP)
            w.write(ipv6_bytes, t_gps_ns=...)
    """

    def __init__(self, stream, linktype=LINKTYPE_RAW, *, nanosecond=True, snaplen=DEFAULT_SNAPLEN):
        if linktype not in (LINKTYPE_RAW, LINKTYPE_PPP):
            raise ValueError(f"linktype must be {LINKTYPE_RAW} (RAW) or {LINKTYPE_PPP} (PPP), got {linktype}")
        _check_range("snaplen", snaplen, 64, 0xFFFFFFFF)
        self.stream = stream
        self.linktype = linktype
        self.nanosecond = bool(nanosecond)
        self.snaplen = snaplen
        self.frames = 0
        magic = MAGIC_NS if self.nanosecond else MAGIC_US
        stream.write(struct.pack("<IHHiIII", magic, PCAP_VERSION[0], PCAP_VERSION[1],
                                 0, 0, snaplen, linktype))

    def write(self, packet, *, t_gps_ns):
        """Append one IPv6 packet stamped with GPS time t_gps_ns."""
        packet = bytes(packet)
        if not packet or packet[0] >> 4 != 6:
            raise ValueError("expected an IPv6 packet (version 6)")
        frame = (struct.pack("!H", PPP_PROTO_IPV6) + packet) if self.linktype == LINKTYPE_PPP else packet
        if len(frame) > self.snaplen:
            # never truncate silently: a cut header would decode as malformed
            raise ValueError(f"frame of {len(frame)} bytes exceeds snaplen {self.snaplen}")
        sec, frac = divmod(gps_to_pcap_ns(t_gps_ns), TB.NS_PER_S)
        if not self.nanosecond:
            frac //= 1000                    # microseconds, truncated toward the past
        self.stream.write(struct.pack("<IIII", sec, frac, len(frame), len(frame)) + frame)
        self.frames += 1


def write_pcap(path, frames, linktype=LINKTYPE_RAW, *, nanosecond=True):
    """Write Frame objects (in the given order) to a new pcap file; returns its Path."""
    path = Path(path)
    with open(path, "wb") as fh:
        writer = PcapWriter(fh, linktype, nanosecond=nanosecond)
        for fr in frames:
            writer.write(fr.packet, t_gps_ns=fr.t_gps_ns)
    return path


# ------------------------------------------------------------ golden frames

def load_golden(filename="tcrh_vectors.json", golden_dir=None):
    """Parsed spec/golden/<filename>."""
    path = Path(golden_dir) if golden_dir is not None else GOLDEN_DIR
    return json.loads((path / filename).read_text(encoding="utf-8"))


def encode_vector_time_gps_ns(v):
    """
    Time stamp of an encode vector's frame: its ingress time when the vector
    gives one, else the first instant of unit Epoch_Base (so that
    clock_u(stamp) == Epoch_Base, as at a real ingress).
    """
    if "t_ingress_gps_ns" in v:
        return int(v["t_ingress_gps_ns"])
    return v["epoch_base"] * TB.unit_ns(v["unit_code"])


def golden_encode_frames(vectors=None, *, sid_to_addr=sid_address,
                         ingress_sid=DEFAULT_INGRESS_SID, src=HOST_SRC):
    """
    One frame per T-CRH `encode` vector, in file order (frame n+1 = vector n).
    The routing header is expect_hex byte for byte, i.e. a fresh header with
    Segments Left = Num Hops, sent by the host `src` to the ingress node
    (`ingress_sid`), which will do spec 6 steps 5-7. The checksum uses SID[0].
    """
    vectors = vectors if vectors is not None else load_golden()
    frames = []
    for pid, v in enumerate(vectors["encode"]):
        rh = bytes.fromhex(v["expect_hex"])
        hdr = P.TcrhHeader.decode(rh)
        t = encode_vector_time_gps_ns(v)
        pkt = packet_with_routing_header(rh, src=src, dst=sid_to_addr(ingress_sid),
                                         final_dst=sid_to_addr(hdr.sids_rev[0]),
                                         payload=payload_bytes(pid, t), seq=pid)
        frames.append(Frame(t, pkt, v["name"]))
    return frames


def _vector_frame(rh, t, pid, name, *, sid_to_addr, ingress_sid, src):
    """
    A frame for arbitrary T-CRH bytes, malformed ones included. A well-formed
    header is addressed to its current SID (SID[SL]; the ingress while
    SL = Num Hops) with the checksum over SID[0]. Bytes that are not a
    well-formed T-CRH have no SID to trust, so they go to the ingress.
    """
    parsed = tcrh_sids(rh)
    ingress = sid_to_addr(ingress_sid)
    if parsed is None:
        dst = final = ingress
    else:
        sl, sids = parsed
        final = sid_to_addr(sids[0])
        dst = sid_to_addr(sids[sl]) if sl < len(sids) else ingress
    pkt = packet_with_routing_header(rh, src=src, dst=dst, final_dst=final,
                                     payload=payload_bytes(pid, max(t, 0)), seq=pid)
    return Frame(t, pkt, name)


def _unit_of(raw):
    """Unit length (ns) from a T-CRH flags byte, 1 ms if the byte is missing."""
    return TB.unit_ns((raw[4] >> 4) & 3) if len(raw) > 4 else TB.unit_ns(0)


def golden_vector_frames(vectors=None, *, sid_to_addr=sid_address,
                         ingress_sid=DEFAULT_INGRESS_SID, src=HOST_SRC):
    """
    Frames for the T-CRH `process` and `link_down` vectors: for each vector the
    input bytes (hex_in, MALFORMED ON PURPOSE for the malformed-* vectors) and,
    when there is one, the expected output (expect_hex_out). Names are
    "<section>/<vector>/in" and ".../out".

    Time stamps: a process vector's frames are stamped at the first instant of
    unit now_u (the node's clock on arrival; the output leaves at the same
    instant), so the dissector's late flag can be compared with expect_late.
    link_down vectors have no clock: they are stamped at Epoch_Base (or 0 if
    the bytes do not parse).
    """
    vectors = vectors if vectors is not None else load_golden()
    frames = []
    pid = 0
    for section in ("process", "link_down"):
        for v in vectors[section]:
            raw = bytes.fromhex(v["hex_in"])
            if "now_u" in v:
                t = v["now_u"] * _unit_of(raw)
            elif len(raw) >= 12:
                t = struct.unpack_from("!I", raw, 8)[0] * _unit_of(raw)
            else:
                t = 0
            kw = dict(sid_to_addr=sid_to_addr, ingress_sid=ingress_sid, src=src)
            frames.append(_vector_frame(raw, t, pid, f"{section}/{v['name']}/in", **kw))
            pid += 1
            if v.get("expect_hex_out"):
                out = bytes.fromhex(v["expect_hex_out"])
                frames.append(_vector_frame(out, t, pid, f"{section}/{v['name']}/out", **kw))
                pid += 1
    return frames


def crh_encode_frames(vectors=None, *, sid_to_addr=sid_address, src=HOST_SRC):
    """
    CRH-16 / CRH-32 `encode` vectors (RFC 9631), which Wireshark decodes by
    itself, as they look ON THE WIRE: each fresh header (Segments Left = number
    of SIDs) is walked with the reference chronoroute.proto.crh_process_at_node,
    one frame per transmission (SL = n-1 .. 0, addressed to SID[SL], checksum
    over SID[0]). Names are "<vector>/sl<SL>". Stamped 1 ms apart from GPS
    time 0 (a CRH carries no time).

    The fresh header itself is not written: Wireshark 4.6 reads SID[SL] as
    the "current SID", which lies past the end of a header with no padding
    slot when SL = n, so it reports such a frame as malformed (measured; see
    tools/wireshark/README.md).
    """
    vectors = vectors if vectors is not None else load_golden("crh_vectors.json")
    frames = []
    pid = 0
    for v in vectors["encode"]:
        raw = bytes.fromhex(v["expect_hex"])
        final = sid_to_addr(P.CrhHeader.decode(raw).sids_rev[0])
        res = P.crh_process_at_node(raw)          # the ingress: SL = n -> n - 1
        while res.action == "forward":
            sl = res.out_bytes[3]
            pkt = packet_with_routing_header(res.out_bytes, src=src, dst=sid_to_addr(res.next_sid),
                                             final_dst=final,
                                             payload=payload_bytes(pid, pid * TB.NS_PER_MS), seq=pid)
            frames.append(Frame(pid * TB.NS_PER_MS, pkt, f"{v['name']}/sl{sl}"))
            pid += 1
            res = P.crh_process_at_node(res.out_bytes)
        if res.action != "deliver":
            raise ValueError(f"CRH vector {v['name']} did not walk to delivery: {res}")
    return frames


# -------------------------------------------------------------- process walk

@dataclass(frozen=True)
class WalkFrame:
    """
    One transmission of the walked packet.
    t_gps_ns        arrival time at to_sid's node (the frame's time stamp, so the
                    dissector's margin is what that node's deadline check sees)
    from_sid        the transmitting node; None for the ingress
    to_sid          the node whose address is in the Destination Address
    routing_header  the T-CRH as transmitted
    event           why it was sent: 'ingress', 'forward', 'fallback_late' (this
                    node found it late), 'fallback_dev' (DEV was set upstream),
                    'fallback_link_down' (spec 6 step 7)
    """
    t_gps_ns: int
    from_sid: int | None
    to_sid: int
    routing_header: bytes
    event: str


@dataclass(frozen=True)
class WalkArrival:
    """What process_at_node did when the packet reached `sid` at t_gps_ns."""
    sid: int
    t_gps_ns: int
    now_u: int
    result: P.ProcessResult


@dataclass(frozen=True)
class Walk:
    header: bytes
    t_ingress_gps_ns: int
    policy: str
    frames: tuple[WalkFrame, ...]
    arrivals: tuple[WalkArrival, ...]

    @property
    def outcome(self):
        """Action of the last node: 'deliver' or 'drop_late'."""
        return self.arrivals[-1].result.action


def process_walk(header, t_ingress_gps_ns, link_delays_ns, *, policy="greedy", link_down_at=()):
    """
    Walk one packet along its T-CRH path with the reference processing
    functions (chronoroute.proto: ingress_send, process_at_node,
    link_down_fallback), recording every transmission.

    header           a fresh T-CRH (Segments Left = Num Hops), exactly one header
    t_ingress_gps_ns when the ingress sends it; Epoch_Base must have been stamped
                     from it (Epoch_Base == ceil(t / u) mod 2^32, spec 4)
    link_delays_ns   one delay per transmission, used in order (MODELLED timing:
                     arrival = previous arrival + delay, zero processing time).
                     A greedy fallback leg is ONE transmission: the satellites it
                     crosses on the way to SID[0] do not change the bytes.
                     Extra delays are ignored; too few raise ValueError.
    policy           every node's deviation policy: 'greedy', 'continue', 'drop'
    link_down_at     hop indices k (0 = ingress, up to Num Hops - 1) whose next
                     link is down when the packet arrives there
    """
    raw = bytes(header)
    hdr = P.TcrhHeader.decode(raw)
    if hdr.segments_left != hdr.num_hops:
        raise ValueError("process_walk needs a fresh header (Segments Left = Num Hops)")
    _require_int("t_ingress_gps_ns", t_ingress_gps_ns)
    if P.epoch_base_at_ingress(t_ingress_gps_ns, hdr.unit_code) != hdr.epoch_base:
        raise ValueError(
            f"Epoch_Base {hdr.epoch_base} was not stamped at t_ingress = {t_ingress_gps_ns} ns "
            f"(that would give {P.epoch_base_at_ingress(t_ingress_gps_ns, hdr.unit_code)})")
    if policy not in P.POLICIES:
        raise ValueError(f"policy must be one of {P.POLICIES}, got {policy!r}")
    delays = list(link_delays_ns)
    for d in delays:
        _check_range("link delay", d, 0, 10 ** 15)
    down = frozenset(link_down_at)
    for k in down:
        _check_range("link_down_at hop", k, 0, hdr.num_hops - 1)

    # The ingress: steps 5-7 without a deadline check.
    out, nxt = P.ingress_send(raw)
    event = "ingress"
    if 0 in down:
        res = P.link_down_fallback(out)
        out, nxt, event = res.out_bytes, res.next_sid, "fallback_link_down"

    frames, arrivals = [], []
    t, sender = t_ingress_gps_ns, None
    # A packet reaches at most Num Hops nodes; the bound only guards against a bug.
    for step in range(hdr.num_hops + 1):
        if step >= len(delays):
            raise ValueError(f"process_walk needs more link delays (used {len(delays)}, "
                             f"the packet is still travelling towards SID {nxt})")
        t += delays[step]
        frames.append(WalkFrame(t, sender, nxt, out, event))
        now_u = P.clock_u(t, hdr.unit_code)
        res = P.process_at_node(out, now_u, policy)
        arrivals.append(WalkArrival(nxt, t, now_u, res))
        if res.action in ("deliver", "drop_late"):
            return Walk(raw, t_ingress_gps_ns, policy, tuple(frames), tuple(arrivals))
        if res.action == "forward":
            if res.hop_index in down:
                ld = P.link_down_fallback(res.out_bytes)
                out, new_next, event = ld.out_bytes, ld.next_sid, "fallback_link_down"
            else:
                out, new_next, event = res.out_bytes, res.next_sid, "forward"
        elif res.action == "fallback":
            out, new_next = res.out_bytes, res.next_sid
            event = "fallback_late" if res.late else "fallback_dev"
        else:   # we built the bytes ourselves, so nothing else can happen
            raise AssertionError(f"unexpected action {res.action!r} in a walk")
        sender, nxt = nxt, new_next
    raise AssertionError("the walk did not end within Num Hops + 1 transmissions")


def walk_frames(walk, *, pid=0, sid_to_addr=sid_address, src=HOST_SRC):
    """The walk's transmissions as Frame objects (source address stays `src`)."""
    frames = []
    final = None
    for wf in walk.frames:
        hdr, _n = P.TcrhHeader.decode_prefix(wf.routing_header)
        final = sid_to_addr(hdr.sids_rev[0])
        pkt = packet_with_routing_header(wf.routing_header, src=src, dst=sid_to_addr(wf.to_sid),
                                         final_dst=final,
                                         payload=payload_bytes(pid, walk.t_ingress_gps_ns), seq=pid)
        sender = "ingress" if wf.from_sid is None else f"SID {wf.from_sid}"
        frames.append(Frame(wf.t_gps_ns, pkt, f"{wf.event}: {sender} -> SID {wf.to_sid}"))
    return frames


# ------------------------------------------------------- the demo walk (CLI)

DEMO_VECTOR = "h10-real-gps-time-uc1"
DEMO_SLOW_HOP = 6          # this hop's link is up but slow (MODELLED)
DEMO_SLOW_FACTOR = 3
DEMO_ON_TIME_NUM, DEMO_ON_TIME_DEN = 9, 10   # other hops take 90 % of their budget


def demo_walk(vectors=None):
    """
    A 10-hop walk on the golden vector h10-real-gps-time-uc1 (a real GPS time,
    2026-10). MODELLED link delays: every hop takes 90 % of its planned
    per-hop budget, except hop 6 whose link is up but 3x slower; the packet
    is late at hop 6, sets DEV, and the greedy policy sends it straight to
    SID[0], which takes the rest of the planned budget. Integer arithmetic only.
    """
    vectors = vectors if vectors is not None else load_golden()
    v = next(x for x in vectors["encode"] if x["name"] == DEMO_VECTOR)
    budgets = v["cumulative_budgets_ns"]
    per_hop = [b - a for a, b in zip([0] + budgets[:-1], budgets)]
    delays = []
    for k, b in enumerate(per_hop, start=1):
        if k == DEMO_SLOW_HOP:
            delays.append(b * DEMO_SLOW_FACTOR)
            delays.append(budgets[-1] - budgets[DEMO_SLOW_HOP - 1])   # fallback leg to SID[0]
            break
        delays.append(b * DEMO_ON_TIME_NUM // DEMO_ON_TIME_DEN)
    return process_walk(bytes.fromhex(v["expect_hex"]), int(v["t_ingress_gps_ns"]), delays,
                        policy="greedy")


# ---------------------------------------------------------------------- CLI

def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_golden_pcaps(out_dir, golden_dir=None):
    """
    Write every golden pcap into out_dir (created if needed) plus frames.json
    (frame number -> name, per file). Returns {file name: [frame names]}.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    tcrh = load_golden("tcrh_vectors.json", golden_dir)
    crh = load_golden("crh_vectors.json", golden_dir)
    walk = demo_walk(tcrh)
    plan = {
        "tcrh_encode_raw.pcap": (golden_encode_frames(tcrh), LINKTYPE_RAW),
        "tcrh_encode_ppp.pcap": (golden_encode_frames(tcrh), LINKTYPE_PPP),
        "tcrh_vectors_raw.pcap": (golden_vector_frames(tcrh), LINKTYPE_RAW),
        "crh_encode_raw.pcap": (crh_encode_frames(crh), LINKTYPE_RAW),
        "tcrh_walk_raw.pcap": (walk_frames(walk), LINKTYPE_RAW),
        "tcrh_walk_ppp.pcap": (walk_frames(walk), LINKTYPE_PPP),
    }
    index = {}
    for name, (frames, linktype) in plan.items():
        write_pcap(out / name, frames, linktype)
        index[name] = [fr.name for fr in frames]
    (out / "frames.json").write_text(
        json.dumps(index, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m chronoroute.trace.pcap",
        description="Write ChronoRoute pcap files (IPv6 + T-CRH) for Wireshark/tshark.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("golden", help="golden-vector pcaps + a demo walk, with a manifest")
    g.add_argument("out_dir", help="output directory (created if needed)")
    g.add_argument("--golden-dir", default=None, help="spec/golden directory (default: this checkout's)")
    args = parser.parse_args(argv)

    from chronoroute import labels as labels_mod, provenance as prov   # only the CLI writes manifests
    timer = prov.RunTimer().start()
    index = write_golden_pcaps(args.out_dir, args.golden_dir)
    timer.stop()
    golden = Path(args.golden_dir) if args.golden_dir else GOLDEN_DIR
    out = Path(args.out_dir)
    outputs = [out / name for name in sorted(index)] + [out / "frames.json"]
    prov.write_manifest(
        out,
        tool="chronoroute.trace.pcap",
        tool_version=chronoroute.__version__,
        command=["python", "-m", "chronoroute.trace.pcap"] + list(argv if argv is not None else sys.argv[1:]),
        config={
            "tcrh_vectors_sha256": _sha256(golden / "tcrh_vectors.json"),
            "crh_vectors_sha256": _sha256(golden / "crh_vectors.json"),
            "address_plan": ADDRESS_PLAN,
            "host_src": str(HOST_SRC),
            "ingress_sid": DEFAULT_INGRESS_SID,
            "pcap": {"magic": f"0x{MAGIC_NS:08X}", "linktypes": {"raw": LINKTYPE_RAW, "ppp": LINKTYPE_PPP},
                     "clock": "pcap ns = GPS ns + (315964800 - 18) s"},
            "demo_walk": {"vector": DEMO_VECTOR, "policy": "greedy", "slow_hop": DEMO_SLOW_HOP,
                          "slow_factor": DEMO_SLOW_FACTOR,
                          "on_time_fraction": [DEMO_ON_TIME_NUM, DEMO_ON_TIME_DEN]},
        },
        seeds=[],
        outputs=outputs,
        # The shared label table (chronoroute/labels.py): the header bytes are
        # the real output of the real encoder (plan section 2, row 17), REAL;
        # the address plan and the walk's delays/time stamps are MODELLED.
        labels=labels_mod.pick("tcrh_header_bytes", "pcap_addresses", "pcap_timestamps",
                               "walk_link_delays"),
        extra={"frames": {name: len(names) for name, names in sorted(index.items())}},
        timer=timer,
    )
    for name in sorted(index):
        print(f"{out / name}: {len(index[name])} frames")
    print(f"{out / 'manifest.json'}")
    return 0


__all__ = [
    "LINKTYPE_PPP", "LINKTYPE_RAW", "LINKTYPES", "PPP_PROTO_IPV6", "MAGIC_NS", "MAGIC_US",
    "IPPROTO_TCP", "IPPROTO_UDP", "IPPROTO_IPV6", "IPPROTO_ROUTING", "IPPROTO_NONE",
    "IPPROTO_ICMPV6", "ICMPV6_PARAMETER_PROBLEM", "ICMPV6_TIME_EXCEEDED", "IPV6_MIN_MTU",
    "DEFAULT_PORT", "PAYLOAD_MAGIC", "GPS_TO_PCAP_NS", "ADDRESS_PLAN", "HOST_SRC",
    "INNER_SRC", "INNER_DST", "DEFAULT_INGRESS_SID",
    "sid_address", "gps_to_pcap_ns", "pcap_to_gps_ns", "payload_bytes",
    "internet_checksum", "pseudo_header", "udp_datagram", "tcp_segment", "ipv6_packet",
    "icmpv6_error_packet", "tcrh_sids", "packet_with_routing_header",
    "Frame", "PcapWriter", "write_pcap",
    "load_golden", "encode_vector_time_gps_ns", "golden_encode_frames", "golden_vector_frames",
    "crh_encode_frames", "WalkFrame", "WalkArrival", "Walk", "process_walk", "walk_frames",
    "demo_walk", "write_golden_pcaps", "main",
]


if __name__ == "__main__":
    sys.exit(main())

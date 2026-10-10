"""Tests for chronoroute.proto.crh (RFC 9631) and the comparison-header sizes."""

import dataclasses

import pytest
from hypothesis import given, strategies as st

from chronoroute.proto import (
    CrhHeader, CrhProcessResult, CrhWrongRoutingType, CrhTruncated, CrhTrailingBytes,
    CrhDecodeError, crh_process_at_node, min_hdr_ext_len, ICMP_CODE_MIN_LENGTH,
    ROUTING_TYPE_CRH16, ROUTING_TYPE_CRH32, TcrhHeader,
    crh16_size, crh32_size, srh_size, tcrh_size, pad8, encapsulation_overhead,
)

NS3_CRH16_HEX = "11010503000700030002000000000000"   # crh-experiment.cc:530


# ----------------------------------------------------------------- sizes (spec section 9)

def test_regression_bug5_crh16_fixed_part_is_4_bytes():
    """Bug #5 (header.py:60): v0 used CRH16_FIXED = 8, giving 24/32/40 B at
    5/10/13 hops. RFC 9631's fixed part is 4 octets."""
    assert [crh16_size(n) for n in (5, 10, 13)] == [16, 24, 32]


def test_comparison_sizes_at_10_hops_match_spec():
    assert (tcrh_size(10), crh16_size(10), crh32_size(10), srh_size(10)) == (48, 24, 48, 168)
    assert srh_size(13) == 216 and tcrh_size(13) == 56


def test_size_helpers_match_ns3_formulas():
    for n in range(0, 300):
        assert crh16_size(n) == ((4 + n * 2) + 7) // 8 * 8          # ns-3 Crh16Size
        assert crh32_size(n) == ((4 + n * 4) + 7) // 8 * 8          # ns-3 Crh32Size
        assert srh_size(n) == ((8 + n * 16) + 7) // 8 * 8           # ns-3 SrhSize
    assert [pad8(x) for x in (0, 1, 8, 9, 21)] == [0, 8, 8, 16, 24]


def test_encapsulation_overhead():
    assert encapsulation_overhead(10) == 48
    assert encapsulation_overhead(10, "source") == 48
    assert encapsulation_overhead(10, "encap") == 88
    assert encapsulation_overhead(10, "encap", "srh") == 208
    assert encapsulation_overhead(10, "source", "crh16") == 24
    with pytest.raises(ValueError):
        encapsulation_overhead(10, "tunnel")
    with pytest.raises(ValueError):
        encapsulation_overhead(10, "source", "mpls")


def test_size_input_validation():
    with pytest.raises(ValueError):
        crh16_size(-1)
    with pytest.raises(TypeError):
        srh_size(2.0)


# ----------------------------------------------------------------- encode / decode

def test_ns3_crh16_vector():
    hdr = CrhHeader.from_forward([2, 3, 7])
    assert hdr.encode().hex() == NS3_CRH16_HEX
    assert hdr.routing_type == ROUTING_TYPE_CRH16 and hdr.segments_left == 3
    assert hdr.size == 16 and hdr.hdr_ext_len == 1


def test_crh32_vector():
    hdr = CrhHeader.from_forward([2, 3, 7], routing_type=ROUTING_TYPE_CRH32)
    assert hdr.encode().hex() == "11010603000000070000000300000002"
    assert CrhHeader.from_forward([0x12345678], routing_type=6).encode().hex() == "1100060112345678"


def test_decode_reads_every_slot_like_ns3():
    back = CrhHeader.decode(bytes.fromhex(NS3_CRH16_HEX))
    assert back.sids_rev == (7, 3, 2, 0, 0, 0)          # padding slots included
    assert back.segments_left == 3 and back.next_header == 17
    assert back.encode().hex() == NS3_CRH16_HEX           # bytes round-trip exactly
    assert back.remaining_sids_fwd() == (2, 3, 7)


def test_current_sid_and_remaining():
    hdr = dataclasses.replace(CrhHeader.from_forward([2, 3, 7]), segments_left=1)
    assert hdr.current_sid() == 3
    assert hdr.remaining_sids_fwd() == (7,)
    with pytest.raises(ValueError):
        CrhHeader.from_forward([2, 3, 7]).current_sid()    # SL = 3 indexes past the list


def test_decode_errors():
    with pytest.raises(CrhWrongRoutingType) as e:
        CrhHeader.decode(TcrhHeader.from_forward([2], [1], 0, 0).encode())
    assert e.value.pointer == 2 and isinstance(e.value, CrhDecodeError)
    with pytest.raises(CrhTruncated):
        CrhHeader.decode(bytes.fromhex(NS3_CRH16_HEX)[:8])
    with pytest.raises(CrhTruncated):
        CrhHeader.decode(b"\x11\x00\x05")
    with pytest.raises(CrhTrailingBytes):
        CrhHeader.decode(bytes.fromhex(NS3_CRH16_HEX) + b"x")
    hdr, n = CrhHeader.decode_prefix(bytes.fromhex(NS3_CRH16_HEX) + b"x")
    assert n == 16 and hdr.segments_left == 3


def test_from_forward_validation():
    with pytest.raises(ValueError):
        CrhHeader.from_forward([])
    with pytest.raises(ValueError):
        CrhHeader.from_forward([0x10000])                 # does not fit CRH-16
    with pytest.raises(ValueError):
        CrhHeader.from_forward([1], routing_type=253)
    with pytest.raises(ValueError):
        CrhHeader.from_forward(list(range(256)))


@given(st.sampled_from([5, 6]).flatmap(lambda t: st.tuples(
    st.just(t),
    st.lists(st.integers(min_value=0, max_value=(1 << (16 if t == 5 else 32)) - 1), min_size=1, max_size=255))))
def test_property_crh_round_trip(case):
    rtype, sids = case
    hdr = CrhHeader.from_forward(sids, routing_type=rtype)
    raw = hdr.encode()
    assert len(raw) == (crh16_size if rtype == 5 else crh32_size)(len(sids))
    assert (raw[1] + 1) * 8 == len(raw)
    back = CrhHeader.decode(raw)
    assert back.encode() == raw
    assert back.remaining_sids_fwd() == tuple(sids)
    assert back.sids_rev[:len(sids)] == hdr.sids_rev and not any(back.sids_rev[len(sids):])


# ----------------------------------------------------------------- RFC 9631 section 5.1

def test_min_length_matches_rfc_examples():
    assert [min_hdr_ext_len(sl, 5) for sl in (0, 1, 2, 3, 6, 7, 10)] == [0, 0, 0, 1, 1, 2, 2]
    assert [min_hdr_ext_len(sl, 6) for sl in (0, 1, 2, 3, 4, 5)] == [0, 0, 1, 1, 2, 2]


@given(st.integers(min_value=0, max_value=255), st.sampled_from([5, 6]))
def test_property_min_length_equals_pad8_rule(sl, rtype):
    sid = 2 if rtype == 5 else 4
    # the ns-3 GetMinimumLength formula: pad8(4 + SL * sid size) / 8 - 1
    assert min_hdr_ext_len(sl, rtype) == pad8(4 + sl * sid) // 8 - 1


# ----------------------------------------------------------------- forwarding

def test_walk_decrement_then_index():
    raw = CrhHeader.from_forward([2, 3, 7]).encode()
    seen = []
    while True:
        r = crh_process_at_node(raw)
        if r.action == "deliver":
            break
        assert r.action == "forward"
        seen.append((r.next_sid, r.out_bytes[3]))
        raw = r.out_bytes
    assert seen == [(2, 2), (3, 1), (7, 0)]
    assert r.out_bytes == raw


def test_forged_segments_left_rejected_with_code_6():
    forged = dataclasses.replace(CrhHeader.from_forward([2, 3]), segments_left=6).encode()
    assert len(forged) == 8 and forged[1] == 0
    r = crh_process_at_node(forged)
    assert r == CrhProcessResult(action="drop_malformed", reason="min_length",
                                 icmp_code=ICMP_CODE_MIN_LENGTH, icmp_pointer=3)
    honest = CrhHeader.from_forward([2, 3]).encode()
    assert crh_process_at_node(honest).action == "forward"


def test_crh_process_passes_payload_and_rejects_bad_bytes():
    r = crh_process_at_node(CrhHeader.from_forward([4, 9]).encode() + b"PAY")
    assert r.next_sid == 4 and r.out_bytes.endswith(b"PAY")
    assert crh_process_at_node(b"\x11\x01\x05\x02\x00").reason == "truncated"
    r = crh_process_at_node(TcrhHeader.from_forward([2], [1], 0, 0).encode())
    assert (r.action, r.reason, r.icmp_code, r.icmp_pointer) == ("drop_malformed", "wrong_type", 0, 2)


def test_crh_unrecognised_type_with_sl0_is_ignored():
    # RFC 8200 section 4.4: an unrecognised routing type with Segments Left 0
    # is ignored (process the Next Header); only SL > 0 is a Parameter Problem
    tcrh_sl0 = bytearray(TcrhHeader.from_forward([2], [1], 0, 0).encode())
    tcrh_sl0[3] = 0
    r = crh_process_at_node(bytes(tcrh_sl0) + b"PAY")
    assert (r.action, r.reason, r.icmp_code, r.icmp_pointer) == ("ignore", "wrong_type", None, None)
    assert r.out_bytes == bytes(tcrh_sl0) + b"PAY" and r.next_sid is None

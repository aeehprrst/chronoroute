"""Tests for chronoroute.proto.tcrh and the T-CRH sizes (spec/tcrh-v1.md)."""

import dataclasses
from fractions import Fraction

import pytest
from hypothesis import given, settings, strategies as st

from chronoroute.proto import (
    TcrhHeader, ProcessResult, build_header, encode_deltas, process_at_node, ingress_send,
    link_down_fallback, NumHopsZero,
    TcrhDecodeError, WrongRoutingType, TruncatedHeader, SegmentsLeftTooLarge,
    LengthMismatch, TrailingBytes, FLAG_DEV, FLAG_GREEDY, FLAG_SAT, MOD32, UNIT_NS,
    ground_station_sid, is_ground_station_sid, clock_u, tcrh_size, pad8, hdr_ext_len,
    ms_to_ns, CrhHeader,
)

V0_HEX = "1102fd0300030000000003e8000708000307000206000000"


def v0():
    return TcrhHeader.from_forward([2, 3, 7], [6, 7, 8], 1000, 0)


def at(hdr, sl, **kw):
    """Bytes of hdr as they look on arrival with Segments Left = sl."""
    return dataclasses.replace(hdr, segments_left=sl, **kw).encode()


# ----------------------------------------------------------------- sizes

def test_tcrh_sizes_match_spec_examples():
    assert [tcrh_size(h) for h in (1, 3, 5, 10, 13, 255)] == [16, 24, 32, 48, 56, 784]
    assert tcrh_size(0) == 16


def test_tcrh_size_limits():
    with pytest.raises(ValueError):
        tcrh_size(256)
    with pytest.raises(ValueError):
        tcrh_size(-1)


@given(st.integers(min_value=1, max_value=255))
def test_size_and_hdr_ext_len_formulas(h):
    hdr = TcrhHeader.from_forward(list(range(h)), [1] * h, 0, 1)
    raw = hdr.encode()
    assert len(raw) == hdr.size == tcrh_size(h) == pad8(12 + 3 * h)
    assert len(raw) % 8 == 0
    assert raw[1] == hdr.hdr_ext_len == len(raw) // 8 - 1 == hdr_ext_len(len(raw))
    assert (raw[1] + 1) * 8 == len(raw)
    assert raw[12 + 3 * h:] == bytes(len(raw) - 12 - 3 * h)        # zero padding


# ----------------------------------------------------------------- encode / decode

def test_v0_golden_vector_bytes_and_deadlines():
    hdr = v0()
    assert hdr.encode().hex() == V0_HEX
    assert hdr.deadlines() == (1006, 1013, 1021)
    assert [hdr.deadline(k) for k in (1, 2, 3)] == [1006, 1013, 1021]
    assert TcrhHeader.decode(bytes.fromhex(V0_HEX)) == hdr


def test_regression_bug4_reverse_order_and_decrement_then_index():
    """Bug #4 (header.py:115-121, simulator.py:195-199): v0 Python wrote SIDs in
    FORWARD order (hex ...000206000307000708...), never decremented Segments Left
    and forwarded from its Python path list instead of the bytes, so it was not
    wire-compatible with ns-3. The walk below uses only the bytes."""
    raw = v0().encode()
    assert raw[12:21].hex() == "000708000307000206"                # SID[0] = last hop
    visited = []
    raw, sid = ingress_send(raw)
    visited.append(sid)
    assert raw[3] == 2                                              # decremented first ...
    for now in (1006, 1013):
        r = process_at_node(raw, now)
        assert r.action == "forward"
        visited.append(r.next_sid)
        raw = r.out_bytes
    final = process_at_node(raw, 1021)
    assert final.action == "deliver" and raw[3] == 0
    assert visited == [2, 3, 7]                                     # ... then indexed


def test_regression_bug4_path_list_mutation_does_not_change_header():
    sids, deltas = [2, 3, 7], [6, 7, 8]
    hdr = TcrhHeader.from_forward(sids, deltas, 1000, 0)
    raw = hdr.encode()
    sids[0] = 99
    deltas[0] = 200
    assert hdr.encode() == raw
    assert process_at_node(ingress_send(raw)[0], 1006).next_sid == 3


def test_forward_views_and_flag_helpers():
    hdr = TcrhHeader.from_forward([2, 3, ground_station_sid(7)], [6, 7, 8], 1000, 3,
                                  next_header=41, extra_flags=FLAG_SAT)
    assert hdr.sids_fwd == (2, 3, 0xF007)
    assert hdr.sids_rev == (0xF007, 3, 2)
    assert hdr.deltas_fwd == (6, 7, 8)
    assert hdr.unit_code == 3 and hdr.unit_ns == 125_000
    assert hdr.flags == 0x34
    assert hdr.is_sat and not hdr.is_dev and not hdr.is_greedy
    assert hdr.segments_left == hdr.num_hops == 3 and hdr.dev_hop == 0
    assert is_ground_station_sid(hdr.sids_fwd[-1]) and not is_ground_station_sid(2)


def test_ground_station_sid_range():
    assert ground_station_sid(0) == 0xF000
    assert ground_station_sid(0xFFE) == 0xFFFE
    with pytest.raises(ValueError):
        ground_station_sid(0xFFF)                                   # would be 0xFFFF, reserved
    with pytest.raises(ValueError):
        ground_station_sid(-1)


def test_header_is_frozen_and_hashable():
    hdr = v0()
    with pytest.raises(dataclasses.FrozenInstanceError):
        hdr.segments_left = 1
    assert hash(hdr) == hash(TcrhHeader.decode(hdr.encode()))
    assert isinstance(TcrhHeader(17, 0, 0, 1, 0, 0, [5], [1]).sids_rev, tuple)


@pytest.mark.parametrize("kwargs", [
    dict(sids_fwd=[1, 2], deltas_fwd=[1]),                      # length mismatch
    dict(sids_fwd=[], deltas_fwd=[]),                           # h = 0
    dict(sids_fwd=list(range(256)), deltas_fwd=[1] * 256),      # h = 256
    dict(sids_fwd=[0xFFFF], deltas_fwd=[1]),                    # reserved SID
    dict(sids_fwd=[0x10000], deltas_fwd=[1]),                   # SID > 16 bits
    dict(sids_fwd=[1], deltas_fwd=[256]),                       # delta > 255 (no silent clamp)
    dict(sids_fwd=[1], deltas_fwd=[-1]),
    dict(sids_fwd=[1], deltas_fwd=[1], epoch_base=MOD32),
    dict(sids_fwd=[1], deltas_fwd=[1], unit_code=4),
    dict(sids_fwd=[1], deltas_fwd=[1], extra_flags=0x10),       # unit bits via extra_flags
    dict(sids_fwd=[1], deltas_fwd=[1], extra_flags=0x08),       # reserved bit
    dict(sids_fwd=[1], deltas_fwd=[1], next_header=256),
])
def test_from_forward_validation(kwargs):
    args = dict(epoch_base=0, unit_code=1)
    args.update(kwargs)
    with pytest.raises(ValueError):
        TcrhHeader.from_forward(**args)


def test_from_forward_rejects_float_delta():
    with pytest.raises(TypeError):
        TcrhHeader.from_forward([1], [2.0], 0, 1)


def test_constructor_validation():
    with pytest.raises(ValueError):
        TcrhHeader(17, 2, 0, 1, 0, 0, [5], [1])                     # SL > NumHops
    with pytest.raises(ValueError):
        TcrhHeader(17, 1, 0, 2, 0, 0, [5], [1, 2])                  # counts differ


# ----- decode validation (section 6 step 1) -----

def test_decode_wrong_type():
    with pytest.raises(WrongRoutingType) as e:
        TcrhHeader.decode(CrhHeader.from_forward([2, 3, 7]).encode())
    assert e.value.reason == "wrong_type" and e.value.pointer == 2
    assert isinstance(e.value, TcrhDecodeError) and isinstance(e.value, ValueError)


def test_decode_truncated():
    raw = v0().encode()
    with pytest.raises(TruncatedHeader) as e:
        TcrhHeader.decode(raw[:7])
    assert e.value.reason == "truncated" and e.value.pointer is None
    with pytest.raises(TruncatedHeader):
        TcrhHeader.decode(raw[:23])


def test_decode_sl_greater_than_num_hops():
    raw = bytearray(v0().encode())
    raw[3] = 4
    with pytest.raises(SegmentsLeftTooLarge) as e:
        TcrhHeader.decode(bytes(raw))
    assert e.value.reason == "sl_gt_numhops" and e.value.pointer == 3


def test_decode_hdr_ext_len_too_small():
    raw = bytearray(v0().encode())
    raw[1] = 1                                   # 16 B announced, 3 hops need 24
    with pytest.raises(LengthMismatch) as e:
        TcrhHeader.decode(bytes(raw))
    assert e.value.reason == "length_mismatch" and e.value.pointer == 1
    with pytest.raises(LengthMismatch):
        TcrhHeader.decode(bytes(raw[:16]))


def test_decode_trailing_bytes_vs_decode_prefix():
    raw = v0().encode() + b"payload!"
    with pytest.raises(TrailingBytes):
        TcrhHeader.decode(raw)
    hdr, n = TcrhHeader.decode_prefix(raw)
    assert hdr == v0() and n == 24


def test_decode_ignores_reserved_fields_and_accepts_longer_header():
    raw = bytearray(v0().encode())
    raw[4] |= 0xC8                               # reserved flag bits
    raw[7] = 0xAB                                # Reserved byte
    raw[22] = 0x01                               # padding
    hdr = TcrhHeader.decode(bytes(raw))
    assert hdr.sids_fwd == (2, 3, 7) and hdr.deadlines() == (1006, 1013, 1021)
    assert hdr.unit_code == 0 and not hdr.is_dev
    longer = bytes(raw[:1]) + bytes([3]) + bytes(raw[2:]) + bytes(8)
    assert TcrhHeader.decode(longer).sids_fwd == (2, 3, 7)


def test_decode_rejects_non_bytes():
    with pytest.raises(TypeError):
        TcrhHeader.decode(V0_HEX)


# ----------------------------------------------------------------- deadlines

def test_deadline_and_current_hop():
    hdr = v0()
    assert hdr.current_hop_index() == 0 and hdr.current_deadline() is None
    for sl, k, d in ((2, 1, 1006), (1, 2, 1013), (0, 3, 1021)):
        h = dataclasses.replace(hdr, segments_left=sl)
        assert h.current_hop_index() == k
        assert h.current_deadline() == d
    with pytest.raises(ValueError):
        hdr.deadline(0)
    with pytest.raises(ValueError):
        hdr.deadline(4)


def test_deadlines_wrap():
    hdr = TcrhHeader.from_forward([1, 2, 3], [2, 1, 5], MOD32 - 3, 0)
    assert hdr.deadlines() == (MOD32 - 1, 0, 5)
    assert hdr.deadline(2) == 0


# ----------------------------------------------------------------- encode_deltas (5.1)

def test_exact_unit_boundary():
    # 3.0 units exactly -> 3; one nanosecond more -> 4; same unit again -> delta 0
    assert encode_deltas([300_000, 300_001, 400_000], 1) == ((3, 1, 0), False)
    assert encode_deltas([Fraction(300_000)], 1) == ((3,), False)


def test_float_budget_noise_needs_explicit_conversion():
    noisy_ms = 0.1 * 3                                      # 0.30000000000000004
    with pytest.raises(TypeError):
        encode_deltas([noisy_ms * 1e6], 1)
    assert encode_deltas([ms_to_ns(noisy_ms)], 1) == ((3,), False)


def test_regression_bug6_no_rounding_down():
    """Bug #6 (header.py:120): v0 used int(round(delta)) per hop -> banker's
    rounding [2.5, 3.5, 2.4, 2.6] -> [2, 4, 2, 3], so hop 1's deadline (2) was
    BELOW its 2.5 ms budget. Ceil-cumulative never goes below a budget and
    never drifts by a whole unit."""
    budgets = [2_500_000, 6_000_000, 8_400_000, 11_000_000]    # cumulative ns
    deltas, sat = encode_deltas(budgets, 0)
    assert deltas == (3, 3, 3, 2) and not sat
    cum = 0
    for d, b in zip(deltas, budgets):
        cum += d
        assert 0 <= cum * 1_000_000 - b < 1_000_000


def test_saturation_sets_sat_and_later_hops_catch_up():
    assert encode_deltas([30_000_000, 31_000_000], 1) == ((255, 55), True)
    assert encode_deltas([300_000_000, 700_000_000, 701_000_000], 0) == ((255, 255, 191), True)
    assert encode_deltas([25_500_000], 1) == ((255,), False)   # exactly 255 fits


def test_decreasing_budget_is_clamped_to_zero_as_spec_says():
    assert encode_deltas([500_000, 300_000, 600_000], 1) == ((5, 0, 1), False)


def test_encode_deltas_input_validation():
    with pytest.raises(ValueError):
        encode_deltas([-1], 1)
    with pytest.raises(TypeError):
        encode_deltas([True], 1)
    with pytest.raises(ValueError):
        encode_deltas([1], 7)
    assert encode_deltas([], 1) == ((), False)


budget_lists = st.lists(st.integers(min_value=0, max_value=40_000_000), min_size=1, max_size=40).map(
    lambda incs: [sum(incs[:i + 1]) for i in range(len(incs))])


@given(budget_lists, st.integers(min_value=0, max_value=3))
def test_property_deadlines_never_early_unless_sat_and_within_one_unit(budgets, uc):
    u = UNIT_NS[uc]
    deltas, sat = encode_deltas(budgets, uc)
    assert all(0 <= d <= 255 for d in deltas) and len(deltas) == len(budgets)
    if not sat:
        cum = 0
        for d, b in zip(deltas, budgets):
            cum += d
            assert cum * u >= b                  # never earlier than the budget
            assert cum * u - b < u               # within one unit of Epoch + B_k/u
    else:
        assert 255 in deltas


@given(st.lists(st.fractions(min_value=0, max_value=10**8), min_size=1, max_size=20),
       st.integers(min_value=0, max_value=3))
def test_property_fraction_budgets_exact(incs, uc):
    budgets = [sum(incs[:i + 1], Fraction(0)) for i in range(len(incs))]
    deltas, sat = encode_deltas(budgets, uc)
    if not sat:
        u = UNIT_NS[uc]
        cum = 0
        for d, b in zip(deltas, budgets):
            cum += d
            assert b <= cum * u < b + u


# ----------------------------------------------------------------- build_header

def test_build_header_stamps_epoch_at_ingress_and_sat():
    hdr = build_header([100, 200], [30_000_000, 31_000_000], 1_000_000_000, 1)
    assert hdr.epoch_base == 10_000
    assert hdr.deltas_fwd == (255, 55) and hdr.is_sat
    assert hdr.encode().hex() == "1102fd02140200000000271000c8370064ff000000000000"
    assert build_header([1], [1], 0, 1, next_header=6).next_header == 6
    with pytest.raises(ValueError):
        build_header([1, 2], [1], 0, 1)


def test_regression_bug7_epoch_stamped_at_ingress_not_schedule_epoch():
    """Bug #7 (scheduler.py:128): v0 put the SCHEDULE epoch in Epoch_Base, so a
    packet sent 14 s after the schedule was computed was 'late' at every hop on
    a healthy network. Stamped at ingress, a packet that meets every budget is
    on time everywhere."""
    schedule_epoch = 1_400_000_000_000_000_000
    t_ingress = schedule_epoch + 14 * 10**9
    budgets = [3_000_000, 7_500_000, 12_000_000]
    raw, _ = ingress_send(build_header([5, 6, 7], budgets, t_ingress, 1).encode())
    for b in budgets:
        r = process_at_node(raw, clock_u(t_ingress + b, 1), "drop")
        assert not r.late and r.action in ("forward", "deliver")
        raw = r.out_bytes


@settings(max_examples=150)
@given(st.integers(min_value=0, max_value=2**62), budget_lists, st.integers(min_value=0, max_value=3),
       st.data())
def test_property_on_budget_arrivals_are_never_late(t_ingress, budgets, uc, data):
    """End to end: a packet that reaches every hop no later than its budget is
    never flagged (no false positive from quantisation), when SAT is clear."""
    sids = list(range(1, len(budgets) + 1))
    hdr = build_header(sids, budgets, t_ingress, uc)
    raw, first = ingress_send(hdr.encode())
    assert first == sids[0]
    for k, b in enumerate(budgets, start=1):
        early = data.draw(st.integers(min_value=0, max_value=b), label="early")
        r = process_at_node(raw, clock_u(t_ingress + b - early, uc), "drop")
        if not hdr.is_sat:
            assert not r.late
        if r.action == "drop_late":
            break
        assert r.hop_index == k
        raw = r.out_bytes
    else:
        assert r.action == "deliver"


# ----------------------------------------------------------------- process_at_node (section 6)

def test_on_time_and_inside_deadline_unit():
    for now in (1000, 1006):
        r = process_at_node(at(v0(), 2), now)
        assert (r.action, r.next_sid, r.late, r.hop_index, r.deadline_u) == ("forward", 3, False, 1, 1006)
        assert r.out_bytes == at(v0(), 1)
        assert r.reason is None and r.icmp_code is None


def test_late_by_one_unit_greedy_conversion():
    r = process_at_node(at(v0(), 2), 1007, "greedy")
    assert (r.action, r.next_sid, r.late, r.hop_index) == ("fallback", 7, True, 1)
    hdr = TcrhHeader.decode(r.out_bytes)
    assert hdr.segments_left == 0 and hdr.flags == FLAG_DEV | FLAG_GREEDY and hdr.dev_hop == 1
    assert hdr.is_greedy and hdr.is_dev


def test_policy_continue_and_drop():
    r = process_at_node(at(v0(), 1), 1014, "continue")
    assert (r.action, r.next_sid, r.late) == ("forward", 7, True)
    hdr = TcrhHeader.decode(r.out_bytes)
    assert (hdr.segments_left, hdr.flags, hdr.dev_hop) == (0, FLAG_DEV, 2)
    r = process_at_node(at(v0(), 2), 1007, "drop")
    assert (r.action, r.out_bytes, r.next_sid, r.late, r.reason) == ("drop_late", None, None, True, "late_strict")


def test_final_endpoint_checks_deadline_but_always_delivers():
    """Bug #1's protocol half: the final endpoint checks its deadline too (spec 11)."""
    r = process_at_node(at(v0(), 0), 1021)
    assert (r.action, r.late, r.out_bytes) == ("deliver", False, at(v0(), 0))
    for policy in ("greedy", "continue", "drop"):
        r = process_at_node(at(v0(), 0), 1022, policy)
        assert (r.action, r.late, r.hop_index, r.deadline_u) == ("deliver", True, 3, 1021)
        hdr = TcrhHeader.decode(r.out_bytes)
        assert hdr.is_dev and hdr.dev_hop == 3 and not hdr.is_greedy


def test_already_dev_packet_gets_no_second_dev_hop():
    dev1 = dataclasses.replace(v0(), flags=FLAG_DEV, dev_hop=1)
    r = process_at_node(at(dev1, 1), 1100, "continue")
    assert (r.action, r.next_sid, r.late) == ("forward", 7, False)
    assert TcrhHeader.decode(r.out_bytes).dev_hop == 1
    r = process_at_node(at(dev1, 1), 1010, "greedy")           # on time, but DEV set upstream
    assert r.action == "fallback" and not r.late
    r = process_at_node(at(dev1, 1), 1010, "drop")
    assert r.action == "drop_late" and not r.late


def test_ingress_arrival_has_no_deadline_check():
    r = process_at_node(v0().encode(), MOD32 - 1)
    assert (r.action, r.next_sid, r.late, r.hop_index, r.deadline_u) == ("forward", 2, False, 0, None)


def test_wrap_late_and_on_time():
    w = TcrhHeader.from_forward([1, 2, 3], [2, 1, 5], MOD32 - 3, 0)
    assert process_at_node(at(w, 2), 0).late
    assert not process_at_node(at(w, 1), MOD32 - 1).late


def test_payload_and_reserved_bytes_pass_through():
    raw = bytearray(at(v0(), 2))
    raw[4] |= 0x88
    raw[7] = 0x5A
    raw[23] = 0x01
    packet = bytes(raw) + b"\xde\xad\xbe\xef"
    r = process_at_node(packet, 1006)
    expect = bytearray(packet)
    expect[3] = 1
    assert r.out_bytes == bytes(expect)
    r = process_at_node(packet, 1007)
    assert r.out_bytes[4] == 0x88 | FLAG_DEV | FLAG_GREEDY and r.out_bytes[7] == 0x5A
    assert r.out_bytes[-4:] == b"\xde\xad\xbe\xef"


@pytest.mark.parametrize("mutate, reason, pointer", [
    (lambda b: b[:3] + b"\x04" + b[4:], "sl_gt_numhops", 3),
    (lambda b: b[:1] + b"\x01" + b[2:], "length_mismatch", 1),
    (lambda b: b[:16], "truncated", None),
    (lambda b: b[:5], "truncated", None),
    (lambda b: b[:2] + b"\x05" + b[3:], "wrong_type", 2),
])
def test_malformed_packets_are_dropped(mutate, reason, pointer):
    r = process_at_node(mutate(at(v0(), 2)), 1000)
    assert r == ProcessResult(action="drop_malformed", reason=reason,
                              icmp_code=None if pointer is None else 0, icmp_pointer=pointer)


def test_process_argument_validation():
    with pytest.raises(ValueError):
        process_at_node(at(v0(), 2), 1000, "teleport")
    with pytest.raises(ValueError):
        process_at_node(at(v0(), 2), MOD32)
    with pytest.raises(TypeError):
        process_at_node(at(v0(), 2), 1000.0)


def test_ingress_send():
    out, first = ingress_send(v0().encode())
    assert first == 2 and out == at(v0(), 2)
    with pytest.raises(ValueError):
        ingress_send(at(v0(), 2))                                  # not fresh
    with pytest.raises(TcrhDecodeError):
        ingress_send(v0().encode()[:10])


def test_num_hops_zero_is_malformed():
    # Spec section 2: Num Hops is 1..255, and section 6 step 1c rejects 0
    # (Parameter Problem, Code 0, pointer -> Num Hops). Before, a header with
    # no entries at all decoded fine and was "delivered".
    raw = bytes.fromhex("1101fd0000000000" "00000000" "00000000")
    with pytest.raises(NumHopsZero) as e:
        TcrhHeader.decode(raw)
    assert e.value.reason == "numhops_zero" and e.value.pointer == 5
    assert isinstance(e.value, TcrhDecodeError)
    assert process_at_node(raw, 5) == ProcessResult(
        action="drop_malformed", reason="numhops_zero", icmp_code=0, icmp_pointer=5)
    # checked before SL > NumHops (the order is part of the contract)
    raw_sl1 = raw[:3] + b"\x01" + raw[4:]
    assert process_at_node(raw_sl1, 5).reason == "numhops_zero"
    with pytest.raises(ValueError):
        TcrhHeader(17, 0, 0, 0, 0, 0, [], [])                      # the value object agrees
    with pytest.raises(ValueError):
        ingress_send(raw)


def test_unrecognised_routing_type_follows_rfc8200():
    # RFC 8200 section 4.4: a routing header of a type the node does not
    # know is IGNORED when Segments Left is 0 (process the Next Header), and
    # discarded with Parameter Problem Code 0 -> Routing Type otherwise.
    crh_sl0 = bytes.fromhex("11010500000700030002000000000000")       # CRH-16, SL 0
    r = process_at_node(crh_sl0 + b"PAYLOAD", 5, "greedy")
    assert r == ProcessResult(action="ignore", out_bytes=crh_sl0 + b"PAYLOAD",
                              reason="wrong_type")
    crh_sl3 = crh_sl0[:3] + b"\x03" + crh_sl0[4:]
    assert process_at_node(crh_sl3, 5) == ProcessResult(
        action="drop_malformed", reason="wrong_type", icmp_code=0, icmp_pointer=2)
    # decode() itself still refuses: these bytes are not a T-CRH
    with pytest.raises(WrongRoutingType):
        TcrhHeader.decode(crh_sl0)


# ----------------------------------------------------------------- next link down (step 7)

def test_link_down_at_the_ingress_sets_dev_with_dev_hop_0():
    # spec section 2/6 step 7: Dev Hop 0 with DEV set = the ingress found its
    # first link down (the ingress does no deadline check, so only this can)
    out, first = ingress_send(v0().encode())                       # SL = 2, next = 2
    r = link_down_fallback(out)
    assert r.action == "fallback" and r.reason == "link_down"
    assert r.next_sid == 7 and r.hop_index == 0 and r.late is False and r.deadline_u is None
    expect = bytearray(out)
    expect[3], expect[4], expect[6] = 0, FLAG_DEV | FLAG_GREEDY, 0
    assert r.out_bytes == bytes(expect)
    back = TcrhHeader.decode(r.out_bytes)
    assert back.is_dev and back.is_greedy and back.dev_hop == 0 and back.segments_left == 0
    # the final endpoint delivers such a packet (DEV with Dev Hop 0 is valid)
    assert process_at_node(r.out_bytes, 5000).action == "deliver"


def test_link_down_after_a_transit_hop_and_with_dev_already_set():
    hop1 = process_at_node(at(v0(), 2), 1006).out_bytes            # on time, SL now 1
    r = link_down_fallback(hop1 + b"PAY")
    assert r.hop_index == 1 and r.next_sid == 7
    assert r.out_bytes[3:7] == bytes([0, FLAG_DEV | FLAG_GREEDY, 3, 1]) and r.out_bytes.endswith(b"PAY")
    # DEV already set upstream (continue policy): Dev Hop is kept
    cont = process_at_node(at(v0(), 1), 1014, "continue").out_bytes    # late at hop 2, SL 0
    assert cont[6] == 2
    r = link_down_fallback(cont)
    assert r.hop_index == 2 and r.out_bytes[6] == 2 and r.out_bytes[4] == FLAG_DEV | FLAG_GREEDY


def test_link_down_refuses_what_it_cannot_mean():
    with pytest.raises(ValueError):
        link_down_fallback(v0().encode())                          # fresh: step 5 not done
    greedy = at(v0(), 0, flags=FLAG_DEV | FLAG_GREEDY, dev_hop=1)
    with pytest.raises(ValueError):
        link_down_fallback(greedy)                                 # greedy mode skips dead links itself
    r = link_down_fallback(at(v0(), 1)[:2] + b"\x05" + at(v0(), 1)[3:])
    assert (r.action, r.reason, r.icmp_pointer) == ("drop_malformed", "wrong_type", 2)


# ----------------------------------------------------------------- round trip property

headers = st.integers(min_value=1, max_value=255).flatmap(lambda h: st.builds(
    lambda sl, flags, dev, epoch, sids, deltas, nh: TcrhHeader(nh, sl, flags, h, dev, epoch, sids, deltas),
    st.integers(min_value=0, max_value=h),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=255),
    st.integers(min_value=0, max_value=MOD32 - 1),
    st.lists(st.integers(min_value=0, max_value=0xFFFF), min_size=h, max_size=h),
    st.lists(st.integers(min_value=0, max_value=255), min_size=h, max_size=h),
    st.integers(min_value=0, max_value=255),
))


@settings(max_examples=200)
@given(headers)
def test_property_round_trip(hdr):
    raw = hdr.encode()
    assert TcrhHeader.decode(raw) == hdr
    assert TcrhHeader.decode(raw).encode() == raw
    assert len(raw) == tcrh_size(hdr.num_hops)
    assert raw[2] == 253 and raw[7] == 0

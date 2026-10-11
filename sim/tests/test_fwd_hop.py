"""The engine's fast byte path (fwd/hop.py) must behave EXACTLY like the
normative reference chronoroute.proto: same action, next SID, output bytes,
late flag, hop index, deadline and reason, for every input, including
malformed bytes and the exceptions of the reference functions."""

import json
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from chronoroute.fwd import hop
from chronoroute.proto import tcrh as P

REPO = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((REPO / "spec" / "golden" / "tcrh_vectors.json").read_text(encoding="utf-8"))


def ref_process(raw, now_u, policy):
    r = P.process_at_node(raw, now_u, policy)
    return (r.action, r.next_sid, r.out_bytes, r.late, r.hop_index, r.deadline_u, r.reason)


def outcome(fn, *args):
    """Result, or the exception type and message (so errors are compared too)."""
    try:
        return ("ok", fn(*args))
    except Exception as exc:              # noqa: BLE001 - comparing behaviour, errors included
        return ("err", type(exc).__name__, str(exc))


@st.composite
def headers(draw):
    """Mostly valid T-CRH bytes, sometimes with any field mutated (malformed on purpose)."""
    h = draw(st.integers(1, 20))
    sids = draw(st.lists(st.integers(0, 0xFFFE), min_size=h, max_size=h))
    deltas = draw(st.lists(st.integers(0, 255), min_size=h, max_size=h))
    epoch = draw(st.integers(0, 2**32 - 1))
    uc = draw(st.integers(0, 3))
    extra = draw(st.sampled_from([0, P.FLAG_DEV, P.FLAG_SAT, P.FLAG_DEV | P.FLAG_GREEDY, P.FLAG_GREEDY]))
    hdr = P.TcrhHeader.from_forward(sids, deltas, epoch, uc, extra_flags=extra)
    raw = bytearray(hdr.encode())
    raw[3] = draw(st.integers(0, h))                     # any Segments Left
    raw[6] = draw(st.integers(0, 255))                   # any Dev Hop
    if draw(st.booleans()):
        raw[4] = draw(st.integers(0, 255))               # any flags, reserved bits included
    mutation = draw(st.sampled_from(["none"] * 6 + ["type", "numhops", "sl", "hel", "truncate",
                                                    "trailing", "short"]))
    if mutation == "type":
        raw[2] = draw(st.integers(0, 255))
    elif mutation == "numhops":
        raw[5] = draw(st.integers(0, 255))
    elif mutation == "sl":
        raw[3] = draw(st.integers(0, 255))
    elif mutation == "hel":
        raw[1] = draw(st.integers(0, 255))
    elif mutation == "truncate":
        raw = raw[:draw(st.integers(0, len(raw)))]
    elif mutation == "trailing":
        raw += bytes(draw(st.integers(1, 30)))
    elif mutation == "short":
        raw = raw[:draw(st.integers(0, 11))]
    return bytes(raw)


@settings(max_examples=3000, deadline=None)
@given(raw=headers(), now_u=st.integers(0, 2**32 - 1), policy=st.sampled_from(P.POLICIES),
       near=st.booleans())
def test_fast_process_equals_reference(raw, now_u, policy, near):
    if near and len(raw) >= 12 and raw[2] == P.ROUTING_TYPE_TCRH:
        # clocks near the deadline are where an off-by-one would hide
        now_u = (int.from_bytes(raw[8:12], "big") + sum(raw[14::3]) + now_u % 7 - 3) % 2**32
    assert outcome(hop.fast_process, raw, now_u, policy) == outcome(ref_process, raw, now_u, policy)


@settings(max_examples=2000, deadline=None)
@given(raw=headers())
def test_fast_ingress_and_link_down_equal_reference(raw):
    assert outcome(hop.fast_ingress, raw) == outcome(P.ingress_send, raw)

    def ref_ld(b):
        r = P.link_down_fallback(b)
        return (r.action, r.next_sid, r.out_bytes, r.hop_index, r.reason)
    assert outcome(hop.fast_link_down, raw) == outcome(ref_ld, raw)


@pytest.mark.parametrize("v", GOLDEN["process"], ids=[v["name"] for v in GOLDEN["process"]])
def test_fast_process_golden_vectors(v):
    action, next_sid, out, late, k, deadline, reason = hop.fast_process(
        bytes.fromhex(v["hex_in"]), v["now_u"], v["policy"])
    assert action == v["expect_action"]
    assert next_sid == v["expect_next_sid"]
    assert (out.hex() if out is not None else None) == v["expect_hex_out"]
    assert late == v["expect_late"]
    assert k == v["expect_hop_index"]
    assert deadline == v["expect_deadline_u"]
    assert reason == v["expect_reason"]


@pytest.mark.parametrize("v", GOLDEN["link_down"], ids=[v["name"] for v in GOLDEN["link_down"]])
def test_fast_link_down_golden_vectors(v):
    action, next_sid, out, k, reason = hop.fast_link_down(bytes.fromhex(v["hex_in"]))
    assert action == v["expect_action"]
    assert next_sid == v["expect_next_sid"]
    assert (out.hex() if out is not None else None) == v["expect_hex_out"]
    assert k == v["expect_hop_index"]
    assert reason == v["expect_reason"]


def test_verify_mode_catches_a_divergence(monkeypatch):
    proc = hop.HopProcessor("greedy", mode="fast", verify_every=1)
    raw = bytes.fromhex(GOLDEN["process"][0]["hex_in"])
    proc.process(raw, 1003)                       # agrees: no error
    assert proc.verified == 1
    real = hop.fast_process
    monkeypatch.setattr(hop, "fast_process", lambda r, n, p: real(r, n + 100, p))
    with pytest.raises(hop.HopMismatch):
        proc.process(raw, 1003)


def test_reference_mode_calls_proto():
    proc = hop.HopProcessor("continue", mode="reference")
    raw = bytes.fromhex(GOLDEN["process"][0]["hex_in"])
    assert proc.process(raw, 1003) == ref_process(raw, 1003, "continue")
    with pytest.raises(ValueError):
        hop.HopProcessor("sideways")

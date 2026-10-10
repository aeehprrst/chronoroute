"""
Golden vectors (spec/golden/*.json): the cross-implementation contract.

Every vector is decoded, re-encoded and processed by chronoroute.proto, the
way spec/golden/README.md tells any other implementation to consume them.
The last tests check that the files are exactly what gen_vectors.py produces
(so they cannot drift from the generator) and that the mandatory cases exist.
"""

import importlib.util
import json
from pathlib import Path

import pytest

import chronoroute.proto as P

GOLDEN = Path(__file__).resolve().parents[2] / "spec" / "golden"
TCRH = json.loads((GOLDEN / "tcrh_vectors.json").read_text(encoding="utf-8"))
CRH = json.loads((GOLDEN / "crh_vectors.json").read_text(encoding="utf-8"))


def _ids(vectors):
    return [v["name"] for v in vectors]


# ----------------------------------------------------------------- T-CRH encode

def build(v):
    """Inputs -> header, exactly as README.md describes."""
    uc = v["unit_code"]
    if "epoch_base" in v:
        epoch = v["epoch_base"]
    else:
        epoch = P.epoch_base_at_ingress(int(v["t_ingress_gps_ns"]), uc)
    if "deltas_fwd" in v:
        deltas, sat = v["deltas_fwd"], False
    else:
        deltas, sat = P.encode_deltas(v["cumulative_budgets_ns"], uc)
    return P.TcrhHeader.from_forward(v["sids_fwd"], deltas, epoch, uc,
                                     next_header=v["next_header"],
                                     extra_flags=v["flags"] | (P.FLAG_SAT if sat else 0))


@pytest.mark.parametrize("v", TCRH["encode"], ids=_ids(TCRH["encode"]))
def test_tcrh_encode_vector(v):
    assert ("deltas_fwd" in v) != ("cumulative_budgets_ns" in v)
    assert ("epoch_base" in v) != ("t_ingress_gps_ns" in v)
    hdr = build(v)
    raw = hdr.encode()
    assert raw.hex() == v["expect_hex"]
    assert list(hdr.deadlines()) == v["expect_deadlines_u"]
    assert hdr.is_sat == v["expect_sat"]
    assert hdr.epoch_base == v["expect_epoch_base"]
    assert list(hdr.deltas_fwd) == v["expect_deltas_fwd"]
    assert hdr.flags == v["expect_flags"]
    assert len(raw) == v["expect_size"] == P.tcrh_size(len(v["sids_fwd"]))
    # decode side: the bytes alone give back the path and every deadline
    back = P.TcrhHeader.decode(bytes.fromhex(v["expect_hex"]))
    assert back == hdr and back.encode() == raw
    assert list(back.sids_fwd) == v["sids_fwd"]
    assert [back.deadline(k) for k in range(1, back.num_hops + 1)] == v["expect_deadlines_u"]


def test_tcrh_build_header_matches_budget_vectors():
    """build_header() (the convenience used by simulators) agrees with the
    vectors that give budgets and an ingress time."""
    for v in TCRH["encode"]:
        if "cumulative_budgets_ns" in v and "t_ingress_gps_ns" in v and v["flags"] == 0:
            hdr = P.build_header(v["sids_fwd"], v["cumulative_budgets_ns"],
                                 int(v["t_ingress_gps_ns"]), v["unit_code"], v["next_header"])
            assert hdr.encode().hex() == v["expect_hex"], v["name"]


# ----------------------------------------------------------------- T-CRH process

@pytest.mark.parametrize("v", TCRH["process"], ids=_ids(TCRH["process"]))
def test_tcrh_process_vector(v):
    r = P.process_at_node(bytes.fromhex(v["hex_in"]), v["now_u"], v["policy"])
    assert r.action == v["expect_action"]
    assert r.next_sid == v["expect_next_sid"]
    assert (None if r.out_bytes is None else r.out_bytes.hex()) == v["expect_hex_out"]
    assert r.late == v["expect_late"]
    assert r.hop_index == v["expect_hop_index"]
    assert r.deadline_u == v["expect_deadline_u"]
    assert r.reason == v["expect_reason"]
    # the exact ICMPv6 Parameter Problem (spec 6 step 1), not just "some pointer"
    assert r.icmp_code == v["expect_icmp_code"]
    assert r.icmp_pointer == v["expect_icmp_pointer"]


@pytest.mark.parametrize("v", TCRH["link_down"], ids=_ids(TCRH["link_down"]))
def test_tcrh_link_down_vector(v):
    r = P.link_down_fallback(bytes.fromhex(v["hex_in"]))
    assert r.action == v["expect_action"]
    assert r.next_sid == v["expect_next_sid"]
    assert (None if r.out_bytes is None else r.out_bytes.hex()) == v["expect_hex_out"]
    assert r.hop_index == v["expect_hop_index"]
    assert r.reason == v["expect_reason"]
    assert r.icmp_code == v["expect_icmp_code"]
    assert r.icmp_pointer == v["expect_icmp_pointer"]
    assert r.late is False


# ----------------------------------------------------------------- CRH

@pytest.mark.parametrize("v", CRH["encode"], ids=_ids(CRH["encode"]))
def test_crh_encode_vector(v):
    hdr = P.CrhHeader.from_forward(v["sids_fwd"], routing_type=v["routing_type"],
                                   next_header=v["next_header"])
    raw = hdr.encode()
    assert raw.hex() == v["expect_hex"]
    assert len(raw) == v["expect_size"] and raw[1] == v["expect_hdr_ext_len"]
    back = P.CrhHeader.decode(raw)
    assert list(back.sids_rev) == v["expect_decoded_sids_rev"]
    assert list(back.remaining_sids_fwd()) == v["sids_fwd"]


@pytest.mark.parametrize("v", CRH["process"], ids=_ids(CRH["process"]))
def test_crh_process_vector(v):
    r = P.crh_process_at_node(bytes.fromhex(v["hex_in"]))
    assert r.action == v["expect_action"]
    assert r.next_sid == v["expect_next_sid"]
    assert (None if r.out_bytes is None else r.out_bytes.hex()) == v["expect_hex_out"]
    assert r.reason == v["expect_reason"]
    assert r.icmp_code == v["expect_icmp_code"]
    assert r.icmp_pointer == v["expect_icmp_pointer"]


# ----------------------------------------------------------------- the files themselves

def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_vectors", GOLDEN / "gen_vectors.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_files_are_exactly_what_the_generator_writes():
    gen = _load_generator()
    assert (GOLDEN / "tcrh_vectors.json").read_text(encoding="utf-8") == gen.render_tcrh()
    assert (GOLDEN / "crh_vectors.json").read_text(encoding="utf-8") == gen.render_crh()


def test_generation_is_deterministic():
    gen = _load_generator()
    assert gen.render_tcrh() == gen.render_tcrh()
    assert gen.render_crh() == gen.render_crh()


def test_schema_top_level():
    assert set(TCRH) == {"spec", "encode", "process", "link_down"} and TCRH["spec"] == "tcrh-v1"
    assert set(CRH) == {"spec", "encode", "process"} and CRH["spec"] == "rfc9631"
    names = _ids(TCRH["encode"]) + _ids(TCRH["process"]) + _ids(TCRH["link_down"])
    assert len(names) == len(set(names)), "vector names must be unique"


def test_mandatory_cases_are_present():
    enc = {v["name"]: v for v in TCRH["encode"]}
    v0 = enc["v0-3hop"]
    assert v0["expect_hex"] == "1102fd0300030000000003e8000708000307000206000000"
    assert v0["expect_deadlines_u"] == [1006, 1013, 1021]
    assert {len(v["sids_fwd"]) for v in enc.values()} >= {1, 10, 13, 255}
    assert any(v["expect_sat"] for v in enc.values())
    assert {v["unit_code"] for v in enc.values()} == {0, 1, 2, 3}
    assert any(P.is_ground_station_sid(s) for v in enc.values() for s in v["sids_fwd"])
    assert any(v["expect_epoch_base"] > P.MOD32 - 10 and v["expect_deadlines_u"][-1] < 10
               for v in enc.values()), "need a deadline that wraps past 2^32"
    b = enc["budget-exact-boundary-uc1"]
    assert b["cumulative_budgets_ns"][:2] == [300_000, 300_001] and b["expect_deltas_fwd"][:2] == [3, 1]
    proc = {v["name"]: v for v in TCRH["process"]}
    actions = {v["expect_action"] for v in proc.values()}
    assert actions == set(P.ACTIONS)
    assert {v["policy"] for v in proc.values()} == set(P.POLICIES)
    reasons = {v["expect_reason"] for v in proc.values() if v["expect_action"] == "drop_malformed"}
    assert {"sl_gt_numhops", "truncated", "length_mismatch", "wrong_type", "numhops_zero"} <= reasons
    # every process vector carries the ICMP keys (null when nothing is sent)
    assert all("expect_icmp_code" in v and "expect_icmp_pointer" in v for v in proc.values())
    pointers = {v["expect_reason"]: v["expect_icmp_pointer"] for v in proc.values()
                if v["expect_action"] == "drop_malformed"}
    assert pointers == {"truncated": None, "wrong_type": 2, "numhops_zero": 5,
                        "sl_gt_numhops": 3, "length_mismatch": 1}
    assert proc["not-tcrh-sl0-ignored"]["expect_action"] == "ignore"
    # Dev Hop 0 with DEV set (the ingress found its first link down) is pinned
    down = {v["name"]: v for v in TCRH["link_down"]}
    assert down["ingress-link-down"]["expect_hop_index"] == 0
    assert bytes.fromhex(down["ingress-link-down"]["expect_hex_out"])[4:7] == bytes([3, 3, 0])

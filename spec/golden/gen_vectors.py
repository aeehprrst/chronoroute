#!/usr/bin/env python3
"""
gen_vectors.py
--------------
Deterministic generator for the T-CRH v1 and CRH golden test vectors:

    spec/golden/tcrh_vectors.json
    spec/golden/crh_vectors.json

Usage (from the repository root):
    venv/bin/python -B spec/golden/gen_vectors.py           # (re)write both files
    venv/bin/python -B spec/golden/gen_vectors.py --check   # exit 1 if a file is stale

The expectations are computed by the reference implementation
(chronoroute.proto), so on their own they would only prove that Python agrees
with itself. That is why several vectors are ALSO worked out by hand below
(HAND_VERIFIED_*) and the generator refuses to write anything if the
implementation disagrees with the hand arithmetic. The v0-3hop vector is the
hex printed by the ns-3 reference (scratch/tcrh-experiment.cc) and spec 10.

Output is stable: keys are sorted, there are no timestamps, one vector per
line, so regenerating with unchanged code gives a byte-identical file.
"""

import argparse
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import chronoroute.proto as P
except ImportError:  # running from a checkout without `pip install -e .`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim"))
    import chronoroute.proto as P

HERE = Path(__file__).resolve().parent
TCRH_FILE = HERE / "tcrh_vectors.json"
CRH_FILE = HERE / "crh_vectors.json"

GS = P.ground_station_sid          # ground station g -> SID 0xF000 + g
U = P.UNIT_NS                      # unit code -> nanoseconds


# =========================================================================
#  Hand-verified vectors (the arithmetic is shown; the generator asserts it)
# =========================================================================
#
# (1) v0-3hop  -- spec section 10, ns-3 tcrh-experiment.cc self-test.
#     Path 2 -> 3 -> 7, d = 6, 7, 8 (unit code 0 = 1 ms), Epoch_Base 1000.
#       11        Next Header 17 (UDP)
#       02        Hdr Ext Len: size = pad8(12 + 3*3) = pad8(21) = 24 -> 24/8 - 1 = 2
#       fd        Routing Type 253
#       03        Segments Left = h = 3
#       00        Flags: unit code 0, nothing else
#       03        Num Hops 3
#       00 00     Dev Hop 0, Reserved 0
#       000003e8  Epoch_Base 1000
#       0007 08   SID[0] = s_3 = 7, Delta[0] = d_3 = 8   (reversed order)
#       0003 07   SID[1] = s_2 = 3, Delta[1] = d_2 = 7
#       0002 06   SID[2] = s_1 = 2, Delta[2] = d_1 = 6
#       000000    padding 21 -> 24
#     Deadlines: D_1 = 1000+6 = 1006, D_2 = 1006+7 = 1013, D_3 = 1013+8 = 1021.
#
# (2) budget-exact-boundary-uc1  -- u = 0.1 ms = 100 000 ns, Epoch_Base 5000.
#     B = 300 000, 300 001, 400 000, 400 000 ns
#       target_1 = ceil(300 000 / 100 000) = ceil(3)        = 3 -> d_1 = 3 - 0 = 3
#       target_2 = ceil(300 001 / 100 000) = ceil(3.00001)  = 4 -> d_2 = 4 - 3 = 1
#       target_3 = ceil(400 000 / 100 000) = 4                  -> d_3 = 4 - 4 = 0
#       target_4 = 4                                            -> d_4 = 0
#     A budget of exactly 3.0 units gives 3 (not 4); one nanosecond more gives 4;
#     a Delta of 0 is legal. D = 5003, 5004, 5004, 5004.
#     size = pad8(12 + 12) = 24, HEL 2; flags = 1 << 4 = 0x10; 5000 = 0x00001388
#       11 02 fd 04 | 10 04 00 00 | 00001388 | f000 00 | 000c 00 | 000b 01 | 000a 03
#
# (3) sat-uc1  -- u = 100 000 ns, T_ingress = 1 000 000 000 ns (1 s).
#     Epoch_Base = ceil(1e9 / 1e5) = 10000 = 0x2710.
#     B = 30 ms, 31 ms = 30 000 000, 31 000 000 ns
#       target_1 = 300 -> d_1 = 300 > 255 -> clamp 255, SAT;  E = 255
#       target_2 = 310 -> d_2 = 310 - 255 = 55 (0x37);         E = 310
#     So hop 1's deadline (10255) is earlier than its budget (10300): that is
#     exactly what SAT warns about. Hop 2 catches up: 10310.
#     flags = 0x10 | 0x04 = 0x14; size = pad8(12 + 6) = 24, HEL 2
#       11 02 fd 02 | 14 02 00 00 | 00002710 | 00c8 37 | 0064 ff | 000000000000
#
# (4) unit-code-2  -- u = 0.25 ms = 250 000 ns, T_ingress = 1 000 000 123 ns.
#     Epoch_Base = ceil(1 000 000 123 / 250 000) = ceil(4000.000492) = 4001
#     B = 1 800 000, 5 190 000, 9 000 001 ns
#       target_1 = ceil(7.2)       = 8   -> d_1 = 8
#       target_2 = ceil(20.76)     = 21  -> d_2 = 13
#       target_3 = ceil(36.000004) = 37  -> d_3 = 16
#     D = 4009, 4022, 4038. flags = 2 << 4 = 0x20.
#
# (5) half-unit-budgets-uc0 -- the v0 encoder's banker's rounding regression.
#     Per-hop budgets 2.5, 3.5, 2.4, 2.6 ms; v0 rounded each one on its own
#     (round-half-even) to 2, 4, 2, 3, so hop 1's deadline was 0.5 ms EARLY.
#     Cumulative B = 2.5, 6.0, 8.4, 11.0 ms; T_ingress = 5 s -> Epoch_Base 5000.
#       targets ceil(2.5)=3, ceil(6.0)=6, ceil(8.4)=9, ceil(11.0)=11
#       d = 3, 3, 3, 2;  D = 5003, 5006, 5009, 5011 (each >= budget, < budget + 1)
#
# (6) wrap-deadlines-uc0 -- Epoch_Base = 2^32 - 3 = 4294967293 = 0xfffffffd,
#     d = 2, 1, 5: D_1 = 4294967295, D_2 = 4294967296 mod 2^32 = 0, D_3 = 5.
#
# (7) wrap-epoch-uc1 -- T_ingress = 2^32 * 100 000 - 1 ns, one ns before unit 2^32.
#     Epoch_Base = ceil(T / u) mod 2^32 = 2^32 mod 2^32 = 0.
#     B = 250 000, 500 000 ns -> targets 3, 5 -> d = 3, 2 -> D = 3, 5.

HAND_VERIFIED_ENCODE = {
    "v0-3hop": ("1102fd0300030000000003e8000708000307000206000000", [1006, 1013, 1021]),
    "budget-exact-boundary-uc1": ("1102fd041004000000001388f00000000c00000b01000a03",
                                  [5003, 5004, 5004, 5004]),
    "sat-uc1": ("1102fd021402000000002710" "00c8370064ff" "000000000000", [10255, 10310]),
    "unit-code-2": (None, [4009, 4022, 4038]),
    "half-unit-budgets-uc0": (None, [5003, 5006, 5009, 5011]),
    "wrap-deadlines-uc0": ("1102fd0300030000fffffffd000305000201000102000000",
                           [4294967295, 0, 5]),
    "wrap-epoch-uc1": (None, [3, 5]),
}


# =========================================================================
#  Encode vectors (inputs)
# =========================================================================

def _cum(values):
    out, running = [], 0
    for v in values:
        running += v
        out.append(running)
    return out


def encode_cases():
    """Each case: inputs only. Exactly one of deltas_fwd / cumulative_budgets_ns
    and one of epoch_base / t_ingress_gps_ns."""
    cases = []

    cases.append(dict(name="v0-3hop", note="ns-3 reference vector (spec 10), unit 1 ms",
                      sids_fwd=[2, 3, 7], deltas_fwd=[6, 7, 8], unit_code=0,
                      epoch_base=1000, next_header=17, flags=0))

    cases.append(dict(name="h1-ground-station-encap",
                      note="h=1 (16 B), final endpoint is ground station 5, Next Header 41 (encapsulation)",
                      sids_fwd=[GS(5)], deltas_fwd=[42], unit_code=1,
                      epoch_base=123456789, next_header=41, flags=0))

    cases.append(dict(name="budget-exact-boundary-uc1",
                      note="exactly 3.0 units -> 3; 3 units + 1 ns -> 4; Delta 0 is legal",
                      sids_fwd=[10, 11, 12, GS(0)],
                      cumulative_budgets_ns=[300_000, 300_001, 400_000, 400_000],
                      unit_code=1, epoch_base=5000, next_header=17, flags=0))

    cases.append(dict(name="sat-uc1",
                      note="30 ms hop at 0.1 ms does not fit in a byte: clamp to 255, set SAT; hop 2 catches up",
                      sids_fwd=[100, 200], cumulative_budgets_ns=[30_000_000, 31_000_000],
                      unit_code=1, t_ingress_gps_ns=1_000_000_000, next_header=17, flags=0))

    cases.append(dict(name="sat-repeated-uc0",
                      note="two consecutive saturations at 1 ms: 300 ms then 700 ms cumulative",
                      sids_fwd=[1, 2, 3], cumulative_budgets_ns=[300_000_000, 700_000_000, 701_000_000],
                      unit_code=0, epoch_base=0, next_header=17, flags=0))

    for uc in (0, 1, 2, 3):
        cases.append(dict(name=f"unit-code-{uc}",
                          note=f"same budgets and ingress time in unit code {uc} ({U[uc]} ns)",
                          sids_fwd=[7, 8, GS(2)],
                          cumulative_budgets_ns=[1_800_000, 5_190_000, 9_000_001],
                          unit_code=uc, t_ingress_gps_ns=1_000_000_123, next_header=17, flags=0))

    cases.append(dict(name="half-unit-budgets-uc0",
                      note="per-hop 2.5/3.5/2.4/2.6 ms: v0 banker's rounding gave 2,4,2,3 (hop 1 early)",
                      sids_fwd=[21, 22, 23, GS(1)],
                      cumulative_budgets_ns=_cum([2_500_000, 3_500_000, 2_400_000, 2_600_000]),
                      unit_code=0, t_ingress_gps_ns=5_000_000_000, next_header=6, flags=0))

    cases.append(dict(name="wrap-deadlines-uc0",
                      note="Epoch_Base = 2^32 - 3: D_2 and D_3 wrap past 2^32",
                      sids_fwd=[1, 2, 3], deltas_fwd=[2, 1, 5], unit_code=0,
                      epoch_base=(1 << 32) - 3, next_header=17, flags=0))

    cases.append(dict(name="wrap-epoch-uc1",
                      note="T_ingress one ns before unit 2^32: Epoch_Base = ceil(...) mod 2^32 = 0",
                      sids_fwd=[0x0100, GS(10)], cumulative_budgets_ns=[250_000, 500_000],
                      unit_code=1, t_ingress_gps_ns=(1 << 32) * U[1] - 1, next_header=17, flags=0))

    # A realistic 10-hop path at the provisional default unit, stamped with a
    # real GPS time (today's CelesTrak snapshot time). Predicted per-hop delays
    # (ns) times a slack of 1.3, rounded up to the ns with integer arithmetic.
    pred = [2_650_000, 3_390_000, 4_120_000, 1_800_000, 5_205_000,
            3_390_000, 2_981_000, 4_407_000, 3_112_000, 6_033_000]
    t_real = P.utc_to_gps_ns(datetime(2026, 10, 10, 13, 58, 0, 123456, tzinfo=timezone.utc))
    cases.append(dict(name="h10-real-gps-time-uc1",
                      note="h=10 (48 B), GPS time of 2026-10-10T13:58:00.123456Z, budgets = 1.3 x prediction",
                      sids_fwd=[1201, 1202, 1340, 1341, 1342, 1480, 1481, 1620, 1621, GS(3)],
                      cumulative_budgets_ns=[(c * 13 + 9) // 10 for c in _cum(pred)],
                      unit_code=1, t_ingress_gps_ns=t_real, next_header=17, flags=0))

    cases.append(dict(name="h13-uc3",
                      note="h=13 (56 B) at 0.125 ms, Next Header 59 (no next header)",
                      sids_fwd=[300 + i for i in range(12)] + [GS(4)],
                      deltas_fwd=[20, 31, 0, 255, 1, 17, 40, 22, 9, 13, 100, 2, 60],
                      unit_code=3, epoch_base=0x89ABCDEF, next_header=59, flags=0))

    cases.append(dict(name="h255-uc0",
                      note="maximum h=255 (784 B); deadlines wrap past 2^32 part way along",
                      sids_fwd=list(range(1, 255)) + [GS(254)],
                      deltas_fwd=[(37 * k) % 256 for k in range(1, 256)],
                      unit_code=0, epoch_base=4294950000, next_header=17, flags=0))

    cases.append(dict(name="explicit-sat-flag-uc2",
                      note="deltas given directly with the SAT flag passed in (re-encoding a saturated header)",
                      sids_fwd=[5, GS(1)], deltas_fwd=[255, 10], unit_code=2,
                      epoch_base=77, next_header=17, flags=P.FLAG_SAT))
    return cases


def build_from_case(c):
    """Turn one encode case into a TcrhHeader, following spec/golden/README.md."""
    uc = c["unit_code"]
    if "epoch_base" in c:
        epoch = c["epoch_base"]
    else:
        epoch = P.epoch_base_at_ingress(int(c["t_ingress_gps_ns"]), uc)
    if "deltas_fwd" in c:
        deltas, sat = list(c["deltas_fwd"]), False
    else:
        deltas, sat = P.encode_deltas(c["cumulative_budgets_ns"], uc)
    flags = c["flags"] | (P.FLAG_SAT if sat else 0)
    return P.TcrhHeader.from_forward(c["sids_fwd"], deltas, epoch, uc,
                                     next_header=c["next_header"], extra_flags=flags)


def encode_vectors():
    out = []
    for c in encode_cases():
        hdr = build_from_case(c)
        v = dict(c)
        if "t_ingress_gps_ns" in v:
            # 64-bit values are strings: JSON numbers above 2^53 are not exact in JavaScript
            v["t_ingress_gps_ns"] = str(v["t_ingress_gps_ns"])
        v["expect_hex"] = hdr.encode().hex()
        v["expect_deadlines_u"] = list(hdr.deadlines())
        v["expect_sat"] = hdr.is_sat
        v["expect_epoch_base"] = hdr.epoch_base
        v["expect_deltas_fwd"] = list(hdr.deltas_fwd)
        v["expect_flags"] = hdr.flags
        v["expect_size"] = hdr.size
        if c["name"] in HAND_VERIFIED_ENCODE:
            hexp, dl = HAND_VERIFIED_ENCODE[c["name"]]
            assert hexp is None or v["expect_hex"] == hexp, (c["name"], v["expect_hex"], hexp)
            assert v["expect_deadlines_u"] == dl, (c["name"], v["expect_deadlines_u"], dl)
        out.append(v)
    return out


# =========================================================================
#  Process vectors
# =========================================================================
#
# Base packet: v0-3hop (unit 1 ms, Epoch_Base 1000, path 2 -> 3 -> 7,
# D_1 = 1006, D_2 = 1013, D_3 = 1021). Hop index on arrival k = 3 - SL.
#
# Hand-verified process cases:
#   late-by-one-unit-hop1-greedy: SL = 2 -> k = 1, D_1 = 1006, now = 1007.
#     serial_diff(1007, 1006) = 1 > 0 -> late: Flags |= DEV (0x01), Dev Hop = 1.
#     SL != 0, DEV set, policy greedy -> Flags |= GREEDY (0x03), SL = 0,
#     next SID = SID[0] = 7. Bytes 3/4/6 become 00/03/01:
#       1102fd00 03030100 000003e8 000708 000307 000206 000000
#   policy-continue-late-hop2: SL = 1 -> k = 2, D_2 = 1013, now = 1014 -> late,
#     DEV, Dev Hop 2; continue -> SL = 0, next SID = SID[0] = 7:
#       1102fd00 01030200 000003e8 ...
#   already-dev-continue: DEV set at hop 1 (Dev Hop 1), now at hop 2 and late
#     again (now 1100 > 1013): no check because DEV is set, Dev Hop stays 1,
#     late = false, continue -> SL 0, next SID 7:  1102fd00 01030100 ...

#   malformed-numhops-zero (spec 6 step 1c): 11 01 fd 00 | 00 00 00 00 | 0...
#     Num Hops (byte 5) = 0 -> discard, Code 0, pointer 5, reason numhops_zero.
#   not-tcrh-sl0-ignored (step 1b, RFC 8200 4.4): the ns-3 CRH-16 vector with
#     SL = 0 (byte 3): 11 01 05 00 0007 0003 0002 ... -> ignore, bytes unchanged.

HAND_VERIFIED_PROCESS = {
    "late-by-one-unit-hop1-greedy": ("fallback", 7, "1102fd0003030100000003e8000708000307000206000000"),
    "policy-continue-late-hop2": ("forward", 7, "1102fd0001030200000003e8000708000307000206000000"),
    "already-dev-continue": ("forward", 7, "1102fd0001030100000003e8000708000307000206000000"),
    "on-time-hop1": ("forward", 3, "1102fd0100030000000003e8000708000307000206000000"),
    "malformed-numhops-zero": ("drop_malformed", None, None),
    "not-tcrh-sl0-ignored": ("ignore", None, "11010500000700030002000000000000"),
}
# (reason, ICMP code, ICMP pointer) for the step 1 cases, by hand from spec 6
HAND_VERIFIED_ICMP = {
    "malformed-numhops-zero": ("numhops_zero", 0, 5),
    "malformed-numhops-zero-sl1": ("numhops_zero", 0, 5),
    "malformed-sl-gt-numhops": ("sl_gt_numhops", 0, 3),
    "malformed-hdr-ext-len-too-small": ("length_mismatch", 0, 1),
    "malformed-wrong-type": ("wrong_type", 0, 2),
    "malformed-truncated": ("truncated", None, None),
    "malformed-truncated-fixed-part": ("truncated", None, None),
    "not-tcrh-sl0-ignored": ("wrong_type", None, None),
}


def _v0():
    return P.TcrhHeader.from_forward([2, 3, 7], [6, 7, 8], 1000, 0)


def _with(hdr, **changes):
    return dataclasses.replace(hdr, **changes).encode()


def _patched(raw, **byte_values):
    """Set raw bytes by offset, for malformed / unusual headers the encoder refuses to build."""
    b = bytearray(raw)
    for off, val in byte_values.items():
        b[int(off.lstrip("b"))] = val
    return bytes(b)


def process_cases():
    v0 = _v0()
    dev1 = dataclasses.replace(v0, flags=P.FLAG_DEV, dev_hop=1)
    cases = [
        ("on-time-hop1", "arrival at hop 1 before its deadline", _with(v0, segments_left=2), 1003, "greedy"),
        ("inside-deadline-unit-hop1", "arrival inside unit D_1 itself is on time",
         _with(v0, segments_left=2), 1006, "greedy"),
        ("late-by-one-unit-hop1-greedy", "one unit late at hop 1: DEV + GREEDY, SL=0, head for SID[0]",
         _with(v0, segments_left=2), 1007, "greedy"),
        ("policy-continue-late-hop2", "late at hop 2, policy continue: DEV recorded, keep the SID list",
         _with(v0, segments_left=1), 1014, "continue"),
        ("policy-drop-late-hop1", "late at hop 1, policy drop: discard (late, strict)",
         _with(v0, segments_left=2), 1007, "drop"),
        ("policy-drop-on-time-hop2", "on time at hop 2: the drop policy does not apply",
         _with(v0, segments_left=1), 1013, "drop"),
        ("final-endpoint-on-time", "SL=0 at the final endpoint, inside D_3: deliver unchanged",
         _with(v0, segments_left=0), 1021, "greedy"),
        ("final-endpoint-late", "the final endpoint also checks: DEV, Dev Hop 3, still delivered",
         _with(v0, segments_left=0), 1022, "greedy"),
        ("final-endpoint-late-drop-policy", "step 3 (deliver) comes before the policy: delivered even under drop",
         _with(v0, segments_left=0), 1030, "drop"),
        ("already-dev-continue", "DEV already set at hop 1: no second check, Dev Hop stays 1",
         _with(dev1, segments_left=1), 1100, "continue"),
        ("already-dev-greedy-on-time", "DEV set upstream: a greedy node converts even an on-time packet",
         _with(dev1, segments_left=1), 1010, "greedy"),
        ("already-dev-drop", "DEV set upstream and policy drop: discard although on time here",
         _with(dev1, segments_left=1), 1010, "drop"),
        ("greedy-packet-at-final-endpoint", "GREEDY packet reaches SID[0]: deliver, no deadline check",
         _with(dataclasses.replace(dev1, flags=P.FLAG_DEV | P.FLAG_GREEDY), segments_left=0), 1500, "greedy"),
        ("ingress-sl-equals-numhops", "SL = NumHops (ingress): no deadline check, forward to SID[h-1]",
         v0.encode(), 999999, "greedy"),
    ]

    wrap = P.TcrhHeader.from_forward([1, 2, 3], [2, 1, 5], (1 << 32) - 3, 0)   # D = 4294967295, 0, 5
    cases += [
        ("wrap-late-hop1", "D_1 = 2^32-1, clock wrapped to 0: one unit late", _with(wrap, segments_left=2), 0, "greedy"),
        ("wrap-on-time-hop2", "D_2 = 0 (wrapped), clock still at 2^32-1: on time",
         _with(wrap, segments_left=1), (1 << 32) - 1, "greedy"),
        # serial_diff(now, D_1) with D_1 = 2^32 - 1:
        #   now = 2^31 - 1 -> ((2^31 - 1) - (2^32 - 1) + 2^31) mod 2^32 - 2^31 = -2^31 -> not late
        #   now = 2^31 - 2 -> 2^31 - 1 > 0                                          -> late
        ("wrap-serial-half-range-not-late", "now - D_1 = -2^31 exactly: the half-range boundary counts as not late",
         _with(wrap, segments_left=2), (1 << 31) - 1, "greedy"),
        ("wrap-serial-half-range-late", "now - D_1 = 2^31 - 1 (mod 2^32): late",
         _with(wrap, segments_left=2), (1 << 31) - 2, "greedy"),
    ]

    uc3 = build_from_case(next(c for c in encode_cases() if c["name"] == "unit-code-3"))  # D = 8016, 8043, 8074
    cases += [
        ("uc3-late-by-one-hop2-continue", "unit code 3: late by one 0.125 ms unit at hop 2",
         _with(uc3, segments_left=1), 8044, "continue"),
        ("uc3-on-time-final", "unit code 3: final endpoint exactly at D_3",
         _with(uc3, segments_left=0), 8074, "greedy"),
    ]

    sat = build_from_case(next(c for c in encode_cases() if c["name"] == "sat-uc1"))   # D = 10255, 10310
    cases.append(("sat-header-late-hop1", "SAT header: flags pass through, hop 1 judged on the clamped deadline",
                  _with(sat, segments_left=1), 10256, "greedy"))

    # Reserved bits / byte / padding are ignored on receipt and passed through unchanged.
    odd = _patched(_with(v0, segments_left=2), b4=0x88, b7=0x5A, b21=0xEE, b23=0x01)
    cases.append(("reserved-bits-ignored", "reserved flag bits 0x88, Reserved byte and padding nonzero: ignored, kept",
                  odd, 1006, "greedy"))
    # A Hdr Ext Len larger than Num Hops needs is accepted (the check is only "<").
    longer = _patched(_with(v0, segments_left=2) + bytes(8), b1=3)
    cases.append(("longer-hdr-ext-len-accepted", "HEL 3 (32 B) for 3 hops (24 B needed): accepted",
                  longer, 1005, "greedy"))

    # Malformed (section 6 step 1). The encoder refuses to build these, so patch bytes.
    good = _with(v0, segments_left=2)
    cases += [
        ("malformed-sl-gt-numhops", "Segments Left 4 > Num Hops 3", _patched(good, b3=4), 1000, "greedy"),
        ("malformed-hdr-ext-len-too-small", "HEL 1 (16 B) cannot hold 3 hops (24 B)",
         _patched(good, b1=1), 1000, "greedy"),
        ("malformed-truncated", "HEL says 24 B, only 16 present", good[:16], 1000, "greedy"),
        ("malformed-truncated-fixed-part", "fewer than 8 bytes", good[:6], 1000, "greedy"),
        ("malformed-wrong-type", "routing type 5 (a CRH-16, SL 3) handed to T-CRH processing: "
         "RFC 8200 4.4 Parameter Problem, pointer 2",
         P.CrhHeader.from_forward([2, 3, 7]).encode(), 1000, "greedy"),
        ("not-tcrh-sl0-ignored", "routing type 5 with SL 0: RFC 8200 4.4 says ignore the header "
         "and process Next Header (no ICMP)",
         dataclasses.replace(P.CrhHeader.from_forward([2, 3, 7]), segments_left=0).encode(),
         1000, "greedy"),
        # Num Hops 0 (spec 2: 1..255; 6 step 1c). The encoder refuses it, so patch bytes:
        # the h=1 header with Num Hops forced to 0 and SL 0 (or 1, to pin the check order).
        ("malformed-numhops-zero", "Num Hops 0: discard, Parameter Problem pointer 5",
         bytes.fromhex("1101fd00000000000000000000000000"), 5, "greedy"),
        ("malformed-numhops-zero-sl1", "Num Hops 0 and SL 1: numhops_zero is checked before SL > NumHops",
         bytes.fromhex("1101fd01000000000000000000000000"), 5, "greedy"),
    ]

    # DEV with Dev Hop 0: the ingress found its first link down (spec 6 step 7)
    # and the packet reached SID[0] by the fallback; a valid header, delivered.
    ingress_dev = dataclasses.replace(v0, flags=P.FLAG_DEV | P.FLAG_GREEDY, dev_hop=0)
    cases.append(("dev-hop-0-at-final-endpoint",
                  "DEV|GREEDY with Dev Hop 0 (set by the ingress, link down): valid, delivered",
                  _with(ingress_dev, segments_left=0), 1500, "greedy"))
    return cases


def process_vectors():
    out = []
    for name, note, raw, now_u, policy in process_cases():
        r = P.process_at_node(raw, now_u, policy)
        v = dict(name=name, note=note, hex_in=raw.hex(), now_u=now_u, policy=policy,
                 expect_action=r.action, expect_next_sid=r.next_sid,
                 expect_hex_out=None if r.out_bytes is None else r.out_bytes.hex(),
                 expect_late=r.late, expect_hop_index=r.hop_index,
                 expect_deadline_u=r.deadline_u, expect_reason=r.reason,
                 # ICMPv6 Parameter Problem (spec 6 step 1): null unless one is sent
                 expect_icmp_code=r.icmp_code, expect_icmp_pointer=r.icmp_pointer)
        if name in HAND_VERIFIED_PROCESS:
            act, sid, hexo = HAND_VERIFIED_PROCESS[name]
            assert (v["expect_action"], v["expect_next_sid"], v["expect_hex_out"]) == (act, sid, hexo), (name, v)
        if name in HAND_VERIFIED_ICMP:
            assert (v["expect_reason"], v["expect_icmp_code"], v["expect_icmp_pointer"]) == \
                HAND_VERIFIED_ICMP[name], (name, v)
        if v["expect_action"] != "drop_malformed":
            assert v["expect_icmp_code"] is None and v["expect_icmp_pointer"] is None, name
        out.append(v)
    return out


# =========================================================================
#  Link-down vectors (spec 6 step 7)
# =========================================================================
#
# Input: the packet as it leaves step 5 (ingress_send, or a 'forward' from
# process_at_node), when the node finds the link to the next SID down.
# Hand-verified:
#   ingress-link-down: v0 after ingress_send, SL = 2 -> k = 3 - 2 - 1 = 0.
#     DEV clear -> Flags 0x01, Dev Hop 0; GREEDY -> 0x03; SL 0; next SID[0] = 7.
#       1102fd00 03030000 000003e8 000708 000307 000206 000000
#   hop1-link-down: SL = 1 -> k = 1: Flags 0x03, Dev Hop 1.
#       1102fd00 03030100 000003e8 ...

HAND_VERIFIED_LINK_DOWN = {
    "ingress-link-down": (7, 0, "1102fd0003030000000003e8000708000307000206000000"),
    "hop1-link-down": (7, 1, "1102fd0003030100000003e8000708000307000206000000"),
}


def link_down_cases():
    v0 = _v0()
    out_ingress, _first = P.ingress_send(v0.encode())                       # SL 2
    hop1 = P.process_at_node(out_ingress, 1006, "greedy").out_bytes          # SL 1
    late2 = P.process_at_node(hop1, 1014, "continue").out_bytes              # DEV, Dev Hop 2, SL 0
    sat = build_from_case(next(c for c in encode_cases() if c["name"] == "sat-uc1"))
    sat_out, _ = P.ingress_send(sat.encode())
    return [
        ("ingress-link-down", "the ingress finds the link to s_1 down: DEV with Dev Hop 0 (spec 2)",
         out_ingress),
        ("hop1-link-down", "node 1 forwarded on time, then finds its next link down: Dev Hop 1", hop1),
        ("dev-already-set-continue-link-down",
         "DEV set at hop 2 under 'continue', next link down: Dev Hop stays 2, GREEDY added", late2),
        ("sat-header-ingress-link-down", "SAT and UNIT bits pass through (0x14 -> 0x17)", sat_out),
        ("link-down-malformed-numhops-zero", "bytes that fail step 1 are discarded as in process",
         bytes.fromhex("1101fd00000000000000000000000000")),
    ]


def link_down_vectors():
    out = []
    for name, note, raw in link_down_cases():
        r = P.link_down_fallback(raw)
        v = dict(name=name, note=note, hex_in=raw.hex(), expect_action=r.action,
                 expect_next_sid=r.next_sid,
                 expect_hex_out=None if r.out_bytes is None else r.out_bytes.hex(),
                 expect_hop_index=r.hop_index, expect_reason=r.reason,
                 expect_icmp_code=r.icmp_code, expect_icmp_pointer=r.icmp_pointer)
        if name in HAND_VERIFIED_LINK_DOWN:
            sid, k, hexo = HAND_VERIFIED_LINK_DOWN[name]
            assert (v["expect_action"], v["expect_next_sid"], v["expect_hop_index"],
                    v["expect_hex_out"], v["expect_reason"]) == ("fallback", sid, k, hexo,
                                                                  "link_down"), (name, v)
        out.append(v)
    return out


# =========================================================================
#  CRH vectors (RFC 9631)
# =========================================================================
#
# ns3-crh16-3hop (crh-experiment.cc self-test): path 2 -> 3 -> 7
#   11 NH 17 | 01 HEL (pad8(4 + 3*2) = 16 B) | 05 CRH-16 | 03 SL
#   0007 0003 0002 (reversed) | 000000000000 padding 10 -> 16
# crh32-3hop: 11 | 01 (pad8(4 + 3*4) = 16) | 06 | 03 | 00000007 00000003 00000002

HAND_VERIFIED_CRH = {
    "ns3-crh16-3hop": "11010503000700030002000000000000",
    "crh32-3hop": "11010603000000070000000300000002",
    "crh16-2hop": "1100050200030002",
}


def crh_encode_vectors():
    cases = [
        ("ns3-crh16-3hop", "ns-3 crh-experiment.cc self-test vector", 5, [2, 3, 7], 17),
        ("crh16-2hop", "two SIDs fill the first 8 octets exactly", 5, [2, 3], 17),
        ("crh16-5hop", "5 SIDs -> 16 B", 5, [11, 12, 13, 14, GS(1)], 17),
        ("crh16-10hop", "10 SIDs -> 24 B", 5, list(range(100, 109)) + [GS(2)], 17),
        ("crh16-13hop", "13 SIDs -> 32 B", 5, list(range(200, 212)) + [GS(3)], 41),
        ("crh32-1hop", "CRH-32, one 32-bit SID -> 8 B", 6, [0x12345678], 17),
        ("crh32-3hop", "CRH-32 version of the ns-3 path", 6, [2, 3, 7], 17),
    ]
    out = []
    for name, note, rtype, sids, nh in cases:
        hdr = P.CrhHeader.from_forward(sids, routing_type=rtype, next_header=nh)
        raw = hdr.encode()
        back = P.CrhHeader.decode(raw)
        v = dict(name=name, note=note, routing_type=rtype, sids_fwd=sids, next_header=nh,
                 expect_hex=raw.hex(), expect_size=hdr.size, expect_hdr_ext_len=hdr.hdr_ext_len,
                 expect_decoded_sids_rev=list(back.sids_rev))
        if name in HAND_VERIFIED_CRH:
            assert v["expect_hex"] == HAND_VERIFIED_CRH[name], (name, v["expect_hex"])
        out.append(v)
    return out


def crh_process_vectors():
    p3 = P.CrhHeader.from_forward([2, 3, 7])
    forged = dataclasses.replace(P.CrhHeader.from_forward([2, 3]), segments_left=6)
    forged32 = dataclasses.replace(P.CrhHeader.from_forward([9], routing_type=6), segments_left=2)
    cases = [
        ("walk-sl3-source", "source: decrement to 2, then index -> SID[2] = 2",
         dataclasses.replace(p3, segments_left=3).encode()),
        ("walk-sl2", "SL 2 -> 1, SID[1] = 3", dataclasses.replace(p3, segments_left=2).encode()),
        ("walk-sl1", "SL 1 -> 0, SID[0] = 7", dataclasses.replace(p3, segments_left=1).encode()),
        ("walk-sl0-deliver", "SL 0: this node is the destination", dataclasses.replace(p3, segments_left=0).encode()),
        ("ns3-forged-sl6", "2-SID header (HEL 0) with SL forged to 6: L = 1 > 0, ICMP code 6",
         forged.encode()),
        ("crh32-forged-sl2", "1-SID CRH-32 (HEL 0) with SL 2: L = 1 > 0", forged32.encode()),
        ("crh16-sl6-fits", "6 SIDs fit in 16 B (HEL 1): L = ceil(4/4) = 1, accepted",
         P.CrhHeader.from_forward([1, 2, 3, 4, 5, 6]).encode()),
        ("wrong-type", "a T-CRH (type 253, SL 3) handed to CRH processing", _v0().encode()),
        ("wrong-type-sl0-ignored", "a T-CRH with SL 0 handed to CRH processing: RFC 8200 4.4, ignored",
         dataclasses.replace(_v0(), segments_left=0).encode()),
        ("truncated", "HEL says 16 B, only 8 present", p3.encode()[:8]),
    ]
    out = []
    for name, note, raw in cases:
        r = P.crh_process_at_node(raw)
        out.append(dict(name=name, note=note, hex_in=raw.hex(), expect_action=r.action,
                        expect_next_sid=r.next_sid,
                        expect_hex_out=None if r.out_bytes is None else r.out_bytes.hex(),
                        expect_reason=r.reason, expect_icmp_code=r.icmp_code,
                        expect_icmp_pointer=r.icmp_pointer))
    return out


# =========================================================================
#  Rendering (stable: sorted keys, one vector per line, no timestamps)
# =========================================================================

def render(doc):
    keys = sorted(doc)
    lines = ["{"]
    for i, key in enumerate(keys):
        comma = "," if i < len(keys) - 1 else ""
        val = doc[key]
        if isinstance(val, list):
            lines.append(f"  {json.dumps(key)}: [")
            for j, item in enumerate(val):
                item_comma = "," if j < len(val) - 1 else ""
                lines.append("    " + json.dumps(item, sort_keys=True) + item_comma)
            lines.append("  ]" + comma)
        else:
            lines.append(f"  {json.dumps(key)}: {json.dumps(val, sort_keys=True)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def render_tcrh():
    return render({"spec": "tcrh-v1", "encode": encode_vectors(), "process": process_vectors(),
                   "link_down": link_down_vectors()})


def render_crh():
    return render({"spec": "rfc9631", "encode": crh_encode_vectors(), "process": crh_process_vectors()})


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="do not write; exit 1 if a file is stale")
    args = ap.parse_args(argv)
    stale = []
    for path, text in ((TCRH_FILE, render_tcrh()), (CRH_FILE, render_crh())):
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            print(f"up to date: {path.name}")
            continue
        if args.check:
            stale.append(path.name)
            print(f"STALE: {path.name}")
        else:
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote: {path.name}")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())

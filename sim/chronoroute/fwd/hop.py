"""
hop.py
------
What a node does with the T-CRH bytes it receives: spec/tcrh-v1.md section 6,
operating ONLY on the header bytes (the engine never forwards from its own
Python copy of the path).

Two interchangeable implementations behind one interface (HopProcessor):

  reference   calls chronoroute.proto directly (process_at_node,
              ingress_send, link_down_fallback): the golden-tested,
              normative code. About 10 microseconds per call, because it
              builds and validates a TcrhHeader object every time.
  fast        the same algorithm written straight on the bytes (indexing and
              one sum over the Delta bytes, no objects). About 1 microsecond.
              For any input that is not a plain well-formed T-CRH (fewer
              than 12 bytes, another routing type, Num Hops 0, SL > Num
              Hops, a length mismatch, truncation, a non-fresh header at the
              ingress, ...) it hands the bytes to the reference code, so
              every error path IS the reference behaviour.

Why both: the plan's throughput target (3e5 hop events per second, master
plan P3 acceptance) is out of reach if every hop builds a TcrhHeader, and
the reviewer (should-fix 8) asked for exactly this: "run the byte path in
validation mode with an equivalence test". The equivalence is proved by
sim/tests/test_fwd_hop.py (hypothesis: random headers, random clocks,
every policy, plus the golden vectors), and at run time verify_every = N
re-runs every N-th hop through the reference code and stops the run on any
difference. Runs record which mode they used.

All results are plain tuples (no objects on the hot path):

    process(raw, now_u)  -> (action, next_sid, out_bytes, late, k, deadline_u, reason)
    ingress(raw)         -> (out_bytes, first_sid)
    link_down(raw)       -> (action, next_sid, out_bytes, k, reason)

action is one of proto.ACTIONS ('deliver', 'forward', 'fallback',
'drop_late', 'drop_malformed', 'ignore').
"""

from ..proto import tcrh as P
from ..proto.timebase import HALF32, MOD32

_MASK32 = MOD32 - 1
_FLAG_DEV = P.FLAG_DEV
_FLAG_GREEDY = P.FLAG_GREEDY
_RT = P.ROUTING_TYPE_TCRH


class HopMismatch(AssertionError):
    """The fast byte path disagreed with the reference code (a bug; the run stops)."""


def _ref_process(raw, now_u, policy):
    r = P.process_at_node(raw, now_u, policy)
    return (r.action, r.next_sid, r.out_bytes, r.late, r.hop_index, r.deadline_u, r.reason)


def _ref_ingress(raw):
    return P.ingress_send(raw)


def _ref_link_down(raw):
    r = P.link_down_fallback(raw)
    return (r.action, r.next_sid, r.out_bytes, r.hop_index, r.reason)


def _patch(raw, sl, flags, dev_hop):
    """Copy of raw with only the mutable fields (SL, Flags, Dev Hop) rewritten (spec section 2)."""
    out = bytearray(raw)
    out[3] = sl
    out[4] = flags
    out[6] = dev_hop
    return bytes(out)


def _well_formed(raw):
    """True for a plain T-CRH that passes every step-1 check (else the reference decides)."""
    n = len(raw)
    if n < 12 or raw[2] != _RT:
        return False
    nh = raw[5]
    if nh == 0 or raw[3] > nh:
        return False
    total = (raw[1] + 1) * 8
    need = (12 + 3 * nh + 7) // 8 * 8
    return total >= need and n >= total


def fast_process(raw, now_u, policy):
    """spec section 6 on the bytes; identical results to proto.process_at_node."""
    # step 1 (validation), inlined from _well_formed: anything unusual -> the reference code
    n = len(raw)
    if n < 12 or raw[2] != _RT:
        return _ref_process(raw, now_u, policy)
    sl = raw[3]
    nh = raw[5]
    if nh == 0 or sl > nh or (raw[1] + 1) * 8 < (12 + 3 * nh + 7) // 8 * 8 or n < (raw[1] + 1) * 8:
        return _ref_process(raw, now_u, policy)
    flags = raw[4]
    dev_hop = raw[6]
    k = nh - sl
    if k >= 1:
        epoch = (raw[8] << 24) | (raw[9] << 16) | (raw[10] << 8) | raw[11]
        # D_k = Epoch_Base + sum(Delta[i] for i in SL..NumHops-1); Delta[i] is byte 12 + 3i + 2
        deadline = (epoch + sum(raw[14 + 3 * sl:12 + 3 * nh:3])) & _MASK32
    else:
        deadline = None
    late = False
    if not flags & _FLAG_DEV and sl < nh:
        if ((now_u - deadline + HALF32) & _MASK32) - HALF32 > 0:
            late = True
            flags |= _FLAG_DEV
            dev_hop = k
    if sl == 0:
        return ("deliver", None, _patch(raw, 0, flags, dev_hop), late, k, deadline, None)
    if flags & _FLAG_DEV:
        if policy == "greedy":
            flags |= _FLAG_GREEDY
            return ("fallback", (raw[12] << 8) | raw[13], _patch(raw, 0, flags, dev_hop),
                    late, k, deadline, None)
        if policy == "drop":
            return ("drop_late", None, None, late, k, deadline, "late_strict")
    sl -= 1
    off = 12 + 3 * sl
    # the common case (forward): rewrite SL, Flags, Dev Hop in a copy (spec section 2), inlined _patch
    out = bytearray(raw)
    out[3] = sl
    out[4] = flags
    out[6] = dev_hop
    return ("forward", (raw[off] << 8) | raw[off + 1], bytes(out), late, k, deadline, None)


def fast_ingress(raw):
    """Ingress steps 5-6 on a fresh header; identical to proto.ingress_send (errors included)."""
    if not _well_formed(raw) or raw[3] != raw[5]:
        return _ref_ingress(raw)           # raises exactly what the reference raises
    sl = raw[3] - 1
    off = 12 + 3 * sl
    return _patch(raw, sl, raw[4], raw[6]), (raw[off] << 8) | raw[off + 1]


def fast_link_down(raw):
    """spec section 6 step 7 on the bytes; identical to proto.link_down_fallback."""
    if not _well_formed(raw) or raw[3] >= raw[5] or raw[4] & _FLAG_GREEDY:
        return _ref_link_down(raw)         # malformed result or the reference's ValueError
    nh, sl, flags, dev_hop = raw[5], raw[3], raw[4], raw[6]
    k = nh - sl - 1
    if not flags & _FLAG_DEV:
        flags |= _FLAG_DEV
        dev_hop = k
    flags |= _FLAG_GREEDY
    return ("fallback", (raw[12] << 8) | raw[13], _patch(raw, 0, flags, dev_hop), k, "link_down")


class HopProcessor:
    """One node behaviour for a run: policy, implementation, optional verification.

    verify_every = N > 0 re-runs every N-th call through the reference code
    and raises HopMismatch on any difference (1 = every call).
    """

    def __init__(self, policy, mode="fast", verify_every=0):
        if policy not in P.POLICIES:
            raise ValueError(f"policy must be one of {P.POLICIES}, got {policy!r}")
        if mode not in ("fast", "reference"):
            raise ValueError(f"mode must be 'fast' or 'reference', got {mode!r}")
        self.policy = policy
        self.mode = mode
        self.verify_every = int(verify_every)
        self.calls = 0
        self.verified = 0

    def _check(self, name, got, want):
        self.verified += 1
        if got != want:
            raise HopMismatch(f"{name}: fast path {got!r} != reference {want!r}")

    def process(self, raw, now_u):
        if self.mode == "reference":
            return _ref_process(raw, now_u, self.policy)
        res = fast_process(raw, now_u, self.policy)
        self.calls += 1
        if self.verify_every and self.calls % self.verify_every == 0:
            self._check("process_at_node", res, _ref_process(raw, now_u, self.policy))
        return res

    def ingress(self, raw):
        if self.mode == "reference":
            return _ref_ingress(raw)
        res = fast_ingress(raw)
        self.calls += 1
        if self.verify_every and self.calls % self.verify_every == 0:
            self._check("ingress_send", res, _ref_ingress(raw))
        return res

    def link_down(self, raw):
        if self.mode == "reference":
            return _ref_link_down(raw)
        res = fast_link_down(raw)
        self.calls += 1
        if self.verify_every and self.calls % self.verify_every == 0:
            self._check("link_down_fallback", res, _ref_link_down(raw))
        return res


__all__ = ["HopMismatch", "HopProcessor", "fast_process", "fast_ingress", "fast_link_down"]

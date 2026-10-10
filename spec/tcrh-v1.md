# T-CRH v1: Temporal Compact Routing Header

Status: project specification, version 1.0.1 (2026-10-10; changes in §12). Experimental,
closed-domain.
Single source of truth for every implementation (Python `chronoroute.proto`, the ns-3
module `contrib/chronoroute`, the website engine, and the Wireshark dissector).
Machine-checkable examples live in `spec/golden/tcrh_vectors.json`; any implementation
that disagrees with a golden vector is wrong.

## 1. Purpose

T-CRH is an IPv6 Routing Header that carries a ground-computed path through a LEO
constellation together with a cumulative arrival deadline for every hop. Each node
compares its clock with the deadline for the hop it has just completed. A packet that is
late reveals that reality has diverged from the predicted schedule, including links that
are up but slow, and the node switches the packet to a fallback forwarding mode.

T-CRH extends the Compact Routing Header (RFC 9631, CRH-16) with a time base and one
deadline byte per hop.

## 2. Wire format

```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+---------------+---------------+---------------+---------------+
|  Next Header  |  Hdr Ext Len  | Rtg Type =253 | Segments Left |   bytes 0-3
+---------------+---------------+---------------+---------------+
|     Flags     |   Num Hops    |    Dev Hop    |   Reserved    |   bytes 4-7
+---------------+---------------+---------------+---------------+
|                          Epoch_Base                           |   bytes 8-11
+---------------+---------------+---------------+---------------+
|        SID[0] (16 bits)       |  Delta[0]     |  SID[1] ...   |   3 bytes per entry
+---------------+---------------+---------------+---------------+
|                ...  zero padding to a multiple of 8 bytes     |
+---------------------------------------------------------------+
```

All multi-byte fields are big-endian (network byte order).

| Field | Size | Meaning |
|---|---|---|
| Next Header | 1 B | Protocol of the header that follows (6 TCP, 17 UDP, 41 IPv6, 59 none). |
| Hdr Ext Len | 1 B | Header length in 8-octet units, not counting the first 8 octets (RFC 8200 §4.4). `total_bytes = (HdrExtLen + 1) * 8`. |
| Routing Type | 1 B | 253 (RFC 4727 experimental value). |
| Segments Left | 1 B | Number of entries not yet consumed (RFC 9631 semantics). Mutable. |
| Flags | 1 B | See §3. Mutable. |
| Num Hops | 1 B | Number of entries `h` actually present (1..255; 0 is malformed, §6 step 1c). Lets a parser stop before the padding. |
| Dev Hop | 1 B | Hop index `k` (0..h) of the node that first set DEV: `k` = 1..h for node k (§6 steps 2 and 7), `k` = 0 for the ingress, which can only set DEV because its first link is down (§6 step 7). Meaningful only while DEV is set; 0 while DEV is clear. Mutable. Was `Reserved` in v0. |
| Reserved | 1 B | Zero on transmit, ignored on receipt. |
| Epoch_Base | 4 B | Ingress time-stamp in deadline units, see §4. |
| Entry `i` | 3 B | `SID[i]` (2 B) and `Delta[i]` (1 B, unsigned), see §5. |
| Padding | 0-7 B | Zeros up to the next multiple of 8 bytes. |

Size: `size(h) = pad8(12 + 3h)`, where `pad8(n) = 8 * ceil(n / 8)`.
Examples: h=1 → 16 B, h=3 → 24 B, h=5 → 32 B, h=10 → 48 B, h=13 → 56 B, h=255 → 784 B.
Hdr Ext Len = `size/8 - 1`.

Mutable fields (change in flight): Segments Left, Flags, Dev Hop. Every other byte is
immutable after ingress. This differs from RFC 9631 (where only Segments Left is mutable)
and must be stated whenever T-CRH is used with IPsec AH.

## 3. Flags

| Bit (mask) | Name | Meaning |
|---|---|---|
| 0x01 | DEV | A node found the packet late (or the plan otherwise broken). Set once, never cleared. Same value as v0. |
| 0x02 | GREEDY | The packet is being forwarded by the fallback (geographic) mode, not by its SID list. |
| 0x04 | SAT | At encode time at least one Delta had to be clamped to 255 (the budget did not fit). |
| 0x08 | — | Reserved, zero. |
| 0x30 | UNIT | Deadline unit code `uc` (two bits, `(flags >> 4) & 3`), see §4. |
| 0xC0 | — | Reserved, zero. |

Unit codes: `uc = 0` → u = 1 ms (v0-compatible); `uc = 1` → u = 0.1 ms; `uc = 2` → u = 0.25 ms;
`uc = 3` → u = 0.125 ms. Provisional default for v1 is `uc = 1` (0.1 ms). Experiment E13
chooses the final default.

## 4. Time base

* The deadline unit `u` comes from the UNIT bits. Every time quantity in the header
  (Epoch_Base and every Delta) is a count of `u`.
* Timescale: GPS time (continuous, no leap seconds). `GPS = UTC + 18 s` for all dates in
  this project (no leap second has been inserted since 2017-01-01). Simulators that run on
  a relative clock define `t0_gps` (the GPS instant of simulation time 0) in their
  configuration and add it to simulation time.
* A node's unit clock: `clock_u(t) = floor(t_gps / u) mod 2^32`, where `t_gps` is the
  node's current GPS time in the same base as Epoch_Base. Implementations should compute it
  in integer nanoseconds: `floor(t_gps_ns / u_ns)`.
* Epoch_Base is stamped **per packet at ingress** (when the header is created), not at
  schedule-computation time: `Epoch_Base = ceil(T_ingress_gps / u) mod 2^32`.
  Rounding the anchor up means the anchor can only add slack, never remove it.
* All comparisons use serial-number arithmetic on 32 bits:
  `serial_diff(a, b) = ((a - b + 2^31) mod 2^32) - 2^31` (a signed value in [-2^31, 2^31)).
  Wrap periods: 49.7 days at u = 1 ms, 4.97 days at u = 0.1 ms. Paths last far less than
  a second, so a deadline is never more than 2^31 units away from the clock.

## 5. Entries and deadlines

* The path has `h` hops: node 1 (first SID after the ingress node) ... node h (the final
  segment endpoint, normally the egress ground station). Forward-order SIDs are
  `s_1..s_h`; forward-order deltas are `d_1..d_h`.
* Entries are stored **in reverse order**, as in RFC 9631: `SID[i] = s_{h-i}` and
  `Delta[i] = d_{h-i}` for `i = 0..h-1`. So `SID[0]` is the final endpoint and
  `SID[h-1]` is the first hop.
* `d_k` is the budget, in units of `u`, for reaching node k from node k-1.
* **Cumulative arrival deadline** at node k (k = 1..h):
  `D_k = (Epoch_Base + d_1 + d_2 + ... + d_k) mod 2^32`.
  Equivalently, with Segments Left `SL = h - k` on arrival at node k,
  `D_k = Epoch_Base + sum(Delta[i] for i in SL..h-1)`.

### 5.1 Encoding the deltas (ceil-cumulative)

Given exact cumulative time budgets from ingress `B_1 <= B_2 <= ... <= B_h` (real numbers,
any time unit), the encoder computes:

```
E = 0                                   # encoded cumulative sum, in units
for k in 1..h:
    target = ceil(B_k / u)              # use exact integer/rational arithmetic
    d_k = target - E
    if d_k > 255: d_k = 255; set SAT
    if d_k < 0:   d_k = 0                # cannot happen when B is non-decreasing
    E = E + d_k
```

Properties: no deadline is ever earlier than its budget unless SAT is set; rounding error
never accumulates (each `D_k` is within one unit of `Epoch_Base + B_k/u` when SAT is
clear); a Delta of 0 is legal (two consecutive hops fall in the same unit).

Implementations MUST do the `ceil` on exact values (integer nanoseconds, or fractions) so
that, for example, a budget of exactly 3.0 units encodes to 3, never 4.

How `B_k` is chosen (multiplicative slack `S`, additive slack, quantile budgets) is a
scheduler policy, not part of the wire format.

## 6. Processing at a node

Applied when a node receives a packet whose IPv6 Destination Address is one of its own
SID addresses (routing headers are examined only by the node named in the Destination
Address, RFC 8200 §4.4). `now_u` is the node's unit clock on arrival.

```
1. Validate, in this order; the first check that fails decides:
   a. fewer than 8 bytes                       -> discard (truncated; no ICMPv6 message:
                                                  there is no field to point at)
   b. Routing Type != 253: not a T-CRH. The node handles it as RFC 8200 §4.4 says for
      an unrecognised Routing Type:
        SL == 0 -> ignore this routing header and process the Next Header;
        SL != 0 -> discard; ICMPv6 Parameter Problem, Code 0, pointer -> Routing Type.
   c. NumHops == 0                             -> discard; Code 0, pointer -> Num Hops
   d. SL > NumHops                             -> discard; Code 0, pointer -> Segments Left
   e. (HdrExtLen + 1) * 8 < pad8(12 + 3 * NumHops)
                                               -> discard; Code 0, pointer -> Hdr Ext Len
   f. fewer bytes than (HdrExtLen + 1) * 8     -> discard (truncated; no ICMPv6 message)
   A Hdr Ext Len larger than needed, a nonzero Reserved byte, nonzero reserved flag bits
   and nonzero padding are accepted and passed on unchanged.
2. Deadline check (only if DEV is clear and SL < NumHops, i.e. this is not the ingress):
       k   = NumHops - SL                   # this node's hop index, 1..h
       D_k = Epoch_Base + sum(Delta[i] for i in SL..NumHops-1)   (mod 2^32)
       if serial_diff(now_u, D_k) > 0:      # strictly later than the deadline unit
           set DEV; DevHop = k
3. If SL == 0: this node is the final segment endpoint. Process Next Header (deliver,
   or decapsulate in encapsulation mode, §8). Stop.
4. If DEV is set, apply the node's deviation policy:
     greedy   : set GREEDY; set SL = 0; set the Destination Address to the address of
                SID[0] (the final endpoint); forward with the fallback function. Nodes that
                later see GREEDY keep using the fallback function.
     continue : keep following the SID list (go to step 5); DEV records the miss.
     drop     : discard (counted as "late, strict").
5. SL = SL - 1;  sid = SID[SL]   (decrement first, then index).
6. Look sid up in the CRH-FIB. Missing entry -> discard; ICMPv6 Parameter Problem,
   Code 0 (RFC 9631 §7). Otherwise set the Destination Address to the entry's address and
   forward on the entry's interface.
7. Next link down: the CRH-FIB entry exists, but its link is down (at the ingress: the
   link to s_1). No deadline can show this, so it is a deviation of its own:
     if DEV is clear: set DEV; DevHop = k   (k from step 2, k = NumHops - SL on arrival;
                                              k = 0 at the ingress)
     set GREEDY; set SL = 0; set the Destination Address to the address of SID[0];
     forward with the fallback function. A node without a fallback function discards
     the packet.
   This applies under every deviation policy: "continue" cannot follow a dead link, and
   "drop" is about late packets. Only SL, Flags and Dev Hop change. On the bytes as they
   leave step 5 (SL already decremented), k = NumHops - SL - 1.
```

The ingress node creates the header with `SL = h`, then performs steps 5-7 itself (no
deadline check at the ingress).

**ICMPv6 pointers.** The Parameter Problem pointers of step 1 are, as offsets inside the
routing header: Hdr Ext Len 1, Routing Type 2, Segments Left 3, Num Hops 5. The Pointer
field of the ICMPv6 message (RFC 4443 §3.4) counts from the start of the invoking packet,
so it is the routing header's own offset in the packet plus that value. The golden
vectors (`expect_icmp_code`, `expect_icmp_pointer`) give the offset inside the routing
header.

"Late" means the node's unit clock has moved past the deadline unit: a packet arriving
anywhere inside unit `D_k` is on time. The comparison is pure integer arithmetic.

## 7. SID allocation

| Range | Use |
|---|---|
| 0x0000 - 0xEFFF | Satellites. For the real fleet the registry is stable and append-only, keyed by NORAD catalogue number. |
| 0xF000 - 0xFFFE | Ground stations and gateways: ground station g -> 0xF000 + g. |
| 0xFFFF | Reserved. |

Each node's SID address is derived from its SID inside the unique-local prefix
`fd00::/8` (exact mapping defined by each simulator's address plan and recorded in its
run manifest).

## 8. Ingress modes

RFC 8200 §4 forbids nodes on the path from inserting extension headers. T-CRH therefore
enters the network in one of two ways:

* **Source insertion:** the sending host builds the T-CRH itself (Next Header = the
  transport protocol). Overhead: `size(h)` bytes per packet.
* **Encapsulation at the gateway:** the gateway (or user terminal) wraps the original
  packet in a new IPv6 header plus T-CRH, Next Header = 41 (IPv6). The egress endpoint
  removes the outer header. Overhead: `40 + size(h)` bytes per packet (like SRv6 H.Encaps).

Experiments that report overhead state which mode they assume.

## 9. Sizes of comparison headers (for experiments)

| Header | Size for n segments |
|---|---|
| T-CRH (this spec) | `pad8(12 + 3n)` |
| CRH-16 (RFC 9631) | `pad8(4 + 2n)` |
| CRH-32 (RFC 9631) | `pad8(4 + 4n)` |
| SRv6 SRH (RFC 8754), no TLVs | `8 + 16n` |

At 10 hops: T-CRH 48 B, CRH-16 24 B, CRH-32 48 B, SRH 168 B.

## 10. Golden vector v0-3hop (from the ns-3 reference, unit 1 ms)

Path 2 -> 3 -> 7, deltas 6, 7, 8 ms, Epoch_Base 1000, Next Header 17, flags 0:

```
11 02 fd 03 | 00 03 00 00 | 00 00 03 e8 | 00 07 08 | 00 03 07 | 00 02 06 | 00 00 00
```

Arrival deadlines: node 2 -> 1006, node 3 -> 1013, node 7 -> 1021.

## 11. Changes from v0

* Byte 6 is now Dev Hop (was Reserved, always zero in v0, so v0 headers decode unchanged).
* Flags gain GREEDY (0x02, already used by the Python simulator), SAT (0x04) and the UNIT
  code (0x30). A v0 header has UNIT = 0, i.e. 1 ms, so v0 headers decode unchanged.
* Epoch_Base is per packet at ingress, in deadline units, on GPS time.
* Deltas use ceil-cumulative encoding instead of round-half-even per hop.
* Serial-number (wrap-safe) comparison.
* The final segment endpoint also checks its deadline.

## 12. Revisions of this document

* 1.0.1 (2026-10-10, P1 review): §6 step 1 now lists the validation order, rejects
  Num Hops = 0 (pointer 5), and says how an unrecognised Routing Type is handled
  (RFC 8200 §4.4: ignored when SL = 0). New §6 step 7 (next link down), which can set
  DEV at the ingress with Dev Hop 0 (§2). The ICMPv6 pointers are listed. Golden vectors:
  new `malformed-numhops-zero*`, `not-tcrh-sl0-ignored` and `dev-hop-0-at-final-endpoint`
  process vectors, a `link_down` section, and ICMP code/pointer on every process vector.
  No wire-format change. Every expectation of the v1.0 vectors is unchanged (the process
  vectors only gain the two ICMP keys); the only behaviour that changed, Num Hops = 0
  being delivered and an unrecognised type with SL = 0 being discarded, had no vector.

# Golden test vectors

Machine-checkable examples for `spec/tcrh-v1.md` (T-CRH v1) and RFC 9631 (CRH-16/32).
**Any implementation that disagrees with a vector is wrong** (Python `chronoroute.proto`,
the ns-3 module, the website engine, the Wireshark dissector).

| File | Contents |
|---|---|
| `tcrh_vectors.json` | T-CRH v1: header encoding (`encode`), per-node processing (`process`) and the next-link-down step (`link_down`) |
| `crh_vectors.json` | CRH-16 / CRH-32 baseline (RFC 9631), byte-exact with ns-3 `crh-experiment.cc` |
| `gen_vectors.py` | The deterministic generator. Several vectors are worked out by hand in its comments and asserted. |

Regenerate with `venv/bin/python -B spec/golden/gen_vectors.py` (or `make golden`, which also
fails if the result differs from git). `--check` only reports stale files. Output is stable:
sorted keys, one vector per line, no timestamps. Never edit the JSON by hand.

## Conventions

* Hex strings are lowercase, no separators, the whole routing header (padding included).
* Integers are JSON numbers, except **`t_ingress_gps_ns`, which is a decimal string**: GPS
  nanoseconds exceed 2^53, the largest integer a JavaScript number holds exactly. Parse it
  as a 64-bit integer (`BigInt` in JS, `uint64_t`/`int64_t` in C++, `int` in Python).
* All times are integers. `*_ns` are nanoseconds; `*_u` and `epoch_base` are deadline units.
* Every vector has a unique `name` and a human `note`. Ignore keys you do not use.

## `tcrh_vectors.json`

`{"spec": "tcrh-v1", "encode": [...], "process": [...], "link_down": [...]}`

### `encode` vectors: build a header, compare bytes

Inputs (exactly one of each pair is present):

| Key | Meaning |
|---|---|
| `sids_fwd` | SIDs in path order: first hop after the ingress first, final endpoint last |
| `deltas_fwd` **or** `cumulative_budgets_ns` | Per-hop deltas in units, used as given; or cumulative budgets B_1..B_h in ns, to encode with spec 5.1 |
| `epoch_base` **or** `t_ingress_gps_ns` | Epoch_Base in units, used as given; or the ingress GPS time: `Epoch_Base = ceil(t / u) mod 2^32` |
| `unit_code` | 0..3 (u = 1 ms, 0.1 ms, 0.25 ms, 0.125 ms) |
| `next_header` | Next Header byte |
| `flags` | Extra state flag bits set by the encoder (DEV/GREEDY/SAT); normally 0. UNIT bits are **not** in here |

How to build (any implementation):

1. `epoch = epoch_base`, or `ceil(t_ingress_gps_ns / u) mod 2^32` with exact integer arithmetic.
2. `deltas = deltas_fwd` and `sat = false`; or `(deltas, sat) = encode_deltas(cumulative_budgets_ns)`
   (spec 5.1, exact integer ceil: 300000 ns at u = 100000 ns is 3 units, 300001 ns is 4).
3. `flags_byte = (unit_code << 4) | flags | (0x04 if sat)`.
4. Fresh header: `Segments Left = Num Hops = h`, `Dev Hop = 0`, `Reserved = 0`, entries in
   **reverse** order (`SID[0]` = final endpoint), zero padding to a multiple of 8.

Expected outputs: `expect_hex` (the encoded header), `expect_deadlines_u` (`D_1..D_h`, mod 2^32),
`expect_sat`, plus the intermediate values `expect_epoch_base`, `expect_deltas_fwd`,
`expect_flags` (whole Flags byte) and `expect_size` (bytes).

Decoders should also decode `expect_hex` and recover `sids_fwd` and every deadline.

### `process` vectors: one node's processing step (spec section 6)

| Key | Meaning |
|---|---|
| `hex_in` | Packet bytes on arrival, starting with the T-CRH (malformed on purpose in `malformed-*`) |
| `now_u` | The node's unit clock, `floor(t_gps / u) mod 2^32`, in the packet's unit |
| `policy` | Node deviation policy: `greedy`, `continue` or `drop` |
| `expect_action` | `deliver`, `forward`, `fallback`, `drop_late`, `drop_malformed`, or `ignore` (not a T-CRH and SL = 0: RFC 8200 §4.4, process the Next Header; bytes unchanged) |
| `expect_next_sid` | SID to forward towards (CRH-FIB lookup is done by the caller), or `null` |
| `expect_hex_out` | Bytes sent on / delivered (only Segments Left, Flags, Dev Hop change; everything else, including Reserved, padding and reserved flag bits, is copied unchanged), or `null` when discarded |
| `expect_late` | `true` only if **this** node's deadline check fired and set DEV (a packet that already had DEV is not checked again) |
| `expect_hop_index` | `k = NumHops - SL` on arrival (0 at the ingress), `null` if malformed |
| `expect_deadline_u` | `D_k` for this node, `null` at the ingress or if malformed |
| `expect_reason` | `null`, `late_strict` (`drop_late`), `wrong_type` (`ignore`), or why the bytes are malformed (below) |
| `expect_icmp_code` | ICMPv6 Parameter Problem code to send (always `0` here), or `null` when no ICMPv6 message is sent |
| `expect_icmp_pointer` | offset of the offending field **inside the routing header**, or `null`. The Pointer field of the ICMPv6 message counts from the start of the invoking packet, so add the routing header's own offset in the packet |

Step 1 (spec §6), checked in this order; the first failing check decides:

| Check | `expect_reason` | `expect_icmp_code` | `expect_icmp_pointer` |
|---|---|---|---|
| fewer than 8 bytes | `truncated` | `null` | `null` |
| Routing Type ≠ 253 and SL = 0 | `wrong_type`, action `ignore` | `null` | `null` |
| Routing Type ≠ 253 and SL ≠ 0 | `wrong_type` | `0` | `2` (Routing Type) |
| Num Hops = 0 | `numhops_zero` | `0` | `5` (Num Hops) |
| SL > Num Hops | `sl_gt_numhops` | `0` | `3` (Segments Left) |
| `(HdrExtLen+1)*8 < pad8(12+3*NumHops)` | `length_mismatch` | `0` | `1` (Hdr Ext Len) |
| fewer bytes than `(HdrExtLen+1)*8` | `truncated` | `null` | `null` |

A Hdr Ext Len larger than needed is accepted. Every non-malformed vector has `null` for both
ICMP keys.

### `link_down` vectors: the next link is down (spec section 6 step 7)

The input is the packet **as it leaves step 5** (after the ingress's own step 5, or after a
`forward` from `process`): the node has looked up the next SID and found its link down.

| Key | Meaning |
|---|---|
| `hex_in` | Packet bytes as they leave step 5 (Segments Left already decremented) |
| `expect_action` | `fallback`, or `drop_malformed` for bytes that fail step 1 |
| `expect_next_sid` | `SID[0]` (the final endpoint), or `null` |
| `expect_hex_out` | DEV set (if it was clear) with Dev Hop = k, GREEDY set, SL = 0; nothing else changes |
| `expect_hop_index` | `k = NumHops - SL - 1` on the input bytes: **0 at the ingress** |
| `expect_reason` | `link_down`, or the step 1 reason |
| `expect_icmp_code`, `expect_icmp_pointer` | as in `process` |

A packet that already has DEV keeps its Dev Hop. Dev Hop 0 with DEV set therefore means "the
ingress found its first link down"; the `process` vector `dev-hop-0-at-final-endpoint` shows such
a packet is valid and delivered.

## `crh_vectors.json`

`{"spec": "rfc9631", "encode": [...], "process": [...]}`

* `encode`: `routing_type` (5 = CRH-16, 6 = CRH-32), `sids_fwd`, `next_header` → `expect_hex`,
  `expect_size`, `expect_hdr_ext_len`, and `expect_decoded_sids_rev`: a CRH has no SID count,
  so a decoder returns **every** SID slot, padding slots included (as ns-3 does).
* `process`: `hex_in` → `expect_action` (`deliver`, `forward`, `drop_malformed`, or `ignore`
  for a routing type other than 5/6 with SL = 0, RFC 8200 §4.4), `expect_next_sid`,
  `expect_hex_out`, `expect_reason` (`min_length`, `wrong_type`, `truncated`),
  `expect_icmp_code` (6 for the RFC 9631 5.1 minimum-length failure, 0 for a wrong routing
  type with SL ≠ 0) and `expect_icmp_pointer` (byte offset inside the routing header).

## Consumers

* Python: `sim/tests/test_golden_vectors.py` (also checks the files equal the generator output).
* ns-3: `tools/golden_to_inc.py` generates `ns3/contrib/chronoroute/test/golden-vectors.inc`
  (ns-3 has no JSON library), which `ns3/contrib/chronoroute/test/chronoroute-test-suite.cc`
  checks (`./test.py --no-build -s chronoroute`). `tools/ns3-sync.sh` regenerates the `.inc`
  and links the module into the ns-3 tree; `make golden` fails if the `.inc` is stale.
* Website engine / Wireshark dissector: load the JSON in their own test runners.

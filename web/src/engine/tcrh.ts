/**
 * T-CRH v1, the Temporal Compact Routing Header: a TypeScript port of the Python
 * reference sim/chronoroute/proto/tcrh.py. spec/tcrh-v1.md (v1.0.1) is normative (section
 * numbers below refer to it) and spec/golden/tcrh_vectors.json is the contract:
 * src/engine/golden.test.ts checks this file against every vector.
 *
 *  0               1               2               3
 * +---------------+---------------+---------------+---------------+
 * |  Next Header  |  Hdr Ext Len  | Rtg Type =253 | Segments Left |  bytes 0-3
 * +---------------+---------------+---------------+---------------+
 * |     Flags     |   Num Hops    |    Dev Hop    |   Reserved    |  bytes 4-7
 * +---------------+---------------+---------------+---------------+
 * |                          Epoch_Base                           |  bytes 8-11
 * +---------------+---------------+---------------+---------------+
 * |        SID[0] (16 bits)       |  Delta[0]     |  SID[1] ...   |  3 B per entry
 * +---------------+---------------+---------------+---------------+
 *                  (zero padding to a multiple of 8 bytes)
 *
 * Entries are stored in REVERSE path order (RFC 9631): SID[0] is the final endpoint and
 * SID[h-1] the first hop. A node decrements Segments Left first, then reads SID[SL].
 * All multi-byte fields are big-endian; they are read and written with DataView.
 *
 * Number safety: see timebase.ts. Wire values are numbers (all sums stay below 2^33);
 * nanosecond budgets and GPS times are bigint.
 */
import { tcrhSize, TCRH_ENTRY_BYTES, TCRH_FIXED_BYTES, TCRH_MAX_HOPS } from './sizes';
import {
  MOD32,
  checkRange,
  epochBaseAtIngress,
  ratioCeilDiv,
  serialDiff,
  unitNs,
  unitNsBig,
  type Ratio,
  type UnitCode,
} from './timebase';

// ----- Header constants -----
export const ROUTING_TYPE_TCRH = 253; // RFC 4727 experimental value
export const MAX_HOPS = TCRH_MAX_HOPS; // Num Hops is one byte
export const MAX_DELTA = 255; // Delta is one unsigned byte
export const DEFAULT_NEXT_HEADER = 17; // UDP, as in the ns-3 reference

// ----- Byte offsets (also the ICMPv6 Parameter Problem pointers) -----
export const OFF_NEXT_HEADER = 0;
export const OFF_HDR_EXT_LEN = 1;
export const OFF_ROUTING_TYPE = 2;
export const OFF_SEGMENTS_LEFT = 3;
export const OFF_FLAGS = 4;
export const OFF_NUM_HOPS = 5;
export const OFF_DEV_HOP = 6;
export const OFF_RESERVED = 7;
export const OFF_EPOCH_BASE = 8;
export const OFF_ENTRIES = TCRH_FIXED_BYTES; // 12

// ----- Flag bits (section 3) -----
export const FLAG_DEV = 0x01;
export const FLAG_GREEDY = 0x02;
export const FLAG_SAT = 0x04;
export const FLAG_UNIT_MASK = 0x30;
export const FLAG_UNIT_SHIFT = 4;
export const FLAG_RESERVED_MASK = 0xc8;
export const FLAG_STATE_MASK = FLAG_DEV | FLAG_GREEDY | FLAG_SAT;

// ----- SID allocation (section 7) -----
export const SID_SATELLITE_MAX = 0xefff;
export const SID_GROUND_BASE = 0xf000;
export const SID_GROUND_MAX = 0xfffe;
export const SID_RESERVED = 0xffff;

// ----- Deviation policies and processing outcomes (section 6) -----
export type Policy = 'greedy' | 'continue' | 'drop';
export type Action = 'deliver' | 'forward' | 'fallback' | 'drop_late' | 'drop_malformed' | 'ignore';
export const POLICIES: readonly Policy[] = ['greedy', 'continue', 'drop'];
export const ACTIONS: readonly Action[] = ['deliver', 'forward', 'fallback', 'drop_late', 'drop_malformed', 'ignore'];

/** SID of ground station number g (section 7): 0xF000 + g. */
export function groundStationSid(g: number): number {
  checkRange('ground station number', g, 0, SID_GROUND_MAX - SID_GROUND_BASE);
  return SID_GROUND_BASE + g;
}

/** True for SIDs in the ground-station block 0xF000 - 0xFFFE. */
export function isGroundStationSid(sid: number): boolean {
  return sid >= SID_GROUND_BASE && sid <= SID_GROUND_MAX;
}

// ------------------------------------------------------------------ errors

/** Why bytes are not a valid T-CRH, in the order the checks run (golden README). */
export type DecodeReason =
  | 'truncated'
  | 'wrong_type'
  | 'numhops_zero'
  | 'sl_gt_numhops'
  | 'length_mismatch'
  | 'trailing_bytes';

export class TcrhDecodeError extends Error {
  readonly reason: DecodeReason;
  /** Offset of the offending field inside the routing header (ICMPv6 pointer), or null. */
  readonly pointer: number | null;

  constructor(reason: DecodeReason, message: string, pointer: number | null = null) {
    super(message);
    this.name = 'TcrhDecodeError';
    this.reason = reason;
    this.pointer = pointer;
  }
}

// ------------------------------------------------------------------ the header

/**
 * One T-CRH as values. sidsRev / deltasRev are in WIRE order (reversed path, index = SL).
 * The Reserved byte and the padding are not stored: encode writes them as zero. Flags is
 * stored exactly as received, reserved bits included.
 */
export interface TcrhHeader {
  readonly nextHeader: number;
  readonly segmentsLeft: number;
  readonly flags: number;
  readonly numHops: number;
  readonly devHop: number;
  readonly epochBase: number;
  readonly sidsRev: readonly number[];
  readonly deltasRev: readonly number[];
}

/** Validate field ranges (as the Python dataclass does) and return a frozen copy. */
export function makeHeader(h: TcrhHeader): TcrhHeader {
  checkRange('next_header', h.nextHeader, 0, 255);
  checkRange('num_hops', h.numHops, 1, MAX_HOPS); // section 2: 1..255
  checkRange('segments_left', h.segmentsLeft, 0, h.numHops);
  checkRange('flags', h.flags, 0, 255);
  checkRange('dev_hop', h.devHop, 0, 255);
  checkRange('epoch_base', h.epochBase, 0, MOD32 - 1);
  if (h.sidsRev.length !== h.numHops || h.deltasRev.length !== h.numHops) {
    throw new RangeError(`num_hops=${h.numHops} but ${h.sidsRev.length} SIDs and ${h.deltasRev.length} deltas`);
  }
  for (const sid of h.sidsRev) checkRange('SID', sid, 0, 0xffff);
  for (const d of h.deltasRev) checkRange('delta', d, 0, MAX_DELTA);
  return Object.freeze({
    nextHeader: h.nextHeader,
    segmentsLeft: h.segmentsLeft,
    flags: h.flags,
    numHops: h.numHops,
    devHop: h.devHop,
    epochBase: h.epochBase,
    sidsRev: Object.freeze([...h.sidsRev]),
    deltasRev: Object.freeze([...h.deltasRev]),
  });
}

/**
 * A fresh header (Segments Left = Num Hops = h, Dev Hop = 0) from a FORWARD-order path:
 * sidsFwd[0] is the first hop after the ingress, sidsFwd[h-1] the final endpoint;
 * deltasFwd[k-1] is d_k in units. extraFlags may hold DEV / GREEDY / SAT only.
 */
export function fromForward(
  sidsFwd: readonly number[],
  deltasFwd: readonly number[],
  epochBase: number,
  unitCode: number,
  nextHeader: number = DEFAULT_NEXT_HEADER,
  extraFlags = 0,
): TcrhHeader {
  if (sidsFwd.length !== deltasFwd.length) {
    throw new RangeError('every hop needs exactly one delta (sidsFwd and deltasFwd differ in length)');
  }
  if (sidsFwd.length < 1 || sidsFwd.length > MAX_HOPS) {
    throw new RangeError(`a T-CRH carries 1..${MAX_HOPS} hops, got ${sidsFwd.length}`);
  }
  // 0xFFFF is reserved (section 7): never put it in a new path.
  for (const sid of sidsFwd) checkRange('SID', sid, 0, SID_RESERVED - 1);
  // No silent clamping here: clamping is encodeDeltas' job, and it sets SAT.
  for (const d of deltasFwd) checkRange('delta', d, 0, MAX_DELTA);
  checkRange('epoch_base', epochBase, 0, MOD32 - 1);
  unitNs(unitCode); // validates 0..3
  checkRange('extra_flags', extraFlags, 0, 255);
  if ((extraFlags & ~FLAG_STATE_MASK) !== 0) {
    throw new RangeError('extra_flags may only contain DEV/GREEDY/SAT; the unit goes in unitCode');
  }
  const h = sidsFwd.length;
  return makeHeader({
    nextHeader,
    segmentsLeft: h,
    flags: (unitCode << FLAG_UNIT_SHIFT) | extraFlags,
    numHops: h,
    devHop: 0,
    epochBase,
    sidsRev: [...sidsFwd].reverse(),
    deltasRev: [...deltasFwd].reverse(),
  });
}

/** Bytes on the wire: pad8(12 + 3h). */
export function sizeOf(h: TcrhHeader): number {
  return tcrhSize(h.numHops);
}

/** Hdr Ext Len: 8-octet units not counting the first 8 (RFC 8200 section 4.4). */
export function hdrExtLenOf(h: TcrhHeader): number {
  return sizeOf(h) / 8 - 1;
}

/** Serialise (big-endian, zero Reserved byte, zero padding). */
export function encode(h: TcrhHeader): Uint8Array {
  const size = sizeOf(h);
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  view.setUint8(OFF_NEXT_HEADER, h.nextHeader);
  view.setUint8(OFF_HDR_EXT_LEN, size / 8 - 1);
  view.setUint8(OFF_ROUTING_TYPE, ROUTING_TYPE_TCRH);
  view.setUint8(OFF_SEGMENTS_LEFT, h.segmentsLeft);
  view.setUint8(OFF_FLAGS, h.flags);
  view.setUint8(OFF_NUM_HOPS, h.numHops);
  view.setUint8(OFF_DEV_HOP, h.devHop);
  view.setUint8(OFF_RESERVED, 0);
  view.setUint32(OFF_EPOCH_BASE, h.epochBase, false);
  let off = OFF_ENTRIES;
  for (let i = 0; i < h.numHops; i += 1) {
    view.setUint16(off, h.sidsRev[i] ?? 0, false);
    view.setUint8(off + 2, h.deltasRev[i] ?? 0);
    off += TCRH_ENTRY_BYTES;
  }
  return out;
}

/**
 * Validate and parse. Checks run in this fixed order (section 6 step 1), so every
 * implementation reports the same reason for the same bytes:
 *   1. fewer than 8 bytes                              -> truncated
 *   2. Routing Type != 253                             -> wrong_type       (pointer 2)
 *   3. Num Hops == 0                                   -> numhops_zero     (pointer 5)
 *   4. Segments Left > Num Hops                        -> sl_gt_numhops    (pointer 3)
 *   5. (HdrExtLen + 1) * 8 < pad8(12 + 3 * NumHops)    -> length_mismatch  (pointer 1)
 *   6. fewer bytes than (HdrExtLen + 1) * 8            -> truncated
 *   7. (exact only) more bytes than that               -> trailing_bytes
 * A non-zero Reserved byte, reserved flag bits or padding are ignored (section 2), as is a
 * Hdr Ext Len larger than needed.
 */
function parse(raw: Uint8Array, exact: boolean): { header: TcrhHeader; length: number } {
  if (raw.length < 8) throw new TcrhDecodeError('truncated', `T-CRH needs at least 8 bytes, got ${raw.length}`);
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const nextHeader = view.getUint8(OFF_NEXT_HEADER);
  const hel = view.getUint8(OFF_HDR_EXT_LEN);
  const rtype = view.getUint8(OFF_ROUTING_TYPE);
  const sl = view.getUint8(OFF_SEGMENTS_LEFT);
  const flags = view.getUint8(OFF_FLAGS);
  const nhops = view.getUint8(OFF_NUM_HOPS);
  const devHop = view.getUint8(OFF_DEV_HOP);
  if (rtype !== ROUTING_TYPE_TCRH) {
    throw new TcrhDecodeError('wrong_type', `routing type ${rtype} is not T-CRH (${ROUTING_TYPE_TCRH})`, OFF_ROUTING_TYPE);
  }
  if (nhops === 0) {
    // A header with no entries has no final endpoint to deliver to or to fall back towards.
    throw new TcrhDecodeError('numhops_zero', 'Num Hops is 0 (a T-CRH carries 1..255 entries)', OFF_NUM_HOPS);
  }
  if (sl > nhops) {
    throw new TcrhDecodeError('sl_gt_numhops', `Segments Left ${sl} > Num Hops ${nhops}`, OFF_SEGMENTS_LEFT);
  }
  const total = (hel + 1) * 8;
  const need = tcrhSize(nhops);
  if (total < need) {
    throw new TcrhDecodeError(
      'length_mismatch',
      `Hdr Ext Len ${hel} gives ${total} bytes, but ${nhops} hops need ${need}`,
      OFF_HDR_EXT_LEN,
    );
  }
  if (raw.length < total) {
    throw new TcrhDecodeError('truncated', `Hdr Ext Len announces ${total} bytes, only ${raw.length} present`);
  }
  if (exact && raw.length !== total) {
    throw new TcrhDecodeError('trailing_bytes', `Hdr Ext Len announces ${total} bytes, got ${raw.length}`);
  }
  const epochBase = view.getUint32(OFF_EPOCH_BASE, false);
  const sidsRev: number[] = [];
  const deltasRev: number[] = [];
  let off = OFF_ENTRIES;
  for (let i = 0; i < nhops; i += 1) {
    // Num Hops lets the parser stop before the padding.
    sidsRev.push(view.getUint16(off, false));
    deltasRev.push(view.getUint8(off + 2));
    off += TCRH_ENTRY_BYTES;
  }
  const header = makeHeader({ nextHeader, segmentsLeft: sl, flags, numHops: nhops, devHop, epochBase, sidsRev, deltasRev });
  return { header, length: total };
}

/** Parse exactly one T-CRH (raw.length must equal its Hdr Ext Len size). */
export function decode(raw: Uint8Array): TcrhHeader {
  return parse(raw, true).header;
}

/** Parse a T-CRH at the start of raw (a payload may follow). */
export function decodePrefix(raw: Uint8Array): { header: TcrhHeader; length: number } {
  return parse(raw, false);
}

// ----- path-order views and flags -----

export function sidsFwdOf(h: TcrhHeader): number[] {
  return [...h.sidsRev].reverse();
}

export function deltasFwdOf(h: TcrhHeader): number[] {
  return [...h.deltasRev].reverse();
}

export function unitCodeOf(h: TcrhHeader): UnitCode {
  return ((h.flags >> FLAG_UNIT_SHIFT) & 3) as UnitCode;
}

export function unitNsOf(h: TcrhHeader): number {
  return unitNs(unitCodeOf(h));
}

export const isDev = (h: TcrhHeader): boolean => (h.flags & FLAG_DEV) !== 0;
export const isGreedy = (h: TcrhHeader): boolean => (h.flags & FLAG_GREEDY) !== 0;
export const isSat = (h: TcrhHeader): boolean => (h.flags & FLAG_SAT) !== 0;

// ----- deadlines (section 5) -----

/**
 * Cumulative arrival deadline D_k at hop k (1..h), mod 2^32: Epoch_Base + d_1 + ... + d_k.
 * In wire order these are the entries SL..h-1 for SL = h - k.
 */
export function deadline(h: TcrhHeader, k: number): number {
  checkRange('hop index k', k, 1, h.numHops);
  let sum = h.epochBase;
  for (let i = h.numHops - k; i < h.numHops; i += 1) sum += h.deltasRev[i] ?? 0;
  return sum % MOD32;
}

/** (D_1, ..., D_h). */
export function deadlines(h: TcrhHeader): number[] {
  const out: number[] = [];
  let running = h.epochBase;
  for (const d of deltasFwdOf(h)) {
    running = (running + d) % MOD32;
    out.push(running);
  }
  return out;
}

/** k = NumHops - SL: hop index of the node holding the packet on arrival (0 = ingress). */
export function currentHopIndex(h: TcrhHeader): number {
  return h.numHops - h.segmentsLeft;
}

/** D_k for the node holding the packet on arrival; null at the ingress (k = 0). */
export function currentDeadline(h: TcrhHeader): number | null {
  const k = currentHopIndex(h);
  return k >= 1 ? deadline(h, k) : null;
}

// ------------------------------------------------------------------ encoding deltas (5.1)

/** A cumulative budget in nanoseconds: an exact integer, or an exact rational. */
export type Budget = bigint | Ratio;

function asRatio(b: Budget): Ratio {
  if (typeof b === 'bigint') return { num: b, den: 1n };
  if (typeof b === 'object' && b !== null && typeof b.num === 'bigint' && typeof b.den === 'bigint' && b.den > 0n) return b;
  throw new TypeError('budgets must be bigint nanoseconds or an exact Ratio (never a float)');
}

/**
 * Ceil-cumulative delta encoding, exactly as spec section 5.1. Budgets B_1 <= ... <= B_h are
 * the time allowed from ingress to arrival at hop k, in ns. Returns the h one-byte deltas
 * and whether any delta had to be clamped to 255 (SAT).
 */
export function encodeDeltas(cumulativeBudgetsNs: readonly Budget[], unitCode: number): { deltas: number[]; sat: boolean } {
  const u = unitNsBig(unitCode);
  const deltas: number[] = [];
  let sat = false;
  let encoded = 0n; // E: encoded cumulative sum, units
  for (const budget of cumulativeBudgetsNs) {
    const b = asRatio(budget);
    if (b.num < 0n) throw new RangeError('a cumulative budget cannot be negative');
    const target = ratioCeilDiv(b, u); // exact ceil(B_k / u)
    let d = target - encoded;
    if (d > BigInt(MAX_DELTA)) {
      d = BigInt(MAX_DELTA);
      sat = true;
    }
    if (d < 0n) d = 0n; // cannot happen when B is non-decreasing
    encoded += d;
    deltas.push(Number(d));
  }
  return { deltas, sat };
}

/**
 * What the ingress does: stamp Epoch_Base = ceil(T_ingress / u) mod 2^32 for THIS packet,
 * encode the budgets, set SAT if a delta saturated. Returns a fresh header.
 */
export function buildHeader(
  sidsFwd: readonly number[],
  cumulativeBudgetsNs: readonly Budget[],
  tIngressGpsNs: bigint,
  unitCode: number,
  nextHeader: number = DEFAULT_NEXT_HEADER,
): TcrhHeader {
  if (sidsFwd.length !== cumulativeBudgetsNs.length) {
    throw new RangeError('every hop needs exactly one cumulative budget');
  }
  const { deltas, sat } = encodeDeltas(cumulativeBudgetsNs, unitCode);
  const epoch = epochBaseAtIngress(tIngressGpsNs, unitCode);
  return fromForward(sidsFwd, deltas, epoch, unitCode, nextHeader, sat ? FLAG_SAT : 0);
}

// ------------------------------------------------------------------ processing (section 6)

export interface ProcessResult {
  /** deliver | forward | fallback | drop_late | drop_malformed */
  readonly action: Action;
  /** SID to look up in the CRH-FIB (forward) or head for (fallback); null otherwise. */
  readonly nextSid: number | null;
  /** Packet bytes sent on or delivered (mutable fields updated); null when discarded. */
  readonly outBytes: Uint8Array | null;
  /** True only when THIS node's deadline check fired and set DEV. */
  readonly late: boolean;
  /** k = NumHops - SL on arrival (0 at the ingress); null if malformed. */
  readonly hopIndex: number | null;
  /** D_k for this node; null at the ingress or if malformed. */
  readonly deadlineU: number | null;
  /** null; 'late_strict' (drop_late); 'link_down' (step 7); 'wrong_type' (ignore); or the DecodeReason (drop_malformed). */
  readonly reason: string | null;
  /** 0 when an ICMPv6 Parameter Problem should be sent; null otherwise. */
  readonly icmpCode: number | null;
  readonly icmpPointer: number | null;
}

/** Copy the packet and rewrite only the mutable fields (SL, Flags, Dev Hop; section 2). */
function patch(raw: Uint8Array, segmentsLeft: number, flags: number, devHop: number): Uint8Array {
  const out = raw.slice();
  out[OFF_SEGMENTS_LEFT] = segmentsLeft;
  out[OFF_FLAGS] = flags;
  out[OFF_DEV_HOP] = devHop;
  return out;
}

/** Step 1 failed: discard, with ICMPv6 Code 0 when there is a field to point at. */
function malformed(error: TcrhDecodeError): ProcessResult {
  return result({
    action: 'drop_malformed',
    reason: error.reason,
    icmpCode: error.pointer !== null ? 0 : null,
    icmpPointer: error.pointer,
  });
}

function result(fields: Partial<ProcessResult> & { action: Action }): ProcessResult {
  return {
    nextSid: null,
    outBytes: null,
    late: false,
    hopIndex: null,
    deadlineU: null,
    reason: null,
    icmpCode: null,
    icmpPointer: null,
    ...fields,
  };
}

/**
 * Spec section 6, step by step, as a pure function of the packet bytes and the node's unit
 * clock nowU (= clockU(t_gps_ns, unit code)). raw starts with the T-CRH; bytes after the
 * header (the payload) are kept. The CRH-FIB lookup (step 6) is the caller's job.
 */
export function processAtNode(raw: Uint8Array, nowU: number, policy: Policy = 'greedy'): ProcessResult {
  if (!POLICIES.includes(policy)) throw new RangeError(`policy must be one of ${POLICIES.join(', ')}, got ${String(policy)}`);
  checkRange('now_u', nowU, 0, MOD32 - 1);

  // 1. Validate.
  let hdr: TcrhHeader;
  try {
    hdr = parse(raw, false).header;
  } catch (error) {
    if (!(error instanceof TcrhDecodeError)) throw error;
    // 1b. Not a T-CRH: RFC 8200 section 4.4 for an unrecognised Routing Type. With Segments
    // Left 0 the node ignores the header and processes the Next Header (bytes unchanged);
    // otherwise it discards with a Parameter Problem pointing at the Routing Type.
    // (wrong_type implies at least 8 bytes, so byte 3 exists.)
    if (error.reason === 'wrong_type' && raw[OFF_SEGMENTS_LEFT] === 0) {
      return result({ action: 'ignore', outBytes: raw.slice(), reason: error.reason });
    }
    return malformed(error);
  }

  let sl = hdr.segmentsLeft;
  let flags = hdr.flags;
  let devHop = hdr.devHop;
  const k = currentHopIndex(hdr);
  const deadlineU = currentDeadline(hdr); // null when k == 0 (ingress)
  let late = false;

  // 2. Deadline check: only if DEV is clear and this is not the ingress.
  if ((flags & FLAG_DEV) === 0 && sl < hdr.numHops && deadlineU !== null) {
    if (serialDiff(nowU, deadlineU) > 0) {
      late = true;
      flags |= FLAG_DEV;
      devHop = k;
    }
  }

  const common = { late, hopIndex: k, deadlineU };

  // 3. Final segment endpoint: deliver (late or not; DEV records the miss).
  if (sl === 0) {
    return result({ action: 'deliver', outBytes: patch(raw, sl, flags, devHop), ...common });
  }

  // 4. Deviation policy, for a packet found late here or earlier.
  if ((flags & FLAG_DEV) !== 0) {
    if (policy === 'greedy') {
      flags |= FLAG_GREEDY;
      return result({
        action: 'fallback',
        nextSid: hdr.sidsRev[0] ?? null,
        outBytes: patch(raw, 0, flags, devHop),
        ...common,
      });
    }
    if (policy === 'drop') {
      return result({ action: 'drop_late', reason: 'late_strict', ...common });
    }
    // 'continue': keep following the SID list; DEV records the miss.
  }

  // 5. Decrement first, then index.
  sl -= 1;
  const nextSid = hdr.sidsRev[sl] ?? null;
  // 6. (caller) CRH-FIB lookup of nextSid.
  return result({ action: 'forward', nextSid, outBytes: patch(raw, sl, flags, devHop), ...common });
}

/**
 * Section 6 step 7, "next link down", as a pure function of the bytes. raw is the packet as
 * it leaves step 5 (from ingressSend, or the outBytes of a 'forward'), and the node has just
 * found the link to the next SID down. No deadline can show that, so it is a deviation of its
 * own: if DEV is clear, set it with Dev Hop = k (k = NumHops - SL - 1 on these bytes, 0 at the
 * ingress). Then set GREEDY and SL = 0 and head for SID[0], under every policy. Only SL,
 * Flags and Dev Hop change. Returns 'drop_malformed' for bytes that fail step 1; throws
 * RangeError for a packet that cannot be in this state (SL == NumHops, or GREEDY set).
 */
export function linkDownFallback(raw: Uint8Array): ProcessResult {
  let hdr: TcrhHeader;
  try {
    hdr = parse(raw, false).header;
  } catch (error) {
    if (!(error instanceof TcrhDecodeError)) throw error;
    return malformed(error);
  }
  if (hdr.segmentsLeft >= hdr.numHops) {
    throw new RangeError(
      `linkDownFallback needs the bytes as they leave step 5 (SL < NumHops), got SL=${hdr.segmentsLeft} NumHops=${hdr.numHops}`,
    );
  }
  if (isGreedy(hdr)) throw new RangeError('a GREEDY packet is already in fallback mode; it skips dead links itself');
  const k = hdr.numHops - hdr.segmentsLeft - 1;
  let flags = hdr.flags;
  let devHop = hdr.devHop;
  if ((flags & FLAG_DEV) === 0) {
    flags |= FLAG_DEV;
    devHop = k;
  }
  flags |= FLAG_GREEDY;
  return result({
    action: 'fallback',
    nextSid: hdr.sidsRev[0] ?? null,
    outBytes: patch(raw, 0, flags, devHop),
    hopIndex: k,
    reason: 'link_down',
  });
}

/**
 * The ingress node's own forwarding of a header it has just built (section 6, last
 * paragraph): steps 5-6 without a deadline check. raw must start with a fresh T-CRH
 * (SL == Num Hops >= 1). Throws TcrhDecodeError for malformed bytes.
 */
export function ingressSend(raw: Uint8Array): { outBytes: Uint8Array; firstSid: number } {
  const hdr = parse(raw, false).header;
  if (hdr.segmentsLeft !== hdr.numHops) {
    throw new RangeError(
      `ingress expects a fresh header (SL == NumHops >= 1), got SL=${hdr.segmentsLeft} NumHops=${hdr.numHops}`,
    );
  }
  const sl = hdr.segmentsLeft - 1;
  return { outBytes: patch(raw, sl, hdr.flags, hdr.devHop), firstSid: hdr.sidsRev[sl] ?? 0 };
}

// ------------------------------------------------------------------ hex helpers

/** Strict hex -> bytes (whitespace ignored). Throws on odd length or non-hex characters. */
export function hexToBytes(hex: string): Uint8Array {
  const clean = hex.replace(/\s+/g, '');
  if (clean.length % 2 !== 0) throw new SyntaxError('hex text must have an even number of digits');
  if (/[^0-9a-fA-F]/.test(clean)) throw new SyntaxError('hex text may only contain 0-9 and a-f');
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i += 1) out[i] = Number.parseInt(clean.slice(2 * i, 2 * i + 2), 16);
  return out;
}

/** Lowercase hex, no separators (the golden-vector convention) unless one is given. */
export function bytesToHex(bytes: Uint8Array, separator = ''): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(separator);
}

/**
 * The IPv6 Compact Routing Header, CRH-16 and CRH-32 (RFC 9631), which T-CRH extends.
 * Port of sim/chronoroute/proto/crh.py; byte-exact with the ns-3 CrhHeader and checked
 * against spec/golden/crh_vectors.json in golden.test.ts.
 *
 *  +---------------+---------------+---------------+---------------+
 *  |  Next Header  |  Hdr Ext Len  | Routing Type  | Segments Left |   4 fixed bytes
 *  +---------------+---------------+---------------+---------------+
 *  |  SID[0] | SID[1] | ...  (16 bits each for CRH-16, type 5; 32 bits for CRH-32, type 6)
 *  +---------------------------------------------------------------+
 *                 (zero padding to a 64-bit boundary)
 *
 * SIDs are stored in reverse path order. A node decrements Segments Left first, then reads
 * SID[Segments Left]. There is no SID count, so decode returns EVERY SID slot, padding
 * slots included (as ns-3 does); the minimum-length check (RFC 9631 section 5.1) proves the
 * slot a node reads is inside the header.
 */
import { CRH_FIXED_BYTES, pad8 } from './sizes';
import { checkRange } from './timebase';

export const ROUTING_TYPE_CRH16 = 5;
export const ROUTING_TYPE_CRH32 = 6;
export type CrhRoutingType = typeof ROUTING_TYPE_CRH16 | typeof ROUTING_TYPE_CRH32;
export const DEFAULT_NEXT_HEADER = 17;
/** Largest size Hdr Ext Len can describe. */
export const MAX_HEADER_BYTES = (255 + 1) * 8;

export const OFF_HDR_EXT_LEN = 1;
export const OFF_ROUTING_TYPE = 2;
export const OFF_SEGMENTS_LEFT = 3;
export const OFF_SIDS = CRH_FIXED_BYTES; // 4

/** ICMPv6 Parameter Problem codes used by RFC 9631 section 5. */
export const ICMP_CODE_ERRONEOUS_FIELD = 0;
export const ICMP_CODE_MIN_LENGTH = 6;

export function isCrhRoutingType(value: number): value is CrhRoutingType {
  return value === ROUTING_TYPE_CRH16 || value === ROUTING_TYPE_CRH32;
}

/** SID size in bytes: 2 for CRH-16, 4 for CRH-32. */
export function sidBytes(routingType: number): 2 | 4 {
  if (routingType === ROUTING_TYPE_CRH16) return 2;
  if (routingType === ROUTING_TYPE_CRH32) return 4;
  throw new RangeError(`CRH routing type must be 5 (CRH-16) or 6 (CRH-32), got ${routingType}`);
}

export type CrhDecodeReason = 'truncated' | 'wrong_type' | 'trailing_bytes';

export class CrhDecodeError extends Error {
  readonly reason: CrhDecodeReason;
  readonly pointer: number | null;

  constructor(reason: CrhDecodeReason, message: string, pointer: number | null = null) {
    super(message);
    this.name = 'CrhDecodeError';
    this.reason = reason;
    this.pointer = pointer;
  }
}

/**
 * L, the minimum CRH length for this Segments Left, in 8-octet units not counting the first
 * 8 octets (RFC 9631 section 5.1, literally):
 *   CRH-16: SL <= 2 -> 0, else ceil((SL - 2) / 4)
 *   CRH-32: SL <= 1 -> 0, else ceil((SL - 1) / 2)
 */
export function minHdrExtLen(segmentsLeft: number, routingType: number): number {
  checkRange('segments_left', segmentsLeft, 0, 255);
  const [firstWord, perWord] = sidBytes(routingType) === 2 ? [2, 4] : [1, 2];
  if (segmentsLeft <= firstWord) return 0;
  return Math.ceil((segmentsLeft - firstWord) / perWord);
}

/** One CRH as values; sidsRev is in wire order. segmentsLeft may exceed the slots (a forged header). */
export interface CrhHeader {
  readonly routingType: CrhRoutingType;
  readonly nextHeader: number;
  readonly segmentsLeft: number;
  readonly sidsRev: readonly number[];
}

export function crhSizeOf(h: CrhHeader): number {
  return pad8(CRH_FIXED_BYTES + sidBytes(h.routingType) * h.sidsRev.length);
}

export function crhHdrExtLenOf(h: CrhHeader): number {
  return crhSizeOf(h) / 8 - 1;
}

function makeCrh(h: CrhHeader): CrhHeader {
  sidBytes(h.routingType);
  checkRange('next_header', h.nextHeader, 0, 255);
  checkRange('segments_left', h.segmentsLeft, 0, 255);
  const top = h.routingType === ROUTING_TYPE_CRH16 ? 0xffff : 0xffffffff;
  for (const sid of h.sidsRev) checkRange('SID', sid, 0, top);
  const header = Object.freeze({ ...h, sidsRev: Object.freeze([...h.sidsRev]) });
  if (crhSizeOf(header) > MAX_HEADER_BYTES) {
    throw new RangeError(`${h.sidsRev.length} SIDs do not fit in a ${MAX_HEADER_BYTES}-byte header`);
  }
  return header;
}

/** Fresh header from a FORWARD-order path; Segments Left = n (as ns-3 SetPath). */
export function crhFromForward(
  sidsFwd: readonly number[],
  routingType: CrhRoutingType = ROUTING_TYPE_CRH16,
  nextHeader: number = DEFAULT_NEXT_HEADER,
): CrhHeader {
  if (sidsFwd.length < 1 || sidsFwd.length > 255) {
    throw new RangeError(`a CRH path has 1..255 SIDs (Segments Left is one byte), got ${sidsFwd.length}`);
  }
  return makeCrh({ routingType, nextHeader, segmentsLeft: sidsFwd.length, sidsRev: [...sidsFwd].reverse() });
}

export function encodeCrh(h: CrhHeader): Uint8Array {
  const size = crhSizeOf(h);
  const out = new Uint8Array(size);
  const view = new DataView(out.buffer);
  view.setUint8(0, h.nextHeader);
  view.setUint8(OFF_HDR_EXT_LEN, size / 8 - 1);
  view.setUint8(OFF_ROUTING_TYPE, h.routingType);
  view.setUint8(OFF_SEGMENTS_LEFT, h.segmentsLeft);
  const step = sidBytes(h.routingType);
  let off = OFF_SIDS;
  for (const sid of h.sidsRev) {
    if (step === 2) view.setUint16(off, sid, false);
    else view.setUint32(off, sid, false);
    off += step;
  }
  return out;
}

function parseCrh(raw: Uint8Array, exact: boolean): { header: CrhHeader; length: number } {
  if (raw.length < 8) throw new CrhDecodeError('truncated', `a CRH is at least 8 bytes, got ${raw.length}`);
  const view = new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  const nextHeader = view.getUint8(0);
  const hel = view.getUint8(OFF_HDR_EXT_LEN);
  const rtype = view.getUint8(OFF_ROUTING_TYPE);
  const sl = view.getUint8(OFF_SEGMENTS_LEFT);
  if (!isCrhRoutingType(rtype)) {
    throw new CrhDecodeError('wrong_type', `routing type ${rtype} is not CRH-16 (5) or CRH-32 (6)`, OFF_ROUTING_TYPE);
  }
  const total = (hel + 1) * 8;
  if (raw.length < total) {
    throw new CrhDecodeError('truncated', `Hdr Ext Len announces ${total} bytes, only ${raw.length} present`);
  }
  if (exact && raw.length !== total) {
    throw new CrhDecodeError('trailing_bytes', `Hdr Ext Len announces ${total} bytes, got ${raw.length}`);
  }
  const step = sidBytes(rtype);
  const sids: number[] = [];
  for (let off = OFF_SIDS; off < total; off += step) {
    sids.push(step === 2 ? view.getUint16(off, false) : view.getUint32(off, false));
  }
  return { header: makeCrh({ routingType: rtype, nextHeader, segmentsLeft: sl, sidsRev: sids }), length: total };
}

/** Parse exactly one CRH (raw.length must equal its Hdr Ext Len size). */
export function decodeCrh(raw: Uint8Array): CrhHeader {
  return parseCrh(raw, true).header;
}

export function decodeCrhPrefix(raw: Uint8Array): { header: CrhHeader; length: number } {
  return parseCrh(raw, false);
}

export type CrhAction = 'deliver' | 'forward' | 'drop_malformed' | 'ignore';

export interface CrhProcessResult {
  readonly action: CrhAction;
  readonly nextSid: number | null;
  readonly outBytes: Uint8Array | null;
  /** null, or 'wrong_type' / 'truncated' / 'min_length'. */
  readonly reason: string | null;
  readonly icmpCode: number | null;
  readonly icmpPointer: number | null;
}

/**
 * RFC 9631 section 5 forwarding step, as a pure function of the bytes (raw starts with the
 * CRH; a payload may follow):
 *   (not type 5/6: RFC 8200 section 4.4 -> 'ignore' when SL == 0, else Code 0, pointer 2)
 *   0. Segments Left == 0 -> deliver
 *   1. L > Hdr Ext Len    -> discard, ICMPv6 Parameter Problem Code 6, pointer 3
 *   2. decrement Segments Left
 *   3. current SID = SID[Segments Left]   (decrement THEN index)
 *   4. (caller) CRH-FIB lookup
 */
export function crhProcessAtNode(raw: Uint8Array): CrhProcessResult {
  const empty = { nextSid: null, outBytes: null, reason: null, icmpCode: null, icmpPointer: null };
  let hdr: CrhHeader;
  try {
    hdr = parseCrh(raw, false).header;
  } catch (error) {
    if (!(error instanceof CrhDecodeError)) throw error;
    // RFC 8200 section 4.4, unrecognised Routing Type: with Segments Left 0 the node ignores
    // the header and processes the Next Header. (wrong_type implies at least 8 bytes.)
    if (error.reason === 'wrong_type' && raw[OFF_SEGMENTS_LEFT] === 0) {
      return { ...empty, action: 'ignore', outBytes: raw.slice(), reason: error.reason };
    }
    return {
      ...empty,
      action: 'drop_malformed',
      reason: error.reason,
      icmpCode: error.pointer !== null ? ICMP_CODE_ERRONEOUS_FIELD : null,
      icmpPointer: error.pointer,
    };
  }
  if (hdr.segmentsLeft === 0) return { ...empty, action: 'deliver', outBytes: raw.slice() };
  if (minHdrExtLen(hdr.segmentsLeft, hdr.routingType) > crhHdrExtLenOf(hdr)) {
    return {
      ...empty,
      action: 'drop_malformed',
      reason: 'min_length',
      icmpCode: ICMP_CODE_MIN_LENGTH,
      icmpPointer: OFF_SEGMENTS_LEFT,
    };
  }
  const sl = hdr.segmentsLeft - 1;
  const out = raw.slice();
  out[OFF_SEGMENTS_LEFT] = sl;
  return { ...empty, action: 'forward', nextSid: hdr.sidsRev[sl] ?? null, outBytes: out };
}

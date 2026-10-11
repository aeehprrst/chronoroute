/**
 * On-the-wire sizes of T-CRH and the headers it is compared with (spec/tcrh-v1.md
 * sections 2, 8 and 9). Port of sim/chronoroute/proto/sizes.py.
 *
 * Every IPv6 extension header is a whole number of 8-octet units; Hdr Ext Len counts
 * those units NOT including the first 8 octets (RFC 8200 section 4.4):
 *
 *   T-CRH  (this project)       pad8(12 + 3n)   12 fixed bytes, 3 per hop
 *   CRH-16 (RFC 9631, type 5)   pad8(4 + 2n)    4 fixed bytes, 2 per SID
 *   CRH-32 (RFC 9631, type 6)   pad8(4 + 4n)    4 fixed bytes, 4 per SID
 *   SRv6 SRH (RFC 8754)         8 + 16n         a full IPv6 address per segment, no TLVs
 */

export const IPV6_HEADER_BYTES = 40;

export const TCRH_FIXED_BYTES = 12;
export const TCRH_ENTRY_BYTES = 3;
export const TCRH_MAX_HOPS = 255;

export const CRH_FIXED_BYTES = 4;
export const CRH16_SID_BYTES = 2;
export const CRH32_SID_BYTES = 4;

export const SRH_FIXED_BYTES = 8;
export const SRH_SEGMENT_BYTES = 16;

export type OverheadMode = 'source' | 'encap';
export type HeaderKind = 'tcrh' | 'crh16' | 'crh32' | 'srh';

export const MODES: readonly OverheadMode[] = ['source', 'encap'];
export const HEADERS: readonly HeaderKind[] = ['tcrh', 'crh16', 'crh32', 'srh'];

function checkCount(n: number, upper?: number): void {
  if (typeof n !== 'number' || !Number.isSafeInteger(n)) {
    throw new TypeError(`segment count must be an integer, got ${String(n)}`);
  }
  if (n < 0) throw new RangeError(`segment count must be >= 0, got ${n}`);
  if (upper !== undefined && n > upper) throw new RangeError(`segment count must be <= ${upper}, got ${n}`);
}

/** Round a byte count up to the next multiple of 8 (64-bit boundary). */
export function pad8(nbytes: number): number {
  checkCount(nbytes);
  return Math.ceil(nbytes / 8) * 8;
}

/** Hdr Ext Len for an extension header of `sizeBytes` (a multiple of 8, >= 8). */
export function hdrExtLen(sizeBytes: number): number {
  checkCount(sizeBytes);
  if (sizeBytes < 8 || sizeBytes % 8 !== 0) {
    throw new RangeError(`extension header size must be a multiple of 8 and >= 8, got ${sizeBytes}`);
  }
  return sizeBytes / 8 - 1;
}

/** T-CRH with n hops: pad8(12 + 3n). n is limited to 255 by Num Hops. */
export function tcrhSize(n: number): number {
  checkCount(n, TCRH_MAX_HOPS);
  return pad8(TCRH_FIXED_BYTES + TCRH_ENTRY_BYTES * n);
}

/** RFC 9631 CRH-16 with n SIDs: pad8(4 + 2n). */
export function crh16Size(n: number): number {
  checkCount(n);
  return pad8(CRH_FIXED_BYTES + CRH16_SID_BYTES * n);
}

/** RFC 9631 CRH-32 with n SIDs: pad8(4 + 4n). */
export function crh32Size(n: number): number {
  checkCount(n);
  return pad8(CRH_FIXED_BYTES + CRH32_SID_BYTES * n);
}

/** RFC 8754 SRv6 SRH with n segments and no TLVs: 8 + 16n (already 8-aligned). */
export function srhSize(n: number): number {
  checkCount(n);
  return SRH_FIXED_BYTES + SRH_SEGMENT_BYTES * n;
}

const SIZE_FN: Readonly<Record<HeaderKind, (n: number) => number>> = {
  tcrh: tcrhSize,
  crh16: crh16Size,
  crh32: crh32Size,
  srh: srhSize,
};

export function headerSize(header: HeaderKind, n: number): number {
  const fn = SIZE_FN[header];
  if (!fn) throw new RangeError(`header must be one of ${HEADERS.join(', ')}, got ${String(header)}`);
  return fn(n);
}

/**
 * Bytes a routing header adds to each packet (spec section 8).
 *   'source': the sending host inserts the header itself       -> size(n)
 *   'encap' : a gateway adds an outer IPv6 header plus the RH   -> 40 + size(n)
 */
export function encapsulationOverhead(n: number, mode: OverheadMode = 'source', header: HeaderKind = 'tcrh'): number {
  if (!MODES.includes(mode)) throw new RangeError(`mode must be one of ${MODES.join(', ')}, got ${String(mode)}`);
  return headerSize(header, n) + (mode === 'encap' ? IPV6_HEADER_BYTES : 0);
}

/** Display metadata for the comparison headers (spec section 9). */
export const HEADER_INFO: Readonly<Record<HeaderKind, { name: string; source: string; formula: string }>> = {
  tcrh: { name: 'T-CRH', source: 'this project, spec section 2', formula: 'pad8(12 + 3n)' },
  crh16: { name: 'CRH-16', source: 'RFC 9631', formula: 'pad8(4 + 2n)' },
  crh32: { name: 'CRH-32', source: 'RFC 9631', formula: 'pad8(4 + 4n)' },
  srh: { name: 'SRv6 SRH', source: 'RFC 8754, no TLVs', formula: '8 + 16n' },
};

/**
 * Splits T-CRH header bytes into the fields of spec/tcrh-v1.md section 2, for display.
 * This is a layout helper, not the protocol engine: it does not validate deadlines or
 * process packets. It is checked against every golden `encode` vector in tests.
 */

export const TCRH_ROUTING_TYPE = 253;

/** Unit length in nanoseconds for each UNIT code (spec section 3). */
export const UNIT_NS: readonly number[] = [1_000_000, 100_000, 250_000, 125_000];

const NEXT_HEADER_NAMES: Readonly<Record<number, string>> = {
  6: 'TCP',
  17: 'UDP',
  41: 'IPv6',
  59: 'No Next Header',
};

export function nextHeaderName(value: number): string | null {
  return NEXT_HEADER_NAMES[value] ?? null;
}

/** pad8(n) = 8 * ceil(n / 8) */
export function pad8(n: number): number {
  return 8 * Math.ceil(n / 8);
}

/** Header size in bytes for h hops: pad8(12 + 3h) (spec section 2). */
export function tcrhSize(hops: number): number {
  return pad8(12 + 3 * hops);
}

/** Comparison header sizes for n segments (spec section 9). */
export const HEADER_SIZE_FORMULAS: ReadonlyArray<{ name: string; formula: string; size: (n: number) => number }> = [
  { name: 'T-CRH (this project)', formula: 'pad8(12 + 3n)', size: tcrhSize },
  { name: 'CRH-16 (RFC 9631)', formula: 'pad8(4 + 2n)', size: (n) => pad8(4 + 2 * n) },
  { name: 'CRH-32 (RFC 9631)', formula: 'pad8(4 + 4n)', size: (n) => pad8(4 + 4 * n) },
  { name: 'SRv6 SRH (RFC 8754), no TLVs', formula: '8 + 16n', size: (n) => 8 + 16 * n },
];

export function hexToBytes(hex: string): Uint8Array {
  const clean = hex.replace(/\s+/g, '');
  if (clean.length % 2 !== 0 || /[^0-9a-f]/i.test(clean)) throw new Error('Invalid hex string');
  const bytes = new Uint8Array(clean.length / 2);
  for (let i = 0; i < bytes.length; i += 1) bytes[i] = Number.parseInt(clean.slice(2 * i, 2 * i + 2), 16);
  return bytes;
}

export function bytesToHex(bytes: ArrayLike<number>, separator = ' '): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join(separator);
}

export interface TcrhEntry {
  /** Storage index i (entries are stored in reverse path order). */
  index: number;
  offset: number;
  sid: number;
  delta: number;
}

export interface TcrhLayout {
  nextHeader: number;
  hdrExtLen: number;
  routingType: number;
  segmentsLeft: number;
  flags: number;
  numHops: number;
  devHop: number;
  reserved: number;
  epochBase: number;
  /** Stored order: entries[0] is SID[0], the final endpoint. */
  entries: TcrhEntry[];
  /** Offset and length of the zero padding. */
  padding: { offset: number; length: number };
  size: number;
  flagNames: string[];
  unitCode: number;
  unitNs: number;
}

/** Read the fields of a well-formed T-CRH header. Throws on bytes that cannot be one. */
export function readTcrhLayout(bytes: Uint8Array): TcrhLayout {
  if (bytes.length < 12) throw new Error('T-CRH needs at least 12 bytes');
  const at = (i: number): number => {
    const value = bytes[i];
    if (value === undefined) throw new Error(`Byte ${i} is missing`);
    return value;
  };
  const routingType = at(2);
  if (routingType !== TCRH_ROUTING_TYPE) throw new Error(`Routing Type is ${routingType}, not 253`);
  const hdrExtLen = at(1);
  const size = (hdrExtLen + 1) * 8;
  const numHops = at(5);
  const used = 12 + 3 * numHops;
  if (size < pad8(used) || bytes.length < size) throw new Error('Header length does not fit Num Hops');
  const flags = at(4);
  const entries: TcrhEntry[] = [];
  for (let i = 0; i < numHops; i += 1) {
    const offset = 12 + 3 * i;
    entries.push({ index: i, offset, sid: (at(offset) << 8) | at(offset + 1), delta: at(offset + 2) });
  }
  const flagNames: string[] = [];
  if (flags & 0x01) flagNames.push('DEV');
  if (flags & 0x02) flagNames.push('GREEDY');
  if (flags & 0x04) flagNames.push('SAT');
  const unitCode = (flags >> 4) & 3;
  return {
    nextHeader: at(0),
    hdrExtLen,
    routingType,
    segmentsLeft: at(3),
    flags,
    numHops,
    devHop: at(6),
    reserved: at(7),
    // >>> 0 keeps the 32-bit value unsigned.
    epochBase: ((at(8) << 24) | (at(9) << 16) | (at(10) << 8) | at(11)) >>> 0,
    entries,
    padding: { offset: used, length: size - used },
    size,
    flagNames,
    unitCode,
    unitNs: UNIT_NS[unitCode] ?? Number.NaN,
  };
}

/** Path order SIDs s_1..s_h (the reverse of the stored order). */
export function forwardSids(layout: TcrhLayout): number[] {
  return layout.entries.map((entry) => entry.sid).reverse();
}

/** Cumulative arrival deadlines D_1..D_h, mod 2^32 (spec section 5). */
export function deadlines(layout: TcrhLayout): number[] {
  const forwardDeltas = layout.entries.map((entry) => entry.delta).reverse();
  const result: number[] = [];
  let sum = layout.epochBase;
  for (const delta of forwardDeltas) {
    sum = (sum + delta) % 2 ** 32;
    result.push(sum);
  }
  return result;
}

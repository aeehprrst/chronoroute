/**
 * Maps every byte of a T-CRH (and anything after it) to the field it belongs to, with its
 * value and a plain-language meaning. Used by the byte maps on the protocol page. All
 * values come from the engine's decoder; nothing is typed in by hand.
 */
import {
  decodePrefix,
  deadlines,
  isGroundStationSid,
  unitCodeOf,
  FLAG_DEV,
  FLAG_GREEDY,
  FLAG_RESERVED_MASK,
  FLAG_SAT,
  ROUTING_TYPE_TCRH,
  SID_GROUND_BASE,
  SID_RESERVED,
  TcrhDecodeError,
  type TcrhHeader,
} from '../../engine/tcrh';
import { tcrhSize } from '../../engine/sizes';
import { UNIT_NS } from '../../engine/timebase';

export type ByteKind = 'fixed' | 'time' | 'sid' | 'pad' | 'extra' | 'unknown';

export interface ByteInfo {
  index: number;
  value: number;
  /** Field name, e.g. "Segments Left" or "SID[0]". */
  field: string;
  /** Bytes of one field share a group (highlighted together). */
  group: string;
  kind: ByteKind;
  /** Inclusive byte range of the field. */
  first: number;
  last: number;
  /** Changes in flight (Segments Left, Flags, Dev Hop). */
  mutable: boolean;
  valueText: string;
  meaning: string;
}

export interface ByteDescription {
  infos: ByteInfo[];
  header: TcrhHeader | null;
  /** Header length announced by Hdr Ext Len, when the header parsed. */
  headerLength: number | null;
  error: TcrhDecodeError | null;
}

export const NEXT_HEADER_NAMES: Readonly<Record<number, string>> = {
  6: 'TCP',
  17: 'UDP',
  41: 'IPv6 (encapsulation)',
  59: 'No Next Header',
};

export function unitLabel(unitCode: number): string {
  const ns = UNIT_NS[unitCode as 0 | 1 | 2 | 3];
  return ns === undefined ? '?' : `${ns / 1_000_000} ms`;
}

export function flagNames(flags: number): string[] {
  const names: string[] = [];
  if (flags & FLAG_DEV) names.push('DEV');
  if (flags & FLAG_GREEDY) names.push('GREEDY');
  if (flags & FLAG_SAT) names.push('SAT');
  return names;
}

export function sidKind(sid: number): string {
  if (sid === SID_RESERVED) return 'reserved value';
  if (isGroundStationSid(sid)) return `ground station ${sid - SID_GROUND_BASE}`;
  return 'satellite';
}

export const hex2 = (v: number): string => v.toString(16).padStart(2, '0');

/** "Epoch_Base + d_1" (k = 1), "Epoch_Base + d_1 + d_2" (k = 2), "Epoch_Base + d_1 + … + d_k" (k >= 3). */
export function deadlineSumText(k: number): string {
  if (k <= 1) return 'Epoch_Base + d_1';
  if (k === 2) return 'Epoch_Base + d_1 + d_2';
  return `Epoch_Base + d_1 + … + d_${k}`;
}

function flagsMeaning(flags: number): string {
  const parts: string[] = [];
  if (flags & FLAG_DEV) parts.push('DEV: a node found the packet late');
  if (flags & FLAG_GREEDY) parts.push('GREEDY: forwarded by the geographic fallback');
  if (flags & FLAG_SAT) parts.push('SAT: a delta was clamped to 255 when the header was built');
  if (parts.length === 0) parts.push('no state flags set');
  const uc = (flags >> 4) & 3;
  parts.push(`deadline unit code ${uc} = ${unitLabel(uc)}`);
  if (flags & FLAG_RESERVED_MASK) parts.push('reserved bits set (ignored on receipt)');
  return `${parts.join('; ')}. Mutable: DEV and GREEDY are set in flight.`;
}

/** Describe the fixed part by position only (used when the header does not parse). */
function positional(bytes: Uint8Array, reason: string): ByteInfo[] {
  const names = ['Next Header', 'Hdr Ext Len', 'Routing Type', 'Segments Left', 'Flags', 'Num Hops', 'Dev Hop', 'Reserved'];
  return Array.from(bytes, (value, index) => {
    const name = names[index];
    if (name !== undefined) {
      return {
        index,
        value,
        field: name,
        group: `f${index}`,
        kind: 'fixed' as const,
        first: index,
        last: index,
        mutable: index === 3 || index === 4 || index === 6,
        valueText: String(value),
        meaning: `${name} would be here in a T-CRH, but these bytes do not parse: ${reason}`,
      };
    }
    return {
      index,
      value,
      field: 'Unparsed',
      group: 'unparsed',
      kind: 'unknown' as const,
      first: 8,
      last: bytes.length - 1,
      mutable: false,
      valueText: `0x${hex2(value)}`,
      meaning: `Not interpreted: ${reason}`,
    };
  });
}

export function describeTcrhBytes(bytes: Uint8Array): ByteDescription {
  let parsed: { header: TcrhHeader; length: number };
  try {
    parsed = decodePrefix(bytes);
  } catch (error) {
    if (error instanceof TcrhDecodeError) {
      return { infos: positional(bytes, error.message), header: null, headerLength: null, error };
    }
    throw error;
  }
  const { header: h, length } = parsed;
  const infos: ByteInfo[] = [];
  const put = (
    first: number,
    last: number,
    field: string,
    group: string,
    kind: ByteKind,
    valueText: string,
    meaning: string,
    mutable = false,
  ) => {
    for (let i = first; i <= last && i < bytes.length; i += 1) {
      infos[i] = { index: i, value: bytes[i] ?? 0, field, group, kind, first, last, mutable, valueText, meaning };
    }
  };

  const nh = NEXT_HEADER_NAMES[h.nextHeader];
  put(0, 0, 'Next Header', 'nh', 'fixed', `${h.nextHeader}${nh ? ` (${nh})` : ''}`, 'The protocol of the header that follows the T-CRH.');
  put(1, 1, 'Hdr Ext Len', 'hel', 'fixed', String(length / 8 - 1), `Header length in 8-byte units after the first 8: (${length / 8 - 1} + 1) × 8 = ${length} bytes.`);
  put(2, 2, 'Routing Type', 'rt', 'fixed', String(ROUTING_TYPE_TCRH), 'Marks the routing header as a T-CRH (253 is an RFC 4727 experimental value).');
  const sl = h.segmentsLeft;
  const slMeaning =
    sl === h.numHops
      ? 'Equal to Num Hops: a fresh header at the ingress, before its first step.'
      : `The packet is addressed to SID[${sl}], hop ${h.numHops - sl} of ${h.numHops}.`;
  put(3, 3, 'Segments Left', 'sl', 'fixed', String(sl), `Entries not yet visited. ${slMeaning} Mutable: each node decrements it.`, true);
  const names = flagNames(h.flags);
  put(4, 4, 'Flags', 'flags', 'fixed', `0x${hex2(h.flags)}${names.length ? ` (${names.join(', ')})` : ''}`, flagsMeaning(h.flags), true);
  put(5, 5, 'Num Hops', 'nhops', 'fixed', String(h.numHops), `The path has ${h.numHops} ${h.numHops === 1 ? 'entry' : 'entries'}; a parser stops reading there, before the padding.`);
  put(6, 6, 'Dev Hop', 'devhop', 'fixed', String(h.devHop), h.devHop === 0 ? 'No node has found the packet late. Mutable.' : `The packet was first found late at hop ${h.devHop}. Mutable.`, true);
  const rsvd = bytes[7] ?? 0;
  put(7, 7, 'Reserved', 'rsvd', 'fixed', String(rsvd), rsvd === 0 ? 'Zero on transmit, ignored on receipt.' : 'Should be zero on transmit; receivers ignore it.');
  const uc = unitCodeOf(h);
  put(8, 11, 'Epoch_Base', 'epoch', 'time', `${h.epochBase} units`, `Ingress time stamp in units of ${unitLabel(uc)}: ceil(T_ingress / u) mod 2^32. Every deadline counts from here.`);

  const ds = deadlines(h);
  for (let i = 0; i < h.numHops; i += 1) {
    const off = 12 + 3 * i;
    const k = h.numHops - i; // hop this entry belongs to
    const sid = h.sidsRev[i] ?? 0;
    const role = i === 0 ? ' (final endpoint)' : i === h.numHops - 1 ? ' (first hop)' : '';
    put(off, off + 1, `SID[${i}]`, `sid${i}`, 'sid', `${sid} (0x${sid.toString(16).padStart(4, '0')})`, `Segment identifier of hop ${k} of ${h.numHops}${role}: ${sidKind(sid)}. Stored in reverse path order.`);
    const d = h.deltasRev[i] ?? 0;
    put(off + 2, off + 2, `Delta[${i}]`, `delta${i}`, 'time', `${d} units`, `d_${k}: the budget for reaching hop ${k} from ${k === 1 ? 'the ingress' : `hop ${k - 1}`}. Deadline D_${k} = ${deadlineSumText(k)} = ${ds[k - 1] ?? ''} (mod 2^32).`);
  }
  const used = 12 + 3 * h.numHops;
  const need = tcrhSize(h.numHops);
  if (used < need) {
    const nonzero = Array.from(bytes.subarray(used, need)).some((b) => b !== 0);
    put(used, need - 1, 'Padding', 'pad', 'pad', `${need - used} B`, nonzero ? 'Padding to a multiple of 8 bytes. Not zero here; receivers ignore it.' : 'Zero padding to a multiple of 8 bytes.');
  }
  if (length > need) {
    put(need, length - 1, 'Extra header space', 'pad2', 'pad', `${length - need} B`, 'Hdr Ext Len announces more bytes than the entries need. Accepted and ignored.');
  }
  if (bytes.length > length) {
    put(length, bytes.length - 1, 'After the header', 'payload', 'extra', `${bytes.length - length} B`, 'Not part of the T-CRH: the payload (the header named by Next Header). Passed through unchanged.');
  }
  return { infos, header: h, headerLength: length, error: null };
}

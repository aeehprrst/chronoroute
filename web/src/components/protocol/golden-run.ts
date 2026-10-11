/**
 * Runs the shared golden test vectors (spec/golden/tcrh_vectors.json and crh_vectors.json)
 * through the TypeScript engine and reports, per vector, which expectations held.
 *
 * Used twice: by the protocol page at BUILD time (so the "N/N vectors pass" figure is
 * computed, never typed in) and by src/engine/golden.test.ts. Pure: no file access here;
 * the caller passes the parsed JSON.
 */
import {
  buildHeader,
  bytesToHex,
  decode,
  deadlines,
  deltasFwdOf,
  encode,
  encodeDeltas,
  fromForward,
  hexToBytes,
  ingressSend,
  isSat,
  processAtNode,
  linkDownFallback,
  sidsFwdOf,
  sizeOf,
  FLAG_SAT,
  type Policy,
} from '../../engine/tcrh';
import { crhFromForward, crhHdrExtLenOf, crhProcessAtNode, crhSizeOf, decodeCrh, encodeCrh, isCrhRoutingType } from '../../engine/crh';
import { epochBaseAtIngress } from '../../engine/timebase';

export type VectorGroup = 'tcrh-encode' | 'tcrh-process' | 'tcrh-link-down' | 'crh-encode' | 'crh-process';

export const GROUP_LABELS: Readonly<Record<VectorGroup, string>> = {
  'tcrh-encode': 'T-CRH encoding',
  'tcrh-process': 'T-CRH processing at a node',
  'tcrh-link-down': 'T-CRH next link down',
  'crh-encode': 'CRH-16/32 encoding (RFC 9631)',
  'crh-process': 'CRH-16/32 processing (RFC 9631)',
};

export interface VectorOutcome {
  group: VectorGroup;
  name: string;
  note: string;
  /** Expectations that did not hold (empty when the vector passes). */
  failures: string[];
}

export interface GoldenReport {
  outcomes: VectorOutcome[];
  passed: number;
  total: number;
  byGroup: Record<VectorGroup, { passed: number; total: number }>;
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function list(file: unknown, key: string, fileName: string): Json[] {
  if (!isObject(file) || !Array.isArray(file[key])) throw new Error(`${fileName}: missing "${key}" array`);
  return (file[key] as unknown[]).filter(isObject);
}

const num = (v: Json, key: string): number => {
  const value = v[key];
  if (typeof value !== 'number') throw new Error(`"${key}" is not a number`);
  return value;
};
const nums = (v: Json, key: string): number[] => {
  const value = v[key];
  if (!Array.isArray(value) || !value.every((x) => typeof x === 'number')) throw new Error(`"${key}" is not a number list`);
  return value as number[];
};
const text = (v: Json, key: string): string => {
  const value = v[key];
  if (typeof value !== 'string') throw new Error(`"${key}" is not a string`);
  return value;
};
const nullableNum = (v: Json, key: string): number | null => (v[key] === null ? null : num(v, key));
const nullableText = (v: Json, key: string): string | null => (v[key] === null ? null : text(v, key));

function same(failures: string[], what: string, got: unknown, want: unknown): void {
  const a = JSON.stringify(got);
  const b = JSON.stringify(want);
  if (a !== b) failures.push(`${what}: got ${a}, expected ${b}`);
}

/** Run one check function, turning a thrown error into a failure. */
function run(group: VectorGroup, v: Json, check: (failures: string[]) => void): VectorOutcome {
  const failures: string[] = [];
  const name = typeof v['name'] === 'string' ? v['name'] : '(unnamed)';
  const note = typeof v['note'] === 'string' ? v['note'] : '';
  try {
    check(failures);
  } catch (error) {
    failures.push(`threw: ${error instanceof Error ? error.message : String(error)}`);
  }
  return { group, name, note, failures };
}

/** T-CRH `encode` vector: build, compare bytes and intermediates, decode back, ingress step. */
export function checkTcrhEncode(v: Json): VectorOutcome {
  return run('tcrh-encode', v, (f) => {
    const uc = num(v, 'unit_code');
    const sids = nums(v, 'sids_fwd');
    const epoch = 'epoch_base' in v ? num(v, 'epoch_base') : epochBaseAtIngress(BigInt(text(v, 't_ingress_gps_ns')), uc);
    let deltas: number[];
    let sat = false;
    if ('deltas_fwd' in v) {
      deltas = nums(v, 'deltas_fwd');
    } else {
      const encoded = encodeDeltas(
        nums(v, 'cumulative_budgets_ns').map((b) => BigInt(b)),
        uc,
      );
      deltas = encoded.deltas;
      sat = encoded.sat;
    }
    const header = fromForward(sids, deltas, epoch, uc, num(v, 'next_header'), num(v, 'flags') | (sat ? FLAG_SAT : 0));
    const bytes = encode(header);
    same(f, 'encoded hex', bytesToHex(bytes), text(v, 'expect_hex'));
    same(f, 'Epoch_Base', epoch, num(v, 'expect_epoch_base'));
    same(f, 'deltas', deltas, nums(v, 'expect_deltas_fwd'));
    same(f, 'Flags byte', header.flags, num(v, 'expect_flags'));
    same(f, 'SAT', isSat(header), v['expect_sat']);
    same(f, 'size', sizeOf(header), num(v, 'expect_size'));
    same(f, 'deadlines', deadlines(header), nums(v, 'expect_deadlines_u'));

    // buildHeader (the ingress API) must agree whenever the vector is stated that way.
    if ('t_ingress_gps_ns' in v && 'cumulative_budgets_ns' in v && num(v, 'flags') === 0) {
      const built = buildHeader(
        sids,
        nums(v, 'cumulative_budgets_ns').map((b) => BigInt(b)),
        BigInt(text(v, 't_ingress_gps_ns')),
        uc,
        num(v, 'next_header'),
      );
      same(f, 'buildHeader hex', bytesToHex(encode(built)), text(v, 'expect_hex'));
    }

    // Decoders must recover the path and every deadline from expect_hex.
    const decoded = decode(hexToBytes(text(v, 'expect_hex')));
    same(f, 'decoded SIDs', sidsFwdOf(decoded), sids);
    same(f, 'decoded deltas', deltasFwdOf(decoded), nums(v, 'expect_deltas_fwd'));
    same(f, 'decoded deadlines', deadlines(decoded), nums(v, 'expect_deadlines_u'));
    same(f, 're-encoded hex', bytesToHex(encode(decoded)), text(v, 'expect_hex'));

    // The ingress forwards to s_1 with SL = h - 1 (no deadline check).
    const sent = ingressSend(hexToBytes(text(v, 'expect_hex')));
    same(f, 'ingress first SID', sent.firstSid, sids[0]);
    same(f, 'ingress Segments Left', sent.outBytes[3], sids.length - 1);
  });
}

/** T-CRH `process` vector: one node's processing step. */
export function checkTcrhProcess(v: Json): VectorOutcome {
  return run('tcrh-process', v, (f) => {
    const res = processAtNode(hexToBytes(text(v, 'hex_in')), num(v, 'now_u'), text(v, 'policy') as Policy);
    same(f, 'action', res.action, text(v, 'expect_action'));
    same(f, 'next SID', res.nextSid, nullableNum(v, 'expect_next_sid'));
    same(f, 'hex out', res.outBytes ? bytesToHex(res.outBytes) : null, nullableText(v, 'expect_hex_out'));
    same(f, 'late', res.late, v['expect_late']);
    same(f, 'hop index', res.hopIndex, nullableNum(v, 'expect_hop_index'));
    same(f, 'deadline', res.deadlineU, nullableNum(v, 'expect_deadline_u'));
    same(f, 'reason', res.reason, nullableText(v, 'expect_reason'));
    if ('expect_icmp_code' in v) same(f, 'ICMP code', res.icmpCode, nullableNum(v, 'expect_icmp_code'));
    if ('expect_icmp_pointer' in v) same(f, 'ICMP pointer', res.icmpPointer, nullableNum(v, 'expect_icmp_pointer'));
  });
}

/** T-CRH `link_down` vector: spec section 6 step 7 on bytes as they leave step 5. */
export function checkTcrhLinkDown(v: Json): VectorOutcome {
  return run('tcrh-link-down', v, (f) => {
    const res = linkDownFallback(hexToBytes(text(v, 'hex_in')));
    same(f, 'action', res.action, text(v, 'expect_action'));
    same(f, 'next SID', res.nextSid, nullableNum(v, 'expect_next_sid'));
    same(f, 'hex out', res.outBytes ? bytesToHex(res.outBytes) : null, nullableText(v, 'expect_hex_out'));
    same(f, 'hop index', res.hopIndex, nullableNum(v, 'expect_hop_index'));
    same(f, 'reason', res.reason, nullableText(v, 'expect_reason'));
    same(f, 'ICMP code', res.icmpCode, nullableNum(v, 'expect_icmp_code'));
    same(f, 'ICMP pointer', res.icmpPointer, nullableNum(v, 'expect_icmp_pointer'));
  });
}

/** CRH `encode` vector (RFC 9631 baseline). */
export function checkCrhEncode(v: Json): VectorOutcome {
  return run('crh-encode', v, (f) => {
    const rtype = num(v, 'routing_type');
    if (!isCrhRoutingType(rtype)) throw new Error(`routing_type ${rtype} is not 5 or 6`);
    const header = crhFromForward(nums(v, 'sids_fwd'), rtype, num(v, 'next_header'));
    same(f, 'encoded hex', bytesToHex(encodeCrh(header)), text(v, 'expect_hex'));
    same(f, 'size', crhSizeOf(header), num(v, 'expect_size'));
    same(f, 'Hdr Ext Len', crhHdrExtLenOf(header), num(v, 'expect_hdr_ext_len'));
    same(f, 'decoded SID slots', decodeCrh(hexToBytes(text(v, 'expect_hex'))).sidsRev, nums(v, 'expect_decoded_sids_rev'));
  });
}

/** CRH `process` vector. */
export function checkCrhProcess(v: Json): VectorOutcome {
  return run('crh-process', v, (f) => {
    const res = crhProcessAtNode(hexToBytes(text(v, 'hex_in')));
    same(f, 'action', res.action, text(v, 'expect_action'));
    same(f, 'next SID', res.nextSid, nullableNum(v, 'expect_next_sid'));
    same(f, 'hex out', res.outBytes ? bytesToHex(res.outBytes) : null, nullableText(v, 'expect_hex_out'));
    same(f, 'reason', res.reason, nullableText(v, 'expect_reason'));
    same(f, 'ICMP code', res.icmpCode, nullableNum(v, 'expect_icmp_code'));
    same(f, 'ICMP pointer', res.icmpPointer, nullableNum(v, 'expect_icmp_pointer'));
  });
}

/** Run every vector in both files. Throws only if a file is not shaped like a vector file. */
export function runGoldenVectors(tcrhFile: unknown, crhFile: unknown): GoldenReport {
  const outcomes: VectorOutcome[] = [
    ...list(tcrhFile, 'encode', 'tcrh_vectors.json').map(checkTcrhEncode),
    ...list(tcrhFile, 'process', 'tcrh_vectors.json').map(checkTcrhProcess),
    // link_down was added in spec 1.0.1; older vector files do not have it.
    ...(isObject(tcrhFile) && 'link_down' in tcrhFile ? list(tcrhFile, 'link_down', 'tcrh_vectors.json') : []).map(
      checkTcrhLinkDown,
    ),
    ...list(crhFile, 'encode', 'crh_vectors.json').map(checkCrhEncode),
    ...list(crhFile, 'process', 'crh_vectors.json').map(checkCrhProcess),
  ];
  const groups: VectorGroup[] = ['tcrh-encode', 'tcrh-process', 'tcrh-link-down', 'crh-encode', 'crh-process'];
  const byGroup = Object.fromEntries(
    groups.map((g) => {
      const inGroup = outcomes.filter((o) => o.group === g);
      return [g, { passed: inGroup.filter((o) => o.failures.length === 0).length, total: inGroup.length }];
    }),
  ) as Record<VectorGroup, { passed: number; total: number }>;
  const passed = outcomes.filter((o) => o.failures.length === 0).length;
  return { outcomes, passed, total: outcomes.length, byGroup };
}

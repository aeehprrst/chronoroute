/**
 * Every shared golden vector (../spec/golden/*.json, read-only) must pass, field by field.
 * The same files are checked by the Python reference and the ns-3 module.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
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
  linkDownFallback,
  processAtNode,
  sidsFwdOf,
  sizeOf,
  FLAG_SAT,
  type Policy,
} from './tcrh';
import { crhFromForward, crhHdrExtLenOf, crhProcessAtNode, crhSizeOf, decodeCrh, encodeCrh, type CrhRoutingType } from './crh';
import { epochBaseAtIngress, utcIsoToGpsNs } from './timebase';
import { runGoldenVectors } from '../components/protocol/golden-run';

const GOLDEN = path.resolve(import.meta.dirname, '..', '..', '..', 'spec', 'golden');
const tcrhFile = JSON.parse(readFileSync(path.join(GOLDEN, 'tcrh_vectors.json'), 'utf8')) as {
  spec: string;
  encode: Array<Record<string, unknown>>;
  process: Array<Record<string, unknown>>;
  link_down: Array<Record<string, unknown>>;
};
const crhFile = JSON.parse(readFileSync(path.join(GOLDEN, 'crh_vectors.json'), 'utf8')) as {
  spec: string;
  encode: Array<Record<string, unknown>>;
  process: Array<Record<string, unknown>>;
};

interface EncodeVector {
  name: string;
  sids_fwd: number[];
  deltas_fwd?: number[];
  cumulative_budgets_ns?: number[];
  epoch_base?: number;
  t_ingress_gps_ns?: string;
  unit_code: number;
  next_header: number;
  flags: number;
  expect_hex: string;
  expect_deadlines_u: number[];
  expect_sat: boolean;
  expect_epoch_base: number;
  expect_deltas_fwd: number[];
  expect_flags: number;
  expect_size: number;
}

interface ProcessVector {
  name: string;
  hex_in: string;
  now_u: number;
  policy: Policy;
  expect_action: string;
  expect_next_sid: number | null;
  expect_hex_out: string | null;
  expect_late: boolean;
  expect_hop_index: number | null;
  expect_deadline_u: number | null;
  expect_reason: string | null;
  expect_icmp_code: number | null;
  expect_icmp_pointer: number | null;
}

interface LinkDownVector {
  name: string;
  hex_in: string;
  expect_action: string;
  expect_next_sid: number | null;
  expect_hex_out: string | null;
  expect_hop_index: number | null;
  expect_reason: string | null;
  expect_icmp_code: number | null;
  expect_icmp_pointer: number | null;
}

interface CrhEncodeVector {
  name: string;
  routing_type: CrhRoutingType;
  sids_fwd: number[];
  next_header: number;
  expect_hex: string;
  expect_size: number;
  expect_hdr_ext_len: number;
  expect_decoded_sids_rev: number[];
}

interface CrhProcessVector {
  name: string;
  hex_in: string;
  expect_action: string;
  expect_next_sid: number | null;
  expect_hex_out: string | null;
  expect_reason: string | null;
  expect_icmp_code: number | null;
  expect_icmp_pointer: number | null;
}

const tcrhEncode = tcrhFile.encode as unknown as EncodeVector[];
const tcrhProcess = tcrhFile.process as unknown as ProcessVector[];
const tcrhLinkDown = tcrhFile.link_down as unknown as LinkDownVector[];
const crhEncode = crhFile.encode as unknown as CrhEncodeVector[];
const crhProcess = crhFile.process as unknown as CrhProcessVector[];

describe('vector files', () => {
  it('are the expected specs and are not empty', () => {
    expect(tcrhFile.spec).toBe('tcrh-v1');
    expect(crhFile.spec).toBe('rfc9631');
    expect(tcrhEncode.length).toBeGreaterThan(0);
    expect(tcrhProcess.length).toBeGreaterThan(0);
    expect(tcrhLinkDown.length).toBeGreaterThan(0);
    expect(crhEncode.length).toBeGreaterThan(0);
    expect(crhProcess.length).toBeGreaterThan(0);
  });

  it('have unique names', () => {
    for (const group of [tcrhEncode, tcrhProcess, tcrhLinkDown, crhEncode, crhProcess]) {
      const names = group.map((v) => v.name);
      expect(new Set(names).size).toBe(names.length);
    }
  });
});

describe('T-CRH encode vectors', () => {
  it.each(tcrhEncode.map((v) => [v.name, v] as const))('%s', (_name, v) => {
    const epoch =
      v.epoch_base !== undefined ? v.epoch_base : epochBaseAtIngress(BigInt(v.t_ingress_gps_ns ?? 'x'), v.unit_code);
    let deltas: number[];
    let sat = false;
    if (v.deltas_fwd) {
      deltas = v.deltas_fwd;
    } else {
      const enc = encodeDeltas((v.cumulative_budgets_ns ?? []).map((b) => BigInt(b)), v.unit_code);
      deltas = enc.deltas;
      sat = enc.sat;
    }
    const header = fromForward(v.sids_fwd, deltas, epoch, v.unit_code, v.next_header, v.flags | (sat ? FLAG_SAT : 0));
    expect(bytesToHex(encode(header))).toBe(v.expect_hex);
    expect(epoch).toBe(v.expect_epoch_base);
    expect(deltas).toEqual(v.expect_deltas_fwd);
    expect(header.flags).toBe(v.expect_flags);
    expect(isSat(header)).toBe(v.expect_sat);
    expect(sizeOf(header)).toBe(v.expect_size);
    expect(deadlines(header)).toEqual(v.expect_deadlines_u);

    if (v.t_ingress_gps_ns !== undefined && v.cumulative_budgets_ns !== undefined && v.flags === 0) {
      const built = buildHeader(
        v.sids_fwd,
        v.cumulative_budgets_ns.map((b) => BigInt(b)),
        BigInt(v.t_ingress_gps_ns),
        v.unit_code,
        v.next_header,
      );
      expect(bytesToHex(encode(built))).toBe(v.expect_hex);
    }
  });

  it.each(tcrhEncode.map((v) => [v.name, v] as const))('%s decodes back', (_name, v) => {
    const decoded = decode(hexToBytes(v.expect_hex));
    expect(sidsFwdOf(decoded)).toEqual(v.sids_fwd);
    expect(deltasFwdOf(decoded)).toEqual(v.expect_deltas_fwd);
    expect(deadlines(decoded)).toEqual(v.expect_deadlines_u);
    expect(decoded.segmentsLeft).toBe(v.sids_fwd.length);
    expect(decoded.devHop).toBe(0);
    expect(bytesToHex(encode(decoded))).toBe(v.expect_hex);
  });

  it.each(tcrhEncode.map((v) => [v.name, v] as const))('%s: ingress forwards to the first hop', (_name, v) => {
    const sent = ingressSend(hexToBytes(v.expect_hex));
    expect(sent.firstSid).toBe(v.sids_fwd[0]);
    expect(sent.outBytes[3]).toBe(v.sids_fwd.length - 1);
    // Only Segments Left changes.
    const before = hexToBytes(v.expect_hex);
    sent.outBytes.forEach((b, i) => {
      if (i !== 3) expect(b).toBe(before[i]);
    });
  });
});

describe('T-CRH process vectors', () => {
  it.each(tcrhProcess.map((v) => [v.name, v] as const))('%s', (_name, v) => {
    const res = processAtNode(hexToBytes(v.hex_in), v.now_u, v.policy);
    expect(res.action).toBe(v.expect_action);
    expect(res.nextSid).toBe(v.expect_next_sid);
    expect(res.outBytes ? bytesToHex(res.outBytes) : null).toBe(v.expect_hex_out);
    expect(res.late).toBe(v.expect_late);
    expect(res.hopIndex).toBe(v.expect_hop_index);
    expect(res.deadlineU).toBe(v.expect_deadline_u);
    expect(res.reason).toBe(v.expect_reason);
    expect(res.icmpCode).toBe(v.expect_icmp_code);
    expect(res.icmpPointer).toBe(v.expect_icmp_pointer);
  });
});

describe('T-CRH link_down vectors (spec 6 step 7)', () => {
  it.each(tcrhLinkDown.map((v) => [v.name, v] as const))('%s', (_name, v) => {
    const res = linkDownFallback(hexToBytes(v.hex_in));
    expect(res.action).toBe(v.expect_action);
    expect(res.nextSid).toBe(v.expect_next_sid);
    expect(res.outBytes ? bytesToHex(res.outBytes) : null).toBe(v.expect_hex_out);
    expect(res.hopIndex).toBe(v.expect_hop_index);
    expect(res.reason).toBe(v.expect_reason);
    expect(res.icmpCode).toBe(v.expect_icmp_code);
    expect(res.icmpPointer).toBe(v.expect_icmp_pointer);
  });

  it('refuses packets that cannot be in that state', () => {
    const fresh = hexToBytes(tcrhEncode[0]?.expect_hex ?? '');
    expect(() => linkDownFallback(fresh)).toThrow(RangeError); // SL == NumHops: step 5 not done
    const lateByOne = ((deadlines(decode(fresh))[0] ?? 0) + 1) % 2 ** 32;
    const greedy = processAtNode(ingressSend(fresh).outBytes, lateByOne, 'greedy');
    expect(greedy.action).toBe('fallback');
    expect(() => linkDownFallback(greedy.outBytes ?? new Uint8Array())).toThrow(RangeError);
  });
});

describe('CRH (RFC 9631) vectors', () => {
  it.each(crhEncode.map((v) => [v.name, v] as const))('encode %s', (_name, v) => {
    const header = crhFromForward(v.sids_fwd, v.routing_type, v.next_header);
    expect(bytesToHex(encodeCrh(header))).toBe(v.expect_hex);
    expect(crhSizeOf(header)).toBe(v.expect_size);
    expect(crhHdrExtLenOf(header)).toBe(v.expect_hdr_ext_len);
    expect([...decodeCrh(hexToBytes(v.expect_hex)).sidsRev]).toEqual(v.expect_decoded_sids_rev);
  });

  it.each(crhProcess.map((v) => [v.name, v] as const))('process %s', (_name, v) => {
    const res = crhProcessAtNode(hexToBytes(v.hex_in));
    expect(res.action).toBe(v.expect_action);
    expect(res.nextSid).toBe(v.expect_next_sid);
    expect(res.outBytes ? bytesToHex(res.outBytes) : null).toBe(v.expect_hex_out);
    expect(res.reason).toBe(v.expect_reason);
    expect(res.icmpCode).toBe(v.expect_icmp_code);
    expect(res.icmpPointer).toBe(v.expect_icmp_pointer);
  });
});

describe('build-time runner used by the protocol page', () => {
  it('reports every vector as passing', () => {
    const report = runGoldenVectors(tcrhFile, crhFile);
    const failing = report.outcomes.filter((o) => o.failures.length > 0);
    expect(failing).toEqual([]);
    expect(report.total).toBe(tcrhEncode.length + tcrhProcess.length + tcrhLinkDown.length + crhEncode.length + crhProcess.length);
    expect(report.passed).toBe(report.total);
  });

  it('detects a wrong expectation (the runner is not vacuous)', () => {
    const first = tcrhFile.encode[0] ?? {};
    const broken = { ...tcrhFile, encode: [{ ...first, expect_hex: '00' }] };
    const report = runGoldenVectors(broken, { encode: [], process: [] });
    expect(report.total).toBe(1 + tcrhProcess.length + tcrhLinkDown.length);
    expect(report.passed).toBe(tcrhProcess.length + tcrhLinkDown.length);
  });
});

describe('the GPS time stated in a vector note', () => {
  it('h10-real-gps-time-uc1: 2026-10-10T13:58:00.123456Z is the vector ingress time', () => {
    const v = tcrhEncode.find((x) => x.name === 'h10-real-gps-time-uc1');
    expect(v?.t_ingress_gps_ns).toBe(utcIsoToGpsNs('2026-10-10T13:58:00.123456Z').toString());
  });
});

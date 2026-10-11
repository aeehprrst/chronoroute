/**
 * Pure logic of the header builder: text inputs -> a T-CRH, with every intermediate value
 * and plain-language validation errors. All arithmetic is exact (decimal text is parsed
 * into rationals; nanoseconds are bigint), so the result is the engine's real output.
 */
import { buildHeader, bytesToHex, deadlines, encode, encodeDeltas, isSat, MAX_HOPS, SID_RESERVED, type TcrhHeader } from '../../engine/tcrh';
import {
  NS_PER_MS,
  epochBaseAtIngress,
  formatRatio,
  gpsNsToUtcIso,
  parseDecimal,
  ratio,
  ratioAdd,
  ratioCeilDiv,
  ratioMul,
  unitNsBig,
  utcIsoToGpsNs,
  type Ratio,
  type UnitCode,
} from '../../engine/timebase';

export interface BuilderRow {
  sid: string;
  delayMs: string;
}

export interface BuilderInput {
  rows: readonly BuilderRow[];
  slack: string;
  unitCode: UnitCode;
  /** ISO 8601 UTC time, or an integer number of GPS nanoseconds. */
  ingress: string;
  nextHeader: number;
}

export interface BuilderHop {
  k: number;
  sid: number;
  /** B_k in ns (exact). */
  budgetNs: Ratio;
  target: bigint;
  delta: number;
  deadline: number;
  clamped: boolean;
}

export type BuilderResult =
  | { ok: false; errors: string[] }
  | {
      ok: true;
      header: TcrhHeader;
      hex: string;
      hops: BuilderHop[];
      sat: boolean;
      epochBase: number;
      tIngressGpsNs: bigint;
      ingressUtc: string | null;
    };

const MAX_DELAY_MS = ratio(100_000n);
const MAX_SLACK = ratio(100n);

/** "1201", "0xF003" -> SID number, or null. */
export function parseSid(text: string): number | null {
  const t = text.trim();
  let value: number;
  if (/^0x[0-9a-f]{1,4}$/i.test(t)) value = Number.parseInt(t.slice(2), 16);
  else if (/^\d{1,5}$/.test(t)) value = Number(t);
  else return null;
  return value >= 0 && value < SID_RESERVED ? value : null;
}

function lessOrEqual(a: Ratio, b: Ratio): boolean {
  return a.num * b.den <= b.num * a.den;
}

export function parseIngress(text: string): { gpsNs: bigint; utc: string | null } | string {
  const t = text.trim();
  if (/^\d{1,25}$/.test(t)) return { gpsNs: BigInt(t), utc: null };
  try {
    const gpsNs = utcIsoToGpsNs(t);
    return { gpsNs, utc: gpsNsToUtcIso(gpsNs) };
  } catch (error) {
    const why = error instanceof Error ? error.message : String(error);
    return `Ingress time: ${why}. Write a UTC time such as 2026-10-10T13:58:00.123456Z, or a whole number of GPS nanoseconds.`;
  }
}

export function computeBuild(input: BuilderInput): BuilderResult {
  const errors: string[] = [];
  if (input.rows.length < 1 || input.rows.length > MAX_HOPS) {
    errors.push(`A T-CRH carries 1 to ${MAX_HOPS} hops; this path has ${input.rows.length}.`);
  }
  const sids: number[] = [];
  const delays: Ratio[] = [];
  input.rows.forEach((row, i) => {
    const sid = parseSid(row.sid);
    if (sid === null) {
      errors.push(
        `Hop ${i + 1}: the SID must be a whole number from 0 to 65534, or hex such as 0xF003. 65535 (0xFFFF) is reserved.`,
      );
    } else {
      sids.push(sid);
    }
    const delay = parseDecimal(row.delayMs);
    if (delay === null) {
      errors.push(`Hop ${i + 1}: the delay must be a non-negative number of milliseconds, such as 2.65.`);
    } else if (!lessOrEqual(delay, MAX_DELAY_MS)) {
      errors.push(`Hop ${i + 1}: keep the delay at or below 100000 ms (100 s).`);
    } else {
      delays.push(delay);
    }
  });
  const slack = parseDecimal(input.slack);
  if (slack === null || slack.num === 0n) {
    errors.push('Slack S must be a positive number, such as 1.3.');
  } else if (!lessOrEqual(slack, MAX_SLACK)) {
    errors.push('Slack S must be at most 100.');
  }
  const ingress = parseIngress(input.ingress);
  if (typeof ingress === 'string') errors.push(ingress);
  if (![6, 17, 41, 59].includes(input.nextHeader)) errors.push('Next Header must be 6, 17, 41 or 59.');
  if (errors.length > 0 || slack === null || typeof ingress === 'string') return { ok: false, errors };

  // B_k = S * (b_1 + ... + b_k), in ns, exactly.
  const budgets: Ratio[] = [];
  let cumulativeMs = ratio(0n);
  for (const d of delays) {
    cumulativeMs = ratioAdd(cumulativeMs, d);
    budgets.push(ratioMul(ratioMul(cumulativeMs, slack), ratio(NS_PER_MS)));
  }
  const header = buildHeader(sids, budgets, ingress.gpsNs, input.unitCode, input.nextHeader);
  const { deltas } = encodeDeltas(budgets, input.unitCode);
  const ds = deadlines(header);
  const u = unitNsBig(input.unitCode);
  let encoded = 0n;
  const hops: BuilderHop[] = sids.map((sid, i) => {
    const budgetNs = budgets[i] ?? ratio(0n);
    const target = ratioCeilDiv(budgetNs, u);
    const delta = deltas[i] ?? 0;
    const clamped = target - encoded > 255n;
    encoded += BigInt(delta);
    return { k: i + 1, sid, budgetNs, target, delta, deadline: ds[i] ?? 0, clamped };
  });
  return {
    ok: true,
    header,
    hex: bytesToHex(encode(header)),
    hops,
    sat: isSat(header),
    epochBase: epochBaseAtIngress(ingress.gpsNs, input.unitCode),
    tIngressGpsNs: ingress.gpsNs,
    ingressUtc: ingress.utc,
  };
}

/** A budget in ns as milliseconds text (exact when it fits in 6 decimals, else marked ≈). */
export function nsRatioToMs(r: Ratio): string {
  return formatRatio(ratio(r.num, r.den * NS_PER_MS), 6);
}

/**
 * Example inputs. Each one reproduces a golden encode vector byte for byte (checked in
 * src/engine/builder.test.ts). The SIDs and delays are test inputs from
 * spec/golden/gen_vectors.py, not a real Starlink route.
 */
export const BUILDER_EXAMPLES: ReadonlyArray<{ id: string; label: string; vector: string; input: BuilderInput }> = [
  {
    id: 'h10',
    label: '10 hops at 0.1 ms',
    vector: 'h10-real-gps-time-uc1',
    input: {
      rows: [
        ['1201', '2.65'],
        ['1202', '3.39'],
        ['1340', '4.12'],
        ['1341', '1.8'],
        ['1342', '5.205'],
        ['1480', '3.39'],
        ['1481', '2.981'],
        ['1620', '4.407'],
        ['1621', '3.112'],
        ['0xF003', '6.033'],
      ].map(([sid, delayMs]) => ({ sid: sid ?? '', delayMs: delayMs ?? '' })),
      slack: '1.3',
      unitCode: 1,
      ingress: '2026-10-10T13:58:00.123456Z',
      nextHeader: 17,
    },
  },
  {
    id: 'u1',
    label: '3 hops at 0.1 ms, last budget 1 ns past a unit boundary',
    vector: 'unit-code-1',
    input: {
      rows: [
        { sid: '7', delayMs: '1.8' },
        { sid: '8', delayMs: '3.39' },
        { sid: '0xF002', delayMs: '3.810001' },
      ],
      slack: '1',
      unitCode: 1,
      ingress: '1000000123',
      nextHeader: 17,
    },
  },
  {
    id: 'sat',
    label: 'A hop too long for one byte (SAT)',
    vector: 'sat-uc1',
    input: {
      rows: [
        { sid: '100', delayMs: '30' },
        { sid: '200', delayMs: '1' },
      ],
      slack: '1',
      unitCode: 1,
      ingress: '1000000000',
      nextHeader: 17,
    },
  },
];

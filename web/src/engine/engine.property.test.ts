/**
 * Property tests for the T-CRH engine with a small seeded generator (no extra dependency).
 * Every run uses the same seeds, so a failure is reproducible.
 */
import { describe, expect, it } from 'vitest';
import {
  buildHeader,
  decode,
  decodePrefix,
  deadlines,
  deltasFwdOf,
  encode,
  encodeDeltas,
  fromForward,
  ingressSend,
  isSat,
  processAtNode,
  sidsFwdOf,
  FLAG_DEV,
  FLAG_GREEDY,
  FLAG_SAT,
  OFF_DEV_HOP,
  OFF_FLAGS,
  OFF_SEGMENTS_LEFT,
  type Budget,
} from './tcrh';
import { tcrhSize } from './sizes';
import {
  MOD32,
  clockU,
  epochBaseAtIngress,
  ratio,
  serialDiff,
  unitNsBig,
  type UnitCode,
} from './timebase';

/** mulberry32: a tiny, well-known 32-bit PRNG. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gen(seed: number) {
  const next = rng(seed);
  const int = (lo: number, hi: number) => lo + Math.floor(next() * (hi - lo + 1));
  const big = (lo: bigint, hi: bigint) => {
    // uniform enough for tests: combine two 32-bit draws
    const span = hi - lo + 1n;
    const r = (BigInt(int(0, 0xffffffff)) << 32n) | BigInt(int(0, 0xffffffff));
    return lo + (r % span);
  };
  const unit = () => int(0, 3) as UnitCode;
  /** Mostly short paths, sometimes long, occasionally the maximum. */
  const hops = () => {
    const r = next();
    if (r < 0.05) return 255;
    if (r < 0.25) return int(14, 254);
    return int(1, 13);
  };
  return { next, int, big, unit, hops };
}

const RUNS = 300;

describe('encode / decode round trip', () => {
  it('decode(encode(h)) == h and encode(decode(b)) == b for random fresh headers', () => {
    const g = gen(1);
    for (let run = 0; run < RUNS; run += 1) {
      const h = g.hops();
      const sids = Array.from({ length: h }, () => g.int(0, 0xfffe));
      const deltas = Array.from({ length: h }, () => g.int(0, 255));
      const epoch = g.int(0, MOD32 - 1);
      const uc = g.unit();
      const nh = g.int(0, 255);
      const extra = g.int(0, 7);
      const header = fromForward(sids, deltas, epoch, uc, nh, extra);
      const bytes = encode(header);
      expect(bytes.length).toBe(tcrhSize(h));
      expect(bytes.length % 8).toBe(0);
      const back = decode(bytes);
      expect(back).toEqual(header);
      expect(sidsFwdOf(back)).toEqual(sids);
      expect(deltasFwdOf(back)).toEqual(deltas);
      expect(encode(back)).toEqual(bytes);
      // A payload after the header is not part of it.
      const withPayload = new Uint8Array([...bytes, 1, 2, 3]);
      expect(decodePrefix(withPayload).length).toBe(bytes.length);
      expect(() => decode(withPayload)).toThrow();
    }
  });

  it('deadlines equal Epoch_Base plus the running sum of deltas, mod 2^32', () => {
    const g = gen(2);
    for (let run = 0; run < RUNS; run += 1) {
      const h = g.hops();
      const deltas = Array.from({ length: h }, () => g.int(0, 255));
      const epoch = g.int(0, MOD32 - 1);
      const header = fromForward(Array.from({ length: h }, (_, i) => i), deltas, epoch, 0);
      let sum = BigInt(epoch);
      deadlines(header).forEach((d, i) => {
        sum += BigInt(deltas[i] ?? 0);
        expect(BigInt(d)).toBe(sum % (1n << 32n));
      });
    }
  });
});

/** Random non-decreasing cumulative budgets in ns: integers and exact rationals. */
function randomBudgets(g: ReturnType<typeof gen>, h: number, maxStepNs: number): Budget[] {
  const out: Budget[] = [];
  let acc = ratio(0n);
  for (let k = 0; k < h; k += 1) {
    // whole nanoseconds, or exact sevenths of a nanosecond (a fraction no float can hold)
    const step = g.next() < 0.5 ? ratio(BigInt(g.int(0, maxStepNs))) : ratio(BigInt(g.int(0, maxStepNs * 7)), 7n);
    acc = ratio(acc.num * step.den + step.num * acc.den, acc.den * step.den);
    out.push(g.next() < 0.5 && acc.den === 1n ? acc.num : acc);
  }
  return out;
}

const toRatio = (b: Budget) => (typeof b === 'bigint' ? { num: b, den: 1n } : b);

describe('ceil-cumulative delta encoding (spec 5.1)', () => {
  it('without SAT, every encoded cumulative deadline is >= its budget and within one unit of it', () => {
    const g = gen(3);
    let checked = 0;
    for (let run = 0; run < RUNS; run += 1) {
      const uc = g.unit();
      const u = unitNsBig(uc);
      const budgets = randomBudgets(g, g.int(1, 40), Number(u) * 60);
      const { deltas, sat } = encodeDeltas(budgets, uc);
      if (sat) continue;
      let encoded = 0n;
      budgets.forEach((b, i) => {
        encoded += BigInt(deltas[i] ?? 0);
        const r = toRatio(b);
        // encoded * u >= B  and  encoded * u < B + u   (exactly, with rationals)
        expect(encoded * u * r.den >= r.num).toBe(true);
        expect(encoded * u * r.den < r.num + u * r.den).toBe(true);
      });
      checked += 1;
    }
    expect(checked).toBeGreaterThan(RUNS / 2);
  });

  it('with SAT set, at least one delta is 255; every delta is a byte', () => {
    const g = gen(4);
    let saturated = 0;
    for (let run = 0; run < RUNS; run += 1) {
      const uc = g.unit();
      const budgets = randomBudgets(g, g.int(1, 20), Number(unitNsBig(uc)) * 600);
      const { deltas, sat } = encodeDeltas(budgets, uc);
      for (const d of deltas) expect(d >= 0 && d <= 255 && Number.isInteger(d)).toBe(true);
      if (sat) {
        saturated += 1;
        expect(deltas.includes(255)).toBe(true);
      }
    }
    expect(saturated).toBeGreaterThan(0);
  });

  it('a budget of exactly n units encodes to n, one more nanosecond to n + 1', () => {
    for (const uc of [0, 1, 2, 3] as const) {
      const u = unitNsBig(uc);
      for (const n of [0n, 1n, 3n, 200n]) {
        expect(encodeDeltas([n * u], uc).deltas).toEqual([Number(n)]);
        expect(encodeDeltas([n * u + 1n], uc).deltas).toEqual([Number(n) + 1]);
      }
    }
  });

  it('rejects floats and negative budgets', () => {
    expect(() => encodeDeltas([3.5 as unknown as bigint], 0)).toThrow(TypeError);
    expect(() => encodeDeltas([-1n], 0)).toThrow(RangeError);
  });
});

describe('deadlines are never early unless SAT (end to end through processAtNode)', () => {
  it('a packet that arrives exactly at T_ingress + B_k is on time at every hop', () => {
    const g = gen(5);
    for (let run = 0; run < RUNS; run += 1) {
      const uc = g.unit();
      const u = unitNsBig(uc);
      const h = g.int(1, 30);
      // Real GPS times are ~1.5e18 ns; include values right at the 2^32-unit wrap too.
      const t0 = g.next() < 0.2 ? (1n << 32n) * u - BigInt(g.int(0, 5_000_000)) : g.big(1_000_000_000_000_000_000n, 2_000_000_000_000_000_000n);
      const budgets = randomBudgets(g, h, Number(u) * 40);
      const header = buildHeader(
        Array.from({ length: h }, (_, i) => i + 1),
        budgets,
        t0,
        uc,
      );
      if (isSat(header)) continue;
      let packet = ingressSend(encode(header)).outBytes;
      for (let k = 1; k <= h; k += 1) {
        const b = toRatio(budgets[k - 1] ?? 0n);
        // floor((T0 + B_k) / u) with an exact rational B_k
        const arrivalNs = t0 * b.den + b.num; // scaled by den
        const nowU = Number(((arrivalNs / (u * b.den)) % (1n << 32n)));
        const res = processAtNode(packet, nowU, 'greedy');
        expect(res.late).toBe(false);
        expect(res.hopIndex).toBe(k);
        if (k < h) {
          expect(res.action).toBe('forward');
          packet = res.outBytes ?? new Uint8Array();
        } else {
          expect(res.action).toBe('deliver');
        }
      }
    }
  });

  it('one unit after a deadline is late, and the result follows the policy', () => {
    const g = gen(6);
    for (let run = 0; run < RUNS; run += 1) {
      const h = g.int(2, 20);
      const sids = Array.from({ length: h }, () => g.int(0, 0xfffe));
      const header = fromForward(sids, Array.from({ length: h }, () => g.int(0, 255)), g.int(0, MOD32 - 1), g.unit());
      const lateAt = g.int(1, h);
      const policy = (['greedy', 'continue', 'drop'] as const)[g.int(0, 2)] ?? 'greedy';
      const ds = deadlines(header);
      let packet = ingressSend(encode(header)).outBytes;
      for (let k = 1; k <= h; k += 1) {
        const dk = ds[k - 1] ?? 0;
        const nowU = k === lateAt ? (dk + 1) % MOD32 : dk;
        const before = packet;
        const res = processAtNode(packet, nowU, policy);
        expect(res.deadlineU).toBe(dk);
        if (k < lateAt) {
          expect(res.late).toBe(false);
          expect(res.action).toBe('forward');
        } else if (k === lateAt) {
          expect(res.late).toBe(true);
          if (k === h) {
            expect(res.action).toBe('deliver');
          } else if (policy === 'greedy') {
            expect(res.action).toBe('fallback');
            expect(res.nextSid).toBe(sids[h - 1]);
            const out = res.outBytes ?? new Uint8Array();
            expect(out[OFF_SEGMENTS_LEFT]).toBe(0);
            expect((out[OFF_FLAGS] ?? 0) & (FLAG_DEV | FLAG_GREEDY)).toBe(FLAG_DEV | FLAG_GREEDY);
          } else if (policy === 'drop') {
            expect(res.action).toBe('drop_late');
            expect(res.outBytes).toBeNull();
          } else {
            expect(res.action).toBe('forward');
          }
        } else {
          // DEV is already set: no second check, Dev Hop stays.
          expect(res.late).toBe(false);
        }
        if (res.outBytes) {
          // Only Segments Left, Flags and Dev Hop may change.
          res.outBytes.forEach((byte, i) => {
            if (i !== OFF_SEGMENTS_LEFT && i !== OFF_FLAGS && i !== OFF_DEV_HOP) expect(byte).toBe(before[i]);
          });
          if (res.outBytes[OFF_FLAGS] !== undefined && ((res.outBytes[OFF_FLAGS] ?? 0) & FLAG_DEV) !== 0) {
            expect(res.outBytes[OFF_DEV_HOP]).toBe(lateAt);
          }
          // SAT and the unit bits pass through unchanged.
          expect((res.outBytes[OFF_FLAGS] ?? 0) & (FLAG_SAT | 0x30)).toBe((before[OFF_FLAGS] ?? 0) & (FLAG_SAT | 0x30));
        }
        if (res.action !== 'forward' || !res.outBytes) break;
        packet = res.outBytes;
      }
    }
  });
});

describe('time base', () => {
  it('Epoch_Base is ceil(t/u) mod 2^32 and the unit clock is floor(t/u) mod 2^32', () => {
    const g = gen(7);
    for (let run = 0; run < RUNS; run += 1) {
      const uc = g.unit();
      const u = unitNsBig(uc);
      const t = g.big(0n, 3_000_000_000_000_000_000n);
      const e = BigInt(epochBaseAtIngress(t, uc));
      const c = BigInt(clockU(t, uc));
      const ceil = (t + u - 1n) / u;
      const floor = t / u;
      expect(e).toBe(ceil % (1n << 32n));
      expect(c).toBe(floor % (1n << 32n));
      expect(t % u === 0n ? e === c : (c + 1n) % (1n << 32n) === e).toBe(true);
    }
  });

  it('serialDiff recovers small differences across the 2^32 wrap', () => {
    const g = gen(8);
    for (let run = 0; run < RUNS; run += 1) {
      const a = g.int(0, MOD32 - 1);
      const d = g.int(-(2 ** 31), 2 ** 31 - 1);
      const b = (((a + d) % MOD32) + MOD32) % MOD32;
      expect(serialDiff(b, a)).toBe(d);
      const s = serialDiff(a, b);
      expect(s >= -(2 ** 31) && s < 2 ** 31).toBe(true);
    }
    expect(serialDiff(0, MOD32 - 1)).toBe(1);
    expect(serialDiff(MOD32 - 1, 0)).toBe(-1);
    expect(serialDiff(2 ** 31, 0)).toBe(-(2 ** 31));
  });
});

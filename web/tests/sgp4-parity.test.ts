/**
 * SGP4 TOLERANCE TEST: the browser's positions (satellite.js 7.1.0 through the same functions
 * the orbit worker uses, rotated to ECEF by GMST) against Python's (python-sgp4 2.27,
 * chronoroute.orbit) for EVERY satellite of the route planner's shell, at the parity instant.
 *
 * Why a tolerance and not equality: satellite.js json2satrec() reads EPOCH with a JavaScript
 * Date, which keeps whole milliseconds only. CelesTrak publishes microseconds, so the browser's
 * epoch can be up to 1 ms early, and a satellite moves about 7.6 m in 1 ms along its track.
 * Python keeps the microseconds. tools/web_parity.py therefore also exports Python positions
 * computed with every EPOCH cut to milliseconds: against those the two implementations must
 * agree far more closely, which shows that the epoch rounding is the whole difference.
 *
 * Thresholds: <= 10 m against full-precision Python (the plan's tolerance), <= 1 m against the
 * millisecond-epoch Python. Route parity itself never depends on this (route-parity.test.ts
 * runs both routers on Python's positions).
 */
import { describe, expect, it } from 'vitest';
import { initSatrecs, propagateAllTemeKm } from '../src/lib/orbit/propagate';
import { ecefFrameFromTeme } from '../src/lib/route/frame';
import { referenceRun, servedRun } from './parity-gate';
import { framePositions, PARITY_FILE, readParity, SERVED_PARITY_FILE } from './parity-data';

const runs = [referenceRun(readParity(PARITY_FILE)), servedRun(readParity(SERVED_PARITY_FILE))];

function stats(values: number[]): { median: number; p99: number; max: number } {
  const s = [...values].sort((a, b) => a - b);
  const at = (q: number) => s[Math.min(s.length - 1, Math.floor(q * s.length))]!;
  return { median: at(0.5), p99: at(0.99), max: s[s.length - 1]! };
}

for (const run of runs) {
  const { doc, ctx } = run;
  const byNorad = new Map(ctx.records.map((r) => [r.NORAD_CAT_ID, r]));
  describe(`${run.role} run: SGP4 satellite.js vs python-sgp4 for ${doc.frame.norad.length} satellites at ${doc.t_utc}`, () => {
    const ordered = doc.frame.norad.map((n) => byNorad.get(n)!);
    const { satrecs, errors } = initSatrecs(ordered);
    const ms = Number(BigInt(doc.t_unix_ns) / 1_000_000n);
    const teme = new Float64Array(satrecs.length * 3);
    const failed = propagateAllTemeKm(satrecs, ms, teme);
    const mine = ecefFrameFromTeme(teme, ms).ecefKm;
    const full = framePositions(doc.frame.ecef_km);
    const msEpoch = framePositions(doc.frame.ecef_ms_epoch_km);

    const errorsM = (ref: Float64Array) => {
      const out: number[] = [];
      for (let i = 0; i < satrecs.length; i += 1) {
        const dx = mine[3 * i]! - ref[3 * i]!;
        const dy = mine[3 * i + 1]! - ref[3 * i + 1]!;
        const dz = mine[3 * i + 2]! - ref[3 * i + 2]!;
        out.push(Math.hypot(dx, dy, dz) * 1000);
      }
      return out;
    };

    it('initialises and propagates every element set (the instant is a whole millisecond)', () => {
      expect(BigInt(doc.t_unix_ns) % 1_000_000n).toBe(0n);
      expect([...ctx.net.norads]).toEqual(doc.frame.norad);
      expect(errors).toEqual([]);
      expect(failed).toBe(0);
      expect(ordered.every((r) => r !== undefined)).toBe(true);
    });

    it('agrees within 10 m of full-precision Python, and within 1 m once EPOCH is cut to milliseconds', () => {
      const eFull = errorsM(full);
      const eMs = errorsM(msEpoch);
      expect(eFull.every(Number.isFinite)).toBe(true);
      const sFull = stats(eFull);
      const sMs = stats(eMs);
      console.log(
        `[sgp4] ${run.role}: vs full EPOCH: median ${sFull.median.toFixed(3)} m, p99 ${sFull.p99.toFixed(3)} m, max ${sFull.max.toFixed(3)} m; ` +
          `vs ms EPOCH: median ${sMs.median.toFixed(4)} m, p99 ${sMs.p99.toFixed(4)} m, max ${sMs.max.toFixed(4)} m`,
      );
      expect(sFull.max).toBeLessThanOrEqual(10);
      expect(sMs.max).toBeLessThanOrEqual(1);
      // The rounding explains the gap: the ms-epoch reference is far closer than the full one.
      expect(sMs.median).toBeLessThan(sFull.median);
    });
  });
}

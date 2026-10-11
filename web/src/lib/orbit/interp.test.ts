/**
 * The frame interpolation used on the GPU and for picking must follow the orbit, even at the
 * fastest clock speed (frames 600 s apart). Checked against SGP4 itself at the midpoint.
 */
import { describe, expect, it } from 'vitest';
import { EARTH_EQUATORIAL_RADIUS_KM } from './constants';
import { interpolateRow } from './interp';
import { initSatrecs, propagateAllToScene } from './propagate';
import { readPinnedRecords } from './test-data';

// Fixed reference data: the pinned 2026-10-10 snapshot, whatever snapshot the site is built from.
const snapshot = { records: await readPinnedRecords() };
const { satrecs } = initSatrecs(snapshot.records);
const T0 = Date.parse('2026-10-10T14:02:22Z');

function frame(ms: number): Float32Array {
  const out = new Float32Array(satrecs.length * 3);
  propagateAllToScene(satrecs, ms, out);
  return out;
}

describe('interpolateRow', () => {
  it('stays close to SGP4 between frames 600 s apart (x600), for every satellite', () => {
    const a = frame(T0);
    const b = frame(T0 + 600_000);
    const truth = frame(T0 + 300_000);
    const p = new Float32Array(3);
    const errors: number[] = [];
    let worstChord = 0;
    for (let i = 0; i < satrecs.length; i += 1) {
      expect(interpolateRow(a, b, i, 0.5, p)).toBe(true);
      const err = Math.hypot(p[0]! - truth[i * 3]!, p[1]! - truth[i * 3 + 1]!, p[2]! - truth[i * 3 + 2]!);
      errors.push(err * EARTH_EQUATORIAL_RADIUS_KM);
      const chord = Math.hypot(
        (a[i * 3]! + b[i * 3]!) / 2 - truth[i * 3]!,
        (a[i * 3 + 1]! + b[i * 3 + 1]!) / 2 - truth[i * 3 + 1]!,
        (a[i * 3 + 2]! + b[i * 3 + 2]!) / 2 - truth[i * 3 + 2]!,
      );
      worstChord = Math.max(worstChord, chord * EARTH_EQUATORIAL_RADIUS_KM);
    }
    errors.sort((x, y) => x - y);
    const median = errors[errors.length >> 1]!;
    const p99 = errors[Math.floor(errors.length * 0.99)]!;
    const worst = errors[errors.length - 1]!;
    console.info(
      `x600 midpoint error vs SGP4: median ${median.toFixed(3)} km, p99 ${p99.toFixed(3)} km, ` +
        `max ${worst.toFixed(3)} km; straight chord max ${worstChord.toFixed(0)} km`,
    );
    // Measured on the 2026-10-10 snapshot: median 0.65 km, p99 1.09 km, max 2.61 km. What is left
    // is SGP4's short-period J2 terms (radius oscillating twice per orbit) and, for the largest
    // errors, the lowest and most eccentric orbits. 5 km is under 0.001 scene units, about one
    // pixel at the closest zoom.
    expect(p99).toBeLessThan(1.5);
    expect(worst).toBeLessThan(5);
    // A straight mix(posA, posB, 0.5) would be hundreds of km off: the reason for the slerp.
    expect(worstChord).toBeGreaterThan(300);
  });

  it('stays within 100 m of SGP4 between frames 60 s apart (x60)', () => {
    const a = frame(T0);
    const b = frame(T0 + 60_000);
    const truth = frame(T0 + 30_000);
    const p = new Float32Array(3);
    let worst = 0;
    for (let i = 0; i < satrecs.length; i += 1) {
      interpolateRow(a, b, i, 0.5, p);
      const err = Math.hypot(p[0]! - truth[i * 3]!, p[1]! - truth[i * 3 + 1]!, p[2]! - truth[i * 3 + 2]!);
      worst = Math.max(worst, err * EARTH_EQUATORIAL_RADIUS_KM * 1000);
    }
    console.info(`x60 midpoint error vs SGP4: max ${worst.toFixed(1)} m`);
    expect(worst).toBeLessThan(100);
  });

  it('stays within 50 m of SGP4 between frames 1 s apart (x1)', () => {
    const a = frame(T0);
    const b = frame(T0 + 1_000);
    const truth = frame(T0 + 500);
    const p = new Float32Array(3);
    let worst = 0;
    for (let i = 0; i < satrecs.length; i += 1) {
      interpolateRow(a, b, i, 0.5, p);
      const err = Math.hypot(p[0]! - truth[i * 3]!, p[1]! - truth[i * 3 + 1]!, p[2]! - truth[i * 3 + 2]!);
      worst = Math.max(worst, err * EARTH_EQUATORIAL_RADIUS_KM * 1000);
    }
    expect(worst).toBeLessThan(50);
  });

  it('returns the end frames exactly at alpha 0 and 1, and hides rows without a position', () => {
    const a = new Float32Array([1.07, 0, 0, 0, 0, 0]);
    const b = new Float32Array([0, 1.07, 0, 1, 1, 1]);
    const p = [0, 0, 0];
    interpolateRow(a, b, 0, 0, p);
    expect(p[0]).toBeCloseTo(1.07, 6);
    interpolateRow(a, b, 0, 1, p);
    expect(p[1]).toBeCloseTo(1.07, 6);
    expect(interpolateRow(a, b, 1, 0.5, p)).toBe(false);
    expect(p).toEqual([0, 0, 0]);
  });
});

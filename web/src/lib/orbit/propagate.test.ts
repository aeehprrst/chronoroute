/**
 * Cross-check of our propagation (satellite.js 7.1.0, through the same functions the worker
 * uses) against the reference SGP4 implementation in Python.
 *
 * Reference: python-sgp4 2.27 (accelerated C++ core), run on 2026-10-10 in
 * ~/chronoroute/venv on the raw pinned file
 * data/pinned/20261010T1358Z-celestrak/starlink_supgp.json, with sgp4.omm.initialize() and
 * Satrec.sgp4(jd, fr) at 2026-10-10T14:02:22Z (the snapshot download time,
 * jd = 2461323.5, fr = 0.5849768518518519). Positions in TEME, km. Command:
 *
 *   ~/chronoroute/venv/bin/python -B -I -c "
 *   import json; from sgp4.api import Satrec, jday; from sgp4 import omm
 *   d = {o['NORAD_CAT_ID']: o for o in json.load(open('starlink_supgp.json'))}
 *   jd, fr = jday(2026, 10, 10, 14, 2, 22)
 *   for n in (44714, 48881, 100001):
 *       for mode in ('full', 'ms'):
 *           f = {k: str(v) for k, v in d[n].items()}
 *           if mode == 'ms': f['EPOCH'] = f['EPOCH'][:23]
 *           s = Satrec(); omm.initialize(s, f); print(n, mode, s.sgp4(jd, fr))"
 *
 * Two references per satellite:
 *  - "full": EPOCH with its full microsecond precision, as CelesTrak publishes it.
 *  - "ms": EPOCH truncated to milliseconds. satellite.js json2satrec() parses EPOCH with the
 *    JavaScript Date object, which keeps only milliseconds, so its epoch is up to 1 ms early.
 *    At 7.6 km/s that is up to 7.6 m along the track. Against the "ms" reference the two
 *    implementations agree to well under a metre, which shows the remaining gap to "full"
 *    is exactly this epoch rounding and nothing else.
 *
 * scripts/sgp4-crosscheck.mjs prints the JavaScript side of the same comparison.
 */
import { describe, expect, it } from 'vitest';
import { EARTH_EQUATORIAL_RADIUS_KM } from './constants';
import { initSatrecs, propagateAllToScene, propagateKm } from './propagate';
import { sceneToKm } from './frames';
import { readPinnedRecords } from './test-data';

const AT_MS = Date.parse('2026-10-10T14:02:22Z');

const REFERENCE: Array<{
  norad: number;
  name: string;
  full: [number, number, number];
  ms: [number, number, number];
}> = [
  {
    norad: 44714,
    name: 'STARLINK-1008',
    full: [5274.67225, 3688.260029, 2014.602412],
    ms: [5274.670991, 3688.264874, 2014.59687],
  },
  {
    norad: 48881,
    name: 'STARLINK-3005',
    full: [1118.974043, -158.951025, 6841.633755],
    ms: [1118.968776, -158.95601, 6841.634497],
  },
  {
    norad: 100001,
    name: 'STARLINK-38128',
    full: [3989.374374, -627.483747, -5541.920674],
    ms: [3989.370274, -627.478793, -5541.924187],
  },
];

// Fixed reference data: the pinned 2026-10-10 snapshot, whatever snapshot the site is built from.
const snapshot = { records: await readPinnedRecords() };
const { satrecs } = initSatrecs(snapshot.records);

function distanceM(a: { x: number; y: number; z: number }, b: [number, number, number]): number {
  return Math.hypot(a.x - b[0], a.y - b[1], a.z - b[2]) * 1000;
}

describe('SGP4 cross-check against python-sgp4 2.27', () => {
  for (const ref of REFERENCE) {
    it(`${ref.name} (NORAD ${ref.norad}) agrees within 10 m (and within 1 m of the ms-epoch reference)`, () => {
      const index = snapshot.records.findIndex((r) => r.NORAD_CAT_ID === ref.norad);
      expect(index).toBeGreaterThanOrEqual(0);
      expect(snapshot.records[index]!.OBJECT_NAME).toBe(ref.name);
      const state = propagateKm(satrecs[index]!, AT_MS);
      expect(state).not.toBeNull();
      const dFull = distanceM(state!.r, ref.full);
      const dMs = distanceM(state!.r, ref.ms);
      expect(dFull).toBeLessThan(10);
      expect(dMs).toBeLessThan(1);
    });
  }

  it('the Float32 scene positions sent to the GPU round-trip to within 2 m of the Float64 result', () => {
    const out = new Float32Array(satrecs.length * 3);
    const failed = propagateAllToScene(satrecs, AT_MS, out);
    expect(failed).toBe(0);
    for (const ref of REFERENCE) {
      const index = snapshot.records.findIndex((r) => r.NORAD_CAT_ID === ref.norad);
      const km = sceneToKm({ x: out[index * 3]!, y: out[index * 3 + 1]!, z: out[index * 3 + 2]! });
      const exact = propagateKm(satrecs[index]!, AT_MS)!.r;
      expect(Math.hypot(km.x - exact.x, km.y - exact.y, km.z - exact.z) * 1000).toBeLessThan(2);
    }
  });

  it('draws altitude true to scale: 480 km above the equator is r = 1.0753 scene units', () => {
    expect((EARTH_EQUATORIAL_RADIUS_KM + 480) / EARTH_EQUATORIAL_RADIUS_KM).toBeCloseTo(1.0753, 4);
    // Every satellite of the snapshot lies between 150 km and 700 km above the equatorial radius.
    const out = new Float32Array(satrecs.length * 3);
    propagateAllToScene(satrecs, AT_MS, out);
    let min = Infinity;
    let max = 0;
    for (let i = 0; i < satrecs.length; i += 1) {
      const r = Math.hypot(out[i * 3]!, out[i * 3 + 1]!, out[i * 3 + 2]!);
      min = Math.min(min, r);
      max = Math.max(max, r);
    }
    expect(min).toBeGreaterThan(1 + 150 / EARTH_EQUATORIAL_RADIUS_KM - 0.0034);
    expect(max).toBeLessThan(1 + 700 / EARTH_EQUATORIAL_RADIUS_KM);
  });
});

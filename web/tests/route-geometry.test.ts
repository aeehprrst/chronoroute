/**
 * Unit tests of the route planner's geometry (src/lib/route/geometry.ts). The parity test
 * compares it with Python on real positions; these check the physics on their own.
 */
import { describe, expect, it } from 'vitest';
import {
  closestApproach,
  ecefToGeodetic,
  elevationDeg,
  geodeticToEcef,
  propagationNs,
  segmentClears,
  segmentMinHeightKm,
  temeToEcef,
  WGS84_A_KM,
  WGS84_B_KM,
  type Vec3,
} from '../src/lib/route/geometry';

/** Deterministic pseudo-random numbers (mulberry32), so failures can be replayed. */
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

describe('WGS84 frames', () => {
  it('geodetic -> ECEF -> geodetic round-trips to below a micrometre, ground to LEO', () => {
    const r = rng(1);
    for (let i = 0; i < 2000; i += 1) {
      const lat = -90 + 180 * r();
      const lon = -180 + 360 * r();
      const h = 2000 * r();
      const [x, y, z] = geodeticToEcef(lat, lon, h);
      const g = ecefToGeodetic(x, y, z);
      expect(Math.abs(g.heightKm - h)).toBeLessThan(1e-9);
      expect(Math.abs(g.latDeg - lat)).toBeLessThan(1e-9);
      if (Math.abs(lat) < 89.9) expect(Math.abs(((g.lonDeg - lon + 540) % 360) - 180)).toBeLessThan(1e-9);
    }
  });

  it('puts the equator at radius a and the poles at radius b', () => {
    expect(geodeticToEcef(0, 0, 0)[0]).toBeCloseTo(WGS84_A_KM, 9);
    expect(geodeticToEcef(90, 0, 0)[2]).toBeCloseTo(WGS84_B_KM, 9);
  });

  it('elevation: straight up is 90 deg, a point on the local horizon plane is 0 deg', () => {
    const lat = 13.091934;
    const lon = 80.278053;
    const gs = geodeticToEcef(lat, lon, 0);
    const above = geodeticToEcef(lat, lon, 500);
    expect(elevationDeg(gs, above, lat, lon)).toBeCloseTo(90, 6);
    // a point displaced from the station along local east lies on the horizon plane
    const lonR = (lon * Math.PI) / 180;
    const east: Vec3 = [gs[0] - Math.sin(lonR) * 1000, gs[1] + Math.cos(lonR) * 1000, gs[2]];
    expect(Math.abs(elevationDeg(gs, east, lat, lon))).toBeLessThan(1e-9);
  });

  it('TEME -> ECEF is a rotation about z by GMST', () => {
    const [x, y, z] = temeToEcef(7000, 0, 1000, Math.PI / 2);
    expect(x).toBeCloseTo(0, 9);
    expect(y).toBeCloseTo(-7000, 9);
    expect(z).toBe(1000);
  });
});

describe('the 80 km grazing rule', () => {
  it('closest approach of a segment through the centre plane', () => {
    const { rMinKm, t } = closestApproach([7000, -3000, 0], [7000, 3000, 0]);
    expect(rMinKm).toBeCloseTo(7000, 9);
    expect(t).toBeCloseTo(0.5, 12);
  });

  it('segmentClears agrees with a dense search for segments in and around the 21 km band', () => {
    const r = rng(7);
    let decidedExactly = 0;
    for (let i = 0; i < 300; i += 1) {
      // Two satellites at ~460 km whose chord dips to a random height between 40 and 140 km.
      const lat = -60 + 120 * r();
      const lon = -180 + 360 * r();
      const az = 2 * Math.PI * r();
      const half = 1500 + 1500 * r(); // km of arc on either side
      const ang = half / 6371;
      const centre = geodeticToEcef(lat, lon, 0);
      const up = centre.map((v) => v / Math.hypot(...centre)) as unknown as Vec3;
      const ref: Vec3 = Math.abs(up[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0];
      const e1 = [up[1] * ref[2] - up[2] * ref[1], up[2] * ref[0] - up[0] * ref[2], up[0] * ref[1] - up[1] * ref[0]];
      const n1 = Math.hypot(e1[0]!, e1[1]!, e1[2]!);
      const u1 = e1.map((v) => v / n1);
      const u2 = [up[1] * u1[2]! - up[2] * u1[1]!, up[2] * u1[0]! - up[0] * u1[2]!, up[0] * u1[1]! - up[1] * u1[0]!];
      const dir = [0, 1, 2].map((k) => Math.cos(az) * u1[k]! + Math.sin(az) * u2[k]!);
      const radius = 6378 + 460;
      const pa = [0, 1, 2].map((k) => radius * (Math.cos(ang) * up[k]! - Math.sin(ang) * dir[k]!)) as unknown as Vec3;
      const pb = [0, 1, 2].map((k) => radius * (Math.cos(ang) * up[k]! + Math.sin(ang) * dir[k]!)) as unknown as Vec3;
      let dense = Infinity;
      for (let s = 0; s <= 4000; s += 1) {
        const t = s / 4000;
        dense = Math.min(dense, ecefToGeodetic(pa[0] + t * (pb[0] - pa[0]), pa[1] + t * (pb[1] - pa[1]), pa[2] + t * (pb[2] - pa[2])).heightKm);
      }
      const golden = segmentMinHeightKm(pa, pb);
      expect(golden).toBeLessThanOrEqual(dense + 1e-6); // golden section finds the true minimum (dense can only be above it)
      expect(dense - golden).toBeLessThan(0.01);
      if (Math.abs(dense - 80) > 0.01) expect(segmentClears(pa, pb)).toBe(dense >= 80);
      const { rMinKm } = closestApproach(pa, pb);
      if (rMinKm - WGS84_B_KM >= 80 && rMinKm - WGS84_A_KM < 80) decidedExactly += 1;
    }
    expect(decidedExactly).toBeGreaterThan(10); // the exact (golden-section) branch was exercised
  });

  it('a missing position (NaN) never gives a usable link', () => {
    expect(segmentClears([Number.NaN, 0, 0], [7000, 0, 0])).toBe(false);
  });
});

describe('light time', () => {
  it('rounds to the nearest nanosecond and returns -1 for a missing distance', () => {
    expect(propagationNs(299_792.458)).toBe(1_000_000_000);
    expect(propagationNs(0)).toBe(0);
    expect(propagationNs(0.00018)).toBe(1); // 0.600 ns -> 1
    expect(propagationNs(0.00012)).toBe(0); // 0.400 ns -> 0
    expect(propagationNs(1000)).toBe(3_335_641); // 3,335,640.95 ns
    expect(propagationNs(Number.NaN)).toBe(-1);
  });
});

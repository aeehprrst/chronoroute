/**
 * Sun position (Astronomical Almanac low-precision formulas) against published values.
 */
import { describe, expect, it } from 'vitest';
import { sunPos, jday } from 'satellite.js';
import { DEG } from './constants';
import { sunPosition } from './sun';

describe('sunPosition', () => {
  it('matches Meeus, Astronomical Algorithms (2nd ed.), example 25.a: 1992 October 13.0', () => {
    // Published apparent values: RA = 198.38083 deg, Dec = -7.78507 deg (0h TD; TD - UT was about 59 s).
    const s = sunPosition(Date.parse('1992-10-13T00:00:00Z'));
    expect(Math.abs(s.decDeg - -7.78507)).toBeLessThan(0.01);
    expect(Math.abs(s.raDeg - 198.38083)).toBeLessThan(0.02);
  });

  it('has declination +23.44 at the June 2026 solstice and -23.44 at the December 2026 solstice', () => {
    // Solstice instants (UTC) from the published 2026 tables: 2026-06-21 08:24, 2026-12-21 20:50.
    // The obliquity in 2026 is 23.436 degrees; near a solstice the declination changes by
    // under 0.0001 degrees per hour, so the minute of the instant does not matter.
    // Tolerance: the stated 0.01 degree accuracy of the formulas.
    expect(Math.abs(sunPosition(Date.parse('2026-06-21T08:24:00Z')).decDeg - 23.436)).toBeLessThan(0.01);
    expect(Math.abs(sunPosition(Date.parse('2026-12-21T20:50:00Z')).decDeg - -23.436)).toBeLessThan(0.01);
  });

  it('has declination 0 and ecliptic longitude 180 at the September 2026 equinox', () => {
    // 2026-09-23 00:05 UTC. Near an equinox the declination changes by about 0.016 degrees per hour.
    const s = sunPosition(Date.parse('2026-09-23T00:05:00Z'));
    expect(Math.abs(s.decDeg)).toBeLessThan(0.02);
    expect(Math.abs(s.eclipticLongitudeDeg - 180)).toBeLessThan(0.05);
  });

  it('agrees with the independent satellite.js sunPos (Vallado) within 0.02 degrees through 2026', () => {
    for (let month = 0; month < 12; month += 1) {
      const date = new Date(Date.UTC(2026, month, 10, 12, 0, 0));
      const ours = sunPosition(date.getTime()).eci;
      const theirs = sunPos(jday(date)).rsun;
      const norm = Math.hypot(theirs.x, theirs.y, theirs.z);
      const dot = (ours.x * theirs.x + ours.y * theirs.y + ours.z * theirs.z) / norm;
      expect(Math.acos(Math.min(1, dot)) / DEG).toBeLessThan(0.02);
    }
  });

  it('returns a unit vector', () => {
    const { eci } = sunPosition(Date.parse('2026-10-10T14:02:22Z'));
    expect(Math.hypot(eci.x, eci.y, eci.z)).toBeCloseTo(1, 12);
  });
});

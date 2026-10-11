/**
 * Low-precision position of the Sun, used to place the day/night terminator on the globe.
 *
 * Algorithm: the low-precision formulas for the Sun of The Astronomical Almanac (section C),
 * stated accuracy about 0.01 degrees between 1950 and 2050. The U.S. Naval Observatory page
 * "Approximate Solar Coordinates" gives the same formulas with slightly different rounding of
 * the coefficients. Checked in sun.test.ts against the worked example 25.a of J. Meeus,
 * "Astronomical Algorithms" (2nd ed.), the 2026 solstices and equinox, and satellite.js sunPos.
 *
 *   n = JD - 2451545.0
 *   L = 280.460 + 0.9856474 n          mean longitude (deg)
 *   g = 357.528 + 0.9856003 n          mean anomaly (deg)
 *   lambda = L + 1.915 sin g + 0.020 sin 2g      ecliptic longitude (deg)
 *   epsilon = 23.439 - 0.0000004 n     obliquity of the ecliptic (deg)
 *   RA = atan2(cos epsilon sin lambda, cos lambda),  dec = asin(sin epsilon sin lambda)
 *
 * The result is a direction in the equatorial frame of date (the ecliptic latitude of the Sun
 * is below 0.0003 degrees and is taken as zero). The difference between that frame and TEME
 * (nutation, a few arcseconds) is far below the accuracy of the formula. UTC is used for TT;
 * the 69 s difference moves the Sun by under 0.001 degrees.
 */
import { DEG, julianDateFromMs } from './constants';
import type { Vec3 } from './frames';

export interface SunPosition {
  /** Unit vector towards the Sun in ECI (TEME-like) axes, x towards the equinox, z north. */
  eci: Vec3;
  /** Right ascension in degrees, [0, 360). */
  raDeg: number;
  /** Declination in degrees. */
  decDeg: number;
  /** Apparent ecliptic longitude in degrees, [0, 360). */
  eclipticLongitudeDeg: number;
}

function wrap360(deg: number): number {
  const r = deg % 360;
  return r < 0 ? r + 360 : r;
}

/** Position of the Sun at Unix time `ms`. */
export function sunPosition(ms: number): SunPosition {
  const n = julianDateFromMs(ms) - 2451545.0;
  const L = wrap360(280.46 + 0.9856474 * n);
  const g = wrap360(357.528 + 0.9856003 * n) * DEG;
  const lambdaDeg = wrap360(L + 1.915 * Math.sin(g) + 0.02 * Math.sin(2 * g));
  const lambda = lambdaDeg * DEG;
  const epsilon = (23.439 - 0.0000004 * n) * DEG;

  const x = Math.cos(lambda);
  const y = Math.cos(epsilon) * Math.sin(lambda);
  const z = Math.sin(epsilon) * Math.sin(lambda);
  return {
    eci: { x, y, z },
    raDeg: wrap360(Math.atan2(y, x) / DEG),
    decDeg: Math.asin(z) / DEG,
    eclipticLongitudeDeg: lambdaDeg,
  };
}

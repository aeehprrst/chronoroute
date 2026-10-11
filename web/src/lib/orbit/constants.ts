/**
 * Physical constants and scene scale used by the globe. All REAL (published standards).
 *
 * Scene scale: 1 scene unit = the WGS84 equatorial radius of the Earth, 6378.137 km.
 * Satellite altitudes are drawn true to scale: a satellite 480 km above the equator sits at
 * r = (6378.137 + 480) / 6378.137 = 1.0753 scene units.
 */

/** WGS84 equatorial radius (km). One scene unit. */
export const EARTH_EQUATORIAL_RADIUS_KM = 6378.137;

/** WGS84 flattening. */
export const WGS84_FLATTENING = 1 / 298.257223563;

/** WGS84 polar radius (km): a (1 - f) = 6356.752314 km. */
export const EARTH_POLAR_RADIUS_KM = EARTH_EQUATORIAL_RADIUS_KM * (1 - WGS84_FLATTENING);

/** Polar radius in scene units (b / a = 0.996647). */
export const EARTH_POLAR_SCALE = 1 - WGS84_FLATTENING;

/**
 * WGS72 gravitational parameter (km^3/s^2) and equatorial radius (km). SGP4 uses WGS72, so
 * the mean altitude derived from an element set's mean motion uses the same constants.
 */
export const WGS72_MU_KM3_S2 = 398600.8;
export const WGS72_RADIUS_KM = 6378.135;

export const MS_PER_DAY = 86_400_000;
export const DEG = Math.PI / 180;

/** Unix time (ms) -> Julian Date (UTC). JD 2440587.5 is 1970-01-01T00:00:00Z. */
export function julianDateFromMs(ms: number): number {
  return ms / MS_PER_DAY + 2440587.5;
}

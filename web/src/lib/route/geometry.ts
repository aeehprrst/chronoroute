/**
 * Geometry of the route planner: WGS84 frames, elevation angles, the 80 km grazing test and
 * light time. A line-by-line port of the Python reference, so the browser decides what Python
 * decides, up to last-bit (one ulp) differences between the two maths libraries:
 *
 *   sim/chronoroute/orbit/frames.py    geodetic <-> ECEF (WGS84), elevation, TEME -> ECEF
 *   sim/chronoroute/topo/geometry.py   closest approach, golden-section height, light time
 *
 * Why the arithmetic is written so carefully: the parity test (tests/route-parity.test.ts)
 * runs this code on the very positions Python used and expects the same links, the same
 * integer delays and the same path. Floating-point sums give slightly different answers
 * when their terms are added in a different order, so every formula below adds its terms
 * in the order numpy does (measured with numpy 2.5.3):
 *
 *   np.radians(x)                    x * (pi / 180)          (not x * pi / 180)
 *   np.degrees(x)                    x * (180 / pi)
 *   np.linalg.norm(v, axis=-1)       sqrt((x*x + y*y) + z*z)
 *   np.einsum('...i,...i->...')      (a0*b0 + a2*b2) + a1*b1  (numpy pairs elements 0 and 2)
 *
 * The order of operations is ours to choose; the sin, cos, atan2, asin and sqrt results are not.
 * V8's Math.sin/Math.cos are not guaranteed to round exactly like numpy's (glibc's) functions,
 * so results can differ in the last bit. Measured on the 60 cities: geodeticToEcef matches
 * Python bit for bit for 55; Frankfurt, Los Angeles, Paris, Riyadh and Tokyo differ by one ulp
 * in one coordinate (Paris z: 4780.962108418493 here, ...492 in Python). Such a difference can
 * only change a decision for a value sitting within an ulp of a threshold (25 deg, 80 km,
 * 70 deg, or half a nanosecond). The parity gate therefore runs on Python's positions for the
 * satellites AND the cities (tests/parity-gate.ts), and compares this conversion separately
 * with a 1e-9 km tolerance.
 *
 * Units: km, radians inside, degrees at the edges. All REAL physics (WGS84 is the GPS datum;
 * the speed of light is exact by definition), applied by our code.
 */

/** WGS84 semi-major axis a (km). */
export const WGS84_A_KM = 6378.137;
/** WGS84 flattening f. */
export const WGS84_F = 1.0 / 298.257223563;
/** WGS84 semi-minor axis b = a (1 - f) (km). */
export const WGS84_B_KM = WGS84_A_KM * (1.0 - WGS84_F);
/** First eccentricity squared e^2 = f (2 - f). */
export const WGS84_E2 = WGS84_F * (2.0 - WGS84_F);

/** Speed of light (m/s), exact by the SI definition of the metre. */
export const C_M_PER_S = 299_792_458;
/** Per-hop processing delay (ns): the existing model's 0.5 ms. MODELLED. */
export const PROCESSING_NS = 500_000;
/** Laser links must clear the WGS84 ellipsoid by this much (km): Hypatia's rule. */
export const MIN_GRAZING_ALT_KM = 80.0;
/** Golden-section steps for the exact height test (as topo/geometry.py). */
export const GOLDEN_STEPS = 80;
const INV_PHI = (Math.sqrt(5.0) - 1.0) / 2.0;

const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;

export type Vec3 = readonly [number, number, number];

export function radians(deg: number): number {
  return deg * DEG2RAD;
}

export function degrees(rad: number): number {
  return rad * RAD2DEG;
}

/** numpy's batched einsum dot product order: (a0*b0 + a2*b2) + a1*b1. */
export function dot3(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[2] * b[2] + a[1] * b[1];
}

/** numpy's norm order: sqrt((x*x + y*y) + z*z). */
export function norm3(x: number, y: number, z: number): number {
  return Math.sqrt(x * x + y * y + z * z);
}

/** WGS84 latitude/longitude (degrees) and ellipsoidal height (km) -> ECEF km (frames.geodetic_to_ecef). */
export function geodeticToEcef(latDeg: number, lonDeg: number, heightKm = 0.0): [number, number, number] {
  const lat = radians(latDeg);
  const lon = radians(lonDeg);
  const sinLat = Math.sin(lat);
  const n = WGS84_A_KM / Math.sqrt(1.0 - WGS84_E2 * sinLat * sinLat); // prime-vertical radius
  const x = (n + heightKm) * Math.cos(lat) * Math.cos(lon);
  const y = (n + heightKm) * Math.cos(lat) * Math.sin(lon);
  const z = (n * (1.0 - WGS84_E2) + heightKm) * sinLat;
  return [x, y, z];
}

export interface Geodetic {
  latDeg: number;
  lonDeg: number;
  heightKm: number;
}

/**
 * ECEF km -> WGS84 latitude, longitude (degrees) and height (km): Bowring's iteration, six
 * rounds, exactly as frames.ecef_to_geodetic.
 */
export function ecefToGeodetic(x: number, y: number, z: number, iterations = 6): Geodetic {
  const p = Math.hypot(x, y);
  const lon = Math.atan2(y, x);
  let lat = Math.atan2(z, p * (1.0 - WGS84_E2)); // first guess
  for (let i = 0; i < iterations; i += 1) {
    const s = Math.sin(lat);
    const n = WGS84_A_KM / Math.sqrt(1.0 - WGS84_E2 * s * s);
    lat = Math.atan2(z + WGS84_E2 * n * s, p);
  }
  const sinLat = Math.sin(lat);
  const cosLat = Math.cos(lat);
  // Height formula that stays accurate both near the equator and near the poles.
  const height = p * cosLat + z * sinLat - WGS84_A_KM * Math.sqrt(1.0 - WGS84_E2 * sinLat * sinLat);
  return { latDeg: degrees(lat), lonDeg: degrees(lon), heightKm: height };
}

/** Height above WGS84 (km) of the point a + t d. */
function heightAlong(a: Vec3, d: Vec3, t: number): number {
  return ecefToGeodetic(a[0] + t * d[0], a[1] + t * d[1], a[2] + t * d[2]).heightKm;
}

/**
 * Elevation angle (degrees above the local WGS84 horizon) of `target` seen from a ground
 * point at geodetic latitude/longitude (frames.elevation_deg). "Up" is the ellipsoid normal,
 * which is what an antenna's elevation mask refers to.
 */
export function elevationDeg(ground: Vec3, target: Vec3, groundLatDeg: number, groundLonDeg: number): number {
  const lat = radians(groundLatDeg);
  const lon = radians(groundLonDeg);
  const up: Vec3 = [Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)];
  const d: Vec3 = [target[0] - ground[0], target[1] - ground[1], target[2] - ground[2]];
  const dist = norm3(d[0], d[1], d[2]);
  const sinEl = dot3(d, up) / dist;
  return degrees(Math.asin(Math.min(1.0, Math.max(-1.0, sinEl))));
}

/** Distance (km) between two ECEF points, in numpy's order. */
export function distanceKm(a: Vec3, b: Vec3): number {
  return norm3(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
}

/**
 * Light time over distKm, rounded to the NEAREST integer nanosecond (halves up):
 * floor(d_km * 1e12 / c + 0.5), the one formula every implementation uses
 * (topo/geometry.propagation_ns). -1 for a missing distance (NaN).
 */
export function propagationNs(distKm: number): number {
  const out = Math.floor((distKm * 1e12) / C_M_PER_S + 0.5);
  return Number.isFinite(out) ? out : -1;
}

/** distance / c in ns as a float (for checks only, never for routing). */
export function lightTimeNsExact(distKm: number): number {
  return (distKm * 1e12) / C_M_PER_S;
}

/** Smallest distance from the Earth's centre to the segment a -> b, and where it is (t in [0, 1]). */
export function closestApproach(a: Vec3, b: Vec3): { rMinKm: number; t: number } {
  const d: Vec3 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const dd = dot3(d, d);
  const num = -dot3(a, d);
  let t = dd > 0.0 ? num / dd : 0.0;
  t = Math.min(1.0, Math.max(0.0, t)); // np.clip (NaN stays NaN in both)
  const q0 = a[0] + t * d[0];
  const q1 = a[1] + t * d[1];
  const q2 = a[2] + t * d[2];
  return { rMinKm: norm3(q0, q1, q2), t };
}

/**
 * Exact lowest height (km above WGS84) of the straight segment a -> b: golden-section search
 * on the geodetic height along the segment, plus the two end points (geometry.segment_min_height_km).
 */
export function segmentMinHeightKm(a: Vec3, b: Vec3, steps = GOLDEN_STEPS): number {
  const d: Vec3 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  let lo = 0.0;
  let hi = 1.0;
  let x1 = hi - INV_PHI * (hi - lo);
  let x2 = lo + INV_PHI * (hi - lo);
  let h1 = heightAlong(a, d, x1);
  let h2 = heightAlong(a, d, x2);
  for (let i = 0; i < steps; i += 1) {
    const left = h1 <= h2; // the minimum is in [lo, x2]
    if (left) hi = x2;
    else lo = x1;
    const newX1 = hi - INV_PHI * (hi - lo);
    const newX2 = lo + INV_PHI * (hi - lo);
    // keep the point we already know, evaluate only the new one
    const hNew = heightAlong(a, d, left ? newX1 : newX2);
    if (left) {
      x2 = x1;
      h2 = h1;
      x1 = newX1;
      h1 = hNew;
    } else {
      x1 = x2;
      h1 = h2;
      x2 = newX2;
      h2 = hNew;
    }
  }
  const ends = Math.min(heightAlong(a, d, 0.0), heightAlong(a, d, 1.0));
  return Math.min(Math.min(h1, h2), ends);
}

/**
 * True when the whole segment a -> b stays at least minAltKm above WGS84 (geometry.segment_clears).
 * The surface lies between the spheres of radius b and a, so the closest approach r_min decides
 * almost every segment: r_min - a >= 80 certainly clears, r_min - b < 80 certainly fails; only
 * the 21 km band in between needs the exact golden-section height. NaN input gives false.
 */
export function segmentClears(a: Vec3, b: Vec3, minAltKm = MIN_GRAZING_ALT_KM): boolean {
  const { rMinKm } = closestApproach(a, b);
  if (!Number.isFinite(rMinKm)) return false;
  if (rMinKm - WGS84_A_KM >= minAltKm) return true;
  if (rMinKm - WGS84_B_KM < minAltKm) return false;
  return segmentMinHeightKm(a, b) >= minAltKm;
}

/**
 * TEME -> ECEF for a position: r_ecef = R3(gmst) r_teme (frames.teme_to_ecef; UT1 = UTC, no
 * polar motion, the same simplification as the Python model).
 */
export function temeToEcef(x: number, y: number, z: number, gmstRad: number): [number, number, number] {
  const c = Math.cos(gmstRad);
  const s = Math.sin(gmstRad);
  return [c * x + s * y, -s * x + c * y, z];
}

/** Great-circle distance (km) on a sphere of the IUGG mean radius (data/cities.great_circle_km). */
export function greatCircleKm(latADeg: number, lonADeg: number, latBDeg: number, lonBDeg: number): number {
  const r = 6371.0088;
  const lat1 = radians(latADeg);
  const lon1 = radians(lonADeg);
  const lat2 = radians(latBDeg);
  const lon2 = radians(lonBDeg);
  const sLat = Math.sin((lat2 - lat1) / 2);
  const sLon = Math.sin((lon2 - lon1) / 2);
  // numpy squares with x * x; written out so no pow() rounding can differ.
  const h = sLat * sLat + Math.cos(lat1) * Math.cos(lat2) * (sLon * sLon);
  return 2 * r * Math.asin(Math.sqrt(h));
}

/**
 * Earth surface geometry in Earth-local scene axes (ECEF mapped as in frames.ts).
 *
 * The mesh is the WGS84 ellipsoid (equatorial radius 1, polar radius 0.996647), built from a
 * three.js SphereGeometry. Texture coordinates are set so that each vertex samples the
 * equirectangular texture at its own GEODETIC latitude and longitude, which is how NASA's
 * Blue Marble and Black Marble maps are gridded (longitude -180 at the left edge, latitude +90
 * at the top). Normals are the ellipsoid normals (the geodetic "up" direction).
 *
 * Mapping, checked in frames.test.ts for Greenwich, Chennai, New York and Sydney:
 *   u = (longitude + 180) / 360,  v = (latitude + 90) / 180   (v = 1 at the top row; flipY)
 */
import { SphereGeometry, type BufferGeometry } from 'three';
import { geodeticToEcf } from './sgp4';
import { DEG, EARTH_EQUATORIAL_RADIUS_KM, EARTH_POLAR_SCALE } from './constants';
import { kmToScene, type Vec3 } from './frames';

/** Earth-local scene position of a point at geodetic latitude/longitude (degrees) and height (km) on WGS84. */
export function geodeticToScene(latDeg: number, lonDeg: number, heightKm = 0): Vec3 {
  return kmToScene(geodeticToEcf({ latitude: latDeg * DEG, longitude: lonDeg * DEG, height: heightKm }));
}

/**
 * Geodetic latitude/longitude (degrees) of a point on the surface of the scene ellipsoid
 * (Earth-local axes). Uses tan(geodetic) = tan(parametric) * a / b.
 */
export function sceneSurfaceToGeodetic(p: Vec3): { latDeg: number; lonDeg: number } {
  // Undo the axis mapping: ECEF x = scene x, ECEF y = -scene z, ECEF z = scene y.
  const ex = p.x;
  const ey = -p.z;
  const ez = p.y;
  const lonDeg = Math.atan2(ey, ex) / DEG;
  const rho = Math.hypot(ex, ey);
  // Parametric latitude beta: (rho, ez) = (cos beta, b sin beta) with a = 1, b = EARTH_POLAR_SCALE.
  const beta = Math.atan2(ez / EARTH_POLAR_SCALE, rho);
  const latDeg = Math.atan2(Math.sin(beta), Math.cos(beta) * EARTH_POLAR_SCALE) / DEG;
  return { latDeg, lonDeg };
}

/** Texture coordinates (u, v) of a geodetic position on an equirectangular map, three.js convention (v = 1 at the top). */
export function geodeticToUv(latDeg: number, lonDeg: number): { u: number; v: number } {
  let u = (lonDeg + 180) / 360;
  if (u >= 1) u -= 1;
  if (u < 0) u += 1;
  return { u, v: (latDeg + 90) / 180 };
}

/** Build the ellipsoid geometry. Segments: 192 x 96 on desktop is plenty for a sphere this smooth. */
export function createEarthGeometry(widthSegments = 192, heightSegments = 96): BufferGeometry {
  const geometry = new SphereGeometry(1, widthSegments, heightSegments);
  const pos = geometry.getAttribute('position');
  const uv = geometry.getAttribute('uv');
  const normal = geometry.getAttribute('normal');
  const b = EARTH_POLAR_SCALE;
  for (let i = 0; i < pos.count; i += 1) {
    const x = pos.getX(i);
    const y = pos.getY(i);
    const z = pos.getZ(i);
    // SphereGeometry gives a unit sphere; its polar angle is the parametric latitude beta.
    // Squash to the ellipsoid: (x, b*y, z).
    pos.setY(i, y * b);
    // Geodetic latitude of that ellipsoid point: tan(phi) = tan(beta) / b.
    const beta = Math.asin(Math.max(-1, Math.min(1, y)));
    const phi = Math.atan2(Math.sin(beta), Math.cos(beta) * b);
    uv.setY(i, (phi / DEG + 90) / 180);
    // Ellipsoid normal (x / a^2, y / b^2, z / a^2) at the squashed point (x, b*y, z).
    const nx = x;
    const ny = (y * b) / (b * b);
    const nz = z;
    const len = Math.hypot(nx, ny, nz) || 1;
    normal.setXYZ(i, nx / len, ny / len, nz / len);
  }
  pos.needsUpdate = true;
  uv.needsUpdate = true;
  normal.needsUpdate = true;
  geometry.computeBoundingSphere();
  return geometry;
}

/** Reference places used to check the texture orientation (REAL coordinates, WGS84). */
export const REFERENCE_CITIES = [
  { name: 'Greenwich', latDeg: 51.4779, lonDeg: -0.0015 },
  { name: 'Chennai', latDeg: 13.0827, lonDeg: 80.2707 },
  { name: 'New York', latDeg: 40.7128, lonDeg: -74.006 },
  { name: 'Sydney', latDeg: -33.8688, lonDeg: 151.2093 },
] as const;

/** Earth radius (km) used to convert scene units back to kilometres in labels. */
export const SCENE_UNIT_KM = EARTH_EQUATORIAL_RADIUS_KM;

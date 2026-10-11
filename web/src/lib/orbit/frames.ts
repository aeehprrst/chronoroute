/**
 * Reference frames for the globe.
 *
 * World frame of the 3D scene = Earth-centred inertial. SGP4 (satellite.js) returns positions
 * in TEME, a true-equator, mean-equinox inertial frame; we draw it directly, so orbital planes
 * stay fixed in the scene (apart from their slow real precession) and the Earth turns under them.
 *
 * Axes: three.js is Y-up, so ECI/ECEF axes map to scene axes as
 *     scene.x =  X,   scene.y = Z (north pole),   scene.z = -Y
 * which is a proper rotation (determinant +1, -90 degrees about X), and positions are divided
 * by the WGS84 equatorial radius (1 scene unit = 6378.137 km).
 *
 * The Earth mesh and everything fixed to the ground (city markers) live in an "Earth-local"
 * group whose axes are ECEF mapped the same way. That group is rotated about the scene Y axis
 * by GMST, because TEME -> PEF (pseudo Earth-fixed) is a rotation about Z by -GMST (Vallado,
 * Crawford, Hujsak and Kelso, "Revisiting Spacetrack Report #3", AIAA 2006-6753; polar motion
 * of about 10 m is ignored). Rotating a scene vector about +Y by GMST equals rotating the
 * ECI vector about +Z by GMST, i.e. ECEF -> ECI. This is verified in frames.test.ts against
 * satellite.js ecfToEci.
 */
import { gstime } from './sgp4';
import { EARTH_EQUATORIAL_RADIUS_KM } from './constants';

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/** Greenwich mean sidereal time (IAU 1982, as used by SGP4) in radians, [0, 2 pi). UTC is used for UT1 (|UT1 - UTC| < 0.9 s, under 0.004 degrees). */
export function gmstRad(ms: number): number {
  return gstime(new Date(ms));
}

/** ECI/TEME (or ECEF) kilometres -> scene units with the axis mapping above. */
export function kmToScene(v: Vec3): Vec3 {
  const k = 1 / EARTH_EQUATORIAL_RADIUS_KM;
  return { x: v.x * k, y: v.z * k, z: -v.y * k };
}

/** Inverse of kmToScene: scene units -> kilometres in ECI/ECEF axes. */
export function sceneToKm(v: Vec3): Vec3 {
  const k = EARTH_EQUATORIAL_RADIUS_KM;
  return { x: v.x * k, y: -v.z * k, z: v.y * k };
}

/**
 * Write one ECI position (km, Float64 inputs) into a Float32Array at slot `index`, in scene
 * units and axes. The conversion is done in double precision before the single rounding to
 * float32 (about 0.8 m of resolution at LEO radius).
 */
export function writeSceneFromKm(out: Float32Array, index: number, x: number, y: number, z: number): void {
  const k = 1 / EARTH_EQUATORIAL_RADIUS_KM;
  const o = index * 3;
  out[o] = x * k;
  out[o + 1] = z * k;
  out[o + 2] = -y * k;
}

/** Rotate a scene vector about the scene +Y axis by `angle` radians (three.js Object3D.rotation.y convention). */
export function rotateSceneY(v: Vec3, angle: number): Vec3 {
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  return { x: v.x * c + v.z * s, y: v.y, z: -v.x * s + v.z * c };
}

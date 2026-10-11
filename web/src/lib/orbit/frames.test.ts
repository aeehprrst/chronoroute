/**
 * Frames and Earth orientation: GMST, the ECI/ECEF -> scene mapping, the GMST rotation of the
 * Earth group, and the texture placement of reference cities.
 */
import { describe, expect, it } from 'vitest';
import { ecfToEci, geodeticToEcf, gstime } from 'satellite.js';
import { SphereGeometry } from 'three';
import { DEG } from './constants';
import { gmstRad, kmToScene, rotateSceneY, sceneToKm } from './frames';
import {
  REFERENCE_CITIES,
  createEarthGeometry,
  geodeticToScene,
  geodeticToUv,
  sceneSurfaceToGeodetic,
} from './earth-geometry';

const close = (a: { x: number; y: number; z: number }, b: { x: number; y: number; z: number }, tol: number) =>
  Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z) < tol;

describe('GMST', () => {
  it('is 349.04 degrees at 2026-09-10T00:00Z', () => {
    // IAU 1982 formula by hand: T = (2461293.5 - 2451545) / 36525 = 0.2668994;
    // GMST = 100.4606184 + 36000.77004 T + 0.000387933 T^2 = 9709.04397 = 349.044 deg (mod 360).
    const deg = gmstRad(Date.parse('2026-09-10T00:00:00Z')) / DEG;
    expect(Math.abs(deg - 349.04)).toBeLessThan(0.01);
    expect(Math.abs(deg - 349.044)).toBeLessThan(0.001);
  });

  it('matches satellite.js gstime', () => {
    const ms = Date.parse('2026-10-10T14:02:22Z');
    expect(gmstRad(ms)).toBe(gstime(new Date(ms)));
  });
});

describe('scene axes', () => {
  it('maps ECI x -> scene x, ECI z (north) -> scene y, ECI y -> scene -z, and back', () => {
    expect(close(kmToScene({ x: 6378.137, y: 0, z: 0 }), { x: 1, y: 0, z: 0 }, 1e-15)).toBe(true);
    expect(close(kmToScene({ x: 0, y: 6378.137, z: 0 }), { x: 0, y: 0, z: -1 }, 1e-15)).toBe(true);
    expect(close(kmToScene({ x: 0, y: 0, z: 6378.137 }), { x: 0, y: 1, z: 0 }, 1e-15)).toBe(true);
    const v = { x: 1234.5, y: -6000.25, z: 3000.75 };
    expect(close(sceneToKm(kmToScene(v)), v, 1e-9)).toBe(true);
  });

  it('is right-handed: scene(x) cross scene(y) = scene(z) for ECI x, y, z', () => {
    const R = 6378.137;
    const ex = kmToScene({ x: R, y: 0, z: 0 });
    const ey = kmToScene({ x: 0, y: R, z: 0 });
    const ez = kmToScene({ x: 0, y: 0, z: R });
    const cross = {
      x: ex.y * ey.z - ex.z * ey.y,
      y: ex.z * ey.x - ex.x * ey.z,
      z: ex.x * ey.y - ex.y * ey.x,
    };
    expect(close(cross, ez, 1e-12)).toBe(true);
  });

  it('rotating the Earth group by +GMST about scene Y equals satellite.js ECEF -> ECI', () => {
    for (const iso of ['2026-09-10T00:00:00Z', '2026-10-10T14:02:22Z', '2026-12-31T23:59:59Z']) {
      const gmst = gmstRad(Date.parse(iso));
      for (const city of REFERENCE_CITIES) {
        const ecf = geodeticToEcf({ latitude: city.latDeg * DEG, longitude: city.lonDeg * DEG, height: 0 });
        const viaGroup = rotateSceneY(kmToScene(ecf), gmst);
        const viaSatelliteJs = kmToScene(ecfToEci(ecf, gmst));
        expect(close(viaGroup, viaSatelliteJs, 1e-12)).toBe(true);
      }
    }
  });
});

describe('Earth texture placement', () => {
  it('places Greenwich, Chennai, New York and Sydney on their own texture pixels', () => {
    for (const city of REFERENCE_CITIES) {
      const p = geodeticToScene(city.latDeg, city.lonDeg);
      const back = sceneSurfaceToGeodetic(p);
      expect(back.latDeg).toBeCloseTo(city.latDeg, 9);
      expect(back.lonDeg).toBeCloseTo(city.lonDeg, 9);
    }
    // Hemisphere checks in Earth-local scene axes (prime meridian +x, 90 E is -z, north +y).
    const greenwich = geodeticToScene(51.4779, -0.0015);
    expect(greenwich.x).toBeGreaterThan(0.6);
    expect(greenwich.y).toBeGreaterThan(0.7);
    expect(Math.abs(greenwich.z)).toBeLessThan(0.001);
    const chennai = geodeticToScene(13.0827, 80.2707);
    expect(chennai.z).toBeLessThan(-0.9); // east of Greenwich by 80 degrees: towards -z
    const newYork = geodeticToScene(40.7128, -74.006);
    expect(newYork.z).toBeGreaterThan(0.7); // west: +z
    const sydney = geodeticToScene(-33.8688, 151.2093);
    expect(sydney.y).toBeLessThan(-0.5);
    expect(sydney.x).toBeLessThan(-0.7);
    // Texture coordinates of the cities on the equirectangular map.
    expect(geodeticToUv(0, 0)).toEqual({ u: 0.5, v: 0.5 });
    expect(geodeticToUv(13.0827, 80.2707).u).toBeCloseTo((80.2707 + 180) / 360, 12);
  });

  it('gives every Earth mesh vertex the uv of its own geodetic latitude and longitude', () => {
    const geometry = createEarthGeometry(72, 36);
    const pos = geometry.getAttribute('position');
    const uv = geometry.getAttribute('uv');
    const normal = geometry.getAttribute('normal');
    let checked = 0;
    for (let i = 0; i < pos.count; i += 1) {
      const p = { x: pos.getX(i), y: pos.getY(i), z: pos.getZ(i) };
      const { latDeg, lonDeg } = sceneSurfaceToGeodetic(p);
      expect(uv.getY(i)).toBeCloseTo((latDeg + 90) / 180, 6);
      if (Math.abs(latDeg) < 89.9) {
        // Away from the poles the longitude is defined; u = 0 and u = 1 are the same seam.
        const expectedU = (lonDeg + 180) / 360;
        const du = Math.abs(uv.getX(i) - expectedU);
        expect(Math.min(du, Math.abs(du - 1))).toBeLessThan(1e-6);
        // The vertex lies on the WGS84 ellipsoid where the city formula would put that lat/lon.
        expect(close(p, geodeticToScene(latDeg, lonDeg), 1e-6)).toBe(true);
        // The normal is the geodetic "up": it has the vertex's geodetic latitude (to float32 precision).
        const n = { x: normal.getX(i), y: normal.getY(i), z: normal.getZ(i) };
        expect(Math.abs(Math.asin(n.y) / DEG - latDeg)).toBeLessThan(1e-3);
        checked += 1;
      }
    }
    expect(checked).toBeGreaterThan(2000);
  });

  it('starts from three.js SphereGeometry with u = 0 at longitude -180 (the -x side)', () => {
    // Guard against a three.js change in the sphere's uv layout, which the mapping relies on.
    const sphere = new SphereGeometry(1, 8, 4);
    const pos = sphere.getAttribute('position');
    const uv = sphere.getAttribute('uv');
    for (let i = 0; i < pos.count; i += 1) {
      const u = uv.getX(i);
      const y = pos.getY(i);
      if (Math.abs(y) > 0.999) continue;
      const lon = Math.atan2(-pos.getZ(i), pos.getX(i)) / DEG; // ECEF y = -scene z
      const expected = (lon + 180) / 360;
      const du = Math.abs(u - expected);
      expect(Math.min(du, Math.abs(du - 1))).toBeLessThan(1e-9);
    }
  });
});

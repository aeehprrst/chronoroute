/**
 * SGP4 propagation of the whole snapshot with satellite.js. Shared by the Web Worker and the
 * tests, so the tested code is the code that runs in the browser.
 *
 * Positions are computed in double precision (km, TEME), converted to scene units in double
 * precision, and only then written to a Float32Array for the GPU.
 */
import { eciToGeodetic, json2satrec, propagate, type SatRec } from './sgp4';
import type { OmmRecord } from '../data-types';
import { gmstRad, writeSceneFromKm } from './frames';

export interface InitError {
  /** Row index in the snapshot. */
  index: number;
  norad: number;
  name: string;
  /** satellite.js error code (satrec.error), or -1 if json2satrec threw. */
  code: number;
  message: string;
}

export interface SatrecSet {
  /** One entry per snapshot row; null where initialisation failed (never silently dropped: see errors). */
  satrecs: Array<SatRec | null>;
  errors: InitError[];
}

/** satellite.js SatRecError codes (SGP4 "error" values, Vallado 2006). */
const SGP4_ERRORS: Record<number, string> = {
  1: 'mean eccentricity out of range',
  2: 'mean motion below zero',
  3: 'perturbed eccentricity out of range',
  4: 'semi-latus rectum below zero',
  6: 'orbit has decayed',
};

export function sgp4ErrorText(code: number): string {
  return SGP4_ERRORS[code] ?? `SGP4 error ${code}`;
}

/** json2satrec for every record. Failures are kept as null and listed in `errors`. */
export function initSatrecs(records: readonly OmmRecord[]): SatrecSet {
  const satrecs: Array<SatRec | null> = new Array<SatRec | null>(records.length).fill(null);
  const errors: InitError[] = [];
  records.forEach((record, index) => {
    try {
      const satrec = json2satrec(record);
      if (satrec.error !== 0) {
        errors.push({
          index,
          norad: record.NORAD_CAT_ID,
          name: record.OBJECT_NAME,
          code: satrec.error,
          message: sgp4ErrorText(satrec.error),
        });
        return;
      }
      satrecs[index] = satrec;
    } catch (error) {
      errors.push({
        index,
        norad: record.NORAD_CAT_ID,
        name: record.OBJECT_NAME,
        code: -1,
        message: error instanceof Error ? error.message : String(error),
      });
    }
  });
  return { satrecs, errors };
}

/** Propagate one satellite to Unix time `ms`. Returns TEME km / km/s, or null on any SGP4 error or non-finite result. */
export function propagateKm(
  satrec: SatRec,
  ms: number,
): { r: { x: number; y: number; z: number }; v: { x: number; y: number; z: number } } | null {
  const state = propagate(satrec, new Date(ms));
  if (!state) return null;
  const { position: r, velocity: v } = state;
  if (!Number.isFinite(r.x) || !Number.isFinite(r.y) || !Number.isFinite(r.z)) return null;
  return { r, v };
}

/**
 * Propagate every satellite to `ms` and write scene positions into `out` (3 floats per row).
 * Rows that are null or fail at this instant are written as (0, 0, 0), which the shader hides.
 * Returns the number of rows that failed at this instant (initialisation failures excluded).
 */
export function propagateAllToScene(satrecs: ReadonlyArray<SatRec | null>, ms: number, out: Float32Array): number {
  let failed = 0;
  const date = new Date(ms);
  for (let i = 0; i < satrecs.length; i += 1) {
    const satrec = satrecs[i];
    if (!satrec) {
      writeSceneFromKm(out, i, 0, 0, 0);
      continue;
    }
    const state = propagate(satrec, date);
    const r = state?.position;
    if (!r || !Number.isFinite(r.x) || !Number.isFinite(r.y) || !Number.isFinite(r.z)) {
      writeSceneFromKm(out, i, 0, 0, 0);
      failed += 1;
      continue;
    }
    writeSceneFromKm(out, i, r.x, r.y, r.z);
  }
  return failed;
}

/**
 * Propagate every satellite to `ms` and write TEME positions in km, Float64 (3 per row), for
 * the route planner, which needs full precision (the globe's Float32 scene units are not
 * enough for integer-nanosecond delays). Rows that are null or fail are written as NaN, so a
 * failed satellite can never be used as if it were at the origin. Returns the failure count.
 */
export function propagateAllTemeKm(satrecs: ReadonlyArray<SatRec | null>, ms: number, out: Float64Array): number {
  let failed = 0;
  for (let i = 0; i < satrecs.length; i += 1) {
    const satrec = satrecs[i];
    const state = satrec ? propagateKm(satrec, ms) : null;
    if (!state) {
      out[3 * i] = Number.NaN;
      out[3 * i + 1] = Number.NaN;
      out[3 * i + 2] = Number.NaN;
      if (satrec) failed += 1;
      continue;
    }
    out[3 * i] = state.r.x;
    out[3 * i + 1] = state.r.y;
    out[3 * i + 2] = state.r.z;
  }
  return failed;
}

export interface SatelliteNow {
  /** Height above the WGS84 ellipsoid (km). */
  altitudeKm: number;
  /** Geodetic latitude and longitude of the sub-satellite point (degrees). */
  latDeg: number;
  lonDeg: number;
  /** Speed in the inertial frame (km/s). */
  speedKmS: number;
}

/** Altitude, sub-satellite point and speed at `ms`, or null if SGP4 fails at that instant. */
export function satelliteNow(satrec: SatRec, ms: number): SatelliteNow | null {
  const state = propagateKm(satrec, ms);
  if (!state) return null;
  const geo = eciToGeodetic(state.r, gmstRad(ms));
  return {
    altitudeKm: geo.height,
    latDeg: (geo.latitude * 180) / Math.PI,
    lonDeg: (geo.longitude * 180) / Math.PI,
    speedKmS: Math.hypot(state.v.x, state.v.y, state.v.z),
  };
}

/** Orbital period (minutes) from the satrec's mean motion (rad/min). */
export function periodMinutes(satrec: SatRec): number {
  return (2 * Math.PI) / satrec.no;
}

/**
 * Sample one orbital period of positions centred on `centerMs` (scene units), for drawing the
 * selected satellite's orbit. Points where SGP4 fails are skipped. Returns the samples and the
 * time span covered.
 */
export function orbitTrackToScene(
  satrec: SatRec,
  centerMs: number,
  samples = 180,
): { points: Float32Array; startMs: number; endMs: number } {
  const periodMs = periodMinutes(satrec) * 60_000;
  const startMs = centerMs - periodMs / 2;
  const step = periodMs / samples;
  const tmp = new Float32Array((samples + 1) * 3);
  let n = 0;
  for (let k = 0; k <= samples; k += 1) {
    const state = propagateKm(satrec, startMs + k * step);
    if (!state) continue;
    writeSceneFromKm(tmp, n, state.r.x, state.r.y, state.r.z);
    n += 1;
  }
  return { points: tmp.slice(0, n * 3), startMs, endMs: startMs + periodMs };
}

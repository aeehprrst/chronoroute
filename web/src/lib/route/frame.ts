/**
 * The browser's positions frame: SGP4 TEME positions (Float64, from the orbit worker or from
 * propagateAllTemeKm) rotated into ECEF by GMST, exactly the rotation the Python model uses
 * (frames.teme_to_ecef: UT1 = UTC, no polar motion).
 */
import { gmstRad } from '../orbit/frames';
import { temeToEcef } from './geometry';
import type { PositionFrame } from './topology';

/** TEME km (3 per satellite, NaN = failed) at Unix time `ms` -> ECEF frame. */
export function ecefFrameFromTeme(temeKm: Float64Array, ms: number): PositionFrame {
  const gmst = gmstRad(ms);
  const ecefKm = new Float64Array(temeKm.length);
  for (let i = 0; i < temeKm.length; i += 3) {
    const [x, y, z] = temeToEcef(temeKm[i]!, temeKm[i + 1]!, temeKm[i + 2]!, gmst);
    ecefKm[i] = x;
    ecefKm[i + 1] = y;
    ecefKm[i + 2] = z;
  }
  return { ecefKm };
}

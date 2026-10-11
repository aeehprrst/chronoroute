/**
 * Grouping of satellites into "shells" for colouring the globe. DERIVED: our grouping by
 * inclination and mean altitude, computed from the public orbital elements. It is not
 * SpaceX's shell list, which is not published in this form.
 *
 * Bands seen in the 2026-10-10 snapshot (inclination, rounded): 43 deg, 53 deg (53.0-53.2),
 * 70 deg, 97.3-97.6 deg, and a few at 30.5 deg. Satellites whose mean altitude is below
 * 450 km are put in their own group whatever their inclination: one element set cannot
 * tell orbit raising after launch, lowering, deorbiting or a lower operational shell apart.
 */
import { WGS72_MU_KM3_S2, EARTH_EQUATORIAL_RADIUS_KM } from './constants';

export type ShellId = 0 | 1 | 2 | 3 | 4 | 5;

export interface ShellInfo {
  id: ShellId;
  key: 'inc43' | 'inc53' | 'inc70' | 'inc97' | 'other' | 'low';
  /** Short legend label. */
  label: string;
  /** One-line explanation for the legend. */
  detail: string;
  /** Display colour (sRGB hex). Chosen for contrast on the dark background, not from SpaceX material. */
  color: string;
}

/** Legend order. The index is the ShellId used in the GPU attribute. */
export const SHELLS: readonly ShellInfo[] = [
  { id: 0, key: 'inc53', label: '53°', detail: 'Inclination 51.5° to 54.5°', color: '#6fb1ff' },
  { id: 1, key: 'inc43', label: '43°', detail: 'Inclination 41.5° to 44.5°', color: '#4fd1c5' },
  { id: 2, key: 'inc70', label: '70°', detail: 'Inclination 68.5° to 71.5°', color: '#ece27e' },
  { id: 3, key: 'inc97', label: '97–98°', detail: 'Inclination 96.5° to 98.5° (near-polar)', color: '#e39cf5' },
  { id: 4, key: 'other', label: 'Other', detail: 'Any other inclination', color: '#c3cddb' },
  {
    id: 5,
    key: 'low',
    label: 'Below 450 km',
    detail: 'Mean altitude under 450 km, any inclination: raising, lowering, deorbiting or a lower shell',
    color: '#ff9a7a',
  },
];

/** Mean altitude threshold (km) below which a satellite goes into the "Below 450 km" group. */
export const LOW_ALTITUDE_KM = 450;

/**
 * Mean altitude above the equatorial radius (km) from the OMM mean motion (rev/day), using
 * Kepler's third law with the WGS72 constants of SGP4. This is the semi-major axis minus
 * 6378.137 km: a grouping value, not the altitude at any instant (the globe computes that
 * with SGP4).
 */
export function meanAltitudeKm(meanMotionRevPerDay: number): number {
  const n = (meanMotionRevPerDay * 2 * Math.PI) / 86_400; // rad/s
  const a = Math.cbrt(WGS72_MU_KM3_S2 / (n * n));
  return a - EARTH_EQUATORIAL_RADIUS_KM;
}

/** Shell group for one element set. */
export function classifyShell(inclinationDeg: number, meanMotionRevPerDay: number): ShellId {
  if (meanAltitudeKm(meanMotionRevPerDay) < LOW_ALTITUDE_KM) return 5;
  const i = inclinationDeg;
  if (i >= 51.5 && i <= 54.5) return 0;
  if (i >= 41.5 && i <= 44.5) return 1;
  if (i >= 68.5 && i <= 71.5) return 2;
  if (i >= 96.5 && i <= 98.5) return 3;
  return 4;
}

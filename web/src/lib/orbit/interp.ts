/**
 * Interpolation between two propagated frames A and B (positions at times tA < tB).
 *
 * The vertex shader and the CPU (picking, the selection marker) use the same rule:
 * spherical interpolation of the direction and linear interpolation of the radius. For a
 * near-circular orbit this follows the orbit arc, whereas a straight mix(posA, posB, alpha)
 * would cut the chord: at 600x speed frames are 600 s of orbit apart (about 38 degrees of arc)
 * and the chord midpoint would sit about 370 km below the orbit. interp.test.ts checks the
 * rule against SGP4 itself.
 *
 * Rows written as (0, 0, 0) (no position) stay at the origin, which the renderer hides.
 */

/** Below this angle (rad) the normalised linear mix is used; it equals slerp to float precision. Same value in the GLSL below. */
const SMALL_ANGLE = 0.0001;

/**
 * Interpolate row `index` of frames `a` and `b` at `alpha` in [0, 1]; writes x, y, z into `out`
 * starting at `outOffset`. Returns false if either frame has no position for the row.
 */
export function interpolateRow(
  a: Float32Array,
  b: Float32Array,
  index: number,
  alpha: number,
  out: Float32Array | number[],
  outOffset = 0,
): boolean {
  const o = index * 3;
  const ax = a[o] ?? 0;
  const ay = a[o + 1] ?? 0;
  const az = a[o + 2] ?? 0;
  const bx = b[o] ?? 0;
  const by = b[o + 1] ?? 0;
  const bz = b[o + 2] ?? 0;
  const ra = Math.hypot(ax, ay, az);
  const rb = Math.hypot(bx, by, bz);
  if (ra < 0.5 || rb < 0.5) {
    out[outOffset] = 0;
    out[outOffset + 1] = 0;
    out[outOffset + 2] = 0;
    return false;
  }
  const nax = ax / ra;
  const nay = ay / ra;
  const naz = az / ra;
  const nbx = bx / rb;
  const nby = by / rb;
  const nbz = bz / rb;
  // Angle from the chord length: accurate for small angles, unlike acos(dot).
  const chord = Math.hypot(nbx - nax, nby - nay, nbz - naz);
  const angle = 2 * Math.asin(Math.min(1, chord / 2));
  let dx: number;
  let dy: number;
  let dz: number;
  if (angle < SMALL_ANGLE) {
    dx = nax + (nbx - nax) * alpha;
    dy = nay + (nby - nay) * alpha;
    dz = naz + (nbz - naz) * alpha;
    const len = Math.hypot(dx, dy, dz);
    dx /= len;
    dy /= len;
    dz /= len;
  } else {
    const s = Math.sin(angle);
    const wa = Math.sin((1 - alpha) * angle) / s;
    const wb = Math.sin(alpha * angle) / s;
    dx = wa * nax + wb * nbx;
    dy = wa * nay + wb * nby;
    dz = wa * naz + wb * nbz;
  }
  const r = ra + (rb - ra) * alpha;
  out[outOffset] = dx * r;
  out[outOffset + 1] = dy * r;
  out[outOffset + 2] = dz * r;
  return true;
}

/** GLSL version of interpolateRow, used by the satellite vertex shader. */
export const GLSL_ORBIT_INTERP = /* glsl */ `
vec3 orbitInterp(vec3 a, vec3 b, float t) {
  float ra = length(a);
  float rb = length(b);
  vec3 na = a / ra;
  vec3 nb = b / rb;
  float angle = 2.0 * asin(min(1.0, length(nb - na) * 0.5));
  vec3 dir;
  if (angle < 0.0001) {
    dir = normalize(mix(na, nb, t));
  } else {
    float s = sin(angle);
    dir = (sin((1.0 - t) * angle) * na + sin(t * angle) * nb) / s;
  }
  return dir * mix(ra, rb, t);
}
`;

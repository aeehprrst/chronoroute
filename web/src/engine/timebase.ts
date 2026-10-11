/**
 * The T-CRH time base (spec/tcrh-v1.md section 4), ported from the Python reference
 * sim/chronoroute/proto/timebase.py. The specification is normative.
 *
 * Every time quantity on the wire (Epoch_Base and every Delta) is a count of the
 * deadline unit u, chosen by the two UNIT bits in the Flags byte.
 *
 * Number safety (why some values are bigint and others are not):
 *   * GPS time in nanoseconds is about 1.48e18 in 2026, far above 2^53 (about 9.0e15),
 *     the largest integer a JavaScript number holds exactly. Every nanosecond quantity
 *     here is therefore a bigint, and every division on it is exact integer division.
 *   * Wire values are 32-bit unit counts (< 2^32). The largest sum the engine ever forms
 *     from them is Epoch_Base + 255 deltas of at most 255, i.e. below 2^32 + 65,025 <
 *     2^33. That is far below 2^53, so plain number arithmetic on wire values is exact.
 *   * serialDiff() forms a - b + 2^31 from two values below 2^32; |result| < 2^34. Exact.
 */

/** Deadline unit code: the two UNIT bits of the Flags byte (spec section 3). */
export type UnitCode = 0 | 1 | 2 | 3;

/** Unit length in nanoseconds for each unit code (spec section 3). */
export const UNIT_NS: readonly [number, number, number, number] = [1_000_000, 100_000, 250_000, 125_000];

export const UNIT_CODES: readonly UnitCode[] = [0, 1, 2, 3];

/** Provisional v1 default: 0.1 ms (spec section 3; experiment E13 chooses the final one). */
export const DEFAULT_UNIT_CODE: UnitCode = 1;

/** GPS = UTC + 18 s (no leap second since 2017-01-01; spec section 4). */
export const GPS_UTC_OFFSET_S = 18;

export const NS_PER_S = 1_000_000_000n;
export const NS_PER_MS = 1_000_000n;

export const MOD32 = 2 ** 32;
export const HALF32 = 2 ** 31;
const MOD32_BIG = 1n << 32n;

/** 1980-01-06T00:00:00Z (the GPS epoch) in seconds since 1970. */
const GPS_EPOCH_UNIX_S = Date.UTC(1980, 0, 6) / 1000;
/** GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on. */
const OFFSET_VALID_FROM_UNIX_S = Date.UTC(2017, 0, 1) / 1000;

// ------------------------------------------------------------------ checks

/** An integer that a JavaScript number represents exactly. */
export function requireInt(name: string, value: number): void {
  if (typeof value !== 'number' || !Number.isSafeInteger(value)) {
    throw new TypeError(`${name} must be an integer, got ${String(value)}`);
  }
}

export function checkRange(name: string, value: number, lo: number, hi: number): void {
  requireInt(name, value);
  if (value < lo || value > hi) {
    throw new RangeError(`${name} must be in ${lo}..${hi}, got ${value}`);
  }
}

export function isUnitCode(value: unknown): value is UnitCode {
  return value === 0 || value === 1 || value === 2 || value === 3;
}

/** Length of deadline unit `unitCode` in nanoseconds (RangeError if not 0..3). */
export function unitNs(unitCode: number): number {
  if (!isUnitCode(unitCode)) throw new RangeError(`unit code must be 0..3, got ${String(unitCode)}`);
  return UNIT_NS[unitCode];
}

export function unitNsBig(unitCode: number): bigint {
  return BigInt(unitNs(unitCode));
}

// ------------------------------------------------------------------ exact integer helpers

/** floor(a / b) for bigint, b > 0 (bigint division alone truncates toward zero). */
export function floorDiv(a: bigint, b: bigint): bigint {
  if (b <= 0n) throw new RangeError('divisor must be positive');
  const q = a / b;
  return a % b !== 0n && a < 0n ? q - 1n : q;
}

/** ceil(a / b) for bigint, b > 0. */
export function ceilDiv(a: bigint, b: bigint): bigint {
  return -floorDiv(-a, b);
}

/** Reduce a bigint to the 32-bit field it is stored in (mod 2^32, never negative). */
export function mod32Big(x: bigint): number {
  const r = x % MOD32_BIG;
  return Number(r < 0n ? r + MOD32_BIG : r);
}

/** Reduce an integer to the 32-bit field it is stored in (mod 2^32, never negative). */
export function u32(x: number): number {
  requireInt('value', x);
  return ((x % MOD32) + MOD32) % MOD32;
}

// ------------------------------------------------------------------ exact rationals

/** An exact rational number num / den with den > 0 (used for budgets; never a float). */
export interface Ratio {
  readonly num: bigint;
  readonly den: bigint;
}

function gcd(a: bigint, b: bigint): bigint {
  let x = a < 0n ? -a : a;
  let y = b < 0n ? -b : b;
  while (y !== 0n) [x, y] = [y, x % y];
  return x;
}

export function ratio(num: bigint, den: bigint = 1n): Ratio {
  if (den === 0n) throw new RangeError('denominator must not be zero');
  const sign = den < 0n ? -1n : 1n;
  const g = gcd(num, den) || 1n;
  return { num: (sign * num) / g, den: (sign * den) / g };
}

export function ratioAdd(a: Ratio, b: Ratio): Ratio {
  return ratio(a.num * b.den + b.num * a.den, a.den * b.den);
}

export function ratioMul(a: Ratio, b: Ratio): Ratio {
  return ratio(a.num * b.num, a.den * b.den);
}

/** ceil(r / divisor) for a positive integer divisor, exactly. */
export function ratioCeilDiv(r: Ratio, divisor: bigint): bigint {
  return ceilDiv(r.num, r.den * divisor);
}

/**
 * Parse a non-negative decimal written by a person ("3.445", "12", ".5") into an exact
 * Ratio. Returns null for anything else (signs, exponents, separators, empty input).
 */
export function parseDecimal(text: string): Ratio | null {
  const match = /^(\d*)(?:\.(\d*))?$/.exec(text.trim());
  if (!match) return null;
  const whole = match[1] ?? '';
  const frac = match[2] ?? '';
  if (whole === '' && frac === '') return null;
  return ratio(BigInt((whole || '0') + frac), 10n ** BigInt(frac.length));
}

/** Decimal text of a Ratio with at most `digits` fractional digits (truncated toward zero; for display). */
export function formatRatio(r: Ratio, digits: number): string {
  const negative = r.num < 0n;
  const num = negative ? -r.num : r.num;
  const scale = 10n ** BigInt(digits);
  const scaled = (num * scale) / r.den;
  const exact = (num * scale) % r.den === 0n;
  const whole = scaled / scale;
  let frac = digits > 0 ? (scaled % scale).toString().padStart(digits, '0') : '';
  frac = frac.replace(/0+$/, '');
  const body = frac ? `${whole}.${frac}` : `${whole}`;
  return `${negative ? '-' : ''}${exact ? '' : '≈'}${body}`;
}

// ------------------------------------------------------------------ float -> ns (one sanctioned crossing)

/** The exact binary value of a finite double as num / 2^k. */
function exactBinary(x: number): Ratio {
  if (!Number.isFinite(x)) throw new RangeError(`a time must be finite, got ${String(x)}`);
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const hi = view.getUint32(0);
  const lo = view.getUint32(4);
  const negative = hi >>> 31 === 1;
  const biased = (hi >>> 20) & 0x7ff;
  let mantissa = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);
  let exponent: number;
  if (biased === 0) {
    exponent = -1074; // subnormal
  } else {
    mantissa |= 1n << 52n;
    exponent = biased - 1075;
  }
  const signed = negative ? -mantissa : mantissa;
  return exponent >= 0 ? { num: signed << BigInt(exponent), den: 1n } : { num: signed, den: 1n << BigInt(-exponent) };
}

/** floor(r + 1/2): nearest integer, halves rounded up (as the Python reference). */
function roundHalfUp(r: Ratio): bigint {
  return floorDiv(2n * r.num + r.den, 2n * r.den);
}

/**
 * Seconds (a float) to integer nanoseconds, rounded to the NEAREST ns on the exact binary
 * value of the float, so 0.1 * 3 = 0.30000000000000004 lands on 300000000.
 */
export function secondsToNs(seconds: number): bigint {
  const r = exactBinary(seconds);
  return roundHalfUp({ num: r.num * NS_PER_S, den: r.den });
}

/** Same as secondsToNs, input in milliseconds. */
export function msToNs(ms: number): bigint {
  const r = exactBinary(ms);
  return roundHalfUp({ num: r.num * NS_PER_MS, den: r.den });
}

// ------------------------------------------------------------------ UTC <-> GPS

const ISO_UTC = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|[+-]\d{2}:\d{2})$/;

/**
 * GPS time in integer nanoseconds since the GPS epoch (1980-01-06T00:00:00Z) of an ISO 8601
 * instant such as "2026-10-10T13:58:00.123456Z" (up to 9 fractional digits, exact).
 * Throws for malformed text, impossible dates, leap-second notation and dates before 2017.
 */
export function utcIsoToGpsNs(iso: string): bigint {
  const m = ISO_UTC.exec(iso.trim());
  if (!m) throw new SyntaxError('expected an ISO 8601 time such as 2026-10-10T13:58:00.123Z');
  const [year, month, day, hour, minute, second] = m.slice(1, 7).map(Number) as [number, number, number, number, number, number];
  const ms = Date.UTC(year, month - 1, day, hour, minute, second);
  const check = new Date(ms);
  if (
    check.getUTCFullYear() !== year ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day ||
    hour > 23 ||
    minute > 59 ||
    second > 59
  ) {
    throw new RangeError('that date or time does not exist');
  }
  const zone = m[8] ?? 'Z';
  let offsetS = 0;
  if (zone !== 'Z') {
    const sign = zone.startsWith('-') ? -1 : 1;
    offsetS = sign * (Number(zone.slice(1, 3)) * 3600 + Number(zone.slice(4, 6)) * 60);
  }
  const unixS = ms / 1000 - offsetS;
  if (unixS < OFFSET_VALID_FROM_UNIX_S) {
    throw new RangeError('GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on');
  }
  const fracNs = BigInt((m[7] ?? '').padEnd(9, '0'));
  return (BigInt(unixS - GPS_EPOCH_UNIX_S) + BigInt(GPS_UTC_OFFSET_S)) * NS_PER_S + fracNs;
}

/** GPS nanoseconds of a UTC instant given in whole milliseconds since 1970 (e.g. Date.now()). */
export function utcMsToGpsNs(unixMs: number): bigint {
  requireInt('unixMs', unixMs);
  if (unixMs < OFFSET_VALID_FROM_UNIX_S * 1000) {
    throw new RangeError('GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on');
  }
  return (BigInt(unixMs) - BigInt(GPS_EPOCH_UNIX_S * 1000)) * NS_PER_MS + BigInt(GPS_UTC_OFFSET_S) * NS_PER_S;
}

/** Inverse of utcIsoToGpsNs: "YYYY-MM-DDTHH:MM:SS.nnnnnnnnnZ" (nanoseconds kept). */
export function gpsNsToUtcIso(tGpsNs: bigint): string {
  const unixNs = tGpsNs - BigInt(GPS_UTC_OFFSET_S) * NS_PER_S + BigInt(GPS_EPOCH_UNIX_S) * NS_PER_S;
  const unixS = floorDiv(unixNs, NS_PER_S);
  if (unixS < BigInt(OFFSET_VALID_FROM_UNIX_S)) {
    throw new RangeError('GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on');
  }
  const fracNs = unixNs - unixS * NS_PER_S;
  const base = new Date(Number(unixS) * 1000).toISOString().slice(0, 19);
  return `${base}.${fracNs.toString().padStart(9, '0')}Z`;
}

// ------------------------------------------------------------------ unit clock and anchor

/** A node's unit clock: floor(t_gps / u) mod 2^32 (spec section 4). */
export function clockU(tGpsNs: bigint, unitCode: number): number {
  return mod32Big(floorDiv(tGpsNs, unitNsBig(unitCode)));
}

/**
 * Epoch_Base stamped per packet at ingress: ceil(T_ingress / u) mod 2^32. Rounding the
 * anchor up can only add slack to every deadline, never remove it.
 */
export function epochBaseAtIngress(tGpsNs: bigint, unitCode: number): number {
  return mod32Big(ceilDiv(tGpsNs, unitNsBig(unitCode)));
}

// ------------------------------------------------------------------ serial arithmetic

/** Signed 32-bit serial difference a - b, in [-2^31, 2^31) (spec section 4). */
export function serialDiff(a: number, b: number): number {
  requireInt('a', a);
  requireInt('b', b);
  const x = a - b + HALF32;
  return (((x % MOD32) + MOD32) % MOD32) - HALF32;
}

/** True when the clock has moved PAST the deadline unit (arriving inside it is on time). */
export function isLate(nowU: number, deadlineU: number): boolean {
  return serialDiff(nowU, deadlineU) > 0;
}

/** Days until a 32-bit unit counter wraps: 2^32 * u. */
export function wrapPeriodDays(unitCode: number): number {
  return (MOD32 * unitNs(unitCode)) / 1e9 / 86_400;
}

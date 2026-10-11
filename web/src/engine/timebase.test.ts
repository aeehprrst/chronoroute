import { describe, expect, it } from 'vitest';
import {
  ceilDiv,
  clockU,
  epochBaseAtIngress,
  floorDiv,
  formatRatio,
  gpsNsToUtcIso,
  isLate,
  msToNs,
  parseDecimal,
  ratio,
  secondsToNs,
  unitNs,
  utcIsoToGpsNs,
  utcMsToGpsNs,
  wrapPeriodDays,
} from './timebase';
import { crh16Size, crh32Size, encapsulationOverhead, hdrExtLen, pad8, srhSize, tcrhSize } from './sizes';

describe('units', () => {
  it('match spec section 3', () => {
    expect([0, 1, 2, 3].map(unitNs)).toEqual([1_000_000, 100_000, 250_000, 125_000]);
    expect(() => unitNs(4)).toThrow(RangeError);
  });

  it('wrap periods match spec section 4 (49.7 days at 1 ms, 4.97 days at 0.1 ms)', () => {
    expect(wrapPeriodDays(0).toFixed(1)).toBe('49.7');
    expect(wrapPeriodDays(1).toFixed(2)).toBe('4.97');
  });
});

describe('exact integer division', () => {
  it('floors and ceils negative and positive values like Python', () => {
    expect(floorDiv(7n, 2n)).toBe(3n);
    expect(floorDiv(-7n, 2n)).toBe(-4n);
    expect(ceilDiv(7n, 2n)).toBe(4n);
    expect(ceilDiv(-7n, 2n)).toBe(-3n);
    expect(ceilDiv(6n, 2n)).toBe(3n);
  });
});

describe('GPS time', () => {
  it('converts UTC to GPS nanoseconds (GPS = UTC + 18 s since 2017)', () => {
    // 2017-01-01T00:00:00Z is 1167264000 s after the GPS epoch (UTC days), + 18 s.
    expect(utcIsoToGpsNs('2017-01-01T00:00:00Z')).toBe((1_167_264_000n + 18n) * 1_000_000_000n);
    expect(utcIsoToGpsNs('2026-10-10T13:58:00.123456Z')).toBe(1_475_675_898_123_456_000n);
    expect(utcIsoToGpsNs('2026-10-10T19:28:00.123456+05:30')).toBe(1_475_675_898_123_456_000n);
    expect(utcMsToGpsNs(Date.UTC(2026, 9, 10, 13, 58, 0, 123))).toBe(1_475_675_898_123_000_000n);
  });

  it('round-trips with nanoseconds', () => {
    const t = utcIsoToGpsNs('2026-10-10T13:58:00.123456789Z');
    expect(gpsNsToUtcIso(t)).toBe('2026-10-10T13:58:00.123456789Z');
  });

  it('refuses impossible dates, leap-second notation and dates before 2017', () => {
    expect(() => utcIsoToGpsNs('2026-02-30T00:00:00Z')).toThrow();
    expect(() => utcIsoToGpsNs('2016-12-31T23:59:60Z')).toThrow();
    expect(() => utcIsoToGpsNs('2016-06-01T00:00:00Z')).toThrow();
    expect(() => utcIsoToGpsNs('yesterday')).toThrow();
  });

  it('stamps Epoch_Base by rounding up and the clock by rounding down', () => {
    expect(epochBaseAtIngress(1_000_000_123n, 1)).toBe(10_001);
    expect(clockU(1_000_000_123n, 1)).toBe(10_000);
    expect(epochBaseAtIngress(1_000_000_000n, 1)).toBe(10_000);
    expect(epochBaseAtIngress((1n << 32n) * 100_000n - 1n, 1)).toBe(0);
  });

  it('judges late strictly after the deadline unit', () => {
    expect(isLate(1006, 1006)).toBe(false);
    expect(isLate(1007, 1006)).toBe(true);
    expect(isLate(0, 2 ** 32 - 1)).toBe(true);
  });
});

describe('float to nanoseconds (one sanctioned crossing)', () => {
  // Expected values were produced by the Python reference (chronoroute.proto.timebase).
  it('rounds the exact binary value to the nearest ns, as the Python reference does', () => {
    expect(secondsToNs(0.1 * 3)).toBe(300_000_000n);
    expect(msToNs(0.1 * 3)).toBe(300_000n);
    expect(msToNs(2.5)).toBe(2_500_000n);
    expect(msToNs(2.6)).toBe(2_600_000n);
    expect(msToNs(123.456789)).toBe(123_456_789n);
    expect(msToNs(1e-7)).toBe(0n);
    // 5e-7 is stored as slightly less than 5e-7, so 0.4999... ns rounds down
    expect(msToNs(5e-7)).toBe(0n);
    expect(msToNs(1.5e-6)).toBe(2n);
    expect(secondsToNs(5e-7)).toBe(500n);
  });
});

describe('decimal parsing', () => {
  it('is exact', () => {
    expect(parseDecimal('3.445')).toEqual(ratio(3445n, 1000n));
    expect(parseDecimal('12')).toEqual(ratio(12n));
    expect(parseDecimal('.5')).toEqual(ratio(1n, 2n));
    expect(parseDecimal('1.30')).toEqual(ratio(13n, 10n));
    for (const bad of ['', '.', '-1', '1e3', '1,5', 'abc']) expect(parseDecimal(bad)).toBeNull();
    expect(formatRatio(ratio(1n, 3n), 3)).toBe('≈0.333');
    expect(formatRatio(ratio(5n, 2n), 3)).toBe('2.5');
  });
});

describe('sizes (spec sections 2, 8 and 9)', () => {
  it('gives the examples in the spec', () => {
    expect([1, 3, 5, 10, 13, 255].map(tcrhSize)).toEqual([16, 24, 32, 48, 56, 784]);
    expect([tcrhSize(10), crh16Size(10), crh32Size(10), srhSize(10)]).toEqual([48, 24, 48, 168]);
    expect(encapsulationOverhead(10, 'encap', 'tcrh')).toBe(88);
    expect(encapsulationOverhead(10)).toBe(48);
    expect(hdrExtLen(784)).toBe(97);
    expect(pad8(0)).toBe(0);
    expect(() => tcrhSize(256)).toThrow(RangeError);
    expect(() => hdrExtLen(12)).toThrow(RangeError);
  });
});

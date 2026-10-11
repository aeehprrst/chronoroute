import { describe, expect, it } from 'vitest';
import { formatAge, formatInt, formatUtc, parseUtc } from '../src/lib/format';

describe('parseUtc', () => {
  it('reads CelesTrak epochs without a zone as UTC', () => {
    expect(parseUtc('2026-10-10T11:09:41.999962')).toBe(Date.UTC(2026, 9, 10, 11, 9, 41, 999));
    expect(parseUtc('2026-10-10T14:02:22Z')).toBe(Date.UTC(2026, 9, 10, 14, 2, 22));
    expect(Number.isNaN(parseUtc('not a date'))).toBe(true);
  });
});

describe('formatUtc', () => {
  it('truncates to seconds or minutes and labels the zone', () => {
    expect(formatUtc('2026-10-10T14:02:22Z')).toBe('2026-10-10 14:02:22 UTC');
    expect(formatUtc('2026-10-08T17:33:41.999990Z', 'minutes')).toBe('2026-10-08 17:33 UTC');
    expect(formatUtc('garbage')).toBe('garbage');
  });
});

describe('formatAge', () => {
  const t0 = Date.UTC(2026, 9, 10, 14, 2, 22);
  it('uses the two largest units', () => {
    expect(formatAge(t0, t0 + 45_000)).toBe('45 s');
    expect(formatAge(t0, t0 + 5 * 60_000)).toBe('5 min');
    expect(formatAge(t0, t0 + 3 * 3_600_000 + 12 * 60_000)).toBe('3 h 12 min');
    expect(formatAge(t0, t0 + 2 * 86_400_000 + 4 * 3_600_000)).toBe('2 d 4 h');
    expect(formatAge(t0, t0 + 86_400_000)).toBe('1 d');
  });
  it('marks future times', () => {
    expect(formatAge(t0 + 90 * 60_000, t0)).toBe('in 1 h 30 min');
  });
});

describe('formatInt', () => {
  it('groups thousands with commas', () => {
    expect(formatInt(11130)).toBe('11,130');
    expect(formatInt(100001)).toBe('100,001');
    expect(formatInt(999)).toBe('999');
  });
});

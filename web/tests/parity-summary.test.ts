/**
 * The parity badge's data and wording (src/lib/route/parity-summary.ts): the page must never
 * claim more than the gate checked.
 */
import { describe, expect, it } from 'vitest';
import {
  allPathsIdentical,
  badgeConclusion,
  describeRun,
  parseParitySummary,
  PARITY_RULE,
  PARITY_SUMMARY_SCHEMA,
  type ParityRunSummary,
  type ParitySummary,
} from '../src/lib/route/parity-summary';

const reference: ParityRunSummary = {
  role: 'reference',
  snapshot_id: '20261010T1358Z-celestrak',
  web_snapshot_id: null,
  t_utc: '2026-10-10T14:02:22Z',
  shell_id: '53.2deg-463km',
  pairs: 20,
  reachable: 19,
  identical_paths: 19,
  ties: 0,
  mismatches: 0,
  pairs_with_diagnostics: 0,
};
const served: ParityRunSummary = {
  ...reference,
  role: 'served',
  snapshot_id: '20261010T2035Z-celestrak',
  web_snapshot_id: '20261010T2035Z-supgp',
  t_utc: '2026-10-10T20:35:57Z',
};
const summary = (runs: ParityRunSummary[]): ParitySummary => ({ schema: PARITY_SUMMARY_SCHEMA, rule: PARITY_RULE, runs });

describe('parity summary', () => {
  it('says "identical" when every path was identical in every run', () => {
    const s = summary([reference, served]);
    expect(allPathsIdentical(s)).toBe(true);
    expect(describeRun(reference)).toContain('All 19 paths identical');
    expect(describeRun(served)).toContain('Served snapshot 20261010T2035Z-supgp');
    expect(badgeConclusion(s)).toMatch(/^Routes identical given identical positions/);
  });

  it('names equal-cost ties as ties and drops the "identical" claim', () => {
    const withTie = { ...served, identical_paths: 17, ties: 2 };
    const s = summary([reference, withTie]);
    expect(allPathsIdentical(s)).toBe(false);
    expect(describeRun(withTie)).toContain('17 of 19 paths identical');
    expect(describeRun(withTie)).toContain('2 equal-cost ties');
    expect(describeRun(withTie)).not.toContain('All 19');
    expect(badgeConclusion(s)).toMatch(/^Routes equal in cost/);
    expect(badgeConclusion(s)).not.toMatch(/identical given/);
  });

  it('accepts what the gate writes and rejects other schemas or numbers that do not add up', () => {
    const good = summary([reference, served]);
    expect(parseParitySummary(JSON.parse(JSON.stringify(good)))).toEqual(good);
    expect(parseParitySummary({ ...good, commit: 'abc1234' })?.commit).toBe('abc1234');
    expect(parseParitySummary(null)).toBeNull();
    expect(parseParitySummary({ ...good, schema: 'chronoroute.web-parity-summary/1' })).toBeNull();
    expect(parseParitySummary({ ...good, runs: [] })).toBeNull();
    // more identical paths + ties than pairs with a path
    expect(parseParitySummary(summary([{ ...reference, ties: 1 }]))).toBeNull();
    // fewer accounted pairs than pairs with a path
    expect(parseParitySummary(summary([{ ...reference, identical_paths: 18 }]))).toBeNull();
    expect(parseParitySummary(summary([{ ...reference, reachable: 21 }]))).toBeNull();
    expect(parseParitySummary(summary([{ ...reference, pairs: -1 }]))).toBeNull();
  });
});

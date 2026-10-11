/**
 * Checks the parity GATE itself (tests/parity-gate.ts): fed Python answers that were altered on
 * purpose, it must fail exactly when the rule says so. Uses the reference parity file
 * (web/.parity/parity.json) and changes copies of single pairs in memory; the file on disk is
 * never touched.
 */
import { describe, expect, it } from 'vitest';
import { allPathsIdentical, describeRun, type ParitySummary } from '../src/lib/route/parity-summary';
import { comparePair, referenceRun, summarizeRun, type Outcome } from './parity-gate';
import { readParity, type ParityPair } from './parity-data';

const run = referenceRun(readParity());
const reachable = run.doc.pairs.filter((p) => p.reachable);
const unreachable = run.doc.pairs.filter((p) => !p.reachable);
const base = reachable[0]!; // Chennai -> London (the first canonical pair)

/** The hex string with byte `index` (negative: from the end) XOR-ed with 0x01. */
function flipByte(hex: string, index: number): string {
  const n = hex.length / 2;
  const i = index < 0 ? n + index : index;
  const byte = (parseInt(hex.slice(2 * i, 2 * i + 2), 16) ^ 0x01).toString(16).padStart(2, '0');
  return hex.slice(0, 2 * i) + byte + hex.slice(2 * i + 2);
}

/** A different but plausible-looking path: the same ends, the interior reversed. */
function otherPath(p: ParityPair): number[] {
  const nodes = p.path_nodes!;
  const interior = nodes.slice(1, -1).reverse();
  expect(interior.length).toBeGreaterThan(1); // otherwise reversing would change nothing
  return [nodes[0]!, ...interior, nodes[nodes.length - 1]!];
}

const passes = (o: Outcome) => o.costOk && o.headerOk;

describe('the parity gate fails exactly when it should', () => {
  it('passes the unaltered Python answer, as an identical path', () => {
    const o = comparePair(run, base);
    expect(passes(o)).toBe(true);
    expect(o.samePath).toBe(true);
    expect(o.tie).toBe(false);
    expect(o.diagnostics).toEqual([]);
  });

  it('fails on one flipped byte in the T-CRH, the template, the packet or the pcap', () => {
    for (const key of ['header_hex', 'template_hex', 'packet_hex', 'pcap_hex'] as const) {
      for (const index of [0, 5, -1]) {
        const o = comparePair(run, { ...base, [key]: flipByte(base[key]!, index) });
        expect(o.costOk, `${key}[${index}]`).toBe(true);
        expect(o.headerOk, `${key}[${index}]`).toBe(false);
      }
    }
  });

  it('accepts a 1 ns cost difference and fails at 2 ns', () => {
    expect(passes(comparePair(run, { ...base, cost_ns: base.cost_ns! + 1 }))).toBe(true);
    expect(passes(comparePair(run, { ...base, cost_ns: base.cost_ns! - 1 }))).toBe(true);
    expect(comparePair(run, { ...base, cost_ns: base.cost_ns! + 2 }).costOk).toBe(false);
    expect(comparePair(run, { ...base, cost_ns: base.cost_ns! - 2 }).costOk).toBe(false);
  });

  it('fails when only one side finds a path', () => {
    // Python "has no path" where TypeScript finds one.
    const { path_nodes: _p, ...noPath } = base;
    expect(comparePair(run, { ...noPath, reachable: false, cost_ns: null }).costOk).toBe(false);
    // Python "has a path" where TypeScript finds none (Reykjavik -> Oslo at this instant).
    expect(unreachable.length).toBeGreaterThan(0);
    const north = unreachable[0]!;
    expect(passes(comparePair(run, north))).toBe(true);
    const claimed = { ...north, reachable: true, cost_ns: 5_000_000, path_nodes: base.path_nodes!, sids_fwd: base.sids_fwd!, hop_delays_ns: base.hop_delays_ns! };
    expect(comparePair(run, claimed).costOk).toBe(false);
  });

  it('accepts a genuine tie (equal cost, other path) as a TIE and still compares every byte on Python\'s path', () => {
    const tie = comparePair(run, { ...base, path_nodes: otherPath(base) });
    expect(passes(tie)).toBe(true);
    expect(tie.samePath).toBe(false);
    expect(tie.tie).toBe(true);
    expect(tie.diagnostics.some((d) => d.startsWith('tie: equal-cost paths'))).toBe(true);
    // The tie branch rebuilds template, header, packet and pcap: each one is checked.
    for (const key of ['header_hex', 'template_hex', 'packet_hex', 'pcap_hex'] as const) {
      const o = comparePair(run, { ...base, path_nodes: otherPath(base), [key]: flipByte(base[key]!, -1) });
      expect(o.headerOk, `tie with a flipped ${key} byte`).toBe(false);
    }
  });

  it('fails a different path that costs more than 1 ns more or less', () => {
    const o = comparePair(run, { ...base, path_nodes: otherPath(base), cost_ns: base.cost_ns! + 2 });
    expect(o.costOk).toBe(false);
    expect(o.tie).toBe(false);
  });

  it('counts ties separately in the summary, so the badge never calls them identical', () => {
    const outcomes = run.doc.pairs.map((p, i) => comparePair(run, i === 0 ? { ...p, path_nodes: otherPath(p) } : p));
    const s = summarizeRun(run, outcomes);
    expect(s).toMatchObject({ pairs: 20, reachable: 19, identical_paths: 18, ties: 1, mismatches: 0 });
    const summary: ParitySummary = { schema: 'chronoroute.web-parity-summary/2', rule: 'r', runs: [s] };
    expect(allPathsIdentical(summary)).toBe(false);
    expect(describeRun(s)).toContain('18 of 19 paths identical');
    expect(describeRun(s)).toContain('1 equal-cost tie ');
    expect(describeRun(s)).not.toContain('All 19 paths identical');
  });
});

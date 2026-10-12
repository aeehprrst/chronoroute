/**
 * ROUTE PARITY: the TypeScript route planner against the Python reference.
 * This file is the deploy gate of .github/workflows/pages.yml and refresh-data.yml.
 *
 * Two runs (tests/parity-gate.ts explains them and the exact rule):
 *   reference  web/.parity/parity.json: the experiments' pinned snapshot 20261010T1358Z, on the
 *              inputs embedded in that file (a fixed yardstick);
 *   served     web/.parity/served/parity.json: the snapshot this build publishes, with the
 *              planner reading the published files in public/data, as the browser does.
 * Both are written by `npm run data` (scripts/build-data.sh). For 20 canonical city pairs at
 * the snapshot's download time, the TypeScript planner runs on Python's positions frame
 * (satellites and cities), so float noise from two SGP4 implementations or two maths
 * libraries cannot change a path; SGP4 itself is compared with a tolerance in
 * sgp4-parity.test.ts.
 *
 * Blocks a deploy: a path cost more than 1 ns off, or any differing byte of the T-CRH template,
 * the per-packet T-CRH, the packet or the pcap (on an equal-cost tie: rebuilt from Python's
 * path). Preconditions that make the comparison meaningful (same satellites in the same order,
 * same parameters, the served files made from the same download) also fail the test.
 * Everything else is printed as a diagnostic.
 *
 * After everything passed, PARITY_SUMMARY_OUT=<file> writes the summary the route page shows
 * (schema chronoroute.web-parity-summary/2, src/lib/route/parity-summary.ts).
 */
import { describe, expect, it } from 'vitest';
import { writeFileSync } from 'node:fs';
import { geodeticToEcef } from '../src/lib/route/geometry';
import { utcNsToGpsNs } from '../src/lib/route/planner';
import { PARITY_RULE, PARITY_SUMMARY_SCHEMA, parseParitySummary, type ParitySummary } from '../src/lib/route/parity-summary';
import { comparePair, referenceRun, servedRun, summarizeRun, withoutSnapshotId, type Outcome, type ParityRun } from './parity-gate';
import { PARITY_FILE, readParity, SERVED_PARITY_FILE } from './parity-data';

const runs: ParityRun[] = [referenceRun(readParity(PARITY_FILE)), servedRun(readParity(SERVED_PARITY_FILE))];
const outcomes = new Map<ParityRun, Outcome[]>(runs.map((run) => [run, []]));

for (const run of runs) {
  const { doc, ctx } = run;
  const results = outcomes.get(run)!;

  describe(`${run.role} run: route parity with Python on ${doc.snapshot_id} at ${doc.t_utc} (${run.inputsFrom})`, () => {
    it('uses the same satellites, node numbering and inputs as Python', () => {
      // Structural preconditions: without these the comparison below would be meaningless.
      expect([...ctx.net.norads]).toEqual(doc.frame.norad);
      expect(doc.pairs.length).toBe(20);
      expect(doc.slack).toBe('1.5');
      expect(doc.unit_code).toBe(1);
      expect(doc.processing_ns).toBe(500_000);
      expect(doc.t_utc).toBe(doc.fetched_utc);
      expect(utcNsToGpsNs(run.tUnixNs).toString()).toBe(doc.t_gps_ns);
      expect(doc.gsl_params.min_elevation_deg).toBe(25);
      expect(doc.gsl_params.max_links_per_gs).toBe(4);
      expect(ctx.net.model.polar_cutoff_deg).toBe(doc.grid_params['polar_cutoff_deg']);
      expect(ctx.net.model.min_grazing_alt_km).toBe(doc.grid_params['min_grazing_alt_km']);
      expect(ctx.net.model.max_range_km).toBe(doc.grid_params['max_range_km']);
      expect(ctx.net.referenceUtc).toBe(doc.fetched_utc);
      if (run.role === 'reference') expect(doc.snapshot_id).toBe('20261010T1358Z-celestrak');
    });

    if (run.served) {
      const served = run.served;
      it('tests the files actually served: same download as the Python side (sha256, time, source)', () => {
        expect(served.sha256Raw).toBe(doc.sha256_raw);
        expect(served.fetchedUtc).toBe(doc.fetched_utc);
        expect(served.source).toBe(doc.source);
        // Diagnostic: are the served topology files the documents Python routed on? A difference
        // that changes a route fails the pairs below; one that does not is printed here.
        const sameShells = JSON.stringify(withoutSnapshotId(served.shellsRaw)) === JSON.stringify(withoutSnapshotId(doc.shells));
        const sameIsl = JSON.stringify(withoutSnapshotId(served.islRaw)) === JSON.stringify(withoutSnapshotId(doc.isl_grid4));
        if (!sameShells) console.warn(`[parity] served: shells.json differs from the shells Python routed on`);
        if (!sameIsl) console.warn(`[parity] served: isl_grid4.json differs from the laser-link pairs Python routed on`);
        console.log(`[parity] served: ${served.webSnapshotId} (sha256 ${served.sha256Raw.slice(0, 12)}...); shells.json ${sameShells ? 'identical' : 'DIFFERENT'}, isl_grid4.json ${sameIsl ? 'identical' : 'DIFFERENT'} (ignoring snapshot_id)`);
      });
    }

    it("converts city coordinates like Python (within 1e-9 km; the gate itself uses Python's)", () => {
      let exact = 0;
      let total = 0;
      for (const [name, xyz] of Object.entries(doc.frame.city_ecef_km)) {
        const city = ctx.cities.find((c) => c.name === name)!;
        const mine = geodeticToEcef(city.latDeg, city.lonDeg, 0);
        for (let i = 0; i < 3; i += 1) {
          expect(Math.abs(mine[i]! - xyz[i]!)).toBeLessThan(1e-9);
          total += 1;
          if (mine[i] === xyz[i]) exact += 1;
        }
      }
      // Not a failure: V8's Math.sin/cos may round differently from numpy's in the last bit.
      console.log(`[parity] ${run.role}: ${exact} of ${total} city ECEF coordinates bit-identical to Python's`);
    });

    for (const py of doc.pairs) {
      const label = `${py.src} -> ${py.dst}`;
      it(`${label}: same cost (within 1 ns) and byte-identical header, packet and pcap`, () => {
        const o = comparePair(run, py);
        results.push(o);
        for (const d of o.diagnostics) console.warn(`[parity] ${run.role} ${label}: ${d}`);
        expect(o.costOk, `${label}: path cost differs by more than 1 ns`).toBe(true);
        expect(o.headerOk, `${label}: header, packet or pcap bytes differ`).toBe(true);
      });
    }
  });
}

describe('parity summary', () => {
  it('0 mismatches in every run; writes PARITY_SUMMARY_OUT only after that', () => {
    const summaries = runs.map((run) => summarizeRun(run, outcomes.get(run)!));
    for (const s of summaries) {
      console.log(
        `[parity] ${s.role} ${s.snapshot_id} at ${s.t_utc}: ${s.pairs} pairs (${s.reachable} with a path): ` +
          `${s.mismatches} mismatches, ${s.identical_paths} identical paths, ${s.ties} equal-cost ties, ` +
          `${s.pairs_with_diagnostics} pairs with diagnostics`,
      );
    }
    for (const [i, run] of runs.entries()) {
      expect(outcomes.get(run)!.length, `${run.role}: every pair was compared`).toBe(run.doc.pairs.length);
      expect(summaries[i]!.mismatches, `${run.role}: mismatches`).toBe(0);
    }
    const summary: ParitySummary = {
      schema: PARITY_SUMMARY_SCHEMA,
      rule: PARITY_RULE,
      runs: summaries,
      // The commit CI checked (GitHub sets GITHUB_SHA); absent in local runs.
      ...(process.env['GITHUB_SHA'] ? { commit: process.env['GITHUB_SHA'] } : {}),
    };
    // What we write must be what the page accepts.
    expect(parseParitySummary(JSON.parse(JSON.stringify(summary)))).toEqual(summary);
    const out = process.env['PARITY_SUMMARY_OUT'];
    if (out) writeFileSync(out, `${JSON.stringify(summary)}\n`);
  });
});

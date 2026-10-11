import { afterEach, describe, expect, it, vi } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import RoutePlanner from '../src/components/route/RoutePlanner';
import { parseLatestPointer, parseManifest } from '../src/lib/data';
import type { RouteData } from '../src/lib/route/load';
import { planRoute } from '../src/lib/route/planner';
import { parseIslDoc, parseShellsDoc } from '../src/lib/route/topology';
import { ratioCeilDiv, unitNsBig } from '../src/engine/timebase';
import { DATA_DIR, runStations, servedRun } from './parity-gate';
import { readParity, SERVED_PARITY_FILE } from './parity-data';

// Seed the island's state as if the worker had just returned a plan. Server rendering
// exercises the actual result markup without starting a worker or browser fetches.
const state = vi.hoisted(() => ({ values: [] as unknown[] }));
vi.mock('react', async (importOriginal) => {
  const original = await importOriginal<typeof import('react')>();
  return {
    ...original,
    useState: (initial: unknown) => state.values.length > 0 ? [state.values.shift(), vi.fn()] : original.useState(initial),
  };
});
afterEach(() => { state.values = []; });

const run = servedRun(readParity(SERVED_PARITY_FILE));
const read = (rel: string) => JSON.parse(readFileSync(path.join(DATA_DIR, rel), 'utf8')) as unknown;
const pointer = parseLatestPointer(read('latest.json'));
const data: RouteData = {
  snapshot: { manifest: parseManifest(read(`${pointer.path}manifest.json`)), records: run.ctx.records, path: pointer.path },
  shells: parseShellsDoc(read(`${pointer.path}shells.json`)),
  isl: parseIslDoc(read(`${pointer.path}isl_grid4.json`)),
  cities: run.ctx.cities,
  registry: run.ctx.registry,
  parity: null,
};

describe('route planner final deadline label', () => {
  it.each(['1.5', '30'])('explains the encoded deadline accurately at slack %s', (slack) => {
    const [src, dst] = runStations(run, 'Chennai', 'London');
    const plan = planRoute(run.ctx.net, run.frame, run.ctx.sats, src, dst, run.tUnixNs, { slack, unitCode: 1 });
    if (!plan.reachable) throw new Error('The parity pair must have a path');
    expect(plan.sat).toBe(slack === '30');
    const tMs = Number(run.tUnixNs / 1_000_000n);
    state.values = [
      { kind: 'ready', data, ctx: run.ctx, initErrors: [] },
      src.name, dst.name, 0, false, slack, 1, tMs,
      { plan, failed: 0, tMs }, null, false,
    ];
    const html = renderToStaticMarkup(createElement(RoutePlanner));
    const label = html.match(/<dt>(Final deadline in the header.*?)<\/dt>/)?.[1]?.replace(/<[^>]*>/g, '');
    expect(label).toBeDefined();
    if (plan.sat) {
      const unclamped = ratioCeilDiv(plan.budgets.at(-1)!, unitNsBig(plan.unitCode));
      expect(label).toContain('SAT: deltas clamped to 255 units');
      expect(label).toContain(`ceil(B${plan.sizes.hops}/u) would be ${unclamped} units`);
      expect(label).not.toContain('rounded up');
      expect(BigInt(unclamped)).toBeGreaterThan(plan.hops.at(-1)!.deadlineAfterEpochNs / unitNsBig(plan.unitCode));
    } else {
      expect(label).toContain('rounded up to whole 0.1 ms units');
      expect(label).not.toContain('SAT');
    }
  });
});

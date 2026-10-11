/** Verify the SGP4 deploy gate propagates both snapshots, using the served browser inputs. */
import { expect, it, vi } from 'vitest';
import { servedRun } from './parity-gate';
import { readParity, SERVED_PARITY_FILE } from './parity-data';
import type { OmmRecord } from '../src/lib/data-types';

const propagated = vi.hoisted(() => ({ records: [] as (readonly OmmRecord[])[] }));
vi.mock('../src/lib/orbit/propagate', async (importOriginal) => {
  const original = await importOriginal<typeof import('../src/lib/orbit/propagate')>();
  return {
    ...original,
    initSatrecs: (...args: Parameters<typeof original.initSatrecs>) => {
      propagated.records.push(args[0]);
      return original.initSatrecs(...args);
    },
  };
});

// Register and run the actual tolerance suite, while observing its propagation inputs.
import './sgp4-parity.test';

it('runs the SGP4 tolerance check for reference and served snapshots', () => {
  expect(propagated.records).toHaveLength(2);
  const served = servedRun(readParity(SERVED_PARITY_FILE));
  expect(propagated.records[1]).toEqual(served.ctx.records);
});

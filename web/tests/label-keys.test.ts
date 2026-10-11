/**
 * The site's label table must equal Python's (sim/chronoroute/labels.py TABLE), which
 * tools/web_parity.py exports into web/.parity/parity.json.
 */
import { describe, expect, it } from 'vitest';
import { LABEL_TABLE } from '../src/lib/label-keys';
import { LABELS } from '../src/lib/labels';
import { readParity } from './parity-data';

describe('honesty labels', () => {
  it('src/lib/label-keys.ts equals chronoroute.labels.TABLE, key for key', () => {
    const python = readParity().labels;
    expect({ ...LABEL_TABLE }).toEqual(python);
  });

  it('satellite positions are REAL (REAL physics + REAL code on REAL elements), routes DERIVED', () => {
    expect(LABEL_TABLE.satellite_positions_sgp4).toBe('REAL');
    expect(LABEL_TABLE.routes_and_budgets).toBe('DERIVED');
    expect(LABEL_TABLE.isl_topology_grid4).toBe('MODELLED');
    // The site's own definitions say so too (they are shown on every chip's tooltip).
    const real = LABELS.find((l) => l.kind === 'real')!;
    const derived = LABELS.find((l) => l.kind === 'derived')!;
    expect(real.example).toMatch(/SGP4/);
    expect(derived.example).not.toMatch(/SGP4/);
  });
});

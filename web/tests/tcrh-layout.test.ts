/**
 * The display helper must agree with every golden `encode` vector in
 * ../spec/golden/tcrh_vectors.json (read-only, shared with the other implementations).
 */
import { describe, expect, it } from 'vitest';
import path from 'node:path';
import { readTcrhEncodeVectors } from '../src/lib/data-build';
import {
  HEADER_SIZE_FORMULAS,
  deadlines,
  forwardSids,
  hexToBytes,
  readTcrhLayout,
  tcrhSize,
} from '../src/lib/tcrh-layout';

const SPEC_DIR = path.resolve(import.meta.dirname, '..', '..', 'spec');
const vectors = await readTcrhEncodeVectors(SPEC_DIR);

describe('golden encode vectors', () => {
  it('are present', () => {
    expect(vectors.length).toBeGreaterThan(0);
    expect(vectors.some((v) => v.name === 'v0-3hop')).toBe(true);
  });

  it.each(vectors.map((v) => [v.name, v] as const))('%s decodes to its expected fields', (_name, v) => {
    const layout = readTcrhLayout(hexToBytes(v.expect_hex));
    expect(layout.size).toBe(v.expect_size);
    expect(layout.size).toBe(tcrhSize(v.sids_fwd.length));
    expect(layout.routingType).toBe(253);
    expect(layout.nextHeader).toBe(v.next_header);
    expect(layout.flags).toBe(v.expect_flags);
    expect(layout.unitCode).toBe(v.unit_code);
    expect(layout.flagNames.includes('SAT')).toBe(v.expect_sat);
    expect(layout.numHops).toBe(v.sids_fwd.length);
    expect(layout.segmentsLeft).toBe(v.sids_fwd.length);
    expect(layout.devHop).toBe(0);
    expect(layout.epochBase).toBe(v.expect_epoch_base);
    expect(forwardSids(layout)).toEqual(v.sids_fwd);
    expect(layout.entries.map((e) => e.delta).reverse()).toEqual(v.expect_deltas_fwd);
    expect(deadlines(layout)).toEqual(v.expect_deadlines_u);
  });
});

describe('spec section 10 reference vector', () => {
  it('matches the bytes printed in the specification', () => {
    const v = vectors.find((x) => x.name === 'v0-3hop');
    expect(v?.expect_hex).toBe('1102fd0300030000000003e8000708000307000206000000');
    expect(v?.expect_deadlines_u).toEqual([1006, 1013, 1021]);
  });
});

describe('header sizes (spec sections 2 and 9)', () => {
  it('gives the example T-CRH sizes', () => {
    expect([1, 3, 5, 10, 13, 255].map(tcrhSize)).toEqual([16, 24, 32, 48, 56, 784]);
  });

  it('gives the 10-hop comparison from section 9', () => {
    expect(HEADER_SIZE_FORMULAS.map((row) => row.size(10))).toEqual([48, 24, 48, 168]);
  });
});

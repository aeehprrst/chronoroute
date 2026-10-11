/**
 * Byte descriptions used by the byte map: the deadline formula in each delta's text must name
 * exactly the deltas it sums (no "d_1 + … + d_1" for hop 1).
 */
import { describe, expect, it } from 'vitest';
import { hexToBytes } from '../../engine/tcrh';
import { deadlineSumText, describeTcrhBytes } from './byte-fields';

describe('deadlineSumText', () => {
  it('writes the sum without an ellipsis for hops 1 and 2', () => {
    expect(deadlineSumText(1)).toBe('Epoch_Base + d_1');
    expect(deadlineSumText(2)).toBe('Epoch_Base + d_1 + d_2');
  });

  it('uses the ellipsis only from hop 3 on', () => {
    expect(deadlineSumText(3)).toBe('Epoch_Base + d_1 + … + d_3');
    expect(deadlineSumText(10)).toBe('Epoch_Base + d_1 + … + d_10');
  });
});

describe('describeTcrhBytes on the spec section 10 header (golden vector v0-3hop)', () => {
  // Path 2 -> 3 -> 7, deltas 6, 7, 8 at 1 ms, Epoch_Base 1000: deadlines 1006, 1013, 1021.
  const hex = '1102fd0300030000000003e8000708000307000206000000';
  const described = describeTcrhBytes(hexToBytes(hex));

  it('gives every delta the right formula and value', () => {
    const texts = described.infos.filter((b) => b.field.startsWith('Delta[')).map((b) => b.meaning);
    expect(texts.some((t) => t.includes('Deadline D_1 = Epoch_Base + d_1 = 1006 (mod 2^32).'))).toBe(true);
    expect(texts.some((t) => t.includes('Deadline D_2 = Epoch_Base + d_1 + d_2 = 1013 (mod 2^32).'))).toBe(true);
    expect(texts.some((t) => t.includes('Deadline D_3 = Epoch_Base + d_1 + … + d_3 = 1021 (mod 2^32).'))).toBe(true);
    expect(texts.some((t) => t.includes('d_1 + … + d_1'))).toBe(false);
  });
});

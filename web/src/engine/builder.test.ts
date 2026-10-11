/**
 * The protocol page's header builder and stepper logic, checked against the golden vectors:
 * every builder example must reproduce its golden vector byte for byte.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { BUILDER_EXAMPLES, computeBuild, parseSid } from '../components/protocol/builder-logic';
import { buildTrace, defaultDelays } from '../components/protocol/stepper-logic';
import { bytesToHex, deadlines, decode, encode, fromForward, hexToBytes } from './tcrh';

const GOLDEN = path.resolve(import.meta.dirname, '..', '..', '..', 'spec', 'golden');
const vectors = (JSON.parse(readFileSync(path.join(GOLDEN, 'tcrh_vectors.json'), 'utf8')) as {
  encode: Array<{ name: string; expect_hex: string; expect_deadlines_u: number[]; expect_sat: boolean }>;
}).encode;

describe('builder examples', () => {
  it.each(BUILDER_EXAMPLES.map((e) => [e.vector, e] as const))('reproduce golden vector %s', (name, example) => {
    const v = vectors.find((x) => x.name === name);
    expect(v).toBeDefined();
    const result = computeBuild(example.input);
    expect(result.ok).toBe(true);
    if (!result.ok || !v) return;
    expect(result.hex).toBe(v.expect_hex);
    expect(result.hops.map((h) => h.deadline)).toEqual(v.expect_deadlines_u);
    expect(result.sat).toBe(v.expect_sat);
    expect(result.hops.some((h) => h.clamped)).toBe(v.expect_sat);
  });

  it('explains bad input in words instead of building', () => {
    const result = computeBuild({
      rows: [
        { sid: '65535', delayMs: '1' },
        { sid: '12', delayMs: '-3' },
      ],
      slack: '0',
      unitCode: 1,
      ingress: '2016-01-01T00:00:00Z',
      nextHeader: 17,
    });
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors).toHaveLength(4);
    expect(result.errors.join(' ')).toMatch(/reserved/);
  });

  it('parses SIDs in decimal and hex, and refuses the reserved value', () => {
    expect(parseSid('0xF003')).toBe(61443);
    expect(parseSid('1201')).toBe(1201);
    expect(parseSid('0xFFFF')).toBeNull();
    expect(parseSid('-1')).toBeNull();
    expect(parseSid('1.5')).toBeNull();
  });
});

describe('stepper trace', () => {
  const header = fromForward([2, 3, 7], [6, 7, 8], 1000, 0, 17); // spec section 10
  const hex = bytesToHex(encode(header));

  it('is the spec section 10 vector', () => {
    expect(hex).toBe(vectors.find((v) => v.name === 'v0-3hop')?.expect_hex);
  });

  it('on-time arrivals are delivered with no flags', () => {
    const delays = defaultDelays(header, 'on-time');
    const trace = buildTrace(hex, delays, 'greedy');
    expect(trace.ok).toBe(true);
    if (!trace.ok) return;
    expect(trace.steps.map((s) => s.action)).toEqual(['send', 'forward', 'forward', 'deliver']);
    expect(trace.steps.every((s) => !s.late)).toBe(true);
    const last = trace.steps[trace.steps.length - 1];
    expect(last?.bytesOut ? decode(last.bytesOut).flags & 0x03 : -1).toBe(0);
  });

  it('a slow link is caught at the next hop and converts to greedy fallback', () => {
    const delays = defaultDelays(header, 'slow');
    const trace = buildTrace(hex, delays, 'greedy');
    expect(trace.ok).toBe(true);
    if (!trace.ok) return;
    const lateStep = trace.steps.find((s) => s.late);
    expect(lateStep?.hopIndex).toBe(2);
    expect(lateStep?.action).toBe('fallback');
    expect(lateStep?.nextSid).toBe(7);
    // arrival is strictly after the deadline unit
    expect((lateStep?.nowU ?? 0) > (lateStep?.deadlineU ?? 0)).toBe(true);
    expect(trace.steps[trace.steps.length - 1]?.action).toBe('deliver');
  });

  it('uses deadlines the engine computes', () => {
    const trace = buildTrace(hex, defaultDelays(header, 'on-time'), 'continue');
    if (!trace.ok) throw new Error('trace failed');
    expect(trace.deadlines).toEqual(deadlines(decode(hexToBytes(hex))));
  });

  it('a down link is a deviation of its own (step 7), even at the ingress', () => {
    const atHop = buildTrace(hex, defaultDelays(header, 'down'), 'drop', 2);
    if (!atHop.ok) throw new Error('trace failed');
    const down = atHop.steps.find((s) => s.kind === 'linkdown');
    expect(down?.hopIndex).toBe(1);
    expect(down?.devHopOut).toBe(1);
    expect(down?.action).toBe('fallback');
    expect(atHop.steps[atHop.steps.length - 1]?.action).toBe('deliver');

    const atIngress = buildTrace(hex, defaultDelays(header, 'down'), 'greedy', 1);
    if (!atIngress.ok) throw new Error('trace failed');
    const first = atIngress.steps.find((s) => s.kind === 'linkdown');
    expect(first?.hopIndex).toBe(0);
    expect(first?.devHopOut).toBe(0);
    expect(first?.bytesOut ? bytesToHex(first.bytesOut) : '').toBe('1102fd0003030000000003e8000708000307000206000000');
  });

  it('the drop policy discards a late packet', () => {
    const trace = buildTrace(hex, defaultDelays(header, 'slow'), 'drop');
    if (!trace.ok) throw new Error('trace failed');
    expect(trace.steps[trace.steps.length - 1]?.action).toBe('drop_late');
  });
});

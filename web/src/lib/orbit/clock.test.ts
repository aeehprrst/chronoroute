/**
 * Simulated clock and frame scheduling.
 */
import { describe, expect, it } from 'vitest';
import { clampScrub, createClock, jumpTo, simTimeAt, SCRUB_RANGE_MS, withSpeed } from './clock';
import { FrameBuffer, type Frame } from './frame-buffer';

const T = Date.parse('2026-10-10T14:02:22Z');

describe('clock', () => {
  it('runs at the chosen speed and never jumps on a speed change', () => {
    let c = createClock(T, 1000, 60);
    expect(simTimeAt(c, 2000)).toBe(T + 60_000);
    c = withSpeed(c, 2000, 0);
    expect(simTimeAt(c, 9000)).toBe(T + 60_000);
    c = withSpeed(c, 9000, 600);
    expect(simTimeAt(c, 10_000)).toBe(T + 60_000 + 600_000);
  });

  it('jumps keep the speed, and the scrub offset is limited to 6 hours', () => {
    const c = jumpTo(createClock(T, 0, 1), 5000, T - 3_600_000);
    expect(simTimeAt(c, 6000)).toBe(T - 3_600_000 + 1000);
    expect(clampScrub(7 * 3_600_000)).toBe(SCRUB_RANGE_MS);
    expect(clampScrub(-7 * 3_600_000)).toBe(-SCRUB_RANGE_MS);
  });
});

function fakeFrame(buffer: FrameBuffer, simMs: number): Frame {
  return { simMs, generation: buffer.generation, positions: new Float32Array(3), failed: 0 };
}

describe('FrameBuffer', () => {
  it('requests one frame per real second ahead of the clock while running', () => {
    const buffer = new FrameBuffer();
    buffer.reset();
    // At x60 a frame covers 60 s of simulated time.
    expect(buffer.requests(T, 60)).toEqual([T, T + 60_000]);
    expect(buffer.requests(T + 1000, 60)).toEqual([T + 120_000]);
    expect(buffer.requests(T + 2000, 60)).toEqual([]);
    expect(buffer.requests(T + 61_000, 60)).toEqual([T + 180_000]);
  });

  it('interpolates between the frames around the simulated time', () => {
    const buffer = new FrameBuffer();
    buffer.reset();
    buffer.add(fakeFrame(buffer, T));
    buffer.add(fakeFrame(buffer, T + 60_000));
    const pair = buffer.select(T + 15_000);
    expect(pair?.a.simMs).toBe(T);
    expect(pair?.b.simMs).toBe(T + 60_000);
    expect(pair?.alpha).toBeCloseTo(0.25, 12);
    // Past the last frame it holds the last frame instead of extrapolating.
    const held = buffer.select(T + 90_000);
    expect(held?.a.simMs).toBe(T + 60_000);
    expect(held?.alpha).toBe(0);
    expect(buffer.size).toBe(1);
  });

  it('keeps old frames on screen after a reset until a new frame arrives, then drops them', () => {
    const buffer = new FrameBuffer();
    buffer.reset();
    buffer.add(fakeFrame(buffer, T));
    const old = buffer.generation;
    buffer.reset();
    expect(buffer.add({ simMs: T + 1, generation: old, positions: new Float32Array(3), failed: 0 })).toBe(false);
    expect(buffer.select(T + 3_600_000)?.a.simMs).toBe(T);
    buffer.add(fakeFrame(buffer, T + 3_600_000));
    expect(buffer.size).toBe(1);
    expect(buffer.select(T + 3_600_000)?.a.simMs).toBe(T + 3_600_000);
  });

  it('requests exactly the paused instant once while paused', () => {
    const buffer = new FrameBuffer();
    buffer.reset();
    expect(buffer.requests(T, 0)).toEqual([T]);
    expect(buffer.requests(T, 0)).toEqual([]);
  });

  it('restarts the schedule when the clock has run far ahead (hidden tab)', () => {
    const buffer = new FrameBuffer();
    buffer.reset();
    buffer.requests(T, 1);
    const g = buffer.generation;
    expect(buffer.requests(T + 3_600_000, 1)).toEqual([T + 3_600_000, T + 3_601_000]);
    expect(buffer.generation).toBe(g + 1);
  });
});

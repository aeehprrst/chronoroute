/**
 * Scheduling and selection of propagated frames.
 *
 * The worker propagates every satellite at given simulated instants ("frames"). While the
 * clock runs, frames are requested one real second apart (sim step = speed x 1 s), so the
 * worker runs at 1 Hz; the renderer interpolates between the frame just before and the frame
 * just after the current simulated time. While paused, one frame at exactly the paused instant
 * is requested and shown without interpolation.
 *
 * Any control action calls reset(): frames already received stay on screen until the first
 * frame of the new generation arrives, then the old ones are dropped.
 */
import type { Speed } from './clock';

export interface Frame {
  simMs: number;
  generation: number;
  /** Scene positions, 3 floats per satellite; (0, 0, 0) where SGP4 failed. */
  positions: Float32Array;
  /** Satellites that failed in SGP4 at this instant (initialisation failures excluded). */
  failed: number;
}

export interface FramePair<F extends Frame = Frame> {
  a: F;
  b: F;
  /** Interpolation weight of b, in [0, 1]. */
  alpha: number;
}

export class FrameBuffer<F extends Frame = Frame> {
  private frames: F[] = [];
  private lastRequestedMs = Number.NaN;
  private _generation = 0;

  get generation(): number {
    return this._generation;
  }

  /** Start a new generation (after a jump or speed change). Returns the new generation. */
  reset(): number {
    this._generation += 1;
    this.lastRequestedMs = Number.NaN;
    return this._generation;
  }

  /** Add a frame from the worker. Frames from older generations are ignored. Returns true if kept. */
  add(frame: F): boolean {
    if (frame.generation !== this._generation) return false;
    // The first frame of a new generation replaces everything older.
    this.frames = this.frames.filter((f) => f.generation === this._generation && f.simMs !== frame.simMs);
    this.frames.push(frame);
    this.frames.sort((x, y) => x.simMs - y.simMs);
    return true;
  }

  /**
   * Simulated instants that should be requested now so that a frame after `simMs` is ready in
   * time. Call once per rendered frame; it returns an empty list most of the time.
   */
  requests(simMs: number, speed: Speed): number[] {
    const out: number[] = [];
    if (speed === 0) {
      if (this.lastRequestedMs !== simMs) {
        out.push(simMs);
        this.lastRequestedMs = simMs;
      }
      return out;
    }
    const step = speed * 1000;
    // Nothing requested yet in this generation, or the clock ran ahead (e.g. a hidden tab).
    if (!(this.lastRequestedMs >= simMs - step)) {
      if (!Number.isNaN(this.lastRequestedMs)) this.reset();
      out.push(simMs);
      this.lastRequestedMs = simMs;
    }
    while (this.lastRequestedMs < simMs + step) {
      this.lastRequestedMs += step;
      out.push(this.lastRequestedMs);
    }
    return out;
  }

  /** Frames to draw at `simMs`, or null before the first frame arrives. Drops frames that are no longer needed. */
  select(simMs: number): FramePair<F> | null {
    const frames = this.frames;
    if (frames.length === 0) return null;
    let i = -1;
    for (let k = 0; k < frames.length; k += 1) {
      if ((frames[k] as F).simMs <= simMs) i = k;
      else break;
    }
    if (i > 0) {
      frames.splice(0, i);
      i = 0;
    }
    const first = frames[0] as F;
    if (i === -1) return { a: first, b: first, alpha: 0 };
    const next = frames[1];
    if (!next || first.generation !== this._generation) return { a: first, b: first, alpha: 0 };
    const span = next.simMs - first.simMs;
    const alpha = span > 0 ? Math.min(1, Math.max(0, (simMs - first.simMs) / span)) : 0;
    return { a: first, b: next, alpha };
  }

  /** Number of frames held (for tests). */
  get size(): number {
    return this.frames.length;
  }
}

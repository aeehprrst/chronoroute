/** Messages between the globe (main thread) and src/workers/orbit.worker.ts. */
import type { OmmRecord } from '../data-types';
import type { InitError, SatelliteNow } from './propagate';

export type ToWorker =
  | { type: 'init'; records: OmmRecord[] }
  | { type: 'frame'; generation: number; simMs: number; selected: number }
  | { type: 'track'; index: number; centerMs: number }
  /** Route planner: Float64 TEME km of every satellite at simMs (NaN where SGP4 fails). */
  | { type: 'teme64'; requestId: number; simMs: number };

export type FromWorker =
  | { type: 'ready'; count: number; errors: InitError[] }
  | { type: 'init-failed'; message: string }
  | {
      type: 'frame';
      generation: number;
      simMs: number;
      positions: Float32Array;
      failed: number;
      selected: number;
      /** Details of the selected satellite at simMs (null if none selected or SGP4 failed). */
      selectedNow: SatelliteNow | null;
    }
  | { type: 'track'; index: number; centerMs: number; points: Float32Array }
  | { type: 'teme64'; requestId: number; simMs: number; teme: Float64Array; failed: number };

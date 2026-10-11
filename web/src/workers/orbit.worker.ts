/**
 * Orbit worker: holds the satellite.js satrecs for the whole snapshot and propagates them with
 * SGP4 on request (about once per real second while the clock runs). Positions are computed in
 * Float64, converted to scene units, and sent back as a transferred Float32Array.
 *
 * Requests from older generations (superseded by a jump or speed change) are dropped, so
 * dragging the time slider never builds up a backlog.
 */
import type { SatRec } from '../lib/orbit/sgp4';
import { initSatrecs, orbitTrackToScene, propagateAllTemeKm, propagateAllToScene, satelliteNow } from '../lib/orbit/propagate';
import type { FromWorker, ToWorker } from '../lib/orbit/worker-protocol';

/** The parts of the dedicated worker scope used here (typed without the webworker lib, which clashes with the DOM lib). */
interface WorkerScope {
  postMessage(message: FromWorker, transfer: Transferable[]): void;
  onmessage: ((event: MessageEvent<ToWorker>) => void) | null;
}
const scope = globalThis as unknown as WorkerScope;

let satrecs: Array<SatRec | null> = [];
let latestGeneration = -1;
type FrameRequest = Extract<ToWorker, { type: 'frame' }>;
let queue: FrameRequest[] = [];
let scheduled = false;

function post(message: FromWorker, transfer: Transferable[] = []): void {
  scope.postMessage(message, transfer);
}

function processQueue(): void {
  scheduled = false;
  // Keep only requests of the newest generation; serve them in time order.
  queue = queue.filter((q) => q.generation === latestGeneration);
  const request = queue.shift();
  if (!request) return;
  const positions = new Float32Array(satrecs.length * 3);
  const failed = propagateAllToScene(satrecs, request.simMs, positions);
  const sel = request.selected;
  const satrec = sel >= 0 ? satrecs[sel] : null;
  post(
    {
      type: 'frame',
      generation: request.generation,
      simMs: request.simMs,
      positions,
      failed,
      selected: sel,
      selectedNow: satrec ? satelliteNow(satrec, request.simMs) : null,
    },
    [positions.buffer],
  );
  if (queue.length > 0) schedule();
}

function schedule(): void {
  if (scheduled) return;
  scheduled = true;
  setTimeout(processQueue, 0);
}

scope.onmessage = (event: MessageEvent<ToWorker>) => {
  const message = event.data;
  switch (message.type) {
    case 'init': {
      try {
        const result = initSatrecs(message.records);
        satrecs = result.satrecs;
        post({ type: 'ready', count: satrecs.length, errors: result.errors });
      } catch (error) {
        post({ type: 'init-failed', message: error instanceof Error ? error.message : String(error) });
      }
      break;
    }
    case 'frame': {
      if (message.generation > latestGeneration) latestGeneration = message.generation;
      queue.push(message);
      schedule();
      break;
    }
    case 'track': {
      const satrec = satrecs[message.index];
      const points = satrec ? orbitTrackToScene(satrec, message.centerMs).points : new Float32Array(0);
      post({ type: 'track', index: message.index, centerMs: message.centerMs, points }, [points.buffer]);
      break;
    }
    case 'teme64': {
      // Full-precision positions for the route planner (the globe's Float32 frames are too coarse).
      const teme = new Float64Array(satrecs.length * 3);
      const failed = propagateAllTemeKm(satrecs, message.simMs, teme);
      post({ type: 'teme64', requestId: message.requestId, simMs: message.simMs, teme, failed }, [teme.buffer]);
      break;
    }
  }
};

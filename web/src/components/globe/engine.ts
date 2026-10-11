/**
 * GlobeEngine: the non-React state of a globe (clock, frame buffer, selection, worker).
 * React components read it on a slow timer; the 3D canvas reads it every animation frame.
 */
import type { OmmRecord } from '../../lib/data-types';
import { createClock, jumpTo, simTimeAt, withSpeed, type ClockState, type Speed } from '../../lib/orbit/clock';
import { FrameBuffer, type Frame, type FramePair } from '../../lib/orbit/frame-buffer';
import { meanAltitudeKm, classifyShell, SHELLS } from '../../lib/orbit/shells';
import type { InitError, SatelliteNow } from '../../lib/orbit/propagate';
import type { FromWorker, ToWorker } from '../../lib/orbit/worker-protocol';
import { parseUtc } from '../../lib/format';

/** Per-satellite facts taken from the element sets (index = snapshot row). */
export interface SatMeta {
  count: number;
  names: string[];
  objectIds: string[];
  norad: Int32Array;
  inclinationDeg: Float32Array;
  meanAltitudeKm: Float32Array;
  epochMs: Float64Array;
  epochText: string[];
  dataSource: Array<string | null>;
  shell: Uint8Array;
  /** 1 where satellite.js could not initialise the element set (not drawn, listed in the UI). */
  initFailed: Uint8Array;
}

export function buildMeta(records: readonly OmmRecord[]): SatMeta {
  const n = records.length;
  const meta: SatMeta = {
    count: n,
    names: new Array<string>(n),
    objectIds: new Array<string>(n),
    norad: new Int32Array(n),
    inclinationDeg: new Float32Array(n),
    meanAltitudeKm: new Float32Array(n),
    epochMs: new Float64Array(n),
    epochText: new Array<string>(n),
    dataSource: new Array<string | null>(n),
    shell: new Uint8Array(n),
    initFailed: new Uint8Array(n),
  };
  records.forEach((r, i) => {
    meta.names[i] = r.OBJECT_NAME;
    meta.objectIds[i] = r.OBJECT_ID;
    meta.norad[i] = r.NORAD_CAT_ID;
    meta.inclinationDeg[i] = r.INCLINATION;
    meta.meanAltitudeKm[i] = meanAltitudeKm(r.MEAN_MOTION);
    meta.epochMs[i] = parseUtc(r.EPOCH);
    meta.epochText[i] = r.EPOCH;
    meta.dataSource[i] = typeof r.DATA_SOURCE === 'string' ? r.DATA_SOURCE : null;
    meta.shell[i] = classifyShell(r.INCLINATION, r.MEAN_MOTION);
  });
  return meta;
}

export interface EngineFrame extends Frame {
  selected: number;
  selectedNow: SatelliteNow | null;
}

export interface TrackState {
  index: number;
  centerMs: number;
  points: Float32Array;
}

export interface FlyRequest {
  index: number;
  serial: number;
}

export interface CameraCommand {
  kind: 'zoom-in' | 'zoom-out' | 'reset';
  serial: number;
}

export class GlobeEngine {
  readonly meta: SatMeta;
  readonly buffer = new FrameBuffer<EngineFrame>();
  clock: ClockState;
  /** Selected row, or -1. */
  selected = -1;
  /** Visibility per ShellId. */
  readonly visible: boolean[] = SHELLS.map(() => true);
  visibilityVersion = 0;
  initErrors: InitError[] = [];
  ready = false;
  track: TrackState | null = null;
  fly: FlyRequest | null = null;
  cameraCommand: CameraCommand | null = null;
  /** Last value computed by pump(). */
  simMs: number;
  pair: FramePair<EngineFrame> | null = null;

  private worker: Worker | null = null;
  private trackPending = -1;
  private flySerial = 0;
  private cameraSerial = 0;

  constructor(meta: SatMeta, startSimMs: number, speed: Speed) {
    this.meta = meta;
    this.clock = createClock(startSimMs, Date.now(), speed);
    this.simMs = startSimMs;
  }

  /** Start the worker and send it the element sets. Resolves when the satrecs are ready. */
  start(worker: Worker, records: OmmRecord[]): Promise<void> {
    this.worker = worker;
    return new Promise((resolve, reject) => {
      worker.onmessage = (event: MessageEvent<FromWorker>) => this.onMessage(event.data, resolve, reject);
      worker.onerror = (event) => reject(new Error(event.message || 'The orbit worker failed to start.'));
      this.post({ type: 'init', records });
    });
  }

  dispose(): void {
    this.worker?.terminate();
    this.worker = null;
  }

  private post(message: ToWorker): void {
    this.worker?.postMessage(message);
  }

  private onMessage(message: FromWorker, resolve: () => void, reject: (e: Error) => void): void {
    switch (message.type) {
      case 'ready':
        this.initErrors = message.errors;
        for (const e of message.errors) this.meta.initFailed[e.index] = 1;
        this.ready = true;
        resolve();
        break;
      case 'init-failed':
        reject(new Error(message.message));
        break;
      case 'frame':
        this.buffer.add({
          simMs: message.simMs,
          generation: message.generation,
          positions: message.positions,
          failed: message.failed,
          selected: message.selected,
          selectedNow: message.selectedNow,
        });
        break;
      case 'track':
        if (message.index === this.trackPending) this.trackPending = -1;
        if (message.index === this.selected) {
          this.track = { index: message.index, centerMs: message.centerMs, points: message.points };
        }
        break;
    }
  }

  /** Advance: request frames the worker should compute, and pick the frames to draw now. */
  pump(): FramePair<EngineFrame> | null {
    const simMs = simTimeAt(this.clock, Date.now());
    this.simMs = simMs;
    if (this.ready) {
      const times = this.buffer.requests(simMs, this.clock.speed);
      for (const t of times) {
        this.post({ type: 'frame', generation: this.buffer.generation, simMs: t, selected: this.selected });
      }
      // Refresh the orbit path of the selected satellite when it is missing or 20 min old.
      if (this.selected >= 0 && this.trackPending !== this.selected) {
        const stale =
          !this.track || this.track.index !== this.selected || Math.abs(simMs - this.track.centerMs) > 20 * 60_000;
        if (stale) {
          this.trackPending = this.selected;
          this.post({ type: 'track', index: this.selected, centerMs: simMs });
        }
      }
    }
    this.pair = this.buffer.select(simMs);
    return this.pair;
  }

  setSpeed(speed: Speed): void {
    this.clock = withSpeed(this.clock, Date.now(), speed);
    this.buffer.reset();
  }

  jump(simMs: number): void {
    this.clock = jumpTo(this.clock, Date.now(), simMs);
    this.buffer.reset();
  }

  select(index: number, flyTo: boolean): void {
    this.selected = index;
    if (index < 0) this.track = null;
    // Ask for the details of the new selection in the next frames.
    this.buffer.reset();
    if (flyTo && index >= 0) {
      this.flySerial += 1;
      this.fly = { index, serial: this.flySerial };
    }
  }

  /** Zoom or reset the view (buttons; the canvas applies it on its next frame). */
  commandCamera(kind: CameraCommand['kind']): void {
    this.cameraSerial += 1;
    this.cameraCommand = { kind, serial: this.cameraSerial };
  }

  setVisible(shell: number, visible: boolean): void {
    this.visible[shell] = visible;
    this.visibilityVersion += 1;
  }

  /** Details of the selected satellite from the frame on screen, with that frame's time. */
  selectedDetails(): { now: SatelliteNow | null; atMs: number } | null {
    const pair = this.pair;
    if (this.selected < 0 || !pair) return null;
    const frame = pair.a.selected === this.selected ? pair.a : pair.b.selected === this.selected ? pair.b : null;
    if (!frame) return null;
    return { now: frame.selectedNow, atMs: frame.simMs };
  }

  /** SGP4 failures in the frame on screen (initialisation failures not included). */
  failedNow(): number {
    return this.pair?.a.failed ?? 0;
  }

  /**
   * Satellites drawn in the frame on screen: in a visible colour group, and with a position
   * (the worker writes (0, 0, 0) where SGP4 failed or the element set never initialised).
   * Counted directly, so a satellite that is both hidden and failed is not subtracted twice.
   * Null until the first frame has arrived.
   */
  drawnNow(): number | null {
    const frame = this.pair?.a;
    if (!frame) return null;
    const p = frame.positions;
    let drawn = 0;
    for (let i = 0; i < this.meta.count; i += 1) {
      if (this.meta.initFailed[i]) continue;
      if (!(this.visible[this.meta.shell[i] ?? 4] ?? true)) continue;
      const k = 3 * i;
      if (p[k] === 0 && p[k + 1] === 0 && p[k + 2] === 0) continue;
      drawn += 1;
    }
    return drawn;
  }
}

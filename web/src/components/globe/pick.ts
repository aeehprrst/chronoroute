/**
 * Screen-space picking: the visible satellite whose drawn position is nearest to the pointer,
 * within `radiusPx`. Positions are interpolated exactly as the vertex shader does; satellites
 * hidden behind the Earth are skipped.
 */
import { Vector3, type Camera } from 'three';
import { interpolateRow } from '../../lib/orbit/interp';
import type { FramePair } from '../../lib/orbit/frame-buffer';

export interface PickInput {
  camera: Camera;
  pair: FramePair;
  visible: readonly boolean[];
  shells: Uint8Array;
  /** Pointer position in CSS pixels relative to the canvas, and the canvas size. */
  x: number;
  y: number;
  width: number;
  height: number;
  radiusPx: number;
}

/** Radius used for the occlusion test: the polar radius, so limb satellites are never wrongly hidden. */
const OCCLUDER_RADIUS = 0.9966;

/** True if the segment from the camera to `p` passes through the Earth before reaching `p`. */
export function hiddenByEarth(cam: Vector3, p: Vector3): boolean {
  const dx = p.x - cam.x;
  const dy = p.y - cam.y;
  const dz = p.z - cam.z;
  const a = dx * dx + dy * dy + dz * dz;
  const b = 2 * (cam.x * dx + cam.y * dy + cam.z * dz);
  const c = cam.x * cam.x + cam.y * cam.y + cam.z * cam.z - OCCLUDER_RADIUS * OCCLUDER_RADIUS;
  const disc = b * b - 4 * a * c;
  if (disc <= 0) return false;
  const t = (-b - Math.sqrt(disc)) / (2 * a);
  return t > 0 && t < 1;
}

/** Index of the picked satellite, or -1. */
export function pickSatellite(input: PickInput): number {
  const { camera, pair, visible, shells, x, y, width, height, radiusPx } = input;
  const n = shells.length;
  const tmp = new Float32Array(3);
  const p = new Vector3();
  const cam = camera.position.clone();
  let best = -1;
  let bestD2 = radiusPx * radiusPx;
  for (let i = 0; i < n; i += 1) {
    if (!visible[shells[i] ?? 4]) continue;
    if (!interpolateRow(pair.a.positions, pair.b.positions, i, pair.alpha, tmp)) continue;
    p.set(tmp[0]!, tmp[1]!, tmp[2]!);
    if (hiddenByEarth(cam, p)) continue;
    p.project(camera);
    if (p.z > 1 || p.z < -1) continue;
    const sx = ((p.x + 1) / 2) * width;
    const sy = ((1 - p.y) / 2) * height;
    const d2 = (sx - x) * (sx - x) + (sy - y) * (sy - y);
    if (d2 < bestD2) {
      bestD2 = d2;
      best = i;
    }
  }
  return best;
}

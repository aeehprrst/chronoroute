/**
 * Build-time readers (Node only; import from .astro frontmatter, never from client code).
 * Paths are resolved from the project root (web/), which is the working directory of
 * `astro build` / `astro dev` when run through the npm scripts.
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { parseLatestPointer, parseManifest } from './data';
import type { SnapshotManifest } from './data-types';

/** web/public/data */
export const PUBLIC_DATA_DIR = path.resolve(process.cwd(), 'public', 'data');
/** The shared spec directory, one level above web/ (../spec). Read-only. */
export const SPEC_DIR = path.resolve(process.cwd(), '..', 'spec');

export type ManifestResult =
  | { ok: true; manifest: SnapshotManifest }
  | { ok: false; reason: string };

/** Read public/data/latest.json and the manifest it points to. Never throws. */
export async function readLatestManifest(dataDir: string = PUBLIC_DATA_DIR): Promise<ManifestResult> {
  try {
    const pointer = parseLatestPointer(JSON.parse(await readFile(path.join(dataDir, 'latest.json'), 'utf8')));
    const manifest = parseManifest(
      JSON.parse(await readFile(path.join(dataDir, pointer.path, 'manifest.json'), 'utf8')),
    );
    if (manifest.snapshot_id !== pointer.snapshot_id) {
      return { ok: false, reason: 'latest.json and manifest.json name different snapshots.' };
    }
    return { ok: true, manifest };
  } catch (error) {
    const code = (error as { code?: unknown }).code;
    if (code === 'ENOENT') {
      return { ok: false, reason: 'No snapshot has been published to public/data yet.' };
    }
    return { ok: false, reason: error instanceof Error ? error.message : String(error) };
  }
}

/** One `encode` vector of spec/golden/tcrh_vectors.json (only the keys the site uses). */
export interface TcrhEncodeVector {
  name: string;
  note: string;
  sids_fwd: number[];
  unit_code: number;
  next_header: number;
  expect_hex: string;
  expect_deadlines_u: number[];
  expect_deltas_fwd: number[];
  expect_epoch_base: number;
  expect_flags: number;
  expect_size: number;
  expect_sat: boolean;
}

/** Read every T-CRH `encode` golden vector from ../spec/golden/tcrh_vectors.json. */
export async function readTcrhEncodeVectors(specDir: string = SPEC_DIR): Promise<TcrhEncodeVector[]> {
  const raw: unknown = JSON.parse(await readFile(path.join(specDir, 'golden', 'tcrh_vectors.json'), 'utf8'));
  if (typeof raw !== 'object' || raw === null || !Array.isArray((raw as { encode?: unknown }).encode)) {
    throw new Error('tcrh_vectors.json: missing "encode" array');
  }
  return (raw as { encode: TcrhEncodeVector[] }).encode;
}

/** Read one golden vector by name. Returns null (never invents one) when it is missing. */
export async function readTcrhEncodeVector(name: string, specDir: string = SPEC_DIR): Promise<TcrhEncodeVector | null> {
  try {
    const vectors = await readTcrhEncodeVectors(specDir);
    return vectors.find((vector) => vector.name === name) ?? null;
  } catch {
    return null;
  }
}

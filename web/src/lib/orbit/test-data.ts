/**
 * Test helpers (Node only; imported by *.test.ts, never by browser code).
 *
 *  - readPublishedSnapshot(): the snapshot the site will serve (public/data, written by
 *    `npm run data` / CI). It can be any snapshot: the pinned one, or a fresh download in the
 *    refresh workflow. Tests on it must not assume which.
 *  - readPinnedRecords(): the raw CelesTrak SupGP objects of the experiments' pinned snapshot
 *    data/pinned/20261010T1358Z-celestrak (committed, never edited). Tests with fixed reference
 *    values (positions recorded from Python at a fixed instant) use this, so they do not depend
 *    on which snapshot the site is built from.
 *  - findPinnedRawFor(manifest): the raw download a published snapshot was made from, found
 *    under data/pinned/ by its sha256 (the manifest's sha256_raw).
 */
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { ommRowsToRecords, parseLatestPointer, parseManifest } from '../data';
import type { OmmRecord, SnapshotManifest } from '../data-types';

const WEB_DIR = path.resolve(import.meta.dirname, '..', '..', '..');
export const PUBLIC_DATA_DIR = path.join(WEB_DIR, 'public', 'data');
export const PINNED_ROOT = path.join(WEB_DIR, '..', 'data', 'pinned');
/** The experiments' pinned snapshot (task brief: use it for all experiments). */
export const PINNED_DIR = path.join(PINNED_ROOT, '20261010T1358Z-celestrak');

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, 'utf8'));
}

export interface PublishedSnapshot {
  manifest: SnapshotManifest;
  omm: { fields: string[]; rows: unknown[][] };
  records: OmmRecord[];
}

export async function readPublishedSnapshot(): Promise<PublishedSnapshot> {
  const pointer = parseLatestPointer(await readJson(path.join(PUBLIC_DATA_DIR, 'latest.json')));
  const manifest = parseManifest(await readJson(path.join(PUBLIC_DATA_DIR, pointer.path, 'manifest.json')));
  const omm = (await readJson(path.join(PUBLIC_DATA_DIR, pointer.path, manifest.files.omm))) as PublishedSnapshot['omm'];
  return { manifest, omm, records: ommRowsToRecords(omm) };
}

/** Raw OMM objects of the pinned 2026-10-10 SupGP download (11,130 objects, none excluded). */
export async function readPinnedRecords(): Promise<OmmRecord[]> {
  const raw = (await readJson(path.join(PINNED_DIR, 'starlink_supgp.json'))) as OmmRecord[];
  return [...raw].sort((a, b) => a.NORAD_CAT_ID - b.NORAD_CAT_ID);
}

/**
 * The raw file whose sha256 equals the manifest's sha256_raw: first in the folder that
 * scripts/build-data.sh recorded in web/.parity/source.json (a fresh download can live outside
 * data/pinned in CI), then in every data/pinned/<folder>/.
 */
export function findPinnedRawFor(manifest: SnapshotManifest): string | null {
  if (manifest.raw_file === null) return null;
  const candidates: string[] = [];
  try {
    const source = JSON.parse(readFileSync(path.join(WEB_DIR, '.parity', 'source.json'), 'utf8')) as { pinned_dir?: unknown };
    if (typeof source.pinned_dir === 'string') candidates.push(path.join(source.pinned_dir, manifest.raw_file));
  } catch {
    // no source.json: only data/pinned is searched
  }
  for (const folder of readdirSync(PINNED_ROOT).sort()) candidates.push(path.join(PINNED_ROOT, folder, manifest.raw_file));
  for (const file of candidates) {
    try {
      if (!statSync(file).isFile()) continue;
    } catch {
      continue;
    }
    if (createHash('sha256').update(readFileSync(file)).digest('hex') === manifest.sha256_raw) return file;
  }
  return null;
}

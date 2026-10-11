/**
 * Checks the files in public/data against the data contract (DATA_CONTRACT.md).
 * They are produced by the Python pipeline (`npm run data`, and CI before every build), or,
 * for offline development only, by `npm run data:offline-fallback`.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { json2satrec, propagate } from 'satellite.js';
import {
  DataContractError,
  isDevelopmentSnapshot,
  ommRowsToRecords,
  parseLatestPointer,
  parseManifest,
} from '../src/lib/data';
import { OMM_FIELDS } from '../src/lib/data-types';
import { readLatestManifest } from '../src/lib/data-build';
import { parseCities } from '../src/lib/route/cities';
import { DEFAULT_SHELL } from '../src/lib/route/context';
import { parseRegistry } from '../src/lib/route/sids';
import { buildShellNetwork, parseIslDoc, parseShellsDoc } from '../src/lib/route/topology';

const DATA_DIR = path.resolve(import.meta.dirname, '..', 'public', 'data');
const readJson = async (rel: string): Promise<unknown> =>
  JSON.parse(await readFile(path.join(DATA_DIR, rel), 'utf8'));

// Missing files fail here with ENOENT: run `npm run data` first.
const pointer = parseLatestPointer(await readJson('latest.json'));
const manifest = parseManifest(await readJson(`${pointer.path}manifest.json`));
const omm = (await readJson(`${pointer.path}${manifest.files.omm}`)) as { fields: string[]; rows: unknown[][] };
const records = ommRowsToRecords(omm);

describe('published snapshot in public/data', () => {
  it('latest.json points at the manifest it names', () => {
    expect(manifest.snapshot_id).toBe(pointer.snapshot_id);
    expect(pointer.path).toBe(`snapshots/${pointer.snapshot_id}/`);
  });

  it('has one row per counted element set, in the contract column order', () => {
    expect(omm.fields).toEqual([...OMM_FIELDS]);
    expect(records.length).toBe(manifest.count);
    expect(manifest.count).toBeGreaterThan(0);
  });

  it('is sorted by NORAD_CAT_ID with no duplicates', () => {
    const ids = records.map((r) => r.NORAD_CAT_ID);
    for (let i = 1; i < ids.length; i += 1) expect(ids[i]!).toBeGreaterThan(ids[i - 1]!);
  });

  it('keeps only epochs within max_epoch_age_days of the download, matching the manifest range', () => {
    const fetched = Date.parse(manifest.fetched_utc);
    const epochs = records.map((r) => Date.parse(`${r.EPOCH}Z`)).sort((a, b) => a - b);
    expect(fetched - epochs[0]!).toBeLessThanOrEqual(manifest.max_epoch_age_days * 86_400_000);
    expect(epochs[0]).toBe(Date.parse(manifest.epoch_min));
    expect(epochs[epochs.length - 1]).toBe(Date.parse(manifest.epoch_max));
  });

  it('propagates with satellite.js at the download time (first, six-digit and last rows)', () => {
    const sixDigit = records.find((r) => r.NORAD_CAT_ID >= 100000);
    const samples = [records[0], sixDigit, records[records.length - 1]].filter((r) => r !== undefined);
    expect(samples.length).toBeGreaterThan(0);
    for (const record of samples) {
      const satrec = json2satrec(record);
      expect(satrec.error).toBe(0);
      const state = propagate(satrec, new Date(manifest.fetched_utc));
      expect(state).toBeTruthy();
      const position = state?.position;
      expect(position && typeof position === 'object').toBe(true);
      if (position && typeof position === 'object') {
        // LEO: geocentric radius between 6,500 km and 8,500 km (TEME, km).
        const r = Math.hypot(position.x, position.y, position.z);
        expect(r).toBeGreaterThan(6500);
        expect(r).toBeLessThan(8500);
      }
    }
  });

  it('is readable by the build-time reader used by DataBadge', async () => {
    const result = await readLatestManifest(DATA_DIR);
    expect(result.ok).toBe(true);
  });
});

describe('route planner files (written by the Python pipeline, not by the offline fallback)', () => {
  const pipeline = !isDevelopmentSnapshot(manifest);

  it('the snapshot comes from the Python pipeline (CI never deploys the offline fallback)', () => {
    if (process.env['CI']) expect(pipeline).toBe(true);
    if (pipeline) expect(manifest.pipeline).toMatch(/^chronoroute-pipeline /);
  });

  it.runIf(pipeline)('shells.json and isl_grid4.json describe this snapshot at its download time', async () => {
    const shells = parseShellsDoc(await readJson(`${pointer.path}shells.json`));
    const isl = parseIslDoc(await readJson(`${pointer.path}isl_grid4.json`));
    expect(shells.snapshot_id).toBe(manifest.snapshot_id);
    expect(isl.snapshot_id).toBe(manifest.snapshot_id);
    expect(shells.reference_utc).toBe(manifest.fetched_utc);
    expect(isl.reference_utc).toBe(manifest.fetched_utc);
    // Every satellite named by the topology files is an element set of this snapshot.
    const ids = new Set(records.map((r) => r.NORAD_CAT_ID));
    for (const shell of shells.shells) for (const plane of shell.planes) for (const n of plane) expect(ids.has(n)).toBe(true);
    // The route planner's shell can be built from them (degree <= 4, pairs inside the planes, ...).
    const net = buildShellNetwork(shells, isl, DEFAULT_SHELL);
    expect(net.norads.length).toBeGreaterThan(1000);
  });

  it.runIf(pipeline)('data/static holds verbatim copies of the repository city list and SID registry', async () => {
    const repoStatic = path.resolve(DATA_DIR, '..', '..', '..', 'data', 'static');
    for (const name of ['cities.csv', 'sid_registry.json']) {
      expect(await readFile(path.join(DATA_DIR, 'static', name), 'utf8')).toBe(await readFile(path.join(repoStatic, name), 'utf8'));
    }
    expect(parseCities(await readFile(path.join(DATA_DIR, 'static', 'cities.csv'), 'utf8')).length).toBe(60);
    expect(() => parseRegistry(JSON.parse(readFileSync(path.join(DATA_DIR, 'static', 'sid_registry.json'), 'utf8')))).not.toThrow();
  });
});

describe('contract validators reject bad data', () => {
  it('rejects a manifest whose counts do not add up', async () => {
    const good = (await readJson(`${pointer.path}manifest.json`)) as Record<string, unknown>;
    expect(() => parseManifest({ ...good, count_raw: (good['count_raw'] as number) + 1 })).toThrow(DataContractError);
    expect(() => parseManifest({ ...good, fetched_utc: '2026-10-10 14:02:22' })).toThrow(DataContractError);
  });

  it('rejects a wrong schema, and optional fields of the wrong type', async () => {
    const good = (await readJson(`${pointer.path}manifest.json`)) as Record<string, unknown>;
    expect(() => parseManifest({ ...good, schema: 'something-else/2' })).toThrow(DataContractError);
    expect(() => parseManifest({ ...good, max_epoch_age_days: 0 })).toThrow(DataContractError);
    expect(() => parseManifest({ ...good, files: 'omm.min.json' })).toThrow(DataContractError);
  });

  it('accepts a manifest with only the fields of the project brief, filling in the defaults', async () => {
    const good = (await readJson(`${pointer.path}manifest.json`)) as Record<string, unknown>;
    const goodExcluded = good['excluded'] as Record<string, unknown>;
    const minimal: Record<string, unknown> = {
      snapshot_id: good['snapshot_id'],
      source: good['source'],
      source_url: good['source_url'],
      fetched_utc: good['fetched_utc'],
      http_date: good['http_date'],
      count: good['count'],
      epoch_min: good['epoch_min'],
      epoch_median: good['epoch_median'],
      epoch_max: good['epoch_max'],
      sha256_raw: good['sha256_raw'],
      excluded: { stale_epoch: goodExcluded['stale_epoch'], sgp4_error: goodExcluded['sgp4_error'] },
      attribution: good['attribution'],
      pipeline: 'python pipeline 0123abc',
    };
    const parsed = parseManifest(minimal);
    expect(parsed.schema).toBe('chronoroute.web-snapshot/1');
    expect(parsed.excluded.invalid).toBe(0);
    expect(parsed.excluded.duplicate).toBe(0);
    expect(parsed.count_raw).toBe(
      (good['count'] as number) + (goodExcluded['stale_epoch'] as number) + (goodExcluded['sgp4_error'] as number),
    );
    expect(parsed.max_epoch_age_days).toBe(3);
    expect(parsed.raw_file).toBeNull();
    expect(parsed.sgp4_check).toBeNull();
    expect(parsed.files.omm).toBe('omm.min.json');
    // The brief's fields stay required.
    const withoutSha = { ...minimal };
    delete withoutSha['sha256_raw'];
    expect(() => parseManifest(withoutSha)).toThrow(DataContractError);
    expect(() => parseManifest({ ...minimal, excluded: { stale_epoch: 0 } })).toThrow(DataContractError);
  });

  it('rejects rows of the wrong width', () => {
    expect(() => ommRowsToRecords({ fields: [...OMM_FIELDS], rows: [[1, 2, 3]] })).toThrow(DataContractError);
  });
});

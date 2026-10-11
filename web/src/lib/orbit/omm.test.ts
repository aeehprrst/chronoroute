/**
 * OMM reconstruction: the compact omm.min.json rows, turned back into objects by
 * ommRowsToRecords(), must equal the raw CelesTrak objects they were made from, value for
 * value, and must initialise in satellite.js, including six-digit NORAD IDs.
 *
 * The published snapshot can be any download (the pinned one, or a fresh one in the refresh
 * workflow); its raw file is found under data/pinned/ by the manifest's sha256_raw.
 */
import { describe, expect, it } from 'vitest';
import { readFile } from 'node:fs/promises';
import { json2satrec } from 'satellite.js';
import { ommRowsToRecords } from '../data';
import { OMM_FIELDS } from '../data-types';
import { initSatrecs } from './propagate';
import { findPinnedRawFor, readPinnedRecords, readPublishedSnapshot } from './test-data';

const snapshot = await readPublishedSnapshot();
const rawPath = findPinnedRawFor(snapshot.manifest);
if (rawPath === null) {
  throw new Error(
    `No raw file under data/pinned/ matches sha256_raw ${snapshot.manifest.sha256_raw} of the published snapshot (run \`npm run data\`).`,
  );
}
const raw = JSON.parse(await readFile(rawPath, 'utf8')) as Array<Record<string, unknown>>;

describe('OMM reconstruction round trip', () => {
  it(`rebuilds every kept raw object exactly (${snapshot.records.length} element sets)`, () => {
    // Newest EPOCH per NORAD id (the contract's duplicate rule) for the comparison.
    const byId = new Map<number, Record<string, unknown>>();
    for (const o of raw) {
      const id = o['NORAD_CAT_ID'] as number;
      const prev = byId.get(id);
      if (!prev || String(o['EPOCH']) > String(prev['EPOCH'])) byId.set(id, o);
    }
    expect(snapshot.records.length).toBe(snapshot.manifest.count);
    for (const record of snapshot.records) {
      const source = byId.get(record.NORAD_CAT_ID);
      expect(source, `NORAD ${record.NORAD_CAT_ID} missing from the raw file`).toBeDefined();
      expect(record).toEqual(source);
    }
  });

  it('re-encodes to the same rows (objects -> rows -> objects -> rows)', () => {
    const rows = snapshot.records.map((r) => OMM_FIELDS.map((f) => (r[f] === undefined ? null : r[f])));
    expect(rows).toEqual(snapshot.omm.rows);
    expect(ommRowsToRecords({ fields: [...OMM_FIELDS], rows })).toEqual(snapshot.records);
  });

  it('handles six-digit NORAD IDs: 100001 (STARLINK-38128) of the pinned snapshot initialises in satellite.js', async () => {
    const pinned = await readPinnedRecords();
    const record = pinned.find((r) => r.NORAD_CAT_ID === 100001);
    expect(record?.OBJECT_NAME).toBe('STARLINK-38128');
    const satrec = json2satrec(record!);
    expect(satrec.error).toBe(0);
    expect(satrec.satnum).toBe('100001');
    // ... and every six-digit id of the published snapshot does too.
    const six = snapshot.records.filter((r) => r.NORAD_CAT_ID >= 100000);
    expect(six.length).toBeGreaterThan(0);
    for (const r of six) expect(json2satrec(r).satnum).toBe(String(r.NORAD_CAT_ID));
  });

  it('initialises every element set of the snapshot (failures would be listed, not dropped)', () => {
    const { satrecs, errors } = initSatrecs(snapshot.records);
    expect(satrecs.length).toBe(snapshot.records.length);
    expect(errors).toEqual([]);
    expect(satrecs.every((s) => s !== null)).toBe(true);
  });

  it('reports a broken element set instead of dropping it silently', () => {
    const good = snapshot.records[0]!;
    const broken = { ...good, NORAD_CAT_ID: 999999, OBJECT_NAME: 'BROKEN', ECCENTRICITY: 1.5 };
    const { satrecs, errors } = initSatrecs([good, broken]);
    expect(satrecs[0]).not.toBeNull();
    expect(satrecs[1]).toBeNull();
    expect(errors).toHaveLength(1);
    expect(errors[0]).toMatchObject({ index: 1, norad: 999999, name: 'BROKEN' });
  });
});

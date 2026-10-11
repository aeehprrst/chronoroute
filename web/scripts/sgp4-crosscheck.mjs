#!/usr/bin/env node
/**
 * Prints satellite.js SGP4 positions (TEME, km) for a few satellites of the published
 * snapshot, for comparison with the Python reference recorded in
 * src/lib/orbit/propagate.test.ts (python-sgp4 2.27, sgp4.omm.initialize + Satrec.sgp4).
 *
 * Usage (from web/):
 *   node scripts/sgp4-crosscheck.mjs [ISO_UTC_TIME] [NORAD ...]
 * Defaults: the snapshot download time (manifest fetched_utc) and NORAD 44714 48881 100001.
 *
 * Output: one JSON object per line. Reads public/data only; writes nothing.
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { json2satrec, propagate } from 'satellite.js';

const webDir = path.resolve(import.meta.dirname, '..');
const dataDir = path.join(webDir, 'public', 'data');
const readJson = async (file) => JSON.parse(await readFile(file, 'utf8'));

const latest = await readJson(path.join(dataDir, 'latest.json'));
const manifest = await readJson(path.join(dataDir, latest.path, 'manifest.json'));
const omm = await readJson(path.join(dataDir, latest.path, manifest.files.omm));

const [timeArg, ...idArgs] = process.argv.slice(2);
const at = new Date(timeArg ?? manifest.fetched_utc);
if (Number.isNaN(at.getTime())) {
  console.error(`Not an ISO 8601 time: ${timeArg}`);
  process.exit(2);
}
const ids = (idArgs.length > 0 ? idArgs : ['44714', '48881', '100001']).map(Number);

// Same reconstruction as ommRowsToRecords() in src/lib/data.ts: fields[i] -> row[i], nulls dropped.
const records = omm.rows.map((row) => {
  const record = {};
  omm.fields.forEach((field, i) => {
    if (row[i] !== null) record[field] = row[i];
  });
  return record;
});

const require = createRequire(import.meta.url);
const version = require(path.join(webDir, 'node_modules', 'satellite.js', 'package.json')).version;
console.log(JSON.stringify({ library: 'satellite.js', version, at_utc: at.toISOString(), snapshot: manifest.snapshot_id }));

let failures = 0;
for (const id of ids) {
  const record = records.find((r) => r.NORAD_CAT_ID === id);
  if (!record) {
    console.log(JSON.stringify({ norad: id, error: 'not in snapshot' }));
    failures += 1;
    continue;
  }
  const satrec = json2satrec(record);
  const state = satrec.error === 0 ? propagate(satrec, at) : null;
  if (!state) {
    console.log(JSON.stringify({ norad: id, name: record.OBJECT_NAME, error: `SGP4 error ${satrec.error}` }));
    failures += 1;
    continue;
  }
  const r = state.position;
  const v = state.velocity;
  console.log(
    JSON.stringify({
      norad: id,
      name: record.OBJECT_NAME,
      epoch: record.EPOCH,
      satnum: satrec.satnum,
      r_km: [r.x, r.y, r.z].map((x) => Number(x.toFixed(6))),
      v_km_s: [v.x, v.y, v.z].map((x) => Number(x.toFixed(9))),
    }),
  );
}
process.exit(failures === 0 ? 0 : 1);

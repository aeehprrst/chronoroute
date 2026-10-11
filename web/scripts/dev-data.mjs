#!/usr/bin/env node
/**
 * OFFLINE FALLBACK for local development only. NEVER used by CI or by any deployment.
 *
 * The site's data comes from the project's Python pipeline: `npm run data`
 * (scripts/build-data.sh -> `cr export web`), which also writes the route planner's files
 * (shells.json, isl_grid4.json, data/static/) and the parity check. Use this script only when
 * you cannot run Python (e.g. on a machine without the venv) and only need the globe: it
 * converts the pinned CelesTrak SupGP snapshot (../data/pinned/<dir>/starlink_supgp.json)
 * into the three files of the data contract (DATA_CONTRACT.md):
 *
 *   public/data/latest.json
 *   public/data/snapshots/<id>/manifest.json
 *   public/data/snapshots/<id>/omm.min.json
 *
 * Its manifest says "pipeline": "dev-data.mjs (development)", and the site then shows a
 * "development snapshot" note. The route planner says it cannot start (no topology files),
 * and the parity tests need `npm run data`.
 *
 * Usage: npm run data:offline-fallback   (node scripts/dev-data.mjs [--snapshot-dir <dir>] [--out <dir>])
 *
 * Rules (also in DATA_CONTRACT.md):
 *   - fetched_utc is the HTTP Date header recorded in supgp_headers.txt (never "now").
 *   - An element set is excluded as stale when fetched_utc - EPOCH > 3 days.
 *   - Every kept element set must initialise and propagate with satellite.js SGP4 at
 *     fetched_utc; failures are excluded as sgp4_error.
 *   - sha256_raw is the hash of the raw bytes; it must match SHA256SUMS if that exists.
 *   - Output is deterministic: no generation time stamp, rows sorted by NORAD_CAT_ID.
 */
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { json2satrec, propagate } from 'satellite.js';

const WEB_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const DEFAULT_SNAPSHOT_DIR = path.resolve(WEB_ROOT, '..', 'data', 'pinned', '20261010T1358Z-celestrak');
const DEFAULT_OUT_DIR = path.resolve(WEB_ROOT, 'public', 'data');

const RAW_FILE = 'starlink_supgp.json';
const HEADERS_FILE = 'supgp_headers.txt';
const SOURCE = 'CelesTrak SupGP';
const SOURCE_URL = 'https://celestrak.org/NORAD/elements/supplemental/sup-gp.php?FILE=starlink&FORMAT=json';
const ATTRIBUTION =
  'Orbit data courtesy of CelesTrak (celestrak.org); SupGP elements derived from SpaceX ephemerides.';
const PIPELINE = 'dev-data.mjs (development)';
const MAX_EPOCH_AGE_DAYS = 3;
const DAY_MS = 86_400_000;

/** Column order of omm.min.json; must equal OMM_FIELDS in src/lib/data-types.ts. */
const FIELDS = [
  'OBJECT_NAME',
  'OBJECT_ID',
  'EPOCH',
  'MEAN_MOTION',
  'ECCENTRICITY',
  'INCLINATION',
  'RA_OF_ASC_NODE',
  'ARG_OF_PERICENTER',
  'MEAN_ANOMALY',
  'EPHEMERIS_TYPE',
  'CLASSIFICATION_TYPE',
  'NORAD_CAT_ID',
  'ELEMENT_SET_NO',
  'REV_AT_EPOCH',
  'BSTAR',
  'MEAN_MOTION_DOT',
  'MEAN_MOTION_DDOT',
  'RMS',
  'DATA_SOURCE',
];
const STRING_FIELDS = new Set(['OBJECT_NAME', 'OBJECT_ID', 'EPOCH', 'CLASSIFICATION_TYPE']);
const OPTIONAL_STRING_FIELDS = new Set(['RMS', 'DATA_SOURCE']);
const EPOCH_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;

function fail(message) {
  console.error(`dev-data: ERROR: ${message}`);
  process.exit(1);
}

function parseArgs(argv) {
  const options = { snapshotDir: DEFAULT_SNAPSHOT_DIR, outDir: DEFAULT_OUT_DIR };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = argv[i + 1];
    if (arg === '--snapshot-dir' && next) {
      options.snapshotDir = path.resolve(next);
      i += 1;
    } else if (arg === '--out' && next) {
      options.outDir = path.resolve(next);
      i += 1;
    } else {
      fail(`unknown or incomplete argument: ${arg}`);
    }
  }
  return options;
}

/** "Date: Sat, 10 Oct 2026 14:02:22 GMT" from a saved HTTP response header block. */
function readHttpDate(headersText) {
  const line = headersText.split(/\r?\n/).find((l) => /^date:/i.test(l));
  if (!line) fail(`${HEADERS_FILE} has no Date header`);
  const httpDate = line.slice(line.indexOf(':') + 1).trim();
  const ms = Date.parse(httpDate);
  if (Number.isNaN(ms)) fail(`cannot parse HTTP Date "${httpDate}"`);
  return { httpDate, fetchedMs: ms };
}

/** ISO 8601 UTC with "Z", whole seconds when the instant has no fraction. */
function isoSeconds(ms) {
  const iso = new Date(ms).toISOString();
  return iso.endsWith('.000Z') ? `${iso.slice(0, 19)}Z` : iso;
}

function validRecord(obj) {
  if (typeof obj !== 'object' || obj === null || Array.isArray(obj)) return false;
  for (const field of FIELDS) {
    const value = obj[field];
    if (OPTIONAL_STRING_FIELDS.has(field)) {
      if (value !== undefined && typeof value !== 'string') return false;
    } else if (STRING_FIELDS.has(field)) {
      if (typeof value !== 'string' || value === '') return false;
    } else if (typeof value !== 'number' || !Number.isFinite(value)) {
      return false;
    }
  }
  return (
    EPOCH_RE.test(obj.EPOCH) &&
    Number.isInteger(obj.NORAD_CAT_ID) &&
    obj.NORAD_CAT_ID > 0 &&
    obj.EPHEMERIS_TYPE === 0 && // SGP4 element sets only
    (obj.CLASSIFICATION_TYPE === 'U' || obj.CLASSIFICATION_TYPE === 'C')
  );
}

function sgp4Ok(obj, atDate) {
  try {
    const satrec = json2satrec(obj);
    if (!satrec || satrec.error !== 0) return false;
    const state = propagate(satrec, atDate);
    if (!state || typeof state.position !== 'object' || state.position === null) return false;
    const { x, y, z } = state.position;
    return [x, y, z].every(Number.isFinite);
  } catch {
    return false;
  }
}

async function main() {
  const { snapshotDir, outDir } = parseArgs(process.argv.slice(2));
  const dirName = path.basename(snapshotDir);
  const stamp = /^(\d{8}T\d{4}Z)/.exec(dirName);
  if (!stamp) fail(`snapshot directory name must start with YYYYMMDDTHHMMZ: ${dirName}`);
  const snapshotId = `${stamp[1]}-supgp`;

  const rawPath = path.join(snapshotDir, RAW_FILE);
  const raw = await readFile(rawPath).catch(() => fail(`cannot read ${rawPath}`));
  const sha256 = createHash('sha256').update(raw).digest('hex');

  const sumsPath = path.join(snapshotDir, 'SHA256SUMS');
  if (existsSync(sumsPath)) {
    const sums = await readFile(sumsPath, 'utf8');
    const line = sums.split(/\r?\n/).find((l) => l.trim().endsWith(RAW_FILE));
    if (!line) fail(`SHA256SUMS has no line for ${RAW_FILE}`);
    const expected = line.trim().split(/\s+/)[0].toLowerCase();
    if (expected !== sha256) fail(`sha256 mismatch for ${RAW_FILE}: SHA256SUMS ${expected}, actual ${sha256}`);
    console.log(`dev-data: sha256 of ${RAW_FILE} matches SHA256SUMS`);
  } else {
    console.log('dev-data: no SHA256SUMS next to the raw file; hash not cross-checked');
  }

  const headersText = await readFile(path.join(snapshotDir, HEADERS_FILE), 'utf8').catch(() =>
    fail(`cannot read ${HEADERS_FILE}; fetched_utc must come from the recorded HTTP Date`),
  );
  const { httpDate, fetchedMs } = readHttpDate(headersText);
  const fetchedDate = new Date(fetchedMs);

  let objects;
  try {
    objects = JSON.parse(raw.toString('utf8'));
  } catch (error) {
    fail(`${RAW_FILE} is not valid JSON: ${error.message}`);
  }
  if (!Array.isArray(objects)) fail(`${RAW_FILE} must contain a JSON array`);

  const excluded = { stale_epoch: 0, sgp4_error: 0, invalid: 0, duplicate: 0 };
  /** @type {Map<number, {obj: object, epochMs: number}>} */
  const byId = new Map();
  for (const obj of objects) {
    if (!validRecord(obj)) {
      excluded.invalid += 1;
      continue;
    }
    const epochMs = Date.parse(`${obj.EPOCH}Z`);
    if (Number.isNaN(epochMs)) {
      excluded.invalid += 1;
      continue;
    }
    if (fetchedMs - epochMs > MAX_EPOCH_AGE_DAYS * DAY_MS) {
      excluded.stale_epoch += 1;
      continue;
    }
    if (!sgp4Ok(obj, fetchedDate)) {
      excluded.sgp4_error += 1;
      continue;
    }
    const previous = byId.get(obj.NORAD_CAT_ID);
    if (previous) {
      excluded.duplicate += 1;
      if (epochMs > previous.epochMs) byId.set(obj.NORAD_CAT_ID, { obj, epochMs });
    } else {
      byId.set(obj.NORAD_CAT_ID, { obj, epochMs });
    }
  }

  const kept = [...byId.values()].sort((a, b) => a.obj.NORAD_CAT_ID - b.obj.NORAD_CAT_ID);
  if (kept.length === 0) fail('no element sets survived the checks');
  const total = kept.length + Object.values(excluded).reduce((s, n) => s + n, 0);
  if (total !== objects.length) fail(`internal count error: ${total} != ${objects.length}`);

  // Epoch statistics on the original strings (microsecond precision kept, "Z" appended).
  const byEpoch = [...kept].sort((a, b) => a.epochMs - b.epochMs || (a.obj.EPOCH < b.obj.EPOCH ? -1 : 1));
  const epochAt = (i) => `${byEpoch[i].obj.EPOCH}Z`;
  const epochMin = epochAt(0);
  const epochMedian = epochAt(Math.floor((byEpoch.length - 1) / 2)); // lower median
  const epochMax = epochAt(byEpoch.length - 1);

  const satellitePkg = JSON.parse(
    await readFile(path.join(WEB_ROOT, 'node_modules', 'satellite.js', 'package.json'), 'utf8'),
  );

  const manifest = {
    schema: 'chronoroute.web-snapshot/1',
    snapshot_id: snapshotId,
    source: SOURCE,
    source_url: SOURCE_URL,
    fetched_utc: isoSeconds(fetchedMs),
    http_date: httpDate,
    count: kept.length,
    count_raw: objects.length,
    epoch_min: epochMin,
    epoch_median: epochMedian,
    epoch_max: epochMax,
    max_epoch_age_days: MAX_EPOCH_AGE_DAYS,
    raw_file: RAW_FILE,
    sha256_raw: sha256,
    excluded,
    sgp4_check: { library: 'satellite.js', version: satellitePkg.version, at_utc: isoSeconds(fetchedMs) },
    attribution: ATTRIBUTION,
    pipeline: PIPELINE,
    files: { omm: 'omm.min.json' },
  };

  const omm = {
    fields: FIELDS,
    rows: kept.map(({ obj }) => FIELDS.map((field) => (obj[field] === undefined ? null : obj[field]))),
  };

  const relDir = `snapshots/${snapshotId}/`;
  const snapDir = path.join(outDir, 'snapshots', snapshotId);
  await mkdir(snapDir, { recursive: true });
  const ommText = `${JSON.stringify(omm)}\n`;
  await writeFile(path.join(snapDir, 'omm.min.json'), ommText);
  await writeFile(path.join(snapDir, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
  await writeFile(
    path.join(outDir, 'latest.json'),
    `${JSON.stringify({ snapshot_id: snapshotId, path: relDir }, null, 2)}\n`,
  );

  console.log(`dev-data: snapshot ${snapshotId} (development pipeline)`);
  console.log(`dev-data: raw objects ${objects.length}, kept ${kept.length}, excluded ${JSON.stringify(excluded)}`);
  console.log(`dev-data: epochs ${epochMin} .. ${epochMax} (median ${epochMedian})`);
  console.log(`dev-data: fetched ${manifest.fetched_utc} (HTTP Date "${httpDate}")`);
  console.log(`dev-data: wrote ${path.relative(WEB_ROOT, snapDir)}/omm.min.json (${ommText.length} bytes), manifest.json, and latest.json`);
}

await main();

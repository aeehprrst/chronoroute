/**
 * Runtime validation and loading for the data contract (see DATA_CONTRACT.md).
 * Safe in the browser and in Node: no Node imports here. The build-time file reader
 * lives in data-build.ts.
 */
import {
  MANIFEST_DEFAULTS,
  MANIFEST_SCHEMA,
  OMM_REQUIRED_FIELDS,
  type LatestPointer,
  type OmmRecord,
  type SnapshotManifest,
} from './data-types';
import { dataHref } from './paths';

export class DataContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'DataContractError';
  }
}

type Json = Record<string, unknown>;

function isObject(value: unknown): value is Json {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function str(obj: Json, key: string, where: string): string {
  const value = obj[key];
  if (typeof value !== 'string' || value === '') {
    throw new DataContractError(`${where}: "${key}" must be a non-empty string`);
  }
  return value;
}

function count(obj: Json, key: string, where: string): number {
  const value = obj[key];
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 0) {
    throw new DataContractError(`${where}: "${key}" must be a non-negative integer`);
  }
  return value;
}

function isoUtc(obj: Json, key: string, where: string): string {
  const value = str(obj, key, where);
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value) || Number.isNaN(Date.parse(value))) {
    throw new DataContractError(`${where}: "${key}" must be an ISO 8601 UTC time ending in Z`);
  }
  return value;
}

/** Validate public/data/latest.json. */
export function parseLatestPointer(value: unknown): LatestPointer {
  const where = 'latest.json';
  if (!isObject(value)) throw new DataContractError(`${where}: not a JSON object`);
  const snapshot_id = str(value, 'snapshot_id', where);
  const path = str(value, 'path', where);
  if (!/^snapshots\/[A-Za-z0-9._-]+\/$/.test(path)) {
    throw new DataContractError(`${where}: "path" must look like "snapshots/<id>/"`);
  }
  return { snapshot_id, path };
}

/** A non-negative integer if the key is present, otherwise the default. */
function optionalCount(obj: Json, key: string, where: string, fallback: number): number {
  return obj[key] === undefined ? fallback : count(obj, key, where);
}

/**
 * Validate a snapshot manifest.json. Throws DataContractError with the first problem found.
 *
 * Required (the fields of the project brief): snapshot_id, source, source_url, fetched_utc,
 * http_date, count, epoch_min, epoch_median, epoch_max, sha256_raw, excluded.stale_epoch,
 * excluded.sgp4_error, attribution, pipeline. The other fields are optional; when present
 * they are checked, and when absent they get the defaults in MANIFEST_DEFAULTS
 * (see DATA_CONTRACT.md).
 */
export function parseManifest(value: unknown): SnapshotManifest {
  const where = 'manifest.json';
  if (!isObject(value)) throw new DataContractError(`${where}: not a JSON object`);
  if (value['schema'] !== undefined && value['schema'] !== MANIFEST_SCHEMA) {
    throw new DataContractError(`${where}: "schema", if present, must be "${MANIFEST_SCHEMA}"`);
  }
  const excludedRaw = value['excluded'];
  if (!isObject(excludedRaw)) throw new DataContractError(`${where}: "excluded" must be an object`);
  const excluded = {
    stale_epoch: count(excludedRaw, 'stale_epoch', `${where} excluded`),
    sgp4_error: count(excludedRaw, 'sgp4_error', `${where} excluded`),
    invalid: optionalCount(excludedRaw, 'invalid', `${where} excluded`, 0),
    duplicate: optionalCount(excludedRaw, 'duplicate', `${where} excluded`, 0),
  };
  const checkRaw = value['sgp4_check'];
  if (checkRaw !== undefined && !isObject(checkRaw)) {
    throw new DataContractError(`${where}: "sgp4_check", if present, must be an object`);
  }
  const filesRaw = value['files'];
  if (filesRaw !== undefined && !isObject(filesRaw)) {
    throw new DataContractError(`${where}: "files", if present, must be an object`);
  }
  const sha = str(value, 'sha256_raw', where);
  if (!/^[0-9a-f]{64}$/.test(sha)) throw new DataContractError(`${where}: "sha256_raw" must be 64 lowercase hex digits`);
  const ageRaw = value['max_epoch_age_days'];
  if (ageRaw !== undefined && (typeof ageRaw !== 'number' || !(ageRaw > 0))) {
    throw new DataContractError(`${where}: "max_epoch_age_days", if present, must be a positive number`);
  }
  const countKept = count(value, 'count', where);
  const excludedTotal =
    excluded.stale_epoch + excluded.sgp4_error + excluded.invalid + excluded.duplicate;

  const manifest: SnapshotManifest = {
    schema: MANIFEST_SCHEMA,
    snapshot_id: str(value, 'snapshot_id', where),
    source: str(value, 'source', where),
    source_url: str(value, 'source_url', where),
    fetched_utc: isoUtc(value, 'fetched_utc', where),
    http_date: str(value, 'http_date', where),
    count: countKept,
    count_raw: optionalCount(value, 'count_raw', where, countKept + excludedTotal),
    epoch_min: isoUtc(value, 'epoch_min', where),
    epoch_median: isoUtc(value, 'epoch_median', where),
    epoch_max: isoUtc(value, 'epoch_max', where),
    max_epoch_age_days: typeof ageRaw === 'number' ? ageRaw : MANIFEST_DEFAULTS.max_epoch_age_days,
    raw_file: value['raw_file'] === undefined ? null : str(value, 'raw_file', where),
    sha256_raw: sha,
    excluded,
    sgp4_check: isObject(checkRaw)
      ? {
          library: str(checkRaw, 'library', `${where} sgp4_check`),
          version: str(checkRaw, 'version', `${where} sgp4_check`),
          at_utc: isoUtc(checkRaw, 'at_utc', `${where} sgp4_check`),
        }
      : null,
    attribution: str(value, 'attribution', where),
    pipeline: str(value, 'pipeline', where),
    files: { omm: isObject(filesRaw) ? str(filesRaw, 'omm', `${where} files`) : MANIFEST_DEFAULTS.omm_file },
  };

  if (manifest.count + excludedTotal !== manifest.count_raw) {
    throw new DataContractError(
      `${where}: count (${manifest.count}) + excluded (${excludedTotal}) must equal count_raw (${manifest.count_raw})`,
    );
  }
  if (!(manifest.epoch_min <= manifest.epoch_median && manifest.epoch_median <= manifest.epoch_max)) {
    throw new DataContractError(`${where}: epochs must satisfy epoch_min <= epoch_median <= epoch_max`);
  }
  return manifest;
}

/** True when the manifest was written by the development converter rather than the Python pipeline. */
export function isDevelopmentSnapshot(manifest: SnapshotManifest): boolean {
  return manifest.pipeline.startsWith('dev-data.mjs');
}

/** Validate omm.min.json and turn its rows back into OMM objects for satellite.js json2satrec(). */
export function ommRowsToRecords(value: unknown): OmmRecord[] {
  const where = 'omm.min.json';
  if (!isObject(value)) throw new DataContractError(`${where}: not a JSON object`);
  const fields = value['fields'];
  const rows = value['rows'];
  if (!Array.isArray(fields) || !fields.every((f) => typeof f === 'string')) {
    throw new DataContractError(`${where}: "fields" must be an array of strings`);
  }
  if (!Array.isArray(rows)) throw new DataContractError(`${where}: "rows" must be an array`);
  for (const required of OMM_REQUIRED_FIELDS) {
    if (!fields.includes(required)) throw new DataContractError(`${where}: missing field ${required}`);
  }
  const width = fields.length;
  return rows.map((row: unknown, index) => {
    if (!Array.isArray(row) || row.length !== width) {
      throw new DataContractError(`${where}: row ${index} must have ${width} values`);
    }
    const record: Record<string, unknown> = {};
    for (let i = 0; i < width; i += 1) {
      const value: unknown = row[i];
      // null marks an optional field that the source object did not have: leave it out.
      if (value !== null) record[fields[i] as string] = value;
    }
    return record as unknown as OmmRecord;
  });
}

export async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url, { credentials: 'omit' });
  if (!response.ok) throw new DataContractError(`GET ${url} failed: HTTP ${response.status}`);
  return response.json();
}

export interface LoadedSnapshot {
  manifest: SnapshotManifest;
  records: OmmRecord[];
  /** Directory of the snapshot relative to the data root ("snapshots/<id>/"), from latest.json. */
  path: string;
}

/**
 * Browser loader: latest.json -> manifest.json -> omm.min.json, all from this site's own
 * /data directory (no third-party requests). Throws DataContractError on any problem.
 */
export async function loadLatestSnapshot(): Promise<LoadedSnapshot> {
  const pointer = parseLatestPointer(await fetchJson(dataHref('latest.json')));
  const manifest = parseManifest(await fetchJson(dataHref(`${pointer.path}manifest.json`)));
  if (manifest.snapshot_id !== pointer.snapshot_id) {
    throw new DataContractError('latest.json and manifest.json name different snapshots');
  }
  const records = ommRowsToRecords(await fetchJson(dataHref(`${pointer.path}${manifest.files.omm}`)));
  if (records.length !== manifest.count) {
    throw new DataContractError(
      `omm.min.json has ${records.length} rows but the manifest says ${manifest.count}`,
    );
  }
  return { manifest, records, path: pointer.path };
}

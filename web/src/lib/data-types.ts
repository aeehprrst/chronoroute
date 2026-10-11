/**
 * Types for the website's data contract. The prose version, with every rule, is
 * web/DATA_CONTRACT.md. If the two ever disagree, fix both in the same change.
 *
 * Files (all under public/data/, served at <base>/data/):
 *   latest.json                         -> LatestPointer
 *   snapshots/<id>/manifest.json        -> SnapshotManifest
 *   snapshots/<id>/omm.min.json         -> OmmMin
 */

/** Provenance label carried by every number and visual on the site. */
export type DataLabel = 'real' | 'derived' | 'modelled' | 'unknown';

/** public/data/latest.json */
export interface LatestPointer {
  /** Snapshot identifier, e.g. "20261010T1358Z-supgp". */
  snapshot_id: string;
  /** Directory of the snapshot relative to public/data/, with a trailing slash, e.g. "snapshots/20261010T1358Z-supgp/". */
  path: string;
}

/** Counts of raw objects that were left out of omm.min.json, by reason. */
export interface SnapshotExclusions {
  /** EPOCH more than max_epoch_age_days before fetched_utc. */
  stale_epoch: number;
  /** satellite.js could not initialise or propagate the element set at fetched_utc. */
  sgp4_error: number;
  /** A required OMM field was missing or had the wrong type. */
  invalid: number;
  /** A second element set for a NORAD_CAT_ID that was already kept (the newest EPOCH wins). */
  duplicate: number;
}

/** The SGP4 sanity check the pipeline ran on every kept element set. */
export interface Sgp4Check {
  library: string;
  version: string;
  /** Instant (ISO 8601 UTC) at which every element set was propagated. */
  at_utc: string;
}

/** Format identifier of manifest.json. */
export const MANIFEST_SCHEMA = 'chronoroute.web-snapshot/1';

/**
 * Defaults for the optional manifest fields (see DATA_CONTRACT.md). The other optional fields
 * default as follows: schema -> MANIFEST_SCHEMA; excluded.invalid and excluded.duplicate -> 0;
 * count_raw -> count + all exclusions; raw_file -> null; sgp4_check -> null.
 */
export const MANIFEST_DEFAULTS = {
  /** The stale-epoch rule of the project brief: more than 3 days before the download. */
  max_epoch_age_days: 3,
  omm_file: 'omm.min.json',
} as const;

/**
 * public/data/snapshots/<id>/manifest.json, as returned by parseManifest(): optional fields
 * already filled in with their defaults.
 */
export interface SnapshotManifest {
  /** Format identifier of this file (optional in the file; defaults to MANIFEST_SCHEMA). */
  schema: typeof MANIFEST_SCHEMA;
  snapshot_id: string;
  /** Human name of the source, e.g. "CelesTrak SupGP". */
  source: string;
  source_url: string;
  /** When the raw file was downloaded (ISO 8601 UTC, "Z"), from the HTTP Date header. */
  fetched_utc: string;
  /** The raw HTTP Date header of the download. */
  http_date: string;
  /** Number of element sets in omm.min.json. */
  count: number;
  /** Number of objects in the raw file. count + sum(excluded) === count_raw. */
  count_raw: number;
  /** Oldest, median (lower median for an even count) and newest EPOCH of the kept element sets (ISO 8601 UTC, "Z"). */
  epoch_min: string;
  epoch_median: string;
  epoch_max: string;
  /** Exclusion threshold used for stale_epoch, in days. */
  max_epoch_age_days: number;
  /** File name of the raw download inside the pinned snapshot (null if the manifest does not say). */
  raw_file: string | null;
  /** sha256 (hex) of the raw downloaded bytes. */
  sha256_raw: string;
  excluded: SnapshotExclusions;
  /** The SGP4 check the producer ran (null if the manifest does not record one). */
  sgp4_check: Sgp4Check | null;
  attribution: string;
  /** "dev-data.mjs (development)" or "<python pipeline commit>". */
  pipeline: string;
  /** File names inside the snapshot directory. */
  files: { omm: string };
}

/** Column order of omm.min.json. Matches the key order of CelesTrak's OMM JSON for SupGP. */
export const OMM_FIELDS = [
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
] as const;

export type OmmField = (typeof OMM_FIELDS)[number];

/** Fields every row must have. RMS and DATA_SOURCE exist only in SupGP and are optional. */
export const OMM_REQUIRED_FIELDS: readonly OmmField[] = OMM_FIELDS.filter(
  (field) => field !== 'RMS' && field !== 'DATA_SOURCE',
);

/**
 * One OMM element set as CelesTrak publishes it in JSON. EPOCH is UTC without a "Z".
 * Pass it straight to satellite.js json2satrec().
 */
export interface OmmRecord {
  OBJECT_NAME: string;
  OBJECT_ID: string;
  EPOCH: string;
  MEAN_MOTION: number;
  ECCENTRICITY: number;
  INCLINATION: number;
  RA_OF_ASC_NODE: number;
  ARG_OF_PERICENTER: number;
  MEAN_ANOMALY: number;
  /** Always 0 (SGP4); other ephemeris types are excluded as invalid. */
  EPHEMERIS_TYPE: 0;
  /** "U" (GP) or "C" (SupGP); anything else is excluded as invalid. */
  CLASSIFICATION_TYPE: 'U' | 'C';
  /** Can have six digits (e.g. 100001). Never assume five. */
  NORAD_CAT_ID: number;
  ELEMENT_SET_NO: number;
  REV_AT_EPOCH: number;
  BSTAR: number;
  MEAN_MOTION_DOT: number;
  MEAN_MOTION_DDOT: number;
  /** SupGP only: fit residual reported by CelesTrak, as a string. */
  RMS?: string;
  /** SupGP only: e.g. "SpaceX-E". */
  DATA_SOURCE?: string;
  /** Keeps the type assignable to satellite.js OMMJsonObject (which allows extra keys). */
  [key: string]: unknown;
}

/**
 * public/data/snapshots/<id>/omm.min.json: a column-oriented OMM list, sorted by NORAD_CAT_ID.
 * Values are copied verbatim from the source; null only where an optional field (RMS,
 * DATA_SOURCE) is absent in the source object.
 */
export interface OmmMin {
  fields: OmmField[];
  rows: Array<Array<string | number | null>>;
}

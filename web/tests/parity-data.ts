/**
 * Reader for the Python parity files written by tools/web_parity.py (schema
 * chronoroute.web-parity/1). Node only; used by the parity tests.
 *
 * Two files, both written by `npm run data` (scripts/build-data.sh):
 *   web/.parity/parity.json         the reference run: the experiments' pinned snapshot
 *                                   20261010T1358Z-celestrak (override: PARITY_FILE);
 *   web/.parity/served/parity.json  the served run: the snapshot published in public/data
 *                                   (override: SERVED_PARITY_FILE).
 * A missing file is an error, never a skipped test: CI must not deploy without the check.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';

export const PARITY_FILE = process.env['PARITY_FILE'] ?? path.resolve(import.meta.dirname, '..', '.parity', 'parity.json');
export const SERVED_PARITY_FILE =
  process.env['SERVED_PARITY_FILE'] ?? path.resolve(import.meta.dirname, '..', '.parity', 'served', 'parity.json');

export interface ParityPair {
  src: string;
  dst: string;
  src_g: number;
  dst_g: number;
  great_circle_km: number;
  gsl: Record<string, { visible: number[]; selected: number[] }>;
  reachable: boolean;
  cost_ns: number | null;
  path_nodes?: number[];
  path_norads?: Array<number | null>;
  sids_fwd?: number[];
  hop_delays_ns?: number[];
  prop_ns?: number[];
  budgets_ceil_ns?: number[];
  template_hex?: string;
  header_hex?: string;
  packet_hex?: string;
  pcap_hex?: string;
}

export interface ParityDoc {
  schema: 'chronoroute.web-parity/1';
  snapshot_id: string;
  source: string;
  /** sha256 of the raw download the Python side read (null for a website-layout folder). */
  sha256_raw: string | null;
  fetched_utc: string;
  t_utc: string;
  t_unix_ns: string;
  t_gps_ns: string;
  shell_id: string;
  slack: string;
  unit_code: 0 | 1 | 2 | 3;
  next_header: number;
  processing_ns: number;
  grid_params: Record<string, unknown>;
  gsl_params: { min_elevation_deg: number; max_links_per_gs: number; policy: string };
  labels: Record<string, string>;
  label_notes: Record<string, string>;
  frame: {
    norad: number[];
    ecef_km: Array<[number, number, number] | null>;
    lat_deg: Array<number | null>;
    ecef_ms_epoch_km: Array<[number, number, number] | null>;
    isl_down: Array<[number, number]>;
    city_ecef_km: Record<string, [number, number, number]>;
  };
  omm_min: string;
  shells: unknown;
  isl_grid4: unknown;
  cities_csv: string;
  sid_registry: unknown;
  pairs: ParityPair[];
}

export function readParity(file: string = PARITY_FILE): ParityDoc {
  let text: string;
  try {
    text = readFileSync(file, 'utf8');
  } catch (error) {
    throw new Error(
      `Parity file ${file} is missing. Run \`npm run data\` (or \`venv/bin/python -B tools/web_parity.py\` from the repository root). (${String(error)})`,
    );
  }
  const doc = JSON.parse(text) as ParityDoc;
  if (doc.schema !== 'chronoroute.web-parity/1') throw new Error(`${file}: unexpected schema ${String(doc.schema)}`);
  return doc;
}

/** Frame positions as a Float64Array (NaN for a satellite whose SGP4 failed). */
export function framePositions(rows: ReadonlyArray<readonly [number, number, number] | null>): Float64Array {
  const out = new Float64Array(rows.length * 3).fill(Number.NaN);
  rows.forEach((row, i) => {
    if (row) out.set(row, i * 3);
  });
  return out;
}

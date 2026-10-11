/** Build-only evidence reader: the only inputs are each release's summary.csv and manifest.json. */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { LABEL_TABLE } from '../label-keys';
import { PREREG_HASH, PREREG_SHA, type ExperimentDefinition } from './catalog';
import { chartModel, parseCsv, type Row, type ChartEvidence } from './data';
export const RESULTS_ROOT = path.resolve(process.cwd(), '..', 'results');
export interface ResultManifest {
  schema: string;
  tool: string;
  tool_version: string;
  git_sha: string;
  dirty: boolean;
  run_id: string;
  command: string;
  config_sha256: string;
  config: Record<string, unknown>;
  extra: Record<string, unknown>;
  seeds: number[];
  snapshot: { id: string; sha256: string } | null;
  labels: Record<string, string>;
  started_utc: string;
  ended_utc: string;
  wall_seconds: number;
  outputs: { path: string; sha256: string; size_bytes: number }[];
}
export interface ExperimentData {
  definition: ExperimentDefinition;
  rows: Row[];
  columns: string[];
  csvText: string;
  manifestText: string;
  manifest: ResultManifest;
  summarySha: string;
  preregSha: string;
  evidence: ChartEvidence;
}

export async function loadExperiment(
  definition: ExperimentDefinition,
  root = RESULTS_ROOT,
): Promise<ExperimentData> {
  if (!/^E\d+$/.test(definition.id) || !/^[-\w]+$/.test(definition.run))
    throw new Error('Invalid result release path');
  const folder = path.join(root, definition.id, definition.run);
  const [csv, manifestBytes] = await Promise.all([
    readFile(path.join(folder, 'summary.csv')),
    readFile(path.join(folder, 'manifest.json')),
  ]);
  const manifestText = manifestBytes.toString('utf8');
  const manifest = JSON.parse(manifestText) as ResultManifest;
  if (
    !manifest ||
    manifest.schema !== 'chronoroute.manifest/1' ||
    manifest.dirty !== false ||
    !Array.isArray(manifest.outputs) ||
    !Array.isArray(manifest.seeds) ||
    !manifest.config ||
    !manifest.extra ||
    !manifest.labels ||
    !/^[a-f0-9]{40}$/.test(manifest.git_sha) ||
    !/^[a-f0-9]{64}$/.test(manifest.config_sha256) ||
    typeof manifest.command !== 'string' ||
    typeof manifest.tool !== 'string'
  )
    throw new Error(`${folder}: invalid or dirty manifest`);
  const campaign = (manifest.config['campaign'] ?? manifest.config) as Record<
    string,
    unknown
  >;
  if (
    campaign['prereg_git_sha'] !== PREREG_SHA ||
    campaign['prereg_sha256'] !== PREREG_HASH
  )
    throw new Error(`${folder}: invalid preregistration`);
  for (const [key, value] of Object.entries(manifest.labels)) {
    if (
      !(key in LABEL_TABLE) ||
      (value !== LABEL_TABLE[key as keyof typeof LABEL_TABLE] &&
        !(
          ['orbital_elements', 'satellite_positions_sgp4'].includes(key) &&
          value === 'MODELLED'
        ))
    )
      throw new Error(`${folder}: unknown honesty label`);
  }
  const entries = manifest.outputs.filter((r) => r.path === 'summary.csv');
  if (entries.length !== 1)
    throw new Error(`${folder}: summary.csv has no unique manifest output`);
  const summarySha = createHash('sha256').update(csv).digest('hex');
  if (
    entries[0]!.sha256 !== summarySha ||
    entries[0]!.size_bytes !== csv.byteLength
  )
    throw new Error(`${folder}: summary hash or size mismatch`);
  const csvText = csv.toString('utf8');
  if (!Buffer.from(csvText).equals(csv))
    throw new Error(`${folder}: summary is not UTF-8`);
  const { columns, rows } = parseCsv(csvText);
  for (const column of definition.tableColumns)
    if (!columns.includes(column))
      throw new Error(`${folder}: missing summary column ${column}`);
  for (const metric of definition.metrics) {
    for (const column of [metric.key, metric.lo, metric.hi])
      if (column && !columns.includes(column))
        throw new Error(`${folder}: missing chart column ${column}`);
    chartModel(rows, metric);
  }
  return {
    definition,
    rows,
    columns,
    csvText,
    manifestText,
    manifest,
    summarySha,
    preregSha: PREREG_SHA,
    evidence: {
      runId: manifest.run_id,
      commit: manifest.git_sha,
      summarySha,
      manifestSha: createHash('sha256').update(manifestBytes).digest('hex'),
      dirty: false,
    },
  };
}

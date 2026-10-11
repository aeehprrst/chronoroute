/**
 * Build-only evidence reader: each release's summary.csv and manifest.json, plus (for E1, E4
 * and E5) the registered paired_contrasts.csv used for the verdict. Every file read here must
 * be a unique manifest output with a matching SHA-256 and size.
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { LABEL_TABLE } from '../label-keys';
import { PREREG_HASH, PREREG_SHA, type ExperimentDefinition } from './catalog';
import { chartModel, parseCsv, type Row, type ChartEvidence } from './data';
export const RESULTS_ROOT = path.resolve(process.cwd(), '..', 'results');
export interface ManifestOutput {
  path: string;
  sha256: string;
  size_bytes: number;
}
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
  outputs: ManifestOutput[];
  versions?: Record<string, unknown>;
  host?: Record<string, unknown>;
}
/** The verified paired-contrast table (build time only; never serialised into a page). */
export interface ContrastData {
  file: string;
  rows: Row[];
  sha256: string;
  text: string;
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
  contrasts: ContrastData | null;
}

/** Refuse a file that is not a unique manifest output with the recorded hash and size. */
function verifyOutput(
  manifest: ResultManifest,
  folder: string,
  name: string,
  bytes: Buffer,
): { sha256: string; text: string } {
  const entries = manifest.outputs.filter((r) => r.path === name);
  if (entries.length !== 1)
    throw new Error(`${folder}: ${name} has no unique manifest output`);
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  if (entries[0]!.sha256 !== sha256 || entries[0]!.size_bytes !== bytes.byteLength)
    throw new Error(`${folder}: ${name} hash or size mismatch`);
  const text = bytes.toString('utf8');
  if (!Buffer.from(text).equals(bytes))
    throw new Error(`${folder}: ${name} is not UTF-8`);
  return { sha256, text };
}

export async function loadExperiment(
  definition: ExperimentDefinition,
  root = RESULTS_ROOT,
): Promise<ExperimentData> {
  if (
    !/^E\d+$/.test(definition.id) ||
    !/^[-\w]+$/.test(definition.run) ||
    (definition.contrasts !== undefined && !/^[-\w]+\.csv$/.test(definition.contrasts))
  )
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
  const { sha256: summarySha, text: csvText } = verifyOutput(
    manifest,
    folder,
    'summary.csv',
    csv,
  );
  const { columns, rows } = parseCsv(csvText);
  for (const column of definition.tableColumns)
    if (!columns.includes(column))
      throw new Error(`${folder}: missing summary column ${column}`);
  for (const metric of definition.metrics) {
    for (const column of [metric.key, metric.lo, metric.hi, ...(metric.companions ?? [])])
      if (column && !columns.includes(column))
        throw new Error(`${folder}: missing chart column ${column}`);
    chartModel(rows, metric);
  }
  let contrasts: ContrastData | null = null;
  if (definition.contrasts) {
    const bytes = await readFile(path.join(folder, definition.contrasts));
    const { sha256, text } = verifyOutput(manifest, folder, definition.contrasts, bytes);
    const parsed = parseCsv(text);
    for (const column of ['const', 'condition', 'comparator', 'endpoint', 'mean_diff', 'lo', 'hi', 'adjusted_p', 'material_loss'])
      if (!parsed.columns.includes(column))
        throw new Error(`${folder}: missing contrast column ${column}`);
    contrasts = { file: definition.contrasts, rows: parsed.rows, sha256, text };
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
    contrasts,
  };
}

/** A short, page-sized description of a manifest; the full file is offered as a download. */
export function manifestSummary(data: ExperimentData) {
  const m = data.manifest;
  const inputs = Array.isArray(m.extra['inputs']) ? m.extra['inputs'].length : 0;
  const pick = (name: string) => m.outputs.find((o) => o.path === name);
  return {
    schema: m.schema,
    bytes: Buffer.byteLength(data.manifestText),
    sha256: data.evidence.manifestSha,
    outputs: m.outputs.length,
    outputBytes: m.outputs.reduce((s, o) => s + o.size_bytes, 0),
    files: [pick('summary.csv'), data.contrasts ? pick(data.contrasts.file) : undefined].filter(
      (o): o is ManifestOutput => o !== undefined,
    ),
    inputs,
    versions: Object.entries(m.versions ?? {}).map(([k, v]) => `${k} ${String(v)}`),
    host: Object.entries(m.host ?? {}).map(([k, v]) => `${k}: ${String(v)}`),
  };
}

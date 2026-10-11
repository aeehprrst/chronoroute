/**
 * Build-only reader for the Network Simulation page: one real ns-3 probe, hop by hop, from
 * results/network-walk/<run>/walk.json (written by tools/network_walk.py). The file must be a
 * unique output of a clean manifest with the recorded SHA-256 and size, as on the experiment
 * pages; otherwise the build fails.
 */
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';

export const WALK_RUN = '20261011T223851Z';
export const WALK_ROOT = path.resolve(process.cwd(), '..', 'results', 'network-walk');

export interface WalkHop {
  node_id: number;
  t_ns: number;
  sl: number;
  flags: number;
  now_u: number;
  deadline_u: number | null;
  elapsed_ms: number;
  deadline_ms: number | null;
  margin_ms: number | null;
  hex: string | null;
}
export interface WalkNode {
  hop: number;
  node_id: number;
  kind: 'sat' | 'gs';
  name: string;
  sid: number;
  norad: number | null;
  lat: number;
  lon: number;
}
export interface WalkRun {
  pkt: number;
  outcome: string;
  late_node: number | null;
  hops: WalkHop[];
}
export interface Walk {
  schema: string;
  run: string;
  t0_utc: string;
  unit_ns: number;
  epoch_base: number;
  flow: { id: number; src: string; dst: string };
  send_t_ns: number;
  fault: {
    kind: string;
    names: [string, string];
    rate_bps: number;
    nominal_rate_bps: number;
    start_ns: number;
    stop_ns: number;
    link_state: string;
    label: string;
  };
  path: WalkNode[];
  fault_run: WalkRun;
  nofault_run: WalkRun;
  detection: {
    probes_crossing_slowed_link: number;
    flagged_late: number;
    detection_rate: number;
    baseline_same_probes_crossed_no_fault: number;
    baseline_flagged: number;
    false_alarms_no_fault_run_all_probes: number;
    first_detection_after_fault_start_ms: number;
  };
  labels: Record<string, string>;
}
export interface WalkEvidence {
  walk: Walk;
  walkSha: string;
  manifestPath: string;
  gitSha: string;
  tool: string;
  command: string;
}

/** Read walk.json only if the manifest lists it once, clean, with matching hash and size. */
export async function loadWalk(root = WALK_ROOT, run = WALK_RUN): Promise<WalkEvidence> {
  const dir = path.join(root, run);
  const manifest = JSON.parse(await readFile(path.join(dir, 'manifest.json'), 'utf8'));
  if (manifest.dirty !== false) throw new Error(`network walk ${run}: manifest is not from a clean tree`);
  if (!/^[0-9a-f]{40}$/.test(String(manifest.git_sha))) throw new Error(`network walk ${run}: bad git sha`);
  const entries = (manifest.outputs ?? []).filter((o: { path: string }) => o.path === 'walk.json');
  if (entries.length !== 1) throw new Error(`network walk ${run}: walk.json is not a unique manifest output`);
  const bytes = await readFile(path.join(dir, 'walk.json'));
  const sha = createHash('sha256').update(bytes).digest('hex');
  if (sha !== entries[0].sha256 || bytes.length !== entries[0].size_bytes) {
    throw new Error(`network walk ${run}: walk.json does not match its manifest`);
  }
  const walk = JSON.parse(bytes.toString('utf8')) as Walk;
  if (walk.schema !== 'chronoroute.network-walk/1') throw new Error(`network walk ${run}: unknown schema ${walk.schema}`);
  if (walk.path.length !== walk.fault_run.hops.length || walk.path.length !== walk.nofault_run.hops.length) {
    throw new Error(`network walk ${run}: path and hop lists differ in length`);
  }
  return {
    walk,
    walkSha: sha,
    manifestPath: `results/network-walk/${run}/manifest.json`,
    gitSha: manifest.git_sha,
    tool: manifest.tool,
    command: Array.isArray(manifest.command) ? manifest.command.join(' ') : String(manifest.command),
  };
}

/** Flags byte -> named bits (spec/tcrh-v1.md section 3). */
export function decodeFlags(flags: number) {
  return { dev: (flags & 0x01) !== 0, greedy: (flags & 0x02) !== 0, sat: (flags & 0x04) !== 0, unit: (flags >> 4) & 3 };
}

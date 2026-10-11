/**
 * The CI parity summary, public/data/parity.json (schema chronoroute.web-parity-summary/2).
 *
 * tests/route-parity.test.ts writes it (PARITY_SUMMARY_OUT) only after the deploy gate passed;
 * the route page shows it as its parity badge. Writer and reader share this one type, and the
 * badge's wording lives here, next to the numbers it describes, so that the page can never
 * claim more than the gate checked: "identical paths" is said only when every path WAS
 * identical; equal-cost ties (which the gate accepts) are named as ties.
 *
 * Two runs per build:
 *   reference  the experiments' pinned snapshot (data/pinned/20261010T1358Z-celestrak): a
 *              fixed yardstick that does not change when new orbit data arrives;
 *   served     the snapshot this build publishes (the data the route page uses).
 */

export const PARITY_SUMMARY_SCHEMA = 'chronoroute.web-parity-summary/2';

/** What the gate blocks on, in one sentence (copied into the summary file). */
export const PARITY_RULE =
  "deploy blocked unless every pair has a path cost within 1 ns of Python's and a byte-identical T-CRH template, " +
  "T-CRH, packet and pcap (for an equal-cost tie: built from Python's path); both sides use Python's positions of " +
  'the satellites and the cities';

export type ParityRole = 'reference' | 'served';

export interface ParityRunSummary {
  role: ParityRole;
  /** The pinned snapshot folder the Python side read (e.g. 20261010T1358Z-celestrak). */
  snapshot_id: string;
  /** The website snapshot id the page shows (served run only; null for the reference run). */
  web_snapshot_id: string | null;
  t_utc: string;
  shell_id: string;
  pairs: number;
  /** Pairs for which Python found a path. */
  reachable: number;
  /** Pairs where both found exactly the same path. */
  identical_paths: number;
  /** Pairs with equal cost (within 1 ns) but a different path. */
  ties: number;
  mismatches: number;
  pairs_with_diagnostics: number;
}

export interface ParitySummary {
  schema: typeof PARITY_SUMMARY_SCHEMA;
  rule: string;
  runs: ParityRunSummary[];
  /** The commit CI checked (GitHub's GITHUB_SHA); absent in local runs. */
  commit?: string;
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const isText = (v: unknown): v is string => typeof v === 'string' && v.length > 0;

function parseRun(value: unknown): ParityRunSummary | null {
  if (!value || typeof value !== 'object') return null;
  const r = value as Record<string, unknown>;
  const counts = ['pairs', 'reachable', 'identical_paths', 'ties', 'mismatches', 'pairs_with_diagnostics'] as const;
  if (r['role'] !== 'reference' && r['role'] !== 'served') return null;
  if (!isText(r['snapshot_id']) || !isText(r['t_utc']) || !isText(r['shell_id'])) return null;
  if (!(r['web_snapshot_id'] === null || isText(r['web_snapshot_id']))) return null;
  if (!counts.every((k) => isCount(r[k]))) return null;
  const run = value as ParityRunSummary;
  // Internal consistency: a summary that does not add up is not shown at all.
  if (run.reachable > run.pairs || run.identical_paths + run.ties + run.mismatches < run.reachable) return null;
  if (run.identical_paths + run.ties > run.reachable) return null;
  return run;
}

/** The summary, or null when the file is missing, of another schema or inconsistent. */
export function parseParitySummary(value: unknown): ParitySummary | null {
  if (!value || typeof value !== 'object') return null;
  const s = value as Record<string, unknown>;
  if (s['schema'] !== PARITY_SUMMARY_SCHEMA || !isText(s['rule']) || !Array.isArray(s['runs']) || s['runs'].length === 0) return null;
  const runs = s['runs'].map(parseRun);
  if (runs.some((r) => r === null)) return null;
  if (s['commit'] !== undefined && !isText(s['commit'])) return null;
  const out: ParitySummary = { schema: PARITY_SUMMARY_SCHEMA, rule: s['rule'], runs: runs as ParityRunSummary[] };
  if (isText(s['commit'])) out.commit = s['commit'];
  return out;
}

/** True when every Python path was reproduced exactly (no ties, no mismatches) in every run. */
export function allPathsIdentical(summary: ParitySummary): boolean {
  return summary.runs.every((r) => r.mismatches === 0 && r.ties === 0 && r.identical_paths === r.reachable);
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** One sentence per run, for the badge. Says "identical" only for what was identical. */
export function describeRun(run: ParityRunSummary): string {
  const which =
    run.role === 'reference'
      ? `Reference snapshot ${run.snapshot_id} (the experiments' pinned data)`
      : `Served snapshot ${run.web_snapshot_id ?? run.snapshot_id} (the data on this page)`;
  const head = `${which} at ${run.t_utc}: ${plural(run.mismatches, 'mismatch', 'mismatches')} over ${run.pairs} canonical city pairs (${run.reachable} with a path).`;
  if (run.mismatches === 0 && run.ties === 0 && run.identical_paths === run.reachable) {
    return `${head} All ${run.reachable} paths identical to Python's, with a byte-identical header, packet and pcap.`;
  }
  return (
    `${head} ${run.identical_paths} of ${run.reachable} paths identical to Python's; ` +
    `${plural(run.ties, 'equal-cost tie', 'equal-cost ties')} (cost within 1 ns, different path) compared on Python's path, ` +
    'whose header, packet and pcap were rebuilt and matched byte for byte.'
  );
}

/** The closing sentence of the badge. */
export function badgeConclusion(summary: ParitySummary): string {
  return allPathsIdentical(summary)
    ? "Routes identical given identical positions (Python's SGP4 positions of the satellites and cities)."
    : "Routes equal in cost given identical positions (Python's SGP4 positions of the satellites and cities); " +
        'not every path is the same one.';
}

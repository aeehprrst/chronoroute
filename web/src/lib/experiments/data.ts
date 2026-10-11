import {
  E0_CHECK_KINDS,
  E0_CHECK_NOTES,
  type CheckKind,
  type ExperimentDefinition,
  type Metric,
} from './catalog';
export type Row = Record<string, string>;
export interface ChartEvidence {
  runId: string;
  commit: string;
  summarySha: string;
  manifestSha: string;
  dirty: false;
}

/** Strict CSV parser; values stay strings so infinity and missingness survive hydration. */
export function parseCsv(text: string): { columns: string[]; rows: Row[] } {
  const records: string[][] = [];
  let record: string[] = [];
  let cell = '';
  let quoted = false;
  let closed = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (quoted) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i++;
        } else {
          quoted = false;
          closed = true;
        }
      } else cell += c;
      continue;
    }
    if (c === '"') {
      if (cell || closed) throw new Error('Malformed CSV quote');
      quoted = true;
      continue;
    }
    if (c === ',' || c === '\n' || c === '\r') {
      record.push(cell);
      cell = '';
      closed = false;
      if (c !== ',') {
        if (c === '\r' && text[i + 1] === '\n') i++;
        records.push(record);
        record = [];
      }
      continue;
    }
    if (closed) throw new Error('Malformed CSV after closing quote');
    cell += c;
  }
  if (quoted) throw new Error('Unclosed CSV quote');
  if (cell || closed || record.length) {
    record.push(cell);
    records.push(record);
  }
  const columns = records.shift();
  if (
    !columns?.length ||
    columns.some((c) => !c) ||
    new Set(columns).size !== columns.length
  )
    throw new Error('Missing or duplicate CSV columns');
  const rows = records.map((r) => {
    if (r.length !== columns.length) throw new Error('CSV row width differs');
    if (r.some((v) => /^[+-]?nan$/i.test(v.trim())))
      throw new Error('NaN in scientific CSV');
    return Object.fromEntries(columns.map((c, i) => [c, r[i]!]));
  });
  if (!rows.length) throw new Error('Empty scientific summary');
  return { columns, rows };
}

export function numeric(value: string | undefined): number | null {
  if (value === undefined || value.trim() === '') return null;
  if (/^[+]?inf(?:inity)?$/i.test(value)) return Infinity;
  if (/^-inf(?:inity)?$/i.test(value)) return -Infinity;
  if (!/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value))
    throw new Error(`Invalid scientific number: ${value}`);
  const n = Number(value);
  if (!Number.isFinite(n)) throw new Error('Numeric overflow');
  return n;
}

export function formatValue(value: string | undefined): string {
  if (value === undefined || value === '') return 'undefined';
  if (/^[+]?inf(?:inity)?$/i.test(value)) return '∞';
  if (/^-inf(?:inity)?$/i.test(value)) return '−∞';
  return value;
}

/** Rounded display of a stored value (the stored string stays the source of truth). */
export function fmt(value: string | undefined, digits = 3): string {
  const n = numeric(value);
  if (n === null) return 'undefined';
  if (!Number.isFinite(n)) return formatValue(value);
  if (n === 0) return '0';
  if (Math.abs(n) >= 1000) return String(Math.round(n));
  return String(Number(n.toPrecision(digits)));
}

/** p-value columns: p, p_lower, p_upper, adjusted_p and similar. */
export function isPValueColumn(column: string): boolean {
  return column === 'p' || /^p_/.test(column) || /_p$/.test(column);
}
/** True when a row's recorded intervals all have zero width (every paired difference identical). */
export function zeroWidth(row: Row): boolean {
  const pairs = [
    ['lo', 'hi'],
    ['lo90', 'hi90'],
    ['lo95', 'hi95'],
  ].filter(([a, b]) => row[a!] !== undefined && row[b!] !== undefined);
  return (
    pairs.length > 0 &&
    pairs.every(([a, b]) => {
      const lo = numeric(row[a!]);
      return lo !== null && lo === numeric(row[b!]);
    })
  );
}
/**
 * A stored p-value of 0 is never shown as 0: it is below the numerical resolution of the
 * computation (cancellation in 2(1 - F)), or it comes from the zero-variance branch.
 */
export function formatPValue(value: string | undefined, degenerate = false): string {
  const n = numeric(value);
  if (n === 0)
    return degenerate
      ? '< numerical resolution (zero-variance branch)'
      : '< numerical resolution';
  return formatValue(value);
}
/** Rounded p-value for prose; a stored 0 is never shown as 0. */
export function fmtP(value: string | undefined, degenerate = false): string {
  return numeric(value) === 0 ? formatPValue(value, degenerate) : fmt(value);
}
export function formatCell(row: Row, column: string): string {
  return isPValueColumn(column)
    ? formatPValue(row[column], zeroWidth(row))
    : formatValue(row[column]);
}

export const FILTER_KEYS = ['const', 'condition', 'mode', 'endpoint', 'k'] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export interface Selection {
  const?: string | undefined;
  condition?: string | undefined;
  mode?: string | undefined;
  endpoint?: string | undefined;
  k?: string | undefined;
  selected?: boolean;
  search?: string;
}
type WithId = Pick<ExperimentDefinition, 'id'>;
export function selectRows(def: WithId, rows: Row[], selection: Selection): Row[] {
  return rows.filter(
    (r) =>
      FILTER_KEYS.every((k) => !selection[k] || r[k] === selection[k]) &&
      (def.id !== 'E01' || !selection.selected || r['selected'] === 'True') &&
      (!selection.search ||
        Object.values(r).some((v) =>
          v.toLowerCase().includes(selection.search!.toLowerCase()),
        )),
  );
}
/** The first view of each experiment; computed once at build time and passed to the island. */
export function initialSelection(def: WithId, rows: Row[]): Selection {
  const first = rows[0] ?? {};
  const selection: Selection = { selected: true };
  const set = (key: FilterKey, value: string | undefined) => {
    if (value !== undefined) selection[key] = value;
  };
  if (def.id !== 'E16') {
    set('const', first['const']);
    set(
      'condition',
      def.id === 'E05'
        ? 'trigger'
        : def.id === 'E01'
          ? 'rate-0.3-middle'
          : first['condition'],
    );
  }
  set('mode', first['mode']);
  set('endpoint', first['endpoint']);
  if (def.id === 'E01') selection.k = '2';
  return selection;
}
export function filterOptions(rows: Row[]): Partial<Record<FilterKey, string[]>> {
  const options: Partial<Record<FilterKey, string[]>> = {};
  for (const key of FILTER_KEYS)
    if (rows.some((r) => r[key] !== undefined))
      options[key] = [...new Set(rows.map((r) => r[key]!))];
  return options;
}

/** What the browser island needs: the definition's chart/table parts and the first view only. */
export type ExplorerDefinition = Pick<ExperimentDefinition, 'id' | 'metrics' | 'tableColumns'>;
export interface ExplorerProps {
  definition: ExplorerDefinition;
  /** Rows of the initial selection (every column), or every row when that is all of them. */
  rows: Row[];
  totalRows: number;
  columns: string[];
  options: Partial<Record<FilterKey, string[]>>;
  selection: Selection;
  /** The byte-identical summary.csv download, fetched and hash-checked in the browser. */
  csvHref: string;
  evidence: ChartEvidence;
}
export function explorerProps(
  def: ExperimentDefinition,
  rows: Row[],
  columns: string[],
  evidence: ChartEvidence,
  csvHref: string,
): ExplorerProps {
  const selection = initialSelection(def, rows);
  const initial = selectRows(def, rows, selection);
  return {
    definition: { id: def.id, metrics: def.metrics, tableColumns: def.tableColumns },
    rows: initial.length === rows.length ? rows : initial,
    totalRows: rows.length,
    columns,
    options: filterOptions(rows),
    selection,
    csvHref,
    evidence,
  };
}
/**
 * Browser-side evidence check of the downloaded summary: its SHA-256 must equal the manifest
 * entry verified at build time, and it must parse to the same columns and row count.
 */
export async function verifySummaryBytes(
  bytes: ArrayBuffer,
  expectedSha: string,
  columns: string[],
  totalRows: number,
  subtle: SubtleCrypto | null = globalThis.crypto?.subtle ?? null,
): Promise<Row[]> {
  if (!subtle) throw new Error('this browser cannot compute SHA-256 here');
  const digest = new Uint8Array(await subtle.digest('SHA-256', bytes));
  const hex = Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join('');
  if (hex !== expectedSha)
    throw new Error('the downloaded summary.csv does not match the manifest SHA-256');
  const parsed = parseCsv(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  if (
    parsed.columns.length !== columns.length ||
    parsed.columns.some((c, i) => c !== columns[i]) ||
    parsed.rows.length !== totalRows
  )
    throw new Error('the downloaded summary.csv differs from the build');
  return parsed.rows;
}

export interface PlotPoint {
  row: Row;
  label: string;
  value: number;
  lo: number;
  hi: number;
  x: number;
  y: number;
  lowY: number;
  highY: number;
  series: string;
}
export interface PlotModel {
  points: PlotPoint[];
  omitted: { label: string; reason: string; row: Row }[];
  minimum: number;
  maximum: number;
  hasIntervals: boolean;
  bounds: number[];
  ticks: { value: number; y: number }[];
}
/** Only coordinates are computed here; estimates and uncertainty are never recalculated. */
export function chartModel(rows: Row[], metric: Metric): PlotModel {
  const points: PlotPoint[] = [];
  const omitted: { label: string; reason: string; row: Row }[] = [];
  const bounds: number[] = [];
  rows.forEach((row, i) => {
    const label = [
      row['check'],
      row['constellation'],
      row['scheme'],
      row['const'],
      row['condition'],
      row['entries'],
      row['protocol'],
      row['rule'],
      row['k'],
    ]
      .filter(Boolean)
      .join(' / ');
    const value = numeric(row[metric.key]);
    const lo = metric.lo ? numeric(row[metric.lo]) : value;
    const hi = metric.hi ? numeric(row[metric.hi]) : value;
    if (lo !== null && hi !== null && lo > hi)
      throw new Error('Reversed confidence interval');
    for (const k of ['lower_bound', 'upper_bound']) {
      const b = numeric(row[k]);
      if (b !== null && Number.isFinite(b)) bounds.push(b);
    }
    if (
      value === null ||
      lo === null ||
      hi === null ||
      ![value, lo, hi].every(Number.isFinite)
    ) {
      omitted.push({
        label,
        reason: `estimate ${formatValue(row[metric.key])}; interval ${formatValue(metric.lo ? row[metric.lo] : row[metric.key])} to ${formatValue(metric.hi ? row[metric.hi] : row[metric.key])}`,
        row,
      });
      return;
    }
    const x = row['entries'] !== undefined ? numeric(row['entries'])! : i;
    points.push({
      row,
      label,
      value,
      lo,
      hi,
      x,
      y: 0,
      lowY: 0,
      highY: 0,
      series: row['protocol'] ?? '',
    });
  });
  const all = [...points.flatMap((p) => [p.value, p.lo, p.hi]), ...bounds];
  const minimum = all.length ? Math.min(...all) : 0;
  const maximum = all.length ? Math.max(...all) : 0;
  const span = maximum - minimum || Math.max(Math.abs(maximum) * 0.1, 1);
  const low = minimum - span * 0.1;
  const high = maximum + span * 0.1;
  const xs = points.map((p) => p.x);
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);
  for (const p of points) {
    p.x = 75 + ((p.x - xmin) / (xmax - xmin || 1)) * 740;
    p.y = 260 - ((p.value - low) / (high - low)) * 220;
    p.lowY = 260 - ((p.lo - low) / (high - low)) * 220;
    p.highY = 260 - ((p.hi - low) / (high - low)) * 220;
  }
  return {
    points,
    omitted,
    minimum,
    maximum,
    hasIntervals: !!metric.lo,
    bounds: [...new Set(bounds)],
    ticks: [...new Set([minimum, maximum])].map((value) => ({
      value,
      y: 260 - ((value - low) / (high - low)) * 220,
    })),
  };
}
/** "blackhole_losses 0; pdr_mean 0.995" for the columns that must accompany a metric. */
export function companionText(metric: Metric, row: Row): string {
  return (metric.companions ?? [])
    .filter((c) => row[c] !== undefined)
    .map((c) => `${c} ${formatValue(row[c])}`)
    .join('; ');
}

const SIGNIFICANCE = 0.05;
/** Summary metric -> registered paired-contrast endpoint, per experiment. */
const CONTRAST_ENDPOINTS: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  E01: { event_mean: 'detected', restricted_mean_s: 'restricted_s' },
  E04: {
    pdr_mean: 'pdr',
    blackhole_mean: 'blackhole_s',
    effective_p99_mean: 'effective_p99_s',
  },
  E05: {
    triggered_pdr_mean: 'triggered_pdr',
    stuck_rate_mean: 'stuck_rate',
    triggered_stretch_mean_mean: 'triggered_stretch_mean',
    triggered_extra_hops_mean_mean: 'triggered_extra_hops_mean',
  },
};
function findContrast(
  contrasts: Row[],
  cell: { const?: string | undefined; condition?: string | undefined },
  primary: string,
  comparator: string,
  endpoint: string,
): Row | undefined {
  return contrasts.find(
    (c) =>
      c['const'] === cell.const &&
      c['condition'] === cell.condition &&
      c['comparator'] === comparator &&
      c['endpoint'] === endpoint &&
      (c['primary'] === undefined || c['primary'] === primary),
  );
}
const significant = (c: Row | undefined) => {
  const p = numeric(c?.['adjusted_p']);
  return p !== null && p < SIGNIFICANCE;
};
const diff = (c: Row | undefined) => numeric(c?.['mean_diff']) ?? null;
/** "0.167 [0.039, 0.295]" from a contrast row, with the primary (paired Student-t) interval. */
function interval(c: Row, est = 'mean_diff', lo = 'lo', hi = 'hi'): string {
  return `${fmt(c[est])} [${fmt(c[lo])}, ${fmt(c[hi])}]`;
}
function describeContrast(c: Row): string {
  if (!c['mean_diff'] && c['tail_failure_mean_diff'])
    return `Paired tail-failure indicator difference ${interval(c, 'tail_failure_mean_diff', 'tail_failure_lo', 'tail_failure_hi')} (latency contrast undefined with infinite tails)`;
  if (!c['mean_diff'])
    return `Paired contrast undefined${c['reason'] ? `: ${c['reason']}` : ''}`;
  const base = `paired difference ${interval(c)} (Student-t 95%), Holm-adjusted p ${fmtP(c['adjusted_p'], zeroWidth(c))}`;
  if (c['material_loss'] === 'True') return `Registered material loss; ${base}`;
  return significant(c)
    ? `Significant after adjustment, below the material threshold; ${base}`
    : `Not significant after adjustment; ${base}`;
}

export interface LossCase {
  policy: string;
  context: string;
  metric: string;
  ours: string;
  oursDetail: string;
  competitor: string;
  theirs: string;
  theirsDetail: string;
  note: string;
  sourceRows: string;
}
/**
 * Point disadvantages from the summary. When a registered paired contrast exists for the same
 * cell, comparator and endpoint, its interval and adjusted p-value are quoted; otherwise no
 * significance is inferred from marginal intervals.
 */
export function lossCases(
  def: ExperimentDefinition,
  rows: Row[],
  contrasts: Row[] | null = null,
): LossCase[] {
  const cases: LossCase[] = [];
  if (def.id === 'E00' || def.id === 'E16') return cases;
  if (def.id === 'E02') {
    rows.forEach((r, i) => {
      if (r['protocol'] !== 'tcrh') return;
      rows.forEach((b, j) => {
        if (
          b['mode'] === r['mode'] &&
          b['entries'] === r['entries'] &&
          b['protocol'] !== 'tcrh' &&
          numeric(r['added_bytes'])! > numeric(b['added_bytes'])!
        )
          cases.push({
            policy: 'tcrh',
            context: `${r['mode']} / entries ${r['entries']}`,
            metric: 'added_bytes',
            ours: r['added_bytes']!,
            oursDetail: '',
            competitor: b['protocol']!,
            theirs: b['added_bytes']!,
            theirsDetail: '',
            note: 'Header cost disadvantage',
            sourceRows: `${i + 1}, ${j + 1}`,
          });
      });
    });
    return cases;
  }
  const primary =
    def.id === 'E01' ? selectRows(def, rows, { selected: true, k: '2' }) : rows;
  const target = def.id === 'E01' ? 'chronoroute' : 'greedy_visited';
  const metrics: [string, boolean][] =
    def.id === 'E01'
      ? [
          ['event_mean', true],
          ['restricted_mean_s', false],
          ['fpr', false],
        ]
      : def.id === 'E04'
        ? [
            ['pdr_mean', true],
            ['blackhole_mean', false],
            ['effective_p99_mean', false],
          ]
        : [
            ['triggered_pdr_mean', true],
            ['stuck_rate_mean', false],
            ['triggered_stretch_mean_mean', false],
            ['triggered_extra_hops_mean_mean', false],
          ];
  for (const r of primary) {
    if (
      !(def.id === 'E05'
        ? ['greedy_visited', 'grid_detour'].includes(r['scheme'] ?? '')
        : r['scheme'] === target) ||
      (def.id === 'E05' && r['condition'] !== 'trigger')
    )
      continue;
    const context = `${r['const']} / ${r['condition']}`;
    for (const b of primary) {
      if (
        b['scheme'] === r['scheme'] ||
        b['const'] !== r['const'] ||
        b['condition'] !== r['condition']
      )
        continue;
      for (const [metric, higher] of metrics) {
        const ours = numeric(r[metric]);
        const theirs = numeric(b[metric]);
        if (ours === null || theirs === null) continue;
        const tie =
          def.id === 'E05' &&
          metric === 'stuck_rate_mean' &&
          ours === theirs &&
          ((r['scheme'] === 'greedy_visited' &&
            b['scheme'] === 'greedy_pure') ||
            (r['scheme'] === 'grid_detour' &&
              b['scheme'] === 'greedy_visited'));
        if (!(tie || (higher ? ours < theirs : ours > theirs))) continue;
        const endpoint = CONTRAST_ENDPOINTS[def.id]?.[metric];
        const contrast =
          contrasts && endpoint
            ? findContrast(contrasts, r, r['scheme']!, b['scheme']!, endpoint)
            : undefined;
        const notes = [
          tie
            ? 'Predicted reduction unsupported (tie)'
            : b['scheme']?.startsWith('o_')
              ? 'Privileged oracle advantage'
              : contrast
                ? describeContrast(contrast)
                : contrasts && !endpoint
                  ? 'Point disadvantage; no registered paired contrast for this metric'
                  : 'Point disadvantage; adjusted paired significance unavailable',
        ];
        if (tie && contrast) notes.push(describeContrast(contrast));
        if (def.id === 'E01' && b['scheme'] === 'ls_d')
          notes.push(
            'LS-D comparator flaw: it reads the injected delay without noise and advertises any change, so this is not valid evidence about slowness detection.',
          );
        const spec = def.metrics.find((m) => m.key === metric);
        cases.push({
          policy: r['scheme']!,
          context,
          metric,
          ours: r[metric]!,
          oursDetail: spec ? companionText(spec, r) : '',
          competitor: b['scheme']!,
          theirs: b[metric]!,
          theirsDetail: spec ? companionText(spec, b) : '',
          note: notes.join(' '),
          sourceRows: `${rows.indexOf(r) + 1}, ${rows.indexOf(b) + 1}`,
        });
      }
    }
  }
  return cases;
}

export type VerdictStatus =
  | 'supported'
  | 'not supported'
  | 'mixed'
  | 'unestablished'
  | 'incomplete';
export interface Verdict {
  status: VerdictStatus;
  /** One sentence that starts with the status in words. */
  summary: string;
  /** Derived facts behind the verdict; every number comes from the summary or contrasts. */
  details: string[];
}
const verdictOf = (status: VerdictStatus, summary: string, details: string[] = []): Verdict => ({
  status,
  summary,
  details,
});

/** "1–3, 5, 7" */
export function ranges(values: number[]): string {
  const sorted = [...new Set(values)].sort((a, b) => a - b);
  const parts: string[] = [];
  for (let i = 0; i < sorted.length; i++) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j]! + 1) j++;
    parts.push(
      j === i
        ? String(sorted[i])
        : j === i + 1
          ? `${sorted[i]}, ${sorted[j]}`
          : `${sorted[i]}–${sorted[j]}`,
    );
    i = j;
  }
  return parts.length ? parts.join(', ') : 'none';
}
const unique = (values: (string | undefined)[]) =>
  [...new Set(values.filter((v): v is string => v !== undefined))];
const countWord = (k: number, m: number) => `${k} of ${m}`;

/** "9/36" when event_mean × n is a whole number of runs, otherwise the stored proportion. */
export function detections(row: Row | undefined): string {
  if (!row) return 'not recorded';
  const p = numeric(row['event_mean']);
  const n = numeric(row['n']);
  if (p === null || n === null) return 'undefined';
  const k = p * n;
  return Math.abs(k - Math.round(k)) < 1e-6 ? `${Math.round(k)}/${n}` : fmt(row['event_mean']);
}

function e0Verdict(rows: Row[]): Verdict {
  const violations = rows.reduce((s, r) => s + (numeric(r['violations']) ?? NaN), 0);
  if (!(violations === 0))
    return verdictOf(
      'not supported',
      'Hypothesis not supported (Fail): recorded correctness violations block the campaign.',
    );
  const unknown = rows.filter((r) => !((r['check'] ?? '') in E0_CHECK_KINDS));
  if (unknown.length)
    throw new Error(`Unclassified E0 check: ${unique(unknown.map((r) => r['check'])).join(', ')}`);
  const byKind = (kind: CheckKind) => {
    const checks = unique(rows.filter((r) => E0_CHECK_KINDS[r['check']!] === kind).map((r) => r['check']));
    return checks
      .map((check) => {
        const of = rows.filter((r) => r['check'] === check);
        const counts = of.map((r) => `${r['constellation']} ${r['checked']}`).join(', ');
        const note = E0_CHECK_NOTES[check];
        return `${check} (${counts}${note ? `; ${note}` : ''})`;
      })
      .join('; ');
  };
  const details = [
    `External references, where another implementation, an independent reader or fixed expected values are compared: ${byKind('reference')}.`,
    `Self-consistency only: ${byKind('self')}.`,
    `Model invariants, one implementation against registered limits: ${byKind('invariant')}.`,
  ];
  const polar = rows.filter((r) => r['check'] === 'isl_polar_cutoff');
  if (polar.length)
    details.push(
      `isl_polar_cutoff cannot fail here: the highest latitude reached is ${polar.map((r) => `${fmt(r['worst'], 4)}° (${r['constellation']})`).join(' and ')} against a ${fmt(polar[0]!['limit'])}° cutoff.`,
    );
  const grazing = rows.filter((r) => r['check'] === 'isl_grazing');
  if (grazing.length)
    details.push(
      `isl_grazing worst values (${grazing.map((r) => `${r['constellation']} ${fmt(r['worst'], 5)} ${r['unit']}`).join(', ')}) are certified spherical lower bounds, not exact minimum heights.`,
    );
  return verdictOf(
    'supported',
    `Hypothesis supported (Pass): all ${rows.length} recorded checks have 0 violations. Only the cross-implementation and fixed-value rows are external references; the rest are self-consistency or invariant checks.`,
    details,
  );
}

function e2Verdict(rows: Row[]): Verdict {
  if (!rows.every((r) => numeric(r['encoder_violations']) === 0))
    return verdictOf('not supported', 'Hypothesis not supported (Fail): encoder accounting has violations.');
  const modes = unique(rows.map((r) => r['mode']));
  const size = (mode: string, entries: number, protocol: string) =>
    numeric(
      rows.find(
        (r) => r['mode'] === mode && numeric(r['entries']) === entries && r['protocol'] === protocol,
      )?.['added_bytes'],
    );
  const entries = [...new Set(rows.map((r) => numeric(r['entries'])!))].sort((a, b) => a - b);
  const perMode = modes.map((mode) => {
    const t = (e: number) => size(mode, e, 'tcrh')!;
    const known = (p: string) => entries.filter((e) => size(mode, e, p) !== null && size(mode, e, 'tcrh') !== null);
    const srh = known('srh');
    const crh16 = known('crh16');
    const crh32 = known('crh32');
    return {
      mode,
      lessThanSrh: srh.length === entries.length && srh.every((e) => t(e) < size(mode, e, 'srh')!),
      moreThanCrh16: crh16.length === entries.length && crh16.every((e) => t(e) > size(mode, e, 'crh16')!),
      crh32Smaller: crh32.filter((e) => size(mode, e, 'crh32')! < t(e)),
      crh32Ties: crh32.filter((e) => size(mode, e, 'crh32')! === t(e)),
      crh32Larger: crh32.filter((e) => size(mode, e, 'crh32')! > t(e)),
    };
  });
  const same = perMode.every(
    (m) =>
      ranges(m.crh32Smaller) === ranges(perMode[0]!.crh32Smaller) &&
      ranges(m.crh32Ties) === ranges(perMode[0]!.crh32Ties),
  );
  const span = `${entries[0]}–${entries[entries.length - 1]}`;
  const crossover = (m: (typeof perMode)[number]) =>
    `CRH-32 is smaller at ${ranges(m.crh32Smaller)} entries, equal at ${ranges(m.crh32Ties)}, and larger at ${ranges(m.crh32Larger)}`;
  const supported = perMode.every((m) => m.lessThanSrh && m.moreThanCrh16);
  const first = perMode[0]!;
  const example = first.crh32Smaller[first.crh32Smaller.length - 1];
  const details = [
    `Encoder checks: ${rows.filter((r) => r['encoder_checked'] === 'True').length} of ${rows.length} rows checked, 0 violations.`,
  ];
  if (example !== undefined)
    details.push(
      `Example (${first.mode} insertion, ${example} entries): T-CRH adds ${size(first.mode, example, 'tcrh')} bytes, CRH-32 ${size(first.mode, example, 'crh32')}, CRH-16 ${size(first.mode, example, 'crh16')}, SRv6 SRH ${size(first.mode, example, 'srh')}.`,
    );
  if (!same) for (const m of perMode) details.push(`${m.mode} insertion: ${crossover(m)}.`);
  details.push('The CRH-16 overhead penalty is a real cost (preregistration section 9).');
  return verdictOf(
    supported ? 'supported' : 'not supported',
    `${supported ? 'Hypothesis supported' : 'Hypothesis not supported'}: T-CRH adds ${first.moreThanCrh16 ? 'more' : 'not always more'} bytes than CRH-16 and ${first.lessThanSrh ? 'fewer' : 'not always fewer'} than SRv6 SRH at every registered entry count (${span}). Against CRH-32 there is a crossover${same ? `: ${crossover(first)}` : ' that depends on the insertion mode'}.`,
    details,
  );
}

const E1_MAGNITUDES = {
  rate: { label: 'Rate cut', unit: 'factor', small: '0.6', nominal: '0.3', strong: '0.2', nul: '1' },
  delay: { label: 'Added delay', unit: 'ns', small: '250000', nominal: '1000000', strong: '4000000', nul: '0' },
  arq: { label: 'ARQ loss', unit: 'probability', small: '0.01', nominal: '0.1', strong: '0.3', nul: '0' },
} as const;
const E1_DISPLAY: Record<string, string> = {
  '250000': '0.25 ms',
  '1000000': '1 ms',
  '4000000': '4 ms',
};
function e1Verdict(rows: Row[], contrasts: Row[] | null): Verdict {
  const sel = rows.filter((r) => r['selected'] === 'True' && r['k'] === '2');
  const ours = sel.filter((r) => r['scheme'] === 'chronoroute');
  if (!ours.length || ours.some((r) => numeric(r['fpr']) === null))
    return verdictOf(
      'unestablished',
      'Unestablished: the operating constraint is undefined for missing or undefined selected-point results.',
    );
  const fprs = ours.map((r) => numeric(r['fpr'])!);
  const maxFpr = Math.max(...fprs);
  const fprText = `clean-packet false-positive rate ${fmt(String(Math.min(...fprs)))} to ${fmt(String(maxFpr))} across cells, ${maxFpr > 0.01 ? 'above' : 'within'} the registered 0.01 limit`;
  if (maxFpr > 0.01)
    return verdictOf(
      'not supported',
      `Hypothesis not supported: the selected operating point fails the registered false-positive constraint (${fprText}). Detection advantages and blind spots remain cell-dependent.`,
    );
  // C5 (REAL orbital elements) first, then the MODELLED shells.
  const consts = unique(ours.map((r) => r['const'])).sort((a, b) =>
    a === 'C5' ? -1 : b === 'C5' ? 1 : a.localeCompare(b),
  );
  const cell = (c: string, condition: string, scheme = 'chronoroute') =>
    sel.find((r) => r['const'] === c && r['condition'] === condition && r['scheme'] === scheme);
  const conditions = unique(ours.map((r) => r['condition']));
  const position = (c: string) => ['first', 'middle', 'last'].indexOf(c.split('-').pop() ?? '');
  const at = (family: string, magnitude: string) =>
    conditions
      .filter((c) => c.startsWith(`${family}-${magnitude}-`))
      .sort((a, b) => position(a) - position(b));
  // Supported in a cell: significantly more detections than BOTH LS-H and CRH-16 (Holm-adjusted).
  const wins = (c: string, condition: string) =>
    !!contrasts &&
    ['ls_h', 'crh16'].every((comp) => {
      const k = findContrast(contrasts, { const: c, condition }, 'chronoroute', comp, 'detected');
      return (diff(k) ?? 0) > 0 && significant(k);
    });
  const details = [
    `Operating point: rule ${ours[0]!['rule']} with k = 2 consecutive alarms, chosen on pilot seeds only and frozen; ${fprText}.`,
  ];
  let supportedCells = 0;
  let testedCells = 0;
  const familyWords: Record<string, string> = {};
  for (const [family, m] of Object.entries(E1_MAGNITUDES)) {
    const parts: string[] = [];
    let famWins = 0;
    let famCells = 0;
    for (const grade of ['nominal', 'strong', 'small'] as const) {
      const conds = at(family, m[grade]);
      if (!conds.length) continue;
      const shown = consts
        .map((c) => `${c} ${conds.map((cond) => detections(cell(c, cond))).join(', ')}`)
        .join('; ');
      const positions = conds.map((cond) => cond.split('-').pop()).join(', ');
      const label = `${grade} ${family === 'delay' ? (E1_DISPLAY[m[grade]] ?? m[grade]) : m[grade]}${conds.length > 1 ? ` (${positions} third)` : ''}`;
      let judged = '';
      if (grade !== 'small' && contrasts) {
        const cells = consts.flatMap((c) => conds.map((cond) => wins(c, cond)));
        const k = cells.filter(Boolean).length;
        famWins += k;
        famCells += cells.length;
        judged = k === cells.length ? ' — supported' : k === 0 ? ' — not supported' : ` — supported in ${countWord(k, cells.length)} cells`;
      } else if (grade === 'small') judged = ' — may stay undetected by hypothesis';
      parts.push(`${label}: ${shown}${judged}`);
    }
    if (!parts.length) continue;
    supportedCells += famWins;
    testedCells += famCells;
    familyWords[family] = famWins === famCells ? 'supported' : famWins === 0 ? 'not supported' : 'partly supported';
    details.push(`${m.label}, runs detected per shell (${consts.join(', ')}): ${parts.join('. ')}.`);
  }
  // Separate the strong rate cut from the nominal one in the headline.
  const rateCells = (magnitude: string) =>
    consts.flatMap((c) => at('rate', magnitude).map((cond) => wins(c, cond)));
  const nominalRate = rateCells(E1_MAGNITUDES.rate.nominal);
  const strongRate = rateCells(E1_MAGNITUDES.rate.strong);
  // Why the delay family is missed: rules that do detect the strong delay break the FPR limit.
  const strongDelay = at('delay', E1_MAGNITUDES.delay.strong)[0];
  if (strongDelay) {
    const looser = consts.map((c) => {
      const detecting = rows.filter(
        (r) =>
          r['scheme'] === 'chronoroute' &&
          r['k'] === '2' &&
          r['selected'] !== 'True' &&
          r['const'] === c &&
          r['condition'] === strongDelay &&
          (numeric(r['event_mean']) ?? 0) >= 0.5,
      );
      const lowest = detecting.map((r) => numeric(r['fpr'])).filter((v): v is number => v !== null);
      return lowest.length ? `${c} ${fmt(String(Math.min(...lowest)))}` : `${c} no such rule`;
    });
    details.push(
      `Why delays are missed: S = 1.5 leaves several milliseconds of spare time per hop mid-path. Every unselected rule that detects the 4 ms delay in at least half the runs has a clean false-positive rate of at least ${looser.join(' and ')}, above the 1% limit.`,
    );
  }
  const nulls = Object.entries(E1_MAGNITUDES).flatMap(([family, m]) => at(family, m.nul));
  if (nulls.length) {
    const fired = consts.flatMap((c) => nulls.map((cond) => numeric(cell(c, cond)?.['event_mean']) ?? 0));
    details.push(
      `Null controls (rate factor 1, delay 0, ARQ loss 0): ${fired.every((v) => v === 0) ? 'no detections in any cell' : 'detections recorded; see the table'}.`,
    );
  }
  let lqLosses = 0;
  if (contrasts) {
    const detection = contrasts.filter((c) => c['endpoint'] === 'detected');
    const tally = (comp: string) => {
      const of = detection.filter((c) => c['comparator'] === comp);
      const d = (c: Row) => diff(c) ?? 0;
      return {
        n: of.length,
        sigWin: of.filter((c) => d(c) > 0 && significant(c)).length,
        win: of.filter((c) => d(c) > 0 && !significant(c)).length,
        tie: of.filter((c) => d(c) === 0).length,
        sigLoss: of.filter((c) => d(c) < 0 && significant(c)).length,
        loss: of.filter((c) => d(c) < 0 && !significant(c)).length,
        material: contrasts.filter((c) => c['comparator'] === comp && c['material_loss'] === 'True').length,
      };
    };
    const text = (t: ReturnType<typeof tally>) =>
      `${t.sigWin} significant wins, ${t.win} non-significant wins, ${t.tie} ties, ${t.sigLoss} significant losses and ${t.loss} non-significant losses over ${t.n} cells`;
    const maxEvent = (scheme: string) =>
      Math.max(
        ...sel
          .filter((r) => r['scheme'] === scheme && !nulls.includes(r['condition']!))
          .map((r) => numeric(r['event_mean']) ?? 0),
      );
    const fprRange = (scheme: string) => {
      const v = sel.filter((r) => r['scheme'] === scheme).map((r) => numeric(r['fpr'])).filter((x): x is number => x !== null);
      if (!v.length) return 'undefined';
      const [lo, hi] = [fmt(String(Math.min(...v))), fmt(String(Math.max(...v)))];
      return lo === hi ? `${lo} in every cell` : `${lo} to ${hi}`;
    };
    const blind = Math.max(maxEvent('ls_h'), maxEvent('crh16'));
    const lsh = tally('ls_h');
    const crh = tally('crh16');
    const e2e = tally('e2e');
    const lq = tally('lq');
    const lsd = tally('ls_d');
    lqLosses = lq.sigLoss;
    details.push(
      `Detection against LS-H: ${text(lsh)}; CRH-16: ${text(crh)}. ${blind === 0 ? 'These wins hold by construction: LS-H and CRH-16 detect no fault in any cell, because they have no slowness detector.' : `LS-H and CRH-16 have no slowness detector; their highest detection probability in a fault cell is ${fmt(String(blind))}.`}`,
      `Against E2E: ${text(e2e)}. E2E's clean false-positive rate is ${fprRange('e2e')}, so this is not a matched-false-positive comparison.`,
      `Against LQ, a practical local monitor (false-positive rate ${fprRange('lq')}): ${text(lq)}; ${lq.material} registered material losses (detection and restricted delay). These losses are robust.`,
      `Against LS-D: ${text(lsd)}; ${lsd.material} registered material losses. They are kept as registered but are not valid evidence: LS-D measures the queue estimate plus the exact injected fault delay plus the expected ARQ delay from the configured loss probability, without noise, and re-advertises any change at the 1 s update interval. Its detection hardly depends on fault size: for 0.25, 1 and 4 ms of added delay it detects ${consts
        .map(
          (c) =>
            `${c} ${['250000', '1000000', '4000000']
              .map((mag) => detections(cell(c, `delay-${mag}-middle`, 'ls_d')))
              .join(', ')}`,
        )
        .join('; ')}. The registered LS-D delay comparison therefore cannot be judged.`,
    );
    const material = contrasts.filter((c) => c['material_loss'] === 'True');
    const zeroP = contrasts.filter((c) => numeric(c['adjusted_p']) === 0);
    details.push(
      `Registered material losses: ${material.length} (${material.filter((c) => c['endpoint'] === 'detected').length} detection, ${material.filter((c) => c['endpoint'] !== 'detected').length} restricted delay); point disadvantages: ${contrasts.filter((c) => c['point_disadvantage'] === 'True').length}. All are in paired_contrasts.csv.`,
      `${zeroP.length} adjusted p-values are stored as 0. They are below the numerical resolution of the computation (${zeroP.filter((c) => zeroWidth(c)).length} from zero-variance paired differences, the rest from cancellation), not exactly zero.`,
    );
  }
  const anyWin = supportedCells > 0;
  const allWin = testedCells > 0 && supportedCells === testedCells;
  const status: VerdictStatus = !contrasts
    ? 'unestablished'
    : allWin
      ? 'supported'
      : anyWin
        ? 'mixed'
        : 'not supported';
  const rateWord = (cells: boolean[]) =>
    cells.every(Boolean) ? 'supported' : cells.some(Boolean) ? 'partly supported' : 'not supported';
  const lead =
    status === 'mixed'
      ? supportedCells * 2 < testedCells
        ? 'Mixed, mostly not supported'
        : 'Mixed'
      : status === 'supported'
        ? 'Hypothesis supported'
        : 'Hypothesis not supported';
  return verdictOf(
    status,
    !contrasts
      ? `Unestablished: the selected operating point meets the false-positive constraint (${fprText}); paired comparisons are not available to judge the detection hypothesis.`
      : `${lead}: at the frozen pilot rule (${fprText}), the hypothesis is ${rateWord(nominalRate)} for the nominal rate cut (factor ${E1_MAGNITUDES.rate.nominal}) and ${familyWords['delay'] ?? 'not judged'} for the added-delay family, ${rateWord(strongRate)} for the strong rate cut (factor ${E1_MAGNITUDES.rate.strong}) and ${familyWords['arq'] ?? 'not judged'} for ARQ loss (significantly more detections than both LS-H and CRH-16 in ${supportedCells} of ${testedCells} nominal and strong cells; neither comparator has a slowness detector). LQ beats ChronoRoute significantly in ${lqLosses} cells, and the LS-D comparison is not valid evidence.`,
    details,
  );
}

function e4Verdict(rows: Row[], contrasts: Row[] | null): Verdict {
  if (!contrasts)
    return verdictOf(
      'unestablished',
      'Unestablished: paired comparisons are not available; point disadvantages below are descriptive only.',
    );
  const of = (comp: string, endpoint: string) =>
    contrasts.filter(
      (c) => c['primary'] === 'greedy_visited' && c['comparator'] === comp && c['endpoint'] === endpoint,
    );
  const better = (list: Row[], higher: boolean) => ({
    n: list.length,
    point: list.filter((c) => (higher ? (diff(c) ?? 0) > 0 : (diff(c) ?? 0) < 0)).length,
    sig: list.filter((c) => (higher ? (diff(c) ?? 0) > 0 : (diff(c) ?? 0) < 0) && significant(c)).length,
  });
  const pdr = ['continue', 'crh16'].map((comp) => ({ comp, ...better(of(comp, 'pdr'), true) }));
  const bh = ['continue', 'crh16'].map((comp) => ({ comp, ...better(of(comp, 'blackhole_s'), false) }));
  const tailAbove = (comp: string) =>
    of(comp, 'effective_p99_s').filter((c) => (numeric(c['tail_failure_lo']) ?? 0) > 0);
  const tailLsh = tailAbove('ls_h');
  const tailSnap = tailAbove('snap');
  const cellName = (c: Row) => `${c['const']} ${c['condition']}`;
  const describe = (list: { comp: string; n: number; point: number; sig: number }[]) =>
    list.map((x) => `${x.comp} ${x.point} of ${x.n} cells (Holm-significant in ${x.sig})`).join(', ');
  const details = [
    `PDR, greedy_visited higher than: ${describe(pdr)}.`,
    `Registered blackhole time, greedy_visited lower than: ${describe(bh)}.`,
  ];
  // The blackhole metric does not count the fallback's own hop_limit/loop losses.
  const gv = rows.filter((r) => r['scheme'] === 'greedy_visited' && r['condition'] !== 'none');
  const lost = (r: Row) => (numeric(r['sent']) ?? 0) - (numeric(r['delivered']) ?? 0);
  const hidden = gv.filter((r) => numeric(r['blackhole_losses']) === 0 && lost(r) > 0);
  const example = [...hidden].sort((a, b) => lost(b) - lost(a))[0];
  if (example) {
    const lsh = rows.find(
      (r) => r['scheme'] === 'ls_h' && r['const'] === example['const'] && r['condition'] === example['condition'],
    );
    details.push(
      `The blackhole metric counts only next_link_down, no_fallback and stuck losses (plus in-flight and node_down), not the fallback’s own hop_limit or loop losses. greedy_visited has 0 counted blackhole losses in ${hidden.length} of ${gv.length} outage cells yet still loses packets there. Example, ${cellName(example)}: blackhole ${fmt(example['blackhole_mean'])} s with ${example['blackhole_losses']} counted losses, but ${lost(example)} of ${example['sent']} packets lost (PDR ${fmt(example['pdr_mean'], 6)})${lsh ? `; LS-H has blackhole ${fmt(lsh['blackhole_mean'])} s with ${lsh['blackhole_losses']} counted losses and PDR ${fmt(lsh['pdr_mean'], 6)}` : ''}.`,
    );
  }
  details.push(
    tailLsh.length
      ? `No-tail-penalty hypothesis not supported against LS-H: the paired tail-failure indicator (greedy_visited minus LS-H) is above zero in ${tailLsh.map((c) => `${cellName(c)} ${interval(c, 'tail_failure_mean_diff', 'tail_failure_lo', 'tail_failure_hi')}`).join(', ')}. The registered material-loss rule needs a finite latency ratio, so its list is empty for tails by construction.`
      : 'The paired tail-failure indicator against LS-H does not exceed zero in any cell.',
    tailSnap.length
      ? `Against SNAP the tail-failure indicator is above zero in ${tailSnap.map(cellName).join(', ')}.`
      : 'Against SNAP the paired tail-failure indicator is not above zero in any cell.',
  );
  const lshPdr = of('ls_h', 'pdr');
  details.push(
    `LS-H has a higher PDR point estimate than greedy_visited in ${lshPdr.filter((c) => (diff(c) ?? 0) < 0).length} of ${lshPdr.length} cells (Holm-significant in ${lshPdr.filter((c) => (diff(c) ?? 0) < 0 && significant(c)).length}).`,
  );
  const ttm = (scheme: string) => {
    const list = rows.filter((r) => r['scheme'] === scheme && r['condition'] !== 'none');
    const sum = (k: string) => list.reduce((s, r) => s + (numeric(r[k]) ?? 0), 0);
    return `${sum('ttm_censored')} of ${sum('outages')}`;
  };
  details.push(
    `Time to mitigation (a registered secondary endpoint) is censored in ${ttm('greedy_visited')} greedy_visited outages, because fallback packets still meet the dead link by definition, against ${ttm('ls_h')} for LS-H.`,
    'Intervals quoted here are the registered paired Student-t 95% intervals; paired_contrasts.csv also holds bootstrap intervals.',
  );
  const improves = [...pdr, ...bh].every((x) => x.n > 0 && x.point === x.n);
  const tailOk = !tailLsh.length && !tailSnap.length;
  const status: VerdictStatus = improves && tailOk ? 'supported' : improves || tailOk ? 'mixed' : 'not supported';
  const spread = (list: { sig: number; point: number }[], key: 'sig' | 'point') => {
    const lo = Math.min(...list.map((x) => x[key]));
    const hi = Math.max(...list.map((x) => x[key]));
    return lo === hi ? String(lo) : `${lo} to ${hi}`;
  };
  const cellsText = (list: { n: number; point: number; sig: number }[]) =>
    `${list.every((x) => x.point === x.n) ? 'every outage cell' : `${spread(list, 'point')} of ${list[0]?.n ?? 0} outage cells`} (Holm-significant in ${spread(list, 'sig')})`;
  return verdictOf(
    status,
    `${status === 'mixed' ? 'Mixed' : status === 'supported' ? 'Hypothesis supported' : 'Hypothesis not supported'}: against continue and CRH-16 the greedy-with-visited fallback has higher PDR in ${cellsText(pdr)} and lower registered blackhole time in ${cellsText(bh)}, but that metric excludes the fallback’s own hop_limit and loop losses${tailLsh.length ? `, and the no-tail-penalty hypothesis is not supported against LS-H (tail-failure indicator above zero in ${tailLsh.length} cells)` : ''}.`,
    details,
  );
}

function e5Verdict(rows: Row[], contrasts: Row[] | null): Verdict {
  if (!contrasts)
    return verdictOf(
      'unestablished',
      'Unestablished: paired comparisons are not available; point disadvantages below are descriptive only.',
    );
  const stuck = (primary: string, comp: string) =>
    contrasts.filter(
      (c) => c['primary'] === primary && c['comparator'] === comp && c['endpoint'] === 'stuck_rate',
    );
  const show = (list: Row[]) =>
    list
      .map(
        (c) =>
          `${c['const']} ${interval(c)}, Holm-adjusted p ${fmtP(c['adjusted_p'], zeroWidth(c))}${zeroWidth(c) && diff(c) === 0 ? ' (identical in every run)' : ''}`,
      )
      .join('; ');
  const visited = stuck('greedy_visited', 'greedy_pure');
  const grid = stuck('grid_detour', 'greedy_visited');
  const visitedOk = visited.length > 0 && visited.every((c) => (diff(c) ?? 0) < 0 && significant(c));
  const gridOk = grid.length > 0 && grid.every((c) => (diff(c) ?? 0) < 0 && significant(c));
  const trigger = rows.filter((r) => r['condition'] === 'trigger');
  const completion = unique(trigger.map((r) => r['const'])).flatMap((c) => {
    const cont = trigger.find((r) => r['const'] === c && r['scheme'] === 'continue');
    const vis = trigger.find((r) => r['const'] === c && r['scheme'] === 'greedy_visited');
    const a = numeric(cont?.['triggered_pdr_mean']);
    const b = numeric(vis?.['triggered_pdr_mean']);
    return a !== null && b !== null && a > b ? [`${c}: continue ${fmt(cont!['triggered_pdr_mean'])} vs greedy_visited ${fmt(vis!['triggered_pdr_mean'])}`] : [];
  });
  const details = [
    `Stuck/loop loss rate, greedy_visited minus greedy_pure (paired Student-t 95%): ${show(visited)}.`,
    `Grid detour minus greedy_visited: ${show(grid)}.`,
    completion.length
      ? `Continue completes more triggered packets than greedy_visited in ${completion.join('; ')}.`
      : 'Continue does not complete more triggered packets than greedy_visited in any shell.',
  ];
  const status: VerdictStatus = visitedOk && gridOk ? 'supported' : visitedOk || gridOk ? 'mixed' : 'not supported';
  return verdictOf(
    status,
    `${status === 'mixed' ? 'Mixed' : status === 'supported' ? 'Hypothesis supported' : 'Hypothesis not supported'}: greedy-with-visited ${visitedOk ? 'reduces' : 'does not significantly reduce'} the stuck/loop loss rate against pure greedy in ${visited.filter((c) => (diff(c) ?? 0) < 0 && significant(c)).length} of ${visited.length} shells; the Grid detour ${gridOk ? 'reduces it further' : 'shows no extra benefit'}${completion.length ? `, and continue wins triggered completion in ${completion.map((t) => t.split(':')[0]).join(' and ')}` : ''}.`,
    details,
  );
}

function e16Verdict(rows: Row[]): Verdict {
  if (!rows.every((r) => r['equivalent'] === 'True'))
    return verdictOf(
      'unestablished',
      'Equivalence unestablished for at least one endpoint: interchangeability is not shown in that cell.',
    );
  const degenerate = rows.every((r) => zeroWidth(r));
  const cells = unique(rows.map((r) => `${r['const']}|${r['condition']}`));
  const pairs = cells.reduce(
    (s, key) => s + (numeric(rows.find((r) => `${r['const']}|${r['condition']}` === key)?.['n']) ?? 0),
    0,
  );
  const details = [
    `All ${rows.length} endpoint rows pass the registered TOST over ${cells.length} cells (${pairs} paired runs).`,
  ];
  if (degenerate)
    details.push(
      `Common-random-numbers design: both engines replay the same pre-generated send list and nothing else is random, so per-packet identity is expected. All ${pairs} paired differences are exactly 0 (ratios exactly 1): every interval has zero width, and the p-values come from the zero-variance branch, not from a t distribution. The equivalence test is therefore degenerate; the preregistration declared this design.`,
    );
  details.push(
    'No packet was lost in any run on either engine, so PDR and false-positive equivalence sit at the boundary and do not test loss paths. The agreement covers delivery, queueing and deadline flags.',
  );
  return verdictOf(
    'supported',
    `Hypothesis supported within the replayed scope: every endpoint is equivalent${degenerate ? ', but by a common-random-numbers design that makes the test degenerate (all paired differences exactly 0)' : ''}, and no run lost a packet, so loss paths are not tested.`,
    details,
  );
}

/** Honest verdict derived from the verified summary (and, where registered, paired contrasts). */
export function verdict(
  def: ExperimentDefinition,
  rows: Row[],
  contrasts: Row[] | null = null,
): Verdict {
  if (rows.some((r) => r['complete'] === 'False'))
    return verdictOf('incomplete', 'Incomplete: the registered verdict is unestablished.');
  if (def.id === 'E00') return e0Verdict(rows);
  if (def.id === 'E16') return e16Verdict(rows);
  if (def.id === 'E02') return e2Verdict(rows);
  if (def.id === 'E01') return e1Verdict(rows, contrasts);
  if (def.id === 'E04') return e4Verdict(rows, contrasts);
  if (def.id === 'E05') return e5Verdict(rows, contrasts);
  return verdictOf(
    'unestablished',
    'Unestablished: no verdict rule is registered for this experiment.',
  );
}

import type { ExperimentDefinition, Metric } from './catalog';
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
export interface Selection {
  const?: string | undefined;
  condition?: string | undefined;
  mode?: string | undefined;
  endpoint?: string | undefined;
  k?: string | undefined;
  selected?: boolean;
  search?: string;
}
export function selectRows(
  def: ExperimentDefinition,
  rows: Row[],
  selection: Selection,
): Row[] {
  return rows.filter(
    (r) =>
      ['const', 'condition', 'mode', 'endpoint', 'k'].every(
        (k) =>
          !selection[k as keyof Selection] ||
          r[k] === selection[k as keyof Selection],
      ) &&
      (def.id !== 'E01' || !selection.selected || r['selected'] === 'True') &&
      (!selection.search ||
        Object.values(r).some((v) =>
          v.toLowerCase().includes(selection.search!.toLowerCase()),
        )),
  );
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
  omitted: { label: string; reason: string }[];
  minimum: number;
  maximum: number;
  hasIntervals: boolean;
  bounds: number[];
  ticks: { value: number; y: number }[];
}
/** Only coordinates are computed here; estimates and uncertainty are never recalculated. */
export function chartModel(rows: Row[], metric: Metric): PlotModel {
  const points: PlotPoint[] = [];
  const omitted: { label: string; reason: string }[] = [];
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

export interface LossCase {
  policy: string;
  context: string;
  metric: string;
  ours: string;
  competitor: string;
  theirs: string;
  note: string;
  sourceRows: string;
}
/** Point disadvantages are descriptive; no significance is inferred from marginal intervals. */
export function lossCases(def: ExperimentDefinition, rows: Row[]): LossCase[] {
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
            competitor: b['protocol']!,
            theirs: b['added_bytes']!,
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
        if (tie || (higher ? ours < theirs : ours > theirs))
          cases.push({
            policy: r['scheme']!,
            context,
            metric,
            ours: r[metric]!,
            competitor: b['scheme']!,
            theirs: b[metric]!,
            note: tie
              ? 'Predicted reduction unsupported (tie)'
              : b['scheme']?.startsWith('o_')
                ? 'Privileged oracle advantage'
                : 'Point disadvantage; adjusted paired significance unavailable',
            sourceRows: `${rows.indexOf(r) + 1}, ${rows.indexOf(b) + 1}`,
          });
      }
    }
  }
  return cases;
}

export function verdict(def: ExperimentDefinition, rows: Row[]): string {
  if (rows.some((r) => r['complete'] === 'False'))
    return 'Incomplete: the registered verdict is unestablished.';
  if (def.id === 'E00')
    return rows.every((r) => numeric(r['violations']) === 0)
      ? 'Pass: all recorded correctness checks have zero violations.'
      : 'Fail: recorded correctness violations block the campaign.';
  if (def.id === 'E16')
    return rows.every((r) => r['equivalent'] === 'True')
      ? 'Scoped equivalence established for every recorded endpoint.'
      : 'Equivalence unestablished for at least one endpoint.';
  if (def.id === 'E02')
    return rows.every((r) => numeric(r['encoder_violations']) === 0)
      ? 'Accounting checks pass; size advantages depend on protocol and padding. The CRH-16 penalty remains a cost.'
      : 'Fail: encoder accounting has violations.';
  if (def.id === 'E01') {
    const selected = selectRows(def, rows, { selected: true, k: '2' }).filter(
      (r) => r['scheme'] === 'chronoroute',
    );
    if (
      selected.some(
        (r) => numeric(r['fpr']) !== null && numeric(r['fpr'])! > 0.01,
      )
    )
      return 'The selected operating point fails the preregistered false-positive constraint in at least one cell. Detection advantages and blind spots remain cell-dependent.';
    if (!selected.length || selected.some((r) => numeric(r['fpr']) === null))
      return 'The operating constraint is unestablished for missing or undefined selected-point results.';
    return 'The selected operating point meets the recorded point-estimate false-positive constraint. Detection advantages remain cell-dependent; adjusted paired significance is not established by this summary alone.';
  }
  return 'Mixed or unsupported policy advantages: inspect completion, costs and point disadvantages below. This summary alone does not establish adjusted paired significance.';
}

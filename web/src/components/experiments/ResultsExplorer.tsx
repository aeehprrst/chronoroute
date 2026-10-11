import { useEffect, useId, useState } from 'react';
import {
  chartModel,
  companionText,
  FILTER_KEYS,
  formatCell,
  formatValue,
  selectRows,
  verifySummaryBytes,
  type ExplorerProps,
  type Row,
  type Selection,
} from '../../lib/experiments/data';

type Load =
  | { state: 'complete'; rows: Row[]; fetched: boolean }
  | { state: 'partial'; rows: Row[] }
  | { state: 'error'; rows: Row[]; message: string };

/**
 * Static first render remains usable without scripting: the build passes only the rows of the
 * initial selection. With scripting, the same summary.csv offered for download is fetched, its
 * SHA-256 is checked against the manifest, and only then do other selections unlock.
 */
export default function ResultsExplorer({
  definition,
  rows: initialRows,
  totalRows,
  columns,
  options,
  selection: initialSelection,
  csvHref,
  evidence,
}: ExplorerProps) {
  if (
    !evidence ||
    evidence.dirty !== false ||
    !evidence.runId ||
    !/^[a-f0-9]{40}$/.test(evidence.commit) ||
    !/^[a-f0-9]{64}$/.test(evidence.summarySha) ||
    !/^[a-f0-9]{64}$/.test(evidence.manifestSha)
  )
    throw new Error('A chart requires a verified clean manifest reference');
  const uid = useId();
  const startsComplete = initialRows.length === totalRows;
  const [load, setLoad] = useState<Load>(
    startsComplete
      ? { state: 'complete', rows: initialRows, fetched: false }
      : { state: 'partial', rows: initialRows },
  );
  useEffect(() => {
    if (startsComplete) return;
    let live = true;
    fetch(csvHref)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.arrayBuffer();
      })
      .then((bytes) =>
        verifySummaryBytes(bytes, evidence.summarySha, columns, totalRows),
      )
      .then((rows) => {
        if (live) setLoad({ state: 'complete', rows, fetched: true });
      })
      .catch((error: unknown) => {
        if (live)
          setLoad({
            state: 'error',
            rows: initialRows,
            message: error instanceof Error ? error.message : String(error),
          });
      });
    return () => {
      live = false;
    };
    // Runs once: the props are fixed for the lifetime of the page.
  }, []);
  const ready = load.state === 'complete';
  const rows = load.rows;
  const [selection, setSelection] = useState<Selection>(initialSelection);
  const [metricIndex, setMetricIndex] = useState(0);
  const [page, setPage] = useState(0);
  const [allColumns, setAllColumns] = useState(false);
  const filtered = selectRows(definition, rows, selection);
  const metric = definition.metrics[metricIndex]!;
  const chart = chartModel(filtered, metric);
  const tableColumns = allColumns ? columns : definition.tableColumns;
  const pageSize = 25;
  const shown = filtered.slice(page * pageSize, (page + 1) * pageSize);
  const span =
    chart.maximum - chart.minimum || Math.max(Math.abs(chart.maximum) * 0.1, 1);
  const chartLow = chart.minimum - span * 0.1;
  const chartHigh = chart.maximum + span * 0.1;
  const series = [...new Set(chart.points.map((p) => p.series))];
  const colors = [
    'var(--accent)',
    'var(--deadline)',
    'var(--real)',
    'var(--derived)',
  ];
  return (
    <div className="results-explorer">
      <p className="result-load" aria-live="polite">
        {load.state === 'partial' &&
          `This first view shows the ${initialRows.length} rows of the initial selection, out of ${totalRows}. With scripting, the page loads the same summary.csv offered for download and checks its SHA-256 against the manifest before other selections are enabled.`}
        {load.state === 'complete' &&
          load.fetched &&
          `All ${totalRows} rows loaded; the downloaded summary.csv matches the manifest SHA-256.`}
        {load.state === 'error' &&
          `The full summary could not be verified (${load.message}). Only the initial selection is shown; use Download CSV for every row.`}
      </p>
      <div className="result-controls">
        {FILTER_KEYS.filter((key) => options[key]).map((key) => (
          <label key={key}>
            {
              {
                const: 'Constellation',
                condition: 'Condition',
                mode: 'Insertion mode',
                endpoint: 'Endpoint',
                k: 'Consecutive alarms',
              }[key]
            }
            <select
              value={String(selection[key] ?? '')}
              disabled={!ready}
              onChange={(e) => {
                setSelection({ ...selection, [key]: e.target.value });
                setPage(0);
              }}
            >
              {(key === 'const' || key === 'condition') && (
                <option value="">All</option>
              )}
              {options[key]!.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
        ))}
        <label>
          Chart metric
          <select
            value={metricIndex}
            onChange={(e) => setMetricIndex(Number(e.target.value))}
          >
            {definition.metrics.map((m, i) => (
              <option key={m.key} value={i}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        {definition.id === 'E01' && (
          <label>
            <input
              type="checkbox"
              checked={!!selection.selected}
              disabled={!ready}
              onChange={(e) => {
                setSelection({ ...selection, selected: e.target.checked });
                setPage(0);
              }}
            />{' '}
            Pilot-selected rule only
          </label>
        )}
      </div>
      <figure
        data-manifest-sha256={evidence.manifestSha}
        data-summary-sha256={evidence.summarySha}
      >
        <figcaption id={`${uid}-caption`}>
          {metric.label} ({metric.unit}).{' '}
          {chart.hasIntervals
            ? 'Shaded bands show recorded 95% confidence intervals over runs, not packets.'
            : 'Exact checks or accounting: sampling confidence intervals do not apply.'}
          {metric.note && ` ${metric.note}`}
        </figcaption>
        <div className="result-chart-scroll">
          <svg
            role="img"
            aria-labelledby={`${uid}-caption ${uid}-description`}
            viewBox="0 0 900 440"
            width="900"
            height="440"
          >
            <desc id={`${uid}-description`}>
              Values and confidence bounds from the verified summary CSV. Exact
              values are available in the data table. Infinite and undefined
              values are listed below.
            </desc>
            <line x1="65" y1="30" x2="65" y2="270" stroke="currentColor" />
            <line x1="65" y1="270" x2="840" y2="270" stroke="currentColor" />
            {chart.ticks.map((tick) => (
              <g key={tick.value}>
                <line
                  x1="60"
                  x2="65"
                  y1={tick.y}
                  y2={tick.y}
                  stroke="currentColor"
                />
                <text x="4" y={tick.y + 4} fill="currentColor" fontSize="12">
                  {tick.value.toPrecision(5)}
                </text>
              </g>
            ))}
            {chart.bounds.map((b) => (
              <line
                key={b}
                x1="65"
                x2="840"
                y1={260 - ((b - chartLow) / (chartHigh - chartLow)) * 220}
                y2={260 - ((b - chartLow) / (chartHigh - chartLow)) * 220}
                stroke="currentColor"
                strokeDasharray="5 5"
              >
                <title>{`Registered equivalence bound: ${b}`}</title>
              </line>
            ))}
            {definition.id === 'E02' &&
              series.map((s, i) => (
                <polyline
                  key={s}
                  points={chart.points
                    .filter((p) => p.series === s)
                    .map((p) => `${p.x},${p.y}`)
                    .join(' ')}
                  fill="none"
                  stroke={colors[i % colors.length]}
                  strokeWidth="2"
                />
              ))}
            {chart.points.map((p, i) => {
              const companions = companionText(metric, p.row);
              return (
                <g key={i}>
                  <title>
                    {`${p.label}: ${p.value}; ${
                      chart.hasIntervals
                        ? `95% CI [${p.lo}, ${p.hi}]`
                        : 'exact accounting'
                    }${companions ? `; ${companions}` : ''}`}
                  </title>
                  {chart.hasIntervals && (
                    <rect
                      x={p.x - 7}
                      y={p.highY}
                      width="14"
                      height={Math.max(p.lowY - p.highY, 1)}
                      fill="var(--accent)"
                      opacity="0.3"
                    />
                  )}
                  <circle
                    cx={p.x}
                    cy={p.y}
                    r="4"
                    fill={colors[series.indexOf(p.series) % colors.length]}
                  />
                  {definition.id !== 'E02' && (
                    <text
                      x={p.x}
                      y="285"
                      transform={`rotate(55 ${p.x} 285)`}
                      fill="currentColor"
                      fontSize="10"
                    >
                      {p.row['scheme'] ?? p.label}
                    </text>
                  )}
                </g>
              );
            })}
            {definition.id === 'E02' &&
              [...new Set(filtered.map((r) => r['entries']))]
                .filter((_, i) => i % 5 === 0)
                .map((entry) => {
                  const p = chart.points.find(
                    (p) => p.row['entries'] === entry,
                  );
                  return (
                    p && (
                      <text
                        key={entry}
                        x={p.x}
                        y="290"
                        fill="currentColor"
                        fontSize="12"
                      >
                        {entry}
                      </text>
                    )
                  );
                })}
            {definition.id === 'E02' &&
              series.map((s, i) => (
                <text
                  key={s}
                  x="80"
                  y={330 + i * 22}
                  fill={colors[i % colors.length]}
                  fontSize="13"
                >
                  {s}
                </text>
              ))}
          </svg>
        </div>
        {metric.companions && chart.points.length > 0 && (
          <ul className="result-companions">
            {chart.points.map((p, i) => (
              <li key={i}>
                {p.label}: {formatValue(p.row[metric.key])} {metric.unit};{' '}
                {companionText(metric, p.row)}
              </li>
            ))}
          </ul>
        )}
        {definition.id === 'E16' && (
          <p>
            Dashed lines are the registered equivalence margins. The table also
            contains the TOST equivalence intervals and both one-sided p-values;
            the verdict uses the recorded TOST decision. A stored p-value of 0
            is shown as below numerical resolution: here it comes from the
            zero-variance branch, because every paired difference is exactly 0.
          </p>
        )}
        {!chart.points.length && (
          <p>No finite eligible estimates to plot for this selection.</p>
        )}
        {chart.omitted.length > 0 && (
          <details open>
            <summary>
              Infinite or undefined results; retained, not replaced
            </summary>
            <ul>
              {chart.omitted.map((r, i) => {
                const companions = companionText(metric, r.row);
                return (
                  <li key={i}>
                    {r.label}: {r.reason}
                    {companions && `; ${companions}`}
                  </li>
                );
              })}
            </ul>
          </details>
        )}
      </figure>
      <h3>Data table</h3>
      <div className="result-controls">
        <label>
          Search this selection
          <input
            type="search"
            value={selection.search ?? ''}
            onChange={(e) => {
              setSelection({ ...selection, search: e.target.value });
              setPage(0);
            }}
          />
        </label>
        <label>
          <input
            type="checkbox"
            checked={allColumns}
            onChange={(e) => setAllColumns(e.target.checked)}
          />{' '}
          Show all CSV columns
        </label>
        <button
          type="button"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
        >
          Previous rows
        </button>
        <button
          type="button"
          disabled={(page + 1) * pageSize >= filtered.length}
          onClick={() => setPage(page + 1)}
        >
          Next rows
        </button>
      </div>
      <p aria-live="polite">
        Showing {shown.length ? page * pageSize + 1 : 0}–
        {Math.min((page + 1) * pageSize, filtered.length)} of {filtered.length}{' '}
        matching rows. The download contains every original row and column.
      </p>
      <div
        className="table-wrap"
        tabIndex={0}
        role="region"
        aria-label="Scrollable results table"
      >
        <table>
          <caption>
            Values from summary.csv. Empty fields are shown as undefined;
            infinite effective latency remains infinite; a p-value stored as 0
            is shown as below numerical resolution.
          </caption>
          <thead>
            <tr>
              {tableColumns.map((c) => (
                <th key={c} scope="col">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i}>
                {tableColumns.map((c) => (
                  <td key={c}>{formatCell(r, c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <noscript>
        <p>
          The initial chart and table are available without scripting. Use
          Download CSV for the full dataset; enable scripting to change
          selections and browse table rows.
        </p>
      </noscript>
    </div>
  );
}

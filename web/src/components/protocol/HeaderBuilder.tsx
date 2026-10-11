/**
 * Header builder: SIDs + per-hop delays (ms) + slack S + unit + ingress time -> a T-CRH,
 * built by the engine with exact arithmetic. Shows the bytes, the deadlines and how each
 * delta was chosen (spec section 5.1). Can hand the header to the decoder and the stepper.
 */
import { useId, useMemo, useState } from 'react';
import { MAX_HOPS } from '../../engine/tcrh';
import { UNIT_CODES, type UnitCode } from '../../engine/timebase';
import { tcrhSize } from '../../engine/sizes';
import ByteMap from './ByteMap';
import { BUILDER_EXAMPLES, computeBuild, nsRatioToMs, type BuilderInput, type BuilderRow } from './builder-logic';
import { NEXT_HEADER_NAMES, flagNames, hex2, unitLabel } from './byte-fields';
import { gpsNsToUtcIso, utcMsToGpsNs } from '../../engine/timebase';
import './protocol.css';

interface Props {
  /** Golden encode vectors (name + hex), to say when the built header equals one. */
  vectors: ReadonlyArray<{ name: string; hex: string }>;
}

interface Row extends BuilderRow {
  key: number;
}

let nextKey = 1;
const withKeys = (rows: readonly BuilderRow[]): Row[] => rows.map((r) => ({ ...r, key: nextKey++ }));

const FIRST = BUILDER_EXAMPLES[0];

export function sendToTool(event: 'tcrh:decode' | 'tcrh:step', hex: string, targetId: string): void {
  window.dispatchEvent(new CustomEvent(event, { detail: { hex } }));
  const target = document.getElementById(targetId);
  if (target) {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    target.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    target.focus({ preventScroll: true });
  }
}

export default function HeaderBuilder({ vectors }: Props) {
  const id = useId();
  const [rows, setRows] = useState<Row[]>(() => withKeys(FIRST ? FIRST.input.rows : [{ sid: '1', delayMs: '1' }]));
  const [slack, setSlack] = useState(FIRST?.input.slack ?? '1.3');
  const [unitCode, setUnitCode] = useState<UnitCode>(FIRST?.input.unitCode ?? 1);
  const [ingress, setIngress] = useState(FIRST?.input.ingress ?? '2026-10-10T13:58:00Z');
  const [nextHeader, setNextHeader] = useState(FIRST?.input.nextHeader ?? 17);
  const [copied, setCopied] = useState(false);

  const result = useMemo(
    () => computeBuild({ rows, slack, unitCode, ingress, nextHeader }),
    [rows, slack, unitCode, ingress, nextHeader],
  );
  const match = result.ok ? vectors.find((v) => v.hex === result.hex) : undefined;

  const load = (example: BuilderInput) => {
    setRows(withKeys(example.rows));
    setSlack(example.slack);
    setUnitCode(example.unitCode);
    setIngress(example.ingress);
    setNextHeader(example.nextHeader);
  };

  const update = (key: number, patch: Partial<BuilderRow>) =>
    setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)));

  const copy = async (hex: string) => {
    try {
      await navigator.clipboard.writeText(hex);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const groupedHex = result.ok ? (result.hex.match(/.{1,16}/g) ?? []).map((w) => w.match(/../g)?.join(' ') ?? '').join('\n') : '';

  return (
    <div className="pr-tool">
      <div className="pr-cols">
        {/* ---------------- inputs ---------------- */}
        <div className="stack">
          <div>
            <p className="pr-h">Examples</p>
            <div className="pr-btns">
              {BUILDER_EXAMPLES.map((ex) => (
                <button key={ex.id} type="button" className="pr-btn pr-btn--quiet" onClick={() => load(ex.input)}>
                  {ex.label}
                </button>
              ))}
            </div>
            <p className="pr-small pr-muted" style={{ marginTop: 'var(--space-2)' }}>
              Each example is the input of a golden test vector. The SIDs and delays are test values, not a real
              Starlink route.
            </p>
          </div>

          <div>
            <p className="pr-h" id={`${id}-path`}>
              Path ({rows.length} {rows.length === 1 ? 'hop' : 'hops'}, first hop first)
            </p>
            <div className="pr-path__head" aria-hidden="true">
              <span>k</span>
              <span>SID</span>
              <span>Delay (ms)</span>
              <span />
            </div>
            <ol className="pr-path pr-path__list" aria-labelledby={`${id}-path`}>
              {rows.map((row, i) => (
                <li key={row.key} className="pr-path__row">
                  <span className="pr-path__k" aria-hidden="true">
                    {i + 1}
                  </span>
                  <input
                    className="pr-input"
                    value={row.sid}
                    inputMode="text"
                    spellCheck={false}
                    autoComplete="off"
                    aria-label={`Hop ${i + 1} SID${i === rows.length - 1 ? ' (final endpoint)' : ''}`}
                    onChange={(e) => update(row.key, { sid: e.target.value })}
                  />
                  <input
                    className="pr-input"
                    value={row.delayMs}
                    inputMode="decimal"
                    spellCheck={false}
                    autoComplete="off"
                    aria-label={`Hop ${i + 1} predicted delay in milliseconds`}
                    onChange={(e) => update(row.key, { delayMs: e.target.value })}
                  />
                  <button
                    type="button"
                    className="pr-btn pr-btn--quiet pr-btn--icon"
                    aria-label={`Remove hop ${i + 1}`}
                    disabled={rows.length <= 1}
                    onClick={() => setRows((rs) => rs.filter((r) => r.key !== row.key))}
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                </li>
              ))}
            </ol>
            <div className="pr-btns" style={{ marginTop: 'var(--space-3)' }}>
              <button
                type="button"
                className="pr-btn"
                disabled={rows.length >= MAX_HOPS}
                onClick={() => setRows((rs) => [...rs, ...withKeys([{ sid: String(rs.length + 1), delayMs: '3' }])])}
              >
                Add hop
              </button>
            </div>
            <p className="pr-small pr-muted" style={{ marginTop: 'var(--space-2)' }}>
              SIDs are 0 to 65534 in decimal or hex (0xF000 + g is ground station g). The last hop is the final
              endpoint.
            </p>
          </div>

          <div className="pr-row">
            <label className="pr-field">
              <span>Slack S (B_k = S × sum of delays)</span>
              <input
                className="pr-input"
                value={slack}
                inputMode="decimal"
                spellCheck={false}
                autoComplete="off"
                onChange={(e) => setSlack(e.target.value)}
              />
            </label>
            <label className="pr-field">
              <span>Deadline unit u</span>
              <select className="pr-select" value={unitCode} onChange={(e) => setUnitCode(Number(e.target.value) as UnitCode)}>
                {UNIT_CODES.map((uc) => (
                  <option key={uc} value={uc}>
                    {`code ${uc}: ${unitLabel(uc)}${uc === 1 ? ' (provisional default)' : ''}`}
                  </option>
                ))}
              </select>
            </label>
            <label className="pr-field">
              <span>Next Header</span>
              <select className="pr-select" value={nextHeader} onChange={(e) => setNextHeader(Number(e.target.value))}>
                {Object.entries(NEXT_HEADER_NAMES).map(([value, name]) => (
                  <option key={value} value={value}>
                    {`${value} ${name}`}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="pr-row">
            <label className="pr-field" style={{ flexBasis: '16rem' }}>
              <span>Ingress time: UTC (ISO 8601) or GPS nanoseconds</span>
              <input
                className="pr-input"
                value={ingress}
                spellCheck={false}
                autoComplete="off"
                onChange={(e) => setIngress(e.target.value)}
              />
            </label>
            <button
              type="button"
              className="pr-btn"
              onClick={() => setIngress(gpsNsToUtcIso(utcMsToGpsNs(Date.now())).replace(/\.(\d{3})\d{6}Z$/, '.$1Z'))}
            >
              Use this device's clock
            </button>
          </div>
        </div>

        {/* ---------------- output ---------------- */}
        <div className="stack">
          <div
            className={`pr-status ${result.ok ? 'pr-status--ok' : 'pr-status--bad'}`}
            role="status"
            aria-live="polite"
          >
            <span className="pr-status__mark">{result.ok ? 'VALID' : 'FIX'}</span>
            {result.ok ? (
              <span>
                A {tcrhSize(result.header.numHops)}-byte T-CRH with {result.header.numHops}{' '}
                {result.header.numHops === 1 ? 'hop' : 'hops'}
                {result.sat ? '. SAT is set: at least one delta was clamped to 255.' : '.'}
                {match ? (
                  <>
                    {' '}
                    Byte-identical to golden vector <code>{match.name}</code>.
                  </>
                ) : null}
              </span>
            ) : (
              <ul className="pr-errors">
                {result.errors.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            )}
          </div>

          {result.ok && (
            <>
              <ByteMap hex={result.hex} caption="The header the engine built. Hover or focus a byte." />

              <div>
                <p className="pr-h">Hex</p>
                <pre className="pr-hex">
                  {groupedHex}
                </pre>
                <div className="pr-btns" style={{ marginTop: 'var(--space-2)' }}>
                  <button type="button" className="pr-btn" onClick={() => void copy(result.hex)}>
                    {copied ? 'Copied' : 'Copy hex'}
                  </button>
                  <button type="button" className="pr-btn" onClick={() => sendToTool('tcrh:decode', result.hex, 'decode-tool')}>
                    Open in the decoder
                  </button>
                  <button type="button" className="pr-btn" onClick={() => sendToTool('tcrh:step', result.hex, 'step-tool')}>
                    Follow this packet
                  </button>
                </div>
              </div>

              <dl className="pr-kv">
                <div>
                  <dt>Epoch_Base</dt>
                  <dd className="pr-deadline">{result.epochBase}</dd>
                </div>
                <div>
                  <dt>Ingress (GPS ns)</dt>
                  <dd>{result.tIngressGpsNs.toString()}</dd>
                </div>
                <div>
                  <dt>Flags</dt>
                  <dd>
                    0x{hex2(result.header.flags)} {flagNames(result.header.flags).join(' ') || '(no state flags)'}
                  </dd>
                </div>
                <div>
                  <dt>Hdr Ext Len</dt>
                  <dd>{tcrhSize(result.header.numHops) / 8 - 1}</dd>
                </div>
              </dl>

              <div className="pr-table-wrap" role="region" aria-label="Deadline table" tabIndex={0}>
                <table>
                  <caption>
                    How each delta is chosen (spec 5.1): target = ceil(B_k / u), d_k = target − (sum of earlier
                    deltas), clamped to 255. Unit u = {unitLabel(unitCode)}.
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">k</th>
                      <th scope="col">SID</th>
                      <th scope="col" className="pr-r">
                        B_k (ms)
                      </th>
                      <th scope="col" className="pr-r">
                        ceil(B_k/u)
                      </th>
                      <th scope="col" className="pr-r">
                        d_k
                      </th>
                      <th scope="col" className="pr-r">
                        D_k
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.hops.map((hop) => (
                      <tr key={hop.k}>
                        <td className="pr-r">{hop.k}</td>
                        <td className="pr-r">{hop.sid}</td>
                        <td className="pr-r">{nsRatioToMs(hop.budgetNs)}</td>
                        <td className="pr-r">{hop.target.toString()}</td>
                        <td className="pr-r">
                          {hop.delta}
                          {hop.clamped ? ' (SAT)' : ''}
                        </td>
                        <td className="pr-r pr-deadline">{hop.deadline}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="pr-small pr-muted">
                D_k = Epoch_Base + d_1 + … + d_k, modulo 2<span className="sr-inline"> to the power </span><sup>32</sup>, in units of {unitLabel(unitCode)}.
                {result.ingressUtc ? ` Ingress time ${result.ingressUtc} (UTC); GPS time = UTC + 18 s.` : ''}
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Packet stepper: follows one packet hop by hop through spec section 6. Every step calls
 * the engine (ingressSend, processAtNode, linkDownFallback); the reader picks the header,
 * the deviation policy and example arrival times (or a down link).
 */
import { useEffect, useId, useMemo, useState } from 'react';
import { decode, hexToBytes, POLICIES, type Policy, type TcrhHeader } from '../../engine/tcrh';
import { UNIT_NS } from '../../engine/timebase';
import ByteMap from './ByteMap';
import { flagNames, hex2, unitLabel } from './byte-fields';
import { buildTrace, defaultDelays, middleHop, type Scenario, type TraceStep } from './stepper-logic';
import './protocol.css';

interface Preset {
  label: string;
  hex: string;
}

interface Props {
  presets: readonly Preset[];
}

const POLICY_TEXT: Record<Policy, string> = {
  greedy: 'greedy: switch to geographic forwarding',
  continue: 'continue: keep the SID list, record the miss',
  drop: 'drop: discard late packets',
};

const SCENARIO_TEXT: Record<Scenario, string> = {
  'on-time': 'Every hop on time',
  slow: 'Link into the middle hop is up but slow',
  down: 'Link into the middle hop is down',
};

function tryDecode(hex: string): TcrhHeader | null {
  try {
    return decode(hexToBytes(hex));
  } catch {
    return null;
  }
}

function verdict(step: TraceStep): { text: string; tone: 'ok' | 'late' | 'drop' | 'down' | 'info' } {
  if (step.kind === 'ingress') return { text: 'sent', tone: 'info' };
  if (step.kind === 'transit') return { text: 'fallback', tone: 'info' };
  if (step.kind === 'linkdown') return { text: 'link down', tone: 'down' };
  if (step.action === 'drop_late') return { text: step.late ? 'late · dropped' : 'dropped', tone: 'drop' };
  if (step.late) return { text: step.action === 'deliver' ? 'late · delivered' : 'late', tone: 'late' };
  if (!step.checked) return { text: step.action === 'deliver' ? 'delivered' : 'no check', tone: 'info' };
  return { text: step.action === 'deliver' ? 'on time · delivered' : 'on time', tone: 'ok' };
}

export default function ProcessStepper({ presets }: Props) {
  const id = useId();
  const [extra, setExtra] = useState<Preset | null>(null);
  const options = useMemo(() => (extra ? [...presets, extra] : [...presets]), [presets, extra]);
  const [hex, setHex] = useState(presets[0]?.hex ?? '');
  const header = useMemo(() => tryDecode(hex), [hex]);
  const [policy, setPolicy] = useState<Policy>('greedy');
  const [scenario, setScenario] = useState<Scenario>('slow');
  const [delays, setDelays] = useState<string[]>(() => (header ? defaultDelays(header, 'slow').map(String) : []));
  const [downInto, setDownInto] = useState<number | null>(null);
  const [step, setStep] = useState(0);

  const applyScenario = (h: TcrhHeader | null, s: Scenario) => {
    setScenario(s);
    setDelays(h ? defaultDelays(h, s).map(String) : []);
    setDownInto(h && s === 'down' ? middleHop(h) : null);
    setStep(0);
  };

  const chooseHeader = (newHex: string) => {
    setHex(newHex);
    applyScenario(tryDecode(newHex), scenario);
  };

  useEffect(() => {
    const onStep = (event: Event) => {
      const sent = (event as CustomEvent<{ hex?: unknown }>).detail?.hex;
      if (typeof sent !== 'string') return;
      setExtra({ label: 'The header from the builder', hex: sent });
      setHex(sent);
      const h = tryDecode(sent);
      setScenario('slow');
      setDelays(h ? defaultDelays(h, 'slow').map(String) : []);
      setDownInto(null);
      setStep(0);
    };
    window.addEventListener('tcrh:step', onStep);
    return () => window.removeEventListener('tcrh:step', onStep);
  }, []);

  const trace = useMemo(
    () =>
      buildTrace(
        hex,
        delays.map((d) => (/^\d{1,6}$/.test(d.trim()) ? Number(d) : Number.NaN)),
        policy,
        downInto,
      ),
    [hex, delays, policy, downInto],
  );

  const steps = trace.ok ? trace.steps : [];
  const current = Math.min(step, Math.max(0, steps.length - 1));
  const cur = steps[current];
  const unitNs = trace.ok ? UNIT_NS[trace.unitCode] : 0;
  const epoch = trace.ok ? trace.header.epochBase : 0;
  const msAfter = (nowU: number) => {
    const units = (((nowU - epoch) % 2 ** 32) + 2 ** 32) % 2 ** 32;
    return `${units} units = ${((units * unitNs) / 1e6).toLocaleString('en-GB', { maximumFractionDigits: 4 })} ms`;
  };

  return (
    <div className="pr-tool">
      <div className="pr-row">
        <label className="pr-field" style={{ flexBasis: '14rem' }}>
          <span>Header (golden test vectors)</span>
          <select className="pr-select" value={hex} onChange={(e) => chooseHeader(e.target.value)}>
            {options.map((p) => (
              <option key={p.label} value={p.hex}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <label className="pr-field" style={{ flexBasis: '14rem' }}>
          <span>Deviation policy of every node</span>
          <select
            className="pr-select"
            value={policy}
            onChange={(e) => {
              setPolicy(e.target.value as Policy);
              setStep(0);
            }}
          >
            {POLICIES.map((p) => (
              <option key={p} value={p}>
                {POLICY_TEXT[p]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {header && (
        <fieldset className="pr-fieldset">
          <legend>Scenario (example inputs, not measurements)</legend>
          <div className="pr-seg" role="radiogroup" aria-label="Scenario">
            {(Object.keys(SCENARIO_TEXT) as Scenario[]).map((s) => (
              <label key={s}>
                <input
                  type="radio"
                  name={`${id}-scenario`}
                  value={s}
                  checked={scenario === s}
                  onChange={() => applyScenario(header, s)}
                />
                {SCENARIO_TEXT[s]}
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {header && (
        <details>
          <summary className="pr-small">
            Arrival times: actual delay of each hop, in units of {unitLabel((header.flags >> 4) & 3)} (edit to try your
            own)
          </summary>
          <div className="pr-delays" style={{ marginTop: 'var(--space-3)' }}>
            {delays.map((d, i) => (
              <label key={i} className="pr-field">
                <span>
                  Hop {i + 1} (budget {header.deltasRev[header.numHops - 1 - i]})
                </span>
                <input
                  className="pr-input"
                  value={d}
                  inputMode="numeric"
                  aria-invalid={!/^\d{1,6}$/.test(d.trim())}
                  onChange={(e) => {
                    const next = [...delays];
                    next[i] = e.target.value;
                    setDelays(next);
                    setStep(0);
                  }}
                />
              </label>
            ))}
          </div>
          <label className="pr-field" style={{ marginTop: 'var(--space-3)', maxWidth: '20rem' }}>
            <span>Down link (spec section 6 step 7)</span>
            <select
              className="pr-select"
              value={downInto ?? ''}
              onChange={(e) => {
                setDownInto(e.target.value === '' ? null : Number(e.target.value));
                setStep(0);
              }}
            >
              <option value="">No link down</option>
              {Array.from({ length: header.numHops }, (_, i) => (
                <option key={i} value={i + 1}>
                  {i === 0 ? 'Ingress → hop 1' : `Hop ${i} → hop ${i + 1}`}
                </option>
              ))}
            </select>
          </label>
        </details>
      )}

      {!trace.ok && (
        <div className="pr-status pr-status--bad" role="status">
          <span className="pr-status__mark">FIX</span>
          <span>{trace.error}</span>
        </div>
      )}

      {trace.ok && cur && (
        <>
          <ol className="pr-route" aria-label="Steps of this packet; choose one to jump to it">
            {steps.map((s, i) => {
              const v = verdict(s);
              const tone = i > current ? 'future' : v.tone === 'info' ? '' : v.tone;
              return (
                <li key={i} className="pr-route__item">
                  {i > 0 && (
                    <span className="pr-arrow" aria-hidden="true">
                      →
                    </span>
                  )}
                  <button
                    type="button"
                    className={`pr-stop ${tone ? `pr-stop--${tone}` : ''} ${i === current ? 'is-current' : ''}`}
                    aria-current={i === current ? 'step' : undefined}
                    onClick={() => setStep(i)}
                  >
                    <span className="pr-stop__name">
                      {s.kind === 'ingress' ? 'Ingress' : s.kind === 'transit' ? 'Fallback' : s.kind === 'linkdown' ? 'Step 7' : `SID ${s.sid}`}
                    </span>
                    <span className="pr-stop__state">{i > current ? 'next' : v.text}</span>
                  </button>
                </li>
              );
            })}
          </ol>

          <div className="pr-btns">
            <button type="button" className="pr-btn" disabled={current === 0} onClick={() => setStep(current - 1)}>
              Previous step
            </button>
            <button
              type="button"
              className="pr-btn pr-btn--primary"
              disabled={current >= steps.length - 1}
              onClick={() => setStep(current + 1)}
            >
              Next step
            </button>
            <button type="button" className="pr-btn pr-btn--quiet" disabled={current === 0} onClick={() => setStep(0)}>
              Back to the ingress
            </button>
            <span className="pr-small pr-muted" style={{ alignSelf: 'center' }}>
              Step {current + 1} of {steps.length}
            </span>
          </div>

          <p className="sr-only" role="status" aria-live="polite">
            {`Step ${current + 1} of ${steps.length}: ${cur.title}. ${verdict(cur).text}. ${cur.notes[0] ?? ''}`}
          </p>
          <section className="pr-step-card" aria-labelledby={`${id}-steptitle`}>
            <div className="pr-step-card__head">
              <h3 className="pr-step-card__title" id={`${id}-steptitle`}>
                {cur.title}
              </h3>
              <span className={`pr-verdict pr-verdict--${verdict(cur).tone}`}>{verdict(cur).text}</span>
            </div>
            <ul className="pr-notes">
              {cur.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
            <dl className="pr-kv">
              <div>
                <dt>Segments Left</dt>
                <dd>
                  {cur.slIn} → {cur.slOut ?? '—'}
                </dd>
              </div>
              {cur.hopIndex !== null && cur.kind !== 'transit' && (
                <div>
                  <dt>Hop index k</dt>
                  <dd>{cur.hopIndex}</dd>
                </div>
              )}
              {cur.deadlineU !== null && (
                <div>
                  <dt>Deadline D_k</dt>
                  <dd className="pr-deadline">
                    {cur.deadlineU}
                    <br />
                    <span className="pr-muted">Epoch_Base + {msAfter(cur.deadlineU)}</span>
                  </dd>
                </div>
              )}
              <div>
                <dt>Arrival clock now_u</dt>
                <dd>
                  {cur.nowU !== null ? (
                    <>
                      {cur.nowU}
                      <br />
                      <span className="pr-muted">Epoch_Base + {msAfter(cur.nowU)}</span>
                    </>
                  ) : (
                    <span className="pr-muted">{cur.kind === 'ingress' ? 'not checked at the ingress' : 'not modelled'}</span>
                  )}
                </dd>
              </div>
              {cur.diff !== null && (
                <div>
                  <dt>serial_diff(now_u, D_k)</dt>
                  <dd className={cur.diff > 0 ? 'pr-deadline' : ''}>
                    {cur.diff > 0 ? `+${cur.diff}` : cur.diff} {cur.diff > 0 ? '(late)' : '(on time)'}
                  </dd>
                </div>
              )}
              <div>
                <dt>Action</dt>
                <dd>{cur.action}</dd>
              </div>
              {cur.nextSid !== null && (
                <div>
                  <dt>Next SID</dt>
                  <dd>{cur.nextSid}</dd>
                </div>
              )}
              {cur.flagsOut !== null && (
                <div>
                  <dt>Flags after</dt>
                  <dd>
                    0x{hex2(cur.flagsOut)} {flagNames(cur.flagsOut).join(' ')}
                  </dd>
                </div>
              )}
              {cur.devHopOut !== null && (
                <div>
                  <dt>Dev Hop after</dt>
                  <dd>{cur.devHopOut}</dd>
                </div>
              )}
            </dl>
            <ByteMap
              hex={Array.from(cur.bytesOut ?? cur.bytesIn, (b) => hex2(b)).join('')}
              caption={
                cur.bytesOut
                  ? cur.changed.length > 0
                    ? `Bytes as they leave this step. Changed: ${cur.changed.map((i) => `byte ${i}`).join(', ')}.`
                    : 'Bytes as they leave this step (unchanged).'
                  : 'The packet is discarded; these are the bytes that arrived.'
              }
              changed={cur.changed}
            />
          </section>

          <div className="pr-table-wrap" role="region" aria-label="All steps" tabIndex={0}>
            <table>
              <caption>Every step of this packet (the engine's output for the inputs above)</caption>
              <thead>
                <tr>
                  <th scope="col">Step</th>
                  <th scope="col" className="pr-r">
                    now_u
                  </th>
                  <th scope="col" className="pr-r">
                    D_k
                  </th>
                  <th scope="col">Result</th>
                  <th scope="col">Action</th>
                  <th scope="col" className="pr-r">
                    SL after
                  </th>
                  <th scope="col">Flags after</th>
                  <th scope="col" className="pr-r">
                    Dev Hop
                  </th>
                </tr>
              </thead>
              <tbody>
                {steps.map((s, i) => (
                  <tr key={i} className={i === current ? 'is-current' : ''}>
                    <th scope="row">{s.title}</th>
                    <td className="pr-r">{s.nowU ?? '—'}</td>
                    <td className="pr-r pr-deadline">{s.deadlineU ?? '—'}</td>
                    <td>{verdict(s).text}</td>
                    <td className="pr-mono">{s.action}</td>
                    <td className="pr-r">{s.slOut ?? '—'}</td>
                    <td className="pr-mono">{s.flagsOut !== null ? flagNames(s.flagsOut).join(' ') || 'none' : '—'}</td>
                    <td className="pr-r">{s.devHopOut ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

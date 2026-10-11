/**
 * The route planner (/route): pick two cities and an instant within 6 hours of the orbit
 * snapshot; the browser computes the path and its T-CRH, with the same rules and the same
 * integer arithmetic as the Python reference (checked by tests/route-parity.test.ts).
 *
 * Pipeline per request:
 *   orbit worker (SGP4, satellite.js, Float64 TEME km for the shell's satellites)
 *   -> ECEF by GMST (lib/route/frame.ts)
 *   -> laser links up/down + ground links at that instant (lib/route/topology.ts)
 *   -> Dijkstra, lowest-node-id tie-break (lib/route/dijkstra.ts)
 *   -> budgets with slack S, T-CRH via the existing engine, IPv6 + UDP packet, pcap
 *      (lib/route/planner.ts, engine/tcrh.ts, engine/packet.ts)
 *
 * Nothing here is typed in by hand: every number shown comes from that computation or from
 * the published data files.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { FromWorker, ToWorker } from '../../lib/orbit/worker-protocol';
import type { InitError } from '../../lib/orbit/propagate';
import { loadRouteData, type RouteData } from '../../lib/route/load';
import { buildRouteContext, flowStations, type RouteContext } from '../../lib/route/context';
import { ecefFrameFromTeme } from '../../lib/route/frame';
import { planRoute, DEFAULT_SLACK, type RoutePlan } from '../../lib/route/planner';
import { bytesToHex } from '../../engine/tcrh';
import { formatRatio, ratio, unitNsBig, UNIT_NS, type UnitCode } from '../../engine/timebase';
import { badgeConclusion, describeRun } from '../../lib/route/parity-summary';
import { LABEL_TABLE, labelKind, type LabelKey } from '../../lib/label-keys';
import type { DataLabel } from '../../lib/data-types';
import { formatAge, formatInt } from '../../lib/format';
import { REPO_URL } from '../../lib/site';
import ByteMap from '../protocol/ByteMap';
import './route.css';

/** The planner accepts instants within this much of the snapshot's reference time. */
const WINDOW_MIN = 360;
const MINUTE_MS = 60_000;
/** Data older than this is flagged as stale (the refresh workflow runs every 4 hours). */
const STALE_MS = 24 * 3_600_000;

type Phase =
  | { kind: 'loading'; message: string }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; data: RouteData; ctx: RouteContext; initErrors: InitError[] };

// ------------------------------------------------------------------ small pieces

function Chip({ kind, note }: { kind: DataLabel; note?: string }) {
  const name = kind.toUpperCase();
  return (
    <span className={`rp-chip rp-chip--${kind}`}>
      <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true" focusable="false" className="rp-chip__mark">
        {kind === 'real' && <circle cx="5" cy="5" r="4" fill="currentColor" />}
        {kind === 'derived' && <path d="M5 0.6 9.4 5 5 9.4 0.6 5Z" fill="currentColor" />}
        {kind === 'modelled' && <rect x="1.25" y="1.25" width="7.5" height="7.5" fill="none" stroke="currentColor" strokeWidth="1.5" />}
        {kind === 'unknown' && <circle cx="5" cy="5" r="3.6" fill="none" stroke="currentColor" strokeWidth="1.4" strokeDasharray="2 1.6" />}
      </svg>
      <span className="rp-chip__name">
        <span className="sr-only">Label: </span>
        {name}
      </span>
      {note ? <span className="rp-chip__note">{note}</span> : null}
    </span>
  );
}

function KeyChip({ k, note }: { k: LabelKey; note?: string }) {
  return <Chip kind={labelKind(k)} {...(note ? { note } : {})} />;
}

const ms3 = (ns: number) => (ns / 1e6).toFixed(3);
const sidHex = (sid: number) => `0x${sid.toString(16).toUpperCase().padStart(4, '0')}`;
const utcText = (ms: number) => `${new Date(ms).toISOString().slice(0, 19).replace('T', ' ')} UTC`;
const nsRatioMs = (r: { num: bigint; den: bigint }) => formatRatio(ratio(r.num, r.den * 1_000_000n), 6);
/**
 * A whole number of deadline units, given in ns, as ms with exactly as many decimals as the unit
 * needs (1 ms: 0, 0.1 ms: 1, 0.25 ms: 2, 0.125 ms: 3), so the value is exact, never rounded,
 * and every row of a column has the same number of decimals.
 */
const UNIT_DECIMALS: Readonly<Record<UnitCode, number>> = { 0: 0, 1: 1, 2: 2, 3: 3 };
function unitsMs(ns: bigint, unitCode: UnitCode): string {
  const digits = UNIT_DECIMALS[unitCode];
  const whole = ns / 1_000_000n;
  const frac = (ns % 1_000_000n).toString().padStart(6, '0');
  if (frac.slice(digits) !== '0'.repeat(6 - digits)) throw new RangeError(`${ns} ns is not a whole number of units`);
  return digits > 0 ? `${whole}.${frac.slice(0, digits)}` : `${whole}`;
}

function signedMinutes(min: number): string {
  if (min === 0) return 'at the snapshot time';
  const sign = min > 0 ? '+' : '−';
  const a = Math.abs(min);
  const h = Math.floor(a / 60);
  const m = a % 60;
  return `${sign}${h > 0 ? `${h} h ` : ''}${m} min from the snapshot time`;
}

// ------------------------------------------------------------------ the island

export default function RoutePlanner() {
  const [phase, setPhase] = useState<Phase>({ kind: 'loading', message: 'Loading the orbit snapshot and the laser-link model…' });
  const workerRef = useRef<Worker | null>(null);
  const requestRef = useRef(0);
  const [src, setSrc] = useState('Chennai');
  const [dst, setDst] = useState('London');
  const [offsetMin, setOffsetMin] = useState(0);
  const [useNow, setUseNow] = useState(false);
  const [slackText, setSlackText] = useState(DEFAULT_SLACK);
  const [unitCode, setUnitCode] = useState<UnitCode>(1);
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [plan, setPlan] = useState<{ plan: RoutePlan; failed: number; tMs: number } | null>(null);
  const [planError, setPlanError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Load the data and start the worker once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await loadRouteData();
        const ctx = buildRouteContext({
          shells: data.shells,
          isl: data.isl,
          records: data.snapshot.records,
          cities: data.cities,
          registry: data.registry,
        });
        if (cancelled) return;
        setPhase({ kind: 'loading', message: `Initialising SGP4 for ${formatInt(ctx.records.length)} satellites…` });
        const worker = new Worker(new URL('../../workers/orbit.worker.ts', import.meta.url), { type: 'module' });
        workerRef.current = worker;
        const initErrors = await new Promise<InitError[]>((resolve, reject) => {
          worker.onmessage = (event: MessageEvent<FromWorker>) => {
            if (event.data.type === 'ready') resolve(event.data.errors);
            else if (event.data.type === 'init-failed') reject(new Error(event.data.message));
          };
          worker.onerror = (event) => reject(new Error(event.message || 'The orbit worker failed to start.'));
          worker.postMessage({ type: 'init', records: ctx.records } satisfies ToWorker);
        });
        if (cancelled) return;
        // Default instant: now, if it lies within the window; otherwise the snapshot time.
        const refMs = Date.parse(data.snapshot.manifest.fetched_utc);
        if (Math.abs(Date.now() - refMs) <= WINDOW_MIN * MINUTE_MS) setUseNow(true);
        setPhase({ kind: 'ready', data, ctx, initErrors });
      } catch (error) {
        if (!cancelled) setPhase({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
      }
    })();
    return () => {
      cancelled = true;
      workerRef.current?.terminate();
      workerRef.current = null;
    };
  }, []);

  // Keep "now" fresh (once a minute is enough for a planner).
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const refMs = phase.kind === 'ready' ? Date.parse(phase.data.snapshot.manifest.fetched_utc) : 0;
  const nowInWindow = phase.kind === 'ready' && Math.abs(nowMs - refMs) <= WINDOW_MIN * MINUTE_MS;
  const effectiveNow = useNow && nowInWindow;
  // Whole seconds: the planner works with exact integers.
  const tMs = effectiveNow ? Math.floor(nowMs / 1000) * 1000 : refMs + offsetMin * MINUTE_MS;

  // Plan whenever an input changes.
  useEffect(() => {
    if (phase.kind !== 'ready' || !workerRef.current) return;
    if (src === dst) {
      setPlan(null);
      setPlanError('Pick two different cities.');
      return;
    }
    const worker = workerRef.current;
    const ctx = phase.ctx;
    const id = (requestRef.current += 1);
    setBusy(true);
    worker.onmessage = (event: MessageEvent<FromWorker>) => {
      const message = event.data;
      if (message.type !== 'teme64' || message.requestId !== requestRef.current) return;
      try {
        const frame = ecefFrameFromTeme(message.teme, message.simMs);
        const [a, b] = flowStations(ctx, src, dst);
        const result = planRoute(ctx.net, frame, ctx.sats, a, b, BigInt(message.simMs) * 1_000_000n, { slack: slackText, unitCode });
        setPlan({ plan: result, failed: message.failed, tMs: message.simMs });
        setPlanError(null);
      } catch (error) {
        setPlan(null);
        setPlanError(error instanceof Error ? error.message : String(error));
      } finally {
        setBusy(false);
      }
    };
    worker.postMessage({ type: 'teme64', requestId: id, simMs: tMs } satisfies ToWorker);
  }, [phase, src, dst, tMs, slackText, unitCode]);

  if (phase.kind === 'loading') return <p className="rp-status">{phase.message}</p>;
  if (phase.kind === 'error') {
    return (
      <div className="rp-status rp-status--error" role="alert">
        <p>
          <strong>The route planner could not start.</strong> {phase.message}
        </p>
        <p className="muted">
          It needs the Python pipeline's files in this site's data folder (shells.json and isl_grid4.json next to the
          orbit snapshot, and the city list and SID registry under data/static/). A development snapshot made with
          dev-data.mjs does not have them.
        </p>
      </div>
    );
  }

  const { data, ctx, initErrors } = phase;
  const m = data.snapshot.manifest;
  return (
    <div className="rp">
      <form className="rp-controls" onSubmit={(e) => e.preventDefault()} aria-label="Route planner inputs">
        <div className="rp-field">
          <label htmlFor="rp-src">From</label>
          <select id="rp-src" value={src} onChange={(e) => setSrc(e.currentTarget.value)}>
            {ctx.cities.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} ({c.country})
              </option>
            ))}
          </select>
        </div>
        <button
          type="button"
          className="button rp-swap"
          onClick={() => {
            setSrc(dst);
            setDst(src);
          }}
          aria-label="Swap the two cities"
        >
          ⇄
        </button>
        <div className="rp-field">
          <label htmlFor="rp-dst">To</label>
          <select id="rp-dst" value={dst} onChange={(e) => setDst(e.currentTarget.value)}>
            {ctx.cities.map((c) => (
              <option key={c.name} value={c.name}>
                {c.name} ({c.country})
              </option>
            ))}
          </select>
        </div>

        <fieldset className="rp-time">
          <legend>Time (UTC)</legend>
          <div className="rp-time__buttons">
            <button type="button" className="button" aria-pressed={effectiveNow} disabled={!nowInWindow} onClick={() => setUseNow(true)}>
              Now
            </button>
            <button
              type="button"
              className="button"
              aria-pressed={!effectiveNow && offsetMin === 0}
              onClick={() => {
                setUseNow(false);
                setOffsetMin(0);
              }}
            >
              Snapshot time
            </button>
          </div>
          <label htmlFor="rp-offset" className="rp-time__label">
            Minutes from the snapshot time (−{WINDOW_MIN} to +{WINDOW_MIN})
          </label>
          <input
            id="rp-offset"
            type="range"
            min={-WINDOW_MIN}
            max={WINDOW_MIN}
            step={1}
            value={effectiveNow ? Math.round((tMs - refMs) / MINUTE_MS) : offsetMin}
            onChange={(e) => {
              setUseNow(false);
              setOffsetMin(Number(e.currentTarget.value));
            }}
            aria-valuetext={effectiveNow ? 'now' : signedMinutes(offsetMin)}
          />
          <p className="rp-time__value">
            <time dateTime={new Date(tMs).toISOString()} className="num">
              {utcText(tMs)}
            </time>{' '}
            <span className="muted">({effectiveNow ? 'now' : signedMinutes(offsetMin)})</span>
          </p>
          {!nowInWindow && (
            <p className="rp-note">
              “Now” is {formatAge(refMs, nowMs)} after the snapshot, outside its ±6 h window, so it is not offered. SGP4
              predictions lose accuracy as the elements age.
            </p>
          )}
        </fieldset>

        <details className="rp-advanced">
          <summary>Deadline settings</summary>
          <div className="rp-field">
            <label htmlFor="rp-slack">Slack S (budget = S × predicted delay)</label>
            <input id="rp-slack" inputMode="decimal" value={slackText} onChange={(e) => setSlackText(e.currentTarget.value)} />
          </div>
          <div className="rp-field">
            <label htmlFor="rp-unit">Deadline unit</label>
            <select id="rp-unit" value={unitCode} onChange={(e) => setUnitCode(Number(e.currentTarget.value) as UnitCode)}>
              {([0, 1, 2, 3] as const).map((code) => (
                <option key={code} value={code}>
                  {UNIT_NS[code] / 1e6} ms (unit code {code}){code === 1 ? ', default' : ''}
                </option>
              ))}
            </select>
          </div>
        </details>
      </form>

      <p className="rp-hypothetical">
        <Chip kind="modelled" /> Hypothetical path on MODELLED laser links. Starlink's routing is not public and does not use
        T-CRH.
      </p>

      <div aria-live="polite" aria-busy={busy}>
        {planError && <p className="rp-status rp-status--error">{planError}</p>}
        {plan && <PlanView plan={plan.plan} failed={plan.failed} ctx={ctx} data={data} tMs={plan.tMs} />}
      </div>

      <section className="rp-panel" aria-labelledby="rp-inputs-title">
        <h3 id="rp-inputs-title">What the planner used</h3>
        <ul className="rp-facts" role="list">
          <li>
            <KeyChip k="orbital_elements" /> {m.source} snapshot <span className="mono">{m.snapshot_id}</span>, downloaded{' '}
            {m.fetched_utc} ({formatAge(Date.parse(m.fetched_utc), nowMs)} ago).{' '}
            {nowMs - Date.parse(m.fetched_utc) > STALE_MS ? (
              <strong className="rp-stale">Stale: more than 24 hours old (the 4-hourly refresh has not completed since).</strong>
            ) : null}{' '}
            {m.attribution}
          </li>
          <li>
            <KeyChip k="satellite_positions_sgp4" /> SGP4 (satellite.js, in your browser) for the {formatInt(ctx.net.norads.length)}{' '}
            satellites of the shell, rotated to Earth-fixed coordinates by Greenwich sidereal time.
            {initErrors.length > 0 ? ` ${initErrors.length} element sets could not be initialised and are left out.` : ''}
          </li>
          <li>
            <KeyChip k="shells_and_planes" /> Shell <span className="mono">{ctx.net.shellId}</span>: {formatInt(ctx.net.norads.length)}{' '}
            satellites in {ctx.net.nPlanes} orbital planes inferred by our pipeline ({formatInt(ctx.net.offGrid)} satellites in no
            plane are left out). SpaceX does not publish its planes.
          </li>
          <li>
            <KeyChip k="isl_topology_grid4" /> Grid-4 laser links: {formatInt(ctx.net.islA.length)} pairs chosen by the Python
            pipeline at {ctx.net.referenceUtc}. At the chosen time a pair is down if its line of sight dips below{' '}
            {ctx.net.model.min_grazing_alt_km} km above the ellipsoid, or (cross-plane pairs) if either satellite is beyond ±
            {ctx.net.model.polar_cutoff_deg}° latitude.
          </li>
          <li>
            <KeyChip k="gsl_mask_and_assignment" note="mask ASSUMED, choice MODELLED" /> Ground links: a city sees satellites at
            least 25° above its horizon (the value in Starlink's filings, as used by Hypatia) and connects to the 4 highest.
          </li>
          <li>
            <KeyChip k="processing_delay" /> 0.5 ms processing per hop is added to the light time of every link.
          </li>
          <li>
            <KeyChip k="city_coordinates" /> City coordinates from Natural Earth (public domain).
            {ctx.provisionalSids > 0
              ? ` ${ctx.provisionalSids} satellites are not yet in the committed SID registry and carry provisional SIDs.`
              : ''}
          </li>
          <li>
            <Chip kind="unknown" /> Starlink's real routing is not public; nothing here is taken from it.
          </li>
        </ul>
        <ParityBadge data={data} />
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ result

function ParityBadge({ data }: { data: RouteData }) {
  const p = data.parity;
  if (!p) {
    return <p className="rp-note">No parity summary was published with this build.</p>;
  }
  // The wording comes from lib/route/parity-summary.ts: "identical" only when every path was.
  return (
    <div className="rp-parity">
      <p>
        <strong>Parity with the Python reference</strong> (checked before this deploy; the gate fails on a path cost more
        than 1 ns off or any differing header, packet or pcap byte):
      </p>
      <ul role="list">
        {p.runs.map((run) => (
          <li key={run.role}>{describeRun(run)}</li>
        ))}
      </ul>
      <p>
        {badgeConclusion(p)}
        {p.commit ? (
          <>
            {' '}
            Checked at commit{' '}
            <a href={`${REPO_URL}/commit/${p.commit}`} className="mono">
              {p.commit.slice(0, 7)}
            </a>
            .
          </>
        ) : null}
      </p>
    </div>
  );
}

function PlanView({ plan, failed, ctx, data, tMs }: { plan: RoutePlan; failed: number; ctx: RouteContext; data: RouteData; tMs: number }) {
  const nameOf = (node: number) =>
    node < ctx.net.norads.length ? ctx.sats.names[node]! : node === plan.instant.srcNode ? plan.src.name : plan.dst.name;
  const visible = plan.instant.gsl.map((g) => g.visible.length);
  const diag = (
    <p className="rp-note">
      At {utcText(tMs)}: {formatInt(plan.islUp)} of {formatInt(plan.islTotal)} laser-link pairs up; {plan.src.name} sees{' '}
      {visible[0]} satellites at 25° or more, {plan.dst.name} {visible[1]}.
      {failed > 0 ? ` SGP4 failed for ${failed} satellites at this instant; their links are down.` : ''}
    </p>
  );
  if (!plan.reachable) {
    return (
      <section className="rp-panel" aria-labelledby="rp-result-title">
        <h3 id="rp-result-title">
          No path from {plan.src.name} to {plan.dst.name}
        </h3>
        <p>
          At this instant the model has no route: either a city sees no satellite of the shell at 25° or more (the 53° shell
          does not reach the far north and south), or the laser-link grid is cut between the two.
        </p>
        {diag}
      </section>
    );
  }
  const h = plan.sizes.hops;
  const { unitCode } = plan;
  const unitMs = UNIT_NS[unitCode] / 1e6;
  const rhLen = plan.headerBytes.length;
  const lastHop = plan.hops[plan.hops.length - 1]!;
  const predicted = plan.costNs;
  const fileName = `chronoroute-${plan.src.name}-${plan.dst.name}-${new Date(tMs).toISOString().slice(0, 19).replace(/[:]/g, '')}Z.pcap`
    .replace(/\s+/g, '_')
    .replace(/[^A-Za-z0-9._-]/g, '');
  return (
    <>
      <section className="rp-panel" aria-labelledby="rp-result-title">
        <h3 id="rp-result-title">
          {plan.src.name} → {plan.dst.name}: {h} hops, {h - 1} satellites <KeyChip k="routes_and_budgets" />
        </h3>
        <ol className="rp-path" aria-label="Path">
          {plan.path.map((node, i) => (
            <li key={`${node}-${i}`}>
              {nameOf(node)}
              {node < ctx.net.norads.length ? <span className="muted num"> ({ctx.net.norads[node]})</span> : <span className="muted"> (ground)</span>}
            </li>
          ))}
        </ol>
        {diag}
        <dl className="rp-totals">
          <div>
            <dt>Light time along the path</dt>
            <dd className="num">{ms3(plan.lightTimeNs)} ms</dd>
          </div>
          <div>
            <dt>Predicted delay (incl. {h} × 0.5 ms processing)</dt>
            <dd className="num">{ms3(predicted)} ms</dd>
          </div>
          <div>
            <dt>Great circle {plan.src.name}–{plan.dst.name}</dt>
            <dd className="num">
              {formatInt(Math.round(plan.greatCircleKm))} km → light-speed bound {(plan.boundNs / 1e6).toFixed(3)} ms
            </dd>
          </div>
          <div>
            <dt>Light time ÷ bound, predicted ÷ bound</dt>
            <dd className="num">
              {(plan.lightTimeNs / plan.boundNs).toFixed(3)}, {(predicted / plan.boundNs).toFixed(3)}
            </dd>
          </div>
          <div>
            <dt>
              Final cumulative budget B<sub>{h}</sub> (slack S = {formatRatio(plan.slack, 6)})
            </dt>
            <dd className="num">{nsRatioMs(plan.budgets[plan.budgets.length - 1]!)} ms after ingress</dd>
          </div>
          <div>
            <dt>
              Final deadline in the header, D<sub>{h}</sub> − E (rounded up to whole {unitMs} ms units)
            </dt>
            <dd className="num">
              {(lastHop.deadlineAfterEpochNs / unitNsBig(unitCode)).toString()} units = {unitsMs(lastHop.deadlineAfterEpochNs, unitCode)} ms after Epoch_Base
            </dd>
          </div>
        </dl>
      </section>

      <section className="rp-panel" aria-labelledby="rp-hops-title">
        <h3 id="rp-hops-title">Hop by hop</h3>
        <div className="table-wrap">
          <table className="rp-table">
            <caption>
              Per-hop delays and deadlines. Budget = S × predicted hop delay; cumulative deadline D<sub>k</sub> = Epoch_Base + Δ
              <sub>1</sub> + … + Δ<sub>k</sub> in units of {unitMs} ms (ceil-cumulative encoding, spec section 5.1).
            </caption>
            <thead>
              <tr>
                <th scope="col">k</th>
                <th scope="col">Node</th>
                <th scope="col">NORAD</th>
                <th scope="col">SID</th>
                <th scope="col">Distance (km)</th>
                <th scope="col">Light (ms)</th>
                <th scope="col">Hop (ms)</th>
                <th scope="col">Budget (ms)</th>
                <th scope="col">Cumulative budget (ms)</th>
                <th scope="col">Δ (units)</th>
                <th scope="col">
                  D<sub>k</sub> (units)
                </th>
                <th scope="col">
                  D<sub>k</sub> − E (ms)
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="num">0</td>
                <td>{plan.src.name} (ground, ingress)</td>
                <td />
                <td className="mono">
                  {sidHex(plan.src.sid)}
                  {plan.src.provisional ? ' *' : ''}
                </td>
                <td colSpan={8} className="muted">
                  Epoch_Base E = {plan.epochBase} (packet enters at {utcText(tMs)})
                </td>
              </tr>
              {plan.hops.map((hop) => (
                <tr key={hop.k}>
                  <td className="num">{hop.k}</td>
                  <td>{hop.kind === 'sat' ? hop.name : `${hop.name} (ground)`}</td>
                  <td className="num">{hop.norad ?? ''}</td>
                  <td className="mono">
                    {sidHex(hop.sid)}
                    {hop.provisional ? ' *' : ''}
                  </td>
                  <td className="num">{hop.distanceKm.toFixed(1)}</td>
                  <td className="num">{ms3(hop.propNs)}</td>
                  <td className="num">{ms3(hop.hopDelayNs)}</td>
                  <td className="num">{nsRatioMs(hop.budgetStepNs)}</td>
                  <td className="num">{nsRatioMs(hop.budgetNs)}</td>
                  <td className="num">{hop.deltaUnits}</td>
                  <td className="num">{hop.deadlineU}</td>
                  <td className="num">{unitsMs(hop.deadlineAfterEpochNs, unitCode)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="rp-note">
          <KeyChip k="satellite_positions_sgp4" note="distances" /> <KeyChip k="processing_delay" note="0.5 ms per hop" />{' '}
          Names and NORAD ids are CelesTrak's. SIDs come from the project's SID registry (spec section 7); a city's SID is
          0xF000 + its registry number.{plan.hops.some((x) => x.provisional) || plan.src.provisional ? ' * provisional SID: not yet in the committed registry.' : ''}
          {plan.sat ? ' SAT is set: a delta was too large for one byte and was clamped.' : ''}
        </p>
      </section>

      <section className="rp-panel" aria-labelledby="rp-bytes-title">
        <h3 id="rp-bytes-title">
          The packet <KeyChip k="tcrh_header_bytes" note="real encoder output" />
        </h3>
        <p>
          The T-CRH ({rhLen} bytes, {h} entries) as the ingress builds it for a packet entering at {utcText(tMs)}, inside a whole
          IPv6 packet: the sending host <span className="mono">fd00:0:0:ffff::1</span> addresses the ingress ground station, and
          the UDP checksum covers the final destination (RFC 8200 section 8.1).
        </p>
        <PacketHex packet={plan.packetBytes} rhLen={rhLen} />
        <ByteMap hex={bytesToHex(plan.headerBytes)} caption="T-CRH byte map: hover or focus a byte" />
        <p className="button-row">
          <button
            type="button"
            className="button button--primary"
            onClick={() => {
              const blob = new Blob([new Uint8Array(plan.pcapBytes)], { type: 'application/vnd.tcpdump.pcap' });
              const url = URL.createObjectURL(blob);
              const a = document.createElement('a');
              a.href = url;
              a.download = fileName;
              document.body.append(a);
              a.click();
              a.remove();
              window.setTimeout(() => URL.revokeObjectURL(url), 1000);
            }}
          >
            Download .pcap ({plan.pcapBytes.length} bytes)
          </button>
        </p>
        <p className="rp-note">
          <KeyChip k="pcap_addresses" note="SID s → fd00::s" /> <KeyChip k="pcap_timestamps" note="time stamp = ingress time" /> A
          classic pcap with one frame (LINKTYPE_RAW, nanosecond time stamps). Wireshark opens it; the project's dissector{' '}
          <a href={`${REPO_URL}/tree/main/tools/wireshark`}>tools/wireshark/tcrh.lua</a> decodes every T-CRH field.
        </p>
      </section>

      <section className="rp-panel" aria-labelledby="rp-size-title">
        <h3 id="rp-size-title">Header size for these {h} segments</h3>
        <div className="table-wrap">
          <table className="rp-table rp-table--narrow">
            <caption>Bytes added to every packet in source mode (spec sections 8 and 9).</caption>
            <thead>
              <tr>
                <th scope="col">Header</th>
                <th scope="col">Formula</th>
                <th scope="col">Bytes</th>
                <th scope="col">Carries deadlines</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>T-CRH (this project)</td>
                <td className="mono">pad8(12 + 3n)</td>
                <td className="num">{plan.sizes.tcrh}</td>
                <td>yes</td>
              </tr>
              <tr>
                <td>CRH-16 (RFC 9631)</td>
                <td className="mono">pad8(4 + 2n)</td>
                <td className="num">{plan.sizes.crh16}</td>
                <td>no</td>
              </tr>
              <tr>
                <td>CRH-32 (RFC 9631)</td>
                <td className="mono">pad8(4 + 4n)</td>
                <td className="num">{plan.sizes.crh32}</td>
                <td>no</td>
              </tr>
              <tr>
                <td>SRv6 SRH (RFC 8754, no TLVs)</td>
                <td className="mono">8 + 16n</td>
                <td className="num">{plan.sizes.srh}</td>
                <td>no</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="rp-note">
          Snapshot <span className="mono">{data.snapshot.manifest.snapshot_id}</span>; labels follow the project's shared table (
          {Object.keys(LABEL_TABLE).length} keys, sim/chronoroute/labels.py).
        </p>
      </section>
    </>
  );
}

function PacketHex({ packet, rhLen }: { packet: Uint8Array; rhLen: number }) {
  const parts = useMemo(() => {
    const cut = [0, 40, 40 + rhLen, 48 + rhLen, packet.length];
    const names = ['IPv6 header (40 B, Next Header 43)', `T-CRH, Routing Type 253 (${rhLen} B)`, 'UDP header (8 B)', `Payload (${packet.length - 48 - rhLen} B: "CRT1", packet id, send time)`];
    return names.map((name, i) => ({ name, hex: bytesToHex(packet.slice(cut[i]!, cut[i + 1]!), ' '), cls: `rp-hex--${i}` }));
  }, [packet, rhLen]);
  return (
    <figure className="rp-hexbox">
      <figcaption>
        Full packet, {packet.length} bytes (hex). <span className="sr-only">Segments follow.</span>
      </figcaption>
      {parts.map((p) => (
        <div key={p.name} className={`rp-hex ${p.cls}`}>
          <span className="rp-hex__name">{p.name}</span>
          <code className="rp-hex__bytes">{p.hex}</code>
        </div>
      ))}
      <details>
        <summary>Copy as one hex string</summary>
        <code className="rp-hex__bytes rp-hex__all">{bytesToHex(packet)}</code>
      </details>
    </figure>
  );
}

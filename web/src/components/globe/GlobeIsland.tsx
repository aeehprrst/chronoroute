/**
 * The globe island. Rendered on the server as a loading frame; in the browser it loads the
 * orbit snapshot from this site's /data (loadLatestSnapshot), starts the orbit worker, and
 * lazy-loads the 3D canvas (three.js) only when the island is on screen.
 *
 * variant="live": the full /live globe with clock controls, legend toggles, search, picking
 * and a text summary. variant="mini": the small home-page globe (no zoom, no picking).
 */
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { loadLatestSnapshot } from '../../lib/data';
import type { OmmRecord, SnapshotManifest } from '../../lib/data-types';
import { formatInt, formatUtc } from '../../lib/format';
import { clampScrub, SCRUB_RANGE_MS, speedLabel, SPEEDS, type Speed } from '../../lib/orbit/clock';
import { SHELLS } from '../../lib/orbit/shells';
import { GlobeEngine, buildMeta, type SatMeta } from './engine';
import './globe.css';

const GlobeCanvas = lazy(() => import('./GlobeCanvas'));

const HOUR_MS = 3_600_000;
const DAY_MS = 86_400_000;

export interface GlobeIslandProps {
  variant: 'live' | 'mini';
  /** Link to the full globe (mini variant). */
  liveHref?: string;
}

/** Reference of the time slider: the moving present, or a fixed instant. */
type ScrubRef = { kind: 'now' } | { kind: 'fixed'; ms: number; label: string };

function scrubRefMs(ref: ScrubRef): number {
  return ref.kind === 'now' ? Date.now() : ref.ms;
}

function scrubRefLabel(ref: ScrubRef): string {
  return ref.kind === 'now' ? 'now' : ref.label;
}

type Status =
  | { kind: 'loading' }
  | { kind: 'error'; message: string }
  | { kind: 'ready'; manifest: SnapshotManifest; engine: GlobeEngine };

function utc(ms: number, precision: 'seconds' | 'minutes' = 'seconds'): string {
  return formatUtc(new Date(ms).toISOString(), precision);
}

/** "2 h 05 min", "3 d 4 h", "40 s" for a non-negative duration. */
function duration(ms: number): string {
  const s = Math.floor(Math.abs(ms) / 1000);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return h > 0 ? `${d} d ${h} h` : `${d} d`;
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`;
  if (m > 0) return `${m} min`;
  return `${s % 60} s`;
}

function signedDuration(ms: number): string {
  if (Math.abs(ms) < 1000) return '0 s';
  return `${ms < 0 ? '−' : '+'}${duration(ms)}`;
}

/** True if the browser can create a WebGL 2 context (three.js r186 needs WebGL 2). The probe context is released at once. */
function hasWebGL2(): boolean {
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl2');
    if (!gl) return false;
    gl.getExtension('WEBGL_lose_context')?.loseContext();
    return true;
  } catch {
    return false;
  }
}

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia(query);
    setMatches(mq.matches);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [query]);
  return matches;
}

/* ---------------------------------------------------------------- Clock bar */

function ClockBar({
  engine,
  manifest,
  scrubCenter,
  onScrubCenter,
  onChange,
}: {
  engine: GlobeEngine;
  manifest: SnapshotManifest;
  scrubCenter: ScrubRef;
  onScrubCenter: (center: ScrubRef) => void;
  onChange: () => void;
}) {
  const sim = engine.simMs;
  const speed = engine.clock.speed;
  const now = Date.now();
  const live = speed === 1 && Math.abs(sim - now) < 1500;
  const offset = sim - scrubRefMs(scrubCenter);
  const refLabel = scrubRefLabel(scrubCenter);
  const fetchedMs = Date.parse(manifest.fetched_utc);

  const setSpeed = (s: Speed) => {
    engine.setSpeed(s);
    onChange();
  };
  const jumpNow = () => {
    engine.jump(Date.now());
    onScrubCenter({ kind: 'now' });
    onChange();
  };
  const jumpSnapshot = () => {
    engine.jump(fetchedMs);
    onScrubCenter({ kind: 'fixed', ms: fetchedMs, label: 'the snapshot download time' });
    onChange();
  };

  return (
    <div className="globe-clock" role="group" aria-label="Simulated clock">
      <div className="globe-clock__readout">
        <p className="globe-clock__label">Simulated UTC</p>
        <p className="globe-clock__time num">
          <time dateTime={new Date(sim).toISOString()}>{utc(sim)}</time>
        </p>
        <p className="globe-clock__state num">
          <span className={live ? 'globe-clock__live' : undefined}>{live ? '×1 · current time' : speedLabel(speed)}</span>
          {!live && (
            <span className="muted">
              {' · '}
              {Math.abs(sim - now) < 1500 ? 'at the current time' : `${signedDuration(sim - now)} from now`}
            </span>
          )}
        </p>
      </div>

      <div className="globe-clock__controls">
        <div className="globe-seg" role="group" aria-label="Clock speed">
          {SPEEDS.map((s) => (
            <button
              key={s}
              type="button"
              className="globe-btn"
              aria-pressed={speed === s}
              onClick={() => setSpeed(s)}
            >
              {s === 0 ? 'Pause' : speedLabel(s)}
            </button>
          ))}
        </div>
        <div className="globe-clock__jumps">
          <button type="button" className="globe-btn" onClick={jumpNow}>
            Now
          </button>
          <button type="button" className="globe-btn" onClick={jumpSnapshot}>
            Snapshot time
          </button>
        </div>
        <div className="globe-scrub">
          <label htmlFor="globe-scrub" className="globe-scrub__label">
            Shift time <span className="muted">(±6 h from {refLabel})</span>
          </label>
          <input
            id="globe-scrub"
            type="range"
            min={-SCRUB_RANGE_MS / 60_000}
            max={SCRUB_RANGE_MS / 60_000}
            step={1}
            value={Math.round(clampScrub(offset) / 60_000)}
            aria-valuetext={`${signedDuration(offset)} from ${refLabel}`}
            onChange={(e) => {
              engine.jump(scrubRefMs(scrubCenter) + Number(e.currentTarget.value) * 60_000);
              onChange();
            }}
          />
          <output htmlFor="globe-scrub" className="globe-scrub__value num">
            {signedDuration(offset)}
            {Math.abs(offset) > SCRUB_RANGE_MS ? ' (outside the slider range)' : ''}
          </output>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- Legend */

function ShellLegend({
  engine,
  counts,
  interactive,
  onChange,
}: {
  engine: GlobeEngine;
  counts: number[];
  interactive: boolean;
  onChange: () => void;
}) {
  return (
    <div className="globe-legend">
      <p className="globe-legend__title">
        <span className="globe-chip globe-chip--derived">
          <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true" focusable="false">
            <path d="M5 0.6 9.4 5 5 9.4 0.6 5Z" fill="currentColor" />
          </svg>
          <span className="globe-chip__name">DERIVED</span>
        </span>{' '}
        Colour groups: our grouping by inclination and mean altitude
      </p>
      <ul className="globe-legend__list" role="list">
        {SHELLS.map((shell) => {
          const on = engine.visible[shell.id] ?? true;
          const count = counts[shell.id] ?? 0;
          const content = (
            <>
              <span className="globe-swatch" style={{ background: shell.color }} aria-hidden="true" />
              <span className="globe-legend__name">{shell.label}</span>
              <span className="globe-legend__count num">{formatInt(count)}</span>
            </>
          );
          return (
            <li key={shell.key}>
              {interactive ? (
                <button
                  type="button"
                  className="globe-legend__item"
                  aria-pressed={on}
                  title={shell.detail}
                  onClick={() => {
                    engine.setVisible(shell.id, !on);
                    onChange();
                  }}
                >
                  {content}
                  <span className="sr-only">
                    {`: ${shell.detail}. ${on ? 'Shown' : 'Hidden'}; press to ${on ? 'hide' : 'show'}.`}
                  </span>
                </button>
              ) : (
                <span className="globe-legend__item" title={shell.detail}>
                  {content}
                </span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Server-rendered and loading-state stand-in for the status line and the legend, with the same
 * structure and size, so the section does not grow (and push later content down) when the
 * snapshot has loaded. The group names come from the static SHELLS list; no counts are shown.
 */
function LegendPlaceholder() {
  return (
    <>
      <p className="globe-status globe-status--pending">Loading the orbit snapshot…</p>
      <div className="globe-panels" aria-hidden="true">
        <div className="globe-legend">
          <p className="globe-legend__title">
            <span className="globe-chip globe-chip--derived">
              <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true" focusable="false">
                <path d="M5 0.6 9.4 5 5 9.4 0.6 5Z" fill="currentColor" />
              </svg>
              <span className="globe-chip__name">DERIVED</span>
            </span>{' '}
            Colour groups: our grouping by inclination and mean altitude
          </p>
          <ul className="globe-legend__list" role="list">
            {SHELLS.map((shell) => (
              <li key={shell.key}>
                <span className="globe-legend__item">
                  <span className="globe-swatch" style={{ background: shell.color }} />
                  <span className="globe-legend__name">{shell.label}</span>
                  <span className="globe-legend__count num">…</span>
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}

/* ---------------------------------------------------------------- Search */

function SearchBox({ meta, onSelect }: { meta: SatMeta; onSelect: (index: number) => void }) {
  const [query, setQuery] = useState('');
  const results = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (q.length === 0) return [];
    const out: number[] = [];
    const digits = /^\d+$/.test(q);
    for (let i = 0; i < meta.count && out.length < 8; i += 1) {
      if (meta.initFailed[i]) continue;
      if (digits ? String(meta.norad[i]).startsWith(q) : (meta.names[i] ?? '').includes(q)) out.push(i);
    }
    return out;
  }, [meta, query]);

  return (
    <form
      className="globe-search"
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        const first = results[0];
        if (first !== undefined) onSelect(first);
      }}
    >
      <label htmlFor="globe-search-input" className="globe-search__label">
        Find a satellite
      </label>
      <input
        id="globe-search-input"
        type="search"
        autoComplete="off"
        spellCheck={false}
        placeholder="Name or NORAD ID, e.g. STARLINK-1008 or 100001"
        value={query}
        onChange={(e) => setQuery(e.currentTarget.value)}
        aria-describedby="globe-search-status"
      />
      <p id="globe-search-status" className="sr-only" aria-live="polite">
        {query.trim() === '' ? '' : `${results.length === 8 ? 'At least 8' : results.length} matches`}
      </p>
      {results.length > 0 && (
        <ul className="globe-search__results" role="list">
          {results.map((i) => (
            <li key={i}>
              <button type="button" className="globe-search__result" onClick={() => onSelect(i)}>
                <span>{meta.names[i]}</span>
                <span className="muted num">NORAD {meta.norad[i]}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {query.trim() !== '' && results.length === 0 && <p className="globe-search__none muted">No satellite matches.</p>}
    </form>
  );
}

/* ---------------------------------------------------------------- Info panel */

function InfoPanel({ engine, onClose }: { engine: GlobeEngine; onClose: () => void }) {
  const i = engine.selected;
  if (i < 0) return null;
  const m = engine.meta;
  const shell = SHELLS[m.shell[i] ?? 4];
  const details = engine.selectedDetails();
  const now = details?.now ?? null;
  const pending = details ? 'SGP4 failed at this time' : '…';
  const epochMs = m.epochMs[i] ?? Number.NaN;
  const ageH = (engine.simMs - epochMs) / HOUR_MS;
  const source = m.dataSource[i];
  const latLon = now
    ? `${Math.abs(now.latDeg).toFixed(2)}° ${now.latDeg >= 0 ? 'N' : 'S'}, ${Math.abs(now.lonDeg).toFixed(2)}° ${now.lonDeg >= 0 ? 'E' : 'W'}`
    : pending;
  return (
    <section className="globe-info" aria-labelledby="globe-info-title">
      <div className="globe-info__head">
        <div>
          <h3 id="globe-info-title" className="globe-info__title">
            {m.names[i]}
          </h3>
          <p className="globe-info__ids num">
            NORAD {m.norad[i]} · {m.objectIds[i]}
          </p>
        </div>
        <button type="button" className="globe-btn globe-info__close" onClick={onClose} aria-label="Close satellite details">
          Close
        </button>
      </div>
      <dl className="globe-info__list">
        <div>
          <dt>Altitude above WGS84</dt>
          <dd className="num">{now ? `${now.altitudeKm.toFixed(1)} km` : pending}</dd>
        </div>
        <div>
          <dt>Speed (inertial)</dt>
          <dd className="num">{now ? `${now.speedKmS.toFixed(3)} km/s` : pending}</dd>
        </div>
        <div>
          <dt>Sub-satellite point</dt>
          <dd className="num">{latLon}</dd>
        </div>
        <div>
          <dt>Inclination</dt>
          <dd className="num">
            {(m.inclinationDeg[i] ?? 0).toFixed(2)}°{' '}
            <span className="muted">
              <span className="globe-swatch" style={{ background: shell?.color }} aria-hidden="true" /> group {shell?.label}
            </span>
          </dd>
        </div>
        <div className="globe-info__wide">
          <dt>Element epoch</dt>
          <dd className="num">
            {utc(epochMs)}{' '}
            <span className="muted">
              {Number.isFinite(ageH) ? `(${Math.abs(ageH).toFixed(1)} h ${ageH >= 0 ? 'before' : 'after'} the simulated time)` : ''}
            </span>
          </dd>
        </div>
        <div className="globe-info__wide">
          <dt>Data source</dt>
          <dd>
            {source ? (
              <>
                <span className="mono">{source}</span> <span className="muted">(CelesTrak SupGP, derived from SpaceX ephemerides)</span>
              </>
            ) : (
              'CelesTrak'
            )}
          </dd>
        </div>
      </dl>
      <p className="globe-info__note muted">
        REAL: SGP4 on the public elements at{' '}
        {details ? <time dateTime={new Date(details.atMs).toISOString()}>{utc(details.atMs)}</time> : 'the simulated time'},
        updated each second (a prediction, not tracking data). The group is DERIVED: our grouping by inclination and mean
        altitude.
      </p>
    </section>
  );
}

/* ---------------------------------------------------------------- Island */

export default function GlobeIsland({ variant, liveHref }: GlobeIslandProps) {
  const [status, setStatus] = useState<Status>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [, setTick] = useState(0);
  const [webgl, setWebgl] = useState<'unknown' | 'ok' | 'none'>('unknown');
  const [contextLost, setContextLost] = useState(false);
  const [canvasKey, setCanvasKey] = useState(0);
  const [onScreen, setOnScreen] = useState(true);
  const [announcement, setAnnouncement] = useState('');
  const [scrubCenter, setScrubCenter] = useState<ScrubRef>({ kind: 'now' });
  const rootRef = useRef<HTMLDivElement | null>(null);
  const stageWrapRef = useRef<HTMLDivElement | null>(null);
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)');
  const narrow = useMediaQuery('(max-width: 47.99em), (pointer: coarse)');
  const coarse = useMediaQuery('(pointer: coarse)');
  // On touch screens a swipe over the live globe scrolls the page until the reader turns on
  // "Move globe"; only then do one-finger drags turn the globe (and pinches zoom it).
  const [touchMove, setTouchMove] = useState(false);
  const touchLocked = variant === 'live' && coarse && !touchMove;
  const compact = variant === 'mini' || narrow;

  const rerender = useCallback(() => setTick((t) => t + 1), []);

  // Load the snapshot and start the worker.
  useEffect(() => {
    let disposed = false;
    let engine: GlobeEngine | null = null;
    setStatus({ kind: 'loading' });
    setWebgl(hasWebGL2() ? 'ok' : 'none');
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    (async () => {
      const { manifest, records } = await loadLatestSnapshot();
      const meta = buildMeta(records);
      const start = Date.now();
      const speed: Speed = reduce ? 0 : variant === 'mini' ? 60 : 1;
      engine = new GlobeEngine(meta, start, speed);
      const worker = new Worker(new URL('../../workers/orbit.worker.ts', import.meta.url), {
        type: 'module',
        name: 'orbit',
      });
      await engine.start(worker, records as OmmRecord[]);
      if (disposed) {
        engine.dispose();
        return;
      }
      engine.pump();
      setStatus({ kind: 'ready', manifest, engine });
    })().catch((error: unknown) => {
      engine?.dispose();
      if (!disposed) setStatus({ kind: 'error', message: error instanceof Error ? error.message : String(error) });
    });
    return () => {
      disposed = true;
      engine?.dispose();
    };
  }, [variant, attempt]);

  // Slow UI refresh (clock readout, info panel) and engine pump when the canvas is not drawing.
  useEffect(() => {
    if (status.kind !== 'ready') return;
    const id = window.setInterval(() => {
      status.engine.pump();
      setTick((t) => t + 1);
    }, 250);
    return () => window.clearInterval(id);
  }, [status]);

  // Stop drawing when the globe is off screen.
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) setOnScreen(entry.isIntersecting);
    });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  const engine = status.kind === 'ready' ? status.engine : null;

  const select = useCallback(
    (index: number, flyTo: boolean) => {
      if (!engine) return;
      engine.select(index, flyTo);
      setAnnouncement(
        index >= 0 ? `Selected ${engine.meta.names[index]}, NORAD ${engine.meta.norad[index]}.` : 'Selection cleared.',
      );
      rerender();
    },
    [engine, rerender],
  );
  const onPick = useCallback((index: number) => select(index, false), [select]);
  // A search result is chosen below the globe: turn the globe to it and bring the globe and its
  // details panel into view, or the reader sees no response.
  const onSearchSelect = useCallback(
    (index: number) => {
      select(index, true);
      window.requestAnimationFrame(() => {
        stageWrapRef.current?.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth', block: 'start' });
      });
    },
    [select, reducedMotion],
  );
  const onContextLost = useCallback(() => setContextLost(true), []);

  const counts = useMemo(() => {
    const c = SHELLS.map(() => 0);
    if (engine) {
      for (let i = 0; i < engine.meta.count; i += 1) {
        if (!engine.meta.initFailed[i]) c[engine.meta.shell[i] ?? 4] = (c[engine.meta.shell[i] ?? 4] ?? 0) + 1;
      }
    }
    return c;
  }, [engine]);

  const manifest = status.kind === 'ready' ? status.manifest : null;
  const initFailed = engine?.initErrors.length ?? 0;
  const failedNow = engine?.failedNow() ?? 0;
  const loadedCount = engine ? engine.meta.count - initFailed : 0;
  const hiddenCount = engine ? SHELLS.reduce((sum, s) => sum + (engine.visible[s.id] ? 0 : (counts[s.id] ?? 0)), 0) : 0;
  // Counted from the frame on screen, so a satellite that is both hidden and failed counts once.
  const drawnNow = engine ? engine.drawnNow() : null;
  const simMs = engine ? engine.simMs : 0;
  const epochGapMs = manifest ? simMs - Date.parse(manifest.epoch_median) : 0;
  const farFromEpoch = manifest ? Math.abs(epochGapMs) > manifest.max_epoch_age_days * DAY_MS : false;

  const stageMessage =
    status.kind === 'loading'
      ? 'Loading the orbit snapshot and starting SGP4…'
      : status.kind === 'ready' && webgl === 'none'
        ? 'This browser could not start WebGL 2, so the 3D view is not available. The text below lists what it would show.'
        : null;

  return (
    <div
      ref={rootRef}
      className={`globe globe--${variant}`}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && engine && engine.selected >= 0) select(-1, false);
      }}
    >
      {variant === 'live' && engine && manifest && (
        <ClockBar
          engine={engine}
          manifest={manifest}
          scrubCenter={scrubCenter}
          onScrubCenter={setScrubCenter}
          onChange={rerender}
        />
      )}
      {variant === 'live' && !engine && <div className="globe-clock globe-clock--placeholder" aria-hidden="true" />}

      {farFromEpoch && manifest && (
        <p className="globe-warning" role="status">
          The simulated time is {duration(epochGapMs)} {epochGapMs > 0 ? 'after' : 'before'} the median element epoch
          ({utc(Date.parse(manifest.epoch_median), 'minutes')}). SGP4 errors grow with the time from the element epoch,
          so positions this far from it are less accurate.
        </p>
      )}

      <div className="globe-stage-wrap" ref={stageWrapRef}>
        <div className="globe-stage">
          <div
            className="globe-stage__view"
            role="img"
            aria-label={
              engine && manifest
                ? `3D globe: the Earth with ${formatInt(loadedCount)} Starlink satellites at their SGP4 positions for ${utc(simMs, 'minutes')}.${variant === 'live' ? ' A text summary follows the globe.' : ''}`
                : '3D globe of Starlink satellites (loading).'
            }
          >
            {engine && webgl === 'ok' && !contextLost && (
              <Suspense fallback={null}>
                <GlobeCanvas
                  key={canvasKey}
                  engine={engine}
                  variant={variant}
                  compact={compact}
                  reducedMotion={reducedMotion}
                  active={onScreen}
                  touchLocked={touchLocked}
                  onPick={onPick}
                  onContextLost={onContextLost}
                />
              </Suspense>
            )}
          </div>
          {stageMessage && <p className="globe-stage__msg">{stageMessage}</p>}
          {status.kind === 'error' && (
            <div className="globe-stage__msg globe-stage__msg--error">
              <p>The orbit snapshot could not be loaded: {status.message}</p>
              <button type="button" className="globe-btn" onClick={() => setAttempt((a) => a + 1)}>
                Try again
              </button>
            </div>
          )}
          {contextLost && (
            <div className="globe-stage__msg globe-stage__msg--error">
              <p>The browser stopped the 3D graphics (WebGL context lost), for example to free memory.</p>
              <button
                type="button"
                className="globe-btn"
                onClick={() => {
                  setContextLost(false);
                  setCanvasKey((k) => k + 1);
                }}
              >
                Restart the 3D view
              </button>
            </div>
          )}
          {variant === 'mini' && engine && (
            <p className="globe-stage__clock num" aria-hidden="true">
              {utc(simMs, 'minutes')} · {speedLabel(engine.clock.speed)}
            </p>
          )}
        </div>
        {variant === 'live' && engine && webgl === 'ok' && !contextLost && (
          <div className="globe-view-buttons" role="group" aria-label="View">
            <button type="button" className="globe-btn" onClick={() => engine.commandCamera('zoom-in')} aria-label="Zoom in">
              +
            </button>
            <button type="button" className="globe-btn" onClick={() => engine.commandCamera('zoom-out')} aria-label="Zoom out">
              −
            </button>
            <button type="button" className="globe-btn" onClick={() => engine.commandCamera('reset')}>
              Reset view
            </button>
            {coarse && (
              <button type="button" className="globe-btn" aria-pressed={touchMove} onClick={() => setTouchMove((m) => !m)}>
                Move globe
              </button>
            )}
          </div>
        )}
        {variant === 'live' && engine && engine.selected >= 0 && (
          <div className="globe-info-slot">
            <InfoPanel engine={engine} onClose={() => select(-1, false)} />
          </div>
        )}
      </div>

      {variant === 'live' && engine && webgl === 'ok' && (
        <p className="globe-hint">
          {coarse
            ? touchMove
              ? 'Drag to turn the globe and pinch to zoom. Turn off Move globe to scroll the page with a swipe again. Tap a dot to see that satellite.'
              : 'A swipe over the globe scrolls the page. Turn on Move globe to turn it with your finger, or use the buttons to zoom. Tap a dot to see that satellite.'
            : 'Drag to turn the globe. Click it and scroll, pinch, or use the buttons to zoom. Click a dot to see that satellite.'}
        </p>
      )}

      {engine && (
        <p className="globe-status num">
          {formatInt(loadedCount)} satellites propagated
          {initFailed > 0 ? `; ${formatInt(initFailed)} element sets could not be initialised by SGP4 and are not drawn` : '; 0 SGP4 initialisation errors'}
          {`; ${formatInt(failedNow)} SGP4 failures at the time shown`}
          {hiddenCount > 0 ? `; ${formatInt(hiddenCount)} hidden by the legend` : ''}.
        </p>
      )}

      {engine && (
        <div className="globe-panels">
          <ShellLegend engine={engine} counts={counts} interactive={variant === 'live'} onChange={rerender} />
          {variant === 'live' && <SearchBox meta={engine.meta} onSelect={onSearchSelect} />}
        </div>
      )}

      {!engine && status.kind !== 'error' && <LegendPlaceholder />}

      {variant === 'mini' && liveHref && (
        <p className="globe-mini__link">
          <a className="button" href={liveHref}>
            Open the live globe
          </a>
        </p>
      )}

      {variant === 'live' && engine && manifest && (
        <details className="globe-summary">
          <summary>Text summary of the globe</summary>
          <div className="globe-summary__body">
            <p>
              Simulated time {utc(simMs)} ({engine.clock.speed === 0 ? 'paused' : `${speedLabel(engine.clock.speed)} real time`}).{' '}
              {drawnNow === null
                ? `The globe is computing its first frame from the ${formatInt(manifest.count)} element sets in the ${manifest.source} snapshot downloaded ${formatUtc(manifest.fetched_utc)}.`
                : `The globe draws ${formatInt(drawnNow)} of the ${formatInt(manifest.count)} element sets in the ${manifest.source} snapshot downloaded ${formatUtc(manifest.fetched_utc)}, each at its SGP4 position for that time, around an Earth turned to the same instant, with day and night from the Sun's direction.`}
            </p>
            <div className="table-wrap">
            <table>
              <caption>Satellites per colour group (derived: our grouping by inclination and mean altitude)</caption>
              <thead>
                <tr>
                  <th scope="col">Group</th>
                  <th scope="col">Rule</th>
                  <th scope="col">Satellites</th>
                  <th scope="col">Shown</th>
                </tr>
              </thead>
              <tbody>
                {SHELLS.map((s) => (
                  <tr key={s.key}>
                    <th scope="row">{s.label}</th>
                    <td>{s.detail}</td>
                    <td className="num">{formatInt(counts[s.id] ?? 0)}</td>
                    <td>{engine.visible[s.id] ? 'Yes' : 'No'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
            {engine.initErrors.length > 0 && (
              <>
                <p>Element sets that SGP4 could not initialise (not drawn):</p>
                <ul>
                  {engine.initErrors.map((e) => (
                    <li key={e.index}>
                      {e.name} (NORAD {e.norad}): {e.message}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <p>
              Reference markers on the Earth: Greenwich, Chennai, New York and Sydney, placed from their latitude and
              longitude to check the map orientation.
            </p>
          </div>
        </details>
      )}

      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}

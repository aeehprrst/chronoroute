/**
 * Header size comparison for n hops: T-CRH vs CRH-16 vs CRH-32 vs SRv6 SRH, computed by
 * src/engine/sizes.ts from the formulas of spec section 9. In encapsulation mode the 40-byte
 * outer IPv6 header is added (spec section 8). The table is the text version of the bars.
 */
import { useId, useState } from 'react';
import {
  HEADERS,
  HEADER_INFO,
  IPV6_HEADER_BYTES,
  TCRH_MAX_HOPS,
  encapsulationOverhead,
  headerSize,
  type HeaderKind,
  type OverheadMode,
} from '../../engine/sizes';
import './protocol.css';

const TABLE_HOPS = [1, 3, 5, 10, 13, 20] as const;

export default function SizeCompare() {
  const id = useId();
  const [hopsText, setHopsText] = useState('10');
  const [mode, setMode] = useState<OverheadMode>('source');
  const [hover, setHover] = useState<HeaderKind | null>(null);

  const parsed = Number(hopsText);
  const valid = /^\d{1,3}$/.test(hopsText.trim()) && parsed >= 1 && parsed <= TCRH_MAX_HOPS;
  const n = valid ? parsed : 10;
  const rows = HEADERS.map((h) => ({
    kind: h,
    rh: headerSize(h, n),
    total: encapsulationOverhead(n, mode, h),
  }));
  const max = Math.max(...rows.map((r) => r.total));
  const shown = rows.find((r) => r.kind === hover);

  return (
    <div className="pr-tool">
      <div className="pr-row">
        <label className="pr-field" style={{ flex: '2 1 14rem' }}>
          <span>Number of hops n: {n}</span>
          <input
            type="range"
            min={1}
            max={40}
            value={Math.min(n, 40)}
            onChange={(e) => setHopsText(e.target.value)}
            aria-describedby={`${id}-range-note`}
          />
        </label>
        <label className="pr-field" style={{ flex: '1 1 7rem' }}>
          <span>or type 1 to 255</span>
          <input
            className="pr-input"
            value={hopsText}
            inputMode="numeric"
            aria-invalid={!valid}
            onChange={(e) => setHopsText(e.target.value)}
          />
        </label>
        <fieldset className="pr-fieldset">
          <legend>Mode (spec section 8)</legend>
          <div className="pr-seg">
            {(['source', 'encap'] as const).map((m) => (
              <label key={m}>
                <input
                  type="radio"
                  name={`${id}-mode`}
                  value={m}
                  checked={mode === m}
                  onChange={() => setMode(m)}
                />
                {m === 'source' ? 'Source insertion' : 'Encapsulation (+40 B)'}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      <p className="pr-small pr-muted" id={`${id}-range-note`}>
        {valid ? '' : 'Type a whole number from 1 to 255 (Num Hops is one byte). Showing n = 10. '}
        The slider covers 1 to 40 hops; type a larger n if you need it.
      </p>

      <figure style={{ margin: 0 }}>
        <figcaption className="pr-h">
          Bytes added to each packet with {n} {n === 1 ? 'hop' : 'hops'},{' '}
          {mode === 'source' ? 'source insertion' : 'encapsulation at the gateway'}
        </figcaption>
        <ul className="pr-bars" onMouseLeave={() => setHover(null)}>
          {rows.map((r) => (
            <li key={r.kind} className="pr-bar" onMouseEnter={() => setHover(r.kind)}>
              <span className="pr-bar__label">
                <span>
                  {HEADER_INFO[r.kind].name} <small>{HEADER_INFO[r.kind].source}</small>
                </span>
                <span className="pr-bar__value">
                  {mode === 'encap' && <small>{IPV6_HEADER_BYTES} + {r.rh} = </small>}
                  {r.total} B
                </span>
              </span>
              <span className="pr-bar__track" aria-hidden="true">
                {mode === 'encap' && (
                  <span className="pr-bar__seg pr-bar__seg--ipv6" style={{ width: `${(IPV6_HEADER_BYTES / max) * 100}%` }} />
                )}
                <span
                  className={`pr-bar__seg ${r.kind === 'tcrh' ? 'pr-bar__seg--ours' : ''}`}
                  style={{ width: `${(r.rh / max) * 100}%` }}
                />
              </span>
            </li>
          ))}
        </ul>
        <p className="pr-sizes-hover" aria-hidden="true">
          {shown
            ? `${HEADER_INFO[shown.kind].name}, ${n} ${n === 1 ? 'hop' : 'hops'}: ${shown.rh} B routing header (${HEADER_INFO[shown.kind].formula})${
                mode === 'encap' ? ` + ${IPV6_HEADER_BYTES} B outer IPv6 = ${shown.total} B` : ''
              }.`
            : 'Hover over a bar for its formula; the table below lists every formula.'}
        </p>
        {mode === 'encap' && (
          <ul className="pr-legend" aria-hidden="true">
            <li>
              <span className="pr-swatch" style={{ background: 'repeating-linear-gradient(45deg, #4a5d7e 0 2px, transparent 2px 4px)' }} />{' '}
              outer IPv6 header (40 B)
            </li>
            <li>
              <span className="pr-swatch" style={{ background: 'var(--accent)' }} /> T-CRH
            </li>
            <li>
              <span className="pr-swatch" style={{ background: '#6f809c' }} /> other routing headers
            </li>
          </ul>
        )}
      </figure>

      <div className="pr-table-wrap" role="region" aria-label="Header sizes table" tabIndex={0}>
        <table>
          <caption>
            Routing header size in bytes ({mode === 'source' ? 'source insertion' : 'plus the 40-byte outer IPv6 header'}).
            pad8(x) rounds x up to a multiple of 8.
          </caption>
          <thead>
            <tr>
              <th scope="col">Header</th>
              <th scope="col">Formula</th>
              {[...new Set([...TABLE_HOPS, n])]
                .sort((a, b) => a - b)
                .map((k) => (
                  <th key={k} scope="col" className="pr-r">
                    n = {k}
                  </th>
                ))}
            </tr>
          </thead>
          <tbody>
            {HEADERS.map((h) => (
              <tr key={h} className={h === 'tcrh' ? 'is-current' : ''}>
                <th scope="row">
                  {HEADER_INFO[h].name} <span className="pr-muted">({HEADER_INFO[h].source})</span>
                </th>
                <td className="pr-mono">{HEADER_INFO[h].formula}</td>
                {[...new Set([...TABLE_HOPS, n])]
                  .sort((a, b) => a - b)
                  .map((k) => (
                    <td key={k} className="pr-r">
                      {encapsulationOverhead(k, mode, h)}
                    </td>
                  ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * Interactive byte map of a T-CRH: 8 bytes per row (one 8-octet unit of Hdr Ext Len).
 * Hover or focus a byte to see its field, value and meaning. Keyboard: Tab enters the map,
 * arrow keys move by one byte (left/right) or one row (up/down), Home/End jump to the ends.
 * Only one byte is in the tab order at a time (roving tabindex). Every byte button carries
 * a full text label, so the map works with a screen reader.
 */
import { useId, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { hexToBytes } from '../../engine/tcrh';
import { describeTcrhBytes, hex2, type ByteInfo } from './byte-fields';
import './protocol.css';

interface Props {
  /** Bytes as hex (lowercase or uppercase, whitespace ignored). */
  hex: string;
  /** Short caption above the map. */
  caption?: string;
  /** Byte indexes to mark as changed (e.g. by the last processing step). */
  changed?: readonly number[];
}

const KIND_LABEL: Record<ByteInfo['kind'], string> = {
  fixed: 'fixed field',
  time: 'time value',
  sid: 'segment identifier',
  pad: 'padding',
  extra: 'after the header',
  unknown: 'not parsed',
};

function byteLabel(info: ByteInfo, changed: boolean): string {
  const range = info.first === info.last ? `byte ${info.first}` : `bytes ${info.first} to ${info.last}`;
  return (
    `Byte ${info.index}, hex ${hex2(info.value)}. ${info.field} (${range})` +
    `${info.valueText ? ` = ${info.valueText}` : ''}. ${info.meaning}` +
    `${info.mutable ? ' This field is mutable.' : ''}${changed ? ' Changed by the last step.' : ''}`
  );
}

export default function ByteMap({ hex, caption, changed = [] }: Props) {
  const id = useId();
  const bytes = useMemo(() => {
    try {
      return hexToBytes(hex);
    } catch {
      return new Uint8Array();
    }
  }, [hex]);
  const { infos } = useMemo(() => describeTcrhBytes(bytes), [bytes]);
  const [active, setActive] = useState(0);
  const [hover, setHover] = useState<number | null>(null);
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const changedSet = useMemo(() => new Set(changed), [changed]);

  if (infos.length === 0) return <p className="pr-muted">No bytes to show.</p>;

  const activeIndex = Math.min(active, infos.length - 1);
  const shownIndex = hover !== null && hover < infos.length ? hover : activeIndex;
  const shown = infos[shownIndex];

  const move = (to: number) => {
    const next = Math.max(0, Math.min(infos.length - 1, to));
    setActive(next);
    refs.current[next]?.focus();
  };

  const onKey = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const map: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowLeft: index - 1,
      ArrowDown: index + 8,
      ArrowUp: index - 8,
      Home: 0,
      End: infos.length - 1,
    };
    const to = map[event.key];
    if (to !== undefined) {
      event.preventDefault();
      move(to);
    }
  };

  const rows: ByteInfo[][] = [];
  for (let i = 0; i < infos.length; i += 8) rows.push(infos.slice(i, i + 8));
  const tall = rows.length > 12;

  return (
    <div className="pr-bytemap">
      {caption && (
        <p className="pr-bytemap__caption" id={`${id}-cap`}>
          {caption}
        </p>
      )}
      <div className="pr-bytemap__body">
        <div
          className={`pr-bytemap__grid${tall ? ' pr-bytemap__grid--tall' : ''}`}
          role="group"
          aria-label={`${caption ? `${caption}. ` : ''}${infos.length} bytes, 8 per row. Arrow keys move between bytes.`}
          onMouseLeave={() => setHover(null)}
        >
          {rows.map((row, r) => (
            <div className="pr-bytemap__row" key={r}>
              <span className="pr-bytemap__offset" aria-hidden="true">
                {String(r * 8).padStart(3, ' ')}
              </span>
              {row.map((info) => {
                const inGroup = shown !== undefined && info.group === shown.group;
                const isChanged = changedSet.has(info.index);
                return (
                  <button
                    key={info.index}
                    ref={(el) => {
                      refs.current[info.index] = el;
                    }}
                    type="button"
                    tabIndex={info.index === activeIndex ? 0 : -1}
                    className={[
                      'pr-byte',
                      `pr-byte--${info.kind}`,
                      info.mutable ? 'pr-byte--mutable' : '',
                      inGroup ? 'is-group' : '',
                      info.index === shownIndex ? 'is-shown' : '',
                      isChanged ? 'is-changed' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                    aria-label={byteLabel(info, isChanged)}
                    onFocus={() => setActive(info.index)}
                    onMouseEnter={() => setHover(info.index)}
                    onClick={() => setActive(info.index)}
                    onKeyDown={(e) => onKey(e, info.index)}
                  >
                    {hex2(info.value)}
                  </button>
                );
              })}
            </div>
          ))}
        </div>

        {shown && (
          <div className="pr-bytemap__detail" aria-hidden="true">
            <p className="pr-bytemap__field">
              <span className={`pr-swatch pr-swatch--${shown.kind}`} />
              {shown.field}
              <span className="pr-bytemap__range">
                {shown.first === shown.last ? `byte ${shown.first}` : `bytes ${shown.first}–${shown.last}`}
                {' · '}
                {KIND_LABEL[shown.kind]}
                {shown.mutable ? ' · mutable' : ''}
              </span>
            </p>
            {shown.valueText && <p className="pr-bytemap__value">{shown.valueText}</p>}
            <p className="pr-bytemap__meaning">{shown.meaning}</p>
          </div>
        )}
      </div>
      <ul className="pr-legend" aria-label="Byte colours">
        <li>
          <span className="pr-swatch pr-swatch--fixed" /> fixed field
        </li>
        <li>
          <span className="pr-swatch pr-swatch--fixed pr-swatch--mutable" /> mutable in flight
        </li>
        <li>
          <span className="pr-swatch pr-swatch--time" /> time (Epoch_Base, deltas)
        </li>
        <li>
          <span className="pr-swatch pr-swatch--sid" /> SID
        </li>
        <li>
          <span className="pr-swatch pr-swatch--pad" /> padding
        </li>
        {changed.length > 0 && (
          <li>
            <span className="pr-swatch pr-swatch--changed" /> changed by this step
          </li>
        )}
      </ul>
    </div>
  );
}

/**
 * Header decoder: paste hex -> the engine validates it in the order of spec section 6 step 1
 * and either explains, in plain words, why the bytes are not a valid T-CRH, or shows every
 * field. Example buttons load golden test vectors.
 */
import { useEffect, useId, useMemo, useState } from 'react';
import { decodePrefix, deadlines, processAtNode, TcrhDecodeError, type TcrhHeader } from '../../engine/tcrh';
import { tcrhSize } from '../../engine/sizes';
import ByteMap from './ByteMap';
import { describeTcrhBytes, flagNames, hex2, sidKind, unitLabel } from './byte-fields';
import './protocol.css';

interface Example {
  label: string;
  hex: string;
  note: string;
}

interface Props {
  examples: readonly Example[];
}

type Parsed =
  | { kind: 'empty' }
  | { kind: 'bad-hex'; message: string }
  | { kind: 'bytes'; bytes: Uint8Array; hex: string };

/** Accepts spaces, newlines, colons, dashes, commas and 0x prefixes. */
function parseHexText(text: string): Parsed {
  const clean = text.replace(/0x/gi, '').replace(/[\s:,-]+/g, '');
  if (clean === '') return { kind: 'empty' };
  const bad = /[^0-9a-f]/i.exec(clean);
  if (bad) return { kind: 'bad-hex', message: `"${bad[0]}" is not a hex digit. Use 0-9 and a-f only.` };
  if (clean.length % 2 !== 0) {
    return { kind: 'bad-hex', message: `That is ${clean.length} hex digits, an odd number. Every byte needs two digits.` };
  }
  const bytes = new Uint8Array(clean.length / 2);
  for (let i = 0; i < bytes.length; i += 1) bytes[i] = Number.parseInt(clean.slice(2 * i, 2 * i + 2), 16);
  if (bytes.length > 4096) return { kind: 'bad-hex', message: 'Paste at most 4096 bytes.' };
  return { kind: 'bytes', bytes, hex: clean.toLowerCase() };
}

const CHECKS = [
  'At least 8 bytes',
  'Routing Type is 253',
  'Num Hops is not 0',
  'Segments Left ≤ Num Hops',
  'Hdr Ext Len covers all entries',
  'Every announced byte is present',
] as const;

function failingCheck(error: TcrhDecodeError, length: number): number {
  switch (error.reason) {
    case 'truncated':
      return length < 8 ? 0 : 5;
    case 'wrong_type':
      return 1;
    case 'numhops_zero':
      return 2;
    case 'sl_gt_numhops':
      return 3;
    case 'length_mismatch':
      return 4;
    default:
      return 5;
  }
}

function explain(error: TcrhDecodeError, b: Uint8Array): string {
  const at = (i: number) => b[i] ?? 0;
  const nh = at(5);
  const hel = at(1);
  switch (error.reason) {
    case 'truncated':
      return b.length < 8
        ? `Too short: a T-CRH needs at least 8 bytes for its fixed fields, and this is ${b.length}.`
        : `Hdr Ext Len (byte 1) announces (${hel} + 1) × 8 = ${(hel + 1) * 8} bytes, but only ${b.length} are here. Paste the whole header.`;
    case 'wrong_type': {
      const rt = at(2);
      const known: Record<number, string> = {
        4: ' (4 is the SRv6 Segment Routing Header, RFC 8754)',
        5: ' (5 is CRH-16, RFC 9631)',
        6: ' (6 is CRH-32, RFC 9631)',
      };
      return `Byte 2, the Routing Type, is ${rt}. A T-CRH has Routing Type 253, so these bytes are not a T-CRH${known[rt] ?? ''}.`;
    }
    case 'numhops_zero':
      return 'Byte 5, Num Hops, is 0. A T-CRH carries 1 to 255 entries; with none there is no endpoint to deliver to or to fall back towards.';
    case 'sl_gt_numhops':
      return `Byte 3, Segments Left, is ${at(3)}, but Num Hops (byte 5) is ${nh}. A packet cannot have more segments left than its path has hops.`;
    case 'length_mismatch':
      return `Byte 1, Hdr Ext Len, is ${hel}, so the header is (${hel} + 1) × 8 = ${(hel + 1) * 8} bytes. But ${nh} hops need pad8(12 + 3 × ${nh}) = ${tcrhSize(nh)} bytes.`;
    default:
      return error.message;
  }
}

function warnings(h: TcrhHeader, b: Uint8Array, length: number): string[] {
  const out: string[] = [];
  if ((b[7] ?? 0) !== 0) out.push('The Reserved byte (7) is not zero. Receivers ignore it and pass it on.');
  if ((h.flags & 0xc8) !== 0) out.push('Reserved flag bits are set. Receivers ignore them and pass them on.');
  const used = 12 + 3 * h.numHops;
  if (Array.from(b.subarray(used, length)).some((x) => x !== 0)) out.push('The padding is not all zero. Receivers ignore it.');
  if (length > tcrhSize(h.numHops)) out.push(`Hdr Ext Len announces ${length} bytes; ${tcrhSize(h.numHops)} would be enough. Accepted.`);
  if (b.length > length) out.push(`${b.length - length} bytes follow the header. They are the payload, not part of the T-CRH.`);
  if (h.sidsRev.includes(0xffff)) out.push('A SID is 0xFFFF, which is reserved (spec section 7).');
  if ((h.flags & 0x01) === 0 && h.devHop !== 0) out.push('Dev Hop is not 0 although DEV is clear. Dev Hop only means something while DEV is set.');
  if ((h.flags & 0x02) !== 0 && (h.flags & 0x01) === 0) out.push('GREEDY is set without DEV. The processing rules always set DEV first.');
  return out;
}

function stateText(h: TcrhHeader): string {
  const sl = h.segmentsLeft;
  const dev = (h.flags & 0x01) !== 0;
  const greedy = (h.flags & 0x02) !== 0;
  const parts: string[] = [];
  if (greedy) parts.push(`In geographic fallback (GREEDY), heading for SID[0] = ${h.sidsRev[0]}, the final endpoint.`);
  else if (sl === h.numHops) parts.push('A fresh header: the ingress has not sent it yet.');
  else if (sl === 0) parts.push(`Addressed to the final endpoint, SID[0] = ${h.sidsRev[0]} (hop ${h.numHops}).`);
  else parts.push(`Addressed to SID[${sl}] = ${h.sidsRev[sl]}, hop ${h.numHops - sl} of ${h.numHops}.`);
  if (dev) parts.push(h.devHop === 0 ? 'DEV is set with Dev Hop 0: the ingress found its first link down.' : `DEV is set: first found late (or its next link down) at hop ${h.devHop}.`);
  return parts.join(' ');
}

export default function HeaderDecoder({ examples }: Props) {
  const id = useId();
  const [text, setText] = useState(() => examples[0]?.hex.replace(/(..)/g, '$1 ').trim() ?? '');

  useEffect(() => {
    const onDecode = (event: Event) => {
      const hex = (event as CustomEvent<{ hex?: unknown }>).detail?.hex;
      if (typeof hex === 'string') setText(hex.replace(/(..)/g, '$1 ').trim());
    };
    window.addEventListener('tcrh:decode', onDecode);
    return () => window.removeEventListener('tcrh:decode', onDecode);
  }, []);

  const parsed = useMemo(() => parseHexText(text), [text]);
  const decoded = useMemo(() => {
    if (parsed.kind !== 'bytes') return null;
    try {
      const { header, length } = decodePrefix(parsed.bytes);
      return { ok: true as const, header, length };
    } catch (error) {
      if (error instanceof TcrhDecodeError) {
        // What a node would do with these bytes (step 1); the clock does not matter here.
        const outcome = processAtNode(parsed.bytes, 0, 'greedy');
        return { ok: false as const, error, outcome };
      }
      throw error;
    }
  }, [parsed]);

  const ds = useMemo(() => (decoded?.ok ? deadlines(decoded.header) : []), [decoded]);

  const fields = useMemo(() => {
    if (parsed.kind !== 'bytes' || !decoded?.ok) return [];
    const seen = new Set<string>();
    return describeTcrhBytes(parsed.bytes).infos.filter((info) => {
      if (seen.has(info.group) || info.kind === 'sid' || info.field.startsWith('Delta')) return false;
      seen.add(info.group);
      return true;
    });
  }, [parsed, decoded]);

  return (
    <div className="pr-tool">
      <div>
        <p className="pr-h">Examples from the golden test vectors</p>
        <div className="pr-btns">
          {examples.map((ex) => (
            <button
              key={ex.label}
              type="button"
              className="pr-btn pr-btn--quiet"
              title={ex.note}
              onClick={() => setText(ex.hex.replace(/(..)/g, '$1 ').trim())}
            >
              {ex.label}
            </button>
          ))}
        </div>
      </div>

      <label className="pr-field" htmlFor={`${id}-hex`}>
        <span>Header bytes in hex (spaces, colons and 0x are fine)</span>
      </label>
      <textarea
        id={`${id}-hex`}
        className="pr-textarea"
        value={text}
        spellCheck={false}
        autoComplete="off"
        style={{ marginTop: 'var(--space-2)' }}
        aria-describedby={`${id}-status`}
        onChange={(e) => setText(e.target.value)}
      />

      <div id={`${id}-status`} role="status" aria-live="polite">
        {parsed.kind === 'empty' && <p className="pr-muted pr-small">Paste a header, or choose an example.</p>}
        {parsed.kind === 'bad-hex' && (
          <div className="pr-status pr-status--bad">
            <span className="pr-status__mark">HEX</span>
            <span>{parsed.message}</span>
          </div>
        )}
        {decoded && !decoded.ok && parsed.kind === 'bytes' && (
          <div className="pr-status pr-status--bad">
            <span className="pr-status__mark">{decoded.outcome.action === 'ignore' ? 'IGNORED' : 'INVALID'}</span>
            <span>
              {explain(decoded.error, parsed.bytes)}{' '}
              {decoded.outcome.action === 'ignore'
                ? 'Because Segments Left is 0, a node ignores this routing header and goes on to the Next Header (RFC 8200 section 4.4).'
                : decoded.outcome.icmpCode !== null
                  ? `A node discards the packet and sends ICMPv6 Parameter Problem, Code ${decoded.outcome.icmpCode}, pointing at byte ${decoded.outcome.icmpPointer} of the routing header.`
                  : 'A node discards the packet. No ICMPv6 message is sent: there is no field to point at.'}
            </span>
          </div>
        )}
        {decoded?.ok && (
          <div className="pr-status pr-status--ok">
            <span className="pr-status__mark">VALID</span>
            <span>
              A {decoded.length}-byte T-CRH with {decoded.header.numHops} {decoded.header.numHops === 1 ? 'hop' : 'hops'}.{' '}
              {stateText(decoded.header)}
            </span>
          </div>
        )}
      </div>

      {parsed.kind === 'bytes' && decoded && (
        <div>
          <p className="pr-h">Validation, in the order of spec section 6 step 1</p>
          <ol className="pr-checks">
            {CHECKS.map((label, i) => {
              const fail = decoded.ok ? -1 : failingCheck(decoded.error, parsed.bytes.length);
              const state = decoded.ok || i < fail ? 'pass' : i === fail ? 'fail' : 'skip';
              return (
                <li key={label}>
                  <span className={`pr-check-mark pr-check-mark--${state}`}>
                    {state === 'pass' ? 'PASS' : state === 'fail' ? 'FAIL' : 'NOT RUN'}
                  </span>
                  <span>{label}</span>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {parsed.kind === 'bytes' && <ByteMap hex={parsed.hex} caption="Hover or focus a byte to see its field." />}

      {parsed.kind === 'bytes' && decoded?.ok && (
        <>
          {warnings(decoded.header, parsed.bytes, decoded.length).length > 0 && (
            <div>
              <p className="pr-h">Accepted, but worth knowing</p>
              <ul className="pr-notes">
                {warnings(decoded.header, parsed.bytes, decoded.length).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="pr-table-wrap" role="region" aria-label="Fixed fields" tabIndex={0}>
            <table>
              <caption>Fixed fields and padding</caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Bytes</th>
                  <th scope="col">Value</th>
                  <th scope="col">Meaning</th>
                </tr>
              </thead>
              <tbody>
                {fields.map((f) => (
                  <tr key={f.group}>
                    <th scope="row">{f.field}</th>
                    <td className="pr-mono">{f.first === f.last ? f.first : `${f.first}–${f.last}`}</td>
                    <td className="pr-mono">{f.valueText}</td>
                    <td className="pr-wrap pr-muted">{f.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="pr-table-wrap" role="region" aria-label="Entries" tabIndex={0}>
            <table>
              <caption>
                Entries in wire order (reverse path order). Unit u = {unitLabel((decoded.header.flags >> 4) & 3)}.
                Flags: {flagNames(decoded.header.flags).join(', ') || 'none'} (0x{hex2(decoded.header.flags)}).
              </caption>
              <thead>
                <tr>
                  <th scope="col" className="pr-r">
                    i
                  </th>
                  <th scope="col" className="pr-r">
                    Hop k
                  </th>
                  <th scope="col" className="pr-r">
                    SID[i]
                  </th>
                  <th scope="col">Kind</th>
                  <th scope="col" className="pr-r">
                    Delta[i] = d_k
                  </th>
                  <th scope="col" className="pr-r">
                    D_k
                  </th>
                </tr>
              </thead>
              <tbody>
                {decoded.header.sidsRev.map((sid, i) => {
                  const k = decoded.header.numHops - i;
                  return (
                    <tr key={i} className={i === decoded.header.segmentsLeft && i < decoded.header.numHops ? 'is-current' : ''}>
                      <td className="pr-r">{i}</td>
                      <td className="pr-r">{k}</td>
                      <td className="pr-r">{sid}</td>
                      <td>{sidKind(sid)}</td>
                      <td className="pr-r">{decoded.header.deltasRev[i]}</td>
                      <td className="pr-r pr-deadline">{ds[k - 1]}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

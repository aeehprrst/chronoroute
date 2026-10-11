/**
 * Pure logic of the packet stepper: walks one packet through spec section 6 hop by hop,
 * calling the engine (ingressSend, processAtNode, linkDownFallback) at every node. The
 * arrival times and the down link are example inputs chosen by the reader; every outcome is
 * the engine's real output.
 */
import {
  decode,
  deadlines,
  deltasFwdOf,
  hexToBytes,
  ingressSend,
  linkDownFallback,
  processAtNode,
  sidsFwdOf,
  unitCodeOf,
  FLAG_DEV,
  FLAG_GREEDY,
  type Action,
  type Policy,
  type TcrhHeader,
} from '../../engine/tcrh';
import { MOD32, serialDiff, type UnitCode } from '../../engine/timebase';

export type StepKind = 'ingress' | 'node' | 'linkdown' | 'transit';

export interface TraceStep {
  kind: StepKind;
  title: string;
  sid: number | null;
  hopIndex: number | null;
  /** Arrival unit clock; null where it is not modelled. */
  nowU: number | null;
  deadlineU: number | null;
  /** serial_diff(now_u, D_k) when the deadline check ran. */
  diff: number | null;
  checked: boolean;
  late: boolean;
  action: Action | 'send' | 'transit';
  nextSid: number | null;
  slIn: number;
  slOut: number | null;
  flagsIn: number;
  flagsOut: number | null;
  devHopOut: number | null;
  bytesIn: Uint8Array;
  bytesOut: Uint8Array | null;
  changed: number[];
  notes: string[];
}

export type TraceResult =
  | {
      ok: true;
      header: TcrhHeader;
      unitCode: UnitCode;
      sidsFwd: number[];
      deadlines: number[];
      steps: TraceStep[];
    }
  | { ok: false; error: string };

export type Scenario = 'on-time' | 'slow' | 'down';

/** The hop whose incoming link is slow (or down) in the example scenarios: the middle of the path. */
export function middleHop(header: TcrhHeader): number {
  return Math.max(1, Math.ceil(header.numHops / 2));
}

/**
 * Example per-hop delays in deadline units. 'on-time' and 'down': each hop takes its budget
 * minus a fifth. 'slow': the same, except that the link into the middle hop is up but slow;
 * it adds enough queueing delay to use up the slack gathered so far and then miss by about
 * half that hop's budget.
 */
export function defaultDelays(header: TcrhHeader, scenario: Scenario): number[] {
  const budgets = deltasFwdOf(header);
  const onTime = budgets.map((d) => d - Math.floor(d / 5));
  if (scenario !== 'slow') return onTime;
  const m = middleHop(header);
  let slack = 0;
  for (let i = 0; i < m; i += 1) slack += (budgets[i] ?? 0) - (onTime[i] ?? 0);
  const extra = slack + Math.max(1, Math.ceil((budgets[m - 1] ?? 0) / 2));
  return onTime.map((d, i) => (i === m - 1 ? d + extra : d));
}

function changedBytes(a: Uint8Array, b: Uint8Array | null): number[] {
  if (!b) return [];
  const out: number[] = [];
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) if (a[i] !== b[i]) out.push(i);
  return out;
}

const units = (n: number): string => `${n} unit${n === 1 ? '' : 's'}`;

/**
 * @param linkDownInto hop k (1..h) whose incoming link is down, so the node before it (the
 *   ingress when k = 1) finds its next link down after step 5; null for no dead link.
 */
export function buildTrace(
  hex: string,
  delays: readonly number[],
  policy: Policy,
  linkDownInto: number | null = null,
): TraceResult {
  let bytes: Uint8Array;
  let header: TcrhHeader;
  try {
    bytes = hexToBytes(hex);
    header = decode(bytes);
  } catch (error) {
    return { ok: false, error: `The header does not decode: ${error instanceof Error ? error.message : String(error)}.` };
  }
  const h = header.numHops;
  if (header.segmentsLeft !== h || header.devHop !== 0 || (header.flags & (FLAG_DEV | FLAG_GREEDY)) !== 0) {
    return {
      ok: false,
      error: 'The stepper needs a fresh header: Segments Left equal to Num Hops, no DEV or GREEDY flag, Dev Hop 0.',
    };
  }
  if (delays.length !== h || delays.some((d) => !Number.isSafeInteger(d) || d < 0 || d > 100_000)) {
    return { ok: false, error: `Give one whole-number delay from 0 to 100000 units for each of the ${h} hops.` };
  }
  if (linkDownInto !== null && (!Number.isSafeInteger(linkDownInto) || linkDownInto < 1 || linkDownInto > h)) {
    return { ok: false, error: `The down link must lead into a hop from 1 to ${h}.` };
  }
  const sids = sidsFwdOf(header);
  const ds = deadlines(header);
  const steps: TraceStep[] = [];

  /** Step 7 at the node that just forwarded towards hop `into`; returns the fallback bytes. */
  const linkDown = (packet: Uint8Array, into: number): Uint8Array | null => {
    const res = linkDownFallback(packet);
    const flagsIn = packet[4] ?? 0;
    const hadDev = (flagsIn & FLAG_DEV) !== 0;
    const k = res.hopIndex ?? 0;
    const where = k === 0 ? 'the ingress' : `hop ${k}`;
    steps.push({
      kind: 'linkdown',
      title: `Link to SID ${sids[into - 1]} is down`,
      sid: k === 0 ? null : (sids[k - 1] ?? null),
      hopIndex: k,
      nowU: null,
      deadlineU: null,
      diff: null,
      checked: false,
      late: false,
      action: res.action,
      nextSid: res.nextSid,
      slIn: packet[3] ?? 0,
      slOut: res.outBytes ? (res.outBytes[3] ?? 0) : null,
      flagsIn,
      flagsOut: res.outBytes ? (res.outBytes[4] ?? 0) : null,
      devHopOut: res.outBytes ? (res.outBytes[6] ?? 0) : null,
      bytesIn: packet,
      bytesOut: res.outBytes,
      changed: changedBytes(packet, res.outBytes),
      notes: [
        `At ${where}, the forwarding entry for SID ${sids[into - 1]} exists but its link is down. No deadline can show this, so it is a deviation of its own (spec section 6 step 7).`,
        `${
          hadDev
            ? `DEV is already set, so Dev Hop stays ${packet[6] ?? 0}.`
            : `The node sets DEV and writes Dev Hop = ${k}${k === 0 ? ' (0 means the ingress)' : ''}.`
        } It sets GREEDY and Segments Left = 0 and heads for SID[0] = ${res.nextSid} with the fallback function, under every policy.`,
      ],
    });
    return res.outBytes;
  };

  /** Geographic forwarding to SID[0] and delivery there. */
  const fallbackTail = (out: Uint8Array) => {
    steps.push({
      kind: 'transit',
      title: 'Geographic forwarding',
      sid: null,
      hopIndex: null,
      nowU: null,
      deadlineU: null,
      diff: null,
      checked: false,
      late: false,
      action: 'transit',
      nextSid: sids[h - 1] ?? null,
      slIn: 0,
      slOut: 0,
      flagsIn: out[4] ?? 0,
      flagsOut: out[4] ?? 0,
      devHopOut: out[6] ?? 0,
      bytesIn: out,
      bytesOut: out,
      changed: [],
      notes: [
        'Satellites on the way see GREEDY and use the fallback function; they do not run the T-CRH steps and do not change the header.',
        'Which satellites the packet crosses, and when it arrives, depend on the inter-satellite link topology. This page does not model it, so no route or time is shown here.',
      ],
    });
    // DEV is set, so the endpoint does not check its deadline: its clock cannot change the outcome.
    const end = processAtNode(out, ds[h - 1] ?? 0, policy);
    steps.push({
      kind: 'node',
      title: `SID ${sids[h - 1]} · final endpoint`,
      sid: sids[h - 1] ?? null,
      hopIndex: end.hopIndex,
      nowU: null,
      deadlineU: end.deadlineU,
      diff: null,
      checked: false,
      late: end.late,
      action: end.action,
      nextSid: end.nextSid,
      slIn: 0,
      slOut: end.outBytes ? (end.outBytes[3] ?? 0) : null,
      flagsIn: out[4] ?? 0,
      flagsOut: end.outBytes ? (end.outBytes[4] ?? 0) : null,
      devHopOut: end.outBytes ? (end.outBytes[6] ?? 0) : null,
      bytesIn: out,
      bytesOut: end.outBytes,
      changed: changedBytes(out, end.outBytes),
      notes: [
        'Arrival time not modelled. It cannot change the outcome: DEV is set, so the endpoint does not check its deadline.',
        `Segments Left is 0: the endpoint delivers the packet. DEV and GREEDY are set, and Dev Hop = ${end.outBytes?.[6] ?? '?'} records where the plan broke.`,
      ],
    });
  };

  // Ingress: steps 5-6 only, no deadline check.
  const sent = ingressSend(bytes);
  steps.push({
    kind: 'ingress',
    title: 'Ingress ground station',
    sid: null,
    hopIndex: 0,
    nowU: null,
    deadlineU: null,
    diff: null,
    checked: false,
    late: false,
    action: 'send',
    nextSid: sent.firstSid,
    slIn: h,
    slOut: h - 1,
    flagsIn: header.flags,
    flagsOut: header.flags,
    devHopOut: 0,
    bytesIn: bytes,
    bytesOut: sent.outBytes,
    changed: changedBytes(bytes, sent.outBytes),
    notes: [
      `The ingress stamps Epoch_Base = ${header.epochBase} and writes the path with Segments Left = Num Hops = ${h}.`,
      `It decrements Segments Left to ${h - 1} and looks up SID[${h - 1}] = ${sent.firstSid}, the first hop. The ingress does not check a deadline.`,
    ],
  });

  let packet = sent.outBytes;
  if (linkDownInto === 1) {
    const out = linkDown(packet, 1);
    if (out) fallbackTail(out);
    return { ok: true, header, unitCode: unitCodeOf(header), sidsFwd: sids, deadlines: ds, steps };
  }

  let clock = header.epochBase;
  for (let k = 1; k <= h; k += 1) {
    clock += delays[k - 1] ?? 0;
    const nowU = clock % MOD32;
    const flagsIn = packet[4] ?? 0;
    const slIn = packet[3] ?? 0;
    const devHopIn = packet[6] ?? 0;
    const res = processAtNode(packet, nowU, policy);
    const checked = (flagsIn & FLAG_DEV) === 0;
    const deadlineU = res.deadlineU;
    const diff = checked && deadlineU !== null ? serialDiff(nowU, deadlineU) : null;
    const notes: string[] = [];
    if (checked && deadlineU !== null && diff !== null) {
      if (res.late) {
        notes.push(
          `Arrived in unit ${nowU}, ${units(diff)} after the deadline D_${k} = ${deadlineU}: late. The node sets DEV and writes Dev Hop = ${k}.`,
        );
      } else {
        notes.push(
          diff === 0
            ? `Arrived in unit ${nowU}, the deadline unit D_${k} itself: on time.`
            : `Arrived in unit ${nowU}, ${units(-diff)} before the deadline D_${k} = ${deadlineU}: on time.`,
        );
      }
    } else {
      notes.push(`DEV is already set (Dev Hop ${devHopIn}), so this node does not check its deadline again.`);
    }
    const flagsOut = res.outBytes ? (res.outBytes[4] ?? 0) : null;
    if (res.action === 'forward') {
      notes.push(
        `Segments Left ${slIn} → ${slIn - 1}; the node reads SID[${slIn - 1}] = ${res.nextSid} and forwards to it${
          policy === 'continue' && flagsOut !== null && (flagsOut & FLAG_DEV) !== 0
            ? ' (policy continue: the packet keeps following its SID list, DEV records the miss)'
            : ''
        }.`,
      );
    } else if (res.action === 'fallback') {
      notes.push(
        `Policy greedy: the node sets GREEDY, sets Segments Left to 0 and addresses the packet to SID[0] = ${res.nextSid}, the final endpoint. From here on the packet is forwarded geographically, not by its SID list.`,
      );
    } else if (res.action === 'drop_late') {
      notes.push('Policy drop: the node discards the packet. It is counted as late (strict).');
    } else if (res.action === 'deliver') {
      notes.push(
        `Segments Left is 0: this node is the final endpoint and delivers the packet${
          (flagsOut ?? 0) & FLAG_DEV ? '; DEV and Dev Hop record where the plan broke' : ''
        }.`,
      );
    }
    steps.push({
      kind: 'node',
      title: `Hop ${k} · SID ${sids[k - 1]}${k === h ? ' · final endpoint' : ''}`,
      sid: sids[k - 1] ?? null,
      hopIndex: res.hopIndex,
      nowU,
      deadlineU,
      diff,
      checked,
      late: res.late,
      action: res.action,
      nextSid: res.nextSid,
      slIn,
      slOut: res.outBytes ? (res.outBytes[3] ?? 0) : null,
      flagsIn,
      flagsOut,
      devHopOut: res.outBytes ? (res.outBytes[6] ?? 0) : null,
      bytesIn: packet,
      bytesOut: res.outBytes,
      changed: changedBytes(packet, res.outBytes),
      notes,
    });

    if (res.action === 'forward' && res.outBytes) {
      if (linkDownInto === k + 1) {
        const out = linkDown(res.outBytes, k + 1);
        if (out) fallbackTail(out);
        break;
      }
      packet = res.outBytes;
      continue;
    }
    if (res.action === 'fallback' && res.outBytes) fallbackTail(res.outBytes);
    break;
  }
  return { ok: true, header, unitCode: unitCodeOf(header), sidsFwd: sids, deadlines: ds, steps };
}

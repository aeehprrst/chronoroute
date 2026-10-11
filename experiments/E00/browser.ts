/** E0 adapter: run the production browser propagation and protocol engines. */
import { readFileSync, writeFileSync } from 'node:fs';
import { initSatrecs, propagateAllTemeKm } from '../../web/src/lib/orbit/propagate';
import { ecefFrameFromTeme } from '../../web/src/lib/route/frame';
import { ommRowsToRecords } from '../../web/src/lib/data';
import * as T from '../../web/src/engine/tcrh';
import * as C from '../../web/src/engine/crh';

const input = JSON.parse(readFileSync(process.argv[2]!, 'utf8'));
const cases = input.cases.map((c: any) => {
  let result: any;
  if (c.op === 'CE') {
    result = { hex: T.bytesToHex(C.encodeCrh(C.crhFromForward(c.sids, c.routing_type, c.nh))) };
  } else if (c.op === 'CP') {
    const r = C.crhProcessAtNode(T.hexToBytes(c.hex));
    result = { action: r.action, next_sid: r.nextSid, hex: r.outBytes ? T.bytesToHex(r.outBytes) : null,
      reason: r.reason, icmp_code: r.icmpCode, icmp_pointer: r.icmpPointer };
  } else if (c.op === 'B') {
    const h = T.buildHeader(c.sids, c.budgets.map(BigInt), BigInt(c.t), c.unit, c.nh);
    result = { hex: T.bytesToHex(T.encode(h)) };
  } else if (c.op === 'E') {
    let deltas = c.deltas;
    let flags = c.flags;
    if (c.budgets) {
      const encoded = T.encodeDeltas(c.budgets.map(BigInt), c.unit);
      deltas = encoded.deltas;
      if (encoded.sat) flags |= T.FLAG_SAT;
    }
    result = { hex: T.bytesToHex(T.encode(T.fromForward(c.sids, deltas, c.epoch, c.unit, c.nh, flags))) };
  } else if (c.op === 'I') {
    const r = T.ingressSend(T.hexToBytes(c.hex));
    result = { hex: T.bytesToHex(r.outBytes), first_sid: r.firstSid };
  } else {
    const r = c.op === 'L' ? T.linkDownFallback(T.hexToBytes(c.hex))
      : T.processAtNode(T.hexToBytes(c.hex), c.now, c.policy);
    result = { action: r.action, next_sid: r.nextSid, hex: r.outBytes ? T.bytesToHex(r.outBytes) : null,
      late: r.late, hop_index: r.hopIndex, deadline_u: r.deadlineU, reason: r.reason,
      icmp_code: r.icmpCode, icmp_pointer: r.icmpPointer };
  }
  return { id: c.id, ...result };
});
const orbits = input.orbits.map((o: any) => {
  const sources = { pinned: o.records, exported: ommRowsToRecords(o.omm_min) };
  const outputs: any = {};
  for (const [source, records] of Object.entries(sources)) {
    const { satrecs, errors } = initSatrecs(records as any);
    if (errors.length) throw new Error(JSON.stringify(errors));
    outputs[source] = o.times_ns.map((t: string) => {
      const ms = Number(BigInt(t) / 1000000n);
      const teme = new Float64Array(satrecs.length * 3);
      const failed = propagateAllTemeKm(satrecs, ms, teme);
      if (failed) throw new Error(`SGP4 failed for ${failed} satellites`);
      const ecef = ecefFrameFromTeme(teme, ms).ecefKm;
      if (![...ecef].every(Number.isFinite)) throw new Error('nonfinite ECEF');
      return Array.from({ length: satrecs.length }, (_, i) => [...ecef.slice(3 * i, 3 * i + 3)]);
    });
  }
  return { constellation: o.constellation, norads: o.records.map((r: any) => r.NORAD_CAT_ID), ...outputs };
});
writeFileSync(process.argv[3]!, JSON.stringify({ cases, orbits }) + '\n');

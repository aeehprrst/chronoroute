/**
 * The route parity gate, shared by tests/route-parity.test.ts (the deploy
 * gate itself) and tests/parity-gate.test.ts (which checks that the gate fails when it should).
 * Node only.
 *
 * A "run" is one Python parity file (tools/web_parity.py) plus the website inputs the
 * TypeScript planner reads for the same snapshot:
 *   reference  the experiments' pinned snapshot 20261010T1358Z; the inputs (shells, laser-link
 *              pairs, element sets, cities, SID registry) are the copies embedded in the parity
 *              file. A fixed yardstick: it does not move when new orbit data arrives.
 *   served     the snapshot this build publishes; the inputs are read from public/data exactly
 *              as the browser reads them (snapshots/<id>/shells.json, isl_grid4.json,
 *              omm.min.json, static/cities.csv, static/sid_registry.json), so a defect in the
 *              files actually served blocks the deploy as well.
 *
 * Positions: the planner runs on Python's positions for the satellites (frame.ecef_km) AND for
 * the cities (frame.city_ecef_km). The TypeScript geodetic -> ECEF conversion uses V8's
 * Math.sin/cos, which can differ from numpy's by one ulp (5 of the 60 cities do), and we do not
 * let that leak into the gate; the conversion is compared on its own, with a 1e-9 km tolerance.
 *
 * What fails a pair, and nothing else:
 *   * a path cost differing by more than 1 ns (a path on one side only counts as that);
 *   * any differing byte in the T-CRH template, the per-packet T-CRH, the IPv6 + T-CRH + UDP
 *     packet or its pcap file.
 * Same path: the bytes planRoute built are compared. Equal cost but a different path (a genuine
 * tie): the same bytes are rebuilt by the same function (planner.pathBytes) from Python's path
 * and compared, and the pair is counted as a TIE, never as an identical path.
 * Everything else (laser links up/down, visible and connected satellites, per-hop delays) is a
 * printed diagnostic.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { ommRowsToRecords, parseLatestPointer, parseManifest } from '../src/lib/data';
import type { OmmRecord } from '../src/lib/data-types';
import { parseCities, type City } from '../src/lib/route/cities';
import { buildRouteContext, flowStations, type RouteContext } from '../src/lib/route/context';
import { exactSlack, pathBytes, planRoute, type PathBytes, type PlanStation } from '../src/lib/route/planner';
import type { ParityRole, ParityRunSummary } from '../src/lib/route/parity-summary';
import { parseRegistry, type SidRegistry } from '../src/lib/route/sids';
import { parseIslDoc, parseShellsDoc, type IslDoc, type PositionFrame, type ShellsDoc } from '../src/lib/route/topology';
import { bytesToHex } from '../src/engine/tcrh';
import type { UnitCode } from '../src/engine/timebase';
import { framePositions, type ParityDoc, type ParityPair } from './parity-data';

export const COST_EPSILON_NS = 1;
export const DATA_DIR = path.resolve(import.meta.dirname, '..', 'public', 'data');

export interface ParityInputs {
  shells: ShellsDoc;
  isl: IslDoc;
  records: OmmRecord[];
  cities: City[];
  registry: SidRegistry;
}

/** What the served files say about themselves (checked against the parity file). */
export interface ServedFacts {
  webSnapshotId: string;
  fetchedUtc: string;
  source: string;
  sha256Raw: string;
  /** The raw topology documents, for the "same documents as Python" diagnostic. */
  shellsRaw: unknown;
  islRaw: unknown;
}

export interface ParityRun {
  role: ParityRole;
  doc: ParityDoc;
  /** Where the planner's inputs came from (shown in the test names). */
  inputsFrom: string;
  served: ServedFacts | null;
  ctx: RouteContext;
  frame: PositionFrame;
  tUnixNs: bigint;
}

export interface Outcome {
  pair: string;
  costOk: boolean;
  headerOk: boolean;
  samePath: boolean;
  tie: boolean;
  diagnostics: string[];
}

function makeRun(role: ParityRole, doc: ParityDoc, inputs: ParityInputs, inputsFrom: string, served: ServedFacts | null): ParityRun {
  return {
    role,
    doc,
    inputsFrom,
    served,
    ctx: buildRouteContext({ ...inputs, shellId: doc.shell_id }),
    frame: { ecefKm: framePositions(doc.frame.ecef_km) },
    tUnixNs: BigInt(doc.t_unix_ns),
  };
}

/** The reference run: the planner's inputs are the copies embedded in the parity file. */
export function referenceRun(doc: ParityDoc): ParityRun {
  const inputs: ParityInputs = {
    shells: parseShellsDoc(doc.shells),
    isl: parseIslDoc(doc.isl_grid4),
    records: ommRowsToRecords(JSON.parse(doc.omm_min)),
    cities: parseCities(doc.cities_csv),
    registry: parseRegistry(doc.sid_registry),
  };
  return makeRun('reference', doc, inputs, 'inputs embedded in the parity file', null);
}

/** The served run: the planner's inputs are the published files in dataDir (public/data). */
export function servedRun(doc: ParityDoc, dataDir: string = DATA_DIR): ParityRun {
  const read = (rel: string) => readFileSync(path.join(dataDir, rel), 'utf8');
  const pointer = parseLatestPointer(JSON.parse(read('latest.json')));
  const manifest = parseManifest(JSON.parse(read(`${pointer.path}manifest.json`)));
  const shellsRaw: unknown = JSON.parse(read(`${pointer.path}shells.json`));
  const islRaw: unknown = JSON.parse(read(`${pointer.path}isl_grid4.json`));
  const inputs: ParityInputs = {
    shells: parseShellsDoc(shellsRaw),
    isl: parseIslDoc(islRaw),
    records: ommRowsToRecords(JSON.parse(read(`${pointer.path}${manifest.files.omm}`))),
    cities: parseCities(read('static/cities.csv')),
    registry: parseRegistry(JSON.parse(read('static/sid_registry.json'))),
  };
  const served: ServedFacts = {
    webSnapshotId: manifest.snapshot_id,
    fetchedUtc: manifest.fetched_utc,
    source: manifest.source,
    sha256Raw: manifest.sha256_raw,
    shellsRaw,
    islRaw,
  };
  return makeRun('served', doc, inputs, `published files in ${path.relative(process.cwd(), dataDir) || '.'}`, served);
}

/**
 * The two ground stations of a pair, with Python's city positions (frame.city_ecef_km) in place
 * of our own geodetic -> ECEF conversion. Latitude and longitude stay ours (the elevation test
 * uses them for the local "up" direction, which is part of the code under test).
 */
export function runStations(run: ParityRun, src: string, dst: string): [PlanStation, PlanStation] {
  const pin = (s: PlanStation): PlanStation => {
    const xyz = run.doc.frame.city_ecef_km[s.name];
    if (!xyz) throw new Error(`${s.name}: the parity file has no position for this city`);
    return { ...s, ecefKm: [xyz[0], xyz[1], xyz[2]] };
  };
  const [a, b] = flowStations(run.ctx, src, dst);
  return [pin(a), pin(b)];
}

const sameList = (a: readonly number[], b: readonly number[]) => a.length === b.length && a.every((x, i) => x === b[i]);

/** True when all four byte strings equal Python's. */
function bytesMatch(mine: Pick<PathBytes, 'templateBytes' | 'headerBytes' | 'packetBytes' | 'pcapBytes'>, py: ParityPair): boolean {
  return (
    bytesToHex(mine.templateBytes) === py.template_hex &&
    bytesToHex(mine.headerBytes) === py.header_hex &&
    bytesToHex(mine.packetBytes) === py.packet_hex &&
    bytesToHex(mine.pcapBytes) === py.pcap_hex
  );
}

/** Plan one pair with the TypeScript planner and compare it with Python's answer. */
export function comparePair(run: ParityRun, py: ParityPair): Outcome {
  const { ctx, doc } = run;
  const label = `${py.src} -> ${py.dst}`;
  const [src, dst] = runStations(run, py.src, py.dst);
  const unitCode = doc.unit_code as UnitCode;
  const plan = planRoute(ctx.net, run.frame, ctx.sats, src, dst, run.tUnixNs, { slack: doc.slack, unitCode });
  const diagnostics: string[] = [];

  // --- diagnostics (never block a deploy on their own) ---
  if (src.g !== py.src_g || dst.g !== py.dst_g) diagnostics.push('ground station numbers differ');
  const down = ctx.net.islA.reduce<string[]>((acc, a, i) => {
    if (!plan.instant.isl.up[i]) acc.push(`${ctx.net.norads[a]}-${ctx.net.norads[ctx.net.islB[i]!]}`);
    return acc;
  }, []);
  const pyDown = doc.frame.isl_down.map(([a, b]) => `${a}-${b}`);
  if (down.join() !== pyDown.join()) diagnostics.push(`laser links down: TS [${down.join(' ')}] Python [${pyDown.join(' ')}]`);
  ([0, 1] as const).forEach((which) => {
    const name = which === 0 ? py.src : py.dst;
    const links = plan.instant.gsl[which];
    const vis = links.visible.map((n) => ctx.net.norads[n]!).sort((a, b) => a - b);
    const sel = links.selected.map((n) => ctx.net.norads[n]!).sort((a, b) => a - b);
    if (!sameList(vis, py.gsl[name]!.visible)) diagnostics.push(`${name}: visible satellites differ`);
    if (!sameList(sel, py.gsl[name]!.selected)) diagnostics.push(`${name}: connected satellites differ`);
  });

  // --- the gate ---
  let costOk: boolean;
  let headerOk = true;
  let samePath = false;
  let tie = false;
  if (!py.reachable) {
    costOk = !plan.reachable;
    if (plan.reachable) diagnostics.push(`TS found a path (${plan.costNs} ns), Python none`);
  } else if (!plan.reachable) {
    costOk = false;
    diagnostics.push(`Python found a path (${py.cost_ns} ns), TS none`);
  } else {
    costOk = Math.abs(plan.costNs - py.cost_ns!) <= COST_EPSILON_NS;
    samePath = sameList(plan.path, py.path_nodes!);
    if (samePath) {
      if (!sameList(plan.hopDelaysNs, py.hop_delays_ns!)) diagnostics.push('per-hop delays differ');
      if (!sameList(plan.sidsFwd, py.sids_fwd!)) diagnostics.push('SIDs differ');
      headerOk = bytesMatch(plan, py);
    } else {
      // Different path. Within 1 ns: a genuine tie, which the gate accepts; the encoder is
      // still compared, on Python's path, with the planner's own byte builder.
      tie = costOk;
      diagnostics.push(
        `${tie ? 'tie: equal-cost' : 'different'} paths (TS ${plan.path.join(' ')} = ${plan.costNs} ns / ` +
          `Python ${py.path_nodes!.join(' ')} = ${py.cost_ns} ns)`,
      );
      const rebuilt = pathBytes(py.sids_fwd!, py.hop_delays_ns!, exactSlack(doc.slack), BigInt(doc.t_gps_ns), unitCode, src.sid, dst.sid);
      headerOk = bytesMatch(rebuilt, py);
    }
  }
  return { pair: label, costOk, headerOk, samePath, tie, diagnostics };
}

/** The run's line in public/data/parity.json. */
export function summarizeRun(run: ParityRun, outcomes: readonly Outcome[]): ParityRunSummary {
  return {
    role: run.role,
    snapshot_id: run.doc.snapshot_id,
    web_snapshot_id: run.served?.webSnapshotId ?? null,
    t_utc: run.doc.t_utc,
    shell_id: run.doc.shell_id,
    pairs: outcomes.length,
    reachable: run.doc.pairs.filter((p) => p.reachable).length,
    identical_paths: outcomes.filter((o) => o.samePath && o.costOk && o.headerOk).length,
    ties: outcomes.filter((o) => o.tie && o.headerOk).length,
    mismatches: outcomes.filter((o) => !o.costOk || !o.headerOk).length,
    pairs_with_diagnostics: outcomes.filter((o) => o.diagnostics.length > 0).length,
  };
}

/** A topology document without its snapshot_id (the served copy names the website snapshot). */
export function withoutSnapshotId(doc: unknown): unknown {
  if (!doc || typeof doc !== 'object') return doc;
  const { snapshot_id: _ignored, ...rest } = doc as Record<string, unknown>;
  return rest;
}

/**
 * From two cities and an instant to the T-CRH bytes: the route planner's core, a port of
 * sim/chronoroute/route/scheduler.py plan_path() + route/command.py route_report().
 *
 *   1. Path: canonical Dijkstra (dijkstra.ts) on the graph of the instant (topology.ts):
 *      source city -> satellites -> destination city.
 *   2. Predicted delay of hop k: the edge weight, i.e. light time round(d/c) + 0.5 ms
 *      processing, integer ns (taken as dist[v] - dist[u] along the path, as Python does).
 *   3. Cumulative budget with multiplicative slack S: B_k = S * (d_1 + ... + d_k), an exact
 *      rational ("1.5" is exactly 3/2; never a binary float).
 *   4. Header: the existing TypeScript T-CRH engine (src/engine/tcrh.ts buildHeader) with the
 *      ceil-cumulative deltas of spec section 5.1. The template has Epoch_Base = 0; the packet
 *      entering at the chosen instant carries Epoch_Base = ceil(T_gps / u) mod 2^32.
 *   5. Packet and pcap (src/engine/packet.ts), as chronoroute.trace.pcap builds them.
 *
 * Labels: positions REAL (SGP4 on REAL elements), shells/planes DERIVED, laser links MODELLED,
 * ground-link mask ASSUMED / assignment MODELLED, processing delay MODELLED, the route and
 * its budgets DERIVED, the header bytes REAL output of the real encoder. The path is
 * hypothetical: Starlink's routing is not public and does not use T-CRH.
 */
import { dijkstra, pathTo } from './dijkstra';
import { PROCESSING_NS, distanceKm, greatCircleKm, lightTimeNsExact, type Vec3 } from './geometry';
import {
  DEFAULT_GSL,
  buildInstantNetwork,
  satPos,
  type GroundLinks,
  type GslParams,
  type InstantNetwork,
  type PositionFrame,
  type ShellNetwork,
  type Station,
} from './topology';
import { buildHeader, deadlines, encode, encodeDeltas, isSat, type TcrhHeader } from '../../engine/tcrh';
import {
  epochBaseAtIngress,
  parseDecimal,
  ratio,
  ratioCeilDiv,
  ratioMul,
  unitNsBig,
  type Ratio,
  type UnitCode,
} from '../../engine/timebase';
import { HOST_SRC, packetWithRoutingHeader, payloadBytes, pcapFile, sidAddress } from '../../engine/packet';
import { crh16Size, crh32Size, srhSize, tcrhSize } from '../../engine/sizes';

export const DEFAULT_SLACK = '1.5';
export const DEFAULT_UNIT_CODE: UnitCode = 1;
export const DEFAULT_NEXT_HEADER = 17;

const UNIX_TO_GPS_EPOCH_S = 315_964_800n;
const GPS_UTC_OFFSET_S = 18n;
const NS_PER_S = 1_000_000_000n;
/** GPS = UTC + 18 s holds from 2017-01-01T00:00:00Z on. */
const GPS_VALID_FROM_UNIX_NS = 1_483_228_800n * NS_PER_S;

/** UTC ns since 1970 -> GPS ns since 1980-01-06 (scheduler.utc_ns_to_gps_ns). */
export function utcNsToGpsNs(utcNs: bigint): bigint {
  if (utcNs < GPS_VALID_FROM_UNIX_NS) throw new RangeError('GPS = UTC + 18 s only holds from 2017-01-01T00:00:00Z on');
  return utcNs - UNIX_TO_GPS_EPOCH_S * NS_PER_S + GPS_UTC_OFFSET_S * NS_PER_S;
}

/** The slack factor S as an exact positive rational, from its decimal text ("1.5" -> 3/2). */
export function exactSlack(text: string): Ratio {
  const value = parseDecimal(text);
  if (value === null || value.num <= 0n) throw new RangeError(`slack must be a positive decimal number, got ${JSON.stringify(text)}`);
  return value;
}

/** B_k = S * (d_1 + ... + d_k) as exact rationals (ns). */
export function cumulativeBudgets(hopDelaysNs: readonly number[], slack: Ratio): Ratio[] {
  let running = 0n;
  return hopDelaysNs.map((d) => {
    if (!Number.isSafeInteger(d) || d < 0) throw new RangeError(`hop delays must be non-negative integer ns, got ${d}`);
    running += BigInt(d);
    return ratioMul(ratio(running), slack);
  });
}

/** Per-satellite facts the planner shows (node order = ShellNetwork.norads). */
export interface SatelliteInfo {
  sids: readonly number[];
  provisional: readonly boolean[];
  names: readonly string[];
}

export interface PlanStation extends Station {
  provisional: boolean;
}

export interface PlanOptions {
  slack?: string;
  unitCode?: UnitCode;
  gsl?: GslParams;
  processingNs?: number;
}

export interface RouteHop {
  /** 1..h */
  k: number;
  node: number;
  kind: 'sat' | 'gs';
  norad: number | null;
  name: string;
  sid: number;
  provisional: boolean;
  /** Straight-line distance from the previous node (km), for display. */
  distanceKm: number;
  propNs: number;
  hopDelayNs: number;
  /** B_k - B_(k-1), exact. */
  budgetStepNs: Ratio;
  /** B_k, exact. */
  budgetNs: Ratio;
  /** ceil(B_k) ns. */
  budgetCeilNs: bigint;
  deltaUnits: number;
  /** D_k = Epoch_Base + delta_1 + ... + delta_k (mod 2^32), in units. */
  deadlineU: number;
  /** (D_k - Epoch_Base) * u: how long after the ingress unit the deadline falls (ns). */
  deadlineAfterEpochNs: bigint;
}

interface PlanCommon {
  instant: InstantNetwork;
  src: PlanStation;
  dst: PlanStation;
  tUnixNs: bigint;
  tGpsNs: bigint;
  greatCircleKm: number;
  /** Great-circle distance / c, ns (float): the light-speed lower bound. */
  boundNs: number;
  islUp: number;
  islTotal: number;
}

export type RoutePlan =
  | (PlanCommon & { reachable: false })
  | (PlanCommon & {
      reachable: true;
      path: number[];
      costNs: number;
      hops: RouteHop[];
      sidsFwd: number[];
      hopDelaysNs: number[];
      propNs: number[];
      budgets: Ratio[];
      budgetsCeilNs: bigint[];
      slack: Ratio;
      unitCode: UnitCode;
      header: TcrhHeader;
      templateBytes: Uint8Array;
      headerBytes: Uint8Array;
      packetBytes: Uint8Array;
      pcapBytes: Uint8Array;
      epochBase: number;
      sat: boolean;
      lightTimeNs: number;
      sizes: { hops: number; tcrh: number; crh16: number; crh32: number; srh: number };
    });

function ceilRatio(r: Ratio): bigint {
  return ratioCeilDiv(r, 1n);
}

/** Everything that is built from a path's SIDs and hop delays: budgets, T-CRH and packet bytes. */
export interface PathBytes {
  budgets: Ratio[];
  header: TcrhHeader;
  /** The T-CRH template (Epoch_Base = 0), as the scheduler stores it. */
  templateBytes: Uint8Array;
  /** The T-CRH of the packet entering at tGpsNs. */
  headerBytes: Uint8Array;
  /** IPv6 + T-CRH + UDP: host -> ingress ground station, checksum over the final destination. */
  packetBytes: Uint8Array;
  /** A one-frame classic pcap of packetBytes, time-stamped at tGpsNs. */
  pcapBytes: Uint8Array;
}

/**
 * Budgets, header and packet for one path (steps 3 to 5 above). One function for both the
 * planner and the parity gate: on a genuine tie (equal cost, different path) the gate builds
 * Python's path with exactly this code, so the encoder is still compared byte for byte.
 */
export function pathBytes(
  sidsFwd: readonly number[],
  hopDelaysNs: readonly number[],
  slack: Ratio,
  tGpsNs: bigint,
  unitCode: UnitCode,
  srcSid: number,
  dstSid: number,
): PathBytes {
  const budgets = cumulativeBudgets(hopDelaysNs, slack);
  const header = buildHeader(sidsFwd, budgets, tGpsNs, unitCode, DEFAULT_NEXT_HEADER);
  const headerBytes = encode(header);
  const templateBytes = encode(buildHeader(sidsFwd, budgets, 0n, unitCode, DEFAULT_NEXT_HEADER));
  const packetBytes = packetWithRoutingHeader(headerBytes, {
    src: HOST_SRC,
    dst: sidAddress(srcSid),
    finalDst: sidAddress(dstSid),
    payload: payloadBytes(0, tGpsNs),
  });
  return { budgets, header, templateBytes, headerBytes, packetBytes, pcapBytes: pcapFile([{ packet: packetBytes, tGpsNs }]) };
}

function ratioSub(a: Ratio, b: Ratio): Ratio {
  return ratio(a.num * b.den - b.num * a.den, a.den * b.den);
}

/** Plan one route at one instant. Never throws for "no path": returns reachable = false. */
export function planRoute(
  net: ShellNetwork,
  frame: PositionFrame,
  sats: SatelliteInfo,
  src: PlanStation,
  dst: PlanStation,
  tUnixNs: bigint,
  options: PlanOptions = {},
): RoutePlan {
  const slack = exactSlack(options.slack ?? DEFAULT_SLACK);
  const unitCode = options.unitCode ?? DEFAULT_UNIT_CODE;
  const processingNs = options.processingNs ?? PROCESSING_NS;
  const S = net.norads.length;
  if (sats.sids.length !== S || sats.names.length !== S || sats.provisional.length !== S) {
    throw new RangeError('satellite info must have one entry per satellite node');
  }
  const instant = buildInstantNetwork(net, frame, src, dst, options.gsl ?? DEFAULT_GSL, processingNs);
  const tGpsNs = utcNsToGpsNs(tUnixNs);
  const gc = greatCircleKm(src.latDeg, src.lonDeg, dst.latDeg, dst.lonDeg);
  const common: PlanCommon = {
    instant,
    src,
    dst,
    tUnixNs,
    tGpsNs,
    greatCircleKm: gc,
    boundNs: lightTimeNsExact(gc),
    islUp: instant.isl.up.reduce((n, u) => n + u, 0),
    islTotal: instant.isl.up.length,
  };
  const sp = dijkstra(instant.graph, instant.srcNode, instant.dstNode);
  const path = pathTo(sp, instant.dstNode);
  if (path === null) return { ...common, reachable: false };

  const dist = (v: number) => sp.dist[v]!;
  const hopDelaysNs = path.slice(1).map((v, i) => dist(v) - dist(path[i]!));
  const propNs = hopDelaysNs.map((d) => d - processingNs);
  const nodeSid = (v: number) => (v < S ? sats.sids[v]! : v === instant.srcNode ? src.sid : dst.sid);
  const sidsFwd = path.slice(1).map(nodeSid);
  const { budgets, header, templateBytes, headerBytes, packetBytes, pcapBytes } = pathBytes(
    sidsFwd,
    hopDelaysNs,
    slack,
    tGpsNs,
    unitCode,
    src.sid,
    dst.sid,
  );
  const { deltas } = encodeDeltas(budgets, unitCode);
  const ds = deadlines(header);
  const u = unitNsBig(unitCode);
  const epochBase = epochBaseAtIngress(tGpsNs, unitCode);
  const pos = (v: number): Vec3 => (v < S ? satPos(frame, v) : v === instant.srcNode ? src.ecefKm : dst.ecefKm);
  let previous = ratio(0n);
  const hops: RouteHop[] = path.slice(1).map((v, i) => {
    const b = budgets[i]!;
    const step = ratioSub(b, previous);
    previous = b;
    const deadlineU = ds[i]!;
    const afterUnits = BigInt((((deadlineU - epochBase) % 2 ** 32) + 2 ** 32) % 2 ** 32);
    const isSatNode = v < S;
    return {
      k: i + 1,
      node: v,
      kind: isSatNode ? 'sat' : 'gs',
      norad: isSatNode ? net.norads[v]! : null,
      name: isSatNode ? sats.names[v]! : v === instant.srcNode ? src.name : dst.name,
      sid: sidsFwd[i]!,
      provisional: isSatNode ? sats.provisional[v]! : (v === instant.srcNode ? src : dst).provisional,
      distanceKm: distanceKm(pos(path[i]!), pos(v)),
      propNs: propNs[i]!,
      hopDelayNs: hopDelaysNs[i]!,
      budgetStepNs: step,
      budgetNs: b,
      budgetCeilNs: ceilRatio(b),
      deltaUnits: deltas[i]!,
      deadlineU,
      deadlineAfterEpochNs: afterUnits * u,
    };
  });
  const h = sidsFwd.length;
  return {
    ...common,
    reachable: true,
    path,
    costNs: dist(instant.dstNode),
    hops,
    sidsFwd,
    hopDelaysNs,
    propNs,
    budgets,
    budgetsCeilNs: budgets.map(ceilRatio),
    slack,
    unitCode,
    header,
    templateBytes,
    headerBytes,
    packetBytes,
    pcapBytes,
    epochBase,
    sat: isSat(header),
    lightTimeNs: propNs.reduce((a, b) => a + b, 0),
    sizes: { hops: h, tcrh: tcrhSize(h), crh16: crh16Size(h), crh32: crh32Size(h), srh: srhSize(h) },
  };
}

/** Ground links of one city in the plan (index 0 = source, 1 = destination). */
export function stationLinks(plan: RoutePlan, which: 0 | 1): GroundLinks {
  return plan.instant.gsl[which];
}

/**
 * The network the route planner searches, at one instant: the shell's satellites, their
 * Grid-4 laser links (from isl_grid4.json) and the two cities' ground links.
 *
 * Port of the Python model (sim/chronoroute/topo/graph.py build_scenario, isl_grid4.isl_state,
 * gsl.select_links). What comes from where:
 *
 *   satellites        every satellite in an orbital plane of the shell (shells.json, DERIVED),
 *                     node id = rank by NORAD id (0 .. S-1), as in Python
 *   laser-link pairs  isl_grid4.json (MODELLED): chosen once by Python at the snapshot's
 *                     reference instant; NOT re-computed here (the plan's design: the browser
 *                     never re-implements the plane clustering)
 *   link up/down      evaluated HERE at the chosen instant with Python's rules:
 *                       cross-plane pair down while |latitude| of either end > 70 deg,
 *                       any pair down while its line of sight dips below 80 km above WGS84,
 *                       any pair down when a position is missing (SGP4 failed),
 *                       optional range limit (null in the published model)
 *   ground links      25 deg elevation mask (ASSUMED), at most 4 satellites per city: the
 *                     highest elevations, ties to the lower node id (MODELLED). For a single
 *                     instant Python's "sticky_top_k" and "highest_elevation_top_k" policies
 *                     pick exactly this set (stickiness only acts from the second step on).
 *   ground stations   node ids S (source) and S+1 (destination), as in `cr route`; they may
 *                     start or end a path but never relay one.
 *   edge weight       round(distance / c) to the nearest ns + 500,000 ns processing (integers).
 */
import {
  PROCESSING_NS,
  distanceKm,
  ecefToGeodetic,
  elevationDeg,
  propagationNs,
  segmentClears,
  type Vec3,
} from './geometry';

export const SHELLS_SCHEMA = 'chronoroute.web-shells/1';
export const ISL_SCHEMA = 'chronoroute.web-isl-grid4/1';
export const KIND_INTRA = 0;
export const KIND_CROSS = 1;
export const KIND_GSL = 2;
export const MAX_ISL_DEGREE = 4;

export class TopologyError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'TopologyError';
  }
}

type Json = Record<string, unknown>;
const isObject = (v: unknown): v is Json => typeof v === 'object' && v !== null && !Array.isArray(v);
const isInt = (v: unknown): v is number => typeof v === 'number' && Number.isSafeInteger(v);

function need(cond: unknown, message: string): asserts cond {
  if (!cond) throw new TopologyError(message);
}

// ------------------------------------------------------------------ shells.json

export interface ShellEntry {
  shell_id: string;
  layer: string;
  inclination_deg: number;
  altitude_km: number;
  count: number;
  n_planes: number;
  off_grid: number;
  quality: number;
  shares_planes_with: string | null;
  /** One list per plane (RAAN order), NORAD ids in slot order. */
  planes: number[][];
  off_grid_norads: number[];
}

export interface ShellsDoc {
  schema: typeof SHELLS_SCHEMA;
  snapshot_id: string;
  reference_utc: string;
  label: 'DERIVED';
  note: string;
  shells: ShellEntry[];
  in_transit: number[];
}

function intList(v: unknown, where: string): number[] {
  need(Array.isArray(v) && v.every((x) => isInt(x) && x > 0), `${where} must be a list of positive integers`);
  return v as number[];
}

/** Validate shells.json (schema chronoroute.web-shells/1, written by `cr export web`). */
export function parseShellsDoc(value: unknown): ShellsDoc {
  need(isObject(value), 'shells.json: not a JSON object');
  need(value['schema'] === SHELLS_SCHEMA, `shells.json: schema must be "${SHELLS_SCHEMA}"`);
  need(value['label'] === 'DERIVED', 'shells.json: label must be DERIVED');
  need(typeof value['snapshot_id'] === 'string', 'shells.json: snapshot_id must be a string');
  need(typeof value['reference_utc'] === 'string', 'shells.json: reference_utc must be a string');
  need(Array.isArray(value['shells']), 'shells.json: shells must be a list');
  const shells = (value['shells'] as unknown[]).map((s, i): ShellEntry => {
    const where = `shells.json shells[${i}]`;
    need(isObject(s) && typeof s['shell_id'] === 'string', `${where}: shell_id missing`);
    need(Array.isArray(s['planes']), `${where}: planes must be a list`);
    const planes = (s['planes'] as unknown[]).map((p, j) => intList(p, `${where}.planes[${j}]`));
    return {
      shell_id: s['shell_id'] as string,
      layer: String(s['layer']),
      inclination_deg: Number(s['inclination_deg']),
      altitude_km: Number(s['altitude_km']),
      count: Number(s['count']),
      n_planes: Number(s['n_planes']),
      off_grid: Number(s['off_grid']),
      quality: Number(s['quality']),
      shares_planes_with: typeof s['shares_planes_with'] === 'string' ? (s['shares_planes_with'] as string) : null,
      planes,
      off_grid_norads: intList(s['off_grid_norads'] ?? [], `${where}.off_grid_norads`),
    };
  });
  return {
    schema: SHELLS_SCHEMA,
    snapshot_id: value['snapshot_id'] as string,
    reference_utc: value['reference_utc'] as string,
    label: 'DERIVED',
    note: String(value['note'] ?? ''),
    shells,
    in_transit: intList(value['in_transit'] ?? [], 'shells.json in_transit'),
  };
}

// ------------------------------------------------------------------ isl_grid4.json

export interface IslModel {
  name: string;
  polar_cutoff_deg: number;
  min_grazing_alt_km: number;
  cross_max_du_factor: number;
  max_range_km: number | null;
  max_degree: number;
  inter_shell_links: boolean;
}

export interface IslShell {
  shell_id: string;
  layer: string;
  max_cross_du_deg: number;
  /** [a, b] NORAD ids, a < b, sorted. */
  intra: Array<[number, number]>;
  cross: Array<[number, number]>;
}

export interface IslDoc {
  schema: typeof ISL_SCHEMA;
  snapshot_id: string;
  reference_utc: string;
  label: 'MODELLED';
  note: string;
  model: IslModel;
  shells: IslShell[];
}

function pairList(v: unknown, where: string): Array<[number, number]> {
  need(Array.isArray(v), `${where} must be a list`);
  let prev: [number, number] | null = null;
  return (v as unknown[]).map((p, i) => {
    need(Array.isArray(p) && p.length === 2 && isInt(p[0]) && isInt(p[1]), `${where}[${i}] must be [a, b]`);
    const pair: [number, number] = [p[0] as number, p[1] as number];
    need(pair[0] > 0 && pair[0] < pair[1], `${where}[${i}]: NORAD ids must satisfy 0 < a < b`);
    need(prev === null || prev[0] < pair[0] || (prev[0] === pair[0] && prev[1] < pair[1]), `${where} must be sorted without duplicates`);
    prev = pair;
    return pair;
  });
}

/** Validate isl_grid4.json (schema chronoroute.web-isl-grid4/1, written by `cr export web`). */
export function parseIslDoc(value: unknown): IslDoc {
  need(isObject(value), 'isl_grid4.json: not a JSON object');
  need(value['schema'] === ISL_SCHEMA, `isl_grid4.json: schema must be "${ISL_SCHEMA}"`);
  need(value['label'] === 'MODELLED', 'isl_grid4.json: label must be MODELLED');
  const m = value['model'];
  need(isObject(m), 'isl_grid4.json: model must be an object');
  const num = (k: string) => {
    need(typeof m[k] === 'number' && Number.isFinite(m[k]), `isl_grid4.json: model.${k} must be a number`);
    return m[k] as number;
  };
  const range = m['max_range_km'];
  need(range === null || (typeof range === 'number' && range > 0), 'isl_grid4.json: model.max_range_km must be null or > 0');
  need(m['inter_shell_links'] === false, 'isl_grid4.json: only models without inter-shell links are supported');
  const model: IslModel = {
    name: String(m['name']),
    polar_cutoff_deg: num('polar_cutoff_deg'),
    min_grazing_alt_km: num('min_grazing_alt_km'),
    cross_max_du_factor: num('cross_max_du_factor'),
    max_range_km: range as number | null,
    max_degree: num('max_degree'),
    inter_shell_links: false,
  };
  need(Array.isArray(value['shells']), 'isl_grid4.json: shells must be a list');
  const shells = (value['shells'] as unknown[]).map((s, i): IslShell => {
    const where = `isl_grid4.json shells[${i}]`;
    need(isObject(s) && typeof s['shell_id'] === 'string', `${where}: shell_id missing`);
    return {
      shell_id: s['shell_id'] as string,
      layer: String(s['layer']),
      max_cross_du_deg: Number(s['max_cross_du_deg']),
      intra: pairList(s['intra'], `${where}.intra`),
      cross: pairList(s['cross'], `${where}.cross`),
    };
  });
  need(typeof value['snapshot_id'] === 'string' && typeof value['reference_utc'] === 'string', 'isl_grid4.json: snapshot_id/reference_utc missing');
  return {
    schema: ISL_SCHEMA,
    snapshot_id: value['snapshot_id'] as string,
    reference_utc: value['reference_utc'] as string,
    label: 'MODELLED',
    note: String(value['note'] ?? ''),
    model,
    shells,
  };
}

// ------------------------------------------------------------------ the shell's network

export interface ShellNetwork {
  shellId: string;
  /** In-plane satellites, ascending NORAD id; node id = index. */
  norads: readonly number[];
  nodeOf: ReadonlyMap<number, number>;
  /** Candidate laser links as node ids (a < b), sorted by (a, b), with their kind. */
  islA: Int32Array;
  islB: Int32Array;
  islKind: Uint8Array;
  model: IslModel;
  referenceUtc: string;
  /** Satellites of the shell left out because they are in no plane (no Grid-4 slot). */
  offGrid: number;
  nPlanes: number;
}

/**
 * The shell's satellites and candidate laser links. Refuses files that do not belong
 * together (different snapshots or reference instants), pairs that name a satellite outside
 * the shell's planes, duplicates, and any satellite with more than 4 laser links.
 */
export function buildShellNetwork(shells: ShellsDoc, isl: IslDoc, shellId: string): ShellNetwork {
  need(shells.snapshot_id === isl.snapshot_id, 'shells.json and isl_grid4.json come from different snapshots');
  need(shells.reference_utc === isl.reference_utc, 'shells.json and isl_grid4.json have different reference times');
  const shell = shells.shells.find((s) => s.shell_id === shellId);
  const islShell = isl.shells.find((s) => s.shell_id === shellId);
  need(shell !== undefined, `shells.json has no shell ${shellId}`);
  need(islShell !== undefined, `isl_grid4.json has no shell ${shellId}`);
  const members = new Set<number>();
  for (const plane of shell.planes) {
    for (const n of plane) {
      need(!members.has(n), `NORAD ${n} appears in two planes of ${shellId}`);
      members.add(n);
    }
  }
  need(members.size > 0, `shell ${shellId} has no satellites in planes`);
  const norads = [...members].sort((a, b) => a - b);
  const nodeOf = new Map<number, number>(norads.map((n, i) => [n, i]));
  const rows: Array<[number, number, number]> = [];
  for (const [kind, list] of [
    [KIND_INTRA, islShell.intra],
    [KIND_CROSS, islShell.cross],
  ] as const) {
    for (const [a, b] of list) {
      const ia = nodeOf.get(a);
      const ib = nodeOf.get(b);
      need(ia !== undefined && ib !== undefined, `laser-link pair [${a}, ${b}] names a satellite outside the planes of ${shellId}`);
      rows.push([ia, ib, kind]);
    }
  }
  // Node ids rise with NORAD ids, so (a, b) order is NORAD order; sort for a canonical list.
  rows.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  const degree = new Uint8Array(norads.length);
  for (let i = 0; i < rows.length; i += 1) {
    const r = rows[i]!;
    if (i > 0) {
      const p = rows[i - 1]!;
      need(p[0] !== r[0] || p[1] !== r[1], `laser-link pair listed twice (nodes ${r[0]}, ${r[1]})`);
    }
    degree[r[0]] = (degree[r[0]] ?? 0) + 1;
    degree[r[1]] = (degree[r[1]] ?? 0) + 1;
  }
  need(degree.every((d) => d <= MAX_ISL_DEGREE), 'a satellite has more than 4 Grid-4 links');
  return {
    shellId,
    norads,
    nodeOf,
    islA: Int32Array.from(rows, (r) => r[0]),
    islB: Int32Array.from(rows, (r) => r[1]),
    islKind: Uint8Array.from(rows, (r) => r[2]),
    model: isl.model,
    referenceUtc: isl.reference_utc,
    offGrid: shell.off_grid,
    nPlanes: shell.planes.length,
  };
}

// ------------------------------------------------------------------ one instant

/** Positions of the shell's satellites at one instant: ECEF km, 3 per node, NaN = no position. */
export interface PositionFrame {
  ecefKm: Float64Array;
  /** Geodetic latitude (deg) per node; computed from ecefKm when not given. */
  latDeg?: Float64Array;
}

export function satPos(frame: PositionFrame, node: number): Vec3 {
  const o = node * 3;
  return [frame.ecefKm[o]!, frame.ecefKm[o + 1]!, frame.ecefKm[o + 2]!];
}

/** Geodetic latitude of every node (NaN where the position is missing), as Python's SatelliteArray. */
export function latitudesDeg(ecefKm: Float64Array): Float64Array {
  const n = ecefKm.length / 3;
  const out = new Float64Array(n);
  for (let i = 0; i < n; i += 1) {
    out[i] = ecefToGeodetic(ecefKm[3 * i]!, ecefKm[3 * i + 1]!, ecefKm[3 * i + 2]!).latDeg;
  }
  return out;
}

export interface IslState {
  up: Uint8Array;
  distKm: Float64Array;
}

/** Up/down and length of every candidate laser link (isl_grid4.isl_state, one time step). */
export function islState(net: ShellNetwork, frame: PositionFrame): IslState {
  const lat = frame.latDeg ?? latitudesDeg(frame.ecefKm);
  const L = net.islA.length;
  const up = new Uint8Array(L);
  const distKm = new Float64Array(L);
  const { polar_cutoff_deg: polar, min_grazing_alt_km: grazing, max_range_km: range } = net.model;
  for (let i = 0; i < L; i += 1) {
    const a = net.islA[i]!;
    const b = net.islB[i]!;
    const pa = satPos(frame, a);
    const pb = satPos(frame, b);
    const dist = distanceKm(pa, pb);
    distKm[i] = dist;
    let ok = segmentClears(pa, pb, grazing);
    if (net.islKind[i] === KIND_CROSS && (Math.abs(lat[a]!) > polar || Math.abs(lat[b]!) > polar)) ok = false;
    if (!Number.isFinite(dist)) ok = false;
    if (range !== null && !(dist <= range)) ok = false;
    up[i] = ok ? 1 : 0;
  }
  return { up, distKm };
}

/** One city ground station. SID = 0xF000 + g (spec section 7). */
export interface Station {
  name: string;
  latDeg: number;
  lonDeg: number;
  ecefKm: Vec3;
  g: number;
  sid: number;
}

export interface GroundLinks {
  /** Node ids of the visible satellites (elevation >= mask), ascending. */
  visible: number[];
  /** Node ids of the at most k connected satellites, ascending. */
  selected: number[];
  /** Elevation (deg) of every satellite; NaN where the position is missing. */
  elevDeg: Float64Array;
}

export interface GslParams {
  minElevationDeg: number;
  maxLinksPerGs: number;
}

export const DEFAULT_GSL: GslParams = { minElevationDeg: 25.0, maxLinksPerGs: 4 };

/** gsl.select_links for one station at one instant (the first step of either policy). */
export function groundLinks(station: Station, frame: PositionFrame, params: GslParams = DEFAULT_GSL): GroundLinks {
  const n = frame.ecefKm.length / 3;
  const elevDeg = new Float64Array(n);
  const visible: number[] = [];
  for (let i = 0; i < n; i += 1) {
    const e = elevationDeg(station.ecefKm, satPos(frame, i), station.latDeg, station.lonDeg);
    elevDeg[i] = e;
    if (Number.isFinite(e) && e >= params.minElevationDeg) visible.push(i);
  }
  let selected = visible;
  if (visible.length > params.maxLinksPerGs) {
    // highest elevation first; equal elevation -> lower node id (np.lexsort((node, -elev)))
    selected = [...visible]
      .sort((a, b) => {
        const ea = elevDeg[a]!;
        const eb = elevDeg[b]!;
        if (ea !== eb) return ea > eb ? -1 : 1;
        return a - b;
      })
      .slice(0, params.maxLinksPerGs)
      .sort((a, b) => a - b);
  }
  return { visible, selected, elevDeg };
}

// ------------------------------------------------------------------ the graph (CSR)

/** Undirected weighted graph, both directions stored, rows ascending (topo/graph.CsrGraph). */
export interface CsrGraph {
  nNodes: number;
  indptr: Int32Array;
  indices: Int32Array;
  /** Integer ns. */
  weights: Float64Array;
  /** false = may start/end a path but not relay one (ground stations). */
  transit: Uint8Array;
}

/** csr_from_edges: refuses self loops, non-positive weights and duplicate edges. */
export function csrFromEdges(nNodes: number, a: readonly number[], b: readonly number[], w: readonly number[], transit: Uint8Array): CsrGraph {
  const m = a.length;
  const seen = new Set<number>();
  for (let i = 0; i < m; i += 1) {
    const x = a[i]!;
    const y = b[i]!;
    const wt = w[i]!;
    need(x !== y, 'self-loop in edge list');
    need(Number.isSafeInteger(wt) && wt > 0, 'edge weights must be positive integers (ns)');
    const key = Math.min(x, y) * nNodes + Math.max(x, y);
    need(!seen.has(key), 'duplicate edge in edge list');
    seen.add(key);
  }
  const order = Array.from({ length: 2 * m }, (_, k) => k);
  const src = (k: number) => (k < m ? a[k]! : b[k - m]!);
  const dst = (k: number) => (k < m ? b[k]! : a[k - m]!);
  order.sort((p, q) => src(p) - src(q) || dst(p) - dst(q));
  const indptr = new Int32Array(nNodes + 1);
  const indices = new Int32Array(2 * m);
  const weights = new Float64Array(2 * m);
  order.forEach((k, pos) => {
    indptr[src(k) + 1] = (indptr[src(k) + 1] ?? 0) + 1;
    indices[pos] = dst(k);
    weights[pos] = w[k < m ? k : k - m]!;
  });
  for (let u = 0; u < nNodes; u += 1) indptr[u + 1] = (indptr[u + 1] ?? 0) + (indptr[u] ?? 0);
  return { nNodes, indptr, indices, weights, transit };
}

export interface InstantNetwork {
  graph: CsrGraph;
  isl: IslState;
  /** Ground links of the source (index 0) and destination (index 1) stations. */
  gsl: [GroundLinks, GroundLinks];
  /** Light time of every graph edge, keyed "u-v" with u < v (for the per-hop table). */
  srcNode: number;
  dstNode: number;
}

/**
 * The graph of one instant for one pair of cities: up laser links + each city's connected
 * ground links, weight = light time (nearest ns) + 500,000 ns. Node ids: satellites 0..S-1,
 * source S, destination S+1 (as `cr route`).
 */
export function buildInstantNetwork(
  net: ShellNetwork,
  frame: PositionFrame,
  src: Station,
  dst: Station,
  gslParams: GslParams = DEFAULT_GSL,
  processingNs: number = PROCESSING_NS,
): InstantNetwork {
  need(src.name !== dst.name, 'a flow needs two different end points');
  const S = net.norads.length;
  need(frame.ecefKm.length === 3 * S, `position frame has ${frame.ecefKm.length / 3} satellites, the shell ${S}`);
  const isl = islState(net, frame);
  const gsl: [GroundLinks, GroundLinks] = [groundLinks(src, frame, gslParams), groundLinks(dst, frame, gslParams)];
  const ea: number[] = [];
  const eb: number[] = [];
  const ew: number[] = [];
  for (let i = 0; i < net.islA.length; i += 1) {
    if (!isl.up[i]) continue;
    ea.push(net.islA[i]!);
    eb.push(net.islB[i]!);
    ew.push(propagationNs(isl.distKm[i]!) + processingNs);
  }
  [src, dst].forEach((station, gi) => {
    for (const sat of gsl[gi]!.selected) {
      ea.push(sat);
      eb.push(S + gi);
      ew.push(propagationNs(distanceKm(satPos(frame, sat), station.ecefKm)) + processingNs);
    }
  });
  const transit = new Uint8Array(S + 2).fill(1);
  transit[S] = 0;
  transit[S + 1] = 0;
  return { graph: csrFromEdges(S + 2, ea, eb, ew, transit), isl, gsl, srcNode: S, dstNode: S + 1 };
}

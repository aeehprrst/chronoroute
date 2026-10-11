/**
 * Everything the planner needs that does not change with the chosen instant: the shell's
 * network, its satellites' names and SIDs, the cities and the SID registry. Built once per
 * snapshot, in the browser (route page) and in the tests (parity), by the same function.
 */
import type { OmmRecord } from '../data-types';
import type { City } from './cities';
import { geodeticToEcef } from './geometry';
import type { PlanStation, SatelliteInfo } from './planner';
import { assignGroundNumbers, assignSatelliteSids, type SidRegistry } from './sids';
import { buildShellNetwork, TopologyError, type IslDoc, type ShellNetwork, type ShellsDoc } from './topology';
import { groundStationSid } from '../../engine/tcrh';

/** The shell `cr route` uses by default: Starlink's 53 deg / 463 km shell (DERIVED id). */
export const DEFAULT_SHELL = '53.2deg-463km';

export interface RouteContext {
  net: ShellNetwork;
  sats: SatelliteInfo;
  /** OMM records of the shell's satellites, in node order (for SGP4). */
  records: OmmRecord[];
  cities: City[];
  registry: SidRegistry;
  /** How many of the shell's satellites carry a provisional SID. */
  provisionalSids: number;
}

export function buildRouteContext(input: {
  shells: ShellsDoc;
  isl: IslDoc;
  records: readonly OmmRecord[];
  cities: City[];
  registry: SidRegistry;
  shellId?: string;
}): RouteContext {
  const net = buildShellNetwork(input.shells, input.isl, input.shellId ?? DEFAULT_SHELL);
  const byNorad = new Map<number, OmmRecord>(input.records.map((r) => [r.NORAD_CAT_ID, r]));
  const records = net.norads.map((n) => {
    const record = byNorad.get(n);
    if (!record) throw new TopologyError(`NORAD ${n} is in a plane of ${net.shellId} but not in the snapshot's element sets`);
    return record;
  });
  const { satelliteSids, provisional } = assignSatelliteSids(input.registry, net.norads);
  return {
    net,
    sats: { sids: satelliteSids, provisional, names: records.map((r) => r.OBJECT_NAME) },
    records,
    cities: input.cities,
    registry: input.registry,
    provisionalSids: provisional.filter(Boolean).length,
  };
}

/** The two ground stations of a flow (g numbers as Python's registry would give them). */
export function flowStations(ctx: RouteContext, srcName: string, dstName: string): [PlanStation, PlanStation] {
  const byName = new Map(ctx.cities.map((c) => [c.name, c]));
  const numbers = assignGroundNumbers(ctx.registry, [srcName, dstName]);
  const station = (name: string): PlanStation => {
    const city = byName.get(name);
    const num = numbers.get(name);
    if (!city || !num) throw new RangeError(`unknown city ${name}`);
    return {
      name,
      latDeg: city.latDeg,
      lonDeg: city.lonDeg,
      ecefKm: geodeticToEcef(city.latDeg, city.lonDeg, 0.0),
      g: num.g,
      sid: groundStationSid(num.g),
      provisional: num.provisional,
    };
  };
  return [station(srcName), station(dstName)];
}

/**
 * The SID registry (spec/tcrh-v1.md section 7; data/static/sid_registry.json, served verbatim
 * at data/static/sid_registry.json). Port of the reading side of
 * sim/chronoroute/route/sids.py: satellites keep their SID for life (keyed by NORAD id),
 * ground station g has SID 0xF000 + g (keyed by city name).
 *
 * New satellites or cities that the committed registry does not know yet get the SIDs that
 * Python's in-memory ensure_satellites / ensure_ground_stations would give them (the next free
 * numbers, new satellites in NORAD order, new cities in name order). Those SIDs are marked
 * PROVISIONAL on the page: they become final only when the registry file in the repository is
 * updated (`cr export sids`), and an earlier append elsewhere could change them.
 */
import { SID_GROUND_BASE, SID_GROUND_MAX, SID_SATELLITE_MAX } from '../../engine/tcrh';

export const REGISTRY_SCHEMA = 'chronoroute.sid-registry/1';
export const FIRST_SATELLITE_SID = 1;

export class RegistryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'RegistryError';
  }
}

export interface SidRegistry {
  /** NORAD id -> SID, committed entries only. */
  satellites: ReadonlyMap<number, number>;
  /** city name -> g, committed entries only. */
  groundStations: ReadonlyMap<string, number>;
}

/** Validate the registry JSON with the rules of SidRegistry.__init__ (in order, no gaps, no duplicates). */
export function parseRegistry(value: unknown): SidRegistry {
  if (typeof value !== 'object' || value === null) throw new RegistryError('sid_registry.json: not a JSON object');
  const doc = value as Record<string, unknown>;
  if (doc['schema'] !== REGISTRY_SCHEMA) throw new RegistryError(`sid_registry.json: schema must be ${REGISTRY_SCHEMA}`);
  const sats = doc['satellites'];
  const gss = doc['ground_stations'];
  if (!Array.isArray(sats) || !Array.isArray(gss)) throw new RegistryError('sid_registry.json: satellites and ground_stations must be lists');
  const satellites = new Map<number, number>();
  sats.forEach((entry: unknown, i) => {
    const expect = FIRST_SATELLITE_SID + i;
    if (!Array.isArray(entry) || entry.length !== 2 || !Number.isSafeInteger(entry[0]) || !Number.isSafeInteger(entry[1])) {
      throw new RegistryError(`satellite entry ${i} must be [sid, norad]`);
    }
    const [sid, norad] = entry as [number, number];
    if (sid !== expect) throw new RegistryError(`satellite SIDs must be 1, 2, 3, ... in order; found ${sid} where ${expect} was expected`);
    if (sid > SID_SATELLITE_MAX) throw new RegistryError(`satellite SID ${sid} is above 0xEFFF`);
    if (norad <= 0 || satellites.has(norad)) throw new RegistryError(`NORAD id ${norad} is not positive or appears twice`);
    satellites.set(norad, sid);
  });
  const groundStations = new Map<string, number>();
  gss.forEach((entry: unknown, i) => {
    if (!Array.isArray(entry) || entry.length !== 2 || entry[0] !== i || typeof entry[1] !== 'string' || entry[1] === '') {
      throw new RegistryError(`ground station entry ${i} must be [${i}, "<name>"]`);
    }
    if (groundStations.has(entry[1])) throw new RegistryError(`ground station ${entry[1]} appears twice`);
    if (i > SID_GROUND_MAX - SID_GROUND_BASE) throw new RegistryError('too many ground stations');
    groundStations.set(entry[1], i);
  });
  return { satellites, groundStations };
}

export interface SidAssignment {
  /** SID per satellite node (same order as the NORAD list given). */
  satelliteSids: number[];
  /** Which satellite nodes got a provisional SID. */
  provisional: boolean[];
}

/** SIDs for the given NORAD ids; unknown ones are numbered as Python's ensure_satellites would. */
export function assignSatelliteSids(registry: SidRegistry, norads: readonly number[]): SidAssignment {
  const fresh = [...new Set(norads.filter((n) => !registry.satellites.has(n)))].sort((a, b) => a - b);
  if (FIRST_SATELLITE_SID + registry.satellites.size + fresh.length - 1 > SID_SATELLITE_MAX) {
    throw new RegistryError('the satellite SID space 0x0001-0xEFFF is full');
  }
  const extra = new Map<number, number>(fresh.map((n, i) => [n, FIRST_SATELLITE_SID + registry.satellites.size + i]));
  return {
    satelliteSids: norads.map((n) => registry.satellites.get(n) ?? extra.get(n)!),
    provisional: norads.map((n) => !registry.satellites.has(n)),
  };
}

/** g numbers for the given city names; unknown names numbered in name order (ensure_ground_stations). */
export function assignGroundNumbers(registry: SidRegistry, names: readonly string[]): Map<string, { g: number; provisional: boolean }> {
  const fresh = [...new Set(names.filter((n) => !registry.groundStations.has(n)))].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const out = new Map<string, { g: number; provisional: boolean }>();
  for (const name of names) {
    const known = registry.groundStations.get(name);
    if (known !== undefined) out.set(name, { g: known, provisional: false });
  }
  fresh.forEach((name, i) => {
    const g = registry.groundStations.size + i;
    if (g > SID_GROUND_MAX - SID_GROUND_BASE) throw new RegistryError('the ground-station SID space 0xF000-0xFFFE is full');
    out.set(name, { g, provisional: true });
  });
  return out;
}

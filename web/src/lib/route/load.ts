/**
 * Browser loader for the route planner: everything comes from this site's own /data
 * directory (no third-party requests).
 *
 *   latest.json -> snapshots/<id>/manifest.json + omm.min.json     (data contract)
 *   snapshots/<id>/shells.json + isl_grid4.json                    (cr export web)
 *   static/cities.csv + static/sid_registry.json                   (verbatim copies of data/static/)
 *   parity.json (optional)                                         (summary of the CI parity check)
 */
import { DataContractError, fetchJson, loadLatestSnapshot, type LoadedSnapshot } from '../data';
import { dataHref } from '../paths';
import { parseCities, type City } from './cities';
import { parseParitySummary, type ParitySummary } from './parity-summary';
import { parseRegistry, type SidRegistry } from './sids';
import { parseIslDoc, parseShellsDoc, type IslDoc, type ShellsDoc } from './topology';

export interface RouteData {
  snapshot: LoadedSnapshot;
  shells: ShellsDoc;
  isl: IslDoc;
  cities: City[];
  registry: SidRegistry;
  parity: ParitySummary | null;
}

async function fetchText(url: string): Promise<string> {
  const response = await fetch(url, { credentials: 'omit' });
  if (!response.ok) throw new DataContractError(`GET ${url} failed: HTTP ${response.status}`);
  return response.text();
}

async function optionalJson(url: string): Promise<unknown> {
  try {
    const response = await fetch(url, { credentials: 'omit' });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

export async function loadRouteData(): Promise<RouteData> {
  const snapshot = await loadLatestSnapshot();
  const base = snapshot.path;
  const [shellsRaw, islRaw, citiesText, registryRaw, parityRaw] = await Promise.all([
    fetchJson(dataHref(`${base}shells.json`)),
    fetchJson(dataHref(`${base}isl_grid4.json`)),
    fetchText(dataHref('static/cities.csv')),
    fetchJson(dataHref('static/sid_registry.json')),
    optionalJson(dataHref('parity.json')),
  ]);
  return {
    snapshot,
    shells: parseShellsDoc(shellsRaw),
    isl: parseIslDoc(islRaw),
    cities: parseCities(citiesText),
    registry: parseRegistry(registryRaw),
    parity: parseParitySummary(parityRaw),
  };
}

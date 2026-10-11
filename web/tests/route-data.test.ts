/**
 * The route planner's inputs: cities.csv, the SID registry, the topology files and the packet
 * builder. The real files are read from the repository (data/static/), never edited.
 */
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { parseCities, parseCsv, CityFileError } from '../src/lib/route/cities';
import { assignGroundNumbers, assignSatelliteSids, parseRegistry, RegistryError } from '../src/lib/route/sids';
import { buildShellNetwork, groundLinks, parseIslDoc, parseShellsDoc, TopologyError, type Station } from '../src/lib/route/topology';
import { geodeticToEcef } from '../src/lib/route/geometry';
import { internetChecksum, pcapFile, pseudoHeader, sidAddress, udpDatagram, HOST_SRC } from '../src/engine/packet';

const STATIC = path.resolve(import.meta.dirname, '..', '..', 'data', 'static');
const citiesText = readFileSync(path.join(STATIC, 'cities.csv'), 'utf8');
const registryJson: unknown = JSON.parse(readFileSync(path.join(STATIC, 'sid_registry.json'), 'utf8'));

describe('cities.csv', () => {
  it('reads all 60 cities, sorted by name, coordinates exactly as written', () => {
    const cities = parseCities(citiesText);
    expect(cities.length).toBe(60);
    expect(cities.map((c) => c.name)).toEqual([...cities.map((c) => c.name)].sort());
    const chennai = cities.find((c) => c.name === 'Chennai')!;
    expect(chennai.latText).toBe('13.091934');
    expect(chennai.latDeg).toBe(13.091934);
    expect(chennai.isoA2).toBe('IN');
  });

  it('refuses a wrong header, a duplicate and an out-of-range coordinate', () => {
    expect(() => parseCities('name,lat\nX,1\n')).toThrow(CityFileError);
    expect(() => parseCities('name,lat,lon,country,iso_a2,ne_id\nA,1,2,C,AA,1\nA,1,2,C,AA,2\n')).toThrow(/duplicate/);
    expect(() => parseCities('name,lat,lon,country,iso_a2,ne_id\nA,91,2,C,AA,1\n')).toThrow(/out of range/);
  });

  it('parses quoted CSV fields like Python csv', () => {
    expect(parseCsv('a,"b, c","d ""e"""\n')).toEqual([['a', 'b, c', 'd "e"']]);
  });
});

describe('SID registry', () => {
  const registry = parseRegistry(registryJson);

  it('reads the committed registry (spec section 7 numbering)', () => {
    expect(registry.satellites.get(44714)).toBe(1);
    expect(registry.groundStations.get('Addis Ababa')).toBe(0);
    expect(registry.groundStations.get('Chennai')).toBe(12);
  });

  it('numbers unknown satellites like Python ensure_satellites: next SIDs, in NORAD order, marked provisional', () => {
    const n = registry.satellites.size;
    const { satelliteSids, provisional } = assignSatelliteSids(registry, [999002, 44714, 999001]);
    expect(satelliteSids).toEqual([n + 2, 1, n + 1]);
    expect(provisional).toEqual([true, false, true]);
  });

  it('numbers unknown cities in name order (ensure_ground_stations)', () => {
    const g = registry.groundStations.size;
    const out = assignGroundNumbers(registry, ['Zzz', 'Chennai', 'Aaa']);
    expect(out.get('Chennai')).toEqual({ g: 12, provisional: false });
    expect(out.get('Aaa')).toEqual({ g, provisional: true });
    expect(out.get('Zzz')).toEqual({ g: g + 1, provisional: true });
  });

  it('refuses gaps and duplicates', () => {
    expect(() => parseRegistry({ schema: 'chronoroute.sid-registry/1', satellites: [[2, 5]], ground_stations: [] })).toThrow(RegistryError);
    expect(() => parseRegistry({ schema: 'chronoroute.sid-registry/1', satellites: [[1, 5], [2, 5]], ground_stations: [] })).toThrow(RegistryError);
  });
});

describe('topology files', () => {
  const shells = {
    schema: 'chronoroute.web-shells/1',
    snapshot_id: 's',
    reference_utc: '2026-10-10T14:02:22Z',
    label: 'DERIVED',
    shells: [{ shell_id: 'x', layer: 'broadband', planes: [[10, 11, 12], [20, 21]], off_grid_norads: [] }],
    in_transit: [],
  };
  const isl = {
    schema: 'chronoroute.web-isl-grid4/1',
    snapshot_id: 's',
    reference_utc: '2026-10-10T14:02:22Z',
    label: 'MODELLED',
    model: { name: 'grid4', polar_cutoff_deg: 70, min_grazing_alt_km: 80, cross_max_du_factor: 1, max_range_km: null, max_degree: 4, inter_shell_links: false },
    shells: [{ shell_id: 'x', layer: 'broadband', max_cross_du_deg: 10, intra: [[10, 11], [10, 12], [11, 12], [20, 21]], cross: [[10, 20]] }],
  };

  it('builds node ids by NORAD rank and keeps the pairs', () => {
    const net = buildShellNetwork(parseShellsDoc(shells), parseIslDoc(isl), 'x');
    expect(net.norads).toEqual([10, 11, 12, 20, 21]);
    expect([...net.islA]).toEqual([0, 0, 0, 1, 3]);
    expect([...net.islB]).toEqual([1, 2, 3, 2, 4]);
    expect([...net.islKind]).toEqual([0, 0, 1, 0, 0]);
  });

  it('refuses files from different snapshots and pairs outside the planes', () => {
    expect(() => buildShellNetwork(parseShellsDoc(shells), parseIslDoc({ ...isl, snapshot_id: 't' }), 'x')).toThrow(TopologyError);
    const bad = { ...isl, shells: [{ ...isl.shells[0]!, cross: [[10, 99]] }] };
    expect(() => buildShellNetwork(parseShellsDoc(shells), parseIslDoc(bad), 'x')).toThrow(/outside the planes/);
    const unsorted = { ...isl, shells: [{ ...isl.shells[0]!, intra: [[11, 12], [10, 11]] }] };
    expect(() => parseIslDoc(unsorted)).toThrow(/sorted/);
  });

  it('ground links: 25 deg mask, the 4 highest, equal elevation -> lower node id', () => {
    const lat = 0;
    const lon = 0;
    const station: Station = { name: 'S', latDeg: lat, lonDeg: lon, ecefKm: geodeticToEcef(lat, lon, 0), g: 0, sid: 0xf000 };
    // node 0: overhead; nodes 1 and 2: the same elevation (mirror images); 3, 4: lower; 5: below the mask
    const pts = [
      geodeticToEcef(0, 0, 500),
      geodeticToEcef(2, 0, 500),
      geodeticToEcef(-2, 0, 500),
      geodeticToEcef(0, 4, 500),
      geodeticToEcef(0, -4.5, 500),
      geodeticToEcef(0, 30, 500),
    ];
    const ecefKm = Float64Array.from(pts.flat());
    const links = groundLinks(station, { ecefKm });
    expect(links.visible).toEqual([0, 1, 2, 3, 4]);
    expect(links.elevDeg[1]).toBe(links.elevDeg[2]); // an exact tie
    expect(links.selected).toEqual([0, 1, 2, 3]);
    expect(links.elevDeg[5]!).toBeLessThan(25);
  });
});

describe('packet builder', () => {
  it('Internet checksum: RFC 1071 section 3 example', () => {
    // 0001 f203 f4f5 f6f7 -> sum ddf2, checksum ~ddf2 = 220d
    expect(internetChecksum(Uint8Array.from([0x00, 0x01, 0xf2, 0x03, 0xf4, 0xf5, 0xf6, 0xf7]))).toBe(0x220d);
  });

  it('a UDP datagram checks out against its pseudo-header (one-complement sum = 0xffff)', () => {
    const dst = sidAddress(0xf01e);
    const payload = Uint8Array.from([1, 2, 3, 4, 5]);
    const udp = udpDatagram(HOST_SRC, dst, payload);
    const all = new Uint8Array([...pseudoHeader(HOST_SRC, dst, udp.length, 17), ...udp]);
    expect(internetChecksum(all)).toBe(0);
  });

  it('SID addresses follow fd00::<sid>, and the pcap header is classic 2.4 / nanoseconds / RAW', () => {
    expect(Array.from(sidAddress(0x12d2).slice(12))).toEqual([0, 0, 0x12, 0xd2]);
    expect(sidAddress(1)[0]).toBe(0xfd);
    const file = pcapFile([]);
    expect(Array.from(file.slice(0, 4))).toEqual([0x4d, 0x3c, 0xb2, 0xa1]);
    expect(new DataView(file.buffer).getUint32(20, true)).toBe(101);
  });
});

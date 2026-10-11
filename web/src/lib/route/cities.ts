/**
 * The curated city list, data/static/cities.csv (REAL: Natural Earth coordinates, public
 * domain; see data/static/CITIES_SOURCE.md). The site serves a verbatim copy at
 * data/static/cities.csv. Same checks as sim/chronoroute/data/cities.py load_cities():
 * exact header, latitude in -90..90, longitude in -180..180, no empty or duplicate name,
 * a two-letter upper-case country code. Sorted by name (Python's string order: code points).
 */

export const CITY_COLUMNS = ['name', 'lat', 'lon', 'country', 'iso_a2', 'ne_id'] as const;

export interface City {
  name: string;
  latDeg: number;
  lonDeg: number;
  country: string;
  isoA2: string;
  neId: string;
  /** The coordinates exactly as written in the file. */
  latText: string;
  lonText: string;
}

export class CityFileError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'CityFileError';
  }
}

/** Minimal RFC 4180 reader (quoted fields, doubled quotes), enough for Python's csv module output. */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  let i = 0;
  const src = text.replace(/^﻿/, '');
  while (i < src.length) {
    const ch = src[i]!;
    if (quoted) {
      if (ch === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        field += ch;
      }
    } else if (ch === '"' && field === '') {
      quoted = true;
    } else if (ch === ',') {
      row.push(field);
      field = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && src[i + 1] === '\n') i += 1;
      row.push(field);
      rows.push(row);
      row = [];
      field = '';
    } else {
      field += ch;
    }
    i += 1;
  }
  if (quoted) throw new CityFileError('cities.csv: unterminated quoted field');
  if (field !== '' || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}

/** Python's float(): a decimal number (no hex, no 'inf'/'nan' accepted here). */
function parseCoordinate(text: string, where: string): number {
  if (!/^\s*[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?\s*$/.test(text)) {
    throw new CityFileError(`${where}: ${JSON.stringify(text)} is not a number`);
  }
  return Number(text);
}

export function parseCities(text: string): City[] {
  const rows = parseCsv(text);
  const header = rows[0];
  if (!header || header.join(',') !== CITY_COLUMNS.join(',')) {
    throw new CityFileError(`cities.csv: header must be ${CITY_COLUMNS.join(',')}`);
  }
  const seen = new Set<string>();
  const cities: City[] = [];
  rows.slice(1).forEach((row, k) => {
    const lineno = k + 2;
    if (row.length === 1 && row[0] === '') return; // blank line
    if (row.length !== CITY_COLUMNS.length) throw new CityFileError(`cities.csv:${lineno}: expected ${CITY_COLUMNS.length} fields`);
    const [rawName, lat, lon, country, iso, neId] = row as [string, string, string, string, string, string];
    const name = rawName.trim();
    if (!name) throw new CityFileError(`cities.csv:${lineno}: empty name`);
    if (seen.has(name)) throw new CityFileError(`cities.csv:${lineno}: duplicate city ${name}`);
    seen.add(name);
    const latDeg = parseCoordinate(lat, `cities.csv:${lineno} lat`);
    const lonDeg = parseCoordinate(lon, `cities.csv:${lineno} lon`);
    if (!(latDeg >= -90 && latDeg <= 90 && lonDeg >= -180 && lonDeg <= 180)) {
      throw new CityFileError(`cities.csv:${lineno}: ${name}: coordinates out of range`);
    }
    if (!/^[A-Z]{2}$/.test(iso)) throw new CityFileError(`cities.csv:${lineno}: ${name}: iso_a2 ${iso} is not a 2-letter code`);
    cities.push({ name, latDeg, lonDeg, country, isoA2: iso, neId, latText: lat, lonText: lon });
  });
  // Python sorts str by code point; compare the same way (not localeCompare).
  return cities.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

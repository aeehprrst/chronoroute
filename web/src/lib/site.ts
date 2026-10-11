/**
 * Site-wide constants. Navigation lists ONLY pages that exist. When a Results page is built,
 * add it here (and nowhere else).
 */

export const SITE_NAME = 'ChronoRoute';
export const SITE_TAGLINE = 'Deadline-based source routing for LEO satellite constellations';
export const REPO_URL = 'https://github.com/aeehprrst/chronoroute';
/**
 * Licences, as in the repository's LICENSE file: MIT, except the ns-3 code under ns3/ (the
 * module in ns3/contrib/ and the programs in ns3/scratch/), which is GPL-2.0-only because it
 * builds on ns-3. Third-party orbit data keeps its source's terms.
 */
export const LICENCE = 'MIT';
export const LICENCE_SHORT = 'MIT (ns-3 code: GPL-2.0-only)';
export const LICENCE_URL = `${REPO_URL}/blob/main/LICENSE`;

export interface NavItem {
  /** Page path relative to the base, without slashes ('' is the home page). */
  path: string;
  label: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { path: '', label: 'Home' },
  { path: 'live', label: 'Live globe' },
  { path: 'route', label: 'Route planner' },
  { path: 'protocol', label: 'Protocol' },
  { path: 'experiments', label: 'Experiments' },
  { path: 'methodology', label: 'Methodology' },
  { path: 'about', label: 'About' },
];

/**
 * The project's ONE honesty-label table, mirrored from sim/chronoroute/labels.py (TABLE).
 * Every producer of data (bundle, website files, fleet report, course results) takes its
 * labels from that table, so the site uses the same key for the same thing and shows the same
 * label. tests/label-keys.test.ts checks this copy against the Python table exported in
 * web/.parity/parity.json, so the two can never drift apart silently.
 *
 * Python has three manifest labels (REAL / DERIVED / MODELLED); an ASSUMED parameter is filed
 * under MODELLED with a note (gsl_mask_and_assignment). The site's fourth label, UNKNOWN, is
 * for things that are not public and that we never claim (Starlink's real routing).
 */
import type { DataLabel } from './data-types';

export const LABEL_TABLE = {
  // REAL
  orbital_elements: 'REAL',
  catalogue_names_and_ids: 'REAL',
  epoch_ages: 'REAL',
  satcat_status: 'REAL',
  city_coordinates: 'REAL',
  satellite_positions_sgp4: 'REAL',
  tcrh_header_bytes: 'REAL',
  // DERIVED
  shells_and_planes: 'DERIVED',
  in_transit_flags: 'DERIVED',
  gp_vs_supgp_disagreement: 'DERIVED',
  routes_and_budgets: 'DERIVED',
  // MODELLED
  isl_topology_grid4: 'MODELLED',
  gsl_mask_and_assignment: 'MODELLED',
  processing_delay: 'MODELLED',
  link_rate_and_queues: 'MODELLED',
  traffic_probes: 'MODELLED',
  fault_slow_link: 'MODELLED',
  ns3_processing_delay_zero: 'MODELLED',
  pcap_addresses: 'MODELLED',
  pcap_timestamps: 'MODELLED',
  walk_link_delays: 'MODELLED',
} as const satisfies Record<string, 'REAL' | 'DERIVED' | 'MODELLED'>;

export type LabelKey = keyof typeof LABEL_TABLE;

/** The chip kind (LabelChip / route page) for a label key. */
export function labelKind(key: LabelKey): DataLabel {
  return LABEL_TABLE[key].toLowerCase() as DataLabel;
}

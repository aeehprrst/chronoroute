import type { DataLabel } from './data-types';

export interface LabelInfo {
  kind: DataLabel;
  /** Text shown on the chip. */
  name: string;
  /** One-sentence definition used on the methodology page and in chip tooltips. */
  definition: string;
  /** A short example from this project. */
  example: string;
}

/** The four provenance labels, in the order they are always presented. */
export const LABELS: readonly LabelInfo[] = [
  {
    kind: 'real',
    name: 'REAL',
    definition:
      'Public or measured data, real physics computed with real code on REAL inputs, or the exact output of our real code, such as the bytes of a header.',
    example:
      'CelesTrak orbital elements, satellite positions computed from them with SGP4, the speed of light, the bytes of a T-CRH.',
  },
  {
    kind: 'derived',
    name: 'DERIVED',
    definition:
      'Computed by our code from REAL inputs by an inference or a choice that could be made differently.',
    example: 'Shells and orbital planes inferred from the elements, the colour groups, a planned route and its budgets.',
  },
  {
    kind: 'modelled',
    name: 'MODELLED',
    definition: 'Our assumption, used because the truth is not public.',
    example: 'Which satellites are joined by laser links, the traffic, the failures.',
  },
  {
    kind: 'unknown',
    name: 'UNKNOWN',
    definition: 'Not public, so we do not claim it.',
    example: "Starlink's real routing. Starlink does not use T-CRH.",
  },
];

export function labelInfo(kind: DataLabel): LabelInfo {
  const info = LABELS.find((label) => label.kind === kind);
  if (!info) throw new Error(`Unknown data label: ${String(kind)}`);
  return info;
}

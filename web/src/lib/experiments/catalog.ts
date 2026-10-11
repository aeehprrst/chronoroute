/** Reviewed result releases. Questions and hypotheses transcribed from the frozen preregistration. */
export const PREREG_SHA = 'b87f08a7cc9431d139bf66372f03133035494b8c';
export const PREREG_HASH =
  '1d1541f60be8411f565c5eda4e64322354c276a7321181e2ee9ee92f065ea5d3';
export interface Metric {
  key: string;
  label: string;
  unit: string;
  lo?: string;
  hi?: string;
  /** Columns always shown beside this metric (e.g. the loss count behind a blackhole time). */
  companions?: string[];
  /** What the metric does and does not count; shown with the chart. */
  note?: string;
}
/** A provenance fact that the manifest alone does not show (shown under "How this was made"). */
export interface ProvenanceNote {
  title: string;
  text: string;
  commits: { role: string; sha: string }[];
}
export interface ExperimentDefinition {
  id: string;
  slug: string;
  run: string;
  title: string;
  question: string;
  hypothesis: string;
  limitations: string[];
  /** Caveats shown above the "Where ChronoRoute loses" table. */
  lossNotes: string[];
  metrics: Metric[];
  tableColumns: string[];
  /** Manifested paired-contrast table read at build time for the verdict (never sent to the browser). */
  contrasts?: string;
  provenance?: ProvenanceNote[];
}

/**
 * What each E0 check compares. 'reference': another implementation, an independent reader or
 * fixed expected values. 'self': an implementation compared with expectations it made itself.
 * 'invariant': one implementation's output checked against a registered physical limit.
 * The verdict refuses an unclassified check, so a new gate row cannot be described silently.
 */
export type CheckKind = 'reference' | 'self' | 'invariant';
export const E0_CHECK_KINDS: Readonly<Record<string, CheckKind>> = {
  positions_finite: 'invariant',
  isl_grazing: 'invariant',
  link_light_time: 'invariant',
  isl_polar_cutoff: 'invariant',
  gsl_light_time: 'invariant',
  gsl_elevation: 'invariant',
  gsl_visibility_complete: 'invariant',
  gsl_degree: 'invariant',
  path_great_circle: 'invariant',
  full_orbit_coverage: 'invariant',
  wire_python: 'self',
  wire_golden_fixed: 'reference',
  wire_browser: 'reference',
  wire_ns3: 'reference',
  wire_capture_bytes: 'reference',
  wire_wireshark_fields: 'reference',
  orbit_pinned_full: 'reference',
  orbit_pinned_ms_epoch: 'reference',
  orbit_exported_full: 'reference',
  orbit_exported_ms_epoch: 'reference',
};
export const E0_CHECK_NOTES: Readonly<Record<string, string>> = {
  wire_golden_fixed: 'golden vectors against their fixed expected values',
  wire_browser: 'the browser TypeScript implementation',
  wire_ns3: 'the ns-3 C++ implementation',
  wire_capture_bytes: 'frame bytes as tshark itself reads them',
  wire_wireshark_fields: 'Wireshark dissector fields',
  orbit_pinned_full: 'browser SGP4 positions against the Python reference',
  wire_python: 'mostly Python compared with Python-made expectations',
};

export const EXPERIMENTS: readonly ExperimentDefinition[] = [
  {
    id: 'E00',
    slug: 'e0',
    run: '20261011T214507Z',
    title: 'Correctness gate',
    question: 'Do geometry, physics and all wire implementations agree?',
    hypothesis:
      'No invariant or wire-byte violations; position differences stay within the existing parity tolerances. Any violation blocks the campaign.',
    limitations: [
      'Sampled geometry is not a continuous-time proof.',
      'Agreement of implementations does not establish the realism of the network model.',
      'Only the cross-implementation and fixed-value checks are external references. wire_python mostly compares Python with Python-made expectations, and the geometry rows check one implementation against registered limits.',
      'isl_polar_cutoff cannot fail on 53° shells: the highest latitude reached stays far below the 70° cutoff, so its zero violations carry no evidence.',
      'The isl_grazing "worst" value is a certified spherical lower bound on the grazing height, not the exact minimum height.',
      'path_great_circle compares propagation delay only; processing time is not added to the bound.',
    ],
    lossNotes: [],
    metrics: [
      { key: 'violations', label: 'Correctness violations', unit: 'count' },
    ],
    tableColumns: [
      'check',
      'constellation',
      'label',
      'checked',
      'violations',
      'worst',
      'limit',
      'unit',
      'bound',
    ],
  },
  {
    id: 'E01',
    slug: 'e1',
    run: '20261011T154940Z-confirmatory-resumed',
    title: 'Detection of up-but-slow links',
    question:
      'Can deadlines detect an up-but-slow ISL without excessive false alarms, and where do they fail relative to local and conventional monitors?',
    hypothesis:
      'At a pilot-selected operating point with clean-packet FPR at most 1%, ChronoRoute detects nominal/strong faults more often than LS-H and CRH-16, and has shorter censored detection delay than LS-D. Small faults inside the budget may remain undetected. LQ may beat ChronoRoute; this is a primary comparison, not an excluded case.',
    limitations: [
      'Detection is counterfactual with common random numbers; loss before a checker can prevent an alarm.',
      'Selected rules are frozen from the pilot. Other rule and event-setting sweeps remain available in the table.',
      'Chart intervals are marginal per-cell intervals. The verdict quotes the registered paired comparisons from paired_contrasts.csv: paired Student-t 95% intervals (primary) with Holm-adjusted p-values. A binary endpoint that is 0 or 1 in every run gives a zero-width interval.',
      'The rate-cut fault at factor 0.3 is the registered nominal magnitude. With fluid background traffic at 0.3 of nominal capacity, that cut puts the link at exactly full load, so the queue stays short and fits inside the S = 1.5 budgets.',
      'S = 1.5 gives each hop a deadline at 1.5 times the planned elapsed time, which leaves several milliseconds of spare time mid-path; 0.25 to 4 ms of added delay fits inside it. Looser rules detect more but exceed the registered 1% false-positive limit (rows with selected = False).',
      'LS-D is not a valid comparator for slowness detection in this release: its measurement is the queue estimate plus the exact injected fault delay plus the expected ARQ delay computed from the configured loss probability, with no measurement noise. With the registered 1 s update interval it re-advertises any nonzero change, so its 20% threshold never matters, and a run counts as detected unless a twin advert coincides. Its numbers stay as registered but are not evidence either way.',
      'LS-H and CRH-16 have no slowness detector, so ChronoRoute wins against them hold by construction. E2E runs at a clean false-positive rate of 0, so comparisons with it are not at matched false-positive rates. LQ uses only local queue and ARQ state; its advantages are robust.',
      'Pair 0 has only 2 ISLs, so its middle and last fault positions are the same link.',
      'O-Q is a privileged oracle. The local queue monitor is a practical comparator.',
    ],
    lossNotes: [
      'Rows against LS-D are kept as registered, but LS-D reads the injected delay without measurement noise and advertises any change, so they are not valid evidence about slowness detection.',
      'Rows against LQ are robust: LQ is a practical local monitor using only local queue and ARQ state.',
      'False-positive rows against E2E, LQ and CRH-16 compare different operating points; E2E runs at a clean false-positive rate of 0.',
    ],
    contrasts: 'paired_contrasts.csv',
    metrics: [
      {
        key: 'event_mean',
        lo: 'event_lo',
        hi: 'event_hi',
        label: 'Event detection probability',
        unit: 'proportion',
      },
      {
        key: 'fpr',
        lo: 'fpr_lo',
        hi: 'fpr_hi',
        label: 'Clean-packet false-positive rate',
        unit: 'proportion',
      },
      {
        key: 'restricted_mean_s',
        lo: 'restricted_lo',
        hi: 'restricted_hi',
        label: 'Restricted mean detection delay',
        unit: 's',
      },
      {
        key: 'packet_pdet',
        lo: 'packet_pdet_lo',
        hi: 'packet_pdet_hi',
        label: 'Counterfactual packet detection',
        unit: 'proportion',
      },
    ],
    tableColumns: [
      'const',
      'condition',
      'scheme',
      'rule',
      'selected',
      'k',
      'n',
      'complete',
      'event_mean',
      'event_lo',
      'event_hi',
      'fpr',
      'fpr_lo',
      'fpr_hi',
      'restricted_mean_s',
      'restricted_lo',
      'restricted_hi',
      'lost_at_fault',
      'effective_p99_inf_flows',
    ],
  },
  {
    id: 'E02',
    slug: 'e2',
    run: '20261011T214624Z-confirmatory',
    title: 'Header overhead',
    question: 'What wire cost buys per-hop time checking?',
    hypothesis:
      'T-CRH costs more than CRH-16 and less than SRv6 SRH over the registered segment counts. Relative to CRH-32 it trades a larger fixed part for a smaller per-entry part; enumerate the crossover and padding ties rather than assert a universal saving. Encapsulation adds the outer IPv6 header. This is exact code/byte accounting, not a statistical latency claim.',
    limitations: [
      'Exact encoder and padding accounting has no sampling confidence interval.',
      'This page reads summary.csv only. The capture comparison (capture_summary.csv and capture_frames.csv.gz in the same result folder) is not read here, so no capture agreement claim is made on this page.',
      'Only T-CRH appears in the captures; SRH sizes are exact accounting without a captured SRH encoder.',
      'Header savings are not measured latency or throughput savings.',
    ],
    lossNotes: [
      'The CRH-16 overhead penalty is a real cost at every entry count, and CRH-32 is smaller than T-CRH at small entry counts; both are listed below.',
    ],
    metrics: [
      { key: 'added_bytes', label: 'Added on-wire bytes', unit: 'bytes' },
      {
        key: 'reference_percent',
        label: 'Overhead relative to reference packet',
        unit: '%',
      },
    ],
    tableColumns: [
      'entries',
      'protocol',
      'mode',
      'header_bytes',
      'added_bytes',
      'reference_bytes',
      'reference_percent',
      'final_percent',
      'encoder_checked',
      'encoder_violations',
      'label',
    ],
  },
  {
    id: 'E04',
    slug: 'e4',
    run: '20261011T185503Z-collected',
    title: 'Hard failures',
    question:
      'Does local fallback preserve delivery under repairable link and satellite outages?',
    hypothesis:
      'ChronoRoute with greedy-with-visited improves PDR and blackhole time relative to continue and CRH-16, without a material effective-tail penalty relative to SNAP or LS-H+BFD. O-T is a privileged reference, not an implementable competitor.',
    limitations: [
      'Outages and repair histories are MODELLED, not operational measurements.',
      'The registered blackhole metric counts only losses with reason next_link_down, no_fallback or stuck (plus in-flight and node_down losses). Losses of the fallback itself to hop_limit or loop are not counted, so a fallback can show zero blackhole time while still losing packets. The counted losses (blackhole_losses) and PDR are always shown beside it.',
      'Blackhole estimates condition on runs with outages; their denominator can differ from delivery estimates.',
      'Losses have infinite effective latency. Infinite tails and unavailable intervals remain visible. The registered material-loss rule needs a finite latency ratio, which is undefined with infinite tails, so it can never fire for tails here; the paired tail-failure indicator is used instead.',
      'Time to mitigation is censored for fallback outages by construction: fallback packets still meet the dead link.',
      'Paired comparisons quoted in the verdict come from paired_contrasts.csv: paired Student-t 95% intervals (primary) and Holm-adjusted p-values. Chart intervals are marginal per-cell intervals.',
      'Stretch depends on the send-time graph and step-crossing tolerance. Raw values and exact-domain violations must be distinguished.',
    ],
    lossNotes: [
      'Blackhole rows show the counted blackhole losses and PDR beside each time, because the registered blackhole metric does not count the fallback’s own hop_limit and loop losses.',
      'The registered tail hypothesis is “no material effective-tail penalty against SNAP or LS-H”; the verdict reports the paired tail-failure indicator against LS-H, where it is not supported.',
    ],
    contrasts: 'paired_contrasts.csv',
    provenance: [
      {
        title: 'Recovery',
        text: 'The registered simulations ran at the producer commit. The first collection crashed while writing the new tail-failure columns, so the collector commit only re-collected the finished runs; no simulation was rerun, and the per-run and summary tables are byte-identical to the first collection. recovery.json and runtime.json in the result folder record this.',
        commits: [
          { role: 'Simulations (producer)', sha: 'b805d2def53aefe7e8ad788d67986252691a2967' },
          { role: 'Collection (manifest commit)', sha: 'a18cffb6da450ea4449acf46f455b474fee2dcbf' },
        ],
      },
    ],
    metrics: [
      {
        key: 'pdr_mean',
        lo: 'pdr_lo',
        hi: 'pdr_hi',
        label: 'Packet delivery ratio',
        unit: 'proportion',
      },
      {
        key: 'blackhole_mean',
        lo: 'blackhole_lo',
        hi: 'blackhole_hi',
        label: 'Blackhole time',
        unit: 's',
        companions: ['blackhole_losses', 'pdr_mean', 'sent', 'delivered'],
        note: 'Counts only next_link_down, no_fallback and stuck losses (plus in-flight and node_down); the fallback’s own hop_limit and loop losses are not counted. Counted losses and PDR are shown with every point.',
      },
      {
        key: 'effective_p99_mean',
        lo: 'effective_p99_lo',
        hi: 'effective_p99_hi',
        label: 'Effective P99 latency; losses infinite',
        unit: 's',
      },
    ],
    tableColumns: [
      'const',
      'condition',
      'scheme',
      'n',
      'complete',
      'pdr_mean',
      'pdr_lo',
      'pdr_hi',
      'sent',
      'delivered',
      'blackhole_mean',
      'blackhole_lo',
      'blackhole_hi',
      'blackhole_n',
      'blackhole_losses',
      'outages',
      'ttm_censored',
      'effective_p99_mean',
      'effective_p99_lo',
      'effective_p99_hi',
      'infinite_tail_runs',
      'stretch_violations',
      'stretch_min_exact',
      'stretch_min_raw',
    ],
  },
  {
    id: 'E05',
    slug: 'e5',
    run: '20261011T185503Z-confirmatory',
    title: 'Fallback policies',
    question:
      'Does loop avoidance improve fallback completion, and does a Grid detour justify its cost?',
    hypothesis:
      'Greedy-with-visited reduces stuck/loop losses relative to pure greedy; Grid detour reduces those losses further or improves stretch, but may add hops. Continue/drop can win on cost or delivered-packet latency and must remain visible.',
    limitations: [
      'The intervention forces the checker decision at an on-path node without adding service delay; these are policy outcomes, not false-positive data.',
      'Triggered-only completion and cost prevent untriggered traffic from hiding policy effects.',
      'Losses have infinite effective latency. Undefined trigger denominators are not zero.',
      'Chart intervals are marginal per-cell intervals. The verdict quotes the registered paired comparisons from paired_contrasts.csv: paired Student-t 95% intervals (primary) with Holm-adjusted p-values.',
      'Continue never reroutes, so it can complete more triggered packets than a fallback when the planned path still works; it remains a visible competitor.',
      'Raw stretch below unity can result from step crossing; use the recorded exact-domain and tolerance-adjusted checks.',
    ],
    lossNotes: [
      'Continue completing more triggered packets than a fallback policy is a real loss for the fallback, not an artefact.',
      'A Grid detour that does not reduce stuck losses below greedy-with-visited is listed as an unsupported advantage.',
    ],
    contrasts: 'paired_contrasts.csv',
    metrics: [
      {
        key: 'triggered_pdr_mean',
        lo: 'triggered_pdr_lo',
        hi: 'triggered_pdr_hi',
        label: 'Triggered-packet delivery ratio',
        unit: 'proportion',
      },
      {
        key: 'stuck_rate_mean',
        lo: 'stuck_rate_lo',
        hi: 'stuck_rate_hi',
        label: 'Triggered stuck/loop loss rate',
        unit: 'proportion',
      },
      {
        key: 'triggered_stretch_mean_mean',
        lo: 'triggered_stretch_mean_lo',
        hi: 'triggered_stretch_mean_hi',
        label: 'Triggered stretch',
        unit: 'ratio',
      },
      {
        key: 'triggered_extra_hops_mean_mean',
        lo: 'triggered_extra_hops_mean_lo',
        hi: 'triggered_extra_hops_mean_hi',
        label: 'Triggered extra hops',
        unit: 'hops',
      },
    ],
    tableColumns: [
      'const',
      'condition',
      'scheme',
      'n',
      'complete',
      'triggered',
      'triggered_pdr_mean',
      'triggered_pdr_lo',
      'triggered_pdr_hi',
      'stuck_rate_mean',
      'stuck_rate_lo',
      'stuck_rate_hi',
      'triggered_stretch_mean_mean',
      'triggered_extra_hops_mean_mean',
      'infinite_tail_runs',
      'stretch_violations',
      'stretch_min_exact',
      'stretch_min_adjusted',
      'stretch_min_raw',
    ],
  },
  {
    id: 'E16',
    slug: 'e16',
    run: '20261011T194240Z-confirmatory',
    title: 'Python and ns-3 agreement',
    question:
      'Are the Python and ns-3 implementations interchangeable within the registered scope?',
    hypothesis:
      'Deterministic replay agrees per packet exactly. Stochastic run-level PDR, FPR and latency pass the registered equivalence tests. Failure to establish equivalence is not evidence of equivalence.',
    limitations: [
      'Zero processing delay, no background or jitter, stable planning, source insertion and continue policy; agreement is scoped to this model.',
      'Common-random-numbers design (declared in the preregistration): both engines replay the same pre-generated send list and nothing else is random, so per-packet identity is expected. The equivalence test is therefore degenerate: every paired difference is exactly 0, the intervals have zero width, and the p-values come from the zero-variance branch, not from a t distribution.',
      'No packet was lost in any run on either engine, so PDR and false-positive equivalence sit at the boundary and say nothing about loss paths. The agreement covers delivery, queueing and deadline flags.',
      'TOST uses the recorded equivalence intervals; ordinary confidence intervals are also shown.',
      'The allowed summary covers stochastic equivalence. Per-packet deterministic records are in the repository but are not a separate chart input here.',
    ],
    lossNotes: [],
    metrics: [
      {
        key: 'estimate',
        lo: 'lo95',
        hi: 'hi95',
        label: 'Paired engine agreement',
        unit: 'see scale column',
      },
    ],
    tableColumns: [
      'const',
      'condition',
      'endpoint',
      'n',
      'complete',
      'estimate',
      'lo90',
      'hi90',
      'lo95',
      'hi95',
      'p_lower',
      'p_upper',
      'lower_bound',
      'upper_bound',
      'equivalent',
      'reason',
      'undefined_runs',
      'infinite_runs',
      'scale',
    ],
  },
];

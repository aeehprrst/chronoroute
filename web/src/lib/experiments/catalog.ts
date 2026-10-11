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
}
export interface ExperimentDefinition {
  id: string;
  slug: string;
  run: string;
  title: string;
  question: string;
  hypothesis: string;
  limitations: string[];
  metrics: Metric[];
  tableColumns: string[];
}
export const EXPERIMENTS: readonly ExperimentDefinition[] = [
  {
    id: 'E00',
    slug: 'e0',
    run: '20261011T100448Z',
    title: 'Correctness gate',
    question: 'Do geometry, physics and all wire implementations agree?',
    hypothesis:
      'No invariant or wire-byte violations; position differences stay within the existing parity tolerances. Any violation blocks the campaign.',
    limitations: [
      'Sampled geometry is not a continuous-time proof.',
      'Agreement of implementations does not establish the realism of the network model.',
    ],
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
      'Marginal confidence intervals are not multiplicity-adjusted paired contrasts. The allowed summary cannot establish every registered significance claim.',
      'O-Q is a privileged oracle. The local queue monitor is a practical comparator.',
    ],
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
    run: '20261011T175659Z-confirmatory',
    title: 'Header overhead',
    question: 'What wire cost buys per-hop time checking?',
    hypothesis:
      'T-CRH costs more than CRH-16 and less than SRv6 SRH over the registered segment counts. Relative to CRH-32 it trades a larger fixed part for a smaller per-entry part; enumerate the crossover and padding ties rather than assert a universal saving. Encapsulation adds the outer IPv6 header. This is exact code/byte accounting, not a statistical latency claim.',
    limitations: [
      'Exact encoder and padding accounting has no sampling confidence interval.',
      'The allowed summary contains size accounting, not the separate capture-comparison table; no capture agreement claim is made here.',
      'Header savings are not measured latency or throughput savings.',
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
      'Blackhole estimates condition on runs with outages; their denominator can differ from delivery estimates.',
      'Losses have infinite effective latency. Infinite tails and unavailable intervals remain visible.',
      'Paired, adjusted significance contrasts are not present in this summary; point disadvantages do not by themselves establish a material loss.',
      'Stretch depends on the send-time graph and step-crossing tolerance. Raw values and exact-domain violations must be distinguished.',
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
      'blackhole_mean',
      'blackhole_lo',
      'blackhole_hi',
      'blackhole_n',
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
      'Marginal intervals do not supply adjusted paired significance contrasts.',
      'Raw stretch below unity can result from step crossing; use the recorded exact-domain and tolerance-adjusted checks.',
    ],
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
      'Both engines replay identical explicit send-time lists. Randomness is in traffic, not independent engine resampling.',
      'TOST uses the recorded equivalence intervals; ordinary confidence intervals are also shown. Degenerate intervals reflect exactly matching paired endpoints.',
      'The allowed summary covers stochastic equivalence. Per-packet deterministic records are in the repository but are not a separate chart input here.',
    ],
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

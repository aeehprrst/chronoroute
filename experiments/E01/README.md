# E1: up-but-slow detection

The frozen protocol is [PREREG.md](../PREREG.md). `campaign.py` contains the
exact E1 simulation grid and the nine offline budget rules. Every generated
config has separate `campaign`, `engine` and `scheme` blocks; the launcher
removes the campaign block before invoking the strictly validated CLI.

Start with the E1 portion of the registered pilot matrix:

```bash
venv/bin/python -B experiments/E01/campaign.py \
  --out results/E01/<new-campaign>-pilot --workers 8
```

Run only after committing the implementation and passing `make check`.
The launcher refuses a dirty implementation or an altered preregistration.
It verifies retained pairs and freezes physical fault targets, measures
serial runs and a bounded parallel batch, and records every failed job.
ChronoRoute uses `cr run --scheme` to retain accounting and per-hop arrays;
the baselines use `cr eval scheme`. All use `continue`. Deadline rules are
evaluated by `cr eval score --rules --flow 0 --check-plans`, using same-seed
fault-free twins. Budget changes never cause another simulation.

Pilot clean FPR pools each unique no-fault run once and each nominal fault
run once. Family detection ratios pool runs before equally weighting the
three families. The frozen rule file hashes the input score manifests.
Pilot figures are descriptive and are not confirmatory findings.

This first launcher deliberately cannot start confirmation. The remaining
registered cost pilots for E4/E5/E16 and the deterministic E16 validity gate
must also pass, and the complete measured campaign forecast must fit the
registered budget. The partial E1 pilot can establish a resource failure;
it cannot establish resource feasibility. If the measured budget fails,
preserve the evidence and commit a prospective amendment before reading
confirmatory outcomes. Do not silently remove cells, seeds, accounting or
null controls.

After the E1 pilot, run the remaining registered cost pilots and deterministic
replay gate from a clean, tested commit (build ns-3 first):

```bash
venv/bin/python -B experiments/E01/prerequisites.py \
  --e1-pilot results/E01/<campaign>-pilot \
  --out results/E01/<new-campaign>-prerequisites --workers 8
```

The E5 hook is an explicit MODELLED intervention. It invokes the ordinary
late-policy handler with a forced checker input, recording that input and
the actual clock separately. It adds no service delay, changes no link and
does not count as a real deadline alarm or an FPR observation. It records
visited-set entries and the Python set object's memory cost; the visited
set has no support in the current wire header. Regression tests compare
all pre-trigger paths/times and the full untriggered controls across policies.

E16 exports common geometry and schedules with explicit zero processing,
then sends exactly the same packet-ID/time list on Python and ns-3. The
comparison reads actual queue/loss replay output from both engines; it
does not use the light-time-only predictor. Lost packets, absent delivery
times, paths, clocks, deadlines and header decisions remain in the check.

The network, queues, jitter and faults are MODELLED. C5 elements and SGP4
physics are REAL; C2 positions are MODELLED; routes and budgets are DERIVED.
Starlink's operational routing is UNKNOWN and Starlink does not use T-CRH.

The final scorer is calibrated before confirmation. This keeps the original
operating-point file frozen, rechecks its original packet/FPR counts, measures
the event sensitivities and reverse-flow analysis, and benchmarks long routes
using additional pilot seeds. Supplemental pilots affect the compute forecast
only. The scientific grid and rule selection remain the registered ones.

```bash
venv/bin/python -B experiments/E01/resource_gate.py \
  --pilot results/E01/<pilot> --prerequisites results/E01/<prerequisites> \
  --out results/E01/<calibration> --workers 8
venv/bin/python -B experiments/E01/confirm.py \
  --pilot results/E01/<pilot> --prerequisites results/E01/<calibration> \
  --e0 results/E00/<gate> --out results/E01/<confirmation> --workers 8
```

The forecast retains a conservative cost allowance for each constellation and
scheme, charges both scoring and ROC work, and reserves the other registered
experiments. An unsuccessful forecast blocks confirmation. ROC work is split
into bounded chunks; inference always uses the complete run population.

Confirmation records every job, including failures/timeouts and jobs that could
not start before the campaign deadline. `per_run.csv` contains detector
endpoints and denominators; `run_metrics.csv` retains delivery, latency, loss
reasons and state/control accounting. `summary.csv` contains run-level intervals,
`campaign_roc.csv` the registered rule curves, `paired_contrasts.csv` both fixed
Holm families, and `population_fpr.csv` the operating-constraint verdict.
Reverse-direction endpoints and fixed-city bootstrap sensitivities are also
retained. LS uses native installation events and has undefined packet FPR;
O-Q is a privileged delivery bound with undefined detector endpoints.

The adjacent ignored `<confirmation>-raw/` cache retains the full packet traces,
configs and producer manifests. The committed aggregate folder includes a
compressed ledger of those manifests and their output hashes, replay-gate
comparisons, offline ROC outputs and standalone figures. The aggregate manifest
checks its own portable files. Reproducing raw records on another checkout
requires rerunning the recorded commands; hashes alone are not packet traces.

O-Q uses an exact integer A* search with cached nominal reverse distances for
fluid/no-background runs. Queue waits and fault penalties remain in the actual
edge weights; equal-cost routes retain the original lowest-predecessor rule.
Poisson background retains the original search/query order. Differential tests
compare foreground packet traces, header decisions, arrival times and the full
control ledger. The number of virtual queues inspected is a computational
diagnostic and can change. A recalibration can additionally compare real pilot
files against a previous clean calibration with `--previous-calibration DIR`;
all comparisons must pass, and earlier pilot time stays charged to the budget.

`packet_run_ratios.csv` and `packet_ratio_distribution.csv` show the run-level
packet-detection distribution and undefined exposures explicitly. Localisation
is undefined for the unlocalised E2E monitor. Delivery and control accounting
remain all-flow quantities even in the reverse-detection summary. The raw-cache
collection manifest indexes completed simulation/scoring logs as well as the
producer files.

To continue a stopped campaign, supply `--resume-from <checkpoint>` to
`confirm.py` and choose a new `--out` folder. The launcher verifies the source
collection and frozen configuration, copies only complete validated simulation
and scoring producers, and preserves their original manifests. Incomplete jobs
run again in the new cache; the original checkpoint stays unchanged. Analysis
must agree with an uninterrupted run. Earlier active wall time remains charged
to the campaign budget; the user's pause does not. The resumed inventory and
runtime record distinguish reused work from new computation.

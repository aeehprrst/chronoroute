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

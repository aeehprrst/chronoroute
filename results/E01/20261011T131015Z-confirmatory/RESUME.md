# E1 stopped checkpoint

This is an incomplete confirmatory campaign, stopped at the user’s request.
There is no final E1 summary, confidence interval or scientific verdict here.
The scientific configuration and selected rules remain frozen. C5 orbital
inputs are REAL; routes/budgets are DERIVED; network outcomes and C2 are MODELLED.
Starlink operational routing is UNKNOWN; Starlink does not use T-CRH.

Implementation and experiment code were committed before the run. See
`checkpoint.json` for the commit, original command, status counts and charged
elapsed runtime. `inventory.csv` is the original last-flushed inventory;
`checkpoint_inventory.csv` additionally records unflushed and interrupted jobs.
The adjacent ignored `20261011T131015Z-confirmatory-raw/` contains full local
traces, configs, observations and producer manifests. Do not delete it.
The compressed producer ledger preserves original manifests and hashes.

## Resume safely

The current launcher has no resume option and refuses an existing output
folder. Do not rerun the original command into this folder, delete the cache,
interpret this checkpoint as complete, or silently omit pending seeds.

Next session: first implement and test checkpoint reuse in the launcher. Tests
must establish equivalence with an uninterrupted small run, reject changed
configs, seeds, twins, selected rules or inputs, and retain interrupted jobs.
Run `make check` and commit that implementation before starting more experiments.
Reuse only validated completed raw/scoring outputs with their original producer
commits. Complete missing parent metadata or scores explicitly; interrupted
files are not automatically successful. Preserve all original evidence.
Charge the previous E1 wall time in `checkpoint.json` to the campaign budget;
exclude the user’s pause. Finish every registered seed and offline ROC job,
then generate the full run-level analysis and final clean manifests. The
original pilot operating-point file must remain unchanged.

Pilot inputs: `results/E01/20261011T113605Z-pilot/`.
Passed resource calibration: `results/E01/20261011T130817Z-calibration/`.
Correctness gate: `results/E00/20261011T100448Z/`.
Earlier failed resource forecasts remain preserved in their original folders.

Also fix and test the provenance output-exclusion argument-limit issue before
resuming: the large raw collection originally returned an unknown git status.
Its collection manifest records an independent bounded git-state probe of the
same clean commit. Individual scientific producers retain their original state.
Do not discard unknown provenance or silently force a dirty value.

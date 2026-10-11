E4 uses the frozen grid in experiments/PREREG.md through ../policy_campaign.py.
Targets and stationary renewal histories are compiled before policy outcomes.
No-outage runs remain in delivery estimates; blackhole endpoints condition on
common outage-bearing seeds. Losses have infinite effective latency.

Run `venv/bin/python -B experiments/E04/run.py --out results/E04/<run> --workers 8`
from a clean implementation commit after the E0/E16 and resource gates pass.
Raw traces stay in the adjacent ignored `<run>-raw` cache. The aggregate folder
contains configs, manifests, inventory, per-run data, paired contrasts and figures.

If all simulations completed but collection failed, use a new output folder with
`--collect-from results/E04/<original-run> --collect-log <original-log>`.
Collection validates every original producer manifest, configuration, seed and
metric identity before reusing it. Original producer manifests stay unchanged.
The new manifest identifies the collection commit and retains original producers
in its ledger. Runtime accounting includes the logged previous attempt plus an
explicit MODELLED reserve for unmeasured failed-analysis overhead.

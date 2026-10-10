"""
run_all.py
----------
Runs the whole Tier 1 pipeline (Experiments 1-5) on the 480-satellite dev
shell and writes, for every experiment,

    results/legacy-v0.9/dev/<expN_name>/
        <expN_name>.png      the figure
        <expN_name>.csv      exactly the plotted numbers (plus raw-run CSVs)
        manifest.json        commit, config, seeds, versions, output hashes

    python run_all.py                  # all five
    python run_all.py exp1_slack_sweep # just one (by name)

The v0 figures in results/legacy-v0/ are never touched.
"""

import sys
import time

import common
import scale
import exp1_slack_sweep
import exp2_header_overhead
import exp3_control_plane
import exp4_failure_resilience
import exp5_path_stretch

PRESET = 'dev'

EXPERIMENTS = [
    ('1  Slack factor sweep (headline)', exp1_slack_sweep),
    ('2  Header overhead',               exp2_header_overhead),
    ('3  Control-plane cost',            exp3_control_plane),
    ('4  Failure resilience',            exp4_failure_resilience),
    ('5  Fallback path stretch',         exp5_path_stretch),
]


def main(only=None, workers=None):
    """only: list of experiment names (e.g. ['exp2_header_overhead']); None = all."""
    print("=" * 66)
    print(" ChronoRoute -- Tier 1 simulation pipeline (legacy v0.9)")
    print("=" * 66)

    # the Tier 1 shell, and its own results folder
    scale.use_preset(PRESET, verbose=False)
    common.RESULTS_DIR = common.results_dir_for(PRESET)
    print(f"  results -> {common.RESULTS_DIR}")

    t0 = time.time()
    results = {}
    for name, module in EXPERIMENTS:
        if only is not None and module.NAME not in only:
            continue
        print(f"\n--- Experiment {name} " + "-" * (42 - len(name)))
        started = time.time()
        results[name] = module.run(workers=workers)
        print(f"    ({time.time() - started:.1f}s)")

    print("\n" + "=" * 66)
    print(f" {len(results)} experiment(s) complete in {time.time() - t0:.1f}s")
    print(f" Results are in  {common.RESULTS_DIR}")
    print("=" * 66)
    return results


if __name__ == '__main__':
    main(only=sys.argv[1:] or None)

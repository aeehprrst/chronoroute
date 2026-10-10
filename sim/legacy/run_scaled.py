"""
run_scaled.py
-------------
Runs the whole experiment suite at a chosen real constellation scale.

    python run_scaled.py                # Starlink Shell 1 (default)
    python run_scaled.py kuiper         # Kuiper Shell 1
    python run_scaled.py telesat        # Telesat Lightspeed polar
    python run_scaled.py dev            # the original Tier 1 shell
    python run_scaled.py starlink exp7_schedule_interval   # just one

Every experiment goes to  results/legacy-v0.9/<preset>/<expN_name>/  with
its PNG, the CSV of the plotted numbers and a manifest.json, so a scaled run
never overwrites another preset's results (or the frozen v0 figures).
"""

import sys
import time

import scale
import common


def main(preset='starlink', only=None, workers=None):
    """only: list of experiment names to run (None = all seven)."""
    print("=" * 68)
    print(f" ChronoRoute -- scaled run: {scale.describe(preset)}")
    print("=" * 68)

    # 1. reconfigure the constellation, 2. install the numpy fast path
    scale.use_preset(preset)
    scale.install_fast_topology()

    # 3. send every experiment to this preset's own results folder
    common.RESULTS_DIR = common.results_dir_for(preset)
    print(f"  results -> {common.RESULTS_DIR}")

    import exp1_slack_sweep, exp2_header_overhead, exp3_control_plane
    import exp4_failure_resilience, exp5_path_stretch
    import exp6_scale_validation, exp7_schedule_interval

    suite = [
        ('1  Slack factor sweep',      exp1_slack_sweep),
        ('2  Header overhead',         exp2_header_overhead),
        ('3  Control-plane cost',      exp3_control_plane),
        ('4  Failure resilience',      exp4_failure_resilience),
        ('5  Fallback path stretch',   exp5_path_stretch),
        ('7  Schedule interval sweep', exp7_schedule_interval),
        # Experiment 6 visits every preset; it restores this one when it
        # finishes, but running it last keeps the cache of this preset's
        # scenario useful for the others.
        ('6  Cross-scale validation',  exp6_scale_validation),
    ]

    t0 = time.time()
    results = {}
    for name, module in suite:
        if only is not None and module.NAME not in only:
            continue
        print(f"\n--- Experiment {name} " + "-" * max(0, 44 - len(name)))
        started = time.time()
        results[name] = module.run(workers=workers)
        print(f"    ({time.time() - started:.1f}s)")

    print("\n" + "=" * 68)
    print(f" Complete in {time.time() - t0:.1f}s -> {common.RESULTS_DIR}")
    print("=" * 68)
    return results


if __name__ == '__main__':
    preset = sys.argv[1] if len(sys.argv) > 1 else 'starlink'
    if preset not in scale.PRESETS:
        print(f"unknown preset {preset!r}. options: {list(scale.PRESETS)}")
        sys.exit(1)
    main(preset, only=sys.argv[2:] or None)

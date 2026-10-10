"""
run_scaled.py
-------------
Runs the whole experiment suite at a chosen real constellation scale.

    python run_scaled.py                # Starlink Shell 1 (default)
    python run_scaled.py kuiper         # Kuiper Shell 1
    python run_scaled.py telesat        # Telesat Lightspeed polar
    python run_scaled.py dev            # the original Tier 1 shell

Figures go to  ../results_<preset>/  so a scaled run never overwrites your
Tier 1 figures. Keep both: the comparison is itself a result.
"""

import os
import sys
import time

import scale
import common


def main(preset='starlink'):
    print("=" * 68)
    print(f" ChronoRoute -- scaled run: {scale.describe(preset)}")
    print("=" * 68)

    # 1. reconfigure the constellation, 2. install the numpy fast path
    scale.use_preset(preset)
    scale.install_fast_topology()

    # 3. send figures to their own directory
    out = os.path.join(os.path.dirname(os.path.abspath(common.__file__)),
                       '..', f'results_{preset}')
    os.makedirs(out, exist_ok=True)
    common.RESULTS_DIR = out
    print(f"  figures -> {os.path.abspath(out)}")

    # 4. import experiments AFTER reconfiguring, so they pick up the new size
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
        # Experiment 6 reconfigures the constellation itself, so it must run
        # last -- anything after it would inherit the wrong scale.
        ('6  Cross-scale validation',  exp6_scale_validation),
    ]

    t0 = time.time()
    results = {}
    for name, module in suite:
        print(f"\n--- Experiment {name} " + "-" * max(0, 44 - len(name)))
        started = time.time()
        results[name] = module.run()
        print(f"    ({time.time() - started:.1f}s)")

    print("\n" + "=" * 68)
    print(f" Complete in {time.time() - t0:.1f}s -> {os.path.abspath(out)}")
    print("=" * 68)
    return results


if __name__ == '__main__':
    preset = sys.argv[1] if len(sys.argv) > 1 else 'starlink'
    if preset not in scale.PRESETS:
        print(f"unknown preset {preset!r}. options: {list(scale.PRESETS)}")
        sys.exit(1)
    main(preset)
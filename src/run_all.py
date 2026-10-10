"""
run_all.py
----------
Runs the whole Tier 1 pipeline and produces all five result figures.

    python run_all.py
"""

import time
import exp1_slack_sweep
import exp2_header_overhead
import exp3_control_plane
import exp4_failure_resilience
import exp5_path_stretch

EXPERIMENTS = [
    ('1  Slack factor sweep (headline)', exp1_slack_sweep),
    ('2  Header overhead',               exp2_header_overhead),
    ('3  Control-plane cost',            exp3_control_plane),
    ('4  Failure resilience',            exp4_failure_resilience),
    ('5  Fallback path stretch',         exp5_path_stretch),
]


def main():
    print("=" * 66)
    print(" ChronoRoute -- Tier 1 simulation pipeline")
    print("=" * 66)

    t0 = time.time()
    results = {}

    for name, module in EXPERIMENTS:
        print(f"\n--- Experiment {name} " + "-" * (42 - len(name)))
        started = time.time()
        results[name] = module.run()
        print(f"    ({time.time() - started:.1f}s)")

    print("\n" + "=" * 66)
    print(f" All 5 experiments complete in {time.time() - t0:.1f}s")
    print(" Figures are in  ../results/")
    print("=" * 66)
    return results


if __name__ == '__main__':
    main()
#!/usr/bin/env python3
"""
scratch_regressions.py
----------------------
Regression tests for the bug fixes in the Assessment 6-8 ns-3 programs
(~/ns-3-dev/scratch/{bottleneck,crh,tcrh}-experiment.cc), bugs #18-#21 of the
Phase 1 plan. They run the BUILT programs and check what they print / write:

  #18 tcrh-experiment: integer-ms truncation. With zero jitter and slack 1.0
      every packet reaches hop 1 about 0.13 ms (the transmission time) after its
      deadline, so every one must be flagged; at slack 1.1 none may be. The
      old code compared floor(now in ms) with the deadline and missed them all.
      The program's own self-test (PART A) also checks the integer helpers.
  #19 bottleneck-experiment: the "mean RTT" column was FlowMonitor's one-way
      delay (delaySum / rxPackets). No "RTT" label may remain; the CSV column
      is mean_one_way_delay_ms.
  #20 crh-experiment: the path trace recorded the SID the SENDER chose, so the
      PASS check compared the intended path with itself. With --miswire=1 one
      CRH-FIB entry is deliberately wrong (n1 sends SID 7 to n5, not n6); the
      trace must show the node that really received the packet and FAIL.
  #21 tcrh-experiment: every deviation in the degraded phase counted as a
      "correct detection". With a null fault (--degraded equal to the normal
      20 ms, i.e. factor 1.0) nothing can be detected, so the counterfactual
      (paired) detection rate must be exactly 0 at every slack; the old
      scoring reported up to 100 %.

Usage (inside WSL, from anywhere):
    ~/chronoroute/venv/bin/python -B \
        ~/chronoroute/ns3/contrib/chronoroute/test/scratch_regressions.py \
        [--bin-dir ~/ns-3-dev/build/scratch] [--only 18,21]

--bin-dir may point at copies of the OLD binaries to watch the tests fail.
Exit status 0 only if every selected check passes.
"""

import argparse
import csv
import glob
import math
import os
import subprocess
import sys
import tempfile

DEFAULT_BIN_DIR = os.path.expanduser("~/ns-3-dev/build/scratch")


def find_binary(bin_dir, name):
    # ns3.44-<name>-<profile>: the part after the name must be the profile
    # alone, or "tcrh-experiment" would also match "tcrh-experiment-a8-default"
    hits = sorted(glob.glob(os.path.join(bin_dir, f"ns3*-{name}-*")))
    hits = [h for h in hits if os.access(h, os.X_OK) and not h.endswith(".o")
            and "-" not in os.path.basename(h).split(f"-{name}-", 1)[1]]
    if not hits:
        raise FileNotFoundError(f"no built {name} in {bin_dir}")
    return hits[0]


def run(cmd, cwd):
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=900)
    return proc.returncode, proc.stdout + proc.stderr


def read_rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


class Check:
    def __init__(self, bug):
        self.bug = bug
        self.problems = []

    def expect(self, cond, what):
        if not cond:
            self.problems.append(what)
        return cond

    @property
    def ok(self):
        return not self.problems


def check_18(bin_dir, work):
    c = Check("#18 tcrh-experiment integer-ms truncation")
    exe = find_binary(bin_dir, "tcrh-experiment")
    sweep = os.path.join(work, "t18_sweep.csv")
    code, out = run([exe, "--jitterMs=0", "--packets=20", f"--sizeCsv={work}/t18_sizes.csv",
                     f"--sweepCsv={sweep}"], work)
    if not c.expect(code == 0, f"exit code {code} (self-test or option failed): {out[-400:]!r}"):
        return c
    c.expect("SELF-TEST FAILED" not in out, "self-test failed")
    rows = read_rows(sweep)
    col = "fp_pct" if "fp_pct" in rows[0] else "false_positive_pct"  # v0.9 name / old name
    for r in rows:
        s = float(r["slack"])
        fp = float(r[col])
        if math.isclose(s, 1.0):
            c.expect(fp == 100.0, f"S=1.0, zero jitter: {fp}% flagged, expected 100% "
                                  "(each packet is ~0.13 ms late at hop 1)")
        else:
            c.expect(fp == 0.0, f"S={s}, zero jitter: {fp}% flagged, expected 0%")
    return c


def check_19(bin_dir, work):
    c = Check("#19 bottleneck-experiment 'RTT' is one-way delay")
    exe = find_binary(bin_dir, "bottleneck-experiment")
    out_csv = os.path.join(work, "t19.csv")
    if os.path.exists(out_csv):
        os.remove(out_csv)
    code, out = run([exe, "--time=2", "--verbose=1", f"--csv={out_csv}"], work)
    if not c.expect(code == 0, f"exit code {code}: {out[-400:]!r}"):
        return c
    c.expect("RTT" not in out, "a label still says RTT")
    with open(out_csv) as f:
        header = f.readline().strip().split(",")
    c.expect("mean_one_way_delay_ms" in header, f"CSV header {header} lacks mean_one_way_delay_ms")
    c.expect(not any("rtt" in h.lower() for h in header), "CSV header mentions rtt")
    c.expect("mean_delay_ms" not in header, "ambiguous mean_delay_ms column still present")
    return c


def check_20(bin_dir, work):
    c = Check("#20 crh-experiment self-referential path check")
    exe = find_binary(bin_dir, "crh-experiment")
    code, out = run([exe, "--quiet=1", f"--pathCsv={work}/t20_ok.csv"], work)
    c.expect(code == 0 and "OVERALL: PASS" in out, f"normal run should PASS (exit {code})")
    c.expect("actual   : n0 -> n2 -> n3 -> n4 -> n5 -> n6" in out, "long path trace wrong")
    code, out = run([exe, "--quiet=1", "--miswire=1", f"--pathCsv={work}/t20_bad.csv"], work)
    c.expect(code != 0 and "OVERALL: FAIL" in out,
             f"a miswired FIB must make the check FAIL (exit {code})")
    c.expect("actual   : n0 -> n1 -> n5" in out,
             "trace must show n5, the node that really received packet 1")
    return c


def check_21(bin_dir, work):
    c = Check("#21 tcrh-experiment confounded detection metric")
    exe = find_binary(bin_dir, "tcrh-experiment")
    sweep = os.path.join(work, "t21_null.csv")
    code, out = run([exe, "--degraded=20", "--packets=60", f"--sizeCsv={work}/t21_sizes.csv",
                     f"--sweepCsv={sweep}"], work)
    if not c.expect(code == 0, f"exit code {code}: {out[-400:]!r}"):
        return c
    rows = read_rows(sweep)
    col = "detect_attributed_pct" if "detect_attributed_pct" in rows[0] else "detection_pct"
    for r in rows:
        v = float(r[col])
        c.expect(math.isnan(v) or v == 0.0,
                 f"null fault, S={r['slack']}: {col} = {v}%, expected 0 (nothing to detect)")
        if "attributed" in r:
            c.expect(int(r["attributed"]) == 0, f"S={r['slack']}: attributed = {r['attributed']}")
    # the regular run: the null-fault control arm and the no-fault arm must agree
    # packet for packet, and the fault may never UN-flag a packet
    sweep2 = os.path.join(work, "t21_fault.csv")
    code, out = run([exe, "--packets=60", f"--sizeCsv={work}/t21_sizes.csv",
                     f"--sweepCsv={sweep2}"], work)
    if not c.expect(code == 0, f"exit code {code}"):
        return c
    rows = read_rows(sweep2)
    if c.expect("null_attributed" in rows[0], "no null-fault control columns"):
        for r in rows:
            c.expect(int(r["null_attributed"]) == 0 and int(r["null_differs"]) == 0,
                     f"S={r['slack']}: null-fault arm differs from the no-fault arm")
            c.expect(int(r["unflagged_by_fault"]) == 0,
                     f"S={r['slack']}: the fault un-flagged {r['unflagged_by_fault']} packets")
    return c


def expected_operating_point(rows, fpr_max=1.0, min_det=1.0):
    """
    The Python exp1 rule (sim/legacy/exp1_slack_sweep.choose_operating_point):
    the highest paired detection whose false-alarm rate is <= fpr_max %, and
    only if that detection is >= min_det %; ties to the lower false-alarm
    rate, then the larger slack. None if no slack qualifies.
    """
    feasible = []
    for r in rows:
        det, fp, s = float(r["detect_attributed_pct"]), float(r["fp_pct"]), float(r["slack"])
        if not math.isnan(det) and fp <= fpr_max and det >= min_det and det > 0:
            feasible.append((det, -fp, s))
    return max(feasible)[2] if feasible else None


def check_21op(bin_dir, work):
    """
    #21, part 2 (P1 review): the fixed program still recommended S = 1.30 by
    Youden J (detection minus false alarms, 7 % false alarms there). It must
    use the same rule as Python's Experiment 1 (false alarms <= 1 %, detection
    >= 1 %), print that S or "no operating point", and never present a Youden
    pick as the recommendation.
    """
    c = Check("#21 tcrh-experiment operating point: FPR-limited, not Youden J")
    exe = find_binary(bin_dir, "tcrh-experiment")
    for tag, extra in (("fault", []), ("null", ["--degraded=20"])):
        sweep = os.path.join(work, f"t21op_{tag}.csv")
        code, out = run([exe, "--packets=300", f"--sizeCsv={work}/t21op_sizes.csv",
                         f"--sweepCsv={sweep}"] + extra, work)
        if not c.expect(code == 0, f"{tag}: exit code {code}"):
            return c
        c.expect("Best operating point (max detections minus false alarms" not in out,
                 f"{tag}: still recommends the Youden J slack")
        want = expected_operating_point(read_rows(sweep))
        lines = [ln for ln in out.splitlines() if ln.strip().startswith("Operating point")]
        if want is None:
            c.expect("no operating point" in out.lower(),
                     f"{tag}: no slack qualifies, but the program does not say so")
            c.expect(not any("S = " in ln for ln in lines),
                     f"{tag}: printed an operating point although none qualifies: {lines}")
        elif c.expect(len(lines) == 1, f"{tag}: expected one 'Operating point' line, got {lines}"):
            c.expect(f"S = {want:.2f}" in lines[0],
                     f"{tag}: expected S = {want:.2f} (FPR <= 1 %, detection >= 1 %), got {lines[0]!r}")
    return c


CHECKS = {"18": check_18, "19": check_19, "20": check_20, "21": check_21, "21op": check_21op}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Regression tests for ns-3 scratch bugs #18-#21")
    ap.add_argument("--bin-dir", default=DEFAULT_BIN_DIR)
    ap.add_argument("--only", default=",".join(CHECKS))
    args = ap.parse_args(argv)
    failed = 0
    with tempfile.TemporaryDirectory(prefix="cr-scratch-reg-") as work:
        for key in args.only.split(","):
            try:
                c = CHECKS[key](args.bin_dir, work)
            except (FileNotFoundError, KeyError, ValueError, subprocess.TimeoutExpired) as err:
                c = Check(f"#{key}")
                c.problems.append(f"could not run: {err!r}")
            print(f"{'PASS' if c.ok else 'FAIL'}  {c.bug}")
            for p in c.problems:
                print(f"      - {p}")
            failed += not c.ok
    print(f"{len(args.only.split(',')) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

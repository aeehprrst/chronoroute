#!/usr/bin/env python3
"""
run_tcrh_sweep.py
-----------------
Regenerate EVERY file of results/legacy-v0.9/ns3/tcrh_sweep/ (the re-scored
ns-3 T-CRH slack sweep, changelog section 10) from the programs in this
repository, and write its manifest.json against THIS repository's commit.

    make ns3-legacy                       # syncs, builds, then runs this
    NS3_DIR=~/ns-3-dev venv/bin/python -B ns3/run_tcrh_sweep.py   # programs already built

Programs (ns3/scratch/, linked into $NS3_DIR/scratch by tools/ns3-sync.sh):
  tcrh-experiment.cc      the fixed program (bugs #18, #21; FPR-limited operating point)
  tcrh-experiment-a8.cc   the original Assessment 8 program, only for the
                          old-code null-fault evidence file
Plots: ns3/plots/plot_tcrh.py (run in the output folder).

Outputs (all in the output folder; every run is deterministic, so a re-run
gives byte-identical CSVs):
  tcrh_sweep_v09.csv, tcrh_sweep_v09.log, tcrh_sizes_v09.csv   RngRun 1, 1000 packets per S
  tcrh_sweep_v09_n60.csv                                       60 packets per S (Assessment 8 size)
  tcrh_sweep_v09_nullfault.csv                                 fault 20 -> 20 ms (null)
  tcrh_sweep_v09_degraded25.csv                                fault 20 -> 25 ms
  tcrh_sweep_v09_runs1-5.csv                                   RngRun 1..5, one header, rows in run order
  tcrh_sweep_v09_runs1-5_summary.csv                           mean and 95% t-CI over the 5 runs
  tcrh_sweep_v09_oldcode_nullfault.csv                         the OLD program, null fault
  fig1_tcrh_size_v09.png, fig2_tcrh_sweep_v09.png              plot_tcrh.py
  v0_tcrh_sweep.csv                                            Assessment 8 output, copied from
                                                               ns3/legacy/ (= git show 6314c8a:
                                                               tcrh_sweep.csv in the student's
                                                               own ns-3 tree; that commit exists
                                                               nowhere else, so it is stored here)

All or nothing: every step that can fail (programs built, the stored
Assessment 8 CSV intact) is checked first, and the programs and plots write
into a staging folder next to the output folder. Only when every step has
succeeded are the files moved in and the manifest written, so a failed run
never leaves new CSVs next to old figures and an old manifest. Files in the
output folder that this script does not produce (ns3_rescore_v09.md) are kept.

The run (RngRun), not the packet, is the unit of analysis for the headline
numbers: the per-packet Wilson intervals in the sweep CSVs describe one run
only. The summary CSV gives the mean over RngRun 1-5 with a Student-t 95%
interval (4 degrees of freedom), like the Python experiments.
"""

import argparse
import csv
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sim"))
sys.path.insert(0, str(REPO / "sim" / "legacy"))

from chronoroute import __version__                              # noqa: E402
from chronoroute.provenance import RunTimer, write_manifest      # noqa: E402

NS3_DIR = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3-dev"))
OUT = REPO / "results" / "legacy-v0.9" / "ns3" / "tcrh_sweep"
NS3_BASE = "ns-3.44 (43dce6710b8d) + ChronoRoute Assessment 6-8 snapshot 6314c8a76c21"
A8_COMMIT = "6314c8a76c217d04b318b41cdad16e8087d40a64"
# The Assessment 8 sweep CSV, stored in this repository because commit
# 6314c8a exists only in the student's own ~/ns-3-dev (never pushed): reading
# it with `git show` made the script crash on every other ns-3 tree.
A8_CSV = REPO / "ns3" / "legacy" / "v0_tcrh_sweep.csv"
A8_CSV_SHA256 = "63cb2ef58521dcae87e1bd2c5776eed7484b7f4b7057d0a83e478685276311e9"
PLOT_SCRIPT = REPO / "ns3" / "plots" / "plot_tcrh.py"
RUNS = [1, 2, 3, 4, 5]
PACKETS = 1000


def binary(name):
    # ns3.44-<name>-<profile>: the part after the name must be the profile
    # alone, or "tcrh-experiment" would also match "tcrh-experiment-a8-default"
    hits = [h for h in sorted(glob.glob(str(NS3_DIR / "build" / "scratch" / f"ns3*-{name}-*")))
            if os.access(h, os.X_OK) and not h.endswith(".o")
            and "-" not in Path(h).name.split(f"-{name}-", 1)[1]]
    if not hits:
        sys.exit(f"run_tcrh_sweep: {name} is not built in {NS3_DIR}; run `make ns3-legacy`")
    return hits[0]


def run(cmd, cwd, log=None, env=None):
    """Run one program; keep its stdout as `log` if asked. Stop on failure."""
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=1800, env=env)
    if proc.returncode != 0:
        sys.exit(f"run_tcrh_sweep: {' '.join(map(str, cmd))} failed:\n{proc.stdout}{proc.stderr}")
    if log is not None:
        Path(log).write_text(proc.stdout, encoding="utf-8")
    return proc.stdout


def concat_runs(parts, dest):
    """One header, then every run's rows in run order (the 5-run file)."""
    with open(dest, "w", encoding="utf-8", newline="") as out:
        for i, part in enumerate(parts):
            lines = Path(part).read_text(encoding="utf-8").splitlines(keepends=True)
            out.writelines(lines if i == 0 else lines[1:])


def summarise_runs(runs_csv, dest):
    """Mean and 95% t-CI over RngRuns, per slack: the run is the unit of analysis."""
    import common                     # the same t quantile and CI as the Python experiments
    with open(runs_csv, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    slacks = sorted({float(r["slack"]) for r in rows})
    out = []
    for s in slacks:
        rs = [r for r in rows if float(r["slack"]) == s]
        entry = {"slack": s, "n_runs": len({r["rng_run"] for r in rs})}
        for col, name in (("fp_pct", "false_alarm"), ("detect_attributed_pct", "detection"),
                          ("null_attributed", "null_attributed")):
            vals = [float(r[col]) for r in rs]
            vals = [v for v in vals if v == v]                  # drop NaN (S = 1.0 detection)
            mean, lo, hi, n = common.mean_ci(vals, bounds=(0.0, 100.0) if col != "null_attributed"
                                             else None)
            entry.update({f"{name}_mean": mean, f"{name}_ci95_lo": lo, f"{name}_ci95_hi": hi,
                          f"{name}_min": min(vals) if vals else None,
                          f"{name}_max": max(vals) if vals else None})
        out.append(entry)
    fields = list(out[0])
    with open(dest, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for e in out:
            w.writerow({k: ("" if v is None else (repr(v) if isinstance(v, float) else v))
                        for k, v in e.items()})
    return out


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def assessment8_csv():
    """The stored Assessment 8 CSV, after checking it is the pinned file."""
    if not A8_CSV.is_file():
        sys.exit(f"run_tcrh_sweep: {A8_CSV} is missing (the Assessment 8 sweep CSV)")
    data = A8_CSV.read_bytes()
    if hashlib.sha256(data).hexdigest() != A8_CSV_SHA256:
        sys.exit(f"run_tcrh_sweep: {A8_CSV} is not the Assessment 8 file "
                 f"(sha256 must be {A8_CSV_SHA256}); restore it with git")
    return data


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    out = args.out.resolve()
    # everything that can be checked up front is checked before anything is written
    new = binary("tcrh-experiment")
    old = binary("tcrh-experiment-a8")
    v0 = assessment8_csv()
    if not PLOT_SCRIPT.is_file():
        sys.exit(f"run_tcrh_sweep: plot script {PLOT_SCRIPT} not found")

    # Staging folder next to the output folder (same file system, so the final
    # moves are renames). It is removed whatever happens; the output folder is
    # only touched once every program and the plots have succeeded.
    out.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{out.name}.staging-", dir=out.parent))
    try:
        with RunTimer() as timer, tempfile.TemporaryDirectory(prefix="cr-ns3-sweep-") as tmp:
            sizes_tmp = f"--sizeCsv={tmp}/sizes.csv"
            # run in the staging folder with relative names, so the log says
            # "wrote tcrh_sweep_v09.csv" and not a path on this machine
            run([new, f"--packets={PACKETS}", "--RngRun=1", "--sizeCsv=tcrh_sizes_v09.csv",
                 "--sweepCsv=tcrh_sweep_v09.csv"], stage, log=stage / "tcrh_sweep_v09.log")
            run([new, "--packets=60", "--RngRun=1", sizes_tmp,
                 f"--sweepCsv={stage}/tcrh_sweep_v09_n60.csv"], tmp)
            run([new, f"--packets={PACKETS}", "--degraded=20", sizes_tmp,
                 f"--sweepCsv={stage}/tcrh_sweep_v09_nullfault.csv"], tmp)
            run([new, f"--packets={PACKETS}", "--degraded=25", sizes_tmp,
                 f"--sweepCsv={stage}/tcrh_sweep_v09_degraded25.csv"], tmp)
            parts = []
            for r in RUNS:
                part = f"{tmp}/run{r}.csv"
                run([new, f"--packets={PACKETS}", f"--RngRun={r}", sizes_tmp,
                     f"--sweepCsv={part}"], tmp)
                parts.append(part)
            concat_runs(parts, stage / "tcrh_sweep_v09_runs1-5.csv")
            summary = summarise_runs(stage / "tcrh_sweep_v09_runs1-5.csv",
                                     stage / "tcrh_sweep_v09_runs1-5_summary.csv")
            # the OLD program (Assessment 8) on a null fault: bug #21 evidence
            run([old, "--degraded=20", sizes_tmp,
                 f"--sweepCsv={stage}/tcrh_sweep_v09_oldcode_nullfault.csv"], tmp)
            # the Assessment 8 output itself (checked against its pinned sha256 above)
            (stage / "v0_tcrh_sweep.csv").write_bytes(v0)
            # figures, from the CSVs just written
            run([sys.executable, "-B", str(PLOT_SCRIPT)], stage,
                env=dict(os.environ, MPLBACKEND="Agg"))
        # every step succeeded: move the new files in (renames on one file system)
        out.mkdir(exist_ok=True)
        for f in sorted(stage.iterdir()):
            os.replace(f, out / f.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    outputs = sorted(str(p) for p in out.iterdir()
                     if p.is_file() and p.name != "manifest.json" and not p.name.startswith("."))
    manifest = write_manifest(
        out, tool="ns-3 scratch/tcrh-experiment.cc (via ns3/run_tcrh_sweep.py)",
        tool_version=__version__,
        command=["ns3/run_tcrh_sweep.py"] + (argv if argv is not None else sys.argv[1:]),
        config={
            "experiment": "ns3_tcrh_slack_sweep_rescored",
            "topology": "7-node linear IPv4/UDP, 20 ms links",
            "fault": "n3-n4 delay 20 -> 45 ms (main), 20 -> 25 ms (degraded25), "
                     "20 -> 20 ms (nullfault)",
            "jitter": "Exp(mean 2 ms) per sending hop, drawn once per packet",
            "packets_per_slack": PACKETS,
            "slacks": [1.0, 1.1, 1.2, 1.3, 1.5, 1.75, 2.0, 2.5, 3.0],
            "header": "v0 T-CRH, 1 ms units, ceil-cumulative deltas",
            "scoring": "paired counterfactual (healthy / fault / null-fault copies)",
            "operating_point_rule": "highest paired detection with false alarms <= 1 % and "
                                    "detection >= 1 % (as Python exp1); Youden J printed "
                                    "for continuity only",
            "ci_headline": "Student-t 95% over RngRun 1-5 (the run is the unit); per-packet "
                           "Wilson intervals in the sweep CSVs are per-run diagnostics",
        },
        seeds=RUNS, outputs=outputs,
        labels={"topology": "MODELLED", "link_fault": "MODELLED", "jitter": "MODELLED",
                "header_bytes": "REAL"},
        extra={
            "ns3_dir": str(NS3_DIR),
            "ns3_base": NS3_BASE,
            "programs": {
                "ns3/scratch/tcrh-experiment.cc": sha256(REPO / "ns3/scratch/tcrh-experiment.cc"),
                "ns3/scratch/tcrh-experiment-a8.cc": sha256(REPO / "ns3/scratch/tcrh-experiment-a8.cc"),
                "ns3/plots/plot_tcrh.py": sha256(REPO / "ns3/plots/plot_tcrh.py"),
            },
            "binaries": {Path(new).name: sha256(new), Path(old).name: sha256(old)},
            "rng_runs": {"tcrh_sweep_v09.csv": 1, "tcrh_sweep_v09_n60.csv": 1,
                         "tcrh_sweep_v09_nullfault.csv": 1, "tcrh_sweep_v09_degraded25.csv": 1,
                         "tcrh_sweep_v09_runs1-5.csv": RUNS,
                         "tcrh_sweep_v09_oldcode_nullfault.csv": 1},
            "v0_tcrh_sweep.csv": f"ns3/legacy/v0_tcrh_sweep.csv (sha256 {A8_CSV_SHA256[:12]}), "
                                 f"= git show {A8_COMMIT[:7]}:tcrh_sweep.csv in the original "
                                 "ns-3 tree (Assessment 8, confounded score)",
            "ns3_rescore_v09.md": "hand-written notes; not produced by this run",
        },
        timer=timer, repo_dir=str(REPO))
    for e in summary:
        if e["slack"] in (1.3, 1.5):
            print(f"  S = {e['slack']}: false alarms {e['false_alarm_mean']:.2f} % "
                  f"[{e['false_alarm_ci95_lo']:.2f}, {e['false_alarm_ci95_hi']:.2f}], detection "
                  f"{e['detection_mean']:.2f} % [{e['detection_ci95_lo']:.2f}, "
                  f"{e['detection_ci95_hi']:.2f}] over RngRun 1-5")
    print(f"run_tcrh_sweep: wrote {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

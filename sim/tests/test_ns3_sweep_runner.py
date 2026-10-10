"""
Tests for ns3/run_tcrh_sweep.py (`make ns3-legacy`), the script that
regenerates results/legacy-v0.9/ns3/tcrh_sweep/.

What is checked (P1 review, residue of finding 21):
  - it works on ANY ns-3.44 tree. v0.9 copied the Assessment 8 CSV with
    `git -C $NS3_DIR show 6314c8a:tcrh_sweep.csv`, a commit that exists only
    in the student's own ~/ns-3-dev, so on a fresh tree the script crashed;
    the CSV is now stored in the repository (ns3/legacy/v0_tcrh_sweep.csv)
    and checked against a pinned sha256;
  - a failed step leaves the output folder exactly as it was. v0.9 let the
    sweeps write straight into it and crashed afterwards, leaving new CSVs
    next to old figures and the old manifest.

No ns-3 build is needed: a fake ns-3 tree holds stand-in programs that write
the published CSVs (and the published log), so a correct runner must
reproduce the published folder byte for byte, apart from the figures (which
depend on the matplotlib build) and the manifest.
"""

import hashlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PUBLISHED = REPO / "results" / "legacy-v0.9" / "ns3" / "tcrh_sweep"
STORED_A8 = REPO / "ns3" / "legacy" / "v0_tcrh_sweep.csv"
A8_COMMIT = "6314c8a76c217d04b318b41cdad16e8087d40a64"

# every file the runner regenerates whose bytes do not depend on the plotting library
REPRODUCED = ["tcrh_sizes_v09.csv", "tcrh_sweep_v09.csv", "tcrh_sweep_v09.log",
              "tcrh_sweep_v09_n60.csv", "tcrh_sweep_v09_nullfault.csv",
              "tcrh_sweep_v09_degraded25.csv", "tcrh_sweep_v09_runs1-5.csv",
              "tcrh_sweep_v09_runs1-5_summary.csv", "tcrh_sweep_v09_oldcode_nullfault.csv",
              "v0_tcrh_sweep.csv"]
FIGURES = ["fig1_tcrh_size_v09.png", "fig2_tcrh_sweep_v09.png"]

FAKE_PROGRAM = '''#!{python} -B
"""Stand-in for an ns-3 scratch program: writes what the real one wrote."""
import shutil
import sys
from pathlib import Path

SRC = Path({src!r})          # the published results folder
OLD = {old!r}                # the Assessment 8 program?
CRASH = {crash!r}

opts = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
if CRASH:
    sys.exit("fake ns-3 program: simulated crash")
if "sizeCsv" in opts:
    shutil.copyfile(SRC / "tcrh_sizes_v09.csv", opts["sizeCsv"])
sweep = Path(opts["sweepCsv"])
if OLD:
    shutil.copyfile(SRC / "tcrh_sweep_v09_oldcode_nullfault.csv", sweep)
elif opts.get("degraded") == "20":
    shutil.copyfile(SRC / "tcrh_sweep_v09_nullfault.csv", sweep)
elif opts.get("degraded") == "25":
    shutil.copyfile(SRC / "tcrh_sweep_v09_degraded25.csv", sweep)
elif opts.get("packets") == "60":
    shutil.copyfile(SRC / "tcrh_sweep_v09_n60.csv", sweep)
elif sweep.name == "tcrh_sweep_v09.csv":
    shutil.copyfile(SRC / "tcrh_sweep_v09.csv", sweep)
    sys.stdout.write((SRC / "tcrh_sweep_v09.log").read_text(encoding="utf-8"))
else:                        # one RngRun of the 5-run file
    lines = (SRC / "tcrh_sweep_v09_runs1-5.csv").read_text(encoding="utf-8").splitlines(True)
    col = lines[0].rstrip("\\n").split(",").index("rng_run")
    keep = [ln for ln in lines[1:] if ln.rstrip("\\n").split(",")[col] == opts["RngRun"]]
    sweep.write_text("".join([lines[0]] + keep), encoding="utf-8")
'''


@pytest.fixture
def runner(monkeypatch):
    """The runner as a module (it is a script, not part of the package)."""
    spec = importlib.util.spec_from_file_location("run_tcrh_sweep_under_test",
                                                  REPO / "ns3" / "run_tcrh_sweep.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fake_ns3_tree(root, crash_old=False):
    """An ns-3 tree as a fresh ns-3.44 checkout would look after the build:
    the two programs in build/scratch, and a git repository WITHOUT the
    student's Assessment 6-8 commit 6314c8a."""
    scratch = root / "build" / "scratch"
    scratch.mkdir(parents=True)
    for name, old in (("tcrh-experiment", False), ("tcrh-experiment-a8", True)):
        prog = scratch / f"ns3.44-{name}-default"
        prog.write_text(FAKE_PROGRAM.format(python=sys.executable, src=str(PUBLISHED),
                                            old=old, crash=old and crash_old),
                        encoding="utf-8")
        prog.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


def snapshot(folder):
    """{name: bytes} of every file in a folder (and nothing for a missing one)."""
    folder = Path(folder)
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())} if folder.is_dir() else {}


def test_stored_assessment8_csv_matches_its_pinned_hash(runner):
    data = STORED_A8.read_bytes()
    assert hashlib.sha256(data).hexdigest() == runner.A8_CSV_SHA256
    assert data == (PUBLISHED / "v0_tcrh_sweep.csv").read_bytes()
    assert data.startswith(b"slack,false_positive_pct,detection_pct,delivered_pct\n")


def test_stored_assessment8_csv_is_the_commit_6314c8a_file():
    """Where the original ns-3 tree is available (the student's machine), the
    stored copy must be exactly `git show 6314c8a:tcrh_sweep.csv`."""
    ns3 = Path.home() / "ns-3-dev"
    if shutil.which("git") is None or not (ns3 / ".git").exists():
        pytest.skip("the original ~/ns-3-dev tree is not on this machine")
    got = subprocess.run(["git", "-C", str(ns3), "show", f"{A8_COMMIT}:tcrh_sweep.csv"],
                         capture_output=True)
    if got.returncode != 0:
        pytest.skip("~/ns-3-dev does not contain commit 6314c8a")
    assert got.stdout == STORED_A8.read_bytes()


def test_runs_on_a_fresh_ns3_tree_and_reproduces_the_published_files(runner, tmp_path,
                                                                     monkeypatch):
    monkeypatch.setattr(runner, "NS3_DIR", fake_ns3_tree(tmp_path / "ns-3.44"))
    out = tmp_path / "results" / "tcrh_sweep"
    assert runner.main(["--out", str(out)]) == 0

    for name in REPRODUCED:
        assert (out / name).read_bytes() == (PUBLISHED / name).read_bytes(), name
    assert (out / "v0_tcrh_sweep.csv").read_bytes() == STORED_A8.read_bytes()
    for name in FIGURES:
        assert (out / name).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", name

    from chronoroute.provenance import validate_manifest
    manifest = validate_manifest(out)                 # raises if invalid or stale
    assert {o["path"] for o in manifest["outputs"]} == set(REPRODUCED + FIGURES)
    # nothing left behind next to the output folder (the staging folder is gone)
    assert sorted(p.name for p in out.parent.iterdir()) == ["tcrh_sweep"]


@pytest.mark.parametrize("failure", ["program_crashes", "stored_csv_corrupt"])
def test_a_failed_run_leaves_the_output_folder_untouched(runner, tmp_path, monkeypatch,
                                                        failure):
    monkeypatch.setattr(runner, "NS3_DIR",
                        fake_ns3_tree(tmp_path / "ns-3.44",
                                      crash_old=failure == "program_crashes"))
    if failure == "stored_csv_corrupt":
        bad = tmp_path / "v0_tcrh_sweep.csv"
        bad.write_bytes(STORED_A8.read_bytes().replace(b"100", b"99", 1))
        monkeypatch.setattr(runner, "A8_CSV", bad)

    out = tmp_path / "results" / "tcrh_sweep"
    out.mkdir(parents=True)
    # an earlier, complete result: its files must survive a failed re-run unchanged
    (out / "tcrh_sweep_v09.csv").write_text("old sweep\n", encoding="utf-8")
    (out / "fig2_tcrh_sweep_v09.png").write_bytes(b"old figure")
    (out / "manifest.json").write_text("{}\n", encoding="utf-8")
    (out / "ns3_rescore_v09.md").write_text("hand-written notes\n", encoding="utf-8")
    before = snapshot(out)

    with pytest.raises(SystemExit) as stop:
        runner.main(["--out", str(out)])
    assert stop.value.code not in (0, None)
    assert snapshot(out) == before
    assert sorted(p.name for p in out.parent.iterdir()) == ["tcrh_sweep"]

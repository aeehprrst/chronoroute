#!/usr/bin/env python3
"""
run_leo.py
----------
Course milestone "LEO topology + time-varying schedule in ns-3": build the
ns-3 program chronoroute-leo, run it on a scenario bundle, check it against
Python, and collect everything into results/course-milestone/<run-id>/ with a
manifest.json.

From git alone (the bundle is rebuilt from a named recipe, deterministically):

    venv/bin/python -B ns3/run_leo.py --recipe c5-463-60s
    venv/bin/python -B ns3/run_leo.py --recipe c5-463-10s-small

or on a bundle that already exists:

    venv/bin/python -B ns3/run_leo.py --bundle /tmp/cr-sa/bundles/c5-463-60s

One "run" is three ns-3 runs of the same bundle with the same seed:

  nofault/  every flow, no fault: the baseline, and the E16-lite cross-check
            (ns-3 versus the Python prediction, packet by packet)
  fault/    every flow, one laser link on a scheduled path slowed down
            ("up but slow") for a while: detection
  anim/     the NetAnim slice: only the fault flow, only 100-300 satellites
            around its path, a few seconds around the fault start

plus, with --sensitivity-rates (default 1Mbps,500kbps,250kbps), one more fault run per
rate (sensitivity/<rate>/, no capture; it keeps only the rows of the probes
that met the slowed link, slowed_link_probes.csv.gz): the same fault at a
milder slow-down, to show how detection depends on its size. A run whose fault makes no probe
late fails chronoroute-leo's "the fault made probes late" self-check on
purpose; that one failure is expected there and recorded, any other is fatal.

Then the analysis (chronoroute.export.ns3_crosscheck):

  flow_summary.csv      per run and flow: PDR, latency p50/p99, drops, fraction
                        of delivered probes flagged (DEV) before/during/after
  detection.json        flagged among probes that crossed the slowed link
                        during the fault, versus the same probes without fault
  sensitivity.json      the same detection figures for each milder fault rate
  margins.json          deadline margins of the on-time probes of the no-fault
                        run: at the final hop and the smallest on each path
  loss_causes.json      which kind of link (laser, ground up/down) the
                        link-down losses happened on
  crosscheck_nofault.json   ns-3 vs Python: path, outcome, per-hop times
  crosscheck_fault.json     the same for the fault run, leaving out probes that
                            met the slowed link during the fault
  pcap_check.json       tools/wireshark/check_pcap.sh on both captures, plus
                        Segments Left order and DEV-in-window checks
  run.log               everything this script printed
  manifest.json         provenance (chronoroute.provenance.write_manifest)

Large files are gzip-compressed deterministically (packets.csv.gz,
capture.pcap.gz; tshark and Wireshark read .pcap.gz directly). The NetAnim
XML stays plain because NetAnim cannot read gzip.

All or nothing: everything is written to <run-id>.staging first and renamed
to <run-id> only when every step succeeded.
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Never write __pycache__ into the source tree (project convention, like
# `python -B`), neither here nor in any Python child (cr, the ./ns3 script).
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sim"))

from chronoroute import __version__  # noqa: E402
from chronoroute.export import ns3_crosscheck as cc  # noqa: E402
from chronoroute.provenance import RunTimer, write_manifest  # noqa: E402

NS3_DIR = Path(os.environ.get("NS3_DIR", Path.home() / "ns-3-dev"))
NS3_JOBS = 8          # WSL has 7.6 GiB of RAM: never more than 8 compile jobs
PROGRAM = "chronoroute-leo"

# The milestone bundles as `cr export bundle` arguments (everything except
# --out). The bundle builder is deterministic, so these recipes plus the
# pinned snapshot in git give byte-identical bundles: the results can be
# reproduced from a clean checkout with --recipe.
MILESTONE_CITIES = ("Chennai,Mumbai,London,New York,Singapore,Sydney,Tokyo,Johannesburg,"
                    "Sao Paulo,Frankfurt")
RECIPES = {
    "c5-463-60s": [
        "export", "bundle", "--snapshot", "data/pinned/20261010T1358Z-celestrak",
        "--shell", "53.2deg-463km", "--cities", MILESTONE_CITIES, "--start", "2026-10-10T14:00:00Z",
        "--duration-s", "60", "--flow", "Chennai->London", "--flow", "New York->Sydney",
        "--flow", "Sao Paulo->Tokyo", "--flow", "Mumbai->Frankfurt",
        "--flow", "Singapore->Johannesburg", "--reverse", "--refresh-ms", "1000"],
    "c5-463-10s-small": [
        "export", "bundle", "--snapshot", "data/pinned/20261010T1358Z-celestrak",
        "--shell", "53.2deg-463km", "--cities", "Chennai,London,Singapore",
        "--start", "2026-10-10T14:00:00Z", "--duration-s", "10", "--flow", "Chennai->London",
        "--flow", "Singapore->London", "--reverse"],
}
DEFAULT_BUNDLE_ROOT = Path(os.environ.get("CR_BUNDLE_ROOT", "/tmp/cr-bundles"))
# The one chronoroute-leo self-check that a deliberately mild fault may fail.
CHECK_FAULT_MADE_LATE = "the fault made probes late"
# The bundle's data files (their sha256 go into the results manifest, so a
# rebuilt bundle can be compared file by file).
BUNDLE_DATA_FILES = ("nodes.csv", "isl.csv", "isl_delay.csv", "gsl.csv", "positions.csv", "schedule.csv",
                     "scenario.json")


def _bundle_command(bundle):
    """The `cr export bundle` command recorded in an existing bundle's manifest, if any."""
    try:
        return json.loads((Path(bundle) / "manifest.json").read_text(encoding="utf-8")).get("command")
    except (OSError, ValueError):
        return None


def build_bundle_from_recipe(name, bundle_root, log):
    """Run `cr export bundle` for a named recipe (from the repository root); return the bundle dir.

    It runs in a child process on purpose: building the bundle takes ~0.8 GB,
    and a child forked from a big parent would report the parent's memory as
    its own peak (ru_maxrss), which would spoil the ns-3 memory figures.
    """
    out = Path(bundle_root) / name
    argv = RECIPES[name] + ["--out", str(out)]
    log(f"bundle: cr {' '.join(argv)}")
    code = ("import sys; from chronoroute.cli import main; sys.exit(main(sys.argv[1:]))")
    env = dict(os.environ, PYTHONPATH=str(REPO / "sim"))
    proc = subprocess.run([sys.executable, "-B", "-c", code, *argv], cwd=REPO, env=env,
                          capture_output=True, text=True, check=False)
    for line in (proc.stdout + proc.stderr).splitlines():
        log(f"[bundle] {line}")
    if proc.returncode != 0:
        raise SystemExit(f"cr export bundle failed for recipe {name} (exit {proc.returncode})")
    return out, ["cr"] + argv


class Log:
    """Print to the terminal and keep a copy for run.log."""

    def __init__(self):
        self.lines = []

    def __call__(self, *parts):
        text = " ".join(str(p) for p in parts)
        print(text, flush=True)
        self.lines.append(text)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def keep_rows_meeting_the_slowed_link(src, dst):
    """Copy the header and the rows whose fault_link column is not empty; remove src."""
    with open(src, encoding="utf-8", newline="") as fin, open(dst, "w", encoding="utf-8", newline="") as fout:
        header = fin.readline()
        col = header.rstrip("\n").split(",").index("fault_link")
        fout.write(header)
        for line in fin:
            if line.rstrip("\n").split(",")[col] != "":
                fout.write(line)
    os.remove(src)


def gzip_deterministic(src, dst):
    """gzip with no file name and mtime 0 inside, so equal inputs give equal bytes."""
    with open(src, "rb") as fin, open(dst, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz:
            shutil.copyfileobj(fin, gz, 1 << 20)
    os.remove(src)


def build(log):
    """./ns3 build -j8 chronoroute-leo (a full build if the target is still unknown)."""
    cmd = ["./ns3", "build", f"-j{NS3_JOBS}", PROGRAM]
    proc = subprocess.run(cmd, cwd=NS3_DIR, capture_output=True, text=True, check=False)
    if proc.returncode != 0 and "does not exist" in proc.stdout + proc.stderr:
        # a freshly added example is only known after CMake runs again
        cmd = ["./ns3", "build", f"-j{NS3_JOBS}"]
        proc = subprocess.run(cmd, cwd=NS3_DIR, capture_output=True, text=True, check=False)
    log(f"build: {' '.join(cmd)} -> exit {proc.returncode}")
    if proc.returncode != 0:
        log(proc.stdout[-4000:], proc.stderr[-4000:])
        raise SystemExit("build failed")


def find_binary():
    found = sorted((NS3_DIR / "build" / "contrib" / "chronoroute" / "examples").glob(f"ns3.*-{PROGRAM}-*"))
    if not found:
        raise SystemExit(f"{PROGRAM} binary not found under {NS3_DIR}/build; build first")
    return found[-1]


def run_ns3(binary, args, out_dir, log, label, allowed_failed_checks=()):
    """Run the program once; return (exit code, wall s, peak RSS kB).

    The program exits 1 when a self-check fails. allowed_failed_checks names
    self-checks that may fail in THIS run (a deliberately mild fault cannot
    make probes late); exit 1 is then accepted only if every failed check is
    in that list, as run_info.json records them.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(binary)] + [f"--{k}={v}" for k, v in args.items()] + [f"--outDir={out_dir}"]
    log(f"[{label}] {' '.join(cmd)}")
    t0 = time.monotonic()
    with open(out_dir / "ns3.log", "w", encoding="utf-8") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=out_dir)
        # wait4 gives THIS child's peak resident set (ru_maxrss, kB on Linux)
        _pid, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
    wall = time.monotonic() - t0
    log(f"[{label}] exit {proc.returncode}, wall {wall:.1f} s, peak RSS {usage.ru_maxrss / 1024:.0f} MiB")
    text = (out_dir / "ns3.log").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(("  [", "  flow", "Outcomes", "Topology", "pcap", "Wall", PROGRAM, "  fault",
                            "  built", "  flows")):
            log(f"[{label}]   {line.strip()}")
    if proc.returncode == 1 and allowed_failed_checks and (out_dir / "run_info.json").exists():
        checks = json.loads((out_dir / "run_info.json").read_text(encoding="utf-8"))["checks"]
        failed = sorted(name for name, ok in checks.items() if not ok)
        if failed and set(failed) <= set(allowed_failed_checks):
            log(f"[{label}] expected self-check failure only: {failed}")
            return proc.returncode, wall, usage.ru_maxrss
    if proc.returncode != 0:
        log(text[-3000:])
        raise SystemExit(f"{label}: chronoroute-leo failed (exit {proc.returncode})")
    return proc.returncode, wall, usage.ru_maxrss


def table(rows, cols):
    """A plain-text table for run.log and the docs."""
    widths = [max(len(c), *(len(_fmt(r.get(c))) for r in rows)) for c in cols]
    out = ["  ".join(c.rjust(w) for c, w in zip(cols, widths))]
    for r in rows:
        out.append("  ".join(_fmt(r.get(c)).rjust(w) for c, w in zip(cols, widths)))
    return "\n".join(out)


def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def write_csv(path, rows):
    cols = list(rows[0].keys())
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(",".join("" if r[c] is None else str(r[c]) for c in cols) + "\n")


def anim_stats(xml_path):
    """Counts in the NetAnim XML (a quick sanity check).

    NetAnim paints every node red at t = 0 by default; the program repaints
    satellites blue and stations green at t = 0, so a red colour update at
    t > 0 is a node where a deadline miss was detected.
    """
    text = Path(xml_path).read_text(encoding="utf-8", errors="replace")
    red = re.findall(r'<nu p="c" t="([^"]+)" id="(\d+)" r="255" g="0" b="0"', text)
    return {"bytes": len(text.encode("utf-8")),
            "node_elements": text.count("<node "),
            "link_elements": text.count("<link "),
            "packet_elements": text.count("<p "),
            "packets_with_tcrh_metadata": text.count("ns3::TcrhHeader (T-CRH("),
            "packets_with_dev_in_metadata": len(re.findall(r"T-CRH\(nh=\d+ sl=\d+ flags=0x\d?[13579bdf] ", text)),
            "position_updates": text.count('<nu p="p"'),
            "link_description_updates": text.count("<linkupdate "),
            "nodes_turned_red_for_deviation": sorted({int(i) for t, i in red if float(t) > 0})}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--bundle", help="scenario bundle directory (cr export bundle)")
    which.add_argument("--recipe", choices=sorted(RECIPES),
                       help="rebuild a milestone bundle from its recipe first (reproducible from git)")
    ap.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT),
                    help="where --recipe writes the bundle (default $CR_BUNDLE_ROOT or /tmp/cr-bundles)")
    ap.add_argument("--run-id", help="output folder name (default: <bundle name>-seed<seed>)")
    ap.add_argument("--out-root", default=str(REPO / "results" / "course-milestone"))
    ap.add_argument("--seed", type=int, default=1, help="ns-3 RngRun (probe start offsets)")
    ap.add_argument("--fault-flow", type=int, default=0)
    ap.add_argument("--fault-start-ms", type=int, help="default 20000 (60 s bundles) or 40%% of the window")
    ap.add_argument("--fault-duration-ms", type=int, help="default 20000 (60 s bundles) or 30%% of the window")
    ap.add_argument("--fault-rate", default="200kbps",
                    help="rate of the slowed link; below one probe flow's 240 kb/s so a queue builds")
    ap.add_argument("--sensitivity-rates", default="1Mbps,500kbps,250kbps",
                    help="comma-separated milder fault rates, one extra fault run each ('' for none)")
    ap.add_argument("--anim-max-sats", type=int, default=200)
    ap.add_argument("--anim-before-ms", type=int, default=2000, help="slice window starts this long before the fault")
    ap.add_argument("--anim-after-ms", type=int, default=4000, help="slice window ends this long after the fault start")
    ap.add_argument("--no-build", action="store_true")
    args = ap.parse_args(argv)

    log = Log()
    timer = RunTimer().start()
    recipe_command = None
    if args.recipe:
        bundle, recipe_command = build_bundle_from_recipe(args.recipe, args.bundle_root, log)
    else:
        bundle = Path(args.bundle)
    bundle = bundle.resolve()
    scenario = json.loads((bundle / "scenario.json").read_text(encoding="utf-8"))
    window_ms = scenario["time"]["window_ms"]
    if args.fault_start_ms is None:
        args.fault_start_ms = 20000 if window_ms >= 60000 else (window_ms * 4 // 10) // 1000 * 1000
    if args.fault_duration_ms is None:
        args.fault_duration_ms = 20000 if window_ms >= 60000 else (window_ms * 3 // 10) // 1000 * 1000
    run_id = args.run_id or f"{bundle.name}-seed{args.seed}"
    out_root = Path(args.out_root)
    final = out_root / run_id
    stage = out_root / f"{run_id}.staging"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    log(f"run_leo: bundle {bundle} ({scenario['counts']['satellites']} satellites, "
        f"{scenario['counts']['ground_stations']} ground stations, {window_ms} ms), run id {run_id}")
    if not args.no_build:
        build(log)
    binary = find_binary()
    log(f"binary: {binary} (sha256 {sha256_file(binary)[:16]}...)")

    common = {"bundle": bundle, "seed": args.seed, "faultFlow": args.fault_flow,
              "faultStartMs": args.fault_start_ms, "faultDurationMs": args.fault_duration_ms,
              "faultRate": args.fault_rate, "policy": "continue", "probeRate": 100, "payload": 200,
              "dataRate": "1Gbps", "queueSize": "100p"}
    anim_from = max(0, args.fault_start_ms - args.anim_before_ms)
    anim_to = min(window_ms, args.fault_start_ms + args.anim_after_ms)
    runs = {
        "nofault": dict(common, fault=0, pcap=1),
        "fault": dict(common, fault=1, pcap=1),
        "anim": dict(common, fault=1, pcap=0, anim=1, animMaxSats=args.anim_max_sats,
                     animFromMs=anim_from, animToMs=anim_to),
    }
    sens_rates = [r.strip() for r in args.sensitivity_rates.split(",") if r.strip()]
    sens_runs = {f"sensitivity/{rate}": dict(common, fault=1, pcap=0, faultRate=rate) for rate in sens_rates}
    resources = {}
    for label, a in list(runs.items()) + list(sens_runs.items()):
        allowed = (CHECK_FAULT_MADE_LATE,) if label in sens_runs else ()
        _code, wall, rss = run_ns3(binary, a, stage / label, log, label, allowed_failed_checks=allowed)
        resources[label] = {"wall_s": round(wall, 2), "peak_rss_kb": rss}

    info = {label: json.loads((stage / label / "run_info.json").read_text(encoding="utf-8"))
            for label in list(runs) + list(sens_runs)}
    for label in info:
        # the program's own high-water mark (VmHWM, measured after exec), next to wait4's figure
        resources[label]["program_peak_rss_kb"] = info[label]["peak_rss_kb"]
    effective = sorted({info[label]["effective_policy"] for label in info})
    log(f"deviation policy: configured 'continue', effective at every node: {effective}")
    fault_start_ns = args.fault_start_ms * cc.NS_PER_MS
    fault_stop_ns = (args.fault_start_ms + args.fault_duration_ms) * cc.NS_PER_MS

    # ---------------------------------------------------------------- analysis
    log("analysis: loading the bundle and the packets")
    rb = cc.load_replay_bundle(bundle)
    pk = {label: cc.read_packets(stage / label / "packets.csv") for label in runs}
    flows = {f["flow_id"]: (f["src"], f["dst"]) for f in info["nofault"]["flows"]}

    cross_nf = cc.crosscheck(rb, pk["nofault"])

    # A probe that reaches the slowed link just after the fault ends can still
    # wait for the last slow transmission (up to ~14 ms at 200 kb/s) or a
    # backlog that is draining, so the fault-run cross-check leaves out probes
    # that met the link from the fault start until 1 s after its end.
    drain_tail_ns = 1000 * cc.NS_PER_MS

    def met_slowed_link(p):
        return (p["fault_link"] != "" and p["fault_link_t_ns"] is not None
                and fault_start_ns <= p["fault_link_t_ns"] < fault_stop_ns + drain_tail_ns)

    cross_f = cc.crosscheck(rb, pk["fault"], exclude=met_slowed_link)
    det = cc.detection(pk["fault"], pk["nofault"], fault_start_ns, fault_stop_ns)
    det["fault_link"] = info["fault"]["fault"]
    margins = cc.margin_summary(pk["nofault"], rb.unit_ns)

    # milder faults: the same detection figures, against the same no-fault run
    sensitivity = {"note": "the same fault (link, start, duration) at milder slow-downs; detection "
                           "needs a queue that outgrows the deadline slack (MODELLED fault)",
                   "runs": []}
    for label in sens_runs:
        sp = cc.read_packets(stage / label / "packets.csv")
        d = cc.detection(sp, pk["nofault"], fault_start_ns, fault_stop_ns)
        sensitivity["runs"].append({
            "fault_rate": info[label]["fault"]["rate"], "isl_id": info[label]["fault"]["isl_id"],
            "self_checks_failed": sorted(k for k, ok in info[label]["checks"].items() if not ok),
            **{k: v for k, v in d.items() if k != "per_flow"}})
        log(f"[{label}] detection: crossed {d['probes_crossing_slowed_link']}, flagged {d['flagged_late']} "
            f"(rate {d['detection_rate']}), lost in its queue {d['probes_lost_in_its_queue']}")
    sensitivity["runs"].insert(0, {"fault_rate": info["fault"]["fault"]["rate"], "isl_id": det["fault_link"]["isl_id"],
                                   "self_checks_failed": [], "main_fault_run": True,
                                   **{k: v for k, v in det.items() if k not in ("per_flow", "fault_link")}})
    losses = {label: cc.drop_causes(rb, pk[label]) for label in ("nofault", "fault")}
    summary = (cc.flow_summary(pk["nofault"], flows, fault_start_ns, fault_stop_ns, "nofault")
               + cc.flow_summary(pk["fault"], flows, fault_start_ns, fault_stop_ns, "fault"))
    write_csv(stage / "flow_summary.csv", summary)

    # the slice run against the full fault run, probe by probe (same seed, same
    # send instants): identical except where the full run's other flows queued
    # behind the slice flow's probes on the slowed link
    full_of = {(p["flow_id"], p["seq"]): p for p in pk["fault"]}
    same_path = same_lat = 0
    for p in pk["anim"]:
        q = full_of[(p["flow_id"], p["seq"])]
        same_path += p["taken_path"] == q["taken_path"]
        same_lat += p["latency_ns"] == q["latency_ns"]
    slice_vs_full = {"probes": len(pk["anim"]), "path_identical": same_path,
                     "latency_identical": same_lat}

    with open(stage / "crosscheck_nofault.json", "w", encoding="utf-8") as fh:
        json.dump(cross_nf, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(stage / "crosscheck_fault.json", "w", encoding="utf-8") as fh:
        json.dump(dict(cross_f, note="probes that met the slowed link from the fault start until 1 s "
                                     "after its end are left out"),
                  fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(stage / "detection.json", "w", encoding="utf-8") as fh:
        json.dump(det, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(stage / "sensitivity.json", "w", encoding="utf-8") as fh:
        json.dump(sensitivity, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(stage / "margins.json", "w", encoding="utf-8") as fh:
        json.dump(margins, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with open(stage / "loss_causes.json", "w", encoding="utf-8") as fh:
        json.dump(dict(losses, note="link-down losses by the kind of dead link: isl, gsl-up (the "
                                    "source station's first hop) or gsl-down (the last hop); "
                                    "drop_queue losses are all on the slowed link (detection.json)"),
                  fh, indent=2, sort_keys=True)
        fh.write("\n")

    # ---------------------------------------------------------------- pcap checks
    pcap_res = {}
    for label in ("nofault", "fault"):
        pcap = stage / label / "capture.pcap"
        code, summ, text = cc.run_check_pcap(REPO, pcap)
        sem = cc.pcap_semantics(pcap, rb.t0_unix_ns, fault_start_ns, fault_stop_ns)
        pcap_res[label] = {"check_pcap_exit": code, "check_pcap": summ, "semantics": sem,
                           "capture_nodes": info[label]["capture_nodes"]}
        log(f"[{label}] check_pcap.sh: exit {code}; {text.strip().splitlines()[-1] if text.strip() else ''}")
        if code != 0:
            log(text[-3000:])
            raise SystemExit(f"{label}: check_pcap.sh found invalid frames")
    with open(stage / "pcap_check.json", "w", encoding="utf-8") as fh:
        json.dump(pcap_res, fh, indent=2, sort_keys=True)
        fh.write("\n")
    anim = anim_stats(stage / "anim" / "anim.xml")

    # ---------------------------------------------------------------- printout
    log("")
    log("Per-flow summary [traffic, link rate, queues, fault MODELLED; positions REAL; routes DERIVED]:")
    log(table(summary, ["run", "flow_id", "src", "dst", "sent", "delivered", "pdr", "latency_p50_ms",
                        "latency_p99_ms", "drop_link_down", "drop_iface_down", "drop_queue",
                        "flagged_frac_before", "flagged_frac_during", "flagged_frac_after"]))
    log("")
    log(f"Detection: {json.dumps({k: v for k, v in det.items() if k != 'per_flow'}, sort_keys=True)}")
    log(f"Detection per flow: {json.dumps(det['per_flow'], sort_keys=True)}")
    log("Detection by fault rate (sensitivity.json): " + "; ".join(
        f"{r['fault_rate']}: {r['flagged_late']}/{r['probes_crossing_slowed_link']} flagged, "
        f"{r['probes_lost_in_its_queue']} lost in its queue" for r in sensitivity["runs"]))
    log(f"Deadline margins of on-time probes, no-fault run (margins.json): {json.dumps(margins, sort_keys=True)}")
    log(f"Link-down losses by dead link: {json.dumps(losses, sort_keys=True)}")
    log("")
    for name, res in (("no-fault run", cross_nf), ("fault run, slowed-link probes left out", cross_f)):
        log(f"E16-lite cross-check, {name}: {res['path_identical']}/{res['probes_compared']} paths identical, "
            f"{res['outcome_identical']} outcomes identical, "
            f"{res['per_hop_time_clock_deadline_identical']} with identical per-hop time/clock/deadline; "
            f"latency - light time (ns) {res['latency_minus_light_time_ns']}; residual after serialization (ns) "
            f"{res['residual_after_serialization_ns']} (zero {res['residual_zero']}, positive "
            f"{res['residual_positive']}, negative {res['residual_negative']}); held vs interpolated light "
            f"time per hop (ns) {res['held_vs_interpolated_light_time_ns_per_hop']}")
    log(f"Slice run vs full fault run (same probes): {slice_vs_full}")
    log(f"pcap: {json.dumps(pcap_res, sort_keys=True)}")
    log(f"NetAnim slice: {anim}")
    log(f"Resources: {resources}")

    # ---------------------------------------------------------------- compress, manifest
    for label in runs:
        gzip_deterministic(stage / label / "packets.csv", stage / label / "packets.csv.gz")
        if (stage / label / "capture.pcap").exists():
            gzip_deterministic(stage / label / "capture.pcap", stage / label / "capture.pcap.gz")
    for label in sens_runs:
        # A sensitivity run differs from the no-fault run only for probes that met
        # the slowed link, and its figures in sensitivity.json come from those
        # rows: keep them (slowed_link_probes.csv.gz, same columns) and not the
        # other ~56,000 identical rows (~7.7 MB per run). The run is deterministic,
        # so `run_leo.py` reproduces the full file if it is ever needed.
        keep_rows_meeting_the_slowed_link(stage / label / "packets.csv", stage / label / "slowed_link_probes.csv")
        gzip_deterministic(stage / label / "slowed_link_probes.csv", stage / label / "slowed_link_probes.csv.gz")
    (stage / "run.log").write_text("\n".join(log.lines) + "\n", encoding="utf-8")

    module = REPO / "ns3" / "contrib" / "chronoroute"
    programs = {str(p.relative_to(REPO)): sha256_file(p)
                for p in sorted(module.glob("*/*")) if p.suffix in (".h", ".cc")}
    programs["ns3/run_leo.py"] = sha256_file(Path(__file__))
    programs["sim/chronoroute/export/ns3_crosscheck.py"] = sha256_file(Path(cc.__file__))
    ns3_head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=NS3_DIR, capture_output=True,
                              text=True, check=False).stdout.strip()
    snap = scenario["snapshot"]
    outputs = sorted(p for p in stage.rglob("*") if p.is_file() and p.name != "manifest.json")
    timer.stop()
    config = {
        "experiment": "course-milestone: LEO topology + time-varying schedule in ns-3",
        "bundle": str(bundle), "bundle_manifest_sha256": sha256_file(bundle / "manifest.json"),
        "bundle_recipe": args.recipe, "bundle_command": recipe_command or _bundle_command(bundle),
        "bundle_data_sha256": {name: sha256_file(bundle / name) for name in sorted(BUNDLE_DATA_FILES)},
        "shell": scenario["shell"]["shell_id"], "t0_utc": scenario["time"]["t0_utc"],
        "window_ms": window_ms, "step_ms": scenario["time"]["step_ms"],
        "schedule_refresh_ms": scenario["time"]["schedule_refresh_ms"],
        # (bundles written before these settings existed did not record them)
        "plan_links": scenario["models"].get("planning", {}).get("plan_links", "instant (not recorded)"),
        "gsl_policy": scenario["models"]["gsl"].get("policy"),
        "isl_max_range_km": scenario["models"]["isl"].get("max_range_km"),
        "slack": scenario["tcrh"]["slack"], "unit_code": scenario["tcrh"]["unit_code"],
        "deviation_policy": "continue", "effective_policy": effective,
        "runs": {k: {kk: str(vv) for kk, vv in v.items()} for k, v in list(runs.items()) + list(sens_runs.items())},
        "delay_update": "Delay held per 100 ms step (step function), not interpolated",
        "link_down": "IPv6 interfaces of both ends set down (SetDown semantics)",
        "processing_delay_ns3": 0,
        "probe_pid": "flow_id * 1000000 + seq, in the payload after 'CRT1'",
        "pcap_timestamps": "UTC Unix time = t0_unix_ns + simulation time (GPS - 18 s)",
    }
    extra = {
        "binary": {"path": str(binary), "sha256": sha256_file(binary)},
        "ns3_dir": str(NS3_DIR), "ns3_git_head": ns3_head, "ns3_base": "ns-3.44, build profile default",
        "programs": programs,
        "run_info": info,
        "resources": resources,
        "detection": {k: v for k, v in det.items() if k != "per_flow"},
        "sensitivity": sensitivity,
        "margins": margins,
        "loss_causes": losses,
        "crosscheck_nofault": {k: v for k, v in cross_nf.items() if k != "mismatch_examples"},
        "slice_vs_full_fault_run": slice_vs_full,
        "anim_xml": anim,
        "pcap_check": pcap_res,
        "snapshot_attribution": snap.get("attribution"),
    }
    write_manifest(stage, tool="ns3-chronoroute-leo", tool_version=__version__, command=sys.argv,
                   config=config, seeds=[args.seed],
                   snapshot={"id": snap["id"], "sha256": snap["sha256"], "sha256_of": snap["sha256_of"]},
                   outputs=outputs, labels=cc.LABELS, extra=extra, timer=timer)
    if final.exists():
        shutil.rmtree(final)
    stage.rename(final)
    print(f"run_leo: wrote {final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

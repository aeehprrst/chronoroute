"""Preregistered E1 pilot, with a hard separation from confirmation.

The E1 portion of the fixed pilot matrix is run first to measure its cost.
The other pilot families and deterministic E16 remain required before any
confirmatory launch. A partial pilot can block confirmation, never allow it.
"""

import argparse
import copy
import csv
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor

from chronoroute import __version__, labels, provenance
from chronoroute.baselines.params import normalise_scheme
from chronoroute.fwd.config import normalise
from chronoroute.fwd.presets import SCIENCE_PAIRS_PLAN, CITY_NAME_MAP
from chronoroute.fwd.scenario import build_scenario
from chronoroute.trace.writer import write_json

REPO = Path(__file__).resolve().parents[2]
PREREG_SHA = "b87f08a7cc9431d139bf66372f03133035494b8c"
PREREG_HASH = "1d1541f60be8411f565c5eda4e64322354c276a7321181e2ee9ee92f065ea5d3"
PAIRS = tuple(tuple(CITY_NAME_MAP.get(c, c) for c in p) for p in SCIENCE_PAIRS_PLAN
              if p[0] not in ("Reykjavik", "Anchorage"))
SCHEMES = ("chronoroute", "ls_h", "ls_d", "e2e", "lq", "crh16", "o_q")
RULES = ([{"kind": "mult", "slack": s, "unit_code": 1} for s in ("1.1", "1.25", "1.5", "2", "3")]
         + [{"kind": "add", "per_hop_ns": a, "const_ns": 0, "unit_code": 1} for a in (250000, 1000000)]
         + [{"kind": "quantile", "alpha": a, "sigma_ns": 400000, "unit_code": 1} for a in ("0.01", "0.001")])
CONDITIONS = {}
for _family, _kind, _key, _values, _nominal, _null in (
        ("rate", "rate_cut", "factor", (0.2, 0.3, 0.6), 0.3, 1),
        ("delay", "slow_processing", "delta_ns", (250000, 1000000, 4000000), 1000000, 0),
        ("arq", "arq", "loss", (0.01, 0.1, 0.3), 0.1, 0)):
    for _value, _position in [(v, "middle") for v in _values] + [(_nominal, p) for p in ("first", "last")] + [(_null, "middle")]:
        _name = f"{_family}-{_value}-{_position}"
        CONDITIONS[_name] = {"family": _family, "position": _position, "null": _value == _null,
                             "fault": {"kind": _kind, _key: _value, "start_s": 4, "stop_s": 8}}
        if _family == "arq":
            CONDITIONS[_name]["fault"].update(max_retries=3, retry_extra_ns=500000)
NOMINAL = ("rate-0.3-middle", "delay-1000000-middle", "arq-0.1-middle")
ENV = {**os.environ, **{k: "1" for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
       "PYTHONDONTWRITEBYTECODE": "1", "MPLBACKEND": "Agg"}


def validate_protocol():
    """Reject edited protocols or dirty implementation trees before work starts."""
    if provenance.file_sha256(REPO / "experiments/PREREG.md") != PREREG_HASH:
        raise ValueError("preregistration hash differs from the frozen protocol")
    committed = subprocess.check_output(["git", "show", f"{PREREG_SHA}:experiments/PREREG.md"], cwd=REPO)
    if provenance.sha256_hex(committed) != PREREG_HASH:
        raise ValueError("preregistration commit does not contain the frozen protocol")


def pair_id(seed, phase):
    """The fixed, balanced pair mapping; refuse accidental pilot contamination."""
    if phase == "pilot" and 0 <= seed < 100:
        return seed % 18
    if phase == "confirmatory" and 1000 <= seed <= 1035:
        return (seed - 1000) % 18
    raise ValueError("seed is outside the registered phase")


def jobs(phase):
    """All E1 jobs, including the exact shared twins and three null families."""
    rows = []
    for const in ("C5", "C2"):
        seeds = range(6) if phase == "pilot" else range(1000, 1036)
        for seed in seeds:
            schemes = ("chronoroute", "ls_h", "ls_d", "o_q") if phase == "pilot" and seed == 0 else (("chronoroute",) if phase == "pilot" else SCHEMES)
            for scheme in schemes:
                # Cost pilots have no extra twin jobs in the fixed 96-job matrix.
                conditions = (("none",) + NOMINAL if scheme == "chronoroute" else NOMINAL) if phase == "pilot" else ("none", *CONDITIONS)
                for condition in conditions:
                    rows.append({"id": f"{const}-{scheme}-s{seed:04d}-{condition}", "const": const,
                                 "scheme": scheme, "seed": seed, "phase": phase,
                                 "pair_id": pair_id(seed, phase), "condition": condition})
    return rows


def document(job, targets=None):
    """A strictly normalised engine/scheme config with outer campaign metadata."""
    seed, phase = job["seed"], job["phase"]
    pi = pair_id(seed, phase)
    src, dst = PAIRS[pi]
    engine = {"seed": seed,
              "scenario": {"kind": "real" if job["const"] == "C5" else "walker", "preset": "C2",
                           "duration_s": 12, "drain_s": 2, "chunk_steps": 200},
              "traffic": {"flows": [{"src": src, "dst": dst}, {"src": dst, "dst": src}]},
              "schedule": {"plan_links": "instant", "planner_processing_ns": 900000},
              "forwarding": {"policy": "continue", "jitter": {"model": "j1", "mean_ns": 400000},
                             "background": {"model": "fluid", "rho": 0.3, "links": "isl"}, "verify_every": 100},
              "output": {"invariants": "all"}}
    if job["condition"] != "none":
        cond = CONDITIONS[job["condition"]]
        fault = copy.deepcopy(cond["fault"])
        if targets is None:
            fault["on_path"] = {"flow": 0, "at_s": 4, "position": cond["position"], "kind": "isl"}
        else:
            fault["link"] = list(targets[cond["position"]])
        engine["faults"] = [fault]
    scheme = {"name": job["scheme"], "outputs": {"stretch_oracle": False}}
    if job["scheme"] == "ls_d":
        scheme["ls_d"] = {"window_s": 0.2, "threshold": 0.2, "variant": "avg", "probe_ms": 100,
                          "inter_update_s": 1, "min_interval_s": 1}
    if job["scheme"] == "e2e":
        scheme["e2e"] = {"feedback": False, "report_delay_ms": 50}
    return {"campaign": {"prereg_path": "experiments/PREREG.md", "prereg_git_sha": PREREG_SHA,
                         "prereg_sha256": PREREG_HASH, "phase": phase, "experiment": "E01",
                         "cell_id": f"{job['const']}-{job['scheme']}-{job['condition']}", "pair_id": pi, "seed": seed},
            "engine": normalise(engine), "scheme": normalise_scheme(scheme)}


def preflight(out, *, constellations=("C5", "C2"), pairs=range(18)):
    """Verify every planned row and freeze physical targets before simulation."""
    out.mkdir(parents=True, exist_ok=True)
    targets, checks = {}, 0
    for const in constellations:
        for pi in pairs:
            j = {"const": const, "scheme": "chronoroute", "seed": pi, "phase": "pilot", "condition": "none"}
            sc = build_scenario(document(j)["engine"])
            for flow in sc.flows:
                for start in range(0, 12000, 1000):
                    if sc.plan(flow, start, start + 1000) is None:
                        raise ValueError(f"no path: {const}, pair {pi}, flow {flow}, row {start}")
                    checks += 1
            targets[f"{const}:{pi}"] = {p: list(sc.resolve_on_path({"flow": 0, "at_s": 4, "position": p, "kind": "isl"},
                                                                  4000000000, False)) for p in ("first", "middle", "last")}
    write_json(out / "preflight.json", {"targets": targets, "checks": checks, "violations": 0})
    return targets


def measured_command(command, stem, *, timeout=60):
    """Measure one actual child with wait4: per-child peak RSS, no nested pool."""
    stem.parent.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    timed_out = False
    with open(stem.with_suffix(".log"), "wb") as log:
        child = subprocess.Popen(command, cwd=REPO, env=ENV, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        while True:
            pid, status, usage = os.wait4(child.pid, os.WNOHANG)
            if pid:
                child.returncode = os.waitstatus_to_exitcode(status)
                break
            if time.monotonic() - begin >= timeout and not timed_out:
                timed_out = True
                os.killpg(child.pid, signal.SIGKILL)
            time.sleep(0.02)
    return {"command": command, "wall_s": time.monotonic() - begin, "cpu_s": usage.ru_utime + usage.ru_stime,
            "peak_rss_kb": usage.ru_maxrss,
            "returncode": child.returncode, "status": "timeout" if timed_out else ("ok" if child.returncode == 0 else "failed")}


def run_job(job, out, targets):
    """One logged simulation, including a manifest even if the engine fails."""
    folder = out / "runs" / job["id"]
    folder.mkdir(parents=True, exist_ok=False)
    doc = document(job, targets[f"{job['const']}:{job['pair_id']}"])
    write_json(folder / "config.json", doc)
    write_json(folder / "engine.json", {**doc["engine"], "scheme": doc["scheme"]})
    prefix = [str(REPO / "venv/bin/python"), "-B", "-m", "chronoroute.cli"]
    action = ["run", "--scheme"] if job["scheme"] == "chronoroute" else ["eval", "scheme"]
    with provenance.RunTimer() as timer:
        row = {**job, **measured_command(prefix + action + ["--config", str(folder / "engine.json"), "--out", str(folder / "raw")],
                                       folder / "simulation")}
    if (folder / "raw/manifest.json").exists():
        attach_metadata(folder / "raw", doc["campaign"], row)
    write_json(folder / "observation.json", row)
    provenance.write_manifest(folder, tool="E01 pilot job", tool_version=__version__, command=row["command"],
                              config=doc, seeds=[job["seed"]], snapshot=REPO / doc["engine"]["scenario"]["snapshot"],
                              outputs=sorted(p for p in folder.rglob("*") if p.is_file()),
                              labels=labels.pick(*(["orbital_elements"] if job["const"] == "C5" else []),
                                                 "routes_and_budgets", "isl_topology_grid4", "traffic_probes", "fault_slow_link"),
                              extra={"campaign": doc["campaign"], "observation": row,
                                     "runtime_observation": "REAL host measurement; simulated network is MODELLED",
                                     "synthetic_positions": "MODELLED" if job["const"] == "C2" else None}, timer=timer)
    return row


def attach_metadata(folder, campaign, observation, *, inputs=()):
    """Add launcher facts without changing an engine's config or output hashes."""
    from chronoroute.fwd.rng import COMPONENTS
    path = folder / "manifest.json"
    doc = json.loads(path.read_text())
    doc["extra"].update(campaign=campaign, measured_command=observation, rng_components=COMPONENTS,
                        inputs=[{"path": str(p), "sha256": provenance.file_sha256(p)} for p in inputs])
    write_json(path, doc)
    provenance.validate_manifest(path)


def score_pilot(out, planned):
    """Offline CLI scoring; incomplete pilot outputs never freeze a rule."""
    observations, rows, twins_seen = [], [], set()
    for job in planned:
        if job["scheme"] != "chronoroute" or job["condition"] == "none":
            continue
        folder = out / "runs" / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        twin_id = f"{job['const']}-chronoroute-s{job['seed']:04d}-none"
        twin = out / "runs" / twin_id / "raw"
        cmd = [str(REPO / "venv/bin/python"), "-B", "-m", "chronoroute.cli", "eval", "score", str(folder / "raw"),
               "--twin", str(twin), "--rules", str(out / "rules.json"), "--check-plans", "--flow", "0", "--k", "2",
               "--window-ms", "1000", "--out", str(folder / "score")]
        observation = {"id": job["id"], **measured_command(cmd, folder / "score_command")}
        observations.append(observation)
        if observation["status"] != "ok":
            continue
        campaign = document(job)["campaign"]
        attach_metadata(folder / "score", campaign, observation,
                        inputs=[folder / "raw/manifest.json", twin / "manifest.json", out / "rules.json"])
        summary = json.loads((folder / "score/summary.json").read_text())
        for ri, result in enumerate(summary["detection"][1:]):
            det = result["faults"][0]
            rows.append({"const": job["const"], "seed": job["seed"], "rule_index": ri,
                         "family": CONDITIONS[job["condition"]]["family"], "clean": result["fpr"]["clean"],
                         "fp": result["fpr"]["false_positives"], "tp": det["packet"]["true_detections"],
                         "crossed": det["packet"]["exposed"], "detected": int(det["event"]["detected"])})
            key = (job["const"], job["seed"], ri)
            if key not in twins_seen:
                twins_seen.add(key)
                rows.append({"const": job["const"], "seed": job["seed"], "rule_index": ri, "family": "none",
                             "clean": result["fpr_twin"]["clean"], "fp": result["fpr_twin"]["false_positives"],
                             "tp": 0, "crossed": 0, "detected": 0})
    write_json(out / "score_inventory.json", observations)
    write_csv(out / "pilot_counts.csv", rows)
    if len(observations) == 36 and all(o["status"] == "ok" for o in observations):
        frozen = {c: select_rule(rows, c) for c in ("C5", "C2")}
        frozen["inputs"] = [{"path": str(p.relative_to(out)), "sha256": provenance.file_sha256(p)}
                            for p in sorted(out.glob("runs/*/score/manifest.json"))]
        write_json(out / "operating_points.json", frozen)
    return rows


def plot_pilot(out, observations, counts):
    """Standalone pilot figures generated solely from observed rows."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figures = out / "figures"
    figures.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 4))
    groups = sorted({(r["const"], r["scheme"]) for r in observations})
    for i, (const, scheme) in enumerate(groups):
        vals = [r["wall_s"] for r in observations if (r["const"], r["scheme"]) == (const, scheme)]
        ax.scatter([i] * len(vals), vals, s=18)
    ax.set_xticks(range(len(groups)), [f"{c}\n{s}" for c, s in groups], fontsize=8)
    ax.set_ylabel("Observed child wall time (s)")
    ax.set_title("E1 pilot runtime; timeouts retained; serial and batch observations")
    fig.tight_layout()
    fig.savefig(figures / "runtime.png", dpi=160)
    plt.close(fig)
    if counts:
        fig, ax = plt.subplots(figsize=(6, 4))
        for const in ("C5", "C2"):
            points = []
            for ri in range(9):
                rr = [r for r in counts if r["const"] == const and r["rule_index"] == ri]
                clean, crossed = sum(r["clean"] for r in rr), sum(r["crossed"] for r in rr)
                if clean and crossed:
                    points.append((sum(r["fp"] for r in rr) / clean, sum(r["tp"] for r in rr) / crossed))
            if points:
                ax.scatter(*zip(*points), label=const)
        ax.axvline(0.01, color="grey", linestyle="--")
        ax.set(xlabel="Pooled clean-packet FPR", ylabel="Pooled attributed packet detection",
               title="Pilot only: nominal middle-third faults; nine offline rules")
        ax.legend()
        fig.tight_layout()
        fig.savefig(figures / "pilot_packet_roc.png", dpi=160)
        plt.close(fig)


def resource_forecast(rows, *, batch_wall_s, batch_process_s, spent_s):
    """Conservative partial-pilot projection; partial evidence cannot pass."""
    if not rows or batch_wall_s <= 0 or batch_process_s <= 0:
        raise ValueError("measured nonempty pilot and batch timings required")
    efficiency = min(6.0, batch_process_s / batch_wall_s)
    successful = [r for r in rows if r["status"] == "ok"]
    costs = {}
    for const in ("C5", "C2"):
        cells = {}
        for scheme in SCHEMES:
            times = [r.get("cpu_s", r["wall_s"]) for r in successful if r["const"] == const and r["scheme"] == scheme]
            if times:
                cells[scheme] = sum(times) / len(times)
        costs[const] = max(cells.values()) if cells else 60.0
    e1 = 4788 * sum(costs.values()) / efficiency
    memory = max(r["peak_rss_kb"] for r in rows) * 1024 * 8
    reason = "remaining E4/E5/E16 cost pilots and deterministic E16 gate required"
    if any(r["status"] != "ok" for r in rows):
        reason = "failed or timed-out pilot jobs; confirmation blocked"
    elif spent_s + e1 > 21600:
        reason = "E1 projection alone exceeds campaign budget; prospective amendment required"
    return {"label": "MODELLED", "status": "blocked", "confirmation_allowed": False, "reason": reason,
            "measured_jobs": len(rows), "measured_spent_s": spent_s, "measured_batch_wall_s": batch_wall_s,
            "measured_batch_process_s": batch_process_s, "effective_workers": efficiency,
            "conservative_serial_s_by_constellation": costs, "e1_projected_s": e1,
            "eight_worker_peak_bytes": memory, "remaining_pilot_jobs": 96 - len(rows),
            "remaining_families_not_in_projection": ["E4", "E5", "E16", "analysis", "reserve"]}


def select_rule(rows, const):
    """Pooled pilot rates, equal family weights, then frozen table-order ties."""
    candidates = []
    for ri in range(9):
        rr = [r for r in rows if r["const"] == const and r["rule_index"] == ri]
        if any({r["seed"] for r in rr if r["family"] == f} != set(range(6)) for f in ("rate", "delay", "arq")):
            raise ValueError("all six seeds in each nominal family required")
        clean, fp = sum(r["clean"] for r in rr), sum(r["fp"] for r in rr)
        fpr = fp / clean if clean else None
        rates, denominators = [], {}
        for family in ("rate", "delay", "arq"):
            fr = [r for r in rr if r["family"] == family]
            n = sum(r["crossed"] for r in fr)
            denominators[family] = n
            rates.append(sum(r["tp"] for r in fr) / n if n else None)
        score = sum(rates) / 3 if all(r is not None for r in rates) else None
        candidates.append({"rule_index": ri, "rule": RULES[ri], "fpr": fpr, "score": score,
                           "crossed_by_family": denominators,
                           "ineligible_reason": ("zero crossed in a nominal family" if score is None else
                                                 ("clean FPR undefined or above limit" if fpr is None or fpr > 0.01 else None)),
                           "eligible": fpr is not None and fpr <= 0.01 and score is not None})
    eligible = [c for c in candidates if c["eligible"]]
    best = min(eligible, key=lambda c: (-c["score"], c["fpr"], c["rule_index"])) if eligible else candidates[4]
    return {**best, "failed_fpr": not eligible, "candidates": candidates}


def write_csv(path, rows):
    """Write an inventory without replacing undefined values by observations."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]) if rows else ["status"])
        w.writeheader()
        w.writerows(rows)


def archive_raw(folder):
    """Lossless archival of completed generated output after analysis."""
    import shutil
    with tarfile.open(folder.with_suffix(".tar.gz"), "w:gz") as archive:
        archive.add(folder, arcname=folder.name)
    shutil.rmtree(folder)


def main(argv=None):
    """Run the E1 pilot portion only; a separate validity gate guards confirmation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 9), default=8)
    if argv is not None and "--help" in argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    validate_protocol()
    if provenance.git_state(REPO)["dirty"]:
        raise ValueError("commit and clean the implementation before running the pilot")
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    with provenance.RunTimer() as timer:
        targets = preflight(args.out)
        write_json(args.out / "rules.json", RULES)
        planned = jobs("pilot")
        write_json(args.out / "planned_jobs.json", planned)
        # Serial observations are part of the fixed matrix, never extra seeds.
        serial = [j for j in planned if j["seed"] == 0 and j["condition"] == "none"]
        rows = [run_job(j, args.out, targets) for j in serial]
        remaining = [j for j in planned if j not in serial]
        # Keep measured memory headroom, allowing twice the serial CR peak for
        # the more expensive cost-check schemes before their peaks are known.
        ram = provenance.host_info()["ram_bytes"]
        peak = max(r["peak_rss_kb"] for r in rows) * 1024
        workers = min(args.workers, max(1, int(0.75 * ram / (2 * peak)))) if ram else 1
        batch_start = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            rows.extend(pool.map(lambda j: run_job(j, args.out, targets), remaining))
        batch_wall = time.monotonic() - batch_start
        write_csv(args.out / "inventory.csv", rows)
        counts = score_pilot(args.out, planned)
        plot_pilot(args.out, rows, counts)
        forecast = resource_forecast(rows, batch_wall_s=batch_wall,
                                     batch_process_s=sum(r["cpu_s"] for r in rows[len(serial):]), spent_s=timer.wall_seconds)
        write_json(args.out / "resource_forecast.json", forecast)
        write_csv(args.out / "summary.csv", [{"endpoint": "runtime_gate", "status": forecast["status"],
                                             "value": forecast["e1_projected_s"], "unit": "seconds", "label": "MODELLED",
                                             "reason": forecast["reason"]}])
    provenance.write_manifest(args.out, tool="E01 pilot", tool_version=__version__, command=[sys.executable, "-B", __file__, *(argv if argv is not None else sys.argv[1:])],
                              config={"prereg_git_sha": PREREG_SHA, "prereg_sha256": PREREG_HASH, "requested_workers": args.workers,
                                      "workers": workers, "phase": "pilot"},
                              seeds=list(range(6)), snapshot=REPO / "data/pinned/20261010T1358Z-celestrak",
                              outputs=sorted(p for p in args.out.rglob("*") if p.is_file() and p != args.out / "manifest.json"),
                              labels=labels.pick("routes_and_budgets", "isl_topology_grid4", "traffic_probes", "fault_slow_link"),
                              extra={"forecast": forecast, "confirmation_started": False}, timer=timer)
    print(json.dumps(forecast, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

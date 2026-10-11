"""The remaining fixed pilot matrix and deterministic E16 validity gate."""

import argparse
import copy
import csv
import json
from pathlib import Path
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import numpy as np

from chronoroute import __version__, labels, provenance
from chronoroute.baselines import run as brun
from chronoroute.baselines.engine import SchemeEngine
from chronoroute.baselines.params import normalise_scheme
from chronoroute.eval import load
from chronoroute.export import bundle, ns3_crosscheck
from chronoroute.fwd.config import normalise
from chronoroute.fwd.faults import renewal_periods
from chronoroute.fwd.rng import KeyedStreams
from chronoroute.fwd.scenario import build_scenario
from chronoroute.trace.writer import write_json

import campaign as e1

REPO = e1.REPO
NS3 = Path.home() / "ns-3-dev/build/contrib/chronoroute/examples/ns3.44-chronoroute-leo-default"


def send_times(seed, *, stochastic):
    """Registered CBR or conditional-Poisson integer sends, identical on both engines."""
    rng = KeyedStreams(seed)
    result = []
    for flow in range(2):
        if stochastic:
            gen = rng.generator("traffic", (flow,))
            values = set()
            while len(values) < 1200:
                values.add(int(gen.integers(0, 12000000000)))
            result.append(sorted(values))
        else:
            offset = int(rng.uniform("flow_offset", (flow,), 0) * 10000000)
            result.append(list(range(offset, 12000000000, 10000000)))
    return result


def write_sends(path, sends):
    """One explicit packet-ID/send-time list consumed by ns-3."""
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["flow_id", "seq", "send_ns"])
        for flow, times in enumerate(sends):
            w.writerows((flow, seq, t) for seq, t in enumerate(times))


def replay_config(const, seed, *, stochastic, fault):
    """E16 has zero processing in both actual and predicted timing."""
    j = {"const": const, "seed": seed, "phase": "pilot", "scheme": "chronoroute", "condition": "none"}
    cfg = e1.document(j)["engine"]
    cfg["schedule"].update(plan_links="stable", planner_processing_ns=0)
    cfg["forwarding"].update(processing_ns=0, jitter={"model": "none", "mean_ns": 400000},
                             background={"model": "none", "rho": 0, "links": "all", "packet_bytes": 1500, "window_ms": 10})
    for flow, times in zip(cfg["traffic"]["flows"], send_times(seed, stochastic=stochastic)):
        flow["send_times_ns"] = times
    if fault:
        cfg["faults"] = [{"kind": "rate_cut", "factor": 0.0002, "start_s": 4, "stop_s": 8,
                          "on_path": {"flow": 0, "at_s": 4, "position": "middle", "kind": "isl"}}]
    return normalise(cfg)


def targeted_faults(seed, node):
    """Stationary profile-B intervals on one satellite, not population churn."""
    periods = renewal_periods(KeyedStreams(seed), "node_fault", (node,), 3000000000, 27000000000, "0.05", 2000000000)
    return [{"kind": "node_down", "node": node, "start_s": a / 1e9, "stop_s": b / 1e9} for a, b in periods]


def deviation_factory(target, records):
    """MODELLED policy intervention: invoke ordinary late processing without service delay.

    Only the checker's decision input is forced past its encoded deadline.
    The actual packet clock, arrival time, queue service and geometry stay
    unchanged. Each intervention records both clocks; these are not FPR data.
    """
    class ControlledDeviation(SchemeEngine):
        def _on_arrive(self, p, t, frm, node, inport):
            raw = p.raw
            if (p.flow != 0 or node != target or not 4000000000 <= t < 8000000000 or
                    raw is None or raw[4] & 1 or p.pkt in self._triggered or
                    self._lost_on_arrival(node, t, inport)):
                return super()._on_arrive(p, t, frm, node, inport)
            k = raw[5] - raw[3]
            deadline = (int.from_bytes(raw[8:12], "big") + sum(raw[14 + 3 * (raw[5] - 1 - i)] for i in range(k))) & 0xFFFFFFFF
            forced = (deadline + 1) & 0xFFFFFFFF
            self._triggered.add(p.pkt)
            records.append({"pkt": p.pkt, "node": node, "t_ns": t, "label": "MODELLED",
                            "actual_now_u": self.clock_u(t), "forced_checker_now_u": forced,
                            "path_before": list(p.path), "reason": "controlled policy intervention, not a deadline alarm"})
            original = self._fp
            self._fp = lambda r, now, policy: original(r, forced, policy)
            try:
                return super()._on_arrive(p, t, frm, node, inport)
            finally:
                self._fp = original

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._triggered = set()

        def _finish(self, p, t, node, outcome, reason=None):
            if p.pkt in self._triggered:
                record = next(r for r in reversed(records) if r["pkt"] == p.pkt)
                record.update(outcome=outcome, drop_reason=reason, visited_entries=len(p.visited or ()),
                              visited_set_object_bytes=sys.getsizeof(p.visited) if p.visited is not None else 0)
            return super()._finish(p, t, node, outcome, reason)
    return ControlledDeviation


def pilot_jobs():
    """The remaining thirty jobs of preregistration section 10."""
    rows = []
    for const in ("C5", "C2"):
        for scheme in ("greedy_visited", "continue", "o_t", "snap", "ls_h", "crh16"):
            rows.append({"id": f"E04-{const}-{scheme}-s0001", "experiment": "E04", "const": const, "scheme": scheme, "seed": 1})
        for policy in ("greedy_visited", "greedy_pure", "grid_detour", "continue", "drop"):
            rows.append({"id": f"E05-{const}-{policy}-s0002", "experiment": "E05", "const": const, "scheme": policy, "seed": 2})
        for fault in (False, True):
            for engine in ("python", "ns3"):
                rows.append({"id": f"E16-{const}-{engine}-{'fault' if fault else 'none'}-s0003", "experiment": "E16",
                             "const": const, "scheme": engine, "seed": 3, "fault": fault})
    return rows


def pilot_config(job):
    """Compile a targeted renewal history or frozen policy intervention."""
    cfg = e1.document({**job, "phase": "pilot", "scheme": "chronoroute", "condition": "none"})["engine"]
    cfg["schedule"].update(plan_links="stable", planner_processing_ns=500000)
    cfg["forwarding"].update(jitter={"model": "none", "mean_ns": 400000},
                             background={"model": "none", "rho": 0, "links": "all", "packet_bytes": 1500, "window_ms": 10})
    scheme = {"name": "chronoroute"}
    if job["experiment"] == "E04":
        cfg["scenario"].update(duration_s=30, drain_s=2)
        sc = build_scenario(cfg)
        target = sc.resolve_on_path({"flow": 0, "at_s": 3, "position": "middle"}, 3000000000, True)
        cfg["faults"] = targeted_faults(1, target)
        name = job["scheme"]
        if name == "greedy_visited":
            cfg["forwarding"].update(policy="greedy", fallback="greedy_visited")
        elif name in ("continue", "crh16"):
            cfg["forwarding"].update(policy="continue", fallback="none")
            scheme["name"] = "crh16" if name == "crh16" else "chronoroute"
        else:
            scheme["name"] = name
            if name == "ls_h":
                scheme["ls"] = {"bfd": True, "preset": "olsr_leo"}
        intervention = {"target": target, "stream": ["node_fault", [target]], "intervals": cfg["faults"]}
    else:
        sc = build_scenario(cfg)
        path = sc.path_at(0, 4000000000)
        candidates = [n for n in path if n < sc.topo.n_sats]
        index = int(KeyedStreams(2).uniform("experiment_target", (0,), 0) * len(candidates))
        target = candidates[index]
        policy = job["scheme"]
        cfg["forwarding"].update(policy="greedy" if policy.startswith("greedy") or policy == "grid_detour" else policy,
                                 fallback=policy if policy in ("greedy_visited", "greedy_pure", "grid_detour") else "greedy_visited")
        intervention = {"label": "MODELLED", "target": target, "stream": ["experiment_target", [0]], "records": []}
    return normalise(cfg), normalise_scheme(scheme), intervention


def run_child(job, out):
    """One pilot engine process with its ordinary complete output accounting."""
    cfg, scheme, intervention = pilot_config(job)
    campaign = {"prereg_path": "experiments/PREREG.md", "prereg_git_sha": e1.PREREG_SHA, "prereg_sha256": e1.PREREG_HASH,
                "phase": "pilot", "experiment": job["experiment"], "cell_id": job["id"], "pair_id": job["seed"] % 18, "seed": job["seed"]}
    factory = deviation_factory(intervention["target"], intervention["records"]) if job["experiment"] == "E05" else SchemeEngine
    summary, _ = brun.run_scheme(cfg, scheme, out, argv=[sys.executable, "-B", __file__, *sys.argv[1:]],
                                engine_factory=factory, run_extra={"campaign": campaign, "intervention": intervention})
    e1.attach_metadata(out, campaign, {"kind": "child engine; measured by parent"})
    return int(not summary["conservation"]["ok"] or summary["invariants"]["violations"] != 0)


def run_replay(const, seed, fault, stochastic, out, *, engines=("python", "ns3")):
    """Export common schedule/truth and replay both engines, including queues."""
    out.mkdir(parents=True, exist_ok=False)
    pair_timer = provenance.RunTimer().start()
    cfg = replay_config(const, seed, stochastic=stochastic, fault=fault)
    sc = build_scenario(cfg)
    target = sc.resolve_on_path({"flow": 0, "at_s": 4, "position": "middle", "kind": "isl"}, 4000000000, False)
    if fault:
        cfg["faults"][0].pop("on_path")
        cfg["faults"][0]["link"] = list(target)
    bc = bundle.BundleConfig(shell_id=sc.topo.shell.shell_id, cities=tuple(sc.cities), t0_ns=sc.t0_ns,
                             window_ms=14000, flows=tuple((f.src, f.dst) for f in sc.flows), processing_ns=0)
    b = bundle.build_bundle(sc.fleet, bc, sc.registry)
    bundle.write_bundle(b, out / "bundle", command=[sys.executable, "-B", __file__, "export-common-replay"])
    sends = [f["send_times_ns"] for f in cfg["traffic"]["flows"]]
    write_sends(out / "sends.csv", sends)
    scheme = normalise_scheme({"name": "chronoroute", "outputs": {"stretch_oracle": False}})
    write_json(out / "engine.json", {**cfg, "scheme": scheme})
    campaign = {"prereg_path": "experiments/PREREG.md", "prereg_git_sha": e1.PREREG_SHA, "prereg_sha256": e1.PREREG_HASH,
                "phase": "pilot", "experiment": "E16", "cell_id": out.name, "pair_id": seed % 18, "seed": seed}
    e1.attach_metadata(out / "bundle", campaign, {"kind": "common schedule and truth export"})
    rows = []
    for engine in engines:
        child = out / engine
        child.mkdir()
        if engine == "python":
            cmd = [str(REPO / "venv/bin/python"), "-B", "-m", "chronoroute.cli", "run", "--scheme",
                   "--config", str(out / "engine.json"), "--out", str(child)]
        else:
            li = next(i for i, (a, c) in enumerate(zip(b.scenario.isl_a, b.scenario.isl_b)) if {int(a), int(c)} == set(target))
            cmd = [str(NS3), f"--bundle={out / 'bundle'}", f"--outDir={child}", f"--seed={seed}",
                   f"--fault={int(fault)}", f"--faultIsl={li}", "--faultStartMs=4000", "--faultDurationMs=4000",
                   "--faultRate=200000bps", "--queueSize=2500000B", "--policy=continue", "--pcap=0",
                   "--sendStopMs=12000", "--drainMs=2000", f"--sendTimes={out / 'sends.csv'}"]
        with provenance.RunTimer() as timer:
            row = {"experiment": "E16", "const": const, "scheme": engine, "seed": seed, "fault": fault,
                   **e1.measured_command(cmd, out / f"{engine}_command")}
        if engine == "python" and row["status"] == "ok":
            e1.attach_metadata(child, campaign, row, inputs=[out / "bundle/manifest.json", out / "sends.csv"])
        elif engine == "ns3":
            provenance.write_manifest(child, tool="E16 ns3 replay", tool_version=__version__, command=cmd,
                                      config={"run": cfg, "queue_bytes": 2500000}, seeds=[seed],
                                      outputs=list(p for p in child.rglob("*") if p.is_file()),
                                      labels=labels.pick("routes_and_budgets", "traffic_probes", "link_rate_and_queues"),
                                      extra={"campaign": campaign, "observation": row,
                                             "inputs": [{"path": str(p), "sha256": provenance.file_sha256(p)} for p in (out / "bundle/manifest.json", out / "sends.csv")]}, timer=timer)
        rows.append(row)
    comparison = None
    if len(rows) == 2 and all(r["status"] == "ok" for r in rows):
        comparison = ns3_crosscheck.compare_replays(load.load_run(out / "python"), ns3_crosscheck.read_packets(out / "ns3/packets.csv"))
        write_json(out / "comparison.json", comparison)
    write_json(out / "inventory.json", rows)
    pair_timer.stop()
    provenance.write_manifest(out, tool="E16 paired replay", tool_version=__version__, command=[sys.executable, "-B", __file__, *sys.argv[1:]],
                              config={"campaign": campaign, "stochastic": stochastic, "run": cfg}, seeds=[seed],
                              outputs=sorted(p for p in out.rglob("*") if p.is_file() and p != out / "manifest.json"),
                              labels=labels.pick("routes_and_budgets", "traffic_probes", "link_rate_and_queues"),
                              extra={"campaign": campaign, "comparison": comparison}, timer=pair_timer)
    return rows, comparison


def main(argv=None):
    """Run the remaining matrix, gates and a manifested complete resource forecast."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--e1-pilot", type=Path)
    parser.add_argument("--job-json", type=Path)
    parser.add_argument("--workers", type=int, default=8, choices=range(1, 9))
    if argv is not None and "--help" in argv:
        parser.print_help()
        return 0
    args = parser.parse_args(argv)
    if args.job_json:
        return run_child(json.loads(args.job_json.read_text()), args.out)
    e1.validate_protocol()
    if provenance.git_state(REPO)["dirty"]:
        raise ValueError("commit implementation before experiments")
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=False)
    observations, comparisons = [], []
    with provenance.RunTimer() as timer:
        # Gate work is outside the fixed cost-pilot matrix, with pilot seed 0.
        for const in ("C5", "C2"):
            for fault in (False, True):
                rows, comparison = run_replay(const, 0, fault, False, args.out / f"gate-{const}-{'fault' if fault else 'none'}")
                observations.extend(rows)
                comparisons.append(comparison)
        gate_ok = all(c is not None and c["violations"] == 0 for c in comparisons)
        pilot = pilot_jobs()
        for job in pilot:
            if job["experiment"] == "E16" and job["scheme"] == "python":
                rows, _ = run_replay(job["const"], 3, job["fault"], True, args.out / f"cost-{job['const']}-{'fault' if job['fault'] else 'none'}")
                observations.extend(rows)
        remaining = [j for j in pilot if j["experiment"] != "E16"]
        for job in remaining:
            write_json(args.out / f"{job['id']}.json", job)
        def work(job):
            cmd = [str(REPO / "venv/bin/python"), "-B", __file__, "--job-json", str(args.out / f"{job['id']}.json"),
                   "--out", str(args.out / job["id"])]
            return {**job, **e1.measured_command(cmd, args.out / f"{job['id']}_command", timeout=120 if job["experiment"] == "E04" else 60)}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            observations.extend(pool.map(work, remaining))
        e1.write_csv(args.out / "inventory.csv", [{**r, "id": r.get("id", f"{r['experiment']}-{r['const']}-{r['scheme']}-{r['seed']}-{r.get('fault')}")}
                                                for r in observations])
        write_json(args.out / "observations.json", observations)
        e1_forecast = json.loads((args.e1_pilot / "resource_forecast.json").read_text())
        effort = {}
        for family, n in (("E04", 2160), ("E05", 432), ("E16", 288)):
            cells = [r["cpu_s"] for r in observations if r["experiment"] == family and r["status"] == "ok"]
            effort[family] = 1.25 * max(cells) * n / e1_forecast["effective_workers"] if cells else None
        score_times = json.loads((args.e1_pilot / "score_inventory.json").read_text())
        effort["E01_scoring_and_roc"] = 9576 * max(r["cpu_s"] for r in score_times) / e1_forecast["effective_workers"]
        total = (timer.wall_seconds + e1_forecast["measured_spent_s"] + e1_forecast["e1_projected_s"] +
                 sum(v for v in effort.values() if v is not None) + 1200 + 3600 / e1_forecast["effective_workers"])
        allowed = gate_ok and all(r["status"] == "ok" for r in observations) and all(v is not None for v in effort.values()) and total <= 21600
        forecast = {"label": "MODELLED", "confirmation_allowed": allowed, "deterministic_gate_passed": gate_ok,
                    "projected_campaign_wall_s": total, "remaining_work_s": effort, "spent_prerequisites_s": timer.wall_seconds,
                    "e1_forecast": e1_forecast, "reason": "all gates passed" if allowed else "gate, failed pilot or resource limit failed"}
        write_json(args.out / "resource_forecast.json", forecast)
        e1.write_csv(args.out / "summary.csv", [{"endpoint": f"deterministic_gate_{i}", "violations": c["violations"] if c else None,
                                               "status": "passed" if c and c["violations"] == 0 else "failed"} for i, c in enumerate(comparisons)])
    provenance.write_manifest(args.out, tool="E01 prerequisite pilots", tool_version=__version__, command=[sys.executable, "-B", __file__, *(argv if argv is not None else sys.argv[1:])],
                              config={"prereg_git_sha": e1.PREREG_SHA, "prereg_sha256": e1.PREREG_HASH, "workers": args.workers}, seeds=[0, 1, 2, 3],
                              outputs=sorted(p for p in args.out.rglob("*") if p.is_file() and p != args.out / "manifest.json"),
                              labels=labels.pick("routes_and_budgets", "traffic_probes", "link_rate_and_queues"),
                              extra={"forecast": forecast, "e1_pilot_manifest_sha256": provenance.file_sha256(args.e1_pilot / "manifest.json")}, timer=timer)
    print(json.dumps(forecast, indent=2), flush=True)
    return 0 if allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())

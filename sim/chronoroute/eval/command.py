"""
command.py
----------
The `cr eval` commands.

    cr eval scheme --config RUN.yaml [--scheme NAME] [--seed N] --out DIR
        run one comparison scheme (baselines/run.py); RUN.yaml is an engine
        config (docs/sim-config.md) with an optional `scheme:` block
        (docs/baselines.md). --scheme NAME overrides the block with a bare name.

    cr eval score RUN_DIR [--twin DIR] [--slack S ...] [--k K] [--window-ms W]
                  [--warmup-s X] [--q-th-ms Q] --out DIR
        the metrics of one run (PDR with loss reasons, effective quantiles,
        stretch with its check, labels and clean FPR, control bytes, blackhole
        and time-to-mitigation per fault); with --twin (the same run without the
        fault) also the counterfactual and event-level detection, re-scored for
        every --slack offline. Writes summary.json, summary.csv, manifest.json.

    cr eval roc --pairs FAULT_DIR:TWIN_DIR ... --slack S ... [--k K] [--window-ms W] --out DIR
        the event ROC over a slack sweep (offline), one row per slack.
"""

import csv
import json
import sys
from dataclasses import replace
from pathlib import Path

from .. import __version__, provenance
from ..fwd import config as config_mod
from ..trace import writer as tw
from . import detection, metrics
from .load import load_run
from .offline import Rule, check_plans

EVAL_LABELS = {"evaluation_metrics": "DERIVED"}


def _scheme_cmd(args):
    from ..baselines import run as brun
    try:
        cfg, scheme = brun.load_run_file(args.config, seed=args.seed,
                                         scheme_override=args.scheme)
    except (config_mod.ConfigError, OSError) as exc:
        print(f"cr eval scheme: {exc}", file=sys.stderr)
        return 2
    summary, written = brun.run_scheme(cfg, scheme, args.out, argv=["cr"] + list(args.argv))
    c = summary["counts"]
    print(f"cr eval scheme: {summary['scheme']['label']}: {c['sent']} sent, {c['delivered']} delivered, "
          f"{c['dropped']} dropped, {c['no_route']} without a route, {c['unfinished']} unfinished, "
          f"{c['late']} flagged late")
    if summary["drops"]:
        print("cr eval scheme: drops by reason: " + ", ".join(f"{k} {v}" for k, v in summary["drops"].items()))
    cb = summary["scheme"]["control_bytes"]
    print("cr eval scheme: control bytes " + ", ".join(f"{m} {v['bytes']}" for m, v in cb.items()))
    st = summary["scheme"].get("crh_state_steady_bytes_per_s")
    if st:
        print(f"cr eval scheme: satellite state uploads (CRH-FIB, station table, element sets), steady "
              f"state: uplink {st['uplink']} B/s, isl {st['isl']} B/s (DERIVED from sizes and periods)")
    print(f"cr eval scheme: conservation {'ok' if summary['conservation']['ok'] else 'BROKEN'}, "
          f"invariant violations {summary['invariants']['violations']}; wrote {len(written)} files to {args.out}")
    ok = summary["conservation"]["ok"] and summary["invariants"]["violations"] == 0
    return 0 if ok else 1


def score_run(run_dir, *, twin_dir=None, slacks=(), k=1, window_ns=1_000_000_000, warmup_ns=0, q_th_ns=None,
              rules=(), flow=None, include_null=False, check_plan_rules=False, sensitivity_ks=(), secondary_flow=None):
    """Everything `cr eval score` reports, as one JSON-ready dict."""
    run = load_run(run_dir)
    mask = metrics.measurement_mask(run, warmup_ns)
    det_mask = mask & (run.flow == flow) if flow is not None else mask
    out = {"run": str(run_dir), "scheme": run.scheme.get("label", run.scheme.get("name")),
           "seed": run.engine.get("seed"), "pdr": metrics.pdr_total(run, mask),
           "pdr_by_flow": metrics.pdr_by_flow(run, mask), "latency": metrics.latency_summary(run, mask),
           "control": metrics.control_summary(run)}
    if run.has_extras():
        out["stretch"] = metrics.stretch(run, mask)
        lab = metrics.packet_labels(run, det_mask, q_th_ns)
        out["labels"] = {name: int((lab == i).sum()) for i, name in enumerate(metrics.LABELS)}
        fl = detection.flags_for(run)
        no_packet_detector = run.scheme.get("name") in ("ls_h", "ls_d", "o_q")
        out["fpr"] = None if no_packet_detector else metrics.deadline_fpr(lab, fl.flagged & det_mask)
        out["faults"] = []
        for f in run.faults:
            row = {"fault": f, "blackhole": metrics.blackhole(run, f),
                   "ttm": metrics.time_to_mitigation(run, f)}
            out["faults"].append(row)
    if twin_dir is not None:
        twin = load_run(twin_dir)
        faults = detection.scored_faults(run, twin)
        if not faults:
            detection.check_twin(run, twin)
        if include_null and not faults:
            faults = [f for f in run.faults if detection.is_null_fault(f)]
        det = []
        rule_list = [None] + [Rule(kind="mult", slack=str(s)) for s in slacks] + list(rules)
        native_ls = run.scheme.get("name") in ("ls_h", "ls_d")
        if len(rule_list) > 1 and run.scheme.get("name", "chronoroute") != "chronoroute":
            raise ValueError("offline rules apply only to ChronoRoute")
        twin_mask = metrics.measurement_mask(twin, warmup_ns)
        if flow is not None:
            twin_mask &= twin.flow == flow
        if check_plan_rules:
            changes, checked = [], 0
            from ..fwd.scenario import build_scenario
            for data in (run, twin):
                cfg = data.engine["config"]
                sc = build_scenario(cfg) if cfg["schedule"]["plan_links"] == "instant" else None
                for rule in rule_list[1:]:
                    changed = check_plans(cfg, data, rule, scenario=sc)
                    checked += len(data.schedule)
                    changes.extend((str(data.dir), rule.label, row) for row in changed)
            out["plan_checks"] = {"checked": checked, "violations": len(changes), "changed": changes}
            if changes:
                raise ValueError("offline rule changes planned paths; direct rerun or prospective amendment required")
        for rule in rule_list:
            if rule is not None and run.engine.get("policy") != "continue":
                raise ValueError("offline slack re-scoring needs a flag-and-continue run")
            f1 = detection.flags_for(run, rule)
            f0 = detection.flags_for(twin, rule)
            all_f1, all_f0 = f1, f0
            f1 = replace(f1, flagged=f1.flagged & det_mask)
            f0 = replace(f0, flagged=f0.flagged & twin_mask)
            rows = []
            # only the faults the twin does not have; check_twin (inside every call below)
            # refuses a twin whose other faults differ from the fault run's
            for f in faults:
                rows.append({"fault": metrics.fault_element(f),
                             "packet": detection.counterfactual(run, twin, f1, f0, f, det_mask),
                             "event": detection.event_detection(run, twin, f1, f0, f, k, window_ns),
                             "control_plane": detection.control_plane_detection(run, twin, f)})
            fe = detection.false_events_per_hour(twin, f0, k, window_ns)
            if native_ls:
                lo, hi = metrics.send_window(twin)
                fe["events"] = sum(lo <= d["t_ns"] < hi and d["kind"] in ("adjacency_down", "metric") for d in twin.detections)
                fe["per_hour"] = fe["events"] / fe["hours"] if fe["hours"] else None
            det.append({"rule": "as run" if rule is None else rule.label, "faults": rows,
                        "false_events_per_hour_twin": fe["per_hour"], "false_events_twin": fe,
                        "fpr": None if no_packet_detector else metrics.deadline_fpr(lab, f1.flagged),
                        "fpr_twin": None if no_packet_detector else metrics.deadline_fpr(metrics.packet_labels(twin, twin_mask, q_th_ns), f0.flagged)})
            sensitivities = []
            for sensitivity_k in sensitivity_ks:
                if sensitivity_k <= 0:
                    raise ValueError("event sensitivity k must be positive")
                sfe = detection.false_events_per_hour(twin, f0, sensitivity_k, window_ns)
                if native_ls:
                    sfe = fe
                sensitivities.append({"k": sensitivity_k, "false_events_twin": sfe,
                    "faults": [{"event": detection.event_detection(run, twin, f1, f0, f, sensitivity_k, window_ns),
                                "control_plane": row["control_plane"]} for f, row in zip(faults, rows)]})
            det[-1]["sensitivities"] = sensitivities
            secondary = []
            if secondary_flow is not None and not native_ls and run.scheme.get("name") != "o_q":
                sm1 = mask & (run.flow == secondary_flow)
                sm0 = metrics.measurement_mask(twin, warmup_ns) & (twin.flow == secondary_flow)
                sf1 = replace(all_f1, flagged=all_f1.flagged & sm1)
                sf0 = replace(all_f0, flagged=all_f0.flagged & sm0)
                for f in faults:
                    secondary.append({"flow": secondary_flow,
                        "packet": detection.counterfactual(run, twin, sf1, sf0, f, sm1),
                        "event": detection.event_detection(run, twin, sf1, sf0, f, k, window_ns),
                        "fpr": metrics.deadline_fpr(metrics.packet_labels(run, sm1, q_th_ns), sf1.flagged),
                        "fpr_twin": metrics.deadline_fpr(metrics.packet_labels(twin, sm0, q_th_ns), sf0.flagged),
                        "false_events_twin": detection.false_events_per_hour(twin, sf0, k, window_ns)})
            det[-1]["secondary"] = secondary
        out["detection"] = det
    return out


def _flat_rows(res):
    rows = []
    base = {"run": res["run"], "scheme": res["scheme"], "seed": res["seed"]}
    for f in res["pdr_by_flow"]:
        r = dict(base, metric="pdr", flow=f["flow"], value=f["pdr"], n=f["sent"],
                 detail=json.dumps(f["losses"], sort_keys=True))
        rows.append(r)
    for f in res["latency"]:
        for key, v in f.items():
            if key.startswith("q"):
                rows.append(dict(base, metric=key, flow=f["flow"], value=v if v != float("inf") else "inf",
                                 n=f["sent"], detail=""))
    if "stretch" in res:
        s = res["stretch"]
        rows.append(dict(base, metric="stretch_min", flow="", value=s["min"], n=s["n_no_step_crossing"],
                         detail=f"packets in their send step (tol 0), >= 1 exactly; violations={s['violations']}"))
        rows.append(dict(base, metric="stretch_min_tol_adjusted", flow="", value=s["min_tol_adjusted"],
                         n=s["n_in_send_graph"], detail="(L_det + tol) / L*"))
        rows.append(dict(base, metric="stretch_min_raw", flow="", value=s["min_raw"], n=s["n"],
                         detail="raw L_det / L*, step-crossing packets included: may be < 1 by up to tol"))
    if res.get("fpr") is not None:
        rows.append(dict(base, metric="clean_fpr", flow="", value=res["fpr"]["fpr"], n=res["fpr"]["clean"],
                         detail=""))
    for m, v in res["control"].get("control_bytes", {}).items():
        rows.append(dict(base, metric=f"control_bytes_{m}", flow="", value=v, n="", detail=""))
    for d in res.get("detection", []):
        for f in d["faults"]:
            rows.append(dict(base, metric="p_det_packet", flow="", value=f["packet"]["p_det_packet"],
                             n=f["packet"]["exposed"], detail=d["rule"]))
            rows.append(dict(base, metric="lost_at_fault", flow="", value=f["packet"]["lost_at_fault"],
                             n=f["packet"]["reached"], detail=d["rule"] + "; dropped on the faulty element, "
                             "not in p_det"))
            event = f["control_plane"] if res["scheme"].startswith(("ls_h", "ls_d")) else f["event"]
            rows.append(dict(base, metric="event_detected", flow="", value=int(event["detected"]),
                             n=1, detail=d["rule"]))
    return rows


def _write_outputs(out_dir, doc, rows, argv, config):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def clean(x):
        if isinstance(x, float) and x == float("inf"):
            return "inf"
        if isinstance(x, dict):
            return {str(k): clean(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [clean(v) for v in x]
        return x

    tw.write_json(out_dir / "summary.json", clean(doc))
    cols = ["run", "scheme", "seed", "metric", "flow", "value", "n", "detail"]
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    provenance.write_manifest(out_dir, tool="cr eval", tool_version=__version__, command=argv, config=config,
                              seeds=[], outputs=[out_dir / "summary.json", out_dir / "summary.csv"],
                              labels=EVAL_LABELS)


def _score_cmd(args):
    try:
        res = score_run(args.run, twin_dir=args.twin, slacks=args.slack or (), k=args.k,
                        window_ns=int(args.window_ms * 1_000_000), warmup_ns=int(args.warmup_s * 1e9),
                        q_th_ns=None if args.q_th_ms is None else int(args.q_th_ms * 1_000_000),
                        rules=[Rule(**r) for r in json.loads(Path(args.rules).read_text())] if args.rules else (),
                        flow=args.flow, include_null=args.include_null, check_plan_rules=args.check_plans,
                        sensitivity_ks=args.sensitivity_k or (), secondary_flow=args.secondary_flow)
    except ValueError as exc:
        # e.g. detection.check_twin refusing a pair that is not a counterfactual pair: say why
        # and write nothing (a half-scored folder would look like a result)
        print(f"cr eval score: {exc}", file=sys.stderr)
        return 2
    _write_outputs(args.out, res, _flat_rows(res), ["cr"] + list(args.argv),
                   {"run": str(args.run), "twin": args.twin, "slack": list(args.slack or []), "k": args.k,
                    "window_ms": args.window_ms, "warmup_s": args.warmup_s, "q_th_ms": args.q_th_ms,
                    "rules": args.rules, "flow": args.flow, "include_null": args.include_null, "check_plans": args.check_plans,
                    "sensitivity_k": args.sensitivity_k, "secondary_flow": args.secondary_flow})
    p = res["pdr"]
    print(f"cr eval score: PDR {p['pdr']} ({p['delivered']}/{p['sent']}), losses {p['losses']}")
    if "stretch" in res:
        s = res["stretch"]
        print(f"cr eval score: stretch min {s['min']} over {s['n_no_step_crossing']} packets that stayed "
              f"in their send step (>= 1 exactly); tolerance-adjusted min {s['min_tol_adjusted']}; "
              f"raw min {s['min_raw']} (step-crossing packets included); violations {s['violations']} "
              f"({s['n_path_not_in_send_graph']} paths outside the send-time graph)")
    print(f"cr eval score: wrote {args.out}")
    return 0 if res.get("stretch", {}).get("violations", 0) == 0 else 1


def _roc_cmd(args):
    pairs = []
    for spec in args.pairs:
        a, b = spec.split(":", 1)
        pairs.append((load_run(a), load_run(b)))
    rules = [Rule(kind="mult", slack=str(s)) for s in args.slack or ()]
    if args.rules:
        rules += [Rule(**r) for r in json.loads(Path(args.rules).read_text())]
    if not rules:
        rules = [None]
    try:
        rows = detection.event_roc(pairs, None, rules, k=args.k, window_ns=int(args.window_ms * 1_000_000),
                                   flow=args.flow, include_null=args.include_null)
    except ValueError as exc:
        print(f"cr eval roc: {exc}", file=sys.stderr)
        return 2
    doc = {"pairs": args.pairs, "k": args.k, "window_ms": args.window_ms, "rows": rows}
    flat = [{"run": ";".join(args.pairs), "scheme": "chronoroute", "seed": "", "metric": "roc", "flow": "",
             "value": r["p_det"], "n": r["fault_events"],
             "detail": json.dumps({k: v for k, v in r.items() if k != "p_det"}, sort_keys=True)} for r in rows]
    _write_outputs(args.out, doc, flat, ["cr"] + list(args.argv),
                   {"pairs": args.pairs, "slack": list(args.slack or ()), "k": args.k, "window_ms": args.window_ms,
                    "rules": args.rules, "flow": args.flow, "include_null": args.include_null})
    for r in rows:
        print(f"cr eval roc: {r['rule']}: P_det {r['p_det']}, false events/h {r['false_events_per_hour']}, "
              f"clean FPR {r['clean_fpr']}")
    return 0


def register(registry):
    p = registry.command("eval", "scheme", help="run one comparison scheme (docs/baselines.md)",
                         func=_scheme_cmd, group_help="baselines and offline evaluation")
    p.add_argument("--config", required=True, help="engine config plus an optional scheme: block")
    p.add_argument("--scheme", default=None, help="scheme name (overrides the scheme: block)")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--out", required=True)
    p = registry.command("eval", "score", help="metrics of one run (and detection against its twin)",
                         func=_score_cmd)
    p.add_argument("run")
    p.add_argument("--twin", default=None, help="the same run without the fault (same seed)")
    p.add_argument("--slack", type=str, nargs="*", default=None, help="slack values to re-score offline")
    p.add_argument("--k", type=int, default=1, help="event detector: flags needed")
    p.add_argument("--window-ms", type=float, default=1000.0, help="event detector window")
    p.add_argument("--warmup-s", type=float, default=0.0)
    p.add_argument("--q-th-ms", type=float, default=None, help="queueing threshold of the 'congested' label")
    p.add_argument("--rules", help="JSON array of offline.Rule parameter mappings")
    p.add_argument("--flow", type=int, help="restrict packet flags and detection denominators to this flow")
    p.add_argument("--include-null", action="store_true", help="explicitly score null faults against their twins")
    p.add_argument("--check-plans", action="store_true", help="refuse offline rules that change any recorded path")
    p.add_argument("--sensitivity-k", type=int, nargs="+", help="additional descriptive event thresholds, using the same flags")
    p.add_argument("--secondary-flow", type=int, help="also report detection on this flow with the same offline rules")
    p.add_argument("--out", required=True)
    p = registry.command("eval", "roc", help="event ROC over an offline slack sweep", func=_roc_cmd)
    p.add_argument("--pairs", nargs="+", required=True, help="FAULT_DIR:TWIN_DIR pairs")
    p.add_argument("--slack", nargs="+")
    p.add_argument("--rules", help="JSON array of offline.Rule parameter mappings; omitted rules use native flags")
    p.add_argument("--flow", type=int)
    p.add_argument("--include-null", action="store_true")
    p.add_argument("--k", type=int, default=1)
    p.add_argument("--window-ms", type=float, default=1000.0)
    p.add_argument("--out", required=True)


__all__ = ["score_run", "register"]

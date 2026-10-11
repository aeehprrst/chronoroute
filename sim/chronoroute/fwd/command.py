"""
command.py
----------
`cr run --config FILE [--seed N] --out DIR`: one run of the simulator v2.

Writes into DIR (spec/trace-v1.md and docs/sim-config.md describe every file):

    run.json             the trace/1 run description (nodes, time base, ground-truth faults, labels)
    events.jsonl.gz      trace/1 events (all packets, sampled packets, or none: output.trace)
    packets.csv.gz       one row per packet (outcome, reason, latency, path, DEV, per-hop clocks)
    schedule.csv.gz      every planned (flow, refresh interval): path, SIDs, budgets, T-CRH template
    summary.json         counts, drops by reason, per-flow PDR/latency, invariants, speed, memory
    capture.pcap         (output.pcap) frames of sampled packets as they leave each node
    synthetic_omm.json   (Walker presets) the generated element sets the positions come from
    manifest.json        provenance (commit, config, seed, snapshot sha256, output sha256s)
"""

import hashlib
import sys
from pathlib import Path

from .. import __version__, labels as labels_mod, provenance
from ..data import omm
from ..trace import writer as tw
from . import config as config_mod
from .engine import Engine
from .scenario import build_scenario

TOOL = "python-sim"

# Labels this engine needs that the shared table (chronoroute/labels.py) does
# not have yet. They are used only while the key is missing from the table
# (a request to the labels owner is open); once added there, the table wins.
PENDING_LABELS = {
    "synthetic_walker_constellation": "MODELLED",
    "background_cross_traffic": "MODELLED",
    "fault_models": "MODELLED",
    "jitter_j1": "MODELLED",
    "fallback_forwarding": "MODELLED",
}


def _label(key):
    return labels_mod.TABLE[key] if key in labels_mod.TABLE else PENDING_LABELS[key]


def run_labels(cfg):
    """{key: label} for everything a run's outputs show (see PENDING_LABELS)."""
    keys = []
    if cfg["scenario"]["kind"] == "real":
        keys += ["orbital_elements", "satellite_positions_sgp4"]
    else:
        keys += ["synthetic_walker_constellation"]
    keys += ["city_coordinates", "shells_and_planes", "isl_topology_grid4", "gsl_mask_and_assignment",
             "routes_and_budgets", "tcrh_header_bytes", "processing_delay", "link_rate_and_queues",
             "traffic_probes"]
    fw = cfg["forwarding"]
    if fw["background"]["model"] != "none":
        keys.append("background_cross_traffic")
    if fw["jitter"]["model"] != "none":
        keys.append("jitter_j1")
    if cfg["faults"]:
        keys.append("fault_models")
        if any(f["kind"] in ("slow_processing", "rate_cut", "arq") for f in cfg["faults"]):
            keys.append("fault_slow_link")
    if fw["fallback"] != "none":
        keys.append("fallback_forwarding")
    return {k: _label(k) for k in keys}


def _nodes(sc):
    topo = sc.topo
    out = []
    real = sc.cfg["scenario"]["kind"] == "real"
    for i in range(topo.n_sats):
        out.append({"node_id": i, "kind": "sat", "sid": int(topo.sat_sid[i]),
                    "norad": int(topo.sat_norad[i]) if real else None, "name": topo.sat_name[i],
                    "lat": None, "lon": None})
    for j, gs in enumerate(topo.stations):
        out.append({"node_id": topo.n_sats + j, "kind": "gs", "sid": int(topo.gs_sid[j]), "norad": None,
                    "name": gs.name, "lat": gs.lat_deg, "lon": gs.lon_deg})
    return out


def _positions(sc):
    if sc.cfg["scenario"]["kind"] == "real":
        rel = Path(sc.snapshot_dir)
        try:
            rel = rel.resolve().relative_to(provenance.REPO_ROOT)
        except ValueError:
            pass
        return {"source": "snapshot", "path": (rel / sc.fleet.source.raw_file).as_posix()}
    return {"source": "snapshot", "path": "synthetic_omm.json"}


def write_schedule(path, rows, flows):
    raw, gz, fh = tw.open_gzip_text(path)
    fh.write("flow_id,src,dst,valid_from_ms,valid_to_ms,path_nodes,sids_fwd,cumulative_budgets_ns,"
             "predicted_hop_delays_ns,tcrh_hex_template\n")
    for fid, start, end, e in sorted(rows, key=lambda r: (r[1], r[0])):
        f = flows[fid]
        if e is None:
            fh.write(f"{fid},{f.src_node},{f.dst_node},{start},{end},,,,,\n")
            continue
        fh.write(f"{fid},{f.src_node},{f.dst_node},{start},{end},{' '.join(map(str, e.path))},"
                 f"{' '.join(map(str, e.sids_fwd))},{' '.join(map(str, e.budgets_ceil_ns))},"
                 f"{' '.join(map(str, e.hop_delays_ns))},{e.template.hex()}\n")
    fh.close()
    gz.close()
    raw.close()


def write_pcap(path, frames):
    from ..trace import pcap as pcapw
    with open(path, "wb") as fh:
        w = pcapw.PcapWriter(fh, pcapw.LINKTYPE_PPP)
        for t_gps, _pkt, packet in sorted(frames, key=lambda f: (f[0], f[1])):
            w.write(packet, t_gps_ns=t_gps)
    return path


def engine_doc(cfg, sc, eng):
    """run.json "engine": what the run was, including its full normalised config (so a viewer
    or a script can re-run it exactly: fwd/rerun.py) and the shared failure-detection delay."""
    out = cfg["output"]
    return {"version": __version__, "seed": cfg["seed"], "config_sha256": provenance.config_sha256(cfg),
            "shell": sc.topo.shell.shell_id, "step_ns": sc.step_ns, "duration_ns": sc.duration_ns,
            "end_ns": sc.end_ns, "drain_ns": sc.drain_ns, "processing_ns": cfg["forwarding"]["processing_ns"],
            "link_rate_bps": cfg["forwarding"]["link_rate_bps"],
            "l2_overhead_bytes": cfg["traffic"]["l2_overhead_bytes"],
            "policy": cfg["forwarding"]["policy"], "fallback": cfg["forwarding"]["fallback"],
            "slack": cfg["schedule"]["slack"], "refresh_ms": cfg["schedule"]["refresh_ms"],
            "carrier_detect_ns": eng.carrier_ns,
            "trace_level": out["trace"], "sample_every": out["sample_every"], "config": cfg}


def run_config(cfg, out_dir, *, argv=None, write_manifest=True, run_extra=None):
    """Run one normalised config into out_dir. Returns (summary dict, list of written paths).

    run_extra: further top-level run.json keys (fwd/rerun.py adds "rerun")."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timer = provenance.RunTimer().start()
    sc = build_scenario(cfg)
    out = cfg["output"]
    written = []
    events = tw.EventWriter(out_dir / "events.jsonl.gz") if out["trace"] != "none" else None
    packets = tw.PacketCsvWriter(out_dir / "packets.csv.gz") if out["packets_csv"] else None
    frames = [] if out["pcap"] else None
    try:
        eng = Engine(sc, trace=events, packets_csv=packets, pcap_frames=frames)
        summary = eng.run()
    except BaseException:
        # a failed run (e.g. an invariant violation with output.invariants = all) leaves
        # closed, incomplete files and no manifest: nothing can be mistaken for a result
        for w in (events, packets):
            if w is not None:
                w.abort()
        raise
    if events is not None:
        events.close()
        written.append(out_dir / "events.jsonl.gz")
    if packets is not None:
        packets.close()
        written.append(out_dir / "packets.csv.gz")
    write_schedule(out_dir / "schedule.csv.gz", eng.schedule_rows, sc.flows)
    written.append(out_dir / "schedule.csv.gz")
    if frames is not None:
        written.append(write_pcap(out_dir / "capture.pcap", frames))
    if sc.synthetic_omm is not None:
        (out_dir / "synthetic_omm.json").write_bytes(sc.synthetic_omm)
        written.append(out_dir / "synthetic_omm.json")
    labels = run_labels(cfg)
    flows_doc = [{"flow_id": f.flow_id, "src": f.src, "dst": f.dst, "src_node": f.src_node,
                  "dst_node": f.dst_node, "rate_pps": str(f.rate_pps), "model": f.model,
                  "payload_bytes": f.payload_bytes, "great_circle_km": round(f.great_circle_km, 3)}
                 for f in sc.flows]
    extra = {"engine": engine_doc(cfg, sc, eng), "flows": flows_doc}
    extra.update(run_extra or {})
    doc = tw.run_json(
        tool=TOOL, t0_utc=omm.format_utc_ns(sc.t0_ns), t0_gps_ns=sc.t0_gps_ns,
        unit_code=cfg["schedule"]["unit_code"],
        snapshot_id=sc.fleet.snapshot_id, bundle=None, nodes=_nodes(sc), positions=_positions(sc),
        faults=eng.faults.log, labels=labels, extra=extra)
    tw.write_run_json(out_dir / "run.json", doc)
    written.append(out_dir / "run.json")
    summary["scenario"] = {"kind": cfg["scenario"]["kind"], "shell": sc.topo.shell.shell_id,
                           "satellites": sc.topo.n_sats, "ground_stations": sc.topo.n_gs,
                           "isl_links": sc.topo.n_isl, "gsl_links": sc.topo.n_links - sc.topo.n_isl,
                           "off_grid_left_out": sc.topo.excluded_off_grid, "steps": sc.n_steps,
                           "flows": len(sc.flows), "science_pairs": sc.pairs_report}
    summary["labels"] = labels
    summary["wall_seconds_total"] = round(timer.wall_seconds, 3)
    # end to end: every hop event over the whole command (scenario build, planning, topology,
    # forwarding and writing the outputs) - what a user waits for; the forwarding-only rate
    # (hop_events_per_s_forwarding) is the engine's own speed
    summary["hop_events_per_s_end_to_end"] = (round(summary["counts"]["hop_events"] / timer.wall_seconds, 1)
                                              if timer.wall_seconds > 0 else None)
    tw.write_json(out_dir / "summary.json", summary)
    written.append(out_dir / "summary.json")
    timer.stop()
    if write_manifest:
        if sc.snapshot_dir is not None:
            snap = sc.snapshot_dir
        else:
            snap = {"id": sc.fleet.snapshot_id, "sha256": hashlib.sha256(sc.synthetic_omm).hexdigest(),
                    "sha256_of": "synthetic_omm.json"}
        manifest = provenance.write_manifest(
            out_dir, tool="cr run", tool_version=__version__, command=argv or ["cr", "run"], config=cfg,
            seeds=[cfg["seed"]], snapshot=snap, outputs=written, labels=labels,
            extra={"trace_schema": tw.SCHEMA, "counts": summary["counts"],
                   "conservation_ok": summary["conservation"]["ok"],
                   "invariant_violations": summary["invariants"]["violations"],
                   "hop_events_per_s_forwarding": summary["hop_events_per_s_forwarding"],
                   "peak_rss_mb": summary["peak_rss_mb"]},
            timer=timer)
        written.append(manifest)
    return summary, written


def _run(args):
    try:
        cfg = config_mod.load_config(args.config, seed=args.seed)
    except (config_mod.ConfigError, OSError) as exc:
        print(f"cr run: {exc}", file=sys.stderr)
        return 2
    summary, written = run_config(cfg, args.out, argv=["cr"] + list(args.argv))
    c = summary["counts"]
    print(f"cr run: {c['sent']} packets sent, {c['delivered']} delivered, {c['dropped']} dropped, "
          f"{c['no_route']} without a route, {c['unfinished']} unfinished; {c['late']} flagged late; "
          f"{c['hop_events']} hop events")
    if summary["drops"]:
        print("cr run: drops by reason: " + ", ".join(f"{k} {v}" for k, v in summary["drops"].items()))
    print(f"cr run: conservation {'ok' if summary['conservation']['ok'] else 'BROKEN'}, "
          f"invariant violations {summary['invariants']['violations']} "
          f"({summary['invariants']['checked_packets']} packets checked)")
    print(f"cr run: forwarding {summary['hop_events_per_s_forwarding']} hop events/s (forwarding only), "
          f"{summary['hop_events_per_s_end_to_end']} hop events/s end to end; "
          f"loop {summary['timing_s']['loop']} s (planning {summary['timing_s']['plan']} s), "
          f"total {summary['wall_seconds_total']} s, peak RSS {summary['peak_rss_mb']} MB")
    print(f"cr run: wrote {len(written)} files to {args.out}")
    ok = summary["conservation"]["ok"] and summary["invariants"]["violations"] == 0
    return 0 if ok else 1


def register(registry):
    """ (the group itself takes the arguments)."""
    registry.group("run", help="run the ChronoRoute simulator v2 (see docs/sim-config.md)")
    parser = registry.group_parser("run")
    parser.set_defaults(func=_run)
    _add_args(parser)


def _add_args(parser):
    parser.add_argument("--config", required=True, help="run configuration (YAML subset or JSON), "
                                                         "see docs/sim-config.md")
    parser.add_argument("--seed", type=int, default=None, help="seed (overrides the config's seed)")
    parser.add_argument("--out", required=True, help="output folder (created)")


__all__ = ["TOOL", "PENDING_LABELS", "run_labels", "run_config", "register"]

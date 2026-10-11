"""
run.py
------
Run ONE scheme on one scenario into a result folder. The folder is a normal
`cr run` folder (spec/trace-v1.md) plus the baseline extras:

    run.json              trace/1 run description; extra key "scheme" (name, label, settings)
    events.jsonl.gz       trace/1 events (for table schemes sl/flags/hex are null: no routing header)
    packets.csv.gz        the engine's per-packet rows (outcome, reason, path, DEV, clocks)
    scheme_packets.csv.gz per packet: arrival time (ns) at every node, light time of every hop,
                          routing-header bytes, deterministic latency L_det, the send-time oracle
                          L*, its hop count and the stretch tolerance, LQ / E2E flags
    scheme_events.csv.gz  control-plane detections (LS-H adjacency down, LS-D metric updates)
    schedule.csv.gz       planned rows (crh data plane schemes; empty otherwise)
    control.json          control bytes per medium and message type, satellite state, scheme stats
    summary.json          the engine summary plus the scheme block
    manifest.json         provenance (config = {"run": engine config, "scheme": scheme settings})

A run file is the engine's config (docs/sim-config.md) with one extra
top-level block `scheme:` (docs/baselines.md); `split_run_document` takes it
apart so that the engine's own checks still refuse any unknown key.
"""

import copy
import hashlib
import json
from pathlib import Path

from .. import __version__, labels as labels_mod, provenance
from ..data import omm
from ..fwd import command as fwd_command, config as config_mod
from ..fwd.scenario import build_scenario
from ..trace import writer as tw
from .engine import EXTRAS_COLUMNS, SchemeEngine
from .params import normalise_scheme, scheme_label

TOOL = "python-sim"

# Labels the baseline outputs need that the shared table (labels.py) does not have yet;
# used only while a key is missing there (request to the labels owner), the table wins.
PENDING_LABELS = {
    "baseline_control_plane_models": "MODELLED",
    "control_byte_models": "MODELLED",
    "feedback_model": "MODELLED",
    # how a node learns that its link failed (one carrier-detection model for every scheme,
    # run.json scheme.failure_visibility says which and whether the run is like-for-like)
    "failure_detection_model": "MODELLED",
}


def _label(key):
    if key in labels_mod.TABLE:
        return labels_mod.TABLE[key]
    if key in PENDING_LABELS:
        return PENDING_LABELS[key]
    return fwd_command._label(key)


def scheme_labels(cfg, scheme):
    out = fwd_command.run_labels(cfg)
    keys = ["control_byte_models", "failure_detection_model"]
    if scheme["name"] not in ("chronoroute",):
        keys.insert(0, "baseline_control_plane_models")
    if scheme["name"] == "e2e" or (scheme["name"] == "chronoroute" and scheme["feedback"]["mode"] == "fb1"):
        keys.append("feedback_model")
    for k in keys:
        out[k] = _label(k)
    return out


class ExtrasWriter(tw.PacketCsvWriter):
    COLUMNS = EXTRAS_COLUMNS


def split_run_document(doc):
    """(engine document, scheme document) from a run file's mapping."""
    if not isinstance(doc, dict):
        raise config_mod.ConfigError("a run file must hold a mapping")
    doc = copy.deepcopy(doc)
    scheme = doc.pop("scheme", "chronoroute")
    return doc, scheme


def load_run_file(path, *, seed=None, scheme_override=None):
    """(engine config, scheme settings) from a run file (YAML subset or JSON)."""
    doc = config_mod.load_document(path)
    eng_doc, sch_doc = split_run_document(doc)
    if scheme_override is not None:
        sch_doc = scheme_override
    return config_mod.normalise(eng_doc, seed=seed), normalise_scheme(sch_doc)


def write_scheme_events(path, detections):
    raw, gz, fh = tw.open_gzip_text(path)
    fh.write("t_ns,kind,a,b,end,value\n")
    for d in detections:
        val = d[5] if len(d) > 5 else ""
        fh.write(f"{d[0]},{d[1]},{d[2]},{d[3]},{d[4]},{val}\n")
    fh.close()
    gz.close()
    raw.close()


def run_scheme(cfg, scheme, out_dir, *, argv=None, write_manifest=True, run_extra=None):
    """Run one scheme. Returns (summary, written paths). cfg and scheme are normalised dicts.
    run_extra: further top-level run.json keys (fwd/rerun.py adds "rerun")."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timer = provenance.RunTimer().start()
    sc = build_scenario(cfg)
    out = cfg["output"]
    written = []
    events = tw.EventWriter(out_dir / "events.jsonl.gz") if out["trace"] != "none" else None
    packets = tw.PacketCsvWriter(out_dir / "packets.csv.gz") if out["packets_csv"] else None
    extras = ExtrasWriter(out_dir / "scheme_packets.csv.gz")
    # the pcap writer shows T-CRH bytes; only the chronoroute scheme really carries them
    frames = [] if (out["pcap"] and scheme["name"] == "chronoroute") else None
    try:
        eng = SchemeEngine(sc, scheme, trace=events, packets_csv=packets, pcap_frames=frames, extras=extras)
        summary = eng.run()
        eng.finish_control()
    except BaseException:
        for w in (events, packets, extras):
            if w is not None:
                w.abort()
        raise
    for w, name in ((events, "events.jsonl.gz"), (packets, "packets.csv.gz"), (extras, "scheme_packets.csv.gz")):
        if w is not None:
            w.close()
            written.append(out_dir / name)
    fwd_command.write_schedule(out_dir / "schedule.csv.gz", eng.schedule_rows, sc.flows)
    written.append(out_dir / "schedule.csv.gz")
    write_scheme_events(out_dir / "scheme_events.csv.gz", eng.detections())
    written.append(out_dir / "scheme_events.csv.gz")
    if frames is not None:
        written.append(fwd_command.write_pcap(out_dir / "capture.pcap", frames))
    if sc.synthetic_omm is not None:
        (out_dir / "synthetic_omm.json").write_bytes(sc.synthetic_omm)
        written.append(out_dir / "synthetic_omm.json")
    labels = scheme_labels(cfg, scheme)
    control = eng.control_report()
    control["scheme_label"] = scheme_label(scheme)
    tw.write_json(out_dir / "control.json", control)
    written.append(out_dir / "control.json")
    flows_doc = [{"flow_id": f.flow_id, "src": f.src, "dst": f.dst, "src_node": f.src_node,
                  "dst_node": f.dst_node, "rate_pps": str(f.rate_pps), "model": f.model,
                  "payload_bytes": f.payload_bytes, "great_circle_km": round(f.great_circle_km, 3)}
                 for f in sc.flows]
    scheme_doc = {"name": scheme["name"], "label": scheme_label(scheme), "settings": scheme,
                  "data_plane": eng.plane, "header_on_wire": eng.hdr_kind,
                  "trace_hex_is_internal_tcrh": eng.plane == "crh" and scheme["name"] != "chronoroute",
                  "step_tolerance_ns": eng.step_tol, "failure_visibility": eng.failure_visibility()}
    extra = {"engine": fwd_command.engine_doc(cfg, sc, eng), "flows": flows_doc, "scheme": scheme_doc}
    extra.update(run_extra or {})
    doc = tw.run_json(
        tool=TOOL, t0_utc=omm.format_utc_ns(sc.t0_ns), t0_gps_ns=sc.t0_gps_ns,
        unit_code=cfg["schedule"]["unit_code"], snapshot_id=sc.fleet.snapshot_id, bundle=None,
        nodes=fwd_command._nodes(sc), positions=fwd_command._positions(sc), faults=eng.real_faults.log,
        labels=labels, extra=extra)
    tw.write_run_json(out_dir / "run.json", doc)
    written.append(out_dir / "run.json")
    summary["scheme"] = {"name": scheme["name"], "label": scheme_label(scheme),
                         "control_bytes": control["ledger"]["by_medium"]}
    if control.get("crh_state_uploads", {}).get("counted"):
        summary["scheme"]["crh_state_steady_bytes_per_s"] = control["crh_state_uploads"]["steady_state_bytes_per_s"]
    summary["scenario"] = {"kind": cfg["scenario"]["kind"], "shell": sc.topo.shell.shell_id,
                           "satellites": sc.topo.n_sats, "ground_stations": sc.topo.n_gs,
                           "isl_links": sc.topo.n_isl, "gsl_links": sc.topo.n_links - sc.topo.n_isl,
                           "steps": sc.n_steps, "flows": len(sc.flows)}
    summary["labels"] = labels
    summary["wall_seconds_total"] = round(timer.wall_seconds, 3)
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
            out_dir, tool="cr eval scheme", tool_version=__version__, command=argv or ["cr", "eval", "scheme"],
            config={"run": cfg, "scheme": scheme}, seeds=[cfg["seed"]], snapshot=snap, outputs=written,
            labels=labels,
            extra={"trace_schema": tw.SCHEMA, "scheme": scheme_label(scheme), "counts": summary["counts"],
                   "conservation_ok": summary["conservation"]["ok"],
                   "invariant_violations": summary["invariants"]["violations"],
                   "control_bytes_total": control["ledger"]["total_bytes"]},
            timer=timer)
        written.append(manifest)
    return summary, written


def scheme_config_json(cfg, scheme):
    """Canonical JSON of what a run used (handy for result tables)."""
    return json.dumps({"run": cfg, "scheme": scheme}, sort_keys=True)


__all__ = ["TOOL", "PENDING_LABELS", "scheme_labels", "split_run_document", "load_run_file", "run_scheme",
           "scheme_config_json"]

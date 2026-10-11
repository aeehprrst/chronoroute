"""Extract one real ns-3 probe, hop by hop, for the website's Network Simulation page.

    venv/bin/python -B tools/network_walk.py --out results/network-walk/<UTC stamp>

Reads the committed course-milestone run (default results/course-milestone/c5-463-10s-small-seed1),
converts its fault and no-fault ns-3 runs to chronoroute.trace/1 with `cr trace from-ns3` (which
rebuilds the scenario bundle from its recorded recipe and checks every byte against the run
manifest), and writes walk.json:

* the first probe of flow 0 that a node flagged late (DEV) in the fault run, every hop of it:
  node, SID, Segments Left and Flags on arrival, the header bytes as they arrived, the node's
  unit clock and the deadline it checked;
* the same probe (same flow and send time) in the paired no-fault run;
* where the path's nodes were (latitude/longitude on a sphere, for drawing only) at the send time;
* the run's own detection totals (detection.json).

Nothing is computed here that the ns-3 run did not record, apart from unit conversions and the
drawing coordinates. The trace conversion runs in a scratch folder outside the repository.
"""
import argparse
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "sim"))

from chronoroute import __version__, labels, provenance  # noqa: E402
from chronoroute.trace.writer import write_json  # noqa: E402

UNIT_NS = {0: 1_000_000, 1: 100_000, 2: 250_000, 3: 125_000}


def convert(run, variant, out, bundle_args, hex_every=0):
    cmd = [sys.executable, "-B", "-m", "chronoroute.cli", "trace", "from-ns3", str(run), "--variant", variant,
           "--out", str(out), "--hex-every", str(hex_every), "--hex-late", "10", "--hex-first", "1", *bundle_args]
    subprocess.run(cmd, check=True, cwd=REPO, stdout=subprocess.DEVNULL)
    return cmd


def load(trace):
    run = json.loads((trace / "run.json").read_text())
    import gzip
    with gzip.open(trace / "events.jsonl.gz", "rt") as fh:
        events = [json.loads(line) for line in fh]
    return run, events


def probe_events(events, pkt):
    return [e for e in events if e["pkt"] == pkt]


def latlon(x, y, z):
    r = math.sqrt(x * x + y * y + z * z)
    return round(math.degrees(math.asin(z / r)), 4), round(math.degrees(math.atan2(y, x)), 4)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=Path, default=REPO / "results/course-milestone/c5-463-10s-small-seed1")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    state = provenance.git_state(REPO)
    if state["dirty"] is not False:
        raise SystemExit("commit the code first: the manifest must record a clean tree")
    run_dir = args.run.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    commands = []
    with provenance.RunTimer() as timer, tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
        tmp = Path(tmp)
        commands.append(convert(run_dir, "fault", tmp / "fault", ["--rebuild-bundle", str(tmp / "bundle")]))
        # every probe keeps its bytes in the no-fault run, so the chosen probe twin has them too
        commands.append(convert(run_dir, "nofault", tmp / "nofault", ["--bundle", str(tmp / "bundle")], hex_every=1))
        frun, fev = load(tmp / "fault")
        nrun, nev = load(tmp / "nofault")
        unit_ns = UNIT_NS[int(frun["unit_code"])]
        nodes = {n["node_id"]: n for n in frun["nodes"]}

        late = next(e for e in fev if e["ev"] == "late" and e["flow"] == 0)
        f_events = probe_events(fev, late["pkt"])
        send = next(e for e in f_events if e["ev"] == "send")
        twin_send = next(e for e in nev if e["ev"] == "send" and e["flow"] == send["flow"] and e["t"] == send["t"])
        n_events = probe_events(nev, twin_send["pkt"])
        if not all(e.get("hex") for e in f_events + n_events):
            raise SystemExit("header bytes were not kept for the chosen probe or its twin")
        epoch_base = int(bytes.fromhex(send["hex"])[8:12].hex(), 16)

        def hops(evs):
            rows = []
            for e in evs:
                if e["ev"] not in ("send", "hop"):
                    continue
                rows.append({
                    "node_id": e["node"], "t_ns": e["t"], "sl": e["sl"], "flags": e["flags"],
                    "now_u": e["now_u"], "deadline_u": e["deadline_u"],
                    "elapsed_ms": round((e["now_u"] - epoch_base) * unit_ns / 1e6, 4),
                    "deadline_ms": None if e["deadline_u"] is None else round((e["deadline_u"] - epoch_base) * unit_ns / 1e6, 4),
                    "margin_ms": None if e["deadline_u"] is None else round((e["deadline_u"] - e["now_u"]) * unit_ns / 1e6, 4),
                    "hex": e.get("hex"),
                })
            ends = [e for e in evs if e["ev"] in ("deliver", "drop")]
            lates = [e for e in evs if e["ev"] == "late"]
            return rows, (ends[0]["ev"] if ends else "unfinished"), (lates[0]["node"] if lates else None)

        f_hops, f_end, f_late = hops(f_events)
        n_hops, n_end, n_late = hops(n_events)
        if [h["node_id"] for h in f_hops] != [h["node_id"] for h in n_hops]:
            raise SystemExit("the paired probes took different paths")

        # Drawing coordinates at the send time (bundle positions, nearest sample at or before it).
        import csv
        bundle = tmp / "bundle"
        t_ms = send["t"] // 1_000_000
        want = {h["node_id"] for h in f_hops}
        best = {}
        with open(bundle / "positions.csv", newline="") as fh:
            for r in csv.DictReader(fh):
                nid, tm = int(r["node_id"]), int(r["t_ms"])
                if nid in want and tm <= t_ms and (nid not in best or tm > best[nid][0]):
                    best[nid] = (tm, float(r["x_m"]), float(r["y_m"]), float(r["z_m"]))
        path = []
        for k, h in enumerate(f_hops):
            n = nodes[h["node_id"]]
            if n["kind"] == "gs":
                lat, lon = n["lat"], n["lon"]
            else:
                lat, lon = latlon(*best[h["node_id"]][1:])
            path.append({"hop": k, "node_id": n["node_id"], "kind": n["kind"], "name": n["name"], "sid": n["sid"],
                         "norad": n["norad"], "lat": lat, "lon": lon})

        detection = json.loads((run_dir / "detection.json").read_text())
        fault = frun["faults"][0]
        walk = {
            "schema": "chronoroute.network-walk/1",
            "run": str(run_dir.relative_to(REPO)),
            "t0_utc": frun["t0_utc"], "unit_ns": unit_ns, "epoch_base": epoch_base,
            "flow": {"id": send["flow"], "src": path[0]["name"], "dst": path[-1]["name"]},
            "send_t_ns": send["t"],
            "fault": {"kind": fault["kind"], "names": fault["params"]["names"], "rate_bps": fault["params"]["rate_bps"],
                      "nominal_rate_bps": fault["params"]["nominal_rate_bps"], "start_ns": fault["start_ns"],
                      "stop_ns": fault["stop_ns"], "link_state": fault["params"]["link_state"], "label": fault["params"]["label"]},
            "path": path,
            "fault_run": {"pkt": late["pkt"], "outcome": f_end, "late_node": f_late, "hops": f_hops},
            "nofault_run": {"pkt": twin_send["pkt"], "outcome": n_end, "late_node": n_late, "hops": n_hops},
            "detection": {k: detection[k] for k in ("probes_crossing_slowed_link", "flagged_late", "detection_rate",
                                                    "baseline_same_probes_crossed_no_fault", "baseline_flagged",
                                                    "false_alarms_no_fault_run_all_probes", "first_detection_after_fault_start_ms")},
            "labels": {"positions": "REAL (SGP4 on CelesTrak elements; drawn on a sphere)", "laser_links": "MODELLED (Grid-4)",
                       "fault": "MODELLED", "header_bytes": "REAL (encoder output carried in ns-3)", "timing": "MODELLED (ns-3 links and queues)"},
        }
        write_json(out / "walk.json", walk)
    inputs = [run_dir / "manifest.json", run_dir / "detection.json", run_dir / "fault/packets.csv.gz", run_dir / "nofault/packets.csv.gz"]
    provenance.write_manifest(
        out, tool="tools/network_walk.py", tool_version=__version__,
        command=[sys.executable, "-B", "tools/network_walk.py", *(argv or sys.argv[1:])],
        config={"run": str(run_dir.relative_to(REPO)), "flow": 0, "pick": "first probe of flow 0 flagged late"},
        seeds=[], snapshot=REPO / "data/pinned/20261010T1358Z-celestrak", outputs=[out / "walk.json"],
        labels=labels.pick("satellite_positions_sgp4", "isl_topology_grid4", "tcrh_header_bytes"),
        extra={"inputs": {str(p.relative_to(REPO)): provenance.file_sha256(p) for p in inputs},
               "conversion_commands": [[str(c) for c in cmd[3:]] for cmd in commands]},
        timer=timer)
    provenance.validate_manifest(out / "manifest.json")
    print(f"network_walk: probe {late['pkt']} of flow 0, {len(f_hops)} nodes, late at node {f_late}; wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

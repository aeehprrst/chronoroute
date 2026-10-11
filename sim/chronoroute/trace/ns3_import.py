"""
ns3_import.py
-------------
`cr trace from-ns3 RUN_DIR --out DIR`: turn one ns-3 course-milestone run
(results/course-milestone/<run>/, docs/course-milestone.md) into a
chronoroute.trace/1 run folder (spec/trace-v1.md), so the viewer, the website
replay and any trace tool can show what ns-3 really did.

What goes in:
  RUN_DIR/manifest.json            the bundle used (path + sha256 of every bundle file)
  RUN_DIR/<variant>/packets.csv.gz one row per probe: path, per-hop arrival time,
                                   unit clock, deadline, margin, DEV, outcome
  RUN_DIR/<variant>/run_info.json  t0, unit code, the deviation policy really applied
  RUN_DIR/<variant>/fault_log.csv  the fault as applied (ground truth)
  the scenario bundle              nodes.csv, scenario.json, schedule.csv, positions.csv

What comes out (DIR):
  run.json, events.jsonl.gz        the trace
  bundle/                          byte-identical copies of the bundle's positions.csv,
                                   nodes.csv, isl.csv and scenario.json: run.json's
                                   positions = {"source": "bundle", "path": "bundle"}
                                   (spec/trace-v1.md 1.2: a bundle directory, here relative
                                   to the run folder), so the trace does not depend on a
                                   /tmp bundle; run.json "bundle" keeps the original path
  manifest.json                    provenance (write_manifest)

Packet ids: pkt = the ns-3 probe uid, checked to be the rank of (send time, flow id)
as the spec requires.

Nothing is invented. Times, paths, clocks, deadlines, margins, DEV and outcomes are
copied from packets.csv. The only thing ns-3 does not write per hop is the header
bytes, and those are REBUILT, not guessed: the schedule row's T-CRH template
(schedule.csv, the bytes the ns-3 source shim inserted; ns-3 checked them byte for
byte against Python), Epoch_Base from the row, then the golden-tested reference
(proto.ingress_send / proto.process_at_node, under the run's effective policy) at
every hop with the unit clock ns-3 recorded. Every value the rebuild produces that
packets.csv also has is compared, and the import stops at the first difference:
  * Epoch_Base = ceil((t0_gps + send) / u) mod 2^32;
  * the node clock = floor((t0_gps + t_arrival) / u) mod 2^32 at every hop;
  * the deadline the header gives at hop k = hop_deadline_u[k], and the margin;
  * the next SID maps to the next node of the taken path;
  * DEV is set exactly at first_late_hop, and the final DEV / Dev Hop equal the row's;
  * a delivered packet's latency = rx - send = latency_ns.

Event conventions (one packet; k = hop index). They are the python-sim engine's
(fwd/engine.py, the producer spec/trace-v1.md documents), so both tools' traces
read the same way:
  send     t = send time at the source city; sl/flags/hex = the header as it leaves
           the source (after ingress_send, SL = h - 1); now_u = source clock;
           deadline_u = null; next = the first hop.
  hop      the packet ARRIVED at `node` at t: sl/flags/hex = the header AS IT ARRIVED
           (before this node's processing, so SL = h - k at hop k); deadline_u =
           D_k checked there; now_u = the node's clock on arrival; next = the next
           node (null at the destination).
  late     same t and node as the hop: this node's deadline check set DEV; sl/flags/hex
           = the header after processing (DEV set); next, reason = null. At most one
           per packet (DEV is set once).
  deliver  at the destination city, t = rx time; sl/flags/hex = the final header;
           deadline_u / now_u = those of the last hop.
  drop     reason = the ns-3 outcome (drop_queue, drop_link_down, drop_iface_down),
           at the node and time ns-3 reports; sl/flags/hex = the header held there.
  hex is written only for sampled packets, on EVERY event of such a packet (the bytes
  rule of spec/trace-v1.md 4, which reader.validate_run checks): every --hex-every'th probe id, the first
  --hex-first probes of every flow and the first --hex-late late probes of every
  flow (so the HUD can show the bytes of the packets the viewer plays first).
No "fallback" events: these runs use the deviation policy 'continue' (run_info.json
effective_policy), so a late packet keeps its path; the importer refuses any other
policy rather than guess what ns-3 did.

Events are sorted by (t, pkt); a packet's own events at one instant keep the order
above (hop, late, deliver).
"""

import csv
import gzip
import hashlib
import json
import shutil
import sys
from fractions import Fraction
from pathlib import Path

from .. import __version__
from .. import provenance
from ..export import ns3_crosscheck as xc
from ..proto import tcrh as tcrh_mod
from ..proto import timebase

SCHEMA = "chronoroute.trace/1"
VARIANTS = ("fault", "nofault", "anim")
DEFAULT_HEX_EVERY = 100
DEFAULT_HEX_LATE = 10
DEFAULT_HEX_FIRST = 10
EVENT_KEYS = ("t", "ev", "pkt", "flow", "node", "next", "sl", "flags", "deadline_u", "now_u",
              "reason", "hex")
DROP_OUTCOMES = ("drop_queue", "drop_link_down", "drop_iface_down")
BUNDLE_COPY = "bundle"
BUNDLE_COPY_FILES = ("positions.csv", "nodes.csv", "isl.csv", "scenario.json")


class ImportCheckError(ValueError):
    """A value rebuilt from the bundle disagrees with what ns-3 recorded."""


class BundleMissing(FileNotFoundError):
    """The run's bundle is not on disk (or not byte-identical); the message says how to rebuild it."""


# ----------------------------------------------------------------------- inputs

def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_run_manifest(run_dir):
    path = Path(run_dir) / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found: RUN_DIR must be a course-milestone result folder")
    return json.loads(path.read_text(encoding="utf-8"))


def bundle_problems(bundle_dir, expected_sha):
    """[] when every file listed in the run manifest has the recorded sha256, else what differs."""
    bundle_dir = Path(bundle_dir)
    out = []
    for name, sha in sorted(expected_sha.items()):
        path = bundle_dir / name
        if not path.is_file():
            out.append(f"{name} missing")
        elif _sha256(path) != sha:
            out.append(f"{name} sha256 differs")
    return out


def rebuild_command(manifest, out_dir):
    """The run's own `cr export bundle` command, writing to out_dir instead."""
    cmd = list(manifest["config"]["bundle_command"])
    if cmd[:1] == ["cr"]:
        cmd = cmd[1:]
    i = cmd.index("--out")
    cmd[i + 1] = str(out_dir)
    return cmd


def find_bundle(run_dir, bundle=None):
    """The run's bundle folder, verified file by file against the run manifest's sha256."""
    manifest = read_run_manifest(run_dir)
    expected = manifest["config"].get("bundle_data_sha256") or {}
    if not expected:
        raise ValueError(f"{run_dir}/manifest.json has no bundle_data_sha256 to verify a bundle against")
    candidate = Path(bundle) if bundle else Path(manifest["config"]["bundle"])
    problems = bundle_problems(candidate, expected)
    if problems:
        cmd = " ".join(["cr", *rebuild_command(manifest, candidate)])
        raise BundleMissing(
            f"bundle {candidate} is not the one this run used ({', '.join(problems)}). "
            f"Rebuild it from its recipe (deterministic, byte-identical):\n  {cmd}\n"
            f"or pass --rebuild-bundle DIR to let this command do it.")
    return candidate


def rebuild_bundle(run_dir, out_dir):
    """Re-run the run's recorded `cr export bundle` command into out_dir and verify the sha256s."""
    from .. import cli
    manifest = read_run_manifest(run_dir)
    code = cli.main(rebuild_command(manifest, out_dir))
    if code != 0:
        raise RuntimeError(f"cr export bundle exited with {code}")
    problems = bundle_problems(out_dir, manifest["config"]["bundle_data_sha256"])
    if problems:
        raise RuntimeError(f"rebuilt bundle {out_dir} differs from the run's: {', '.join(problems)}")
    return Path(out_dir)


def read_bundle_nodes(bundle_dir):
    """nodes.csv -> list of trace node dicts (spec/trace-v1.md run.json 'nodes')."""
    out = []
    with open(Path(bundle_dir) / "nodes.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sat = r["kind"] == "sat"
            out.append({"node_id": int(r["node_id"]), "kind": r["kind"], "sid": int(r["sid"]),
                        "norad": int(r["norad"]) if sat else None, "name": r["name"],
                        "lat": None if sat else float(r["lat"]),
                        "lon": None if sat else float(r["lon"])})
    return out


def read_schedule_templates(bundle_dir):
    """(flow_id, valid_from_ms) -> T-CRH template bytes, from schedule.csv."""
    out = {}
    with open(Path(bundle_dir) / "schedule.csv", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[(int(r["flow_id"]), int(r["valid_from_ms"]))] = bytes.fromhex(r["tcrh_hex_template"])
    return out


def parse_rate_bps(text):
    """'1Gbps' / '200kbps' / '1000000' -> integer bits per second."""
    text = str(text).strip()
    for suffix, mult in (("Gbps", 10 ** 9), ("Mbps", 10 ** 6), ("kbps", 10 ** 3), ("bps", 1)):
        if text.endswith(suffix):
            return int(round(float(text[: -len(suffix)]) * mult))
    return int(text)


def read_faults(fault_log, nominal_rate_bps):
    """fault_log.csv -> trace faults (one per slow_start/slow_end pair)."""
    out, open_ = [], {}
    with open(fault_log, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            key = int(r["isl_id"])
            if r["event"] == "slow_start":
                open_[key] = r
            elif r["event"] == "slow_end":
                start = open_.pop(key, None)
                if start is None:
                    raise ValueError(f"{fault_log}: slow_end without slow_start for ISL {key}")
                a, b = sorted((int(start["node_a"]), int(start["node_b"])))   # spec: a < b
                rate = int(start["data_rate_bps"])
                out.append({
                    "kind": "rate_cut", "link": [a, b],
                    "node": None, "start_ns": int(start["t_ns"]), "stop_ns": int(r["t_ns"]),
                    # factor as an exact fraction string, as python-sim writes it
                    "params": {"factor": str(Fraction(rate, int(nominal_rate_bps))),
                               "rate_bps": rate, "nominal_rate_bps": int(nominal_rate_bps),
                               "extra_delay_ns": int(start["extra_delay_ns"]),
                               "isl_id": key, "link_state": "up",
                               "names": [start["name_a"], start["name_b"]],
                               "label": start["label"]}})
            else:
                raise ValueError(f"{fault_log}: unknown event {r['event']!r}")
    if open_:
        raise ValueError(f"{fault_log}: slow_start without slow_end for ISL {sorted(open_)}")
    return out


# ----------------------------------------------------------------------- conversion

def _check(cond, packet, message):
    if not cond:
        raise ImportCheckError(f"probe uid={packet['uid']} (flow {packet['flow_id']}, seq "
                               f"{packet['seq']}): {message}")


def _event(t, ev, pkt, flow, node, *, nxt=None, sl=None, flags=None, deadline_u=None,
           now_u=None, reason=None, hexs=None):
    return {"t": t, "ev": ev, "pkt": pkt, "flow": flow, "node": node, "next": nxt, "sl": sl,
            "flags": flags, "deadline_u": deadline_u, "now_u": now_u, "reason": reason, "hex": hexs}


def packet_events(p, *, templates, sid_to_node, t0_gps_ns, unit_code, policy, with_hex):
    """The trace events of one packets.csv row (module docstring), with every cross-check."""
    unit = timebase.unit_ns(unit_code)
    pkt, flow = p["uid"], p["flow_id"]
    path = p["taken_path"]
    h = p["num_hops"]
    send = p["send_ns"]
    template = templates.get((flow, p["row_from_ms"]))
    _check(template is not None, p, f"no schedule row for flow {flow} from {p['row_from_ms']} ms")
    epoch = timebase.epoch_base_at_ingress(t0_gps_ns + send, unit_code)
    _check(epoch == p["epoch_base"], p, f"Epoch_Base {p['epoch_base']} != ceil((t0+send)/u) = {epoch}")
    raw = bytearray(template)
    raw[tcrh_mod.OFF_EPOCH_BASE:tcrh_mod.OFF_EPOCH_BASE + 4] = epoch.to_bytes(4, "big")
    hdr = tcrh_mod.TcrhHeader.decode(bytes(raw))
    _check(hdr.num_hops == h, p, f"template has {hdr.num_hops} hops, the row says {h}")
    planned = [sid_to_node.get(s) for s in hdr.sids_fwd]
    _check(planned == p["planned_path"][1:], p, "template SIDs do not map to planned_path")

    out, first_sid = tcrh_mod.ingress_send(bytes(raw))
    _check(len(path) >= 1 and path[0] == p["planned_path"][0], p, "taken path does not start at the source")
    nxt = sid_to_node[first_sid]
    events = [_event(send, "send", pkt, flow, path[0], nxt=nxt, sl=out[3], flags=out[4],
                     now_u=timebase.clock_u(t0_gps_ns + send, unit_code),
                     hexs=out.hex() if with_hex else None)]
    raw = out
    late_at = None
    last_deadline = last_now = None
    n_arrivals = len(p["hop_t_ns"])
    _check(len(path) == n_arrivals + 1, p, f"{len(path)} path nodes but {n_arrivals} arrival times")
    for k in range(1, n_arrivals + 1):
        t = p["hop_t_ns"][k - 1]
        node = path[k]
        _check(node == nxt, p, f"hop {k} arrived at node {node}, the header sent it to {nxt}")
        now_u = p["hop_now_u"][k - 1]
        _check(now_u == timebase.clock_u(t0_gps_ns + t, unit_code), p,
               f"hop {k}: clock {now_u} != floor((t0+t)/u)")
        res = tcrh_mod.process_at_node(raw, now_u, policy)
        _check(res.hop_index == k, p, f"hop {k}: header says hop {res.hop_index}")
        _check(res.deadline_u == p["hop_deadline_u"][k - 1], p,
               f"hop {k}: rebuilt deadline {res.deadline_u} != recorded {p['hop_deadline_u'][k - 1]}")
        _check(timebase.serial_diff(res.deadline_u, now_u) == p["hop_margin_u"][k - 1], p,
               f"hop {k}: margin differs")
        if res.action == "deliver":
            nxt = None
        elif res.action == "forward":
            nxt = sid_to_node.get(res.next_sid)
            _check(nxt is not None, p, f"hop {k}: next SID {res.next_sid} is not a node of the bundle")
            if k < len(path) - 1:
                _check(nxt == path[k + 1], p, f"hop {k}: header forwards to {nxt}, path says {path[k + 1]}")
        else:
            raise ImportCheckError(f"probe uid={pkt}: hop {k}: unexpected action {res.action!r} "
                                   f"under policy {policy!r}")
        ob = res.out_bytes
        # hop: the header as it arrived (raw); late: as it leaves, with DEV (module docstring)
        events.append(_event(t, "hop", pkt, flow, node, nxt=nxt, sl=raw[3], flags=raw[4],
                             deadline_u=res.deadline_u, now_u=now_u,
                             hexs=raw.hex() if with_hex else None))
        if res.late:
            late_at = k
            events.append(_event(t, "late", pkt, flow, node, sl=ob[3], flags=ob[4],
                                 deadline_u=res.deadline_u, now_u=now_u,
                                 hexs=ob.hex() if with_hex else None))
        raw = ob
        last_deadline, last_now = res.deadline_u, now_u

    flags = raw[tcrh_mod.OFF_FLAGS]
    dev_hop = raw[tcrh_mod.OFF_DEV_HOP]
    if p["first_late_hop"] is not None or late_at is not None:
        _check(late_at == p["first_late_hop"], p,
               f"DEV set at hop {late_at}, packets.csv first_late_hop = {p['first_late_hop']}")
    outcome = p["outcome"]
    if outcome == "delivered":
        _check(n_arrivals == h and path[-1] == p["outcome_node"], p, "delivered but path incomplete")
        _check(p["rx_ns"] == p["hop_t_ns"][-1] == p["outcome_t_ns"], p, "rx time != last arrival")
        _check(p["latency_ns"] == p["rx_ns"] - send, p, "latency != rx - send")
        _check(int(bool(flags & tcrh_mod.FLAG_DEV)) == p["dev"], p, "final DEV differs")
        _check(dev_hop == p["dev_hop"], p, f"final Dev Hop {dev_hop} != {p['dev_hop']}")
        events.append(_event(p["rx_ns"], "deliver", pkt, flow, path[-1], sl=raw[3], flags=flags,
                             deadline_u=last_deadline, now_u=last_now,
                             hexs=raw.hex() if with_hex else None))
    elif outcome in DROP_OUTCOMES:
        _check(p["outcome_node"] == path[-1], p, "drop node is not the last node reached")
        _check(p["outcome_t_ns"] >= (p["hop_t_ns"][-1] if n_arrivals else send), p,
               "drop before the last arrival")
        if p["dev"] and not flags & tcrh_mod.FLAG_DEV:
            # Link-down discard (spec section 6 step 7): DEV with Dev Hop = the holding node.
            flags |= tcrh_mod.FLAG_DEV
            dev_hop = p["dev_hop"]
            patched = bytearray(raw)
            patched[tcrh_mod.OFF_FLAGS] = flags
            patched[tcrh_mod.OFF_DEV_HOP] = dev_hop
            raw = bytes(patched)
        _check(int(bool(flags & tcrh_mod.FLAG_DEV)) == p["dev"] and dev_hop == p["dev_hop"], p,
               "DEV / Dev Hop of the dropped probe differ")
        events.append(_event(p["outcome_t_ns"], "drop", pkt, flow, p["outcome_node"], sl=raw[3],
                             flags=flags, reason=outcome, hexs=raw.hex() if with_hex else None))
    else:
        raise ImportCheckError(f"probe uid={pkt}: unknown outcome {outcome!r}")
    return events


def _hex_sample(packets, hex_every, hex_late, hex_first=0):
    """Probe ids that carry header bytes (deterministic).

    Every hex_every'th uid, the first hex_first probes of every flow (what the viewer
    shows first) and the first hex_late late probes of every flow.
    """
    chosen = {p["uid"] for p in packets if hex_every and p["uid"] % hex_every == 0}
    first, late = {}, {}
    for p in sorted(packets, key=lambda r: (r["send_ns"], r["uid"])):
        f = p["flow_id"]
        if first.get(f, 0) < hex_first:
            chosen.add(p["uid"])
            first[f] = first.get(f, 0) + 1
        if p["dev"] and late.get(f, 0) < hex_late:
            chosen.add(p["uid"])
            late[f] = late.get(f, 0) + 1
    return chosen


def write_events(path, events):
    """events.jsonl.gz, deterministic: compact JSON in EVENT_KEYS order, gzip mtime 0, no name."""
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=6) as gz:
            for e in events:
                gz.write((json.dumps({k: e[k] for k in EVENT_KEYS}, separators=(",", ":"))
                          + "\n").encode("utf-8"))


def convert(run_dir, out_dir, *, variant="fault", bundle=None, hex_every=DEFAULT_HEX_EVERY,
            hex_late=DEFAULT_HEX_LATE, hex_first=DEFAULT_HEX_FIRST, command=None, timer=None):
    """Convert one variant of a course-milestone run (module docstring). Returns a summary dict."""
    run_dir, out_dir = Path(run_dir), Path(out_dir)
    if variant not in VARIANTS:
        raise ValueError(f"variant must be one of {VARIANTS}")
    vdir = run_dir / variant
    packets_path = vdir / "packets.csv.gz"
    if not packets_path.is_file():
        packets_path = vdir / "packets.csv"
    if not packets_path.is_file():
        raise FileNotFoundError(f"{vdir}: no packets.csv(.gz)")
    run_manifest = read_run_manifest(run_dir)
    bundle_dir = find_bundle(run_dir, bundle)
    run_info = json.loads((vdir / "run_info.json").read_text(encoding="utf-8"))
    scenario = json.loads((bundle_dir / "scenario.json").read_text(encoding="utf-8"))

    t0_gps_ns = int(run_info["t0_gps_ns"])
    unit_code = int(run_info["unit_code"])
    if t0_gps_ns != int(scenario["time"]["t0_gps_ns"]):
        raise ImportCheckError("run_info t0_gps_ns differs from the bundle's scenario.json")
    if unit_code != int(scenario["tcrh"]["unit_code"]):
        raise ImportCheckError("run_info unit_code differs from the bundle's scenario.json")
    policy = run_info.get("effective_policy") or run_info.get("policy")
    if policy != "continue":
        raise ImportCheckError(f"effective_policy {policy!r}: only 'continue' runs can be imported "
                               "(the importer does not guess fallback forwarding)")

    nodes = read_bundle_nodes(bundle_dir)
    sid_to_node = {n["sid"]: n["node_id"] for n in nodes}
    templates = read_schedule_templates(bundle_dir)
    packets = xc.read_packets(packets_path)
    # spec/trace-v1.md: pkt ids 0, 1, 2, ... in order of send time (ties: by flow id)
    ranked = sorted(packets, key=lambda r: (r["send_ns"], r["flow_id"]))
    if any(r["uid"] != i for i, r in enumerate(ranked)):
        raise ImportCheckError("ns-3 probe uids are not the rank of (send time, flow id); "
                               "pkt ids would not follow spec/trace-v1.md")
    sampled = _hex_sample(packets, hex_every, hex_late, hex_first)

    events = []
    for p in packets:
        events.extend(packet_events(p, templates=templates, sid_to_node=sid_to_node,
                                    t0_gps_ns=t0_gps_ns, unit_code=unit_code, policy=policy,
                                    with_hex=p["uid"] in sampled))
    events.sort(key=lambda e: (e["t"], e["pkt"]))       # stable: a packet's own order is kept

    nominal = parse_rate_bps(run_info.get("data_rate", "1Gbps"))
    faults = read_faults(vdir / "fault_log.csv", nominal)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / BUNDLE_COPY).mkdir(exist_ok=True)
    copies = []
    for name in BUNDLE_COPY_FILES:
        shutil.copyfile(bundle_dir / name, out_dir / BUNDLE_COPY / name)
        copies.append(out_dir / BUNDLE_COPY / name)
    run = {
        "schema": SCHEMA,
        "tool": "ns-3",
        "t0_utc": scenario["time"]["t0_utc"],
        "t0_gps_ns": t0_gps_ns,
        "unit_code": unit_code,
        "snapshot_id": scenario["snapshot"]["id"],
        "bundle": str(bundle_dir),
        "nodes": nodes,
        "positions": {"source": "bundle", "path": BUNDLE_COPY},
        "faults": faults,
        "labels": dict(xc.LABELS),
    }
    (out_dir / "run.json").write_text(json.dumps(run, indent=1) + "\n", encoding="utf-8")
    write_events(out_dir / "events.jsonl.gz", events)

    counts = {"probes": len(packets), "events": len(events),
              "delivered": sum(p["outcome"] == "delivered" for p in packets),
              "dropped": sum(p["outcome"] in DROP_OUTCOMES for p in packets),
              "late": sum(1 for e in events if e["ev"] == "late"),
              "hex_sampled_probes": len(sampled),
              "by_event": {ev: sum(1 for e in events if e["ev"] == ev)
                           for ev in ("send", "hop", "late", "fallback", "drop", "deliver")}}
    summary = {"out_dir": str(out_dir), "variant": variant, "bundle": str(bundle_dir),
               "policy": policy, "faults": len(faults), **counts}

    snap_dir = Path(provenance.REPO_ROOT) / "data" / "pinned" / scenario["snapshot"]["id"]
    provenance.write_manifest(
        out_dir, tool="cr-trace-from-ns3", tool_version=__version__,
        command=command or ["cr", "trace", "from-ns3", str(run_dir), "--out", str(out_dir)],
        config={"run_dir": str(run_dir), "variant": variant, "bundle": str(bundle_dir),
                "bundle_data_sha256": run_manifest["config"]["bundle_data_sha256"],
                "packets_sha256": _sha256(packets_path), "hex_every": hex_every,
                "hex_late_per_flow": hex_late, "hex_first_per_flow": hex_first,
                "source_run_id": run_manifest.get("run_id"),
                "source_git_sha": run_manifest.get("git_sha")},
        seeds=[], snapshot=snap_dir if (snap_dir / "SHA256SUMS").is_file() else None,
        outputs=[out_dir / "run.json", out_dir / "events.jsonl.gz", *copies],
        labels=dict(xc.LABELS),
        extra={"counts": counts, "checks": [
            "Epoch_Base = ceil((t0_gps + send) / u) for every probe",
            "node clock = floor((t0_gps + t) / u) at every hop",
            "rebuilt deadline and margin = packets.csv at every hop",
            "next SID maps to the next node of taken_path",
            "DEV set exactly at first_late_hop; final DEV and Dev Hop equal packets.csv",
            "latency = rx - send for every delivered probe",
            "pkt id = rank of (send time, flow id)",
            "bundle/ files are byte-identical copies of the verified bundle"],
            "source_seeds": run_manifest.get("seeds")},
        timer=timer)
    return summary


# ----------------------------------------------------------------------- command

def run_command(args):
    from ..provenance import RunTimer
    bundle = args.bundle
    try:
        if args.rebuild_bundle:
            print(f"rebuilding the run's bundle into {args.rebuild_bundle} ...")
            bundle = str(rebuild_bundle(args.run_dir, args.rebuild_bundle))
        with RunTimer() as timer:
            summary = convert(args.run_dir, args.out, variant=args.variant, bundle=bundle,
                              hex_every=args.hex_every, hex_late=args.hex_late,
                              hex_first=args.hex_first,
                              command=["cr", *getattr(args, "argv", [])], timer=timer)
    except (BundleMissing, ImportCheckError, FileNotFoundError) as exc:
        print(f"cr trace from-ns3: {exc}", file=sys.stderr)
        return 3
    print(f"wrote {summary['out_dir']}  (chronoroute.trace/1, tool ns-3, variant {summary['variant']})")
    print(f"  bundle {summary['bundle']} (sha256 of every file = the run manifest's)")
    print(f"  probes {summary['probes']}: delivered {summary['delivered']}, dropped {summary['dropped']}, "
          f"late (DEV) {summary['late']}; policy {summary['policy']}; faults {summary['faults']}")
    print(f"  events {summary['events']}: " + ", ".join(f"{k} {v}" for k, v in summary["by_event"].items()))
    print(f"  header bytes rebuilt and checked against packets.csv at every hop; "
          f"hex kept for {summary['hex_sampled_probes']} probes")
    return 0


def register_args(parser):
    parser.add_argument("run_dir", help="course-milestone result folder, e.g. "
                        "results/course-milestone/c5-463-10s-small-seed1")
    parser.add_argument("--out", required=True, help="output trace folder")
    parser.add_argument("--variant", choices=VARIANTS, default="fault",
                        help="which ns-3 run of the folder (default fault)")
    parser.add_argument("--bundle", default=None, help="bundle folder (default: the one in the "
                        "run manifest); checked against the manifest's sha256")
    parser.add_argument("--rebuild-bundle", default=None, metavar="DIR",
                        help="first rebuild the run's bundle from its recipe into DIR")
    parser.add_argument("--hex-every", type=int, default=DEFAULT_HEX_EVERY,
                        help="keep header bytes for every N-th probe id (default 100; 0 = none)")
    parser.add_argument("--hex-late", type=int, default=DEFAULT_HEX_LATE,
                        help="also keep them for the first N late probes of each flow (default 10)")
    parser.add_argument("--hex-first", type=int, default=DEFAULT_HEX_FIRST,
                        help="and for the first N probes of each flow (default 10)")


__all__ = ["convert", "find_bundle", "rebuild_bundle", "packet_events", "read_faults",
           "ImportCheckError", "BundleMissing", "run_command", "register_args"]

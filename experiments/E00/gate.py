#!/usr/bin/env python3
"""Preregistered E0 correctness gate. Refuses dirty code and missing checks."""

import argparse
import csv
import gzip
import json
import os
import shutil
import subprocess
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "sim"))
sys.path.insert(0, str(REPO / "tools"))

from chronoroute import __version__, labels, proto, provenance
from chronoroute.data import cities, omm, snapshot
from chronoroute.fwd import presets
from chronoroute.orbit import frames, planes
from chronoroute.orbit.propagate import SatelliteArray
from chronoroute.route import dijkstra, scheduler, sids
from chronoroute.topo import geometry, graph, gsl, isl_grid4
from chronoroute.trace import pcap
from web_parity import _ms_epoch_ecef_km

HERE = Path(__file__).resolve().parent


def load_config(path):
    """Verify the frozen protocol and required E0 coverage before creating output."""
    cfg = json.loads(Path(path).read_text())
    prereg = REPO / cfg["campaign"]["prereg_path"]
    if provenance.file_sha256(prereg) != cfg["campaign"]["prereg_sha256"]:
        raise ValueError("preregistration file hash differs")
    committed = subprocess.check_output(
        ["git", "show", f"{cfg['campaign']['prereg_git_sha']}:experiments/PREREG.md"], cwd=REPO)
    if provenance.sha256_hex(committed) != cfg["campaign"]["prereg_sha256"]:
        raise ValueError("preregistration commit hash differs")
    if cfg["offsets_s"] != list(range(0, 6001, 10)) or cfg["orbit_satellites"] != 200:
        raise ValueError("E0 coverage differs from preregistration")
    if (cfg["snapshot"], cfg["shell"], cfg["start_utc"]) != (
            "data/pinned/20261010T1358Z-celestrak", "53.2deg-463km", "2026-10-10T14:00:00Z"):
        raise ValueError("pinned constellation or start differs from preregistration")
    model = {"walker": presets.WALKER_PRESETS["C2"].as_dict(), "grid": isl_grid4.Grid4Params().as_dict(),
             "gsl": gsl.GslParams().as_dict(), "processing_ns": geometry.PROCESSING_NS,
             "schedule_slack": scheduler.DEFAULT_SLACK, "schedule_unit_code": scheduler.DEFAULT_UNIT_CODE}
    if cfg["model"] != model:
        raise ValueError("model defaults differ from frozen configuration")
    if cfg["pairs"] != [[presets.CITY_NAME_MAP.get(a, a), presets.CITY_NAME_MAP.get(b, b)]
                        for a, b in presets.SCIENCE_PAIRS_PLAN if a not in ("Reykjavik", "Anchorage")]:
        raise ValueError("city population differs from preregistration")
    return cfg


def require_clean():
    """A correctness run must describe committed code, with no unknown git state."""
    state = provenance.git_state()
    if not state["sha"] or state["dirty"] is not False:
        raise ValueError("E0 requires a clean committed checkout")
    return state["sha"]


def select_records(records, count):
    """The preregistered catalogue-order selection, including both endpoints."""
    ordered = sorted(records, key=lambda r: r.norad)
    if count < 2 or len(ordered) < count or len({r.norad for r in ordered}) != len(ordered):
        raise ValueError("not enough distinct satellites for the fixed selection")
    return [ordered[i * (len(ordered) - 1) // (count - 1)] for i in range(count)]


def metric(name, constellation, label, values, limit, unit, *, lower=False):
    """Count each nonfinite or out-of-bound observation; empty is not a pass."""
    a = np.asarray(values, dtype=float).reshape(-1)
    if not a.size:
        raise ValueError(f"empty check: {name}")
    finite = np.isfinite(a)
    bad = ~finite | ((a < limit) if lower else (a > limit))
    f = a[finite]
    return {"check": name, "constellation": constellation, "label": label,
            "checked": int(a.size), "violations": int(bad.sum()),
            "worst": float((f.min() if lower else f.max())) if f.size else None,
            "limit": limit, "unit": unit, "bound": "minimum" if lower else "maximum"}


def orbit_metrics(constellation, full, ms_epoch, outputs, offsets):
    """Compare actual browser outputs, preserving failed positions as violations."""
    full, ms_epoch = np.asarray(full), np.asarray(ms_epoch)
    if full.shape != ms_epoch.shape or full.ndim != 3 or full.shape[1] != len(offsets):
        raise ValueError("reference orbit shape differs")
    rows, detail = [], []
    label = "REAL" if constellation == "C5" else "MODELLED"
    for source, points in outputs.items():
        arr = np.asarray(points, dtype=float)
        if arr.shape != (full.shape[1], full.shape[0], 3):
            raise ValueError(f"{source}: browser orbit shape differs")
        e_full = np.linalg.norm(arr.transpose(1, 0, 2) - full, axis=2) * 1000
        e_ms = np.linalg.norm(arr.transpose(1, 0, 2) - ms_epoch, axis=2) * 1000
        rows += [metric(f"orbit_{source}_full", constellation, label, e_full, 10, "m"),
                 metric(f"orbit_{source}_ms_epoch", constellation, label, e_ms, 1, "m")]
        for ti, offset in enumerate(offsets):
            for si in range(full.shape[0]):
                detail.append({"constellation": constellation, "input": source, "offset_s": offset,
                               "satellite_index": si, "full_error_m": float(e_full[si, ti]),
                               "ms_error_m": float(e_ms[si, ti])})
    return rows, detail


def certified_heights(pa, pb):
    """Fast independent certificate, refining only uncertified WGS84 segments."""
    low = geometry.height_lower_bound_km(pa, pb)
    refine = np.isfinite(low) & (low < geometry.MIN_GRAZING_ALT_KM)
    if np.any(refine):
        low[refine] = geometry.segment_min_height_km(np.asarray(pa)[refine], np.asarray(pb)[refine])
    return low


def link_metrics(sc, k, constellation):
    """Check stored link state against geometry, including every visible GSL."""
    pos = sc.sat_pos_km[:, k]
    active = sc.isl_up[:, k]
    a, b = sc.isl_a[active], sc.isl_b[active]
    pa, pb = pos[a], pos[b]
    rows = [metric("positions_finite", constellation, "REAL" if constellation == "C5" else "MODELLED",
                   np.isfinite(pos).all(axis=1).astype(int), 1, "boolean", lower=True),
            metric("isl_grazing", constellation, "MODELLED", certified_heights(pa, pb), 80, "km", lower=True)]
    dist = np.linalg.norm(pb - pa, axis=1)
    stored = sc.graph.prop_ns[:len(sc.isl_a), k][active]
    residual = stored - geometry.light_time_ns_exact(dist)
    # A half-nanosecond is the registered rounding allowance, not extra delay.
    rows.append(metric("link_light_time", constellation, "REAL" if constellation == "C5" else "MODELLED", residual, -0.5, "ns", lower=True))
    cross = sc.isl_kind[active] == 1
    if np.any(cross):
        lat = np.maximum(np.abs(sc.sat_lat_deg[a[cross], k]), np.abs(sc.sat_lat_deg[b[cross], k]))
        rows.append(metric("isl_polar_cutoff", constellation, "MODELLED", lat,
                           sc.grid_params.polar_cutoff_deg, "degrees"))
    visible = sc.gsl_visible[:, k]
    if np.any(visible):
        sat = sc.gsl_sat[visible]
        gs = np.array([x.ecef_km for x in sc.ground_stations])[sc.gsl_gs[visible]]
        gd = np.linalg.norm(pos[sat] - gs, axis=1)
        gp = sc.graph.prop_ns[len(sc.isl_a):, k][visible]
        rows.append(metric("gsl_light_time", constellation, "REAL" if constellation == "C5" else "MODELLED", gp - geometry.light_time_ns_exact(gd),
                           -0.5, "ns", lower=True))
    selected = sc.gsl_up[:, k]
    if np.any(selected):
        # Recompute elevations from positions, rather than trust the selected table.
        elevations = [float(gsl.elevation_deg(sc.ground_stations[int(g)], pos[int(s)]))
                      for g, s in zip(sc.gsl_gs[selected], sc.gsl_sat[selected])]
        rows.append(metric("gsl_elevation", constellation, "MODELLED", elevations,
                           sc.gsl_params.min_elevation_deg, "degrees", lower=True))
    if sc.ground_stations:
        counts = np.bincount(sc.gsl_gs[selected], minlength=len(sc.ground_stations))
        rows.append(metric("gsl_degree", constellation, "MODELLED", counts,
                           sc.gsl_params.max_links_per_gs, "links"))
    return rows


def physics_run(cfg, constellation, fleet, shell_id):
    """Build the real export pipeline at all check instants, then check its outputs."""
    t0 = omm.parse_epoch_ns(cfg["start_utc"].removesuffix("Z"))
    times = [t0 + t * 1_000_000_000 for t in cfg["offsets_s"]]
    by_city = {c.name: c for c in cities.load_cities()}
    names = sorted({n for p in cfg["pairs"] for n in p})
    registry = sids.SidRegistry.load_or_empty(sids.DEFAULT_PATH)
    registry.ensure_ground_stations(names)
    stations = [gsl.ground_station_from_city(by_city[n], registry.ground_station_number(n)) for n in names]
    sc = graph.build_scenario(fleet, shell_id, stations, times, registry=registry, reference_ns=t0)
    rows, detail, schedules = [], [], []
    node = {name: sc.gs_node(i) for i, name in enumerate(names)}
    for k, offset in enumerate(cfg["offsets_s"]):
        for row in link_metrics(sc, k, constellation):
            row["offset_s"] = offset
            rows.append(row)
        csr = sc.graph.csr_at(k)
        for src, dst in cfg["pairs"]:
            cost, path = dijkstra.shortest_path(csr, node[src], node[dst])
            gc = cities.great_circle_km(by_city[src], by_city[dst])
            bound = float(geometry.light_time_ns_exact(gc))
            detail.append({"constellation": constellation, "offset_s": offset, "src": src, "dst": dst,
                           "reachable": path is not None, "hops": len(path) - 1 if path else None,
                           "cost_ns": cost, "great_circle_light_ns": bound,
                           "rounding_allowance_ns": (len(path) - 1) * 0.5 if path else None})
            if path:
                rows.append(metric("path_great_circle", constellation, "DERIVED",
                                   [cost + (len(path) - 1) * 0.5 - bound], 0, "ns", lower=True))
                if k == 0:
                    e = scheduler.plan_path(sc, node[src], node[dst], k)
                    schedules.append({"constellation": constellation, "pair": f"{src}-{dst}",
                                      "sids": list(e.sids_fwd), "budgets": list(e.budgets_ceil_ns),
                                      "t_gps_ns": scheduler.utc_ns_to_gps_ns(t0) + 123})
    records = {r.norad: r for r in fleet.records}
    picked = select_records([records[int(n)] for n in sc.sat_norad], cfg["orbit_satellites"])
    used = set(sc.sat_norad.tolist())
    mean_motion = np.array([float(r.values["MEAN_MOTION"]) for r in records.values() if r.norad in used])
    period_s = 86400 / mean_motion
    rows.append(metric("full_orbit_coverage", constellation, "DERIVED", period_s,
                       max(cfg["offsets_s"]) - min(cfg["offsets_s"]), "s"))
    del sc
    return rows, detail, schedules, picked, times


def python_case(c):
    """Reference result in the common cross-language adapter format."""
    if c["op"] == "CE":
        h = proto.CrhHeader.from_forward(c["sids"], routing_type=c["routing_type"], next_header=c["nh"])
        return {"hex": h.encode().hex()}
    if c["op"] == "CP":
        r = asdict(proto.crh_process_at_node(bytes.fromhex(c["hex"])))
        raw = r.pop("out_bytes")
        return {**r, "hex": raw.hex() if raw is not None else None}
    if c["op"] == "B":
        h = proto.build_header(c["sids"], c["budgets"], int(c["t"]), c["unit"], next_header=c["nh"])
        return {"hex": h.encode().hex()}
    if c["op"] == "E":
        flags = c["flags"]
        if "budgets" in c:
            deltas, sat = proto.encode_deltas(c["budgets"], c["unit"])
            flags |= proto.FLAG_SAT if sat else 0
        else:
            deltas = c["deltas"]
        h = proto.TcrhHeader.from_forward(c["sids"], deltas, c["epoch"], c["unit"],
                                         next_header=c["nh"], extra_flags=flags)
        return {"hex": h.encode().hex()}
    raw = bytes.fromhex(c.get("hex", ""))
    if c["op"] == "I":
        out, sid = proto.ingress_send(raw)
        return {"hex": out.hex(), "first_sid": sid}
    if c["op"] not in ("P", "L"):
        raise ValueError("unknown wire operation")
    r = proto.link_down_fallback(raw) if c["op"] == "L" else proto.process_at_node(raw, c["now"], c["policy"])
    result = asdict(r)
    result["hex"] = result.pop("out_bytes")
    if result["hex"] is not None:
        result["hex"] = result["hex"].hex()
    return result


def make_cases(schedules):
    """Every golden vector plus source/encap schedule headers and hop decisions."""
    vectors = json.loads((REPO / "spec/golden/tcrh_vectors.json").read_text())
    cases = []
    for v in vectors["encode"]:
        c = {"op": "B" if "t_ingress_gps_ns" in v else "E", "name": "golden/" + v["name"],
             "sids": v["sids_fwd"], "unit": v["unit_code"], "nh": v["next_header"],
             "flags": v["flags"], "expected": {"hex": v["expect_hex"]}}
        if c["op"] == "B":
            c.update(t=v["t_ingress_gps_ns"], budgets=v["cumulative_budgets_ns"])
        else:
            c["epoch"] = v["epoch_base"]
            c["budgets" if "cumulative_budgets_ns" in v else "deltas"] = v.get("cumulative_budgets_ns", v.get("deltas_fwd"))
        cases.append(c)
    for section, op in [("process", "P"), ("link_down", "L")]:
        for v in vectors[section]:
            c = {"op": op, "name": "golden/" + v["name"], "hex": v["hex_in"],
                 "now": v.get("now_u", 0), "policy": v.get("policy", "continue")}
            expected = python_case(c)
            for key, val in v.items():
                if key.startswith("expect_"):
                    field = key.removeprefix("expect_").replace("hex_out", "hex")
                    if expected.get(field) != val:
                        raise ValueError(f"Python disagrees with golden vector {v['name']}: {field}")
            c["expected"] = expected
            cases.append(c)
    crh = json.loads((REPO / "spec/golden/crh_vectors.json").read_text())
    for v in crh["encode"]:
        cases.append({"op": "CE", "name": "crh-golden/" + v["name"], "sids": v["sids_fwd"],
                      "routing_type": v["routing_type"], "nh": v["next_header"], "expected": {"hex": v["expect_hex"]}})
    for v in crh["process"]:
        c = {"op": "CP", "name": "crh-golden/" + v["name"], "hex": v["hex_in"]}
        c["expected"] = {k.removeprefix("expect_").replace("hex_out", "hex"): val
                         for k, val in v.items() if k.startswith("expect_")}
        cases.append(c)
    for e in schedules:
        for nh in (17, 41):
            name = f"schedule/{e['constellation']}/{e['pair']}/{nh}"
            c = {"op": "B", "name": name, "sids": e["sids"], "budgets": e["budgets"],
                 "t": str(e["t_gps_ns"]), "unit": 1, "nh": nh}
            c["expected"] = python_case(c)
            cases.append(c)
            raw = c["expected"]["hex"]
            ingress = {"op": "I", "name": name + "/ingress", "hex": raw}
            ingress["expected"] = python_case(ingress)
            cases.append(ingress)
            raw = ingress["expected"]["hex"]
            down = {"op": "L", "name": name + "/link_down", "hex": raw, "now": 0, "policy": "continue"}
            down["expected"] = python_case(down)
            cases.append(down)
            h = proto.TcrhHeader.decode(bytes.fromhex(raw))
            for k in range(1, h.num_hops + 1):
                deadline = h.deadline(k)
                for shift in (0, 1):
                    for policy in ("continue", "greedy", "drop"):
                        step = {"op": "P", "name": f"{name}/hop{k}/{shift}/{policy}", "hex": raw,
                                "now": (deadline + shift) % (1 << 32), "policy": policy}
                        step["expected"] = python_case(step)
                        cases.append(step)
                raw = proto.process_at_node(bytes.fromhex(raw), deadline, "continue").out_bytes.hex()
    for i, c in enumerate(cases):
        c["id"] = i
    return cases


def wire_line(c):
    """Lossless, narrow TSV input to the C++ adapter; it receives no expected values."""
    op = c["op"]
    if op == "CE":
        fields = [op, c["id"], c["routing_type"], c["nh"], ",".join(map(str, c["sids"]))]
    elif op == "CP":
        fields = [op, c["id"], c["hex"]]
    elif op in ("B", "E"):
        fields = [op, c["id"], c["unit"], c["nh"], c.get("t", c.get("epoch")), c.get("flags", 0),
                  ",".join(map(str, c["sids"])), ",".join(map(str, c.get("budgets", c.get("deltas")))),
                  "budgets" if "budgets" in c else "deltas"]
    elif op == "I":
        fields = [op, c["id"], c["hex"]]
    else:
        fields = [op, c["id"], c["hex"], c.get("now", 0), c.get("policy", "continue")]
    return "\t".join(map(str, fields))


def run_command(command, out, commands):
    """Record exact subprocess commands, exit status and their complete output."""
    index = len(commands)
    env = dict(os.environ, OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MPLBACKEND="Agg")
    p = subprocess.run(list(map(str, command)), cwd=REPO, env=env, capture_output=True, text=True, timeout=600)
    log = Path(out) / f"command-{index:02d}.log"
    log.write_text(p.stdout + "\n--- stderr ---\n" + p.stderr)
    commands.append({"argv": list(map(str, command)), "cwd": str(REPO), "returncode": p.returncode,
                     "log": log.name})
    p.check_returncode()
    return p.stdout


def prepare_adapters(out, commands):
    """Compile experiment adapters against the actual installed production engines."""
    out = Path(out)
    node = Path.home() / ".local/opt/node/bin/node"
    if not node.is_file():
        raise FileNotFoundError(node)
    build = Path.home() / "ns-3-dev/build"
    lib = build / "lib"
    cpp = out / "ns3-wire"
    run_command(["c++", "-std=c++20", "-O2", str(HERE / "ns3-wire.cc"), "-I", str(build / "include"),
                 "-L", str(lib), f"-Wl,-rpath,{lib}", "-lns3.44-chronoroute-default",
                 "-lns3.44-internet-default", "-lns3.44-network-default", "-lns3.44-core-default",
                 "-o", str(cpp)], out, commands)
    browser = out / "browser.mjs"
    script = (f"const e=require({json.dumps(str(REPO / 'web/node_modules/esbuild/lib/main.js'))});"
              f"e.buildSync({{entryPoints:[{json.dumps(str(HERE / 'browser.ts'))}],"
              f"outfile:{json.dumps(str(browser))},bundle:true,platform:'node',format:'esm',"
              "define:{'import.meta.env.BASE_URL':'\"/\"'}})")
    run_command([node, "-e", script], out, commands)
    return {"node": node, "browser": browser, "ns3": cpp}


def compare_cases(cases, outputs, producer):
    """No missing, duplicate or extra case can be silently counted as agreement."""
    ids = [c["id"] for c in outputs]
    if len(ids) != len(set(ids)) or set(ids) != {c["id"] for c in cases}:
        raise ValueError(f"{producer}: case coverage differs")
    by_id = {c["id"]: {k: v for k, v in c.items() if k != "id"} for c in outputs}
    differences = [{"producer": producer, "id": c["id"], "name": c["name"],
                    "expected": c["expected"], "actual": by_id[c["id"]]}
                   for c in cases if by_id[c["id"]] != c["expected"]]
    row = metric(f"wire_{producer}", "C5+C2+golden", "REAL",
                 [int(by_id[c["id"]] != c["expected"]) for c in cases], 0, "mismatch")
    return [row], differences


def write_wire_pcap(cases, path):
    """Capture actual input and output bytes; expected malformed vectors stay labelled."""
    frames_out = []
    with open(path, "wb") as fh:
        writer = pcap.PcapWriter(fh)
        for c in cases:
            hexes = [c["hex"]] if "hex" in c else []
            if c["expected"].get("hex") is not None:
                hexes.append(c["expected"]["hex"])
            for raw_hex in hexes:
                raw = bytes.fromhex(raw_hex)
                h = None
                reason = None
                try:
                    h, _ = proto.TcrhHeader.decode_prefix(raw)
                except proto.TcrhDecodeError as e:
                    reason = e.reason
                unit = proto.unit_ns((raw[4] >> 4) & 3) if len(raw) > 4 and raw[2] == 253 else 1_000_000
                now = c.get("now", h.epoch_base if h else 0)
                t = now * unit
                frame = pcap._vector_frame(raw, t, len(frames_out), c["name"],
                                           sid_to_addr=pcap.sid_address, ingress_sid=1, src=pcap.HOST_SRC)
                writer.write(frame.packet, t_gps_ns=t)
                frames_out.append({"case": c["id"], "name": c["name"], "hex": raw_hex,
                                   "reason": reason, "now": now})
    return frames_out


def check_wireshark(path, expected, out, commands):
    """Verify actual frame bytes plus dissector fields and deliberate rejection reasons."""
    fields = ["frame.number", "tcrh.valid", "tcrh.reason", "tcrh.flags", "tcrh.num_hops", "tcrh.dev_hop",
              "tcrh.epoch_base", "tcrh.sid", "tcrh.delta", "tcrh.current_deadline", "tcrh.late", "_ws.lua.error",
              "ipv6.routing.nxt", "ipv6.routing.len", "ipv6.routing.type", "ipv6.routing.segleft",
              "tcrh.reserved", "tcrh.padding", "tcrh.deadline", "ipv6.routing.crh16.sid", "ipv6.routing.crh32.sid"]
    command = ["tshark", "-n", "-r", str(path), "-X", f"lua_script:{REPO / 'tools/wireshark/tcrh.lua'}",
               "-o", "tcrh.timebase:offset", "-o", f"tcrh.offset_ns:{-pcap.GPS_TO_PCAP_NS}",
               "-T", "fields", "-E", "separator=/t", "-E", "occurrence=a", "-E", "aggregator=,"]
    for name in fields:
        command += ["-e", name]
    text = run_command(command, out, commands)
    lines = text.splitlines()
    if len(lines) != len(expected):
        raise ValueError("Wireshark frame coverage differs")
    # Read raw capture bytes independently of the expected list.
    import struct
    data = Path(path).read_bytes()
    packets = []
    offset = 24
    while offset < len(data):
        _, _, caplen, _ = struct.unpack_from("<IIII", data, offset)
        offset += 16
        packets.append(data[offset:offset + caplen])
        offset += caplen
    mismatches, byte_bad, field_bad = [], [], []
    for i, (line, exp, packet) in enumerate(zip(lines, expected, packets)):
        values = line.split("\t")
        if len(values) != len(fields) or int(values[0]) != i + 1:
            raise ValueError("Wireshark fields or frame order differs")
        r = dict(zip(fields, values))
        raw = bytes.fromhex(exp["hex"])
        bad_bytes = packet[40:40 + len(raw)] != raw
        bad_fields = bool(r["_ws.lua.error"])
        if len(raw) >= 8:
            for key, val in zip(("ipv6.routing.nxt", "ipv6.routing.len", "ipv6.routing.type", "ipv6.routing.segleft"), raw[:4]):
                bad_fields |= r[key] != str(val)
        if exp["reason"] == "wrong_type":
            bad_fields |= r["tcrh.valid"] != ""
        else:
            bad_fields |= r["tcrh.valid"] != ("0" if exp["reason"] else "1")
            bad_fields |= r["tcrh.reason"] != (exp["reason"] or "")
        if exp["reason"] is None:
            h = proto.TcrhHeader.decode_prefix(raw)[0]
            want = {"tcrh.flags": h.flags, "tcrh.num_hops": h.num_hops,
                    "tcrh.dev_hop": h.dev_hop, "tcrh.epoch_base": h.epoch_base}
            bad_fields |= any(int(r[k], 0) != v for k, v in want.items())
            bad_fields |= r["tcrh.sid"] != ",".join(map(str, h.sids_rev))
            bad_fields |= r["tcrh.delta"] != ",".join(map(str, h.deltas_rev))
            bad_fields |= int(r["tcrh.reserved"], 0) != raw[7]
            bad_fields |= r["tcrh.padding"] != raw[12 + 3 * h.num_hops:(raw[1] + 1) * 8].hex()
            bad_fields |= r["tcrh.deadline"] != ",".join(str(h.deadline(k)) for k in range(h.num_hops, 0, -1))
            if h.segments_left < h.num_hops:
                dk = h.deadline(h.num_hops - h.segments_left)
                bad_fields |= r["tcrh.current_deadline"] != str(dk)
                if not h.is_dev:
                    margin = proto.serial_diff(dk, exp["now"])
                    # The dissector deliberately withholds a timing verdict for
                    # implausible capture clocks; half-range vectors exercise this.
                    want_late = "" if abs(margin) * proto.unit_ns(h.unit_code) > 120_000_000_000 else str(int(proto.is_late(exp["now"], dk)))
                    bad_fields |= r["tcrh.late"] != want_late
        if len(raw) >= 8 and raw[2] in (5, 6) and len(raw) >= (raw[1] + 1) * 8:
            h = proto.CrhHeader.decode_prefix(raw)[0]
            slots = list(h.sids_rev)
            # Wireshark's native decoder stops at the first zero padding slot.
            slots = [] if raw[3] >= len(slots) else (slots[:slots.index(0)] if 0 in slots else slots)
            key = "ipv6.routing.crh16.sid" if raw[2] == 5 else "ipv6.routing.crh32.sid"
            bad_fields |= r[key] != ",".join(map(str, slots))
        byte_bad.append(int(bad_bytes))
        field_bad.append(int(bad_fields))
        if bad_bytes or bad_fields:
            mismatches.append({"frame": i + 1, "expected": exp, "actual": r,
                               "byte_mismatch": bad_bytes, "field_mismatch": bool(bad_fields)})
    return [metric("wire_capture_bytes", "C5+C2+golden", "REAL", byte_bad, 0, "mismatch"),
            metric("wire_wireshark_fields", "C5+C2+golden", "REAL", field_bad, 0, "mismatch")], mismatches


def write_outputs(out, rows, orbit_detail, path_detail, differences):
    """Write generated tables and figures from actual observations only."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = Path(out)
    # Aggregate repeated checks while retaining measured worst residual and counts.
    aggregate = {}
    for r in rows:
        key = (r["check"], r["constellation"])
        if key not in aggregate:
            aggregate[key] = {k: v for k, v in r.items() if k != "offset_s"}
        else:
            a = aggregate[key]
            a["checked"] += r["checked"]
            a["violations"] += r["violations"]
            if r["worst"] is not None:
                a["worst"] = (min if r["bound"] == "minimum" else max)(a["worst"], r["worst"]) if a["worst"] is not None else r["worst"]
    with (out / "summary.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(next(iter(aggregate.values()))))
        w.writeheader()
        w.writerows(aggregate.values())
    for name, data in [("orbit_errors", orbit_detail), ("paths", path_detail)]:
        if data:
            with gzip.open(out / f"{name}.csv.gz", "wt", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=list(data[0]))
                w.writeheader()
                w.writerows(data)
    (out / "mismatches.json").write_text(json.dumps(differences, indent=2, allow_nan=False) + "\n")
    fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
    for constellation in sorted({r["constellation"] for r in orbit_detail}):
        subset = [r for r in orbit_detail if r["constellation"] == constellation and r["input"] == "pinned"]
        for field, label in [("full_error_m", "full epoch"), ("ms_error_m", "millisecond epoch")]:
            points = {}
            for r in subset:
                points.setdefault(r["offset_s"], []).append(r[field])
            ax.plot(sorted(points), [max(points[t]) for t in sorted(points)], label=f"{constellation}, {label}")
    ax.axhline(10, linestyle="--", color="grey", label="full-epoch limit")
    ax.axhline(1, linestyle=":", color="grey", label="millisecond-epoch limit")
    ax.set(xlabel="Seconds from pinned start", ylabel="Maximum position difference (m)")
    ax.legend(fontsize=8)
    fig.savefig(out / "orbit_errors.png", dpi=160)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 5), layout="constrained")
    data = list(aggregate.values())
    ax.barh(range(len(data)), [r["violations"] for r in data])
    ax.set_yticks(range(len(data)), [f"{r['constellation']}: {r['check']}" for r in data], fontsize=7)
    ax.set(xlabel="Violations (counts from summary.csv)", xlim=(0, max(1, max(r["violations"] for r in data))))
    fig.savefig(out / "violations.png", dpi=160)
    plt.close(fig)
    return [p for p in out.rglob("*") if p.is_file() and p.name != "manifest.json"]


def gate_exit(rows):
    """A partial or violated gate never exits successfully."""
    return 0 if rows and all(r["violations"] == 0 for r in rows) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    git_sha = require_clean()
    cfg = load_config(args.config)
    out = args.out.resolve()
    if out.exists():
        raise FileExistsError(f"refusing to overwrite {out}")
    out.mkdir(parents=True)
    rows, orbit_detail, path_detail, differences, commands = [], [], [], [], []
    inputs, schedules, references = [], [], {}
    with provenance.RunTimer() as timer:
        try:
            adapters = prepare_adapters(out, commands)
            for constellation in ("C5", "C2"):
                print(f"E0 {constellation}: full-orbit physics", flush=True)
                if constellation == "C5":
                    fleet = snapshot.load_pinned(REPO / cfg["snapshot"], "supgp")
                    shell = cfg["shell"]
                else:
                    t0 = omm.parse_epoch_ns(cfg["start_utc"].removesuffix("Z"))
                    fleet = presets.walker_fleet(presets.WALKER_PRESETS["C2"], t0)
                    shell = planes.build_fleet_geometry(fleet.records, t0, satrecs=fleet.satrecs).shells[0].shell_id
                r, paths, headers, picked, times = physics_run(cfg, constellation, fleet, shell)
                rows.extend(r)
                path_detail.extend(paths)
                schedules.extend(headers)
                full = SatelliteArray(picked).propagate(times, geodetic=False).r_ecef
                ms = np.stack([_ms_epoch_ecef_km(picked, t) for t in times], axis=1)
                references[constellation] = (full, ms)
                inputs.append({"constellation": constellation, "records": [dict(r.values) for r in picked],
                               "omm_min": json.loads(snapshot.omm_min_bytes(picked)), "times_ns": list(map(str, times))})
            cases = make_cases(schedules)
            for c in cases:
                rows.append(metric("wire_python", "C5+C2+golden", "REAL", [int(python_case(c) != c["expected"])], 0, "mismatch"))
            inp = out / "inputs.json"
            inp.write_text(json.dumps({"cases": cases, "orbits": inputs}) + "\n")
            browser_output = out / "browser.json"
            run_command([adapters["node"], adapters["browser"], inp, browser_output], out, commands)
            browser = json.loads(browser_output.read_text())
            for o in browser["orbits"]:
                full, ms = references[o["constellation"]]
                if o["norads"] != [r["NORAD_CAT_ID"] for r in next(i for i in inputs if i["constellation"] == o["constellation"])["records"]]:
                    raise ValueError("browser satellite order differs")
                r, detail = orbit_metrics(o["constellation"], full, ms,
                                          {s: o[s] for s in ("pinned", "exported")}, cfg["offsets_s"])
                rows.extend(r)
                orbit_detail.extend(detail)
            if {o["constellation"] for o in browser["orbits"]} != {"C5", "C2"}:
                raise ValueError("missing browser constellation")
            r, diff = compare_cases(cases, browser["cases"], "browser")
            rows.extend(r)
            differences.extend(diff)
            protocol = out / "wire.tsv"
            protocol.write_text("\n".join(wire_line(c) for c in cases) + "\n")
            cpp = run_command([adapters["ns3"], protocol], out, commands)
            r, diff = compare_cases(cases, [json.loads(line) for line in cpp.splitlines()], "ns3")
            rows.extend(r)
            differences.extend(diff)
            frames_out = write_wire_pcap(cases, out / "wire.pcap")
            (out / "wire_frames.json").write_text(json.dumps(frames_out) + "\n")
            r, diff = check_wireshark(out / "wire.pcap", frames_out, out, commands)
            rows.extend(r)
            differences.extend(diff)
        except Exception:
            (out / "error.txt").write_text(traceback.format_exc())
            rows.append(metric("execution", "campaign", "REAL", [1], 0, "error"))
            print(traceback.format_exc(), file=sys.stderr)
        # Retain compressed raw browser output for independent re-analysis.
        if (out / "browser.json").exists():
            with (out / "browser.json").open("rb") as src, gzip.open(out / "browser.json.gz", "wb") as dst:
                shutil.copyfileobj(src, dst)
            (out / "browser.json").unlink()
        files = write_outputs(out, rows, orbit_detail, path_detail, differences)
    libraries = sorted((Path.home() / "ns-3-dev/build/lib").glob("libns3.44-*-default.so"))
    extra = {**cfg["campaign"], "commands": commands, "status": "pass" if gate_exit(rows) == 0 else "fail",
             "implementation_git_sha": git_sha,
             "input_hashes": {str(p.relative_to(REPO)): provenance.file_sha256(p) for p in
                              [args.config.resolve(), REPO / "spec/golden/tcrh_vectors.json", REPO / "spec/golden/crh_vectors.json", REPO / "tools/wireshark/tcrh.lua",
                               REPO / "web/package-lock.json"]},
             "ns3_libraries": {str(p): provenance.file_sha256(p) for p in libraries if "-test-" not in p.name},
             "selected_norads": {i["constellation"]: [r["NORAD_CAT_ID"] for r in i["records"]] for i in inputs},
             "constellation_labels": {"C5": {"orbital_elements": "REAL", "satellite_positions_sgp4": "REAL"},
                                      "C2": {"orbital_elements": "MODELLED", "satellite_positions_sgp4": "MODELLED"}},
             "path_checks": len(path_detail), "no_route_samples": sum(not p["reachable"] for p in path_detail),
             "limitations": "Sampled geometry, not continuous-time proof; MODELLED topology and traffic, DERIVED routes; real Starlink routing UNKNOWN. Wireshark suppresses timing verdicts beyond 120 s clock margin, and its native CRH decoder cannot list SIDs when SL indexes beyond the header."}
    provenance.write_manifest(out, tool="experiments/E00/gate.py", tool_version=__version__,
                              command=[sys.executable, "-B", "experiments/E00/gate.py", *(argv or sys.argv[1:])],
                              config=cfg, seeds=[], snapshot=REPO / cfg["snapshot"], outputs=files,
                              labels=labels.pick("orbital_elements", "satellite_positions_sgp4", "city_coordinates",
                                                 "shells_and_planes", "routes_and_budgets", "isl_topology_grid4",
                                                 "gsl_mask_and_assignment", "processing_delay", "tcrh_header_bytes",
                                                 "pcap_addresses", "pcap_timestamps"), extra=extra, timer=timer)
    provenance.validate_manifest(out / "manifest.json")
    print(f"E0: {sum(r['violations'] for r in rows)} violations; {out}", flush=True)
    return gate_exit(rows)


if __name__ == "__main__":
    sys.exit(main())

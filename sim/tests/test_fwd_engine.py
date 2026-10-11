"""End-to-end tests of the simulator v2 engine on the tiny synthetic preset C1
(24 x 20 Walker at 550 km): conservation, invariants (all on), determinism,
common random numbers, the fault models, deviation policies, fallbacks and
termination."""

import copy
import csv
import gzip
import hashlib
import json

import pytest

from chronoroute import provenance
from chronoroute.fwd import command, config, scenario as scenario_mod
from chronoroute.trace import reader

FLOWS = [{"src": "London", "dst": "New York"}, {"src": "Chennai", "dst": "London"},
         {"src": "Singapore", "dst": "Sydney"}, {"src": "Tokyo", "dst": "Los Angeles"}]


def base_doc(**over):
    doc = {
        "seed": 7,
        "scenario": {"kind": "walker", "preset": "C1", "duration_s": 3, "drain_s": 1, "chunk_steps": 20,
                     "gsl": {"min_elevation_deg": 10}},
        "traffic": {"flows": copy.deepcopy(FLOWS), "rate_pps": 50},
        "output": {"trace": "full", "invariants": "all", "sample_every": 5},
    }
    for path, value in over.items():
        node = doc
        keys = path.split(".")
        for k in keys[:-1]:
            node = node.setdefault(k, {})
        node[keys[-1]] = value
    return doc


def run(tmp_path, name, doc, manifest=False):
    out = tmp_path / name
    summary, written = command.run_config(config.normalise(doc), out, write_manifest=manifest)
    return out, summary


def packets(out):
    with gzip.open(out / "packets.csv.gz", "rt", encoding="utf-8") as fh:
        return {int(r["pkt"]): r for r in csv.DictReader(fh)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- basics

def test_end_to_end_tiny_preset(tmp_path):
    out, s = run(tmp_path, "e2e", base_doc(), manifest=True)
    c = s["counts"]
    assert c["sent"] == 4 * 150 and c["delivered"] == c["sent"]          # 50 pps x 3 s x 4 flows
    assert s["conservation"]["ok"] and c["unfinished"] == 0
    assert s["invariants"]["violations"] == 0
    assert s["invariants"]["checked_packets"] == c["sent"] and s["invariants"]["checked_hops"] == c["hop_events"]
    assert reader.validate_run(out) == []
    m = provenance.validate_manifest(out / "manifest.json")      # raises on any problem
    assert m["seeds"] == [7] and m["tool"] == "cr run"
    assert set(m["labels"].values()) <= {"REAL", "DERIVED", "MODELLED"}
    assert m["labels"]["synthetic_walker_constellation"] == "MODELLED"
    assert "satellite_positions_sgp4" not in m["labels"]       # synthetic positions are not REAL
    run_doc = reader.read_run(out)
    assert run_doc["positions"] == {"source": "snapshot", "path": "synthetic_omm.json"}
    assert (out / "synthetic_omm.json").is_file()
    # every packet: one send, hops, one deliver; SL strictly decreasing along the way
    for pkt, evs in reader.journeys(out).items():
        assert evs[0]["ev"] == "send" and evs[-1]["ev"] == "deliver"
        sls = [e["sl"] for e in evs if e["ev"] == "hop"]
        assert sls == sorted(sls, reverse=True) and sls[-1] == 0
        assert evs[-1]["node"] == run_doc["flows"][evs[0]["flow"]]["dst_node"]


def test_determinism_same_seed_same_bytes(tmp_path):
    doc = base_doc(**{"forwarding.jitter": {"model": "j1", "mean_ns": 400000},
                      "forwarding.background": {"model": "poisson", "rho": 0.3},
                      "faults": [{"kind": "link_renewal", "unavailability": 0.05, "mttr_s": 0.5}]})
    a, sa = run(tmp_path, "a", doc)
    b, sb = run(tmp_path, "b", doc)
    for f in ("events.jsonl.gz", "packets.csv.gz", "schedule.csv.gz", "run.json"):
        assert sha(a / f) == sha(b / f), f
    assert sa["counts"] == sb["counts"]
    c, _ = run(tmp_path, "c", dict(doc, seed=8))
    assert sha(a / "packets.csv.gz") != sha(c / "packets.csv.gz")      # the seed matters


def test_sampled_packets_carry_their_bytes_on_every_event(tmp_path):
    """spec/trace-v1.md 3-4 (minor finding: late and fallback events had hex null): a sampled
    packet's late event carries the bytes after processing, its fallback event the bytes after
    the switch, and the validator refuses a sampled event without hex."""
    sc = scenario_mod.build_scenario(config.normalise(base_doc()))
    a, b = sc.resolve_on_path({"flow": 0, "position": "middle"}, 1_000_000_000, False)
    c, d = sc.resolve_on_path({"flow": 1, "position": "middle"}, 1_000_000_000, False)
    doc = base_doc(**{"forwarding.policy": "greedy", "output.sample_every": 1,
                      "faults": [{"kind": "slow_processing", "link": [a, b], "delta_ns": 20_000_000,
                                  "start_s": 1, "stop_s": 2},
                                 {"kind": "link_down", "link": [c, d], "start_s": 1, "stop_s": 2}]})
    out, s = run(tmp_path, "hex", doc)
    assert s["fallback_reasons"]["late"] > 0 and s["fallback_reasons"]["next_link_down"] > 0
    seen = {"late": 0, "fallback": 0}
    lines = []
    for e in reader.iter_events(out):
        lines.append(e)
        if e["ev"] == "send" and e["hex"] is None:
            continue                                     # (no route: no header at all)
        if e["ev"] in seen:
            seen[e["ev"]] += 1
            raw = bytes.fromhex(e["hex"])
            assert (raw[3], raw[4]) == (e["sl"], e["flags"])
            if e["ev"] == "fallback":
                assert raw[3] == 0 and raw[4] & 0x02 and raw[4] & 0x01       # SL 0, GREEDY, DEV
            else:
                assert raw[4] & 0x01                                          # DEV just set
    assert seen["late"] > 0 and seen["fallback"] > 0
    sampled = {e["pkt"] for e in lines if e["ev"] == "send" and e["hex"] is not None}
    assert sampled and all(e["hex"] is not None for e in lines if e["pkt"] in sampled)
    assert reader.validate_run(out) == []
    # the validator enforces it: drop the bytes of one late event
    import gzip as gz
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "run.json").write_bytes((out / "run.json").read_bytes())
    k = next(i for i, e in enumerate(lines) if e["ev"] == "late")
    lines[k] = dict(lines[k], hex=None)
    with gz.open(bad / "events.jsonl.gz", "wt", encoding="utf-8") as fh:
        for e in lines:
            fh.write(json.dumps(e, separators=(",", ":")) + "\n")
    probs = reader.validate_run(bad)
    assert len(probs) == 1 and "is sampled (hex on its send) but its late event has no hex" in probs[0]


# --------------------------------------------------------------------------- common random numbers

def crossing(row, a, b):
    path = row["path"].split()
    return any({path[i], path[i + 1]} == {str(a), str(b)} for i in range(len(path) - 1))


def test_crn_no_fault_identical_and_fault_changes_only_crossing_packets(tmp_path):
    doc = base_doc(**{"forwarding.jitter": {"model": "j1", "mean_ns": 400000},
                      "forwarding.background": {"model": "poisson", "rho": 0.4},
                      "forwarding.policy": "continue"})
    ref, _ = run(tmp_path, "ref", doc)
    twin, _ = run(tmp_path, "twin", doc)
    assert sha(ref / "events.jsonl.gz") == sha(twin / "events.jsonl.gz")
    # a slow link on flow 1's path; resolve it the same way the engine does
    sc = scenario_mod.build_scenario(config.normalise(doc))
    a, b = sc.resolve_on_path({"flow": 1, "position": "middle"}, 1_000_000_000, False)
    fault = dict(doc, faults=[{"kind": "slow_processing", "link": [a, b], "delta_ns": 3_000_000,
                               "start_s": 1, "stop_s": 2}])
    flt, s = run(tmp_path, "fault", fault)
    p0, p1 = packets(ref), packets(flt)
    assert p0.keys() == p1.keys()
    differ = {k for k in p0 if p0[k] != p1[k]}
    crossed = {k for k in p1 if crossing(p1[k], a, b) or crossing(p0[k], a, b)}
    assert differ, "the fault must change something"
    assert differ <= crossed, sorted(differ - crossed)[:5]
    assert s["faults_logged"] == 1


# --------------------------------------------------------------------------- implementation choices

def test_ready_event_path_equals_direct_queueing(tmp_path):
    """J1 with mean 0 forces the READY-event path; it must give the same packets as direct queueing."""
    a, _ = run(tmp_path, "direct", base_doc())
    b, _ = run(tmp_path, "ready", base_doc(**{"forwarding.jitter": {"model": "j1", "mean_ns": 0}}))
    assert sha(a / "events.jsonl.gz") == sha(b / "events.jsonl.gz")
    assert sha(a / "packets.csv.gz") == sha(b / "packets.csv.gz")


def test_reference_mode_and_verify_mode_equal_fast_mode(tmp_path):
    doc = base_doc(**{"faults": [{"kind": "link_down", "on_path": {"flow": 0}, "start_s": 1, "stop_s": 2},
                                 {"kind": "slow_processing", "on_path": {"flow": 2, "kind": "node"},
                                  "delta_ns": 20_000_000, "start_s": 1, "stop_s": 2}]})
    fast, sf = run(tmp_path, "fast", doc)
    ref, _ = run(tmp_path, "ref", base_doc(**{**{"forwarding.hop_mode": "reference"},
                                               "faults": doc["faults"]}))
    ver, sv = run(tmp_path, "ver", base_doc(**{"forwarding.verify_every": 1, "faults": doc["faults"]}))
    assert sf["counts"]["fallback"] > 0 and sf["counts"]["late"] > 0      # the odd paths were exercised
    for f in ("events.jsonl.gz", "packets.csv.gz"):
        assert sha(fast / f) == sha(ref / f) == sha(ver / f), f
    assert sv["hop_processor"]["verified_calls"] > sv["counts"]["hop_events"]


def test_forwarding_reads_only_the_header_bytes(tmp_path, monkeypatch):
    """Garbling the planner's Python path and SID list after the template is built changes nothing."""
    good, _ = run(tmp_path, "good", base_doc())
    real_plan = scenario_mod.Scenario.plan

    def garbled(self, flow, start_ms, end_ms, csr_cache=None):
        e = real_plan(self, flow, start_ms, end_ms, csr_cache)
        if e is not None:
            object.__setattr__(e, "path", tuple(reversed(e.path)))
            object.__setattr__(e, "sids_fwd", tuple(0xEEEE for _ in e.sids_fwd))
            object.__setattr__(e, "hop_delays_ns", tuple(1 for _ in e.hop_delays_ns))
        return e
    monkeypatch.setattr(scenario_mod.Scenario, "plan", garbled)
    bad, _ = run(tmp_path, "bad", base_doc())
    assert sha(good / "events.jsonl.gz") == sha(bad / "events.jsonl.gz")
    assert sha(good / "packets.csv.gz") == sha(bad / "packets.csv.gz")


# --------------------------------------------------------------------------- faults and policies

def first_isl(tmp_path, flow=0, position="middle"):
    sc = scenario_mod.build_scenario(config.normalise(base_doc()))
    return sc.resolve_on_path({"flow": flow, "position": position}, 1_000_000_000, False), sc


@pytest.mark.parametrize("fb", ["greedy_visited", "greedy_pure", "grid_detour"])
def test_link_down_switches_to_fallback(tmp_path, fb):
    (a, b), _ = first_isl(tmp_path)
    doc = base_doc(**{"forwarding.fallback": fb,
                      "faults": [{"kind": "link_down", "link": [a, b], "start_s": 1, "stop_s": 2}]})
    out, s = run(tmp_path, fb, doc)
    assert s["fallback_reasons"]["next_link_down"] > 0
    assert s["conservation"]["ok"] and s["invariants"]["violations"] == 0
    evs = [e for e in reader.iter_events(out) if e["ev"] == "fallback"]
    assert evs and all(e["reason"] == "next_link_down" for e in evs)
    assert all(e["flags"] & 0x03 == 0x03 for e in evs)            # DEV and GREEDY set (spec 6 step 7)
    rows = packets(out)
    via = [r for r in rows.values() if r["greedy"] == "1" and r["outcome"] == "delivered"]
    assert via, "some packets must reach the destination by the fallback"
    for r in via:
        assert not crossing(r, a, b)                               # never over the dead link
    assert reader.validate_run(out) == []


def test_link_down_without_fallback_drops_with_dev_hop(tmp_path):
    (a, b), sc = first_isl(tmp_path)
    doc = base_doc(**{"forwarding.fallback": "none",
                      "faults": [{"kind": "link_down", "link": [a, b], "start_s": 1, "stop_s": 2}]})
    out, s = run(tmp_path, "nofb", doc)
    assert s["drops"].get("next_link_down", 0) > 0
    rows = [r for r in packets(out).values() if r["reason"] == "next_link_down"]
    for r in rows:
        path = [int(x) for x in r["path"].split()]
        assert r["dev"] == "1" and int(r["dev_hop"]) == len(path) - 1    # Dev Hop = the holding node
        assert path[-1] in (a, b)


@pytest.mark.parametrize("policy,expect", [("continue", "delivered"), ("drop", "late_strict"),
                                           ("greedy", "fallback")])
def test_late_packets_follow_the_deviation_policy(tmp_path, policy, expect):
    (a, b), _ = first_isl(tmp_path, flow=1)
    doc = base_doc(**{"forwarding.policy": policy,
                      "faults": [{"kind": "slow_processing", "link": [a, b], "delta_ns": 30_000_000,
                                  "start_s": 1, "stop_s": 2}]})
    out, s = run(tmp_path, policy, doc)
    late = [r for r in packets(out).values() if r["first_late_hop"]]
    assert late
    for r in late:
        path = [int(x) for x in r["path"].split()]
        k = int(r["first_late_hop"])
        assert {path[k - 1], path[k]} == {a, b}            # flagged at the far end of the slow link
        assert r["dev"] == "1" and int(r["dev_hop"]) == k
    if expect == "delivered":
        assert all(r["outcome"] == "delivered" and r["greedy"] == "0" for r in late)
    elif expect == "late_strict":
        assert all(r["reason"] == "late_strict" for r in late)
    else:
        assert all(r["greedy"] == "1" and r["fallback_reason"] == "late" for r in late)
    assert s["conservation"]["ok"] and s["invariants"]["violations"] == 0


def test_phantom_fault_changes_nothing(tmp_path):
    """A null (phantom) fault, Delta = 0, must leave every packet identical (counterfactual scoring)."""
    (a, b), _ = first_isl(tmp_path)
    ref, _ = run(tmp_path, "ref", base_doc())
    ph, s = run(tmp_path, "ph", base_doc(**{"faults": [{"kind": "slow_processing", "link": [a, b],
                                                       "delta_ns": 0, "start_s": 0, "stop_s": 3}]}))
    assert sha(ref / "packets.csv.gz") == sha(ph / "packets.csv.gz")
    assert s["faults_logged"] == 1


def test_node_down_loses_or_reroutes(tmp_path):
    sc = scenario_mod.build_scenario(config.normalise(base_doc()))
    node = sc.resolve_on_path({"flow": 0, "position": "middle"}, 1_000_000_000, True)
    out, s = run(tmp_path, "nd", base_doc(**{"faults": [{"kind": "node_down", "node": node,
                                                         "start_s": 1, "stop_s": 2}]}))
    assert s["drops"].get("node_down", 0) + s["drops"].get("in_flight_link_down", 0) + \
        s["fallback_reasons"]["next_link_down"] > 0
    # no packet is processed by the dead satellite while it is down: any arrival there ends it
    for pkt, evs in reader.journeys(out).items():
        for i, e in enumerate(evs):
            if e["node"] == node and e["ev"] == "hop" and 1_000_000_000 <= e["t"] < 2_000_000_000:
                assert evs[i + 1]["ev"] == "drop" and evs[i + 1]["reason"] == "node_down", evs
    assert s["conservation"]["ok"]


def test_node_dying_with_a_packet_on_its_way_loses_it(tmp_path):
    """The outage starts 1 us before a packet reaches the satellite: it is lost there (node_down);
    a packet the satellite had already transmitted still arrives downstream."""
    ref, _ = run(tmp_path, "ref", base_doc())
    sc = scenario_mod.build_scenario(config.normalise(base_doc()))
    node = sc.resolve_on_path({"flow": 0, "position": "middle"}, 1_000_000_000, True)
    hops = sorted(e["t"] for e in reader.iter_events(ref) if e["ev"] == "hop" and e["node"] == node
                  and e["t"] > 1_000_000_000)
    t_arr = hops[0]
    start = f"{(t_arr - 1000) // 10**9}.{(t_arr - 1000) % 10**9:09d}"
    out, s = run(tmp_path, "nd2", base_doc(**{"faults": [{"kind": "node_down", "node": node,
                                                          "start_s": start, "stop_s": 2}]}))
    assert s["drops"].get("node_down", 0) >= 1
    assert s["drops"].get("in_flight_link_down", 0) == 0


def test_arq_retries_add_round_trips_and_can_exhaust(tmp_path):
    (a, b), _ = first_isl(tmp_path, flow=2)
    out, s = run(tmp_path, "arq", base_doc(**{"faults": [{"kind": "arq", "link": [a, b], "loss": 0.6,
                                                          "start_s": 0, "stop_s": 3}]}))
    ref, _ = run(tmp_path, "ref", base_doc())
    assert s["drops"].get("arq_exhausted", 0) > 0          # 0.6^4 = 13% of crossing packets
    p0, p1 = packets(ref), packets(out)
    extra = [int(p1[k]["latency_ns"]) - int(p0[k]["latency_ns"]) for k in p1
             if p1[k]["outcome"] == "delivered" and crossing(p1[k], a, b)]
    assert any(x > 0 for x in extra) and any(x == 0 for x in extra)
    assert min(extra) >= 0


def test_rate_cut_with_fluid_background_builds_queue(tmp_path):
    (a, b), _ = first_isl(tmp_path, flow=3)
    doc = base_doc(**{"forwarding.background": {"model": "fluid", "rho": 0.5},
                      "faults": [{"kind": "rate_cut", "link": [a, b], "factor": 0.25, "start_s": 1, "stop_s": 2}]})
    out, s = run(tmp_path, "fluid", doc)
    ref, _ = run(tmp_path, "ref", base_doc(**{"forwarding.background": {"model": "fluid", "rho": 0.5}}))
    p0, p1 = packets(ref), packets(out)
    deltas = [int(p1[k]["latency_ns"]) - int(p0[k]["latency_ns"]) for k in p1
              if crossing(p1[k], a, b) and 1_000_000_000 <= int(p1[k]["send_ns"]) < 2_000_000_000
              and p1[k]["outcome"] == "delivered"]
    assert deltas and max(deltas) > 50_000_000              # backlog grows at (0.5 - 0.25) C for ~1 s
    assert s["background"]["fluid_lost_bits"] >= 0


def test_hop_limit_and_termination_under_heavy_failures(tmp_path):
    doc = base_doc(**{"forwarding.fallback": "greedy_pure", "forwarding.hop_limit": 8,
                      "faults": [{"kind": "link_renewal", "unavailability": 0.3, "mttr_s": 0.3}]})
    out, s = run(tmp_path, "heavy", doc)
    assert s["conservation"]["ok"] and s["counts"]["unfinished"] == 0
    assert s["max_hops"] <= 8
    assert set(s["drops"]) <= {"stuck", "hop_limit", "loop", "in_flight_link_down", "next_link_down"}
    assert reader.validate_run(out) == []


def test_unfinished_packets_are_counted(tmp_path):
    (a, b), _ = first_isl(tmp_path)
    doc = base_doc(**{"scenario.drain_s": 0, "forwarding.policy": "continue",
                      "faults": [{"kind": "rate_cut", "link": [a, b], "factor": 0.0001, "start_s": 2, "stop_s": 3}]})
    out, s = run(tmp_path, "unf", doc)
    assert s["counts"]["unfinished"] > 0 and s["conservation"]["ok"]


def test_no_route_flows_are_reported(tmp_path):
    doc = base_doc(**{"traffic.flows": [{"src": "Reykjavik", "dst": "Toronto"}],
                      "scenario.gsl": {"min_elevation_deg": 25}})
    out, s = run(tmp_path, "nr", doc)
    assert s["counts"]["no_route"] == s["counts"]["sent"] > 0
    assert s["schedule"]["gaps"] == 3 and s["schedule"]["rows"] == 0


def test_explicit_and_poisson_traffic(tmp_path):
    doc = base_doc(**{"traffic.flows": [{"src": "London", "dst": "New York", "send_times_ns": [5, 1_000_000, 2_500_000_000]},
                                        {"src": "Chennai", "dst": "London", "model": "poisson", "rate_pps": 200}]})
    out, s = run(tmp_path, "tr", doc)
    flows = {f["flow_id"]: f for f in s["flows"]}
    assert flows[0]["sent"] == 3
    assert 450 < flows[1]["sent"] < 750                     # Poisson, mean 600 in 3 s
    sends = sorted(int(r["send_ns"]) for r in packets(out).values() if r["flow"] == "0")
    assert sends == [5, 1_000_000, 2_500_000_000]


def test_encapsulation_mode_adds_40_bytes(tmp_path):
    a, _ = run(tmp_path, "src", base_doc(**{"scenario.duration_s": 1}))
    b, _ = run(tmp_path, "enc", base_doc(**{"scenario.duration_s": 1, "traffic.ingress_mode": "encap"}))
    pa, pb = packets(a), packets(b)
    assert all(int(pb[k]["wire_bytes"]) - int(pa[k]["wire_bytes"]) == 40 for k in pa)


# --------------------------------------------------------------------------- the checks are live

def test_buffer_size_is_computed_exactly():
    from chronoroute.fwd.engine import Engine
    sc = scenario_mod.build_scenario(config.normalise(base_doc(**{"scenario.duration_s": 1,
                                                                  "forwarding.buffer_ms": 0.5})))
    assert Engine(sc).buffer_bytes == 62_500                 # 0.5 ms x 1 Gb/s / 8


def test_invariant_checks_fire_on_impossible_geometry(tmp_path, monkeypatch):
    """Pretend the satellites are ten times farther apart: the per-hop light-time check must stop the run."""
    from chronoroute.fwd import engine as engine_mod
    from chronoroute.fwd.topology import Topology
    real = Topology.node_ecef_km
    monkeypatch.setattr(Topology, "node_ecef_km", lambda self, node, k: 10.0 * real(self, node, k))
    with pytest.raises(engine_mod.InvariantViolation, match="distance / c"):
        run(tmp_path, "bad", base_doc(**{"scenario.duration_s": 1}))

"""Every scheme as real code on the shared engine, each checked against a closed form:

  chronoroute   byte-identical to `cr run` (the subclass changes nothing for it)
  O-T           stretch = 1 exactly while the packet stays in its send step; no blackhole
  LS-H          blackhole time = dead interval - (onset - last hello) + SPF delay (and BFD)
  SNAP          lag = telemetry delay + wait for the next upload
  LQ            flags a rate cut at the NEAR end, before ChronoRoute flags it downstream
  CRH-16        never flags, same paths as ChronoRoute flag-and-continue
  E2E           flags only at the destination
  FB1           reroutes at the first refresh after report + 50 ms; FB0 never does
  O-Q           avoids a slow link from the start; O-T does not
  LS-D          advertises at the end of its measurement window (+ SPF); min-delay ignores queues
plus conservation, invariants (all on), trace/1 validity, determinism and common random
numbers for every scheme."""

import copy
import hashlib

import numpy as np
import pytest

from chronoroute.baselines import keyed, params, run as brun
from chronoroute.baselines.engine import step_tolerance_ns
from chronoroute.eval import detection, load, metrics
from chronoroute.fwd import command, config, scenario as sm
from chronoroute.trace import reader

S = 1_000_000_000
MS = 1_000_000


def doc(**over):
    d = {"seed": 3, "scenario": {"kind": "walker", "preset": "C1", "duration_s": 8, "drain_s": 1,
                                 "chunk_steps": 20, "gsl": {"min_elevation_deg": 10}},
         "traffic": {"flows": [{"src": "London", "dst": "New York"}], "rate_pps": 100, "start_offset": 0},
         "forwarding": {"policy": "continue"},
         "output": {"trace": "sampled", "sample_every": 10, "invariants": "all"}}
    for k, v in over.items():
        node = d
        ks = k.split(".")
        for x in ks[:-1]:
            node = node.setdefault(x, {})
        node[ks[-1]] = copy.deepcopy(v)
    return d


def go(tmp_path, name, d, scheme, manifest=False):
    cfg = config.normalise(d)
    out = tmp_path / name
    s, written = brun.run_scheme(cfg, params.normalise_scheme(scheme), out, write_manifest=manifest)
    return load.load_run(out), s


@pytest.fixture(scope="module")
def link():
    """The middle ISL of the London -> New York path at t = 2 s (seed 3, C1)."""
    sc = sm.build_scenario(config.normalise(doc()))
    a, b = sc.resolve_on_path({"flow": 0, "position": "middle"}, 2 * S, False)
    li = sc.topo.link_index[(a, b)]
    path = sc.path_at(0, 2 * S)
    up = a if path.index(a) < path.index(b) else b          # upstream end of the flow
    return {"a": a, "b": b, "li": li, "up": up, "down": b if up == a else a,
            "link_a": int(sc.topo.link_a[li]), "n_links": sc.topo.n_links}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


# ------------------------------------------------------------------------- identity

def test_chronoroute_scheme_is_byte_identical_to_cr_run(tmp_path, link):
    d = doc(**{"forwarding.policy": "greedy", "forwarding.jitter": {"model": "j1", "mean_ns": 400000},
               "faults": [{"kind": "link_down", "link": [link["a"], link["b"]], "start_s": 2, "stop_s": 3},
                          {"kind": "slow_processing", "on_path": {"flow": 0, "kind": "node"},
                           "delta_ns": 4_000_000, "start_s": 4, "stop_s": 5}],
               "output.trace": "full"})
    cfg = config.normalise(d)
    command.run_config(cfg, tmp_path / "base", write_manifest=False)
    brun.run_scheme(cfg, params.normalise_scheme("chronoroute"), tmp_path / "scheme", write_manifest=False)
    for f in ("events.jsonl.gz", "packets.csv.gz", "schedule.csv.gz"):
        assert sha(tmp_path / "base" / f) == sha(tmp_path / "scheme" / f), f


# ------------------------------------------------------------------------- oracle

def test_oracle_topology_stretch_is_one(tmp_path, link):
    r, s = go(tmp_path, "ot", doc(), "o_t")
    st = metrics.stretch(r)
    assert st["n"] == s["counts"]["delivered"] == s["counts"]["sent"]
    ex = r.extras
    m = r.delivered & (ex["tol_ns"] == 0)
    assert m.sum() > 0.5 * r.n
    assert np.array_equal(ex["l_det_ns"][m], ex["oracle_ns"][m])          # exactly 1, in integer ns
    rest = r.delivered & ~m
    assert np.all(np.abs(ex["l_det_ns"][rest] - ex["oracle_ns"][rest]) <= ex["tol_ns"][rest])
    assert st["violations"] == 0 and st["hop_violations"] == 0 and st["n_path_not_in_send_graph"] == 0
    assert step_tolerance_ns(100 * MS) == 5340                           # ceil(16 km/s x 0.1 s / c) + 2 ns


def test_oracle_topology_knows_failures_instantly(tmp_path, link):
    f = [{"kind": "link_down", "link": [link["a"], link["b"]], "start_s": 2, "stop_s": 6}]
    r, s = go(tmp_path, "ot_f", doc(faults=f), "o_t")
    bh = metrics.blackhole(r, r.faults[0])
    # only a packet already sent towards the link before the onset can still be lost on it
    assert bh["losses"] <= 1 and bh["blackhole_ns"] < 30 * MS
    assert metrics.stretch(r)["violations"] == 0


def test_queue_oracle_avoids_a_slow_link_topology_oracle_does_not(tmp_path, link):
    f = [{"kind": "slow_processing", "link": [link["a"], link["b"]], "delta_ns": 30_000_000,
          "start_s": 2, "stop_s": 7}]
    rq, _ = go(tmp_path, "oq", doc(faults=f), "o_q")
    rt, _ = go(tmp_path, "ot2", doc(faults=f), "o_t")
    eq, _ = metrics.exposure(rq, rq.faults[0])
    et, _ = metrics.exposure(rt, rt.faults[0])
    sent_after = (rq.send_ns >= 2 * S) & (rq.send_ns < 6_900 * MS)   # reaching the link before 7 s
    assert eq[sent_after].sum() == 0                 # O-Q never sends into the slowness
    assert et[sent_after].sum() == sent_after.sum()  # O-T keeps the shortest (slow) path


# ------------------------------------------------------------------------- link state

def _ls_closed_form(link, scheme_ls, onset):
    """Knowledge time at the UPSTREAM end: last hello (or BFD packet) before the onset + dead
    interval + SPF (its own LSA needs no flooding)."""
    e_up = 0 if link["up"] == link["link_a"] else 1
    d_idx = 2 * link["li"] + (1 - e_up)              # the direction this end receives on
    if scheme_ls.get("bfd"):
        H, D = 100 * MS, 300 * MS
        ph = int(keyed.phases_ns(3, "ls_bfd_phase", 2 * link["n_links"], H)[d_idx])
    else:
        hello, dead, _minls, _src = params.LS_PRESETS[scheme_ls.get("preset", "olsr_leo")]
        H, D = int(hello) * S, int(dead) * S
        ph = int(keyed.phases_ns(3, "ls_hello_phase", 2 * link["n_links"], H)[d_idx])
    r = ph + ((onset - 1 - ph) // H) * H
    return r + D + 50 * MS - onset, H, D


@pytest.mark.parametrize("ls,dur,pps", [({"fault_detection": "hello"}, 8, 100),
                                        ({"fault_detection": "hello", "bfd": True}, 8, 100),
                                        ({"fault_detection": "hello", "preset": "olsr"}, 10, 100),
                                        ({"fault_detection": "hello", "preset": "ospf"}, 46, 10)])
def test_ls_h_blackhole_equals_dead_interval(tmp_path, link, ls, dur, pps):
    """SILENT failures (sensitivity option): noticed only by missing hellos / BFD."""
    onset = 2 * S
    f = [{"kind": "link_down", "link": [link["a"], link["b"]], "start_s": 2, "stop_s": dur - 1}]
    r, s = go(tmp_path, "lsh", doc(faults=f, **{"scenario.duration_s": dur, "traffic.rate_pps": pps}),
              {"name": "ls_h", "ls": ls})
    bh = metrics.blackhole(r, r.faults[0])
    k_rel, H, D = _ls_closed_form(link, ls, onset)
    gap = S // pps
    assert D - H + 50 * MS < k_rel <= D + 50 * MS
    assert k_rel - gap < bh["blackhole_ns"] <= k_rel, (bh, k_rel)
    assert bh["losses"] == pytest.approx(k_rel / gap, abs=2)
    # after the upstream node knows, nothing more is lost there
    assert s["drops"].get("in_flight_link_down", 0) == bh["losses"]


@pytest.mark.parametrize("carrier_ms", [0, 20])
def test_one_failure_visibility_model_for_every_scheme(tmp_path, link, carrier_ms):
    """Every scheme's node notices a failed link after the SAME carrier detection delay
    (forwarding.carrier_detect_ms; major finding: LS-H used to wait the dead interval while
    ChronoRoute and SNAP saw the failure at once). Losses on the link then stop at
      ChronoRoute (step 7 + detour)     onset + carrier
      SNAP (its +Grid detour)           onset + carrier
      LS-H (its own LSA + SPF delay)    onset + carrier + 50 ms
    (1000 pps: 1 ms between packets)."""
    f = [{"kind": "link_down", "link": [link["a"], link["b"]], "start_s": 2, "stop_s": 6}]
    d = doc(faults=f, **{"traffic.rate_pps": 1000, "forwarding.carrier_detect_ms": carrier_ms,
                         "forwarding.fallback": "grid_detour", "output.trace": "none"})
    c = carrier_ms * MS
    gap = MS
    out = {}
    for name, sch in (("cr", "chronoroute"), ("snapd", {"name": "snap", "snap": {"at_dead_next_hop": "detour"}}),
                      ("lsh", "ls_h")):
        r, _s = go(tmp_path, f"vis{carrier_ms}_{name}", d, sch)
        out[name] = metrics.blackhole(r, r.faults[0])
        assert r.run["scheme"]["failure_visibility"]["carrier_detect_ns"] == c
        assert r.run["engine"]["carrier_detect_ns"] == c
    for name in ("cr", "snapd"):
        bh = out[name]
        if c == 0:
            assert bh["losses"] == 0, (name, bh)          # only packets sent before the onset were lost
        else:
            assert c - gap < bh["blackhole_ns"] <= c, (name, bh)
            assert bh["losses"] == pytest.approx(c / gap, abs=2)
    bh = out["lsh"]
    assert c + 50 * MS - gap < bh["blackhole_ns"] <= c + 50 * MS, bh


def test_ls_h_is_blind_to_slowness(tmp_path, link):
    f = [{"kind": "slow_processing", "link": [link["a"], link["b"]], "delta_ns": 30_000_000,
          "start_s": 2, "stop_s": 7}]
    r, s = go(tmp_path, "lsh_slow", doc(faults=f), "ls_h")
    ex, _ = metrics.exposure(r, r.faults[0])
    sent_after = (r.send_ns >= 2 * S) & (r.send_ns < 6_900 * MS)
    assert ex[sent_after].all() and not r.detections


@pytest.mark.parametrize("variant", ["avg", "min"])
def test_ls_d_advertises_at_window_end(tmp_path, link, variant):
    f = [{"kind": "slow_processing", "link": [link["a"], link["b"]], "delta_ns": 30_000_000,
          "start_s": 2, "stop_s": 7}]
    sch = {"name": "ls_d", "ls_d": {"window_s": 1, "probe_ms": 100, "variant": variant}}
    r, s = go(tmp_path, "lsd", doc(faults=f), sch)
    metric = [d for d in r.detections if d["kind"] == "metric"]
    assert metric
    e_up = 0 if link["up"] == link["link_a"] else 1
    ph = int(keyed.phases_ns(3, "lsd_window_phase", 2 * link["n_links"], 1 * S)[2 * link["li"] + e_up])
    first_window_end = ph + ((2 * S - ph) // S + 1) * S    # first window end after the onset
    mine = [d for d in metric if d["end"] == e_up]
    # the origin installs the new metric at window end + SPF (it is the first node to know)
    assert mine[0]["t_ns"] in (first_window_end + 50 * MS, first_window_end + S + 50 * MS)
    if variant == "min":
        # the minimum over a window that started before the onset is still the light time;
        # the first window entirely inside the fault reports the full 30 ms
        assert mine[0]["value"] == 30_000_000
    tt = metrics.time_to_mitigation(r, r.faults[0])
    assert tt["observed"] and tt["ttm_ns"] <= 2 * S


def test_ls_d_min_variant_ignores_queues(tmp_path, link):
    f = [{"kind": "rate_cut", "link": [link["a"], link["b"]], "factor": 0.0002, "start_s": 2, "stop_s": 6}]
    d = doc(faults=f, **{"traffic.rate_pps": 200})
    ravg, _ = go(tmp_path, "lsd_avg", d, {"name": "ls_d", "ls_d": {"window_s": 1, "variant": "avg"}})
    rmin, _ = go(tmp_path, "lsd_min", d, {"name": "ls_d", "ls_d": {"window_s": 1, "variant": "min"}})
    assert any(x["kind"] == "metric" and x["value"] > 0 for x in ravg.detections)
    # with queueing only (no fixed extra delay), the per-window minimum stays at the light
    # time until the queue never empties during a whole window (RFC 7471 section 1: a
    # propagation-delay measurement should not include queuing)
    early = [x for x in rmin.detections if x["kind"] == "metric" and x["t_ns"] < 3 * S + 100 * MS]
    assert all(x["value"] < 1_000_000 for x in early)


# ------------------------------------------------------------------------- snap

@pytest.mark.parametrize("update_s,expect_s", [(1, "4.0"), (0.1, "3.1")])
def test_snap_lag_is_telemetry_plus_upload_wait(tmp_path, link, update_s, expect_s):
    onset = 2_050 * MS
    f = [{"kind": "link_down", "link": [link["a"], link["b"]], "start_s": 2.05, "stop_s": 7}]
    sch = {"name": "snap", "snap": {"telemetry_s": 1, "update_s": update_s}}
    r, s = go(tmp_path, "snap", doc(faults=f), sch)
    bh = metrics.blackhole(r, r.faults[0])
    known = int(float(expect_s) * S)                 # next upload after onset + 1 s telemetry
    assert known - onset - 10 * MS < bh["blackhole_ns"] <= known - onset
    tel = [x for x in r.control["ledger"]["by_type"] if x["type"] == "snap_telemetry"]
    assert tel[0]["messages"] == 4                   # both ends, at the failure and at the repair
    up = r.control["ledger"]["by_medium"]["uplink"]
    assert up["bytes"] > 0


def test_snap_detour_avoids_the_loss(tmp_path, link):
    f = [{"kind": "link_down", "link": [link["a"], link["b"]], "start_s": 2.05, "stop_s": 7}]
    r, s = go(tmp_path, "snapd", doc(faults=f, **{"output.trace": "full"}),
              {"name": "snap", "snap": {"telemetry_s": 1, "update_s": 1, "at_dead_next_hop": "detour"}})
    assert metrics.blackhole(r, r.faults[0])["losses"] == 0 and s["counts"]["delivered"] == s["counts"]["sent"]
    assert s["fallback_reasons"]["next_link_down"] > 0
    # trace/1 order: the hop (next = null) comes first, then the fallback naming the detour node
    assert reader.validate_run(tmp_path / "snapd") == []
    seen = 0
    for evs in reader.journeys(tmp_path / "snapd").values():
        for i, e in enumerate(evs):
            if e["ev"] == "fallback":
                prev = evs[i - 1]
                assert prev["ev"] in ("hop", "send") and prev["t"] == e["t"] and prev["next"] is None
                assert e["next"] is not None and e["reason"] == "next_link_down"
                seen += 1
    assert seen >= s["fallback_reasons"]["next_link_down"] > 0      # a packet may detour twice
    # and the labels know these packets met a link that a FAULT had down (not a stale one)
    lab = metrics.packet_labels(r)
    assert (lab == 1).sum() >= seen and (lab == 2).sum() == 0


# ------------------------------------------------------------------------- lq, crh16, e2e

def test_lq_detects_rate_cut_at_the_near_end(tmp_path, link):
    f = [{"kind": "rate_cut", "link": [link["a"], link["b"]], "factor": 0.0002, "start_s": 2, "stop_s": 4}]
    d = doc(faults=f, **{"traffic.rate_pps": 200})
    rl, sl = go(tmp_path, "lq", d, {"name": "lq", "lq": {"q_th_ms": 1}})
    rc, _ = go(tmp_path, "cr", d, "chronoroute")
    fl = detection.lq_flags(rl)
    fc = detection.deadline_flags(rc)
    i_l = np.flatnonzero(fl.flagged)
    i_c = np.flatnonzero(fc.flagged)
    assert i_l.size > 0 and i_c.size > 0
    assert set(zip(fl.a[i_l].tolist(), fl.b[i_l].tolist())) == {(link["up"], link["down"])}
    assert set(fl.node[i_l].tolist()) == {link["up"]}                   # the near end
    assert set(fc.node[i_c].tolist()) == {link["down"]}                 # ChronoRoute: the far end
    assert fl.time[i_l].min() >= 2 * S and fl.time[i_l].min() < fc.time[i_c].min()
    assert not np.any(fl.flagged & (rl.send_ns < 2 * S - 100 * MS))      # nothing before the cut


def test_lq_detour_moves_packets_off_the_queue(tmp_path, link):
    f = [{"kind": "rate_cut", "link": [link["a"], link["b"]], "factor": 0.0002, "start_s": 2, "stop_s": 4}]
    d = doc(faults=f, **{"traffic.rate_pps": 200, "forwarding.fallback": "grid_detour"})
    rf, _ = go(tmp_path, "lqf", d, {"name": "lq", "lq": {"action": "flag"}})
    rd, sd = go(tmp_path, "lqd", d, {"name": "lq", "lq": {"action": "detour"}})
    assert rd.control["lq"]["detours"] > 0
    ef, _ = metrics.exposure(rf, rf.faults[0])
    ed, _ = metrics.exposure(rd, rd.faults[0])
    assert ed.sum() < ef.sum()


def test_crh16_never_flags_and_keeps_the_paths(tmp_path, link):
    f = [{"kind": "slow_processing", "link": [link["a"], link["b"]], "delta_ns": 20_000_000,
          "start_s": 2, "stop_s": 5}]
    d = doc(faults=f)
    r16, s16 = go(tmp_path, "crh16", d, "crh16")
    rcr, scr = go(tmp_path, "cr", d, "chronoroute")
    assert scr["counts"]["late"] > 0 and s16["counts"]["late"] == 0
    assert np.all(r16.first_late == -1) and np.all(r16.dev == 0)
    for i in range(r16.n):
        assert np.array_equal(r16.paths[i], rcr.paths[i])
    # the wire carries CRH-16 (pad8(4 + 2n)), not the internal T-CRH
    h = r16.hops[0]
    assert r16.extras["hdr_bytes"][0] == -(-(4 + 2 * h) // 8) * 8


def test_e2e_flags_only_at_the_destination(tmp_path, link):
    f = [{"kind": "slow_processing", "link": [link["a"], link["b"]], "delta_ns": 20_000_000,
          "start_s": 2, "stop_s": 5}]
    r, s = go(tmp_path, "e2e", doc(faults=f), {"name": "e2e", "e2e": {"feedback": False}})
    late = np.flatnonzero(r.first_late >= 1)
    assert late.size > 0
    assert np.all(r.first_late[late] == r.hops[late])                  # hop index of the destination
    assert np.all(r.extras["e2e_late"][late] == 1)
    fl = detection.e2e_flags(r)
    assert set(fl.node[fl.flagged].tolist()) == {r.flows[0]["dst_node"]} and not fl.localised


# ------------------------------------------------------------------------- feedback

def test_fb1_reroutes_at_the_next_refresh(tmp_path, link):
    f = [{"kind": "slow_processing", "link": [link["a"], link["b"]], "delta_ns": 30_000_000,
          "start_s": 2, "stop_s": 7}]
    r0, s0 = go(tmp_path, "fb0", doc(faults=f), "chronoroute")
    r1, s1 = go(tmp_path, "fb1", doc(faults=f),
                {"name": "chronoroute", "feedback": {"mode": "fb1", "penalty": "inf", "hold_s": 10}})
    t0 = metrics.time_to_mitigation(r0, r0.faults[0])
    t1 = metrics.time_to_mitigation(r1, r1.faults[0])
    assert not t0["observed"]
    # first late packet just after 2 s, report +50 ms, next refresh (1 s) at 3 s
    assert t1["observed"] and t1["ttm_ns"] == 1 * S
    act = r1.control["penalties"]["first_activation_ns"]
    assert act == [[3 * S, link["li"]]]
    assert r1.control["ledger"]["by_medium"]["downlink"]["messages"] == r1.control["feedback"]["reports"] > 0
    # the planned rows from 3 s on avoid the link
    for (fl, start), row in r1.schedule.items():
        crosses = any({u, v} == {link["a"], link["b"]} for u, v in zip(row["path"][:-1], row["path"][1:]))
        assert crosses == (start < 3000), start


def test_e2e_feedback_penalises_the_late_path(tmp_path, link):
    f = [{"kind": "slow_processing", "link": [link["a"], link["b"]], "delta_ns": 30_000_000,
          "start_s": 2, "stop_s": 7}]
    r, s = go(tmp_path, "e2efb", doc(faults=f), {"name": "e2e", "e2e": {"penalty": "inf"}})
    tt = metrics.time_to_mitigation(r, r.faults[0])
    assert tt["observed"] and tt["ttm_ns"] == 1 * S
    assert r.control["ledger"]["by_medium"]["ground"]["bytes"] > 0
    assert link["li"] in [li for _t, li in r.control["penalties"]["first_activation_ns"]]


# ------------------------------------------------------------------------- every scheme

ALL = ["chronoroute", "crh16", "e2e", "lq", "o_t", "o_q", "snap", "ls_h", "ls_d"]


@pytest.mark.parametrize("name", ALL)
def test_every_scheme_conserves_packets_and_validates(tmp_path, link, name):
    f = [{"kind": "link_down", "link": [link["a"], link["b"]], "start_s": 2, "stop_s": 3},
         {"kind": "link_renewal", "unavailability": 0.02, "mttr_s": 0.5}]
    d = doc(faults=f, **{"traffic.flows": [{"src": "London", "dst": "New York"},
                                           {"src": "Tokyo", "dst": "Los Angeles"}],
                        "scenario.duration_s": 4, "forwarding.jitter": {"model": "j1", "mean_ns": 400000}})
    r, s = go(tmp_path, name, d, name, manifest=True)
    assert s["conservation"]["ok"] and s["invariants"]["violations"] == 0
    assert s["invariants"]["checked_packets"] == s["counts"]["sent"]
    assert reader.validate_run(tmp_path / name) == []
    from chronoroute import provenance
    m = provenance.validate_manifest(tmp_path / name / "manifest.json")
    assert m["labels"]["control_byte_models"] == "MODELLED"
    st = metrics.stretch(r)
    assert st["violations"] == 0 and st["hop_violations"] == 0


def test_common_random_numbers_and_determinism(tmp_path, link):
    d = doc(**{"forwarding.jitter": {"model": "j1", "mean_ns": 400000}, "traffic.model": "poisson",
               "scenario.duration_s": 3})
    runs = {n: go(tmp_path, n, d, n)[0] for n in ("chronoroute", "ls_h", "snap")}
    base = runs["chronoroute"]
    for r in runs.values():
        assert np.array_equal(r.send_ns, base.send_ns) and np.array_equal(r.flow, base.flow)
    again, _ = go(tmp_path, "ls_h_again", d, "ls_h")
    for f in ("packets.csv.gz", "scheme_packets.csv.gz", "events.jsonl.gz", "control.json"):
        assert sha(tmp_path / "ls_h" / f) == sha(tmp_path / "ls_h_again" / f), f


def test_chronoroute_counts_its_satellite_uploads(tmp_path, link):
    """ChronoRoute's uplink must not be 0 bytes. Every satellite is
    sent its CRH-FIB + station table every fib_refresh_s and (with a fallback) its own and its
    laser partners' element sets every ephemeris_upload_s, at keyed phases; uplink to the nearest
    satellite with a ground link, then h - 1 laser relay hops. Checked against an independent
    count (one BFS per station, not the multi-source BFS the code uses)."""
    from chronoroute.baselines.engine import SchemeEngine
    from chronoroute.baselines.paths import bfs_hops
    d = doc(**{"scenario.duration_s": 3, "traffic.rate_pps": 10, "output.trace": "none"})
    sch = params.normalise_scheme({"name": "chronoroute", "crh_state": {"fib_refresh_s": 1, "ephemeris_upload_s": 2}})
    r, _s = go(tmp_path, "crhst", d, sch)
    cfg = config.normalise(d)
    sc = sm.build_scenario(cfg)
    eng = SchemeEngine(sc, sch)
    tr = eng.truth
    S_, n_gs, end = tr.n_sats, tr.n - tr.n_sats, sc.end_ns
    partners = np.bincount(np.concatenate([tr.a[:tr.n_isl], tr.b[:tr.n_isl]]), minlength=tr.n)[:S_]
    size = {"crh_fib_refresh": 56 + (partners + n_gs) * 4 + n_gs * 12, "ephemeris_upload": 56 + (1 + partners) * 140}
    want = {"uplink": {}, "isl": {}}
    count = {"crh_fib_refresh": 0, "ephemeris_upload": 0}
    for name, comp, period in (("crh_fib_refresh", "crh_fib_phase", S), ("ephemeris_upload", "crh_eph_phase", 2 * S)):
        for sat, ph in enumerate(keyed.phases_ns(3, comp, S_, period).tolist()):
            for t in range(ph, end, period):
                g = tr.graph(tr.step_of(t), 0, 1)
                hops = [x for x in (bfs_hops(g, gs)[sat] for gs in range(S_, tr.n)) if x is not None]
                assert hops, "every C1 satellite reaches a station here"
                h = min(hops)
                count[name] += 1
                want["uplink"][name] = want["uplink"].get(name, 0) + int(size[name][sat])
                if h > 1:
                    want["isl"][name + "_relay"] = want["isl"].get(name + "_relay", 0) + int(size[name][sat]) * (h - 1)
    got = {"uplink": {}, "isl": {}}
    for x in r.control["ledger"]["by_type"]:
        if x["type"].startswith(("crh_fib_refresh", "ephemeris_upload")):
            got[x["medium"]][x["type"]] = x["bytes"]
    assert count["crh_fib_refresh"] > S_ and count["ephemeris_upload"] > 0
    st = r.control["crh_state_uploads"]
    assert (st["crh_fib_refresh"], st["ephemeris_upload"], st["unreachable"]) == (count["crh_fib_refresh"],
                                                                                count["ephemeris_upload"], 0)
    assert got == want and r.control["ledger"]["by_medium"]["uplink"]["bytes"] > 0
    assert r.control["state"]["crh_fib_bytes_mean"] == round(float(((partners + n_gs) * 4).mean()), 1)
    # the amortised (steady-state) rate: sum of size / period, relays with the hops at step 0
    g0 = tr.graph(0, 0, 1)
    h0 = [min(x for x in (bfs_hops(g0, gs)[s] for gs in range(S_, tr.n)) if x is not None) for s in range(S_)]
    up = sum(int(size["crh_fib_refresh"][s]) / 1 + int(size["ephemeris_upload"][s]) / 2 for s in range(S_))
    isl = sum((int(size["crh_fib_refresh"][s]) / 1 + int(size["ephemeris_upload"][s]) / 2) * (h0[s] - 1)
              for s in range(S_))
    steady = r.control["crh_state_uploads"]["steady_state_bytes_per_s"]
    assert steady["uplink"] == pytest.approx(up, abs=1e-3) and steady["isl"] == pytest.approx(isl, abs=1e-3)
    # the defaults (4 h, the SupGP refresh cadence) charge the right FRACTION of satellites in a
    # short run, and count: false turns the charge off (the state report stays)
    r0, _ = go(tmp_path, "crhst0", d, {"name": "chronoroute", "crh_state": {"count": False}})
    assert not any(x["type"].startswith(("crh_fib", "ephemeris")) for x in r0.control["ledger"]["by_type"])
    assert r0.control["state"]["crh_fib_bytes_mean"] > 0


def test_ls_h_hello_bytes_match_the_analytic_count(tmp_path, link):
    d = doc(**{"scenario.duration_s": 2, "traffic.rate_pps": 10})
    r, s = go(tmp_path, "hello", d, "ls_h")
    sc = sm.build_scenario(config.normalise(d))
    n_steps = sc.n_steps
    H = 1 * S
    ph = keyed.phases_ns(3, "ls_hello_phase", 2 * sc.topo.n_links, H)
    total = 0
    for k in range(n_steps):
        ch = sc.topo.chunk_of_step(k)
        up = ch.up[:, k - ch.k0] & (ch.prop[:, k - ch.k0] > 0)
        t0, t1 = k * 100 * MS, min((k + 1) * 100 * MS, sc.end_ns)      # nothing after the run
        for li in np.flatnonzero(up).tolist():
            for dd in (0, 1):
                p = int(ph[2 * li + dd])
                total += sum(1 for n in range(0, 10) if t0 <= p + n * H < t1)
    got = sum(x["messages"] for x in r.control["ledger"]["by_type"] if x["type"] == "hello")
    assert got == total
    assert sum(x["bytes"] for x in r.control["ledger"]["by_type"] if x["type"] == "hello") == 80 * total


@pytest.mark.parametrize('background',['none','fluid','poisson'])
@pytest.mark.parametrize('kind',['rate_cut','arq','slow_processing','link_down'])
def test_queue_oracle_search_optimization_preserves_packets_and_control(tmp_path,monkeypatch,link,background,kind):
    import chronoroute.baselines.engine as engine_module
    from chronoroute.baselines.paths import lazy_path
    import json
    faults={'rate_cut':dict(factor=.002),'arq':dict(loss=.3,max_retries=3,retry_extra_ns=500000),
            'slow_processing':dict(delta_ns=4000000),'link_down':{}}
    fault=dict(kind=kind,link=[link['a'],link['b']],start_s=2,stop_s=3,**faults[kind])
    d=doc(**{'scenario.duration_s':4,'faults':[fault],
             'forwarding.background':{'model':background,'rho':.3,'links':'isl'},
             'forwarding.jitter':{'model':'j1','mean_ns':400000}})
    scheme=params.normalise_scheme({'name':'o_q','outputs':{'stretch_oracle':False}})
    cfg=config.normalise(d)
    brun.run_scheme(cfg,scheme,tmp_path/'optimized',write_manifest=False)
    called=[]
    def reference(*args,**kwargs):
        called.append(kwargs.get('lower_bound'))
        return lazy_path(*args)
    monkeypatch.setattr(engine_module,'lazy_path',reference)
    brun.run_scheme(cfg,scheme,tmp_path/'reference',write_manifest=False)
    assert called and (all(h is not None for h in called) if background!='poisson' else all(h is None for h in called))
    for name in ('packets.csv.gz','scheme_packets.csv.gz','events.jsonl.gz','scheme_events.csv.gz','schedule.csv.gz','control.json'):
        assert (tmp_path/'optimized'/name).read_bytes()==(tmp_path/'reference'/name).read_bytes(),name
    for name in ('optimized','reference'):
        summary=json.loads((tmp_path/name/'summary.json').read_text())
        assert summary['conservation']['ok'] and summary['invariants']['violations']==0

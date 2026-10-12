"""Python side of the website's route parity check (tools/web_parity.py).

The TypeScript side is web/tests/route-parity.test.ts. Here we check that what the parity
file claims about Python is true: every pair is exactly what `cr route` computes at the
snapshot's fetched_utc, the header/packet/pcap bytes are consistent with the reference
encoders, the positions frame is the one the router used, and the file is deterministic and
carries a valid provenance manifest.
"""

import importlib.util
import json
import math
import struct
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from chronoroute import labels, proto, provenance
from chronoroute.data import cities as cities_mod, snapshot
from chronoroute.route import command as route_cmd, scheduler, sids
from chronoroute.topo import geometry
from chronoroute.trace import pcap

REPO = Path(__file__).resolve().parents[2]
PINNED = REPO / "data" / "pinned" / "20261010T1358Z-celestrak"


def _load_tool():
    spec = importlib.util.spec_from_file_location("tools_web_parity", REPO / "tools" / "web_parity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wp = _load_tool()


@pytest.fixture(scope="module")
def fleet():
    return snapshot.load_pinned(PINNED, "supgp")


@pytest.fixture(scope="module")
def doc(fleet):
    return wp.compute_parity(fleet)


def test_canonical_pairs_are_twenty_distinct_known_city_pairs():
    names = {c.name for c in cities_mod.load_cities()}
    assert len(wp.CANONICAL_PAIRS) == 20
    assert len(set(wp.CANONICAL_PAIRS)) == 20
    for src, dst in wp.CANONICAL_PAIRS:
        assert src in names and dst in names and src != dst


def test_header_facts(doc, fleet):
    assert doc["schema"] == wp.SCHEMA
    assert doc["t_utc"] == fleet.fetched_utc == "2026-10-10T14:02:22Z"
    assert int(doc["t_gps_ns"]) == scheduler.utc_ns_to_gps_ns(fleet.fetched_ns)
    assert doc["slack"] == "1.5" and doc["unit_code"] == 1 and doc["processing_ns"] == geometry.PROCESSING_NS
    assert doc["labels"] == dict(labels.TABLE)
    # The raw download's sha256 (the served-snapshot run checks the website manifest against it).
    sums = (PINNED / "SHA256SUMS").read_text(encoding="utf-8")
    assert f"{doc['sha256_raw']} *starlink_supgp.json" in sums.splitlines()
    reach = [p for p in doc["pairs"] if p["reachable"]]
    # Reykjavik and Oslo are north of what the 53 deg shell covers at a 25 deg mask.
    assert [(p["src"], p["dst"]) for p in doc["pairs"] if not p["reachable"]] == [("Reykjavik", "Oslo")]
    assert len(reach) == 19


def test_every_pair_is_exactly_what_cr_route_computes(doc, fleet):
    """At fetched_utc the parity file and `cr route` must agree byte for byte (same code path)."""
    registry = sids.SidRegistry.load()
    for p in doc["pairs"]:
        _lines, entry, sc = route_cmd.route_report(fleet, p["src"], p["dst"], fleet.fetched_ns, slack="1.5",
                                                  shell_id=doc["shell_id"], registry=registry)
        if not p["reachable"]:
            assert entry is None, p["src"]
            continue
        assert list(entry.path) == p["path_nodes"]
        assert sum(entry.hop_delays_ns) == p["cost_ns"]
        assert entry.header_for_packet(fleet.fetched_ns).hex() == p["header_hex"]
        assert entry.template.hex() == p["template_hex"]
        assert [int(s) for s in entry.sids_fwd] == p["sids_fwd"]
        assert [int(n) for n in sc.sat_norad] == doc["frame"]["norad"]


def test_headers_budgets_and_delays_are_consistent(doc):
    frame = np.array(doc["frame"]["ecef_km"], dtype=float)
    city = {k: np.array(v) for k, v in doc["frame"]["city_ecef_km"].items()}
    n_sats = len(doc["frame"]["norad"])
    for p in (q for q in doc["pairs"] if q["reachable"]):
        hdr = proto.TcrhHeader.decode(bytes.fromhex(p["header_hex"]))
        h = len(p["sids_fwd"])
        assert hdr.num_hops == hdr.segments_left == h
        assert list(hdr.sids_fwd) == p["sids_fwd"]
        assert p["sids_fwd"][-1] == proto.ground_station_sid(p["dst_g"])
        assert hdr.epoch_base == proto.epoch_base_at_ingress(int(doc["t_gps_ns"]), 1)
        # cumulative budgets: ceil(3/2 * running sum), and the header's deltas encode them
        running, budgets = 0, []
        for d in p["hop_delays_ns"]:
            running += d
            budgets.append(math.ceil(Fraction(3, 2) * running))
        assert budgets == p["budgets_ceil_ns"]
        assert list(hdr.deltas_fwd) == list(proto.encode_deltas(budgets, 1)[0])
        # every hop delay is light time (nearest ns) + 0.5 ms over the frame's own positions
        pos = []
        for node in p["path_nodes"]:
            if node < n_sats:
                pos.append(frame[node])
            else:
                pos.append(city[p["src"] if node == n_sats else p["dst"]])
        for k, (a, b) in enumerate(zip(pos[:-1], pos[1:])):
            prop = int(geometry.propagation_ns(np.linalg.norm(b - a)))
            assert prop == p["prop_ns"][k]
            assert p["hop_delays_ns"][k] == prop + geometry.PROCESSING_NS
        assert sum(p["hop_delays_ns"]) == p["cost_ns"]


def test_packet_and_pcap_bytes(doc):
    t_gps = int(doc["t_gps_ns"])
    for p in (q for q in doc["pairs"] if q["reachable"]):
        pkt = bytes.fromhex(p["packet_hex"])
        rh = bytes.fromhex(p["header_hex"])
        assert pkt[0] >> 4 == 6 and pkt[6] == 43                          # IPv6, Next Header = Routing
        assert pkt[8:24] == pcap.HOST_SRC.packed
        assert pkt[24:40] == pcap.sid_address(proto.ground_station_sid(p["src_g"]))
        assert pkt[40:40 + len(rh)] == rh
        udp = pkt[40 + len(rh):]
        final = pcap.sid_address(p["sids_fwd"][-1])
        assert pcap.internet_checksum(pcap.pseudo_header(pcap.HOST_SRC, final, len(udp), 17) + udp) == 0
        assert udp[8:] == pcap.payload_bytes(0, t_gps)
        cap = bytes.fromhex(p["pcap_hex"])
        magic, _vmaj, _vmin, _tz, _sig, _snap, linktype = struct.unpack("<IHHiIII", cap[:24])
        assert magic == pcap.MAGIC_NS and linktype == pcap.LINKTYPE_RAW
        sec, frac, incl, orig = struct.unpack("<IIII", cap[24:40])
        assert sec * 10**9 + frac == pcap.gps_to_pcap_ns(t_gps)
        assert incl == orig == len(pkt) and cap[40:] == pkt


def test_frame_positions_and_ms_epoch_reference(doc):
    full = np.array(doc["frame"]["ecef_km"], dtype=float)
    ms = np.array(doc["frame"]["ecef_ms_epoch_km"], dtype=float)
    diff_m = np.linalg.norm(full - ms, axis=1) * 1000
    # cutting EPOCH to whole milliseconds moves a satellite by at most ~7.6 m (one ms of flight)
    assert diff_m.max() < 8.0
    assert np.median(diff_m) > 0.0
    r = np.linalg.norm(full, axis=1)
    assert np.all((r > 6378.137 + 300) & (r < 6378.137 + 600))


def test_isl_down_pairs_are_pairs_of_the_published_file(doc):
    shell = next(s for s in doc["isl_grid4"]["shells"] if s["shell_id"] == doc["shell_id"])
    pairs = {tuple(x) for x in shell["intra"] + shell["cross"]}
    assert doc["frame"]["isl_down"]
    assert all(tuple(x) in pairs for x in doc["frame"]["isl_down"])


def test_written_file_is_deterministic_and_has_a_valid_manifest(doc, fleet, tmp_path):
    a = wp.write_parity(doc, tmp_path / "a", command=["test"], snapshot_dir=PINNED)
    # A second, independent computation over all 20 pairs (fresh fleet, fresh registry), not
    # the same in-memory doc written twice: compute_parity itself must be deterministic.
    fresh = wp.compute_parity(snapshot.load_pinned(PINNED, "supgp"))
    b = wp.write_parity(fresh, tmp_path / "b", command=["test"], snapshot_dir=PINNED)
    assert fresh is not doc and len(fresh["pairs"]) == 20
    assert a.read_bytes() == b.read_bytes()
    m = provenance.validate_manifest(tmp_path / "a")
    assert m["labels"] == labels.pick(*wp.LABEL_KEYS)
    assert [o["path"] for o in m["outputs"]] == [wp.PARITY_FILE]
    assert json.loads(a.read_text())["snapshot_id"] == "20261010T1358Z-celestrak"

"""
`cr trace from-ns3` (sim/chronoroute/trace/ns3_import.py) on the REAL course-milestone
small run (results/course-milestone/c5-463-10s-small-seed1, fault variant):
every path, latency, clock and deadline in the trace equals packets.csv, the
rebuilt header bytes agree with what ns-3 recorded, the trace loads in the viewer
and passes the engine's own trace validator, and a corrupted input is refused.

The run's bundle is taken from where the run manifest says (verified by sha256)
or rebuilt from its recorded recipe (deterministic, ~5 s) when it is not there.
"""

import gzip
import json
import shutil
from pathlib import Path

import pytest

from chronoroute import cli, provenance
from chronoroute.export import ns3_crosscheck as xc
from chronoroute.proto import tcrh, timebase
from chronoroute.trace import ns3_import
from chronoroute.viz import sources

REPO = Path(__file__).resolve().parents[2]
RUN = REPO / "results" / "course-milestone" / "c5-463-10s-small-seed1"


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    try:
        return ns3_import.find_bundle(RUN)
    except ns3_import.BundleMissing:
        return ns3_import.rebuild_bundle(RUN, tmp_path_factory.mktemp("bundle") / "c5-463-10s-small")


@pytest.fixture(scope="module")
def converted(tmp_path_factory, bundle):
    out = tmp_path_factory.mktemp("from-ns3") / "trace"
    summary = ns3_import.convert(RUN, out, bundle=bundle)
    return out, summary


@pytest.fixture(scope="module")
def packets():
    return xc.read_packets(RUN / "fault" / "packets.csv.gz")


def test_counts_match_the_ns3_run(converted, packets):
    _out, s = converted
    info = json.loads((RUN / "fault" / "run_info.json").read_text())
    assert s["probes"] == len(packets) == info["probes"] == 4000
    assert s["delivered"] == info["delivered"] == 4000 and s["dropped"] == 0
    assert s["late"] == info["late_packets"] == 598                 # docs/course-milestone.md 3.7
    assert s["policy"] == "continue" and s["faults"] == 1
    assert s["by_event"]["hop"] == sum(len(p["hop_t_ns"]) for p in packets)


def test_every_path_latency_clock_and_deadline_equals_packets_csv(converted, packets):
    out, _s = converted
    tr = sources.load_trace(out)
    assert tr.problems == [] and tr.tool == "ns-3"
    assert len(tr.packets) == len(packets)
    for p in packets:
        track = tr.packets[p["uid"]]
        assert track.flow == p["flow_id"]
        assert track.path == p["taken_path"]
        assert track.send.t == p["send_ns"]
        assert track.latency_ns == p["latency_ns"]
        assert track.outcome.t == p["rx_ns"]
        hops = track.arrivals
        assert [e.t for e in hops] == p["hop_t_ns"]
        assert [e.now_u for e in hops] == p["hop_now_u"]
        assert [e.deadline_u for e in hops] == p["hop_deadline_u"]
        assert [timebase.serial_diff(e.deadline_u, e.now_u) for e in hops] == p["hop_margin_u"]
        late = track.late_events
        if p["dev"]:
            assert len(late) == 1 and hops.index(next(h for h in hops if h.node == late[0].node)) + 1 \
                == p["first_late_hop"] == p["dev_hop"]
            assert track.outcome.flags & tcrh.FLAG_DEV
        else:
            assert late == [] and not track.outcome.flags & tcrh.FLAG_DEV


def test_rebuilt_header_bytes_agree_with_ns3(converted, packets):
    out, _s = converted
    tr = sources.load_trace(out)
    by_uid = {p["uid"]: p for p in packets}
    sampled = [t for t in tr.packets.values() if t.first_hex() is not None]
    assert len(sampled) >= 40 + 4 * 10                # every 100th + the first 10 of each flow
    assert any(t.is_late for t in sampled)            # the first late probes are sampled too
    for track in sampled:
        p = by_uid[track.pkt]
        h = p["num_hops"]
        send = tcrh.TcrhHeader.decode(bytes.fromhex(track.send.hex))
        assert send.epoch_base == p["epoch_base"] and send.segments_left == h - 1
        for k, e in enumerate(track.arrivals, 1):
            hdr = tcrh.TcrhHeader.decode(bytes.fromhex(e.hex))
            assert hdr.segments_left == h - k == e.sl   # as it arrived (spec/trace-v1.md)
            assert hdr.deadline(k) == e.deadline_u      # the bytes give the deadline ns-3 recorded
            assert hdr.flags == e.flags
        for late in track.late_events:              # bytes after the check: DEV set here
            after = tcrh.TcrhHeader.decode(bytes.fromhex(late.hex))
            assert after.is_dev and after.flags == late.flags and after.segments_left == late.sl
        final = tcrh.TcrhHeader.decode(bytes.fromhex(track.outcome.hex))
        assert bool(final.flags & tcrh.FLAG_DEV) == bool(p["dev"]) and final.dev_hop == p["dev_hop"]


def test_run_json_faults_positions_and_manifest(converted, bundle):
    out, _s = converted
    run = json.loads((out / "run.json").read_text())
    assert run["schema"] == "chronoroute.trace/1" and run["tool"] == "ns-3"
    assert run["t0_utc"] == "2026-10-10T14:00:00Z" and run["t0_gps_ns"] == 1475676018000000000
    assert run["bundle"] == str(bundle)
    assert run["positions"] == {"source": "bundle", "path": "bundle"}     # the copy in the run folder
    for name in ("positions.csv", "nodes.csv", "isl.csv", "scenario.json"):
        assert (out / "bundle" / name).read_bytes() == (Path(bundle) / name).read_bytes(), name
    (fault,) = run["faults"]
    assert fault["kind"] == "rate_cut" and fault["link"] == [1998, 2017]
    assert (fault["start_ns"], fault["stop_ns"]) == (4_000_000_000, 7_000_000_000)
    assert fault["params"]["rate_bps"] == 200_000 and fault["params"]["nominal_rate_bps"] == 10 ** 9
    assert fault["params"]["factor"] == "1/5000"
    assert set(run["labels"].values()) <= {"REAL", "DERIVED", "MODELLED"}
    m = provenance.validate_manifest(out)
    assert m["tool"] == "cr-trace-from-ns3" and {o["path"] for o in m["outputs"]} == \
        {"run.json", "events.jsonl.gz", "bundle/positions.csv", "bundle/nodes.csv", "bundle/isl.csv",
         "bundle/scenario.json"}
    assert m["snapshot"]["id"] == "20261010T1358Z-celestrak"


def test_engine_trace_validator_accepts_it(converted):
    reader = pytest.importorskip("chronoroute.trace.reader")
    out, _s = converted
    assert reader.validate_run(out) == []


def test_conversion_is_deterministic(converted, bundle, tmp_path):
    out, _s = converted
    again = tmp_path / "again"
    ns3_import.convert(RUN, again, bundle=bundle)
    for name in ("run.json", "events.jsonl.gz", "bundle/positions.csv", "bundle/isl.csv"):
        assert (again / name).read_bytes() == (out / name).read_bytes(), name


def test_viewer_loads_it_with_bundle_positions(converted):
    out, _s = converted
    data = sources.load_viewer_data(trace_dir=out)
    assert data.n_sats == 2847 and len(data.isl) == 5361 and "isl.csv" in data.isl.source
    assert isinstance(data.positions.primary, sources.BundlePositions)
    assert [c[0] for c in data.cities] == ["Chennai", "London", "Singapore"]


def test_trace_does_not_need_the_tmp_bundle(converted, tmp_path):
    """With the original bundle gone, positions and links come from the trace's own bundle/ copy."""
    out, _s = converted
    moved = tmp_path / "moved"
    shutil.copytree(out, moved)
    run = json.loads((moved / "run.json").read_text())
    run["bundle"] = str(tmp_path / "no-such-bundle")
    (moved / "run.json").write_text(json.dumps(run, indent=1))
    data = sources.load_viewer_data(trace_dir=moved)
    assert len(data.isl) == 5361 and data.isl.source == "bundle bundle/isl.csv"
    assert data.positions.primary.path == moved / "bundle" / "positions.csv"


def _copy_run(tmp_path, edit_row=None):
    """A copy of the run folder (manifest + fault variant) with one packets.csv value changed."""
    dst = tmp_path / "run"
    (dst / "fault").mkdir(parents=True)
    shutil.copy(RUN / "manifest.json", dst / "manifest.json")
    for name in ("run_info.json", "fault_log.csv"):
        shutil.copy(RUN / "fault" / name, dst / "fault" / name)
    with gzip.open(RUN / "fault" / "packets.csv.gz", "rt") as fh:
        lines = fh.read().splitlines()
    if edit_row is not None:
        lines = edit_row(lines)
    with gzip.open(dst / "fault" / "packets.csv.gz", "wt") as fh:
        fh.write("\n".join(lines) + "\n")
    return dst


def test_a_wrong_deadline_in_packets_csv_is_refused(tmp_path, bundle):
    def tamper(lines):
        header = lines[0].split(",")
        col = header.index("hop_deadline_u")
        row = lines[1].split(",")
        vals = row[col].split()
        vals[2] = str(int(vals[2]) + 1)
        row[col] = " ".join(vals)
        return [lines[0], ",".join(row)] + lines[2:]
    bad = _copy_run(tmp_path, tamper)
    with pytest.raises(ns3_import.ImportCheckError, match="hop 3: rebuilt deadline"):
        ns3_import.convert(bad, tmp_path / "out", bundle=bundle)


def test_a_changed_bundle_is_refused_with_the_rebuild_command(tmp_path, bundle):
    fake = tmp_path / "bundle"
    shutil.copytree(bundle, fake)
    with open(fake / "positions.csv", "a") as fh:
        fh.write("0,0,0.000,0.000,0.000\n")
    with pytest.raises(ns3_import.BundleMissing) as err:
        ns3_import.find_bundle(RUN, fake)
    assert "positions.csv sha256 differs" in str(err.value)
    assert "cr export bundle --snapshot data/pinned/20261010T1358Z-celestrak" in str(err.value)


def test_cli_command(tmp_path, bundle, capsys):
    code = cli.main(["trace", "from-ns3", str(RUN), "--out", str(tmp_path / "t"), "--bundle", str(bundle),
                     "--hex-every", "0", "--hex-first", "1", "--hex-late", "1"])
    assert code == 0
    text = capsys.readouterr().out
    assert "probes 4000: delivered 4000, dropped 0, late (DEV) 598" in text
    tr = sources.load_trace(tmp_path / "t")
    # the first probe of each of the 4 flows + the first late probe of the 2 flows that cross
    # the slowed link
    assert sum(1 for t in tr.packets.values() if t.first_hex() is not None) == 4 + 2

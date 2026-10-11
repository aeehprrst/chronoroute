"""Exact accounting against encoder bytes and independently constructed captures."""
import gzip
import importlib.util
import io
from pathlib import Path
import struct

import pytest

ROOT=Path(__file__).resolve().parents[2]
SPEC=importlib.util.spec_from_file_location('e02_account',ROOT/'experiments/E02/account.py')
e2=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(e2)


def test_sizes_have_both_denominators_and_actual_encoder_checks():
    rows=e2.size_rows()
    assert len(rows)==320
    assert {r['entries'] for r in rows}==set(range(1,41))
    for r in rows:
        assert r['added_bytes']==r['header_bytes']+(40 if r['mode']=='encap' else 0)
        assert r['reference_percent']==100*r['added_bytes']/1400
        assert r['final_percent']==100*r['added_bytes']/(1400+r['added_bytes'])
        assert r['encoder_violations']==0
    assert next(r for r in rows if r['entries']==8 and r['protocol']=='tcrh' and r['mode']=='source')['header_bytes']==40


def test_capture_checks_complete_frame_lengths_and_refuses_truncation(tmp_path):
    from chronoroute import proto
    from chronoroute.trace import pcap
    h=proto.TcrhHeader(17,1,16,1,0,10,(1,),(1,)).encode()
    frame=pcap._vector_frame(h,1_000_000,0,'test',sid_to_addr=pcap.sid_address,ingress_sid=1,src=pcap.HOST_SRC)
    b=io.BytesIO();w=pcap.PcapWriter(b,pcap.LINKTYPE_PPP);w.write(frame.packet,t_gps_ns=1_000_000)
    p=tmp_path/'capture.pcap.gz'
    p.write_bytes(gzip.compress(b.getvalue()))
    rows,info=e2.capture_rows(p)
    assert info['violations']==0 and info['tcrh_frames']==1 and rows[0]['l2_bytes']==2
    assert rows[0]['header_bytes']==len(h) and rows[0]['frame_bytes']==2+len(frame.packet)
    bad=bytearray(b.getvalue());struct.pack_into('<I',bad,24+12,len(frame.packet)+3)
    p.write_bytes(gzip.compress(bad))
    with pytest.raises(ValueError): e2.capture_rows(p)
    p.write_bytes(gzip.compress(b.getvalue()[:-1]))
    with pytest.raises(ValueError): e2.capture_rows(p)


def test_report_crossover_is_enumerated_not_assumed():
    rows=e2.size_rows();v=e2.verdict(rows)
    assert v['tcrh_more_than_crh16'] and v['tcrh_less_than_srh']
    assert v['crh32_larger_entries'] and v['crh32_ties'] and v['crh32_smaller_entries']
    assert all(vv>=1 for vv in v['crh32_ties'])


def test_capture_collection_main_validates_sources_and_outputs(tmp_path,monkeypatch):
    from chronoroute import proto,provenance
    from chronoroute.trace import pcap
    monkeypatch.setattr(e2,'REPO',tmp_path)
    monkeypatch.setattr(e2.e1,'validate_protocol',lambda:None)
    monkeypatch.setattr(e2.provenance,'git_state',lambda *a,**k:{'dirty':False,'sha':'0'*40})
    cfg=__import__('json').loads((ROOT/'experiments/E02/config.json').read_text())
    h=proto.TcrhHeader(17,1,16,1,0,0,(1,),(1,)).encode()
    frame=pcap._vector_frame(h,0,0,'unit-fixture',sid_to_addr=pcap.sid_address,ingress_sid=1,src=pcap.HOST_SRC)
    for relative in cfg['captures']:
        p=tmp_path/relative;p.parent.mkdir(parents=True,exist_ok=True)
        b=io.BytesIO();w=pcap.PcapWriter(b,pcap.LINKTYPE_PPP);w.write(frame.packet,t_gps_ns=0);p.write_bytes(gzip.compress(b.getvalue()))
    source=(tmp_path/cfg['captures'][0]).parent.parent
    provenance.write_manifest(source,tool='unit capture fixture',tool_version='1',command=['unit-fixture'],config={},seeds=[],
        outputs=[tmp_path/p for p in cfg['captures']],labels={})
    snapshot=tmp_path/'data/pinned/20261010T1358Z-celestrak';snapshot.mkdir(parents=True)
    (snapshot/'SHA256SUMS').write_text('')
    assert e2.main(['--out',str(tmp_path/'out')])==0
    m=provenance.validate_manifest(tmp_path/'out/manifest.json')
    assert m['extra']['complete'] and (tmp_path/'out/header-overhead.png').is_file()

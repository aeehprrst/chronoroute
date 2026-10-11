"""E2: exact header accounting and extraction from existing ns-3 captures."""
import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import struct
import sys

from chronoroute import __version__, labels, provenance, proto
from chronoroute.proto import sizes, crh
from chronoroute.trace.writer import write_json

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/E01'))
import campaign as e1


def _repo_relative(path):
    """Repository-relative POSIX path, so committed outputs carry no machine-specific prefix."""
    path=Path(path).resolve()
    return path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else str(path)


def size_rows():
    """Exact byte counts; validate available encoders, without calling SRH captured."""
    rows=[]
    for n in range(1,41):
        encoded={'tcrh':proto.TcrhHeader(17,n,16,n,0,0,tuple(range(1,n+1)),(1,)*n).encode(),
                 'crh16':crh.CrhHeader.from_forward(range(1,n+1),routing_type=5).encode(),
                 'crh32':crh.CrhHeader.from_forward(range(1,n+1),routing_type=6).encode()}
        for name in sizes.HEADERS:
            for mode in sizes.MODES:
                header=sizes.encapsulation_overhead(n,'source',name)
                added=sizes.encapsulation_overhead(n,mode,name)
                violations=int(name in encoded and (len(encoded[name])!=header or (encoded[name][1]+1)*8!=header))
                rows.append(dict(entries=n,protocol=name,mode=mode,header_bytes=header,added_bytes=added,
                    reference_bytes=1400,reference_percent=100*added/1400,
                    final_percent=100*added/(1400+added),encoder_checked=name in encoded,
                    encoder_violations=violations,label='DERIVED'))
    return rows


def capture_rows(path):
    """Read classic PPP/RAW pcap; refuse missing/truncated frames, check actual bytes."""
    data=gzip.decompress(Path(path).read_bytes()) if str(path).endswith('.gz') else Path(path).read_bytes()
    if len(data)<24:raise ValueError('truncated pcap header')
    magic=data[:4]
    if magic in (b'\x4d\x3c\xb2\xa1',b'\xd4\xc3\xb2\xa1'):endian='<'
    elif magic in (b'\xa1\xb2\x3c\x4d',b'\xa1\xb2\xc3\xd4'):endian='>'
    else:raise ValueError('unsupported pcap magic')
    _,major,minor,_,_,snaplen,linktype=struct.unpack_from(endian+'IHHiIII',data)
    if (major,minor)!=(2,4) or linktype not in (9,101):raise ValueError('unsupported pcap version/linktype')
    l2=2 if linktype==9 else 0
    rows=[];offset=24;frames=0;skipped=0
    while offset<len(data):
        if len(data)-offset<16:raise ValueError('truncated record header')
        sec,frac,cap,wire=struct.unpack_from(endian+'IIII',data,offset);offset+=16
        if cap!=wire or cap>snaplen or offset+cap>len(data):raise ValueError('truncated capture frame')
        frame=data[offset:offset+cap];offset+=cap;frames+=1
        if l2 and frame[:2]!=b'\x00\x57':skipped+=1;continue
        ip=frame[l2:]
        if len(ip)<40 or ip[0]>>4!=6:skipped+=1;continue
        if ip[6]!=43 or len(ip)<43 or ip[42]!=253:skipped+=1;continue
        h,consumed=proto.TcrhHeader.decode_prefix(ip[40:])
        if h.next_header!=17:raise ValueError('capture T-CRH upper layer is not UDP')
        udp=ip[40+consumed:]
        if len(udp)<8:raise ValueError('truncated UDP')
        udplen=int.from_bytes(udp[4:6],'big');payload=udplen-8
        predicted=l2+40+sizes.tcrh_size(h.num_hops)+8+payload
        violation=int(payload<0 or len(udp)!=udplen or len(ip)!=40+int.from_bytes(ip[4:6],'big') or
                      consumed!=(ip[41]+1)*8 or consumed!=sizes.tcrh_size(h.num_hops) or predicted!=wire)
        rows.append(dict(capture=_repo_relative(path),frame=frames,entries=h.num_hops,linktype=linktype,l2_bytes=l2,
                         ipv6_bytes=40,header_bytes=consumed,udp_bytes=8,payload_bytes=payload,
                         frame_bytes=wire,predicted_frame_bytes=predicted,violations=violation,label='REAL'))
    return rows,dict(frames=frames,tcrh_frames=len(rows),skipped_frames=skipped,violations=sum(r['violations'] for r in rows),
                     linktype=linktype,l2_bytes=l2)


def verdict(rows):
    """Enumerate padding ties and all crossover domains, rather than interpolate."""
    by={(r['entries'],r['protocol']):r['header_bytes'] for r in rows if r['mode']=='source'}
    return dict(tcrh_more_than_crh16=all(by[n,'tcrh']>by[n,'crh16'] for n in range(1,41)),
                tcrh_less_than_srh=all(by[n,'tcrh']<by[n,'srh'] for n in range(1,41)),
                crh32_larger_entries=[n for n in range(1,41) if by[n,'crh32']>by[n,'tcrh']],
                crh32_ties=[n for n in range(1,41) if by[n,'crh32']==by[n,'tcrh']],
                crh32_smaller_entries=[n for n in range(1,41) if by[n,'crh32']<by[n,'tcrh']],
                encoder_violations=sum(r['encoder_violations'] for r in rows))


def plot(out,rows):
    """Standalone figure generated from the saved exact table."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(9,5))
    for name in sizes.HEADERS:
        r=[x for x in rows if x['protocol']==name and x['mode']=='source']
        ax.plot([x['entries'] for x in r],[x['header_bytes'] for x in r],label=name)
    ax.set(xlabel='Encoded entries',ylabel='Source routing-header bytes',title='E2 — DERIVED exact byte accounting')
    ax.legend();fig.tight_layout();fig.savefig(out/'header-overhead.png',dpi=160);plt.close(fig)


def main(argv=None):
    """Validate immutable capture inputs and write a clean, exact accounting collection."""
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args(argv);e1.validate_protocol()
    if provenance.git_state(REPO)['dirty'] is not False:raise ValueError('commit code before E2')
    config=json.loads((Path(__file__).with_name('config.json')).read_text())
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    with provenance.RunTimer() as timer:
        rows=size_rows();e1.write_csv(args.out/'summary.csv',rows)
        capture=[];inputs=[];checks=[]
        for relative in config['captures']:
            source=REPO/relative;manifest=source.parent.parent/'manifest.json'
            m=provenance.validate_manifest(manifest)
            if m['dirty'] is not False:raise ValueError('dirty capture producer')
            c,info=capture_rows(source)
            if not c:raise ValueError('capture has no T-CRH frames')
            capture.extend(c);checks.append(dict(capture=relative,**info))
            inputs.extend(dict(path=_repo_relative(p),sha256=provenance.file_sha256(p)) for p in (source,manifest))
        # One row per captured frame; gzip keeps the repeated rows small (mtime 0: reproducible bytes).
        e1.write_csv(args.out/'capture_frames.csv',capture)
        frames_csv=args.out/'capture_frames.csv'
        with gzip.GzipFile(args.out/'capture_frames.csv.gz','wb',mtime=0) as fh:fh.write(frames_csv.read_bytes())
        frames_csv.unlink()
        counts=Counter((r['entries'],r['header_bytes'],r['frame_bytes']) for r in capture)
        e1.write_csv(args.out/'capture_summary.csv',[dict(entries=n,header_bytes=h,frame_bytes=f,frames=count,label='REAL') for (n,h,f),count in sorted(counts.items())])
        v=verdict(rows);v.update(captures=checks,complete=not v['encoder_violations'] and not any(c['violations'] for c in checks))
        write_json(args.out/'verdict.json',v);plot(args.out,rows)
        (args.out/'REPORT.md').write_text('E2 exact overhead accounting\n\nSizes and percentages are DERIVED; extracted encoder/capture bytes are REAL implementation output. '
            'The reference percentage divides added bytes by the pre-insertion reference; final percentage has a different denominator. '
            'No confidence intervals apply to exact byte counts. Only T-CRH is measured in the captures. '
            'SRH is exact accounting without a captured SRH encoder. See summary.csv, capture_summary.csv and verdict.json for all sizes, padding ties and checks.\n')
    provenance.write_manifest(args.out,tool='E02 exact accounting',tool_version=__version__,command=[sys.executable,'-B','experiments/E02/account.py',*(argv or sys.argv[1:])],
        config=config,seeds=[],snapshot=REPO/'data/pinned/20261010T1358Z-celestrak',outputs=sorted(p for p in args.out.rglob('*') if p.is_file()),
        labels=labels.pick('tcrh_header_bytes','routes_and_budgets','pcap_addresses','pcap_timestamps'),
        extra=dict(campaign=config['campaign'],inputs=inputs,complete=v['complete']),timer=timer)
    print(json.dumps(v),flush=True);return 0 if v['complete'] else 1


if __name__=='__main__':raise SystemExit(main())

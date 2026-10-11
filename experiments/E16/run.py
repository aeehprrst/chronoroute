"""Registered E16: common actual replays and paired run-level TOST."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import csv
import gzip
import json
from pathlib import Path
import sys
import time

from chronoroute import __version__,labels,provenance
from chronoroute.eval.load import load_run
from chronoroute.export import ns3_crosscheck as cc
from chronoroute.trace.ns3_import import read_faults
from chronoroute.trace.writer import write_json

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'experiments/E01'))
sys.path.insert(0,str(REPO/'experiments'))
import campaign as e1
import prerequisites as pre
from policy_campaign import clean
from policy_analysis import decode


def jobs(stochastic):
    """Four deterministic validity cells and every balanced registered stochastic pair."""
    return [dict(id=f"{const}-{'fault' if fault else 'none'}-s{seed:04d}",const=const,seed=seed,
        pair_id=e1.pair_id(seed,'confirmatory' if stochastic else 'pilot'),fault=fault,stochastic=stochastic)
        for const in ('C5','C2') for fault in (False,True) for seed in (range(1000,1036) if stochastic else (0,))]


def budget(prior):
    """Use manifested campaign effort and preserve the remaining analysis reserve."""
    m=provenance.validate_manifest(prior/'manifest.json')
    if m['dirty'] is not False or not m['extra']['complete']:raise ValueError('E5 prerequisite incomplete or dirty')
    runtime=json.loads((prior/'runtime.json').read_text());forecast=json.loads((prior/'resource_forecast.json').read_text())
    spent=forecast['previous_spent_s']+runtime.get('accounted_wall_s',runtime['wall_s'])
    allowance=21600-spent-1800
    projected=forecast['reserved_future_s']-1800
    if allowance<projected or allowance<=0:raise ValueError('E16 exceeds registered campaign budget')
    return dict(label='MODELLED forecast from REAL manifested wall observations',previous_spent_s=spent,
        available_s=allowance,reserved_analysis_s=1800,projected_e16_s=projected)


def run_job(job,folder,deadline,command):
    """Preserve each successful, failed and unstarted pair with its own manifest."""
    folder.mkdir(parents=True,exist_ok=False);result=None;comparison=None;observations=[]
    status='failed';error=None
    with provenance.RunTimer() as timer:
        try:
            if time.monotonic()+150>deadline:status='not_started';raise TimeoutError('campaign deadline')
            observations,_=pre.run_replay(job['const'],job['seed'],job['fault'],job['stochastic'],folder/'replay',command=command)
            if not all(r['status']=='ok' for r in observations):raise ValueError('engine process failed or timed out')
            py=load_run(folder/'replay/python');packets=cc.read_packets(folder/'replay/ns3/packets.csv')
            info=json.loads((folder/'replay/ns3/run_info.json').read_text())
            native=cc.ns3_run(packets,info,read_faults(folder/'replay/ns3/fault_log.csv',1000000000))
            comparison=cc.compare_replays(py,packets,require_tx=True)
            result={**job,'python':cc.replay_metrics(py),'ns3':cc.replay_metrics(native)}
            write_json(folder/'metrics.json',clean(result));write_json(folder/'strict_comparison.json',comparison)
            if not all(info['checks'].values()) or comparison['violations']:
                raise ValueError('native self-check or per-packet replay mismatch')
            status='ok'
        except Exception as exc:
            error=f'{type(exc).__name__}: {exc}'
        observation={**job,'status':status,'error':error,'wall_s':timer.wall_seconds,
            'cpu_s':sum(r['cpu_s'] for r in observations),'max_rss_kb':max((r['peak_rss_kb'] for r in observations),default=0)}
        write_json(folder/'observation.json',observation)
    provenance.write_manifest(folder,tool='E16 replay job',tool_version=__version__,command=command,
        config={'job':job,'prereg_git_sha':e1.PREREG_SHA,'prereg_sha256':e1.PREREG_HASH,
                'ns3_binary':str(pre.NS3),'ns3_binary_sha256':provenance.file_sha256(pre.NS3)},seeds=[job['seed']],
        snapshot=REPO/'data/pinned/20261010T1358Z-celestrak',
        outputs=sorted(p for p in folder.rglob('*') if p.is_file()),
        labels=labels.pick('routes_and_budgets','traffic_probes','link_rate_and_queues'),
        extra={'observation':observation,'synthetic_positions':'C2 elements and positions MODELLED' if job['const']=='C2' else None},timer=timer)
    return observation,result,comparison


def plot(out,summary):
    """Standalone equivalence intervals with missing endpoints explicitly marked."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    for ax,endpoint in zip(axes.flat,('pdr','fpr','p50','p99')):
        rows=[r for r in summary if r['endpoint']==endpoint]
        for i,r in enumerate(rows):
            ax.axhline(r['lower_bound'],color='grey',linestyle='--');ax.axhline(r['upper_bound'],color='grey',linestyle='--')
            if r['estimate'] is None:ax.text(i,0 if endpoint in ('pdr','fpr') else 1,'undefined',rotation=90)
            else:ax.errorbar(i,r['estimate'],yerr=[[r['estimate']-r['lo95']],[r['hi95']-r['estimate']]],fmt='o',capsize=4)
        ax.set(xticks=range(len(rows)),xticklabels=[r['const']+'/'+r['condition'] for r in rows],title=endpoint,
               ylabel='ns3/python ratio' if endpoint in ('p50','p99') else 'ns3 minus Python')
    fig.suptitle('E16 — MODELLED networks; DERIVED paired 95% intervals and equivalence margins')
    fig.savefig(out/'equivalence.png',dpi=160);plt.close(fig)


def analyse(out,records,observations,comparisons):
    """Keep all cells, failed runs and undefined metrics in the final verdict."""
    summary=[]
    for const in ('C5','C2'):
        for fault in (False,True):
            pairs=[r for r in records if r['stochastic'] and r['const']==const and r['fault']==fault]
            complete={r['seed'] for r in pairs}==set(range(1000,1036)) and len(pairs)==36
            for endpoint in ('pdr','fpr','p50','p99'):
                r=dict(const=const,condition='fault' if fault else 'none',endpoint=endpoint,complete=complete,
                       **cc.equivalence(pairs,endpoint))
                r['equivalent']=bool(r['equivalent'] and complete);summary.append(r)
    e1.write_csv(out/'summary.csv',summary);e1.write_csv(out/'inventory.csv',observations)
    write_json(out/'per_run.json',clean(records));write_json(out/'comparisons.json',comparisons)
    run_rows=[]
    for r in records:
        for engine in ('python','ns3'):
            m=r[engine]
            run_rows.append({**{k:r[k] for k in ('id','const','seed','pair_id','fault','stochastic')},'engine':engine,
                **{k:m[k] for k in ('sent','delivered','pdr','clean','false_positives','fpr')},
                'losses_json':json.dumps(m['losses'],sort_keys=True),'latency_json':json.dumps(clean(m['latency']),sort_keys=True),
                'labels_json':json.dumps(m['labels'],sort_keys=True)})
    e1.write_csv(out/'per_run.csv',run_rows)
    gate=[r for r in observations if not r['stochastic']]
    gate_ok=len(gate)==4 and all(r['status']=='ok' for r in gate)
    complete=gate_ok and len(observations)==148 and all(r['status']=='ok' for r in observations) and all(r['complete'] for r in summary)
    verdict=dict(complete=complete,deterministic_gate_passed=gate_ok,equivalent=complete and all(r['equivalent'] for r in summary),
        packets_python=sum(c['packets_python'] for c in comparisons),packets_ns3=sum(c['packets_ns3'] for c in comparisons),
        checked_fields=sum(c['checked_fields'] for c in comparisons),violations=sum(c['violations'] for c in comparisons),
        mismatched_packets=sum(c['mismatched_packets'] for c in comparisons),
        max_abs_time_error_ns=max((c['max_abs_time_error_ns'] for c in comparisons),default=None),
        undefined_endpoints=[r for r in summary if r['reason']],
        label='MODELLED network outcomes; DERIVED agreement and statistics')
    write_json(out/'verdict.json',verdict);plot(out,summary)
    lines=['E16 Python and ns-3 agreement','',
        'C5 uses REAL public orbital inputs; C2 elements and positions are MODELLED. Network behaviour is MODELLED; comparison statistics are DERIVED. Starlink real routing is UNKNOWN; Starlink does not use T-CRH.','',
        'Complete registered grid: '+str(complete)+'. Scoped equivalence: '+str(verdict['equivalent'])+'.',
        'Per-packet violations: '+str(verdict['violations'])+'. Maximum recorded timing difference (ns): '+str(verdict['max_abs_time_error_ns'])+'.','',
        'summary.csv retains paired TOST one-sided p-values, 90% equivalence intervals and 95% reporting intervals. Every seed remains in the inventory. Per-run source denominators, loss reasons, clean-label counts and per-flow quantiles are in per_run.csv. Losses have infinite effective latency. No undefined or infinite endpoint is dropped to pass equivalence.','',
        'Scope: zero processing delay, no background/jitter, stable planning, source insertion and continue policy; fixed-count conditional-Poisson send-time randomness shared by both engines. This does not establish agreement for other fault models, fallbacks, processing or background traffic.','',
        'Raw bundles and engine outputs remain in the adjacent ignored cache. Producer manifests, exact commands and hashes are retained in the compressed ledger.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
    return verdict


def main(argv=None):
    """Run deterministic gates first, then the complete bounded stochastic grid."""
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--workers',type=int,choices=range(1,9),default=8)
    parser.add_argument('--prior',type=Path,default=REPO/'results/E05/20261011T185503Z-confirmatory')
    args=parser.parse_args(argv);e1.validate_protocol()
    if provenance.git_state(REPO)['dirty'] is not False:raise ValueError('commit implementation before experiments')
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    raw=args.out.with_name(args.out.name+'-raw');raw.mkdir();(raw/'runs').mkdir()
    command=[sys.executable,'-B',str(Path(__file__).resolve()),*(argv if argv is not None else sys.argv[1:])]
    observations=[];records=[];comparisons=[]
    planned=jobs(False)+jobs(True);write_json(args.out/'planned_jobs.json',planned)
    with provenance.RunTimer() as timer:
        forecast=budget(args.prior);write_json(args.out/'resource_forecast.json',forecast)
        deadline=time.monotonic()+forecast['available_s']
        for job in jobs(False):
            obs,record,comparison=run_job(job,raw/'runs'/job['id'],deadline,command)
            observations.append(obs)
            if record is not None:records.append(record)
            if comparison is not None:comparisons.append(comparison)
        gate=all(o['status']=='ok' for o in observations)
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(run_job,j,raw/'runs'/j['id'],deadline if gate else 0,command) for j in jobs(True)]
            for f in as_completed(futures):
                obs,record,comparison=f.result();observations.append(obs)
                if record is not None:records.append(record)
                if comparison is not None:comparisons.append(comparison)
                if len(observations)%12==4:print(json.dumps(dict(completed=len(observations),total=len(planned),wall_s=timer.wall_seconds,
                    failures=sum(o['status']!='ok' for o in observations))),flush=True)
        observations.sort(key=lambda r:(r['stochastic'],r['id']));records.sort(key=lambda r:(r['stochastic'],r['id']))
        verdict=analyse(args.out,records,observations,comparisons)
        with gzip.open(args.out/'producer-manifests.jsonl.gz','wt',encoding='utf-8') as fh:
            for p in sorted(raw.rglob('manifest.json')):
                m=provenance.validate_manifest(p)
                if m['dirty'] is not False:raise ValueError('dirty E16 producer')
                fh.write(json.dumps({'path':str(p),'sha256':provenance.file_sha256(p),'manifest':m},sort_keys=True)+'\n')
        write_json(args.out/'runtime.json',dict(label='REAL host observations',wall_s=timer.wall_seconds,
            previous_spent_s=forecast['previous_spent_s'],workers=args.workers,cpu_s=sum(r['cpu_s'] for r in observations),
            max_rss_kb=max((r['max_rss_kb'] for r in observations),default=0)))
    provenance.write_manifest(args.out,tool='E16 confirmatory agreement',tool_version=__version__,command=command,
        config={'prereg_git_sha':e1.PREREG_SHA,'prereg_sha256':e1.PREREG_HASH,'workers':args.workers,
                'paired_seeds':list(range(1000,1036)),'analysis':'paired Student-t TOST','alpha':.05,
                'ns3_binary_sha256':provenance.file_sha256(pre.NS3)},seeds=[0,*range(1000,1036)],
        snapshot=REPO/'data/pinned/20261010T1358Z-celestrak',outputs=sorted(p for p in args.out.rglob('*') if p.is_file()),
        labels=labels.pick('orbital_elements','routes_and_budgets','traffic_probes','link_rate_and_queues'),
        extra={'complete':verdict['complete'],'equivalent':verdict['equivalent'],'raw_cache':str(raw),
               'synthetic_positions':'C2 elements and positions MODELLED',
               'inputs':[dict(path=str(args.prior/'manifest.json'),sha256=provenance.file_sha256(args.prior/'manifest.json'))]},timer=timer)
    print(json.dumps(verdict),flush=True)
    return 0 if verdict['complete'] else 1


if __name__=='__main__':raise SystemExit(main())

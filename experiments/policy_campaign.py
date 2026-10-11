"""Clean bounded launchers for the registered E4 and E5 grids."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import gzip
import json
import math
from pathlib import Path
import shutil
import sys
import time

import numpy as np
from chronoroute import __version__, labels, provenance
from chronoroute.baselines import run as br
from chronoroute.baselines.engine import SchemeEngine
from chronoroute.baselines.params import normalise_scheme
from chronoroute.eval import load, metrics
from chronoroute.fwd.config import normalise
from chronoroute.fwd.faults import renewal_periods
from chronoroute.fwd.rng import KeyedStreams
from chronoroute.fwd.scenario import build_scenario
from chronoroute.trace.writer import write_json

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'experiments/E01'))
import campaign as e1
import prerequisites as pre
import confirm as e1_confirm
import policy_analysis as analysis

SCHEMES=('greedy_visited','continue','o_t','snap','ls_h','crh16')
POLICIES=('greedy_visited','greedy_pure','grid_detour','continue','drop')
PROFILES={'link-A':('link','0.01',500000000),'link-B':('link','0.05',2000000000),
          'node-A':('node','0.01',500000000),'node-B':('node','0.05',2000000000)}


def clean(value):
    """Represent infinite outcomes explicitly in standard JSON; refuse NaNs."""
    if isinstance(value,float) and not math.isfinite(value):
        if math.isnan(value):raise ValueError('NaN experiment outcome')
        return 'inf' if value>0 else '-inf'
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    return value


def jobs(experiment):
    """Every registered seed and control, without outcome-dependent selection."""
    if experiment not in ('E04','E05'):raise ValueError('unsupported policy experiment')
    rows=[]
    for const in ('C5','C2'):
        for seed in range(1000,1036):
            cells=[(scheme,condition) for scheme in SCHEMES for condition in ('none',*PROFILES)] if experiment=='E04' else [('greedy_visited','none')]+[(p,'trigger') for p in POLICIES]
            for scheme,condition in cells:
                rows.append(dict(id=f'{const}-{scheme}-{condition}-s{seed:04d}',experiment=experiment,const=const,
                                 seed=seed,pair_id=e1.pair_id(seed,'confirmatory'),phase='confirmatory',scheme=scheme,condition=condition))
    return rows


def set_policy(cfg,name):
    """Apply the ordinary registered policy; the intervention adds no service time."""
    cfg['forwarding'].update(policy='greedy' if name in POLICIES[:3] else name,
                            fallback=name if name in POLICIES[:3] else 'greedy_visited')


def compile_faults(seed,profile,target):
    """Stationary target-specific renewal draws, including empty outage histories."""
    kind,u,mttr=PROFILES[profile]
    key=tuple(target) if kind=='link' else (target,)
    periods=renewal_periods(KeyedStreams(seed),kind+'_fault',key,3000000000,27000000000,u,mttr)
    return [dict(kind=kind+'_down',**{kind:target},start_s=f'{a/1e9:.9f}',stop_s=f'{b/1e9:.9f}') for a,b in periods]


def document(job,design=None):
    """Normalised engine/scheme contract with outer frozen campaign metadata."""
    d=e1.document({**job,'scheme':'chronoroute','condition':'none'})
    c=d['engine'];c['scenario']['duration_s']=30 if job['experiment']=='E04' else 12
    c['schedule'].update(plan_links='stable',planner_processing_ns=500000)
    c['forwarding'].update(processing_ns=500000,jitter={'model':'none','mean_ns':400000},
                          background={'model':'none','rho':0,'links':'all','packet_bytes':1500,'window_ms':10})
    selected=design.get(f"{job['const']}:{job['seed']}",{}) if design else {}
    intervention={'label':'MODELLED','records':[]}
    s={'name':'chronoroute','outputs':{'stretch_oracle':True}}
    if job['experiment']=='E04':
        name=job['scheme']
        if name=='greedy_visited':set_policy(c,name)
        elif name in ('continue','crh16'):
            c['forwarding'].update(policy='continue',fallback='none');s['name']='crh16' if name=='crh16' else 'chronoroute'
        else:
            c['forwarding'].update(policy='continue',fallback='none');s['name']=name
            if name=='ls_h':s['ls']={'preset':'olsr_leo','bfd':True,'bfd_interval_ms':100,'bfd_mult':3,'spf_delay_ms':50}
        if job['condition']!='none':
            profile=job['condition'];kind=PROFILES[profile][0];target=selected[kind]
            c['faults']=compile_faults(job['seed'],profile,target)
            intervention.update(target=target,stream=[kind+'_fault',list(target) if kind=='link' else [target]],
                                profile=profile,intervals=c['faults'])
    else:
        set_policy(c,job['scheme']);intervention.update(target=selected.get('trigger',-1) if job['condition']=='trigger' else -1,
                                                       stream=['experiment_target',[0]],interval_ns=[4000000000,8000000000])
    d['engine']=normalise(c);d['scheme']=normalise_scheme(s);d['intervention']=intervention
    d['campaign'].update(experiment=job['experiment'],cell_id=f"{job['const']}-{job['scheme']}-{job['condition']}")
    return d


def preflight(planned,out):
    """Check every stable route and freeze targets before observing any policy result."""
    design={};checks=0
    for job in planned:
        key=f"{job['const']}:{job['seed']}"
        if key in design:continue
        cfg=document({**job,'condition':'none'})['engine'];sc=build_scenario(cfg)
        for flow in sc.flows:
            for t in range(0,int(cfg['scenario']['duration_s']*1000),1000):
                if sc.plan(flow,t,t+1000) is None:raise ValueError(f'no stable route: {key} flow {flow.flow_id} at {t}')
                checks+=1
        if job['experiment']=='E04':
            design[key]={'link':list(sc.resolve_on_path({'flow':0,'at_s':3,'position':'middle','kind':'isl'},3000000000,False)),
                         'node':int(sc.resolve_on_path({'flow':0,'at_s':3,'position':'middle'},3000000000,True))}
        else:
            candidates=[int(n) for n in sc.path_at(0,4000000000) if n<sc.topo.n_sats]
            if not candidates:raise ValueError('no eligible trigger satellite')
            index=int(KeyedStreams(job['seed']).uniform('experiment_target',(0,),0)*len(candidates))
            design[key]={'trigger':candidates[index],'candidates':candidates}
    write_json(out/'design.json',design);write_json(out/'preflight.json',dict(checks=checks,violations=0))
    return design


def effective_tail(run,mask,p):
    """Registered per-flow effective quantile: count losses as infinity, enforce tail support."""
    rows=metrics.latency_summary(run,mask,ps=(p,))
    values=[r['q'+p+'_eff'] for r in rows if r['sent']]
    return (float(np.mean(values))/1e9 if values and all(v is not None for v in values) else None),rows


def trigger_counts(run,records):
    """Trigger-conditioned denominators retain strict drops and undefined empty sets."""
    indices=np.array([r['pkt'] for r in records],dtype=int)
    reasons=[run.reason[i] for i in indices]
    delivered=int(run.delivered[indices].sum())
    from collections import Counter
    return dict(triggered=len(indices),triggered_delivered=delivered,
                triggered_pdr=delivered/len(indices) if len(indices) else None,
                stuck=sum(r in ('stuck','loop','hop_limit','no_fallback') for r in reasons),
                strict_drop=sum(r in ('late_strict','late_drop','late') for r in reasons),triggered_loss_reasons=dict(Counter(r for i,r in zip(indices,reasons) if not run.delivered[i])))


def extract(run,job):
    """Run-level metrics from production evaluators, retaining per-flow and outage accounting."""
    m=metrics.measurement_mask(run);p=metrics.pdr_total(run,m);st=metrics.stretch(run,m);control=metrics.control_summary(run)
    tail,latency=effective_tail(run,m,'0.99')
    outages=[dict(fault=f,blackhole=metrics.blackhole(run,f),ttm=metrics.time_to_mitigation(run,f)) for f in run.faults]
    records=run.run.get('intervention',{}).get('records',[]);tr=trigger_counts(run,records)
    indices=np.array([r['pkt'] for r in records],dtype=int);tm=np.zeros(run.n,bool);tm[indices]=True
    triggered_tail,trigger_latency=effective_tail(run,tm,'0.99')
    triggered_mean=None if not len(indices) else (float(run.latency_ns[indices].mean())/1e9 if tr['triggered_delivered']==len(indices) else math.inf)
    valid=m & run.delivered & (run.extras['oracle_hops']>0)
    extra=run.hops[valid]-run.extras['oracle_hops'][valid]
    triggered_extra=run.hops[valid & tm]-run.extras['oracle_hops'][valid & tm]
    triggered_stretch=metrics.stretch(run,tm)
    r={k:job[k] for k in ('const','scheme','condition','seed','pair_id')}
    r.update(sent=p['sent'],delivered=p['delivered'],pdr=p['pdr'],losses_json=json.dumps(p['losses'],sort_keys=True),
             effective_p99_s=tail,tail_ineligible=sum(l['q0.99_eff'] is None for l in latency),
             delivered_p99_ineligible=sum(l['q0.99'] is None for l in latency),outages=len(outages),
             blackhole_s=float(np.mean([o['blackhole']['blackhole_ns'] for o in outages]))/1e9 if outages else None,
             blackhole_losses=sum(o['blackhole']['losses'] for o in outages),
             ttm_undefined=sum(not o['ttm']['affected_flows'] for o in outages),ttm_censored=sum(bool(o['ttm']['affected_flows']) and not o['ttm']['observed'] for o in outages),
             header_bytes=control.get('header_bytes_per_packet_mean'),header_link_bytes=control.get('header_bytes_on_links'),
             state_json=json.dumps(control.get('state'),sort_keys=True),steady_state_json=json.dumps(control.get('crh_state_upload_bytes_per_s_steady'),sort_keys=True),
             control_json=json.dumps(run.control,sort_keys=True),latency_json=json.dumps(clean(latency),sort_keys=True),
             flow_json=json.dumps(metrics.pdr_by_flow(run,m),sort_keys=True),outage_json=json.dumps(outages,sort_keys=True),
             stretch_min_exact=st['min'],stretch_min_adjusted=st['min_tol_adjusted'],stretch_min_raw=st['min_raw'],
             stretch_mean=st['mean'],stretch_violations=st['violations'],stretch_exact_violations=st['exact_violations'],
             stretch_outside_graph=st['n_path_not_in_send_graph'],stretch_exact_n=st['n_no_step_crossing'],stretch_in_graph_n=st['n_in_send_graph'],
             extra_hops_mean=float(extra.mean()) if len(extra) else None,extra_hops_negative=int((extra<0).sum()),
             **{k:v for k,v in tr.items() if k!='triggered_loss_reasons'},triggered_loss_reasons_json=json.dumps(tr['triggered_loss_reasons'],sort_keys=True),
             never_triggered_forward=int(((run.flow==0)&m&~tm).sum()),triggered_effective_p99_s=triggered_tail,
             triggered_effective_mean_s=triggered_mean,triggered_latency_json=json.dumps(clean(trigger_latency),sort_keys=True),
             triggered_stretch_mean=triggered_stretch['mean'],triggered_extra_hops_mean=float(triggered_extra.mean()) if len(triggered_extra) else None,
             visited_entries_max=max((x.get('visited_entries',0) for x in records),default=0),
             visited_python_bytes_max=max((x.get('visited_set_object_bytes',0) for x in records),default=0))
    r['stuck_rate']=tr['stuck']/tr['triggered'] if tr['triggered'] else None
    r['strict_drop_rate']=tr['strict_drop']/tr['triggered'] if tr['triggered'] else None
    for medium in ('uplink','isl','downlink','ground'):
        r['control_'+medium]=control.get('control_bytes',{}).get(medium,0)
        r['control_rate_'+medium]=control.get('control_bytes_per_s',{}).get(medium,0)
    return r


def check_prefix(run,control):
    """Verify common sends and actual paths/times up to each intervention against control."""
    if run.n!=control.n or not np.array_equal(run.send_ns,control.send_ns) or not np.array_equal(run.flow,control.flow):
        raise ValueError('policy control packets differ')
    records=run.run.get('intervention',{}).get('records',[]);by={r['pkt']:r for r in records};violations=0
    if len(by)!=len(records):raise ValueError('repeated intervention')
    for i in range(run.n):
        rec=by.get(i)
        if rec:
            n=len(rec['path_before'])
            violations+=int(list(control.path(i)[:n])!=rec['path_before'] or list(run.path(i)[:n])!=rec['path_before'] or
                            control.paths.length(i)<=n or int(control.path(i)[n])!=rec['node'] or
                            not np.array_equal(run.arr_ns(i)[:n],control.arr_ns(i)[:n]) or control.arr_ns(i)[n-1]!=rec['t_ns'])
        else:
            violations+=int(not np.array_equal(run.path(i),control.path(i)) or not np.array_equal(run.arr_ns(i),control.arr_ns(i)) or
                            run.outcome[i]!=control.outcome[i] or run.wire[i]!=control.wire[i])
    return dict(packets=run.n,triggered=len(by),violations=violations)


def run_child(config_path,out):
    """Run a frozen document with the already tested hook and production accounting."""
    d=json.loads(config_path.read_text());out.mkdir(parents=True,exist_ok=False)
    factory=pre.deviation_factory(d['intervention']['target'],d['intervention']['records']) if d['campaign']['experiment']=='E05' else SchemeEngine
    summary,_=br.run_scheme(d['engine'],d['scheme'],out/'raw',argv=[sys.executable,'-B',__file__,*sys.argv[1:]],engine_factory=factory,
        run_extra={'campaign':d['campaign'],'intervention':d['intervention']})
    campaign=d['campaign'];job=dict(const=d['engine']['scenario']['kind'],scheme='',condition='',seed=campaign['seed'],pair_id=campaign['pair_id'])
    job.update(d['job'])
    e1.attach_metadata(out/'raw',campaign,{'kind':'parent measures child'},inputs=[config_path])
    row=extract(load.load_run(out/'raw'),job);write_json(out/'metrics.json',clean(row))
    return int(not summary['conservation']['ok'] or summary['invariants']['violations']!=0 or row['stretch_violations']!=0)


def run_job(job,out,raw_root,design,deadline):
    """Record every launch, timeout and failure, with a clean wrapper manifest."""
    folder=raw_root/'runs'/job['id'];config=out/'configs'/(job['id']+'.json')
    command=[str(REPO/'venv/bin/python'),'-B',str(Path(__file__).resolve()),'--child-config',str(config),'--out',str(folder)]
    timeout=120 if job['experiment']=='E04' else 60
    with provenance.RunTimer() as timer:
        if time.monotonic()+timeout>deadline:
            folder.mkdir(parents=True,exist_ok=False);obs=dict(status='not_started',reason='campaign deadline',command=command,wall_s=0,cpu_s=0,peak_rss_kb=0,returncode=None)
        else:
            obs=e1.measured_command(command,raw_root/'logs'/job['id'],timeout=timeout)
            folder.mkdir(parents=True,exist_ok=True)
        row={**job,**obs};write_json(folder/'observation.json',row)
    provenance.write_manifest(folder,tool=job['experiment']+' simulation job',tool_version=__version__,command=command,
        config=json.loads(config.read_text()),seeds=[job['seed']],snapshot=REPO/'data/pinned/20261010T1358Z-celestrak',
        outputs=sorted(p for p in folder.rglob('*') if p.is_file()),labels=labels.pick('routes_and_budgets','isl_topology_grid4','traffic_probes','link_rate_and_queues'),
        extra={'campaign':json.loads(config.read_text())['campaign'],'observation':row,'synthetic_positions':'MODELLED' if job['const']=='C2' else None},timer=timer)
    return row


def validate_gates(e1_result,gates,e0,experiment,prior=None):
    """Recompute remaining resource allowance from manifested active compute, excluding pauses."""
    _,forecast=e1_confirm.validate_inputs(REPO/'results/E01/20261011T113605Z-pilot',gates,e0)
    m=provenance.validate_manifest(e1_result/'manifest.json')
    if m['dirty'] is not False or not m['extra']['complete']:raise ValueError('E1 completion/provenance gate failed')
    runtime=json.loads((e1_result/'runtime.json').read_text());spent=runtime['wall_s']+runtime['previous_spent_s']
    if prior:
        pm=provenance.validate_manifest(prior/'manifest.json')
        if pm['dirty'] is not False or not pm['extra']['complete']:raise ValueError('prior policy campaign incomplete')
        prior_runtime=json.loads((prior/'runtime.json').read_text())
        spent+=prior_runtime.get('accounted_wall_s',prior_runtime['wall_s'])
    reserve=forecast['remaining_work_s']['E16']+1800
    future=forecast['remaining_work_s']['E05'] if experiment=='E04' else 0
    projected=spent+forecast['remaining_work_s'][experiment]+future+reserve
    if projected>21600:raise ValueError('remaining campaign exceeds preregistered compute budget')
    return dict(label='MODELLED projection; REAL manifested active wall observations',previous_spent_s=spent,
                reserved_future_s=reserve+future,available_s=21600-spent-reserve-future,
                projected_campaign_s=projected,confirmation_allowed=True)


def load_completed(source,raw_root,planned,design):
    """Validate original clean producers before collecting completed simulations again."""
    if json.loads((source/'planned_jobs.json').read_text())!=planned:raise ValueError('recovery design differs')
    observations=[];records=[];producer_sha=None
    for job in planned:
        folder=raw_root/'runs'/job['id']
        wrapper=provenance.validate_manifest(folder/'manifest.json')
        raw=provenance.validate_manifest(folder/'raw/manifest.json')
        doc=document(job,design);doc['job']=job
        if wrapper['config']!=doc or raw['config']!={'run':doc['engine'],'scheme':doc['scheme']}:
            raise ValueError('recovery configuration differs')
        for manifest in (wrapper,raw):
            if manifest['dirty'] is not False:raise ValueError('dirty recovery producer')
            if producer_sha is None:producer_sha=manifest['git_sha']
            if manifest['git_sha']!=producer_sha:raise ValueError('recovery producer commits differ')
        obs=json.loads((folder/'observation.json').read_text())
        if obs!=wrapper['extra']['observation'] or any(obs.get(k)!=v for k,v in job.items()) or obs['status']!='ok':
            raise ValueError('recovery observation differs or failed')
        record=analysis.decode(json.loads((folder/'metrics.json').read_text()))
        if any(record.get(k)!=job[k] for k in ('const','scheme','condition','seed','pair_id')):
            raise ValueError('recovery metric identity differs')
        observations.append(obs);records.append(record)
    return observations,records


def recovery_wall(log,expected):
    """Read a completed progress checkpoint; retain failed analysis time as a separate reserve."""
    checkpoint=None
    for line in log.read_text().splitlines():
        try:row=json.loads(line)
        except json.JSONDecodeError:continue
        if isinstance(row,dict) and row.get('completed')==expected and row.get('total')==expected and row.get('failures')==0:
            checkpoint=row
    if checkpoint is None or not math.isfinite(checkpoint['wall_s']) or checkpoint['wall_s']<0:
        raise ValueError('no valid complete simulation checkpoint')
    return checkpoint['wall_s']


def main(argv=None,*,experiment=None):
    """Freeze full design, run bounded children, analyse runs and collect reproducible evidence."""
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--child-config',type=Path);parser.add_argument('--experiment',choices=('E04','E05'),default=experiment)
    parser.add_argument('--workers',type=int,choices=range(1,9),default=8)
    parser.add_argument('--e1',type=Path,default=REPO/'results/E01/20261011T154940Z-confirmatory-resumed')
    parser.add_argument('--gates',type=Path,default=REPO/'results/E01/20261011T130817Z-calibration')
    parser.add_argument('--e0',type=Path,default=REPO/'results/E00/20261011T100448Z');parser.add_argument('--prior',type=Path)
    parser.add_argument('--collect-from',type=Path);parser.add_argument('--collect-log',type=Path)
    args=parser.parse_args(argv)
    if args.child_config:return run_child(args.child_config,args.out)
    if args.experiment is None:parser.error('--experiment required')
    if bool(args.collect_from)!=bool(args.collect_log):parser.error('--collect-from and --collect-log are required together')
    launch=[sys.executable,'-B',str(Path(__file__).resolve()),*(argv if argv is not None else sys.argv[1:]),'--experiment',args.experiment]
    e1.validate_protocol()
    if provenance.git_state(REPO)['dirty'] is not False:raise ValueError('commit implementation before experiments')
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    raw_source=args.collect_from.resolve() if args.collect_from else args.out
    raw_root=raw_source.with_name(raw_source.name+'-raw')
    if not args.collect_from:raw_root.mkdir()
    planned=jobs(args.experiment);observations=[];records=[]
    previous_wall=0;analysis_reserve=0
    with provenance.RunTimer() as timer:
        budget=validate_gates(args.e1,args.gates,args.e0,args.experiment,args.prior);write_json(args.out/'resource_forecast.json',budget)
        if args.collect_from:
            previous_wall=recovery_wall(args.collect_log,len(planned));analysis_reserve=300
            if previous_wall+analysis_reserve>budget['available_s']:raise ValueError('recovery exceeds campaign budget')
            design=json.loads((raw_source/'design.json').read_text())
            observations,records=load_completed(raw_source,raw_root,planned,design)
            for name in ('design.json','preflight.json'):shutil.copyfile(raw_source/name,args.out/name)
            shutil.copyfile(args.collect_log,args.out/'previous-attempt.log')
            write_json(args.out/'recovery.json',dict(source=str(raw_source),observed_wall_s=previous_wall,
                unmeasured_analysis_reserve_s=analysis_reserve,label='REAL logged simulation wall; MODELLED conservative failed-analysis reserve',
                reason='Original simulations completed; CSV export rejected heterogeneous endpoint columns. No simulations rerun.'))
        else:design=preflight(planned,args.out)
        deadline=time.monotonic()+budget['available_s']-previous_wall-analysis_reserve
        write_json(args.out/'planned_jobs.json',planned);(args.out/'configs').mkdir()
        for job in planned:
            d=document(job,design);d['job']=job;write_json(args.out/'configs'/(job['id']+'.json'),d)
        if not args.collect_from:
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                futures=[pool.submit(run_job,j,args.out,raw_root,design,deadline) for j in planned]
                for f in as_completed(futures):
                    observation=f.result();observations.append(observation)
                    if observation['status']=='ok':records.append(analysis.decode(json.loads((raw_root/'runs'/observation['id']/'metrics.json').read_text())))
                    if len(observations)%24==0:
                        print(json.dumps(dict(completed=len(observations),total=len(planned),wall_s=timer.wall_seconds,failures=sum(r['status']!='ok' for r in observations))),flush=True)
        observations.sort(key=lambda x:x['id']);records.sort(key=lambda x:(x['const'],x['condition'],x['scheme'],x['seed']))
        e1.write_csv(args.out/'inventory.csv',observations)
        prefix=[]
        if args.experiment=='E05' and all(r['status']=='ok' for r in observations):
            for const in ('C5','C2'):
                for seed in range(1000,1036):
                    control=load.load_run(raw_root/'runs'/f'{const}-greedy_visited-none-s{seed:04d}'/'raw')
                    for policy in POLICIES:
                        rd=load.load_run(raw_root/'runs'/f'{const}-{policy}-trigger-s{seed:04d}'/'raw')
                        prefix.append(dict(const=const,seed=seed,policy=policy,**check_prefix(rd,control)))
            e1.write_csv(args.out/'prefix_checks.csv',prefix)
        complete=analysis.write_analysis(args.out,records,args.experiment)
        success=complete and len(observations)==len(planned) and all(r['status']=='ok' for r in observations) and not any(x['violations'] for x in prefix)
        provenance.write_manifest(raw_root,tool=args.experiment+' raw collection',tool_version=__version__,command=launch,
            config={'prereg_git_sha':e1.PREREG_SHA,'prereg_sha256':e1.PREREG_HASH,'experiment':args.experiment},seeds=list(range(1000,1036)),
            outputs=sorted(p for p in raw_root.rglob('*') if p.is_file() and p!=raw_root/'manifest.json'),labels=labels.pick('routes_and_budgets','traffic_probes','isl_topology_grid4'),
            extra={'complete':success},timer=timer)
        (args.out/'inputs').mkdir()
        inputs=[args.e1/'manifest.json',args.e1/'runtime.json',args.gates/'manifest.json',args.gates/'resource_forecast.json',args.e0/'manifest.json',raw_root/'manifest.json']
        if args.prior:inputs.extend((args.prior/'manifest.json',args.prior/'runtime.json'))
        if args.collect_from:inputs.extend((raw_source/'planned_jobs.json',raw_source/'design.json',args.out/'previous-attempt.log'))
        with gzip.open(args.out/'inputs/producer-manifests.jsonl.gz','wt',encoding='utf-8') as fh:
            for p in [*(p for p in inputs if p.name=='manifest.json'),*raw_root.glob('runs/*/manifest.json'),*raw_root.glob('runs/*/raw/manifest.json')]:
                m=provenance.validate_manifest(p)
                if m['dirty'] is not False:raise ValueError('dirty evidence producer')
                fh.write(json.dumps(dict(path=str(p),sha256=provenance.file_sha256(p),manifest=m),sort_keys=True)+'\n')
        wall=timer.wall_seconds
        write_json(args.out/'runtime.json',dict(label='REAL host observations; MODELLED failed-analysis reserve when recovering',wall_s=wall,workers=args.workers,
            previous_attempt_observed_wall_s=previous_wall,previous_analysis_reserve_s=analysis_reserve,
            accounted_wall_s=wall+previous_wall+analysis_reserve,
            cpu_s=sum(r['cpu_s'] for r in observations),max_rss_kb=max((r['peak_rss_kb'] for r in observations),default=0),complete=success))
    campaign=dict(prereg_path='experiments/PREREG.md',prereg_git_sha=e1.PREREG_SHA,prereg_sha256=e1.PREREG_HASH,
                  phase='confirmatory',experiment=args.experiment,cell_id='full-registered-grid',pair_id='balanced-18',seed=None)
    provenance.write_manifest(args.out,tool=args.experiment+' confirmatory campaign',tool_version=__version__,command=launch,
        config=dict(campaign=campaign,workers=args.workers,analysis_seed=91000,bootstrap_resamples=10000),seeds=list(range(1000,1036)),
        snapshot=REPO/'data/pinned/20261010T1358Z-celestrak',outputs=sorted(p for p in args.out.rglob('*') if p.is_file()),
        labels=labels.pick('orbital_elements','routes_and_budgets','traffic_probes','isl_topology_grid4','link_rate_and_queues'),
        extra=dict(campaign=campaign,complete=success,raw_cache=str(raw_root),synthetic_positions='C2 elements and positions MODELLED',
                   inputs=[dict(path=str(p),sha256=provenance.file_sha256(p)) for p in inputs]),timer=timer)
    print(json.dumps(dict(complete=success,result=str(args.out))),flush=True)
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())

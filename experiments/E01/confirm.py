"""Run the frozen E1 grid only after clean provenance and campaign validity gates."""
import argparse
import copy
import gzip
import json
import math
from pathlib import Path
import shutil
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from chronoroute import __version__, labels, provenance
from chronoroute.trace.writer import write_json
import campaign as e1
import analysis


def group_jobs(jobs):
    """One shared twin first, then all eighteen registered conditions per group."""
    groups=defaultdict(list)
    for job in jobs:groups[(job['const'],job['scheme'],job['seed'])].append(job)
    expected={'none',*e1.CONDITIONS}
    for group in groups.values():
        if len(group)!=19 or {j['condition'] for j in group}!=expected:
            raise ValueError('incomplete E1 group')
        group.sort(key=lambda j:j['condition']!='none')
    return list(groups.values())


def validate_inputs(pilot, prerequisites, e0):
    """Require valid clean manifests, frozen rule hashes and both exact gates."""
    for folder in (pilot,prerequisites,e0):
        try:
            m=provenance.validate_manifest(folder/'manifest.json')
        except (OSError,ValueError) as exc:
            raise ValueError(f'invalid prerequisite manifest: {folder}') from exc
        if m['dirty'] is not False:raise ValueError('dirty prerequisite producer')
    forecast=json.loads((prerequisites/'resource_forecast.json').read_text())
    if not forecast['confirmation_allowed'] or not forecast['deterministic_gate_passed']:
        raise ValueError('campaign gate does not authorise confirmation')
    import csv
    checks=list(csv.DictReader((e0/'summary.csv').open()))
    if not checks or any(float(r['violations'])!=0 for r in checks):raise ValueError('E0 violation')
    operating=json.loads((pilot/'operating_points.json').read_text())
    for item in operating['inputs']:
        if provenance.file_sha256(pilot/item['path'])!=item['sha256']:raise ValueError('changed pilot selection input')
    for const in ('C5','C2'):
        selected=operating[const]
        if selected['rule']!=e1.RULES[selected['rule_index']]:raise ValueError('invalid frozen rule')
    return operating,forecast


def score_command(job, out, raw, twin, score):
    """Offline CLI scoring, native settings except the registered ChronoRoute sweep."""
    cmd=[str(e1.REPO/'venv/bin/python'),'-B','-m','chronoroute.cli','eval','score',str(raw),
         '--twin',str(twin),'--flow','0','--include-null','--k','2','--window-ms','1000',
         '--sensitivity-k','1','4','--secondary-flow','1','--out',str(score)]
    if job['scheme']=='chronoroute':cmd+=['--rules',str(out/'rules.json'),'--check-plans']
    return cmd


def validate_checkpoint(source, planned, operating, targets, forecast):
    """Validate an immutable stopped collection and all frozen design inputs."""
    source=source.resolve()
    manifest=provenance.validate_manifest(source/'manifest.json')
    if manifest['dirty'] is not False:raise ValueError('unclean checkpoint producer')
    for key,value in (('prereg_git_sha',e1.PREREG_SHA),('prereg_sha256',e1.PREREG_HASH)):
        if manifest['config'].get(key)!=value:raise ValueError('checkpoint preregistration mismatch')
    expected={'planned_jobs.json':planned,'operating_points.json':operating,'rules.json':e1.RULES,
              'resource_forecast.json':forecast}
    for name,value in expected.items():
        if json.loads((source/name).read_text())!=value:raise ValueError('changed checkpoint '+name)
    if json.loads((source/'preflight.json').read_text()).get('targets')!=targets:
        raise ValueError('changed checkpoint targets')
    checkpoint=json.loads((source/'checkpoint.json').read_text())
    elapsed=checkpoint['accounted_previous_e1_wall_s']
    if checkpoint['complete'] or not isinstance(elapsed,(int,float)) or not math.isfinite(elapsed) or elapsed<0:
        raise ValueError('invalid stopped runtime accounting')
    raw=Path(manifest['extra']['raw_cache'])
    if not raw.is_absolute():raw=e1.REPO/raw
    raw_manifest=provenance.validate_manifest(raw/'manifest.json')
    if raw_manifest['dirty'] is not False:raise ValueError('unclean checkpoint raw collection')
    return raw,elapsed


def reuse_job(job, source_raw, raw_root, targets, source_operating, operating_path):
    """Copy complete validated producers without rewriting their original provenance."""
    source=source_raw/'runs'/job['id']
    required=[source/'manifest.json',source/'raw/manifest.json',source/'observation.json']
    if job['condition']!='none':required.append(source/'score/manifest.json')
    if not all(p.exists() for p in required):return None
    wrapper=provenance.validate_manifest(source/'manifest.json')
    raw=provenance.validate_manifest(source/'raw/manifest.json')
    expected=e1.document(job,targets)
    if wrapper['dirty'] is not False or raw['dirty'] is not False:raise ValueError('unclean reusable producer')
    if wrapper['config']!=expected:raise ValueError('reusable config mismatch')
    if raw['config']!={'run':expected['engine'],'scheme':expected['scheme']}:
        raise ValueError('reusable raw config mismatch')
    simulation=json.loads((source/'observation.json').read_text())
    if any(simulation.get(k)!=v for k,v in job.items()):raise ValueError('reusable job identity mismatch')
    if simulation['status']!='ok':return None
    result=None
    if job['condition']!='none':
        score=provenance.validate_manifest(source/'score/manifest.json')
        if score['dirty'] is not False:raise ValueError('unclean reusable score')
        twin=source_raw/'runs'/f"{job['const']}-{job['scheme']}-s{job['seed']:04d}-none"/'raw'
        cfg=dict(check_plans=job['scheme']=='chronoroute',flow=0,include_null=True,k=2,q_th_ms=None,
                 rules=str(source_operating.parent/'rules.json') if job['scheme']=='chronoroute' else None,
                 run=str(source/'raw'),twin=str(twin),secondary_flow=1,sensitivity_k=[1,4],slack=[],warmup_s=0.,window_ms=1000.)
        if score['config']!=cfg:raise ValueError('reusable scoring settings mismatch')
        if job['scheme']=='chronoroute' and json.loads((source_operating.parent/'rules.json').read_text())!=e1.RULES:
            raise ValueError('changed reusable rules')
        if provenance.file_sha256(source_operating)!=provenance.file_sha256(operating_path):
            raise ValueError('changed reusable operating point')
        for item in score['extra']['inputs']:
            if provenance.file_sha256(item['path'])!=item['sha256']:raise ValueError('changed reusable score input')
        result=score['extra']['measured_command']
        if result['status']!='ok':return None
    destination=raw_root/'runs'/job['id'];destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copytree(source,destination)
    return simulation,result


def run_group(group, out, raw_root, targets, deadline, operating, *, resume_raw=None, resume_operating=None):
    """Bounded sequential jobs per twin; every launch/failure remains in inventory."""
    observations=[];records=[];manifests=[]
    twin=raw_root/'runs'/group[0]['id']/'raw'
    twin_ok=False
    for job in group:
        item=dict(job,status='not_started',reason='',simulation_status='not_started',score_status='not_started',
                  wall_s=0.,cpu_s=0.,peak_rss_kb=0,returncode=None,command=[],score_wall_s=0.,score_cpu_s=0.,score_peak_rss_kb=0,
                  raw_path=str(raw_root/'runs'/job['id']/'raw'),score_path='')
        if time.monotonic()+60>deadline:
            item['reason']='campaign deadline: insufficient timeout remaining'
            observations.append(item);continue
        if job['condition']!='none' and not twin_ok:
            item['reason']='shared twin failed';observations.append(item);continue
        cached=reuse_job(job,resume_raw,raw_root,targets[f"{job['const']}:{job['pair_id']}"],resume_operating,out/'operating_points.json') if resume_raw is not None else None
        item['reused']=cached is not None
        simulation=cached[0] if cached else e1.run_job(job,raw_root,targets)
        item.update({k:simulation[k] for k in ('wall_s','cpu_s','peak_rss_kb','returncode','command')},simulation_status=simulation['status'],status=simulation['status'])
        folder=raw_root/'runs'/job['id']
        manifests.append(folder/'manifest.json')
        if simulation['status']=='ok':
            manifests.append(folder/'raw/manifest.json')
            m=provenance.validate_manifest(folder/'raw/manifest.json')
            if m['dirty'] is not False:raise ValueError('dirty confirmatory simulation')
            if job['condition']=='none':twin_ok=True
            elif time.monotonic()+60<=deadline:
                score=folder/'score'
                cmd=score_command(job,out,folder/'raw',twin,score)
                result=cached[1] if cached else e1.measured_command(cmd,folder/'score_command')
                item.update(score_status=result['status'],score_wall_s=result['wall_s'],score_cpu_s=result['cpu_s'],
                            score_peak_rss_kb=result['peak_rss_kb'],score_path=str(score))
                if result['status']=='ok':
                    if not cached:e1.attach_metadata(score,e1.document(job)['campaign'],result,inputs=[folder/'raw/manifest.json',twin/'manifest.json',out/'operating_points.json'])
                    manifests.append(score/'manifest.json')
                    try:
                        records.extend(analysis.extract(json.loads((score/'summary.json').read_text()),job,operating))
                    except ValueError as exc:
                        item.update(status='score_invalid',reason=str(exc))
                else:item.update(status='score_failed',reason='offline score '+result['status'])
            else:item.update(status='score_not_started',reason='campaign deadline before scoring')
        else:item['reason']='simulation '+simulation['status']
        observations.append(item)
    return observations,records,manifests


def roc_jobs(out, raw_root, observations):
    """CLI event ROC by condition, retaining every completed native/rule endpoint."""
    groups=defaultdict(list)
    for row in observations:
        if row['condition']!='none' and row['status']=='ok':groups[(row['const'],row['scheme'],row['condition'])].append(row)
    jobs=[]
    for (const,scheme,condition),rows in groups.items():
        if len(rows)!=36:continue
        pairs=[f"{r['raw_path']}:{raw_root/'runs'/f'{const}-{scheme}-s{r['seed']:04d}-none'/'raw'}" for r in sorted(rows,key=lambda r:r['seed'])]
        for offset in range(0,36,6):
            rid=f'{const}-{scheme}-{condition}-block{offset//6}'
            folder=out/'roc'/rid
            cmd=[str(e1.REPO/'venv/bin/python'),'-B','-m','chronoroute.cli','eval','roc','--pairs',*pairs[offset:offset+6],
                 '--flow','0','--include-null','--k','2','--window-ms','1000','--out',str(folder)]
            if scheme=='chronoroute':cmd+=['--rules',str(out/'rules.json')]
            # Aggregate inference uses all thirty-six runs, never these work chunks.
            jobs.append(dict(id=rid,command=cmd,folder=folder))
    return jobs


def main(argv=None):
    """Clean launch, bounded worker pool, offline scoring, analysis and manifest ledger."""
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('out','pilot','prerequisites','e0'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--workers',type=int,choices=range(1,9),default=8)
    parser.add_argument('--resume-from',type=Path,help='reuse validated producers from an immutable stopped checkpoint into a new output folder')
    if argv is not None and '--help' in argv:parser.print_help();return 0
    args=parser.parse_args(argv)
    e1.validate_protocol()
    if provenance.git_state(e1.REPO)['dirty']:raise ValueError('commit implementation before confirmation')
    operating,forecast=validate_inputs(args.pilot,args.prerequisites,args.e0)
    if args.workers!=forecast.get('workers',args.workers):
        raise ValueError('recompute the resource gate for a different worker count')
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    raw_root=args.out.with_name(args.out.name+'-raw');raw_root.mkdir(exist_ok=False)
    source_paths=[args.pilot/'manifest.json',args.pilot/'operating_points.json',args.prerequisites/'manifest.json',
                  args.prerequisites/'resource_forecast.json',args.e0/'manifest.json']
    write_json(args.out/'operating_points.json',operating)
    write_json(args.out/'rules.json',e1.RULES)
    write_json(args.out/'resource_forecast.json',forecast)
    planned=e1.jobs('confirmatory');groups=group_jobs(planned)
    write_json(args.out/'planned_jobs.json',planned)
    # Reserve the other registered experiments and analysis instead of spending their allocation on E1.
    future=sum(forecast['remaining_work_s'][k] for k in ('E04','E05','E16'))
    spent=forecast['spent_prerequisites_s']+forecast['e1_forecast']['measured_spent_s']
    available=21600-spent-1200-future-600
    deadline=time.monotonic()+available
    observations=[];records=[];manifest_paths=[]
    with provenance.RunTimer() as timer:
        targets=e1.preflight(args.out)
        resume_raw=None
        if args.resume_from:
            args.resume_from=args.resume_from.resolve()
            resume_raw,previous=validate_checkpoint(args.resume_from,planned,operating,targets,forecast)
            spent+=previous;available-=previous;deadline-=previous
            source_paths.extend([args.resume_from/'manifest.json',resume_raw/'manifest.json'])
            write_json(args.out/'resume.json',dict(source=str(args.resume_from),raw_source=str(resume_raw),
                       accounted_previous_e1_wall_s=previous,previous_manifest_sha256=provenance.file_sha256(args.resume_from/'manifest.json'),
                       method='Copy only complete validated original producers; preserve originals and rerun unfinished jobs.'))
        resume_options=dict(resume_raw=resume_raw,resume_operating=args.resume_from/'operating_points.json') if resume_raw is not None else {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures=[pool.submit(run_group,g,args.out,raw_root,targets,deadline,operating,**resume_options) for g in groups]
            for future_result in as_completed(futures):
                oo,rr,mm=future_result.result();observations.extend(oo);records.extend(rr);manifest_paths.extend(mm)
                e1.write_csv(args.out/'inventory.csv',observations)
                print(json.dumps(dict(completed_groups=len(observations)//19,total_groups=len(groups),elapsed_s=timer.wall_seconds,
                                      failures=sum(r['status']!='ok' for r in observations))),flush=True)
        observations.sort(key=lambda r:r['id'])
        records.sort(key=lambda r:tuple(r[k] for k in ('const','scheme','condition','seed','k','rule')))
        e1.write_csv(args.out/'inventory.csv',observations)
        bulky={'latency_json','state_json','steady_state_json','reverse_json'}
        e1.write_csv(args.out/'per_run.csv',[{k:v for k,v in r.items() if k not in bulky} for r in records])
        e1.write_csv(args.out/'run_metrics.csv',[r for r in records if r['k']==2 and r['selected']])
        roc=roc_jobs(args.out,raw_root,observations)
        def do_roc(job):
            if time.monotonic()+60>deadline:return dict(id=job['id'],status='not_started',reason='campaign deadline',wall_s=0,cpu_s=0,peak_rss_kb=0,returncode=None,command=job['command'])
            r=dict(id=job['id'],reason='',**e1.measured_command(job['command'],job['folder'].parent/(job['id']+'_command')))
            if r['status']=='ok':
                e1.attach_metadata(job['folder'],dict(prereg_git_sha=e1.PREREG_SHA,prereg_sha256=e1.PREREG_HASH,phase='confirmatory',experiment='E01'),r,inputs=[args.out/'operating_points.json'])
            return r
        with ThreadPoolExecutor(max_workers=args.workers) as pool:roc_observations=list(pool.map(do_roc,roc))
        roc_observations.sort(key=lambda r:r['id'])
        e1.write_csv(args.out/'roc_inventory.csv',roc_observations)
        complete=analysis.write_analysis(args.out,records)
        provenance.write_manifest(raw_root,tool='E01 raw cache collection',tool_version=__version__,
                    command=[sys.executable,'-B',__file__,*(argv if argv is not None else sys.argv[1:])],
                    config=dict(prereg_git_sha=e1.PREREG_SHA,prereg_sha256=e1.PREREG_HASH,phase='confirmatory'),
                    seeds=list(range(1000,1036)),outputs=sorted(p for p in raw_root.rglob('*') if p.is_file()),
                    labels=labels.pick('routes_and_budgets','traffic_probes','fault_slow_link'),timer=timer)
        manifest_paths.append(raw_root/'manifest.json')
        source_paths.append(raw_root/'manifest.json')
        # Original producer manifests are a compressed evidence ledger. Raw files remain available locally.
        for folder in (args.pilot,args.prerequisites):manifest_paths.extend(folder.rglob('manifest.json'))
        (args.out/'inputs').mkdir()
        if args.resume_from:
            ledger=args.resume_from/'inputs/producer-manifests.jsonl.gz'
            if ledger.exists():shutil.copy2(ledger,args.out/'inputs/checkpoint-producer-manifests.jsonl.gz')
        prerequisite_manifest=json.loads((args.prerequisites/'manifest.json').read_text())
        for item in prerequisite_manifest.get('extra',{}).get('inputs',[]):
            source=Path(item['path'])
            if source.name=='manifest.json' and (source.parent/'observations.json').exists():
                original=source.parent
                manifest_paths.extend(original.rglob('manifest.json'))
                evidence=args.out/'inputs/replay-gates';evidence.mkdir(exist_ok=True)
                for path in original.glob('gate-*/comparison.json'):
                    shutil.copy2(path,evidence/(path.parent.name+'.json'))
                shutil.copy2(original/'summary.csv',evidence/'summary.csv')
                source_paths.append(source)
        with gzip.open(args.out/'inputs/producer-manifests.jsonl.gz','wt',encoding='utf-8') as fh:
            for path in sorted(set(manifest_paths)):
                m=json.loads(path.read_text())
                if m['dirty'] is not False:raise ValueError('dirty evidence producer')
                fh.write(json.dumps(dict(path=str(path),sha256=provenance.file_sha256(path),manifest=m),sort_keys=True)+'\n')
        write_json(args.out/'runtime.json',dict(label='REAL host observations; MODELLED projections',wall_s=timer.wall_seconds,
                   previous_spent_s=spent,reserved_future_s=future,available_e1_s=available,workers=args.workers,
                   reused_jobs=sum(bool(r.get('reused')) for r in observations),
                   reused_producer_cpu_s=sum(r['cpu_s']+r['score_cpu_s'] for r in observations if r.get('reused')),
                   simulation_cpu_s=sum(r['cpu_s'] for r in observations if not r.get('reused')),score_cpu_s=sum(r['score_cpu_s'] for r in observations if not r.get('reused')),
                   roc_cpu_s=sum(r['cpu_s'] for r in roc_observations),max_rss_kb=max(r['peak_rss_kb'] for r in observations)))
    success=complete and len(observations)==9576 and all(r['status']=='ok' for r in observations) and len(roc_observations)==1512 and all(r['status']=='ok' for r in roc_observations)
    provenance.write_manifest(args.out,tool='E01 confirmatory campaign',tool_version=__version__,command=[sys.executable,'-B',__file__,*(argv if argv is not None else sys.argv[1:])],
              config=dict(prereg_git_sha=e1.PREREG_SHA,prereg_sha256=e1.PREREG_HASH,phase='confirmatory',workers=args.workers,
                          analysis_seed=91000,bootstrap_resamples=10000,available_e1_s=available),seeds=list(range(1000,1036)),
              snapshot=e1.REPO/'data/pinned/20261010T1358Z-celestrak',
              outputs=sorted(p for p in args.out.rglob('*') if p.is_file() and p!=args.out/'manifest.json'),
              labels=labels.pick('orbital_elements','routes_and_budgets','isl_topology_grid4','traffic_probes','fault_slow_link'),
              extra=dict(complete=success,synthetic_positions='C2 elements and positions MODELLED',raw_cache=str(raw_root),
                         inputs=[dict(path=str(p),sha256=provenance.file_sha256(p)) for p in source_paths]),timer=timer)
    print(json.dumps(dict(complete=success,result=str(args.out),raw_cache=str(raw_root))),flush=True)
    return 0 if success else 1


if __name__=='__main__':raise SystemExit(main())

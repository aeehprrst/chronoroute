"""Supplemental pilot calibration of the final scorer and conservative campaign budget."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

from chronoroute import __version__, labels, provenance
from chronoroute.trace.writer import write_json
import campaign as e1
import confirm


def project_budget(pilot, observations, scores, *, spent_s, gate_ok, workers=8):
    """Keep the whole grid; use conservative costs separately for the two constellations."""
    effort={};complete=True
    effective=min(pilot['effective_workers'],0.75*workers)
    pilot=dict(pilot,effective_workers=effective,
               e1_projected_s=pilot['e1_projected_s']*pilot['effective_workers']/effective)
    simulation_costs={}
    for const in ('C5','C2'):
        for scheme in e1.SCHEMES:
            values=[r['cpu_s'] for r in observations if r['experiment']=='E01' and r['const']==const and r['scheme']==scheme and r['status']=='ok']
            if not values:complete=False;continue
            simulation_costs[const+':'+scheme]=1.25*max(values)
    pilot['e1_projected_s']=sum(simulation_costs.values())*684/effective
    for family,n_per_const in (('E04',1080),('E05',216),('E16',144)):
        cost=0.
        for const in ('C5','C2'):
            values=[r['cpu_s'] for r in observations if r['experiment']==family and r['const']==const and r['status']=='ok']
            if not values:complete=False
            else:cost+=1.25*max(values)*n_per_const/effective
        effort[family]=cost
    scoring=0.
    score_costs={}
    for const in ('C5','C2'):
        for scheme in e1.SCHEMES:
            values=[r['cpu_s'] for r in scores if r['const']==const and r['scheme']==scheme and r['status']=='ok']
            if not values:complete=False;continue
            score_costs[const+':'+scheme]=1.25*max(values)
            # One CLI score and one ROC comparison equivalent per non-twin job.
            scoring+=2*1.25*max(values)*648/effective
    effort['E01_scoring_and_roc']=scoring
    total=spent_s+pilot['measured_spent_s']+pilot['e1_projected_s']+sum(effort.values())+1200+600
    allowed=complete and gate_ok and all(r['status']=='ok' for r in scores+observations) and total<=21600
    return dict(label='MODELLED',confirmation_allowed=allowed,deterministic_gate_passed=gate_ok,
                projected_campaign_wall_s=total,remaining_work_s=effort,spent_prerequisites_s=spent_s,
                score_serial_allowance_s=score_costs,simulation_serial_allowance_s=simulation_costs,e1_forecast=pilot,workers=workers,
                reason='all gates passed' if allowed else 'incomplete measurement, failed gate/job or resource ceiling')


def main(argv=None):
    """Measure final scoring on pilot seeds, preserving the originally frozen operating points."""
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('pilot','prerequisites','out'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--workers',default=8,type=int,choices=range(1,9))
    if argv is not None and '--help' in argv:parser.print_help();return 0
    args=parser.parse_args(argv)
    e1.validate_protocol()
    if provenance.git_state(e1.REPO)['dirty']:raise ValueError('commit code before calibration')
    for folder in (args.pilot,args.prerequisites):
        if provenance.validate_manifest(folder/'manifest.json')['dirty'] is not False:raise ValueError('dirty pilot')
    args.out=args.out.resolve();args.out.mkdir(parents=True,exist_ok=False)
    write_json(args.out/'rules.json',e1.RULES)
    operating=json.loads((args.pilot/'operating_points.json').read_text())
    write_json(args.out/'operating_points.json',operating)
    frozen=provenance.file_sha256(args.pilot/'operating_points.json')
    preflight=json.loads((args.pilot/'preflight.json').read_text())
    targets=preflight['targets']
    planned=[];score_jobs=[]
    for const in ('C5','C2'):
        for scheme in e1.SCHEMES[1:]:
            for condition in (('none',) if scheme in ('ls_h','ls_d','o_q') else ('none',*e1.NOMINAL)):
                planned.append(dict(id=f'{const}-{scheme}-s0000-{condition}',const=const,scheme=scheme,seed=0,
                                    pair_id=0,phase='pilot',condition=condition))
        for seed in range(6):
            for condition in e1.NOMINAL:
                job=dict(id=f'{const}-chronoroute-s{seed:04d}-{condition}',const=const,scheme='chronoroute',seed=seed,pair_id=seed,phase='pilot',condition=condition)
                score_jobs.append((job,args.pilot/'runs'/job['id']/'raw',args.pilot/'runs'/f'{const}-chronoroute-s{seed:04d}-none'/'raw'))
        for scheme in e1.SCHEMES[1:]:
            for condition in e1.NOMINAL:
                job=dict(id=f'{const}-{scheme}-s0000-{condition}',const=const,scheme=scheme,seed=0,pair_id=0,phase='pilot',condition=condition)
                root=args.pilot if scheme in ('ls_h','ls_d','o_q') else args.out
                score_jobs.append((job,root/'runs'/job['id']/'raw',args.out/'runs'/f'{const}-{scheme}-s0000-none'/'raw'))
        # Supplemental performance checks cover long city-pair routes.
        # Their pilot outcomes never enter the already frozen rule selection.
        for seed,schemes in ((16,e1.SCHEMES),(17,('o_q',))):
            for scheme in schemes:
                for condition in ('none','rate-0.3-middle'):
                    job=dict(id=f'{const}-{scheme}-s{seed:04d}-{condition}',const=const,scheme=scheme,seed=seed,
                             pair_id=seed,phase='pilot',condition=condition)
                    planned.append(job)
                    if condition!='none':
                        score_jobs.append((job,args.out/'runs'/job['id']/'raw',args.out/'runs'/f'{const}-{scheme}-s{seed:04d}-none'/'raw'))
    with provenance.RunTimer() as timer:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            simulations=list(pool.map(lambda j:e1.run_job(j,args.out,targets),planned))
        def score(item):
            job,raw,twin=item
            folder=args.out/'scores'/job['id']
            cmd=confirm.score_command(job,args.out,raw,twin,folder)
            row={**job,**e1.measured_command(cmd,args.out/'score_commands'/job['id'])}
            if row['status']=='ok':
                e1.attach_metadata(folder,e1.document(job)['campaign'],row,inputs=[raw/'manifest.json',twin/'manifest.json',args.pilot/'operating_points.json'])
                if job['scheme']=='chronoroute' and job['seed']<6:
                    old=json.loads((raw.parent/'score/summary.json').read_text())['detection']
                    new=json.loads((folder/'summary.json').read_text())['detection']
                    for before,after in zip(old,new):
                        for key in ('fpr','fpr_twin','false_events_twin'):
                            if before[key]!=after[key]:raise ValueError('changed pilot operating-point metric')
                        if before['faults'][0]['packet']['true_detections']!=after['faults'][0]['packet']['true_detections']:
                            raise ValueError('changed pilot counterfactual packet metric')
            return row
        with ThreadPoolExecutor(max_workers=args.workers) as pool:scores=list(pool.map(score,score_jobs))
        prior=json.loads((args.prerequisites/'resource_forecast.json').read_text())
        pilot=json.loads((args.pilot/'resource_forecast.json').read_text())
        observations=json.loads((args.prerequisites/'observations.json').read_text())
        import csv
        initial=[{**r,'experiment':'E01','cpu_s':float(r['cpu_s'])} for r in csv.DictReader((args.pilot/'inventory.csv').open())]
        observations += initial + [{**r,'experiment':'E01'} for r in simulations]
        forecast=project_budget(pilot,observations,scores,spent_s=prior['spent_prerequisites_s']+timer.wall_seconds,
                                gate_ok=prior['deterministic_gate_passed'] and all(r['status']=='ok' for r in simulations),workers=args.workers)
        if provenance.file_sha256(args.pilot/'operating_points.json')!=frozen:raise ValueError('pilot selection changed')
        e1.write_csv(args.out/'inventory.csv',simulations)
        e1.write_csv(args.out/'score_inventory.csv',scores)
        write_json(args.out/'resource_forecast.json',forecast)
        e1.write_csv(args.out/'summary.csv',[dict(endpoint='resource_gate',value=forecast['projected_campaign_wall_s'],unit='seconds',label='MODELLED',status='passed' if forecast['confirmation_allowed'] else 'blocked')])
    provenance.write_manifest(args.out,tool='E01 final scorer pilot calibration',tool_version=__version__,command=[sys.executable,'-B',__file__,*(argv if argv is not None else sys.argv[1:])],
            config=dict(prereg_git_sha=e1.PREREG_SHA,prereg_sha256=e1.PREREG_HASH,workers=args.workers,phase='pilot',reason='measure final scorer; refine conservative per-constellation cost without changing scientific grid'),
            seeds=[*range(6),16,17],outputs=sorted(p for p in args.out.rglob('*') if p.is_file() and p!=args.out/'manifest.json'),
            labels=labels.pick('routes_and_budgets','traffic_probes','fault_slow_link'),
            extra=dict(forecast=forecast,frozen_operating_sha256=frozen,inputs=[dict(path=str(p),sha256=provenance.file_sha256(p)) for p in (args.pilot/'manifest.json',args.prerequisites/'manifest.json')]),timer=timer)
    print(json.dumps(forecast,indent=2),flush=True)
    return 0 if forecast['confirmation_allowed'] else 1


if __name__=='__main__':raise SystemExit(main())

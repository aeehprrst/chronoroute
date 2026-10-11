"""Preregistered E1 confirmation: run units, gates, paired losses and provenance."""
import importlib.util
import json
from pathlib import Path
import sys
import numpy as np
import pytest

REPO = Path('/home/aeehprrst/chronoroute')
sys.path.insert(0, str(REPO / 'experiments/E01'))
SPEC = importlib.util.spec_from_file_location('e01_analysis', REPO / 'experiments/E01/analysis.py')
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)
SPEC2 = importlib.util.spec_from_file_location('e01_confirm', REPO / 'experiments/E01/confirm.py')
c = importlib.util.module_from_spec(SPEC2)
SPEC2.loader.exec_module(c)


def row(seed, scheme='chronoroute', condition='delay-1000000-middle', detected=0):
    return dict(const='C5', scheme=scheme, condition=condition, seed=seed, pair_id=(seed-1000)%18,
                rule='S=1.5 u1', selected=True, k=2, detected=detected, delay_s=0.1 if detected else None,
                restricted_s=0.1 if detected else 4., tp=detected, crossed=2, reached=3, lost_at_fault=1,
                localised_tp=detected, induced_unexposed=0, lost_flags=0, fp=0, clean=10,
                twin_fp=0, twin_clean=12, false_events=0, sending_hours=12/3600,
                sent=24, delivered=23, pdr=23/24, header_bytes=24, header_link_bytes=240,
                control_uplink=10, control_isl=20, control_downlink=0, control_ground=5,
                control_rate_uplink=10/14, control_rate_isl=20/14, control_rate_downlink=0,
                control_rate_ground=5/14, effective_p99_inf_flows=1, delivered_p99_ineligible_flows=1)


def test_seed_bootstrap_and_fixed_city_sensitivity():
    assert a.endpoint_seed('x') == a.endpoint_seed('x') != a.endpoint_seed('y')
    rows = [row(s, detected=s%2) for s in range(1000,1036)]
    ci = a.block_ci(rows, 'detected', 'x', n_boot=100)
    assert ci['estimate'] == .5 and ci['lo'] <= .5 <= ci['hi']
    assert a.block_ci(rows[:35], 'detected', 'x', n_boot=100)['estimate'] is None
    ratio = a.ratio_ci([0, 2], [0, 4], 'x', n_boot=100)
    assert ratio['estimate'] == .5 and ratio['n_boot_undefined'] > 0


def test_summary_retains_censoring_losses_and_zero_exposure():
    rows = [row(s) for s in range(1000,1036)]
    rows[0].update(crossed=0, tp=0)
    summary = a.summarise(rows, n_boot=100)
    assert summary['n'] == 36 and summary['event_mean'] == 0
    assert summary['restricted_mean_s'] == 4 and summary['km_median_s'] is None
    assert summary['undefined_packet_runs'] == 1 and summary['lost_at_fault'] == 36
    assert summary['pdr_mean'] == pytest.approx(23/24) and summary['effective_p99_inf_flows'] == 36
    assert summary['packet_pdet'] == 0 and summary['fpr'] == 0
    oracle = [dict(r, scheme='o_q', detected=None, restricted_s=None) for r in rows]
    assert a.summarise(oracle,n_boot=100)['event_mean'] is None


def test_paired_comparisons_have_fixed_holm_families_and_honest_losses():
    rows=[]
    for const in ('C5','C2'):
        for condition, spec in c.e1.CONDITIONS.items():
            if spec['null']: continue
            for seed in range(1000,1036):
                rows.append(dict(row(seed,condition=condition), const=const))
                for scheme in a.COMPARATORS:
                    rows.append(dict(row(seed,scheme,condition,1),const=const))
    comparisons = a.contrasts(rows,n_boot=100)
    assert len(comparisons)==300
    assert all(r['holm_family_n']==150 and r['material_loss'] for r in comparisons)
    assert all(r['n']==36 and r['adjusted_p']==0 for r in comparisons)
    incomplete = a.contrasts(rows[:-1],n_boot=100)
    assert any(r['status']=='incomplete' for r in incomplete)


def test_extract_native_ls_oracle_and_null_guards():
    job=dict(const='C5',scheme='ls_d',seed=1000,pair_id=0,condition='delay-1000000-middle')
    doc={'pdr':{'sent':24,'delivered':24,'pdr':1,'losses':{}},'latency':[], 'control':{},
         'detection':[{'rule':'as run','fpr':None,'fpr_twin':None,
          'false_events_twin':{'events':2,'hours':12/3600},
          'faults':[{'packet':{'true_detections':0,'exposed':0,'reached':0,'lost_at_fault':0},
                     'event':{'detected':False,'delay_ns':None},
                     'control_plane':{'detected':True,'delay_ns':100000000}}]}]}
    rows=a.extract(doc,job,{'C5':{'rule_index':2}})
    assert rows[0]['detected']==1 and rows[0]['delay_s']==.1 and rows[0]['fp'] is None
    assert a.extract(doc,dict(job,scheme='o_q'),{'C5':{'rule_index':2}})[0]['detected'] is None
    with pytest.raises(ValueError,match='null'):
        a.extract(doc,dict(job,condition='delay-0-middle'),{'C5':{'rule_index':2}})


def test_design_gates_fail_closed_and_groups_are_complete(tmp_path,monkeypatch):
    jobs=c.e1.jobs('confirmatory')
    groups=c.group_jobs(jobs)
    assert len(groups)==504 and all(len(g)==19 and g[0]['condition']=='none' for g in groups)
    assert sum(map(len,groups))==9576
    with pytest.raises(ValueError): c.group_jobs(jobs[1:])
    with pytest.raises(ValueError): c.validate_inputs(tmp_path,tmp_path,tmp_path)
    assert c.main(['--help'])==0


def test_score_command_native_and_rule_sweeps(tmp_path):
    job=c.e1.jobs('confirmatory')[1]
    cmd=c.score_command(job,tmp_path,tmp_path/'raw',tmp_path/'twin',tmp_path/'score')
    assert cmd[cmd.index('--flow')+1]=='0' and '--check-plans' in cmd and '--include-null' in cmd
    native=c.score_command(dict(job,scheme='ls_d'),tmp_path,tmp_path/'raw',tmp_path/'twin',tmp_path/'score')
    assert '--rules' not in native and '--sensitivity-k' in native


def test_output_writer_figures_and_manifest_from_run_files(tmp_path,monkeypatch):
    from chronoroute import provenance
    rows=[row(s,detected=s%2) for s in range(1000,1036)]
    c.e1.write_csv(tmp_path/'per_run.csv',rows)
    a.write_analysis(tmp_path,rows,n_boot=100)
    assert (tmp_path/'summary.csv').exists() and (tmp_path/'figures/detection.png').exists()
    assert (tmp_path/'figures/packet-roc.png').exists() and (tmp_path/'figures/event-roc.png').exists()
    assert json.loads((tmp_path/'verdict.json').read_text())['complete'] is False


def test_successful_input_validation_and_rejection_of_changed_rule(tmp_path):
    from chronoroute import provenance
    dirs=[tmp_path/n for n in ('pilot','prereq','e0')]
    for d in dirs:d.mkdir()
    pilot,prereq,e0=dirs
    operating={const:{'rule_index':2,'rule':c.e1.RULES[2]} for const in ('C5','C2')}
    operating['inputs']=[]
    (pilot/'operating_points.json').write_text(json.dumps(operating))
    (prereq/'resource_forecast.json').write_text(json.dumps(dict(confirmation_allowed=True,deterministic_gate_passed=True)))
    (e0/'summary.csv').write_text('check,violations\nwire,0\n')
    for d in dirs:
        provenance.write_manifest(d,tool='unit',tool_version='1',command=['unit'],config={},seeds=[],outputs=list(d.iterdir()),labels={})
        m=json.loads((d/'manifest.json').read_text());m['dirty']=False;(d/'manifest.json').write_text(json.dumps(m))
    assert c.validate_inputs(*dirs)[0]==operating
    (pilot/'operating_points.json').write_text('{}')
    with pytest.raises(ValueError):c.validate_inputs(*dirs)


def test_run_group_deadline_retains_every_job_and_roc_inventory(tmp_path):
    job=c.e1.jobs('confirmatory')[0]
    group=[job,dict(job,id='fault',condition='delay-1000000-middle')]
    observations,records,manifests=c.run_group(group,tmp_path,tmp_path,{},0,{'C5':{'rule_index':2}})
    assert len(observations)==2 and all(r['status']=='not_started' for r in observations)
    assert not records and not manifests
    observations=[dict(c.e1.jobs('confirmatory')[1],status='ok',seed=s,raw_path=str(tmp_path/f's{s}')) for s in range(1000,1036)]
    jobs=c.roc_jobs(tmp_path,tmp_path,observations)
    assert len(jobs)==6 and jobs[0]['command'].count('--pairs')==1
    assert '--rules' in jobs[0]['command'] and len([s for s in jobs[0]['command'] if ':/' in s])==6
    assert not c.roc_jobs(tmp_path,tmp_path,observations[:35])


@pytest.mark.parametrize('invalid_score',[False,True])
def test_real_group_simulation_scoring_and_null_manifest(tmp_path,monkeypatch,invalid_score):
    from chronoroute import provenance
    from chronoroute.fwd.config import normalise
    from chronoroute.baselines.params import normalise_scheme
    import time
    validate=provenance.validate_manifest
    monkeypatch.setattr(provenance,'validate_manifest',lambda *args,**kwargs: dict(validate(*args,**kwargs),dirty=False))
    jobs=c.e1.jobs('confirmatory')[:1]
    jobs.append(dict(jobs[0],id='unit-null',condition='delay-0-middle'))
    original=c.e1.document
    def small(job,targets=None):
        doc=original(job)
        cfg={'seed':job['seed'],'scenario':{'kind':'walker','preset':'C1','duration_s':5,'drain_s':1,'gsl':{'min_elevation_deg':10}},
             'traffic':{'flows':[{'src':'London','dst':'New York'}]},'schedule':{'plan_links':'instant'},
             'forwarding':{'policy':'continue'},'output':{'trace':'none'}}
        if job['condition']!='none':cfg['faults']=[dict(kind='slow_processing',on_path={'flow':0,'position':'middle'},start_s=1,stop_s=2,delta_ns=0)]
        doc['engine']=normalise(cfg);doc['scheme']=normalise_scheme({'name':'chronoroute','outputs':{'stretch_oracle':False}})
        return doc
    monkeypatch.setattr(c.e1,'document',small)
    if invalid_score:
        def reject(*args):raise ValueError('unit null gate violation')
        monkeypatch.setattr(c.analysis,'extract',reject)
    (tmp_path/'rules.json').write_text(json.dumps(c.e1.RULES))
    (tmp_path/'operating_points.json').write_text('{}')
    observations,records,manifests=c.run_group(jobs,tmp_path,tmp_path/'raw',{'C5:0':{}},time.monotonic()+120,{'C5':{'rule_index':2}})
    if invalid_score:
        assert observations[-1]['status']=='score_invalid' and not records
        assert 'null gate violation' in observations[-1]['reason']
        return
    assert all(r['status']=='ok' for r in observations) and len(records)==27
    assert all(r['tp']==0 and r['detected']==0 for r in records)
    for m in manifests:provenance.validate_manifest(m)


def test_driver_partial_campaign_is_manifested_as_incomplete(tmp_path,monkeypatch):
    from chronoroute import provenance
    dirs={n:tmp_path/n for n in ('pilot','prereq','e0')}
    for p in dirs.values():
        p.mkdir();(p/'manifest.json').write_text(json.dumps({'dirty':False}))
    (dirs['pilot']/'operating_points.json').write_text('{}')
    (dirs['prereq']/'resource_forecast.json').write_text('{}')
    forecast={'remaining_work_s':{'E04':1,'E05':1,'E16':1},'spent_prerequisites_s':1,'e1_forecast':{'measured_spent_s':1}}
    monkeypatch.setattr(c,'validate_inputs',lambda *args: ({},forecast))
    monkeypatch.setattr(c.provenance,'git_state',lambda *args,**kwargs: {'sha':'0'*40,'dirty':False})
    monkeypatch.setattr(c.e1,'validate_protocol',lambda: None)
    monkeypatch.setattr(c.e1,'preflight',lambda *args: {})
    monkeypatch.setattr(c,'group_jobs',lambda *args: [[]])
    observation=dict(c.e1.jobs('confirmatory')[0],status='ok',cpu_s=1,score_cpu_s=0,peak_rss_kb=1)
    def work(*args):
        (args[2]/'unit-score.log').write_text('unit fixture')
        return [observation],[row(1000)],[]
    monkeypatch.setattr(c,'run_group',work)
    monkeypatch.setattr(c,'roc_jobs',lambda *args: [])
    monkeypatch.setattr(c.analysis,'write_analysis',lambda *args: False)
    args=['--out',str(tmp_path/'out'),'--workers','1']
    for n,p in dirs.items():args+=['--'+('prerequisites' if n=='prereq' else n),str(p)]
    assert c.main(args)==1
    m=provenance.validate_manifest(tmp_path/'out/manifest.json')
    assert not m['extra']['complete']
    raw=provenance.validate_manifest(tmp_path/'out-raw/manifest.json')
    assert any(entry['path']=='unit-score.log' for entry in raw['outputs'])


def test_resource_projection_uses_constellation_costs_without_changing_grid():
    import resource_gate as gate
    pilot={'e1_projected_s':100,'effective_workers':6,'measured_spent_s':10}
    observations=[dict(experiment=family,const=const,status='ok',cpu_s=cost)
                  for family in ('E04','E05','E16') for const,cost in (('C5',4),('C2',2))]
    observations += [dict(experiment='E01',const=const,scheme=scheme,status='ok',cpu_s=1)
                     for const in ('C5','C2') for scheme in c.e1.SCHEMES]
    scores=[dict(const=const,scheme=scheme,status='ok',cpu_s=2 if scheme=='chronoroute' else 1)
            for const in ('C5','C2') for scheme in c.e1.SCHEMES]
    result=gate.project_budget(pilot,observations,scores,spent_s=10,gate_ok=True)
    assert result['confirmation_allowed'] and result['projected_campaign_wall_s']<21600
    assert result['remaining_work_s']['E04']==pytest.approx(1.25*(4+2)*1080/6)
    assert result['remaining_work_s']['E01_scoring_and_roc']==pytest.approx(2*1.25*(2*2+12)*648/6)
    assert not gate.project_budget(pilot,observations,[],spent_s=10,gate_ok=True)['confirmation_allowed']
    assert not gate.project_budget(pilot,observations,scores,spent_s=30000,gate_ok=True)['confirmation_allowed']
    assert gate.main(['--help'])==0


def test_complete_condition_curves_keep_run_units_and_reverse_endpoints(tmp_path):
    rows=[]
    for cond,spec in c.e1.CONDITIONS.items():
        if spec['null']:continue
        for seed in range(1000,1036):
            r=row(seed,condition=cond,detected=seed%2)
            r['reverse_json']=json.dumps([dict(flow=1,packet=dict(true_detections=1,exposed=2,reached=2,lost_at_fault=0),
                          event=dict(detected=True,delay_ns=100000000),fpr=dict(false_positives=0,clean=10),
                          fpr_twin=dict(false_positives=0,clean=12),false_events_twin=dict(events=0,hours=12/3600))])
            rows.append(r)
    assert not a.write_analysis(tmp_path,rows,n_boot=100)
    import csv
    curve=list(csv.DictReader((tmp_path/'campaign_roc.csv').open()))
    assert len(curve)==1 and float(curve[0]['event_mean'])==.5 and int(curve[0]['n'])==36
    reverse=list(csv.DictReader((tmp_path/'reverse_summary.csv').open()))
    assert len(reverse)==15 and all(float(r['event_mean'])==1 for r in reverse)


@pytest.mark.parametrize('previous',[False,True])
def test_calibration_driver_records_all_supplemental_jobs_and_frozen_rule(tmp_path,monkeypatch,previous):
    import resource_gate as gate
    from chronoroute import provenance
    pilot=tmp_path/'pilot';prior=tmp_path/'prior';out=tmp_path/'calibration'
    for p in (pilot,prior):p.mkdir();(p/'manifest.json').write_text('{}')
    (pilot/'operating_points.json').write_text('{}')
    (pilot/'preflight.json').write_text(json.dumps({'targets':{}}))
    (pilot/'inventory.csv').write_text('const,scheme,status,cpu_s\n')
    (pilot/'resource_forecast.json').write_text(json.dumps(dict(effective_workers=6,measured_spent_s=1,e1_projected_s=10)))
    (prior/'resource_forecast.json').write_text(json.dumps(dict(spent_prerequisites_s=1,deterministic_gate_passed=True)))
    observations=[dict(experiment=family,const=const,status='ok',cpu_s=1) for family in ('E04','E05','E16') for const in ('C5','C2')]
    (prior/'observations.json').write_text(json.dumps(observations))
    point=dict(fpr={'x':0},fpr_twin={'x':0},false_events_twin={'x':0},faults=[dict(packet=dict(true_detections=0))])
    for const in ('C5','C2'):
        for seed in range(6):
            for condition in c.e1.NOMINAL:
                score=pilot/'runs'/f'{const}-chronoroute-s{seed:04d}-{condition}'/'score'
                score.mkdir(parents=True);(score/'summary.json').write_text(json.dumps({'detection':[point]}))
    validate=provenance.validate_manifest
    monkeypatch.setattr(gate.e1.provenance,'validate_manifest',lambda *args,**kwargs: {'dirty':False})
    monkeypatch.setattr(gate.e1.provenance,'git_state',lambda *args,**kwargs: {'sha':'0'*40,'dirty':False})
    monkeypatch.setattr(gate.e1,'validate_protocol',lambda: None)
    monkeypatch.setattr(gate.e1,'attach_metadata',lambda *args,**kwargs: None)
    def simulate(job,output,*args):
        folder=output/'runs'/job['id']/'raw';folder.mkdir(parents=True)
        for name in gate.PARITY_FILES:(folder/name).write_bytes(b'unit fixture')
        return dict(job,status='ok',cpu_s=1)
    monkeypatch.setattr(gate.e1,'run_job',simulate)
    def score(command,*args,**kwargs):
        folder=Path(command[command.index('--out')+1]);folder.mkdir(parents=True)
        (folder/'summary.json').write_text(json.dumps({'detection':[point]}))
        return dict(status='ok',cpu_s=1,wall_s=1,peak_rss_kb=1,returncode=0,command=command)
    monkeypatch.setattr(gate.e1,'measured_command',score)
    args=['--pilot',str(pilot),'--prerequisites',str(prior),'--out',str(out),'--workers','8']
    if previous:
        old=tmp_path/'previous';old.mkdir();(old/'manifest.json').write_text('{}')
        (old/'resource_forecast.json').write_text(json.dumps({'spent_prerequisites_s':2}))
        for const in ('C5','C2'):
            for seed,conditions in ((0,('none',)),(16,('none','rate-0.3-middle')),(17,('none','rate-0.3-middle'))):
                for condition in conditions:
                    folder=old/'runs'/f'{const}-o_q-s{seed:04d}-{condition}'/'raw';folder.mkdir(parents=True)
                    for name in gate.PARITY_FILES:(folder/name).write_bytes(b'unit fixture')
        args+=['--previous-calibration',str(old)]
    assert gate.main(args)==0
    m=validate(out/'manifest.json')
    import csv
    assert len(list(csv.DictReader((out/'inventory.csv').open())))==62
    assert len(list(csv.DictReader((out/'score_inventory.csv').open())))==88
    assert m['extra']['frozen_operating_sha256']==provenance.file_sha256(pilot/'operating_points.json')
    if previous:
        parity=json.loads((out/'optimization_parity.json').read_text())
        assert len(parity)==10 and all(r['violations']==0 for r in parity)


def test_packet_ratio_distribution_and_unlocalised_monitors_are_explicit(tmp_path):
    import csv
    rows=[row(seed,detected=seed%2) for seed in range(1000,1036)]
    rows[0].update(crossed=0,tp=0)
    rows += [dict(r,scheme='e2e',localised_tp=None) for r in rows]
    a.write_analysis(tmp_path,rows,n_boot=100)
    ratios=list(csv.DictReader((tmp_path/'packet_run_ratios.csv').open()))
    assert len(ratios)==72 and ratios[0]['packet_ratio']==''
    assert all(r['localisation_ratio']=='' for r in ratios if r['scheme']=='e2e')
    distribution=list(csv.DictReader((tmp_path/'packet_ratio_distribution.csv').open()))
    assert all(int(r['undefined_runs'])==1 and int(r['defined_runs'])==35 for r in distribution)
    assert all(float(r['max'])==.5 for r in distribution)


def test_optimized_pilot_file_comparison_refuses_missing_or_changed_evidence(tmp_path):
    import resource_gate as gate
    before=tmp_path/'before';after=tmp_path/'after'
    before.mkdir();after.mkdir()
    for name in gate.PARITY_FILES:
        (before/name).write_bytes(b'unit fixture');(after/name).write_bytes(b'unit fixture')
    assert gate.compare_pilot_outputs(before,after)['violations']==0
    (after/gate.PARITY_FILES[0]).write_bytes(b'changed fixture')
    assert gate.compare_pilot_outputs(before,after)['violations']==1
    (after/gate.PARITY_FILES[1]).unlink()
    assert gate.compare_pilot_outputs(before,after)['violations']==2

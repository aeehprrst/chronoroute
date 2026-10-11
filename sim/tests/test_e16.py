"""E16 uses actual engine records and paired run-level equivalence."""
import copy
import importlib.util
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from chronoroute.export import ns3_crosscheck as cc
from chronoroute.eval import metrics

ROOT=Path(__file__).resolve().parents[2]


def packet(seq=0):
    return dict(flow_id=0,seq=seq,send_ns=seq*10000000,row_from_ms=0,num_hops=2,epoch_base=1,
        wire_bytes=274,planned_path=[5,1,6],taken_path=[5,1,6],hop_t_ns=[seq*10000000+10,seq*10000000+20],
        hop_now_u=[1,1],hop_deadline_u=[2,3],first_late_hop=None,dev=0,dev_hop=0,outcome='delivered',
        outcome_node=6,outcome_t_ns=seq*10000000+20,rx_ns=seq*10000000+20,latency_ns=20,
        tx_ns=[seq*10000000,seq*10000000+10],wait_ns=[0,0],tx_loss_at='',link_down_at='')


def info():
    return dict(t0_gps_ns=0,unit_code=1,stop_ns=14000000000,send_window_ns=[0,12000000000],
        effective_policy='continue',flows=[dict(flow_id=0,src='A',dst='B')],data_rate='1Gbps')


def test_native_adapter_and_strict_comparator_use_recorded_transmissions():
    rows=[packet()];run=cc.ns3_run(rows,info(),[])
    assert cc.compare_replays(run,rows,require_tx=True)['violations']==0
    changed=copy.deepcopy(rows);changed[0]['tx_ns'][0]+=1
    assert cc.compare_replays(run,changed,require_tx=True)['violations']==1
    duplicate=copy.copy(run);duplicate.n=2
    for attr in ('flow','seq'):setattr(duplicate,attr,np.array([0,0]))
    with pytest.raises(ValueError,match='duplicate'):cc.compare_replays(duplicate,rows)
    del rows[0]['tx_ns']
    with pytest.raises(ValueError,match='transmission'):cc.ns3_run(rows,info(),[])


def test_native_losses_and_rate_cut_backlog_never_become_clean():
    row=packet();row.update(outcome='drop_queue',taken_path=[5],hop_t_ns=[],hop_now_u=[],hop_deadline_u=[],
        tx_ns=[],wait_ns=[],tx_loss_at='5:1:5:-1',outcome_node=5,outcome_t_ns=5,rx_ns=None,latency_ns=None)
    fault=dict(kind='rate_cut',link=[1,5],start_ns=0,stop_ns=10,params={'factor':'1/2'})
    run=cc.ns3_run([row],info(),[fault])
    assert metrics.packet_labels(run).tolist()==[1]
    assert cc.replay_metrics(run)['pdr']==0 and cc.replay_metrics(run)['fpr'] is None
    changed=copy.deepcopy(row);changed['tx_loss_at']=''
    with pytest.raises(ValueError,match='transmitter'):cc.ns3_run([changed],info(),[fault])
    row=packet();row.update(outcome='drop_iface_down',taken_path=[5],hop_t_ns=[],hop_now_u=[],hop_deadline_u=[],
        tx_ns=[0],wait_ns=[0],outcome_node=1,outcome_t_ns=10,rx_ns=None,latency_ns=None)
    run=cc.ns3_run([row],info(),[])
    assert list(run.path(0))==[5,1] and list(run.arr_ns(0))==[10]
    assert cc.compare_replays(run,[row],require_tx=True)['violations']==0
    assert metrics.packet_labels(run).tolist()==[2]
    rows=[packet(0),packet(1),packet(2)]
    rows[0]['tx_ns'][0]=4;rows[0]['wait_ns'][0]=4
    rows[1]['send_ns']=11;rows[1]['tx_ns']=[12,22];rows[1]['wait_ns']=[1,0];rows[1]['hop_t_ns']=[22,32]
    rows[2]['send_ns']=20;rows[2]['tx_ns']=[20,30];rows[2]['wait_ns']=[0,0];rows[2]['hop_t_ns']=[30,40]
    run=cc.ns3_run(rows,info(),[fault])
    assert metrics.packet_labels(run).tolist()==[1,1,0]


def test_replay_metrics_nearest_rank_support_and_losses_are_infinite():
    rows=[packet(i) for i in range(1200)]
    run=cc.ns3_run(rows,info(),[]);r=cc.replay_metrics(run)
    assert r['pdr']==1 and r['fpr']==0 and r['clean']==1200
    assert r['latency'][0]['q0.5']==r['latency'][0]['q0.99_eff']==20
    for row in rows[-20:]:
        row.update(outcome='drop_queue',taken_path=[5],hop_t_ns=[],hop_now_u=[],hop_deadline_u=[],
            tx_ns=[],wait_ns=[],tx_loss_at=f"5:1:{row['send_ns']}:-1",outcome_node=5,rx_ns=None,latency_ns=None)
    r=cc.replay_metrics(cc.ns3_run(rows,info(),[]))
    assert r['losses']['buffer_overflow']==20 and math.isinf(r['latency'][0]['q0.99_eff'])
    assert cc.replay_metrics(cc.ns3_run(rows[:10],info(),[]))['latency'][0]['q0.99_eff'] is None


def test_tost_requires_both_bounds_and_reports_90_and_95_intervals():
    r=cc.tost([0.]*36,.01)
    assert r['equivalent'] and r['lo90']==r['hi90']==r['lo95']==r['hi95']==0
    assert r['p_lower']==r['p_upper']==0
    assert not cc.tost([.01]*36,.01)['equivalent']
    assert not cc.tost([.02]*36,.01)['equivalent']
    d=np.linspace(-.001,.001,36);r=cc.tost(d,.01)
    assert r['equivalent'] and r['lo95']<r['lo90']<0<r['hi90']<r['hi95']
    for values in ([math.inf]*36,[float('nan')]*36,[]):
        with pytest.raises(ValueError):cc.tost(values,.01)


def test_equivalence_keeps_all_runs_undefined_tails_and_flow_log_ratios():
    metric=dict(pdr=1.,fpr=0.,sent=2400,delivered=2400,latency=[
        dict(flow=0,q0_5=1),dict(flow=1,q0_5=1)])
    metric['latency']=[{'flow':f,'q0.5':100,'q0.99_eff':200} for f in (0,1)]
    pairs=[dict(seed=1000+i,python=copy.deepcopy(metric),ns3=copy.deepcopy(metric)) for i in range(36)]
    for endpoint in ('pdr','fpr','p50','p99'):
        r=cc.equivalence(pairs,endpoint);assert r['equivalent'] and r['n']==36
        assert r['estimate']==(1. if endpoint.startswith('p5') or endpoint=='p99' else 0.)
    pairs[0]['ns3']['latency'][0]['q0.99_eff']=math.inf
    r=cc.equivalence(pairs,'p99');assert not r['equivalent'] and r['undefined_runs']==1 and r['n']==36
    pairs[0]['ns3']['fpr']=None
    assert not cc.equivalence(pairs,'fpr')['equivalent']
    pairs[0]['ns3']['latency'][0]['q0.5']=121
    assert cc.equivalence(pairs,'p50')['estimate']==pytest.approx(math.exp(math.log(1.21)/2/36))
    with pytest.raises(ValueError):cc.equivalence(pairs+pairs[:1],'pdr')
    assert not cc.equivalence(pairs[:29],'pdr')['equivalent']


def test_confirmatory_replay_uses_balanced_pairs_instead_of_pilot_mapping():
    import sys
    sys.path.insert(0,str(ROOT/'experiments/E01'))
    import prerequisites as pre
    cfg=pre.replay_config('C2',1000,stochastic=True,fault=True)
    assert cfg['traffic']['flows'][0]['src']=='Mumbai' and cfg['traffic']['flows'][0]['dst']=='Dubai'
    assert cfg['forwarding']['processing_ns']==cfg['schedule']['planner_processing_ns']==0
    assert cfg['forwarding']['fallback']=='none'


def test_e16_registered_grid_and_analysis_preserve_incomplete_cells(tmp_path):
    spec=importlib.util.spec_from_file_location('e16_campaign',ROOT/'experiments/E16/run.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    jobs=mod.jobs(True);assert len(jobs)==144 and len(mod.jobs(False))==4
    assert {j['seed'] for j in jobs}==set(range(1000,1036))
    assert all(j['pair_id']==(j['seed']-1000)%18 for j in jobs)
    verdict=mod.analyse(tmp_path,[],[],[])
    assert not verdict['complete'] and not verdict['equivalent']


def campaign():
    spec=importlib.util.spec_from_file_location('e16_test_campaign',ROOT/'experiments/E16/run.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    return mod


def test_e16_budget_and_dirty_gate_refuse_unreviewable_runs(tmp_path,monkeypatch):
    import json
    mod=campaign()
    monkeypatch.setattr(mod.provenance,'validate_manifest',lambda p:dict(dirty=False,extra={'complete':True}))
    (tmp_path/'runtime.json').write_text(json.dumps(dict(wall_s=100,accounted_wall_s=200)))
    (tmp_path/'resource_forecast.json').write_text(json.dumps(dict(previous_spent_s=1000,reserved_future_s=1900)))
    forecast=mod.budget(tmp_path)
    assert forecast['previous_spent_s']==1200 and forecast['available_s']==18600
    assert forecast['projected_e16_s']==100
    (tmp_path/'runtime.json').write_text(json.dumps(dict(wall_s=21000)))
    with pytest.raises(ValueError,match='budget'):mod.budget(tmp_path)
    monkeypatch.setattr(mod.e1,'validate_protocol',lambda:None)
    monkeypatch.setattr(mod.provenance,'git_state',lambda p:dict(dirty=True))
    with pytest.raises(ValueError,match='commit'):mod.main(['--out',str(tmp_path/'dirty')])
    assert not (tmp_path/'dirty').exists()


def test_e16_unstarted_job_is_manifested_without_launching_an_engine(tmp_path,monkeypatch):
    import json
    mod=campaign()
    monkeypatch.setattr(mod.pre,'run_replay',lambda *a,**k:pytest.fail('deadline must prevent engine launch'))
    job=mod.jobs(True)[0]
    obs,record,comparison=mod.run_job(job,tmp_path/'unstarted',0,['unit-fixture'])
    assert obs['status']=='not_started' and obs['error'].startswith('TimeoutError:')
    assert record is comparison is None
    m=mod.provenance.validate_manifest(tmp_path/'unstarted/manifest.json')
    assert m['extra']['observation']==obs
    assert json.loads((tmp_path/'unstarted/observation.json').read_text())['id']==job['id']


def test_e16_actual_small_replay_compares_both_engines(tmp_path,monkeypatch):
    mod=campaign()
    if not mod.pre.NS3.exists():pytest.skip('ns-3 binary unavailable')
    cfg=mod.pre.replay_config('C2',0,stochastic=False,fault=False)
    cfg['scenario'].update(kind='walker',preset='C1',duration_s=1)
    for flow in cfg['traffic']['flows']:flow['send_times_ns']=list(range(1000000,1000000000,100000000))
    monkeypatch.setattr(mod.pre,'replay_config',lambda *a,**k:cfg)
    obs,record,comparison=mod.run_job(mod.jobs(False)[2],tmp_path/'small',float('inf'),['unit-fixture'])
    assert obs['status']=='ok',obs['error']
    assert record['python']['sent']==record['ns3']['sent']==20
    assert comparison['violations']==comparison['max_abs_time_error_ns']==0
    mod.provenance.validate_manifest(tmp_path/'small/manifest.json')


def test_e16_complete_analysis_and_undefined_tail_preserve_all_seeds(tmp_path,monkeypatch):
    import json
    mod=campaign();monkeypatch.setattr(mod,'plot',lambda *a:None)
    metric=dict(sent=2400,delivered=2400,pdr=1.,clean=2400,false_positives=0,fpr=0.,losses={},labels={},
        latency=[{'flow':f,'q0.5':100,'q0.99_eff':200} for f in (0,1)])
    records=[{**j,'python':copy.deepcopy(metric),'ns3':copy.deepcopy(metric)} for j in mod.jobs(False)+mod.jobs(True)]
    observations=[{**j,'status':'ok'} for j in mod.jobs(False)+mod.jobs(True)]
    comparison=dict(packets_python=2400,packets_ns3=2400,checked_fields=48000,violations=0,mismatched_packets=0,max_abs_time_error_ns=0)
    verdict=mod.analyse(tmp_path,records,observations,[comparison]*148)
    assert verdict['complete'] and verdict['equivalent'] and verdict['packets_python']==355200
    records[-1]['ns3']['latency'][0]['q0.99_eff']=math.inf
    verdict=mod.analyse(tmp_path,records,observations,[comparison]*148)
    assert verdict['complete'] and not verdict['equivalent']
    assert len(verdict['undefined_endpoints'])==1 and verdict['undefined_endpoints'][0]['n']==36
    assert json.loads((tmp_path/'per_run.json').read_text())[-1]['ns3']['latency'][0]['q0.99_eff']=='inf'


def test_strict_replay_compares_recorded_checker_dead_next_link(tmp_path):
    row=packet();row.update(outcome='drop_link_down',taken_path=[5,1],hop_t_ns=[10],
        hop_now_u=[1],hop_deadline_u=[2],tx_ns=[0],wait_ns=[0],outcome_node=1,
        outcome_t_ns=10,rx_ns=None,latency_ns=None,dev=1,dev_hop=1,link_down_at='1:6:10')
    run=cc.ns3_run([row],info(),[])
    # ChronoRoute records this checker decision in hop_k and actual arrivals;
    # table schemes use the explicit event column instead.
    from chronoroute.eval.load import Ragged
    run.extras['link_down_at']=[''];run.extras['hop_k']=Ragged(['1'])
    assert cc.compare_replays(run,[row],require_tx=True)['violations']==0

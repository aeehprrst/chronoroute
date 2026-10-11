"""Registered outage and policy campaigns: design, losses and run-level inference."""
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'experiments'))
sys.path.insert(0, str(ROOT / 'experiments/E01'))
import policy_campaign as pc
import policy_analysis as pa


def test_registered_jobs_preserve_controls_seeds_and_pair_balance():
    for exp, count, schemes in [('E04', 2160, 6), ('E05', 432, 6)]:
        jobs = pc.jobs(exp)
        assert len(jobs) == count and len({j['id'] for j in jobs}) == count
        assert {j['seed'] for j in jobs} == set(range(1000,1036))
        assert all(j['pair_id'] == (j['seed']-1000)%18 for j in jobs)
        assert len([j for j in jobs if j['condition']=='none']) == (432 if exp=='E04' else 72)
    with pytest.raises(ValueError): pc.jobs('E01')


def test_renewal_is_targeted_stationary_and_not_forced():
    from chronoroute.fwd.faults import renewal_periods
    from chronoroute.fwd.rng import KeyedStreams
    for profile in pc.PROFILES:
        target = [12,14] if profile.startswith('link') else 12
        kind, u, mttr = pc.PROFILES[profile]
        key = tuple(target) if kind=='link' else (target,)
        expected = renewal_periods(KeyedStreams(1000),kind+'_fault',key,3_000_000_000,27_000_000_000,u,mttr)
        faults = pc.compile_faults(1000, profile, target)
        assert [(int(round(float(f['start_s'])*1e9)),int(round(float(f['stop_s'])*1e9))) for f in faults] == expected
        assert all(f[kind] == target and f['kind']==kind+'_down' for f in faults)
    assert any(not pc.compile_faults(s,'link-A',[12,14]) for s in range(1000,1036))


def test_documents_enable_stretch_costs_and_exact_registered_policies():
    design={'C5:1000':{'link':[1,2],'node':1,'trigger':2}}
    for exp in ('E04','E05'):
        for j in [x for x in pc.jobs(exp) if x['const']=='C5' and x['seed']==1000]:
            d=pc.document(j,design)
            cfg,sch=d['engine'],d['scheme']
            assert cfg['schedule']['plan_links']=='stable' and cfg['schedule']['slack']=='1.5'
            assert cfg['forwarding']['processing_ns']==cfg['schedule']['planner_processing_ns']==500000
            assert cfg['forwarding']['background']['model']=='none' and cfg['forwarding']['jitter']['model']=='none'
            assert sch['outputs']['stretch_oracle'] and sch['snap']['count_uploads'] and sch['crh_state']['count']
            assert d['campaign']['experiment']==exp and d['campaign']['phase']=='confirmatory'
            if exp=='E04':
                assert cfg['scenario']['duration_s']==30
                if j['scheme'] in ('continue','crh16'): assert cfg['forwarding']['fallback']=='none'
                if j['scheme']=='ls_h': assert sch['ls']['bfd'] and sch['ls']['bfd_mult']==3
            else:
                assert not cfg['faults'] and d['intervention']['target']==(-1 if j['condition']=='none' else 2)


def test_effective_tail_and_trigger_loss_denominators():
    from chronoroute.eval import metrics
    r=SimpleNamespace(n=1200,engine={'end_ns':14_000_000_000,'drain_ns':2_000_000_000},
                      send_ns=np.arange(1200)*10_000_000,flow=np.zeros(1200,int),
                      flows=[{'flow_id':0}],outcome=np.r_[np.zeros(1180,int),np.ones(20,int)],
                      latency_ns=np.r_[np.ones(1180,int)*1000,np.ones(20,int)*-1])
    r.delivered=r.outcome==0
    assert math.isinf(pc.effective_tail(r,metrics.measurement_mask(r),'0.99')[0])
    assert pc.effective_tail(r,np.arange(1200)<500,'0.99')[0] is None
    rec=[{'pkt':i} for i in range(1190,1200)]
    r.reason=['']*1190+['stuck']*4+['late_drop']*6
    d=pc.trigger_counts(r,rec)
    assert d['triggered']==10 and d['stuck']==4 and d['strict_drop']==6 and d['triggered_delivered']==0
    assert pc.trigger_counts(r,[])['triggered_pdr'] is None


def test_analysis_keeps_infinite_runs_and_small_outage_sample():
    rows=[dict(seed=1000+i,pair_id=i%18,pdr=1.,blackhole_s=None if i<30 else .1,
               effective_p99_s=math.inf if i==0 else .01,tail_ineligible=0,outages=int(i>=30),
               stretch_min_exact=1.01,stretch_min_adjusted=1.,stretch_min_raw=.999,
               stretch_violations=0) for i in range(36)]
    a=pa.aggregate(rows,'fixture',n_boot=100)
    assert a['n']==36 and a['complete'] and a['blackhole_n']==6 and a['no_outage_runs']==30
    assert math.isinf(a['effective_p99_mean']) and a['infinite_tail_runs']==1
    assert a['stretch_min_adjusted']==1 and a['stretch_min_raw']==.999
    assert not pa.aggregate(rows[:-1],'incomplete',n_boot=100)['complete']


def test_paired_infinite_categories_are_not_subtracted():
    a=[{'seed':i,'effective_p99_s':x,'pdr':1.} for i,x in enumerate([math.inf,.02,math.inf])]
    b=[{'seed':i,'effective_p99_s':x,'pdr':1.} for i,x in enumerate([.01,math.inf,math.inf])]
    d=pa.contrast(a,b,'effective_p99_s','fixture',n_boot=100)
    assert d['p'] is None and d['reason'] and d['both_infinite']==1
    assert d['a_only_infinite']==1 and d['b_only_infinite']==1 and d['n']==3
    assert d['tail_failure_mean_diff']==0
    with pytest.raises(ValueError): pa.contrast(a,b[:-1],'pdr','bad')
    single=pa.contrast([dict(seed=1,effective_p99_s=.02)],[dict(seed=1,effective_p99_s=.01)],'effective_p99_s','single',n_boot=10)
    assert single['ratio']==pytest.approx(2) and single['ratio_lo'] is None
    missing=pa.contrast([dict(seed=1,effective_p99_s=None),dict(seed=2,effective_p99_s=.02)],
                        [dict(seed=1,effective_p99_s=.01),dict(seed=2,effective_p99_s=.01)],'effective_p99_s','missing')
    assert missing['mean_diff'] is None and missing['p'] is None


def test_five_untriggered_policies_are_packet_identical_and_hook_prefixes_match(tmp_path):
    from chronoroute.baselines import run as br, params
    from chronoroute.fwd.config import normalise
    from chronoroute.fwd.scenario import build_scenario
    from chronoroute.eval.load import load_run
    cfg=normalise({'seed':2,'scenario':{'kind':'walker','preset':'C1','duration_s':9,'drain_s':1,
        'gsl':{'min_elevation_deg':10}},'traffic':{'flows':[{'src':'London','dst':'New York'}]},
        'output':{'invariants':'all','trace':'none'}})
    sc=build_scenario(cfg)
    target=sc.resolve_on_path({'flow':0,'at_s':4,'position':'middle'},4_000_000_000,True)
    controls=[];active=[]
    for name in pc.POLICIES:
        for enabled in (False,True):
            c=json.loads(json.dumps(cfg));pc.set_policy(c,name)
            records=[]
            out=tmp_path/f'{name}-{enabled}'
            s,_=br.run_scheme(c,params.normalise_scheme('chronoroute'),out,
                engine_factory=pc.pre.deviation_factory(target if enabled else -1,records),write_manifest=False,
                run_extra={'intervention':{'records':records}})
            assert s['invariants']['violations']==0
            r=load_run(out)
            (active if enabled else controls).append(r)
            if enabled:
                assert records and len(records)==len({x['pkt'] for x in records})
                for x in records:
                    i=x['pkt'];k=len(x['path_before'])
                    assert list(r.path(i)[:k])==x['path_before']
                    assert r.dev[i] and r.dev_hop[i]>=1
                if name=='drop':assert pc.trigger_counts(r,records)['strict_drop']==len(records)
    base=controls[0]
    for r in controls[1:]:
        for attr in ('wire','latency_ns','outcome','hops','dev','first_late'):assert np.array_equal(getattr(r,attr),getattr(base,attr))
        assert all(np.array_equal(r.path(i),base.path(i)) and np.array_equal(r.arr_ns(i),base.arr_ns(i)) for i in range(r.n))
    for r in active: assert pc.check_prefix(r,base)['violations']==0
    active[0].send_ns[0]+=1
    with pytest.raises(ValueError):pc.check_prefix(active[0],base)


def test_analysis_fixed_families_and_undefined_contrasts(tmp_path):
    rows=[]
    for const in ('C5','C2'):
        for profile in pc.PROFILES:
            for scheme in pc.SCHEMES:
                for seed in range(1000,1036):
                    rows.append(dict(const=const,condition=profile,scheme=scheme,seed=seed,pair_id=(seed-1000)%18,
                        pdr=.98 if scheme=='greedy_visited' else 1.,blackhole_s=None,effective_p99_s=math.inf,
                        tail_ineligible=0,outages=0,stretch_violations=0))
    contrasts=pa.comparisons(rows,'E04',n_boot=100)
    for field in ('pdr','blackhole_s','effective_p99_s'):
        cell=[r for r in contrasts if r['endpoint']==field]
        assert len(cell)==40 and all(r['family_n']==40 for r in cell)
    assert all(r['adjusted_p'] is None for r in contrasts if r['endpoint']!='pdr')
    assert all(r['material_loss'] for r in contrasts if r['endpoint']=='pdr')


def test_serialization_and_no_trigger_ratios_never_emit_nan(tmp_path,monkeypatch):
    import csv
    assert pc.clean({'x':math.inf,'y':[-math.inf]})=={'x':'inf','y':['-inf']}
    assert pa.decode(pc.clean({'x':math.inf}))=={'x':math.inf}
    with pytest.raises(ValueError):pc.clean(float('nan'))
    rows=[dict(seed=s,pair_id=(s-1000)%18,triggered=0,triggered_delivered=0,stuck=0,sent=20,delivered=20,
               const='C5',condition='none',scheme='greedy_visited',pdr=1.,blackhole_s=None) for s in range(1000,1036)]
    a=pa.aggregate(rows,'empty-trigger',n_boot=100)
    assert a['stuck_pooled_estimate'] is None and a['triggered_pdr_pooled_estimate'] is None
    assert not pa.write_analysis(tmp_path,rows,'E05',n_boot=100)
    json.loads((tmp_path/'verdict.json').read_text())
    assert 'nan' not in (tmp_path/'summary.csv').read_text().lower()


def test_preflight_freezes_pair_routes_and_keyed_uniform_targets(tmp_path,monkeypatch):
    sc=SimpleNamespace(flows=[SimpleNamespace(flow_id=0),SimpleNamespace(flow_id=1)],
        plan=lambda *a:True,path_at=lambda *a:[10,1,2,11],topo=SimpleNamespace(n_sats=10),
        resolve_on_path=lambda p,t,node:1 if node else (1,2))
    monkeypatch.setattr(pc,'build_scenario',lambda c:sc)
    for exp in ('E04','E05'):
        planned=[j for j in pc.jobs(exp) if j['const']=='C5' and j['seed']==1000]
        design=pc.preflight(planned,tmp_path)
        assert list(design)==['C5:1000']
        assert json.loads((tmp_path/'preflight.json').read_text())['checks']==(60 if exp=='E04' else 24)
        if exp=='E04':assert design['C5:1000']=={'link':[1,2],'node':1}
        else:assert design['C5:1000']['trigger'] in (1,2)
    sc.plan=lambda *a:None
    with pytest.raises(ValueError):pc.preflight(planned,tmp_path)


def test_child_metrics_and_failed_timeout_inventory(tmp_path,monkeypatch):
    from chronoroute.fwd.config import normalise
    from chronoroute.baselines.params import normalise_scheme
    from chronoroute import provenance
    cfg=normalise({'seed':1000,'scenario':{'kind':'walker','preset':'C1','duration_s':1,'drain_s':1,
        'gsl':{'min_elevation_deg':10}},'traffic':{'flows':[{'src':'London','dst':'New York'}]},'output':{'invariants':'all','trace':'none'}})
    j=pc.jobs('E05')[0];d=pc.document(j,{'C5:1000':{'trigger':1}});d.update(engine=cfg,scheme=normalise_scheme('chronoroute'),job=j)
    path=tmp_path/'config.json';path.write_text(json.dumps(d));out=tmp_path/'child'
    assert pc.run_child(path,out)==0
    m=json.loads((out/'metrics.json').read_text());assert m['sent']==100 and m['triggered']==0
    provenance.validate_manifest(out/'raw/manifest.json')
    wrapper=tmp_path/'wrapper';(wrapper/'configs').mkdir(parents=True);(wrapper/'configs'/(j['id']+'.json')).write_text(json.dumps(d))
    obs=pc.run_job(j,wrapper,tmp_path/'cache',{},0)
    assert obs['status']=='not_started' and obs['returncode'] is None
    provenance.validate_manifest(tmp_path/'cache/runs'/j['id']/'manifest.json')
    with pytest.raises(SystemExit):pc.main(['--help'])


def test_budget_uses_manifested_spent_time_and_rejects_incomplete(monkeypatch,tmp_path):
    forecast={'remaining_work_s':{'E04':100,'E05':20,'E16':10}}
    monkeypatch.setattr(pc.e1_confirm,'validate_inputs',lambda *a:({},forecast))
    good={'dirty':False,'extra':{'complete':True}}
    monkeypatch.setattr(pc.provenance,'validate_manifest',lambda *a:good)
    (tmp_path/'runtime.json').write_text(json.dumps({'wall_s':300,'previous_spent_s':200}))
    b=pc.validate_gates(tmp_path,tmp_path,tmp_path,'E04')
    assert b['previous_spent_s']==500 and b['available_s']==21600-500-1810-20
    assert pc.validate_gates(tmp_path,tmp_path,tmp_path,'E05',tmp_path)['previous_spent_s']==800
    good['extra']['complete']=False
    with pytest.raises(ValueError):pc.validate_gates(tmp_path,tmp_path,tmp_path,'E04')


def test_e5_comparison_families_are_separate_and_missing_stays_visible():
    rows=[]
    for const in ('C5','C2'):
        for scheme in pc.POLICIES:
            for seed in range(1000,1036):rows.append(dict(const=const,condition='trigger',scheme=scheme,seed=seed,
                stuck_rate=.1 if scheme=='greedy_pure' else 0.,triggered_pdr=1.,triggered_stretch_mean=1.,
                triggered_extra_hops_mean=0.,triggered_effective_mean_s=.01))
    result=pa.comparisons(rows,'E05',n_boot=100)
    assert len(result)==20 and all(r['family_n']==2 and r['complete'] for r in result)
    assert next(r for r in result if r['family']=='visited_vs_pure' and r['endpoint']=='stuck_rate')['mean_diff']==pytest.approx(-.1)


def test_driver_failed_jobs_are_manifested_and_command_reproduces_wrapper(tmp_path,monkeypatch):
    from chronoroute import provenance
    job=pc.jobs('E04')[0]
    monkeypatch.setattr(pc,'jobs',lambda exp:[job])
    monkeypatch.setattr(pc.e1,'validate_protocol',lambda:None)
    monkeypatch.setattr(pc.provenance,'git_state',lambda *a,**k:{'dirty':False,'sha':'0'*40})
    monkeypatch.setattr(pc,'validate_gates',lambda *a:dict(available_s=1000,confirmation_allowed=True))
    monkeypatch.setattr(pc,'preflight',lambda *a:{'C5:1000':{'link':[1,2],'node':1}})
    monkeypatch.setattr(pc.e1,'measured_command',lambda *a,**k:dict(status='timeout',wall_s=120,cpu_s=120,
        peak_rss_kb=1,returncode=-9,command=a[0]))
    monkeypatch.setattr(pc.analysis,'plots',lambda *a:None)
    for name in ('e1','gates','e0'):
        p=tmp_path/name;p.mkdir();(p/'runtime.json').write_text('{}');(p/'resource_forecast.json').write_text('{}')
        provenance.write_manifest(p,tool='unit fixture',tool_version='1',command=['unit-fixture'],config={},seeds=[],outputs=[],labels={})
    out=tmp_path/'out'
    assert pc.main(['--out',str(out),'--e1',str(tmp_path/'e1'),'--gates',str(tmp_path/'gates'),'--e0',str(tmp_path/'e0')],experiment='E04')==1
    manifest=provenance.validate_manifest(out/'manifest.json')
    assert manifest['dirty'] is False and not manifest['extra']['complete']
    assert '--experiment E04' in manifest['command']
    assert 'timeout' in (out/'inventory.csv').read_text()


def test_all_e4_schemes_keep_fault_losses_and_valid_stretch(tmp_path):
    from chronoroute.fwd.config import normalise
    from chronoroute.fwd.scenario import build_scenario
    from chronoroute.eval.load import load_run
    c=normalise({'seed':1000,'scenario':{'kind':'walker','preset':'C1','duration_s':9,'drain_s':2,
        'gsl':{'min_elevation_deg':10}},'traffic':{'flows':[{'src':'London','dst':'New York'}]},'output':{'trace':'none','invariants':'all'}})
    sc=build_scenario(c);target=sc.resolve_on_path({'flow':0,'at_s':3,'position':'middle','kind':'isl'},3000000000,False)
    design={'C5:1000':{'link':list(target),'node':target[0]}}
    for name in pc.SCHEMES:
        job=next(j for j in pc.jobs('E04') if j['const']=='C5' and j['seed']==1000 and j['scheme']==name and j['condition']=='link-B')
        d=pc.document(job,design);cfg=d['engine'];cfg['scenario']=c['scenario'];cfg['traffic']=c['traffic']
        cfg['faults']=[dict(kind='link_down',link=list(target),start_s=3,stop_s=8)]
        d['engine']=normalise(cfg);d['job']=job
        path=tmp_path/(name+'.json');path.write_text(json.dumps(d));out=tmp_path/name
        assert pc.run_child(path,out)==0
        run=load_run(out/'raw');row=pc.extract(run,job)
        assert row['outages']==1 and row['stretch_violations']==0
        assert row['stretch_min_exact'] is None or row['stretch_min_exact']>=1
        assert row['stretch_min_adjusted'] is None or row['stretch_min_adjusted']>=1
        if name in ('continue','crh16'):
            assert row['delivered']<row['sent'] and row['blackhole_losses']>0

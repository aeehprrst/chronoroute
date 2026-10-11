"""Run-level inference for E4/E5, preserving undefined and infinite outcomes."""
from collections import defaultdict
import json
import math
from pathlib import Path

import numpy as np
from chronoroute.eval import stats
from chronoroute.trace.writer import write_json
import campaign as e1
import analysis as e1_analysis

ENDPOINTS=('pdr','blackhole_s','effective_p99_s','stretch_mean','extra_hops_mean','stuck_rate','strict_drop_rate',
           'triggered_pdr','triggered_stretch_mean','triggered_extra_hops_mean','triggered_effective_mean_s',
           'triggered_effective_p99_s','header_bytes','header_link_bytes',
           *(f'control_{m}' for m in ('uplink','isl','downlink','ground')),
           *(f'control_rate_{m}' for m in ('uplink','isl','downlink','ground')))


def decode(value):
    """Restore explicitly encoded infinite outcomes, leaving missing values undefined."""
    if isinstance(value,str) and value=='inf':return math.inf
    if isinstance(value,str) and value=='-inf':return -math.inf
    if isinstance(value,dict):return {k:decode(v) for k,v in value.items()}
    if isinstance(value,list):return [decode(v) for v in value]
    return value


def aggregate(rows,name,*,n_boot=10000):
    """Equal-run primary means and bootstrap outage/ratio endpoints with visible denominators."""
    seeds=[int(r['seed']) for r in rows]
    if len(seeds)!=len(set(seeds)):raise ValueError('duplicate seed in cell')
    out=dict(n=len(rows),complete=len(rows)==36 and set(seeds)==set(range(1000,1036)),
             no_outage_runs=sum(r.get('outages',0)==0 for r in rows),
             outages=sum(r.get('outages',0) for r in rows),
             infinite_tail_runs=sum(r.get('effective_p99_s')==math.inf for r in rows),
             tail_ineligible_runs=sum(r.get('effective_p99_s') is None for r in rows),
             undefined_trigger_runs=sum(r.get('triggered',0)==0 for r in rows),
             stretch_violations=sum(r.get('stretch_violations',0) for r in rows),
             triggered=sum(r.get('triggered',0) for r in rows),
             triggered_delivered=sum(r.get('triggered_delivered',0) for r in rows),
             stuck=sum(r.get('stuck',0) for r in rows),strict_drop=sum(r.get('strict_drop',0) for r in rows),
             never_triggered_forward=sum(r.get('never_triggered_forward',0) for r in rows),
             stretch_outside_graph=sum(r.get('stretch_outside_graph',0) for r in rows),
             stretch_exact_n=sum(r.get('stretch_exact_n',0) for r in rows),
             stretch_in_graph_n=sum(r.get('stretch_in_graph_n',0) for r in rows),
             sent=sum(r.get('sent',0) for r in rows),delivered=sum(r.get('delivered',0) for r in rows),
             blackhole_losses=sum(r.get('blackhole_losses',0) for r in rows),
             ttm_undefined=sum(r.get('ttm_undefined',0) for r in rows),ttm_censored=sum(r.get('ttm_censored',0) for r in rows),
             visited_entries_max=max((r.get('visited_entries_max',0) for r in rows),default=0),
             visited_python_bytes_max=max((r.get('visited_python_bytes_max',0) for r in rows),default=0))
    for field in ENDPOINTS:
        values=[r[field] for r in rows if r.get(field) is not None];ci=stats.mean_ci_t(values)
        prefix=field.removesuffix('_s')
        for k,v in (('mean',ci['mean']),('lo',ci['lo']),('hi',ci['hi']),('n',ci['n'])):out[prefix+'_'+k]=v
        if field!='blackhole_s' and len(values)!=len(rows):
            for k in ('mean','lo','hi'):out[prefix+'_'+k]=None
        if field=='blackhole_s':
            boot=stats.bootstrap_ci(values,method='percentile',n_boot=n_boot,seed=e1_analysis.endpoint_seed(name+field)) if values else dict(lo=None,hi=None)
            out.update(blackhole_boot_lo=boot['lo'],blackhole_boot_hi=boot['hi'])
        if field in ('pdr','stuck_rate','triggered_pdr','triggered_stretch_mean','triggered_extra_hops_mean'):
            block=e1_analysis.block_ci(rows,field,name+field,n_boot=n_boot) if all(field in r for r in rows) else dict(estimate=None,lo=None,hi=None)
            for k in ('estimate','lo','hi'):out[field+'_block_'+k]=block[k]
    for field in ('stretch_min_exact','stretch_min_adjusted','stretch_min_raw'):
        values=[r[field] for r in rows if r.get(field) is not None];out[field]=min(values) if values else None
    for label,num,den in [('pdr_pooled','delivered','sent'),('stuck_pooled','stuck','triggered'),('triggered_pdr_pooled','triggered_delivered','triggered')]:
        if all(num in r and den in r for r in rows):
            ci=e1_analysis.ratio_ci([r[num] for r in rows],[r[den] for r in rows],name+label,n_boot=n_boot) if sum(r[den] for r in rows) else dict(estimate=None,lo=None,hi=None,n_boot_undefined=n_boot)
            for key in ('estimate','lo','hi','n_boot_undefined'):out[label+'_'+key]=ci[key]
    return out


def contrast(a,b,endpoint,name,*,n_boot=10000):
    """Paired inference, with infinity categories instead of undefined subtraction."""
    aa={r['seed']:r for r in a};bb={r['seed']:r for r in b}
    if len(aa)!=len(a) or len(bb)!=len(b) or set(aa)!=set(bb):raise ValueError('contrast seed coverage differs')
    pairs=[(aa[s].get(endpoint),bb[s].get(endpoint)) for s in sorted(aa)]
    if endpoint=='blackhole_s' and any((x is None)!=(y is None) for x,y in pairs):raise ValueError('outage histories differ')
    defined=[(x,y) for x,y in pairs if x is not None and y is not None]
    out=dict(n=len(defined),missing_pairs=len(pairs)-len(defined),mean_diff=None,lo=None,hi=None,p=None,
             bootstrap_lo=None,bootstrap_hi=None,reason=None,both_infinite=0,a_only_infinite=0,b_only_infinite=0,
             ratio=None,ratio_lo=None,ratio_hi=None)
    if not defined:out['reason']='no paired defined endpoints';return out
    if endpoint!='blackhole_s' and len(defined)!=len(pairs):
        out['reason']='undefined run endpoints preclude a complete paired contrast';return out
    x=np.array([p[0] for p in defined]);y=np.array([p[1] for p in defined])
    ia=np.isinf(x);ib=np.isinf(y)
    out.update(both_infinite=int((ia&ib).sum()),a_only_infinite=int((ia&~ib).sum()),b_only_infinite=int((~ia&ib).sum()))
    if ia.any() or ib.any():
        out['reason']='latency contrast undefined with infinite tails; retain paired PDR and tail indicators'
        indicator=stats.paired(ia.astype(int),ib.astype(int))
        out.update(tail_failure_mean_diff=indicator['mean_diff'],tail_failure_lo=indicator['lo'],tail_failure_hi=indicator['hi'])
        return out
    ci=stats.paired(x,y);out.update({k:ci[k] for k in ('mean_diff','lo','hi','p')})
    boot=stats.bootstrap_ci(x-y,method='percentile',n_boot=n_boot,seed=e1_analysis.endpoint_seed(name))
    out.update(bootstrap_lo=boot['lo'],bootstrap_hi=boot['hi'])
    if endpoint=='effective_p99_s':
        ratio=stats.paired(np.log(x),np.log(y));out.update(ratio=math.exp(ratio['mean_diff']),
            ratio_lo=math.exp(ratio['lo']) if ratio['lo'] is not None else None,
            ratio_hi=math.exp(ratio['hi']) if ratio['hi'] is not None else None,p=ratio['p'])
    return out


def comparisons(records,experiment,*,n_boot=10000):
    """Fixed Holm families include every registered contrast, including undefined cells."""
    groups=defaultdict(list)
    for r in records:groups[r['const'],r['condition'],r['scheme']].append(r)
    rows=[]
    for const in ('C5','C2'):
        conditions=('link-A','link-B','node-A','node-B') if experiment=='E04' else ('trigger',)
        for condition in conditions:
            comparisons=[('greedy_visited',s,'visited') for s in ('continue','o_t','snap','ls_h','crh16')] if experiment=='E04' else [('greedy_visited','greedy_pure','visited_vs_pure'),('grid_detour','greedy_visited','grid_vs_visited')]
            endpoints=('pdr','blackhole_s','effective_p99_s') if experiment=='E04' else ('stuck_rate','triggered_pdr','triggered_stretch_mean','triggered_extra_hops_mean','triggered_effective_mean_s')
            for primary,other,family in comparisons:
                for endpoint in endpoints:
                    a=groups[const,condition,primary];b=groups[const,condition,other]
                    row=dict(const=const,condition=condition,primary=primary,comparator=other,endpoint=endpoint,family=family,
                             **contrast(a,b,endpoint,f'{const}-{condition}-{primary}-{other}-{endpoint}',n_boot=n_boot))
                    row['complete']=len(a)==len(b)==36
                    rows.append(row)
    families=defaultdict(list)
    for r in rows:families[r['family'],r['endpoint']].append(r)
    for members in families.values():
        adjusted=stats.holm([r['p'] if r['p'] is not None and r['complete'] else 1 for r in members])['adjusted']
        for r,p in zip(members,adjusted):
            r['family_n']=len(members);r['adjusted_p']=p if r['p'] is not None and r['complete'] else None
            diff=r['mean_diff'];r['point_disadvantage']=diff is not None and (diff<0 if r['endpoint'] in ('pdr','triggered_pdr') else diff>0)
            material=(diff is not None and diff<=-.01) if r['endpoint']=='pdr' else ((diff is not None and diff>=.1) if r['endpoint']=='blackhole_s' else ((r['ratio'] is not None and r['ratio']>=1.05) if r['endpoint']=='effective_p99_s' else r['point_disadvantage']))
            r['material_loss']=bool(material and r['adjusted_p'] is not None and r['adjusted_p']<=.05)
    return rows


def plots(out,summary,experiment):
    """Standalone CI figures; infinite tails remain explicit in tables and plotted indicators."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fields=[('pdr','All-flow PDR'),('blackhole','Mean blackhole, seconds'),('infinite_tail','Fraction of runs with infinite effective P99')] if experiment=='E04' else [('triggered_pdr','Triggered-packet PDR'),('stuck_rate','Triggered stuck/loop rate'),('triggered_stretch_mean','Delivered triggered stretch'),('triggered_extra_hops_mean','Delivered triggered extra hops')]
    (out/'figures').mkdir(exist_ok=True)
    for field,ylabel in fields:
        fig,axes=plt.subplots(2,1,figsize=(11,8),layout='constrained')
        for ax,const in zip(axes,('C5','C2')):
            selected=[r for r in summary if r['const']==const and r['condition']!='none']
            labels_=[]
            for i,r in enumerate(selected):
                labels_.append(r['condition']+'/'+r['scheme'])
                value=r['infinite_tail_runs']/r['n'] if field=='infinite_tail' else r.get(field+'_mean')
                if value is None or not math.isfinite(value):continue
                lo=r.get(field+'_lo');hi=r.get(field+'_hi')
                if field=='blackhole':lo=r.get('blackhole_boot_lo');hi=r.get('blackhole_boot_hi')
                ax.errorbar(i,value,yerr=None if lo is None or hi is None else [[max(0,value-lo)],[max(0,hi-value)]],fmt='o',capsize=3)
            ax.set(xticks=range(len(labels_)),xticklabels=labels_,ylabel=ylabel,title=const+' — MODELLED network; DERIVED statistics')
            ax.tick_params(axis='x',labelrotation=65,labelsize=7)
        fig.savefig(out/'figures'/(field+'.png'),dpi=150);plt.close(fig)


def write_analysis(out,records,experiment,*,n_boot=10000):
    """Write all cells, denominators, losses, contrasts and reports from complete run rows."""
    from policy_campaign import jobs,clean
    groups=defaultdict(list)
    for r in records:groups[r['const'],r['condition'],r['scheme']].append(r)
    summary=[]
    keys=sorted({(j['const'],j['condition'],j['scheme']) for j in jobs(experiment)})
    for key in keys:
        rows=groups[key];s=dict(zip(('const','condition','scheme'),key));s.update(aggregate(rows,'-'.join(key),n_boot=n_boot));summary.append(s)
    e1.write_csv(out/'per_run.csv',records);e1.write_csv(out/'summary.csv',summary)
    contrasts=comparisons(records,experiment,n_boot=n_boot);e1.write_csv(out/'paired_contrasts.csv',contrasts)
    city=[]
    for key in keys:
        for pi in range(18):
            rows=[r for r in groups[key] if r['pair_id']==pi]
            city.append(dict(zip(('const','condition','scheme'),key),pair_id=pi,n=len(rows),
                pdr_mean=float(np.mean([r['pdr'] for r in rows])) if rows else None,label='DERIVED descriptive only'))
    e1.write_csv(out/'city_descriptive.csv',city)
    complete=all(r['complete'] for r in summary) and not any(r['stretch_violations'] for r in summary)
    verdict=dict(complete=complete,experiment=experiment,material_losses=[r for r in contrasts if r['material_loss']],
        point_disadvantages=[r for r in contrasts if r['point_disadvantage']],stretch_violations=sum(r['stretch_violations'] for r in summary),
        infinite_tail_runs=sum(r['infinite_tail_runs'] for r in summary),model_label='MODELLED network outcomes; DERIVED statistics',
        unsupported_e5_advantage=[dict(const=r['const'],comparison=r['family'],endpoint=r['endpoint'],reason='point estimate does not show reduced stuck rate') for r in contrasts if experiment=='E05' and r['endpoint']=='stuck_rate' and (r['mean_diff'] is None or r['mean_diff']>=0)])
    write_json(out/'verdict.json',clean(verdict));plots(out,summary,experiment)
    report=[experiment+' preregistered policy experiment','',
        'Network outcomes are MODELLED and statistics DERIVED. C5 uses REAL public orbital inputs; C2 elements and positions are MODELLED. Starlink operational routing is UNKNOWN; Starlink does not use T-CRH.','',
        'All registered cells, missing endpoints, no-outage runs, infinite tails and confidence intervals appear in summary.csv. Per-run source denominators and loss reasons appear in per_run.csv. Outage intervals and TTM censoring are retained there. City averages are descriptive.','',
        'Exact-domain and tolerance-adjusted stretch must be at least one. Raw step-crossing ratios and paths outside the send-time graph are separate diagnostics; no values are clamped. Losses are infinite latency. Triggered P99 is undefined when fewer than the registered observations are available.','',
        'Material losses under the fixed Holm families:']
    report.extend(f"* {r['const']} {r['condition']} {r['primary']} versus {r['comparator']}, {r['endpoint']}: difference {r['mean_diff']}, adjusted p {r['adjusted_p']}." for r in verdict['material_losses'])
    if not verdict['material_losses']:report.append('No material loss satisfies both effect and adjusted significance criteria; every point disadvantage remains in paired_contrasts.csv.')
    report+=['','Undefined tail contrasts retain finite/infinite paired categories and descriptive tail-failure indicators. O-T is privileged. Blackhole comparisons condition on common realised-outage seeds, never on individual outages. The visited set is MODELLED packet state; Python object bytes are host representation cost, not wire support. Raw traces remain locally in the ignored cache; the compressed producer ledger records commands and hashes for reproduction.']
    (out/'REPORT.md').write_text('\n'.join(report)+'\n')
    return complete

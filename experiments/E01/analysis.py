"""E1 run-cluster estimates and the prespecified paired comparisons."""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from chronoroute.eval import detection, stats
from chronoroute.trace.writer import write_json
import campaign as e1

COMPARATORS = ('ls_h','ls_d','e2e','lq','crh16')


def endpoint_seed(name):
    """Stable endpoint streams derived from the registered analysis seed."""
    return 91000 + int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], 'big')


def ratio_ci(num, den, name, *, n_boot=10000):
    """Pool counts, resampling complete runs including zero denominators."""
    return stats.bootstrap_ci(np.column_stack((num,den)),statistic='ratio',method='percentile',
                              n_boot=n_boot,seed=endpoint_seed(name))


def block_ci(rows, field, name, *, n_boot=10000):
    """Resample two independent runs within each of the fixed city blocks."""
    blocks=[[r[field] for r in rows if int(r['pair_id'])==p] for p in range(18)]
    if any(len(b)!=2 or any(v is None for v in b) for b in blocks):
        return dict(estimate=None,lo=None,hi=None,reason='requires two defined runs in every city block')
    arr=np.asarray(blocks,float)
    rng=np.random.Generator(np.random.Philox(endpoint_seed(name)))
    idx=rng.integers(0,2,size=(n_boot,18,2))
    samples=arr[np.arange(18)[None,:,None],idx].mean(axis=(1,2))
    return dict(estimate=float(arr.mean()),lo=float(np.quantile(samples,.025)),hi=float(np.quantile(samples,.975)),reason=None)


def extract(doc, job, operating):
    """Flatten scored files, preserving native LS endpoints and undefined oracle detection."""
    rows=[]
    for ri,d in enumerate(doc['detection']):
        if job['scheme']=='chronoroute' and ri==0:
            continue
        if len(d['faults'])!=1:
            raise ValueError('one registered fault required per E1 score')
        f=d['faults'][0]
        p=f['packet']
        native_ls=job['scheme'] in ('ls_h','ls_d')
        ev=f['control_plane'] if native_ls else f['event']
        if e1.CONDITIONS[job['condition']]['null'] and (p['true_detections'] or f['event']['detected'] or f['control_plane']['detected']):
            raise ValueError('null fault has nonzero attributed detection')
        entries=[(2,ev,d['false_events_twin'])]
        for sensitivity in d.get('sensitivities',[]):
            se=sensitivity['faults'][0]
            sev=se['control_plane'] if native_ls else se['event']
            if e1.CONDITIONS[job['condition']]['null'] and (se['event']['detected'] or se['control_plane']['detected']):
                raise ValueError('null fault has nonzero sensitivity event detection')
            entries.append((sensitivity['k'],sev,sensitivity['false_events_twin']))
        for k,event,fe in entries:
            oracle=job['scheme']=='o_q'
            detected=None if oracle else int(event['detected'])
            delay=None if oracle or not event['detected'] else event['delay_ns']/1e9
            fp=d.get('fpr') if not oracle else None
            ft=d.get('fpr_twin') if not oracle else None
            control=doc['control']
            latency=doc['latency']
            r={key:job[key] for key in ('const','scheme','condition','seed','pair_id')}
            r.update(rule=d['rule'],selected=job['scheme']!='chronoroute' or ri-1==operating[job['const']]['rule_index'],
                     k=k,detected=detected,delay_s=delay,restricted_s=None if oracle else (delay if detected else 4.),
                     tp=None if native_ls or oracle else p['true_detections'],crossed=p['exposed'],reached=p['reached'],
                     lost_at_fault=p['lost_at_fault'],localised_tp=None if job['scheme'] in ('e2e','ls_h','ls_d','o_q') else p.get('localised_true_detections',0),
                     induced_unexposed=p.get('induced_unexposed',0),lost_flags=p.get('lost_flags',0),
                     fp=None if fp is None else fp['false_positives'],clean=None if fp is None else fp['clean'],
                     twin_fp=None if ft is None else ft['false_positives'],twin_clean=None if ft is None else ft['clean'],
                     false_events=None if oracle else fe['events'],sending_hours=fe['hours'],
                     sent=doc['pdr']['sent'],delivered=doc['pdr']['delivered'],pdr=doc['pdr']['pdr'],
                     header_bytes=control.get('header_bytes_per_packet_mean'),header_link_bytes=control.get('header_bytes_on_links'),
                     effective_p99_inf_flows=sum(l.get('q0.99_eff') in ('inf',float('inf')) for l in latency),
                     delivered_p99_ineligible_flows=sum(l.get('q0.99') is None for l in latency),
                     losses_json=json.dumps(doc['pdr']['losses'],sort_keys=True),
                     latency_json=json.dumps(latency,sort_keys=True),state_json=json.dumps(control.get('state',{}),sort_keys=True),
                     steady_state_json=json.dumps(control.get('crh_state_upload_bytes_per_s_steady',{}),sort_keys=True),
                     reverse_json=json.dumps(d.get('secondary',[]),sort_keys=True),
                     changed_but_unreached=p.get('changed_but_unreached',0))
            for medium in ('uplink','isl','downlink','ground'):
                r['control_'+medium]=control.get('control_bytes',{}).get(medium,0)
                r['control_rate_'+medium]=control.get('control_bytes_per_s',{}).get(medium,0)
            rows.append(r)
    if doc.get('plan_checks',{}).get('violations',0):
        raise ValueError('offline plan gate failed')
    return rows


def summarise(rows, *, n_boot=10000):
    """Run means, censored delay, pooled ratios, counts and block sensitivity."""
    first=rows[0]
    name=':'.join(str(first[k]) for k in ('const','scheme','condition','rule','k'))
    out={k:first[k] for k in ('const','scheme','condition','rule','selected','k')}
    out.update(n=len(rows),complete=len(rows)==36 and {int(r['seed']) for r in rows}==set(range(1000,1036)))
    for field,label in (('detected','event'),('restricted_s','restricted'),('pdr','pdr'),('header_bytes','header'),
                        ('header_link_bytes','header_link'), *((f'control_{m}',f'control_{m}') for m in ('uplink','isl','downlink','ground')),
                        *((f'control_rate_{m}',f'control_rate_{m}') for m in ('uplink','isl','downlink','ground'))):
        values=[r[field] for r in rows if r.get(field) is not None]
        ci=stats.mean_ci_t(values)
        out[label+'_mean'+('_s' if label=='restricted' else '')]=ci['mean']
        out[label+'_lo']=ci['lo']; out[label+'_hi']=ci['hi']
    obs=[r for r in rows if r['detected'] is not None]
    out['km_median_s']=detection.km_median([r['restricted_s'] for r in obs],[bool(r['detected']) for r in obs]) if obs else None
    out['censored_runs']=sum(r['detected']==0 for r in obs)
    for prefix,field in (('event_block','detected'),('restricted_block','restricted_s'),('pdr_block','pdr')):
        ci=block_ci(rows,field,name+prefix,n_boot=n_boot)
        for k in ('estimate','lo','hi'): out[prefix+'_'+k]=ci[k]
    out['undefined_packet_runs']=sum(r['crossed']==0 for r in rows)
    for field in ('crossed','reached','lost_at_fault','localised_tp','induced_unexposed','lost_flags','sent','delivered','effective_p99_inf_flows','delivered_p99_ineligible_flows'):
        out[field]=sum(r[field] for r in rows) if all(r[field] is not None for r in rows) else None
    out['tp']=None if first['tp'] is None else sum(r['tp'] for r in rows)
    for label,num,den in (('packet_pdet','tp','crossed'),('fpr','fp','clean'),('false_events_h','false_events','sending_hours'),('pdr_pooled','delivered','sent')):
        if first.get(num) is None:
            ci=dict(estimate=None,lo=None,hi=None,n_boot_undefined=None)
        else:
            ci=ratio_ci([r[num] for r in rows],[r[den] for r in rows],name+label,n_boot=n_boot)
        for k in ('estimate','lo','hi','n_boot_undefined'):out[label if k=='estimate' else label+'_'+k]=ci[k]
    if obs:
        ci=stats.bootstrap_ci([r['restricted_s'] for r in rows],method='percentile',n_boot=n_boot,seed=endpoint_seed(name+'restricted'))
        out.update(restricted_boot_lo=ci['lo'],restricted_boot_hi=ci['hi'])
    else:out.update(restricted_boot_lo=None,restricted_boot_hi=None)
    out['clean']=None if first['clean'] is None else sum(r['clean'] for r in rows)
    out['fp']=None if first['fp'] is None else sum(r['fp'] for r in rows)
    return out


def contrasts(rows, *, n_boot=10000):
    """The two fixed 150-comparison families; retain incomplete comparisons."""
    selected=[r for r in rows if r['selected'] and r['k']==2]
    indexed={(r['const'],r['condition'],r['scheme'],r['seed']):r for r in selected}
    out=[]
    for field in ('detected','restricted_s'):
        family=[]
        for const in ('C5','C2'):
            for cond,spec in e1.CONDITIONS.items():
                if spec['null']:continue
                for comparator in COMPARATORS:
                    aa=[indexed.get((const,cond,'chronoroute',seed)) for seed in range(1000,1036)]
                    bb=[indexed.get((const,cond,comparator,seed)) for seed in range(1000,1036)]
                    r=dict(const=const,condition=cond,comparator=comparator,endpoint=field,n=0,status='incomplete',
                           mean_diff=None,lo=None,hi=None,p=None,bootstrap_lo=None,bootstrap_hi=None,
                           adjusted_p=None,holm_family_n=150,material_loss=False,point_disadvantage=None)
                    if all(x is not None for x in aa+bb):
                        a=np.array([x[field] for x in aa]);b=np.array([x[field] for x in bb])
                        result=stats.paired(a,b)
                        r.update({k:result[k] for k in ('n','mean_diff','lo','hi','p')},status='complete')
                        boot=stats.bootstrap_ci(a-b,method='percentile',n_boot=n_boot,seed=endpoint_seed(str((const,cond,comparator,field))))
                        r.update(bootstrap_lo=boot['lo'],bootstrap_hi=boot['hi'],point_disadvantage=bool(result['mean_diff']<0 if field=='detected' else result['mean_diff']>0))
                    family.append(r)
        adjusted=stats.holm([r['p'] if r['p'] is not None else 1. for r in family])
        for r,p in zip(family,adjusted['adjusted']):
            r['adjusted_p']=p if r['p'] is not None else None
            r['material_loss']=r['status']=='complete' and p<=.05 and (r['mean_diff']<=-.05 if field=='detected' else r['mean_diff']>=.1)
        out.extend(family)
    return out


def comparison_report(paired):
    """REPORT.md lines on the paired contrasts: material losses, wins/ties/losses of the point
    estimate per comparator and endpoint, and (always) where every point disadvantage is listed."""
    lines=['Material losses under the fixed Holm families:','']
    lines+=[f"* {r['const']} {r['condition']}, versus {r['comparator']}, {r['endpoint']}: ChronoRoute minus comparator {r['mean_diff']:.6f}; adjusted p={r['adjusted_p']:.6g}." for r in paired if r['material_loss']] or ['No material loss met both the registered effect-size and adjusted-significance requirements.']
    lines+=['','Point estimates per comparator over the complete paired contrasts (a win, tie or loss is the sign of ChronoRoute minus comparator, significant or not: more detection, or a shorter restricted delay, is a win):','']
    for comparator in COMPARATORS:
        parts=[]
        for field,label in (('detected','detection'),('restricted_s','restricted delay')):
            cell=[r for r in paired if r['comparator']==comparator and r['endpoint']==field]
            done=[r for r in cell if r['status']=='complete']
            losses=sum(bool(r['point_disadvantage']) for r in done)
            ties=sum(r['mean_diff']==0 for r in done)
            parts.append(f"{label} {len(done)-losses-ties} wins, {ties} ties, {losses} losses"+(f" ({len(cell)-len(done)} incomplete)" if len(cell)>len(done) else ''))
        lines.append(f"* versus {comparator}: "+'; '.join(parts)+'.')
    n_point=sum(bool(r['point_disadvantage']) for r in paired)
    lines+=['',f"All {n_point} point disadvantages (ChronoRoute's point estimate worse, significant or not) are listed in `paired_contrasts.csv` (`point_disadvantage`) and `verdict.json` (`point_disadvantages`)."]
    return lines


def write_analysis(out, rows, *, n_boot=10000):
    """Generate all tables/figures from run rows; no completed verdict for partial cells."""
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    groups=defaultdict(list)
    for r in rows:groups[tuple(r[k] for k in ('const','scheme','condition','rule','k'))].append(r)
    summary=[summarise(rs,n_boot=n_boot) for rs in groups.values()]
    e1.write_csv(out/'summary.csv',summary)
    ratio_rows=[];distributions=[]
    for key,rs in groups.items():
        if rs[0]['k']!=2:continue
        values=[]
        for r in rs:
            ratio=r['tp']/r['crossed'] if r['tp'] is not None and r['crossed'] else None
            loc=r['localised_tp']/r['tp'] if r['localised_tp'] is not None and r['tp'] else None
            ratio_rows.append({**{k:r[k] for k in ('const','scheme','condition','seed','pair_id','rule','selected')},
                               'tp':r['tp'],'crossed':r['crossed'],'packet_ratio':ratio,'localisation_ratio':loc})
            if ratio is not None:values.append(ratio)
        distributions.append(dict(zip(('const','scheme','condition','rule','k'),key),defined_runs=len(values),undefined_runs=len(rs)-len(values),
                            min=min(values) if values else None,q25=float(np.quantile(values,.25)) if values else None,
                            median=float(np.median(values)) if values else None,q75=float(np.quantile(values,.75)) if values else None,
                            max=max(values) if values else None))
    e1.write_csv(out/'packet_run_ratios.csv',ratio_rows)
    e1.write_csv(out/'packet_ratio_distribution.csv',distributions)
    paired=contrasts(rows,n_boot=n_boot)
    e1.write_csv(out/'paired_contrasts.csv',paired)
    city=defaultdict(list)
    for r in rows:
        if r['selected'] and r['k']==2:city[tuple(r[k] for k in ('const','scheme','condition','pair_id'))].append(r)
    city_rows=[]
    for key,rs in city.items():
        city_rows.append(dict(zip(('const','scheme','condition','pair_id'),key),n=len(rs),
                        event_descriptive=None if rs[0]['detected'] is None else float(np.mean([r['detected'] for r in rs])),
                        pdr_descriptive=float(np.mean([r['pdr'] for r in rs]))))
    e1.write_csv(out/'city_descriptive.csv',city_rows)
    # Pooled population FPR: fifteen non-null fault runs plus each matching twin once, clustered by seed.
    fpr=[]
    for const in ('C5','C2'):
        for scheme in e1.SCHEMES:
            rs=[r for r in rows if r['const']==const and r['scheme']==scheme and r['selected'] and r['k']==2 and not e1.CONDITIONS[r['condition']]['null']]
            if not rs or rs[0]['fp'] is None:continue
            counts=[]
            for seed in range(1000,1036):
                sample=[r for r in rs if r['seed']==seed]
                if len(sample)!=15:continue
                counts.append([sum(r['fp'] for r in sample)+sample[0]['twin_fp'],sum(r['clean'] for r in sample)+sample[0]['twin_clean']])
            ci=ratio_ci([x[0] for x in counts],[x[1] for x in counts],const+scheme+'population',n_boot=n_boot) if counts else dict(estimate=None,lo=None,hi=None)
            estimate=ci['estimate']
            fpr.append(dict(const=const,scheme=scheme,n=len(counts),fp=sum(x[0] for x in counts),clean=sum(x[1] for x in counts),
                            fpr=estimate,lo=ci['lo'],hi=ci['hi'],meets_1pct=None if estimate is None else estimate<=.01,
                            interval_position=None if estimate is None else ('below' if ci['hi']<=.01 else 'above' if ci['lo']>.01 else 'straddles')))
    e1.write_csv(out/'population_fpr.csv',fpr)
    curve_groups=defaultdict(list)
    for r in rows:
        if r['k']==2 and not e1.CONDITIONS[r['condition']]['null']:
            curve_groups[(r['const'],r['scheme'],r['rule'])].append(r)
    curves=[]
    for (const,scheme,rule),rs in curve_groups.items():
        clusters=[[r for r in rs if r['seed']==seed] for seed in range(1000,1036)]
        if any(len(cluster)!=15 for cluster in clusters):continue
        curve=dict(const=const,scheme=scheme,rule=rule,selected=rs[0]['selected'],n=36,
                   packet_pdet=None,packet_pdet_lo=None,packet_pdet_hi=None,fpr=None,fpr_lo=None,fpr_hi=None,
                   event_mean=None,event_lo=None,event_hi=None,false_events_h=None,false_events_h_lo=None,false_events_h_hi=None)
        if rs[0]['detected'] is not None:
            ci=stats.mean_ci_t([float(np.mean([r['detected'] for r in cluster])) for cluster in clusters])
            curve.update(event_mean=ci['mean'],event_lo=ci['lo'],event_hi=ci['hi'])
            ci=ratio_ci([cluster[0]['false_events'] for cluster in clusters],[cluster[0]['sending_hours'] for cluster in clusters],const+scheme+rule+'events',n_boot=n_boot)
            curve.update(false_events_h=ci['estimate'],false_events_h_lo=ci['lo'],false_events_h_hi=ci['hi'])
        if rs[0]['tp'] is not None:
            for label,numerator,denominator,twin in (('packet_pdet','tp','crossed',False),('fpr','fp','clean',True)):
                num=[sum(r[numerator] for r in cluster)+(cluster[0]['twin_fp'] if twin else 0) for cluster in clusters]
                den=[sum(r[denominator] for r in cluster)+(cluster[0]['twin_clean'] if twin else 0) for cluster in clusters]
                ci=ratio_ci(num,den,const+scheme+rule+label,n_boot=n_boot)
                curve[label]=ci['estimate'];curve[label+'_lo']=ci['lo'];curve[label+'_hi']=ci['hi']
        curves.append(curve)
    e1.write_csv(out/'campaign_roc.csv',curves)
    reverse=[]
    for r in rows:
        if r['k']!=2:continue
        secondary=json.loads(r.get('reverse_json','[]'))
        for s in secondary:
            rr=dict(r)
            p=s['packet'];ev=s['event'];fp=s['fpr'];ft=s['fpr_twin'];fe=s['false_events_twin']
            rr.update(tp=p['true_detections'],crossed=p['exposed'],reached=p['reached'],lost_at_fault=p['lost_at_fault'],
                      localised_tp=None if r['scheme']=='e2e' else p.get('localised_true_detections',0),
                      induced_unexposed=p.get('induced_unexposed',0),lost_flags=p.get('lost_flags',0),
                      changed_but_unreached=p.get('changed_but_unreached',0),
                      detected=int(ev['detected']),delay_s=ev['delay_ns']/1e9 if ev['detected'] else None,
                      restricted_s=ev['delay_ns']/1e9 if ev['detected'] else 4.,
                      fp=fp['false_positives'],clean=fp['clean'],twin_fp=ft['false_positives'],twin_clean=ft['clean'],
                      false_events=fe['events'],sending_hours=fe['hours'])
            reverse.append(rr)
    reverse_groups=defaultdict(list)
    for r in reverse:reverse_groups[tuple(r[k] for k in ('const','scheme','condition','rule','k'))].append(r)
    e1.write_csv(out/'reverse_per_run.csv',[{k:v for k,v in r.items() if k not in ('latency_json','state_json','steady_state_json','reverse_json')} for r in reverse])
    e1.write_csv(out/'reverse_summary.csv',[summarise(rs,n_boot=n_boot) for rs in reverse_groups.values()])
    selected=[s for s in summary if s['selected'] and s['k']==2 and not e1.CONDITIONS[s['condition']]['null']]
    complete=(len(summary)==1620 and len(selected)==210 and all(s['complete'] for s in summary))
    nulls=[r for r in rows if e1.CONDITIONS[r['condition']]['null']]
    null_ok=all((r['tp'] or 0)==0 and (r['detected'] or 0)==0 for r in nulls)
    verdict=dict(complete=complete,null_rows=len(nulls),null_violations=sum(bool((r['tp'] or 0) or (r['detected'] or 0)) for r in nulls),
                 material_losses=[r for r in paired if r['material_loss']],point_disadvantages=[r for r in paired if r['point_disadvantage']],
                 operating_constraints=[r for r in fpr if r['scheme']=='chronoroute'],model_label='MODELLED network outcomes; DERIVED statistics')
    write_json(out/'verdict.json',verdict)
    km=[]
    for key,rs in groups.items():
        if rs[0]['k']!=2 or not rs[0]['selected'] or rs[0]['detected'] is None:continue
        times,surv=detection.kaplan_meier([r['restricted_s'] for r in rs],[bool(r['detected']) for r in rs])
        for t,s in zip(times,surv):km.append(dict(const=key[0],scheme=key[1],condition=key[2],rule=key[3],time_s=float(t),cdf=1-float(s)))
    e1.write_csv(out/'kaplan_meier.csv',km)
    # Standalone figures use the summary estimates and run-cluster intervals above.
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    (out/'figures').mkdir(exist_ok=True)
    conditions=[c for c,s in e1.CONDITIONS.items() if not s['null']]
    for filename,xfield,yfield,xlabel,ylabel in (
        ('packet-roc.png','fpr','packet_pdet','Clean false-flag rate','Counterfactual packet detection'),
        ('event-roc.png','false_events_h','event_mean','Twin false events / sending hour','Counterfactual event detection')):
        fig,axes=plt.subplots(1,2,figsize=(12,5),layout='constrained')
        for ax,const in zip(axes,('C5','C2')):
            for scheme in e1.SCHEMES:
                points=[s for s in curves if s['const']==const and s['scheme']==scheme and s[xfield] is not None and s[yfield] is not None]
                if points:
                    xx=np.array([s[xfield] for s in points]);yy=np.array([s[yfield] for s in points])
                    ax.errorbar(xx,yy,xerr=[np.maximum(0,xx-[s[xfield+'_lo'] for s in points]),np.maximum(0,[s[xfield+'_hi'] for s in points]-xx)],
                                yerr=[np.maximum(0,yy-[s[yfield.replace('_mean','')+'_lo'] for s in points]),np.maximum(0,[s[yfield.replace('_mean','')+'_hi'] for s in points]-yy)],
                                fmt='o',markersize=4,label=scheme,alpha=.7)
                    if scheme=='chronoroute':
                        ax.plot(xx[:5],yy[:5],linewidth=.8)
                        for s,x,y in zip(points,xx,yy):ax.annotate(s['rule'],(x,y),fontsize=5)
            ax.set(xlabel=xlabel,ylabel=ylabel,title=const+' — MODELLED network',ylim=(-.04,1.04))
            if xfield=='fpr':ax.axvline(.01,color='black',linestyle=':',linewidth=.8)
            if ax.get_legend_handles_labels()[0]:ax.legend(fontsize=7)
        fig.savefig(out/'figures'/filename,dpi=150);plt.close(fig)
    for filename,field,low,high,ylabel in (
        ('detection.png','event_mean','event_lo','event_hi','Event detection probability (t 95% CI)'),
        ('restricted-delay.png','restricted_mean_s','restricted_boot_lo','restricted_boot_hi','Restricted mean delay, seconds (run bootstrap 95% CI)'),
        ('delivery.png','pdr_mean','pdr_lo','pdr_hi','All-flow PDR (t 95% CI)')):
        fig,axes=plt.subplots(2,1,figsize=(14,9),layout='constrained')
        for ax,const in zip(axes,('C5','C2')):
            for si,scheme in enumerate(e1.SCHEMES):
                ps=[s for s in selected if s['const']==const and s['scheme']==scheme and s[field] is not None]
                if not ps:continue
                xx=np.array([conditions.index(s['condition']) for s in ps])+(si-3)*.1
                yy=np.array([s[field] for s in ps]);lo=np.array([s[low] if s[low] is not None else s[field] for s in ps]);hi=np.array([s[high] if s[high] is not None else s[field] for s in ps])
                ax.errorbar(xx,yy,yerr=[np.maximum(0,yy-lo),np.maximum(0,hi-yy)],fmt='.',label=scheme,capsize=2,markersize=4)
            ax.set(xticks=range(len(conditions)),xticklabels=conditions,ylabel=ylabel,title=const+' — MODELLED network')
            ax.tick_params(axis='x',labelrotation=50)
            if ax.get_legend_handles_labels()[0]:ax.legend(fontsize=7,ncol=7)
        fig.savefig(out/'figures'/filename,dpi=150);plt.close(fig)
    report=['# E1 preregistered detection results','', 'Network outcomes are MODELLED; statistics and routes are DERIVED. C5 uses REAL public CelesTrak elements; C2 elements and positions are MODELLED. Starlink operational routing is UNKNOWN; Starlink does not use T-CRH.', '',
            'Completion and null controls: see `verdict.json` and `inventory.csv`. Per-run denominators, fault losses before a checker, undefined exposures, censoring and tail eligibility are retained in `per_run.csv` and `summary.csv`.', '',
            'Operating constraints (pooled fault-clean counts plus each twin once, bootstrap over seeds):','']
    for r in fpr:
        if r['scheme']=='chronoroute':
            if r['fpr'] is None:
                report.append(f"* {r['const']}: incomplete population FPR; no operating-constraint verdict.")
            else:
                report.append(f"* {r['const']}: FPR {r['fpr']:.6f}, 95% CI [{r['lo']:.6f}, {r['hi']:.6f}]; interval {r['interval_position']} the registered limit.")
    report+=['']+comparison_report(paired)
    report+=['','LS packet FPR/detection and O-Q detector endpoints are undefined. O-Q is a privileged delivery bound. CRH-16 is the no-detector control. E2E is unlocalised. The short runs are not a measurement of an operational constellation. City results have two replicates and are descriptive. Raw simulation records are retained locally in the ignored raw cache; the committed manifest ledger preserves producer provenance and output hashes. Reproduction requires rerunning those recorded commands.']
    (out/'REPORT.md').write_text('\n'.join(report)+'\n')
    return complete and null_ok

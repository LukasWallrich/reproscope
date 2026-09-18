"""Registered paired-data sensitivity analyses with separate estimand panels.

No reported result enters the numerical engine. Location, scale and influence
choices are labelled as changes in target or diagnostic scope, not author choices.
"""
from pathlib import Path
from itertools import product
import json,math,hashlib,subprocess,os,shutil
import numpy as np
import pandas as pd
from scipy import stats
from . import reference,artifacts,paths,provenance

VERSION='scoped-paired-2'
DRAWS=9999
SEED=8729


def adjust(ps,method):
    ps=np.asarray(ps,float)
    if method=='none':return ps.copy()
    if method=='bonferroni':return np.minimum(1,len(ps)*ps)
    if method!='holm':raise ValueError('unsupported multiplicity procedure')
    order=np.argsort(ps,kind='stable');out=np.empty_like(ps)
    out[order]=np.minimum(1,np.maximum.accumulate(ps[order]*(len(ps)-np.arange(len(ps)))))
    return out


def location(x,kind,axis=-1):
    if kind=='mean':return np.mean(x,axis=axis)
    if kind!='trim20':raise ValueError('unsupported location functional')
    n=x.shape[axis];g=int(.2*n)
    return np.mean(np.sort(x,axis=axis).take(range(g,n-g),axis=axis),axis=axis)


def bca_interval(d,boot,theta,estimator):
    """Bias-corrected and accelerated interval with delete-one acceleration.

    Midranks handle bootstrap ties; finite-simulation rank limits prevent infinite
    bias corrections. Returned probabilities expose reliance on extreme tails.
    """
    ties=np.isclose(boot,theta,rtol=1e-12,atol=1e-12)
    rank=(np.count_nonzero((boot<theta)&~ties)+.5*np.count_nonzero(ties))/len(boot)
    z0=stats.norm.ppf(np.clip(rank,.5/len(boot),1-.5/len(boot)))
    jack=np.array([location(np.delete(d,i),estimator) for i in range(len(d))])
    influence=jack.mean()-jack
    denominator=6*np.sum(influence**2)**1.5
    if not np.isfinite(denominator) or denominator==0 or np.ptp(boot)==0:
        raise ValueError('BCa interval is undefined for a degenerate bootstrap or jackknife distribution')
    acceleration=float(np.sum(influence**3)/denominator)
    z=stats.norm.ppf([.025,.975])
    probabilities=stats.norm.cdf(z0+(z0+z)/(1-acceleration*(z0+z)))
    if not np.isfinite(probabilities).all() or probabilities[0]>=probabilities[1]:
        raise ValueError('BCa adjusted quantiles are undefined or reversed')
    return np.quantile(boot,probabilities).tolist(),probabilities.tolist()


def prepare(work,plans):
    files={p['file'] for p in plans};identifiers={p.get('id_column') for p in plans}
    if len(files)!=1 or len(identifiers)!=1 or None in identifiers:
        raise ValueError('scoped paired family requires one file and one participant ID')
    _,frame=reference.read_data(work,plans[0]);identifier=plans[0]['id_column']
    if frame[identifier].isna().any() or frame[identifier].duplicated().any():raise ValueError('unique nonmissing participant IDs required')
    for p in plans:
        if p.get('included_ids') is not None:raise ValueError('scoped family currently requires an unrestricted deposited sample')
        if p['family']!='paired_t' or p.get('transformations'):raise ValueError('direct paired deposited columns required')
        frame=reference.numeric_sample(frame,{**p,'missingness':None})
    columns=sorted({p[k] for p in plans for k in ('x','y')})
    if not np.isfinite(frame[columns].to_numpy()).all():raise ValueError('scoped family requires complete finite paired observations; no silent sample change')
    frame['_subject']=frame[identifier].astype(str)
    frame=frame.sort_values('_subject',kind='stable').reset_index(drop=True)
    if len(frame)<10:raise ValueError('too few participants for this registered trimmed/influence grid')
    return frame


def engine(work,plans,*,draws=DRAWS):
    """First plan is focal; other plans define the prespecified multiplicity family."""
    frame=prepare(work,plans)
    if len(plans)<2:raise ValueError('multiplicity dimension requires a real multi-analysis family')
    if not (frame[[plans[0]['x'],plans[0]['y']]].to_numpy()>0).all():raise ValueError('log-ratio sensitivity requires strictly positive focal measurements')
    indices={n:np.random.default_rng(SEED+n).integers(n,size=(draws,n)) for n in (len(frame),len(frame)-1)}
    out=Path(work)/'out';out.mkdir(exist_ok=True)
    for n,ix in indices.items():np.savetxt(out/f'bootstrap_indices_{n}.csv',ix,fmt='%d',delimiter=',')
    bases=[];rows=[]
    for omitted,scale,estimator,procedure in product([None]+frame['_subject'].tolist(),['raw','log_ratio'],['mean','trim20'],['paired_t','centred_bootstrap']):
        if estimator!='mean' and procedure=='paired_t':continue
        # Influence checks use one declared bootstrap specification per estimand.
        if omitted is not None and procedure!='centred_bootstrap':continue
        sample=frame if omitted is None else frame[frame['_subject']!=omitted]
        values=[]
        for j,p in enumerate(plans):
            d=sample[p['x']].to_numpy()-sample[p['y']].to_numpy()
            if j==0 and scale=='log_ratio':d=np.log(sample[p['x']].to_numpy()/sample[p['y']].to_numpy())
            theta=float(location(d,estimator));n=len(d)
            if procedure=='paired_t':
                se=float(np.std(d,ddof=1)/np.sqrt(n));t=theta/se
                pvalue=float(2*stats.t.sf(abs(t),n-1));width=float(stats.t.ppf(.975,n-1)*se)
                lo,hi=theta-width,theta+width;symmetric_lo,symmetric_hi=lo,hi;exceedances=None
                bca=None;adjusted_probabilities=None
            else:
                boot=location(d[indices[n]],estimator)
                exceedances=int(np.count_nonzero(np.abs(boot-theta)>=abs(theta)))
                pvalue=(exceedances+1)/(draws+1);se=float(boot.std(ddof=1))
                lo,hi=map(float,np.quantile(boot,[.025,.975]))
                symmetric_width=float(np.quantile(np.abs(boot-theta),.95))
                symmetric_lo,symmetric_hi=theta-symmetric_width,theta+symmetric_width
                bca,adjusted_probabilities=bca_interval(d,boot,theta,estimator) if omitted is None else (None,None)
            mc_interval=reference.binomial_interval(exceedances,draws,error=.05) if exceedances is not None else None
            values.append(dict(mc_raw_p_interval=mc_interval,estimate=theta,se=se,p_raw=pvalue,ci_lower=lo,ci_upper=hi,ci_symmetric_lower=symmetric_lo,ci_symmetric_upper=symmetric_hi,n=n,exceedances=exceedances,bca_interval=bca,bca_probabilities=adjusted_probabilities))
        bid=f'b{len(bases)+1:04d}'
        base=dict(base_id=bid,omitted=omitted,scale=scale,estimator=estimator,procedure=procedure,members=values)
        bases.append(base)
        intervals=('standard','bca') if procedure=='centred_bootstrap' and omitted is None else ('standard',)
        corrections=('none','holm','bonferroni') if omitted is None else ('none',)
        for multiplicity,interval in product(corrections,intervals):
            focal=dict(values[0])
            if interval=='bca':focal['ci_lower'],focal['ci_upper']=focal['bca_interval']
            spec={'scale':scale,'location':estimator,'inference':procedure,'multiplicity':multiplicity,'interval':interval,'sample':'full' if omitted is None else 'leave_out:'+omitted}
            scope='influence_diagnostic' if omitted is not None else 'primary' if scale=='raw' and estimator=='mean' else 'alternative_estimand'
            rows.append({'spec_id':f's{len(rows)+1:04d}','base_id':bid,'spec':spec,**focal,
                'p':float(adjust([v['p_raw'] for v in values],multiplicity)[0]),'converged':True,
                'scope':scope,'panel':scope+'/'+scale+'/'+estimator,
                'effect_metric':estimator+('_log_ratio' if scale=='log_ratio' else '_paired_difference'),
                'ci_scope':'unadjusted 95% '+('BCa bootstrap interval' if interval=='bca' else 'percentile bootstrap interval' if procedure=='centred_bootstrap' else 't interval'),
                'bca_tail_resolution_limited':bool(interval=='bca' and min(focal['bca_probabilities'][0],1-focal['bca_probabilities'][1])*draws<10),
                'draws':draws if procedure=='centred_bootstrap' else None})
    return rows,bases


def dimension_activity(rows):
    activity={}
    for factor in rows[0]['spec']:
        groups={}
        for r in rows:
            key=tuple((k,v) for k,v in r['spec'].items() if k!=factor)
            groups.setdefault(key,[]).append(r)
        changed=[]
        for group in groups.values():
            if len(group)<2:continue
            first=group[0]
            if any(any(not math.isclose(first[k],r[k],rel_tol=1e-9,abs_tol=1e-12) for k in ('estimate','se','p','ci_lower','ci_upper')) for r in group[1:]):
                changed.append([r['spec_id'] for r in group])
        activity[factor]={'active':bool(changed),'matched_comparison_sets':len(changed),'example':changed[0] if changed else []}
    return activity


def verify_r(work,plans,rows,bases):
    """Independent base-R arithmetic on original columns and common resampling indices."""
    from .isolation import command,clean_environment
    work=Path(work)
    config={'plans':plans,'bases':[{k:v for k,v in b.items() if k!='members'} for b in bases],
            'rows':[{'spec_id':r['spec_id'],'base_id':r['base_id'],'multiplicity':r['spec']['multiplicity'],'interval':r['spec']['interval']} for r in rows]}
    (work/'out/reference_config.json').write_text(json.dumps(config))
    source=Path(__file__).with_name('scoped_reference.R');target=work/'out/scoped_reference.R';shutil.copy2(source,target)
    cmd,boundary=command(['Rscript',str(target)],work,{})
    proc=subprocess.run(cmd,cwd=work,capture_output=True,text=True,timeout=300,env=clean_environment(os.environ.copy(),work))
    (work/'out/reference.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode:raise RuntimeError('independent R reference failed: '+proc.stderr[-1500:])
    other=json.loads((work/'out/reference_results.json').read_text());mapped={r['spec_id']:r for r in other}
    errors=[]
    if set(mapped)!={r['spec_id'] for r in rows}:errors.append('independent reference specification coverage differs')
    for row in rows:
        for key in ('estimate','se','p_raw','p','ci_lower','ci_upper','ci_symmetric_lower','ci_symmetric_upper','n'):
            val=mapped.get(row['spec_id'],{}).get(key)
            if val is None or not math.isclose(row[key],val,rel_tol=1e-8,abs_tol=1e-10):errors.append(row['spec_id']+':'+key)
    return {'status':'invalid' if errors else 'verified','checked':len(rows),'problems':errors,'isolation':boundary,
            'scope':'Independent base-R implementation reads original deposited columns and the registered sample/scale/functional settings. Common fixed resampling indices verify bootstrap arithmetic exactly; these are not independent random draws.'}


def perturbation_checks(work,plans):
    import tempfile
    checks=[]
    with tempfile.TemporaryDirectory(prefix='reproscope_scoped_perturb_') as tmp:
        root=Path(tmp)
        for operation in ('baseline','row_permutation','row_removal','outcome_change'):
            fresh=root/operation;(fresh/'out').mkdir(parents=True);shutil.copytree(Path(work)/'data',fresh/'data')
            target=fresh/plans[0]['file'];frame=pd.read_csv(target)
            if operation=='row_permutation':frame=frame.iloc[::-1]
            elif operation=='row_removal':frame=frame.iloc[1:]
            elif operation=='outcome_change':
                x=plans[0]['x'];frame[x]=frame[x]*np.linspace(1.05,1.25,len(frame))
            frame.to_csv(target,index=False)
            rows,bases=engine(fresh,plans,draws=199)
            check=verify_r(fresh,plans,rows,bases)
            primary=next(r for r in rows if r['scope']=='primary' and r['spec']['inference']=='paired_t' and r['spec']['multiplicity']=='none')
            if operation=='baseline':baseline=primary;continue
            expected=(math.isclose(primary['estimate'],baseline['estimate'],rel_tol=1e-12) and primary['n']==baseline['n']) if operation=='row_permutation' else primary['n']==baseline['n']-1 if operation=='row_removal' else not math.isclose(primary['estimate'],baseline['estimate'],rel_tol=1e-9)
            checks.append({'operation':operation,'status':'verified' if check['status']=='verified' and expected else 'failed','reference_checked':check['checked'],'isolation':check['isolation']})
    return {'status':'verified' if all(c['status']=='verified' for c in checks) else 'failed','checks':checks,'scope':'Original-column reference agreement in each perturbed dataset; row order invariance, row-removal N and changed-outcome dependence.'}


def choose_plans(paper_id,analysis_id):
    """Select verified direct paired plans, independent of their result values."""
    from .stage1.audit import acceptance
    for trace_path in sorted((paths.run_dir(paper_id,1)/'replicas').glob('*/trace.json')):
        trace=json.loads(trace_path.read_text())
        evidence=trace.get('execution_evidence') or {}
        if not trace.get('ran') or acceptance(trace.get('hardcoding_audit') or {})!='accepted':continue
        if evidence.get('analyses',{}).get(analysis_id,{}).get('status')!='verified':continue
        work=trace_path.parent/'work';doc=json.loads((work/'out/analysis_plan.json').read_text())
        candidates=[p for p in doc['analyses'] if p.get('family')=='paired_t' and evidence.get('analyses',{}).get(p['analysis_id'],{}).get('status')=='verified']
        focal=next((p for p in candidates if p['analysis_id']==analysis_id),None)
        if not focal:continue
        selected=[focal];seen={tuple(sorted((focal['x'],focal['y'])))}
        for p in candidates:
            key=tuple(sorted((p['x'],p['y'])))
            if p['file']==focal['file'] and key not in seen:
                selected.append(p);seen.add(key)
        if len(selected)>1:
            from .plan_protocol import normalise
            normalised=[]
            for plan in selected:
                plan,receipt,errors=normalise(plan)
                if errors:raise ValueError('unsupported verified legacy plan: '+ '; '.join(errors))
                normalised.append(plan)
            return trace_path.parent.name,normalised
    raise ValueError('scoped multiverse requires a verified focal paired plan and a genuine bound multiplicity family')


def run(paper_id,focal,inputs):
    stage=paths.run_dir(paper_id,3);work=stage/'work'
    if work.exists():
        import uuid
        archive=stage/'work_superseded'/uuid.uuid4().hex;archive.parent.mkdir(exist_ok=True);shutil.move(str(work),archive)
    (work/'out').mkdir(parents=True)
    replica,plans=choose_plans(paper_id,focal['analysis_id'])
    (work/'data').mkdir()
    manifest=paths.manifest(paper_id)
    for file in {p['file'] for p in plans}:shutil.copy2(manifest.path(file),work/file)
    preregistration={'version':VERSION,'base_replica':replica,'plans':plans,
        'contrast':{'x':plans[0]['x'],'y':plans[0]['y'],'direction':'x minus y; log ratio is log(x/y)'},
        'primary_spec':{'scale':'raw','location':'mean','inference':'paired_t','multiplicity':'none','interval':'standard','sample':'full'},
        'multiplicity_family':'All distinct verified paired comparisons in the focal deposited study file; duplicate source occurrences do not enlarge the family.',
        'family_size':len(plans),'draws':DRAWS,'seed':SEED,
        'sample_policy':'Full deposited complete sample. Separate leave-one-participant-out diagnostics use unadjusted centred bootstrap with percentile intervals for each scale/location estimand; influence is not an analytical dimension.',
        'interval_policy':'Standard t/percentile intervals versus BCa bootstrap intervals. BCa uses delete-one acceleration and bootstrap midranks (numerical tie tolerance 1e-12 absolute and relative); ranks are limited to [0.5/B,1-0.5/B]. Fewer than ten expected draws in an adjusted tail is flagged. BCa is incompatible with paired-t inference. Interval choice never changes the p-value.',
        'trimming':'floor(0.2*n) observations from each tail of within-participant differences, including in every bootstrap sample.',
        'scope':'Primary raw mean inference; alternative location/scale estimands in separate panels; influence results diagnostic. No pooled rank across units or sample targets.'}
    (stage/'registered_design.json').write_text(json.dumps(preregistration,indent=2)+'\n')
    rows,bases=engine(work,plans)
    reference_result=verify_r(work,plans,rows,bases)
    perturbation=perturbation_checks(work,plans)
    full_rows=[r for r in rows if r['spec']['sample']=='full']
    activity={k:v for k,v in dimension_activity(full_rows).items() if k!='sample'}
    diagnostic_activity=dimension_activity(rows)['sample']
    from .multiverse_summary import summarise, render_md
    summary = summarise(rows)
    (stage/'sensitivity_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    problems=list(reference_result['problems'])
    if not summary['influence_complete']:problems.append('leave-one-out diagnostics do not cover every baseline participant')
    if perturbation['status']!='verified':problems.append('perturbation checks failed')
    if sum(v['active'] for v in activity.values())<5:problems.append('fewer than five active full-sample analytical dimensions; influence diagnostics excluded')
    # Source is registered, reviewed code, not generated numerical output.
    from .stage1.audit import hardcoding_audit
    audit,call_id=hardcoding_audit(paper_id,Path(__file__).read_text()+'\n'+Path(__file__).with_name('scoped_reference.R').read_text(),json.dumps(rows[:6]),stage='3')
    from .stage1.audit import acceptance
    if acceptance(audit)!='accepted':problems.append('registered engine code audit unresolved')
    report={'mode':VERSION,'reference':reference_result,'perturbation':perturbation,'audit':audit,'audit_call_id':call_id,
        'dimension_activity':activity,'diagnostic_activity':diagnostic_activity,'problems':problems,'n_specs':len(rows),'n_analytical_specs':len(full_rows),'n_influence_specs':len(rows)-len(full_rows),'generation_access':{'status':'not_applicable','scope':'Registered numerical engine: no model generates or executes multiverse code.'}}
    (stage/'execute.json').write_text(json.dumps(report,indent=2)+'\n')
    (stage/'scoped_results.json').write_text(json.dumps({'design':preregistration,'rows':rows,'base_results':bases},indent=2)+'\n')
    render_plots(work, rows)
    flat=[{**r,**r['spec']} for r in rows]
    for r in flat:r.pop('spec')
    pd.DataFrame(flat).to_csv(work/'out/specs.csv',index=False)
    factors=[]
    descriptions={'scale':'Raw differences versus log ratios; different units and target quantities.','location':'Mean versus 20% trimmed mean of within-participant differences.','inference':'Paired t for the mean or a centred empirical bootstrap; two-sided tests.','multiplicity':'Unadjusted, Holm or Bonferroni within the explicitly listed paired-test family.','interval':'Standard t/percentile intervals or BCa bootstrap intervals; BCa is available for bootstrap inference only.'}
    for name,description in descriptions.items():
        levels=list(dict.fromkeys(r['spec'][name] for r in rows))
        factors.append({'name':name,'source':'code','levels':[{'value':v,'verdict':'defensible','rationale':description,'affects':'inference' if name in {'inference','multiplicity','interval'} else 'estimate'} for v in levels]})
    interpretation=render_md(summary) + '\n## Analytical scope and methods\n\n' + (f'The registered multiverse executed {len(full_rows)} full-sample analytical specifications across five active analytical dimensions, plus {len(rows)-len(full_rows)} influence diagnostics. '
        'Raw mean differences, trimmed differences and log ratios answer different questions and are shown separately. '
        'Bootstrap percentile and BCa intervals and centred-bootstrap p values are not dual and may disagree under skew; symmetric bootstrap intervals are also supplied. BCa uses delete-one acceleration; extreme adjusted tails with fewer than ten expected resamples are flagged. '
        'Intervals are unadjusted 95% intervals; multiplicity adjustments apply to the p values across the declared family. '
        'The same participant resampling indices are reused across outcomes, scales and location functionals, and across equally sized leave-one-out samples. '
        'These analyses start with deposited fitted parameters; they cannot validate the original trial processing or TVA fitting. '
        'Raw bootstrap p values include 95% binomial Monte Carlo intervals; these describe simulation error, not uncertainty in the scientific effect. '
        'Positive estimates mean x exceeds y in the registered focal contrast; log-ratio estimates exponentiate to ratios. '
        'The listed multiplicity family is one declared analytical choice, not the only defensible family. '
        'Author choices are not inferred from which specification matches the reported result.')
    (stage/'interpretation.md').write_text(interpretation+'\n')
    incompatible=[['location=trim20','inference=paired_t'],['interval=bca','inference=paired_t']]
    (stage/'grid.json').write_text(json.dumps({'mode':VERSION,'result_contract_version':1,'factors':factors,'grid_size':len(full_rows),'n_specs':len(rows),'n_influence_specs':len(rows)-len(full_rows),'sensitivity_scope':'five analytical dimensions; separate primary, alternative-estimand and influence panels','incompatible':incompatible},indent=2)+'\n')
    space=artifacts.SpecificationSpace(state='abstained' if problems else 'complete',abstain_reason='; '.join(problems) if problems else None,
        meta=artifacts.ArtifactMeta(artifact='SpecificationSpace',stage='3',inputs=inputs,model_calls=[call_id] if call_id else []),
        claim_id=focal['focal_quantity']['claim_id'],factors=factors,grid_size=len(full_rows),n_specs=len(rows),
        runs=[] if problems else rows,reported_estimate=None,rank=None,interpretation=interpretation,
        mode=VERSION,dimension_activity=activity,sensitivity_scope='separate primary, alternative-estimand and influence panels',
        incompatibilities=incompatible,panels=list(dict.fromkeys(r['panel'] for r in rows)),
        unimplementable=[{'name':'upstream fitting and preprocessing','reason':'Trial-level measurement and fitting inputs are not deposited.'}])
    artifacts.save(space,stage/'space.json')
    return space


def render_plots(work,rows):
    from .isolation import command,clean_environment
    work=Path(work)
    (work/'out/scoped_results.json').write_text(json.dumps({'rows':rows}))
    script=work/'out/scoped_plots.R';shutil.copy2(Path(__file__).with_name('scoped_plots.R'),script)
    cmd,boundary=command(['Rscript',str(script)],work,{})
    proc=subprocess.run(cmd,cwd=work,capture_output=True,text=True,timeout=60,env=clean_environment(os.environ.copy(),work))
    (work/'out/plots.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode:raise RuntimeError('R plot rendering failed: '+proc.stderr[-800:])

"""Readable labels and evidence bundles, joined by recorded identifiers."""
import json,re,math
from pathlib import Path
from collections import Counter
from . import editorial


def label(value):
    return re.sub(r'\s+',' ',str(value or '').replace('_',' ')).strip()


def prose_evidence(value):
    """Keep source prose; internal JSON fragments are already shown as comparisons."""
    text=str(value or '').strip()
    if text.startswith(('{','[','```')) or re.match(r'''^["']\w+["']\s*:''',text):
        return ''
    return text


def numeric(value):
    try:
        n=float(value)
        if n!=n:return '—'
        if n==0:return '0'
        return f'{n:.3g}' if abs(n)<.001 else f'{n:,.4f}'.rstrip('0').rstrip('.')
    except (ValueError,TypeError):return '—'


def method_steps(r):
    """Describe the combined verified method, not unrelated defaults in factor prose."""
    if not r:return []
    parts=[f"Data: {Path(r['file']).name}; columns {r['x']} and {r['y']}."]
    if r.get('transform')=='log':parts.append('Take natural logs of both positive condition values before differencing and selection.')
    if r.get('scoring')=='prorate':parts.append(f"Reconstruct each scale from the person's mean unflagged items, requiring at least {math.ceil(len(r['x_items'])*r['min_item_fraction'])} of {len(r['x_items'])} outcome items and {math.ceil(len(r['y_items'])*r['min_item_fraction'])} of {len(r['y_items'])} predictor items. Noninteger cells are treated as fills under the stated assumption.")
    elif r.get('scoring')=='exclude_flagged':parts.append('Exclude records with noninteger item values, under the stated fill-detection assumption.')
    if r.get('outliers')=='iqr_difference':parts.append(f"Retain differences within {r['outlier_threshold']:g} IQRs of the lower and upper quartiles, using linear quantiles.")
    elif r.get('outliers')=='mahalanobis':parts.append(f"Apply the Mahalanobis exclusion to {', '.join(r['outlier_columns'])}, using the chi-square {r['mahalanobis_probability']:g} quantile.")
    elif r.get('outliers')=='studentized_residual_trim':parts.append(f"Exclude the largest {100*r['outlier_fraction']:g}% of maximum absolute internally studentized residuals across the two raw-variable regressions on the selected covariates (round the excluded count up; ties follow deposited row order). Apply this screen once before ranking or resampling.")
    if r['design']=='paired':
        names={'mean':'arithmetic mean of paired differences','trimmed_difference':f"{100*r['trim_fraction']:g}% symmetrically trimmed mean of paired differences",'yuen':f"difference of separately {100*r['trim_fraction']:g}%-trimmed condition means, with paired winsorised covariance",'rank_biserial':'matched-pairs rank-biserial correlation'}
        parts.append(f"Estimate the {names[r['estimator']]}; the contrast is {r['x']} minus {r['y']}.")
    else:
        target='residualise both variables against the nuisance design.' if r['estimator']=='partial' else f"residualise predictor {r['y']} against the nuisance design, then correlate its residuals with unresidualised outcome {r['x']}."
        parts.append(('Partial' if r['estimator']=='partial' else 'Semi-partial')+(' rank' if r['rank'] else ' Pearson')+' correlation; '+target)
        c=r.get('polynomial_column')
        if c:
            if r.get('spline_probabilities'):parts.append(f"Nuisance design: intercept and a two-column natural spline of raw {c}, knots at percentiles {', '.join(f'{100*p:g}' for p in r['spline_probabilities'])}; knots stay fixed within bootstrap resamples.")
            else:parts.append(f"Nuisance design: intercept and {'ranked ' if r['rank'] else ''}{c}, {'linear plus centred quadratic' if r['polynomial_degree']==2 else 'linear'}.")
        if r.get('covariates'):parts.append(('Rank-transformed nuisance covariates: ' if r.get('rank') and r.get('rank_covariates') else 'Additional nuisance covariates: ')+', '.join(r['covariates'])+'.')
    tests={'t':'Student-t test','yuen':'winsorised trimmed-mean t test','wilcoxon':'exact signed-rank test on nonzero untied differences' if r.get('wilcoxon_policy')=='exact_no_ties' else 'signed-rank test with the documented automatic method selection','sign_flip':'paired sign-flip test','freedman_lane':'Freedman–Lane residual-permutation test','residual_permutation':'direct residual-permutation test (fixed nuisance fits; approximate exchangeability)'}
    test_name=tests[r['test']]
    if r['design']=='association' and r['test']=='t':test_name='full-model coefficient t test' if r['estimator']=='semipartial' else 'partial-correlation t test'
    parts.append(f"Inference: {test_name}, {r['alternative']}.")
    if r['test'] in {'sign_flip','freedman_lane','residual_permutation'}:parts.append(f"{r['test_draws']:,} null draws, seed {r['test_seed']}; "+(f"permute {r.get('permutation_target','outcome')} residuals." if r['test'] in {'freedman_lane','residual_permutation'} else 'flip whole paired differences.'))
    if r['test'] in {'freedman_lane','residual_permutation'}:parts.append('Permutation statistic: '+('full-model coefficient t, recomputed in every draw.' if r.get('permutation_statistic')=='t' else 'the selected correlation, recomputed under the declared null.'))
    ci={'student_t':'estimator-matched Student-t','yuen':'winsorised Yuen','fisher_z':'Fisher-z with adjusted degrees of freedom','bca':'BCa participant bootstrap','percentile':'participant percentile bootstrap'}[r['ci']]
    if r['ci']=='fisher_z' and r.get('rank'):ci+=' (approximation for rank partial correlation)'
    parts.append(f"{100*r['ci_level']:g}% interval: {ci}."+(f" {r['ci_draws']:,} resamples, seed {r['ci_seed']}." if r['ci'] in {'bca','percentile'} else ''))
    if r['adjustment']=='holm':parts.append('Holm correction includes these nonfocal paired tests: '+'; '.join(f"{m['x']} minus {m['y']} ({m['alternative']})" for m in r['family'])+'.')
    elif r['adjustment']=='fixed_threshold':parts.append(f"Compare raw p with {r['per_test_alpha']:g}; the display rescales that criterion to .05 without reconstructing the original test family.")
    else:parts.append('No multiplicity adjustment.')
    return parts


def enrich(ctx,base):
    copy=editorial.load(base);findings=ctx['findings'];s3=ctx.get('s3') or {}
    contracts={c['analysis_id']:c for c in (ctx.get('s0') or {}).get('contracts',[])}
    by_claim={cid:c for c in contracts.values() for cid in c.get('claim_ids',[])}
    replicas=(ctx.get('s1') or {}).get('replicas',[])
    readouts={r['claim_id']:r for r in (ctx.get('descriptive') or {}).get('bindings',[])}
    bindings=((ctx.get('s0') or {}).get('readiness') or {}).get('variable_bindings',[])
    for q in findings['quantities']:
        c=by_claim.get(q['claim_id'],{});q['analysis_id']=c.get('analysis_id');q['method']=c.get('model') or c.get('design') or {}
        q['label']=q['label'].replace('_',' ')
        q['data_bindings']=[{'file':Path(str(b.get('file') or '')).name,'table':b.get('table'),'field':label(b.get('contract_field')),'columns':b.get('input_columns') or ([b['chosen']] if b.get('chosen') else []),'operation':b.get('transformation') or 'direct column'} for b in bindings if q['analysis_id'] and b.get('analysis_id')==q['analysis_id']]
        b=readouts.get(q['claim_id'])
        if b:
            q['readout_evidence']={'file':Path(str(b.get('file') or '')).name,'columns':['participant identifier' if c==b.get('id_column') else c for c in b.get('columns',[])], 'operation':label(b.get('operation')),'filters':[f for f in b.get('filters',[]) if f.get('column')!=b.get('id_column')],'complete_on':b.get('complete_on',[]),'n':(q.get('descriptive') or {}).get('n'),'state':b.get('state'),'reason':b.get('reason')}
        q['method_evidence']=[]
        for replica in replicas:
            e=replica.get('execution_evidence',{}).get('analyses',{}).get(q['analysis_id'])
            if e:q['method_evidence'].append({'replica_id':replica.get('replica_id'),**{k:v for k,v in e.items() if k in {'status','family','x','y','n','df','alternative','method_scope','perturbation_status','covariates','predictors','quantities_checked'}}})
        for r in q['replicas']:
            magnitude=(r.get('comparison_basis') or '').startswith('paired magnitude')
            r['difference']=abs(r['replicated'])-abs(q['reported']) if magnitude and r.get('replicated') is not None and q.get('reported') is not None else r.get('raw_diff')
            r['difference_basis']='Magnitude difference' if magnitude else 'Signed difference'
    lookup={q['claim_id']:q for q in findings['quantities']}
    source=ctx.get('_diagnosis_context') or {}
    inventory={g['group_id']:g for g in source.get('inventory',{}).get('groups',[])}
    diagnoses={d['group_id']:d for d in source.get('diagnoses',[])}
    topics=[]
    if copy:
        for t in copy['topics']:
            ds=[diagnoses[i] for i in t['group_ids']];ids=list(dict.fromkeys(cid for i in t['group_ids'] for cid in inventory.get(i,{}).get('claim_ids',[])))
            unique=[];seen=set()
            for d in ds:
                key=tuple(str(d.get(k,'')) for k in ('evidence_status','explanation','evidence_quote','next_check'))
                if key not in seen:unique.append(d);seen.add(key)
            topics.append({**t,'quantities':[lookup[cid] for cid in ids if cid in lookup],
                'evidence_status':dict(Counter(d.get('evidence_status','unresolved') for d in ds)),
                'source_evidence':[{'quote':d.get('evidence_quote'),'source':d.get('evidence_source')} for d in ds if d.get('evidence_quote')],
                'diagnoses':unique})
    else:
        topics=[{'title':d['title'],'finding':d.get('explanation',''),'cause':'','next_check':d.get('next_check',''),
                 'quantities':d['source_quantities'],'group_ids':d['group_ids'],'evidence_status':{d.get('evidence_status','unresolved'):1},'source_evidence':[{'quote':d.get('evidence_quote'),'source':d.get('evidence_source')}],'diagnoses':[d]} for d in findings['diagnoses']]
    priority={'numerical_mismatch':0,'coverage_invalid_input':1,'descriptive_mismatch':2,'precision_mismatch':3,'rounding_boundary':4,'direction_unstated':5}
    topics.sort(key=lambda t:min((priority.get(inventory.get(i,{}).get('kind'),8) for i in t['group_ids']),default=9))
    normal=lambda s:re.sub(r'\s+',' ',str(s or '').replace('\\n',' ')).strip().lower()
    for question in (ctx.get('s2') or {}).get('questions',{}).values():
        if not isinstance(question,dict):continue
        for finding in question.get('findings',[]):
            anchor=normal(finding.get('anchor'));mentioned=set(re.findall(r'\bc\d+\b',finding.get('source_id','')))
            # A review may anchor its judgement to a diagnosis excerpt. Resolve
            # that recorded excerpt to its claims, never by numeric proximity.
            if len(anchor)>=12:
                for gid,diagnosis in diagnoses.items():
                    if anchor in normal(diagnosis.get('evidence_quote')):
                        mentioned.update(inventory.get(gid,{}).get('claim_ids',[]))
            related=[q for q in findings['quantities'] if q['claim_id'] in mentioned or (len(anchor)>=12 and anchor in normal(q.get('source')))]
            finding['quantity_links']=[{'claim_id':q['claim_id'],'kind':q['kind'],'value':q['reported'],'page':q['page']} for q in related]
            ids={q['claim_id'] for q in related}
            finding['issue_links']=[{'index':i,'title':t['title']} for i,t in enumerate(topics,1) if ids & {q['claim_id'] for q in t['quantities']}]
    execution=s3.get('space',{}).get('execution',{})
    ref=execution.get('reference',{});pert=execution.get('perturbation',{})
    by_spec={e['spec_id']:e for e in ref.get('evidence',[])}
    primary=(s3.get('space',{}).get('curve_reference') or {}).get('effect_group')
    findings['sensitivity']['groups'].sort(key=lambda g:g['name']!=primary)
    for g in findings['sensitivity']['groups']:
        g['label']=copy.get('effect_labels',{}).get(g['name'],label(g['name']))
        for n in g['inference']:n['label']=copy.get('null_labels',{}).get(n['null'],label(n['null']))
        for c in g['changes']:c['label']=copy.get('factor_labels',{}).get(c['factor'],label(c['factor']))
        for r in g['rows']:
            r['choices']=[{'factor':copy.get('factor_labels',{}).get(k,label(k)), 'level':copy.get('level_labels',{}).get(k,{}).get(v,label(v))} for k,v in r.get('spec',{}).items()]
            e=by_spec.get(r.get('spec_id'),{})
            # Never embed participant IDs or a generated recipe in the public report.
            r['verification']={'status':e.get('status','not established'),'checks':[{k:c.get(k) for k in ('field','observed','reference','absolute_tolerance','relative_tolerance','status')} for c in e.get('checks',[]) if c['field']!='sample'],
                'sample':{k:e.get('sample',{}).get(k) for k in ('n','complete_cases','flagged_cells','scoring_exclusions','outlier_exclusions')},'method_steps':method_steps(e.get('recipe',{}))}
            counts={c['field']:c.get('reference') for c in e.get('checks',[]) if c.get('status')=='verified' and c['field'] in {'draws','exceedances'}}
            if set(counts)=={'draws','exceedances'}:
                from ..reference import binomial_interval
                draws=int(counts['draws']);exceedances=int(counts['exceedances'])
                r['verification']['monte_carlo']={'draws':draws,'exceedances':exceedances,
                    'resolution':1/(draws+1),'raw_tail_interval':binomial_interval(exceedances,draws,error=.05)}
    from .specification import reported_position
    curve_reference=s3.get('space',{}).get('curve_reference') or {}
    for g in findings['sensitivity']['groups']:
        g['reported_reference']=reported_position(g,curve_reference)
        g['chart_factors']=[{'name':f['name'],'label':copy.get('factor_labels',{}).get(f['name'],label(f['name'])),
            'levels':[{'value':v,'label':copy.get('level_labels',{}).get(f['name'],{}).get(v,label(v))} for v in g['dimensions'][f['name']]]}
            for f in s3.get('factors',[]) if f['name'] in g['dimensions']]
    factors=[]
    for f in s3.get('factors',[]):
        factors.append({**f,'label':copy.get('factor_labels',{}).get(f['name'],label(f['name'])),
            'levels':[{**l,'how':re.sub(r'Independent reference-adapter verification is unavailable for this [^.]+\.', '', l.get('how') or '').replace('Report once-adjusted p in p, declare the raw p family and adjustment; compare against family alpha .05.', 'Report the declared multiplicity-adjusted p-value against family alpha .05; fixed source thresholds retain their exact criterion.'),'label':copy.get('level_labels',{}).get(f['name'],{}).get(l['value'],label(l['value']))} for l in f['levels']]})
    identifiers={e.get('recipe',{}).get('id_column') for e in ref.get('evidence',[]) if e.get('recipe',{}).get('id_column')}
    for f in factors:
        for l in f['levels']:
            for identifier in identifiers:
                l['how']=re.sub(r'\b'+re.escape(identifier)+r'\b','participant identifier',l['how'])
    if s3.get('interpretation_html') and copy.get('factor_labels'):
        from html import escape
        from markupsafe import Markup
        labels=dict(copy['factor_labels'])
        candidates={}
        for levels in copy.get('level_labels',{}).values():
            for key,value in levels.items():candidates.setdefault(key,set()).add(value)
        labels.update({key:next(iter(values)) for key,values in candidates.items() if len(values)==1})
        pattern=re.compile(r'\b(?:'+'|'.join(re.escape(k) for k in labels)+r')\b')
        pieces=re.split(r'(<[^>]+>)',str(s3['interpretation_html']))
        s3['interpretation_html']=Markup(''.join(part if i%2 else pattern.sub(lambda m:escape(labels[m.group()]),part) for i,part in enumerate(pieces)))
    recipes=[e.get('recipe',{}) for e in ref.get('evidence',[])]
    assumptions=[]
    if any(r.get('scoring') in {'prorate','exclude_flagged'} for r in recipes):
        assumptions.append('Item-rescoring alternatives treat non-integer responses as filled cells. This is a reconstruction assumption: fills that happen to be integers cannot be identified, and participant exclusions may change the represented sample.')
    if any(r.get('test')=='freedman_lane' for r in recipes):
        assumptions.append('Residual permutation requires exchangeable reduced-model residuals. Exact agreement between implementations does not establish that assumption.')
    if any(r.get('test') in {'sign_flip','wilcoxon'} for r in recipes):
        assumptions.append('Sign-flip and signed-rank tests use symmetry or sign-exchangeability assumptions. They are not unrestricted substitutes for a test of the arithmetic mean.')
    thresholds=sorted({r['per_test_alpha'] for r in recipes if r.get('adjustment')=='fixed_threshold'})
    if thresholds:
        assumptions.append('Displayed adjusted p-values rescale the source per-test criterion ('+', '.join(numeric(x) for x in thresholds)+') for comparison with .05. The original family of tests has not been reconstructed; no uncomputed family p-values are invented.')
    return {'topics':topics,'has_editorial':bool(copy),'factors':factors,'reference':ref,'perturbation':pert,
        'assumptions':assumptions,'fully_verified':ref.get('status')=='verified' and pert.get('status')=='verified',
        'source_occurrences':(ctx.get('s0') or {}).get('extraction_benchmark') or {},
        'verification_scope':ref.get('scope','Independent verification coverage has not been established for every component.')}

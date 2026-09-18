"""Deterministic reader-facing findings, with explicit evidence denominators."""
from collections import Counter, defaultdict
import math
import statistics


def number(x):
    try:
        value=float(x)
        return value if math.isfinite(value) else None
    except (ValueError,TypeError):return None


def sensitivity(runs, factors):
    groups=defaultdict(list); diagnostics=[]; failures=[]
    for r in runs:
        spec=r.get('spec') or {}
        if r.get('role')=='author_reference':continue
        if r.get('role')=='influence_diagnostic' or str(spec.get('sample','')).startswith('leave_out:'):
            diagnostics.append(r);continue
        if not r.get('converged'):
            failures.append(r);continue
        if number(r.get('estimate')) is None:continue
        metric=r.get('effect_metric') or spec.get('scale') or 'unspecified metric'
        group=r.get('effect_group') or metric
        row=dict(r)
        for key in ('estimate','se','p','ci_lower','ci_upper','ci_level'):row[key]=number(r.get(key))
        groups[(group,metric)].append(row)
    output=[]
    for (group,metric),rows in sorted(groups.items()):
        from ..multiverse_contract import NULLS
        null_value=NULLS.get(metric,0.)
        values=[r['estimate'] for r in rows]
        nulls=defaultdict(list)
        for row in rows:nulls[row.get('null_group') or 'unspecified null'].append(row)
        inference=[]
        for null, rr in nulls.items():
            pp=[r['p'] for r in rr if r['p'] is not None]
            inference.append({'null':null,'n':len(rr),'n_p':len(pp), 'p_min':min(pp) if pp else None,
                              'p_max':max(pp) if pp else None,
                              'significant':sum(r['p'] is not None and r['p']<(number(r.get('p_threshold')) or .05) for r in rr)})
        dimensions={f['name']:sorted({str(r.get('spec',{}).get(f['name'],'')) for r in rows}) for f in factors}
        active={k:v for k,v in dimensions.items() if len(v)>1}
        changes=[]
        for factor in active:
            paired=defaultdict(list)
            for row in rows:
                signature=tuple(sorted((k,str(v)) for k,v in row.get('spec',{}).items() if k!=factor))
                paired[signature].append(row)
            spans=[max(r['estimate'] for r in rr)-min(r['estimate'] for r in rr) for rr in paired.values() if len({r.get('spec',{}).get(factor) for r in rr})>1]
            inference_spans=[]; width_spans=[]
            for rr in paired.values():
                if len({r.get('spec',{}).get(factor) for r in rr})<2:continue
                for null in {r.get('null_group') for r in rr}:
                    ps=[r['p'] for r in rr if r.get('null_group')==null and r['p'] is not None]
                    if len(ps)>1:inference_spans.append(max(ps)-min(ps))
                widths=[r['ci_upper']-r['ci_lower'] for r in rr if r['ci_lower'] is not None and r['ci_upper'] is not None]
                if len(widths)>1:width_spans.append(max(widths)-min(widths))
            changes.append({'factor':factor,'matched_sets':len(spans),'max_change':max(spans) if spans else None,
                'max_p_change':max(inference_spans) if inference_spans else None,
                'max_interval_width_change':max(width_spans) if width_spans else None})
        output.append({'name':group,'metric':metric,'rows':rows,'n':len(rows),
            'min':min(values),'max':max(values),'median':statistics.median(values),
            'null_value':null_value,'positive':sum(v>null_value for v in values),'negative':sum(v<null_value for v in values),
            'intervals':sum(r['ci_lower'] is not None and r['ci_upper'] is not None for r in rows),
            'inference':inference,'dimensions':active,'changes':changes})
    return {'groups':output,'diagnostics':diagnostics,'failures':failures,
            'n_analytical':sum(g['n'] for g in output),
            'active_dimensions':{f['name']:sorted({str(r.get('spec',{}).get(f['name'],'')) for g in output for r in g['rows']}) for f in factors
                if len({str(r.get('spec',{}).get(f['name'],'')) for g in output for r in g['rows']})>1}}


def assemble(s0,s1,s2,s3,descriptive,diagnosis):
    claims=(s0 or {}).get('claims',[])
    from ..reported_metadata import fields as metadata_fields
    metadata=metadata_fields(claims)
    coverage=(s0 or {}).get('computation_coverage') or {}
    accounting={r['claim_id']:r for r in coverage.get('rows',[])}
    matches=defaultdict(list)
    for row in ((s1 or {}).get('match') or {}).get('rows',[]):matches[row['claim_id']].append(row)
    descriptions={r['claim_id']:r for r in (descriptive or {}).get('results',[])}
    replica_by_id={r['replica_id']:r for r in (s1 or {}).get('replicas',[])}
    analysis_by_claim={cid:c['analysis_id'] for c in (s0 or {}).get('contracts',[]) for cid in c.get('claim_ids',[])}
    quantities=[]
    for c in claims:
        cid=c['claim_id'];rows=matches[cid];account=accounting.get(cid,{})
        computed=[r for r in rows if r.get('replicated') is not None]
        from ..divergence import row_reason
        problems=[r for r in computed if row_reason(r) is not None]
        state=account.get('status','unaccounted')
        verified=[r for r in computed if replica_by_id.get(r.get('replica_id'),{}).get('audit_acceptance')=='accepted'
            and replica_by_id.get(r.get('replica_id'),{}).get('execution_evidence',{}).get('analyses',{}).get(analysis_by_claim.get(cid),{}).get('status')=='verified']
        descriptive_result=descriptions.get(cid) or {}
        if not computed and descriptive_result.get('verification')=='verified':
            state='close descriptive agreement' if descriptive_result.get('matches_printed_rounding') is True else 'check difference'
        if computed:state='check difference' if problems else 'close agreement' if len(verified)==len(computed) else 'agreement from unverified implementation'
        basis=((s0 or {}).get('readiness') or {}).get('binding_scope',{}).get(analysis_by_claim.get(cid),{})
        if basis.get('basis')=='conventional_reconstruction' and state=='close agreement':state='close agreement under declared convention'
        quantities.append({'metadata':[m for m in metadata if m['claim_id']==cid],'binding_scope':basis,'claim_id':cid,'label':c.get('description') or c.get('analysis_label') or c.get('target_outcome') or cid,
            'source_aliases':[m for m in ((s0 or {}).get('assignments') or {}).get('term_map',[]) if cid in m.get('claim_ids',[])],
            'study':c.get('study_id'),'kind':c.get('quantity_kind'),'reported':c.get('value'),
            'comparator':c.get('comparator') or '=', 'page':(c.get('location') or {}).get('page'),
            'source':c.get('source_quote'),'status':state,'reason':account.get('reason'),
            'replicas':computed,'n_verified':len(verified),'n_computed':len(computed),'n_attempted':len(rows),'descriptive':descriptions.get(cid)})
    lookup={q['claim_id']:q for q in quantities}
    diagnoses=[]
    issues={g['group_id']:g for g in ((diagnosis or {}).get('inventory') or {}).get('groups',[])}
    for d in (diagnosis or {}).get('diagnoses',[]):
        row=dict(d)
        issue=issues.get(d.get('group_id'),{})
        members=issue.get('claim_ids') or d.get('claim_ids') or [x.split(':')[0] for x in d.get('divergence_ids',[])]
        row['source_quantities']=[lookup[c] for c in members if c in lookup]
        outcome=(issue.get('contract') or {}).get('outcome') or (row['source_quantities'][0]['label'] if row['source_quantities'] else d.get('group_id','Issue'))
        row['kind']=issue.get('kind','')
        row['title']=outcome.split('. ')[0]+' — '+row['kind'].replace('_',' ')
        diagnoses.append(row)
    grouped={}
    for row in diagnoses:
        key=(row.get('kind'),row.get('evidence_status'),row.get('explanation'),row.get('next_check')) if row.get('kind','').startswith('coverage_') else row['group_id']
        if key not in grouped:
            grouped[key]={**row,'group_ids':[row['group_id']]}
        else:
            target=grouped[key];target['group_ids'].append(row['group_id'])
            existing={q['claim_id'] for q in target['source_quantities']}
            target['source_quantities'] += [q for q in row['source_quantities'] if q['claim_id'] not in existing]
            target['title']=f"{len(target['source_quantities'])} quantities — {row['kind'].replace('_',' ')}"
            target['group_id']=', '.join(target['group_ids'])
    priority={'numerical_mismatch':0,'coverage_invalid_input':1,'descriptive_mismatch':2,
              'precision_mismatch':3,'direction_unstated':4,'rounding_boundary':5}
    ordered=sorted(grouped.values(),key=lambda row:priority.get(row.get('kind'),9 if row.get('kind','').startswith('coverage_') else 6))
    return {'quantities':quantities,'n_metadata':len(metadata),'counts':dict(Counter(q['status'] for q in quantities)),
        'coverage':coverage,'diagnoses':ordered,'n_diagnosis_groups':len(diagnoses),
        'sensitivity':sensitivity((s3 or {}).get('runs',[]),(s3 or {}).get('factors',[]))}

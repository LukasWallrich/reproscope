"""Independent named-family and nested-likelihood checks against intake bindings."""
from pathlib import Path
import math
from . import reference

FAMILIES={'paired_t_family','correlation_family','likelihood_ratio'}


def check(work, plan, analysis, rows, regenerated):
    errors=[];compared=0;unsupported=[]
    if plan['family']=='likelihood_ratio':
        binding=analysis.get('likelihood_binding') or {}
        if not binding:
            return {'status':'unverified','reason':'intake likelihood binding missing'}
        for key in ('x','y','table','aggregation'):
            if plan.get(key)!=binding.get(key):errors.append(f'likelihood {key} differs from intake')
        if Path(plan['file']).name!=Path(binding['file']).name:errors.append('likelihood file differs from intake')
        if plan['df_per_subject'] != binding['full_parameters_per_subject']-binding['reduced_parameters_per_subject']:
            errors.append('likelihood parameter difference differs from intake')
        members=[plan]
    else:
        declared=(analysis.get('design') or {}).get('family')
        wanted='paired_t' if plan['family']=='paired_t_family' else 'correlation'
        if declared not in (wanted,):errors.append('family differs from intake design')
        expected={m['member_id']:m for m in analysis.get('members',[])}
        members=plan['members']
        if set(expected)!={m['analysis_id'] for m in members}:errors.append('family members differ from intake')
        for member in members:
            bound=expected.get(member['analysis_id'],{})
            for key in ('x','y','table','numeric_parsing'):
                if member.get(key)!=bound.get(key):errors.append(f'{member["analysis_id"]}: {key} differs from intake')
            if Path(member['file']).name!=Path(bound.get('file','')).name:errors.append('family file differs from intake')
            tail=(analysis.get('design') or {}).get('alternative')
            if tail not in (None,'unknown') and member['alternative']!=tail:errors.append('family tail differs from intake')
    for member in members:
        _,frame=reference.read_data(work,member)
        selection=analysis.get('sample_selection') or {}
        if member.get('included_ids') is not None:
            required=selection.get('included_ids')
            if required is None:required=reference.numeric_sample(frame,member)[member['id_column']].tolist()
            if set(required)!=set(member['included_ids']):errors.append('sample differs from intake')
        elif selection.get('included_ids') is not None:errors.append('intake sample restriction missing')
    result=reference.from_plan(work,plan)
    targets={q['claim_id']:q for q in analysis.get('quantities',[])}
    for row in rows:
        if row.get('analysis_id')!=analysis['analysis_id']:continue
        q=targets.get(row.get('claim_id'),{})
        if q.get('quantity_role')=='supplied_fact':continue
        metric={'p_value':'p_raw','d':'dz'}.get(q.get('quantity_kind'),q.get('quantity_kind'))
        if metric not in result or row.get('value') is None:
            unsupported.append(row.get('claim_id'));continue
        actual=row['value'];expected=result[metric]
        if isinstance(expected,list):
            wanted=q.get('member_ids') or []
            if row.get('member_ids')!=wanted or set(wanted)!=set(result['member_ids']):
                errors.append(f'{row["claim_id"]}: member identity differs');continue
            lookup=dict(zip(result['member_ids'],expected));expected=[lookup[mid] for mid in wanted]
            okay=isinstance(actual,list) and len(actual)==len(expected) and all(math.isclose(float(x),y,rel_tol=1e-5,abs_tol=1e-10) for x,y in zip(actual,expected))
        else:
            okay=isinstance(actual,(int,float)) and math.isclose(actual,expected,rel_tol=1e-5,abs_tol=1e-10)
        if not okay:errors.append(f'{row["claim_id"]}: independently computed {metric} differs')
        if row.get('n')!=result['n']:errors.append(f'{row["claim_id"]}: sample size differs')
        compared+=1
    return {'status':'invalid' if errors else 'verified' if compared and not unsupported and regenerated else 'unverified',
            'family':plan['family'],'n':result['n'],'df':result.get('df'),'member_n':result.get('member_n'),'quantities_checked':compared,'unverified_quantities':unsupported,
            'problems':errors,'support_status':'supported','computation_status':'recomputed_mismatch' if errors else 'recomputed_match',
            'method_scope':'Intake-bound columns, named family members, sample and explicit likelihood parameter counts; reproduction from deposited summaries does not validate upstream fitting.'}

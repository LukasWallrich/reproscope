"""Closed checks for partial Pearson correlations and classical linear models.

Partial-correlation inference uses n-k-2 degrees of freedom (Kim, 2015,
https://pmc.ncbi.nlm.nih.gov/articles/PMC4681537/). OLS uses an intercept,
classical covariance and t/F inference; robust, weighted and transformed fits
remain outside this adapter. Source targets never enter these calculations.
"""
from pathlib import Path
import math
import re
import numpy as np
from scipy import stats
from . import reference


def calculate(frame,plan):
    columns=([plan['x'],plan['y']]+plan['covariates'] if plan['family']=='partial_correlation'
             else [plan['x']]+plan['predictors'])
    values=frame[columns].to_numpy(float)
    if not np.isfinite(values).all():raise ValueError('adjusted model requires finite complete observations')
    n=len(values)
    if plan['family']=='partial_correlation':
        z=np.column_stack([np.ones(n),values[:,2:]])
        if np.linalg.matrix_rank(z)!=z.shape[1]:raise ValueError('rank-deficient covariate matrix')
        residual=values[:,:2]-z@np.linalg.lstsq(z,values[:,:2],rcond=None)[0]
        r=float(np.corrcoef(residual.T)[0,1]);df=n-z.shape[1]-1
        if df<=0 or not np.isfinite(r) or abs(r)>=1:raise ValueError('partial correlation has insufficient degrees of freedom or degenerate residuals')
        t=r*math.sqrt(df/(1-r*r))
        return {'n':n,'df':df,'r':r,'t':t,'p_raw':float(2*stats.t.sf(abs(t),df))}
    y=values[:,0];design=np.column_stack([np.ones(n),values[:,1:]])
    k=design.shape[1];df=n-k
    if df<=0 or np.linalg.matrix_rank(design)!=k:raise ValueError('regression requires a full-rank design and residual degrees of freedom')
    coef=np.linalg.lstsq(design,y,rcond=None)[0];residual=y-design@coef
    sse=float(residual@residual);sst=float(((y-y.mean())**2).sum())
    if sst<=0 or sse<=0:raise ValueError('regression outcome or residual variance is degenerate')
    se=np.sqrt(np.diag(np.linalg.inv(design.T@design))*sse/df)
    r2=1-sse/sst;f=(sst-sse)/(k-1)/(sse/df)
    out={'n':n,'df':df,'r2':r2,'F':f,'p_raw':float(stats.f.sf(f,k-1,df))}
    if plan['coefficient'] is not None:
        index=plan['predictors'].index(plan['coefficient'])+1
        b=float(coef[index]);stderr=float(se[index]);t=b/stderr;q=float(stats.t.ppf(.975,df))
        out.update(coefficient=b,beta=b*values[:,index].std(ddof=1)/y.std(ddof=1),se=stderr,t=t,
                   p_raw=float(2*stats.t.sf(abs(t),df)),ci_lower=b-q*stderr,ci_upper=b+q*stderr)
    return out


def check(work,plan,analysis,rows,regenerated):
    from .plan_protocol import AdjustedPlan
    AdjustedPlan.model_validate(plan)
    errors=[];unsupported=[];compared=0
    bindings={b['contract_field']:b for b in analysis.get('variable_bindings',[])}
    chosen={key:b.get('chosen') for key,b in bindings.items()}
    model=analysis.get('design') or {}
    predictor_columns={value for key,value in chosen.items() if key.startswith('predictors[') and value}
    covariate_columns={value for key,value in chosen.items() if key.startswith('covariates[') and value}
    if not chosen.get('outcome'):errors.append('adjusted model outcome is not directly bound')
    if plan['family']=='partial_correlation':
        if model.get('family')!='correlation' or not analysis.get('covariates'):errors.append('partial correlation not established by intake')
        if {plan['x'],plan['y']}!={chosen.get('outcome')}|predictor_columns:errors.append('partial-correlation pair differs from intake')
        if set(plan['covariates'])!=covariate_columns or len(covariate_columns)!=len(analysis.get('covariates',[])):
            errors.append('covariate set differs from intake')
    else:
        declared=' '.join(str(model.get(key,'')) for key in ('family','evidence','contrast'))+' '+str(analysis.get('identity',{}).get('model',''))
        if not re.search(r'regress|\bOLS\b',declared,re.I):errors.append('linear regression not established by intake')
        if plan['x']!=chosen.get('outcome') or set(plan['predictors'])!=predictor_columns|covariate_columns:
            errors.append('regression design differs from intake')
        if plan['coefficient'] is not None and chosen.get(plan['coefficient_field'])!=plan['coefficient']:
            errors.append('coefficient does not name its intake-bound term')
        target=analysis.get('coefficient_target')
        if target is not None:
            if target.get('state')!='resolved':
                errors.append('Requested coefficient identity remains unresolved by independent source-only readings.')
            elif chosen.get(target.get('binding_field'))!=plan.get('coefficient'):
                errors.append('Declared coefficient differs from the requested source term. Contract: '
                    +target.get('evidence_quote','')+'; required binding: '+str(target.get('binding_field')))
    for binding in bindings.values():
        if binding.get('chosen') and (Path(binding.get('file') or '').name!=Path(plan['file']).name or binding.get('table')!=plan.get('table')):
            errors.append('adjusted model file/table differs from intake')
        if binding.get('input_columns') and binding.get('chosen') not in binding['input_columns']:
            errors.append('derived binding requires a separate transformation adapter')
    _,frame=reference.read_data(work,plan)
    selection=analysis.get('sample_selection') or {}
    if selection and (Path(selection['file']).name!=Path(plan['file']).name or selection.get('table')!=plan.get('table')):
        errors.append('sample binding refers to another table')
    if plan.get('included_ids') is not None:
        identifier=plan.get('id_column')
        if not identifier or identifier not in frame:raise ValueError('missing deposited sample identifier')
        required=selection.get('included_ids')
        if required is None:required=reference.numeric_sample(frame,plan)[identifier].tolist()
        if set(required)!=set(plan['included_ids']):errors.append('declared sample differs from intake-authorised sample')
    elif selection.get('included_ids') is not None:errors.append('intake sample restriction not implemented')
    result=reference.from_plan(work,plan)
    quantities={q['claim_id']:q for q in analysis.get('quantities',[])}
    if plan['family']=='linear_regression' and plan['coefficient'] is None:
        term_quantities=[q['claim_id'] for q in quantities.values()
            if q.get('quantity_role')!='supplied_fact' and q.get('quantity_kind') in {'coefficient','t','ci_bound'}]
        if term_quantities:
            errors.append('Coefficient-level quantities require a declared coefficient and coefficient_field; '
                'both are null, so the plan only computes model-level statistics. Identify the requested term '
                'from the blinded analysis contrast and its exact variable binding, and compute that term: '
                +', '.join(term_quantities))
    for row in rows:
        if row.get('analysis_id')!=analysis['analysis_id']:continue
        q=quantities.get(row.get('claim_id'),{})
        if q.get('quantity_role')=='supplied_fact':continue
        kind=q.get('quantity_kind');raw=str(q.get('quantity_kind_raw') or '').strip()
        metric={'p_value':'p_raw'}.get(kind,kind)
        if kind=='coefficient' and raw in {'beta','β','standardized beta','standardised beta'}:metric='beta'
        if kind=='ci_bound':
            # A bound needs explicit endpoint identity; never choose the closest one.
            metric={'lower':'ci_lower','upper':'ci_upper','ci_lower':'ci_lower','ci_upper':'ci_upper'}.get(raw)
        if kind=='other' and raw.lower() in {'r2','r²','r^2'}:metric='r2'
        if metric not in result or row.get('value') is None or q.get('aggregation','scalar')!='scalar':
            unsupported.append(row.get('claim_id'));continue
        if not isinstance(row['value'],(int,float)) or not math.isclose(float(row['value']),result[metric],rel_tol=1e-5,abs_tol=1e-10):
            errors.append(f"{row['claim_id']}: independently computed {metric} differs")
        if row.get('n') is not None and row['n']!=result['n']:errors.append(f"{row['claim_id']}: independently computed sample size differs")
        compared+=1
    return {'status':'invalid' if errors else 'verified' if compared and regenerated and not unsupported else 'unverified',
            'family':plan['family'],'n':result['n'],'df':result['df'],'problems':errors,'quantities_checked':compared,
            'unverified_quantities':unsupported,'support_status':'supported',
            'coefficient_identity':analysis.get('coefficient_target'),
            'method_scope':'Direct intake-bound outcome, complete predictor/covariate set and sample; classical adjusted calculation. Coefficient identity is checked against independent source-only term readings when supplied.'}

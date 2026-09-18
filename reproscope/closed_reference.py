"""Numerical checks from independently translated closed method recipes.

No imports from generated sources, no executor-defined data selections. Analytic
checks use tight floating-point tolerances. Resampling uses a declared PCG64
stream, row indices from Generator.integers, and Generator.permutation for null
residual permutations. This checks implementation, not validity of assumptions.
"""
import json, math
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
from . import provenance
from .verification_recipe import Recipe, compile_book

VERSION='closed-reference-2'


def sample(work, r):
    from .reference import read_data
    _, frame=read_data(Path(work),r)
    frame=frame.copy()
    cols=list(dict.fromkeys([r['x'],r['y']]+r['covariates']+([r['polynomial_column']] if r['polynomial_column'] else [])+r['outlier_columns']+(r['x_items']+r['y_items'] if r['scoring']!='deposited' else [])))
    frame[cols]=frame[cols].apply(pd.to_numeric,errors='raise')
    frame=frame.dropna(subset=cols)
    audit={'complete_cases':len(frame),'flagged_cells':0,'scoring_exclusions':0}
    if r.get('spline_probabilities') and r.get('spline_knot_scope')=='complete_cases':
        audit['spline_knots']=np.quantile(frame[r['polynomial_column']],r['spline_probabilities']).tolist()
    keep=np.ones(len(frame),dtype=bool)
    if r['scoring']!='deposited':
        for total,items in [(r['x'],r['x_items']),(r['y'],r['y_items'])]:
            if not items:raise ValueError('item reconstruction requires explicit item columns')
            a=frame[items].to_numpy(float)
            if not np.allclose(a.sum(axis=1),frame[total],rtol=1e-7,atol=1e-6):raise ValueError('item sums do not reproduce deposited totals')
            flagged=np.abs(a-np.rint(a))>r['integer_tolerance']
            audit['flagged_cells']+=int(flagged.sum())
            if r['scoring']=='exclude_flagged':keep &= ~flagged.any(axis=1)
            else:
                observed=(~flagged).sum(axis=1)
                keep &= observed>=math.ceil(len(items)*r['min_item_fraction'])
                means=np.divide(np.where(flagged,0.,a).sum(axis=1),observed,out=np.full(len(a),np.nan),where=observed>0)
                frame[total]=means*len(items)
        audit['scoring_exclusions']=int((~keep).sum());frame=frame.loc[keep].copy()
    if r['transform']=='log':
        if (frame[[r['x'],r['y']]]<=0).any().any():raise ValueError('log transform requires strictly positive paired values')
        frame[[r['x'],r['y']]]=np.log(frame[[r['x'],r['y']]])
    before=len(frame)
    if r['outliers']=='iqr_difference':
        d=frame[r['x']]-frame[r['y']];q1,q3=np.quantile(d,[.25,.75]);t=r['outlier_threshold']*(q3-q1)
        frame=frame.loc[(d>=q1-t)&(d<=q3+t)].copy()
    elif r['outliers']=='mahalanobis':
        a=frame[r['outlier_columns']].to_numpy(float);a=a-a.mean(axis=0)
        cov=np.cov(a,rowvar=False,ddof=1)
        if np.linalg.matrix_rank(cov)!=len(r['outlier_columns']):raise ValueError('singular outlier covariance')
        distance=np.sum(a*np.linalg.solve(cov,a.T).T,axis=1)
        frame=frame.loc[distance<=stats.chi2.ppf(r['mahalanobis_probability'],a.shape[1])].copy()
    elif r['outliers']=='studentized_residual_trim':
        raw={**r,'rank':False,'rank_covariates':False}
        y,x,z=vectors(frame,raw);q=np.linalg.qr(z,mode='reduced')[0]
        leverage=np.sum(q*q,axis=1);df=len(frame)-z.shape[1]
        if df<1 or np.any(leverage>=1):raise ValueError('degenerate studentized residual trim')
        scores=[]
        for v in (y,x):
            e=v-q@(q.T@v);scale=np.sqrt(np.dot(e,e)/df)
            if scale<=0:raise ValueError('zero residual variance in trim')
            scores.append(abs(e)/(scale*np.sqrt(1-leverage)))
        score=np.round(np.maximum(*scores),12);count=math.ceil(r['outlier_fraction']*len(frame))
        removed=np.argsort(-score,kind='stable')[:count]
        keep=np.ones(len(frame),dtype=bool);keep[removed]=False
        frame=frame.iloc[keep].copy()
    audit['outlier_exclusions']=before-len(frame)
    if len(frame)<4 or not np.isfinite(frame[cols].to_numpy(float)).all():raise ValueError('insufficient or nonfinite reference sample')
    if r['id_column'] and frame[r['id_column']].isna().any():raise ValueError('missing sample identifier')
    ids=frame[r['id_column']].tolist() if r['id_column'] else frame.index.tolist()
    if len(set(ids))!=len(ids):raise ValueError('duplicate sample identifiers')
    audit.update(n=len(frame),sample_sha256=provenance.digest(sorted(ids)),columns=cols)
    return frame,ids,audit


def spline_term(c,knots):
    """Three-knot natural cubic space, alongside intercept and linear input."""
    a,b,d=knots
    if not a<b<d:raise ValueError('spline knots must be distinct')
    cube=lambda x:np.maximum(x,0.)**3
    return (cube(c-a)-cube(c-b)*(d-a)/(d-b)+cube(c-d)*(b-a)/(d-b))/(d-a)**2


def vectors(frame,r):
    y=frame[r['x']].to_numpy(float);x=frame[r['y']].to_numpy(float)
    z=[np.ones(len(frame))]
    if r['rank']:y,x=stats.rankdata(y),stats.rankdata(x)
    if r['polynomial_column']:
        c=frame[r['polynomial_column']].to_numpy(float)
        if r.get('spline_probabilities'):
            knots=r.get('_spline_knots',np.quantile(c,r['spline_probabilities']))
            z.extend([c,spline_term(c,knots)])
        else:
            if r['rank']:c=stats.rankdata(c)
            if r['polynomial_degree']==2:c=c-c.mean()
            z.append(c)
            if r['polynomial_degree']==2:z.append(c*c)
    z += [stats.rankdata(frame[c].to_numpy(float)) if r['rank'] and r['rank_covariates'] else frame[c].to_numpy(float) for c in r['covariates']]
    z=np.column_stack(z)
    if np.linalg.matrix_rank(z)!=z.shape[1]:raise ValueError('rank deficient nuisance design')
    return y,x,z


def association(frame,r):
    y,x,z=vectors(frame,r)
    # QR projection is separate from the executor's least-squares regression.
    q=np.linalg.qr(z,mode='reduced')[0]
    ey=y-q@(q.T@y);ex=x-q@(q.T@x)
    full=float(np.corrcoef(ey,ex)[0,1])
    effect=full if r['estimator']=='partial' else float(np.corrcoef(y,ex)[0,1])
    df=len(y)-z.shape[1]-1
    if df<1 or abs(full)>=1:raise ValueError('degenerate association')
    t=full*math.sqrt(df/(1-full*full))
    return effect,df,t,(y,x,z,q,ey,ex)


def rank_biserial(d):
    d=d[d!=0]
    if not len(d):raise ValueError('all paired differences are zero')
    ranks=stats.rankdata(abs(d))
    return float(np.sum(ranks*np.sign(d))/ranks.sum())


def paired(frame,r):
    x,y=frame[r['x']].to_numpy(float),frame[r['y']].to_numpy(float);d=x-y;n=len(d)
    if r['estimator']=='mean':effect=float(d.mean());se=float(d.std(ddof=1)/math.sqrt(n));df=n-1
    elif r['estimator']=='trimmed_difference':
        g=int(n*r['trim_fraction']);h=n-2*g
        if h<3:raise ValueError('insufficient trimmed effective sample')
        w=np.clip(d,*np.sort(d)[[g,n-g-1]])
        effect=float(stats.trim_mean(d,r['trim_fraction']));se=float(np.std(w,ddof=1)*math.sqrt((n-1)/(h*(h-1))));df=h-1
    elif r['estimator']=='yuen':
        g=int(n*r['trim_fraction']);h=n-2*g
        if h<3:raise ValueError('insufficient trimmed effective sample')
        # Paired Yuen, WRS2::yuend: winsorise each marginal, preserve covariance.
        wx=np.clip(x,*np.sort(x)[[g,n-g-1]]);wy=np.clip(y,*np.sort(y)[[g,n-g-1]])
        effect=float(stats.trim_mean(x,r['trim_fraction'])-stats.trim_mean(y,r['trim_fraction']))
        se=float(np.std(wx-wy,ddof=1)*math.sqrt((n-1)/(h*(h-1))));df=h-1
    else:effect=rank_biserial(d);se=None;df=None
    return effect,se,df,d


def tail(t,df,alt):
    return float(2*stats.t.sf(abs(t),df) if alt=='two-sided' else stats.t.sf(t,df) if alt=='greater' else stats.t.cdf(t,df))


def bootstrap_associations(frame,r):
    """Batched QR projections; ranks and nuisance terms are rebuilt per draw."""
    columns=[r['x'],r['y']]+([r['polynomial_column']] if r['polynomial_column'] else [])+r['covariates']
    data=frame[columns].to_numpy(float);n=len(data);rng=np.random.default_rng(r['ci_seed']);values=[]
    knots=r.get('_spline_knots')
    if r.get('spline_probabilities') and knots is None:knots=np.quantile(frame[r['polynomial_column']],r['spline_probabilities'])
    for start in range(0,r['ci_draws'],250):
        size=min(250,r['ci_draws']-start);a=data[rng.integers(0,n,(size,n))]
        y=a[:,:,0];x=a[:,:,1];z=[np.ones_like(x)];offset=2
        if r['rank']:y,x=stats.rankdata(y,axis=1),stats.rankdata(x,axis=1)
        if r['polynomial_column']:
            c=a[:,:,2];offset+=1
            if r.get('spline_probabilities'):z.extend([c,spline_term(c,knots)])
            else:
                if r['rank']:c=stats.rankdata(c,axis=1)
                if r['polynomial_degree']==2:c=c-c.mean(axis=1,keepdims=True)
                z.append(c)
                if r['polynomial_degree']==2:z.append(c*c)
        z.extend(stats.rankdata(a[:,:,j],axis=1) if r['rank'] and r['rank_covariates'] else a[:,:,j] for j in range(offset,a.shape[2]))
        design=np.stack(z,axis=2);q,rr=np.linalg.qr(design,mode='reduced')
        if np.any(abs(np.diagonal(rr,axis1=1,axis2=2))<1e-10):raise ValueError('singular bootstrap nuisance design; no draws silently omitted')
        def residual(v):return v-np.einsum('bnk,bk->bn',q,np.einsum('bnk,bn->bk',q,v))
        x=residual(x)
        if r['estimator']=='partial':y=residual(y)
        x-=x.mean(axis=1,keepdims=True);y-=y.mean(axis=1,keepdims=True)
        values.extend(np.sum(x*y,axis=1)/np.sqrt(np.sum(x*x,axis=1)*np.sum(y*y,axis=1)))
    return values


def bootstrap_pairs(frame,r):
    """Resample intact pairs, preserving the declared PCG64 draw sequence."""
    x=frame[r['x']].to_numpy(float);y=frame[r['y']].to_numpy(float);n=len(x)
    rng=np.random.default_rng(r['ci_seed']);values=[];g=int(n*r['trim_fraction'])
    for start in range(0,r['ci_draws'],1000):
        ids=rng.integers(0,n,(min(1000,r['ci_draws']-start),n));d=x[ids]-y[ids]
        if r['estimator']=='mean':est=d.mean(axis=1)
        elif r['estimator']=='trimmed_difference':est=np.sort(d,axis=1)[:,g:n-g].mean(axis=1)
        elif r['estimator']=='yuen':est=np.sort(x[ids],axis=1)[:,g:n-g].mean(axis=1)-np.sort(y[ids],axis=1)[:,g:n-g].mean(axis=1)
        else:
            ranks=stats.rankdata(np.where(d!=0,abs(d),np.nan),axis=1,nan_policy='omit')
            denominator=np.nansum(ranks,axis=1)
            if np.any(denominator==0):raise ValueError('all paired differences zero in a bootstrap sample')
            est=np.nansum(ranks*np.sign(d),axis=1)/denominator
        values.extend(est)
    return values


def calculate(work,recipe,*, cache=None):
    r=Recipe.model_validate(recipe).model_dump()
    # Cache within one immutable-data check only; includes every recipe setting.
    key=provenance.digest(r)
    if cache is not None and key in cache:return cache[key]
    frame,ids,audit=sample(work,r);n=len(frame);se=None;df=None
    if r.get('spline_probabilities'):
        r['_spline_knots']=audit.get('spline_knots',np.quantile(frame[r['polynomial_column']],r['spline_probabilities']).tolist())
    if r['design']=='paired':
        effect,se,df,d=paired(frame,r)
        if r['test'] in {'t','yuen'}:p=tail(effect/se,df,r['alternative'])
        elif r['test']=='wilcoxon':
            policy=r.get('wilcoxon_policy','auto')
            if policy=='exact_no_ties' and (np.any(d==0) or len(np.unique(abs(d)))!=len(d)):
                raise ValueError('screened exact signed-rank method requires nonzero untied differences')
            p=float(stats.wilcoxon(d,zero_method='wilcox',correction=True,alternative=r['alternative'],method='exact' if policy=='exact_no_ties' else 'auto').pvalue)
        elif r['test']=='sign_flip':
            rng=np.random.default_rng(r['test_seed']);k=0
            for start in range(0,r['test_draws'],1000):
                signs=2*rng.integers(0,2,size=(min(1000,r['test_draws']-start),n))-1
                null=np.mean(signs*d,axis=1)
                k+=int(np.count_nonzero(abs(null)>=abs(effect)-1e-12 if r['alternative']=='two-sided' else null>=effect-1e-12 if r['alternative']=='greater' else null<=effect+1e-12))
            p=(k+1)/(r['test_draws']+1)
        else:raise ValueError('test incompatible with paired design')
    else:
        effect,df,t,(y,x,z,q,ey,ex)=association(frame,r)
        if r['test']=='t':p=tail(t,df,r['alternative'])
        elif r['test'] in {'freedman_lane','residual_permutation'}:
            rng=np.random.default_rng(r['test_seed']);predictor=r.get('permutation_target','outcome')=='predictor'
            moving,residual=(x,ex) if predictor else (y,ey)
            fixed=(ey if r['estimator']=='partial' else y) if predictor else ex
            fit=moving-residual;k=0
            statistic=abs(t) if r['permutation_statistic']=='t' else abs(effect)
            for start in range(0,r['test_draws'],250):
                yy=np.array([rng.permutation(residual) for _ in range(min(250,r['test_draws']-start))])
                if r['test']=='freedman_lane':
                    yy=fit+yy
                    if predictor or r['estimator']=='partial':yy=yy-(yy@q)@q.T
                if r['permutation_statistic']=='t':
                    yy=yy-(yy@q)@q.T
                    fixed=ey if predictor else ex
                yy-=yy.mean(axis=1,keepdims=True);xx=fixed-fixed.mean()
                null=(yy@xx)/np.sqrt(np.sum(yy*yy,axis=1)*np.sum(xx*xx))
                if r['permutation_statistic']=='t':null=null*np.sqrt(df/(1-null*null))
                k+=int(np.count_nonzero(abs(null)>=statistic-1e-12))
            p=(k+1)/(r['test_draws']+1)
        else:raise ValueError('test incompatible with association design')
    out={'estimate':effect,'n':n,'p_raw':p,'sample_ids':ids,'sample':audit,'df':df}
    if se is not None:out['se']=se
    if r['test'] in {'sign_flip','freedman_lane','residual_permutation'}:
        from .reference import binomial_interval
        out.update(exceedances=k,draws=r['test_draws'],monte_carlo_interval=binomial_interval(k,r['test_draws']))
    alpha=(1-r['ci_level'])/2
    if r['ci'] in {'student_t','yuen'}:
        if se is None or df is None:raise ValueError('t interval needs matched analytic uncertainty')
        margin=stats.t.ppf(1-alpha,df)*se;ci=[effect-margin,effect+margin]
    elif r['ci']=='fisher_z':
        if (r['rank'] and not r['approximate_rank_fisher']) or r['estimator']!='partial':raise ValueError('Fisher interval only for full Pearson partial r')
        zse=1/math.sqrt(df-1);ci=np.tanh(np.arctanh(effect)+np.array([-1,1])*stats.norm.ppf(1-alpha)*zse)
    elif r['ci']=='bca':
        if r['design']!='paired' or r['estimator']!='mean':raise ValueError('BCa adapter currently supports paired mean')
        result=stats.bootstrap((d,),np.mean,n_resamples=r['ci_draws'],rng=np.random.default_rng(r['ci_seed']),method='BCa',confidence_level=r['ci_level'],batch=1000)
        ci=list(result.confidence_interval)
    else:
        bootstrap=bootstrap_associations(frame,r) if r['design']=='association' else bootstrap_pairs(frame,r)
        ci=np.quantile(bootstrap,[alpha,1-alpha],method='linear')
    out.update(ci_lower=float(ci[0]),ci_upper=float(ci[1]))
    if not all(math.isfinite(out[k]) for k in ['estimate','p_raw','ci_lower','ci_upper']):raise ValueError('nonfinite reference result')
    if r['adjustment']=='none':out['p']=p
    elif r['adjustment']=='fixed_threshold':
        a=r['per_test_alpha']
        if a is None or not 0<a<=.05 or r['family']:raise ValueError('fixed threshold requires source alpha and no invented family')
        out['p']=min(1.,p*.05/a)
    else:
        from statsmodels.stats.multitest import multipletests
        family=[p]+[calculate(work,member,cache=cache)['p_raw'] for member in r['family']]
        if len(family)<2:raise ValueError('Holm requires explicit nonfocal test recipes')
        out['family_p']=family;out['p']=float(multipletests(family,method='holm')[1][0])
    if cache is not None:cache[key]=out
    return out


def check(work,rows,specs,record):
    """Record observed/reference/tolerance for every emitted numerical component."""

    # Specs already contain independently compiled recipes; generated plans only
    # supply their claimed sample identity for comparison, never reference inputs.
    plans=json.loads((Path(work)/'out/analysis_plan.json').read_text())['specs'];plans={p['spec_id']:p for p in plans}
    wanted={s['spec_id']:s for s in specs};problems=[];evidence=[];cache={}
    if len(rows)!=len(wanted) or {r['_spec_id'] for r in rows}!=set(wanted):problems.append('independent verification needs exact specification coverage')
    for row in rows:
        sid=row['_spec_id'];s=wanted.get(sid);checks=[]
        if not s:continue
        r=s['independent_recipe']
        def compare(field,actual,expected,*, atol=1e-9,rtol=1e-7):
            try:ok=math.isfinite(float(actual)) and math.isclose(float(actual),float(expected),rel_tol=rtol,abs_tol=atol)
            except (ValueError,TypeError):ok=False
            checks.append({'field':field,'observed':actual,'reference':expected,'absolute_tolerance':atol,'relative_tolerance':rtol,'status':'verified' if ok else 'failed'})
            if not ok:problems.append(f'{sid}: independent {field} differs (reference values withheld from generator)')
        try:
            if not row.get('_converged'):raise ValueError('specification failed to converge')
            target=calculate(work,r,cache=cache)
            plan=plans[sid]
            if s.get('levels') is not None and plan.get('implemented_levels')!=s['levels']:
                problems.append(f'{sid}: declared implemented levels differ from screened grid')
            sample_ok=plan.get('included_ids') is not None and set(plan['included_ids'])==set(target['sample_ids']) if r['id_column'] else plan.get('included_ids') is None
            checks.append({'field':'sample','status':'verified' if sample_ok else 'failed','reference':target['sample']})
            if not sample_ok:problems.append(f'{sid}: sample identities differ from independently applied selection')
            for field in ['estimate','n','p_raw','p','ci_lower','ci_upper']:
                compare(field,row.get(field),target[field],atol=0 if field=='n' else 1e-300 if field in {'p','p_raw'} else 1e-9,rtol=0 if field=='n' else 1e-7)
            if row.get('se') not in (None,''):
                if 'se' not in target:
                    checks.append({'field':'se','status':'failed','observed':row['se'],'reason':'No standard-error estimator is specified by the screened method.'})
                    problems.append(f'{sid}: screened method specifies no SE; omit the extra SE while retaining its required estimate, interval and p-value')
                else:compare('se',row['se'],target['se'])
            expected_ci={'student_t':{'student_t'},'yuen':{'student_t','paired_yuen'},'fisher_z':{'fisher_z'},'bca':{'bca_bootstrap'},'percentile':{'percentile_bootstrap','case_bootstrap_percentile'}}[r['ci']]
            if row.get('ci_method') not in expected_ci:problems.append(f'{sid}: interval label differs from screened method')
            compare('ci_level',row.get('ci_level'),r['ci_level'])
            if r['test'] in {'sign_flip','freedman_lane','residual_permutation'}:
                compare('draws',row.get('draws'),target['draws'],atol=0,rtol=0)
                compare('exceedances',row.get('exceedances'),target['exceedances'],atol=0,rtol=0)
            expected_method={'none':'none','holm':'holm','fixed_threshold':'fixed_threshold'}[r['adjustment']]
            if row.get('p_adjustment')!=expected_method:problems.append(f'{sid}: adjustment must be {expected_method}, as independently bound to screened methods')
            if r['adjustment']=='fixed_threshold':
                if json.loads(row.get('p_family') or '[]'):problems.append(f'{sid}: fixed source threshold must not invent nonfocal family p-values')
                compare('per_test_alpha',row.get('per_test_alpha'),r['per_test_alpha'])
            elif r['adjustment']=='holm':
                bindings=[{k:m.get(k) for k in ('file','x','y','alternative')} for m in r['family']]
                claimed=plan.get('nonfocal_family_bindings')
                if claimed is None or sorted(claimed,key=lambda v:json.dumps(v,sort_keys=True))!=sorted(bindings,key=lambda v:json.dumps(v,sort_keys=True)):
                    problems.append(f'{sid}: plan must identify screened nonfocal_family_bindings with file, x, y, alternative')
                family=json.loads(row.get('p_family') or '[]');index=int(float(row.get('p_index') or 0))
                other=[v for i,v in enumerate(family) if i!=index]
                want=target['family_p'][1:]
                if len(other)!=len(want):problems.append(f'{sid}: family membership count differs')
                for i,(a,b) in enumerate(zip(sorted(other),sorted(want))):compare(f'nonfocal_family_p_{i+1}',a,b,atol=1e-300)
            evidence.append({'spec_id':sid,'status':'verified' if all(c['status']=='verified' for c in checks) and not any(p.startswith(sid+':') for p in problems) else 'failed','checks':checks,'recipe':r,'sample':target['sample']})
        except (ValueError,TypeError,KeyError,ArithmeticError,np.linalg.LinAlgError) as exc:
            problems.append(f'{sid}: closed method verification failed: {exc}');evidence.append({'spec_id':sid,'status':'failed','checks':checks,'error':str(exc)})
    verified=sum(e['status']=='verified' for e in evidence)
    return {'status':'verified' if not problems and verified==len(wanted) and verified else 'invalid','checked':verified,'total':len(wanted),
        'problems':problems,'unsupported':[],'evidence':evidence,'version':VERSION,'recipe_input_sha256':record['input_sha256'],
        'scope':'All emitted estimates, sample identities, analytic/seeded inference, intervals and multiplicity; independently source-translated closed methods. Statistical assumptions remain subject to scientific review.'}

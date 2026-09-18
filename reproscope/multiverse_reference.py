"""Reference calculations for explicitly declared location sensitivity estimators.

This verifier reads the deposited data and closed method fields. It never imports
or executes the generated estimator implementation to obtain its reference values.
"""
import math
import numpy as np
from scipy import stats
from .reference import read_data, numeric_sample


def samples(work, plan):
    _,frame=read_data(work,plan)
    if plan.get('included_ids') is not None:
        ids=plan.get('id_column')
        if not ids or frame[ids].duplicated().any():raise ValueError('explicit sample needs unique IDs')
        if not set(plan['included_ids'])<=set(frame[ids]):raise ValueError('unknown sample IDs')
        frame=frame[frame[ids].isin(plan['included_ids'])]
    frame=numeric_sample(frame,plan)
    if plan['family']=='independent_t':
        a,b=plan['group_values'];x=frame.loc[frame[plan['group_column']]==a,plan['x']].to_numpy(float);y=frame.loc[frame[plan['group_column']]==b,plan['x']].to_numpy(float)
    elif plan['family']=='paired_t':x=frame[plan['x']].to_numpy(float);y=frame[plan['y']].to_numpy(float)
    else:raise ValueError('location sensitivity requires paired or independent groups')
    transform=plan.get('transform','identity')
    if transform=='log':
        if np.any(x<=0) or np.any(y<=0):raise ValueError('log transform requires positive observations')
        x,y=np.log(x),np.log(y)
    elif transform!='identity':raise ValueError('unsupported transform')
    if not (np.isfinite(x).all() and np.isfinite(y).all()):raise ValueError('nonfinite location inputs')
    rule=plan.get('outlier_rule','none')
    threshold=plan.get('outlier_threshold')
    threshold=float(threshold) if threshold is not None else None
    def retain(v):
        if rule=='none':return v
        if threshold is None or not 0<float(threshold):raise ValueError('outlier threshold must be explicit and positive')
        if rule=='sd':lo,hi=v.mean()-threshold*v.std(ddof=1),v.mean()+threshold*v.std(ddof=1)
        elif rule=='iqr':
            q1,q3=np.quantile(v,[.25,.75]);lo,hi=q1-threshold*(q3-q1),q3+threshold*(q3-q1)
        elif rule=='mad':
            centre=np.median(v);scale=1.4826*np.median(np.abs(v-centre));lo,hi=centre-threshold*scale,centre+threshold*scale
        else:raise ValueError('unsupported outlier rule')
        return v[(v>=lo)&(v<=hi)]
    if plan['family']=='paired_t':x=retain(x-y);y=None
    else:x,y=retain(x),retain(y)
    if len(x)<3 or (y is not None and len(y)<3):raise ValueError('insufficient retained observations')
    return x,y


def calculate(work,plan):
    x,y=samples(work,plan)
    trim=float(plan.get('trim_fraction',0))
    if not 0<=trim<.5:raise ValueError('invalid trim fraction')
    def location(v,axis=-1):return stats.trim_mean(v,trim,axis=axis)
    def variance(v):
        n=len(v);g=int(n*trim);h=n-2*g
        if h<2:raise ValueError('insufficient effective trimmed sample')
        w=np.sort(v).copy()
        if g:w[:g]=w[g];w[n-g:]=w[n-g-1]
        return float(w.var(ddof=1)*(n-1)/(h*(h-1))),h
    theta=float(location(x)-(location(y) if y is not None else 0))
    vx,hx=variance(x)
    if y is None:se=math.sqrt(vx);df=hx-1;n=len(x)
    else:
        vy,hy=variance(y);n=len(x)+len(y)
        if plan.get('equal_var',False):
            pooled=((hx-1)*vx*hx+(hy-1)*vy*hy)/(hx+hy-2)
            se=math.sqrt(pooled*(1/hx+1/hy));df=hx+hy-2
        else:se=math.sqrt(vx+vy);df=(vx+vy)**2/(vx*vx/(hx-1)+vy*vy/(hy-1))
    t=theta/se
    alt=plan.get('alternative','two-sided')
    if alt not in {'two-sided','greater','less'}:raise ValueError('invalid alternative')
    p=float(2*stats.t.sf(abs(t),df) if alt=='two-sided' else stats.t.sf(t,df) if alt=='greater' else stats.t.cdf(t,df))
    result={'n':n,'mean_difference':theta,'log_ratio':theta,'t':t,'p_raw':p,'se_mean_difference':se,'df':df}
    if y is None:result['dz']=theta/x.std(ddof=1)
    else:result['d']=theta/math.sqrt(((len(x)-1)*x.var(ddof=1)+(len(y)-1)*y.var(ddof=1))/(len(x)+len(y)-2))
    return result

import shutil
import numpy as np
import pandas as pd
import pytest
from reproscope import scoped_multiverse as sm


def fixture(tmp_path):
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir()
    rng=np.random.default_rng(16);n=12
    frame=pd.DataFrame({'id':range(n),'a':rng.lognormal(3,.7,n),'b':rng.lognormal(2.8,.7,n),'c':rng.normal(10,3,n),'d':rng.normal(9,3,n),'e':rng.normal(5,1,n),'f':rng.normal(4.8,1,n)})
    frame.to_csv(tmp_path/'data/test.csv',index=False)
    plans=[dict(analysis_id=f'a{i}',family='paired_t',file='data/test.csv',x=x,y=y,id_column='id',included_ids=None,transformations=[],missingness='complete_cases',numeric_parsing='strict_float') for i,(x,y) in enumerate([('a','b'),('c','d'),('e','f')])]
    return plans


def test_five_dimensions_have_real_effects_and_separate_scopes(tmp_path):
    plans=fixture(tmp_path)
    rows,bases=sm.engine(tmp_path,plans,draws=499)
    assert len(rows)==30+4*12
    full=[r for r in rows if r['spec']['sample']=='full']
    active={k:v for k,v in sm.dimension_activity(full).items() if k!='sample'}
    assert len(active)==5 and all(v['active'] for v in active.values())
    assert len([r for r in rows if r['scope']=='primary'])==9
    assert len([r for r in rows if r['scope']=='alternative_estimand'])==21
    assert len([r for r in rows if r['scope']=='influence_diagnostic'])==4*12
    assert not any(r['spec']['location']=='trim20' and r['spec']['inference']=='paired_t' for r in rows)
    assert not any(r['spec']['interval']=='bca' and r['spec']['inference']=='paired_t' for r in rows)
    assert all(r['ci_lower']<=r['ci_upper'] for r in rows)
    frame=pd.read_csv(tmp_path/'data/test.csv');frame.loc[0,'a']=0;frame.to_csv(tmp_path/'data/test.csv',index=False)
    with pytest.raises(ValueError,match='strictly positive'):sm.engine(tmp_path,plans,draws=49)


@pytest.mark.skipif(shutil.which('Rscript') is None,reason='independent base-R reference unavailable')
def test_original_data_recomputed_independently_in_r(tmp_path):
    plans=fixture(tmp_path)
    rows,bases=sm.engine(tmp_path,plans,draws=199)
    result=sm.verify_r(tmp_path,plans,rows,bases)
    assert result['status']=='verified',result
    assert result['isolation']['enforced']
    rows[0]['p']=.999
    assert sm.verify_r(tmp_path,plans,rows,bases)['status']=='invalid'


def test_bca_matches_scipy_for_a_skewed_mean():
    from scipy import stats
    data=np.random.default_rng(91).lognormal(size=30)
    oracle=stats.bootstrap((data,),np.mean,n_resamples=1999,method='BCa',rng=np.random.default_rng(18))
    interval,_=sm.bca_interval(data,oracle.bootstrap_distribution,float(data.mean()),'mean')
    assert np.allclose(interval,oracle.confidence_interval,rtol=1e-10,atol=1e-12)
    with pytest.raises(ValueError,match='degenerate'):
        sm.bca_interval(np.ones(12),np.ones(199),1.,'mean')

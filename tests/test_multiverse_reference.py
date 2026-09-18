import numpy as np
import pandas as pd
import pytest
from scipy import stats
from reproscope.multiverse_reference import calculate

@pytest.mark.parametrize('trim',[0,.1,.2])
@pytest.mark.parametrize('pooled',[True,False])
def test_independent_location_reference_matches_scipy_yuen(tmp_path,trim,pooled):
    (tmp_path/'data').mkdir()
    rng=np.random.default_rng(718)
    x=rng.normal(2,3,31);y=rng.normal(0,1,24);x[-1]=45
    pd.DataFrame({'value':np.r_[x,y],'group':['a']*len(x)+['b']*len(y)}).to_csv(tmp_path/'data/input.csv',index=False)
    p=dict(file='data/input.csv',family='independent_t',x='value',group_column='group',group_values=['a','b'],trim_fraction=trim,equal_var=pooled)
    result=calculate(tmp_path,p);expected=stats.ttest_ind(x,y,trim=trim,equal_var=pooled)
    assert result['t']==pytest.approx(expected.statistic)
    assert result['p_raw']==pytest.approx(expected.pvalue)
    assert result['df']==pytest.approx(expected.df)
    assert result['n']==55


def test_paired_reference_preserves_difference_and_rejects_invalid_log(tmp_path):
    (tmp_path/'data').mkdir()
    x=np.array([1.,2.,3.,4.,5.]);y=np.array([0.,1.,1.,2.,2.])
    pd.DataFrame({'x':x,'y':y}).to_csv(tmp_path/'data/input.csv',index=False)
    p=dict(file='data/input.csv',family='paired_t',x='x',y='y')
    result=calculate(tmp_path,p)
    assert result['t']==pytest.approx(stats.ttest_rel(x,y).statistic)
    with pytest.raises(ValueError,match='positive'):calculate(tmp_path,{**p,'transform':'log'})


def test_resampling_uses_declared_transformed_retained_sample(tmp_path):
    from reproscope.reference import resampling_reference
    from reproscope.multiverse_reference import samples
    import itertools
    (tmp_path/'data').mkdir()
    pd.DataFrame({'x':[2.,3.,4.,5.,60.], 'y':[1.,2.,2.,3.,1.]}).to_csv(tmp_path/'data/input.csv',index=False)
    p=dict(file='data/input.csv',family='paired_t',x='x',y='y',sensitivity_protocol='location-1',transform='log',outlier_rule='iqr',outlier_threshold=1.5,trim_fraction=0,algorithm='sign_flip',test_statistic='mean_difference',alternative='two-sided',resampling_unit='paired_difference')
    delta,_=samples(tmp_path,p)
    values=np.asarray(list(itertools.product((-1,1),repeat=len(delta))))*delta
    expected=np.mean(abs(values.mean(axis=1))>=abs(delta.mean())-1e-12)
    assert resampling_reference(tmp_path,p)['p_raw']==pytest.approx(expected)
    with pytest.raises(ValueError,match='trimmed resampling reference is unsupported'):
        resampling_reference(tmp_path,{**p,'trim_fraction':.2})


def test_screened_two_sided_spelling_maps_to_the_same_reference_test(tmp_path):
    import json
    from reproscope.reference import from_plan,check
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir()
    pd.DataFrame({'x':[2,4,6,8],'y':[1,2,4,5]}).to_csv(tmp_path/'data/input.csv',index=False)
    plan=dict(spec_id='s',implemented_levels={'tail':'two_sided'},file='data/input.csv',family='paired_t',x='x',y='y',alternative='two-sided')
    result=from_plan(tmp_path,plan)
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps({'specs':[plan]}))
    row=dict(_spec_id='s',_converged=True,effect_metric='mean_difference',_estimate=result['mean_difference'],_n=4,inference_method='analytic',p_raw=result['p_raw'])
    specs=[dict(spec_id='s',levels=plan['implemented_levels'],reference_settings={'alternative':'two_sided'})]
    assert check(tmp_path,[row],specs)['status']=='verified'
    adjusted={**row,'p_adjustment':'holm','p_family':json.dumps([result['p_raw'],.7]),'p_index':0}
    receipt=check(tmp_path,[adjusted],specs)
    assert receipt['status']=='partial' and receipt['checked']==1
    assert any('family membership' in item['reason'] for item in receipt['unsupported'])


def test_outlier_plan_retains_starting_ids_and_recomputes_selection(tmp_path):
    import json
    from reproscope.reference import from_plan,check
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir()
    ids=list(range(8))
    pd.DataFrame({'id':ids,'x':[11,12,13,14,15,16,17,80],'y':[10]*8}).to_csv(tmp_path/'data/input.csv',index=False)
    plan=dict(spec_id='s',implemented_levels={'outliers':'iqr'},file='data/input.csv',family='paired_t',x='x',y='y',
        sensitivity_protocol='location-1',id_column='id',included_ids=ids,outlier_rule='iqr',outlier_threshold=1.5)
    specs=[dict(spec_id='s',levels=plan['implemented_levels'],reference_settings={'included_ids':ids})]
    def run(p):
        result=from_plan(tmp_path,p)
        (tmp_path/'out/analysis_plan.json').write_text(json.dumps({'specs':[p]}))
        row=dict(_spec_id='s',_converged=True,effect_metric='mean_difference',_estimate=result['mean_difference'],_n=result['n'],inference_method='analytic',p_raw=result['p_raw'])
        return result,check(tmp_path,[row],specs)
    result,receipt=run(plan)
    assert result['n']==7 and receipt['status']=='verified'
    frame=pd.read_csv(tmp_path/'data/input.csv');frame.loc[7,'x']=18;frame.to_csv(tmp_path/'data/input.csv',index=False)
    result,receipt=run(plan)
    assert result['n']==8 and receipt['status']=='verified'
    # Even numerically self-consistent results on a frozen post-filter sample
    # cannot satisfy a contract whose starting sample includes that participant.
    _,receipt=run({**plan,'included_ids':ids[:-1]})
    assert any('included_ids' in p for p in receipt['problems'])

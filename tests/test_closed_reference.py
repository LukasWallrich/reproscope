"""External numerical anchors and deliberately wrong statistical implementations."""
import json,shutil
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from scipy import stats
from reproscope import closed_reference as ref
from reproscope.verification_recipe import Recipe,compile_book
from reproscope.statistical import validate_result

FIXTURE=Path(__file__).parent/'fixtures/multiverse_verification'

@pytest.fixture
def work(tmp_path):
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir()
    shutil.copy2(FIXTURE/'study.csv',tmp_path/'data/study.csv')
    return tmp_path

def recipe(**kwargs):
    return Recipe(file='data/study.csv',x='y',y='x',id_column='id',design='association',estimator='partial',test='t',ci='fisher_z',polynomial_column='z',**kwargs).model_dump()

def test_external_r_anchors(work):
    anchors=json.loads((FIXTURE/'reference.json').read_text())
    r=recipe();v=ref.calculate(work,r)
    for k,x in anchors['partial'].items():assert v[k]==pytest.approx(x,rel=1e-12)
    r.update(estimator='semipartial',ci='percentile',ci_draws=1000)
    assert ref.calculate(work,r)['estimate']==pytest.approx(anchors['semipartial']['estimate'],rel=1e-12)
    r.update(design='paired',x='a',y='b',estimator='yuen',test='yuen',ci='yuen',polynomial_column=None)
    v=ref.calculate(work,r)
    for k,x in anchors['yuen'].items():assert v[k]==pytest.approx(x,rel=1e-12)


def check_row(work,r,row):
    pdframe=pd.read_csv(work/'data/study.csv')
    (work/'out/analysis_plan.json').write_text(json.dumps({'specs':[{'spec_id':'s1','included_ids':pdframe.id.tolist()}]}))
    result=ref.check(work,[{'_spec_id':'s1','_converged':True,'p_adjustment':'none','ci_method':'fisher_z','ci_level':.95,**row}],
        [{'spec_id':'s1','independent_recipe':r}],{'book':{},'input_sha256':'synthetic'})
    return result


def test_wrong_partial_and_quadratic_methods_are_detected(work):
    r=recipe();correct=ref.calculate(work,r)
    assert check_row(work,r,correct)['status']=='verified'
    semi=ref.calculate(work,{**r,'estimator':'semipartial','ci':'percentile','ci_draws':1000})
    assert check_row(work,r,semi)['status']=='invalid'
    quadratic=ref.calculate(work,{**r,'polynomial_degree':2})
    assert check_row(work,r,quadratic)['status']=='invalid'


def test_bca_cannot_be_replaced_by_percentile(work):
    r={**recipe(),'design':'paired','x':'a','y':'b','polynomial_column':None,'estimator':'mean','ci':'bca','ci_draws':2000}
    expected=ref.calculate(work,r);d=pd.read_csv(work/'data/study.csv').eval('a-b').to_numpy()
    wrong=stats.bootstrap((d,),np.mean,method='percentile',n_resamples=2000,rng=np.random.default_rng(r['ci_seed'])).confidence_interval
    got=check_row(work,r,{**expected,'ci_method':'bca_bootstrap','ci_lower':wrong.low,'ci_upper':wrong.high})
    assert any('ci_' in p for p in got['problems'])


def test_wrong_null_permutation_fails(work):
    r={**recipe(),'test':'freedman_lane','test_draws':2000};expected=ref.calculate(work,r)
    frame=pd.read_csv(work/'data/study.csv');y,x,z,q,ey,ex=ref.association(frame,r)[3]
    rng=np.random.default_rng(r['test_seed']);k=sum(abs(np.corrcoef(rng.permutation(y),ex)[0,1])>=abs(expected['estimate']) for _ in range(r['test_draws']))
    wrong={**expected,'exceedances':int(k),'p_raw':(k+1)/(r['test_draws']+1),'p':(k+1)/(r['test_draws']+1)}
    assert check_row(work,r,expected)['status']=='verified'
    assert check_row(work,r,wrong)['status']=='invalid'


def test_sample_selection_is_not_trusted_from_executor(work):
    r=recipe();row=ref.calculate(work,r);row['n']-=1
    result=check_row(work,r,row)
    assert any('independent n differs' in p for p in result['problems'])
    plan=work/'out/analysis_plan.json';plan.write_text(json.dumps({'specs':[{'spec_id':'s1','included_ids':[999]}]}))
    result=ref.check(work,[{'_spec_id':'s1','_converged':True,**row}], [{'spec_id':'s1','independent_recipe':r}],{'book':{},'input_sha256':'synthetic'})
    assert any('sample identities' in p for p in result['problems'])


def test_bootstrap_reranks_and_refits_each_sample(work):
    r={**recipe(),'rank':True,'polynomial_degree':2,'ci':'percentile','ci_draws':1000}
    frame=pd.read_csv(work/'data/study.csv');actual=ref.bootstrap_associations(frame,r)
    rng=np.random.default_rng(r['ci_seed'])
    expected=[ref.association(frame.iloc[rng.integers(0,len(frame),len(frame))],r)[0] for _ in range(1000)]
    np.testing.assert_allclose(actual,expected,rtol=1e-10,atol=1e-12)


def test_fixed_threshold_does_not_invent_a_family():
    row=dict(_converged=True,estimate=.1,n=40,p_raw=.001,p=.025,p_threshold=.05,inference_method='analytic',effect_metric='r',p_adjustment='fixed_threshold',per_test_alpha=.002)
    assert not validate_result(row,strict=True)
    assert validate_result({**row,'p_family':json.dumps([.001]*25)},strict=True)


def test_unknown_or_conflicting_recipe_fields_fail_closed():
    r=recipe();grid={'factors':[{'name':'a','levels':[{'value':'x'}]},{'name':'b','levels':[{'value':'y'}]}]}
    book={'base':r,'factors':{'a':{'x':{'rank':True}},'b':{'y':{'rank':False}}},'evidence':[],'limitations':[]}
    with pytest.raises(ValueError,match='conflicting'):compile_book(book,grid)
    book['factors']['a']['x']={'pretend_supported':True};book['factors']['b']['y']={}
    with pytest.raises(ValueError):compile_book(book,grid)


def test_marginal_yuen_is_not_trimmed_paired_differences(work):
    r={**recipe(),'design':'paired','x':'a','y':'b','polynomial_column':None,'estimator':'yuen','test':'yuen','ci':'yuen'}
    frame=pd.read_csv(work/'data/study.csv')
    marginal=ref.calculate(work,r)['estimate']
    difference_trim=stats.trim_mean(frame.a-frame.b,.2)
    assert abs(marginal-difference_trim)>.01


def test_signed_rank_effect_preserves_ties_zeros_and_orientation():
    d=np.array([0.,1.,-1.,2.,2.,-4.])
    # Nonzero absolute ranks 1.5,1.5,3.5,3.5,5: W+=8.5, W-=6.5.
    assert ref.rank_biserial(d)==pytest.approx(2/15)
    assert ref.rank_biserial(-d)==pytest.approx(-2/15)


def test_tiny_analytic_probability_cannot_silently_become_zero(work):
    frame=pd.read_csv(work/'data/study.csv');frame['y']=2*frame.x+np.random.default_rng(7).normal(0,.001,len(frame))
    frame.to_csv(work/'data/study.csv',index=False)
    r=recipe();correct=ref.calculate(work,r)
    assert 0<correct['p_raw']<1e-20
    assert check_row(work,r,correct)['status']=='verified'
    wrong={**correct,'p_raw':0.,'p':0.}
    assert check_row(work,r,wrong)['status']=='invalid'


def test_signed_rank_28_pairs_uses_supported_exact_distribution(work):
    # R stats::wilcox.test(d, exact=TRUE), independently run 2026-09-15.
    d=np.arange(1,29,dtype=float);d[:10]*=-1
    pd.DataFrame({'id':range(28),'a':d,'b':np.zeros(28)}).to_csv(work/'data/study.csv',index=False)
    r={**recipe(),'design':'paired','x':'a','y':'b','polynomial_column':None,'estimator':'rank_biserial','test':'wilcoxon','ci':'percentile','ci_draws':1000}
    value=ref.calculate(work,r)['p_raw']
    assert value==pytest.approx(.00038140267133712823,rel=1e-12)
    assert not np.isclose(value,stats.wilcoxon(d,method='approx',correction=True).pvalue,rtol=1e-4)


def test_deposited_total_does_not_require_complete_raw_items(work):
    frame=pd.read_csv(work/'data/study.csv');frame['item']=np.nan;frame.to_csv(work/'data/study.csv',index=False)
    r={**recipe(),'x_items':['item'],'y_items':['item']}
    assert ref.calculate(work,r)['n']==len(frame)


def test_trimmed_difference_matches_independent_r_winsorised_reference(work):
    # R WRS2::winvar on paired differences, h=n-2*floor(.2*n), df=h-1.
    r={**recipe(),'design':'paired','x':'a','y':'b','polynomial_column':None,
       'estimator':'trimmed_difference','test':'yuen','ci':'yuen'}
    actual=ref.calculate(work,r)
    for key,value in {'estimate':.28141493985957805,'se':.37013573280962175,
                      'p_raw':.45447897564505602,'df':24}.items():
        assert actual[key]==pytest.approx(value,rel=1e-12)
    assert check_row(work,r,{**actual,'ci_method':'student_t'})['status']=='verified'
    wrong=ref.calculate(work,{**r,'estimator':'yuen'})
    assert check_row(work,r,{**wrong,'ci_method':'student_t'})['status']=='invalid'


def test_log_scale_precedes_difference_outlier_selection(work):
    # Equal raw differences have markedly different ratios: the final row is
    # an outlier only on the selected logarithmic scale.
    b=np.array([10,12,14,16,18,20,22,24,26,.01],float)
    a=b+1
    pd.DataFrame({'id':range(10),'a':a,'b':b}).to_csv(work/'data/study.csv',index=False)
    r={**recipe(),'design':'paired','x':'a','y':'b','polynomial_column':None,
       'estimator':'mean','test':'t','ci':'student_t','outliers':'iqr_difference','transform':'log'}
    actual=ref.calculate(work,r)
    assert actual['sample_ids']==list(range(9))
    assert actual['estimate']==pytest.approx(np.log(a[:9]/b[:9]).mean(),rel=1e-12)
    assert len(ref.sample(work,{**r,'transform':'identity'})[0])==10
    frame=pd.read_csv(work/'data/study.csv');frame.loc[0,'b']=0;frame.to_csv(work/'data/study.csv',index=False)
    with pytest.raises(ValueError,match='strictly positive'):ref.calculate(work,r)


def test_generation_uses_source_recipe_for_both_numerical_checks(work,monkeypatch):
    from reproscope.stage3 import multiverse as mv
    from reproscope import verification_recipe,reference,multiverse_contract
    r=recipe();grid={'reporting_contracts':{'s1':{}},'factors':[{'name':'method','levels':[{'value':'a'}]}]}
    book={'base':r,'factors':{'method':{'a':{}}},'evidence':[],'limitations':[]}
    record={'book':book,'input_sha256':'independent'}
    specs=[{'spec_id':'s1','levels':{'method':'a'}}]
    (work/'out/specs.csv').write_text('placeholder')
    monkeypatch.setattr(verification_recipe,'prepare',lambda *a:record)
    monkeypatch.setattr(verification_recipe,'compile_book',lambda *a:{'s1':r})
    monkeypatch.setattr(mv,'reference_specifications',lambda *a:specs)
    monkeypatch.setattr(mv,'read_specs',lambda *a:[{'_spec_id':'s1','_converged':True}])
    monkeypatch.setattr(mv,'validate_result',lambda *a,**k:[])
    monkeypatch.setattr(multiverse_contract,'checks',lambda *a:[])
    seen=[]
    def original(folder,rows,received):
        assert received[0]['independent_recipe']==r
        assert received[0]['recipe_record']==record
        seen.append('original');return {'problems':[]}
    def perturbed(folder,got,received):
        assert received[0]['independent_recipe']==r
        seen.append('perturbed');return []
    monkeypatch.setattr(reference,'check',original)
    monkeypatch.setattr(mv,'generation_perturbation_checks',perturbed)
    assert mv.generation_checks(work,grid)==[]
    assert seen==['original','perturbed']


def test_natural_cubic_nuisance_matches_r_splines(work):
    # R splines::ns(z, knots=median(z), Boundary.knots=quantile(z,c(.1,.9))).
    r={**recipe(),'spline_probabilities':[.1,.5,.9]}
    value=ref.calculate(work,r)
    assert value['estimate']==pytest.approx(.36973805688575184,rel=1e-12)
    assert value['p_raw']==pytest.approx(.020522281712256514,rel=1e-12)
    assert value['df']==37


def test_spline_bootstrap_keeps_full_sample_knots_and_ranks_only_outcomes(work):
    r={**recipe(),'spline_probabilities':[.1,.5,.9],'rank':True,'ci':'percentile','ci_draws':1000}
    frame=pd.read_csv(work/'data/study.csv')
    actual=ref.bootstrap_associations(frame,r)
    r['_spline_knots']=np.quantile(frame.z,r['spline_probabilities'])
    rng=np.random.default_rng(r['ci_seed'])
    expected=[ref.association(frame.iloc[rng.integers(0,len(frame),len(frame))],r)[0] for _ in range(1000)]
    np.testing.assert_allclose(actual,expected,rtol=1e-10,atol=1e-12)
    draw=frame.iloc[np.random.default_rng(11).integers(0,len(frame),len(frame))]
    fixed=ref.association(draw,r)[0];varying=ref.association(draw,{k:v for k,v in r.items() if k!='_spline_knots'})[0]
    assert abs(fixed-varying)>1e-5


@pytest.mark.parametrize('estimator',['mean','trimmed_difference','yuen','rank_biserial'])
def test_batched_pair_bootstrap_matches_separate_resampling(work,estimator):
    r={**recipe(),'design':'paired','x':'a','y':'b','estimator':estimator,'ci_draws':1000}
    frame=pd.read_csv(work/'data/study.csv');rng=np.random.default_rng(r['ci_seed'])
    expected=[ref.paired(frame.iloc[rng.integers(0,len(frame),len(frame))],r)[0] for _ in range(1000)]
    np.testing.assert_allclose(ref.bootstrap_pairs(frame,r),expected,rtol=1e-12,atol=1e-12)


def test_freedman_lane_preserves_the_screened_permuted_variable(work):
    r={**recipe(),'test':'freedman_lane','test_draws':1000,'permutation_target':'predictor'}
    got=ref.calculate(work,r)
    frame=pd.read_csv(work/'data/study.csv');y,x,z,q,ey,ex=ref.association(frame,r)[3]
    rng=np.random.default_rng(r['test_seed']);count=0
    for _ in range(1000):
        xp=x-ex+rng.permutation(ex)
        xp=xp-z@np.linalg.lstsq(z,xp,rcond=None)[0]
        count+=abs(np.corrcoef(ey,xp)[0,1])>=abs(got['estimate'])-1e-12
    assert got['exceedances']==count
    assert check_row(work,r,got)['status']=='verified'
    assert check_row(work,r,ref.calculate(work,{**r,'permutation_target':'outcome'}))['status']=='invalid'


def test_exact_signed_rank_domain_is_explicit(work):
    frame=pd.read_csv(work/'data/study.csv');frame.loc[0,'a']=frame.loc[0,'b'];frame.to_csv(work/'data/study.csv',index=False)
    r={**recipe(),'design':'paired','x':'a','y':'b','polynomial_column':None,'estimator':'rank_biserial','test':'wilcoxon','ci':'percentile','wilcoxon_policy':'exact_no_ties'}
    with pytest.raises(ValueError,match='nonzero untied'):ref.calculate(work,r)


def test_studentized_residual_trim_matches_statsmodels(work):
    import statsmodels.api as sm
    frame=pd.read_csv(work/'data/study.csv')
    r={**recipe(),'outliers':'studentized_residual_trim','outlier_fraction':.1,'rank':True,'ci':'percentile','ci_draws':1000}
    z=sm.add_constant(frame[['z']]);scores=[]
    for name in ['x','y']:
        scores.append(abs(sm.OLS(frame[name],z).fit().get_influence().resid_studentized_internal))
    removed=np.argsort(-np.maximum(*scores),kind='stable')[:int(np.ceil(.1*len(frame)))]
    expected=frame.drop(index=removed)
    retained,ids,audit=ref.sample(work,r)
    assert ids==expected.id.tolist()
    assert audit['outlier_exclusions']==len(removed)
    assert ref.calculate(work,r)['estimate']==pytest.approx(ref.association(expected,r)[0])


def test_residual_permutation_is_distinct_from_freedman_lane(work):
    r={**recipe(),'test':'residual_permutation','test_draws':1000,'permutation_target':'predictor'}
    frame=pd.read_csv(work/'data/study.csv');actual=ref.calculate(work,r)
    y,x,z,q,ey,ex=ref.association(frame,r)[3]
    rng=np.random.default_rng(r['test_seed'])
    count=sum(abs(np.corrcoef(ey,rng.permutation(ex))[0,1])>=abs(actual['estimate'])-1e-12 for _ in range(1000))
    assert actual['exceedances']==count
    assert actual['p']==(count+1)/1001
    # With finite draws both methods may give the same exceedance count.
    # Their null statistics must still follow different projection rules.
    rng=np.random.default_rng(r['test_seed']);null=[];direct=[]
    for _ in range(1000):
        perm=rng.permutation(ex);direct.append(np.corrcoef(ey,perm)[0,1])
        reconstructed=x-ex+perm
        null.append(np.corrcoef(ey,reconstructed-q@(q.T@reconstructed))[0,1])
    assert not np.allclose(null,direct)
    count=sum(abs(v)>=abs(actual['estimate'])-1e-12 for v in null)
    assert ref.calculate(work,{**r,'test':'freedman_lane'})['p']==(count+1)/1001


def test_rank_covariates_and_explicit_approximate_fisher(work):
    r={**recipe(),'polynomial_column':None,'covariates':['z'],'rank':True,'rank_covariates':True,'approximate_rank_fisher':True}
    frame=pd.read_csv(work/'data/study.csv');ranked=frame.copy()
    for name in ['x','y','z']:ranked[name]=stats.rankdata(ranked[name])
    expected=ref.association(ranked,{**r,'rank':False})
    got=ref.calculate(work,r)
    assert got['estimate']==pytest.approx(expected[0])
    assert got['ci_lower']==pytest.approx(np.tanh(np.arctanh(expected[0])-stats.norm.ppf(.975)/np.sqrt(expected[1]-1)))
    with pytest.raises(ValueError):Recipe.model_validate({**r,'approximate_rank_fisher':False})


def test_conditional_recipe_patches_are_scoped_and_conflicts_fail():
    r=recipe();grid={'factors':[{'name':'method','levels':[{'value':'full'},{'value':'semi'}]}]}
    book={'base':r,'factors':{'method':{'full':{},'semi':{'estimator':'semipartial'}}},
        'conditions':[{'when':{'method':['semi']},'patch':{'ci':'percentile'}}],'evidence':[],'limitations':[]}
    compiled=list(compile_book(book,grid).values())
    assert [x['ci'] for x in compiled]==['fisher_z','percentile']
    book['conditions'].append({'when':{'method':['semi']},'patch':{'ci':'fisher_z'}})
    with pytest.raises(ValueError,match='conflicting conditional'):compile_book(book,grid)


def test_residual_trim_retains_same_ids_under_duplicate_rows(work):
    import statsmodels.api as sm
    source=pd.read_csv(work/'data/study.csv');rng=np.random.default_rng(8)
    for _ in range(30):
        frame=source.iloc[rng.integers(0,len(source),len(source))].reset_index(drop=True)
        frame['id']=np.arange(len(frame));frame.to_csv(work/'data/study.csv',index=False)
        z=sm.add_constant(frame[['z']]);scores=[]
        for name in ['x','y']:
            scores.append(abs(sm.OLS(frame[name],z).fit().get_influence().resid_studentized_internal))
        removed=np.argsort(-np.round(np.maximum(*scores),12),kind='stable')[:int(np.ceil(.05*len(frame)))]
        r={**recipe(),'outliers':'studentized_residual_trim'}
        _,ids,_=ref.sample(work,r)
        assert ids==frame.drop(index=removed).id.tolist()


def test_freedman_lane_coefficient_t_for_semipartial(work):
    import statsmodels.api as sm
    r={**recipe(),'estimator':'semipartial','ci':'percentile','ci_draws':1000,'test':'freedman_lane','test_draws':1000,'permutation_statistic':'t'}
    frame=pd.read_csv(work/'data/study.csv');z=sm.add_constant(frame[['z']]);full=sm.add_constant(frame[['z','x']])
    reduced=sm.OLS(frame.y,z).fit();observed=sm.OLS(frame.y,full).fit().tvalues['x']
    rng=np.random.default_rng(r['test_seed']);count=0
    for _ in range(1000):
        null=sm.OLS(reduced.fittedvalues+rng.permutation(reduced.resid),full).fit().tvalues['x']
        count+=abs(null)>=abs(observed)-1e-12
    actual=ref.calculate(work,r)
    assert actual['p']==(count+1)/1001
    assert actual['estimate']==pytest.approx(ref.association(frame,r)[0])


def test_source_bindings_reject_symmetric_looking_axis_swap():
    from reproscope.verification_recipe import validate_source_bindings
    grid={'factors':[{'name':'method','field':'model','levels':[{'value':'original'}]}]}
    book={'base':recipe(),'factors':{'method':{'original':{}}},'evidence':[],'limitations':[]}
    bindings=[{'contract_field':'outcome','chosen':'y'}, {'contract_field':'predictors[0]','chosen':'x'}]
    assert validate_source_bindings(book,grid,bindings)
    book['base'].update(x='x',y='y')
    with pytest.raises(ValueError,match='bound outcome y'):validate_source_bindings(book,grid,bindings)


def test_extra_unspecified_se_has_actionable_feedback(work):
    r=recipe();correct=ref.calculate(work,r)
    assert check_row(work,r,correct)['status']=='verified'
    bad=check_row(work,r,{**correct,'se':.1})
    assert bad['status']=='invalid'
    assert any('specifies no SE; omit the extra SE' in e for e in bad['problems'])

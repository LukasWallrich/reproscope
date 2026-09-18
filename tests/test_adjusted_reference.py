import json
import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats
from reproscope.adjusted_reference import calculate,check
from reproscope.plan_protocol import AdjustedPlan


def plan(family='partial_correlation'):
    return dict(analysis_id='a',status='supported',family=family,file='data/d.csv',table=None,header=0,
        x='x',y='y' if family=='partial_correlation' else None,covariates=['z'] if family=='partial_correlation' else [],
        predictors=['y','z'] if family=='linear_regression' else [],coefficient='y' if family=='linear_regression' else None,
        coefficient_field='predictors[0]' if family=='linear_regression' else None,id_column='id',included_ids=None,
        missingness='complete_cases',numeric_parsing='strict_float',alternative='two-sided',transformations=[],
        intercept=True,covariance='classical',confidence_level=.95)


def data():
    rng=np.random.default_rng(718)
    z=rng.normal(size=100);x=3*z+rng.normal(size=100);y=4*z-.5*x+rng.normal(size=100)
    return pd.DataFrame(dict(id=range(100),x=x,y=y,z=z))


def test_partial_correlation_controls_confounder_and_uses_adjusted_df():
    d=data();p=plan();AdjustedPlan.model_validate(p);out=calculate(d,p)
    assert d.x.corr(d.y)>0 and out['r']<0
    fit=sm.OLS(d.x,sm.add_constant(d[['y','z']])).fit()
    assert out['df']==97
    assert out['t']==pytest.approx(fit.tvalues['y'])
    assert out['p_raw']==pytest.approx(fit.pvalues['y'])
    assert out['p_raw']!=pytest.approx(stats.pearsonr(sm.OLS(d.x,sm.add_constant(d.z)).fit().resid,
        sm.OLS(d.y,sm.add_constant(d.z)).fit().resid).pvalue,rel=1e-3,abs=0)


def test_ols_coefficient_and_model_statistics_match_separate_library():
    d=data();p=plan('linear_regression');AdjustedPlan.model_validate(p);out=calculate(d,p)
    fit=sm.OLS(d.x,sm.add_constant(d[['y','z']])).fit()
    for key,want in dict(coefficient=fit.params['y'],t=fit.tvalues['y'],se=fit.bse['y'],p_raw=fit.pvalues['y'],
                         r2=fit.rsquared,F=fit.fvalue,ci_lower=fit.conf_int().loc['y',0],ci_upper=fit.conf_int().loc['y',1]).items():
        assert out[key]==pytest.approx(want)
    assert out['beta']==pytest.approx(fit.params['y']*d.y.std()/d.x.std())
    p.update(coefficient=None,coefficient_field=None)
    assert calculate(d,p)['p_raw']==pytest.approx(fit.f_pvalue)


def test_adjusted_checker_rejects_wrong_covariates_and_sample(tmp_path):
    (tmp_path/'data').mkdir();d=data();d.to_csv(tmp_path/'data/d.csv',index=False)
    p=plan();out=calculate(d,p)
    analysis={'analysis_id':'a','design':{'family':'correlation'},'covariates':['z'],
        'variable_bindings':[{'contract_field':field,'chosen':col,'file':'data/d.csv','table':None}
         for field,col in [('outcome','x'),('predictors[0]','y'),('covariates[0]','z')]],
        'quantities':[{'claim_id':'r','quantity_kind':'r','quantity_role':'inferential'}]}
    rows=[{'analysis_id':'a','claim_id':'r','value':out['r'],'n':100}]
    assert check(tmp_path,p,analysis,rows,True)['status']=='verified'
    analysis['variable_bindings'][-1]['chosen']='unavailable'
    assert 'covariate set differs from intake' in check(tmp_path,p,analysis,rows,True)['problems']
    analysis['variable_bindings'][-1]['chosen']='z'
    p['included_ids']=list(range(99))
    assert 'declared sample differs from intake-authorised sample' in check(tmp_path,p,analysis,rows,True)['problems']


def test_adjusted_singular_design_is_not_silently_regularized():
    d=data();d['z2']=2*d.z;p=plan();p['covariates']=['z','z2']
    with pytest.raises(ValueError,match='rank-deficient'):calculate(d,p)


def test_model_only_plan_explains_missing_coefficient_declaration(tmp_path):
    (tmp_path/'data').mkdir();d=data();d.to_csv(tmp_path/'data/d.csv',index=False)
    p=plan('linear_regression');out=calculate(d,p)
    analysis={'analysis_id':'a','design':{'family':'other','contrast':'OLS coefficient for y'},
        'variable_bindings':[{'contract_field':field,'chosen':col,'file':'data/d.csv','table':None}
            for field,col in [('outcome','x'),('predictors[0]','y'),('predictors[1]','z')]],
        'quantities':[{'claim_id':'b','quantity_kind':'coefficient','quantity_role':'inferential'}]}
    rows=[{'analysis_id':'a','claim_id':'b','value':out['coefficient'],'n':100}]
    assert check(tmp_path,p,analysis,rows,True)['status']=='verified'
    analysis['coefficient_target']={'state':'resolved','binding_field':'predictors[1]','evidence_quote':'OLS coefficient for z'}
    assert any('requested source term' in e for e in check(tmp_path,p,analysis,rows,True)['problems'])
    analysis['coefficient_target']={'state':'resolved','binding_field':'predictors[0]','evidence_quote':'OLS coefficient for y'}
    assert check(tmp_path,p,analysis,rows,True)['status']=='verified'
    analysis.pop('coefficient_target')
    p.update(coefficient=None,coefficient_field=None)
    evidence=check(tmp_path,p,analysis,rows,True)
    assert evidence['status']=='invalid'
    assert any('coefficient and coefficient_field' in message for message in evidence['problems'])
    analysis['quantities']=[{'claim_id':'r2','quantity_kind':'other','quantity_kind_raw':'r2'}]
    rows=[{'analysis_id':'a','claim_id':'r2','value':out['r2']}]
    assert check(tmp_path,p,analysis,rows,True)['status']=='verified'


def test_partial_plan_reexecutes_with_changed_data_and_sample(tmp_path,monkeypatch):
    import sys,subprocess
    from reproscope.stage1 import replicas
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir();data().to_csv(tmp_path/'data/d.csv',index=False)
    p=plan();p['included_ids']=list(range(100))
    analysis={'analysis_id':'a','design':{'family':'correlation'},'covariates':['z'],
        'variable_bindings':[{'contract_field':field,'chosen':col,'file':'data/d.csv','table':None}
         for field,col in [('outcome','x'),('predictors[0]','y'),('covariates[0]','z')]],
        'quantities':[{'claim_id':'r','quantity_kind':'r','quantity_role':'inferential'}]}
    (tmp_path/'CONTRACT.json').write_text(json.dumps({'analyses':[analysis]}))
    script=tmp_path/'out/analysis.py'
    script.write_text('''import json
from pathlib import Path
import pandas as pd
import statsmodels.api as sm
d=pd.read_csv('data/d.csv').dropna(subset=['x','y','z'])
z=sm.add_constant(d.z)
r=sm.OLS(d.x,z).fit().resid.corr(sm.OLS(d.y,z).fit().resid)
p='''+repr(p)+'''
p['included_ids']=d.id.tolist()
Path('out/analysis_plan.json').write_text(json.dumps({'protocol_version':'direct-plan-3','analyses':[p]}))
Path('out/results.json').write_text(json.dumps({'results':[{'analysis_id':'a','claim_id':'r','value':r,'n':len(d)}]}))
''')
    subprocess.run([sys.executable,str(script)],cwd=tmp_path,check=True)
    monkeypatch.setattr(replicas,'prepare_env',lambda *a:{'interpreter':sys.executable,'env':{},'error':None,'log':'','installed':[],'env_dir':None})
    receipt=replicas.rerun_script(tmp_path,script,tmp_path.parent)
    assert receipt['execution_evidence']['analyses']['a']['status']=='verified'
    assert receipt['execution_evidence']['perturbation']['status']=='verified'


def test_adjusted_plan_feedback_excludes_irrelevant_union_branches():
    from reproscope.plan_protocol import validate_document
    import pytest
    with pytest.raises(ValueError) as error:
        validate_document({'protocol_version':'direct-plan-3','analyses':[{'analysis_id':'a','status':'supported','family':'partial_correlation'}]})
    assert 'analysis plan schema errors' in str(error.value)
    assert 'equal_var' not in str(error.value) and 'df_per_subject' not in str(error.value)
    assert 'covariates' in str(error.value)

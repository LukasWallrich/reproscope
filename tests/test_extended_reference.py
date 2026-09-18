import json
import numpy as np
import pandas as pd
import pytest
from reproscope import reference, extended_reference
from reproscope.plan_protocol import ExtendedPlanDocument


def scalar(aid,x,y):
    return dict(analysis_id=aid,status='supported',family='correlation',file='data/test.csv',table=None,header=0,x=x,y=y,id_column='id',included_ids=None,equal_var=False,alternative='two-sided',transformations=[],missingness='complete_cases',numeric_parsing='strict_float',group_column=None,group_values=None,contrast=f'{x} with {y}')


def test_named_family_checks_each_member_and_rejects_swapped_identity(tmp_path):
    (tmp_path/'data').mkdir()
    pd.DataFrame({'id':range(5),'x':[1,2,4,8,16],'y':[1,3,2,4,5],'z':[9,2,4,1,7]}).to_csv(tmp_path/'data/test.csv',index=False)
    plan=dict(analysis_id='a',status='supported',family='correlation_family',members=[scalar('m1','x','y'),scalar('m2','x','z')])
    ExtendedPlanDocument.model_validate({'protocol_version':'direct-plan-3','analyses':[plan]})
    expected=reference.from_plan(tmp_path,plan)
    assert expected['r'][0]!=expected['r'][1]
    a={'analysis_id':'a','design':{'family':'correlation'},'members':[dict(member_id=m['analysis_id'],**{k:m[k] for k in ('x','y','file','table','numeric_parsing')}) for m in plan['members']], 'quantities':[{'claim_id':'q','quantity_kind':'r','member_ids':['m1','m2'],'aggregation':'all'}]}
    rows=[{'analysis_id':'a','claim_id':'q','value':expected['r'],'member_ids':['m1','m2'],'n':5}]
    assert extended_reference.check(tmp_path,plan,a,rows,True)['status']=='verified'
    rows[0]['member_ids'].reverse()
    assert extended_reference.check(tmp_path,plan,a,rows,True)['status']=='invalid'


def test_likelihood_reference_requires_nesting_and_parameter_count_from_intake(tmp_path):
    (tmp_path/'data').mkdir()
    frame=pd.DataFrame({'id':[1,2,3],'full':[-8.,-12.,-5.],'null':[-10.,-13.,-7.]})
    frame.to_csv(tmp_path/'data/test.csv',index=False)
    p=dict(analysis_id='a',status='supported',family='likelihood_ratio',file='data/test.csv',table=None,header=0,x='full',y='null',id_column='id',included_ids=None,missingness='complete_cases',numeric_parsing='strict_float',df_per_subject=2,nesting='larger_contains_smaller',aggregation='sum_subject_loglikelihoods',contrast='larger versus smaller')
    ExtendedPlanDocument.model_validate({'protocol_version':'direct-plan-3','analyses':[p]})
    r=reference.from_plan(tmp_path,p)
    assert r['chi2']==10 and r['df']==6 and r['n']==3
    # chi-square with six df has this closed-form upper tail at ten.
    assert r['p_raw']==pytest.approx(np.exp(-5)*(1+5+25/2))
    a={'analysis_id':'a','likelihood_binding':{**p,'full_parameters_per_subject':5,'reduced_parameters_per_subject':3},'quantities':[{'claim_id':'q','quantity_kind':'chi2'}]}
    rows=[{'analysis_id':'a','claim_id':'q','value':10,'n':3}]
    assert extended_reference.check(tmp_path,p,a,rows,True)['status']=='verified'
    assert extended_reference.check(tmp_path,{**p,'df_per_subject':1},a,rows,True)['status']=='invalid'
    frame.loc[0,'full']=-11;frame.to_csv(tmp_path/'data/test.csv',index=False)
    with pytest.raises(ValueError,match='nesting'):reference.from_plan(tmp_path,p)


def test_likelihood_binding_requires_check_even_if_model_omits_it():
    from reproscope.data_checks import require_likelihood_checks
    bindings={'a1':{'file':'data/fit.csv','table':None,'x':'full','y':'reduced','evidence':'Equality constraints nest models.','assumption':'Sum independent fits.'}}
    checks=require_likelihood_checks([],bindings)
    assert len(checks)==1
    assert checks[0]['columns']==['reduced','full']
    assert require_likelihood_checks(checks,bindings)==checks


def test_family_method_comparison_allows_data_derived_sample_ids_but_not_new_columns():
    from copy import deepcopy
    from reproscope.execution_evidence import stable_method_payload
    baseline={'analysis_id':'a','family':'paired_t_family','members':[{'analysis_id':'m','family':'paired_t','x':'cue','y':'control','included_ids':[1,2,3]}]}
    removed=deepcopy(baseline);removed['members'][0]['included_ids']=[2,3]
    assert stable_method_payload(baseline)==stable_method_payload(removed)
    removed['members'][0]['x']='different'
    assert stable_method_payload(baseline)!=stable_method_payload(removed)

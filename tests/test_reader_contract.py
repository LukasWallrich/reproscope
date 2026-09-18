import pandas as pd
import pytest
from reproscope.intake import verify_roundtrip
from reproscope.report.findings import sensitivity
from reproscope.report.build import spec_curve_svg
from reproscope.stage3.multiverse import build_grid


def test_trimming_groups_together_but_ratio_and_influence_do_not():
    rows=[dict(spec={'estimator':x,'sample':'full'},estimate=v,p=.02,converged=True,
               effect_metric='mean_difference',effect_group='raw',null_group='location')
          for x,v in [('mean',2),('trim20',1.8)]]
    rows += [dict(spec={'sample':'full'},estimate=.2,p=.1,converged=True,effect_metric='log_ratio'),
             dict(spec={'sample':'leave_out:1'},estimate=3,converged=True,effect_metric='mean_difference')]
    got=sensitivity(rows,[{'name':'estimator'}])
    raw=next(g for g in got['groups'] if g['name']=='raw')
    assert raw['n']==2 and raw['changes'][0]['max_change']==pytest.approx(.2)
    assert len(got['groups'])==2 and len(got['diagnostics'])==1 and got['n_analytical']==3


def test_inference_choices_count_with_coincident_estimates():
    rows=[dict(spec={'method':m},estimate=2,p=p,converged=True,effect_metric='mean_difference',null_group='mean') for m,p in [('t',.04),('bootstrap',.08)]]
    result=sensitivity(rows,[{'name':'method'}])
    assert len(result['active_dimensions'])==1
    assert result['groups'][0]['inference'][0]['significant']==1
    assert result['groups'][0]['changes'][0]['max_change']==0


def test_no_implicit_normal_interval_for_arbitrary_estimator():
    svg=spec_curve_svg([dict(estimate=1,se=2,p=.2)],None,None)
    assert '1.96' not in svg and 'declared intervals' in svg


def test_container_conversion_preserves_mixed_cells_and_missingness():
    verify_roundtrip(pd.DataFrame({'a':[5.3,'label',None]}),pd.DataFrame({'a':['5.3','label',None]}))
    with pytest.raises(ValueError):verify_roundtrip(pd.DataFrame({'a':[5.3]}),pd.DataFrame({'a':[5.4]}))
    with pytest.raises(ValueError):verify_roundtrip(pd.DataFrame({'a':[None]}),pd.DataFrame({'a':[0]}))


def test_diagnostic_factor_cannot_inflate_multiverse():
    proposed={'factors':[{'name':'leave-one-out','levels':[{'value':'a'},{'value':'b'}]},
                         {'name':'estimator','levels':[{'value':'mean'},{'value':'trim20'}]}]}
    screen={'factors':[{'name':f['name'],'levels':[dict(value=l['value'],verdict='defensible') for l in f['levels']]} for f in proposed['factors']]}
    grid=build_grid(proposed,screen,exec_cap=None)
    assert [f['name'] for f in grid['factors']]==['estimator']
    assert grid['grid_size']==2 and len(grid['rejected_levels'])==2


def test_ratio_effect_direction_uses_one_as_null():
    rows=[dict(spec={'estimator':str(i)},estimate=v,p=.2,converged=True,effect_metric='odds_ratio',null_group='odds equality') for i,v in enumerate([.8,1.,1.2])]
    group=sensitivity(rows,[{'name':'estimator'}])['groups'][0]
    assert group['null_value']==1 and group['positive']==1 and group['negative']==1


def test_agreement_does_not_upgrade_an_unverified_implementation():
    from reproscope.report.findings import assemble
    s0={'claims':[dict(claim_id='c1',quantity_kind='t',value=2)],'contracts':[dict(analysis_id='a1',claim_ids=['c1'])]}
    s1={'match':{'rows':[dict(claim_id='c1',replica_id='r1',replicated=2,band='A')]},'replicas':[dict(replica_id='r1',audit_acceptance='accepted',execution_evidence={'analyses':{'a1':{'status':'unverified'}}})]}
    q=assemble(s0,s1,None,None,None,None)['quantities'][0]
    assert q['status']=='agreement from unverified implementation' and q['n_verified']==0


def test_test_statistics_cannot_be_effect_curves():
    from types import SimpleNamespace
    from reproscope.multiverse_contract import primary_effect
    contract=SimpleNamespace(design=SimpleNamespace(effect_metric='t'))
    with pytest.raises(ValueError,match='effect-scale'):
        primary_effect({},contract,{'focal_quantity':{'kind':'t'}})


def test_reader_precision_status_matches_divergence_inventory():
    from reproscope.report.findings import assemble
    s0={'claims':[dict(claim_id='c1',quantity_kind='r',value=.4)],'contracts':[]}
    s1={'match':{'rows':[dict(claim_id='c1',replica_id='r1',replicated=.404,band='A',exact_reported_precision=False)]}}
    assert assemble(s0,s1,None,None,None,None)['quantities'][0]['status']=='check difference'


def test_sign_gate_does_not_round_a_negative_value_to_zero():
    from reproscope.stage1.match import grade
    assert grade('b',-.01,-.0001,precision=2)['sign_match'] is True
    assert grade('b',.01,-.0001,precision=2)['sign_match'] is False
    assert grade('b',-.01,0,precision=2)['sign_match'] is None


def test_source_evidence_suppresses_internal_json_fragments():
    from reproscope.report.reader import prose_evidence
    assert not prose_evidence('  "reported": -0.11,\n "replicated": -0.1047')
    assert not prose_evidence('{"reported": 4}')
    assert prose_evidence('"The reported effect was positive."') == '"The reported effect was positive."'


def test_review_anchor_links_to_recorded_diagnosis_not_numeric_neighbours(monkeypatch,tmp_path):
    from reproscope.report import reader
    copy={'topics':[{'title':'Likelihood test','group_ids':['g1']}],
          'factor_labels':{'ci_method':'Interval & uncertainty'},'level_labels':{}}
    monkeypatch.setattr(reader.editorial,'load',lambda _:copy)
    finding={'source_id':'divergence_diagnoses','anchor':'"reported": 2,\\n "replicated": 4'}
    quantities=[{'claim_id':cid,'label':'Quantity','kind':'chi2','reported':2,'page':1,'replicas':[],'source':'Paper quotation'} for cid in ['c1','c2']]
    ctx={'findings':{'quantities':quantities,'sensitivity':{'groups':[]}},
         '_diagnosis_context':{'inventory':{'groups':[{'group_id':'g1','claim_ids':['c1']}]},
                               'diagnoses':[{'group_id':'g1','evidence_quote':'"reported": 2,\n "replicated": 4'}]},
         's2':{'questions':{'scope':'metadata','coding':{'findings':[finding]}}},
         's3':{'interpretation_html':'<a href="#ci_method">ci_method</a>'}}
    reader.enrich(ctx,tmp_path)
    assert [q['claim_id'] for q in finding['quantity_links']]==['c1']
    assert finding['issue_links']==[{'index':1,'title':'Likelihood test'}]
    assert str(ctx['s3']['interpretation_html'])=='<a href="#ci_method">Interval &amp; uncertainty</a>'


def test_new_association_methods_have_explicit_reader_labels():
    from reproscope.report.reader import method_steps
    from reproscope.verification_recipe import Recipe
    r=Recipe(file='data/study.csv',x='outcome',y='predictor',design='association',estimator='partial',test='residual_permutation',permutation_target='predictor',ci='fisher_z',rank=True,rank_covariates=True,approximate_rank_fisher=True,covariates=['age'],outliers='studentized_residual_trim').model_dump()
    text=' '.join(method_steps(r))
    assert 'internally studentized' in text and 'direct residual-permutation' in text
    assert 'Rank-transformed nuisance covariates: age' in text and 'approximation for rank' in text
    r.update(estimator='semipartial',ci='percentile')
    assert 'residualise predictor predictor against the nuisance design, then correlate its residuals with unresidualised outcome outcome' in ' '.join(method_steps(r))


def test_reader_excludes_private_recipe_notes_and_sample_records(monkeypatch,tmp_path):
    import json
    from reproscope.report import reader
    monkeypatch.setattr(reader.editorial,'load',lambda _: {'topics':[]})
    row=dict(spec_id='s1',spec={},estimate=.2,p=.03,converged=True,effect_metric='r')
    from reproscope.verification_recipe import Recipe
    recipe=Recipe(file='data/study.csv',x='outcome',y='predictor',design='association',estimator='partial',test='t',ci='fisher_z',note='PRIVATE_ID: person-123').model_dump()
    evidence=dict(spec_id='s1',status='verified',checks=[],recipe=recipe,sample={'n':8,'included_ids':['person-123'],'private_column':'PRIVATE_ID'})
    ctx={'findings':{'quantities':[],'sensitivity':sensitivity([row],[])},'s3':{'space':{'execution':{'reference':{'evidence':[evidence]}}}}}
    reader.enrich(ctx,tmp_path)
    verification=ctx['findings']['sensitivity']['groups'][0]['rows'][0]['verification']
    assert verification['sample']['n']==8
    assert 'PRIVATE_ID' not in json.dumps(verification) and 'person-123' not in json.dumps(verification)
    assert 'method_note' not in verification

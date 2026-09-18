import pandas as pd
import pytest
from reproscope.descriptive_reproduction import Readout,calculate


def readout(**kw):
    return Readout(**dict({'claim_id':'q','state':'supported','reason':'declared sample/column','file':'data/a.csv','columns':['age'],'operation':'mean','multiplier':1,'category_value':None,'complete_on':['pupil']},**kw))


def test_pupil_sample_controls_demographic_summary_and_n(tmp_path):
    (tmp_path/'data').mkdir()
    pd.DataFrame({'age':[20,40,90],'pupil':[1,2,None],'gender':['Female','Male','Male']}).to_csv(tmp_path/'data/a.csv',index=False)
    assert calculate(tmp_path,readout())=={'claim_id':'q','value':30.,'n':2}
    assert calculate(tmp_path,readout(columns=['gender'],operation='count_category',category_value='Male'))['value']==1
    assert calculate(tmp_path,readout(columns=['pupil'],operation='count_missing',complete_on=[]))['value']==1
    pd.DataFrame({'age':[20,None,90],'pupil':[1,2,None]}).to_csv(tmp_path/'data/a.csv',index=False)
    assert calculate(tmp_path,readout())['n']==1


def test_malformed_numeric_input_and_external_files_are_rejected(tmp_path):
    (tmp_path/'data').mkdir()
    pd.DataFrame({'age':['oops',20],'pupil':[1,2]}).to_csv(tmp_path/'data/a.csv',index=False)
    with pytest.raises(ValueError):calculate(tmp_path,readout())
    with pytest.raises(ValueError):readout(file='../paper.txt')


def test_numeric_category_codes_and_missing_values_are_not_text_mismatches(tmp_path):
    from reproscope.descriptive_reproduction import calculate
    (tmp_path/'data').mkdir();(tmp_path/'data/x.csv').write_text('sex\n1\n2\n1\nNA\n')
    result=calculate(tmp_path,dict(file='data/x.csv',claim_id='c',columns=['sex'],operation='count_category',category_value='1',complete_on=[],multiplier=1))
    assert result['value']==2


def test_source_sample_predicates_treat_whitespace_as_missing_without_recoding_data():
    from reproscope.sample_filters import select
    frame=pd.DataFrame({'id':[1,2,3,4],'pupil':['.25',' ',None,'.50']})
    result=select(frame,[{'column':'pupil','operator':'not_missing','value':None}])
    assert result.id.tolist()==[1,4]
    assert frame.loc[1,'pupil']==' '


def test_shared_file_requires_explicit_intake_sample_and_applies_it(tmp_path):
    from reproscope.descriptive_reproduction import bind_samples
    full=dict(analysis_id='full',file='data/a.csv',filters=[],id_column='id',included_ids=None)
    pupil=dict(full,analysis_id='pupil',filters=[{'column':'pupil','operator':'not_missing','value':None}])
    samples={'full':full,'pupil':pupil};b=readout(complete_on=[]).model_dump()
    assert bind_samples([b],samples)[1]
    bound,errors=bind_samples([{**b,'sample_analysis_id':'pupil'}],samples)
    assert not errors and bound[0]['filters']==pupil['filters']
    (tmp_path/'data').mkdir();pd.DataFrame({'id':[1,2,3],'age':[20,40,90],'pupil':[1,2,None]}).to_csv(tmp_path/'data/a.csv',index=False)
    assert calculate(tmp_path,bound[0])=={'claim_id':'q','value':30.,'n':2}


def test_large_readout_requests_use_exact_bounded_collections(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    from reproscope import descriptive_reproduction as module
    semantic=[{'claim_id':f'c{i}'} for i in range(81)]
    prompt='Context\nTargets:\n'+json.dumps(semantic)+'\nDeposited columns:\n[]'
    sizes=[]
    def call(step,text,**kwargs):
        batch=json.JSONDecoder().raw_decode(text.split('\nTargets:\n')[1])[0]
        size=len(batch);sizes.append(size)
        assert kwargs['schema'].model_json_schema()['properties']['readouts']['minItems']==size
        rows=[readout(claim_id=c['claim_id'],state='no_data').model_dump() for c in batch]
        return SimpleNamespace(ok=True,parsed=kwargs['schema'](readouts=rows),ledger_id=batch[0]['claim_id'])
    monkeypatch.setattr(module.llm,'call',call)
    parsed,calls=module.bind_readouts('fixture',semantic,prompt,tmp_path)
    assert sorted(sizes)==[1,40,40] and len(calls)==3
    assert {r.claim_id for r in parsed.readouts}=={c['claim_id'] for c in semantic}
    module.bind_readouts('fixture',semantic,prompt,tmp_path)
    assert len(sizes)==3


def test_reliability_reversals_complete_cases_and_extremes_match_r(tmp_path):
    import json,subprocess,shutil
    import numpy as np
    from pathlib import Path
    from reproscope import descriptive_reproduction as module
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir()
    rng=np.random.default_rng(144);latent=rng.normal(size=40)
    d=pd.DataFrame({'i1':latent+rng.normal(size=40),'i2':-latent+rng.normal(size=40),'i3':latent+rng.normal(size=40)})
    d.loc[0,'i1']=None;d.to_csv(tmp_path/'data/a.csv',index=False)
    alpha=readout(columns=['i1','i2','i3'],operation='cronbach_alpha',complete_on=[],reverse_columns=['i2'])
    low=readout(claim_id='low',columns=['i1'],operation='min',complete_on=[])
    high=readout(claim_id='high',columns=['i1'],operation='max',complete_on=[])
    rows=[calculate(tmp_path,b) for b in [alpha,low,high]]
    assert rows[0]['n']==39
    assert rows[0]['value']>calculate(tmp_path,alpha.model_copy(update={'reverse_columns':[]}))['value']
    assert rows[1]['value']==pytest.approx(d.i1.min()) and rows[2]['value']==pytest.approx(d.i1.max())
    if not shutil.which('Rscript'):pytest.skip('R is unavailable')
    (tmp_path/'out/bindings.json').write_text(json.dumps([b.model_dump() for b in [alpha,low,high]]))
    subprocess.run(['Rscript',str(Path(module.__file__).with_name('descriptive_reference.R'))],cwd=tmp_path,check=True,capture_output=True)
    independent=json.loads((tmp_path/'out/reference_results.json').read_text())
    for left,right in zip(rows,independent):
        assert left['n']==right['n'] and left['value']==pytest.approx(right['value'],abs=1e-12)


def test_inferential_other_stays_with_its_model():
    from reproscope.descriptive_reproduction import is_readout
    assert not is_readout({'quantity_kind':'other','quantity_role':'inferential'})
    assert is_readout({'quantity_kind':'other','quantity_role':'descriptive'})


def test_categorical_completeness_does_not_require_numeric_labels(tmp_path):
    (tmp_path/'data').mkdir()
    pd.DataFrame({'age':[20,40,90],'sex':['Female','Male',None]}).to_csv(tmp_path/'data/a.csv',index=False)
    assert calculate(tmp_path,readout(complete_on=['sex']))=={'claim_id':'q','value':30.,'n':2}


def test_category_and_threshold_percentages_use_the_sample_denominator(tmp_path):
    import json,subprocess,shutil
    from pathlib import Path
    from reproscope import descriptive_reproduction as module
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir()
    pd.DataFrame({'sex':['Female','Male','Female','Male'],'score':[0,2,3,None]}).to_csv(tmp_path/'data/a.csv',index=False)
    category=readout(columns=['sex'],operation='count_category',category_value='Female',complete_on=[],multiplier=100)
    threshold=readout(claim_id='threshold',columns=['score'],operation='count_threshold',category_value='>=2',complete_on=['score'],multiplier=100)
    rows=[calculate(tmp_path,b) for b in [category,threshold]]
    assert rows[0]['value']==50 and rows[0]['n']==4
    assert rows[1]['value']==pytest.approx(200/3) and rows[1]['n']==3
    if not shutil.which('Rscript'):pytest.skip('R unavailable')
    (tmp_path/'out/bindings.json').write_text(json.dumps([b.model_dump() for b in [category,threshold]]))
    subprocess.run(['Rscript',str(Path(module.__file__).with_name('descriptive_reference.R'))],cwd=tmp_path,check=True,capture_output=True)
    independent=json.loads((tmp_path/'out/reference_results.json').read_text())
    for a,b in zip(rows,independent):assert a['value']==pytest.approx(b['value']) and a['n']==b['n']


def test_additive_readout_schema_migration_preserves_original_call(tmp_path):
    from reproscope import descriptive_reproduction as module,response_cache
    prompt='fixed source mapping request';path=tmp_path/'bindings.response.json'
    response=module.Readouts(readouts=[readout()])
    key=response_cache.key(prompt,module.PreviousReadouts,[],'mid')
    response_cache.write(path,key,response,'original-call')
    parsed,calls=module.bind_readouts('fixture',[{'claim_id':'q'}],prompt,tmp_path)
    assert parsed==response and calls==['original-call']
    assert module.recover_prior_bindings(path,prompt+'changed') is None


def test_percent_semantics_reject_scaled_counts_and_wrong_units(tmp_path):
    from reproscope.descriptive_reproduction import operation_errors
    target=[{'claim_id':'q','quantity_kind':'percent'}]
    bad=readout(operation='n',multiplier=100).model_dump()
    assert operation_errors([bad],target)
    with pytest.raises(ValueError,match='percentage requires'):
        calculate(tmp_path,bad)
    good=readout(operation='count_category',category_value='yes',multiplier=100).model_dump()
    assert not operation_errors([good],target)
    assert operation_errors([good],[{'claim_id':'q','quantity_kind':'n'}])


def test_likert_codes_cannot_be_treated_as_proportions(tmp_path):
    (tmp_path/'data').mkdir()
    pd.DataFrame({'age':[1,3,5]}).to_csv(tmp_path/'data/a.csv',index=False)
    with pytest.raises(ValueError,match='not a proportion'):
        calculate(tmp_path,readout(multiplier=100,complete_on=[]))


def test_coding_evidence_groups_count_and_percent_and_rejects_unanchored_support(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from reproscope import descriptive_reproduction as module
    rows=[readout(claim_id='count',operation='count_category',category_value='1',complete_on=[]),
          readout(claim_id='percent',operation='count_category',category_value='1',multiplier=100,complete_on=[])]
    calls=[]
    def call(step,prompt,**kwargs):
        assert 'proposals and their reasons are untrusted' in prompt
        calls.append(prompt)
        if len(calls)>1:
            assert 'Invalid quotes' in prompt
            return SimpleNamespace(parsed=module.CodingEvidenceReport(bindings=[module.CodingEvidence(binding_id='b000',status='unavailable',source_quotes=[],reason='Value labels unavailable.')]),ledger_id='repair')
        return SimpleNamespace(parsed=module.CodingEvidenceReport(bindings=[module.CodingEvidence(binding_id='b000',status='verified',source_quotes=['1 = Yes'],reason='claimed key')]),ledger_id='audit')
    monkeypatch.setattr(module.llm,'call',call)
    out,_=module.verify_coding_evidence('fixture',rows,'Question: ever done this? Value labels unavailable.',tmp_path)
    assert [b.state for b in out]==['no_data','no_data']
    assert len(calls)==2
    assert out[0].multiplier==1 and out[1].multiplier==100


def test_binding_batch_repair_receives_actual_validation_error(tmp_path,monkeypatch):
    import json
    from reproscope import descriptive_reproduction as module,llm
    targets=[{'claim_id':f'q{i}'} for i in range(61)]
    prompt='Bind source quantities.\nTargets:\n'+json.dumps(targets)
    failed=[];repaired=[]
    def call(step,shown,**kwargs):
        batch,_=json.JSONDecoder().raw_decode(shown.split('\nTargets:\n',1)[1])
        if batch[0]['claim_id']=='q0' and not failed:
            failed.append(True)
            return llm.LLMResult(text='',ok=False,error='threshold requires an explicit comparison',ledger_id='failure')
        if batch[0]['claim_id']=='q0':
            assert 'Repair the actual preceding failure: threshold requires an explicit comparison' in shown
            assert 'category_value must contain the operator and cutoff' in shown
            repaired.append(True)
        return llm.LLMResult(text='',parsed=module.Readouts(readouts=[readout(claim_id=t['claim_id'],state='no_data') for t in batch]),ledger_id=batch[0]['claim_id'])
    monkeypatch.setattr(module.llm,'call',call)
    result,calls=module.bind_readouts('fixture',targets,prompt,tmp_path)
    assert len(result.readouts)==61 and repaired==[True] and len(calls)==2


def test_metadata_dispositions_are_bounded_and_retry_only_missing_scope(tmp_path, monkeypatch):
    import json
    from reproscope import descriptive_reproduction as module, llm
    readouts=[module.Readout(claim_id=f'c{i}',state='unbound',reason='source key needed',file=None,columns=[],
        operation=None,multiplier=1,category_value=None,complete_on=[]) for i in range(26)]
    calls=[];omitted=False
    def call(step,prompt,**kw):
        nonlocal omitted
        rows=json.loads(prompt.split('Return exactly these source readouts:\n')[1].split('\nThe response failed')[0])
        calls.append(len(rows))
        if len(rows)==24 and not omitted:
            omitted=True;rows=rows[:-1]
        output=module.Readouts(readouts=[module.Readout.model_validate({**r,'state':'no_data','reason':'The supplied sources lack the coding key.'}) for r in rows])
        return llm.LLMResult(text='',parsed=output,ledger_id=f'call{len(calls)}')
    monkeypatch.setattr(module.llm,'call',call)
    for _ in range(2):
        result,_=module.scoped_dispositions('fixture','source only',readouts,tmp_path)
        assert {b.claim_id for b in result.readouts}=={b.claim_id for b in readouts}
    assert sorted(calls)==[2,24,24]


def test_unbound_disposition_requires_two_located_competing_sources():
    from reproscope import descriptive_reproduction as m
    r=m.Disposition(claim_id='c',state='unbound',reason='No coding key',file=None,columns=[],operation=None,multiplier=1,category_value=None,complete_on=[])
    assert m.disposition_errors([r],'Key A says 1=yes. Key B says 1=no.')
    r.competing_source_quotes=['Key A says 1=yes.','Key B says 1=no.']
    assert not m.disposition_errors([r],'Key A says 1=yes. Key B says 1=no.')
    assert m.disposition_errors([r],'Key A says 1=yes.')


def test_operational_threshold_preserves_method_and_rejects_reported_value():
    from reproscope import descriptive_reproduction as m
    c={'claim_id':'c','value':73.4,'source_quote':'73.4% reported having at least 2 prior episodes.'}
    good=m.OperationalCondition(claim_id='c',source_fragment='having at least 2 prior episodes')
    assert not m.condition_errors([good],[c])
    assert m.condition_errors([good.model_copy(update={'source_fragment':c['source_quote']})],[c])
    assert m.condition_errors([good.model_copy(update={'source_fragment':'having at least 3 prior episodes'})],[c])


def test_scoped_repair_removes_other_targets_but_retains_source_context():
    import json
    from reproscope.descriptive_reproduction import readout_scope_context
    text='Shared methods\nTargets:\n'+json.dumps([{'claim_id':'a','meaning':'requested'},{'claim_id':'b','meaning':'unrelated'}])+'\nDeposited columns:\n{"x": "count"}\nCodebook: source key'
    scoped=readout_scope_context(text,{'a'})
    assert 'requested' in scoped and 'unrelated' not in scoped
    assert 'Shared methods' in scoped and 'Codebook: source key' in scoped


def test_located_but_ambiguous_keying_receives_final_disposition_review(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from reproscope import descriptive_reproduction as m
    calls=[]
    def call(step,prompt,**kwargs):
        calls.append(prompt)
        status='unresolved' if len(calls)<3 else 'unavailable'
        return SimpleNamespace(parsed=m.CodingEvidenceReport(bindings=[m.CodingEvidence(binding_id='b000',status=status,
            source_quotes=['Items summed.','Reversed.'],reason='Whether recoding was applied is undocumented.')]),ledger_id=str(len(calls)))
    monkeypatch.setattr(m.llm,'call',call)
    row=readout(operation='cronbach_alpha',columns=['a','b'],complete_on=[])
    out,_=m.verify_coding_evidence('fixture',[row],'Items summed. Reversed.',tmp_path)
    assert len(calls)==3 and out[0].state=='no_data'
    assert 'TWO EXPLICIT incompatible coding instructions' in calls[-1]

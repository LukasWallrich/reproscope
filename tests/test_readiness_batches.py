import json
import pytest
from reproscope import artifacts,llm
from reproscope.stage0 import readiness as module


def test_readiness_status_is_closed_and_legacy_executable_labels_are_normalised():
    for label in ['complete','ready','bound']:
        state=module.SlimAnalysisState(analysis_id='a',state=label)
        assert state.state=='complete'
    assert module.SlimAnalysisState(analysis_id='a',state='abstained').state=='abstained'
    with pytest.raises(ValueError):module.SlimAnalysisState(analysis_id='a',state='maybe')
    schema=module.SlimAnalysisState.model_json_schema()
    assert schema['properties']['state']['enum']==['complete','abstained']


def test_intact_legacy_cache_preserves_ledger_and_batch_provenance(tmp_path):
    from reproscope import response_cache,provenance
    class PreviousSchema:
        @staticmethod
        def model_json_schema():
            schema=module.ReadinessOut.model_json_schema()
            schema['$defs']['SlimAnalysisState']['properties']['state'].pop('enum')
            return schema
    old_key=response_cache.key('prompt',PreviousSchema,[],'mid')
    new_key=response_cache.key('prompt',module.ReadinessOut,[],'mid')
    payload=module.ReadinessOut(per_analysis=[module.SlimAnalysisState(analysis_id='a',state='complete')]).model_dump()
    payload['per_analysis'][0]['state']='ready'
    path=tmp_path/'response.json'
    path.write_text(json.dumps(dict(fingerprint=old_key,response=payload,response_hash=provenance.digest(payload),ledger_id='original-call')))
    receipt=tmp_path/'readiness_initial_batches.json'
    receipt.write_text(json.dumps(dict(response_key=old_key,model_calls=['original-call','other-batch'])))
    result,cid=module.read_response(path,new_key,module.ReadinessOut,'prompt','mid')
    assert result.per_analysis[0].state=='complete' and cid=='original-call'
    assert json.loads(receipt.read_text())==dict(response_key=new_key,model_calls=['original-call','other-batch'])
    # Altered payloads cannot use the migration to evade the response hash.
    raw=json.loads(path.read_text());raw['response']['per_analysis'][0]['state']='abstained'
    path.write_text(json.dumps(raw))
    assert module.read_response(path,new_key,module.ReadinessOut,'prompt','mid') is None


def test_large_binding_repairs_have_exact_bounded_analysis_scopes(tmp_path,monkeypatch):
    contracts=[artifacts.EstimandContract(analysis_id=f'a{i}',outcome='x',predictors=['y'],covariates=['z']) for i in range(31)]
    candidate=module.ReadinessOut(per_analysis=[module.SlimAnalysisState(analysis_id=c.analysis_id,state='complete',binding_basis='source_determined') for c in contracts])
    errors={c.analysis_id:['no executable bindings'] for c in contracts};counts=[]
    def call(step,prompt,**kwargs):
        payload=json.loads(prompt.replace(module.RANGE_GUIDANCE,'').split('\n',1)[1]);cs=payload['contracts'];counts.append(len(cs))
        ids={c['analysis_id'] for c in cs}
        assert len(cs)*3<=40 and kwargs['large_context']
        patch=module.ReadinessPatch(per_analysis=[a for a in candidate.per_analysis if a.analysis_id in ids],
            variable_bindings=[module.SlimBinding(analysis_id=c['analysis_id'],contract_field=field,chosen=col,file='data/d.csv')
                              for c in cs for field,col in [('outcome','x'),('predictors[0]','y'),('covariates[0]','z')]])
        return llm.LLMResult(text='',parsed=patch,ledger_id=sorted(ids)[0])
    monkeypatch.setattr(module.llm,'call',call)
    repaired,calls=module.repair_batches(candidate,contracts,errors,set(errors),{},'paper','codebook',tmp_path,'fixture',0)
    assert sorted(counts)==[5,13,13] and len(calls)==3
    assert len(repaired.variable_bindings)==93
    module.repair_batches(candidate,contracts,errors,set(errors),{},'paper','codebook',tmp_path,'fixture',0)
    assert len(counts)==3


def test_global_identifier_check_is_scoped_to_its_actual_data_table():
    request=module.IntegrityRequest(analysis_id='global',file='data/d.csv',kind='unique_id',columns=['id'])
    selected={'a':{'file':'data/d.csv','table':None},'b':{'file':'data/another.csv','table':None},'c':{'file':'data/d.csv','table':None}}
    result=module.scoped_integrity_requests([request],selected)
    assert {x['analysis_id'] for x in result}=={'a','c'}
    assert request.analysis_id=='global'


def test_binding_retry_lists_missing_fields_and_escalates_only_failed_batch(tmp_path, monkeypatch):
    from reproscope import config
    monkeypatch.setattr(config, 'config', lambda: config.Config(tiers={
        'strong': config.ModelSpec(route='claude_p', model='haiku'),
        'contract_repair': config.ModelSpec(route='claude_p', model='sonnet')}))
    contract = artifacts.EstimandContract(analysis_id='a', outcome='x', predictors=['y', 'z'])
    state = module.SlimAnalysisState(analysis_id='a', state='complete', binding_basis='source_determined')
    candidate = module.ReadinessOut(per_analysis=[state])
    calls = []
    def call(step, prompt, **kw):
        calls.append(kw['tier'])
        if len(calls)>1:
            assert 'Missing executable fields' in prompt and 'predictors[1]' in prompt
        fields = ['outcome', 'predictors[0]'] + (['predictors[1]'] if len(calls)==3 else [])
        return llm.LLMResult(text='', parsed=module.ReadinessPatch(per_analysis=[state],
            variable_bindings=[module.SlimBinding(analysis_id='a', contract_field=f, chosen='x', file='data/d.csv') for f in fields]), ledger_id=f'call{len(calls)}')
    monkeypatch.setattr(module.llm, 'call', call)
    for _ in range(2):
        repaired, ids = module.repair_batches(candidate, [contract], {'a':['missing']}, {'a'}, {}, 'paper', 'codebook', tmp_path, 'fixture', 0)
        assert len(repaired.variable_bindings)==3 and ids==['call3']
    assert calls==['strong','strong','contract_repair']


def test_old_derived_range_cache_preserves_numbers_for_source_repair(tmp_path):
    from reproscope import response_cache
    class OldSchema:
        @staticmethod
        def model_json_schema():
            s=module.ReadinessOut.model_json_schema();props=s['$defs']['SlimBinding']['properties']
            props.pop('input_ranges');props.pop('derived_range');props['allowed_range'].pop('description');s['$defs'].pop('InputRange')
            return s
    old_key=response_cache.key('source',OldSchema,[],'mid')
    new_prompt='source'+module.RANGE_GUIDANCE
    new_key=response_cache.key(new_prompt,module.ReadinessOut,[],'mid')
    output=module.ReadinessOut(variable_bindings=[module.SlimBinding(analysis_id='a',contract_field='outcome',input_columns=['x','y'],transformation='sum',allowed_range=[2,10])])
    p=tmp_path/'response.json';response_cache.write(p,old_key,output,'original-call')
    (tmp_path/'readiness_initial_batches.json').write_text(json.dumps({'response_key':old_key,'model_calls':['a','original-call']}))
    result,cid=module.read_response(p,new_key,module.ReadinessOut,new_prompt,'mid')
    assert cid=='original-call' and result.variable_bindings[0].allowed_range==[2,10]
    assert result.variable_bindings[0].input_ranges==[] and result.variable_bindings[0].derived_range==[]
    assert json.loads((tmp_path/'readiness_initial_batches.json').read_text())['model_calls']==['a','original-call']
    assert json.loads((tmp_path/'readiness_initial_batches.json').read_text())['response_key']==new_key

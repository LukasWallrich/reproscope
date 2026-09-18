from copy import deepcopy
from reproscope import dimension_refinement as module,llm
from reproscope.stage3.multiverse import EnumerateOut


def factor(name,values):
    return {'name':name,'levels':[{'value':v,'how':'Declared method'} for v in values]}


def test_active_dimensions_exclude_pins_reference_rows_and_unexecuted_levels():
    grid={'factors':[factor('estimator',['a','b']),factor('fixed',['x'])],
        'reference_specs':[{'spec_id':'reference','levels':{'estimator':'a','fixed':'y'}}]}
    assert module.active_dimensions(grid)==['estimator']
    grid['sampled_spec_ids']=['spec_001']
    assert module.active_dimensions(grid)==[]


def test_refinement_adds_choices_without_rewriting_existing_proposal(tmp_path,monkeypatch):
    proposed={'factors':[factor('estimator',['a','b'])],'_ledger_id':'original'}
    original=deepcopy(proposed)
    addition=factor('outliers',['none','fixed_rule'])
    prompts=[]
    def call(step,prompt,**kwargs):
        prompts.append(prompt)
        assert 'Zero new factors is a valid answer' in prompt
        assert kwargs['tier']=='strong'
        return llm.LLMResult(text='',parsed=EnumerateOut(factors=[addition]),ledger_id='refinement')
    monkeypatch.setattr(module.llm,'call',call)
    result=module.refine('fixture',proposed,{'factors':[]},{'factors':proposed['factors']},'contract','schema','traces',tmp_path,5)
    assert proposed==original and result['factors'][0]==original['factors'][0]
    assert result['factors'][1]['name']=='outliers'
    assert result['_ledger_id']=='original' and result['_dimension_refinement_calls']==['refinement']
    module.refine('fixture',proposed,{'factors':[]},{'factors':proposed['factors']},'contract','schema','traces',tmp_path,5)
    assert len(prompts)==1


def test_no_defensible_addition_ends_refinement_without_fabricating_a_dimension(tmp_path,monkeypatch):
    proposed={'factors':[factor('estimator',['a','b'])]}
    calls=[]
    def call(*args,**kwargs):
        calls.append(True)
        return llm.LLMResult(text='',parsed=EnumerateOut(factors=[],notes='No supported additional choice.'),ledger_id='none')
    monkeypatch.setattr(module.llm,'call',call)
    result=module.refine('fixture',proposed,{}, {'factors':proposed['factors']},'contract','schema','traces',tmp_path,5)
    assert result['_no_further_dimensions'] and result['factors']==proposed['factors']
    assert module.refine('fixture',result,{}, {'factors':proposed['factors']},'contract','schema','traces',tmp_path,5) is None
    assert len(calls)==1

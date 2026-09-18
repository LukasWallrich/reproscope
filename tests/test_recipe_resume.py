import json
from types import SimpleNamespace
from reproscope import verification_recipe as vr


def test_recipe_resume_retains_failed_calls_and_uses_precise_feedback(tmp_path,monkeypatch):
    work=tmp_path/'work';(work/'data').mkdir(parents=True)
    (work/'CONTRACT.json').write_text('{}');(work/'data/f.csv').write_text('x,y\n1,2\n2,3\n')
    folder=tmp_path/'independent_recipe';folder.mkdir()
    base=vr.Recipe(file='data/f.csv',x='x',y='y',design='association',estimator='partial',test='t',ci='fisher_z').model_dump()
    book={'base':base,'factors':{'method':{'rank':{'rank':True}}},'conditions':[],'evidence':[],'limitations':[]}
    grid={'factors':[{'name':'method','levels':[{'value':'rank'}]}]}
    for i in range(1,4):(folder/f'k-{i}.candidate.json').write_text(json.dumps({'book':book,'call':f'old{i}','compile_error':'old vague error'}))
    monkeypatch.setattr(vr.provenance,'digest',lambda _: 'k')
    monkeypatch.setattr(vr.config,'tier',lambda _:SimpleNamespace(route='claude_p',model='model'))
    monkeypatch.setenv('REPROSCOPE_METHOD_REPAIR_TIER','repair')
    calls=[]
    def call(tier,prompt,**kwargs):
        calls.append((tier,prompt))
        if kwargs['schema'] is vr.RecipeBook:
            assert 'approximate_rank_fisher=true' in prompt and 'Previous candidate:' in prompt
            fixed=json.loads(json.dumps(book));fixed['factors']['method']['rank']['approximate_rank_fisher']=True
            parsed=vr.RecipeBook.model_validate(fixed)
        else:parsed=vr.Review(accepted=True,problems=[],evidence=[])
        return SimpleNamespace(ok=True,parsed=parsed,ledger_id=f'new{len(calls)}',error=None)
    monkeypatch.setattr(vr.llm,'call',call)
    result=vr.prepare(work,grid,'fixture')
    assert result['accepted'] and len(calls)==2
    assert [r['call'] for r in result['history'][:3]]==['old1','old2','old3']


def test_source_identifier_is_required_for_membership_checks(tmp_path):
    import pytest
    work=tmp_path/'work';(work/'data').mkdir(parents=True)
    (work/'data/f.csv').write_text('case,x,y\n101,1,2\n102,2,4\n103,3,5\n')
    (work/'data/book.txt').write_text(json.dumps({'sheets':[{'rows':[['Variable','Label'],['case','Participant identifier']]}]}))
    identifiers=vr.source_identifiers(work)
    assert identifiers=={'data/f.csv':['case']}
    base=vr.Recipe(file='data/f.csv',x='x',y='y',design='association',estimator='partial',test='t',ci='fisher_z').model_dump()
    book={'base':base,'factors':{'method':{'original':{}}},'evidence':[],'limitations':[]}
    grid={'factors':[{'name':'method','levels':[{'value':'original'}]}]}
    with pytest.raises(ValueError,match='unique participant identifiers'):vr.validate_source_bindings(book,grid,[],identifiers)
    book['base']['id_column']='case'
    assert vr.validate_source_bindings(book,grid,[],identifiers)

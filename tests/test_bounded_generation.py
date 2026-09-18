from pathlib import Path
import pytest
from reproscope import bounded_generation as bg


def test_payload_contains_only_explicit_supplied_inputs(tmp_path):
    (tmp_path/'data').mkdir();(tmp_path/'out').mkdir()
    (tmp_path/'METHODS.md').write_text('blind methods')
    (tmp_path/'paper.txt').write_text('must not be supplied')
    (tmp_path/'out/results.json').write_text('must not be supplied')
    (tmp_path/'data/a.csv').write_text('x\n1\n2\n')
    assert {p['path'] for p in bg.inputs(tmp_path)}=={'METHODS.md','data/a.csv'}
    (tmp_path/'data/b.csv').symlink_to(tmp_path/'paper.txt')
    with pytest.raises(ValueError,match='regular'):bg.inputs(tmp_path)


@pytest.mark.parametrize('name',['../analysis.py','/tmp/analysis.py','results.json','x/analysis.py'])
def test_only_source_basenames_can_be_written(tmp_path,name):
    (tmp_path/'out').mkdir()
    with pytest.raises(ValueError):
        bg.write_sources(tmp_path,bg.Bundle(files=[bg.SourceFile(name=name,content='x')]))
    assert not list((tmp_path/'out').iterdir())


def test_bundle_schema_rejects_sidecars_before_code_generation_returns():
    for name in ['out/trace.json','analysis_plan.json','requirements.txt','out/requirements.txt']:
        with pytest.raises(ValueError):bg.SourceFile(name=name,content='placeholder')
    assert bg.SourceFile(name='out/analysis.R',content='print(1)').name=='out/analysis.R'
    assert bg.SourceFile(name='helper.py',content='x=1').name=='helper.py'


def test_openrouter_source_generation_requires_matching_budget(tmp_path, monkeypatch):
    from types import SimpleNamespace
    spec=SimpleNamespace(route='openrouter',model='cheap-model')
    monkeypatch.delenv('REPROSCOPE_METERED_BUDGET_FILE',raising=False)
    with pytest.raises(ValueError,match='explicit shared metered budget'):
        bg.generate(tmp_path,paper_id='fixture',stage='1',spec=spec,prompt='',log_path=tmp_path/'log',script_stem='analysis')
    budget=tmp_path/'budget.json';budget.write_text('{"model":"different-model"}')
    monkeypatch.setenv('REPROSCOPE_METERED_BUDGET_FILE',str(budget))
    with pytest.raises(ValueError,match='differs'):
        bg.generate(tmp_path,paper_id='fixture',stage='1',spec=spec,prompt='',log_path=tmp_path/'log',script_stem='analysis')


def test_unverified_requested_analysis_is_a_code_repair_failure(tmp_path,monkeypatch):
    from reproscope import execution_evidence
    from reproscope.stage1 import replicas
    (tmp_path/'CONTRACT.json').write_text('{}')
    monkeypatch.setattr(execution_evidence,'check_replica',lambda *a,**k:{'status':'unverified','analyses':{
        'a1':{'status':'verified'},'a2':{'status':'unverified','reason':'missing requested coefficient'}}})
    assert replicas.generation_validation(tmp_path)==['a2: missing requested coefficient']

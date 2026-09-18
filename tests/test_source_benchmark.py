import json
from types import SimpleNamespace
import pytest
from reproscope import source_benchmark as benchmark


def test_score_refuses_to_attach_old_matches_to_changed_extraction(monkeypatch,tmp_path):
    folder=tmp_path/'gold';folder.mkdir();stage=tmp_path/'stage0';stage.mkdir()
    expected={'source_id':'p001_q001','value':1,'comparator':'=','precision':0,'clean':True}
    (folder/'frozen_inventory.json').write_text(json.dumps({'scope':'Test inventory','pages':[{'page':1,'items':[expected]}]}))
    claim={'claim_id':'c1','value':1,'comparator':'=','precision':0,'quantity_kind':'n','location':{'page':1},'state':'complete','source_validation':'text_anchored'}
    path=stage/'claims.json';path.write_text(json.dumps([claim]))
    monkeypatch.setattr(benchmark,'root',lambda _:folder)
    monkeypatch.setattr(benchmark.paths,'run_dir',lambda *args:stage)
    monkeypatch.setattr(benchmark.paths,'manifest',lambda _:None)
    monkeypatch.setattr(benchmark,'page_texts',lambda *args:['','One participant.'])
    monkeypatch.setattr(benchmark.response_cache,'key',lambda *args:'key')
    monkeypatch.setattr(benchmark.response_cache,'read',lambda *args:None)
    monkeypatch.setattr(benchmark.response_cache,'write',lambda *args:None)
    def match(*args,**kwargs):
        path.write_text(json.dumps([{**claim,'value':2}]))
        result=benchmark.Matches(items=[benchmark.Match(source_id='p001_q001',claim_id='c1',verdict='correct',reason='Matches supplied snapshot',field='value')])
        return SimpleNamespace(ok=True,parsed=result,ledger_id='call')
    monkeypatch.setattr(benchmark.llm,'call',match)
    with pytest.raises(RuntimeError,match='changed during benchmark'):
        benchmark.score('paper')
    assert not (stage/'extraction_benchmark.json').exists()

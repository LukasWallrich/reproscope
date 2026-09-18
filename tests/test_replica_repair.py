import json,sys
from types import SimpleNamespace
from pathlib import Path
from reproscope import replica_repair as module,llm
from reproscope.executor_repair import SourcePatch,SourceChange


def test_repair_only_reads_approved_inputs_and_source_and_archives_outputs(tmp_path,monkeypatch):
    from reproscope import isolation
    from reproscope.stage1 import replicas
    work=tmp_path/'work';out=work/'out';out.mkdir(parents=True);(work/'data').mkdir()
    (work/'CONTRACT.json').write_text('{"analyses":[]}')
    (work/'TASK.md').write_text('Synthetic task')
    script=out/'analysis.py';script.write_text('print("old implementation")\n')
    (out/'results.json').write_text('UNSUPPLIED_RESULT_TARGET')
    (tmp_path/'agent.log').write_text(json.dumps({'version':'bounded-generation-3','tool_surface':'none','model_calls':['initial']}))
    monkeypatch.setenv('REPROSCOPE_REPLICA_REPAIR_TIER','contract_repair')
    monkeypatch.setattr(module.config,'tier',lambda _:SimpleNamespace(route='claude_p',model='repair',model_dump=lambda:{'model':'repair'}))
    calls=[]
    def call(step,prompt,**kw):
        assert 'UNSUPPLIED_RESULT_TARGET' not in prompt
        assert 'old implementation' in prompt and 'Synthetic task' in prompt
        calls.append(kw)
        return llm.LLMResult(text='',parsed=SourcePatch(changes=[SourceChange(filename='analysis.py',old_text='old implementation',new_text='correct implementation')]),ledger_id='repair-call')
    monkeypatch.setattr(module.llm,'call',call)
    monkeypatch.setattr(replicas,'prepare_env',lambda *a:{'error':None,'interpreter':sys.executable,'env':{}})
    monkeypatch.setattr(isolation,'command',lambda cmd,*a:(cmd,{'enforced':True}))
    monkeypatch.setattr(replicas,'generation_validation',lambda *a,**kw:[])
    events=module.repair(work,'fixture',tmp_path,{},['Synthetic method failure'])
    assert len(events)==1 and events[0]['validation_errors']==[]
    assert 'correct implementation' in script.read_text()
    assert not (out/'results.json').exists()
    assert list((tmp_path/'source_repairs').glob('*/before_1/results.json'))
    assert calls[0]['agentic'] is False
    assert json.loads((tmp_path/'agent.log').read_text())['model_calls']==['initial','repair-call']


def test_no_repair_without_opt_in_or_errors(tmp_path,monkeypatch):
    monkeypatch.delenv('REPROSCOPE_REPLICA_REPAIR_TIER',raising=False)
    assert module.repair(tmp_path,'fixture',tmp_path,{},['failure'])==[]
    monkeypatch.setenv('REPROSCOPE_REPLICA_REPAIR_TIER','anything')
    assert module.repair(tmp_path,'fixture',tmp_path,{},[])==[]

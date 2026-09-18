import json
import subprocess
from pathlib import Path
from pydantic import BaseModel
from reproscope import llm

class Result(BaseModel):
    ok: bool


def run_args(monkeypatch,tmp_path,*,agentic=False,images=None):
    captured={}
    def fake_run(cmd,prompt,cwd,timeout,env):
        captured.update(cmd=cmd,prompt=prompt,cwd=cwd)
        if images:
            assert cwd!=tmp_path
            assert [p.read_bytes() for p in sorted(cwd.glob('*.png'))]==[b'image']
        result={'type':'result','is_error':False,'structured_output':{'ok':True}}
        return subprocess.CompletedProcess(cmd,0,json.dumps(result),'')
    monkeypatch.setattr(llm,'_run',fake_run)
    llm._claude_p('Use supplied evidence.','fable',schema=Result,images=images,system=None,cwd=tmp_path,agentic=agentic,timeout_s=30,max_turns=2,env_extra=None)
    return captured


def test_text_only_call_disables_tools_and_customizations(monkeypatch,tmp_path):
    got=run_args(monkeypatch,tmp_path)
    assert '--safe-mode' in got['cmd']
    assert got['cmd'][got['cmd'].index('--tools')+1]==''
    assert 'root keys: ok' in got['prompt'] and 'wrap it in a parameter field' in got['prompt']
    assert 'Use the StructuredOutput tool directly' in got['prompt']
    assert 'do not first emit the JSON as ordinary text' in got['prompt']


def test_image_call_has_only_read_in_a_restricted_image_directory(monkeypatch,tmp_path):
    image=tmp_path/'page.png';image.write_bytes(b'image')
    got=run_args(monkeypatch,tmp_path,images=[image])
    assert got['cmd'][got['cmd'].index('--tools')+1]=='Read'
    assert '--restricted' in got['cmd'] and '--safe-mode' in got['cmd']
    assert not got['cwd'].exists()


def test_agentic_call_has_explicit_tools_and_no_personal_customizations(monkeypatch,tmp_path):
    got=run_args(monkeypatch,tmp_path,agentic=True)
    assert '--safe-mode' in got['cmd']
    assert got['cmd'][got['cmd'].index('--tools')+1]=='Bash,Read,Write,Edit,Glob,Grep'


def test_structured_output_failure_preserves_subtype_and_is_not_repeated(monkeypatch,tmp_path):
    calls=[];entries=[]
    def fake_run(cmd,prompt,cwd,timeout,env):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd,1,json.dumps({'type':'result','is_error':True,'subtype':'error_max_structured_output_retries','result':None}),'')
    monkeypatch.setattr(llm,'_run',fake_run)
    monkeypatch.setattr(llm.ledger,'record',lambda paper,row:entries.append(row) or 'recorded')
    result=llm.call('test','Return the requested object.',paper_id='test',stage='0',route='claude_p',model='haiku',schema=Result)
    assert len(calls)==1 and len(entries)==1
    assert not result.ok and 'error_max_structured_output_retries' in result.error


def test_output_limit_failure_is_not_treated_as_transient(monkeypatch):
    calls=[]
    def fail(*args,**kwargs):
        calls.append(1)
        raise llm.LLMError("Claude's response exceeded the 32000 output token maximum")
    monkeypatch.setattr(llm,'_claude_p',fail)
    monkeypatch.setattr(llm.ledger,'record',lambda *args:'recorded')
    result=llm.call('test','Extract evidence.',paper_id='test',stage='0',route='claude_p',model='haiku')
    assert len(calls)==1 and not result.ok

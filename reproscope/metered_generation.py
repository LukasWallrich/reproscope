"""Opt-in, tool-free generation with a shared conservative API budget.

The budget file is an explicit operator authorization, shared across run IDs.
Pending/unknown charges retain their full reservation, including after a crash.
"""
import fcntl,json,os,time,uuid
from pathlib import Path
import httpx
from . import llm,ledger,provenance


def enabled():
    return bool(os.environ.get('REPROSCOPE_METERED_BUDGET_FILE'))


def update_budget(path,operation):
    with Path(path).open('r+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        data=json.load(stream)
        result=operation(data)
        stream.seek(0);json.dump(data,stream,indent=2);stream.write('\n');stream.truncate()
        return result


def reserve(path,amount,identity,**metadata):
    def operation(data):
        events=data.setdefault('calls',[])
        used=float(data.get('baseline_usd',0))+sum(e.get('cost_usd',e['reserved_usd']) for e in events)
        if used+amount>float(data['cap_usd']):raise ValueError('Shared metered generation budget cannot cover this request')
        events.append({'id':identity,'reserved_usd':amount,'state':'pending',**metadata})
    update_budget(path,operation)


def call(prompt,*,paper_id,schema,log_path,stage='3',step='execute:metered_source'):
    path=Path(os.environ['REPROSCOPE_METERED_BUDGET_FILE'])
    settings=json.loads(path.read_text());model=settings['model'];limit=int(settings.get('max_output_tokens',16000))
    payload,strict=llm.schema_payload(schema)
    body={'model':model,'messages':[{'role':'user','content':prompt}],
        'max_tokens':limit,'reasoning':{'effort':'medium'},'usage':{'include':True},
        'provider':{'require_parameters':True},
        'response_format':{'type':'json_schema','json_schema':{'name':schema.__name__,'strict':strict,'schema':payload}}}
    with httpx.Client(timeout=30) as client:
        response=client.get('https://openrouter.ai/api/v1/models');response.raise_for_status()
        entry=next(m for m in response.json()['data'] if m['id']==model)
    price=entry['pricing'];rates=[price]+price.get('overrides',[])
    input_rate=max(float(r.get('prompt',price['prompt'])) for r in rates)
    output_rate=max(float(r.get('completion',price['completion'])) for r in rates)
    # A UTF-8 byte bound plus schema/transport allowance exceeds BPE token count.
    upper=(len(json.dumps(body,ensure_ascii=False).encode())+4096)*input_rate+limit*output_rate
    identity=uuid.uuid4().hex;reserve(path,upper,identity,paper_id=paper_id,model=model)
    start=time.monotonic();data={};error=None;parsed=None;text='';cost=None
    try:
        with httpx.Client(timeout=900) as client:
            response=client.post(llm.OPENROUTER_URL,headers={'Authorization':'Bearer '+llm.openrouter_key()},json=body)
            response.raise_for_status();data=response.json()
        usage=data.get('usage') or {};cost=usage.get('cost')
        choice=data['choices'][0];text=choice['message'].get('content') or ''
        if choice.get('finish_reason') not in ('stop',None):raise ValueError('Generation ended with '+str(choice.get('finish_reason')))
        parsed=llm.validate(schema,text)
    except Exception as exc:
        error=type(exc).__name__+': '+str(exc)
    usage=data.get('usage') or {}
    row={'stage':stage,'step':step,'route':'openrouter','model':model,
        'ok':error is None,'error':error,'duration_s':time.monotonic()-start,
        'tokens_in':usage.get('prompt_tokens',0),'tokens_out':usage.get('completion_tokens',0),
        'cost_usd':float(cost) if cost is not None else upper,'cost_source':'api' if cost is not None else 'reserved_unknown',
        'prompt_hash':provenance.digest(prompt),'budget_reservation':identity,'tool_surface':'none'}
    call_id=ledger.record(paper_id,row)
    def finish(budget):
        event=next(e for e in budget['calls'] if e['id']==identity)
        event.update(paper_id=paper_id,ledger_id=call_id,state='settled' if cost is not None else 'unknown')
        if cost is not None:event['cost_usd']=float(cost)
    update_budget(path,finish)
    Path(log_path).write_text(json.dumps({'response':data,'error':error,'request_contract':{'model':model,'max_tokens':limit,'tool_surface':'none'},'ledger_id':call_id},indent=2)+'\n')
    return llm.LLMResult(text=text,parsed=parsed,ok=error is None,error=error,ledger_id=call_id,route='openrouter',model=model,
        cost_usd=row['cost_usd'],duration_s=row['duration_s'])

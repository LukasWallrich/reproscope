"""Exact factor/level coverage for independently screened multiverse choices."""
import copy,json
from collections import defaultdict
from pydantic import BaseModel,ConfigDict
from . import llm,response_cache,provenance
from .stage3.multiverse import ScreenedLevel,Incompatible

class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    factor:str
    level:ScreenedLevel
class Completion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    decisions:list[Decision]
    incompatible:list[Incompatible]=[]


def normalise(proposed,screen):
    expected={(f['name'],l['value']) for f in proposed['factors'] for l in f['levels']}
    expected|={(a['factor'],a['canonical']) for a in screen.get('adjustments',[]) if a.get('kind')=='add_level' and a.get('canonical')}
    owners=defaultdict(set)
    for f,l in expected:owners[l].add(f)
    rows=defaultdict(list);notes=[];extras=[]
    for f in screen.get('factors',[]):
        for l in f.get('levels',[]):
            key=(f['name'],l['value'])
            if key not in expected and len(owners[l['value']])==1:
                corrected=(next(iter(owners[l['value']])),l['value'])
                notes.append({'from':list(key),'to':list(corrected),'rule':'unique declared level owner'})
                key=corrected
            if key not in expected:extras.append(list(key));continue
            if l not in rows[key]:rows[key].append(l)
    pending=sorted(k for k in expected if len(rows[k])!=1)
    out=copy.deepcopy(screen);factors=[]
    for name in dict.fromkeys([f['name'] for f in proposed['factors']]+[f for f,_ in sorted(expected)]):
        factors.append({'name':name,'levels':[copy.deepcopy(rows[k][0]) for k in sorted(expected) if k[0]==name and len(rows[k])==1]})
    out['factors']=factors
    out.setdefault('_identity_normalisation',[]).extend(notes)
    if extras:out.setdefault('_discarded_unrequested_levels',[]).extend(extras)
    return out,pending,{f'{f}={l}':rows[(f,l)] for f,l in pending}


def complete(paper_id,proposed,screen,contract,schema,folder):
    out,pending,conflicts=normalise(proposed,screen)
    if not pending:return out
    wanted=set(pending);folder.mkdir(parents=True,exist_ok=True)
    prompt=('Complete only these missing or conflicting multiverse screening decisions under the same scientific standard. '
        'Return exactly ONE level record for each requested factor/value pair. Do not put a level under a new factor named after that level. '
        'Conditional effect groups for raw/rank or different adjustments belong in the existing reporting_rules, not duplicate copies of a factor level. '
        'Use generic level metadata where another factor determines scale; preserve the explicit conditional reporting rules. '
        'Judge scientific validity, rejecting indefensible/underspecified procedures explicitly. A level cannot disappear silently. '
        'Include any additional necessary incompatible combinations. Do not change other accepted decisions or select according to results; no computed results are supplied.\nRequired pairs:\n'
        +json.dumps(pending)+'\nConflicting records:\n'+json.dumps(conflicts)+'\nFocal methods:\n'+contract+'\nData schema:\n'+schema
        +'\nOriginal proposal:\n'+json.dumps(proposed['factors'])+'\nExisting screen and conditional reporting rules:\n'+json.dumps(screen))
    feedback='';calls=[]
    for attempt in range(2):
        shown=prompt+feedback;key=response_cache.key(shown,Completion,[],'strong_alt');path=folder/f'{key}.response.json'
        cached=response_cache.read(path,key,Completion)
        if cached:answer,cid=cached
        else:
            r=llm.call('screen:scope_repair',shown,paper_id=paper_id,stage='3',tier='strong_alt',schema=Completion,large_context=True,timeout_s=900,log_path=path.with_suffix('.log'))
            answer,cid=r.parsed,r.ledger_id
            if answer:response_cache.write(path,key,answer,cid or '')
        if cid:calls.append(cid)
        found=[(r.factor,r.level.value) for r in answer.decisions] if answer else []
        if len(found)!=len(wanted) or set(found)!=wanted:
            feedback='\nReturn exactly these requested factor/level pairs once each: '+json.dumps(pending);continue
        by_factor={f['name']:f for f in out['factors']}
        for r in answer.decisions:by_factor[r.factor]['levels'].append(r.level.model_dump())
        out['incompatible']=[*out.get('incompatible',[]),*[r.model_dump() for r in answer.incompatible]]
        out['_screen_completion_calls']=[*screen.get('_screen_completion_calls',[]),*calls]
        (folder/f'{key}.history.json').write_text(json.dumps({'original_screen':screen,'required_pairs':pending,'model_calls':calls,'completed_screen_hash':provenance.digest(out)},indent=2)+'\n')
        return out
    raise ValueError('Screen completion failed exact factor/level coverage.')

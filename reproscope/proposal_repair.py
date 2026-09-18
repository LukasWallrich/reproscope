"""One source-only operational repair per multiverse decision, then fresh screening."""
import copy,json,os
from typing import Literal
from pydantic import BaseModel,ConfigDict
from . import llm,response_cache,provenance

class Revision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    factor:str
    level:str
    action:Literal['repair','defer']
    how:str|None
    standard_method:str|None
    compatibility_conditions:list[str]
    reason:str
class Revisions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revisions:list[Revision]


def candidates(proposed,screen):
    attempted=set(proposed.get('_operational_repaired_factors',[]))
    originals={(f['name'],l['value']):(f,l) for f in proposed['factors'] for l in f['levels']}
    rows=[]
    for f in screen.get('factors',[]):
        if f['name'] in attempted:continue
        for l in f['levels']:
            key=(f['name'],l['value'])
            if key not in originals or l.get('verdict')!='rejected' or l.get('rejection_kind') not in {'operational','nonstandard'}:continue
            factor,level=originals[key]
            rows.append({'factor':f['name'],'level':l['value'],'decision_field':factor.get('field'),
                'original_how':level.get('how'),'rejection_kind':l['rejection_kind'],'missing_details':l.get('missing_details',[])})
    return rows


def apply(proposed,rows,revisions):
    expected={(r['factor'],r['level']):r for r in rows};found=[(r.factor,r.level) for r in revisions]
    if len(found)!=len(expected) or set(found)!=set(expected):raise ValueError('Operational repair must cover exactly the eligible existing levels; no new factors or levels.')
    out=copy.deepcopy(proposed)
    levels={(f['name'],l['value']):l for f in out['factors'] for l in f['levels']}
    for r in revisions:
        if r.action=='defer':continue
        if not r.how or not r.how.strip():raise ValueError('Repair needs a complete operational definition.')
        if expected[(r.factor,r.level)]['rejection_kind']=='nonstandard' and not r.standard_method:
            raise ValueError('A nonstandard procedure needs a named standard replacement at the same decision node.')
        level=levels[(r.factor,r.level)]
        level['how']=r.how
        level['method_reference']=r.standard_method
        level['compatibility_conditions']=r.compatibility_conditions
    out['_operational_repaired_factors']=sorted(set(proposed.get('_operational_repaired_factors',[]))|{r['factor'] for r in rows})
    return out


def repair(paper_id,proposed,screen,contract,schema,folder):
    rows=candidates(proposed,screen)
    if not rows:return None
    tier=os.environ.get('REPROSCOPE_METHOD_REPAIR_TIER','strong')
    prompt=('Repair only the operational definitions of these existing multiverse options. Factor names and level values are immutable decision nodes. '
        'The supplied rejection types distinguish missing detail from substantive scientific rejection; substantively rejected choices are not eligible. '
        'For nonstandard procedures substitute a named, citable standard method implementing the SAME decision. Do not change the scientific question to rehabilitate a choice. '
        'State exact algorithm, parameters, variables, order of operations, uncertainty calculation and compatibility restrictions. Preserve required covariates. '
        'Separate point estimation from testing and intervals; state valid combinations with the other decisions. Raw-scale outlier handling can remain comparable where substantively justified; transformed/rank effects require explicit separate interpretation. '
        'No analysis results or numerical targets are supplied. There is no dimension quota. Use defer when the original intent cannot be repaired defensibly. '
        'Return every eligible factor/level exactly once. A fresh independent screener will judge the resulting definitions without seeing this repair discussion.\nEligible options:\n'
        +json.dumps(rows)+'\nFocal methods:\n'+contract+'\nData schema:\n'+schema+'\nOther decisions for compatibility:\n'
        +json.dumps(proposed['factors']))
    folder.mkdir(parents=True,exist_ok=True);feedback=''
    for attempt in range(2):
        shown=prompt+feedback;key=response_cache.key(shown,Revisions,[],tier)
        path=folder/f'{key}.response.json';saved=response_cache.read(path,key,Revisions)
        if saved:out,cid=saved
        else:
            result=llm.call('enumerate:operational_repair',shown,paper_id=paper_id,stage='3',tier=tier,
                schema=Revisions,large_context=True,timeout_s=900,log_path=path.with_suffix('.log'))
            out,cid=result.parsed,result.ledger_id
            if out:response_cache.write(path,key,out,cid or '')
        try:
            if out is None:raise ValueError('No structured operational revision returned.')
            revised=apply(proposed,rows,out.revisions)
        except ValueError as exc:feedback='\nCorrect the scope/schema failure: '+str(exc);continue
        receipt={'parent_proposal':provenance.digest(proposed),'screen':screen,'proposal':proposed,'eligible':rows,
            'revisions':out.model_dump(),'model_call':cid,'tier':tier,'status':'awaiting_independent_rescreen'}
        (folder/f'{key}.history.json').write_text(json.dumps(receipt,indent=2)+'\n')
        revised['_operational_repair_calls']=[*proposed.get('_operational_repair_calls',[]),cid]
        return revised
    raise ValueError('Operational proposal repair failed its bounded scope.')

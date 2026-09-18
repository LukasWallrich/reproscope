"""Source-only coefficient identities, resolved outside numerical verification."""
import copy,json,re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from . import config,llm,paths,response_cache,provenance

class Term(BaseModel):
    model_config=ConfigDict(extra='forbid')
    analysis_id:str
    state:Literal['resolved','ambiguous']
    binding_field:str|None=Field(pattern=r'^(?:predictors|covariates)\[\d+\]$',description='Exact contract_field key such as predictors[2], never a deposited column name.')
    evidence_quote:str=Field(description='One exact contiguous substring of a source field. No field labels, added quotation marks, paraphrases, or combined quotes.')
    reason:str
class Terms(BaseModel):
    model_config=ConfigDict(extra='forbid')
    terms:list[Term]


def requested(analysis):
    text=json.dumps({k:analysis.get(k) for k in ('design','model_type')})
    return bool(re.search(r'regress|\bOLS\b',text,re.I) and any(
        q.get('quantity_kind') in {'coefficient','t','ci_bound'} for q in analysis.get('quantities',[])))


def validate(rows,analyses):
    expected={a['analysis_id']:a for a in analyses};errors=[]
    if len(rows)!=len(expected) or {r.analysis_id for r in rows}!=set(expected):
        return ['Return each requested analysis exactly once.']
    for r in rows:
        a=expected[r.analysis_id]
        fields={b['contract_field'] for b in a['variable_bindings'] if b.get('chosen') and re.match(r'(predictors|covariates)\[',b['contract_field'])}
        source=' '.join(str(a.get(k) or '') for k in ('analysis_label','model_type'))+' '+str(a.get('design',{}).get('contrast') or '')
        if r.state=='resolved' and (r.binding_field not in fields or not r.evidence_quote.strip() or r.evidence_quote not in source):
            errors.append(r.analysis_id+': use one of these exact binding fields '+json.dumps(sorted(fields))
                +'; evidence_quote must be ONE unchanged contiguous substring of analysis_label, model_type or design.contrast, with no field labels, added quotation marks or joined excerpts. Received: '+r.evidence_quote)
    return errors


def resolve(paper_id,packet):
    analyses=[{k:a.get(k) for k in ('analysis_id','analysis_label','model_type','design','variable_bindings')}
              for a in packet.get('analyses',[]) if requested(a)]
    if not analyses:return {'targets':{},'model_calls':[]}
    folder=paths.run_dir(paper_id,1)/'coefficient_identity';folder.mkdir(exist_ok=True)
    prompt=('Identify the exact requested regression coefficient from each blinded method contract. No plans, results, or paper values are supplied. '
        'Select its existing predictor/covariate binding_field. The first predictor is not necessarily the requested term: use the analysis label and explicit contrast. '
        'Do not substitute the model focal predictor for a requested covariate coefficient. Use ambiguous for genuinely unresolved or unsupported interaction/level contrasts. '
        'Return every analysis exactly once, quoting the source label, model_type or design.contrast verbatim.\n'+json.dumps(analyses))
    def reading(tier,suffix):
        feedback='';calls=[]
        for attempt in range(2):
            shown=prompt+feedback;key=response_cache.key(shown,Terms,[],tier)
            path=folder/f'{suffix}_{key[:20]}.json';saved=response_cache.read(path,key,Terms)
            if saved:out,cid=saved
            else:
                r=llm.call('coefficient_identity',shown,paper_id=paper_id,stage='1',tier=tier,schema=Terms,timeout_s=600)
                out,cid=r.parsed,r.ledger_id
                if out:response_cache.write(path,key,out,cid or '')
            if cid:calls.append(cid)
            errors=validate(out.terms,analyses) if out else ['No structured response.']
            if not errors:return {t.analysis_id:t.model_dump() for t in out.terms},calls
            feedback='\nCorrect these scope/evidence errors: '+json.dumps(errors)
        raise ValueError('Coefficient identity resolution failed: '+json.dumps(errors))
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(reading,tier,str(i)) for i,tier in enumerate(('strong','mid'))]
        readings=[j.result() for j in jobs]
    targets={}
    for a in analyses:
        aid=a['analysis_id'];left,right=[r[0][aid] for r in readings]
        bound={b['contract_field']:(b.get('chosen'),b.get('file'),b.get('table')) for b in a['variable_bindings']}
        if left['state']==right['state']=='resolved' and bound[left['binding_field']]==bound[right['binding_field']]:
            targets[aid]={**left,'independent_evidence':[left['evidence_quote'],right['evidence_quote']]}
        else:targets[aid]={'state':'ambiguous','binding_field':None,'reason':'Independent source-only term resolutions disagree or are ambiguous.','readings':[left,right]}
    out={'targets':targets,'model_calls':[c for _,calls in readings for c in calls],
         'inputs':provenance.digest(analyses),'scope':'Two independent readings of blinded method identities; no numerical outputs or published targets.'}
    (folder/'report.json').write_text(json.dumps(out,indent=2)+'\n')
    return out


def attach(packet,receipt):
    out=copy.deepcopy(packet)
    for a in out.get('analyses',[]):
        if requested(a):a['coefficient_target']=receipt.get('targets',{}).get(a['analysis_id'],{'state':'ambiguous','reason':'Source-only term resolution missing.'})
    return out

"""Independent source-only review of unassigned empirical analysis definitions.

No replica, reproduced value or execution artifact is an input to this step.
An unspecified method is distinct from an unattempted computational duty.
"""
import json
from typing import Literal
from pydantic import BaseModel,ConfigDict
from . import paths,provenance,response_cache,llm
from .source_mapping import quotation_located

class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    claim_id:str
    status:Literal['method_unspecified','recoverable','sources_conflict']
    missing_fields:list[str]
    candidate_analysis_ids:list[str]
    source_quotes:list[str]
    reason:str

class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    decisions:list[Decision]


CONTRACT_FIELDS={'analysis_id','study_id','claim_ids','outcome','predictors','covariates','design','identity','analysis_label','model_type','sample_rule'}

def source_payload(claims,assignments,contracts,paper):
    pending=[u for u in assignments if u['reason']!='not_an_analysis' and any(c['claim_id']==u['claim_id'] and c['state']=='complete' for c in claims)]
    fields={'claim_id','study_id','quantity_kind','value','precision','comparator','source_quote','target_outcome','target_contrast','target_model','description'}
    return {'unassigned':pending,'source_records':[{k:v for k,v in c.items() if k in fields} for c in claims],
            'contracts':[{k:c.get(k) for k in sorted(CONTRACT_FIELDS)} for c in contracts],'paper':paper}

def source_inputs(stage):
    claims=json.loads((stage/'claims.json').read_text())
    assignments=json.loads((stage/'contract_assignments.json').read_text()) if (stage/'contract_assignments.json').exists() else {}
    contracts=json.loads((stage/'contracts.json').read_text())
    paper=(stage/'paper.txt').read_text() if (stage/'paper.txt').exists() else (paths.corpus_dir(stage.parent.name)/'paper.txt').read_text()
    return source_payload(claims,assignments.get('unassigned',[]),contracts,paper)


def run(paper_id):
    return review(paper_id,source_inputs(paths.run_dir(paper_id,0)))

def review(paper_id,inputs):
    stage=paths.run_dir(paper_id,0);target=stage/'method_availability.json'
    if not inputs['unassigned']:return {'decisions':[],'complete':True}
    prompt=('Independently reconsider each unassigned source quantity using the complete paper and source-defined contracts. No computed results or replica artifacts are supplied. '
        'A prior methods_insufficient label is only a proposal. Search the source context and cross-references for the missing identity. '
        'Return recoverable if a fully identified existing analysis can be established; name it and quote the source basis so the pipeline can repair assignment. '
        'Source-to-source numerical concordance can only confirm a candidate nominated by study, outcome family, predictor, sample, statistic and model/covariates; never search on a matching number alone. '
        'Such a restatement link requires a closed list of possible measures, at most one open identity field, every printed quantity compatible, and exactly one matching candidate with the other candidates printed and excluded. Any p-value implied by source statistics is a consistency check, not independent evidence. '
        'If required identity/method information remains absent, return method_unspecified with the exact missing fields, plausible existing candidate analyses and a located quote showing the unresolved wording. '
        'Use sources_conflict for actual contradictory source definitions. Never guess an identity to achieve coverage. All quantities remain in reporting denominators; method_unspecified is unavailable method information, not a successful reproduction. '
        'Give separate short verbatim contiguous quotes in source_quotes for each supporting passage, never join separate passages with | or paraphrase inside a quote. Return each requested claim_id exactly once.\n'+json.dumps(inputs,separators=(',',':')))
    key=response_cache.key(prompt,Review,[],'strong');cache=stage/'method_availability.response.json'
    saved=response_cache.read(cache,key,Review)
    if saved:response,cid=saved
    else:
        r=llm.call('method_availability',prompt,paper_id=paper_id,stage='0',tier='strong',schema=Review,large_context=True,
            timeout_s=1800,log_path=stage/'logs/method_availability.log')
        response,cid=r.parsed,r.ledger_id
    expected={u['claim_id'] for u in inputs['unassigned']};analyses={c['analysis_id'] for c in inputs['contracts']}
    if response is None or len(response.decisions)!=len(expected) or {d.claim_id for d in response.decisions}!=expected:
        raise ValueError('method availability review failed exact requested scope')
    response_cache.write(cache,key,response,cid or '')
    decisions=[]
    for d in response.decisions:
        anchored=bool(d.source_quotes) and all(quotation_located(q,inputs['paper']) for q in d.source_quotes)
        valid=anchored and set(d.candidate_analysis_ids)<=analyses and bool(d.reason.strip())
        if d.status=='method_unspecified':valid=valid and bool(d.missing_fields)
        decisions.append({**d.model_dump(),'source_anchor_verified':anchored,'validated':valid})
    result={'source_fingerprint':provenance.digest(inputs),'decisions':decisions,'model_call':cid,
            'complete':all(d['validated'] and d['status']=='method_unspecified' for d in decisions),
            'scope':'Independent review of source method identity; no computed results supplied.'}
    target.write_text(json.dumps(result,indent=2)+'\n');return result


def current(stage):
    path=stage/'method_availability.json'
    if not path.exists():return {}
    result=json.loads(path.read_text())
    return result if result.get('source_fingerprint')==provenance.digest(source_inputs(stage)) else {}

"""Source-linked reader copy, separate from numerical evidence and verdicts."""
import json
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from .. import paths, artifacts, config, llm, provenance

class Topic(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(max_length=100)
    finding:str=Field(max_length=450)
    cause:str=Field(max_length=500)
    next_check:str=Field(max_length=300)
    group_ids:list[str]=Field(min_length=1)

class Copy(BaseModel):
    model_config=ConfigDict(extra='forbid')
    topics:list[Topic]=Field(min_length=1,max_length=12)
    factor_labels:dict[str,str]
    level_labels:dict[str,dict[str,str]]
    effect_labels:dict[str,str]
    null_labels:dict[str,str]

PROMPT='''Write concise, self-contained reader copy for an automated statistical reproduction report. The reader wants to understand discrepancies, their root causes and the evidence needed to resolve them. Group the supplied diagnosis groups into at most 12 coherent substantive topics, covering every supplied evidence ID (G001, G002, ...) exactly once in group_ids. Copy those IDs verbatim; claim IDs and analysis IDs are not evidence IDs. Do not merge a demonstrated arithmetic/reporting contradiction with uncertain reconstruction assumptions. Aim for titles under 70 characters, findings under 300, causes under 350 and next checks under 220. Each field should add information rather than repeat the previous field. Group unavailable quantities by their shared missing input or coding key. Titles describe the problem and affected result in plain language, never internal IDs or vague phrases such as "coverage unavailable". Each finding says what is known. Cause separates established mechanism from plausible unresolved causes. Next check names the missing input or test that would resolve the uncertainty. Do not accuse author code when none is provided. No revision history, model commentary, long strings of IDs, boilerplate or a yes/no answer with no stated question. Do not introduce numbers: the renderer supplies all numerical comparisons directly from verified artifacts. Do not reclassify evidence or claim unsupported verification. The supplied source quotes and contracts set the scope; do not generalise beyond them. Provide short readable factor, level, effect-group and null-group labels, preserving distinctions of units, estimators and null hypotheses. Spell out outcome names and study labels using focal_analysis: do not label a curve with internal symbols or abbreviations such as "Exp1: v". State the effect unit or coefficient (for example letters per second, log ratio, rank-biserial correlation). A raw-input rank effect is still dimensionless; distinguish its input scale from its effect unit. Keep labels under 110 characters. A location-estimator label must name the effect estimator, not merely its associated significance test. Full and semi-partial, Pearson and ranks remain distinct. Trimming and outlier handling can share a raw-unit effect group with clearly stated estimator labels. Describe absent records only as unavailable in the supplied deposit, unless the source establishes that they were never retained. Labels for inferred missing-item exclusions must say detectable filled cells, not complete original cases. A fixed source threshold is not a reconstructed test family. No source access or tools; use only this payload. Return the schema.'''


def inputs(base):
    def read(p,d=None):return json.loads((base/p).read_text()) if (base/p).exists() else (d or {})
    diagnosis=read('stage1/diagnosis.json');inventory=read('stage1/divergence_inventory.json');grid=read('stage3/grid.json')
    focal=read('stage3/focal.json');contracts=read('stage0/contracts.json',[])
    focal_analysis=next((c for c in contracts if isinstance(c,dict) and c.get('analysis_id')==focal.get('analysis_id')), {}) if isinstance(contracts,list) else {}
    return {'focal_analysis':{k:focal_analysis.get(k) for k in ('outcome','predictors','covariates','identity','study_id')},'diagnoses':diagnosis.get('diagnoses',[]),'inventory':inventory.get('groups',[]),
        'factors':grid.get('factors',[]),'reporting_contracts':grid.get('reporting_contracts',{})}


def key(payload):return provenance.digest({'input':payload,'prompt':PROMPT,'schema':Copy.model_json_schema()})


def validate(copy,payload):
    from collections import Counter
    expected={d['group_id'] for d in payload['diagnoses']}
    got=[i for t in copy['topics'] for i in t['group_ids']]
    if set(got)!=expected or any(n!=1 for n in Counter(got).values()):raise ValueError('editorial topics must cover every diagnosis exactly once; missing='+json.dumps(sorted(expected-set(got)))+'; unexpected='+json.dumps(sorted(set(got)-expected))+'; duplicated='+json.dumps([k for k,n in Counter(got).items() if n>1]))
    for t in copy['topics']:
        if any('never retained' in t.get(k,'').lower() or 'never collected' in t.get(k,'').lower() for k in ('finding','cause','next_check')):
            raise ValueError('State only that records are unavailable in the supplied deposit; do not infer permanent retention or collection history.')
    for f in payload['factors']:
        if f['name'] not in copy['factor_labels'] or set(copy['level_labels'].get(f['name'],{}))!={l['value'] for l in f['levels']}:raise ValueError('reader labels must cover each factor and level')
    return copy


def presentation_payload(payload):
    """Give the writer compact source evidence and unambiguous linking IDs."""
    aliases={d['group_id']:f'G{i:03d}' for i,d in enumerate(payload['diagnoses'],1)}
    claim_fields={'claim_id','study_id','quantity_kind','value','comparator','source_quote','source_region','location','description','target_outcome','target_contrast','aggregation'}
    def clean(value):
        if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in {'meta','extraction','source_bbox','source_token_id'} and v is not None}
        if isinstance(value,list):return [clean(v) for v in value]
        return value
    shown=clean(payload)
    for d in shown['diagnoses']:d['group_id']=aliases[d['group_id']]
    shown['inventory']=[{**clean(g),'group_id':aliases[g['group_id']],
        'claims':[{k:clean(v) for k,v in c.items() if k in claim_fields and v is not None} for c in g.get('claims',[])]}
        for g in payload['inventory'] if g['group_id'] in aliases]
    shown['required_evidence_ids']=list(aliases.values())
    return shown,{v:k for k,v in aliases.items()}


def restore_links(copy,aliases):
    for t in copy['topics']:
        unknown=[i for i in t['group_ids'] if i not in aliases]
        if unknown:raise ValueError('Use the required evidence IDs verbatim; unexpected IDs: '+json.dumps(unknown))
    for t in copy['topics']:t['group_ids']=[aliases[i] for i in t['group_ids']]
    return copy


def prepare(paper_id):
    base=paths.run_dir(paper_id);payload=inputs(base)
    if not payload['diagnoses']:return None
    folder=base/'report/editorial';folder.mkdir(parents=True,exist_ok=True);sha=key(payload);path=folder/(sha+'.json')
    if path.exists():return validate(json.loads(path.read_text())['copy'],payload)
    spec=config.tier('mid');feedback='';shown,aliases=presentation_payload(payload)
    for attempt in range(1,3):
        result=llm.call('reader_evidence_copy',PROMPT+'\n'+json.dumps(shown)+'\n'+feedback,paper_id=paper_id,stage='report',
            route=spec.route,model=spec.model,agentic=False,schema=Copy,large_context=True,timeout_s=900,log_path=folder/f'{sha}-{attempt}.log')
        if not result.ok or result.parsed is None:raise RuntimeError('Report editorial pass failed: '+str(result.error))
        copy=result.parsed.model_dump()
        try:restore_links(copy,aliases);validate(copy,payload)
        except ValueError as exc:feedback=str(exc)+' Required evidence IDs: '+json.dumps(list(aliases));continue
        path.write_text(json.dumps({'input_sha256':sha,'copy':copy,'model_call':result.ledger_id},indent=2)+'\n');return copy
    raise ValueError('report editorial copy did not satisfy evidence coverage')


def load(base):
    payload=inputs(base);path=base/'report/editorial'/(key(payload)+'.json')
    if not path.exists():return {}
    return validate(json.loads(path.read_text())['copy'],payload)

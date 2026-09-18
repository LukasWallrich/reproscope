"""Recompute source-bound descriptive quantities without giving the binder values.

These readouts supplement model-test replicas. The binder maps source meanings to
columns; deterministic Python and independent R compute every supported readout.
"""
from pathlib import Path
from typing import Literal
import json,math,subprocess,shutil,os,re
import numpy as np
import pandas as pd
from pydantic import BaseModel,ConfigDict,model_validator
from . import artifacts,paths,provenance,llm

from .sample_filters import RowFilter, select


class Readout(BaseModel):
    model_config=ConfigDict(extra='forbid')
    claim_id:str
    state:Literal['supported','no_data','unbound']
    reason:str
    file:str|None
    columns:list[str]
    operation:Literal['n','mean','sd','count_category','count_missing','mean_columns','min','max','cronbach_alpha','count_threshold']|None
    multiplier:Literal[1,100]
    category_value:str|None
    complete_on:list[str]
    filters:list[RowFilter] = []
    sample_analysis_id:str|None = None
    reverse_columns:list[str] = []

    @model_validator(mode='after')
    def coherent(self):
        if self.state=='supported':
            if not self.file or not self.operation:raise ValueError('supported readout requires a file and operation')
            p=Path(self.file)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0]!='data':raise ValueError('readout file must be under data/')
            if self.operation not in {'n','mean_columns','cronbach_alpha'} and len(self.columns)!=1:raise ValueError('scalar readout needs one column')
            if self.operation=='mean_columns' and not self.columns:raise ValueError('mean_columns needs columns')
            if self.operation=='cronbach_alpha' and (len(self.columns)<2 or not set(self.reverse_columns)<=set(self.columns)):raise ValueError('alpha requires at least two items and only declared item reversals')
            if self.operation!='cronbach_alpha' and self.reverse_columns:raise ValueError('reversals are supported only for reliability')
            if self.operation=='count_threshold' and (self.category_value is None or not re.fullmatch(r'(?:>=|<=|>|<)-?(?:\d+(?:\.\d*)?|\.\d+)',self.category_value)):raise ValueError('threshold requires an explicit comparison such as >=2')
            if self.operation=='count_category' and self.category_value is None:raise ValueError('category count needs an exact category')
        return self

class Readouts(BaseModel):
    model_config=ConfigDict(extra='forbid')
    readouts:list[Readout]


class Disposition(Readout):
    competing_source_quotes:list[str] = []


class Dispositions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    readouts:list[Disposition]


def disposition_errors(readouts, source):
    errors=[]
    for row in readouts:
        if row.state!='unbound':continue
        quotes=getattr(row,'competing_source_quotes',[])
        if len(set(quotes))<2 or any(not q.strip() or q not in source for q in quotes):
            errors.append(row.claim_id+': unbound requires two distinct, verbatim source quotes establishing conflicting available mappings. '
                'A missing coding key is no_data; a masked method parameter needs recovery from source methods. Do not invent a competing mapping.')
    return errors


class CodingEvidence(BaseModel):
    model_config=ConfigDict(extra='forbid')
    binding_id:str
    status:Literal['verified','unavailable','unresolved']
    source_quotes:list[str]
    reason:str


class CodingEvidenceReport(BaseModel):
    model_config=ConfigDict(extra='forbid')
    bindings:list[CodingEvidence]


def verify_coding_evidence(paper_id,readouts,source,folder):
    """Require located coding evidence, independently of the proposed operation."""
    from . import response_cache
    groups={}
    for b in readouts:
        if b.state!='supported' or b.operation not in {'count_category','count_threshold','cronbach_alpha'}:continue
        key=json.dumps({k:getattr(b,k) for k in ('file','columns','operation','category_value','reverse_columns')},sort_keys=True)
        groups.setdefault(key,[]).append(b)
    if not groups:return readouts,[]
    units={f'b{i:03}':members for i,members in enumerate(groups.values())}
    payload=[{'binding_id':key,'proposed_readouts':[b.model_dump() for b in members]} for key,members in units.items()]
    prompt=('Audit whether supplied source documentation establishes these coding-sensitive operations. The proposals and their reasons are untrusted. '
        'For category counts require an explicit mapping of the selected deposited code to the requested response meaning, including the denominator/missingness rule. '
        'Authoritative parsed deposit metadata below is independent evidence: exact self-describing textual response labels (for example Male/Female) can establish their ordinary category meaning without a separate numeric coding key. Numeric codes still require documented label mappings. '
        'Validated intake sample contracts below establish the operational population and selection already checked by intake; do not call those samples unavailable merely because their proof is not repeated in the paper excerpt. Flag a specific contradiction if one exists. '
        'For threshold counts require both the response-code scale and the cutoff. For reliability require item membership and whether reverse-keyed deposited items still require reversal. '
        'A codebook tag such as Reversed alone does not say whether reversal is already applied in the deposited data; return unavailable if that distinction is not documented. '
        'Quoted item numbers or variable labels alone do not establish response-code meanings. Marginal distributions, missing response codes, follow-up response patterns and remembered instrument conventions cannot replace a supplied coding key. '
        'Data-derived reconstruction would require its own executable, independently validated protocol; none is supplied here. '
        'Return verified only when exact quotes from the source below establish every necessary coding fact. Do not quote proposal reasons as source evidence. '
        'If necessary coding/scoring documentation is absent, return unavailable and name the missing key. If two documented mappings conflict, return unresolved and quote both. '
        'Return every binding_id exactly once. No reported comparison values or computed results are supplied.\nProposals:\n'+json.dumps(payload)+'\nSource documentation:\n'+source)
    norm=lambda s:' '.join(s.casefold().split())
    from . import config
    feedback='';audit_calls=[]
    escalation='contract_repair' if 'contract_repair' in config.config().tiers else 'strong'
    for attempt,tier in enumerate(('strong','strong',escalation),1):
        shown=prompt+feedback;key=response_cache.key(shown,CodingEvidenceReport,[],tier)
        path=folder/('coding_evidence.response.json' if attempt==1 else f'coding_evidence_{key[:20]}.response.json')
        saved=response_cache.read(path,key,CodingEvidenceReport)
        if not saved and attempt>1:
            # Reuse identical earlier evidence questions; the numbered attempt
            # marker only prevents a repeated unresolved reply satisfying final review.
            legacy_feedback=re.sub(r'^\nEvidence repair review \d+: correct these validation failures\.',
                '\nRepair these evidence validation failures.',feedback)
            legacy_key=response_cache.key(prompt+legacy_feedback,CodingEvidenceReport,[],tier)
            prior=response_cache.read(folder/f'coding_evidence_{legacy_key[:20]}.response.json',legacy_key,CodingEvidenceReport)
            if prior and (attempt<3 or all(b.status!='unresolved' for b in prior[0].bindings)):
                saved=prior
        if saved:report,cid=saved
        else:
            answer=llm.call('descriptive:coding_evidence',shown,paper_id=paper_id,stage='1',tier=tier,schema=CodingEvidenceReport,
                large_context=True,timeout_s=900,log_path=path.with_suffix('.log'))
            report,cid=answer.parsed,answer.ledger_id
            if report:response_cache.write(path,key,report,cid or '')
        if cid:audit_calls.append(cid)
        errors=[]
        if report is None or len(report.bindings)!=len(units) or {b.binding_id for b in report.bindings}!=set(units):
            errors.append('Return every requested binding_id exactly once.')
        elif report:
            for b in report.bindings:
                anchored=bool(b.source_quotes) and all(q.strip() and norm(q) in norm(source) for q in b.source_quotes)
                if b.status in {'verified','unresolved'} and (not anchored or b.status=='unresolved' and len(set(b.source_quotes))<2):
                    errors.append(b.binding_id+': supporting quotes must be verbatim contiguous source text, with no added labels, parenthetical attributions, ellipses or paraphrase. '
                        'Unresolved requires two actual conflicting source mappings. Missing keys are unavailable. Invalid quotes: '+json.dumps(b.source_quotes))
                elif b.status=='unresolved' and attempt<3:
                    errors.append(b.binding_id+': independently confirm whether TWO EXPLICIT incompatible coding instructions exist. '
                        'A generic summation instruction and a Reversed tag are not conflicting mappings: if neither states whether deposited values were already recoded, the coding key is unavailable. '
                        'Use unresolved only when the supplied sources actually instruct different executable mappings, and identify both.')
        if not errors:break
        feedback=f'\nEvidence repair review {attempt+1}: correct these validation failures. Return the full requested binding set.\n'+json.dumps(errors)
    else:raise ValueError('coding evidence failed source validation after bounded repairs: '+json.dumps(errors))
    replacements={};receipt=[]
    for evidence in report.bindings:
        anchored=bool(evidence.source_quotes) and all(norm(q) in norm(source) for q in evidence.source_quotes)
        status=evidence.status
        if status=='verified' and not anchored:status='unresolved'
        receipt.append({**evidence.model_dump(),'status':status,'source_quotes_anchored':anchored,
                        'claim_ids':[b.claim_id for b in units[evidence.binding_id]]})
        if status!='verified':
            for b in units[evidence.binding_id]:
                replacements[b.claim_id]=b.model_copy(update={'state':'no_data' if status=='unavailable' else 'unbound',
                    'reason':evidence.reason if evidence.status!='verified' else 'Coding evidence was not anchored in supplied documentation.'})
    (folder/'coding_evidence.json').write_text(json.dumps({'bindings':receipt,'model_call':cid,'model_calls':audit_calls,'scope':'Source documentation of response coding and scoring; no numerical agreement is used.'},indent=2)+'\n')
    return [replacements.get(b.claim_id,b) for b in readouts],audit_calls

PROMPT='''Map every requested descriptive quantity to a computation from the deposited columns, using its source meaning and study/sample identity. Printed values are withheld. Return every claim_id exactly once. Do not infer missing participants from ID gaps or reconstruct recruitment totals from published counts. Use complete_on only for the source-defined availability/sample rule; do not substitute the full sample for a subgroup. Data from absent studies, missing raw measurements, or unavailable upstream model fitting cannot be reconstructed from processed summaries. Return no_data with the specific missing inputs, or unbound when the association is unresolved. Do not guess from numerical similarity or invent columns. Means/SDs use one exact column; sd is the sample SD. mean_columns averages finite cells of the listed columns. multiplier=100 converts proportions to percentages only when the source quantity uses that unit. n counts available rows; count_category uses the exact observed category label. Use filters for source-defined subgroup membership with exact observed values (eq, ne, or not_missing); do not apply outcome-driven exclusions or silently remove malformed rows. Preserve numeric codes. Numeric blanks are missing; malformed numeric text is an error. A supported mapping may disagree with the paper after computation. Return only the requested schema.'''


def calculate(work,b):
    b=b.model_dump() if isinstance(b,Readout) else b
    if b['multiplier']==100 and b['operation'] not in {'mean','mean_columns','count_category','count_missing','count_threshold'}:
        raise ValueError('percentage requires a proportion or explicit numerator and denominator, not a scaled count')
    path=(Path(work)/b['file']).resolve()
    if not path.is_relative_to((Path(work)/'data').resolve()):raise ValueError('readout data path escapes deposit')
    frame=pd.read_csv(path).replace(r'^\s*$',np.nan,regex=True)
    frame=select(frame,b.get('filters',[]))
    if b.get('included_ids') is not None:
        identifier=b.get('id_column')
        if not identifier or frame[identifier].duplicated().any():raise ValueError('intake sample requires unique IDs')
        if not set(b['included_ids'])<=set(frame[identifier]):raise ValueError('intake sample identifies absent rows')
        frame=frame[frame[identifier].isin(b['included_ids'])]
    if b['complete_on']:frame=frame.dropna(subset=b['complete_on'])
    cols=b['columns'];op=b['operation'];analysis_n=len(frame)
    if op=='n':value=len(frame)
    elif op=='count_category':value=len(select(frame,[{'column':cols[0],'operator':'eq','value':b['category_value']}]))
    elif op=='count_missing':value=int(frame[cols[0]].isna().sum())
    elif op=='count_threshold':
        values=pd.to_numeric(frame[cols[0]],errors='raise')
        if np.isinf(values.to_numpy(float)).any():raise ValueError('nonfinite threshold input')
        match=re.fullmatch(r'(>=|<=|>|<)(-?(?:\d+(?:\.\d*)?|\.\d+))',b['category_value'])
        if not match:raise ValueError('invalid threshold comparison')
        operator,bound=match.groups();bound=float(bound)
        value=int({'<':values.lt,'<=':values.le,'>':values.gt,'>=':values.ge}[operator](bound).sum())
    elif op=='cronbach_alpha':
        data=frame[cols].apply(pd.to_numeric,errors='raise').dropna().copy()
        if len(data)<2 or np.isinf(data.to_numpy(float)).any():raise ValueError('insufficient finite complete cases for reliability')
        for column in b.get('reverse_columns',[]):data[column]=-data[column]
        k=len(cols);total_variance=float(data.sum(axis=1).var(ddof=1))
        if total_variance<=0:raise ValueError('zero total-score variance for reliability')
        value=k/(k-1)*(1-float(data.var(ddof=1).sum())/total_variance);analysis_n=len(data)
    else:
        data=frame[cols].apply(pd.to_numeric,errors='raise').to_numpy(float)
        if np.isinf(data).any():raise ValueError('nonfinite readout input')
        finite=data[np.isfinite(data)]
        if not len(finite) or (op=='sd' and len(finite)<2):raise ValueError('insufficient descriptive observations')
        value=float(np.std(finite,ddof=1) if op=='sd' else np.min(finite) if op=='min' else np.max(finite) if op=='max' else np.mean(finite))
        analysis_n=int(np.isfinite(data).any(axis=1).sum())
    if b['multiplier']==100 and op in {'count_category','count_missing','count_threshold'}:
        if not analysis_n:raise ValueError('percentage denominator is empty')
        value=value/analysis_n
    if b['multiplier']==100 and not 0<=value<=1:
        raise ValueError('percentage input is not a proportion in [0,1]; response coding requires review')
    return {'claim_id':b['claim_id'],'value':float(value*b['multiplier']),'n':analysis_n}


def operation_errors(bindings,semantic):
    """Check requested units before independent arithmetic can endorse a wrong plan."""
    kinds={c['claim_id']:c['quantity_kind'] for c in semantic};errors={}
    for b in bindings:
        if b['state']!='supported':continue
        if kinds.get(b['claim_id'])=='percent' and (b['multiplier']!=100 or b['operation'] not in {'mean','mean_columns','count_category','count_missing','count_threshold'}):
            errors[b['claim_id']]='A percentage requires multiplier=100 and a proportion or explicit category/threshold numerator over the eligible sample. n is a count, not a proportion. Filters define the denominator population, never just numerator membership. Do not infer skip logic or category codes from an absent observed zero.'
        elif kinds.get(b['claim_id'])!='percent' and b['multiplier']!=1:
            errors[b['claim_id']]='The requested quantity is not a percentage; use its original units.'
    return errors


def masked_source(text):
    text=re.sub(r'\d+(?:\.\d+)?','[quantity]',text or '')
    return re.sub(r'\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)\b','[quantity]',text,flags=re.I)


class OperationalCondition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    claim_id:str
    source_fragment:str


class OperationalConditions(BaseModel):
    model_config=ConfigDict(extra='forbid')
    conditions:list[OperationalCondition]


def condition_errors(rows,claims):
    expected={c['claim_id']:c for c in claims};errors=[]
    if len(rows)!=len(expected) or {r.claim_id for r in rows}!=set(expected):return ['Return every requested claim exactly once.']
    for r in rows:
        c=expected[r.claim_id];source=str(c.get('source_quote') or '')+'\n'+str(c.get('description') or '')
        fragment=r.source_fragment
        if not fragment:continue
        if fragment not in source or not re.search(r'\b(at least|at most|more than|fewer than|less than|greater than)\b',fragment,re.I):
            errors.append(r.claim_id+': operational condition must be a verbatim source fragment containing its comparison.')
        value=c.get('value')
        numbers=re.findall(r'(?<!\w)[+-]?\d+(?:\.\d+)?',fragment)
        if value is not None and any(float(n)==float(value) for n in numbers):
            errors.append(r.claim_id+': fragment includes the reported result; return only the operational threshold, or empty if inseparable.')
    return errors


def operational_conditions(paper_id,claims,folder):
    """Retain located count thresholds while withholding reported percentages/counts."""
    from . import response_cache
    chosen=[c for c in claims if c.get('quantity_kind') in {'n','percent'} and re.search(
        r'\b(at least|at most|more than|fewer than|less than|greater than)\b',str(c.get('description'))+' '+str(c.get('source_quote')),re.I)]
    if not chosen:return []
    prompt=('Extract only the operational eligibility/counting condition, including its threshold and variable, from each source fragment. '
        'Return the shortest verbatim source_fragment that retains that condition (for example "having at least 2 prior episodes"). '
        'Exclude observed counts, percentages, effect estimates, and other results. Empty fragment if no operational condition can be separated. '
        'This is source reading only; no dataset or computed results are supplied. Return every requested claim once.\n'
        +json.dumps([{k:c.get(k) for k in ('claim_id','description','source_quote')} for c in chosen]))
    feedback=''
    for attempt in range(2):
        shown=prompt+feedback;key=response_cache.key(shown,OperationalConditions,[],'strong');path=folder/f'operational_conditions_{key[:20]}.json'
        cached=response_cache.read(path,key,OperationalConditions)
        if cached:out,cid=cached
        else:
            r=llm.call('descriptive:operational_conditions',shown,paper_id=paper_id,stage='1',tier='strong',schema=OperationalConditions,timeout_s=600)
            out,cid=r.parsed,r.ledger_id
            if out:response_cache.write(path,key,out,cid or '')
        errors=condition_errors(out.conditions,chosen) if out else ['Missing structured response.']
        if not errors:return [r.model_dump() for r in out.conditions if r.source_fragment]
        feedback='\nCorrect validation errors: '+json.dumps(errors)
    raise ValueError('Operational source conditions unresolved: '+json.dumps(errors))


def intake_samples(stage0):
    def read(name, default):
        p=stage0/name
        return json.loads(p.read_text()) if p.exists() else default
    ready=read('readiness.json',{});contracts=read('contracts.json',[]);out={}
    for c in contracts:
        aid=c['analysis_id'];selection=ready.get('sample_selections',{}).get(aid)
        if not selection or ready.get('per_analysis_state',{}).get(aid)!='complete':continue
        out[aid]={'analysis_id':aid,'study_id':c.get('study_id'),'analysis_label':c.get('analysis_label'),
                  'outcome':c.get('outcome'),**{k:selection.get(k) for k in ('file','id_column','filters')}}
        # Executable predicates take precedence over a materialised ID list.
        out[aid]['included_ids']=selection.get('included_ids') if not selection.get('filters') else None
        file=stage0.parent.parent.parent/'corpus'/stage0.parent.name/(selection.get('file') or '')
        if file.is_file():
            frame=pd.read_csv(file).replace(r'^\s*$',np.nan,regex=True)
            frame=select(frame,selection.get('filters') or [])
            identifier=selection.get('id_column')
            if selection.get('included_ids') is not None:
                frame=frame[frame[identifier].isin(selection['included_ids'])]
            identities=frame[identifier].tolist() if identifier else frame.index.tolist()
            out[aid]['observed_sample_identity']=provenance.digest({'file':selection.get('file'),'ids':sorted(map(str,identities))})
        out[aid]['sample_description']=masked_source(c.get('sample_rule'))
    return out


def bind_samples(bindings, samples):
    """Resolve an explicitly chosen intake sample without using reported values."""
    output=[];errors={}
    for original in bindings:
        b=dict(original);aid=b.get('sample_analysis_id')
        available=[x for x in samples.values() if x.get('file')==b.get('file')]
        choices={json.dumps({k:x.get(k) for k in ('filters','id_column','included_ids')},sort_keys=True) for x in available}
        if b['state']=='supported':
            if aid is None and len(choices)>1:
                errors[b['claim_id']]='Multiple intake samples exist for this file. Select sample_analysis_id by the source-defined population/subgroup, or return unbound.'
            elif aid is not None:
                selected=samples.get(aid)
                if not selected or selected.get('file')!=b.get('file'):
                    errors[b['claim_id']]='Selected intake sample is absent or belongs to a different file.'
                else:
                    required=selected.get('filters') or []
                    b['filters']=required+[f for f in b.get('filters',[]) if f not in required]
                    b['id_column']=selected.get('id_column');b['included_ids']=selected.get('included_ids')
        output.append(b)
    return output,errors


class PreviousReadouts:
    """Exact additive-schema migration: prior bindings cannot contain new operations."""
    @staticmethod
    def model_json_schema():
        schema=Readouts.model_json_schema()
        choices=schema['$defs']['Readout']['properties']['operation']['anyOf'][0]['enum']
        choices.remove('count_threshold')
        return schema
    model_validate=Readouts.model_validate


def recover_prior_bindings(path,prompt):
    from . import response_cache
    key=response_cache.key(prompt,PreviousReadouts,[],'mid')
    return response_cache.read(path,key,PreviousReadouts)


def readout_scope_context(context,ids):
    """Remove unrelated target records while retaining common method/data sources."""
    if '\nTargets:\n' not in context or '\nDeposited columns:\n' not in context:return context
    before,tail=context.split('\nTargets:\n',1)
    targets,after=tail.split('\nDeposited columns:\n',1)
    return before+'\nTargets:\n'+json.dumps([r for r in json.loads(targets) if r.get('claim_id') in ids])+'\nDeposited columns:\n'+after


def scoped_dispositions(paper_id, context, readouts, folder):
    """Resolve small, exact source scopes; never let one reply lose the census."""
    from concurrent.futures import ThreadPoolExecutor
    from . import response_cache,config
    batches=[readouts[i:i+24] for i in range(0,len(readouts),24)]
    def one(batch):
        ids={b.claim_id for b in batch}
        instructions='\nFor unbound, supply competing_source_quotes containing at least two distinct verbatim source excerpts documenting the conflicting mappings; missing documentation alone is no_data.\nReturn exactly these source readouts:\n'+json.dumps([b.model_dump() for b in batch])
        scoped_context=readout_scope_context(context,ids)
        prompt=scoped_context+instructions
        feedback='';calls=[]
        escalation='contract_repair' if 'contract_repair' in config.config().tiers else 'strong'
        for attempt,tier in enumerate(('strong','strong',escalation),1):
            shown=prompt+feedback;key=response_cache.key(shown,Dispositions,[],tier)
            path=folder/f'metadata_disposition_{key[:20]}.response.json'
            cached=response_cache.read(path,key,Dispositions)
            if not cached and attempt==1 and scoped_context!=context:
                prior_key=response_cache.key(context+instructions,Dispositions,[],tier)
                prior=response_cache.read(folder/f'metadata_disposition_{prior_key[:20]}.response.json',prior_key,Dispositions)
                if prior and len(prior[0].readouts)==len(ids) and {b.claim_id for b in prior[0].readouts}==ids and not disposition_errors(prior[0].readouts,scoped_context):
                    cached=prior
            if cached:answer,cid=cached
            else:
                result=llm.call('descriptive:metadata_disposition',shown,paper_id=paper_id,stage='1',tier=tier,
                    schema=Dispositions,large_context=True,timeout_s=600,log_path=path.with_suffix('.log'))
                answer,cid=result.parsed,result.ledger_id
                if answer is not None:response_cache.write(path,key,answer,cid or '')
            if cid:calls.append(cid)
            got=[b.claim_id for b in answer.readouts] if answer else []
            errors=disposition_errors(answer.readouts,context) if answer else []
            if len(got)==len(ids) and set(got)==ids and not errors:
                return [Readout.model_validate({k:v for k,v in b.model_dump().items() if k!='competing_source_quotes'}) for b in answer.readouts],calls
            feedback='\nThe response failed exact source scope. Missing IDs: '+json.dumps(sorted(ids-set(got)))+'; unexpected IDs: '+json.dumps(sorted(set(got)-ids))+'. Return each required ID exactly once; preserve its original target.'
            if errors:feedback+='\nDisposition evidence errors: '+json.dumps(errors)
        raise ValueError('metadata disposition failed bounded source scope: '+', '.join(sorted(ids)))
    with ThreadPoolExecutor(max_workers=min(3,len(batches))) as pool:parts=list(pool.map(one,batches))
    return Readouts(readouts=[b for rows,_ in parts for b in rows]),[cid for _,calls in parts for cid in calls]


def review_readout_gaps(paper_id,parsed,prompt,folder,stage0,*,binding_evidence=None):
    """Resolve source-method gaps with audited parameters, never reproduced targets."""
    # Category coding and reliability keying can be wrong despite two calculators
    # agreeing. Review their source identity independently before computation.
    pending=[b for b in parsed.readouts if b.state=='unbound' or
             (b.state=='supported' and (b.multiplier==100 or b.operation in {'cronbach_alpha','count_category','count_threshold'}))]
    if not pending:return parsed,[]
    methods=stage0/'redacted_methods.md'
    audit=stage0/'leak_audit.json'
    if not methods.exists() or not audit.exists():return parsed,[]
    from .stage1.blind import validate_packet_audit,paper_text
    validate_packet_audit(paper_id)
    from . import response_cache
    # Keep source item labels/table order while removing all reported numbers;
    # fixed numerical scoring parameters come only from the audited methods.
    context='\nAudited methods (method parameters are retained):\n'+methods.read_text()+'\nSource labels and table order with all numerals masked:\n'+masked_source(paper_text(paper_id))
    base=(prompt+'\nIndependently review the unresolved and coding-sensitive readouts listed below. A previous supported label is only a proposal. Use audited methods to recover documented scoring cutoffs and source/table labels to resolve item identity. Do not change coding to fit reported numbers; no computed results are supplied. '
        'count_threshold counts one exact numeric column satisfying category_value such as >=2; multiplier=100 divides that count by the eligible sample size before converting to percent. Use complete_on for the source denominator, including the tested item when the source denominator is its observed responses. '
        'Method cutoffs are inputs, not outcomes: preserve the source-defined comparison exactly. Percentages cannot use operation n; filters define the denominator population, not just numerator membership. Observed category values do not establish the coding scheme: an absent zero does not establish skip logic, and a 1-5 code cannot be assumed to have the clinical meaning of a 0-4 response scale. Require documented labels or return the missing coding key explicitly. '
        'Distinguish a known item order supported by the supplied paper/codebook from a guessed ordering or remembered instrument convention. Reliability requires source-supported item membership and keying, with the supporting source text quoted in reason. Observed item means/correlations cannot establish whether reversal was already applied. '
        'If the provided paper, codebook and column labels genuinely lack an essential item/scoring key or upstream observations, return no_data with the exact missing input and scope of the source check. Multiple imagined partitions of unlabelled items do not constitute competing available mappings: a missing item key is unavailable metadata. Missing checker capability alone is never no_data. If two actual source-supported mappings conflict, keep unbound and cite both. '
        'Return precisely the requested batch claim IDs, no other readouts.\n'+context)
    ids={b.claim_id for b in pending};key=response_cache.key(base+json.dumps([b.model_dump() for b in pending]),Readouts,[],'strong',options={'batch_size':24});path=folder/'source_method_repair.response.json'
    saved=response_cache.read(path,key,Readouts)
    calls=[]
    if saved:patch,cid=saved
    else:
        patch,calls=scoped_dispositions(paper_id,base,pending,folder)
        cid=calls[-1] if calls else None
    if patch is None or len(patch.readouts)!=len(ids) or {b.claim_id for b in patch.readouts}!=ids:
        raise ValueError('descriptive source-method repair failed exact requested scope')
    response_cache.write(path,key,patch,cid or '')
    if not calls:calls=[cid] if cid else []
    unresolved=[b for b in patch.readouts if b.state=='unbound']
    if unresolved:
        # Clarify availability without replacing uncertainty with a preferred code.
        followup=(prompt+context+'\nResolve only the availability disposition of these remaining records. '
            'Return supported only with an executable mapping established by the supplied evidence. '
            'A single ambiguous label (for example, Reversed without saying whether recoding was applied) is a missing scoring key: return no_data and state the missing information. '
            'Use unbound for conflicts between two actual documented mappings and quote both. Do not select the more plausible coding or use observed values to choose. '
            'Preserve the original analytical target. Return exactly the requested IDs.\n')
        legacy_prompt=followup+json.dumps([b.model_dump() for b in unresolved])
        followkey=response_cache.key(legacy_prompt,Readouts,[],'strong');followpath=folder/'metadata_disposition.response.json'
        cached=response_cache.read(followpath,followkey,Readouts)
        if cached and not any(b.state=='unbound' for b in cached[0].readouts):
            resolved,followcall=cached
            if followcall:calls.append(followcall)
        else:
            resolved,followcalls=scoped_dispositions(paper_id,followup,unresolved,folder)
            calls.extend(followcalls)
            followcall=followcalls[-1] if followcalls else None
        required={b.claim_id for b in unresolved}
        if resolved is None or len(resolved.readouts)!=len(required) or {b.claim_id for b in resolved.readouts}!=required:
            raise ValueError('metadata disposition failed exact requested scope')
        response_cache.write(followpath,followkey,resolved,followcall or '')
        resolutions={b.claim_id:b for b in resolved.readouts}
        patch=Readouts(readouts=[resolutions.get(b.claim_id,b) for b in patch.readouts])
    replacement={b.claim_id:b for b in patch.readouts}
    combined=[replacement.get(b.claim_id,b) for b in parsed.readouts]
    codebook=prompt.split('Codebook:\n',1)[1] if 'Codebook:\n' in prompt else ''
    evidence=context+'\nDeposited codebook:\n'+codebook
    if binding_evidence is not None:evidence+='\nAuthoritative parsed deposit metadata and validated intake sample contracts:\n'+json.dumps(binding_evidence)
    checked,evidence_calls=verify_coding_evidence(paper_id,combined,evidence,folder)
    return Readouts(readouts=checked),calls+evidence_calls


def bind_readouts(paper_id, semantic, prompt, folder):
    """Bound large output collections and enforce their exact cardinality."""
    from . import response_cache
    from pydantic import create_model,Field
    from concurrent.futures import ThreadPoolExecutor
    expected={c['claim_id'] for c in semantic}
    def complete(parsed, ids):
        values=[b.claim_id for b in parsed.readouts]
        return len(values)==len(ids) and set(values)==ids
    key=response_cache.key(prompt,Readouts,[],'mid');cache=folder/'bindings.response.json'
    saved=response_cache.read(cache,key,Readouts) or recover_prior_bindings(cache,prompt)
    if saved and complete(saved[0],expected):
        batch_receipt=folder/'binding_batches.json'
        if batch_receipt.exists():
            receipt=json.loads(batch_receipt.read_text())
            if receipt.get('response_key') in {key,response_cache.key(prompt,PreviousReadouts,[],'mid')}:return saved[0],receipt['model_calls']
        prior=folder/'report.json'
        if prior.exists():
            report=json.loads(prior.read_text())
            projected=[{k:b.get(k) for k in Readout.model_fields} for b in report.get('bindings',[])]
            if projected==[b.model_dump() for b in saved[0].readouts] and report.get('binding_call_ids'):
                return saved[0],report['binding_call_ids']
        return saved[0],[saved[1]]
    if not semantic:return Readouts(readouts=[]),[]
    if not saved and len(semantic)<=60:
        r=llm.call('descriptive_bindings',prompt,paper_id=paper_id,stage='1',tier='mid',schema=Readouts,cwd=folder,log_path=folder/'binding.log')
        if r.ok and r.parsed is not None and complete(r.parsed,expected):
            response_cache.write(cache,key,r.parsed,r.ledger_id);return r.parsed,[r.ledger_id]
    def one(entry):
        index,batch=entry;ids={c['claim_id'] for c in batch}
        schema=create_model('ReadoutBatch',__base__=Readouts,
            readouts=(list[Readout],Field(min_length=len(batch),max_length=len(batch))))
        base=prompt.replace('\nTargets:\n'+json.dumps(semantic),'\nTargets:\n'+json.dumps(batch))
        base += f'\nReturn all {len(batch)} requested records exactly once, including an explicit unavailable/unbound disposition. Never return a test/example placeholder.'
        failure=''
        for attempt in range(2):
            shown=base if attempt==0 else base+'\nRepair the actual preceding failure: '+failure+'\nRequired IDs: '+json.dumps(sorted(ids))+\
                '\nFor count_threshold, category_value must contain the operator and cutoff, e.g. ">=2", not just "2" and not a comparison only in reason. A missing observed zero does not establish skip logic or a response-code key. If the source does not document the coding, return no_data with the missing metadata; do not invent a threshold or a denominator.'
            k=response_cache.key(shown,schema,[],'mid');path=folder/f'bindings_batch{index}_attempt{attempt+1}.response.json'
            cached=response_cache.read(path,k,schema)
            if cached:parsed,cid=cached
            else:
                r=llm.call('descriptive_bindings_batch',shown,paper_id=paper_id,stage='1',tier='mid',schema=schema,cwd=folder,log_path=folder/f'binding_batch{index}_attempt{attempt+1}.log')
                if not r.ok or r.parsed is None:
                    failure=r.error or 'No structured binding response was returned.'
                    continue
                parsed,cid=r.parsed,r.ledger_id
            if complete(parsed,ids):
                response_cache.write(path,k,parsed,cid);return parsed.readouts,cid
            failure='The response did not cover the exact requested quantity IDs once each.'
        raise ValueError(f'descriptive binding batch {index} failed exact requested quantity coverage')
    batches=list(enumerate([semantic[i:i+40] for i in range(0,len(semantic),40)],1))
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(one,batches))
    parsed=Readouts(readouts=[r for rows,_ in results for r in rows]);calls=[cid for _,cid in results]
    response_cache.write(cache,key,parsed,calls[-1])
    (folder/'binding_batches.json').write_text(json.dumps({'response_key':key,'model_calls':calls,'batch_size':40,'exact_coverage':True},indent=2)+'\n')
    return parsed,calls


def is_readout(claim):
    kind=claim.get('quantity_kind')
    return kind in {'mean','sd','n','percent'} or (kind=='other' and claim.get('quantity_role')!='inferential')


def run(paper_id):
    from .stage0.readiness import schema_summary
    from .isolation import command,clean_environment
    man=paths.manifest(paper_id);stage=paths.run_dir(paper_id,1);folder=stage/'descriptive';folder.mkdir(exist_ok=True)
    claims=json.loads((paths.run_dir(paper_id,0)/'claims.json').read_text())
    selected=[c for c in claims if c['state']=='complete' and is_readout(c)]
    semantic=[{k:c.get(k) for k in ('claim_id','study_id','quantity_kind','quantity_role','target_outcome','target_contrast','target_model','analysis_label')} for c in selected]
    for target,c in zip(semantic,selected):
        target['description']=masked_source(c.get('description'))
        target['source_context']=masked_source(c.get('source_quote'))
    ready_path=paths.run_dir(paper_id,0)/'readiness.json'
    ready=json.loads(ready_path.read_text()) if ready_path.exists() else {}
    contracts_path=paths.run_dir(paper_id,0)/'contracts.json'
    contracts=json.loads(contracts_path.read_text()) if contracts_path.exists() else []
    unresolved_samples=[{'analysis_id':c['analysis_id'],'study_id':c.get('study_id'),'analysis_label':c.get('analysis_label'),
                         'sample_description':masked_source(c.get('sample_rule')),
                         'reason':masked_source(ready.get('per_analysis_reasons',{}).get(c['analysis_id']))}
                        for c in contracts if ready.get('per_analysis_state',{}).get(c['analysis_id'])!='complete']
    samples=intake_samples(paths.run_dir(paper_id,0))
    summary=schema_summary(man)
    columns=[{'file':'data/'+Path(f['path']).name,'tables':[{'table':t.get('table'),'columns':[{'name':c['name'],'dtype':c.get('dtype'),'categories':list(c.get('value_counts',{})) if c.get('n_distinct',999)<10 else []} for c in t['columns']]} for t in f.get('tables',[])]} for f in summary['files']]
    ins={'unresolved_samples':provenance.digest(unresolved_samples),'intake_samples':provenance.digest(samples),'semantic_targets':provenance.digest(semantic),'column_names':provenance.digest(columns),**provenance.corpus(paper_id),'code':provenance.implementation('descriptive_reproduction.py','sample_filters.py'),'r':artifacts.sha256_file(Path(__file__).with_name('descriptive_reference.R')),**provenance.files({'audited_methods':paths.run_dir(paper_id,0)/'redacted_methods.md'})}
    output=folder/'report.json'
    if output.exists() and json.loads(output.read_text()).get('inputs')==ins:return json.loads(output.read_text())
    if output.exists():
        archive=folder/'superseded';archive.mkdir(exist_ok=True)
        shutil.copy2(output,archive/('report_'+artifacts.sha256_file(output)[:12]+'.json'))
    from . import response_cache
    prompt=PROMPT+'\nThe source_context and description identify the particular reported quantity; section-level analysis labels may mention a different sample. Respect explicit wording such as behavioral participants versus the recording subset. All target numerals are masked. These unresolved intake analyses warn of missing inputs or unidentified exclusions: they do not automatically preclude an unrelated descriptive readout, but a readout of their same population must resolve the same exclusion rule before computation.\n'+json.dumps(unresolved_samples)+'\nIntake has already established the following analysis samples. Choose sample_analysis_id for a descriptive quantity from the same study and population/subgroup when applicable. The controller applies its exact sample rule. A file can contain both full and restricted samples: never infer sample membership from the filename alone. When several samples exist for a file, selection is mandatory; otherwise return unbound. Equal observed_sample_identity hashes establish identical selected rows in this deposit, even when column predicates differ; they do not establish that the procedures always agree. Use sample_description to decide whether the source-defined population is the requested sample. Numerals in sample descriptions are masked; use the operational sample rule, not a reported count or descriptive value. Do not select by reported count or computed descriptive values. Intake samples:\n'+json.dumps(samples)+'\nTargets:\n'+json.dumps(semantic)+'\nDeposited columns:\n'+json.dumps(columns)
    if any(c['quantity_kind']=='other' for c in selected):
        from .stage0.readiness import codebook_text
        prompt+='\nAdditional supported operations: min and max return the observed extreme of one exact column. cronbach_alpha computes raw (unstandardised) alpha on complete cases across the explicitly listed item columns; reverse_columns negates only those items whose source-documented scoring requires reversal. Additive reversal constants do not affect covariance or alpha. Use codebook evidence to identify full scales/subscales and whether deposited items are already keyed. Do not guess subscale membership, automatically reverse negative correlations, or double-reverse already keyed items. If item membership or scoring is genuinely unresolved, return unbound and identify the missing mapping. Adapter limitations alone do not mean no_data. Explain keying evidence in reason. Codebook:\n'+codebook_text(man,summary)
    conditions=operational_conditions(paper_id,selected,folder)
    if conditions:prompt+='\nLocated source operational conditions (thresholds are method inputs; observed results are withheld):\n'+json.dumps(conditions)
    parsed,binding_calls=bind_readouts(paper_id,semantic,prompt,folder)
    parsed,method_calls=review_readout_gaps(paper_id,parsed,prompt,folder,paths.run_dir(paper_id,0),
        binding_evidence={'columns':columns,'validated_samples':samples})
    binding_calls+=method_calls
    call_id=binding_calls[-1] if binding_calls else None
    bindings=[b.model_dump() for b in parsed.readouts]
    ids=[b['claim_id'] for b in bindings]
    if len(ids)!=len(set(ids)) or set(ids)!={c['claim_id'] for c in selected}:raise ValueError('descriptive bindings must cover exact requested quantities')
    bindings,errors=bind_samples(bindings,samples)
    errors.update(operation_errors(bindings,semantic))
    if errors:
        repair_prompt=prompt+'\nRepair only these requested bindings; no computed results are supplied. '
        repair_prompt+='Distinguish unavailable observations from an unresolved mapping: if the source quantity concerns recruitment or excluded participants but the deposit contains only the final analysed sample, return no_data and name the missing recruitment/exclusion records. Do not substitute the final sample or use unbound merely because no intake sample represents the absent population. Use unbound when available evidence permits competing actual sample identities.\n'
        repair_prompt+=json.dumps({'errors':errors,'previous':[b for b in parsed.readouts if b.claim_id in errors]},default=lambda x:x.model_dump())
        repair_key=response_cache.key(repair_prompt,Readouts,[],'mid');repair_path=folder/'sample_repair.response.json'
        saved_repair=response_cache.read(repair_path,repair_key,Readouts)
        if saved_repair:fixed,repair_call=saved_repair
        else:
            r=llm.call('descriptive_sample_repair',repair_prompt,paper_id=paper_id,stage='1',tier='mid',schema=Readouts,log_path=folder/'sample_repair.log')
            if not r.ok or r.parsed is None:raise RuntimeError('descriptive sample repair failed')
            fixed,repair_call=r.parsed,r.ledger_id;response_cache.write(repair_path,repair_key,fixed,repair_call)
        if len(fixed.readouts)!=len(errors) or {b.claim_id for b in fixed.readouts}!=set(errors):raise ValueError('descriptive sample repair must cover exact failed IDs')
        if repair_call:binding_calls.append(repair_call);call_id=repair_call
        replacements={b.claim_id:b.model_dump() for b in fixed.readouts}
        bindings,errors=bind_samples([replacements.get(b['claim_id'],b) for b in bindings],samples)
        errors.update(operation_errors(bindings,semantic))
        if errors:raise ValueError('descriptive sample binding unresolved: '+json.dumps(errors))
    work=folder/'work';(work/'data').mkdir(parents=True,exist_ok=True);(work/'out').mkdir(exist_ok=True)
    for rel in man.data_files:shutil.copy2(man.path(rel),work/'data'/Path(rel).name)
    supported=[b for b in bindings if b['state']=='supported']
    (work/'out/bindings.json').write_text(json.dumps(supported))
    rows=[calculate(work,b) for b in supported]
    script=work/'out/reference.R';shutil.copy2(Path(__file__).with_name('descriptive_reference.R'),script)
    cmd,boundary=command(['Rscript',str(script)],work,{})
    proc=subprocess.run(cmd,cwd=work,capture_output=True,text=True,timeout=60,env=clean_environment(os.environ.copy(),work))
    (folder/'reference.log').write_text(proc.stdout+proc.stderr)
    if proc.returncode:raise RuntimeError('descriptive R verification failed: '+proc.stderr[-1000:])
    independent={r['claim_id']:r for r in json.loads((work/'out/reference_results.json').read_text())}
    for row in rows:
        other=independent.get(row['claim_id'],{})
        row['verification']='verified' if other.get('n')==row['n'] and math.isclose(other.get('value',float('nan')),row['value'],rel_tol=1e-10,abs_tol=1e-12) else 'invalid'
        source=next(c for c in selected if c['claim_id']==row['claim_id'])
        row.update(reported_value=source['value'],printed_precision=source['precision'],meaning=next(c for c in semantic if c['claim_id']==row['claim_id']))
        row['matches_printed_rounding']=round(row['value'],source['precision'] or 0)==source['value']
    result={'inputs':ins,'binding_call_id':call_id,'binding_call_ids':binding_calls,'bindings':bindings,'results':rows,'isolation':boundary,'status':'verified' if all(r['verification']=='verified' for r in rows) else 'invalid','scope':'Source-bound descriptive recomputation from deposited rows, checked independently in R; unavailable recruitment/trial-level quantities remain explicit. Printed values are introduced only after both calculations.'}
    output.write_text(json.dumps(result,indent=2)+'\n');return result

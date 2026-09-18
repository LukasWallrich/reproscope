"""Evidence-bounded statistical analysis and interpretation review, the default Stage 2."""
import json
from typing import Literal
from pydantic import BaseModel, Field
from .. import artifacts, paths, review_backend, provenance
from . import review

PROMPT='stage2_correctness'


class Finding(BaseModel):
    source_id: str
    anchor: str
    evidence_status: Literal['demonstrated','unresolved']
    error: str
    demonstration: str
    consequence: str
    next_check: str


class Answer(BaseModel):
    answer: Literal['clear_error_found','no_clear_error_found','unresolved']
    summary: str
    findings: list[Finding] = Field(default_factory=list)


class Response(BaseModel):
    coding: Answer
    interpretation: Answer
    scope: str


def source_contains(anchor,text):
    from ..source_direction import normalise
    if normalise(anchor) in normalise(text):
        return True
    # JSON source snapshots may quote their evidence strings. Match their decoded
    # string values with conservative PDF whitespace/subscript normalisation; words, signs and values remain fixed.
    try:
        parsed=json.loads(text)
    except (ValueError,TypeError):
        return False
    def contains(value):
        if isinstance(value,str):return normalise(anchor) in normalise(value)
        if isinstance(value,dict):return any(contains(v) for v in value.values())
        if isinstance(value,list):return any(contains(v) for v in value)
        return False
    return contains(parsed)


def validate(payload,sources):
    """Reject missing anchors and inconsistent outcome labels; do not auto-promote evidence."""
    problems=[]
    for name in ('coding','interpretation'):
        question=payload[name]
        for i,f in enumerate(question['findings']):
            text=sources.get(f['source_id'],'')
            f['anchor_verified']=len(f['anchor'].strip())>=8 and source_contains(f['anchor'],text)
            if not f['anchor_verified']:problems.append(f'{name} finding {i}: source anchor not found')
            if f['evidence_status']=='demonstrated' and not f['demonstration'].strip():
                problems.append(f'{name} finding {i}: demonstration missing')
        found=any(f['evidence_status']=='demonstrated' for f in question['findings'])
        uncertain=any(f['evidence_status']=='unresolved' for f in question['findings'])
        if (found and question['answer']!='clear_error_found') or (not found and question['answer']=='clear_error_found') or (question['answer']=='unresolved' and not (uncertain or question.get('limitations'))):
            problems.append(f'{name}: answer inconsistent with evidence status')
    return problems


def qualify(payload, sources):
    """Quarantine unsupported findings without discarding an otherwise usable review."""
    validate(payload,sources)
    for name in ('coding','interpretation'):
        q=payload[name]
        excluded=[f for f in q['findings'] if not f['anchor_verified'] or (f['evidence_status']=='demonstrated' and not f['demonstration'].strip())]
        if excluded:
            q['excluded_findings']=excluded
            q['findings']=[f for f in q['findings'] if f not in excluded]
            q['limitations']=[f"{len(excluded)} proposed finding(s) lacked a verified source anchor or demonstration after citation repair; retained in the audit artifact only."]
            demonstrated=any(f['evidence_status']=='demonstrated' for f in q['findings'])
            q['answer']='clear_error_found' if demonstrated else 'unresolved'
            q['summary']='The retained findings below have verified source anchors. The review remains limited by unsupported proposed findings listed in its audit artifact.'
    payload['citation_validation']='qualified' if any(payload[n].get('excluded_findings') for n in ('coding','interpretation')) else 'complete'
    return validate(payload,sources)


def render_md(payload):
    lines=['# Stage 2 — Statistical analysis and interpretation correctness','',payload['scope'],'',
           'No clear error found means none was established within the inspected material; it is not proof that every upstream or downstream step is correct.','']
    for name,title in [('coding','1. Clear statistical analysis errors'),('interpretation','2. Clear interpretation errors')]:
        q=payload[name]
        lines += ['## '+title,'',f"**{q['answer'].replace('_',' ')}.** {q['summary']}",'']
        lines += q.get('limitations',[])
        for f in q['findings']:
            lines += [f"### {f['evidence_status']}",'',f['error'],'',
                f"Evidence (`{f['source_id']}`):",'', '> '+f['anchor'].replace('\n','\n> '),'',
                'Demonstration / unresolved check: '+f['demonstration'],'',
                'Consequence: '+f['consequence'],'','Next check: '+f['next_check'],'']
    return '\n'.join(lines)


def run(paper_id,force=False):
    stage=paths.run_dir(paper_id,2);inp=review.gather(paper_id)
    diagnosis=paths.run_dir(paper_id,1)/'diagnosis.json'
    ins={**inp.hashes,'diagnosis':artifacts.sha256_file(diagnosis) if diagnosis.exists() else 'missing'}
    # Gather includes review implementation and prompt hashes; the stage marker uses
    # that public dependency set and individual review caching also binds diagnosis.
    existing=review.load_check(paper_id,'correctness')
    if existing and review.reusable(existing,ins,(PROMPT,)) and not force and paths.is_done(stage,inp.hashes):
        return {'skipped':True,'review':stage/'review.json'}
    if existing and review.reusable(existing,ins,(PROMPT,)) and not force:
        rec=existing
    else:
        claim_fields={'claim_id','study_id','quantity_kind','value','comparator','source_quote','location','target_outcome','target_contrast','analysis_label'}
        sources={'paper':inp.paper_text,
            'all_claims':json.dumps([{k:v for k,v in c.model_dump().items() if k in claim_fields} for c in inp.claims],separators=(',',':')),
            'all_contracts':json.dumps([c.model_dump(exclude={'meta','confidence','open_ambiguities','identity','ambiguities','versions_named','software_named'}) for c in inp.contracts],separators=(',',':')),
            'divergence_diagnoses':diagnosis.read_text() if diagnosis.exists() else 'No diagnosis artifact.'}
        for replica in inp.replicas:
            sources['script:'+replica.replica_id]=replica.script_text
        sources['execution_verification']=json.dumps({r.replica_id:{
            'status':r.trace.get('execution_evidence',{}).get('status'),
            'analyses':{aid:{k:v for k,v in evidence.items() if k not in {'protocol_normalisation','method_scope','plan_status','support_status','computation_status'}} for aid,evidence in r.trace.get('execution_evidence',{}).get('analyses',{}).items()},
            'perturbation_status':r.trace.get('execution_evidence',{}).get('perturbation',{}).get('status')}
            for r in inp.replicas})
        material='\n\n'.join(f'[source_id={sid}]\n{text}' for sid,text in sources.items())
        source_path=stage/'correctness_sources.json'
        from .. import ledger, config, llm
        import os
        spec=config.tier('strong_alt' if os.environ.get('REPROSCOPE_REVIEW_BACKEND')=='strong_alt' else 'strong')
        recorded={row['id']:row for row in ledger.rows(paper_id)}
        comparable=lambda h:{k:v for k,v in h.items() if k!='implementation'}
        can_revalidate=bool(not force and existing and existing.response and existing.meta
            and not artifacts.prompt_stale(existing,(PROMPT,))
            and comparable(existing.meta.inputs)==comparable(ins)
            and source_path.exists() and json.loads(source_path.read_text())==sources
            and existing.meta.model_calls and all(recorded.get(cid,{}).get('route')==spec.route and recorded.get(cid,{}).get('model')==spec.model for cid in existing.meta.model_calls))
        source_path.write_text(json.dumps(sources,indent=2)+'\n')
        if can_revalidate:
            r=llm.LLMResult(text='',parsed=Response.model_validate(existing.response),ledger_id=existing.meta.model_calls[0])
        else:
            r=review_backend.call('correctness',artifacts.load_prompt(PROMPT,material=material),
                paper_id=paper_id,stage='2',tier='strong',schema=Response,timeout_s=1800,
                log_path=stage/'logs/correctness.log',large_context=True)
        calls=list(existing.meta.model_calls) if can_revalidate else [r.ledger_id] if r.ledger_id else []
        payload=json.loads(json.dumps(existing.response)) if can_revalidate else r.parsed.model_dump() if r.parsed else None
        if payload:
            # A bounded locator-only repair cannot change the finding, evidence
            # status, claimed consequence or demonstration.
            validate(payload,sources)
            bad=[(q,i,f) for q in ('coding','interpretation') for i,f in enumerate(payload[q]['findings']) if not f['anchor_verified']]
            if bad:
                class Citation(BaseModel):
                    question: Literal['coding','interpretation']
                    index: int
                    source_id: str
                    anchor: str
                class Citations(BaseModel):
                    citations: list[Citation]
                repair_prompt=('Repair citations only. For each listed finding, locate a short exact contiguous quote in the supplied sources that supports its actual claim. Do not invent a quote, change a finding, or add diagnoses. If no support exists use an empty anchor. Return citations with question, index, source_id and anchor.\n'
                    +json.dumps({'findings':[{'question':q,'index':i,'finding':f} for q,i,f in bad],
                        'sources':{sid:sources[sid] for sid in {f['source_id'] for _,_,f in bad} if sid in sources}},indent=2))
                repaired=review_backend.call('correctness_citation_repair',repair_prompt,paper_id=paper_id,stage='2',tier='strong',schema=Citations,timeout_s=1800,large_context=True)
                if repaired.ledger_id:calls.append(repaired.ledger_id)
                if repaired.parsed:
                    required={(q,i) for q,i,_ in bad}
                    for citation in repaired.parsed.citations:
                        if (citation.question,citation.index) in required:
                            f=payload[citation.question]['findings'][citation.index]
                            f['original_anchor']=f['anchor'];f['original_source_id']=f['source_id']
                            f['anchor']=citation.anchor;f['source_id']=citation.source_id
            problems=qualify(payload,sources)
            payload["inspected_code"]={"origin":"pipeline-generated reproduction scripts", "replica_ids":[r.replica_id for r in inp.replicas], "author_code_inspected":False}
        else:problems=[r.error or 'no valid correctness response']
        rec=review.write_check(paper_id,'correctness',inputs=ins,
            prompt_versions={PROMPT:artifacts.prompt_version(PROMPT)},
            model_calls=calls,response=payload,
            abstain_reason='; '.join(problems) if problems else None)
    if rec.state!='complete':raise RuntimeError('correctness review incomplete: '+str(rec.abstain_reason))
    payload=rec.response
    result=artifacts.AnalysisReview(mode='correctness',questions=payload,
        state='complete',scope=payload['scope'],meta=rec.meta)
    artifacts.save(result,stage/'review.json')
    (stage/'review.md').write_text(render_md(payload))
    paths.mark_done(stage,inp.hashes)
    print('stage 2: statistical analysis and interpretation correctness — complete',flush=True)
    return {'skipped':False,'review':stage/'review.json','records':{'correctness':rec}}

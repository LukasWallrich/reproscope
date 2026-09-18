"""Unblinded diagnosis of every divergence and computation limitation."""
from pathlib import Path
from typing import Literal
import json
from pydantic import BaseModel
from .. import artifacts, paths, provenance, review_backend
from .. import divergence

PROMPT = 'stage1_diagnose_focal'  # Existing prompt name retained for cache/tool compatibility.


class Diagnosis(BaseModel):
    group_id: str
    evidence_status: Literal['supported_explanation', 'hypothesis', 'unresolved']
    explanation: str
    evidence_source: str
    evidence_quote: str
    next_check: str


class Response(BaseModel):
    diagnoses: list[Diagnosis]


def key(paper_id):
    root = paths.run_dir(paper_id,1).parent
    names = ['stage1/match.json','stage1/descriptive/report.json','stage0/claims.json',
             'stage0/contracts.json','stage0/readiness.json','stage1/targeted.json']
    files = {name:root/name for name in names}
    for p in (root/'stage1/replicas').glob('*/trace.json'):files[str(p.relative_to(root))]=p
    for p in (root/'stage1/replicas').glob('*/work/out/analysis_plan.json'):files[str(p.relative_to(root))]=p
    return {**provenance.files(files),'implementation':provenance.implementation('divergence.py','stage1/diagnose.py'),
            'review_backend':review_backend.fingerprint()}


def material(root, inv):
    sources = {}
    for g in inv['groups']:
        selected = {k:g[k] for k in ('group_id','analysis_id','kind','claim_ids')}
        selected['claims'] = [{k:v for k,v in c.items() if k in {'claim_id','description','value','quantity_kind','target_outcome','target_contrast','analysis_label','location','source_quote','source_text','source_evidence','printed_precision'}} for c in g['claims']]
        selected['evidence'] = [{k:v for k,v in e.items() if k in {'claim_id','replica_id','reported','replicated','reported_value','value','band','rule','reason','status','n','source','analysis_id','verification','matches_printed_rounding','degrees_of_freedom'}} for e in g['evidence']]
        selected['contract'] = {k:v for k,v in (g['contract'] or {}).items() if k not in {'meta','repair_provenance'}}
        sources['group:'+g['group_id']] = json.dumps(selected,indent=2,default=str)
    analysis_ids = {g['analysis_id'] for g in inv['groups']}
    for p in sorted((root/'stage1/replicas').glob('*/trace.json')):
        trace = json.loads(p.read_text())
        payload = {k:trace.get(k) for k in ('replica_id','open_choices','model_formula','filters','transformations')}
        evidence = trace.get('execution_evidence') or {}
        payload['verification'] = {k:v for k,v in evidence.get('analyses',{}).items() if k in analysis_ids}
        plan = divergence.read(p.parent,'work/out/analysis_plan.json',{})
        payload['plans'] = [a for a in plan.get('analyses',[]) if a.get('analysis_id') in analysis_ids]
        sources['replica:'+p.parent.name] = json.dumps(payload,indent=2,default=str)
    targeted = divergence.read(root,'stage1/targeted.json',{})
    if targeted.get('diagnosis'):
        sources['targeted_conjecture'] = targeted['diagnosis']
    return sources


def diagnosis_batches(root, inv, pending, max_chars=90000):
    """Bound context by affected analyses; every pending group remains a duty."""
    groups=[g for g in inv['groups'] if g['group_id'] in pending]
    batch=[]
    for group in groups:
        candidate=batch+[group]
        shown=material(root, {'groups':candidate})
        if batch and len(json.dumps(shown))>max_chars:
            yield [g['group_id'] for g in batch], material(root, {'groups':batch})
            batch=[group]
        else:batch=candidate
    if batch:yield [g['group_id'] for g in batch], material(root, {'groups':batch})


def run(paper_id: str, force: bool = False) -> Path:
    stage = paths.run_dir(paper_id,1);root=stage.parent
    out, meta = stage/'diagnosis.md',stage/'diagnosis.meta.json'
    ins=key(paper_id);version=artifacts.prompt_version(PROMPT)
    old=divergence.read(stage,'diagnosis.meta.json',{})
    if not force and out.exists() and old.get('inputs')==ins and old.get('prompt_versions',{}).get(PROMPT)==version and divergence.coverage_status(root)['complete']:
        return out
    inv=divergence.inventory(root)
    (stage/'divergence_inventory.json').write_text(json.dumps(inv,indent=2)+'\n')
    sources=material(root,inv)
    (stage/'diagnosis_sources.json').write_text(json.dumps(sources,indent=2)+'\n')
    diagnoses=[];pending=[]
    # These dispositions follow directly from executed accounting; no speculative model call is needed.
    for g in inv['groups']:
        kind=g['kind'];first=g['evidence'][0];source='group:'+g['group_id']
        if kind.startswith('coverage_'):
            reason=first['reason']
            diagnoses.append(dict(group_id=g['group_id'],evidence_status='supported_explanation',
                explanation=reason,evidence_source=source,evidence_quote=reason,
                next_check='Obtain the specifically missing inputs or a corrected deposit, then rerun the bound computation. This disposition does not establish an author coding error.'))
        elif kind=='rounding_boundary':
            diagnoses.append(dict(group_id=g['group_id'],evidence_status='supported_explanation',
                explanation='The computed value does not literally satisfy the printed inequality but is compatible with rounding its boundary. Boundary rounding explains numerical proximity; whether the author rounded this way is unverified.',
                evidence_source=source,evidence_quote=first['rule'],next_check='Check the unrounded author output or reporting convention; retain the literal inequality failure until established.'))
        elif kind=='direction_unstated':
            diagnoses.append(dict(group_id=g['group_id'],evidence_status='supported_explanation',
                explanation='Magnitude agrees at the printed precision. The source does not establish the substantive direction or subtraction order, so direction remains unverified; this is not evidence of a coding mismatch.',
                evidence_source=source,evidence_quote=first['rule'],next_check='Obtain explicit contrast order or signed author output; do not infer it from the reproduced sign.'))
        else:pending.append(g['group_id'])
    calls=[];problems=[]
    if pending:
        from .. import response_cache
        import os
        tier='strong_alt' if os.environ.get('REPROSCOPE_REVIEW_BACKEND')=='strong_alt' else 'strong'
        for batch_number, (batch_ids, model_sources) in enumerate(diagnosis_batches(root, inv, pending), 1):
            # Unique keys retain the exact evidence shown in each bounded call.
            model_sources={f"batch{batch_number}:"+k:v for k,v in model_sources.items()}
            sources.update(model_sources)
            shown=json.dumps({'required_group_ids':batch_ids,'sources':model_sources},indent=2)
            prompt=artifacts.load_prompt(PROMPT,material=shown)
            fingerprint=response_cache.key(prompt,Response,[],tier,options={'review_backend':review_backend.fingerprint()})
            cache=stage/f'diagnosis.batch{batch_number}.response.json'
            saved=response_cache.read(cache,fingerprint,Response) if not force else None
            if saved:
                parsed,cid=saved
            else:
                r=review_backend.call('diagnose',prompt,paper_id=paper_id,stage='1',tier='strong',schema=Response,timeout_s=1800)
                parsed,cid=r.parsed,r.ledger_id
                if parsed is None:problems.append(r.error or 'diagnosis call returned no structured output')
            if cid:calls.append(cid)
            if parsed is None:continue
            # Retain failed candidates as well: replay validation, then repair only
            # missing/unanchored groups without discarding already located diagnoses.
            response_cache.write(cache,fingerprint,parsed,cid or '')
            accepted={};required=set(batch_ids)
            for attempt in range(3):
                from collections import Counter
                from ..stage2.correctness import source_contains
                counts=Counter(d.group_id for d in parsed.diagnoses)
                for d in parsed.diagnoses:
                    if d.group_id not in required or counts[d.group_id]!=1:continue
                    located=bool(d.evidence_quote.strip()) and source_contains(d.evidence_quote,model_sources.get(d.evidence_source,''))
                    if located:accepted[d.group_id]={**d.model_dump(),'anchor_verified':True}
                remaining=required-set(accepted)
                if not remaining:break
                if attempt==2:
                    problems.extend('unlocated or missing diagnosis evidence: '+gid for gid in sorted(remaining));break
                repair_groups=[g for g in inv['groups'] if g['group_id'] in remaining]
                prefix=f'batch{batch_number}:repair{attempt+1}:'
                model_sources={prefix+k:v for k,v in material(root,{'groups':repair_groups}).items()}
                sources.update(model_sources)
                repair_prompt=artifacts.load_prompt(PROMPT,material=json.dumps({'required_group_ids':sorted(remaining),'sources':model_sources},indent=2))
                repair_prompt+='\nThe previous response omitted a requested group or used evidence that could not be located. Return only the requested groups, exactly once each. Copy ONE contiguous evidence quotation verbatim from its named supplied source; no combined fragments, field labels, paraphrases or added attribution. A hypothesis may remain a hypothesis, supported by the observed discrepancy; do not invent a confirmed cause. Previous candidates:\n'+json.dumps([d.model_dump() for d in parsed.diagnoses if d.group_id in remaining])
                repair_key=response_cache.key(repair_prompt,Response,[],tier,options={'review_backend':review_backend.fingerprint()})
                repair_path=stage/f'diagnosis.repair_{repair_key[:20]}.response.json'
                saved=response_cache.read(repair_path,repair_key,Response) if not force else None
                if saved:parsed,cid=saved
                else:
                    answer=review_backend.call('diagnose:evidence_repair',repair_prompt,paper_id=paper_id,stage='1',tier='strong',schema=Response,timeout_s=900)
                    parsed,cid=answer.parsed,answer.ledger_id
                    if parsed:response_cache.write(repair_path,repair_key,parsed,cid or '')
                if cid:calls.append(cid)
                if parsed is None:
                    problems.extend('diagnosis repair unavailable: '+gid for gid in sorted(remaining));break
            diagnoses.extend(accepted.values())
    (stage/'diagnosis_sources.json').write_text(json.dumps(sources,indent=2)+'\n')
    diagnoses_by_id={d['group_id']:d for d in diagnoses}
    ordered=[{**g,'diagnosis':diagnoses_by_id.get(g['group_id'])} for g in inv['groups']]
    receipt=dict(status='complete' if not problems else 'incomplete',inventory_fingerprint=inv['fingerprint'],
        diagnoses=diagnoses,problems=problems,model_calls=calls,scope='All recorded numerical divergences and computation limitations. Unblinded explanations do not grade the paper or identify blame.')
    (stage/'diagnosis.json').write_text(json.dumps(receipt,indent=2)+'\n')
    lines=['# Divergence diagnosis','',f"Coverage: {len(diagnoses_by_id)}/{inv['n_groups']} issue groups across {inv['n_claims']} source quantities.",'',
           'Observed discrepancies, data limitations and uncertain explanations are distinguished below. Grouping retains every affected source occurrence and replica. An unblinded conjecture is not a confirmed coding error.','']
    if not ordered:lines+=['No recorded divergences or computation limitations.','']
    for g in ordered:
        d=g['diagnosis']
        lines += [f"## {g['group_id']} — {', '.join(g['claim_ids'])}",'']
        lines += ['| Claim | Replica / route | Reported | Computed | Status |','| --- | --- | ---: | ---: | --- |']
        for e in g['evidence']:
            lines.append(f"| {e['claim_id']} | {e.get('replica_id',e.get('route','descriptive'))} | {e.get('reported',e.get('reported_value','—'))} | {e.get('replicated',e.get('value','—'))} | {e.get('rule',e.get('reason',g['kind']))} |")
        if d:
            lines += ['',f"**{d['evidence_status'].replace('_',' ')}:** {d['explanation']}",'',
                      f"Evidence: `{d['evidence_source']}` — {d['evidence_quote']}",'',f"Next check: {d['next_check']}",'']
        else:lines+=['','Diagnosis unavailable; coverage remains incomplete.','']
    if problems:lines+=['## Validation problems','']+['- '+p for p in problems]
    out.write_text('\n'.join(lines)+'\n')
    meta.write_text(json.dumps({'inputs':ins,'prompt_versions':{PROMPT:version},'model_calls':calls},indent=2)+'\n')
    if problems:raise RuntimeError('divergence diagnosis incomplete: '+'; '.join(problems))
    return out

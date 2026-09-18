"""Resolve incomplete screened method contracts before any program generation.

Completion sees methods and column names only. Analytical additions are explicit
and independently reviewed; they are never attributed to the paper's authors.
"""
import copy,json,os
from pydantic import BaseModel,ConfigDict
from typing import Literal
from . import llm,response_cache,provenance
from .stage3.multiverse import Incompatible,build_grid

class Definition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    factor:str
    level:str
    how:str
    basis:Literal['screened','implementation_convention','analytical_completion']
    evidence:str
    reason:str
class Completion(BaseModel):
    model_config=ConfigDict(extra='forbid')
    definitions:list[Definition]
    incompatible:list[Incompatible]
class Correction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    definitions:list[Definition]
    incompatible:list[Incompatible]

def apply_correction(previous,patch):
    known={(r.factor,r.level):r for r in previous.definitions}
    keys=[(r.factor,r.level) for r in patch.definitions]
    if len(set(keys))!=len(keys) or not set(keys)<=set(known):raise ValueError('correction may change only existing unique method definitions')
    known.update({(r.factor,r.level):r for r in patch.definitions})
    return Completion(definitions=list(known.values()),incompatible=patch.incompatible)

class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    accepted:bool
    problems:list[str]

INSTRUCTIONS='''Complete the operational contract of an already screened multiverse BEFORE code generation. No tools, data records, results or new dimensions. Return exactly one definition for every surviving factor/level. Preserve its substantive choice. Definitions must jointly specify the point estimator, retained sample/order, uncertainty and hypothesis test for every allowed combination. Never invent author choices. Label substantive resolutions analytical_completion and explain them; seed/count/tie conventions are implementation_convention. Use screened as basis only if unchanged. evidence must be an exact contiguous fragment of supplied methods; it establishes context, not that a new completion was published.
Return the complete incompatible list: exclude genuinely invalid combinations or unresolved analytical branches. Conditions already satisfied by your rewritten definitions must not remain as exclusions; explain removal in the relevant reason. Same-factor mutually exclusive levels need no constraint. Do not remove a genuine restriction to increase the grid. Do not inspect or aim for any target count.
CI and hypothesis tests are separate duties: a percentile interval supplies no p-value. Define any paired analytical t test explicitly. No arbitrary semipartial Fisher interval: exclude the analytical/semi-partial combination if its interval is unspecified, preserving that estimator under supported bootstrap inference. A permutation p-value can accompany an explicitly declared percentile row-bootstrap interval; label this analytical completion, not permutation-derived CI. Partial rank Fisher intervals must be explicitly approximate with SE=1/sqrt(n-q-3), full partial only. Conventional full partial t uses df=n-q-2; semipartial significance is the full-model coefficient test, not substituting semipartial r into the partial t formula.
Permutation methods must name moving variable and algorithm. Distinguish directly permuting a residual vector (no refitting/reprojection) from Freedman-Lane (add fitted reduced-model values then refit). With nuisance variables prefer a coherent Freedman-Lane null if the screened algorithm is otherwise ambiguous, record this as analytical completion and state assumptions. Rank raw variables/covariates before residualization; bootstrap re-ranks/refits each resampled dataset. Never re-rank a directly permuted residual vector. A rank-scale Freedman-Lane procedure operates on fixed ranked variables under its linear-model null, with reprojection; state that approximation explicitly.
Fixed studentized residual trimming uses both raw-variable regressions on selected raw covariates, before ranking, max absolute internally studentized residual per participant, ceil(fraction*n) cases once, ties by deposited row order. Bootstrap/permutation resample only the retained cases, no repeated trim. Recompute n from actual rows, never hardcode reported sample counts. Continuous covariates rank when selected rank procedure says so. Semipartial residualizes the named predictor only, so bind direction explicitly.
Implementation conventions, unless a screened choice explicitly differs: PCG64 default_rng; 20000 null draws, 10000 bootstrap draws; seed 20260915 for each separate procedure/specification; linear empirical quantiles, 95% two-sided CI; add-one Monte Carlo p. These controls are not dimensions. Leave substantive methods explicit in how, no unsupported one-off formula or custom script.
'''

def validate(answer,grid,payload):
    wanted={(f['name'],l['value']) for f in grid['factors'] for l in f['levels']}
    found=[(r.factor,r.level) for r in answer.definitions]
    if len(found)!=len(wanted) or set(found)!=wanted:raise ValueError('method completion must preserve exact factor/level census')
    labels={f'{f}={l}' for f,l in wanted}
    for r in answer.definitions:
        if not r.how.strip() or not r.evidence.strip() or r.evidence not in payload:raise ValueError('method completion evidence must be a located method fragment')
    for c in answer.incompatible:
        if c.a not in labels or c.b not in labels:raise ValueError('incompatible pair must name surviving factor=level labels')

def complete(paper_id,proposed,screen,paper_levels,contract,schema,folder):
    tier=os.getenv('REPROSCOPE_METHOD_REPAIR_TIER')
    if not tier:return screen
    grid=build_grid(proposed,screen,paper_id=paper_id,paper_levels=paper_levels)
    if grid.get('blocking_issues'):return screen
    payload=json.dumps({'factors':grid['factors'],'incompatible':grid.get('incompatible',[]),'contract':contract,'columns':schema},ensure_ascii=False)
    prompt=INSTRUCTIONS+'\nMethods:\n'+payload;folder.mkdir(parents=True,exist_ok=True)
    feedback='';calls=[];previous=None
    for attempt in range(4):
        response_type=Correction if previous is not None else Completion
        shown=prompt+feedback
        if previous is not None:
            shown+='\nPatch mode: return ONLY changed definitions using Correction, plus the complete incompatible list. Preserve every other definition verbatim in the controller. Fix the review findings in this prior candidate, do not redraft from scratch. If a CI-only level needs an accompanying p-value, explicitly pair its percentile CI with the already screened conventional analytic coefficient test (or reject an incompatible combination); do NOT invent a bootstrap-tail p-value from the distribution centred on the observed effect. Maintain the explicit incompatibility between analytical Fisher intervals and semi-partial estimation.\nPrior candidate:\n'+previous.model_dump_json()
        key=response_cache.key(shown,response_type,[],tier);path=folder/f'{key}.json'
        cached=response_cache.read(path,key,response_type)
        if cached:answer,cid=cached
        else:
            result=llm.call('screen:method_completion',shown,paper_id=paper_id,stage='3',tier=tier,schema=response_type,timeout_s=900,large_context=True,log_path=path.with_suffix('.log'))
            answer,cid=result.parsed,result.ledger_id
            if answer:response_cache.write(path,key,answer,cid or '')
        if cid:calls.append(cid)
        try:
            if answer is None:raise ValueError('no structured method completion')
            if previous is not None:answer=apply_correction(previous,answer)
            validate(answer,grid,payload)
        except ValueError as exc:feedback='\nRepair validation: '+str(exc);continue
        review_prompt=INSTRUCTIONS+'\nIndependently review whether these definitions are complete, coherent, scientifically defensible, faithfully preserve accepted choices and explicitly disclose analytical additions. Reject unresolved interactions, unsupported semipartial intervals, unjustified permutation assumptions or exclusions contradicted by the completed rules. Return Review schema.\nMethods:\n'+payload+'\nCompleted definitions:\n'+answer.model_dump_json()
        if attempt:
            review_prompt+='\nSchema clarification for completion provenance: basis classifies the NEW contribution relative to the screened definition, not every clause of a mixed definition. A retained screened statistical method with only clarified sample-count or tie conventions can correctly use implementation_convention. Its evidence field locates the retained screened method. Reject a new statistical test/CI/estimator mislabeled as a computational convention; do not reject a retained method merely because the whole how field includes both original method and new conventions. All scientific completeness and compatibility checks remain required.'
        rkey=response_cache.key(review_prompt,Review,[],'strong_alt');rpath=folder/f'{rkey}.review.json';cached=response_cache.read(rpath,rkey,Review)
        if cached:review,rcid=cached
        else:
            r=llm.call('screen:method_completion_review',review_prompt,paper_id=paper_id,stage='3',tier='strong_alt',schema=Review,timeout_s=900,large_context=True,log_path=rpath.with_suffix('.log'))
            review,rcid=r.parsed,r.ledger_id
            if review:response_cache.write(rpath,rkey,review,rcid or '')
        if rcid:calls.append(rcid)
        if review is None or not review.accepted:
            previous=answer
            feedback='\nRepair independent review: '+json.dumps(review.problems if review else ['review failed']);continue
        out=copy.deepcopy(screen)
        out['adjustments']=[a for a in out.get('adjustments',[]) if a.get('kind')!='rewrite_how']
        out['adjustments'] += [{'kind':'rewrite_how','factor':r.factor,'canonical':r.level,'levels':[],'how':r.how,'rationale':r.reason+' Basis of completion: '+r.basis+'.','mandatory':True} for r in answer.definitions]
        out['incompatible']=[c.model_dump() for c in answer.incompatible]
        out['_method_completion_calls']=calls
        out['_method_completions']=[r.model_dump() for r in answer.definitions]
        (folder/'accepted.json').write_text(json.dumps({'input_sha256':provenance.digest(payload),'completion':answer.model_dump(),'review':review.model_dump(),'calls':calls},indent=2)+'\n')
        return out
    raise RuntimeError('Screened methods remain incomplete after bounded independent completion')

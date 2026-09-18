"""Bounded expansion of underspecified multiverses before any results are read."""
import json
from . import artifacts,llm,response_cache


def active_dimensions(grid):
    from .stage3.multiverse import enumerate_specs
    reference_ids={s['spec_id'] for s in grid.get('reference_specs',[])}
    specs=[s for s in enumerate_specs(grid) if s['spec_id'] not in reference_ids]
    return [f['name'] for f in grid.get('factors',[])
            if len({s['levels'].get(f['name']) for s in specs})>1]


def refine(paper_id,proposed,screen,grid,contract,schema,traces,folder,target):
    """Add independently screenable decisions; preserve existing proposals exactly."""
    from .stage3.multiverse import EnumerateOut
    count=proposed.get('_dimension_refinements',0)
    if count>=2 or proposed.get('_no_further_dimensions'):return None
    active=active_dimensions(grid)
    base=artifacts.load_prompt('stage3_enumerate',contract=contract,schema=schema,traces=traces)
    prompt=base+'\nA source-only screen left '+str(len(active))+' varying dimensions; the configured development target is '+str(target)+'. '
    prompt+='Return ONLY additional factors with new names; the controller preserves all existing factors. Do not rename rejected choices, undo rejection, split one decision into nominal dimensions, or invent choices to reach the target. '
    prompt+='Consider overlooked decisions about data handling, robustness and nuisance functional form only where the actual schema and scientific question justify them. Retain required covariates. Missing-data choices are inapplicable when all required fields are complete. '
    prompt+='Describe provenance, feasibility, dependencies, estimator, scale and null for each addition. Nonlinear nuisance adjustment requires adequate support in the observed covariate distribution. Robust handling requires one fixed justified rule rather than a threshold sweep. '
    prompt+='Covariate-adjusted permutation and bootstrap must preserve the nuisance structure and re-fit it as required; naive outcome shuffling is not an adjusted test. '
    prompt+='Zero new factors is a valid answer when no further defensible choices exist; explain this in notes. No multiverse results are supplied.\nExisting proposal:\n'+json.dumps(proposed.get('factors',[]))+'\nScreening decisions:\n'+json.dumps(screen.get('factors',[]))
    folder.mkdir(parents=True,exist_ok=True)
    existing={f['name'] for f in proposed['factors']}
    failure=''
    for attempt in range(2):
        shown=prompt+failure
        key=response_cache.key(shown,EnumerateOut,[],'strong')
        path=folder/f'addition_{count+1}_attempt{attempt+1}.response.json'
        saved=response_cache.read(path,key,EnumerateOut)
        if saved:additions,cid=saved
        else:
            r=llm.call('enumerate:dimension_refinement',shown,paper_id=paper_id,stage='3',tier='strong',
                schema=EnumerateOut,large_context=True,timeout_s=900,log_path=path.with_suffix('.log'))
            if not r.ok or r.parsed is None:raise RuntimeError('dimension refinement failed: '+str(r.error))
            additions,cid=r.parsed,r.ledger_id
        names=[f.name for f in additions.factors]
        if len(set(names))!=len(names) or existing.intersection(names) or any(len(f.levels)<2 for f in additions.factors):
            failure='\nReturn only genuinely additional factors with unique NEW names and at least two levels each, or an empty factors list. Existing factor names: '+json.dumps(sorted(existing))
            continue
        response_cache.write(path,key,additions,cid or '')
        (folder/f'before_{count+1}.json').write_text(json.dumps({'proposal':proposed,'screen':screen,'grid':grid},indent=2)+'\n')
        return {**proposed,'factors':proposed['factors']+[f.model_dump() for f in additions.factors],
            '_dimension_refinements':count+1,'_no_further_dimensions':not additions.factors,
            '_dimension_refinement_calls':[*proposed.get('_dimension_refinement_calls',[]),cid],
            '_dimension_refinement_notes':[*proposed.get('_dimension_refinement_notes',[]),additions.notes]}
    raise ValueError('dimension refinement failed exact additional-factor scope')

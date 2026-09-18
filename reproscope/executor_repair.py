"""Bounded, tool-free source patches for an existing multiverse executor.

Repairs receive approved inputs, generated source and verifier errors, never
computed result tables. Every patch is archived and executed under isolation.
"""
import json,os,shutil,subprocess
from pathlib import Path
from pydantic import BaseModel,ConfigDict,Field
from . import config,llm,provenance


class SourceChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    filename:str=Field(pattern=r'^[^/\\]+\.(?:py|R|r)$')
    old_text:str=Field(min_length=1)
    new_text:str


class SourcePatch(BaseModel):
    model_config=ConfigDict(extra='forbid')
    changes:list[SourceChange]=Field(min_length=1)


def apply(work,patch):
    """Validate the entire patch before changing any source file."""
    root=(Path(work)/'out').resolve();changes={}
    for edit in patch.changes:
        raw=root/edit.filename
        path=raw.resolve()
        if path.parent!=root or path.suffix.lower() not in {'.py','.r'} or not path.is_file() or raw.is_symlink():
            raise ValueError('patch must name an existing source basename under out/')
        text=changes.get(path,path.read_text())
        if not edit.old_text or text.count(edit.old_text)!=1:
            raise ValueError('old_text must match exactly once in '+edit.filename)
        changes[path]=text.replace(edit.old_text,edit.new_text,1)
    for path,text in changes.items():path.write_text(text)


def patch_failure_feedback(failures, message):
    """A rejected atomic patch leaves the prior numerical defects unchanged."""
    return list(dict.fromkeys([str(message), *failures]))


def repair(work,grid,paper_id,report,executor_prompt):
    from .bounded_generation import inputs,Bundle,write_sources
    from . import metered_generation, artifacts
    executor_prompt += '\n\n' + artifacts.load_prompt('stage3_verification_protocol')
    from .stage3 import multiverse as mv
    from .stage1.replicas import prepare_env,script_command
    from .stage1.audit import acceptance
    from .isolation import command,clean_environment
    work=Path(work);out=work/'out';log=work.parent/'logs/execute.log'
    boundary=json.loads(log.read_text())
    if boundary.get('version') not in {'bounded-generation-1','bounded-generation-2','bounded-generation-3'} or boundary.get('tool_surface')!='none':return report
    initial_calls=boundary.setdefault('source_generation_calls',list(boundary.get('model_calls',[])))
    repair_tier=os.environ.get('REPROSCOPE_EXECUTOR_REPAIR_TIER')
    spec=config.tier(repair_tier or 'strong')
    use_metered=metered_generation.enabled() and not repair_tier
    backend=json.loads(Path(os.environ['REPROSCOPE_METERED_BUDGET_FILE']).read_text())['model'] if use_metered else spec.model_dump()
    key=provenance.digest({'grid':grid,'generation_calls':initial_calls,'repair_backend':backend,'verification_protocol':provenance.implementation('closed_reference.py','verification_recipe.py','statistical.py','stage3/multiverse.py','executor_repair.py')})
    folder=work.parent/'source_repairs'/key;folder.mkdir(parents=True,exist_ok=True)
    history=folder/'events.json'
    events=json.loads(history.read_text()) if history.exists() else []
    def save():
        boundary['source_repairs']=events
        boundary.setdefault('source_repair_runs',{})[key]=events
        log.write_text(json.dumps(boundary,indent=2)+'\n')
        (out/'generation_boundary.json').write_text(json.dumps(boundary,indent=2)+'\n')
        history.write_text(json.dumps(events,indent=2)+'\n')
    if spec.route!='claude_p':return report
    errors=list(report.get('problems') or ['Generated execution has not passed verification.'])
    result=dict(report)
    if not report.get('problems') and acceptance(report.get('audit') or {})=='accepted':
        result.setdefault('initial_executor',dict(result.get('executor') or {}))
        result['executor']={**(result.get('executor') or {}),'ok':True,'error':None,
            'repair_calls':[e['model_call'] for e in events if e.get('model_call')]}
        result['source_repair']={'status':'accepted_after_reverification','events':str(history),'attempts':len(events)}
        return result
    for number in range(len(events)+1,4):
        sources={p.name:p.read_text() for p in out.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in {'.py','.r'}}
        if not sources and not use_metered:break
        payload=inputs(work)
        prompt=(executor_prompt+'\n\nRepair mode: return exact source-code replacements through the SourcePatch schema, not whole files or result tables. '
            'Use exactly a basename from Current source files (for example multiverse.py, never out.multiverse.py) and old_text that occurs exactly once. The controller validates every edit before applying any, then re-executes and verifies the program. '
            'Scripts live under out/; __file__.parent is out/, whereas the working directory contains GRID.json, CONTRACT.json and data/. Any notes must be written by the program. '
            'Verification now independently reconstructs every screened method. Resampling streams: numpy default_rng(seed), sign vectors 2*integers(0,2,(B,n))-1, bootstrap indices integers(0,n,(B,n)) in row order, Freedman-Lane rng.permutation(residual) per draw. Bootstrap quantiles linear; BCa uses SciPy midrank bias correction and jackknife acceleration. Output p_adjustment=fixed_threshold, per_test_alpha=<source criterion>, p_family=[] when the screened level specifies a fixed per-comparison threshold; p=min(1,p_raw*.05/per_test_alpha). For Holm, include plan.nonfocal_family_bindings=[{file,x,y,alternative},...] naming the actual nonfocal tests independently computed from their own bound columns; never copy the focal p. Do not invent a family. This is a threshold-equivalent rescaling, not recovery of a family size. Verify every reported sample ID, CI, SE and p. Fix the actual implementation and its method declarations. Do not mark a supported method unsupported to evade a check; only actual adapter limitations justify that status. '
            'For small analytical tail probabilities use scipy.stats distribution survival functions, not 1-cdf, which loses relative precision. Use exact distribution quantiles for intervals. Emit only standard errors whose estimator is specified by the screened method; a percentile CI does not itself request a bootstrap SE. Preserve all required estimates, intervals and p-values. '
            'Preserve every screened setting and the declared orientation. No computed results or reference target values are supplied.\nVerifier failures:\n'+json.dumps(errors)+'\nApproved inputs:\n'+json.dumps(payload)+'\nCurrent source files:\n'+json.dumps(sources))
        schema=SourcePatch
        if not sources:
            schema=Bundle
            prompt=executor_prompt+'\nReturn multiverse.py (or multiverse.R) through the Bundle schema. Return source files only; the program must write notes and all result files. You have no tools. Scripts live in out/; working directory contains the approved inputs. Use installed numpy, pandas, scipy, statsmodels or base R. No package installation. Preserve all screened methods and settings; implementation will receive mechanical verification feedback.\nApproved inputs:\n'+json.dumps(payload)
        if use_metered:
            answer=metered_generation.call(prompt,paper_id=paper_id,schema=schema,log_path=folder/f'attempt{number}.log')
        else:
            answer=llm.call('execute:source_patch',prompt,paper_id=paper_id,stage='3',route=spec.route,model=spec.model,
                agentic=False,cwd=work,schema=schema,large_context=True,timeout_s=900,log_path=folder/f'attempt{number}.log')
        event={'attempt':number,'model_call':answer.ledger_id,'tool_surface':'none',
            'source_before':provenance.digest(sources),'input_hashes':{p['path']:provenance.digest(p['content']) for p in payload},
            'feedback':errors,'route':answer.route or spec.route,'model':answer.model or spec.model}
        events.append(event)
        if answer.ledger_id:boundary.setdefault('model_calls',[]).append(answer.ledger_id)
        if not answer.ok or answer.parsed is None:
            event['error']=answer.error;errors=patch_failure_feedback(errors,'Source patch response failed validation: '+str(answer.error));save()
            if use_metered and '402 Payment Required' in str(answer.error):break
            continue
        event['patch']=answer.parsed.model_dump()
        backup=folder/f'before_{number}'
        shutil.copytree(out,backup,dirs_exist_ok=True)
        try:
            if sources:apply(work,answer.parsed)
            else:write_sources(work,answer.parsed)
        except ValueError as exc:
            errors=patch_failure_feedback(errors,str(exc));event['error']=str(exc);save();continue
        for path in out.iterdir():
            if path.is_file() and path.suffix.lower() in {'.py','.r'}:continue
            if path.is_dir() and not path.is_symlink():shutil.rmtree(path)
            else:path.unlink()
        environment=prepare_env(out,work.parent/'verification_environment')
        if environment['error']:raise RuntimeError(environment['error'])
        script=next((out/n for n in ('multiverse.py','multiverse.R') if (out/n).exists()),None)
        if script is None:errors=['Required multiverse.py or multiverse.R source is missing.'];event['error']=errors[0]
        else:
            cmd,event['isolation']=command(script_command(script,work,environment['interpreter']),work,environment['env'])
            try:
                proc=subprocess.run(cmd,cwd=work,capture_output=True,text=True,timeout=300,
                    env=clean_environment({**os.environ,**environment['env']},work))
                (out/'run.log').write_text((proc.stdout or '')+'\n'+(proc.stderr or ''))
                event['exit_code']=proc.returncode
                errors=mv.generation_checks(work,grid) if proc.returncode==0 else ['Execution failed: '+(proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'nonzero exit')]
            except subprocess.TimeoutExpired:errors=['Execution exceeded 300 seconds; preserve methods while making computation efficient.']
            except (ValueError,TypeError,KeyError,OSError) as exc:errors=['Execution validation failed: '+str(exc)]
        event['validation_errors']=errors
        event['source_after']=provenance.digest({p.name:p.read_text() for p in out.iterdir() if p.is_file() and p.suffix.lower() in {'.py','.r'}})
        save()
        if not errors:
            result.update(mv.verify_execution(work,grid,paper_id))
            if not result.get('problems') and acceptance(result.get('audit') or {})=='accepted':
                result.setdefault('initial_executor',dict(result.get('executor') or {}))
                result['executor']={**(result.get('executor') or {}),'ok':True,'error':None,
                    'repair_calls':[e['model_call'] for e in events if e.get('model_call')]}
                result['source_repair']={'status':'accepted','events':str(history),'attempts':len(events)}
                return result
            errors=result.get('problems') or ['Provenance audit was not accepted; ensure every statistical output is computed from the supplied data.']
    result.update(mv.verify_execution(work,grid,paper_id))
    result['source_repair']={'status':'exhausted','events':str(history),'attempts':len(events)}
    return result

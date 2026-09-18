"""Opt-in bounded source patches after cheap replica generation fails verification."""
import json,os,shutil,subprocess
from pathlib import Path
from . import config,llm,provenance
from .executor_repair import SourcePatch,apply


def repair(work,paper_id,rdir,term_receipt,errors):
    from .bounded_generation import inputs
    from .stage1.replicas import generation_validation,prepare_env,script_command,find_script
    from .isolation import command,clean_environment
    tier=os.environ.get('REPROSCOPE_REPLICA_REPAIR_TIER')
    if not tier or not errors:return []
    spec=config.tier(tier)
    if spec.route!='claude_p':raise ValueError('Replica source repair requires a tool-free Claude client.')
    work=Path(work);rdir=Path(rdir);out=work/'out';log=rdir/'agent.log'
    boundary=json.loads(log.read_text())
    if boundary.get('tool_surface')!='none':return []
    initial=boundary.setdefault('source_generation_calls',list(boundary.get('model_calls',[])))
    key=provenance.digest({'generation_calls':initial,'spec':spec.model_dump(),'terms':term_receipt,
        'checker':provenance.implementation('execution_evidence.py','adjusted_reference.py','replica_repair.py')})
    folder=rdir/'source_repairs'/key;folder.mkdir(parents=True,exist_ok=True)
    history=folder/'events.json';events=json.loads(history.read_text()) if history.exists() else []
    for number in range(len(events)+1,3):
        sources={p.name:p.read_text() for p in out.iterdir() if p.is_file() and p.suffix.lower() in {'.py','.r'}}
        payload=inputs(work)
        prompt=('Repair this existing independently generated replica using exact source replacements. Return only SourcePatch edits; old_text must occur exactly once. '
            'Preserve the requested analyses and every output quantity. Correct code and method declarations together. Do not replace computed outputs with constants or mark computable requests unsupported. '
            'Quantity dispatch must respect both quantity_kind and quantity_kind_raw: a broad coefficient branch must not swallow standardized beta, and ci_bound endpoints require raw endpoint identity. '
            'The controller re-executes under OS isolation and independently checks every numerical output and the source-defined requested coefficient. '
            'No paper result values or reference computations are supplied. Do not return a replacement implementation; patch the supplied source. You have no tools.\n'
            +'Verifier failures:\n'+json.dumps(errors)+'\nApproved blind inputs:\n'+json.dumps(payload)+'\nCurrent source:\n'+json.dumps(sources))
        answer=llm.call('replica:source_patch',prompt,paper_id=paper_id,stage='1',route=spec.route,model=spec.model,
            agentic=False,cwd=work,schema=SourcePatch,large_context=True,timeout_s=900,log_path=folder/f'attempt{number}.log')
        event={'attempt':number,'model_call':answer.ledger_id,'route':spec.route,'model':spec.model,'tool_surface':'none',
            'feedback':errors,'source_before':provenance.digest(sources),'input_hashes':{p['path']:provenance.digest(p['content']) for p in payload}}
        events.append(event)
        if answer.ok and answer.parsed:
            event['patch']=answer.parsed.model_dump();shutil.copytree(out,folder/f'before_{number}',dirs_exist_ok=True)
            try:
                apply(work,answer.parsed)
                for p in out.iterdir():
                    if p.is_file() and p.suffix.lower() in {'.py','.r'}:continue
                    if p.is_dir() and not p.is_symlink():shutil.rmtree(p)
                    else:p.unlink()
                env=prepare_env(out,rdir);script=find_script(out)
                if env['error'] or script is None:raise ValueError(env['error'] or 'Main analysis script missing.')
                cmd,event['isolation']=command(script_command(script,work,env['interpreter']),work,env['env'])
                proc=subprocess.run(cmd,cwd=work,capture_output=True,text=True,timeout=300,env=clean_environment({**os.environ,**env['env']},work))
                (out/'run.log').write_text((proc.stdout or '')+(proc.stderr or ''))
                event['exit_code']=proc.returncode
                errors=generation_validation(work,term_receipt=term_receipt) if proc.returncode==0 else ['Execution failed: '+proc.stderr[-5000:]]
            except (ValueError,TypeError,KeyError,OSError,subprocess.TimeoutExpired) as exc:errors=[str(exc)]
        else:errors=['Structured source patch failed: '+str(answer.error)]
        event['validation_errors']=errors
        event['source_after']=provenance.digest({p.name:p.read_text() for p in out.iterdir() if p.is_file() and p.suffix.lower() in {'.py','.r'}})
        boundary.setdefault('source_repair_runs',{})[key]=events
        if answer.ledger_id:boundary.setdefault('model_calls',[]).append(answer.ledger_id)
        log.write_text(json.dumps(boundary,indent=2)+'\n')
        (out/'generation_boundary.json').write_text(json.dumps(boundary,indent=2)+'\n')
        history.write_text(json.dumps(events,indent=2)+'\n')
        if not errors:break
    return events

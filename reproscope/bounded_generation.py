"""Tool-free code generation from an explicit blind file payload.

The model receives text copies of approved inputs and cannot browse the workspace.
Only source files are accepted; each execution uses the operating-system boundary.
"""
from pathlib import Path
import hashlib,json,os,subprocess
from pydantic import BaseModel,ConfigDict,Field
from . import llm

VERSION='bounded-generation-3'
MAX_ATTEMPTS=6
class SourceFile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(pattern=r'^(?:out/)?[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:py|[rR])$',
        description='Only Python or R source filenames. Never JSON, CSV, text or requirements files.')
    content:str
class Bundle(BaseModel):
    model_config=ConfigDict(extra='forbid')
    files:list[SourceFile]=Field(min_length=1)


def inputs(work):
    approved=[]
    for name in ('METHODS.md','CONTRACT.json','TASK.md','GRID.json','BASE_ANALYSIS.py','BASE_ANALYSIS.R'):
        if (work/name).is_file():approved.append(work/name)
    approved+=sorted((work/'data').glob('*'))
    payload=[]
    for path in approved:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(work.resolve()):
            raise ValueError('generation input must be a regular supplied file')
        if path.suffix.lower() not in {'.csv','.tsv','.txt','.json','.md','.py','.r'}:
            raise ValueError('tool-free generation currently requires textual deposited inputs')
        payload.append({'path':str(path.relative_to(work)),'content':path.read_text(encoding='utf-8-sig')})
    if sum(len(p['content']) for p in payload)>2_000_000:
        raise ValueError('blind textual payload exceeds bounded generation limit')
    return payload


def write_sources(work,bundle):
    names=[]
    for f in bundle.files:
        p=Path(f.name)
        if len(p.parts)==2 and p.parts[0]=='out':p=Path(p.name)
        if p.is_absolute() or len(p.parts)!=1 or p.suffix.lower() not in {'.py','.r'}:
            raise ValueError('only simple .py/.R source filenames may be generated')
        if len(f.content)>500_000:raise ValueError('generated source exceeds limit')
        names.append(p.name)
    if len(set(names))!=len(names):raise ValueError('duplicate generated filenames')
    for name,f in zip(names,bundle.files):(work/'out'/name).write_text(f.content)


def generate(work,*,paper_id,stage,spec,prompt,log_path,script_stem,timeout_s=1800, validate_outputs=None):
    from .stage1.replicas import prepare_env,script_command
    from .isolation import command,clean_environment
    if spec.route not in {'claude_p','openrouter'}:
        raise ValueError('tool-free generation requires an enforced no-tools client')
    if spec.route=='openrouter':
        from . import metered_generation
        if not metered_generation.enabled():raise ValueError('OpenRouter source generation requires an explicit shared metered budget')
        budget=json.loads(Path(os.environ['REPROSCOPE_METERED_BUDGET_FILE']).read_text())
        if budget['model']!=spec.model:raise ValueError('Source model differs from the authorized budget model')
    work=Path(work);log_path=Path(log_path);log_path.parent.mkdir(parents=True,exist_ok=True)
    payload=inputs(work)
    base=prompt+'\n\nExecution mode: you have no file or shell tools. The approved files are supplied below as JSON. Return source files only through the schema. Write '+script_stem+'.py (or .R), plus source helpers if needed. The controller executes your script in a fresh OS-restricted directory and returns errors for repair. Your script must create all required JSON/CSV outputs and trace.json itself. Use only installed numpy, pandas, scipy, statsmodels or base R; no package installation. Do not include precomputed results. Paths are relative to the supplied working directory.\n\n'+json.dumps(payload)
    base+='\nBundle.files accepts ONLY .py/.R source code. Do not return results.json, trace.json, analysis_plan.json, requirements.txt or any other non-code file in the bundle, even when TASK.md asks for those outputs. The submitted program must create its JSON/CSV/trace outputs during execution. No dependency file is needed in this execution mode.'
    if stage=='1':
        from .plan_protocol import ExtendedPlanDocument
        base+='\nThe generated analysis_plan.json must conform to this exact schema. Select the proper family schema separately for each analysis; do not use one merged dictionary of fields for every family. Required fields and nullability differ. Unsupported entries cannot satisfy an executable requested analysis.\n'+json.dumps(ExtendedPlanDocument.model_json_schema())
    repair='';events=[];calls=[];result=None
    for attempt in range(1,MAX_ATTEMPTS+1):
        if spec.route=='openrouter':
            result=metered_generation.call(base+repair,paper_id=paper_id,stage=stage,
                step=f'{stage}:bounded_generate:{attempt}',schema=Bundle,
                log_path=log_path.with_name(log_path.stem+f'_attempt{attempt}.log'))
        else:
            result=llm.call(f'{stage}:bounded_generate:{attempt}',base+repair,paper_id=paper_id,stage=stage,
            route=spec.route,model=spec.model,agentic=False,cwd=work,schema=Bundle,timeout_s=timeout_s,
            large_context=True,log_path=log_path.with_name(log_path.stem+f'_attempt{attempt}.log'))
        calls.append(result.ledger_id)
        if not result.ok or result.parsed is None:break
        try:
            # Every attempt must create its own outputs; a successful no-op may not inherit a previous attempt's results.
            import shutil
            for prior in (work/'out').iterdir():
                if prior.is_dir() and not prior.is_symlink():shutil.rmtree(prior)
                else:prior.unlink()
            write_sources(work,result.parsed)
        except ValueError as exc:
            repair='\nThe source-file contract failed: '+str(exc)+'. Return only source files, with analysis.py (or .R) / multiverse.py (or .R) basenames; the script must generate result/trace files.'
            events.append({'attempt':attempt,'exit_code':None,'source_contract_error':str(exc)})
            continue
        script=next((work/'out'/(script_stem+ext) for ext in ('.py','.R') if (work/'out'/(script_stem+ext)).exists()),None)
        if script is None:
            repair='\nReturn the required main script, not only helper files.';continue
        environment=prepare_env(work/'out',work.parent)
        if environment['error']:raise RuntimeError(environment['error'])
        cmd,boundary=command(script_command(script,work,environment['interpreter']),work,environment['env'])
        try:
            proc=subprocess.run(cmd,cwd=work,capture_output=True,text=True,timeout=300,
                env=clean_environment({**os.environ,**environment['env']},work))
        except subprocess.TimeoutExpired:
            events.append({'attempt':attempt,'exit_code':124,'isolation':boundary,'error':'execution exceeded 300 seconds'})
            repair='\nThe script exceeded the 300-second execution budget. Return complete, computationally efficient source files implementing the same declared methods. Prior sources:\n'+result.parsed.model_dump_json()
            continue
        output=(proc.stdout or '')+(proc.stderr or '')
        (work/'out/run.log').write_text(output)
        events.append({'attempt':attempt,'exit_code':proc.returncode,'isolation':boundary})
        if proc.returncode==0:
            try:
                validation_errors = validate_outputs(work) if validate_outputs else []
            except (ValueError, TypeError, KeyError, OSError) as exc:
                validation_errors = [f"Output validation could not complete: {exc}"]
            events[-1]['validation_errors'] = validation_errors
            if not validation_errors:break
            repair='\nThe script ran, but output/method verification failed. Correct the implementation and return complete source files. No paper target values are supplied. Failures:\n'+json.dumps(validation_errors)+'\nPrior sources:\n'+result.parsed.model_dump_json()
            continue
        repair='\n\nThe prior source failed. Return complete corrected sources. Failure log:\n'+output[-18000:]+'\nPrior sources:\n'+result.parsed.model_dump_json()
    receipt={'version':VERSION,'status':'enforced','tool_surface':'none','route':spec.route,
        'client_protocol':llm.ROUTE_PROTOCOL_VERSIONS.get(spec.route,'openrouter-no-tools-budget-1'),
        'inputs':{p['path']:hashlib.sha256(p['content'].encode()).hexdigest() for p in payload},
        'model_calls':calls,'executions':events}
    log_path.write_text(json.dumps(receipt,indent=2)+'\n')
    (work/'out/generation_boundary.json').write_text(json.dumps(receipt,indent=2)+'\n')
    if result is None:raise RuntimeError('generation did not run')
    if not events or events[-1]['exit_code']!=0 or events[-1].get('validation_errors'):
        result.ok=False;result.error='bounded generation did not produce a successful execution'
    return result

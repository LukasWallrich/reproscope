"""Stage 3 — robustness: the specification curve on the focal claim.

`run(paper_id, force=False)` walks the seven steps in multiverse.py. Each step that
costs a model call or an agent run reads its own output file first and re-does the work
only when that file is missing or `force` is set, so an interrupted stage resumes at the
step that failed. The grid build is free and deterministic, so it runs every time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import artifacts, config, llm, paths, provenance
from .. import focal as focal_mod
from ..artifacts import (
    ArtifactMeta,
    ClaimRecord,
    EstimandContract,
    FactorLevel,
    SpecFactor,
    SpecificationSpace,
    SpecRun,
)
from . import multiverse as mv

__all__ = ["run", "executor_stale"]

PROMPTS = ("stage3_enumerate", "stage3_paper_level", "stage3_screen",
           "stage3_execute", "stage3_interpret")


def _step(path: Path, force: bool):
    """True when the step must run: no output yet, or the caller forced a rerun."""
    return force or not path.exists()


def _step_keys(inputs: dict[str, str], *prefixes: str) -> dict[str, str]:
    return {k: v for k, v in inputs.items()
            if k.startswith("data:")
            or any(k == p or k.startswith(p) for p in prefixes)}


def _step_stale(
    path: Path,
    force: bool,
    inputs: dict[str, str],
    key_prefixes: tuple[str, ...],
    prompt_names: tuple[str, ...] = (),
) -> bool:
    """True when the step must run: missing, forced, an input changed, or a prompt did.

    Each step records the subset of `_stage_inputs` it reads, plus the version of any
    prompt it calls, under `_inputs` / `_prompt_versions` in its own output file. A file
    that exists but was built from now-stale inputs must not be treated as current.
    """
    if force or not path.exists():
        return True
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return True
    wanted = _step_keys(inputs, *key_prefixes)
    if data.get("_inputs", {}) != wanted:
        return True
    if data.get("_step_provenance") != _step_provenance(prompt_names):
        return True
    recorded_prompts = data.get("_prompt_versions", {})
    return any(recorded_prompts.get(n) != artifacts.prompt_version(n) for n in prompt_names)


def _stamp(out: dict[str, Any], inputs: dict[str, str], key_prefixes: tuple[str, ...],
           prompt_names: tuple[str, ...] = ()) -> dict[str, Any]:
    out["_inputs"] = _step_keys(inputs, *key_prefixes)
    out["_step_provenance"] = _step_provenance(prompt_names)
    if prompt_names:
        out["_prompt_versions"] = {n: artifacts.prompt_version(n) for n in prompt_names}
    return out


def _step_provenance(prompt_names: tuple[str, ...]) -> dict:
    """Generation follows its schema, prompt/model and context-building functions.

    Verification/reporting code changes must not launch a new enumeration, whose
    stochastic differences could otherwise trigger another executor generation.
    """
    import inspect
    schemas = {"stage3_enumerate": mv.EnumerateOut, "stage3_paper_level": mv.PaperLevelsOut,
               "stage3_screen": mv.ScreenOut}
    tiers = {"stage3_enumerate": "cheap", "stage3_paper_level": "cheap",
             "stage3_screen": "strong_alt", "stage3_interpret": "strong"}
    helpers = {"stage3_enumerate": (_schema_text, _traces_text, _trace_context),
               "stage3_paper_level": (mv.derive_paper_levels,),
               "stage3_screen": (_schema_text,),
               "stage3_interpret": (mv.interpretation_prompt, mv.parse_interpretation, mv.defensible_csv)}
    if not prompt_names:
        return {"focal_code": provenance.implementation("focal.py", "statistical.py")}
    return {name: {"schema": provenance.digest(schemas[name].model_json_schema()) if name in schemas else None,
                   "model": config.tier(tiers[name]).model_dump(),
                   "context_code": provenance.digest([inspect.getsource(fn) for fn in helpers[name]])}
            for name in prompt_names}


def executor_stale(stage3_dir: Path, grid_sha: str, *, force: bool,
                   dependencies: dict[str, str] | None = None, check_outputs: bool = True) -> bool:
    """Whether step 4 must run again.

    True when there is no execution report, when the specs.csv it produced is gone, or
    when the grid has changed since it ran — ranking rows built from an older grid
    against the current one would go unnoticed otherwise.
    """
    execute_path = Path(stage3_dir) / "execute.json"
    if force or not execute_path.exists():
        return True
    if not (Path(stage3_dir) / "work" / "out" / "specs.csv").exists():
        return True
    record = json.loads(execute_path.read_text())
    if record.get("grid_sha") != grid_sha:
        return True
    if dependencies is not None:
        if record.get("_inputs") != dependencies:
            return True
        if not check_outputs:
            return False
        work = Path(stage3_dir) / "work" / "out"
        script = next((work / n for n in ("multiverse.R", "multiverse.py") if (work / n).exists()), None)
        current = mv.executor_outputs(work.parent)
        return record.get("output_fingerprint") != current
    return False


def _stage_inputs(paper_id: str) -> dict[str, str]:
    """Hashes of everything Stage 3 reads, for the done.json check.

    Artifact files (claims, contracts, readiness, match, traces) are hashed on their
    analytical payload, not the file: `meta` carries a timestamp and call ids that
    change on every re-save without changing the content.
    """
    file_hashed = {
        "manifest": paths.corpus_dir(paper_id) / "manifest.json",
        "schema": paths.run_dir(paper_id, 0) / "schema.json",
        "paper_text": paths.run_dir(paper_id, 0) / "paper.txt",
        "paper_text:corpus": paths.corpus_dir(paper_id) / "paper.txt",
        "generation_transcript": paths.run_dir(paper_id, 3) / "logs/execute.log",
    }
    out = {n: artifacts.sha256_file(p) for n, p in file_hashed.items() if p.exists()}
    out.update(provenance.corpus(paper_id))
    from .. import review_backend
    out["review_backend"] = review_backend.fingerprint()
    out["implementation"] = provenance.implementation()
    out["scoped_reference"] = artifacts.sha256_file(Path(__file__).parent.parent / "scoped_reference.R")
    out["scoped_plots"] = artifacts.sha256_file(Path(__file__).parent.parent / "scoped_plots.R")
    out["active_models"] = provenance.digest(config.config().model_dump())
    out.update(provenance.files({"models": paths.ROOT / "models.toml"}))
    for script in (paths.run_dir(paper_id, 1) / "replicas").glob("*/work/out/*"):
        if script.suffix.lower() in {".py", ".r"}:
            out[f"script:{script.relative_to(paths.run_dir(paper_id, 1))}"] = artifacts.sha256_file(script)

    artifact_hashed = {
        "claims": (paths.run_dir(paper_id, 0) / "claims.json", ClaimRecord),
        "contracts": (paths.run_dir(paper_id, 0) / "contracts.json", EstimandContract),
        "readiness": (paths.run_dir(paper_id, 0) / "readiness.json", artifacts.DataReadinessRecord),
        "match": (paths.run_dir(paper_id, 1) / "match.json", artifacts.ComparableResult),
    }
    for name, (p, cls) in artifact_hashed.items():
        if p.exists():
            out[name] = artifacts.content_hash(artifacts.load(cls, p))

    traces = sorted((paths.run_dir(paper_id, 1) / "replicas").glob("*/trace.json"))
    for t in traces:
        out[f"trace:{t.parent.name}"] = artifacts.content_hash(
            artifacts.load(artifacts.ReplicaDecisionTrace, t)
        )
        out[f'trace_context:{t.parent.name}']=provenance.digest(_trace_context(json.loads(t.read_text()),t.parent.name))
    for name in PROMPTS:
        out[f"prompt:{name}"] = artifacts.prompt_version(name)
    return out


def _load_claims(paper_id: str) -> list[ClaimRecord]:
    p = paths.run_dir(paper_id, 0) / "claims.json"
    got = artifacts.load(ClaimRecord, p)
    return got if isinstance(got, list) else [got]


def _schema_text(paper_id: str) -> str:
    stage0 = paths.run_dir(paper_id, 0)
    for name in ("schema.json", "readiness.json"):
        if (stage0 / name).exists():
            return (stage0 / name).read_text()
    return "{}"


def _trace_context(d, replica_id):
    return {'replica_id':d.get('replica_id',replica_id),
            **{k:d.get(k,[]) for k in ('open_choices','filters','transformations')},
            **{k:d.get(k) for k in ('ran','model_formula','missingness')},
            'estimator_settings':d.get('estimator_settings',{})}


def _traces_text(paper_id: str) -> str:
    """The replicas' open choices and formulas — the enumerator's first source."""
    items = []
    for t in sorted((paths.run_dir(paper_id, 1) / "replicas").glob("*/trace.json")):
        d = json.loads(t.read_text())
        items.append(_trace_context(d,t.parent.name))
    return json.dumps(items, indent=2)


STEPS = ("focal", "enumerate", "paper_level", "screen", "execute", "rank", "interpret")


def _verify_generated_execution(path, work, grid, paper_id, generated, verification_inputs):
    """Keep completed generation resumable even if its verifier raises."""
    mv._write_json(path, generated)
    generated.update(mv.verify_execution(work, grid, paper_id))
    generated["verification_inputs"] = verification_inputs
    mv._write_json(path, generated)


def run(paper_id: str, force: bool = False, force_steps: set[str] | None = None) -> SpecificationSpace:
    force_steps = force_steps or set()

    def fstep(name: str) -> bool:
        return force or name in force_steps

    stage3 = paths.run_dir(paper_id, 3)
    inputs = _stage_inputs(paper_id)
    space_path = stage3 / "space.json"
    if not force and not force_steps and paths.is_done(stage3, inputs) and space_path.exists():
        print(f"stage 3: up to date ({space_path})", flush=True)
        return artifacts.load(SpecificationSpace, space_path)  # type: ignore[return-value]

    calls: list[str] = []
    manifest = paths.manifest(paper_id)
    claims = _load_claims(paper_id)
    contracts = mv._load_contracts(paper_id)

    # --- 1. focal claim binding ------------------------------------------
    focal_path = stage3 / "focal.json"
    focal_keys = ("manifest", "claims", "contracts")
    if _step_stale(focal_path, fstep("focal"), inputs, focal_keys):
        focal = focal_mod.bind_focal_claim(manifest, claims, contracts, paper_id=paper_id)
        mv._write_json(focal_path, _stamp(focal, inputs, focal_keys))
    focal = mv._read_json(focal_path)
    inputs["focal"] = provenance.digest({k: v for k, v in focal.items() if not k.startswith("_")})
    fq = focal["focal_quantity"]
    print(f"stage 3: focal quantity {fq['kind']} = {fq['reported_value']} "
          f"(claim {fq['claim_id']}, analysis {focal['analysis_id']})", flush=True)

    focal_contract = next(
        (c for c in contracts if c.analysis_id == focal["analysis_id"]), None
    )

    if focal_contract is None:
        raise ValueError("focal analysis has no matching contract")

    policy = getattr(manifest, "multiverse_policy", {}) or {}
    if policy.get("mode") == "scoped_paired" or config.config().scoped_multiverse:
        from .. import scoped_multiverse
        space = scoped_multiverse.run(paper_id, focal, inputs)
        space.generator = "scoped_paired"
        artifacts.save(space,space_path)
        paths.mark_done(stage3, _stage_inputs(paper_id))
        print(f"stage 3: {space.state}, {space.n_specs} scoped paired specifications", flush=True)
        return space

    # --- 2. enumerate -----------------------------------------------------
    proposed_path = stage3 / "factors_proposed.json"
    enumerate_keys = ("manifest", "contracts", "schema", "trace_context:", "focal")
    if _step_stale(proposed_path, fstep("enumerate"), inputs, enumerate_keys, ("stage3_enumerate",)):
        prompt = artifacts.load_prompt(
            "stage3_enumerate",
            contract=focal_contract.model_dump_json(indent=2),
            schema=_schema_text(paper_id),
            traces=_traces_text(paper_id),
        )
        r = llm.call("enumerate", prompt, paper_id=paper_id, stage="3",
                     tier="cheap", schema=mv.EnumerateOut,
                     log_path=stage3 / "logs" / "enumerate.log")
        if not r.ok or r.parsed is None:
            raise RuntimeError(f"stage 3 enumerate failed: {r.error}")
        out = r.parsed.model_dump()
        out["_ledger_id"] = r.ledger_id
        mv._write_json(proposed_path, _stamp(out, inputs, enumerate_keys, ("stage3_enumerate",)))
    proposed = mv._read_json(proposed_path)
    inputs["proposed"] = provenance.digest({k: v for k, v in proposed.items() if not k.startswith("_")})
    calls.append(proposed.get("_ledger_id", ""))
    calls.extend(proposed.get('_dimension_refinement_calls',[]))
    calls.extend(proposed.get('_operational_repair_calls',[]))
    print(f"stage 3: {len(proposed.get('factors', []))} factors proposed", flush=True)

    # --- 2b. what the paper itself did -----------------------------------
    paper_path = stage3 / "paper_level.json"
    paper_level_keys = ("manifest", "claims", "contracts", "schema", "proposed", "focal", "paper_text")
    if _step_stale(paper_path, fstep("paper_level"), inputs, paper_level_keys, ("stage3_paper_level",)):
        mv._write_json(
            paper_path,
            _stamp(
                mv.derive_paper_levels(paper_id, proposed, focal),
                inputs, paper_level_keys, ("stage3_paper_level",),
            ),
        )
    paper = mv._read_json(paper_path)
    calls.append(paper.get("_ledger_id", ""))
    print(f"stage 3: paper levels from {paper['source']}", flush=True)
    for note in paper.get("notes", []):
        print(f"stage 3:   {note}", flush=True)

    # --- 3. screen + grid -------------------------------------------------
    screen_path = stage3 / "screen.json"
    screen_keys = ("manifest", "contracts", "schema", "proposed", "focal")
    if _step_stale(screen_path, fstep("screen"), inputs, screen_keys, ("stage3_screen",)):
        prompt = artifacts.load_prompt(
            "stage3_screen",
            contract=focal_contract.model_dump_json(indent=2),
            schema=_schema_text(paper_id),
            factors=json.dumps(proposed.get("factors", []), indent=2),
        )
        r = llm.call("screen", prompt, paper_id=paper_id, stage="3",
                     tier="strong_alt", schema=mv.ScreenOut,
                     log_path=stage3 / "logs" / "screen.log")
        if not r.ok or r.parsed is None:
            raise RuntimeError(f"stage 3 screen failed: {r.error}")
        out = r.parsed.model_dump()
        out["_ledger_id"] = r.ledger_id
        mv._write_json(screen_path, _stamp(out, inputs, screen_keys, ("stage3_screen",)))
    screen = mv._read_json(screen_path)
    from .. import screen_completion
    screen=screen_completion.complete(paper_id,proposed,screen,focal_contract.model_dump_json(indent=2),
        _schema_text(paper_id),stage3/'screen_completion')
    mv._write_json(screen_path,screen)
    calls.append(screen.get("_ledger_id", ""))
    calls.extend(screen.get('_screen_completion_calls',[]))
    from .. import proposal_repair
    revised=proposal_repair.repair(paper_id,proposed,screen,focal_contract.model_dump_json(indent=2),
        _schema_text(paper_id),stage3/'operational_repairs')
    if revised is not None:
        mv._write_json(proposed_path,_stamp(revised,inputs,enumerate_keys,('stage3_enumerate',)))
        print('stage 3: operationally incomplete options receive one repair and independent rescreen',flush=True)
        return run(paper_id,force_steps={'paper_level','screen'})

    from .. import method_completion
    screen=method_completion.complete(paper_id,proposed,screen,paper.get('levels'),
        focal_contract.model_dump_json(indent=2),_schema_text(paper_id),stage3/'method_completion')
    calls.extend(screen.get('_method_completion_calls',[]))
    mv._write_json(stage3/'completed_screen.json',screen)

    # The grid is a pure function of the enumerator, the screen and the paper levels, and
    # costs nothing to build, so it is rebuilt every run rather than reused from disk.
    # Identical inputs give identical bytes, hence the same grid_sha and no executor churn.
    grid_path = stage3 / "grid.json"
    mv._write_json(grid_path, mv.build_grid(proposed, screen, paper_id=paper_id,
                                            paper_levels=paper.get("levels")))
    grid = mv._read_json(grid_path)
    from .. import dimension_refinement
    active=dimension_refinement.active_dimensions(grid)
    target=config.config().multiverse_min_active_dimensions
    if target and len(active)<target and not grid.get('blocking_issues'):
        refined=dimension_refinement.refine(paper_id,proposed,screen,grid,
            focal_contract.model_dump_json(indent=2),_schema_text(paper_id),_traces_text(paper_id),
            stage3/'dimension_refinement',target)
        if refined is not None:
            mv._write_json(proposed_path,_stamp(refined,inputs,enumerate_keys,('stage3_enumerate',)))
            print(f'stage 3: {len(active)} varying dimensions after screening; refining the proposal before execution',flush=True)
            return run(paper_id,force_steps={'paper_level','screen'})
        grid.setdefault('blocking_issues',[]).append(f'Only {len(active)} varying analytical dimensions are defensible; configured target {target} was not reached after bounded refinement.')
    mv._write_json(stage3/'dimension_goal.json',{'active_dimensions':active,'minimum_active_dimensions':target,
        'refinement_calls':proposed.get('_dimension_refinement_calls',[]),'met':len(active)>=target})
    grid["result_contract_version"] = 1
    grid["proposed_dimensions"] = len(proposed.get("factors",[]))
    from .. import multiverse_contract as scope_contract
    grid['reporting_rules_required']=True
    grid['reporting_rules']=screen.get('reporting_rules') or []
    for scope_attempt in range(3):
        try:
            grid['primary_effect'] = scope_contract.primary_effect(screen, focal_contract, focal)
            grid['effect_metric'] = grid['primary_effect']['metric']
            grid['curve_reference'] = scope_contract.reference(grid['primary_effect'], claims, focal_contract)
            grid['reporting_contracts'] = {s['spec_id']:scope_contract.specification_scope(s,grid) for s in mv.enumerate_specs(grid)}
            break
        except ValueError as exc:
            if scope_attempt==2 or grid.get('blocking_issues'):
                grid.setdefault('blocking_issues',[]).append(str(exc));break
            if not (stage3/'screen_before_scope_repair.json').exists():
                mv._write_json(stage3/'screen_before_scope_repair.json',screen)
            rules,cid=scope_contract.repair_rules(paper_id,grid,[str(exc)],scope_attempt+1)
            if cid:calls.append(cid)
            grid['reporting_rules']=rules;screen['reporting_rules']=rules
            screen.setdefault('_scope_repair_calls',[]).append(cid)
            mv._write_json(screen_path,screen)
    mv._write_json(grid_path, grid)
    n_rejected = len(grid.get("rejected_levels", []))
    n_flagged = len(grid.get("paper_level_flagged", []))
    print(f"stage 3: grid of {grid['grid_size']} specifications over "
          f"{len(active)} varying dimensions ({len(grid['factors'])} listed factors; {n_rejected} levels rejected, "
          f"{n_flagged} documented levels excluded from the defensible curve)", flush=True)
    if grid.get("sampled"):
        print(f"stage 3: executing {grid['n_specs']} of them "
              f"({grid['sample_fraction']:.2%}) as a stratified sample seeded from the "
              f"paper id", flush=True)

    # Nothing the screen accepted, other than the paper's own choices, can change the
    # estimate or its significance: there is no curve to draw, and the executor, the
    # ranking and the reading would all cost model time to reach that same conclusion.
    if grid.get("blocking_issues") or not mv.result_moving_levels(grid):
        space = _abstain(paper_id, focal, grid, proposed, paper, inputs, calls)
        artifacts.save(space, space_path)
        paths.mark_done(stage3, _stage_inputs(paper_id))
        print(f"stage 3: {space.abstain_reason}", flush=True)
        print(f"stage 3: wrote {space_path}", flush=True)
        return space

    # --- 4. execute + verify ---------------------------------------------
    execute_path = stage3 / "execute.json"
    # A failed executor still writes its report, so resume on the artefact that matters:
    # without specs.csv there is nothing to rank, and step 4 runs again.
    # Rerun the executor when there is no report, no specs.csv to rank, or when the grid
    # has changed under a specs.csv produced from an older one.
    grid_sha = artifacts.sha256_file(grid_path)
    specs_existing = stage3 / "work" / "out" / "specs.csv"
    base_id, base_script, _, _ = mv._best_replica(paper_id, focal)
    executor_prompt=artifacts.load_prompt('stage3_execute')
    if focal_contract.covariates:
        executor_prompt+='\n\nFor directly bound adjusted models, the reference also accepts family="partial_correlation" with covariates=[every exact adjustment column], scalar x/y and an intercept, or family="linear_regression" with x as outcome, y=null, predictors=[the full exact design without the intercept], coefficient=<target predictor or null for an overall-model target>. Declare intercept=true, covariance="classical", transformations=[], missingness="complete_cases", numeric_parsing="strict_float", and the realised included_ids. Partial-correlation p-values use n-k-2 df for k covariates. These forms verify directly deposited numeric columns with classical inference. Rank, robust, weighted, transformed and bootstrap alternatives remain unsupported by this reference unless another explicitly documented protocol covers them; faithfully execute their screened methods and identify the verification limit.'
    execute_inputs = {
        **provenance.corpus(paper_id), "grid": grid_sha,
        "focal_contract": provenance.digest(focal_contract.model_dump()),
        "focal": inputs["focal"], "base_replica": base_id or "missing",
        "base_script": artifacts.sha256_file(base_script) if base_script else "missing",
        "prompt": (provenance.digest(executor_prompt) if focal_contract.covariates else artifacts.prompt_version("stage3_execute")),
        "executor": provenance.digest(config.executor().model_dump()),
        "launch_version": "3", "model_client": provenance.implementation("llm.py"), **provenance.files({"environment": paths.ROOT / "uv.lock"}),
    }
    colliding_factors=[f["name"] for f in grid["factors"] if f["name"] in mv.RESULT_COLUMNS]
    if colliding_factors:execute_inputs["factor_namespace"]="separate-result-fields-1"
    verification_inputs = {
        "code": provenance.implementation("stage3/multiverse.py", "execution.py", "reference.py", "adjusted_reference.py", "isolation.py",
                                           "statistical.py", "stage1/audit.py", "stage1/replicas.py", "replica_env.py", "generation_access.py", "multiverse_contract.py", "multiverse_reference.py", "multiverse_perturbation.py", "bounded_generation.py", "executor_repair.py", "metered_generation.py", "verification_recipe.py", "closed_reference.py"),
        "audit_prompt": artifacts.prompt_version("stage1_hardcoding_audit"),
        "computational_protocol": artifacts.prompt_version("stage3_verification_protocol"),
        **provenance.files({"environment": paths.ROOT / "uv.lock"}),
    }
    executed_now = executor_stale(stage3, grid_sha, force=fstep("execute"),
                                  dependencies=execute_inputs, check_outputs=False)
    from .. import metered_generation
    if executed_now and not fstep('execute') and metered_generation.enabled() and execute_path.exists():
        prior=mv._read_json(execute_path)
        if prior.get('_inputs')==execute_inputs and (prior.get('executor') or {}).get('ok') is False:
            executed_now=False
    if executed_now and execute_path.exists():
        print("stage 3: the last execution no longer matches the grid; rerunning the executor",
              flush=True)
    if executed_now:
        try:
            mv.reference_specifications(grid)
        except ValueError as exc:
            grid["blocking_issues"] = [str(exc)]
            space = _abstain(paper_id, focal, grid, proposed, paper, inputs, calls)
            artifacts.save(space, space_path)
            paths.mark_done(stage3, _stage_inputs(paper_id))
            print(f"stage 3: reference contract blocked generation — {exc}", flush=True)
            return space
        assembled = mv.assemble_work(paper_id, focal, grid)
        work = Path(assembled["work"])
        spec = config.executor()
        prompt = executor_prompt + "\n\n" + artifacts.load_prompt("stage3_verification_protocol")
        if colliding_factors:
            prompt += "\nGrid-factor columns that collide with numerical result fields must use factor_<name>. Keep ci_method etc. for the actual result algorithm. Colliding factors: "+", ".join(colliding_factors)
        if grid.get("reporting_contracts"):
            from ..verification_recipe import prepare
            prepare(work, grid, paper_id)
        if spec.generation_mode == "tool_free":
            from ..bounded_generation import generate
            r = generate(work, paper_id=paper_id, stage="3", spec=spec, prompt=prompt,
                         log_path=stage3 / "logs" / "execute.log", script_stem="multiverse",
                         timeout_s=mv.EXECUTOR_TIMEOUT_S,
                         validate_outputs=lambda folder: mv.generation_checks(folder, grid))
        else:
            r = llm.call("execute", prompt, paper_id=paper_id, stage="3",
                         route=spec.route, model=spec.model, agentic=True, cwd=work,
                         timeout_s=mv.EXECUTOR_TIMEOUT_S,
                         log_path=stage3 / "logs" / "execute.log")

        report = dict(assembled)
        report["specs_csv"] = str(work / "out" / "specs.csv")
        report["grid_sha"] = grid_sha
        report["_inputs"] = execute_inputs
        report["executor"] = {"route": spec.route, "model": spec.model,
                              "ok": r.ok, "error": r.error, "ledger_id": r.ledger_id,
                              "duration_s": round(r.duration_s, 1)}
        report["_ledger_id"] = r.ledger_id
        _verify_generated_execution(execute_path, work, grid, paper_id, report, verification_inputs)
    execute = mv._read_json(execute_path)
    work = stage3 / "work"
    transcript = stage3 / "logs/execute.log"
    transcript_sha = artifacts.sha256_file(transcript) if transcript.exists() else None
    if not executed_now and (
        execute.get("verification_inputs") != verification_inputs
        or (execute.get("generation_access") or {}).get("transcript_sha256") != transcript_sha
        or execute.get("output_fingerprint") != mv.executor_outputs(work)
        or (execute.get("audit") or {}).get("verdict") in {None, "not_run", "unparsed"}
    ):
        verified = mv.verify_execution(work, grid, paper_id)
        execute.update(verified)
        execute["verification_inputs"] = verification_inputs
        mv._write_json(execute_path, execute)
    if config.executor().generation_mode=='tool_free' and (execute.get('problems') or (execute.get('executor') or {}).get('ok') is False):
        from ..executor_repair import repair
        execute=repair(work,grid,paper_id,execute,executor_prompt)
        execute['verification_inputs']=verification_inputs
        mv._write_json(execute_path,execute)
    from ..stage1.audit import acceptance
    execute["acceptance"] = acceptance(execute.get("audit") or {}) if not execute.get("problems") else "rejected"
    calls.append(execute.get("_ledger_id", ""))
    calls.append((execute.get("audit") or {}).get("_ledger_id", ""))
    if execute.get("problems"):
        for p in execute["problems"]:
            print(f"stage 3: executor problem — {p}", flush=True)
    specs_path = Path(execute["specs_csv"])
    if not specs_path.exists():
        grid['blocking_issues']=list(execute.get('problems') or ['executor produced no specifications'])
        space=_abstain(paper_id,focal,grid,proposed,paper,inputs,calls)
        space.execution=execute
        space.attempted_specs=0
        artifacts.save(space,space_path)
        (stage3/'done.json').unlink(missing_ok=True)
        raise RuntimeError(f"stage 3: no specs.csv at {specs_path}; see {stage3 / 'logs'}")
    # A partial or non-reproducing specs.csv is not a curve: ranking it and paying a
    # strong call to read it would report a multiverse that was never run.
    executor_failed = (execute.get("executor") or {}).get("ok") is False
    if executor_failed or execute.get("problems"):
        grid["blocking_issues"] = list(execute.get("problems") or [])
        if executor_failed:
            grid["blocking_issues"].append("executor generation failed or was interrupted: "
                + str((execute.get("executor") or {}).get("error")))
        space = _abstain(paper_id, focal, grid, proposed, paper, inputs, calls)
        space.execution = execute
        space.attempted_specs = len(mv.read_specs(specs_path, grid))
        artifacts.save(space, space_path)
        paths.mark_done(stage3, _stage_inputs(paper_id))
        print(f"stage 3: attempted outputs retained; analytical acceptance abstained — {space.abstain_reason}", flush=True)
        return space
    if execute.get("acceptance") != "accepted":
        grid["blocking_issues"] = ["executor audit requires adjudication before analytical acceptance"]
        space = _abstain(paper_id, focal, grid, proposed, paper, inputs, calls)
        space.execution = execute
        artifacts.save(space, space_path)
        (stage3 / "done.json").unlink(missing_ok=True)
        return space
    rows = mv.read_specs(specs_path, grid)

    # --- 5. rank ----------------------------------------------------------
    # A rerun of the executor makes any earlier ranking and reading of the curve stale.
    rank_path = stage3 / "rank.json"
    mv._write_json(rank_path, mv.rank_reported(
        [r for r in rows if r.get('effect_group')==grid['curve_reference']['effect_group'] and r.get('effect_metric')==grid['curve_reference']['metric']], grid['curve_reference']['value'], grid,
        precision=grid["curve_reference"].get("precision"), quantity_kind=grid["curve_reference"]["metric"]))
    ranking = mv._read_json(rank_path)
    print(f"stage 3: same-scale reported {grid['curve_reference']['value']} — {ranking.get('share_below')} of "
          f"{ranking.get('n_converged')} converged estimates below it, "
          f"{ranking.get('share_above')} above (extremeness "
          f"{ranking.get('extremeness')}, rank {ranking.get('rank')})", flush=True)

    # --- 6. interpret -----------------------------------------------------
    interp_md = stage3 / "interpretation.md"
    interp_json = stage3 / "interpretation.json"
    from .. import review_backend
    interpretation_inputs = {"specs": artifacts.sha256_file(specs_path), "grid": grid_sha,
                             "focal": inputs["focal"], "review_backend":review_backend.fingerprint(),
                             "verification":provenance.digest({k:(execute.get("reference") or {}).get(k) for k in ("status","checked","total","version","scope")})}
    interp_stale = _step_stale(interp_json, False, interpretation_inputs,
                              tuple(interpretation_inputs), ("stage3_interpret",))
    if (_step(interp_md, force) or _step(interp_json, force) or executed_now or interp_stale
            or "interpret" in force_steps):
        prompt = mv.interpretation_prompt(
            mv.defensible_csv(specs_path, grid), grid["curve_reference"]["value"], grid,
            method_context={
                'primary_effect':grid.get('primary_effect'),
                'focal_outcome':focal_contract.outcome,
                'contrast':(focal_contract.model_dump().get('identity') or {}).get('contrast'),
                'reference_verification':{k:(execute.get('reference') or {}).get(k) for k in ('status','checked','total','version','scope')},
                'perturbation_status':(execute.get('perturbation') or {}).get('status'),
                'declared_methods':[{'spec_id':e['spec_id'], **{k:e.get('recipe',{}).get(k) for k in ('design','estimator','rank','x','y','covariates','polynomial_column','polynomial_degree','spline_probabilities','scoring','transform','alternative','test','ci','adjustment','per_test_alpha')}} for e in execute.get('reference',{}).get('evidence',[])],
                'direction_rule':'For paired differences only, the contrast is x minus y. Correlation is an association, never x minus y: a negative coefficient means higher values of one variable accompany lower values of the other, conditional on the declared adjustment. Interpret the substantive scales accordingly.'
            }
        )
        r = review_backend.call("interpret", prompt, paper_id=paper_id, stage="3", tier="strong",
                     log_path=stage3 / "logs" / "interpret.log")
        if not r.ok:
            raise RuntimeError(f"stage 3 interpret failed: {r.error}")
        interp_md.write_text(r.text)
        from ..report.findings import sensitivity
        parsed = {"summary": sensitivity([{**r, "spec": {f["name"]:r.get("_factor_levels",r).get(f["name"]) for f in grid["factors"]}, "estimate":r["_estimate"], "p":r["_p"], "converged":r["_converged"]} for r in rows], grid["factors"])}
        parsed["_ledger_id"] = r.ledger_id
        parsed["_inputs"] = interpretation_inputs
        parsed["_step_provenance"] = _step_provenance(("stage3_interpret",))
        parsed["_prompt_versions"] = {"stage3_interpret": artifacts.prompt_version("stage3_interpret")}
        mv._write_json(interp_json, parsed)
    interpretation = mv._read_json(interp_json)
    calls.append(interpretation.get("_ledger_id", ""))

    # --- 7. assemble ------------------------------------------------------
    space = _assemble(paper_id, focal, grid, rows, ranking, execute,
                      interp_md.read_text(), interpretation, inputs, calls, paper)
    artifacts.save(space, space_path)
    paths.mark_done(stage3, _stage_inputs(paper_id))
    print(f"stage 3: wrote {space_path}", flush=True)
    return space


# A binding note that starts with one of these describes a determinate binding: the
# manifest fixed the claim, or the curve quantity was converted from a test statistic.
# Anything else is a fallback the reader should weigh, so the stage reports medium
# confidence. Matching what is known-good rather than what is known-shaky means a new
# fallback in focal.py reads as shaky until it is listed here.
DETERMINATE_BINDING_NOTES = (
    "focal claim fixed by the manifest",
    "only a t statistic was reported",
    "focal estimate stays on the",
)


def binding_is_determinate(notes: list[str]) -> bool:
    """Whether the focal binding rests on the manifest override or an exact match."""
    return all(
        any(n.startswith(prefix) for prefix in DETERMINATE_BINDING_NOTES)
        for n in notes
    )


def _factors(grid: dict[str, Any]) -> list[SpecFactor]:
    factors: list[SpecFactor] = []
    for f in grid["factors"]:
        # A level the paper itself used carries verdict "paper"; `screen_verdict` says
        # what the screen made of it, so a reader can see when the screen would have
        # thrown out the paper's own choice.
        levels = [FactorLevel(value=lv["value"], verdict=lv.get("verdict", "defensible"),
                              rationale=lv.get("rationale"), how=lv.get("how"),
                              affects=lv.get("affects", "estimate"),
                              screen_verdict=lv.get("screen_verdict", "defensible"),
                              **{k:lv.get(k) for k in ("role","effect_group","null_group","estimator","effect_metric","comparability_rationale")})
                  for lv in f["levels"]]
        levels += [FactorLevel(value=r["level"], verdict="rejected", rationale=r["rationale"])
                   for r in grid.get("rejected_levels", []) if r["factor"] == f["name"]]
        src = f.get("source")
        factors.append(SpecFactor(
            name=f["name"],
            source=src if src in ("trace", "grid", "default", "code") else None,
            levels=levels,
            field=f.get("field"),
            paper_level=f.get("paper_level"),
        ))
    return factors


def _abstain(
    paper_id: str,
    focal: dict[str, Any],
    grid: dict[str, Any],
    proposed: dict[str, Any],
    paper: dict[str, Any],
    inputs: dict[str, str],
    calls: list[str],
) -> SpecificationSpace:
    """The specification space when no implementable factor can move the estimate."""
    unimplementable = grid.get("unimplementable", [])
    reason = "; ".join(grid.get("blocking_issues", [])) or (
        "no implementable factor can move the estimate or its significance; "
        f"{len(unimplementable)} unimplementable factors listed"
    )
    return SpecificationSpace(
        meta=ArtifactMeta(
            artifact="SpecificationSpace", stage="3", inputs=inputs,
            prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
            model_calls=[c for c in calls if c],
        ),
        state="abstained",
        generator="general",
        abstain_reason=reason,
        confidence="low" if grid.get("blocking_issues") else "medium",
        open_ambiguities=(list(grid.get("notes", [])) + list(focal.get("notes", []))
                          + list(paper.get("notes", []))),
        claim_id=focal["focal_quantity"]["claim_id"],
        factors=_factors(grid),
        unimplementable=unimplementable,
        incompatibilities=[[i["a"], i["b"]] for i in grid.get("incompatible", [])],
        grid_size=grid.get("grid_size"),
        runs=[],
        reported_estimate=(grid.get("curve_reference") or {}).get("value"),
        curve_reference=grid.get("curve_reference"),
        n_specs=0,
        focal_binding_notes=list(focal.get("notes", [])),
        focal_quantity=focal["focal_quantity"],
        analysis_id=focal["analysis_id"],
        paper_level_source=paper.get("source"),
        screen_adjustments=grid.get("adjustments", []),
        dropped_factors=grid.get("dropped_factors", []),
    )


def _assemble(
    paper_id: str,
    focal: dict[str, Any],
    grid: dict[str, Any],
    rows: list[dict[str, Any]],
    ranking: dict[str, Any],
    execute: dict[str, Any],
    interpretation_md: str,
    interpretation: dict[str, Any],
    inputs: dict[str, str],
    calls: list[str],
    paper: dict[str, Any],
) -> SpecificationSpace:
    factors = _factors(grid)
    names = [f["name"] for f in grid["factors"]]
    runs = [SpecRun(spec={k: r.get("_factor_levels",r).get(k, "") for k in names},
                    estimate=r["_estimate"], se=r["_se"], p=r["_p"],
                    converged=r["_converged"], n=r.get("_n"), error=r.get("error") or None,
                    role=r.get("_role", "defensible"), effect_metric=r.get("effect_metric"),
                    p_threshold=r.get("_alpha"), spec_id=r.get("_spec_id"),
                    **{k:r.get(k) for k in ("effect_group", "null_group", "estimator", "ci_lower", "ci_upper", "ci_method", "ci_level", "p_raw", "p_adjustment", "inference_method")})
            for r in rows]

    problems = list(execute.get("problems", []))
    ambiguities = (list(grid.get("notes", [])) + list(focal.get("notes", []))
                   + list(paper.get("notes", [])))
    shaky_binding = not binding_is_determinate(list(focal.get("notes", [])))
    unresolved_author = bool(paper.get("unresolved"))
    unresolved_adjustments = any(a.get("status") != "applied" for a in grid.get("adjustments", []))
    if unresolved_adjustments:
        ambiguities.append("optional screen amendments remain unresolved")
    reference_incomplete = ((execute.get("reference") or {}).get("status") != "verified"
                            or (execute.get("perturbation") or {}).get("status") != "verified")
    if reference_incomplete:
        ambiguities.append("independent reference or input-perturbation validation is incomplete")
    if shaky_binding:
        ambiguities.append(
            "the focal claim was bound by a fallback rule, not by the manifest override "
            "or an exact numeric match; the whole curve rests on that binding"
        )

    return SpecificationSpace(
        meta=ArtifactMeta(
            artifact="SpecificationSpace", stage="3", inputs=inputs,
            prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
            model_calls=[c for c in calls if c],
        ),
        generator="general",
        dimension_accounting={"proposed":grid.get("proposed_dimensions"),
            "retained":{f['name']:[lv['value'] for lv in f['levels']] for f in grid['factors'] if len(f['levels'])>1},
            "executed":{name:sorted({str(r.get('_factor_levels',r).get(name,'')) for r in rows if r['_converged'] and r.get('_role')!='author_reference'}) for name in names
                        if len({str(r.get('_factor_levels',r).get(name,'')) for r in rows if r['_converged'] and r.get('_role')!='author_reference'})>1},
            "excluded_levels":grid.get('rejected_levels',[])},
        curve_reference=grid.get("curve_reference"), reported_quantity=focal["focal_quantity"],
        confidence="high" if not (problems or shaky_binding or unresolved_author or reference_incomplete or unresolved_adjustments) else "medium",
        open_ambiguities=ambiguities,
        claim_id=focal["focal_quantity"]["claim_id"],
        factors=factors,
        unimplementable=grid.get("unimplementable", []),
        incompatibilities=[[i["a"], i["b"]] for i in grid.get("incompatible", [])],
        grid_size=grid.get("grid_size"),
        runs=runs,
        reported_estimate=(grid.get("curve_reference") or {}).get("value"),
        rank=ranking.get("rank"),
        n_specs=grid.get("n_specs"),
        sensitivity_scope=grid.get("sensitivity_scope", "undetermined"),
        interpretation=interpretation_md,
        # extras (the artifact model allows them, and the report reads them)
        sampled=bool(grid.get("sampled")),
        sample_fraction=grid.get("sample_fraction"),
        exec_cap=grid.get("exec_cap"),
        n_converged=ranking.get("n_converged"),
        focal_binding_notes=list(focal.get("notes", [])),
        focal_quantity=focal["focal_quantity"],
        analysis_id=focal["analysis_id"],
        ranking=ranking,
        interpretation_json={k: v for k, v in interpretation.items() if k != "_ledger_id"},
        execution=execute,
        dropped_factors=grid.get("dropped_factors", []),
        screen_adjustments=grid.get("adjustments", []),
        verification_problems=problems,
        paper_level_spec=ranking.get("paper_level_spec"),
        paper_level_estimate=ranking.get("paper_level_estimate"),
        paper_level_source=paper.get("source"),
        paper_level_evidence=paper.get("evidence", {}),
        paper_level_flagged=grid.get("paper_level_flagged", []),
    )

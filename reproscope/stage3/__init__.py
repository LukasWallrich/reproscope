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

from .. import artifacts, config, llm, paths
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
    return {k: v for k, v in inputs.items() if any(k == p or k.startswith(p) for p in prefixes)}


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
    recorded_prompts = data.get("_prompt_versions", {})
    return any(recorded_prompts.get(n) != artifacts.prompt_version(n) for n in prompt_names)


def _stamp(out: dict[str, Any], inputs: dict[str, str], key_prefixes: tuple[str, ...],
           prompt_names: tuple[str, ...] = ()) -> dict[str, Any]:
    out["_inputs"] = _step_keys(inputs, *key_prefixes)
    if prompt_names:
        out["_prompt_versions"] = {n: artifacts.prompt_version(n) for n in prompt_names}
    return out


def executor_stale(stage3_dir: Path, grid_sha: str, *, force: bool) -> bool:
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
    return json.loads(execute_path.read_text()).get("grid_sha") != grid_sha


def _stage_inputs(paper_id: str) -> dict[str, str]:
    """Hashes of everything Stage 3 reads, for the done.json check.

    Artifact files (claims, contracts, readiness, match, traces) are hashed on their
    analytical payload, not the file: `meta` carries a timestamp and call ids that
    change on every re-save without changing the content.
    """
    file_hashed = {
        "manifest": paths.corpus_dir(paper_id) / "manifest.json",
        "schema": paths.run_dir(paper_id, 0) / "schema.json",
    }
    out = {n: artifacts.sha256_file(p) for n, p in file_hashed.items() if p.exists()}

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


def _traces_text(paper_id: str) -> str:
    """The replicas' open choices and formulas — the enumerator's first source."""
    items = []
    for t in sorted((paths.run_dir(paper_id, 1) / "replicas").glob("*/trace.json")):
        d = json.loads(t.read_text())
        items.append({
            "replica_id": d.get("replica_id", t.parent.name),
            "ran": d.get("ran"),
            "open_choices": d.get("open_choices", []),
            "filters": d.get("filters", []),
            "transformations": d.get("transformations", []),
            "model_formula": d.get("model_formula"),
            "missingness": d.get("missingness"),
            "estimator_settings": d.get("estimator_settings", {}),
        })
    return json.dumps(items, indent=2)


STEPS = ("focal", "enumerate", "paper_level", "screen", "execute", "rank", "interpret")


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
    fq = focal["focal_quantity"]
    print(f"stage 3: focal quantity {fq['kind']} = {fq['reported_value']} "
          f"(claim {fq['claim_id']}, analysis {focal['analysis_id']})", flush=True)

    focal_contract = next(
        (c for c in contracts if c.analysis_id == focal["analysis_id"]), contracts[0]
    )

    # --- 2. enumerate -----------------------------------------------------
    proposed_path = stage3 / "factors_proposed.json"
    enumerate_keys = ("manifest", "claims", "contracts", "schema", "trace:")
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
    calls.append(proposed.get("_ledger_id", ""))
    print(f"stage 3: {len(proposed.get('factors', []))} factors proposed", flush=True)

    # --- 2b. what the paper itself did -----------------------------------
    paper_path = stage3 / "paper_level.json"
    paper_level_keys = ("manifest", "claims", "contracts", "schema", "trace:")
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
    screen_keys = ("manifest", "claims", "contracts", "schema", "trace:")
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
    calls.append(screen.get("_ledger_id", ""))

    # The grid is a pure function of the enumerator, the screen and the paper levels, and
    # costs nothing to build, so it is rebuilt every run rather than reused from disk.
    # Identical inputs give identical bytes, hence the same grid_sha and no executor churn.
    grid_path = stage3 / "grid.json"
    mv._write_json(grid_path, mv.build_grid(proposed, screen, paper_id=paper_id,
                                            paper_levels=paper.get("levels")))
    grid = mv._read_json(grid_path)
    n_rejected = len(grid.get("rejected_levels", []))
    n_flagged = len(grid.get("paper_level_flagged", []))
    print(f"stage 3: grid of {grid['grid_size']} specifications over "
          f"{len(grid['factors'])} factors ({n_rejected} levels rejected, "
          f"{n_flagged} paper levels kept over the screen)", flush=True)
    if grid.get("sampled"):
        print(f"stage 3: executing {grid['n_specs']} of them "
              f"({grid['sample_fraction']:.2%}) as a stratified sample seeded from the "
              f"paper id", flush=True)

    # Nothing the screen accepted, other than the paper's own choices, can change the
    # estimate or its significance: there is no curve to draw, and the executor, the
    # ranking and the reading would all cost model time to reach that same conclusion.
    if not mv.result_moving_levels(grid):
        space = _abstain(paper_id, focal, grid, proposed, paper, inputs, calls)
        artifacts.save(space, space_path)
        paths.mark_done(stage3, inputs)
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
    if not execute_path.exists() and specs_existing.exists() and not force:
        # Execution happened but its report is gone (or was discarded to re-verify):
        # verify the existing specs.csv against the current grid without paying for a rerun.
        report = mv.verify_execution(stage3 / "work", grid, paper_id)
        report.update({"work": str(stage3 / "work"), "specs_csv": str(specs_existing),
                       "grid_sha": grid_sha, "executor": {"note": "re-verified existing output"}})
        mv._write_json(execute_path, report)
    executed_now = executor_stale(stage3, grid_sha, force=fstep("execute"))
    if executed_now and execute_path.exists():
        print("stage 3: the last execution no longer matches the grid; rerunning the executor",
              flush=True)
    if executed_now:
        assembled = mv.assemble_work(paper_id, focal, grid)
        work = Path(assembled["work"])
        spec = config.executor()
        prompt = artifacts.load_prompt("stage3_execute")
        r = llm.call("execute", prompt, paper_id=paper_id, stage="3",
                     route=spec.route, model=spec.model, agentic=True, cwd=work,
                     timeout_s=mv.EXECUTOR_TIMEOUT_S,
                     log_path=stage3 / "logs" / "execute.log")
        report = mv.verify_execution(work, grid, paper_id)
        report.update(assembled)
        report["grid_sha"] = grid_sha
        report["executor"] = {"route": spec.route, "model": spec.model,
                              "ok": r.ok, "error": r.error, "ledger_id": r.ledger_id,
                              "duration_s": round(r.duration_s, 1)}
        report["_ledger_id"] = r.ledger_id
        mv._write_json(execute_path, report)
    execute = mv._read_json(execute_path)
    calls.append(execute.get("_ledger_id", ""))
    calls.append((execute.get("audit") or {}).get("_ledger_id", ""))
    if execute.get("problems"):
        for p in execute["problems"]:
            print(f"stage 3: executor problem — {p}", flush=True)
    specs_path = Path(execute["specs_csv"])
    if not specs_path.exists():
        raise RuntimeError(f"stage 3: no specs.csv at {specs_path}; see {stage3 / 'logs'}")
    rows = mv.read_specs(specs_path, grid)

    # --- 5. rank ----------------------------------------------------------
    # A rerun of the executor makes any earlier ranking and reading of the curve stale.
    rank_path = stage3 / "rank.json"
    if _step(rank_path, force) or "rank" in force_steps or executed_now:
        mv._write_json(rank_path, mv.rank_reported(
            rows, fq.get("reported_value"), grid,
            precision=fq.get("reported_precision")))
    ranking = mv._read_json(rank_path)
    print(f"stage 3: reported {fq.get('reported_value')} — {ranking.get('share_below')} of "
          f"{ranking.get('n_converged')} converged estimates below it, "
          f"{ranking.get('share_above')} above (extremeness "
          f"{ranking.get('extremeness')}, rank {ranking.get('rank')})", flush=True)

    # --- 6. interpret -----------------------------------------------------
    interp_md = stage3 / "interpretation.md"
    interp_json = stage3 / "interpretation.json"
    interp_stale = json.loads(interp_json.read_text()).get("_prompt_versions", {}).get(
        "stage3_interpret"
    ) != artifacts.prompt_version("stage3_interpret") if interp_json.exists() else True
    if (_step(interp_md, force) or _step(interp_json, force) or executed_now or interp_stale
            or "interpret" in force_steps):
        prompt = mv.interpretation_prompt(
            specs_path.read_text(), fq.get("reported_value"), grid
        )
        r = llm.call("interpret", prompt, paper_id=paper_id, stage="3", tier="strong",
                     log_path=stage3 / "logs" / "interpret.log")
        if not r.ok:
            raise RuntimeError(f"stage 3 interpret failed: {r.error}")
        interp_md.write_text(r.text)
        parsed = mv.parse_interpretation(r.text)
        parsed["_ledger_id"] = r.ledger_id
        parsed["_prompt_versions"] = {"stage3_interpret": artifacts.prompt_version("stage3_interpret")}
        mv._write_json(interp_json, parsed)
    interpretation = mv._read_json(interp_json)
    calls.append(interpretation.get("_ledger_id", ""))

    # --- 7. assemble ------------------------------------------------------
    space = _assemble(paper_id, focal, grid, rows, ranking, execute,
                      interp_md.read_text(), interpretation, inputs, calls, paper)
    artifacts.save(space, space_path)
    paths.mark_done(stage3, inputs)
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
                              screen_verdict=lv.get("screen_verdict", "defensible"))
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
    reason = (
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
        abstain_reason=reason,
        confidence="high",
        open_ambiguities=(list(grid.get("notes", [])) + list(focal.get("notes", []))
                          + list(paper.get("notes", []))),
        claim_id=focal["focal_quantity"]["claim_id"],
        factors=_factors(grid),
        unimplementable=unimplementable,
        incompatibilities=[[i["a"], i["b"]] for i in grid.get("incompatible", [])],
        grid_size=grid.get("grid_size"),
        runs=[],
        reported_estimate=focal["focal_quantity"].get("reported_value"),
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
    runs = [SpecRun(spec={k: r.get(k, "") for k in names if k in r},
                    estimate=r["_estimate"], se=r["_se"], p=r["_p"],
                    converged=r["_converged"], n=r.get("_n"), error=r.get("error") or None)
            for r in rows]

    problems = list(execute.get("problems", []))
    ambiguities = (list(grid.get("notes", [])) + list(focal.get("notes", []))
                   + list(paper.get("notes", [])))
    shaky_binding = not binding_is_determinate(list(focal.get("notes", [])))
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
        confidence="high" if not (problems or shaky_binding) else "medium",
        open_ambiguities=ambiguities,
        claim_id=focal["focal_quantity"]["claim_id"],
        factors=factors,
        unimplementable=grid.get("unimplementable", []),
        incompatibilities=[[i["a"], i["b"]] for i in grid.get("incompatible", [])],
        grid_size=grid.get("grid_size"),
        runs=runs,
        reported_estimate=focal["focal_quantity"].get("reported_value"),
        rank=ranking.get("rank"),
        n_specs=grid.get("n_specs"),
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

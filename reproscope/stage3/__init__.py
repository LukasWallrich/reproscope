"""Stage 3 — robustness: the specification curve on the focal claim.

`run(paper_id, force=False)` walks the seven steps in multiverse.py. Every step reads
its own output file first and re-does the work only when that file is missing or `force`
is set, so an interrupted stage resumes at the step that failed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import artifacts, config, llm, paths
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
    """Hashes of everything Stage 3 reads, for the done.json check."""
    wanted = {
        "manifest": paths.corpus_dir(paper_id) / "manifest.json",
        "claims": paths.run_dir(paper_id, 0) / "claims.json",
        "contracts": paths.run_dir(paper_id, 0) / "contracts.json",
        "schema": paths.run_dir(paper_id, 0) / "schema.json",
        "readiness": paths.run_dir(paper_id, 0) / "readiness.json",
        "match": paths.run_dir(paper_id, 1) / "match.json",
    }
    out = {n: artifacts.sha256_file(p) for n, p in wanted.items() if p.exists()}
    traces = sorted((paths.run_dir(paper_id, 1) / "replicas").glob("*/trace.json"))
    for t in traces:
        out[f"trace:{t.parent.name}"] = artifacts.sha256_file(t)
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


def run(paper_id: str, force: bool = False) -> SpecificationSpace:
    stage3 = paths.run_dir(paper_id, 3)
    inputs = _stage_inputs(paper_id)
    space_path = stage3 / "space.json"
    if not force and paths.is_done(stage3, inputs) and space_path.exists():
        print(f"stage 3: up to date ({space_path})", flush=True)
        return artifacts.load(SpecificationSpace, space_path)  # type: ignore[return-value]

    calls: list[str] = []
    manifest = paths.manifest(paper_id)
    claims = _load_claims(paper_id)
    contracts = mv._load_contracts(paper_id)

    # --- 1. focal claim binding ------------------------------------------
    focal_path = stage3 / "focal.json"
    if _step(focal_path, force):
        focal = mv.bind_focal_claim(manifest, claims, contracts, paper_id=paper_id)
        mv._write_json(focal_path, focal)
    focal = mv._read_json(focal_path)
    fq = focal["focal_quantity"]
    print(f"stage 3: focal quantity {fq['kind']} = {fq['reported_value']} "
          f"(claim {fq['claim_id']}, analysis {focal['analysis_id']})", flush=True)

    focal_contract = next(
        (c for c in contracts if c.analysis_id == focal["analysis_id"]), contracts[0]
    )

    # --- 2. enumerate -----------------------------------------------------
    proposed_path = stage3 / "factors_proposed.json"
    if _step(proposed_path, force):
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
        mv._write_json(proposed_path, out)
    proposed = mv._read_json(proposed_path)
    calls.append(proposed.get("_ledger_id", ""))
    print(f"stage 3: {len(proposed.get('factors', []))} factors proposed", flush=True)

    # --- 2b. what the paper itself did -----------------------------------
    paper_path = stage3 / "paper_level.json"
    if _step(paper_path, force):
        mv._write_json(paper_path, mv.derive_paper_levels(paper_id, proposed, focal))
    paper = mv._read_json(paper_path)
    calls.append(paper.get("_ledger_id", ""))
    print(f"stage 3: paper levels from {paper['source']}", flush=True)
    for note in paper.get("notes", []):
        print(f"stage 3:   {note}", flush=True)

    # --- 3. screen + grid -------------------------------------------------
    screen_path = stage3 / "screen.json"
    if _step(screen_path, force):
        prompt = artifacts.load_prompt(
            "stage3_screen",
            contract=focal_contract.model_dump_json(indent=2),
            factors=json.dumps(proposed.get("factors", []), indent=2),
        )
        r = llm.call("screen", prompt, paper_id=paper_id, stage="3",
                     tier="strong_alt", schema=mv.ScreenOut,
                     log_path=stage3 / "logs" / "screen.log")
        if not r.ok or r.parsed is None:
            raise RuntimeError(f"stage 3 screen failed: {r.error}")
        out = r.parsed.model_dump()
        out["_ledger_id"] = r.ledger_id
        mv._write_json(screen_path, out)
    screen = mv._read_json(screen_path)
    calls.append(screen.get("_ledger_id", ""))

    grid_path = stage3 / "grid.json"
    if _step(grid_path, force):
        mv._write_json(grid_path, mv.build_grid(proposed, screen,
                                                paper_levels=paper.get("levels")))
    grid = mv._read_json(grid_path)
    n_rejected = len(grid.get("rejected_levels", []))
    n_flagged = len(grid.get("paper_level_flagged", []))
    print(f"stage 3: grid of {grid['grid_size']} specifications over "
          f"{len(grid['factors'])} factors ({n_rejected} levels rejected, "
          f"{n_flagged} paper levels kept over the screen)", flush=True)

    # --- 4. execute + verify ---------------------------------------------
    execute_path = stage3 / "execute.json"
    # A failed executor still writes its report, so resume on the artefact that matters:
    # without specs.csv there is nothing to rank, and step 4 runs again.
    # Rerun the executor when there is no report, no specs.csv to rank, or when the grid
    # has changed under a specs.csv produced from an older one.
    grid_sha = artifacts.sha256_file(grid_path)
    executed_now = executor_stale(stage3, grid_sha, force=force)
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
    rows = mv.read_specs(specs_path)

    # --- 5. rank ----------------------------------------------------------
    # A rerun of the executor makes any earlier ranking and reading of the curve stale.
    rank_path = stage3 / "rank.json"
    if _step(rank_path, force) or executed_now:
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
    if _step(interp_md, force) or _step(interp_json, force) or executed_now:
        prompt = artifacts.load_prompt(
            "stage3_interpret",
            specs=specs_path.read_text()[:60000],
            reported=fq.get("reported_value"),
            rank=ranking.get("rank"),
            n=ranking.get("n_converged"),
            share_below=ranking.get("share_below"),
            share_above=ranking.get("share_above"),
            share_tied=ranking.get("share_tied"),
            extremeness=ranking.get("extremeness"),
            factors=json.dumps(
                [{"name": f["name"], "levels": [lv["value"] for lv in f["levels"]]}
                 for f in grid["factors"]], indent=2),
        )
        r = llm.call("interpret", prompt, paper_id=paper_id, stage="3", tier="strong",
                     log_path=stage3 / "logs" / "interpret.log")
        if not r.ok:
            raise RuntimeError(f"stage 3 interpret failed: {r.error}")
        interp_md.write_text(r.text)
        parsed = mv.parse_interpretation(r.text)
        parsed["_ledger_id"] = r.ledger_id
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
    factors: list[SpecFactor] = []
    for f in grid["factors"]:
        # A level the paper itself used carries verdict "paper"; `screen_verdict` says
        # what the screen made of it, so a reader can see when the screen would have
        # thrown out the paper's own choice.
        levels = [FactorLevel(value=lv["value"], verdict=lv.get("verdict", "defensible"),
                              rationale=lv.get("rationale"), how=lv.get("how"),
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

    names = [f["name"] for f in grid["factors"]]
    runs = [SpecRun(spec={k: r.get(k, "") for k in names if k in r},
                    estimate=r["_estimate"], se=r["_se"], p=r["_p"],
                    converged=r["_converged"], n=r.get("_n"), error=r.get("error") or None)
            for r in rows]

    problems = list(execute.get("problems", []))
    ambiguities = (list(grid.get("notes", [])) + list(focal.get("notes", []))
                   + list(paper.get("notes", [])))

    return SpecificationSpace(
        meta=ArtifactMeta(
            artifact="SpecificationSpace", stage="3", inputs=inputs,
            prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
            model_calls=[c for c in calls if c],
        ),
        confidence="high" if not problems else "medium",
        open_ambiguities=ambiguities,
        claim_id=focal["focal_quantity"]["claim_id"],
        factors=factors,
        incompatibilities=[[i["a"], i["b"]] for i in grid.get("incompatible", [])],
        grid_size=grid.get("grid_size"),
        runs=runs,
        reported_estimate=focal["focal_quantity"].get("reported_value"),
        rank=ranking.get("rank"),
        n_specs=ranking.get("n_converged"),
        interpretation=interpretation_md,
        # extras (the artifact model allows them, and the report reads them)
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

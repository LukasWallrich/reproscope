"""Targeted reconstruction: an unblinded agent tries to reach the reported numbers.

This arm runs only when the blind replicas disagree with the paper or with each
other on a headline claim. It sees everything the replicas did not, so its result
says whether a defensible route to the reported values exists, not whether the
paper reproduces.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .. import artifacts, llm, paths
from . import audit, blind, match, replicas

TIMEOUT_S = 3600


def targeted_dir(paper_id: str) -> Path:
    return paths.run_dir(paper_id, 1) / "targeted"


def reported_payload(claims: list[artifacts.ClaimRecord]) -> dict:
    return {
        "claims": [
            {
                "claim_id": c.claim_id,
                "quantity_kind": c.quantity_kind,
                "importance": c.importance,
                "value": c.value,
                "precision": c.precision,
                "uncertainty": c.uncertainty,
                "description": c.description,
            }
            for c in claims
        ]
    }


def assemble(paper_id: str) -> Path:
    work = targeted_dir(paper_id) / "work"
    (work / "out").mkdir(parents=True, exist_ok=True)
    claims = blind.claims(paper_id)
    contracts = blind.contracts(paper_id)

    (work / "PAPER.md").write_text(blind.paper_text(paper_id))
    (work / "CONTRACT.json").write_text(
        json.dumps(
            {
                "contracts": [c.model_dump(exclude={"meta"}) for c in contracts],
                "claims": [c.model_dump(exclude={"meta"}) for c in claims],
            },
            indent=2,
            default=str,
        )
    )
    (work / "REPORTED.json").write_text(json.dumps(reported_payload(claims), indent=2, default=str))
    blind.copy_data(paper_id, work / "data")

    dest_root = work / "replicas"
    if dest_root.exists():
        shutil.rmtree(dest_root)
    for trace in replicas.load_traces(paper_id):
        src = blind.replica_dir(paper_id, trace.replica_id) / "work" / "out"
        if src.exists():
            shutil.copytree(src, dest_root / trace.replica_id / "out")
        artifacts.save(trace, dest_root / trace.replica_id / "trace.json")
    (work / "TASK.md").write_text(artifacts.load_prompt("stage1_targeted"))
    return work


def run(
    paper_id: str, result: artifacts.ComparableResult, force: bool = False
) -> artifacts.TargetedReconstruction:
    out_path = paths.run_dir(paper_id, 1) / "targeted.json"
    key = {"match.json": artifacts.sha256_file(paths.run_dir(paper_id, 1) / "match.json")}
    if out_path.exists() and not force:
        loaded = artifacts.load(artifacts.TargetedReconstruction, out_path)
        cached = loaded if isinstance(loaded, artifacts.TargetedReconstruction) else loaded[0]
        if cached.meta and cached.meta.inputs == key:
            return cached

    triggered, reasons = match.targeted_trigger(result)
    if not triggered and not any(s.n_ran for s in result.summaries):
        rec = artifacts.TargetedReconstruction(
            triggered=False,
            outcome="not_triggered",
            notes="No replica produced runnable results, so there is nothing to reconstruct "
            "towards and no miss to explain.",
            state="abstained",
            abstain_reason="no replica ran",
            meta=artifacts.ArtifactMeta(artifact="TargetedReconstruction", stage="1", inputs=key),
        )
        artifacts.save(rec, out_path)
        return rec
    if not triggered:
        rec = artifacts.TargetedReconstruction(
            triggered=False,
            outcome="not_triggered",
            notes="Every headline claim had at least half the replicas in band A or B "
            "and a numeric CV of 0.2 or less.",
            meta=artifacts.ArtifactMeta(artifact="TargetedReconstruction", stage="1", inputs=key),
        )
        artifacts.save(rec, out_path)
        return rec

    work = assemble(paper_id)
    r = llm.call(
        "targeted",
        (work / "TASK.md").read_text(),
        paper_id=paper_id,
        stage="1",
        tier="strong",
        cwd=work,
        agentic=True,
        timeout_s=TIMEOUT_S,
        log_path=targeted_dir(paper_id) / "agent.log",
    )
    call_ids = [r.ledger_id] if r.ledger_id else []

    outcome_path = work / "out" / "outcome.json"
    payload = json.loads(outcome_path.read_text()) if outcome_path.exists() else {}
    script = replicas.find_script(work / "out")
    results_path = work / "out" / "results.json"
    hard, hard_call = audit.hardcoding_audit(
        paper_id,
        script.read_text() if script else "",
        results_path.read_text() if results_path.exists() else "",
        step="targeted_hardcoding_audit",
    )
    if hard_call:
        call_ids.append(hard_call)

    valid = {"reachable", "reachable_indefensibly", "not_reachable"}
    outcome = payload.get("outcome") if payload.get("outcome") in valid else "not_reachable"
    rec = artifacts.TargetedReconstruction(
        triggered=True,
        outcome=outcome,
        added_choices=[str(x) for x in payload.get("added_choices", [])],
        attempts=int(payload.get("attempts") or 0),
        notes=payload.get("notes"),
        trigger_reasons=reasons,
        closest_distance=payload.get("closest_distance"),
        hardcoding_audit=hard,
        agent_ok=r.ok,
        agent_error=r.error,
        state="complete" if outcome_path.exists() else "abstained",
        abstain_reason=None if outcome_path.exists() else "the agent wrote no out/outcome.json",
        meta=artifacts.ArtifactMeta(
            artifact="TargetedReconstruction", stage="1", model_calls=call_ids, inputs=key,
            prompt_versions={"targeted": artifacts.prompt_version("stage1_targeted")},
        ),
    )
    artifacts.save(rec, out_path)
    return rec

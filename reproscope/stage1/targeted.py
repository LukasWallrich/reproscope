"""Targeted reconstruction: an unblinded agent tries to reach the reported numbers.

The arm runs only when the blind replicas miss the paper's focal claim. It sees what
the replicas did not — the reported values, the methods section and the closest
replica's script — so its result says whether a defensible route to the reported
values exists, not whether the paper reproduces.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .. import artifacts, focal, llm, paths
from . import audit, blind, match, replicas

TIMEOUT_S = 3600
MAX_TURNS = 40
PROMPTS = ("stage1_targeted",)

# A heading line: optionally numbered, short, and naming a methods or a closing section.
_METHODS_HEAD = re.compile(r"^(\d+\.?\s*)?(methods?|materials and methods|participants)\b", re.I)
_END_HEAD = re.compile(r"^(\d+\.?\s*)?(general\s+)?(results?|discussion)\b", re.I)
_MAX_HEADING_CHARS = 60


def targeted_dir(paper_id: str) -> Path:
    return paths.run_dir(paper_id, 1) / "targeted"


def methods_section(text: str) -> str:
    """Every Method-to-Results span of a paper, headings kept, in document order.

    Multi-study papers repeat the pair, so all spans are collected rather than the
    first; a "Participants" subheading inside an open span does not start another.
    Returns "" when no heading matches.
    """
    spans: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        heading = 0 < len(stripped) <= _MAX_HEADING_CHARS
        if heading and current is None and _METHODS_HEAD.match(stripped):
            current = [stripped]
            spans.append(current)
            continue
        if current is None:
            continue
        if heading and _END_HEAD.match(stripped):
            current = None
            continue
        current.append(line)
    return "\n".join("\n".join(s).strip() for s in spans if len(s) > 1).strip()


def methods_text(paper_id: str) -> str:
    """The paper's methods section; the redacted methods when no heading is found."""
    section = methods_section(blind.paper_text(paper_id))
    if section:
        return section
    fallback = blind.stage0_dir(paper_id) / "redacted_methods.md"
    return fallback.read_text() if fallback.exists() else ""


def reported_payload(claims: list[artifacts.ClaimRecord]) -> dict:
    """Reported values of the focal analysis's claims. The description identifies which
    quantity of the fit each claim is; kind alone does not when a model has many."""
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


def assemble(
    paper_id: str,
    result: artifacts.ComparableResult,
    binding: dict,
) -> tuple[Path, str | None]:
    """Build the work directory and return it with the id of the replica it started from."""
    work = targeted_dir(paper_id) / "work"
    if work.exists():
        shutil.rmtree(work)
    (work / "out").mkdir(parents=True, exist_ok=True)

    all_claims = blind.claims(paper_id)
    contract = next(
        c for c in blind.contracts(paper_id) if c.analysis_id == binding["analysis_id"]
    )
    analysis_claims = [c for c in all_claims if c.claim_id in set(contract.claim_ids or [])]

    (work / "METHODS.md").write_text(methods_text(paper_id))
    (work / "CONTRACT.json").write_text(
        json.dumps(contract.model_dump(exclude={"meta"}), indent=2, default=str)
    )
    (work / "REPORTED.json").write_text(
        json.dumps(reported_payload(analysis_claims), indent=2, default=str)
    )
    (work / "FOCAL.json").write_text(json.dumps(binding, indent=2, default=str))
    blind.copy_data(paper_id, work / "data")

    closest = match.closest_replicas(result, binding["focal_quantity"]["claim_id"], n=1)
    started_from = closest[0] if closest else None
    if started_from:
        src = replicas.find_script(blind.replica_dir(paper_id, started_from) / "work" / "out")
        if src:
            shutil.copy2(src, work / f"closest_replica{src.suffix}")

    (work / "TASK.md").write_text(
        artifacts.load_prompt(
            "stage1_targeted",
            focal_claim_id=binding["focal_quantity"]["claim_id"],
            closest_replica=started_from or "none (no replica produced a comparable value)",
        )
    )
    return work, started_from


def _record(out_path: Path, key: dict[str, str], **fields) -> artifacts.TargetedReconstruction:
    rec = artifacts.TargetedReconstruction(
        meta=artifacts.ArtifactMeta(
            artifact="TargetedReconstruction",
            stage="1",
            inputs=key,
            prompt_versions={name: artifacts.prompt_version(name) for name in PROMPTS},
            model_calls=fields.pop("model_calls", []),
        ),
        **fields,
    )
    artifacts.save(rec, out_path)
    return rec


def _split_diagnosis(text: str) -> str | None:
    """The agent's `## Diagnosis` section, when it wrote one."""
    m = re.search(r"^#{1,4}\s*Diagnosis\b[^\n]*\n(.*)", text or "", re.M | re.S)
    body = m.group(1).strip() if m else ""
    return body or None


def run(
    paper_id: str, result: artifacts.ComparableResult, force: bool = False
) -> artifacts.TargetedReconstruction:
    out_path = paths.run_dir(paper_id, 1) / "targeted.json"
    key = {"match": artifacts.content_hash(result)}
    if out_path.exists() and not force:
        loaded = artifacts.load(artifacts.TargetedReconstruction, out_path)
        cached = loaded if isinstance(loaded, artifacts.TargetedReconstruction) else loaded[0]
        if cached.meta and cached.meta.inputs == key and not artifacts.prompt_stale(cached, PROMPTS):
            return cached

    try:
        binding = focal.bind_focal_claim(
            paths.manifest(paper_id),
            blind.claims(paper_id),
            blind.contracts(paper_id),
            paper_id=paper_id,
            allow_llm=False,
        )
    except (ValueError, FileNotFoundError) as exc:
        return _record(
            out_path, key,
            triggered=False, outcome="not_triggered",
            notes=f"the focal claim could not be bound, so no miss can be defined: {exc}",
            state="abstained", abstain_reason=f"focal binding failed: {exc}",
        )

    # Only the focal quantity itself can trigger the arm. `binding["claim_ids"]` also
    # holds every claim that shares a number with the focal sentence (sample sizes,
    # p-values, neighbouring cells), and a miss on one of those is not a focal miss.
    focal_ids = {binding["focal_quantity"]["claim_id"]}
    comparable = any(s.n_ran for s in result.summaries if s.claim_id in focal_ids)
    triggered, reasons = match.targeted_trigger(result, sorted(focal_ids))
    if not triggered and not comparable:
        return _record(
            out_path, key,
            triggered=False, outcome="not_triggered",
            notes="No replica produced a usable value for the focal claim, so there is "
            "nothing to reconstruct towards and no miss to explain.",
            state="abstained", abstain_reason="no usable replica row for the focal claim",
        )
    if not triggered:
        return _record(
            out_path, key,
            triggered=False, outcome="not_triggered",
            notes="The focal claim had at least half the usable replica rows in band A or B, "
            "at least one in band A, and a numeric CV of 0.2 or less.",
        )

    work, started_from = assemble(paper_id, result, binding)
    r = llm.call(
        "targeted",
        (work / "TASK.md").read_text(),
        paper_id=paper_id,
        stage="1",
        tier="strong",
        cwd=work,
        agentic=True,
        timeout_s=TIMEOUT_S,
        max_turns=MAX_TURNS,
        log_path=targeted_dir(paper_id) / "agent.log",
    )
    call_ids = [r.ledger_id] if r.ledger_id else []

    outcome_path = work / "out" / "outcome.json"
    try:
        payload = json.loads(outcome_path.read_text()) if outcome_path.exists() else {}
    except json.JSONDecodeError:
        payload = {}
    valid = {"reachable", "reachable_indefensibly", "not_reachable"}
    reported_outcome = payload.get("outcome")

    if not r.ok or reported_outcome not in valid:
        reason = (
            f"the agent did not finish: {r.error}" if not r.ok
            else "the agent wrote no usable out/outcome.json"
        )
        return _record(
            out_path, key,
            triggered=True, outcome="abstained",
            trigger_reasons=reasons, started_from=started_from,
            attempts=int(payload.get("attempts") or 0),
            notes=payload.get("notes"),
            agent_ok=r.ok, agent_error=r.error,
            state="abstained", abstain_reason=reason,
            model_calls=call_ids,
        )

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

    return _record(
        out_path, key,
        triggered=True,
        outcome=reported_outcome,
        added_choices=[str(x) for x in payload.get("added_choices", [])],
        attempts=int(payload.get("attempts") or 0),
        notes=payload.get("notes"),
        diagnosis=_split_diagnosis(r.text),
        trigger_reasons=reasons,
        started_from=started_from,
        closest_distance=payload.get("closest_distance"),
        hardcoding_audit=hard,
        agent_ok=r.ok,
        agent_error=r.error,
        model_calls=call_ids,
    )

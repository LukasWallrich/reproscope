"""Post-hoc checks on a replica's own work: hard-coded results, and fix severity.

Both are cheap-tier calls over material the replica wrote. They never see the
paper's reported values.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from ._prompt import fill

MAX_RESULTS_CHARS = 20_000


def acceptance(audit: dict) -> str:
    """Execution success and analytical acceptance are separate states.

    Suspicious hits need an explicit adjudication with a reason; a numerical
    coincidence between a literal and an outcome is not proof of hardcoding.
    """
    adjudication = audit.get("adjudication") or {}
    if adjudication.get("reason") and adjudication.get("decision") in {"accepted", "rejected"}:
        return adjudication["decision"]
    if audit.get("verdict") == "clean":
        return "accepted"
    return "unresolved"


class HardcodingHit(BaseModel):
    model_config = ConfigDict(extra="allow")

    line: int | None = None
    literal: str | None = None
    used_as: str | None = None
    severity: Literal["suspicious", "confirmed"] | None = None
    affected_claim_ids: list[str] = []
    dependency_scope: Literal["isolated", "shared_computation", "unknown"] = "unknown"


class HardcodingAudit(BaseModel):
    model_config = ConfigDict(extra="allow")

    hits: list[HardcodingHit] = []
    verdict: Literal["clean", "suspicious", "hardcoded"] = "clean"


class FixRating(BaseModel):
    model_config = ConfigDict(extra="allow")

    index: int
    severity: artifacts.Severity
    reason: str | None = None


class FixRatings(BaseModel):
    model_config = ConfigDict(extra="allow")

    ratings: list[FixRating] = []


def hardcoding_audit(
    paper_id: str, script: str, results: str, *, step: str = "hardcoding_audit", stage: str = "1"
) -> tuple[dict[str, Any], str | None]:
    """Return (audit dict for the trace, ledger id)."""
    if not script.strip():
        return {"verdict": "not_run", "hits": [], "note": "no analysis script found"}, None
    import json
    source_roles = {}
    claim_path = paths.run_dir(paper_id, 0) / "claims.json"
    if claim_path.exists():
        source_roles = {c["claim_id"]: c.get("quantity_role", "unknown") for c in json.loads(claim_path.read_text())}
    prompt = fill(
        "stage1_hardcoding_audit",
        script=script,
        results=results or "(no results file)",
    )
    prompt += "\nCanonical quantity provenance roles (independent of replica identity):\n" + json.dumps(source_roles, sort_keys=True)
    from .. import review_backend
    review_call = review_backend.call
    r = review_call(
        step, prompt, paper_id=paper_id, stage=stage, tier="cheap", schema=HardcodingAudit
    )
    if r.parsed is None:
        return {"verdict": "not_run", "hits": [], "note": f"audit call failed: {r.error}"}, r.ledger_id
    out = r.parsed.model_dump()
    out["policy_version"] = "quantity-provenance-1"
    out["source_roles"] = source_roles
    out["prompt_version"] = artifacts.prompt_version("stage1_hardcoding_audit")
    out["coverage"] = {"full_script": True, "script_chars": len(script),
                       "results_chars_seen": len(results),
                       "results_chars_total": len(results)}
    return out, r.ledger_id


def fix_severity(
    paper_id: str, fixes: list[artifacts.ReplicaFix], contracts_text: str
) -> tuple[list[artifacts.ReplicaFix], str | None]:
    """Rate each fix minor/major/critical. Fixes without a rating keep severity None."""
    if not fixes:
        return fixes, None
    listing = "\n".join(f"{i}. {f.description}" for i, f in enumerate(fixes))
    prompt = fill("stage1_fix_severity", fixes=listing, contracts=contracts_text[:20_000])
    from .. import review_backend
    r = review_backend.call(
        "fix_severity", prompt, paper_id=paper_id, stage="1", tier="cheap", schema=FixRatings
    )
    if r.parsed is None:
        return fixes, r.ledger_id
    by_index = {rt.index: rt for rt in r.parsed.ratings}  # type: ignore[attr-defined]
    for i, f in enumerate(fixes):
        rating = by_index.get(i)
        if rating is not None:
            f.severity = rating.severity
            f.reason = rating.reason
    return fixes, r.ledger_id

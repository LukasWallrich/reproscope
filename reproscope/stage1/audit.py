"""Post-hoc checks on a replica's own work: hard-coded results, and fix severity.

Both are cheap-tier calls over material the replica wrote. They never see the
paper's reported values.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm
from ._prompt import fill

MAX_SCRIPT_CHARS = 40_000
MAX_RESULTS_CHARS = 20_000


class HardcodingHit(BaseModel):
    model_config = ConfigDict(extra="allow")

    line: int | None = None
    literal: str | None = None
    used_as: str | None = None
    severity: Literal["suspicious", "confirmed"] | None = None


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
    prompt = fill(
        "stage1_hardcoding_audit",
        script=script[:MAX_SCRIPT_CHARS],
        results=results[:MAX_RESULTS_CHARS] or "(no results file)",
    )
    r = llm.call(
        step, prompt, paper_id=paper_id, stage=stage, tier="cheap", schema=HardcodingAudit
    )
    if r.parsed is None:
        return {"verdict": "not_run", "hits": [], "note": f"audit call failed: {r.error}"}, r.ledger_id
    out = r.parsed.model_dump()
    out["prompt_version"] = artifacts.prompt_version("stage1_hardcoding_audit")
    return out, r.ledger_id


def fix_severity(
    paper_id: str, fixes: list[artifacts.ReplicaFix], contracts_text: str
) -> tuple[list[artifacts.ReplicaFix], str | None]:
    """Rate each fix minor/major/critical. Fixes without a rating keep severity None."""
    if not fixes:
        return fixes, None
    listing = "\n".join(f"{i}. {f.description}" for i, f in enumerate(fixes))
    prompt = fill("stage1_fix_severity", fixes=listing, contracts=contracts_text[:20_000])
    r = llm.call(
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

"""Step 3: a strong model reconciles the two extractions into stage0/claims.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from .extract import ClaimList, SlimLocation

ALLOWED_KINDS = set(get_args(artifacts.QuantityKind))
# The extraction prompt offers finer kinds than the artifact enum carries; the
# original wording is kept in `quantity_kind_raw`.
KIND_MAP = {
    "ci_lower": "ci_bound",
    "ci_upper": "ci_bound",
    "se": "other",
    "z": "other",
    "eta2": "other",
    "percent": "other",
    "beta": "coefficient",
    "b": "coefficient",
    "M": "mean",
    "SD": "sd",
}
ALLOWED_TYPES = {"scalar", "range", "table_cell", "qualitative", "figure"}


class ArbitratedClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    study_id: str | None = None
    claim_type: str | None = None
    importance: str | None = None
    quantity_kind: str | None = None
    value: float | None = None
    comparator: str | None = None
    precision: int | None = None
    uncertainty: str | None = None
    location: SlimLocation | None = None
    description: str | None = None
    analysis_label: str | None = None
    agreed: bool | None = None
    arbiter_note: str | None = None
    confidence: str | None = None


class Dropped(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    description: str | None = None
    reason: str | None = None


class ArbitrationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[ArbitratedClaim] = []
    dropped: list[Dropped] = []
    notes: str | None = None


def to_records(
    out: ArbitrationOut, tier_a: str, tier_b: str, meta: artifacts.ArtifactMeta
) -> list[artifacts.ClaimRecord]:
    records: list[artifacts.ClaimRecord] = []
    for c in out.claims:
        raw_kind = (c.quantity_kind or "other").strip()
        kind = raw_kind if raw_kind in ALLOWED_KINDS else KIND_MAP.get(raw_kind, "other")
        claim_type = c.claim_type if c.claim_type in ALLOWED_TYPES else None
        payload: dict[str, Any] = {
            "meta": meta.model_dump(),
            "claim_id": c.claim_id,
            "study_id": c.study_id,
            "claim_type": claim_type,
            "importance": c.importance if c.importance in {"headline", "supporting"} else "supporting",
            "quantity_kind": kind,
            "quantity_kind_raw": raw_kind,
            "value": c.value,
            "comparator": c.comparator,
            "precision": c.precision,
            "uncertainty": {"reported": c.uncertainty} if c.uncertainty else None,
            "location": c.location.model_dump() if c.location else None,
            "description": c.description,
            "analysis_label": c.analysis_label,
            "confidence": c.confidence if c.confidence in {"high", "medium", "low"} else None,
            "extraction": {
                "model_a": tier_a,
                "model_b": tier_b,
                "agreed": c.agreed,
                "arbiter_note": c.arbiter_note,
            },
        }
        records.append(artifacts.ClaimRecord.model_validate(payload))
    return records


def run(
    manifest,
    list_a: ClaimList,
    list_b: ClaimList,
    pages: list[Path],
    inputs: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[list[artifacts.ClaimRecord], list[str]]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "claims.json"
    if out_path.exists() and not force:
        return artifacts.load(artifacts.ClaimRecord, out_path), []  # type: ignore[return-value]

    prompt = artifacts.load_prompt(
        "stage0_arbitrate",
        list_a=json.dumps([c.model_dump() for c in list_a.claims], indent=1),
        list_b=json.dumps([c.model_dump() for c in list_b.claims], indent=1),
    )
    r = llm.call(
        "arbitrate",
        prompt,
        paper_id=manifest.paper_id,
        stage="0",
        tier="strong",
        schema=ArbitrationOut,
        images=pages,
        cwd=paths.ROOT,
        timeout_s=3600,
        log_path=stage_dir / "logs" / "arbitrate.log",
    )
    if r.parsed is None:
        raise llm.LLMError(f"arbitration failed: {r.error}")
    out: ArbitrationOut = r.parsed  # type: ignore[assignment]

    meta = artifacts.ArtifactMeta(
        artifact="ClaimRecord",
        stage="0",
        inputs=inputs or {},
        prompt_versions={
            "stage0_extract": artifacts.prompt_version("stage0_extract"),
            "stage0_arbitrate": artifacts.prompt_version("stage0_arbitrate"),
        },
        model_calls=[r.ledger_id or ""],
    )
    records = to_records(out, "vision_a", "vision_b", meta)
    artifacts.save(records, out_path)
    (stage_dir / "arbitration.json").write_text(
        json.dumps(
            {
                "dropped": [d.model_dump() for d in out.dropped],
                "notes": out.notes,
                "n_a": len(list_a.claims),
                "n_b": len(list_b.claims),
                "n_arbitrated": len(records),
            },
            indent=2,
        )
        + "\n"
    )
    return records, [r.ledger_id or ""]

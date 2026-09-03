"""Step 4: the estimand contracts and the redacted methods, from one reading of the paper.

This is the only step that sees the paper text, and it sees it once. A leak found
afterwards is repaired sentence by sentence (`redact.repair`), never by re-sending
the paper.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from . import leakcheck, redact

# Fields a contract must never see, so the writer cannot copy a result across.
BLIND_DROP = ("value", "precision", "uncertainty", "comparator")

# Only the prompt that writes the artifacts decides whether they are stale. The
# repair prompt's version is recorded on the redaction report, which owns the scan.
PROMPTS = ("stage0_contracts",)


class SlimAmbiguity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    options: list[str] = []
    note: str | None = None


class SlimContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    analysis_label: str | None = None
    claim_ids: list[str] = []
    study_id: str | None = None
    sample_rule: str | None = None
    outcome: str | None = None
    predictors: list[str] = []
    covariates: list[str] = []
    model_type: str | None = None
    estimator: str | None = None
    se_type: str | None = None
    transformations: list[str] = []
    weights: str | None = None
    missingness: str | None = None
    software_named: list[str] = []
    versions_named: list[str] = []
    ambiguities: list[SlimAmbiguity] = []


class ContractsAndMethods(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contracts: list[SlimContract] = []
    redacted_methods: str = ""


def claims_without_values(claims: list[artifacts.ClaimRecord]) -> list[dict[str, Any]]:
    out = []
    for c in claims:
        d = c.model_dump(exclude_none=True)
        for f in BLIND_DROP:
            d.pop(f, None)
        d.pop("meta", None)
        d.pop("extraction", None)
        out.append(d)
    return out


def to_records(
    contracts: list[SlimContract], meta: artifacts.ArtifactMeta
) -> list[artifacts.EstimandContract]:
    records = []
    for c in contracts:
        payload = c.model_dump()
        payload["versions_named"] = {
            v.split()[0]: " ".join(v.split()[1:]) or "stated" for v in c.versions_named if v.strip()
        }
        payload["meta"] = meta.model_dump()
        records.append(artifacts.EstimandContract.model_validate(payload))
    return records


def run(
    manifest,
    claims: list[artifacts.ClaimRecord],
    paper_text: str,
    inputs: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[list[artifacts.EstimandContract], list[str]]:
    """Write contracts.json and redacted_methods.md, then repair any leak locally."""
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "contracts.json"
    methods_path = stage_dir / "redacted_methods.md"

    if out_path.exists() and methods_path.exists() and not force:
        existing = artifacts.load(artifacts.EstimandContract, out_path)
        records = existing if isinstance(existing, list) else [existing]
        first = records[0] if records else None
        if (
            first
            and not artifacts.prompt_stale(first, PROMPTS)
            and first.meta is not None
            and first.meta.inputs == (inputs or {})
        ):
            return records, []

    r = llm.call(
        "contracts",
        artifacts.load_prompt(
            "stage0_contracts",
            paper_text=paper_text,
            claims_no_values=json.dumps(claims_without_values(claims), indent=1),
        ),
        paper_id=manifest.paper_id,
        stage="0",
        tier="strong",
        schema=ContractsAndMethods,
        large_context=True,
        cwd=manifest.dir,
        timeout_s=3600,
        log_path=stage_dir / "logs" / "contracts.log",
    )
    if r.parsed is None:
        raise llm.LLMError(f"contracts failed: {r.error}")
    out: ContractsAndMethods = r.parsed  # type: ignore[assignment]
    if not out.redacted_methods.strip():
        raise llm.LLMError("contracts call returned no redacted methods document")
    calls = [r.ledger_id or ""]

    meta = artifacts.ArtifactMeta(
        artifact="EstimandContract",
        stage="0",
        inputs=inputs or {},
        prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
        model_calls=calls,
    )
    records = to_records(out.contracts, meta)
    artifacts.save(records, out_path)
    methods_path.write_text(out.redacted_methods.strip() + "\n")

    design = leakcheck.design_numbers_from_manifest(manifest)
    hits, repair_calls = redact.repair(manifest, [out_path, methods_path], claims, design)
    if repair_calls:
        calls += repair_calls
        meta.model_calls = calls
        records = artifacts.load(artifacts.EstimandContract, out_path)  # type: ignore[assignment]
        records = records if isinstance(records, list) else [records]
        for rec in records:
            rec.meta = meta
        artifacts.save(records, out_path)
    if hits:
        print(f"contracts: {len(hits)} leak(s) survive repair; stage 1 will refuse", flush=True)
    return records, calls

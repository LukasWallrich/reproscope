"""Step 4: estimand contracts from the paper text and the value-free claim list."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from . import leakcheck

# Fields a contract must never see, so the writer cannot copy a result across.
BLIND_DROP = ("value", "precision", "uncertainty", "comparator")


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


class ContractList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contracts: list[SlimContract] = []


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


def to_records(out: ContractList, meta: artifacts.ArtifactMeta) -> list[artifacts.EstimandContract]:
    records = []
    for c in out.contracts:
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
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "contracts.json"
    if out_path.exists() and not force:
        return artifacts.load(artifacts.EstimandContract, out_path), []  # type: ignore[return-value]

    prompt = artifacts.load_prompt(
        "stage0_contracts",
        paper_text=paper_text,
        claims_no_values=json.dumps(claims_without_values(claims), indent=1),
    )
    calls: list[str] = []
    attempt_prompt = prompt
    records: list[artifacts.EstimandContract] = []
    hits: list[dict[str, Any]] = []
    design = leakcheck.design_numbers_from_manifest(manifest)

    for attempt in (1, 2):
        r = llm.call(
            "contracts" if attempt == 1 else "contracts:retry",
            attempt_prompt,
            paper_id=manifest.paper_id,
            stage="0",
            tier="strong",
            schema=ContractList,
            cwd=manifest.dir,
            timeout_s=3600,
            log_path=stage_dir / "logs" / f"contracts{attempt}.log",
        )
        calls.append(r.ledger_id or "")
        if r.parsed is None:
            raise llm.LLMError(f"contracts failed: {r.error}")
        meta = artifacts.ArtifactMeta(
            artifact="EstimandContract",
            stage="0",
            inputs=inputs or {},
            prompt_versions={"stage0_contracts": artifacts.prompt_version("stage0_contracts")},
            model_calls=list(calls),
        )
        records = to_records(r.parsed, meta)  # type: ignore[arg-type]
        artifacts.save(records, out_path)
        hits = leakcheck.scan([out_path], claims, design)
        if not hits:
            return records, calls
        attempt_prompt = prompt + (
            "\n\nYour previous contracts contained reported result values, which is "
            "forbidden. Rewrite them without these numbers (describe the quantity "
            "instead):\n" + json.dumps(hits, indent=1)[:4000]
        )

    out_path.unlink(missing_ok=True)  # never leave a leaking artifact behind
    raise RuntimeError(f"contracts leak reported values after a retry: {hits}")

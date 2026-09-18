"""Step 4: the estimand contracts and the redacted methods, from one reading of the paper.

This is the only step that sees the paper text, and it sees it once. A leak found
afterwards is repaired sentence by sentence (`redact.repair`), never by re-sending
the paper.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths, config, response_cache
from ..source_mapping import TermMapping, UnassignedClaim, mapped, mapping_errors, unassigned_errors, missing_term
from . import leakcheck, redact

# Fields a contract must never see, so the writer cannot copy a result across.
BLIND_DROP = ("value", "precision", "uncertainty", "comparator")

# Only the prompt that writes the artifacts decides whether they are stale. The
# repair prompt's version is recorded on the redaction report, which owns the scan.
PROMPTS = ("stage0_contracts", "stage0_assign_claims", "stage0_contract_body", "stage0_shared_methods")


class AnalysisIdentity(BaseModel):
    """Canonical method identifiers; labels and reported numbers are not keys."""
    model_config = ConfigDict(extra="forbid")

    study: str
    outcome: str
    contrast: str
    model: str
    sample: str


class SlimAmbiguity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    kind: Literal["method", "source_identity"] | None = None
    options: list[str] = []
    note: str | None = None


class SlimContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis_id: str
    identity: AnalysisIdentity | None = None
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
    design: artifacts.AnalysisDesign | None = None


class ContractsAndMethods(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contracts: list[SlimContract] = []
    term_map: list[TermMapping] = []
    unassigned: list[UnassignedClaim] = []
    redacted_methods: str = ""


def validate_assignments(contracts, claims, term_map=None, unassigned=None, paper_text=None) -> list[str]:
    """Reject overlapping identities and unmapped/ multiply mapped test results.

    Duplicate source records may share a contract. Equal numeric values never
    establish identity; descriptive quantities may support several analyses.
    """
    import re
    term_map = [m if isinstance(m, TermMapping) else TermMapping.model_validate(m) for m in (term_map or [])]
    unassigned = [u if isinstance(u, UnassignedClaim) else UnassignedClaim.model_validate(u) for u in (unassigned or [])]
    errors = mapping_errors(term_map, claims, paper_text)
    errors += unassigned_errors(unassigned, claims, {cid for ct in contracts for cid in ct.claim_ids}, paper_text)
    unassigned_ids = {u.claim_id for u in unassigned}
    seen_ids, seen_keys = set(), set()
    by_id = {c.claim_id: c for c in claims}
    owners = {cid: [] for cid in by_id}
    inferential = {"t", "F", "chi2", "p_value", "coefficient", "d", "r", "OR", "HR"}
    for ct in contracts:
        if ct.analysis_id in seen_ids:
            errors.append(f"duplicate analysis_id {ct.analysis_id}")
        seen_ids.add(ct.analysis_id)
        identity = getattr(ct, "identity", None)
        if isinstance(identity, BaseModel):
            identity = identity.model_dump()
        fields = ("study", "outcome", "contrast", "model", "sample")
        if not isinstance(identity, dict) or any(not str(identity.get(k, "")).strip() for k in fields):
            errors.append(f"{ct.analysis_id}: missing atomic analysis identity")
        else:
            key = tuple(re.sub(r"[^a-z0-9]", "", str(identity[k]).lower()) for k in fields)
            if key in seen_keys:
                errors.append(f"{ct.analysis_id}: duplicate atomic analysis identity")
            seen_keys.add(key)
        for cid in set(ct.claim_ids):
            if cid not in by_id:
                errors.append(f"{ct.analysis_id}: unknown claim {cid}")
                continue
            owners[cid].append(ct.analysis_id)
            c = by_id[cid]
            if isinstance(identity, dict):
                design=ct.design.model_dump() if isinstance(ct.design,BaseModel) else ct.design or {}
                symmetric=(design.get('family')=='correlation' and
                    mapped(c,'outcome',identity['contrast'],term_map) and mapped(c,'contrast',identity['outcome'],term_map))
                for target, field in (("target_outcome", "outcome"), ("target_contrast", "contrast"), ("target_model", "model")):
                    value = getattr(c, target, None)
                    if value and not mapped(c, field, identity[field], term_map) and not (symmetric and field in {'outcome','contrast'}):
                        errors.append(f"{cid}: source {target} conflicts with {ct.analysis_id}")
            if c.study_id and ct.study_id and c.study_id != ct.study_id:
                errors.append(f"{cid}: study differs from {ct.analysis_id}")
    for m in term_map:
        used = False
        for ct in contracts:
            identity = getattr(ct, "identity", None)
            identity = identity.model_dump() if isinstance(identity, BaseModel) else identity
            design=ct.design.model_dump() if isinstance(ct.design,BaseModel) else ct.design or {}
            destinations=[identity.get(m.field)] if isinstance(identity,dict) else []
            if design.get('family')=='correlation' and m.field in {'outcome','contrast'} and isinstance(identity,dict):destinations.append(identity.get('contrast' if m.field=='outcome' else 'outcome'))
            if m.canonical in destinations:
                used |= any(cid in by_id and (not m.claim_ids or cid in m.claim_ids) and (by_id[cid].study_id or "") == m.study_id and getattr(by_id[cid], "target_" + m.field, None) == m.source_text for cid in ct.claim_ids)
        if not used:
            errors.append(f"source mapping not used by an assigned contract: {m.field}/{m.study_id}/{m.source_text}")
    for cid, c in by_id.items():
        if c.state == "complete" and c.quantity_kind in inferential and cid not in unassigned_ids and len(owners[cid]) != 1:
            errors.append(f"{cid}: inferential claim must belong to exactly one contract (got {owners[cid]})")
    return errors


CONTRACT_CLAIM_FIELDS = (
    "claim_id", "study_id", "claim_type", "quantity_kind", "quantity_role", "aggregation",
    "location", "description", "source_quote", "target_outcome", "target_contrast", "target_model",
)


def claims_without_values(claims: list[artifacts.ClaimRecord]) -> list[dict[str, Any]]:
    """Only eligible source targets enter executable-contract construction.

    Source exclusions remain in claims.json and the assignment audit denominator.
    Keep source context for semantic assignment; drop duplicate anchoring and display
    metadata, and do not give already-invalid targets an executable contract.
    """
    return [{k: getattr(c, k).model_dump() if isinstance(getattr(c, k), BaseModel) else getattr(c, k)
             for k in CONTRACT_CLAIM_FIELDS if getattr(c, k) is not None}
            for c in claims if c.state == "complete"]


def project_eligible(candidate: ContractsAndMethods, claims):
    """Remove ineligible source references, preserving unknown IDs for rejection."""
    by_id = {c.claim_id: c for c in claims}
    allowed = lambda cid: cid not in by_id or by_id[cid].state == "complete"
    term_map = []
    for mapping in candidate.term_map:
        if missing_term(mapping.source_text):
            continue
        if mapping.claim_ids:
            retained=[cid for cid in mapping.claim_ids if allowed(cid)]
            if not retained:continue
            mapping=mapping.model_copy(update={'claim_ids':retained})
        sources = [c for c in claims if (c.study_id or "") == mapping.study_id and
                   getattr(c, "target_" + mapping.field, None) == mapping.source_text]
        if not sources or any(c.state == "complete" for c in sources):
            term_map.append(mapping)
    return candidate.model_copy(update={
        "contracts": [c.model_copy(update={"claim_ids": [cid for cid in c.claim_ids if allowed(cid)]}) for c in candidate.contracts],
        "term_map": term_map,
        "unassigned": [u for u in candidate.unassigned if allowed(u.claim_id)],
    })


def _generate(manifest, step, prompt, schema, log_path, force=False, source_inputs=None, *, model_tier=None, timeout_s=1200):
    tiers = config.config().tiers
    tier = model_tier or ("contract_repair" if step.startswith("contracts:") and "contract_repair" in tiers
                         else "contracts" if "contracts" in tiers else "strong")
    options={"claude_effort": "medium", "source_inputs": {k:v for k,v in (source_inputs or {}).items() if k in {"pdf", "manifest"} or k.startswith("data:")}}
    fingerprint = response_cache.key(prompt, schema, [], tier, options)
    cache_path = log_path.with_suffix(".response.json")
    cached = response_cache.read(cache_path, fingerprint, schema) if not force else None
    if not cached and not force:
        class PriorUnscopedSchema:
            @staticmethod
            def model_json_schema():
                previous=schema.model_json_schema()
                for name in ('TermMapping','TermKey'):
                    definition=previous.get('$defs',{}).get(name,{})
                    definition.get('properties',{}).pop('claim_ids',None)
                return previous
            model_validate=schema.model_validate
        cached=response_cache.read(cache_path,response_cache.key(prompt,PriorUnscopedSchema,[],tier,options),PriorUnscopedSchema)
    if cached:
        parsed, call_id = cached
        return llm.LLMResult(text=parsed.model_dump_json(), parsed=parsed, ledger_id=call_id,
                             route=config.tier(tier).route, model=config.tier(tier).model)
    result = llm.call(step, prompt, paper_id=manifest.paper_id, stage="0", tier=tier,
                      schema=schema, large_context=True, cwd=manifest.dir, timeout_s=timeout_s,
                      claude_effort="medium", log_path=log_path)
    if result.parsed is not None:
        response_cache.write(cache_path, fingerprint, result.parsed, result.ledger_id or "")
    return result


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
    resume_candidate: Any = None,
) -> tuple[list[artifacts.EstimandContract], list[str]]:
    """Write contracts.json and redacted_methods.md, then repair any leak locally."""
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "contracts.json"
    methods_path = stage_dir / "redacted_methods.md"
    assignments_path = stage_dir / "contract_assignments.json"

    if out_path.exists() and methods_path.exists() and assignments_path.exists() and not force:
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

    adopted = None
    chunk_calls = None
    if resume_candidate is not None and not force:
        import hashlib
        adopted = json.loads(resume_candidate.read_text())
        if adopted["claims_hash"] != artifacts.content_hash(claims) or adopted["paper_hash"] != hashlib.sha256(paper_text.encode()).hexdigest():
            raise llm.LLMError("completed contract candidate no longer matches source inputs")
        out = ContractsAndMethods.model_validate(adopted["candidate"])
        r = llm.LLMResult(text=out.model_dump_json(), parsed=out, ledger_id=adopted["model_calls"][-1])
    elif config.config().contract_strategy == "chunked":
        from .contract_chunks import generate
        candidate, chunk_calls = generate(manifest, claims, paper_text, inputs or {}, force)
        r = llm.LLMResult(text=candidate.model_dump_json(), parsed=candidate, ledger_id=chunk_calls[-1] if chunk_calls else None)
    else:
        r = _generate(manifest, "contracts", artifacts.load_prompt(
            "stage0_contracts", paper_text=paper_text,
            claims_no_values=json.dumps(claims_without_values(claims), indent=1)),
            ContractsAndMethods, stage_dir / "logs" / "contracts.log", force, inputs)

    if r.parsed is None:
        raise llm.LLMError(f"contracts failed: {r.error}")
    original_out: ContractsAndMethods = r.parsed
    excluded_ids = {c.claim_id for c in claims if c.state != "complete"}
    projected_ids = sorted({cid for ct in original_out.contracts for cid in ct.claim_ids if cid in excluded_ids})
    out = project_eligible(original_out, claims)
    if not out.redacted_methods.strip():
        raise llm.LLMError("contracts call returned no redacted methods document")
    calls = chunk_calls if chunk_calls is not None else list(adopted["model_calls"]) if adopted else [r.ledger_id or ""]

    availability={'decisions':[],'complete':True}
    def source_method_errors(candidate):
        nonlocal availability
        if not any(u.reason!='not_an_analysis' for u in candidate.unassigned):
            availability={'decisions':[],'complete':True};return []
        from ..method_availability import source_payload,review
        availability=review(manifest.paper_id,source_payload([c.model_dump() for c in claims],
            [u.model_dump() for u in candidate.unassigned],[c.model_dump() for c in candidate.contracts],paper_text))
        if availability.get('model_call'):calls.append(availability['model_call'])
        return ['Independent source review requires assignment repair: '+json.dumps(d)
                for d in availability['decisions'] if d['status']=='recoverable' or not d['validated']]

    assignment_errors = validate_assignments(out.contracts, claims, out.term_map, out.unassigned, paper_text)
    assignment_errors += source_method_errors(out)
    for repair_attempt in range(2):
        if not assignment_errors:
            break
        from .contract_repairs import ContractRepair, apply as apply_repair
        correction = _generate(manifest, "contracts:identity_repair" + (str(repair_attempt+1) if repair_attempt else ""),
            "Return only the minimal ContractRepair patch for these errors. Preserve unchanged "
            "contracts, mappings, unassigned entries and methods. Do not regenerate unchanged entries. "
            "Every claim on a removed contract must be reassigned in this same patch or given an explicit source-supported unassigned disposition. "
            "Never solve identity errors by deleting required analyses or merging scalar tests into a broad topic. "
            "A correlation with age and a correlation with sex are separate analyses; each individually reported cell in a correlation matrix needs its own variable-pair contract. "
            "For regression, distinguish each reported coefficient from the overall model test. "
            "Use complete replacement entries only for identities that change. Remove mappings that "
            "cannot be supported. A source term must not be aliased across different model arithmetic "
            "or design levels; unassign the affected claim with specific located evidence when source "
            "identity cannot be supported. Missing sentinels such as none, null, unknown and not stated "
            "are absent information, not model identities or evidence of a conflict. A sources_conflict "
            "abstention must name its conflict_field and cite actual contradictory source evidence; "
            "reconsider abstentions caused only by a missing-field placeholder. Never change source "
            "claims or choose by reproduced numeric agreement. "
            "Use term_map.claim_ids to scope a phrase whose meaning differs across source occurrences. "
            "For correlations, the unordered variable pair may exchange outcome/contrast positions; do not rename one variable as the other. "
            "A source-only restatement link may use a unique printed signature to confirm candidates nominated by study, predictor, sample, statistic, model/covariates and a closed list of measures. "
            "Record the source context and candidate exclusion in the mapping note. Never match on numbers alone or use computed results. "
            "All supplied source exclusions remain in the audit.\nErrors:\n" + json.dumps(assignment_errors)
            + "\nPaper:\n" + paper_text + "\nEligible source claims:\n"
            + json.dumps(claims_without_values(claims)) + "\nCurrent candidate:\n" + out.model_dump_json()
            + ("\nPrevious repair still failed. Use literal contiguous source quotations, or explicit ellipses for omitted material including running page headers. Do not paraphrase inside quotes." if repair_attempt else ""),
            ContractRepair, stage_dir / "logs" / (f"contracts_patch_repair{repair_attempt+1}.log" if repair_attempt else "contracts_patch_repair.log"), force, inputs)
        calls.append(correction.ledger_id or "")
        if correction.parsed is None:
            raise llm.LLMError(f"contract identity repair failed: {correction.error}")
        try:
            out = apply_repair(out, correction.parsed)
        except ValueError as exc:
            assignment_errors = [f"Invalid repair operations (candidate preserved): {exc}", *assignment_errors]
            continue
        assignment_errors = validate_assignments(out.contracts, claims, out.term_map, out.unassigned, paper_text)
        assignment_errors += source_method_errors(out)
    if assignment_errors or not out.redacted_methods.strip():
        (stage_dir / "invalid_contracts.json").write_text(out.model_dump_json(indent=2))
        raise llm.LLMError("invalid analysis identities: " + " | ".join(assignment_errors))

    meta = artifacts.ArtifactMeta(
        artifact="EstimandContract",
        stage="0",
        inputs=inputs or {},
        prompt_versions={n: artifacts.prompt_version(n) for n in PROMPTS},
        model_calls=calls,
    )
    records = to_records(out.contracts, meta)
    artifacts.save(records, out_path)
    assignments_path.write_text(json.dumps({
        "term_map": [m.model_dump() for m in out.term_map],
        "unassigned": [u.model_dump() for u in out.unassigned],
        "evidence_status": "quotations located; semantic equivalence requires independent calibration",
        "model_calls": calls,
        "method_availability":availability,
        "removed_ineligible_assignments": projected_ids,
        "analyses_without_eligible_targets": [c.analysis_id for c in out.contracts if not c.claim_ids],
        "source_claim_count": len(claims),
        "eligible_claim_count": sum(c.state == "complete" for c in claims),
        "source_excluded": [{"claim_id": c.claim_id, "reason": c.abstain_reason} for c in claims if c.state != "complete"],
        "unassigned_eligible": [u.model_dump() for u in out.unassigned if any(c.claim_id == u.claim_id and c.state == "complete" for c in claims)],
        "adopted_generation": {k:v for k,v in adopted.items() if k != "candidate"} if adopted else None,
    }, indent=2) + "\n")
    methods_path.write_text(out.redacted_methods.strip() + "\n")

    design = leakcheck.design_numbers_from_manifest(manifest)
    result_ids = leakcheck.result_claim_ids(claims, records)
    hits, repair_calls = redact.repair(
        manifest, [out_path, methods_path], claims, design, result_ids
    )
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

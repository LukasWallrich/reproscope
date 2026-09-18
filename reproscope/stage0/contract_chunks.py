"""Bounded source assignments and immutable contract-body generation.

Each source claim gets one assignment row. Code owns group membership and IDs;
method writers cannot drop, merge, or reassign claims while describing analyses.
"""
from __future__ import annotations

import copy
import json
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from pydantic import BaseModel, ConfigDict, create_model

from .. import artifacts, config, llm, paths, provenance
from ..source_mapping import TermMapping, UnassignedClaim, normalise
from .contracts import (AnalysisIdentity, ContractsAndMethods, SlimContract,
                        claims_without_values, validate_assignments, _generate)

PROMPTS = ("stage0_assign_claims", "stage0_contract_body", "stage0_shared_methods")
CHUNK_SIZE = 32
BODY_BATCH_SIZE = 4
WORKERS = 3


class Disposition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Literal["not_an_analysis", "methods_insufficient", "sources_conflict"]
    note: str
    quote: str | None = None
    conflict_field: Literal["study", "outcome", "contrast", "model", "sample", "source_reading"] | None = None


class AssignmentRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    kind: Literal["scalar", "family", "unassigned"]
    identity: AnalysisIdentity | None = None
    design_family: Literal["independent_t", "paired_t", "one_sample_t", "correlation", "mixed_anova", "other", "unknown"] = "unknown"
    members: list[AnalysisIdentity] = []
    disposition: Disposition | None = None


class Assignments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[AssignmentRow]
    term_map: list[TermMapping] = []


# The model cannot return any field that controls assignment or identity.
FIXED_FIELDS = {"analysis_id", "identity", "claim_ids", "study_id", "analysis_label"}
ContractBody = create_model("ContractBody", __config__=ConfigDict(extra="forbid"), **{
    name: (field.annotation, copy.deepcopy(field))
    for name, field in SlimContract.model_fields.items() if name not in FIXED_FIELDS
})


class BodyEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_key: str
    body: ContractBody


class Bodies(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[BodyEntry]


class SharedMethods(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research_questions: str
    design_and_participants: str
    materials_and_measures: str
    procedure: str
    software_and_settings: str


def identity_key(identity, family="unknown"):
    values = [normalise(getattr(identity, field)) for field in
              ("study", "outcome", "contrast", "model", "sample")]
    if family == "correlation":
        values[1:3] = sorted(values[1:3])
    return tuple(values)


def row_errors(result, claims):
    expected = {c.claim_id: c for c in claims}
    ids = [r.claim_id for r in result.rows]
    errors = []
    if len(ids) != len(set(ids)) or set(ids) != set(expected):
        errors.append(f"Exactly one row per input claim required; missing={sorted(set(expected)-set(ids))}; unknown={sorted(set(ids)-set(expected))}; duplicate rows={len(ids)-len(set(ids))}")
    for row in result.rows:
        claim = expected.get(row.claim_id)
        if claim is None:
            continue
        if row.kind == "unassigned":
            if row.identity is not None or row.disposition is None or row.members:
                errors.append(f"{row.claim_id}: unassigned row requires only a disposition")
            if (row.disposition and row.disposition.reason == "not_an_analysis"
                    and (claim.quantity_role == "inferential" or claim.quantity_kind in {"t", "F", "chi2", "p_value", "coefficient", "d", "r", "OR", "HR"})):
                errors.append(f"{row.claim_id}: an inferential quantity cannot be dismissed as not_an_analysis")
            continue
        if row.identity is None or row.disposition is not None:
            errors.append(f"{row.claim_id}: assigned row requires identity and no disposition")
            continue
        if any(not str(v).strip() for v in row.identity.model_dump().values()):
            errors.append(f"{row.claim_id}: empty identity component")
        if claim.study_id and row.identity.study != claim.study_id:
            errors.append(f"{row.claim_id}: study differs from source")
        if row.kind == "family":
            keys = {identity_key(m, row.design_family) for m in row.members}
            if claim.aggregation == "scalar" or len(keys) < 2 or len(keys) != len(row.members):
                errors.append(f"{row.claim_id}: family requires a non-scalar source aggregation and distinct enumerated members")
            if row.design_family not in {"correlation", "paired_t", "independent_t", "one_sample_t"}:
                errors.append(f"{row.claim_id}: family must identify the underlying scalar design")
        elif ((claim.aggregation in {"all", "any", "min", "max", "vector"}
               and not (claim.quantity_kind == "ci_bound" and claim.aggregation in {"min", "max"}))
              or row.members):
            errors.append(f"{row.claim_id}: aggregate source claim requires an enumerated family")
    return errors


def groups_from(rows):
    groups = {}
    for row in rows:
        if row.kind == "unassigned" or row.identity is None:
            continue
        key = identity_key(row.identity, row.design_family)
        if key not in groups:
            groups[key] = {"key": provenance.digest(key)[:16], "identity": row.identity,
                           "kind": row.kind, "design_family": row.design_family,
                           "members": row.members, "claim_ids": []}
        group = groups[key]
        if (group["kind"], group["design_family"]) != (row.kind, row.design_family):
            raise ValueError(f"{row.claim_id}: scalar/family or design conflict within one identity")
        if {identity_key(m, row.design_family) for m in group["members"]} != {identity_key(m, row.design_family) for m in row.members}:
            raise ValueError(f"{row.claim_id}: family membership changed across repeated reports")
        group["claim_ids"].append(row.claim_id)
    return list(groups.values())


def skeletons(rows):
    out = []
    for i, group in enumerate(groups_from(rows), 1):
        identity = group["identity"]
        label = f"{identity.outcome} / {identity.contrast} ({identity.model})".replace("_", " ")
        out.append(SlimContract(analysis_id=f"a{i:03d}", identity=identity,
            claim_ids=group["claim_ids"], study_id=identity.study, analysis_label=label,
            design=artifacts.AnalysisDesign(family=group["design_family"], contrast=identity.contrast,
                independent_unit="not stated", evidence="Method description pending source-only body generation")))
    return out


def dispositions(rows):
    return [UnassignedClaim(claim_id=r.claim_id, **r.disposition.model_dump())
            for r in rows if r.kind == "unassigned" and r.disposition is not None]


def scoped_mappings(mappings, claims, rows=()):
    """A chunk owns only aliases for the source records it was shown."""
    ids = {c.claim_id for c in claims}
    by_id = {c.claim_id: c for c in claims}
    correlations = {r.claim_id for r in rows if r.design_family == "correlation"}
    out = []
    for mapping in mappings:
        if mapping.claim_ids and not set(mapping.claim_ids) <= ids:
            raise ValueError("alias scope reaches outside this assignment chunk")
        # Correlations are unordered pairs. Resolve an alias's source coordinate
        # from its exact string, without changing its semantic destination.
        if (mapping.field in {"outcome", "contrast"} and mapping.claim_ids
                and set(mapping.claim_ids) <= correlations):
            other = "contrast" if mapping.field == "outcome" else "outcome"
            scoped = [by_id[cid] for cid in mapping.claim_ids]
            if (all(getattr(c, "target_" + mapping.field) != mapping.source_text for c in scoped)
                    and all(getattr(c, "target_" + other) == mapping.source_text for c in scoped)):
                mapping = mapping.model_copy(update={"field": other})
        scope = mapping.claim_ids or [c.claim_id for c in claims
            if (c.study_id or "") == mapping.study_id
            and getattr(c, "target_" + mapping.field) == mapping.source_text]
        if not scope:
            raise ValueError("alias does not match any source field in this chunk")
        out.append(mapping.model_copy(update={"claim_ids": scope}))
    return out


def checked_call(manifest, phase, prompt, schema, validator, log_root, source_inputs, force=False):
    tiers = config.config().tiers
    cheap = "contracts" if "contracts" in tiers else "strong"
    escalation = "contract_repair" if "contract_repair" in tiers else "strong"
    calls, feedback = [], ""
    key = provenance.digest({"phase": phase, "prompt": prompt, "schema": schema.model_json_schema()})[:20]
    errors = []
    for attempt, tier in enumerate((cheap, cheap, escalation), 1):
        model_key = provenance.digest(config.tier(tier).model_dump())[:8]
        request_key = provenance.digest({"prompt": prompt + feedback,
            "source_inputs": {k: v for k, v in source_inputs.items() if k in {"pdf", "manifest"} or k.startswith("data:")}})[:10]
        legacy_path = log_root / f"{phase}_{key}_{attempt}_{model_key}.log"
        log_path = log_root / f"{phase}_{key}_{attempt}_{model_key}_{request_key}.log"
        # Preserve prior receipts while allowing a warm transition to immutable request filenames.
        if legacy_path.with_suffix(".response.json").exists() and not log_path.with_suffix(".response.json").exists():
            import shutil
            shutil.copy2(legacy_path.with_suffix(".response.json"), log_path.with_suffix(".response.json"))
        response = _generate(manifest, f"contracts:{phase}:{key}:{attempt}", prompt + feedback,
            schema, log_path, force, source_inputs,
            model_tier=tier, timeout_s=600)
        if response.ledger_id:
            calls.append(response.ledger_id)
        parsed = response.parsed
        errors = [response.error or "missing structured response"] if parsed is None else validator(parsed)
        log_root.mkdir(parents=True, exist_ok=True)
        log_path.with_suffix(".validation.json").write_text(json.dumps({
            "phase": phase, "input_key": key, "attempt": attempt, "tier": tier,
            "model_call": response.ledger_id, "passed": not errors, "errors": errors,
            "response_hash": provenance.digest(parsed.model_dump()) if parsed is not None else None,
        }, indent=2) + "\n")
        if not errors:
            return parsed, calls
        feedback = ("\nThe preceding response failed controller validation. Return a complete corrected response "
                    "for this same bounded input, retaining all required IDs. Errors:\n" + json.dumps(errors)
                    + ("\nPrevious candidate:\n" + parsed.model_dump_json() if parsed is not None else ""))
    raise llm.LLMError(f"{phase} chunk {key} failed: " + " | ".join(errors))


def assignment_pass(manifest, claims, paper_text, source_inputs, force=False):
    rows, mappings, calls, processed = [], [], [], []
    log_root = paths.run_dir(manifest.paper_id, 0) / "logs" / "contract_chunks"
    # Stable physical order; studies are never mixed in a single request.
    studies = {}
    for claim in claims:
        if claim.state == "complete":
            studies.setdefault(claim.study_id or "", []).append(claim)
    for study_claims in studies.values():
        for start in range(0, len(study_claims), CHUNK_SIZE):
            batch = study_claims[start:start + CHUNK_SIZE]
            registry = [{"identity": g["identity"].model_dump(), "kind": g["kind"],
                         "design_family": g["design_family"],
                         "members": [m.model_dump() for m in g["members"]]} for g in groups_from(rows)]
            prompt = artifacts.load_prompt("stage0_assign_claims", paper_text=paper_text,
                registry=json.dumps({"groups": registry, "term_map": [m.model_dump() for m in mappings]}),
                claims=json.dumps(claims_without_values(batch)))

            def validate(candidate):
                errors = row_errors(candidate, batch)
                if errors:
                    return errors
                try:
                    combined_rows = rows + candidate.rows
                    combined_mappings = mappings + scoped_mappings(candidate.term_map, batch, candidate.rows)
                    errors += validate_assignments(skeletons(combined_rows), processed + batch,
                        combined_mappings, dispositions(combined_rows), paper_text)
                except ValueError as exc:
                    errors.append(str(exc))
                return errors

            candidate, made = checked_call(manifest, "assign", prompt, Assignments, validate,
                log_root, source_inputs, force)
            rows.extend(candidate.rows)
            mappings.extend(scoped_mappings(candidate.term_map, batch, candidate.rows))
            calls.extend(made)
            processed.extend(batch)
            print(f"contract assignments: {len(processed)}/{len([c for c in claims if c.state == 'complete'])}", flush=True)
    return rows, mappings, calls


def body_errors(result, groups):
    expected = {g["key"]: g for g in groups}
    keys = [entry.group_key for entry in result.items]
    errors = []
    if set(keys) != set(expected) or len(keys) != len(set(keys)):
        errors.append("Return exactly one body for every supplied group_key")
    for entry in result.items:
        group = expected.get(entry.group_key)
        if group is None:
            continue
        if not entry.body.outcome or not entry.body.model_type or entry.body.design is None:
            errors.append(f"{entry.group_key}: outcome, model_type and source-grounded design are required")
        elif group["design_family"] != "unknown" and entry.body.design.family != group["design_family"]:
            errors.append(f"{entry.group_key}: method body changes the assigned scalar design family")
    return errors


def method_document(shared, contracts):
    sections = [("Research questions", shared.research_questions),
                ("Design and participants", shared.design_and_participants),
                ("Materials and measures", shared.materials_and_measures),
                ("Procedure", shared.procedure)]
    text = "# Methods\n\n" + "\n\n".join(f"## {title}\n\n{body}" for title, body in sections)
    text += "\n\n## Analysis index\n\nThe accompanying contracts specify the complete methods for each analysis.\n"
    for contract in contracts:
        text += f"- {contract.analysis_id}: {contract.analysis_label}\n"
    return text + f"\n## Software and settings\n\n{shared.software_and_settings}\n"


def generate(manifest, claims, paper_text, source_inputs, force=False):
    rows, mappings, calls = assignment_pass(manifest, claims, paper_text, source_inputs, force)
    groups = groups_from(rows)
    fixed = skeletons(rows)
    log_root = paths.run_dir(manifest.paper_id, 0) / "logs" / "contract_chunks"
    by_claim = {c.claim_id: c for c in claims}

    def bodies(batch):
        payload = [{"group_key": g["key"], "identity": g["identity"].model_dump(),
            "kind": g["kind"], "design_family": g["design_family"],
            "members": [m.model_dump() for m in g["members"]],
            "claims": claims_without_values([by_claim[c] for c in g["claim_ids"]])} for g in batch]
        prompt = artifacts.load_prompt("stage0_contract_body", paper_text=paper_text, groups=json.dumps(payload))
        return checked_call(manifest, "body", prompt, Bodies, lambda r: body_errors(r, batch),
                            log_root, source_inputs, force)

    def shared_methods():
        prompt = artifacts.load_prompt("stage0_shared_methods", paper_text=paper_text)
        return checked_call(manifest, "methods", prompt, SharedMethods,
            lambda r: ["All shared-method sections need content or an explicit not-stated statement"]
            if any(not v.strip() for v in r.model_dump().values()) else [], log_root, source_inputs, force)

    batches = [groups[i:i + BODY_BATCH_SIZE] for i in range(0, len(groups), BODY_BATCH_SIZE)]
    results = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        shared_future = pool.submit(shared_methods)
        futures = [pool.submit(bodies, batch) for batch in batches]
        for future in futures:
            parsed, made = future.result()
            results.update({entry.group_key: entry.body for entry in parsed.items})
            calls.extend(made)
        shared, made = shared_future.result()
        calls.extend(made)
    for contract, group in zip(fixed, groups):
        body = results[group["key"]]
        # Stamp only method fields; all assignment fields remain controller-owned.
        for name, value in body:
            setattr(contract, name, value)
        if group["kind"] == "family":
            contract.outcome += "; Enumerated scalar family: " + json.dumps([m.model_dump() for m in group["members"]])
    output = ContractsAndMethods(contracts=fixed, term_map=mappings,
        unassigned=dispositions(rows), redacted_methods=method_document(shared, fixed))
    errors = validate_assignments(output.contracts, claims, output.term_map, output.unassigned, paper_text)
    if errors:
        raise llm.LLMError("assembled chunked contracts failed: " + " | ".join(errors))
    receipt = {"strategy": "claim_rows_then_fixed_bodies", "source_inputs": source_inputs,
               "rows": [r.model_dump() for r in rows], "model_calls": calls,
               "groups": [{**g, "identity": g["identity"].model_dump(), "members": [m.model_dump() for m in g["members"]]} for g in groups]}
    (paths.run_dir(manifest.paper_id, 0) / "contract_grouping.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return output, calls

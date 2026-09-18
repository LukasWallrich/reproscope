"""Stage 0: paper -> claims, estimand contracts, data readiness, blind materials.

Every step writes one artifact and is skipped when that artifact is already there,
so a run that fails halfway resumes without repeating a paid call.
"""

from __future__ import annotations

from pathlib import Path

from .. import artifacts, config, llm, paths
from . import arbitrate, contracts, extract, leakcheck, readiness, redact

PROMPTS = (
    "stage0_extract",
    "stage0_arbitrate",
    "stage0_contracts",
    "stage0_assign_claims",
    "stage0_contract_body",
    "stage0_shared_methods",
    "stage0_readiness",
    "stage0_leak_repair",
    "stage0_leak_audit",
    "stage1_replica_task",
)


def input_hashes(manifest) -> dict[str, str]:
    """PDF, data files, manifest and prompt versions: the stage's whole input surface."""
    h = {"pdf": artifacts.sha256_file(manifest.path(manifest.pdf))}
    for rel in manifest.data_files:
        p = manifest.path(rel)
        if p.exists():
            h[f"data:{rel}"] = artifacts.sha256_file(p)
    h["manifest"] = artifacts.sha256_file(manifest.dir / "manifest.json")
    from .. import provenance
    h.update(provenance.corpus(manifest.paper_id))
    h["implementation"] = provenance.implementation(
        *(f"stage0/{p.name}" for p in sorted(Path(__file__).parent.glob("*.py"))),
        "artifacts.py", "statistical.py", "statistic_metadata.py", "binding_policy.py", "sample_filters.py", "reported_metadata.py", "source_mapping.py", "source_anchor.py", "source_layout.py", "source_diagnostics.py", "response_cache.py", "intake_validation.py", "source_integrity.py", "data_checks.py", "focal.py", "stage1/blind.py")
    h["intake_policy"] = provenance.digest({"descriptive_readouts": config.config().descriptive_readouts, "contract_strategy": config.config().contract_strategy})
    h["models"] = provenance.digest({name: spec.model_dump() for name, spec in config.config().tiers.items()})
    for name in PROMPTS:
        h[f"prompt:{name}"] = artifacts.prompt_version(name)
    return h


STEPS = ("extract", "arbitrate", "contracts", "readiness", "redact")


def step_inputs(manifest, step: str, **upstream) -> dict[str, str]:
    """Scope paid-step caches to their inputs; downstream validators cannot invalidate intake."""
    from .. import provenance
    modules = {
        "arbitrate": ("stage0/arbitrate.py", "stage0/extract.py", "response_cache.py", "artifacts.py", "source_integrity.py", "source_anchor.py", "source_layout.py"),
        "contracts": ("stage0/contracts.py", "stage0/contract_chunks.py", "stage0/contract_repairs.py", "response_cache.py", "source_mapping.py", "artifacts.py", "statistical.py"),
        "readiness": ("stage0/readiness.py", "intake_validation.py", "binding_policy.py", "sample_filters.py", "data_checks.py", "artifacts.py", "statistical.py"),
        "redact": ("stage0/redact.py", "stage0/leakcheck.py", "stage1/blind.py", "statistic_metadata.py", "artifacts.py"),
    }
    prompts = {
        "arbitrate": arbitrate.PROMPTS,
        "contracts": contracts.PROMPTS,
        "readiness": readiness.PROMPTS,
        "redact": (*redact.PROMPTS, "stage1_replica_task"),
    }
    ins = {k: v for k, v in input_hashes(manifest).items()
           if k != "implementation" and not k.startswith("prompt:")}
    ins["implementation"] = provenance.implementation(*modules[step], "llm.py")
    ins.update({f"prompt:{name}": artifacts.prompt_version(name) for name in prompts[step]})
    ins.update({k: artifacts.content_hash(v) for k, v in upstream.items()})
    return ins


def run(paper_id: str, force: bool = False, force_steps: set[str] | None = None) -> None:
    force_steps = force_steps or set()

    def fstep(name: str) -> bool:
        return force or name in force_steps

    manifest = paths.manifest(paper_id)
    stage_dir = paths.run_dir(paper_id, 0)
    inputs = input_hashes(manifest)
    if paths.is_done(stage_dir, inputs) and not force and not force_steps:
        print(f"stage 0 already done for {paper_id} (use --force to rerun)", flush=True)
        return

    pages = extract.render_pages(manifest, force=fstep("extract"))
    text_path = extract.extract_text(manifest, force=fstep("extract"))
    paper_text = text_path.read_text(errors="replace")
    print(f"pages: {len(pages)}, text: {len(paper_text)} chars", flush=True)

    # Readers have independent input-only contexts and separate output caches.
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as readers:
        first=readers.submit(extract.extract_one, manifest, "vision_a", pages,
                             stage_dir / "extract_a.json", force=fstep("extract"))
        second=readers.submit(extract.extract_one, manifest, "vision_b", pages,
                              stage_dir / "extract_b.json", force=fstep("extract"))
        list_a, _ = first.result()
        list_b, _ = second.result()
    list_a = _nonempty(manifest, "vision_a", pages, stage_dir / "extract_a.json", list_a, list_b)
    list_b = _nonempty(manifest, "vision_b", pages, stage_dir / "extract_b.json", list_b, list_a)
    print(f"extracted: A={len(list_a.claims)} B={len(list_b.claims)}", flush=True)
    import json
    coverage = {}
    for lane, extracted in (("A", list_a), ("B", list_b)):
        seen = {r.page for r in extracted.regions}
        coverage[lane] = {"missing_pages": sorted(set(range(1, len(pages)+1))-seen),
                          "unreadable_regions": [r.model_dump() for r in extracted.regions if r.status == "unreadable"],
                          "regions": [r.model_dump() for r in extracted.regions]}
    (stage_dir / "extraction_coverage.json").write_text(json.dumps(coverage, indent=2)+"\n")
    if any(c["missing_pages"] for c in coverage.values()):
        raise ValueError("extraction region inventory does not cover every PDF page; inspect extraction_coverage.json")

    claims, _ = arbitrate.run(
        manifest, list_a, list_b, pages, step_inputs(manifest, "arbitrate", extract_a=list_a, extract_b=list_b),
        force=fstep("arbitrate"),
    )
    print(f"claims: {len(claims)}", flush=True)
    from ..reported_metadata import fields as metadata_fields
    (stage_dir/"reported_fields.json").write_text(json.dumps({"parent_result_records":len(claims),"metadata":metadata_fields([c.model_dump() for c in claims]),"scope":"Printed df fields belong to their parent test; no additional analysis is introduced."},indent=2)+"\n")
    from .. import source_diagnostics
    source_diagnostics.write(stage_dir / "source_diagnostics.json", claims, extract.page_texts(manifest, len(pages)), manifest.path(manifest.pdf))

    # One reading of the paper produces both the contracts and the redacted methods.
    contract_records, _ = contracts.run(
        manifest, claims, paper_text, step_inputs(manifest, "contracts", claims=claims), force=fstep("contracts")
    )
    print(f"contracts: {len(contract_records)}", flush=True)

    assignments = json.loads((stage_dir / "contract_assignments.json").read_text()) if (stage_dir / "contract_assignments.json").exists() else {}
    assignment_errors = contracts.validate_assignments(contract_records, claims, assignments.get("term_map"), assignments.get("unassigned"), paper_text)
    if assignment_errors:
        raise ValueError("invalid analysis identities: " + " | ".join(assignment_errors))
    if manifest.focal_claim:
        from ..focal import bind_focal_claim
        bind_focal_claim(manifest, claims, contract_records, allow_llm=False)

    readiness_record, _ = readiness.run(
        manifest, contract_records, step_inputs(manifest, "readiness", contracts=contract_records), force=fstep("readiness")
    )
    bound = _complete_analyses(readiness_record)
    if not bound and manifest.data_files:
        # One mid-tier call gates every analysis of the paper. When it binds nothing
        # although data were deposited, its verdict is checked once at the strong tier
        # before eight replica agents are launched on an empty packet.
        print("readiness: no analysis bound to the deposited data; rechecking at the strong tier", flush=True)
        readiness_record, _ = readiness.run(
            manifest, contract_records, step_inputs(manifest, "readiness", contracts=contract_records), force=fstep("readiness"), tier="strong"
        )
        bound = _complete_analyses(readiness_record)
        if not bound:
            reasons = list((readiness_record.per_analysis_reasons or {}).values())[:3]
            raise RuntimeError(
                "readiness bound no analysis to the deposited data twice: " + " | ".join(reasons)
            )
    print(
        f"readiness: {len(readiness_record.variable_bindings)} bindings, "
        f"{len(bound)} of {len(contract_records)} analyses complete",
        flush=True,
    )

    report, _ = redact.run(
        manifest, claims, contract_records, step_inputs(manifest, "redact", claims=claims, contracts=contract_records, readiness=readiness_record),
        force=fstep("redact"),
    )
    print(
        f"redaction: scan_clean={report.scan_clean} "
        f"audit={report.leakage_audit_verdict}",
        flush=True,
    )

    if not report.scan_clean:
        # Stage 1 refuses blind material with a hit, so stage 0 is not done either:
        # the caller sees a failure and a rerun redoes the redaction, not the whole stage.
        raise leakcheck.LeakDetected(
            f"{len(report.scan_hits)} reported value(s) survive repair in the blind material"
        )
    import json
    audit_path = stage_dir / "leak_audit.json"
    if audit_path.exists():
        status = json.loads(audit_path.read_text()).get("blinding_status")
        if status in {"blocked", "unresolved"}:
            raise leakcheck.LeakDetected(f"final replica packet blinding is {status}; inspect leak_audit.json")
    if config.config().descriptive_readouts:
        from ..descriptive_reproduction import run as reproduce_descriptives
        descriptive = reproduce_descriptives(paper_id)
        print(f"descriptive readouts: {len(descriptive['results'])} independently checked", flush=True)
    paths.mark_done(stage_dir, inputs)


def _complete_analyses(record) -> list[str]:
    return [a for a, st in (record.per_analysis_state or {}).items() if st == "complete"]


def _nonempty(manifest, tier, pages, out_path, mine, other):
    """A cheap extractor can answer a successful structured call with an empty claim
    list while its notes describe the claims it meant to emit. Arbitration with one
    side empty would pass every claim of the other side unchecked, so the empty
    extractor runs once more and the stage refuses if it is still empty."""
    if mine.claims or not other.claims:
        return mine
    print(f"extracted: {tier} returned no claims; retrying once", flush=True)
    mine, _ = extract.extract_one(manifest, tier, pages, out_path, force=True)
    if not mine.claims:
        raise llm.LLMError(
            f"{tier} returned no claims twice while the other extractor found {len(other.claims)}"
        )
    return mine


__all__ = ["run", "leakcheck", "input_hashes"]

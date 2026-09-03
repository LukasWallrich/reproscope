"""Stage 0: paper -> claims, estimand contracts, data readiness, blind materials.

Every step writes one artifact and is skipped when that artifact is already there,
so a run that fails halfway resumes without repeating a paid call.
"""

from __future__ import annotations

from .. import artifacts, paths
from . import arbitrate, contracts, extract, leakcheck, readiness, redact

PROMPTS = (
    "stage0_extract",
    "stage0_arbitrate",
    "stage0_contracts",
    "stage0_readiness",
    "stage0_leak_repair",
    "stage0_leak_audit",
)


def input_hashes(manifest) -> dict[str, str]:
    """PDF, data files, manifest and prompt versions: the stage's whole input surface."""
    h = {"pdf": artifacts.sha256_file(manifest.path(manifest.pdf))}
    for rel in manifest.data_files:
        p = manifest.path(rel)
        if p.exists():
            h[f"data:{rel}"] = artifacts.sha256_file(p)
    h["manifest"] = artifacts.sha256_file(manifest.dir / "manifest.json")
    for name in PROMPTS:
        h[f"prompt:{name}"] = artifacts.prompt_version(name)
    return h


STEPS = ("extract", "arbitrate", "contracts", "readiness", "redact")


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

    list_a, _ = extract.extract_one(
        manifest, "vision_a", pages, stage_dir / "extract_a.json", force=fstep("extract")
    )
    list_b, _ = extract.extract_one(
        manifest, "vision_b", pages, stage_dir / "extract_b.json", force=fstep("extract")
    )
    print(f"extracted: A={len(list_a.claims)} B={len(list_b.claims)}", flush=True)

    claims, _ = arbitrate.run(manifest, list_a, list_b, pages, inputs, force=fstep("arbitrate"))
    print(f"claims: {len(claims)}", flush=True)

    # One reading of the paper produces both the contracts and the redacted methods.
    contract_records, contract_calls = contracts.run(
        manifest, claims, paper_text, inputs, force=fstep("contracts")
    )
    print(f"contracts: {len(contract_records)}", flush=True)

    # Rebuilt contracts carry new analysis ids and labels, so the two steps that read
    # them are rebuilt too rather than reused against the previous set.
    downstream = force or bool(contract_calls)

    readiness_record, _ = readiness.run(
        manifest, contract_records, inputs, force=downstream or fstep("readiness")
    )
    print(f"readiness: {len(readiness_record.variable_bindings)} bindings", flush=True)

    report, _ = redact.run(
        manifest, claims, contract_records, inputs, force=downstream or fstep("redact")
    )
    print(
        f"redaction: scan_clean={report.scan_clean} "
        f"audit={report.leakage_audit_verdict}",
        flush=True,
    )

    paths.mark_done(stage_dir, inputs)


__all__ = ["run", "leakcheck", "input_hashes"]

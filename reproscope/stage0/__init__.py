"""Stage 0: paper -> claims, estimand contracts, data readiness, blind materials.

Every step writes one artifact and is skipped when that artifact is already there,
so a run that fails halfway resumes without repeating a paid call.
"""

from __future__ import annotations

from .. import artifacts, llm, paths
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
    list_a = _nonempty(manifest, "vision_a", pages, stage_dir / "extract_a.json", list_a, list_b)
    list_b = _nonempty(manifest, "vision_b", pages, stage_dir / "extract_b.json", list_b, list_a)
    print(f"extracted: A={len(list_a.claims)} B={len(list_b.claims)}", flush=True)

    # Each step's cache key is the stage's input surface plus the content of the
    # artifacts it reads, so a rebuilt upstream artifact rebuilds everything below it.
    def keyed(**upstream) -> dict[str, str]:
        return {**inputs, **{k: artifacts.content_hash(v) for k, v in upstream.items()}}

    claims, _ = arbitrate.run(
        manifest, list_a, list_b, pages, keyed(extract_a=list_a, extract_b=list_b),
        force=fstep("arbitrate"),
    )
    print(f"claims: {len(claims)}", flush=True)

    # One reading of the paper produces both the contracts and the redacted methods.
    contract_records, _ = contracts.run(
        manifest, claims, paper_text, keyed(claims=claims), force=fstep("contracts")
    )
    print(f"contracts: {len(contract_records)}", flush=True)

    readiness_record, _ = readiness.run(
        manifest, contract_records, keyed(contracts=contract_records), force=fstep("readiness")
    )
    bound = _complete_analyses(readiness_record)
    if not bound and manifest.data_files:
        # One mid-tier call gates every analysis of the paper. When it binds nothing
        # although data were deposited, its verdict is checked once at the strong tier
        # before eight replica agents are launched on an empty packet.
        print("readiness: no analysis bound to the deposited data; rechecking at the strong tier", flush=True)
        readiness_record, _ = readiness.run(
            manifest, contract_records, keyed(contracts=contract_records), force=True, tier="strong"
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
        manifest, claims, contract_records, keyed(claims=claims, contracts=contract_records),
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

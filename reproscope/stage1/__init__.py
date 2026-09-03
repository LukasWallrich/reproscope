"""Stage 1 — blind reproduction.

Replicas re-implement the analysis from redacted methods and the data alone; the
match step grades them against the reported values; the targeted arm runs only if
they miss; the diagnosis is the unblinded conjecture at the end.
"""

from __future__ import annotations

from typing import Any

from .. import artifacts, config, paths
from . import audit, blind, diagnose, match, replicas, rerun, targeted

__all__ = ["run", "audit", "blind", "diagnose", "match", "replicas", "rerun", "targeted"]

STAGE0_INPUTS = ("claims.json", "contracts.json", "redacted_methods.md", "blind_contract.json")

# Artifact files carry `meta` (a timestamp and call ids that change on every re-save
# without changing the content); hash them on their analytical payload instead of the
# file. blind_contract.json and redacted_methods.md carry no `meta` and stay file-hashed.
STAGE0_ARTIFACT_CLASSES = {
    "claims.json": artifacts.ClaimRecord,
    "contracts.json": artifacts.EstimandContract,
}


def inputs(paper_id: str) -> dict[str, str]:
    s0 = paths.run_dir(paper_id, 0)
    hashes: dict[str, str] = {}
    for name in STAGE0_INPUTS:
        path = s0 / name
        if not path.exists():
            continue
        cls = STAGE0_ARTIFACT_CLASSES.get(name)
        hashes[name] = (
            artifacts.content_hash(artifacts.load(cls, path))
            if cls is not None
            else artifacts.sha256_file(path)
        )
    hashes["models.toml"] = artifacts.sha256_file(paths.ROOT / "models.toml")
    hashes["manifest"] = artifacts.sha256_file(paths.corpus_dir(paper_id) / "manifest.json")
    return hashes


def full_lineup() -> list[str]:
    """Every replica id in models.toml, ignoring REPROSCOPE_FAMILIES and REPROSCOPE_RUNS.

    Stage 1 is only done when the whole lineup has run, so running the frontier
    families first and the cheap ones later leaves the stage open in between.
    """
    return [
        f"{family}_{i}"
        for family, spec in config.replicas().items()
        for i in range(1, spec.runs + 1)
    ]


STEPS = ("replicas", "match", "targeted", "rerun", "diagnose")


def run(
    paper_id: str,
    force: bool = False,
    families: list[str] | None = None,
    only: list[str] | None = None,
    force_steps: set[str] | None = None,
) -> dict[str, Any]:
    """Run Stage 1 end to end. Individual steps resume from what is already on disk."""
    force_steps = force_steps or set()

    def fstep(name: str) -> bool:
        return force or name in force_steps

    stage_dir = paths.run_dir(paper_id, 1)
    ins = inputs(paper_id)
    if paths.is_done(stage_dir, ins) and not force and not force_steps:
        print(f"stage 1 already done for {paper_id} (use --force to rerun)", flush=True)
        return {"skipped": True}

    traces = replicas.run(paper_id, force=fstep("replicas"), families=families, only=only)
    ran = [t for t in traces if t.ran]
    print(f"replicas: {len(ran)}/{len(traces)} produced runnable results", flush=True)

    on_disk = {t.replica_id: t.ran for t in replicas.load_traces(paper_id)}
    missing = [rid for rid in full_lineup() if not on_disk.get(rid)]

    comparison = match.run(paper_id, force=fstep("match"))
    reconstruction = targeted.run(paper_id, comparison, force=fstep("targeted"))
    original = rerun.run(paper_id, force=fstep("rerun"))
    diagnosis = diagnose.run(paper_id, force=fstep("diagnose"))

    complete = not missing
    if complete:
        paths.mark_done(stage_dir, ins)
    else:
        print(f"stage 1 left open; not yet run: {', '.join(missing)}", flush=True)
    return {
        "traces": traces,
        "missing_replicas": missing,
        "match": comparison,
        "targeted": reconstruction,
        "rerun": original,
        "diagnosis": diagnosis,
        "done": complete,
    }

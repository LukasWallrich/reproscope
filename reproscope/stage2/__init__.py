"""Stage 2 — analysis review: three narrow checks plus one broad referee pass."""

from __future__ import annotations

from .. import artifacts, paths
from . import review as _review

__all__ = ["run"]


STEPS = ("causal_language", "mde", "alignment", "broad")


def run(paper_id: str, force: bool = False, force_steps: set[str] | None = None) -> dict:
    """Run the four checks, assemble review.json and review.md, mark the stage done."""
    force_steps = force_steps or set()
    stage_dir = paths.run_dir(paper_id, 2)
    inp = _review.gather(paper_id)

    if paths.is_done(stage_dir, inp.hashes) and not force and not force_steps:
        print(f"stage 2: up to date ({stage_dir / 'review.json'})", flush=True)
        return {"skipped": True, "review": stage_dir / "review.json"}

    records = {}
    for name, fn in (
        ("causal_language", _review.check_causal_language),
        ("mde", _review.check_mde),
        ("alignment", _review.check_alignment),
        ("broad", _review.check_broad),
    ):
        rec = fn(inp, force=force or name in force_steps)
        state = rec.state if rec.state == "complete" else f"abstained ({rec.abstain_reason})"
        print(f"stage 2: {name} — {state}", flush=True)
        records[name] = rec

    result = _review.assemble(inp, records)
    artifacts.save(result, stage_dir / "review.json")
    (stage_dir / "review.md").write_text(_review.render_md(inp, result, records))
    paths.mark_done(stage_dir, inp.hashes)
    print(f"stage 2: wrote {stage_dir / 'review.json'} and review.md", flush=True)
    return {"skipped": False, "review": stage_dir / "review.json", "records": records}

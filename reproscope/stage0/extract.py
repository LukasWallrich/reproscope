"""Step 1 (pages + text layer) and step 2 (the two independent vision extractions)."""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths

MAX_IMAGE_BYTES = 1_500_000
DPI_LADDER = (110, 90, 72)
CHUNK_PAGES = 8


# --- slim schemas ---------------------------------------------------------
# The artifact models allow extra keys and carry open maps, so their JSON schema
# cannot be closed for strict structured-output mode. Every model call therefore
# uses a closed, flat model of its own; the mapping into the artifact happens here.


class SlimLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    kind: str | None = None
    label: str | None = None
    cell: str | None = None


class SlimClaim(BaseModel):
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


class ClaimList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[SlimClaim] = []
    notes: str | None = None


# --- pages and text -------------------------------------------------------


def page_paths(manifest) -> list[Path]:
    return sorted((manifest.dir / "pages").glob("p[0-9][0-9][0-9].png"))


def render_pages(manifest, force: bool = False) -> list[Path]:
    """corpus/<id>/pages/p001.png ... , at the highest DPI that keeps images small."""
    existing = page_paths(manifest)
    if existing and not force:
        return existing
    pdf = manifest.path(manifest.pdf)
    out = manifest.dir / "pages"
    made: list[Path] = []
    for dpi in DPI_LADDER:
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        subprocess.run(
            ["pdftoppm", "-r", str(dpi), "-png", str(pdf), str(out / "pg")], check=True
        )
        made = sorted(out.glob("pg-*.png"))
        if not made:
            raise RuntimeError(f"pdftoppm produced no pages for {pdf}")
        if max(p.stat().st_size for p in made) <= MAX_IMAGE_BYTES:
            break
    pages = []
    for i, p in enumerate(made, 1):
        target = out / f"p{i:03d}.png"
        p.rename(target)
        pages.append(target)
    return pages


def extract_text(manifest, force: bool = False) -> Path:
    out = manifest.dir / "paper.txt"
    if out.exists() and not force:
        return out
    subprocess.run(
        ["pdftotext", "-layout", str(manifest.path(manifest.pdf)), str(out)], check=True
    )
    return out


# --- the vision extractions ----------------------------------------------


def _renumber(claims: list[SlimClaim], page_offset: int, start: int) -> list[SlimClaim]:
    for i, c in enumerate(claims, start):
        c.claim_id = f"c{i:03d}"
        if c.location is not None and c.location.page is not None:
            c.location.page += page_offset
    return claims


def _chunk_call(manifest, tier: str, pages: list[Path], start: int):
    """One extraction over pages[start:start+CHUNK_PAGES].

    A whole paper in one call is not workable: a results page yields ~5k output
    tokens, so 30 pages would exceed any model's output limit. Pages therefore go
    in chunks, and `location.page` is corrected back to PDF numbering here.
    """
    chunk = pages[start : start + CHUNK_PAGES]
    hint = (
        f"\n\nYou are given pages {start + 1}-{start + len(chunk)} of the paper only, "
        "in order. Number `location.page` from 1 for the first image you are given."
    )
    r = llm.call(
        f"extract:{tier}:p{start + 1}",
        artifacts.load_prompt("stage0_extract") + hint,
        paper_id=manifest.paper_id,
        stage="0",
        tier=tier,
        schema=ClaimList,
        images=chunk,
        timeout_s=1800,
        log_path=paths.run_dir(manifest.paper_id, 0) / "logs" / f"extract_{tier}_{start + 1}.log",
    )
    if r.parsed is None:
        raise llm.LLMError(f"{tier} failed on pages {start + 1}-{start + len(chunk)}: {r.error}")
    return start, r.parsed, (r.ledger_id or "")


EXTRACT_PROMPT = "stage0_extract"


def extract_one(
    manifest, tier: str, pages: list[Path], out_path: Path, force: bool = False
) -> tuple[ClaimList, list[str]]:
    """One extractor's claim list, built from page chunks run concurrently."""
    prompt_version = artifacts.prompt_version(EXTRACT_PROMPT)
    if out_path.exists() and not force:
        data = json.loads(out_path.read_text())
        if data.get("prompt_version") == prompt_version:
            return ClaimList.model_validate(data["result"]), data.get("model_calls", [])

    starts = list(range(0, len(pages), CHUNK_PAGES))
    parts: dict[int, ClaimList] = {}
    calls: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, len(starts))) as pool:
        futures = [pool.submit(_chunk_call, manifest, tier, pages, s) for s in starts]
        for f in futures:
            start, part, call_id = f.result()
            parts[start] = part
            calls.append(call_id)

    merged: list[SlimClaim] = []
    notes: list[str] = []
    for start in starts:
        part = parts[start]
        merged += _renumber(part.claims, start, len(merged) + 1)
        if part.notes:
            notes.append(f"pages {start + 1}+: {part.notes}")
    result = ClaimList(claims=merged, notes=" | ".join(notes) or None)
    mode = f"chunked/{CHUNK_PAGES}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "tier": tier,
                "mode": mode,
                "model_calls": calls,
                "prompt_version": prompt_version,
                "result": result.model_dump(),
            },
            indent=2,
        )
        + "\n"
    )
    return result, calls

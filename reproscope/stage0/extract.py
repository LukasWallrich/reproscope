"""Step 1 (pages + text layer) and step 2 (the two independent vision extractions)."""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from . import leakcheck

MAX_IMAGE_BYTES = 1_500_000
DPI_LADDER = (110, 90, 72)
CHUNK_PAGES = 8
PAGE_CHECK_WINDOW = 3  # a mispaged claim is reassigned only within this many pages


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
    # Set by `verify_claim_pages` when the assigned page carries no printed form of the
    # value but exactly one nearby page does; never emitted by the model itself.
    page_corrected: dict[str, int] | None = None


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


def page_texts(manifest, n_pages: int) -> list[str]:
    """Per-page text of the PDF, 1-indexed (`page_texts(...)[0]` is unused).

    `extract_text` runs `pdftotext` without `-nopgbrk`, so the layer it writes is
    already form-feed-separated by page; that split is used when it produces one
    chunk per page. Otherwise each page is pulled individually with `pdftotext -f N
    -l N`, e.g. when a model's chunk was numbered from something other than 1.
    """
    text_path = manifest.dir / "paper.txt"
    if text_path.exists():
        chunks = text_path.read_text(errors="replace").split("\x0c")
        # A trailing form feed leaves one empty chunk after the last page.
        if chunks and not chunks[-1].strip():
            chunks = chunks[:-1]
        if len(chunks) == n_pages:
            return [""] + chunks
    out = [""]
    pdf = str(manifest.path(manifest.pdf))
    for i in range(1, n_pages + 1):
        result = subprocess.run(
            ["pdftotext", "-f", str(i), "-l", str(i), "-layout", pdf, "-"],
            capture_output=True, text=True,
        )
        out.append(result.stdout if result.returncode == 0 else "")
    return out


def verify_claim_pages(
    claims: list[SlimClaim], texts: list[str], window: int = PAGE_CHECK_WINDOW
) -> list[SlimClaim]:
    """Reassign a claim's page when its value is printed on exactly one nearby page.

    `texts` is 1-indexed per `page_texts`. A claim whose assigned page carries no
    printed form of its value (`leakcheck.variants`) but exactly one page within
    `window` does is reassigned to that page, with the correction recorded on the
    claim; a claim found on no nearby page, or on more than one, is left alone —
    there is nothing to disambiguate it with here.
    """
    n_pages = len(texts) - 1
    for c in claims:
        if c.value is None or c.location is None or c.location.page is None:
            continue
        page = c.location.page
        if not (1 <= page <= n_pages):
            continue
        forms = leakcheck.variants(c.value, c.precision)
        if not forms or any(f in texts[page] for f in forms):
            continue
        nearby = [
            p for p in range(max(1, page - window), min(n_pages, page + window) + 1)
            if p != page and any(f in texts[p] for f in forms)
        ]
        if len(nearby) == 1:
            c.page_corrected = {"from": page, "to": nearby[0]}
            c.location.page = nearby[0]
    return claims


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
        # A results-heavy chunk needs tens of thousands of reasoning tokens; a cap
        # ends the completion before any JSON appears.
        reasoning_max_tokens=None,
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
    # One extractor's chunk may have been numbered from something other than 1 (the
    # prompt asks for 1, but not every model follows it), which throws off every page
    # `_renumber` assigned from that chunk on; catch it against the PDF text layer.
    merged = verify_claim_pages(merged, page_texts(manifest, len(pages)))
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

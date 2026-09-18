"""Step 1 (pages + text layer) and step 2 (the two independent vision extractions)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .. import artifacts, config, llm, paths, provenance
from . import leakcheck

MAX_IMAGE_BYTES = 1_500_000
DPI_LADDER = (110, 90, 72)
CHUNK_PAGES = 2
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
    comparator: artifacts.Comparator | None = None
    source_quote: str | None = None
    source_region: str | None = None
    source_token_id: str | None = None
    figure_panel: str | None = None
    figure_endpoints: list[str] = []
    legend_quote: str | None = None
    quantity_role: str | None = None
    aggregation: str | None = None
    target_outcome: str | None = None
    target_contrast: str | None = None
    target_model: str | None = None
    precision: int | None = None
    uncertainty: str | None = None
    location: SlimLocation | None = None
    description: str | None = None
    analysis_label: str | None = None
    # Set by `verify_claim_pages` when the assigned page carries no printed form of the
    # value but exactly one nearby page does; never emitted by the model itself.
    page_corrected: dict[str, int] | None = None


class RegionCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int
    kind: Literal["text", "table", "figure"]
    region_id: str
    status: Literal["complete", "no_targets", "unreadable"]
    claim_ids: list[str] = []


class ClaimList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claims: list[SlimClaim] = []
    regions: list[RegionCoverage] = []
    notes: str | None = None

    @field_validator("notes", mode="before")
    @classmethod
    def empty_notes(cls, value):
        # An empty metadata list carries the same information as an absent note.
        # Do not coerce substantive claim fields or nonempty unexpected objects.
        return None if value == [] else value



class ModelClaim(SlimClaim):
    """Wire contract: internal page-correction maps cannot disable strict output."""
    page_corrected: None = None
    value: float | None = Field(...)
    comparator: artifacts.Comparator | None = Field(...)
    location: SlimLocation | None = Field(...)
    source_quote: str | None = Field(...)
    source_region: str | None = Field(...)
    source_token_id: str | None = Field(...)
    quantity_role: Literal["inferential", "descriptive", "supplied_fact", "unknown"] | None = Field(...)
    aggregation: Literal["scalar", "all", "any", "min", "max", "vector"] | None = Field(...)
    target_outcome: str | None = Field(...)
    target_contrast: str | None = Field(...)
    target_model: str | None = Field(...)


class ModelClaimList(ClaimList):
    claims: list[ModelClaim]
    regions: list[RegionCoverage] = Field(min_length=1)


def coverage_errors(part: ClaimList, n_pages: int) -> list[str]:
    errors = []
    ids = [c.claim_id for c in part.claims]
    if len(set(ids)) != len(ids):
        errors.append("duplicate claim IDs")
    pages = {r.page for r in part.regions}
    if pages != set(range(1, n_pages + 1)):
        errors.append(f"regions must cover exactly relative image pages 1..{n_pages}")
    covered = {cid for r in part.regions for cid in r.claim_ids}
    if covered != set(ids):
        errors.append("region claim_ids must cover exactly the extracted claim IDs")
    for claim in part.claims:
        if not claim.location or claim.location.page not in pages:
            errors.append(f"{claim.claim_id}: missing/invalid relative page")
        elif not any(claim.claim_id in r.claim_ids and claim.location.page == r.page for r in part.regions):
            errors.append(f"{claim.claim_id}: claim page differs from its inventory region")
    return errors


# --- pages and text -------------------------------------------------------


def page_paths(manifest) -> list[Path]:
    return sorted((manifest.dir / "pages").glob("p[0-9][0-9][0-9].png"))


def render_pages(manifest, force: bool = False) -> list[Path]:
    """corpus/<id>/pages/p001.png ... , at the highest DPI that keeps images small."""
    existing = page_paths(manifest)
    stamp = manifest.dir / "pages" / "source.json"
    wanted = {"pdf": artifacts.sha256_file(manifest.path(manifest.pdf)),
              "render": provenance.digest([DPI_LADDER, MAX_IMAGE_BYTES])}
    recorded = json.loads(stamp.read_text()) if stamp.exists() else {}
    if existing and not force and recorded.get("inputs") == wanted and recorded.get("outputs") == provenance.files({p.name: p for p in existing}):
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
    stamp.write_text(json.dumps({"inputs": wanted, "outputs": provenance.files({p.name: p for p in pages})}))
    return pages


def extract_text(manifest, force: bool = False) -> Path:
    out = manifest.dir / "paper.txt"
    stamp = manifest.dir / "paper_text_source.json"
    wanted = artifacts.sha256_file(manifest.path(manifest.pdf))
    recorded = json.loads(stamp.read_text()) if stamp.exists() else {}
    if out.exists() and not force and recorded.get("mode") == "reading-order-v1" and recorded.get("pdf") == wanted and recorded.get("text") == artifacts.sha256_file(out):
        return out
    subprocess.run(
        ["pdftotext", str(manifest.path(manifest.pdf)), str(out)], check=True
    )
    stamp.write_text(json.dumps({"pdf": wanted, "text": artifacts.sha256_file(out), "mode": "reading-order-v1"}))
    return out


def page_texts(manifest, n_pages: int) -> list[str]:
    """Per-page text of the PDF, 1-indexed (`page_texts(...)[0]` is unused).

    `extract_text` runs `pdftotext` without `-nopgbrk`, so the layer it writes is
    already form-feed-separated by page; that split is used when it produces one
    chunk per page. Otherwise each page is pulled individually with `pdftotext -f N
    -l N`, e.g. when a model's chunk was numbered from something other than 1.
    """
    if not n_pages:
        return [""]
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
            ["pdftotext", "-f", str(i), "-l", str(i), pdf, "-"],
            capture_output=True, text=True,
        )
        out.append(result.stdout if result.returncode == 0 else "")
    return out


def verify_claim_pages(
    claims: list[SlimClaim], texts: list[str], window: int = PAGE_CHECK_WINDOW
) -> list[SlimClaim]:
    """Reassign only a distinctive exact quotation found on one nearby page.

    Bare numeric coincidences cannot establish source occurrence identity.
    """
    n_pages = len(texts) - 1
    for c in claims:
        if c.value is None or c.location is None or c.location.page is None:
            continue
        page = c.location.page
        if not (1 <= page <= n_pages):
            continue
        # Numeric tokens recur across studies. Only a distinctive source quotation
        # can justify moving an occurrence to a different page.
        quote = re.sub(r"\s+", " ", c.source_quote or "").strip()
        normalised = [re.sub(r"\s+", " ", t) for t in texts]
        if len(quote) < 20 or quote in normalised[page]:
            continue
        nearby = [
            p for p in range(max(1, page - window), min(n_pages, page + window) + 1)
            if p != page and quote in normalised[p]
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


def _chunk_call(manifest, tier: str, pages: list[Path], start: int, n_pages: int | None = None, scope=None):
    """One extraction over pages[start:start+CHUNK_PAGES].

    A whole paper in one call is not workable: a results page yields ~5k output
    tokens, so 30 pages would exceed any model's output limit. Pages therefore go
    in chunks, and `location.page` is corrected back to PDF numbering here.
    """
    chunk = pages[start : start + (n_pages or CHUNK_PAGES)]
    if len(chunk)==1 and scope is None:
        text=page_texts(manifest,len(pages))[start+1]
        if _output_density(text)>100:
            return _partition_dense_page(manifest,tier,pages,start)
    # Bound output volume on dense tables before requesting hundreds of full records.
    if len(chunk)>1:
        texts=page_texts(manifest,len(pages))
        density=sum(_output_density(texts[i]) for i in range(start+1,start+len(chunk)+1))
        if density>100:return _split_chunk(manifest,tier,pages,start,len(chunk))
    hint = (
        f"\n\nYou are given pages {start + 1}-{start + len(chunk)} of the paper only, "
        "in order. Number `location.page` from 1 for the first image you are given."
    )
    if tier == "vision_a":
        texts = page_texts(manifest, len(pages))
        hint += "\n\nText-layer evidence (check ambiguous layout against images):\n" + "\n".join(
            f"IMAGE PAGE {i-start}:\n{texts[i]}" for i in range(start+1, start+len(chunk)+1))
    from ..source_layout import build as build_layout, prompt_page
    layout = build_layout(manifest.path(manifest.pdf))
    hint += "\n\nPhysical native-PDF candidate locations (both readers must still inspect every image; this list includes non-results and may omit image-only quantities):\n"
    hint += "\n".join(f"IMAGE PAGE {p['page']-start} (PDF page {p['page']}):\n" + prompt_page(p)
                       for p in layout['pages'][start:start+len(chunk)])
    suffix=''
    if scope is not None:
        suffix=f':part{scope["part"]}'
        hint += '\n\nDENSE-PAGE PARTITION: this request covers only the source occurrences specified below. '
        hint += 'Read the full page image for row/column headers and meaning, but restrict output to this partition. '
        if scope['image_only']:
            hint += ('Extract only empirical quantities or figure annotations missing from ALL supplied physical candidate IDs. '
                     'Set source_token_id=null for these image-only occurrences. Do not repeat a quantity represented in the candidate list. ')
        else:
            hint += ('Extract every in-scope result whose source_token_id is in this exact allow-list: '
                     +json.dumps(scope['ids'])+'. Do not output other IDs or null IDs. '
                     'Design constants and cited results remain excluded. ')
        hint += ('Inventory the regions inspected for this partition, with only its claim IDs. '
                 'An empty claims list is valid if this partition contains no eligible results. '
                 'Use claims, regions and notes as direct JSON object keys, never a string under a parameter key.')
    r = llm.call(
        f"extract:{tier}:p{start + 1}{suffix}",
        artifacts.load_prompt("stage0_extract") + hint,
        paper_id=manifest.paper_id,
        stage="0",
        tier=tier,
        schema=ModelClaimList,
        images=chunk,
        timeout_s=1800,
        log_path=paths.run_dir(manifest.paper_id, 0) / "logs" / f"extract_{tier}_{start + 1}{suffix.replace(':','_')}.log",
    )
    if r.parsed is None:
        if len(chunk)>1 and 'timeout' in str(r.error).lower():
            return _split_chunk(manifest,tier,pages,start,len(chunk))
        raise llm.LLMError(f"{tier} failed on pages {start + 1}-{start + len(chunk)}: {r.error}")
    problems = coverage_errors(r.parsed, len(chunk)) + _scope_errors(r.parsed,scope)
    if scope is None and not r.parsed.claims and _prints_results(manifest, start, len(chunk)):
        problems.append("no claims returned from pages containing reported statistics")
    if problems:
        # A model can answer with notes and an empty list while the pages print results
        # (seen from glm-5.3-flash: notes naming claims it never emitted). One corrected
        # reply is asked for; a second empty list fails the chunk.
        r = llm.call(
            f"extract:{tier}:p{start + 1}{suffix}:retry",
            artifacts.load_prompt("stage0_extract") + hint
            + "\n\nThe extraction coverage contract failed: " + "; ".join(problems)
            + ". Return every reported quantity"
            + (" within the assigned source partition ONLY" if scope is not None else "")
            + " with source evidence and a complete region inventory. "
              "Use relative image page numbers. Do not place quantities only in notes.",
            paper_id=manifest.paper_id, stage="0", tier=tier, schema=ModelClaimList, images=chunk,
            timeout_s=1800,
            log_path=paths.run_dir(manifest.paper_id, 0) / "logs" / f"extract_{tier}_{start + 1}{suffix.replace(':','_')}_retry.log",
        )
        if r.parsed is None:
            raise llm.LLMError(f"{tier}: failed extraction coverage repair: {r.error}")
        problems = coverage_errors(r.parsed, len(chunk)) + _scope_errors(r.parsed,scope)
        if scope is None and not r.parsed.claims and _prints_results(manifest, start, len(chunk)):
            problems.append("no claims from result-bearing pages")
        if problems:
            raise llm.LLMError(f"{tier}: extraction coverage unresolved: " + "; ".join(problems))
    return start, ClaimList.model_validate(r.parsed.model_dump()), (r.ledger_id or "")


def _scope_errors(part,scope):
    if scope is None:return []
    allowed=set(scope['ids'])
    wrong=[c.claim_id for c in part.claims if (c.source_token_id is not None if scope['image_only'] else c.source_token_id not in allowed)]
    return ['claims outside the assigned source partition: '+', '.join(wrong)] if wrong else []


def _dense_scopes(page,limit=24):
    candidates=list({c['source_token_id']:c for c in page['numeric_candidates']+page.get('marker_candidates',[])}.values())
    # PDF text order can enumerate a whole column before its neighbouring column.
    # Keep count/percentage and coefficient/uncertainty cells on a visual row
    # together so the model does not complete a row outside its assigned scope.
    rows={}
    for i,c in enumerate(candidates):
        box=c.get('bbox');key=(0,round((box[1]+box[3])/2,1)) if box else (1,i)
        rows.setdefault(key,[]).append(c)
    batches=[];batch=[]
    for key,row in sorted(rows.items()):
        ids=[c['source_token_id'] for c in sorted(row,key=lambda c:(c.get('bbox') or [0])[0])]
        if batch and len(batch)+len(ids)>limit:batches.append(batch);batch=[]
        while len(ids)>limit:batches.append(ids[:limit]);ids=ids[limit:]
        batch.extend(ids)
    if batch:batches.append(batch)
    scopes=[{'part':i+1,'ids':ids,'image_only':False} for i,ids in enumerate(batches)]
    scopes.append({'part':len(scopes)+1,'ids':[],'image_only':True})
    return scopes


def _partition_dense_page(manifest,tier,pages,start):
    """Bound output volume without cropping away table headers or image-only results."""
    from .. import source_layout
    page=source_layout.build(manifest.path(manifest.pdf))['pages'][start]
    scopes=_dense_scopes(page)
    folder=paths.run_dir(manifest.paper_id,0)/'extract_chunks'/tier/f'p{start+1}_parts'
    folder.mkdir(parents=True,exist_ok=True)
    def one(scope):
        inputs={'scope':scope,'page':artifacts.sha256_file(pages[start]),
                'model':config.tier(tier).model_dump(),'prompt':artifacts.prompt_version(EXTRACT_PROMPT),
                'implementation':provenance.implementation('stage0/extract.py','source_layout.py')}
        dest=folder/(provenance.digest(inputs)+'.json')
        if dest.exists():
            saved=json.loads(dest.read_text());return ClaimList.model_validate(saved['result']),saved['ledger_id']
        _,part,cid=_chunk_call(manifest,tier,pages,start,1,scope)
        dest.write_text(json.dumps({'inputs':inputs,'result':part.model_dump(),'ledger_id':cid},indent=2))
        return part,cid
    with ThreadPoolExecutor(max_workers=3) as pool:parts=list(pool.map(one,scopes))
    claims=[];regions=[];calls=[]
    for scope,(part,cid) in zip(scopes,parts):
        old=[c.claim_id for c in part.claims];renamed=_renumber(part.claims,0,len(claims)+1)
        mapping=dict(zip(old,[c.claim_id for c in renamed]));claims.extend(renamed)
        regions.extend(r.model_copy(update={'region_id':f'part{scope["part"]}:{r.region_id}',
                                            'claim_ids':[mapping[c] for c in r.claim_ids]}) for r in part.regions)
        calls.append(cid)
    result=ClaimList(claims=claims,regions=regions,notes='Full-page visual context; exhaustive physical-source partitions plus an image-only pass. '+ ' | '.join(p.notes for p,_ in parts if p.notes))
    errors=coverage_errors(result,1)
    if errors:raise ValueError('dense-page partition merge: '+'; '.join(errors))
    return start,result,calls


def _output_density(text):
    # Correlation matrices commonly omit the leading zero; those cells still
    # require full extraction records and must count towards the output budget.
    return len(re.findall(r'(?<![\w.])[-−]?(?:\d+\.\d+|\.\d+)',text))


def _split_chunk(manifest,tier,pages,start,length):
    """Keep absolute source positions while using smaller independent image calls."""
    parts=[];calls=[];claims=[];regions=[];notes=[]
    with ThreadPoolExecutor(max_workers=min(2,length)) as pool:
        jobs=[pool.submit(_chunk_call,manifest,tier,pages,start+i,1) for i in range(length)]
        parts=[job.result() for job in jobs]
    for absolute,part,cid in parts:
        old=[c.claim_id for c in part.claims]
        renamed=_renumber(part.claims,absolute-start,len(claims)+1)
        mapping=dict(zip(old,[c.claim_id for c in renamed]))
        regions += [r.model_copy(update={'page':r.page+absolute-start,'claim_ids':[mapping[c] for c in r.claim_ids]}) for r in part.regions]
        claims+=renamed;calls.extend(cid if isinstance(cid,list) else [cid])
        if part.notes:notes.append(part.notes)
    merged=ClaimList(claims=claims,regions=regions,notes=' | '.join(notes))
    errors=coverage_errors(merged,length)
    if errors:raise ValueError('split extraction coverage: '+'; '.join(errors))
    return start,merged,calls


# This exact prior implementation differs only in call partitioning/lifecycle.
# Its completed source records remain valid. Remove this migration if source or
# wire semantics change; other hashes, models, PDF pages and prompts must match.
PARTITION_COMPATIBLE_IMPLEMENTATIONS={'64a449af277b92f6c0afd8fd414ec483d29b52e50d32c4a3d11b5b23a0040e9b','b659d1d84481b8ed6c8b9d04914f045777dc4b08fcbccbc38b196eea521fac5f','d44ec5559e20c6b79e3bff33f8839222bb1936ff6939eaa9e4912abd76557221'}
def _compatible_inputs(recorded, wanted):
    if recorded==wanted:return True
    return bool(recorded and recorded.get('implementation') in PARTITION_COMPATIBLE_IMPLEMENTATIONS
                and {k:v for k,v in recorded.items() if k!='implementation'}=={k:v for k,v in wanted.items() if k!='implementation'})


_NUMBER = re.compile(r"(?<![\w.])\d+\.\d+|(?<![\w.])[<>=]\s*\.\d+")
RESULT_NUMBERS_MIN = 20


def _prints_results(manifest, start: int, n: int) -> bool:
    """Whether pages start+1..start+n carry enough decimal numbers to be results pages
    after excluding URL and DOI identifiers, which are not reported quantities."""
    texts = page_texts(manifest, len(page_paths(manifest)))
    body = " ".join(texts[start + 1 : start + n + 1])
    body = re.sub(r"(?:https?://|www\.)\S+|\b10\.\d{4,9}/\S+", "", body, flags=re.I)
    return len(_NUMBER.findall(body)) >= RESULT_NUMBERS_MIN


EXTRACT_PROMPT = "stage0_extract"


def _cached_chunk(manifest, tier, pages, start, cache_dir, dependencies, prompt_version, force):
    """Persist each completed call before another chunk can fail the extraction."""
    chunk = pages[start:start + CHUNK_PAGES]
    inputs = {**dependencies, "pages": provenance.files({p.name: p for p in chunk}),
              "prompt": prompt_version, "start": start}
    cache = cache_dir / f"p{start + 1}.json"
    if cache.exists() and not force:
        record = json.loads(cache.read_text())
        if _compatible_inputs(record.get("inputs"), inputs):
            return start, ClaimList.model_validate(record["result"]), record["ledger_id"]
    if force:
        for page_index in range(start,start+len(chunk)):
            shutil.rmtree(cache_dir/f'p{page_index+1}_parts',ignore_errors=True)
    offset, part, call_id = _chunk_call(manifest, tier, pages, start)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".tmp")
    temporary.write_text(json.dumps({"inputs": inputs, "result": part.model_dump(), "ledger_id": call_id}, indent=2))
    temporary.replace(cache)
    return offset, part, call_id


def extract_one(
    manifest, tier: str, pages: list[Path], out_path: Path, force: bool = False
) -> tuple[ClaimList, list[str]]:
    """One extractor's claim list, built from page chunks run concurrently."""
    prompt_version = artifacts.prompt_version(EXTRACT_PROMPT)
    dependencies = {"pdf": artifacts.sha256_file(manifest.path(manifest.pdf)),
                    "pages": provenance.files({p.name: p for p in pages}),
                    "model": config.tier(tier).model_dump(exclude={"generation_mode"}),
                    "implementation": provenance.implementation("stage0/extract.py", "source_layout.py") }
    if out_path.exists() and not force:
        data = json.loads(out_path.read_text())
        if data.get("prompt_version") == prompt_version and _compatible_inputs(data.get("inputs"), dependencies):
            return ClaimList.model_validate(data["result"]), data.get("model_calls", [])

    starts = list(range(0, len(pages), CHUNK_PAGES))
    parts: dict[int, ClaimList] = {}
    calls: list[str] = []
    with ThreadPoolExecutor(max_workers=min(4, len(starts))) as pool:
        futures = [pool.submit(_cached_chunk, manifest, tier, pages, s,
                               out_path.parent / "extract_chunks" / tier, dependencies, prompt_version, force)
                   for s in starts]
        for f in as_completed(futures):
            start, part, call_id = f.result()
            parts[start] = part
            calls.extend(call_id if isinstance(call_id,list) else [call_id])

    merged: list[SlimClaim] = []
    notes: list[str] = []
    regions = []
    for start in starts:
        part = parts[start]
        old_ids = [c.claim_id for c in part.claims]
        renumbered = _renumber(part.claims, start, len(merged) + 1)
        mapping = dict(zip(old_ids, [c.claim_id for c in renumbered]))
        for region in part.regions:
            if not set(region.claim_ids) <= mapping.keys():
                raise ValueError("region inventory names unknown claim IDs")
            regions.append(region.model_copy(update={"page": region.page+start,
                "claim_ids": [mapping[cid] for cid in region.claim_ids]}))
        merged += renumbered
        if part.notes:
            notes.append(f"pages {start + 1}+: {part.notes}")
    # One extractor's chunk may have been numbered from something other than 1 (the
    # prompt asks for 1, but not every model follows it), which throws off every page
    # `_renumber` assigned from that chunk on; catch it against the PDF text layer.
    merged = verify_claim_pages(merged, page_texts(manifest, len(pages)))
    result = ClaimList(claims=merged, regions=regions, notes=" | ".join(notes) or None)
    mode = f"chunked/{CHUNK_PAGES}"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "tier": tier,
                "mode": mode,
                "model_calls": calls,
                "prompt_version": prompt_version,
                "inputs": dependencies,
                "result": result.model_dump(),
            },
            indent=2,
        )
        + "\n"
    )
    return result, calls

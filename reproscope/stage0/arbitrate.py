"""Step 3: the two extractions become stage0/claims.json.

Entries both extractors report the same way are merged deterministically and never
reach a model. What is left — one extractor's entry the other lacks, or the same
location with two different values — goes to the cheap vision tier in batches, each
item shown as a crop of the page region around the printed value. Items the cheap
tier cannot settle escalate to one strong-tier call when they are headline claims;
supporting claims keep the first extractor's reading at low confidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from .extract import ClaimList, SlimClaim, SlimLocation

PROMPTS = ("stage0_arbitrate", "stage0_arbitrate_strong")

ALLOWED_KINDS = set(get_args(artifacts.QuantityKind))
# The extraction prompt offers finer kinds than the artifact enum carries; the
# original wording is kept in `quantity_kind_raw`.
KIND_MAP = {
    "ci_lower": "ci_bound",
    "ci_upper": "ci_bound",
    "beta": "coefficient",
    "b": "coefficient",
    "M": "mean",
    "SD": "sd",
}
ALLOWED_TYPES = {"scalar", "range", "table_cell", "qualitative", "figure"}

LABEL_SIM = 0.8  # difflib ratio over normalised location labels
DESCRIPTION_SIM = 0.5  # a looser floor: two extractors paraphrase the same sentence
BATCH_SIZE = 20  # items per cheap-tier call
BATCH_WORKERS = 4
CROP_DPI = 110
CROP_MARGIN = 0.12  # fraction of page height added above and below the value
CROP_MAX_FRACTION = 0.6  # a taller region is not a crop; send the whole page


# --- model schemas --------------------------------------------------------


class ArbitrationItem(BaseModel):
    """One decision. Strict-compatible: flat, no open maps."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    decision: Literal["keep", "drop", "correct"]
    value: float | None = None
    uncertain: bool = False
    note: str | None = None


class ArbitrationBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ArbitrationItem] = []


# --- deterministic pairing ------------------------------------------------


def normalise(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def label_similarity(a: str | None, b: str | None) -> float:
    """1.0 when either label is empty, else the difflib ratio of the normalised labels."""
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def labels_match(a: str | None, b: str | None) -> bool:
    """Same place in the paper: similar wording and the same numbering.

    Table 4 and Table 5, or row 1 and row 2, read as similar text but are different
    locations, so any digits in the two labels have to be identical.
    """
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return True
    if re.findall(r"\d+", a or "") != re.findall(r"\d+", b or ""):
        return False
    return SequenceMatcher(None, na, nb).ratio() >= LABEL_SIM


def canonical_kind(claim: SlimClaim) -> str:
    raw = (claim.quantity_kind or "other").strip()
    return raw if raw in ALLOWED_KINDS else KIND_MAP.get(raw, "other")


def values_agree(a: SlimClaim, b: SlimClaim) -> bool:
    """Both values, rounded to the coarser of the two reported precisions, are equal."""
    if a.value is None or b.value is None:
        return False
    precisions = [p for p in (a.precision, b.precision) if p is not None]
    decimals = min(precisions) if precisions else 3
    decimals = max(0, min(int(decimals), 6))
    return round(float(a.value), decimals) == round(float(b.value), decimals)


def _location(claim: SlimClaim) -> SlimLocation:
    return claim.location or SlimLocation()


def _candidate(a: SlimClaim, b: SlimClaim, require_value: bool) -> float | None:
    """Pair score for a and b, or None when they cannot be the same claim."""
    la, lb = _location(a), _location(b)
    if la.page != lb.page:
        return None
    if canonical_kind(a) != canonical_kind(b):
        return None
    if require_value and not values_agree(a, b):
        return None
    if not labels_match(la.label, lb.label) or not labels_match(la.cell, lb.cell):
        return None
    if not require_value and not (normalise(la.cell) and normalise(lb.cell)):
        # Without two table cells to compare, only the wording separates two claims
        # printed on the same page, so a value conflict needs a similar description.
        if label_similarity(a.description, b.description) < DESCRIPTION_SIM:
            return None
    return (
        label_similarity(la.label, lb.label)
        + label_similarity(la.cell, lb.cell)
        + label_similarity(a.description, b.description)
    )


def _pair_pass(
    rows_a: list[SlimClaim], rows_b: list[SlimClaim], require_value: bool
) -> tuple[list[tuple[SlimClaim, SlimClaim]], list[SlimClaim], list[SlimClaim]]:
    """Greedy best-score pairing of A against B, each B entry used at most once."""
    taken: set[int] = set()
    pairs: list[tuple[SlimClaim, SlimClaim]] = []
    left_a: list[SlimClaim] = []
    for a in rows_a:
        best_j, best_score = None, 0.0
        for j, b in enumerate(rows_b):
            if j in taken:
                continue
            score = _candidate(a, b, require_value)
            if score is not None and score > best_score:
                best_j, best_score = j, score
        if best_j is None:
            left_a.append(a)
        else:
            taken.add(best_j)
            pairs.append((a, rows_b[best_j]))
    left_b = [b for j, b in enumerate(rows_b) if j not in taken]
    return pairs, left_a, left_b


def _first(*values: Any) -> Any:
    for v in values:
        if v not in (None, "", []):
            return v
    return None


def merge_claim(a: SlimClaim, b: SlimClaim | None) -> SlimClaim:
    """A's reading, with every gap filled from B. Headline wins over supporting."""
    if b is None:
        return a.model_copy(deep=True)
    la, lb = _location(a), _location(b)
    importance = (
        "headline" if "headline" in {a.importance, b.importance} else _first(a.importance, b.importance)
    )
    return SlimClaim(
        claim_id=a.claim_id,
        study_id=_first(a.study_id, b.study_id),
        claim_type=_first(a.claim_type, b.claim_type),
        importance=importance,
        quantity_kind=_first(a.quantity_kind, b.quantity_kind),
        value=_first(a.value, b.value),
        comparator=_first(a.comparator, b.comparator),
        precision=a.precision if a.precision is not None else b.precision,
        uncertainty=_first(a.uncertainty, b.uncertainty),
        location=SlimLocation(
            page=_first(la.page, lb.page),
            kind=_first(la.kind, lb.kind),
            label=_first(la.label, lb.label),
            cell=_first(la.cell, lb.cell),
        ),
        description=_first(a.description, b.description),
        analysis_label=_first(a.analysis_label, b.analysis_label),
    )


class Resolution:
    """One claim on its way into claims.json, with how it got there."""

    def __init__(self, claim: SlimClaim, source: str, rival: SlimClaim | None = None):
        self.claim = claim
        self.source = source  # "agreed" | "A" | "B" | "conflict"
        self.rival = rival  # the competing value for a conflict
        self.agreed = source == "agreed"
        self.note: str | None = None
        self.confidence: str | None = "high" if source == "agreed" else None
        self.dropped = False
        self.unresolved = source != "agreed"


def partition(list_a: ClaimList, list_b: ClaimList) -> list[Resolution]:
    """Agreements, value conflicts and singletons, in that order of confidence."""
    agreed, left_a, left_b = _pair_pass(list(list_a.claims), list(list_b.claims), require_value=True)
    conflicts, only_a, only_b = _pair_pass(left_a, left_b, require_value=False)

    out = [Resolution(merge_claim(a, b), "agreed") for a, b in agreed]
    out += [Resolution(merge_claim(a, b), "conflict", rival=b) for a, b in conflicts]
    out += [Resolution(merge_claim(a, None), "A") for a in only_a]
    out += [Resolution(merge_claim(b, None), "B") for b in only_b]
    return out


# --- page crops -----------------------------------------------------------

_WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>'
)
_PAGE = re.compile(r'<page width="([\d.]+)" height="([\d.]+)"')
_words_cache: dict[tuple[str, int], tuple[float, float, list[tuple[float, float, float, str]]]] = {}


def page_words(pdf: Path, page: int):
    """(width, height, [(yMin, yMax, xMax, text)]) for one page of the text layer."""
    key = (str(pdf), page)
    if key not in _words_cache:
        html = subprocess.run(
            ["pdftotext", "-bbox-layout", "-f", str(page), "-l", str(page), str(pdf), "-"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        size = _PAGE.search(html)
        width, height = (float(size.group(1)), float(size.group(2))) if size else (0.0, 0.0)
        words = [
            (float(m.group(2)), float(m.group(4)), float(m.group(3)), m.group(5))
            for m in _WORD.finditer(html)
        ]
        _words_cache[key] = (width, height, words)
    return _words_cache[key]


def value_forms(value: float | None, precision: int | None) -> list[str]:
    """The printed spellings of a value: as reported, without the leading zero, grouped."""
    if value is None:
        return []
    decimals = 0 if precision is None else max(0, min(int(precision), 6))
    text = f"{abs(float(value)):.{decimals}f}"
    forms = [text]
    if text.startswith("0."):
        forms.append(text[1:])
    grouped = f"{abs(float(value)):,.{decimals}f}"
    if grouped != text:
        forms.append(grouped)
    if precision is None:
        trimmed = f"{abs(float(value)):g}"
        if trimmed not in forms:
            forms.append(trimmed)
    return forms


def _outside(char: str, digits: str) -> bool:
    """A boundary character: the edge of the word, or something other than `digits`."""
    return char == "" or char not in digits


def _word_holds(word: str, form: str) -> bool:
    """The form appears in the word and is not part of a longer number."""
    start = 0
    while (i := word.find(form, start)) >= 0:
        before = word[i - 1] if i else ""
        after = word[i + len(form) :][:1]
        if _outside(before, "0123456789.") and _outside(after, "0123456789"):
            return True
        start = i + 1
    return False


def value_band(pdf: Path, page: int | None, value: float | None, precision: int | None):
    """(top, bottom) in points around every printing of the value on the page.

    None when the value cannot be located: no text layer, no matching word, a band
    covering most of the page, or a poppler error. The caller then sends the page.
    """
    forms = value_forms(value, precision)
    if not forms or not page:
        return None
    try:
        _width, height, words = page_words(pdf, page)
    except Exception:  # noqa: BLE001 - a crop is an optimisation, never a failure
        return None
    if not words or height <= 0:
        return None
    hits = [(y0, y1) for y0, y1, _x, text in words if any(_word_holds(text, f) for f in forms)]
    if not hits:
        return None
    top = max(0.0, min(y0 for y0, _ in hits) - CROP_MARGIN * height)
    bottom = min(height, max(y1 for _, y1 in hits) + CROP_MARGIN * height)
    if (bottom - top) / height > CROP_MAX_FRACTION:
        return None
    return top, bottom


def render_crop(pdf: Path, page: int, top: float, bottom: float, out_dir: Path) -> Path | None:
    """Render one full-width page band to a PNG, reusing the file if it is already there."""
    try:
        width, _height, _words = page_words(pdf, page)
        scale = CROP_DPI / 72.0
        token = hashlib.sha256(f"{page}:{top:.1f}:{bottom:.1f}".encode()).hexdigest()[:10]
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"p{page:03d}_{token}.png"
        if target.exists():
            return target
        prefix = out_dir / f"tmp_{token}"
        subprocess.run(
            [
                "pdftoppm", "-r", str(CROP_DPI), "-f", str(page), "-l", str(page),
                "-x", "0", "-y", str(int(top * scale)),
                "-W", str(int(width * scale)), "-H", str(int((bottom - top) * scale)),
                "-png", str(pdf), str(prefix),
            ],
            check=True,
            capture_output=True,
        )
        made = sorted(out_dir.glob(f"tmp_{token}-*.png"))
        if not made:
            return None
        made[0].rename(target)
        for extra in made[1:]:
            extra.unlink()
        return target
    except Exception:  # noqa: BLE001 - a crop is an optimisation, never a failure
        return None


def crop_page(
    pdf: Path, page: int, value: float | None, precision: int | None, out_dir: Path
) -> Path | None:
    """The page band around the printed value as a PNG, or None to fall back to the page."""
    band = value_band(pdf, page, value, precision)
    return render_crop(pdf, page, band[0], band[1], out_dir) if band else None


def merge_bands(bands: list[tuple[float, float]], limit: float) -> list[tuple[float, float]]:
    """Overlapping bands become one, so items on the same lines share one crop.

    A merge that would grow the band past `limit` points is not made.
    """
    merged: list[tuple[float, float]] = []
    for top, bottom in sorted(bands):
        if merged and top <= merged[-1][1] and max(bottom, merged[-1][1]) - merged[-1][0] <= limit:
            merged[-1] = (merged[-1][0], max(bottom, merged[-1][1]))
        else:
            merged.append((top, bottom))
    return merged


# --- the model passes -----------------------------------------------------


def _item_payload(item_id: str, res: Resolution, image: int) -> dict[str, Any]:
    c = res.claim
    loc = _location(c)
    payload: dict[str, Any] = {
        "item_id": item_id,
        "reported_by": {"A": "extractor A only", "B": "extractor B only"}.get(
            res.source, "both extractors, with different values"
        ),
        "page": loc.page,
        "quantity_kind": c.quantity_kind,
        "value": c.value,
        "location": {"kind": loc.kind, "label": loc.label, "cell": loc.cell},
        "description": c.description,
        "importance": c.importance,
        "image": image,
    }
    if res.rival is not None:
        payload["value"] = None
        payload["candidate_values"] = [c.value, res.rival.value]
        payload["candidate_descriptions"] = [c.description, res.rival.description]
    return payload


def _batches(items: list[tuple[str, Resolution]], size: int) -> list[list[tuple[str, Resolution]]]:
    """Page-ordered chunks: one call covers a few neighbouring pages at most."""
    ordered = sorted(items, key=lambda kv: (_location(kv[1].claim).page or 10**6, kv[0]))
    return [ordered[i : i + size] for i in range(0, len(ordered), size)]


def _images_for(
    batch: list[tuple[str, Resolution]], pdf: Path, pages: list[Path], crop_dir: Path
) -> tuple[list[Path], dict[str, int]]:
    """One image per item — its crop when the value can be located, else its page.

    Items whose bands overlap share one crop, so a batch sends a handful of images
    rather than one per item.
    """
    bands: dict[str, tuple[float, float]] = {}
    per_page: dict[int, list[tuple[float, float]]] = {}
    for item_id, res in batch:
        page = _location(res.claim).page
        band = value_band(pdf, page, res.claim.value, res.claim.precision)
        if band is not None and page:
            bands[item_id] = band
            per_page.setdefault(page, []).append(band)
    merged = {
        page: merge_bands(found, CROP_MAX_FRACTION * page_words(pdf, page)[1])
        for page, found in per_page.items()
    }

    images: list[Path] = []
    index: dict[Path, int] = {}
    per_item: dict[str, int] = {}
    for item_id, res in batch:
        page = _location(res.claim).page
        img = None
        if item_id in bands and page:
            top, bottom = bands[item_id]
            band = next((b for b in merged[page] if b[0] <= top and b[1] >= bottom), (top, bottom))
            img = render_crop(pdf, page, band[0], band[1], crop_dir)
        if img is None and page and 1 <= page <= len(pages):
            img = pages[page - 1]
        if img is None:
            per_item[item_id] = 0
            continue
        if img not in index:
            images.append(img)
            index[img] = len(images)
        per_item[item_id] = index[img]
    return images, per_item


def _call_batch(
    manifest,
    prompt_name: str,
    tier: str,
    step: str,
    batch: list[tuple[str, Resolution]],
    images: list[Path],
    per_item: dict[str, int],
    log_path: Path,
) -> tuple[dict[str, ArbitrationItem], str]:
    payload = [_item_payload(i, res, per_item.get(i, 0)) for i, res in batch]
    listing = "\n".join(f"- image {n}: {p.name}" for n, p in enumerate(images, 1)) or "none"
    prompt = artifacts.load_prompt(
        prompt_name, items=json.dumps(payload, indent=1), images=listing
    )
    r = llm.call(
        step,
        prompt,
        paper_id=manifest.paper_id,
        stage="0",
        tier=tier,
        schema=ArbitrationBatch,
        images=images,
        agentic=False,
        cwd=paths.ROOT,
        timeout_s=1200,
        log_path=log_path,
    )
    decisions = {d.item_id: d for d in r.parsed.items} if r.parsed is not None else {}
    return decisions, (r.ledger_id or "")


def apply_decision(res: Resolution, decision: ArbitrationItem | None) -> None:
    """Fold one model answer into the resolution; a missing answer leaves it unresolved."""
    if decision is None or decision.uncertain:
        reason = decision.note if decision and decision.note else None
        res.note = f"unresolved: {reason}" if reason else "unresolved"
        res.confidence = "low"
        return
    res.unresolved = False
    res.note = decision.note
    res.confidence = "medium"
    if decision.decision == "drop":
        res.dropped = True
    elif decision.decision == "correct":
        if decision.value is None:
            res.unresolved = True
            res.confidence = "low"
            res.note = decision.note or "no value returned"
        else:
            res.claim.value = decision.value


# --- records and output ---------------------------------------------------


def _sort_key(res: Resolution) -> tuple:
    loc = _location(res.claim)
    return (
        loc.page if loc.page is not None else 10**6,
        normalise(loc.label),
        normalise(loc.cell),
        canonical_kind(res.claim),
        res.claim.value if res.claim.value is not None else 0.0,
        normalise(res.claim.description),
    )


def to_records(
    resolutions: list[Resolution], tier_a: str, tier_b: str, meta: artifacts.ArtifactMeta
) -> list[artifacts.ClaimRecord]:
    """Kept resolutions as ClaimRecords, renumbered c001... in page then label order."""
    records: list[artifacts.ClaimRecord] = []
    for n, res in enumerate(sorted([r for r in resolutions if not r.dropped], key=_sort_key), 1):
        c = res.claim
        raw_kind = (c.quantity_kind or "other").strip()
        payload: dict[str, Any] = {
            "meta": meta.model_dump(),
            "claim_id": f"c{n:03d}",
            "study_id": c.study_id,
            "claim_type": c.claim_type if c.claim_type in ALLOWED_TYPES else None,
            "importance": c.importance if c.importance in {"headline", "supporting"} else "supporting",
            "quantity_kind": canonical_kind(c),
            "quantity_kind_raw": raw_kind,
            "value": c.value,
            "comparator": c.comparator,
            "precision": c.precision,
            "uncertainty": {"reported": c.uncertainty} if c.uncertainty else None,
            "location": c.location.model_dump() if c.location else None,
            "description": c.description,
            "analysis_label": c.analysis_label,
            "confidence": res.confidence,
            "extraction": {
                "model_a": tier_a,
                "model_b": tier_b,
                "agreed": res.agreed,
                "arbiter_note": res.note,
            },
        }
        records.append(artifacts.ClaimRecord.model_validate(payload))
    return records


def run(
    manifest,
    list_a: ClaimList,
    list_b: ClaimList,
    pages: list[Path],
    inputs: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[list[artifacts.ClaimRecord], list[str]]:
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "claims.json"
    if out_path.exists() and not force:
        existing = artifacts.load(artifacts.ClaimRecord, out_path)
        existing = existing if isinstance(existing, list) else [existing]
        if existing and not artifacts.prompt_stale(existing[0], PROMPTS):
            return existing, []

    resolutions = partition(list_a, list_b)
    disputed = [
        (f"i{n:03d}", res) for n, res in enumerate((r for r in resolutions if r.unresolved), 1)
    ]
    pdf = manifest.path(manifest.pdf)
    crop_dir = stage_dir / "crops"
    calls: list[str] = []

    batches = _batches(disputed, BATCH_SIZE)
    prepared = [(b, *_images_for(b, pdf, pages, crop_dir)) for b in batches]
    with ThreadPoolExecutor(max_workers=min(BATCH_WORKERS, max(1, len(prepared)))) as pool:
        futures = [
            pool.submit(
                _call_batch,
                manifest,
                "stage0_arbitrate",
                "vision_a",
                f"arbitrate:batch{k + 1}",
                batch,
                images,
                per_item,
                stage_dir / "logs" / f"arbitrate_batch{k + 1}.log",
            )
            for k, (batch, images, per_item) in enumerate(prepared)
        ]
        answers: dict[str, ArbitrationItem] = {}
        for f in futures:
            decisions, call_id = f.result()
            answers.update(decisions)
            calls.append(call_id)

    for item_id, res in disputed:
        apply_decision(res, answers.get(item_id))

    # Headline claims the cheap tier left open get one strong-tier call.
    escalated = [
        (item_id, res)
        for item_id, res in disputed
        if res.unresolved and res.claim.importance == "headline"
    ]
    if escalated:
        page_numbers = [
            p
            for p in sorted({_location(r.claim).page for _, r in escalated if _location(r.claim).page})
            if 1 <= p <= len(pages)
        ]
        imgs = [pages[p - 1] for p in page_numbers]
        per_item = {
            item_id: page_numbers.index(_location(res.claim).page) + 1
            if _location(res.claim).page in page_numbers
            else 0
            for item_id, res in escalated
        }
        decisions, call_id = _call_batch(
            manifest,
            "stage0_arbitrate_strong",
            "strong",
            "arbitrate:strong",
            escalated,
            imgs,
            per_item,
            stage_dir / "logs" / "arbitrate_strong.log",
        )
        calls.append(call_id)
        for item_id, res in escalated:
            apply_decision(res, decisions.get(item_id))

    meta = artifacts.ArtifactMeta(
        artifact="ClaimRecord",
        stage="0",
        inputs=inputs or {},
        prompt_versions={
            "stage0_extract": artifacts.prompt_version("stage0_extract"),
            **{name: artifacts.prompt_version(name) for name in PROMPTS},
        },
        model_calls=calls,
    )
    records = to_records(resolutions, "vision_a", "vision_b", meta)
    artifacts.save(records, out_path)
    (stage_dir / "arbitration.json").write_text(
        json.dumps(
            {
                "n_a": len(list_a.claims),
                "n_b": len(list_b.claims),
                "n_agreed": sum(1 for r in resolutions if r.agreed),
                "n_conflict": sum(1 for r in resolutions if r.source == "conflict"),
                "n_singleton": sum(1 for r in resolutions if r.source in {"A", "B"}),
                "n_batches": len(batches),
                "n_escalated": len(escalated),
                "n_unresolved": sum(1 for r in resolutions if r.unresolved and not r.dropped),
                "n_claims": len(records),
                "dropped": [
                    {
                        "source": r.source,
                        "page": _location(r.claim).page,
                        "value": r.claim.value,
                        "description": r.claim.description,
                        "reason": r.note,
                    }
                    for r in resolutions
                    if r.dropped
                ],
                "model_calls": calls,
            },
            indent=2,
        )
        + "\n"
    )
    return records, calls

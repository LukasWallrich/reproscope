"""Reconcile independent source readings with explicit unresolved states.

Identity matching precedes comparison of statistical fields. Complete arbitration
responses can correct any source field; unresolved readings remain ineligible.
Source anchoring and duplicate checks run before claims are written.
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

from pydantic import BaseModel, ConfigDict, field_validator

from .. import artifacts, llm, paths, config, response_cache
from .extract import ClaimList, ModelClaim, SlimClaim, SlimLocation
from . import extract

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
    corrected_claim: ModelClaim | None = None
    uncertain: bool = False
    note: str | None = None


    @field_validator("corrected_claim", mode="before")
    @classmethod
    def source_candidate(cls, value):
        if isinstance(value, SlimClaim):
            value = value.model_dump()
            value["page_corrected"] = None
        return value


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
    a = re.sub(r"^section\s+", "", a or "", flags=re.I)
    b = re.sub(r"^section\s+", "", b or "", flags=re.I)
    na, nb = normalise(a), normalise(b)
    if not na or not nb:
        return True
    if re.findall(r"\d+", a or "") != re.findall(r"\d+", b or ""):
        return False
    return SequenceMatcher(None, na, nb).ratio() >= LABEL_SIM


def cells_match(a: str | None, b: str | None) -> bool:
    """Same table cell: the same words, in any order, and the same numbering.

    Cells are slash-separated coordinates ("Attachment - Total attachment / SD"),
    which the two extractors write in different orders and with different lead-ins,
    so the words they share decide. One word apart — Men against Women, M against
    SD — is far enough to keep two cells separate.
    """
    ta, tb = set(re.findall(r"[a-z0-9]+", (a or "").lower())), set(
        re.findall(r"[a-z0-9]+", (b or "").lower())
    )
    if not ta or not tb:
        return True
    if re.findall(r"\d+", a or "") != re.findall(r"\d+", b or ""):
        return False
    return len(ta & tb) / len(ta | tb) >= LABEL_SIM


def canonical_kind(claim: SlimClaim) -> str:
    raw = (claim.quantity_kind or "other").strip()
    return raw if raw in ALLOWED_KINDS else KIND_MAP.get(raw, "other")


def values_agree(a: SlimClaim, b: SlimClaim) -> bool:
    """Exact numeric transcription; reported precision is compared separately."""
    return a.value is not None and b.value is not None and a.value == b.value


def fields_agree(a: SlimClaim, b: SlimClaim) -> bool:
    return values_agree(a, b) and all(
        getattr(a, field) == getattr(b, field)
        for field in ("study_id", "comparator", "precision", "quantity_kind", "aggregation",
                      "target_outcome", "target_contrast", "target_model", "quantity_role"))


def _location(claim: SlimClaim) -> SlimLocation:
    return claim.location or SlimLocation()


def source_position(claim: SlimClaim, texts: list[str]) -> tuple[int, int] | None:
    """Locate a quoted printed token; target names and reported readings are separate.

    Common statistic markers locate the token even if the extracted numeric value,
    comparator or semantic label is disputed. Ambiguous quotations have no position.
    """
    from ..source_integrity import normalise as source_normalise, supported_tokens
    page = _location(claim).page
    if not page or not 0 < page < len(texts) or _location(claim).kind != "text":
        return None
    quote, text = source_normalise(claim.source_quote or ""), source_normalise(texts[page])
    if len(quote) < 8 or text.count(quote) != 1:
        return None
    marker = {"p_value": r"p(?:s|[- ]values?)?", "t": "t", "f": "f", "r": "r", "d": r"d(?:z|_z)?"}.get(canonical_kind(claim))
    if marker:
        pattern = r"(?<!\w)" + marker + r"\s*(?:\([^)]*\))?\s*(?:<=|>=|[<>=≤≥])\s*-?(?P<number>(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
        matches = list(re.finditer(pattern, quote, re.I))
        offsets = [m.start("number") for m in matches]
    else:
        offsets = [m.start() for m in supported_tokens(claim, quote)]
    return (page, text.find(quote) + offsets[0]) if len(offsets) == 1 else None


def _candidate(a: SlimClaim, b: SlimClaim, require_value: bool, positions: dict | None = None) -> float | None:
    """Source identity is independent of numeric agreement and operators."""
    la, lb = _location(a), _location(b)
    if la.page is None or la.page != lb.page:
        return None
    if a.source_token_id and b.source_token_id:
        return 200. if a.source_token_id == b.source_token_id and (not require_value or fields_agree(a,b)) else None
    pa, pb = (positions or {}).get(id(a)), (positions or {}).get(id(b))
    if pa is not None and pb is not None:
        return 100. if pa == pb and (not require_value or fields_agree(a, b)) else None
    for known, other in ((pa, b), (pb, a)):
        spans = (positions or {}).get((id(other), "spans"), [])
        if known and spans and not any(start <= known[1] < end for start, end in spans):
            return None
    if a.study_id and b.study_id and normalise(a.study_id) != normalise(b.study_id):
        return None
    if la.kind and lb.kind and la.kind != lb.kind:
        return None
    if canonical_kind(a) != canonical_kind(b) and {a.quantity_kind, b.quantity_kind} != {"mean", "other"}:
        return None
    if {a.quantity_kind, b.quantity_kind} == {"ci_lower", "ci_upper"}:
        return None
    if not labels_match(la.label, lb.label) or not cells_match(la.cell, lb.cell):
        return None
    # Numeric design levels identify contrasts; reported statistics do not.
    def levels(text):
        return {(n, unit.lower()) for n, unit in re.findall(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(dB|ms|Hz|seconds?|milliseconds?)\b", text or "", re.I)}
    levels_a, levels_b = levels(a.description), levels(b.description)
    if levels_a and levels_b and levels_a != levels_b:
        return None
    # Degrees of freedom and experiment numbers identify sibling tests.
    def design_ids(c):
        text = (c.description or "") + " " + (c.source_quote or "")
        return set((name.lower(), n) for name, n in re.findall(
            r"\b(experiment|exp|study|sample|wave|session)\.?\s*(\d+)\b", text, re.I))
    def dfs(c):
        return set(re.sub(r"\s+", "", m.lower()) for m in re.findall(
            r"\b(?:t|f|r)\s*\([\d.,\s]+\)", c.source_quote or "", re.I))
    for left, right in ((design_ids(a), design_ids(b)), (dfs(a), dfs(b))):
        if left and right and left != right:
            return None
    anchored = bool(a.source_region and a.source_region == b.source_region)
    quote = bool(a.source_quote and a.source_quote == b.source_quote)
    stop = {"the", "a", "an", "of", "in", "for", "and", "between", "to", "was", "is", "when", "with", "p", "t", "d", "dz", "test", "tests", "paired", "condition", "conditions"}
    def words(text):
        return set(re.findall(r"[a-z]+", (text or "").lower())) - stop
    wa, wb = words(a.description), words(b.description)
    containment = len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0
    def without_numbers(text):
        return re.sub(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", "#", text or "")
    similarity = max(label_similarity(without_numbers(a.description), without_numbers(b.description)) if a.description and b.description else 0, containment)
    from ..source_integrity import normalise as source_normalise
    qa = without_numbers(source_normalise(a.source_quote or ""))
    qb = without_numbers(source_normalise(b.source_quote or ""))
    context_similarity = label_similarity(qa, qb) if min(len(qa), len(qb)) >= 20 else 0.
    if not (anchored or quote or context_similarity >= .8 or similarity >= DESCRIPTION_SIM):
        return None
    if require_value and not fields_agree(a, b):
        return None
    semantic_support = sum(bool(getattr(a, field) and getattr(b, field) and normalise(getattr(a, field)) == normalise(getattr(b, field)))
                           for field in ("target_outcome", "target_contrast", "target_model"))
    return 4 * anchored + 3 * quote + 6 * (context_similarity if context_similarity >= .8 else 0) + similarity + .25 * semantic_support + bool(la.cell and lb.cell)


def _pair_pass(rows_a: list[SlimClaim], rows_b: list[SlimClaim], require_value: bool, positions: dict | None = None):
    """Mutual unique best source matches; ambiguous candidates stay unresolved.

    Assignment never uses the value to decide identity, even in the agreement pass.
    This is invariant to input order and does not force ambiguous matches.
    """
    scores = {(i, j): score for i, a in enumerate(rows_a) for j, b in enumerate(rows_b)
              if (score := _candidate(a, b, False, positions)) is not None}
    def best(items):
        ranked = sorted(items, key=lambda item: item[1], reverse=True)
        if not ranked or (len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.05):
            return None
        return ranked[0][0]
    selected = []
    remaining = dict(scores)
    while remaining:
        ab = {i: best([(j, s) for (ii, j), s in remaining.items() if ii == i]) for i in range(len(rows_a))}
        ba = {j: best([(i, s) for (i, jj), s in remaining.items() if jj == j]) for j in range(len(rows_b))}
        certain = [(i, j) for i, j in ab.items() if j is not None and ba[j] == i]
        if not certain:
            break
        selected.extend(certain)
        ia, ib = {i for i, _ in certain}, {j for _, j in certain}
        remaining = {(i, j): s for (i, j), s in remaining.items() if i not in ia and j not in ib}
    if require_value:
        selected = [(i, j) for i, j in selected if fields_agree(rows_a[i], rows_b[j])]
    used_a, used_b = {i for i, _ in selected}, {j for _, j in selected}
    return ([(rows_a[i], rows_b[j]) for i, j in selected],
            [a for i, a in enumerate(rows_a) if i not in used_a],
            [b for j, b in enumerate(rows_b) if j not in used_b])


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
        **{field: (_first(getattr(a, field), getattr(b, field)) or []) if field == "figure_endpoints" else _first(getattr(a, field), getattr(b, field)) for field in
           ("source_quote", "source_region", "source_token_id", "figure_panel", "figure_endpoints", "legend_quote", "quantity_role", "aggregation",
            "target_outcome", "target_contrast", "target_model")},
    )


class Resolution:
    """One claim on its way into claims.json, with how it got there."""

    def __init__(self, claim: SlimClaim, source: str, rival: SlimClaim | None = None):
        self.claim = claim
        self.source_claim_ids = {source: claim.claim_id} if source in {"A", "B"} else {"A": claim.claim_id}
        if rival is not None:
            self.source_claim_ids["B"] = rival.claim_id
        self.decision_calls = []
        self.item_id = None
        self.source = source  # "agreed" | "A" | "B" | "conflict"
        self.rival = rival  # the competing value for a conflict
        self.agreed = source == "agreed"
        self.note: str | None = None
        self.confidence: str | None = "high" if source == "agreed" else None
        self.dropped = False
        self.unresolved = source != "agreed"


def partition(list_a: ClaimList, list_b: ClaimList, source_texts: list[str] | None = None) -> list[Resolution]:
    """Agreements, value conflicts and singletons, in that order of confidence."""
    positions = {id(c): source_position(c, source_texts) for c in list_a.claims + list_b.claims} if source_texts else {}
    if source_texts:
        from ..source_integrity import normalise as source_normalise
        for c in list_a.claims + list_b.claims:
            page = _location(c).page
            quote = source_normalise(c.source_quote or "")
            if page and 0 < page < len(source_texts) and len(quote) >= 8:
                text = source_normalise(source_texts[page])
                positions[(id(c), "spans")] = [(m.start(), m.end()) for m in re.finditer(re.escape(quote), text)]
    pairs, only_a, only_b = _pair_pass(list_a.claims, list_b.claims, require_value=False, positions=positions)
    agreed = [(a, b) for a, b in pairs if fields_agree(a, b) and _location(a).kind != "figure"]
    conflicts = [(a, b) for a, b in pairs if not fields_agree(a, b) or _location(a).kind == "figure"]

    out = [Resolution(merge_claim(a, b), "agreed") for a, b in agreed]
    out += [Resolution(merge_claim(a, b), "conflict", rival=b) for a, b in conflicts]
    out += [Resolution(merge_claim(a, None), "A") for a in only_a]
    out += [Resolution(merge_claim(b, None), "B") for b in only_b]
    for resolution, pair in zip(out, agreed + conflicts):
        resolution.original_pair = pair
        resolution.source_claim_ids = {"A": pair[0].claim_id, "B": pair[1].claim_id}
    return out


def pairing_diagnostics(list_a: ClaimList, list_b: ClaimList, source_texts=None) -> dict:
    # Partition supplies span consistency and mutual-unique assignment.
    rows = partition(list_a, list_b, source_texts)
    pairs = [r.original_pair for r in rows if r.source == "conflict"]
    agreed = sum(r.agreed for r in rows)
    numeric = ("value", "comparator", "precision", "quantity_kind")
    semantic = ("study_id", "aggregation", "target_outcome", "target_contrast", "target_model", "quantity_role")
    n_pairs = agreed + len(pairs)
    total = len(list_a.claims) + len(list_b.claims)
    return {
        "n_source_pairs": n_pairs,
        "source_pair_coverage": 2 * n_pairs / total if total else None,
        "n_transcription_agreed": agreed + sum(all(getattr(a, f) == getattr(b, f) for f in numeric) for a, b in pairs),
        "n_semantic_agreed": agreed + sum(all(getattr(a, f) == getattr(b, f) for f in semantic) for a, b in pairs),
        "field_disputes": {f: sum(getattr(a, f) != getattr(b, f) for a, b in pairs) for f in numeric + semantic},
        "interpretation": "Pair coverage and agreement conditional on candidate pairing; neither measures source precision or recall.",
    }


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
        "candidate_claims": [c.model_dump()] + ([res.rival.model_dump()] if res.rival else []),
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
    if res.note and res.note.startswith("source validation:"):
        payload["validation_failure"] = res.note
    return payload


def _batches(items: list[tuple[str, Resolution]], size: int) -> list[list[tuple[str, Resolution]]]:
    """Page-ordered chunks: one call covers a few neighbouring pages at most."""
    ordered = sorted(items, key=lambda kv: (_location(kv[1].claim).page or 10**6, kv[0]))
    return [ordered[i : i + size] for i in range(0, len(ordered), size)]


def _joint_source_batches(items, duplicate_groups, size=BATCH_SIZE):
    """Give a source reviewer every competing reading of one physical occurrence."""
    peer_group={item:group for group in duplicate_groups for item in group}
    lookup=dict(items);seen=set();groups=[]
    for item,res in sorted(items,key=lambda pair:(_location(pair[1].claim).page or 10**6,pair[0])):
        if item in seen:continue
        ids=[i for i in peer_group.get(item,[item]) if i in lookup]
        if len(ids)>1:
            for i in ids:
                lookup[i].note += (' Joint physical-source review with peer item IDs '+', '.join(ids)+'. '
                    'Inspect whether these are duplicate interpretations or distinct printed quantities with a wrong source_token_id. '
                    'For distinct quantities correct the physical IDs. For one printed quantity retain one complete corrected claim and drop its duplicate records; preserve any genuinely joint target meaning.')
        groups.append([(i,lookup[i]) for i in ids]);seen.update(ids)
    batches=[];batch=[]
    for group in groups:
        if batch and len(batch)+len(group)>size:batches.append(batch);batch=[]
        batch.extend(group)
    if batch:batches.append(batch)
    return batches


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
        band = None if _location(res.claim).kind in {"figure", "table"} else value_band(pdf, page, res.claim.value, res.claim.precision)
        if res.rival is not None:
            band = None  # Full page avoids privileging either candidate reading.
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
    force: bool = False,
) -> tuple[dict[str, ArbitrationItem], str]:
    payload = [_item_payload(i, res, per_item.get(i, 0)) for i, res in batch]
    listing = "\n".join(f"- image {n}: {p.name}" for n, p in enumerate(images, 1)) or "none"
    prompt = artifacts.load_prompt(
        prompt_name, items=json.dumps(payload, indent=1), images=listing
    )
    if step.startswith("arbitrate:source_repair"):
        from ..source_layout import build, index
        layout=build(manifest.path(manifest.pdf))
        pages={_location(r.claim).page for _,r in batch}
        nodes=[n for n in index(layout).values() if n['page'] in pages]
        prompt += "\nController source-validation repair. Resolve each validation_failure from the source. Use correct when any field changes; retain either original candidate claim_id. If a token ID selected the wrong sub-number of a compound printed word, select the correct physical token from the supplied inventory. One physical p-value printed 'for both' is ONE aggregate record covering both named tests: keep one complete aggregate and drop duplicate expansions. Unlabelled ± dispersion is a printed quantity even when SD versus SE is unstated: use quantity_kind=other, record uncertainty explicitly, and do not assert SD. Figure markers state their legend bound, never an exact p inferred from nearby prose. Do not drop a genuinely reported quantity merely because its method is not specified. Physical inventory:\n" + json.dumps(nodes)
    source_path = manifest.path("paper.txt")
    if source_path.exists():
        # Cross-page sentences and figure panels can be interpreted only with
        # the surrounding paper; numeric transcription still comes from images.
        context = source_path.read_text(errors="replace")
        prompt += "\n\nPaper text for cross-page semantic context (damaged glyphs require the image; never use statistical plausibility to change a printed value):\n" + context
    cache_path = log_path.with_suffix(".response.json")
    fingerprint = response_cache.key(prompt, ArbitrationBatch, images, tier)
    cached = response_cache.read(cache_path, fingerprint, ArbitrationBatch) if not force else None
    if cached:
        response, call_id = cached
        expected = {item_id for item_id, _ in batch}
        decisions = {d.item_id: d for d in response.items}
        if set(decisions) == expected and len(decisions) == len(response.items):
            return decisions, call_id
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
    expected = {item_id for item_id, _ in batch}
    if set(decisions) != expected or (r.parsed and len(decisions) != len(r.parsed.items)):
        return {}, (r.ledger_id or "")
    if r.parsed is not None:
        response_cache.write(cache_path, fingerprint, r.parsed, r.ledger_id or "")
    return decisions, (r.ledger_id or "")


def apply_decision(res: Resolution, decision: ArbitrationItem | None, *, source_repair: bool = False) -> None:
    """Fold one model answer into the resolution; a missing answer leaves it unresolved."""
    if decision is None or decision.uncertain:
        reason = decision.note if decision and decision.note else None
        res.note = f"unresolved: {reason}" if reason else "unresolved"
        res.confidence = "low"
        return
    res.note = decision.note
    if decision.decision == "drop":
        res.dropped, res.unresolved = True, False
        return
    if decision.corrected_claim is None:
        res.unresolved = True
        res.confidence = "low"
        res.note = "unresolved: complete source-grounded claim required from arbitration"
        return
    corrected = decision.corrected_claim
    same_occurrence = bool(res.claim.source_token_id and corrected.source_token_id == res.claim.source_token_id
        and _location(corrected).page == _location(res.claim).page)
    # Extractor-local labels are not physical source identities. A paired reading
    # can return either candidate label. Source repair can also correct a bad
    # physical pointer; the stable item and original candidate IDs retain provenance.
    # Unrelated candidate IDs remain invalid, and the corrected source is revalidated.
    if corrected.claim_id != res.claim.claim_id and not (
            corrected.claim_id in res.source_claim_ids.values()
            and (same_occurrence or (source_repair and decision.decision == "correct"))):
        res.unresolved = True
        res.note = "unresolved: arbitration changed claim identity"
        return
    if decision.decision == "keep" and (any(getattr(res.claim,k)!=getattr(corrected,k)
            for k in ("value","comparator","precision","quantity_kind","study_id","aggregation","quantity_role"))
            or any(getattr(_location(res.claim), k) != getattr(_location(corrected), k) for k in ("page", "kind", "cell"))):
        res.unresolved = True
        res.note = "unresolved: keep changed a substantive claim field; correction required"
        return
    res.claim = corrected.model_copy(deep=True, update={"claim_id":res.claim.claim_id})
    res.unresolved = False
    res.confidence = "medium"


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
            "state": "abstained" if res.unresolved else "complete",
            "abstain_reason": res.note if res.unresolved else None,
            "source_validation": "unresolved" if res.unresolved else "unverified",
            **{field: getattr(c, field) for field in
               ("source_quote", "source_region", "source_token_id", "figure_panel", "figure_endpoints", "legend_quote", "target_outcome", "target_contrast", "target_model")},
            "quantity_role": c.quantity_role or "unknown",
            "aggregation": c.aggregation or "scalar",
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
                "source_adjudicated": not res.unresolved and res.confidence == "medium",
            },
        }
        records.append(artifacts.ClaimRecord.model_validate(payload))
    return records


def decision_trace(resolutions, records):
    kept = sorted([r for r in resolutions if not r.dropped], key=_sort_key)
    final = {id(r): c for r, c in zip(kept, records)}
    return [{"item_id": r.item_id, "source_claim_ids": r.source_claim_ids,
             "claim_id": final[id(r)].claim_id if id(r) in final else None,
             "partition": r.source, "decision_calls": r.decision_calls,
             "dropped": r.dropped, "note": r.note,
             "final_state": final[id(r)].state if id(r) in final else "dropped"}
            for r in resolutions]


def _repair_sources(manifest, resolutions, records, pages, stage_dir, meta, calls,
                    source_texts, layout, inputs, force=False):
    from ..source_integrity import validate_sources

    repair_tier = "source_repair" if "source_repair" in config.config().tiers else "strong"
    for round_number in range(1, 5):
        ordered = sorted([r for r in resolutions if not r.dropped], key=_sort_key)
        repair, duplicate_groups = [], {}
        for res, record in zip(ordered, records):
            page = _location(res.claim).page
            if record.state != "abstained" or not page or not 1 <= page <= len(pages):
                continue
            res.unresolved = True
            res.note = "source validation: " + (record.abstain_reason or "unresolved")
            item_id = res.item_id or f"repair_{record.claim_id}"
            res.item_id = item_id
            repair.append((item_id, res))
            if record.abstain_reason == "duplicate source occurrence requires reconciliation":
                duplicate_groups.setdefault(record.occurrence_id, []).append(item_id)
            if round_number > 1:
                res.note += (" Revalidation after source-pointer correction. Resolve all listed peers "
                             "jointly; an otherwise correct record can now duplicate another. "
                             "For table significance use the physical marker ID, not its numerical "
                             "coefficient or shared legend threshold. Transcribe the legend's actual "
                             "comparison glyph from the image; native PDF text may encode < as b.")
        if not repair:
            break
        batches = _joint_source_batches(repair, list(duplicate_groups.values()))

        def review(entry):
            k, batch = entry
            numbers = sorted({_location(r.claim).page for _, r in batch})
            imgs = [pages[p - 1] for p in numbers]
            per_item = {iid: numbers.index(_location(r.claim).page) + 1 for iid, r in batch}
            suffix = str(k + 1) if round_number == 1 else f"_round{round_number}_batch{k + 1}"
            return _call_batch(manifest, "stage0_arbitrate_strong", repair_tier,
                               f"arbitrate:source_repair{suffix}", batch, imgs, per_item,
                               stage_dir / "logs" / f"source_repair{suffix}.log", force=force)

        with ThreadPoolExecutor(max_workers=min(BATCH_WORKERS, len(batches))) as pool:
            answers = list(pool.map(review, enumerate(batches)))
        for batch, (decisions, cid) in zip(batches, answers):
            calls.append(cid)
            for iid, res in batch:
                if cid:
                    res.decision_calls.append(cid)
                apply_decision(res, decisions.get(iid), source_repair=True)
        meta.model_calls = calls
        records = to_records(resolutions, "vision_a", "vision_b", meta)
        validate_sources(records, source_texts, inputs.get("pdf") if inputs else None, layout=layout)
    return records


def run(
    manifest,
    list_a: ClaimList,
    list_b: ClaimList,
    pages: list[Path],
    inputs: dict[str, str] | None = None,
    force: bool = False,
) -> tuple[list[artifacts.ClaimRecord], list[str]]:
    from ..source_integrity import VERSION
    inputs = {**(inputs or {}), "source_integrity_version": VERSION}
    stage_dir = paths.run_dir(manifest.paper_id, 0)
    out_path = stage_dir / "claims.json"
    if out_path.exists() and not force:
        existing = artifacts.load(artifacts.ClaimRecord, out_path)
        existing = existing if isinstance(existing, list) else [existing]
        first = existing[0] if existing else None
        if (
            first
            and not artifacts.prompt_stale(first, PROMPTS)
            and first.meta is not None
            and first.meta.inputs == (inputs or {})
        ):
            return existing, []

    source_texts = extract.page_texts(manifest, len(pages))
    resolutions = partition(list_a, list_b, source_texts)
    diagnostics = pairing_diagnostics(list_a, list_b, source_texts)
    from ..source_integrity import normalise as source_normalise, token_supported
    for resolution in resolutions:
        c = resolution.claim
        page = _location(c).page
        quote = source_normalise(c.source_quote or "")
        text = source_normalise(source_texts[page]) if page and 0 < page < len(source_texts) else ""
        if pages and (not quote or text.count(quote) != 1 or not token_supported(c, quote) or _location(c).kind in {"figure", "table"}):
            resolution.unresolved = True
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
                "arbiter" if "arbiter" in config.config().tiers else "vision_a",
                f"arbitrate:batch{k + 1}",
                batch,
                images,
                per_item,
                stage_dir / "logs" / f"arbitrate_batch{k + 1}.log",
                force=force,
            )
            for k, (batch, images, per_item) in enumerate(prepared)
        ]
        answers: dict[str, ArbitrationItem] = {}
        for (batch, _, _), f in zip(prepared, futures):
            decisions, call_id = f.result()
            for item_id, res in batch:
                res.item_id = item_id
                if call_id:
                    res.decision_calls.append(call_id)
            answers.update(decisions)
            calls.append(call_id)

    for item_id, res in disputed:
        apply_decision(res, answers.get(item_id))

    # Every unresolved required source reading receives one bounded escalation.
    escalated = [
        (item_id, res)
        for item_id, res in disputed
        if res.unresolved
    ]
    for k, escalation_batch in enumerate(_batches(escalated, BATCH_SIZE)):
        page_numbers = [p for p in sorted({_location(r.claim).page for _, r in escalation_batch
                                         if _location(r.claim).page}) if 1 <= p <= len(pages)]
        imgs = [pages[p - 1] for p in page_numbers]
        per_item = {item_id: page_numbers.index(_location(res.claim).page) + 1
                    if _location(res.claim).page in page_numbers else 0
                    for item_id, res in escalation_batch}
        decisions, call_id = _call_batch(
            manifest, "stage0_arbitrate_strong", "strong",
            "arbitrate:strong" if k == 0 else f"arbitrate:strong{k + 1}",
            escalation_batch, imgs, per_item,
            stage_dir / "logs" / f"arbitrate_strong{k + 1}.log", force=force)
        calls.append(call_id)
        for item_id, res in escalation_batch:
            if call_id:
                res.decision_calls.append(call_id)
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
    from ..source_integrity import validate_sources
    from ..source_layout import build as build_layout
    layout = build_layout(pdf)
    (stage_dir / "source_layout.json").write_text(json.dumps(layout, indent=2) + "\n")
    validate_sources(records, source_texts, inputs.get("pdf") if inputs else None, layout=layout)
    # A corrected source pointer can collide with a previously accepted record.
    # Revalidate and regroup after each bounded pass, using source evidence only.
    records = _repair_sources(manifest, resolutions, records, pages, stage_dir,
                              meta, calls, source_texts, layout, inputs, force)
    artifacts.save(records, out_path)
    (stage_dir / "arbitration.json").write_text(
        json.dumps(
            {
                **diagnostics,
                "items": decision_trace(resolutions, records),
                "n_a": len(list_a.claims),
                "n_b": len(list_b.claims),
                "n_agreed": sum(1 for r in resolutions if r.agreed),
                "n_conflict": sum(1 for r in resolutions if r.source == "conflict"),
                "n_singleton": sum(1 for r in resolutions if r.source in {"A", "B"}),
                "n_batches": len(batches),
                "n_escalated": len(escalated),
                "n_unresolved": sum(1 for r in resolutions if r.unresolved and not r.dropped),
                "n_claims": len(records),
                "n_source_unresolved": sum(c.state == "abstained" for c in records),
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

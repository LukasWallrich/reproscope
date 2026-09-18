"""Evidence-bearing mappings from source labels to canonical analysis components.

A located quotation makes a mapping auditable; it is not an independent semantic
judgement. Numerical design conflicts cannot be erased by an alias declaration.
"""
from __future__ import annotations

import re
from typing import Literal
from pydantic import BaseModel, ConfigDict


def normalise(value: str) -> str:
    return re.sub(r'[^a-z0-9]', '', value.lower())


def missing_term(value):
    return value is None or str(value).strip().casefold() in {"", "none", "null", "n/a", "not stated", "unknown", "unspecified"}


def quotation_located(quote, paper):
    """Locate ordered excerpt fragments, preserving numbers and mathematical signs."""
    import unicodedata
    def compact(s):
        s=unicodedata.normalize('NFKC',s).replace('’',"'").replace('‘',"'").replace('−','-')
        return re.sub(r'\s+','',s)
    text=compact(paper or '')
    parts=[compact(p) for p in re.split(r'\.{3}|…',quote or '')]
    position=0
    if not parts or any(len(p)<12 for p in parts):return False
    for part in parts:
        start=text.find(part,position)
        if start<0:return False
        position=start+len(part)
    return True


class TermMapping(BaseModel):
    model_config = ConfigDict(extra='forbid')
    field: Literal['outcome', 'contrast', 'model']
    study_id: str
    source_text: str
    canonical: str
    quote: str
    note: str
    claim_ids: list[str] = []


class UnassignedClaim(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claim_id: str
    reason: Literal['not_an_analysis', 'methods_insufficient', 'sources_conflict']
    note: str
    quote: str | None = None
    conflict_field: Literal["study", "outcome", "contrast", "model", "sample", "source_reading"] | None = None


def design_markers(text: str) -> dict[str, set[str]]:
    """Explicit design levels only: do not interpret arbitrary numbers as designs."""
    text = text.replace('_', ' ')
    text = re.sub(r'\bexperiment\s*(?=\d)', 'study ', text, flags=re.I)
    return {
        'model_arithmetic': {re.sub(r'\s+', '', m.lower()).replace('×', 'x').replace('plus', '+') for m in re.findall(r'(?<!\w)\d+(?:\s*(?:x|×|\+|plus)\s*\d+)+', text, re.I)},
        'levels': {re.sub(r'\s+', '', m.lower()) for m in re.findall(r'(?<![\w.])\d+(?:\.\d+)?\s*(?:dB|ms|Hz|seconds?|milliseconds?)\b', text, re.I)},
        'dimensions': {re.sub(r'\s+', '', m.lower()).replace('×', 'x') for m in re.findall(r'\b\d+\s*[x×]\s*\d+(?:\s*[x×]\s*\d+)*\b', text, re.I)},
        'studies': {re.sub(r'\s+', '', m.lower()) for m in re.findall(r'\b(?:experiment|study|wave|session)\s*\d+\b', text, re.I)},
    }


def compatible_design(source: str, canonical: str) -> bool:
    a, b = design_markers(source), design_markers(canonical)
    return all(not a[k] or not b[k] or a[k] == b[k] for k in a)


def mapping_key(mapping: TermMapping):
    return mapping.field, mapping.study_id, mapping.source_text, tuple(sorted(mapping.claim_ids))


def mapping_errors(mappings: list[TermMapping], claims, paper_text: str | None) -> list[str]:
    """Validate exact source keys, unique destinations and located evidence."""
    from .source_integrity import normalise as source_normalise
    text = source_normalise(paper_text or '')
    errors, seen = [], set()
    for m in mappings:
        key = mapping_key(m)
        if missing_term(m.source_text):
            errors.append(f"missing-value placeholder cannot define an alias: {key}")
        if key in seen:
            errors.append(f'duplicate source mapping: {key}')
        seen.add(key)
        eligible={c.claim_id for c in claims if (c.study_id or '')==m.study_id and getattr(c,'target_'+m.field,None)==m.source_text}
        if len(m.claim_ids)!=len(set(m.claim_ids)) or not set(m.claim_ids)<=eligible:
            errors.append(f'source mapping has invalid claim scope: {key}')
        for other in mappings:
            if other is m or (other.field,other.study_id,other.source_text)!=(m.field,m.study_id,m.source_text) or other.canonical==m.canonical:continue
            if (set(m.claim_ids) or eligible)&(set(other.claim_ids) or eligible):
                errors.append(f'overlapping source mappings have different destinations: {key}')
        if not any((c.study_id or '') == m.study_id and getattr(c, 'target_' + m.field, None) == m.source_text for c in claims):
            errors.append(f'unused or unknown source mapping: {key}')
        quote = source_normalise(m.quote)
        if not quotation_located(quote,text):
            errors.append(f'source mapping quotation not located: {key}')
        if not m.canonical.strip() or not m.note.strip():
            errors.append(f'source mapping lacks destination or rationale: {key}')
        if not compatible_design(m.source_text, m.canonical):
            errors.append(f'source mapping changes explicit design levels: {key}')
    return errors


def mapped(claim, field: str, canonical: str, mappings: list[TermMapping]) -> bool:
    value = getattr(claim, 'target_' + field, None)
    if missing_term(value) or normalise(value) == normalise(canonical):
        return True
    return any(m.field == field and m.study_id == (claim.study_id or '') and
               m.source_text == value and m.canonical == canonical and (not m.claim_ids or claim.claim_id in m.claim_ids) for m in mappings)


def unassigned_errors(unassigned: list[UnassignedClaim], claims, assigned: set[str], paper_text: str | None) -> list[str]:
    from .source_integrity import normalise as source_normalise
    by_id = {c.claim_id: c for c in claims}
    known = set(by_id)
    text = source_normalise(paper_text or '')
    errors, seen = [], set()
    for item in unassigned:
        if item.claim_id not in known or item.claim_id in seen or item.claim_id in assigned:
            errors.append(f'unknown, duplicate or assigned abstention: {item.claim_id}')
        seen.add(item.claim_id)
        if not item.note.strip():
            errors.append(f'assignment abstention lacks explanation: {item.claim_id}')
        if item.reason == 'sources_conflict':
            if item.conflict_field is None:
                errors.append(f'source-conflict abstention must identify the conflicting field: {item.claim_id}')
            elif item.conflict_field in {'outcome','contrast','model'} and item.claim_id in by_id and missing_term(getattr(by_id[item.claim_id], 'target_' + item.conflict_field, None)):
                errors.append(f'missing source field is not evidence of a conflict: {item.claim_id}/{item.conflict_field}')
        if item.reason != 'not_an_analysis':
            quote = source_normalise(item.quote or '')
            if not quotation_located(quote,text):
                errors.append(f'assignment abstention lacks located evidence: {item.claim_id}')
    return errors

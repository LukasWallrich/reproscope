"""Closed checks for a declared condition-matched reconstruction."""
import re
from pydantic import BaseModel, ConfigDict
from typing import Literal
from .source_integrity import normalise

class ColumnPair(BaseModel):
    model_config=ConfigDict(extra='forbid')
    x:str
    y:str
    index:str

class Convention(BaseModel):
    model_config=ConfigDict(extra='forbid')
    convention_id:Literal['condition_matched_columns']
    scope_quote:str
    pairs:list[ColumnPair]


def check(convention, paper, columns):
    """Validate evidence and identical labelled indices without reading result values."""
    if not convention:return ['no registered reconstruction convention']
    q=normalise(convention.scope_quote)
    errors=[]
    # PDF typography varies in apostrophes, hyphenation and spacing around symbols.
    # Preserve every letter/number and their order; this is not fuzzy paraphrase matching.
    source_form=lambda s:re.sub(r'[^\w]+','',normalise(s).casefold())
    if len(q)<12 or source_form(q) not in source_form(paper):errors.append('convention scope quotation not located')
    if not re.search(r'\b(within|each|per|separately|all\b.{0,35}\bconditions?)\b',q,re.I):errors.append('convention lacks a per-condition scope')
    if re.search(r'\b(reference|baseline|pooled)\b',q,re.I):errors.append('source scope names a reference, baseline or pooled level')
    compact=lambda s:re.sub('[^a-z0-9]','',s.lower())
    pairs=convention.pairs
    if not pairs or any(len({getattr(p,k) for p in pairs})!=len(pairs) for k in ('x','y','index')):errors.append('convention requires one-to-one column index sets')
    for p in pairs:
        index=compact(p.index)
        if not index or p.x==p.y or not {p.x,p.y}<=columns or not all(index in compact(x) for x in (p.x,p.y)):errors.append('condition index is not shared by the two available columns')
    return errors

"""Explicit, value-independent sample predicates shared by intake and readouts."""
from typing import Literal
from pydantic import BaseModel,ConfigDict
import pandas as pd

class RowFilter(BaseModel):
    model_config=ConfigDict(extra='forbid')
    column:str
    operator:Literal['eq','ne','not_missing']
    value:str|None


def select(frame, filters):
    for raw in filters:
        f=raw.model_dump() if isinstance(raw,RowFilter) else raw
        values=frame[f['column']].replace(r'^\s*$',pd.NA,regex=True)
        if f['operator']=='not_missing':keep=values.notna()
        else:
            target=float(f['value']) if pd.api.types.is_numeric_dtype(values) else f['value']
            keep=values.notna() & (values.eq(target) if f['operator']=='eq' else values.ne(target))
        frame=frame.loc[keep]
    return frame

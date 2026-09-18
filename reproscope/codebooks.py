"""Render deposited codebooks as text without decoding binary Office files."""
from pathlib import Path
import json


def text(path):
    path=Path(path)
    if path.suffix.lower() in {'.xlsx','.xls'}:
        import pandas as pd
        sheets=pd.read_excel(path,sheet_name=None,header=None)
        return json.dumps({'source_file':path.name,'sheets':[
            {'name':name,'rows':json.loads(frame.to_json(orient='values',force_ascii=False))}
            for name,frame in sheets.items()]},ensure_ascii=False)
    if path.suffix.lower() in {'.txt','.md','.csv','.tsv','.json'}:
        return path.read_text(encoding='utf-8-sig')
    raise ValueError('unsupported codebook format: '+path.suffix)

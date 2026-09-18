import json
import pandas as pd
from types import SimpleNamespace
from reproscope.codebooks import text
from reproscope.stage0.readiness import codebook_text


def test_xlsx_codebook_uses_all_sheets_and_coding_labels(tmp_path):
    path=tmp_path/'Codebook.xlsx'
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame([['Variable','Label'],['x','Reverse keyed item']]).to_excel(writer,index=False,header=False,sheet_name='items')
        pd.DataFrame([['sex','1=Male; 2=Female']]).to_excel(writer,index=False,header=False,sheet_name='codes')
    result=json.loads(text(path))
    assert result['sheets'][0]['rows'][1]==['x','Reverse keyed item']
    assert result['sheets'][1]['rows'][0]==['sex','1=Male; 2=Female']
    manifest=SimpleNamespace(codebook='Codebook.xlsx',path=lambda _:path)
    assert codebook_text(manifest,{'files':[]})==text(path)

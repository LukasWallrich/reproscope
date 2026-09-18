"""Printed test degrees of freedom are fields of a result, not new analyses."""
import re
import unicodedata


def degrees_of_freedom(claim):
    get=lambda k,default=None:claim.get(k,default) if isinstance(claim,dict) else getattr(claim,k,default)
    kind=get('quantity_kind')
    marker={'t':r'\bt','F':r'\bF','r':r'\br','chi2':r'(?:χ\s*\^?2|\bchi2)'}.get(kind)
    if not marker:return []
    text=unicodedata.normalize('NFKC',(get('source_quote') or '')+'; '+(get('source_anchor_quote') or '')).replace('−','-')
    pattern=marker+r'\s*(?:\(\s*(\d+(?:\s*,\s*\d+)?)\s*\)|_?\s*(\d+(?:\s*,\s*\d+)?))\s*(?:[’\x27]?s)?\s*(?:between [A-Za-z][A-Za-z _-]{0,100}\s*)?(?:<=|>=|[<>=≤≥])\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))'
    matches=[m for m in re.finditer(pattern,text,re.I) if float(m[3])==get('value')]
    readings={tuple(int(x.strip()) for x in (m[1] or m[2]).split(',')) for m in matches}
    return list(next(iter(readings))) if len(readings)==1 else []


def fields(claims):
    return [{'claim_id':c['claim_id'],'field':f'degrees_of_freedom[{i}]','value':v,
             'source_quote':c['source_quote'],'page':(c.get('location') or {}).get('page'),
             'state':c.get('state'),'source_validation':c.get('source_validation')}
            for c in claims for i,v in enumerate(degrees_of_freedom(c))]

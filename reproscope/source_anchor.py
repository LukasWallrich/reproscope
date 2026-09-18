"""Locate a quoted statistical clause without rewriting source symbols or readings.

A full quote can differ from a PDF text layer outside its numerical clause. Only a
verbatim, unique clause already present in that quote can provide fallback numeric
evidence. This does not validate the surrounding prose or semantic interpretation.
"""
import re

_STAT = re.compile(r'(?<!\w)(?:p(?:s|[- ]values?)?|ts?|fs?|rs?|d(?:z|_z)?)\s*(?:\([^)]*\)|_?\s*\d+(?:\s*,\s*\d+)?)?\s*(?:<=|>=|[<>=≤≥])\s*-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', re.I)


def locate(claim, page_text: str):
    from .source_integrity import normalise, token_supported
    quote, text = normalise(claim.source_quote or ''), normalise(page_text)
    if len(quote) >= 8 and text.count(quote) == 1 and token_supported(claim, quote):
        return {'quote':quote, 'scope':'full_quote', 'start':text.find(quote)}
    spans=list(_STAT.finditer(quote))
    candidates={quote[a.start():b.end()] for i,a in enumerate(spans) for b in spans[i:]}
    for excerpt in sorted(candidates,key=lambda q:(-len(q),q)):
        if len(excerpt) >= 8 and text.count(excerpt) == 1 and token_supported(claim, excerpt):
            return {'quote':excerpt, 'scope':'numeric_clause_only', 'start':text.find(excerpt)}
    return None

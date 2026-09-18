"""Read-only diagnostics for extraction failures and PDF text-layer limitations."""
from collections import Counter
import json
import re
import subprocess
from . import artifacts
from .source_integrity import normalise


def diagnose(claims, texts, pdf=None):
    page_health=[]
    for page,text in enumerate(texts[1:],1):
        controls=Counter(f'U+{ord(c):04X}' for c in text if ord(c)<32 and c not in '\t\r\n\f')
        if controls:page_health.append({'page':page,'unsupported_controls':dict(controls)})
    reasons=Counter()
    details=[]
    for c in claims:
        if c.state!='abstained':continue
        reason=c.abstain_reason or 'unresolved'
        page=c.location.page if c.location else None
        quote=normalise(c.source_quote or '')
        text=normalise(texts[page]) if page and 0<page<len(texts) else ''
        if 'duplicate source occurrence' in reason:category='duplicate_occurrence'
        elif c.quantity_kind=='p_value' and re.search(r'\bp[_\s]*g\b',quote,re.I):category='parameter_label_conflicts_with_p_value_kind'
        elif quote and text.count(quote)>1:category='quotation_not_unique'
        elif not quote or quote not in text:category='quotation_not_located'
        else:category='numeric_operator_kind_or_adjudication_unresolved'
        reasons[category]+=1
        details.append({'claim_id':c.claim_id,'page':page,'category':category,'reason':reason})
    fonts=[]
    if pdf:
        try:
            result=subprocess.run(['pdffonts',str(pdf)],capture_output=True,text=True,timeout=30,check=True)
            for line in result.stdout.splitlines()[2:]:
                parts=line.split()
                if len(parts)>=8 and parts[-3] in {'yes','no'}:
                    fonts.append({'name':parts[0],'unicode_map':parts[-3]=='yes'})
        except (OSError,subprocess.SubprocessError):pass
    return {'pdf_hash':artifacts.sha256_file(pdf) if pdf else None,
            'pages_with_unsupported_controls':page_health,'fonts':fonts,
            'unresolved_categories':dict(reasons),'unresolved_claims':details,
            'interpretation':'Missing Unicode maps and control characters make text-layer anchoring incomplete. They do not establish that an excluded model reading is correct. No OCR or glyph substitution is treated as ground truth.'}


def write(path,claims,texts,pdf):
    result=diagnose(claims,texts,pdf)
    path.write_text(json.dumps(result,indent=2)+'\n')
    return result

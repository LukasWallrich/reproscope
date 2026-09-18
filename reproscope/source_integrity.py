"""Source evidence, target identity and branch-local eligibility checks.

Text anchoring establishes transcription evidence, not independent source recall.
Visual adjudication remains an explicit assisted reading with a region reference.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

VERSION = "source-integrity-12"


def normalise_quantity_role(claim):
    """Sample counts are descriptives; their role never determines computation duty."""
    if claim.quantity_kind == 'n' and claim.quantity_role == 'inferential':
        claim.quantity_role = 'descriptive'
        claim.role_normalisation = {'from': 'inferential', 'to': 'descriptive',
            'rule': 'sample counts are descriptive quantities, including analysed N; all require computation accounting'}


def normalise(text: str) -> str:
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text).replace("−", "-").replace('⁎','*').replace('∗','*')).strip()
    return re.sub(r"\s+([,;:)\]])", r"\1", text)


def supported_tokens(claim, quote: str):
    if not isinstance(claim.value, (int, float)):
        return False
    matches = re.finditer(r"(?<![\w.])(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?(?!\w|\.\d)", quote)
    for match in matches:
        try:
            if float(match.group()) != abs(float(claim.value)):
                continue
        except ValueError:
            continue
        token = match.group()
        precision = getattr(claim, "precision", None)
        if precision is not None and 'e' not in token.lower() and len(token.partition('.')[2]) != precision:
            continue
        before = quote[:match.start()].rstrip()
        # A nearby different statistic is not support for the requested token.
        # Other kinds retain explicitly limited transcription-only evidence.
        marker = {"p_value": r"p(?:s|[- ]values?)?", "t": "ts?", "F": "fs?", "f": "fs?", "r": "(?:pr|rs?)", "d": r"d(?:\s*z|_z)?"}.get(claim.quantity_kind)
        significant_level = claim.quantity_kind == "p_value" and claim.comparator == "<" and bool(re.search(r"\bsignificant at(?: the)?$",before,re.I))
        description = r"(?:between [A-Za-z][A-Za-z _-]{0,100}\s*)?" if claim.quantity_kind == "r" else ""
        if marker and not significant_level and not re.search(r"(?<!\w)" + marker + r"\s*(?:\([^)]*\)|_?\s*\d+(?:\s*,\s*\d+)?)?\s*(?:[’\x27]?s)?\s*" + description + r"(?:<=|>=|[<>=≤≥])\s*-?$", before, re.I):
            continue
        sign = -1 if before.endswith("-") else 1
        if sign * float(match.group()) != float(claim.value):
            continue
        op = re.search(r"(<=|>=|[<>=≤≥])\s*-?$", before)
        found = "<" if significant_level else {"≤": "<=", "≥": ">="}.get(op[1], op[1]) if op else "="
        if found == (claim.comparator or "="):
            yield match


def token_supported(claim, quote: str) -> bool:
    return len(list(supported_tokens(claim, quote))) == 1


def number_phrase(literal):
    from .source_layout import number_word, NUMBER_WORDS
    word=literal.casefold().strip(',.;:')
    hundreds=re.fullmatch(r'([a-z]+) hundred(?: and)?(?: (.+))?',word)
    if hundreds:
        head=NUMBER_WORDS.get(hundreds[1]);tail=number_phrase(hundreds[2]) if hundreds[2] else 0
        if head is not None and 1<=head<=9 and tail is not None and 0<=tail<100:return 100*head+tail
        return None
    return number_word(word.replace(' ','-'))


def located_table_legend(claim, node, text):
    legend=normalise(claim.legend_quote or '')
    if not legend or not token_supported(claim,legend):return None
    if legend in text:return legend
    if not (node and node.get('kind')=='marker' and claim.extraction and claim.extraction.source_adjudicated):return None
    # Some native PDF layers encode < as b. Keep that native evidence visible;
    # only an image-adjudicated legend can establish the actual operator.
    symbol=re.escape(normalise(node['literal']))
    pattern=r'(?<![*†‡])'+symbol+r'(?![*†‡])\s*p\s*[b\ufffd]\s*(\d+(?:\.\d+)?|\.\d+)'
    for match in re.finditer(pattern,text):
        literal=match[1]
        if float(literal)==claim.value and len(literal.partition('.')[2])==claim.precision:
            return match[0]
    return None


def validate_sources(claims: list, texts: list[str], pdf_hash: str | None = None, *, layout: dict | None = None) -> dict:
    """Attach evidence and reject unresolved/unsupported/duplicate target readings."""
    # texts follows extract.page_texts: index zero is deliberately unused.
    occurrences = {}
    from .source_layout import index as layout_index
    physical = layout_index(layout) if layout and layout.get("pdf_sha256") == pdf_hash else {}
    # Superscript asterisks may be separate native PDF words even when the
    # initial candidate list did not recognise that Unicode glyph.
    marker_words={}
    if physical:
        for p in layout['pages']:
            for word in p.get('words',[]):
                if re.fullmatch(r'\*{1,4}|†{1,2}|‡',normalise(word['text'])):
                    key=f"p{p['page']:03d}:{word['word_id']}:marker"
                    physical[key]={**word,'source_token_id':key,'literal':word['text'],
                                   'page':p['page'],'kind':'marker'}
                    marker_words.setdefault(p['page'],[]).append(physical[key])
    for claim in claims:
        normalise_quantity_role(claim)
        quote = normalise(claim.source_quote or "")
        page = claim.location.page if claim.location else None
        text = normalise(texts[page]) if page and 0 < page < len(texts) else ""
        from .source_anchor import locate
        anchored = locate(claim, text) if not claim.location or claim.location.kind not in {"figure", "table"} else None
        if anchored:
            quote = anchored["quote"]
            claim.source_anchor_quote = quote
            claim.source_anchor_scope = anchored["scope"]
        reason = None
        node = physical.get(claim.source_token_id) if claim.source_token_id else None
        if (node and node['kind']=='number' and claim.quantity_kind=='p_value'
            and claim.location and claim.location.kind=='table' and claim.legend_quote
            and claim.extraction and claim.extraction.source_adjudicated):
            candidates=[m for m in marker_words.get(page,[])
                        if m['context']==node.get('context')
                        and -1 <= m['bbox'][0]-node['bbox'][2] <= 12
                        and abs(m['bbox'][1]-node['bbox'][1]) <= 8
                        and normalise(m['literal']) in quote]
            if len(candidates)==1:
                claim.source_token_resolution={'from':claim.source_token_id,
                    'rule':'unique adjacent native table annotation in the same PDF text line'}
                node=candidates[0];claim.source_token_id=node['source_token_id']
        if node is None and not claim.source_token_id and claim.quantity_kind=='n':
            words=[n for n in physical.values() if n.get('number_word') and n['page']==page and n['value']==claim.value and normalise(n['literal']).casefold().strip(',.;:') in quote.casefold()]
            if len(words)==1:
                node=words[0];claim.source_token_id=node['source_token_id']
        physical_text = normalise(node.get("prefix", "") + node.get("literal", "")) if node and node["kind"] == "number" else ""
        physical_supported = bool(node and node["kind"] == "number" and node["page"] == page
            and any(m.end() == len(physical_text) for m in supported_tokens(claim, physical_text)))
        if node and node.get("number_word") and node["page"] == page:
            from .source_layout import number_word
            # A coordinate may point to the first word of a multiword count.
            # Read the maximal consecutive number phrase; never accept its prefix
            # as a different count (e.g. Two in Two hundred and nine).
            prefix=node.get('prefix','').rstrip()
            suffix=node.get('context','')[len(prefix):].lstrip()
            words=[]
            for word in suffix.split():
                clean=word.casefold().strip(',.;:')
                if number_word(clean) is not None or clean in {'hundred','and'}:words.append(clean)
                else:break
                if word[-1:] in ',.;:':break
            if words and words[-1]=='and':words.pop()
            phrase=' '.join(words)
            phrase_value=number_phrase(phrase) if phrase else node['value']
            preceding=[]
            for word in reversed(prefix.split()):
                clean=word.casefold().strip(',.;:')
                if number_word(clean) is not None or clean in {'hundred','and'}:preceding.insert(0,clean)
                else:break
                if word[-1:] in ',.;:':break
            interior=bool(preceding and number_phrase(' '.join(preceding+words)) is not None)
            physical_supported = (claim.quantity_kind == "n" and claim.value == phrase_value
                and not interior and claim.comparator in {None, "="} and claim.precision in {None, 0})
            if physical_supported and len(words)>1:physical_text=phrase
        native_operator = re.search(r"(<=|>=|[<>=≤≥])\s*-?$", normalise(node.get("prefix", ""))) if node else None
        native_operator_agrees = not native_operator or {"≤":"<=","≥":">="}.get(native_operator[1],native_operator[1]) == (claim.comparator or "=")
        table_legend=located_table_legend(claim,node,text) if claim.location and claim.location.kind=='table' else None
        if claim.state == "abstained":
            reason = claim.abstain_reason or "unresolved source target"
        elif claim.source_token_id and (node is None or node["page"] != page):
            reason = "declared physical source token is missing or belongs to another page"
        elif physical_supported and (not claim.location or claim.location.kind not in {"figure", "table"}):
            claim.source_validation = "text_anchored"
            claim.source_anchor_scope = "physical_numeric_token; semantic association requires separate validation"
            claim.source_anchor_quote = physical_text
            claim.source_bbox = node["bbox"]
        elif (node and node['kind']=='number' and node['page']==page
              and claim.location and claim.location.kind=='table' and claim.location.cell
              and claim.source_region and claim.extraction and claim.extraction.source_adjudicated
              and claim.quantity_role!='unknown' and node['precision']==claim.precision
              and (node['value'] * (-1 if node['value']>0 and re.search(r'[-−]\s*$',node.get('prefix','')) else 1)) == claim.value
              and native_operator_agrees):
            claim.source_validation='visual_adjudicated'
            claim.source_anchor_scope='physical table token; row/column and statistic association image-adjudicated'
            claim.source_anchor_quote=node.get('context') or node['literal']
            claim.source_bbox=node['bbox']
        elif (node and node["kind"] == "number" and node["page"] == page
              and claim.extraction and claim.extraction.source_adjudicated
              and node["value"] == claim.value and node["precision"] == claim.precision
              and native_operator_agrees and token_supported(claim, quote)
              and ("\ufffd" in node.get("prefix", "") or not re.search(r"(?:<=|>=|[<>=≤≥])\s*-?$", normalise(node.get("prefix", "")))
                   or re.fullmatch(r"\(\d+(?:,\s*\d+)?\)\s*(?:<=|>=|[<>=≤≥])\s*-?", normalise(node.get("prefix", ""))))):
            claim.source_validation = "visual_adjudicated"
            claim.source_anchor_scope = "physical_numeric_token plus image-adjudicated statistic/operator; native line is damaged or incomplete"
            claim.source_bbox = node["bbox"]
        elif node and node["kind"] == "number" and (not claim.location or claim.location.kind not in {"figure", "table"}):
            reason = "declared physical numeric token does not support value, comparator, precision or statistic kind"
        elif (not claim.location or claim.location.kind not in {"figure", "table"}) and len(quote) >= 8 and text.count(quote) == 1 and token_supported(claim, quote):
            claim.source_validation = "text_anchored"
        elif (claim.location and claim.location.kind == "figure" and claim.source_region
              and claim.extraction and claim.extraction.source_adjudicated
              and claim.target_contrast and claim.quantity_role != "unknown"
              and claim.figure_panel and len(claim.figure_endpoints) == 2
              and claim.figure_endpoints[0] != claim.figure_endpoints[1]
              and claim.legend_quote and normalise(claim.legend_quote) in text
              and token_supported(claim, normalise(claim.legend_quote))):
            claim.source_validation = "visual_adjudicated"
        elif (node and node['kind']=='marker' and node['page']==page
              and claim.location and claim.location.kind=='table' and claim.location.cell
              and claim.source_region and claim.extraction and claim.extraction.source_adjudicated
              and claim.quantity_role!='unknown' and claim.legend_quote
              and table_legend):
            claim.source_validation='visual_adjudicated'
            claim.source_anchor_scope='physical table annotation plus located legend; cell association image-adjudicated'
            claim.source_bbox=node['bbox']
            claim.source_legend_native=table_legend
        elif (claim.location and claim.location.kind == "table" and claim.location.cell and claim.source_region
              and claim.extraction and claim.extraction.source_adjudicated
              and quote and quote in text and token_supported(claim, quote) and claim.quantity_role != "unknown"):
            claim.source_validation = "visual_adjudicated"
        else:
            reason = "source quotation, numeric token/operator or visual comparison evidence unresolved"
        if node and claim.location and claim.location.kind == "figure" and claim.legend_quote and node["kind"] != "marker":
            reason = "figure significance identity must refer to its annotation, not a legend threshold"
        if node and node["kind"] == "marker":
            symbol = re.escape(normalise(node["literal"]))
            match = re.search(r"(?<![*†‡])" + symbol + r"(?![*†‡])\s*(p\s*(?:<=|>=|[<>=≤≥])\s*(?:\d+(?:\.\d+)?|\.\d+))",
                              normalise(claim.legend_quote or ""), re.I)
            if not match or not token_supported(claim, match.group(1)):
                reason = "physical annotation symbol does not support the selected legend threshold"
        if claim.quantity_role == "unknown":
            reason = reason or "quantity provenance role unresolved"
        if reason:
            claim.state, claim.abstain_reason, claim.source_validation = "abstained", reason, "unresolved"
        tokens = list(supported_tokens(claim, quote))
        token_offset = text.find(quote) + tokens[0].start() if len(tokens) == 1 and quote and text.count(quote) == 1 else None
        visual = claim.location and claim.location.kind in {"figure", "table"}
        # Source identity cannot include disputed statistic/model/contrast fields.
        anchor = [pdf_hash, page, {"offset": token_offset if not visual else None,
                   "region": normalise(claim.source_region or "").casefold() if visual else None,
                   "cell": normalise(claim.location.cell or "").casefold() if visual else None,
                   "panel": normalise(claim.figure_panel or "").casefold() if visual else None,
                   # A legend is shared evidence, not the identity of every bracket.
                   # Endpoint order has no bearing on a physical bracket's identity.
                   "endpoints": sorted(normalise(x).casefold() for x in claim.figure_endpoints) if visual else None}]
        if node:
            # Physical identity stays fixed when readers disagree about the value,
            # statistic type, panel name or interpretation of an annotation.
            anchor = [pdf_hash, page, {"source_token_id": claim.source_token_id}]
        canonical = lambda value: normalise(value).casefold() if isinstance(value, str) else value
        anchor = [canonical(value) for value in anchor]
        claim.occurrence_id = hashlib.sha256(json.dumps(anchor, sort_keys=True).encode()).hexdigest()[:24]
        identity = [claim.study_id, claim.target_outcome, claim.target_contrast,
                    claim.target_model, getattr(claim, "quantity_kind_raw", None) or claim.quantity_kind, claim.aggregation]
        # Missing semantic identity cannot accidentally merge distinct quantities.
        if not all(identity[:4]):
            identity.append(claim.occurrence_id)
        identity = [canonical(value) for value in identity]
        claim.quantity_id = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
        if claim.source_validation != "unresolved":
            occurrences.setdefault(claim.occurrence_id, []).append(claim)
    for group in occurrences.values():
        if len(group) > 1:
            for claim in group:
                claim.state, claim.source_validation = "abstained", "unresolved"
                claim.abstain_reason = "duplicate source occurrence requires reconciliation"
    return source_status(claims)


def source_status(claims: list) -> dict:
    def get(c, k, default=None):
        return c.get(k, default) if isinstance(c, dict) else getattr(c, k, default)
    accepted, invalid = [], {}
    for c in claims:
        extraction = get(c, "extraction") or {}
        note = extraction.get("arbiter_note") if isinstance(extraction, dict) else extraction.arbiter_note
        reason = get(c, "abstain_reason")
        if get(c, "state") != "complete" or (note and note.startswith("unresolved")):
            reason = reason or "unresolved source target"
        elif get(c, "source_validation") not in {"text_anchored", "visual_adjudicated"}:
            reason = "source target lacks validated evidence"
        if reason:
            invalid[get(c, "claim_id")] = reason
        else:
            accepted.append(get(c, "claim_id"))
    return {"version": VERSION, "accepted_claim_ids": accepted, "invalid_claims": invalid,
            "all_targets_validated": bool(claims) and not invalid,
            "source_accuracy_calibration": "not established by anchoring"}


def review_run(root: Path) -> dict:
    def read(name, default):
        p = root / name
        return json.loads(p.read_text()) if p.exists() else default
    source = source_status(read("stage0/claims.json", []))
    coverage = read("stage0/extraction_coverage.json", {})
    coverage_complete = set(coverage) == {"A", "B"} and all(c.get("regions") and not c.get("missing_pages") and not c.get("unreadable_regions") for c in coverage.values())
    findings = read("stage2/broad.json", {}).get("response") or {}
    if read("stage2/review.json", {}).get('mode') == 'correctness':
        correctness = read('stage2/correctness.json', {}).get('response') or {}
        findings = {'findings': [f for name in ('coding','interpretation') for f in correctness.get(name,{}).get('findings',[])]}
    unanchored = sum(not f.get("anchor_verified") for f in findings.get("findings", []))
    execution = read("stage3/execute.json", {})
    space = read("stage3/space.json", {})
    reference = (execution.get("reference") or {}).get("status", "unverified")
    trace_paths = sorted((root / "stage1/replicas").glob("*/trace.json"))
    traces = [json.loads(p.read_text()) for p in trace_paths]
    from .stage1.audit import acceptance
    method_unverified = [t.get("replica_id") for t in traces if t.get("ran") and acceptance(t.get("hardcoding_audit") or {}) == "accepted"
                         and t.get("execution_evidence", {}).get("status") != "verified"]
    assignments = read("stage0/contract_assignments.json", {})
    claim_rows = read("stage0/claims.json", [])
    descriptive = read("stage1/descriptive/report.json", {})
    descriptive_verified = {r["claim_id"] for r in descriptive.get("results", []) if r.get("verification") == "verified"}
    required = {c["claim_id"] for c in claim_rows if c.get("state") == "complete" and c.get("quantity_role") == "inferential"} - descriptive_verified
    unassigned = [u["claim_id"] for u in assignments.get("unassigned", []) if u["claim_id"] in required]
    source_identity = read("stage0/readiness.json", {}).get("source_identity_problems", {})
    blockers = []
    from .divergence import coverage_status
    divergence_coverage = coverage_status(root)
    if not divergence_coverage['complete']:
        blockers.append('divergence diagnosis coverage is incomplete or stale')
    from .computation_coverage import review as computation_review
    computation = computation_review(root)
    if not computation['complete']:
        blockers.append('reported numbers lack verified computations or justified data limitations: '
                        + ', '.join(computation['unresolved_claim_ids']))
    directions = read('stage1/source_direction.json', {})
    if directions.get('status') == 'unresolved':
        blockers.append('paired-contrast source direction binding has unresolved evidence')
    df_unverified = [r['claim_id'] for r in read('stage1/match.json', {}).get('rows', [])
                     if (r.get('degrees_of_freedom') or {}).get('status') in {'unresolved', 'unverified'}]
    if df_unverified:
        blockers.append('reported test degrees of freedom remain unchecked: ' + ', '.join(sorted(set(df_unverified))))
    if descriptive.get("status") == "invalid":
        blockers.append("descriptive independent verification failed")
    if any(b.get("state") == "unbound" for b in descriptive.get("bindings", [])):
        blockers.append("available descriptive source-to-column bindings unresolved")
    if source_identity:
        blockers.append("analysis source identities unresolved: " + ", ".join(sorted(source_identity)))
    if unassigned:
        blockers.append("required source claims lack analysis assignments: " + ", ".join(unassigned))
    if not coverage_complete:
        blockers.append("source region coverage incomplete or unverified")
    accepted_traces = [t for t in traces if t.get("ran") and acceptance(t.get("hardcoding_audit") or {}) == "accepted"]
    if not accepted_traces:
        blockers.append("no accepted executed replica")
    if any(not t.get("run_checks", {}).get("isolation", {}).get("enforced") for t in accepted_traces):
        blockers.append("verification access boundary not established for every accepted replica")
    if method_unverified:
        blockers.append("independent method fidelity incomplete: " + ", ".join(method_unverified))
    if not source["all_targets_validated"]:
        blockers.append(f"source targets invalid or unverified: {len(source['invalid_claims'])}")
    if unanchored:
        blockers.append(f"review findings without verified source anchors: {unanchored}")
    if space.get("state") != "abstained" and reference != "verified":
        blockers.append("simulation/statistical reference verification incomplete")
    if execution.get("problems"):
        blockers.append("multiverse verification failed: " + "; ".join(execution["problems"]))
    if execution and space.get("state") != "abstained":
        if acceptance(execution.get("audit") or {}) != "accepted":
            blockers.append("multiverse computation audit not accepted")
        if (execution.get("perturbation") or {}).get("status") != "verified":
            blockers.append("multiverse input-perturbation verification incomplete")
    return {"source_targets": source, "computation_coverage": computation, "source_region_coverage_complete": bool(coverage_complete), "review_unanchored": unanchored,
            "independent_reference": reference, "method_unverified": method_unverified,
            "source_identity_problems": source_identity, "semantic_blockers": blockers,
            "semantic_ready": not blockers, "divergence_diagnosis": divergence_coverage,
            "scope": "recomputation from deposited data; upstream steps require separate evidence"}

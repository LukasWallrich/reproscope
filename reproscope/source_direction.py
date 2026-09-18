"""Bind qualitative paired-contrast direction without access to computed results.

Printed t/d signs do not define an unspecified subtraction order. Source direction
is attached to the measured variable and named columns, not to 'better/worse'.
"""
import json
import re
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict
from . import llm, paths, provenance, response_cache


class Direction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    analysis_id: str
    x: str
    y: str
    direction: Literal['positive', 'negative', 'not_stated']
    quote: str | None
    reason: str
    author_order: Literal['x_minus_y', 'y_minus_x', 'not_stated'] = 'not_stated'
    order_quote: str | None = None


class Directions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[Direction]


class QuotePatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    analysis_id: str
    quote: str | None
    order_quote: str | None


class QuotePatches(BaseModel):
    model_config = ConfigDict(extra='forbid')
    items: list[QuotePatch]


PROMPT = '''Read the paper and bind the qualitative direction of each requested paired contrast to the exact ordered columns x minus y. You receive source text and intake bindings, never computed results. Positive means the raw measured variable is higher in x than y; negative means lower. Do not infer direction from the sign or magnitude of a printed t or d, significance, model predictions, or an assumed ordering of the word 'versus'. An explicit qualitative statement or explicitly labelled source condition means can establish direction. 'No significant difference' alone establishes no direction. Use not_stated if ambiguous. For each established direction give a verbatim contiguous source quote with enough context to identify outcome and conditions; preserve words and punctuation. Read the whole relevant paragraph, including cross-page continuations. Do not conflate processing speed with threshold, early with late pupil response, or reverse-coded benefit with the measured variable. Return every analysis exactly once with the supplied x and y unchanged. This describes source evidence only, not whether reproduction succeeds.'''
PROMPT += ''' Separately record author_order ONLY if the source explicitly defines the subtraction order or signed test contrast (e.g. it states that the test uses A minus B); locate that declaration in order_quote. 'A versus B' or 'between A and B' alone does not establish subtraction order. Do not infer author_order from the printed statistic sign or the qualitative effect direction: record not_stated in those cases. An explicit order can reveal a source sign inconsistency and must not be overwritten to improve agreement.'''


def normalise(text):
    # PDF font controls are not semantic characters. Preserve every printable
    # character, including signs, digits, Greek letters and punctuation.
    text=unicodedata.normalize('NFKC',text)
    text=re.sub(r'\s+', ' ', re.sub(r'[\x00-\x08\x0b\x0e-\x1f]', '', text)).strip()
    text=re.sub(r'\s+([,;:.)\]])',r'\1',text)
    text=re.sub(r'\b([A-Za-z])\s+(\d)',r'\1\2',text)
    return re.sub(r'(?<=[A-Za-z0-9])\s+\(', '(', text)


def repair_quotes(paper_id,items,text,folder,attempt=1):
    invalid=[i for i in items if (i.direction!='not_stated' and (not i.quote or normalise(i.quote) not in normalise(text)))
             or (i.author_order!='not_stated' and (not i.order_quote or normalise(i.order_quote) not in normalise(text)))]
    if not invalid:return {},None
    prompt='''Repair source locators only. The direction and column bindings are fixed and cannot be edited. The quotations below are not contiguous exact text, for example because of page headers, column layout, or altered punctuation. Return a shorter verbatim contiguous quotation from the paper that supports the SAME direction/outcome/conditions, or the explicit author subtraction order for order_quote. Do not return only a numerical test clause: preserve the qualitative direction or the explicitly labelled condition means. Do not fill a quotation with words that are separated by a page header. If no such supporting quote exists, return null; do not invent one. No reproduced results are supplied. Return each requested analysis_id once.\n'''+json.dumps([i.model_dump() for i in invalid])+'\nPaper:\n'+text
    if attempt>1:
        from difflib import SequenceMatcher
        source=normalise(text)
        candidates={i.analysis_id:[source[m.b:m.b+m.size] for m in
            sorted(SequenceMatcher(None,normalise(i.quote or ''),source,autojunk=False).get_matching_blocks(),key=lambda m:m.size,reverse=True)[:3] if m.size>=30] for i in invalid}
        prompt += '\nThe previous repair still failed literal location, often because figure labels interrupt a sentence. Omit the disconnected prefix when the remaining clause itself supports the fixed direction and conditions. These candidate contiguous excerpts are mechanically located; select a sufficient one or return null. Do not repeat the failed quote unchanged.\n'+json.dumps(candidates)
    key=response_cache.key(prompt,QuotePatches,[],'mid')
    path=folder/('source_direction_quotes.response.json' if attempt==1 else f'source_direction_quotes{attempt}.response.json')
    saved=response_cache.read(path,key,QuotePatches)
    if saved:parsed,call_id=saved
    else:
        response=llm.call('source_direction_quotes',prompt,paper_id=paper_id,stage='1',tier='mid',schema=QuotePatches,log_path=folder/('source_direction_quotes.log' if attempt==1 else f'source_direction_quotes{attempt}.log'))
        if not response.ok or response.parsed is None:raise RuntimeError('Source direction quote repair failed: '+str(response.error))
        parsed,call_id=response.parsed,response.ledger_id
        response_cache.write(path,key,parsed,call_id)
    expected={i.analysis_id for i in invalid}
    if len(parsed.items)!=len(expected) or {i.analysis_id for i in parsed.items}!=expected:
        raise ValueError('Source direction quote repair must cover exact requested IDs')
    return {i.analysis_id:i for i in parsed.items},call_id


def direction_targets(contracts, readiness):
    targets = []
    for c in contracts:
        if (c.get('design') or {}).get('family') != 'paired_t':
            continue
        columns = [b.get('input_columns', []) for b in readiness.get('variable_bindings', [])
                   if b['analysis_id'] == c['analysis_id'] and b['contract_field'] == 'outcome']
        if len(columns) != 1 or len(columns[0]) != 2:
            members=(readiness.get('analysis_families', {}).get(c['analysis_id']) or {}).get('members', [])
            if len(members)!=1 or not all(members[0].get(k) for k in ('x','y')):
                continue
            columns=[[members[0]['x'],members[0]['y']]]
        targets.append({'analysis_id': c['analysis_id'], 'study': c.get('study_id'),
                        'outcome': c.get('outcome'), 'contrast': c['design'].get('contrast'),
                        'x': columns[0][0], 'y': columns[0][1]})
    return targets


def run(paper_id):
    stage = paths.run_dir(paper_id, 0)
    contracts = json.loads((stage / 'contracts.json').read_text())
    readiness = json.loads((stage / 'readiness.json').read_text())
    targets = direction_targets(contracts, readiness)
    if not targets:
        return {'items': [], 'status': 'not_applicable'}
    source_path = paths.corpus_dir(paper_id) / 'paper.txt'
    if not source_path.exists():
        return {'items': [], 'status': 'unresolved', 'reason': 'Source text unavailable for direction binding.'}
    text = source_path.read_text()
    prompt = PROMPT + '\nTargets:\n' + json.dumps(targets) + '\nPaper:\n' + text
    key = response_cache.key(prompt, Directions, [], 'mid')
    folder = paths.run_dir(paper_id, 1)
    cache = folder / 'source_direction.response.json'
    saved = response_cache.read(cache, key, Directions)
    if saved:
        parsed, call_id = saved
    else:
        response = llm.call('source_direction', prompt, paper_id=paper_id, stage='1',
                            tier='mid', schema=Directions, log_path=folder/'source_direction.log')
        if not response.ok or response.parsed is None:
            raise RuntimeError('source direction binding failed: ' + str(response.error))
        parsed, call_id = response.parsed, response.ledger_id
        response_cache.write(cache, key, parsed, call_id)
    expected = {t['analysis_id']: t for t in targets}
    if len(parsed.items) != len(expected) or {i.analysis_id for i in parsed.items} != set(expected):
        raise ValueError('source directions must cover every requested analysis exactly once')
    repairs,repair_call=repair_quotes(paper_id,parsed.items,text,folder)
    patched=[i.model_copy(update={'quote':repairs[i.analysis_id].quote,'order_quote':repairs[i.analysis_id].order_quote}) if i.analysis_id in repairs else i for i in parsed.items]
    second,second_call=repair_quotes(paper_id,patched,text,folder,attempt=2)
    repairs.update(second)
    rows = []
    for item in parsed.items:
        target = expected[item.analysis_id]
        row = item.model_dump()
        if item.analysis_id in repairs:
            patch=repairs[item.analysis_id]
            row['original_quote']=item.quote
            row['original_order_quote']=item.order_quote
            item=item.model_copy(update={'quote':patch.quote,'order_quote':patch.order_quote})
            row.update(quote=item.quote,order_quote=item.order_quote)
        row['anchor_verified'] = bool(item.quote and len(item.quote) >= 15 and normalise(item.quote) in normalise(text))
        row['binding_verified'] = item.x == target['x'] and item.y == target['y']
        row['order_anchor_verified'] = bool(item.order_quote and len(item.order_quote) >= 15 and normalise(item.order_quote) in normalise(text))
        row['anchor_normalisation'] = 'Unicode compatibility, PDF controls, whitespace, punctuation spacing and single-letter numeric subscripts; printable signs and words preserved'
        row['usable'] = row['binding_verified'] and (item.direction == 'not_stated' or row['anchor_verified']) and (item.author_order == 'not_stated' or row['order_anchor_verified'])
        rows.append(row)
    result = {'items': rows, 'call_id': call_id, 'repair_call_id':repair_call, 'repair_call_ids':[c for c in (repair_call,second_call) if c], 'inputs': {'response': key, 'validation': provenance.implementation('source_direction.py')},
              'status': 'anchored' if all(r['usable'] for r in rows) else 'unresolved',
              'scope': 'Model interpretation of located source statements; no reproduced values supplied. Anchoring does not independently establish semantic correctness.'}
    (folder / 'source_direction.json').write_text(json.dumps(result, indent=2)+'\n')
    if result['status']=='unresolved':
        raise RuntimeError('Source direction evidence remains unresolved; repair intake before computational reconstruction.')
    return result


def grade_paired(graded, *, kind, reported, computed, precision, comparator, direction, evidence):
    """Check magnitude and qualitative direction separately, retaining raw signs."""
    if kind not in {'t', 'd'} or comparator:
        return graded
    from .stage1.match import grade, _round_to
    if evidence.get('status') != 'verified' or evidence.get('family') != 'paired_t':
        return graded
    pair = (evidence.get('x'), evidence.get('y'))
    declared = (direction['x'], direction['y']) if direction else (None, None)
    usable = bool(direction and direction.get('usable') and pair in (declared, declared[::-1]))
    magnitude = grade(kind, abs(reported), abs(computed), precision=precision)
    expected = {'positive': 1, 'negative': -1}.get(direction['direction']) if usable else None
    if expected and pair == declared[::-1]:
        expected *= -1
    actual = 1 if computed > 0 else -1 if computed < 0 else 0
    direction_match = actual == expected if expected else None
    out = {**graded, 'magnitude_band': magnitude['band'],
           'magnitude_exact_reported_precision': (_round_to(abs(computed), precision) == _round_to(abs(reported), precision)) if precision is not None else None,
           'substantive_direction_match': direction_match,
           'direction_evidence': direction,
           'raw_sign_match': graded['sign_match'], 'raw_signed_difference': computed-reported,
           'comparison_basis': 'paired magnitude and source qualitative direction',
           'sign_convention_status': 'source direction established; author subtraction order unspecified' if expected else 'source direction not stated; magnitude only'}
    out['band'] = magnitude['band'] if direction_match is True else 'fail' if direction_match is False or magnitude['band']=='fail' else None
    out['rule'] = ('Paired statistic magnitude: ' + str(magnitude['band']) + '; substantive direction: '
                   + ('consistent with source' if direction_match is True else 'opposite to source' if direction_match is False else 'unverifiable from source')
                   + '; raw signed values retained. Test tail is assessed separately.')
    order = direction.get('author_order', 'not_stated') if usable else 'not_stated'
    if order != 'not_stated':
        # This transformation is fixed by source evidence, never selected by fit.
        scale = (1 if pair == declared else -1) * (1 if order == 'x_minus_y' else -1)
        aligned = computed * scale
        signed = grade(kind, reported, aligned, precision=precision)
        out.update(author_aligned_statistic=aligned, author_order_sign_match=signed['sign_match'],
                   sign_convention_status='explicit author subtraction order',
                   comparison_basis='explicit source order and qualitative direction',
                   band='fail' if direction_match is False else signed['band'])
        out['rule'] = ('Source-declared subtraction order: ' + order + '; ' + signed['rule']
                       + '; qualitative direction: ' + ('consistent' if direction_match is True else 'opposite' if direction_match is False else 'not separately stated')
                       + '; raw computed value retained.')
        if direction_match is True and signed['sign_match'] is False:
            out['rule'] += '; printed statistic sign conflicts with the source direction under its explicit order'
    return out

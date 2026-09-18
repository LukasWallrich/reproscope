from reproscope.stage2.correctness import validate,render_md


def answer(findings=None, label='no_clear_error_found'):
    return dict(answer=label,summary='Inspected the available code.',findings=findings or [])


def test_two_questions_and_no_general_causal_rating():
    p=dict(coding=answer(),interpretation=answer(),scope='Deposited-data computations only.')
    assert validate(p,{})==[]
    md=render_md(p)
    assert 'Clear statistical analysis errors' in md and 'Clear interpretation errors' in md
    assert 'Causal language versus design' not in md


def test_claimed_error_requires_consistent_answer_and_anchored_demonstration():
    f=dict(source_id='s',anchor='wrong column',evidence_status='demonstrated',error='Wrong input.',
           demonstration='Selected y instead of the specified x.',consequence='unknown',next_check='Inspect input binding.')
    p=dict(coding=answer([f]),interpretation=answer(),scope='.')
    assert any('inconsistent' in x for x in validate(p,{'s':'the wrong column is used'}))
    p['coding']['answer']='clear_error_found'
    assert validate(p,{'s':'the wrong column is used'})==[]
    assert any('anchor' in x for x in validate(p,{'s':'another source'}))


def test_json_evidence_is_located_after_decoding_only():
    import json
    from reproscope.stage2.correctness import source_contains
    text=json.dumps({'evidence':'"reported": 68.17,\\n "replicated": 712.0'})
    assert source_contains('"reported": 68.17,\\n "replicated": 712.0',text)
    assert not source_contains('"reported": 68.17,\\n "replicated": 71.2',text)


def test_pdf_wrapping_is_not_a_missing_or_wrong_claim():
    from reproscope.stage2.correctness import source_contains
    source='a paired t\ntests showed no difference in t0 between the two cue conditions, t\n(24) = 2.01, p = 0.056.'
    assert source_contains('a paired t tests showed no difference in t0 between the two cue conditions, t(24) = 2.01, p = 0.056',source)
    assert not source_contains('showed a difference in t0',source)
    assert not source_contains('t(24) = -2.01',source)


def test_unanchored_finding_is_quarantined_not_promoted_or_silently_dropped():
    from reproscope.stage2.correctness import qualify
    f=dict(source_id='paper',anchor='unsupported citation',evidence_status='demonstrated',error='An error.',demonstration='claimed evidence',consequence='unknown',next_check='inspect source')
    p=dict(coding=answer([f],'clear_error_found'),interpretation=answer(),scope='.')
    assert qualify(p,{'paper':'The actual source says something else.'})==[]
    assert p['coding']['answer']=='unresolved' and not p['coding']['findings']
    assert p['coding']['excluded_findings']==[f]
    assert p['citation_validation']=='qualified'

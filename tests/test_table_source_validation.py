import pytest
from reproscope.artifacts import ClaimRecord, ClaimLocation, ClaimExtraction
from reproscope.source_layout import parse_bbox
from reproscope.source_integrity import validate_sources, token_supported, number_phrase
from reproscope.source_benchmark import semantic_candidate


def layout(words):
    xml=''.join(f'<word xMin="{i*10}" yMin="2" xMax="{i*10+9}" yMax="8">{w}</word>' for i,w in enumerate(words))
    return parse_bbox('<html><page width="200" height="200"><line>'+xml+'</line></page></html>', 'pdf')


@pytest.mark.parametrize('adjudicated,value,precision,accepted', [(True,-.26,2,True),(False,-.26,2,False),(True,.26,2,False),(True,-.26,3,False)])
def test_table_token_does_not_need_prose_statistic_marker(adjudicated,value,precision,accepted):
    source=layout(['−.26','⁎⁎'])
    c=ClaimRecord(claim_id='c', quantity_kind='r',value=value,precision=precision,comparator='=',
        quantity_role='inferential',source_quote='Anger −.26** .19*',source_region='Table 4',
        location=ClaimLocation(page=1,kind='table',cell='Anger / Age'),
        extraction=ClaimExtraction(source_adjudicated=adjudicated),
        source_token_id=source['pages'][0]['numeric_candidates'][0]['source_token_id'])
    validate_sources([c],['','Native text lists columns separately. −.26 ⁎⁎'],'pdf',layout=source)
    assert (c.state=='complete') == accepted
    if accepted:assert c.source_validation=='visual_adjudicated'


@pytest.mark.parametrize('value,accepted',[(209,True),(2,False),(200,False)])
def test_count_uses_complete_number_phrase_at_physical_coordinate(value,accepted):
    source=layout(['Two','hundred','and','nine','participants'])
    c=ClaimRecord(claim_id='c',quantity_kind='n',quantity_role='descriptive',value=value,precision=0,
        comparator='=',source_quote='Two hundred and nine participants',location=ClaimLocation(page=1,kind='text'),
        source_token_id=source['pages'][0]['numeric_candidates'][0]['source_token_id'])
    validate_sources([c],['','Two hundred and nine participants'],'pdf',layout=source)
    assert (c.state=='complete')==accepted


def test_partial_correlation_marker_and_spaced_sign_are_literal():
    c=ClaimRecord(claim_id='c',quantity_kind='r',value=-.19,comparator='=',precision=2)
    assert token_supported(c,'pr = - .19')
    assert not token_supported(c,'pr = .19')
    assert number_phrase('nine hundred and ninety nine')==999
    assert number_phrase('two nine') is None


def test_interior_number_word_cannot_become_a_separate_count():
    source=layout(['Two','hundred','and','nine','participants'])
    c=ClaimRecord(claim_id='c',quantity_kind='n',quantity_role='descriptive',value=9,precision=0,
        comparator='=',source_quote='Two hundred and nine participants',location=ClaimLocation(page=1,kind='text'),
        source_token_id=source['pages'][0]['numeric_candidates'][-1]['source_token_id'])
    validate_sources([c],['','Two hundred and nine participants'],'pdf',layout=source)
    assert c.state=='abstained'


def test_benchmark_judge_does_not_receive_production_acceptance_or_provenance():
    c={'claim_id':'c','value':.2,'description':'Association', 'state':'complete',
       'meta':{'logs':['private evidence']},'source_validation':'text_anchored'}
    assert semantic_candidate(c)=={'claim_id':'c','value':.2,'description':'Association'}


@pytest.mark.parametrize('legend,damaged,accepted',[('⁎⁎⁎ p < .001.',False,True),('⁎⁎ p < .001.',False,False),('⁎⁎⁎ p < .001.',True,True)])
def test_table_significance_uses_adjacent_marker_identity_not_coefficient(legend,damaged,accepted):
    source=layout(['.27','⁎⁎⁎'])
    token=source['pages'][0]['numeric_candidates'][0]['source_token_id']
    c=ClaimRecord(claim_id='p',quantity_kind='p_value',quantity_role='inferential',value=.001,
        precision=3,comparator='<',source_quote='.27⁎⁎⁎',legend_quote=legend,source_region='Table',
        location=ClaimLocation(page=1,kind='table',cell='Age / beta'),source_token_id=token,
        extraction=ClaimExtraction(source_adjudicated=True))
    coefficient=ClaimRecord(claim_id='b',quantity_kind='coefficient',quantity_role='inferential',value=.27,
        precision=2,comparator='=',source_quote='.27⁎⁎⁎',source_region='Table',
        location=ClaimLocation(page=1,kind='table',cell='Age / beta'),source_token_id=token,
        extraction=ClaimExtraction(source_adjudicated=True))
    native_legend=legend.replace('<','b') if damaged else legend
    validate_sources([c,coefficient],['','.27 ⁎⁎⁎ '+native_legend],'pdf',layout=source)
    assert (c.state=='complete')==accepted
    assert coefficient.state=='complete'
    assert c.occurrence_id != coefficient.occurrence_id
    if accepted:assert c.source_token_id.endswith(':marker')
    if damaged:assert 'p b .001' in c.source_legend_native


def test_benchmark_field_must_name_a_value_slot_not_a_statistic_kind():
    from reproscope.source_benchmark import Match
    from pydantic import ValidationError
    import pytest
    item={'source_id':'s1','claim_id':'c1','verdict':'correct','reason':'Same printed occurrence'}
    for bad in ['mean','standard_deviation','contrast']:
        with pytest.raises(ValidationError):Match(**item,field=bad)
    assert Match(**item,field='value').field=='value'
    assert Match(**item,field='degrees_of_freedom[1]').field=='degrees_of_freedom[1]'

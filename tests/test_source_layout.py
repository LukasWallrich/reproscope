from reproscope.source_layout import parse_bbox


def test_numeric_locations_distinguish_repeated_values_without_semantic_labels():
    xml='''<html xmlns="http://www.w3.org/1999/xhtml"><body><page width="100" height="200"><flow><block>
    <line><word xMin="1" yMin="2" xMax="4" yMax="6">p</word><word xMin="5" yMin="2" xMax="7" yMax="6">&lt;</word><word xMin="8" yMin="2" xMax="15" yMax="6">.001</word></line>
    <line><word xMin="8" yMin="20" xMax="15" yMax="24">.001</word></line>
    </block></flow></page></body></html>'''
    result=parse_bbox(xml,'pdf')
    candidates=result['pages'][0]['numeric_candidates']
    assert len(candidates)==2
    assert candidates[0]['source_token_id']!=candidates[1]['source_token_id']
    assert candidates[0]['value']==.001 and candidates[0]['precision']==3
    assert candidates[0]['context']=='p < .001'
    assert parse_bbox(xml,'pdf')['pages']==result['pages']
    assert parse_bbox(xml,'another')['pages'][0]['numeric_candidates'][0]['source_token_id']!=candidates[0]['source_token_id']


def test_control_glyph_is_preserved_as_damage_not_translated_into_a_statistic():
    xml='<html><page width="100" height="200"><line><word xMin="1" yMin="2" xMax="4" yMax="6">p\x02g</word></line></page></html>'
    result=parse_bbox(xml,'pdf')
    assert result['damaged_control_glyphs']==['U+0002']
    assert result['pages'][0]['words'][0]['text']=='p\ufffdg'
    assert not result['pages'][0]['numeric_candidates']


def test_marker_and_spelled_count_have_physical_identities():
    xml='<html><page width="100" height="200"><line><word xMin="1" yMin="2" xMax="4" yMax="6">**</word><word xMin="5" yMin="2" xMax="9" yMax="6">One</word></line></page></html>'
    page=parse_bbox(xml,'pdf')['pages'][0]
    assert page['marker_candidates'][0]['literal']=='**'
    assert page['numeric_candidates'][0]['value']==1
    assert page['numeric_candidates'][0]['number_word']


def test_compound_number_words_preserve_exact_numeric_values():
    from reproscope.source_layout import number_word
    assert number_word('Forty-seven')==47
    assert number_word('ninety-nine,')==99
    assert number_word('forty-oneish') is None

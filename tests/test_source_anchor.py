from reproscope.stage0.extract import SlimClaim
from reproscope.source_anchor import locate


def test_unique_statistical_clause_survives_context_symbol_mismatch():
    c=SlimClaim(claim_id='c',quantity_kind='t',value=4.71,precision=2,comparator='=',source_quote='Processing speed ν, t(27) = 4.71, p < 0.001, dz = 0.89')
    text='Processing speed v, t(27) = 4.71, p < 0.001, dz = 0.89'
    a=locate(c,text)
    assert a and a['scope']=='numeric_clause_only'
    assert a['quote']=='t(27) = 4.71, p < 0.001, dz = 0.89'
    assert 'ν' in c.source_quote
    for update in ({'value':4.72},{'precision':1},{'comparator':'<'},{'quantity_kind':'F'}):
        assert locate(c.model_copy(update=update),text) is None


def test_excerpt_cannot_drop_wrong_df_or_select_an_ambiguous_occurrence():
    c=SlimClaim(claim_id='c',quantity_kind='t',value=4.71,precision=2,comparator='=',source_quote='The speed ν, t(31) = 4.71')
    assert locate(c,'The speed v, t(27) = 4.71') is None
    c.source_quote='The speed ν, t(27) = 4.71'
    assert locate(c,'The speed v, t(27) = 4.71. Another t(27) = 4.71.') is None


def test_guessing_parameter_cannot_supply_a_p_value_anchor():
    c=SlimClaim(claim_id='c',quantity_kind='p_value',value=.52,precision=2,comparator='=',source_quote='Guessing parameter pg = 0.52')
    assert locate(c,c.source_quote) is None


def test_numeric_clause_scope_is_retained_without_mutating_original_quote():
    from reproscope.artifacts import ClaimRecord, ClaimLocation
    from reproscope.source_integrity import validate_sources
    quote='Processing speed ν, t(27) = 4.71, p < 0.001'
    c=ClaimRecord(claim_id='c',quantity_kind='t',quantity_role='inferential',value=4.71,precision=2,comparator='=',location=ClaimLocation(page=1,kind='text'),source_quote=quote)
    validate_sources([c],['',quote.replace('ν','v')],'pdf')
    assert c.source_validation=='text_anchored' and c.source_anchor_scope=='numeric_clause_only'
    assert c.source_quote==quote and c.source_anchor_quote=='t(27) = 4.71, p < 0.001'


def test_plural_statistic_bounds_keep_kind_operator_and_aggregation():
    from reproscope.artifacts import ClaimRecord, ClaimLocation
    from reproscope.source_integrity import validate_sources
    for kind,quote,value,op in [('t','all ts <= 0.743',.743,'<='),('r','all rs > 0.410',.410,'>')]:
        c=ClaimRecord(claim_id='c',quantity_kind=kind,quantity_role='inferential',aggregation='all',value=value,precision=3,comparator=op,location=ClaimLocation(page=1,kind='text'),source_quote=quote)
        validate_sources([c],['',quote],'pdf')
        assert c.source_validation=='text_anchored' and c.aggregation=='all' and c.comparator==op


def test_subscript_degrees_of_freedom_do_not_block_statistic_anchor():
    from types import SimpleNamespace
    from reproscope.source_integrity import token_supported
    for kind,value,quote in [('F',5.96,'F 1, 285 = 5.96'),('t',5.91,'t27 = 5.91'),('r',.50,'r 107 = .50')]:
        c=SimpleNamespace(quantity_kind=kind,value=value,precision=2,comparator='=')
        assert token_supported(c,quote)
        c.quantity_kind='p_value'
        assert not token_supported(c,quote)


def test_plural_subscript_and_stated_significance_level():
    from types import SimpleNamespace
    from reproscope.source_integrity import token_supported
    c=SimpleNamespace(quantity_kind='F',value=7,precision=0,comparator='>')
    assert token_supported(c,"F 1,285 ’s > 7")
    c=SimpleNamespace(quantity_kind='p_value',value=.01,precision=2,comparator='<')
    assert token_supported(c,'consistently significant at the .01 level')
    assert not token_supported(c,'the chosen alpha was .01')

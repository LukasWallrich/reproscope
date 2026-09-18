from reproscope.artifacts import ClaimRecord, ClaimLocation
from reproscope.source_diagnostics import diagnose


def test_source_health_distinguishes_encoding_limits_from_kind_errors():
    c=ClaimRecord(claim_id='c',state='abstained',quantity_kind='p_value',source_quote='p_g = 0.52',location=ClaimLocation(page=1,kind='text'),abstain_reason='source unresolved')
    out=diagnose([c],['','The page has p_g = 0.52 and p \x05 .001'])
    assert out['pages_with_unsupported_controls']==[{'page':1,'unsupported_controls':{'U+0005':1}}]
    assert out['unresolved_categories']=={'parameter_label_conflicts_with_p_value_kind':1}
    assert c.source_quote=='p_g = 0.52' and c.state=='abstained'

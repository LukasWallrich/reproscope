import pytest
from reproscope.report.editorial import presentation_payload,restore_links,validate


def test_report_links_cover_distinct_diagnoses_without_archive_metadata():
    ids=['a1:numerical_mismatch','a1:direction_unstated']
    payload={'diagnoses':[{'group_id':i,'explanation':'Source-grounded cause.'} for i in ids],
        'inventory':[{'group_id':i,'claim_ids':['c1'],'claims':[{'claim_id':'c1','source_quote':'Reported result','value':2,'meta':{'hash':'archive-only'}}],'contract':{'meta':{'hash':'archive-only'},'outcome':'Outcome','design':{'family':'paired_t'}}} for i in ids],
        'factors':[]}
    shown,aliases=presentation_payload(payload)
    assert shown['required_evidence_ids']==['G001','G002']
    assert 'archive-only' not in str(shown)
    assert shown['inventory'][0]['claims'][0]['source_quote']=='Reported result'
    assert shown['inventory'][0]['contract']['design']=={'family':'paired_t'}
    copy={'topics':[{'group_ids':['G001','G002']} ]}
    assert validate(restore_links(copy,aliases),payload)['topics'][0]['group_ids']==ids
    with pytest.raises(ValueError,match='unexpected IDs'):restore_links({'topics':[{'group_ids':['a1']}]},aliases)
    with pytest.raises(ValueError,match='missing='):validate({'topics':[{'group_ids':[ids[0]]}]},payload)
    with pytest.raises(ValueError,match='duplicated='):validate({'topics':[{'group_ids':ids+[ids[0]]}]},payload)


def test_absent_records_do_not_prove_retention_history():
    payload={'diagnoses':[{'group_id':'c1:unavailable'}],'factors':[]}
    copy={'topics':[{'group_ids':['c1:unavailable'],'cause':'The records were never retained.'}]}
    with pytest.raises(ValueError,match='retention'):validate(copy,payload)

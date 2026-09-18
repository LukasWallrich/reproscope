from copy import deepcopy
import pytest
from reproscope.proposal_repair import candidates,apply,Revision


def fixture():
    p={'factors':[{'name':'estimator','field':'association','levels':[{'value':'base','how':'Pearson'},{'value':'rank','how':'underspecified rank operation'}]},
        {'name':'diagnostic','levels':[{'value':'omit_one','how':'leave one out'}]}]}
    s={'factors':[{'name':'estimator','levels':[{'value':'base','verdict':'defensible'},
        {'value':'rank','verdict':'rejected','rejection_kind':'nonstandard','missing_details':['order','uncertainty']}]},
        {'name':'diagnostic','levels':[{'value':'omit_one','verdict':'rejected','rejection_kind':'substantive'}]}]}
    return p,s


def test_only_operational_or_nonstandard_existing_choices_are_eligible_once():
    p,s=fixture();rows=candidates(p,s)
    assert [(r['factor'],r['level']) for r in rows]==[('estimator','rank')]
    assert 'rationale' not in rows[0]
    original=deepcopy(p)
    r=Revision(factor='estimator',level='rank',action='repair',how='Rank first, then partial correlation of ranks.',
        standard_method='Partial Spearman correlation',compatibility_conditions=['Use a valid rank-association test.'],reason='Exact ordering supplied.')
    out=apply(p,rows,[r])
    assert p==original
    assert out['factors'][0]['levels'][0]==p['factors'][0]['levels'][0]
    assert out['factors'][1]==p['factors'][1]
    assert candidates(out,s)==[]


def test_repair_cannot_add_decisions_or_replace_nonstandard_without_named_method():
    p,s=fixture();rows=candidates(p,s)
    r=Revision(factor='invented',level='rank',action='repair',how='new',standard_method=None,compatibility_conditions=[],reason='')
    with pytest.raises(ValueError,match='exactly'):apply(p,rows,[r])
    r.factor='estimator'
    with pytest.raises(ValueError,match='named standard'):apply(p,rows,[r])
    r.action='defer'
    assert apply(p,rows,[r])['factors']==p['factors']

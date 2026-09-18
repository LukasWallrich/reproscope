import pytest
from reproscope.coefficient_identity import Term,validate,attach,requested

def analysis():
    return {'analysis_id':'a','analysis_label':'Outcome / age','model_type':'OLS regression','design':{'contrast':'Coefficient for age adjusted for exposure'},
        'variable_bindings':[{'contract_field':'predictors[0]','chosen':'exposure'},{'contract_field':'predictors[1]','chosen':'age'}],
        'quantities':[{'quantity_kind':'coefficient'}]}

def test_term_requires_bound_field_and_located_identity():
    a=analysis();t=Term(analysis_id='a',state='resolved',binding_field='predictors[1]',evidence_quote=a['design']['contrast'],reason='Explicit contrast')
    assert not validate([t],[a])
    assert validate([t.model_copy(update={'binding_field':'predictors[2]'})],[a])
    assert validate([t.model_copy(update={'evidence_quote':'invented'})],[a])
    assert validate([t,t],[a])

def test_controller_attachment_does_not_change_blinded_contract():
    a=analysis();packet={'analyses':[a]};out=attach(packet,{'targets':{'a':{'state':'resolved','binding_field':'predictors[1]'}}})
    assert 'coefficient_target' not in a
    assert out['analyses'][0]['coefficient_target']['binding_field']=='predictors[1]'
    assert requested(a)
    a['quantities']=[{'quantity_kind':'other','quantity_kind_raw':'r2'}]
    assert not requested(a)

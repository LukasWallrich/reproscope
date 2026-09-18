from reproscope.artifacts import ClaimRecord
from reproscope.statistic_metadata import paired_t_df


def test_correct_t_cannot_hide_wrong_sample_df():
    c=ClaimRecord(claim_id='c', quantity_kind='t', value=3.52, source_quote='a decrease, t(27) = 3.52')
    evidence={'status':'verified','family':'paired_t','n':27}
    assert paired_t_df(c,evidence)['status']=='mismatch'
    evidence['n']=28
    assert paired_t_df(c,evidence)['status']=='match'


def test_df_is_bound_to_the_reported_statistic_not_first_in_sentence():
    c=ClaimRecord(claim_id='c', quantity_kind='t', value=3.52, source_quote='t(22) = 1.30 and t(27) = 3.52')
    assert paired_t_df(c,{'status':'verified','family':'paired_t','n':28})['reported_df']==27


def test_likelihood_df_uses_the_verified_parameter_difference():
    c=ClaimRecord(claim_id='c', quantity_kind='chi2', value=78.63, source_quote='χ²(84) = 78.63')
    assert paired_t_df(c,{'status':'verified','family':'likelihood_ratio','df':84})['status']=='match'
    assert paired_t_df(c,{'status':'verified','family':'likelihood_ratio','df':28})['status']=='mismatch'


def test_correlation_label_can_name_its_variables_before_value():
    from reproscope.reported_metadata import degrees_of_freedom
    from reproscope.source_integrity import token_supported
    from types import SimpleNamespace
    claim=SimpleNamespace(quantity_kind='r',value=.85,precision=2,comparator='=',source_quote='r34 between actual and estimated frequency = .85')
    assert token_supported(claim,claim.source_quote)
    assert degrees_of_freedom(claim)==[34]
    claim.quantity_kind='p_value'
    assert not token_supported(claim,claim.source_quote)


def test_f_requires_two_source_degrees_and_two_computed_degrees():
    c=ClaimRecord(claim_id='f',quantity_kind='F',value=9.09,source_quote='F(5132) = 9.09')
    e={'status':'verified','family':'ols','df':132}
    assert paired_t_df(c,e)['status']=='source_ambiguous'
    c.source_quote='F(5,132) = 9.09'
    assert paired_t_df(c,e)['status']=='unverified'
    e['df_model']=5
    assert paired_t_df(c,e)['status']=='match'
    e['df_model']=4
    assert paired_t_df(c,e)['status']=='mismatch'


def test_ci_endpoint_extremum_is_scalar_without_changing_test_aggregates():
    from reproscope.statistic_metadata import canonical_aggregation
    endpoint={'quantity_kind':'ci_bound','quantity_kind_raw':'ci_upper','aggregation':'max','member_ids':[]}
    assert canonical_aggregation(endpoint)=='scalar'
    assert canonical_aggregation({**endpoint,'member_ids':['a','b']})=='max'
    assert canonical_aggregation({**endpoint,'quantity_kind':'p_value'})=='max'
    assert canonical_aggregation({**endpoint,'quantity_kind_raw':'unknown'})=='max'

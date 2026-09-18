import pytest
from reproscope.source_direction import grade_paired
from reproscope.stage1.match import grade


def checked(reported, computed, direction='negative', x='cue', y='no_cue', kind='t'):
    return grade_paired(grade(kind, reported, computed, precision=2), kind=kind,
        reported=reported, computed=computed, precision=2, comparator=None,
        direction={'x':'cue','y':'no_cue','direction':direction,'usable':True,'quote':'Threshold decreased with the cue.'},
        evidence={'status':'verified','family':'paired_t','x':x,'y':y})


@pytest.mark.parametrize('reported', [3.52, -3.52])
def test_source_decrease_matches_either_printed_sign(reported):
    g = checked(reported, -3.519)
    assert g['band'] == 'A' and g['substantive_direction_match'] is True
    assert g['replicated_used'] == -3.519 and not g['direction_flipped']


def test_matching_signed_number_can_have_wrong_substantive_direction():
    g = checked(3.52, 3.519)
    assert g['band'] == 'fail' and g['substantive_direction_match'] is False
    assert g['magnitude_band'] == 'A'


def test_reversed_computational_order_is_explicit():
    assert checked(3.52, 3.519, x='no_cue', y='cue')['band'] == 'A'
    assert checked(3.52, -3.519, x='no_cue', y='cue')['band'] == 'fail'


def test_unknown_direction_never_receives_full_match_credit():
    g = checked(3.52, -3.519, direction='not_stated')
    assert g['band'] is None and g['magnitude_band'] == 'A'
    assert g['substantive_direction_match'] is None


def test_direction_agreement_cannot_rescue_wrong_magnitude():
    assert checked(3.52, -1.2)['band'] == 'fail'


@pytest.mark.parametrize('kind', ['r', 'coefficient', 'p_value', 'OR'])
def test_nonpaired_statistics_are_not_absolute_valued(kind):
    g = checked(.5, -.5, kind=kind)
    assert g == grade(kind, .5, -.5, precision=2)


def test_wrong_bound_columns_cannot_authorise_direction_comparison():
    g = checked(3.52, -3.519, x='wrong_column')
    assert g['band'] is None and g['substantive_direction_match'] is None


@pytest.mark.parametrize('order,band', [('x_minus_y','fail'), ('y_minus_x','A')])
def test_explicit_author_order_cannot_be_overridden_by_absolute_value(order, band):
    g=grade_paired(grade('t',3.52,-3.519,precision=2), kind='t', reported=3.52,
        computed=-3.519,precision=2,comparator=None,
        direction={'x':'cue','y':'no_cue','direction':'negative','usable':True,'author_order':order},
        evidence={'status':'verified','family':'paired_t','x':'cue','y':'no_cue'})
    assert g['band']==band and g['sign_convention_status']=='explicit author subtraction order'
    assert g['replicated_used']==-3.519


def test_pdf_spacing_does_not_change_the_anchored_statement():
    from reproscope.source_direction import normalise
    assert normalise('threshold t 0 , t (27) = 3.52')==normalise('threshold t0, t(27) = 3.52')
    assert normalise('decreased by -3.52')!=normalise('increased by 3.52')


def test_unknown_direction_does_not_trigger_computational_search():
    from reproscope.artifacts import ComparableResult, ComparableRow, MatchSummary
    from reproscope.stage1.match import targeted_trigger
    result=ComparableResult(rows=[ComparableRow(claim_id='c',replica_id='r',replicated=-3.52,
        band=None,outcome_status='direction_unverified',magnitude_band='A')],
        summaries=[MatchSummary(claim_id='c',n_ran=1,fraction_matched=0,fraction_a=0)])
    assert targeted_trigger(result,['c'])==(False,[])


def test_named_single_pair_uses_the_same_source_direction_route():
    from reproscope.source_direction import direction_targets
    contracts=[dict(analysis_id='a',design={'family':'paired_t'},outcome='threshold')]
    ready={'variable_bindings':[dict(analysis_id='a',contract_field='outcome',input_columns=[])],
           'analysis_families':{'a':{'members':[{'x':'cue','y':'no_cue'}]}}}
    targets=direction_targets(contracts,ready)
    assert len(targets)==1 and (targets[0]['x'],targets[0]['y'])==('cue','no_cue')
    ready['analysis_families']['a']['members'].append({'x':'other','y':'baseline'})
    assert direction_targets(contracts,ready)==[]

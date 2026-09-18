from reproscope.binding_policy import Convention,check
from reproscope.reported_metadata import degrees_of_freedom

def convention(x='pupil_low',y='speed_low'):
    return Convention(convention_id='condition_matched_columns',scope_quote='Correlations were computed within each condition.',pairs=[dict(x=x,y=y,index='low')])

def test_condition_matching_requires_scope_and_matching_indices():
    c=convention();assert check(c,c.scope_quote,{'pupil_low','speed_low'})==[]
    assert check(convention(y='speed_high'),c.scope_quote,{'pupil_low','speed_high'})
    assert check(c,'Unrelated source.',{'pupil_low','speed_low'})
    c.scope_quote='Within each condition, use the reference baseline.'
    assert check(c,c.scope_quote,{'pupil_low','speed_low'})

def test_df_fields_can_use_validated_physical_continuation_without_new_claim():
    c=dict(quantity_kind='F',value=8.76,source_quote='8.76, p = .003',source_anchor_quote='F 1,285 = 8.76')
    assert degrees_of_freedom(c)==[1,285]
    c['source_quote']='F 1,99 = 8.76'
    assert degrees_of_freedom(c)==[]

def test_one_sample_reference_uses_declared_null(tmp_path):
    import pandas as pd
    from scipy.stats import ttest_1samp
    from reproscope.reference import from_plan
    (tmp_path/'data').mkdir();x=[2.,3.,4.,7.,9.]
    pd.DataFrame({'score':x}).to_csv(tmp_path/'data/x.csv',index=False)
    result=from_plan(tmp_path,dict(family='one_sample_t',file='data/x.csv',x='score',null_value=4,alternative='greater'))
    expected=ttest_1samp(x,4,alternative='greater')
    assert result['t']==expected.statistic and result['p_raw']==expected.pvalue
    assert result['df']==4


def test_scope_matching_preserves_words_but_normalises_pdf_typography():
    c=convention();c.scope_quote="Within each condition, subjects' cross-subject association was estimated."
    source="Within each condition, subjects’ crosssubject association\nwas estimated."
    assert check(c,source,{'pupil_low','speed_low'})==[]
    assert check(c,source.replace('each','one'),{'pupil_low','speed_low'})


def test_readiness_patch_preserves_unrequested_analyses_and_rejects_cross_edits():
    import pytest
    from reproscope.stage0.readiness import ReadinessOut,ReadinessPatch,SlimAnalysisState,apply_patch
    a=SlimAnalysisState(analysis_id='a',state='abstained')
    b=SlimAnalysisState(analysis_id='b',state='complete')
    original=ReadinessOut(per_analysis=[a,b])
    repaired=apply_patch(original,ReadinessPatch(per_analysis=[a.model_copy(update={'state':'complete'})]),{'a'})
    assert {x.analysis_id:x.state for x in repaired.per_analysis}=={'a':'complete','b':'complete'}
    assert original.per_analysis[0].state=='abstained'
    with pytest.raises(ValueError,match='unrequested'):
        apply_patch(original,ReadinessPatch(per_analysis=[b]),{'a'})

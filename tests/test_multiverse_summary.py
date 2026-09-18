import pytest
from reproscope.multiverse_summary import summarise


def row(sid,sample,estimate,interval='standard',**kw):
    return dict(spec_id=sid,spec=dict(scale='raw',location='mean',inference='centred_bootstrap',multiplicity='none',interval=interval,sample=sample),
        estimate=estimate,se=2,ci_lower=estimate-3,ci_upper=estimate+3,p=.01,n=2 if sample=='full' else 1,**kw)


def test_influence_matches_all_settings_and_never_counts_in_multiverse():
    rows=[row('base','full',5),row('other','full',50,interval='bca'),
          row('delete1','leave_out:1',-1),row('delete2','leave_out:2',7)]
    rows[2]['p']=.3
    s=summarise(rows)
    assert s['n_analytical_specs']==2 and s['n_influence_checks']==2
    g=s['influence'][0]
    assert g['baseline_id']=='base' and g['max_abs_change']==6
    assert g['max_change_in_baseline_se']==3
    assert g['most_influential_participants']==['1']
    assert g['sign_changes']==g['interval_side_changes']==g['p_threshold_changes']==1
    assert s['influence_complete']


def test_no_pooled_estimand_and_incomplete_deletions_remain_visible():
    a=row('a','full',5);b=row('b','full',.1);b['spec']['scale']='log_ratio'
    s=summarise([a,b,row('c','leave_out:1',2)])
    assert len(s['analytical'])==2
    assert not s['influence_complete']


@pytest.mark.parametrize('rows',[
    [row('a','full',5,interval='bca'),row('b','leave_out:1',2)],
    [row('a','full',5),row('b','full',5),row('c','leave_out:1',2)],
    [row('a','full',5),row('b','leave_out:1',2),row('c','leave_out:1',3)]])
def test_invalid_baseline_or_duplicate_deletion_is_rejected(rows):
    with pytest.raises(ValueError):summarise(rows)

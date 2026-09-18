from reproscope.screen_completion import normalise


def test_unique_owner_reparenting_never_guesses_between_shared_level_names():
    p={'factors':[{'name':'outliers','levels':[{'value':'robust'},{'value':'none'}]}, {'name':'adjustment','levels':[{'value':'none'}]}]}
    s={'factors':[{'name':'robust','levels':[{'value':'robust','verdict':'rejected'}]},
        {'name':'unknown','levels':[{'value':'none','verdict':'defensible'}]}]}
    out,pending,_=normalise(p,s)
    assert out['factors'][0]['levels']==[{'value':'robust','verdict':'rejected'}]
    assert set(pending)=={('outliers','none'),('adjustment','none')}
    assert out['_discarded_unrequested_levels']==[['unknown','none']]


def test_conflicting_duplicate_metadata_is_repaired_not_selected_by_order():
    p={'factors':[{'name':'estimator','levels':[{'value':'partial'}]}]}
    base={'value':'partial','verdict':'defensible','effect_group':'raw'}
    s={'factors':[{'name':'estimator','levels':[base]}, {'name':'estimator','levels':[{**base,'effect_group':'rank'}]}]}
    out,pending,conflicts=normalise(p,s)
    assert pending==[('estimator','partial')] and len(conflicts['estimator=partial'])==2
    assert out['factors'][0]['levels']==[]
    s['factors'][1]['levels']=[dict(base)]
    out,pending,_=normalise(p,s)
    assert not pending and out['factors'][0]['levels']==[base]

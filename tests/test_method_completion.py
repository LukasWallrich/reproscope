import pytest
from reproscope.method_completion import Completion,validate

def test_completion_requires_exact_choices_and_located_method_evidence():
    grid={'factors':[{'name':'method','levels':[{'value':'a'}]}]}
    row={'factor':'method','level':'a','how':'compute declared method','basis':'analytical_completion','evidence':'method text','reason':'explicit inferential completion'}
    answer=Completion(definitions=[row],incompatible=[])
    validate(answer,grid,'source method text here')
    with pytest.raises(ValueError,match='evidence'):validate(answer,grid,'another source')
    with pytest.raises(ValueError,match='census'):validate(Completion(definitions=[row,row],incompatible=[]),grid,'method text')
    answer=Completion(definitions=[row],incompatible=[{'a':'method=a','b':'invented=level','why':'none'}])
    with pytest.raises(ValueError,match='incompatible'):validate(answer,grid,'method text')


def test_targeted_method_patch_preserves_unaffected_definitions():
    from reproscope.method_completion import Correction,apply_correction
    def row(level,how):return dict(factor='m',level=level,how=how,basis='screened',evidence='source',reason='reason')
    original=Completion(definitions=[row('a','unchanged'),row('b','missing interval')],incompatible=[])
    fixed=apply_correction(original,Correction(definitions=[row('b','complete interval')],incompatible=[]))
    assert fixed.definitions[0]==original.definitions[0]
    assert fixed.definitions[1].how=='complete interval'
    with pytest.raises(ValueError):apply_correction(original,Correction(definitions=[row('invented','new arm')],incompatible=[]))

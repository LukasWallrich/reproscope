import pytest
from reproscope.executor_repair import SourcePatch, apply


def patch(*changes):
    return SourcePatch(changes=[dict(filename=name,old_text=old,new_text=new) for name,old,new in changes])


def test_patch_is_atomic_and_requires_unique_matching_source(tmp_path):
    out=tmp_path/'out';out.mkdir()
    source=out/'multiverse.py';source.write_text('first\nsecond\n')
    with pytest.raises(ValueError,match='exactly once'):
        apply(tmp_path,patch(('multiverse.py','first','changed'),('multiverse.py','absent','x')))
    assert source.read_text()=='first\nsecond\n'
    apply(tmp_path,patch(('multiverse.py','first','changed'),('multiverse.py','second','last')))
    assert source.read_text()=='changed\nlast\n'
    source.write_text('repeat repeat')
    with pytest.raises(ValueError,match='exactly once'):
        apply(tmp_path,patch(('multiverse.py','repeat','x')))


def test_patch_rejects_links_and_non_source_paths(tmp_path):
    out=tmp_path/'out';out.mkdir()
    target=out/'target.py';target.write_text('original')
    (out/'multiverse.py').symlink_to(target)
    with pytest.raises(ValueError,match='source basename'):
        apply(tmp_path,patch(('multiverse.py','original','changed')))
    assert target.read_text()=='original'
    for name in ('../target.py','specs.csv','subdir/code.py'):
        with pytest.raises(ValueError):patch((name,'old','new'))


def test_rejected_patch_retains_the_unrepaired_numerical_failures():
    from reproscope.executor_repair import patch_failure_feedback
    errors = ['spec_001: independent p differs', 'spec_003: interval label differs']
    once = patch_failure_feedback(errors, 'old_text must match exactly once')
    assert once[1:] == errors
    assert patch_failure_feedback(once, once[0]) == once

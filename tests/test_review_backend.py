from types import SimpleNamespace
import pytest
from reproscope import review_backend as backend


def test_alternate_review_route_preserves_requested_tier_and_cannot_generate(monkeypatch):
    monkeypatch.setenv('REPROSCOPE_REVIEW_BACKEND','strong_alt')
    spec=SimpleNamespace(route='codex',model='review-model',model_dump=lambda:{'route':'codex','model':'review-model'})
    monkeypatch.setattr(backend.config,'tier',lambda _:spec)
    monkeypatch.setattr(backend.llm,'call',lambda *args,**kwargs:kwargs)
    result=backend.call('hardcoding_audit','source',stage='1',tier='cheap')
    assert result['route']=='codex' and result['model']=='review-model'
    assert result['extra']['requested_tier']=='cheap' and 'tier' not in result
    for step,stage in [('replica','1'),('extract','0'),('bounded_generate','1')]:
        with pytest.raises(ValueError,match='unblinded'):
            backend.call(step,'payload',stage=stage,tier='cheap')
    with pytest.raises(ValueError):backend.call('review','payload',stage='2',agentic=True)

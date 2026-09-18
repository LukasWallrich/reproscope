import json
from reproscope import response_cache
from reproscope.stage0.arbitrate import ArbitrationBatch


def test_response_cache_preserves_ledger_and_rejects_changed_dependencies_or_content(tmp_path):
    p=tmp_path/'response.json';r=ArbitrationBatch(items=[])
    response_cache.write(p,'original',r,'call123')
    out,call=response_cache.read(p,'original',ArbitrationBatch)
    assert out==r and call=='call123'
    assert response_cache.read(p,'changed',ArbitrationBatch) is None
    d=json.loads(p.read_text());d['response']['items']=[{'item_id':'changed','decision':'drop'}];p.write_text(json.dumps(d))
    assert response_cache.read(p,'original',ArbitrationBatch) is None


def test_response_without_ledger_cannot_create_a_cache_hit(tmp_path):
    p=tmp_path/'response.json'
    response_cache.write(p,'k',ArbitrationBatch(), '')
    assert not p.exists()

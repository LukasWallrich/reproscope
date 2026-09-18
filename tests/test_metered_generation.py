import json
import pytest
from reproscope.metered_generation import reserve,update_budget


def test_budget_counts_shared_pending_and_unknown_reservations(tmp_path):
    path=tmp_path/'budget.json';path.write_text(json.dumps({'cap_usd':3,'baseline_usd':.2}))
    reserve(path,1.4,'paper-a')
    with pytest.raises(ValueError,match='cannot cover'):reserve(path,1.5,'paper-b')
    assert len(json.loads(path.read_text())['calls'])==1
    update_budget(path,lambda d:d['calls'][0].update(cost_usd=.3,state='settled'))
    reserve(path,1.5,'paper-b')
    update_budget(path,lambda d:d['calls'][1].update(state='unknown'))
    with pytest.raises(ValueError,match='cannot cover'):reserve(path,1.01,'paper-c')

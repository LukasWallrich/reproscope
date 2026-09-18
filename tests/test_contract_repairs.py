import pytest
from reproscope.stage0.contracts import ContractsAndMethods
from reproscope.stage0.contract_repairs import ContractRepair, apply
from reproscope.source_mapping import TermMapping


def test_term_quote_patch_preserves_methods_and_unrelated_mappings():
    m=TermMapping(field='model',study_id='s',source_text='paired comparison',canonical='paired_t',quote='wrong quote',note='Same test')
    old=ContractsAndMethods(term_map=[m],redacted_methods='Frozen methods')
    patch=ContractRepair(term_map=[m.model_copy(update={'quote':'A located methods quote'})])
    new=apply(old,patch)
    assert new.redacted_methods==old.redacted_methods and new.term_map[0].quote=='A located methods quote'
    assert old.term_map[0].quote=='wrong quote'


def test_repair_cannot_silently_remove_unknown_or_duplicate_ids():
    with pytest.raises(ValueError):apply(ContractsAndMethods(),ContractRepair(remove_contract_ids=['unknown']))
    m=TermMapping(field='model',study_id='s',source_text='paired comparison',canonical='paired_t',quote='some quote',note='Same test')
    with pytest.raises(ValueError):apply(ContractsAndMethods(term_map=[m]),ContractRepair(term_map=[m,m]))


def test_contract_generation_uses_optional_cheap_route_and_scopes_its_cache(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from reproscope import config, llm
    from reproscope.stage0 import contracts
    selected = config.Config(tiers={
        'strong': config.ModelSpec(route='claude_p', model='haiku'),
        'contracts': config.ModelSpec(route='codex', model='gpt-5.6-luna'),
    })
    monkeypatch.setattr(config, 'config', lambda: selected)
    calls = []
    def call(*args, **kwargs):
        calls.append(kwargs['tier'])
        return llm.LLMResult(text='', parsed=ContractsAndMethods(redacted_methods='Methods'),
                             ledger_id='contract-call', route='codex', model='gpt-5.6-luna')
    monkeypatch.setattr(llm, 'call', call)
    manifest = SimpleNamespace(paper_id='test', dir=tmp_path)
    first = contracts._generate(manifest, 'contracts', 'source prompt',
        ContractsAndMethods, tmp_path / 'contracts.log')
    cached = contracts._generate(manifest, 'contracts', 'source prompt',
        ContractsAndMethods, tmp_path / 'contracts.log')
    assert calls == ['contracts']
    assert cached.ledger_id == first.ledger_id
    assert cached.model == 'gpt-5.6-luna'


def test_contract_repair_preserves_source_assignment_coverage():
    from reproscope.stage0.contracts import SlimContract
    current = ContractsAndMethods(contracts=[SlimContract(analysis_id='a', claim_ids=['c1', 'c2'])])
    with pytest.raises(ValueError, match='without replacement or disposition'):
        apply(current, ContractRepair(remove_contract_ids=['a']))
    repaired = apply(current, ContractRepair(remove_contract_ids=['a'], contracts=[
        SlimContract(analysis_id='b', claim_ids=['c1']),
        SlimContract(analysis_id='c', claim_ids=['c2'])]))
    assert {cid for c in repaired.contracts for cid in c.claim_ids} == {'c1', 'c2'}


def test_contract_repair_can_select_its_own_model_without_changing_generation(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from reproscope import config, llm
    from reproscope.stage0 import contracts
    selected = config.Config(tiers={
        'strong': config.ModelSpec(route='claude_p', model='haiku'),
        'contracts': config.ModelSpec(route='codex', model='gpt-5.6-luna'),
        'contract_repair': config.ModelSpec(route='claude_p', model='sonnet'),
    })
    monkeypatch.setattr(config, 'config', lambda: selected)
    calls = []
    def call(*args, **kwargs):
        calls.append(kwargs['tier'])
        return llm.LLMResult(text='', parsed=ContractRepair(), ledger_id='repair-call')
    monkeypatch.setattr(llm, 'call', call)
    contracts._generate(SimpleNamespace(paper_id='test', dir=tmp_path),
        'contracts:identity_repair', 'repair prompt', ContractRepair, tmp_path / 'repair.log')
    assert calls == ['contract_repair']
    assert selected.tiers['contracts'].model == 'gpt-5.6-luna'

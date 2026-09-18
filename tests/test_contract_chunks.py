import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from reproscope import artifacts, config, llm, paths
from reproscope.stage0 import contract_chunks as chunks
from reproscope.stage0.contracts import AnalysisIdentity, SlimContract
from reproscope.source_mapping import TermMapping


def claim(cid, outcome='X', contrast='Y', **kw):
    return artifacts.ClaimRecord(claim_id=cid, state='complete', study_id='s',
        quantity_kind='r', quantity_role='inferential', target_outcome=outcome,
        target_contrast=contrast, target_model='correlation', **kw)


def row(cid, outcome='X', contrast='Y', **kw):
    return chunks.AssignmentRow(claim_id=cid, kind='scalar', design_family='correlation',
        identity=AnalysisIdentity(study='s', outcome=outcome, contrast=contrast,
                                  model='correlation', sample='all'), **kw)


def test_assignment_census_rejects_missing_duplicate_and_unknown_rows():
    claims = [claim('c1'), claim('c2')]
    assert chunks.row_errors(chunks.Assignments(rows=[row('c1')]), claims)
    assert chunks.row_errors(chunks.Assignments(rows=[row('c1'), row('c1')]), claims)
    assert chunks.row_errors(chunks.Assignments(rows=[row('c1'), row('c3')]), claims)
    assert not chunks.row_errors(chunks.Assignments(rows=[row('c1'), row('c2')]), claims)


def test_repeated_scalar_reports_share_one_identity_but_distinct_pairs_do_not():
    rows = [row('c1'), row('c2', outcome='Y', contrast='X'), row('c3', contrast='Z')]
    groups = chunks.skeletons(rows)
    assert len(groups) == 2
    assert groups[0].claim_ids == ['c1', 'c2']
    assert groups[1].claim_ids == ['c3']


def test_scalar_claim_cannot_be_hidden_in_a_family():
    r = row('c1').model_copy(update={'kind': 'family', 'members': [row('m1').identity, row('m2', contrast='Z').identity]})
    assert chunks.row_errors(chunks.Assignments(rows=[r]), [claim('c1')])
    assert not chunks.row_errors(chunks.Assignments(rows=[r]), [claim('c1', aggregation='all')])
    scalar = row('c2')
    r.identity = r.identity.model_copy(update={'contrast': 'Y_and_Z_family'})
    assert len(chunks.groups_from([r, scalar])) == 2


def test_inferential_claim_cannot_be_dismissed_as_descriptive():
    r = chunks.AssignmentRow(claim_id='c1', kind='unassigned', disposition=chunks.Disposition(
        reason='not_an_analysis', note='A numerical quantity'))
    assert chunks.row_errors(chunks.Assignments(rows=[r]), [claim('c1')])


def test_method_body_schema_cannot_change_source_assignments():
    with pytest.raises(ValidationError):
        chunks.ContractBody.model_validate({'claim_ids': ['injected']})
    with pytest.raises(ValidationError):
        chunks.ContractBody.model_validate({'identity': row('c1').identity.model_dump()})
    assert not chunks.FIXED_FIELDS.intersection(chunks.ContractBody.model_fields)


def test_alias_scope_is_owned_by_one_chunk():
    m = TermMapping(field='outcome', study_id='s', source_text='X', canonical='X_score',
                    quote='The X score is the measure.', note='same measure')
    scoped = chunks.scoped_mappings([m], [claim('c1')])
    assert scoped[0].claim_ids == ['c1']
    with pytest.raises(ValueError, match='outside'):
        chunks.scoped_mappings([m.model_copy(update={'claim_ids': ['c2']})], [claim('c1')])
    with pytest.raises(ValueError, match='does not match'):
        chunks.scoped_mappings([m.model_copy(update={'source_text': 'unrelated'})], [claim('c1')])


def test_bodies_require_exact_group_coverage_and_preserve_design():
    groups = chunks.groups_from([row('c1')])
    assert chunks.body_errors(chunks.Bodies(items=[]), groups)
    body = chunks.ContractBody(outcome='X', model_type='correlation', design=artifacts.AnalysisDesign(
        family='paired_t', contrast='X-Y', independent_unit='person', evidence='source methods'))
    assert chunks.body_errors(chunks.Bodies(items=[chunks.BodyEntry(group_key=groups[0]['key'], body=body)]), groups)


def test_correlation_alias_source_coordinate_is_resolved_only_when_exact():
    m = TermMapping(field='outcome', study_id='s', source_text='Y', canonical='Y_score',
                    quote='The Y score is the measure.', note='same measure', claim_ids=['c1'])
    result = chunks.scoped_mappings([m], [claim('c1')], [row('c1')])
    assert result[0].field == 'contrast'
    assert result[0].canonical == m.canonical
    # No inferred source coordinate for directed models or partly matching scopes.
    directed = row('c1').model_copy(update={'design_family': 'other'})
    assert chunks.scoped_mappings([m], [claim('c1')], [directed])[0].field == 'outcome'
    mixed = m.model_copy(update={'claim_ids': ['c1', 'c2']})
    assert chunks.scoped_mappings([mixed], [claim('c1'), claim('c2', contrast='Z')],
                                 [row('c1'), row('c2', contrast='Z')])[0].field == 'outcome'


def test_bounded_chunk_retry_escalates_only_that_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'config', lambda: config.Config(tiers={
        'contracts': config.ModelSpec(route='codex', model='gpt-5.6-luna'),
        'contract_repair': config.ModelSpec(route='claude_p', model='sonnet')}))
    used = []
    def generate(*args, **kwargs):
        used.append(kwargs['model_tier'])
        return llm.LLMResult(text='', parsed=chunks.Assignments(rows=[]), ledger_id=f'call{len(used)}')
    monkeypatch.setattr(chunks, '_generate', generate)
    with pytest.raises(llm.LLMError, match='missing row'):
        chunks.checked_call(SimpleNamespace(paper_id='test'), 'assign', 'source', chunks.Assignments,
            lambda x: ['missing row'], tmp_path, {})
    assert used == ['contracts', 'contracts', 'contract_repair']


def test_warm_chunk_cache_reuses_model_response(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'config', lambda: config.Config(tiers={
        'contracts': config.ModelSpec(route='codex', model='gpt-5.6-luna'),
        'strong': config.ModelSpec(route='claude_p', model='haiku')}))
    calls = []
    def call(*args, **kwargs):
        calls.append(kwargs['tier'])
        return llm.LLMResult(text='', parsed=chunks.Assignments(rows=[row('c1')]), ledger_id='model-call')
    monkeypatch.setattr(llm, 'call', call)
    manifest = SimpleNamespace(paper_id='test', dir=tmp_path)
    for _ in range(2):
        result, ids = chunks.checked_call(manifest, 'assign', 'source', chunks.Assignments,
            lambda r: chunks.row_errors(r, [claim('c1')]), tmp_path, {})
        assert ids == ['model-call'] and len(result.rows) == 1
    assert calls == ['contracts']
    receipt = json.loads(next(tmp_path.glob('*.validation.json')).read_text())
    assert receipt['passed'] and receipt['model_call'] == 'model-call'


def test_interval_endpoint_extrema_belong_to_one_analysis():
    upper = claim('c1', aggregation='max').model_copy(update={'quantity_kind': 'ci_bound'})
    assert not chunks.row_errors(chunks.Assignments(rows=[row('c1')]), [upper])
    lower = upper.model_copy(update={'aggregation': 'min'})
    assert not chunks.row_errors(chunks.Assignments(rows=[row('c1')]), [lower])
    # An extreme reported across correlations still requires an enumerated family.
    assert chunks.row_errors(chunks.Assignments(rows=[row('c1')]), [claim('c1', aggregation='max')])


def test_shared_methods_index_does_not_duplicate_contract_bodies():
    shared = chunks.SharedMethods(**{name: 'Shared information.' for name in chunks.SharedMethods.model_fields})
    contracts = chunks.skeletons([row('c1')])
    contracts[0].outcome = 'Detailed item scoring belongs in the contract.'
    document = chunks.method_document(shared, contracts)
    assert contracts[0].analysis_id in document
    assert contracts[0].analysis_label in document
    assert contracts[0].outcome not in document

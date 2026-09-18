import json
from reproscope.computation_coverage import review


def put(root, name, payload):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def test_descriptives_cannot_disappear_as_not_an_analysis(tmp_path):
    put(tmp_path, 'stage0/claims.json', [{'claim_id':'c1', 'state':'complete', 'quantity_role':'descriptive'}])
    put(tmp_path, 'stage0/contract_assignments.json', {'unassigned':[{'claim_id':'c1', 'reason':'not_an_analysis'}]})
    assert review(tmp_path)['unresolved_claim_ids'] == ['c1']
    put(tmp_path, 'stage1/descriptive/report.json', {'status':'verified', 'results':[
        {'claim_id':'c1', 'verification':'verified', 'value':22.8}]})
    assert review(tmp_path)['counts'] == {'computed':1}


def test_missing_data_needs_a_reason_and_is_not_computation(tmp_path):
    put(tmp_path, 'stage0/claims.json', [{'claim_id':'c1', 'state':'complete'}])
    put(tmp_path, 'stage1/descriptive/report.json', {'bindings':[{'claim_id':'c1','state':'no_data','reason':''}]})
    assert not review(tmp_path)['complete']
    put(tmp_path, 'stage1/descriptive/report.json', {'bindings':[{
        'claim_id':'c1','state':'no_data','reason':'Trial pupil waveforms were not deposited.'}]})
    assert review(tmp_path)['counts'] == {'unavailable':1}


def test_graded_value_without_independent_evidence_cannot_count(tmp_path):
    put(tmp_path, 'stage0/claims.json', [{'claim_id':'c1', 'state':'complete'}])
    put(tmp_path, 'stage1/match.json', {'rows':[{'claim_id':'c1','outcome_status':'graded',
        'replicated':3.52,'analysis_id':'a1','replica_id':'r1'}]})
    assert not review(tmp_path)['complete']


def test_invalid_input_explanation_must_cover_every_assigned_analysis(tmp_path):
    put(tmp_path, 'stage0/claims.json', [{'claim_id':'c1', 'state':'complete'}])
    put(tmp_path, 'stage0/contracts.json', [{'analysis_id':a,'claim_ids':['c1']} for a in ['a1','a2']])
    put(tmp_path, 'stage0/readiness.json', {'per_analysis_outcome':{'a1':'data_invalid'},
        'per_analysis_reasons':{'a1':'Nested likelihood order violated.'}})
    assert not review(tmp_path)['complete']


def test_sample_count_role_is_independent_of_computation_duty():
    from reproscope.artifacts import ClaimRecord
    from reproscope.source_integrity import normalise_quantity_role
    c=ClaimRecord(claim_id='c', quantity_kind='n', quantity_role='inferential', value=25)
    normalise_quantity_role(c)
    assert c.quantity_role == 'descriptive' and c.role_normalisation['from'] == 'inferential'


def test_inferential_missing_deposit_is_an_accounted_limitation(tmp_path):
    import json
    from reproscope.computation_coverage import review
    stage=tmp_path/'stage0';stage.mkdir()
    (stage/'claims.json').write_text(json.dumps([{'claim_id':'c','state':'complete'}]))
    (stage/'contracts.json').write_text(json.dumps([{'analysis_id':'a','claim_ids':['c']}]))
    (stage/'readiness.json').write_text(json.dumps({'per_analysis_outcome':{'a':'no_data'},'per_analysis_reasons':{'a':'Study data not deposited.'}}))
    got=review(tmp_path)
    assert got['counts']=={'unavailable':1} and got['complete']
    assert got['rows'][0]['reason']=='Study data not deposited.'

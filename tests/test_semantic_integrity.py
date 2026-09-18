"""Regression checks for source truth, evidence scope and independent inference."""
import json
import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from reproscope import artifacts, calibration, reference, source_integrity
from reproscope.stage0 import arbitrate
from reproscope.stage0.extract import ClaimList, SlimClaim, SlimLocation
from reproscope.stage1 import match
from reproscope.stage2 import mde, review


def test_unadjusted_reference_does_not_verify_covariate_adjusted_analysis(tmp_path):
    from reproscope.execution_evidence import check_replica
    out=tmp_path/'out';out.mkdir()
    (out/'analysis_plan.json').write_text(json.dumps({'analyses':[{
        'analysis_id':'a','status':'supported','family':'correlation','file':'data/x.csv','x':'x','y':'y'}]}))
    (out/'results.json').write_text(json.dumps({'results':[{'analysis_id':'a','r':.5}]}))
    result=check_replica(tmp_path,{'analyses':[{'analysis_id':'a','covariates':['age']}]})
    assert result['status']=='partial'
    assert result['analyses']['a']['status']=='unverified'
    assert 'covariates' in result['analyses']['a']['reason']


def test_frozen_missed_pairs_and_operator_conflicts_are_identified_without_values():
    fixture = json.loads((Path(__file__).parent/'fixtures/extraction_source_cases.json').read_text())
    expected = None
    for seed in range(10):
        a, b = list(fixture['a']), list(fixture['b'])
        random.Random(seed).shuffle(a)
        random.Random(seed+100).shuffle(b)
        resolutions = arbitrate.partition(ClaimList(claims=a), ClaimList(claims=b))
        result = sorted((r.claim.claim_id, r.source, r.rival.claim_id if r.rival else '') for r in resolutions)
        assert sum(r.agreed for r in resolutions) == 9
        assert {(r.claim.claim_id, r.rival.claim_id) for r in resolutions if r.rival} == {('c063','c052'), ('c120','c094')}
        if expected is None:
            expected = result
        assert result == expected


def slim(**changes):
    return SlimClaim(**{'claim_id':'c', 'study_id':'s1', 'quantity_kind':'p_value', 'value':.001,
        'comparator':'<', 'precision':3, 'source_quote':'p < .001', 'source_region':'sentence:1',
        'quantity_role':'inferential', 'location':SlimLocation(page=1,kind='text',label='Results'), **changes})


def test_identity_is_not_value_and_ci_endpoints_remain_distinct():
    assert not arbitrate.values_agree(slim(value=.01,precision=2),slim(value=.015,precision=3))
    assert arbitrate._candidate(slim(), slim(study_id='s2'), False) is None
    assert arbitrate._candidate(slim(quantity_kind='ci_lower'),slim(quantity_kind='ci_upper'),False) is None
    pair = arbitrate.partition(ClaimList(claims=[slim()]),ClaimList(claims=[slim(value=.9,comparator='>=')]))
    assert len(pair) == 1 and pair[0].source == 'conflict'


def test_ambiguous_occurrences_are_not_forced_by_input_order_or_equal_numbers():
    a = ClaimList(claims=[slim(claim_id='a'), slim(claim_id='b')])
    b = ClaimList(claims=[slim(claim_id='x')])
    assert all(not r.agreed for r in arbitrate.partition(a,b))


def test_unresolved_or_value_only_arbitration_cannot_become_complete():
    res = arbitrate.Resolution(slim(), 'A')
    arbitrate.apply_decision(res, arbitrate.ArbitrationItem(item_id='i',decision='correct',value=.01))
    claim = arbitrate.to_records([res], 'a', 'b', artifacts.ArtifactMeta(artifact='test'))[0]
    assert claim.state == 'abstained'
    assert 'complete source-grounded claim' in claim.abstain_reason
    full = slim(value=.01,comparator='<=',source_quote='p <= .01')
    arbitrate.apply_decision(res,arbitrate.ArbitrationItem(item_id='i',decision='correct',corrected_claim=full))
    assert not res.unresolved and res.claim.comparator == '<='


def claim(**changes):
    return artifacts.ClaimRecord(**{'claim_id':'c', 'quantity_kind':'p_value','value':.001,'comparator':'<',
        'source_quote':'p < .001','quantity_role':'inferential','location':{'page':1,'kind':'text'},**changes})


@pytest.mark.parametrize('stored,operator,quote',[(.639,'=','p = .699'),(.465,'>','p ≥ .465'),(.001,'=','p < .001')])
def test_wrong_source_number_or_operator_never_passes_anchoring(stored,operator,quote):
    c = claim(value=stored,comparator=operator,source_quote=quote)
    source_integrity.validate_sources([c],['',quote],'pdf')
    assert c.state == 'abstained' and c.source_validation == 'unresolved'


def test_inclusive_operator_and_duplicate_occurrence_gate():
    c = claim(value=.465,comparator='>=',source_quote='all p ≥ .465')
    source_integrity.validate_sources([c],['','all p ≥ .465'],'pdf')
    assert c.source_validation == 'text_anchored'
    duplicate = c.model_copy(update={'claim_id':'duplicate'})
    source_integrity.validate_sources([c,duplicate],['','all p ≥ .465'],'pdf')
    assert all(x.state == 'abstained' for x in [c,duplicate])


def test_source_status_detects_legacy_unresolved_note_even_with_complete_state():
    c = claim(source_validation='text_anchored', extraction={'arbiter_note':'unresolved: bracket invisible'})
    assert not source_integrity.source_status([c])['all_targets_validated']


def test_independent_source_score_counts_both_missed_duplicates_and_wrong_fields():
    gold = [{'source_id':'a','value':.1,'comparator':'='},{'source_id':'b','value':.2,'comparator':'<'}]
    observed = [gold[0],gold[0],{'source_id':'invented','value':.2}]
    score = calibration.score(gold,observed)
    assert score['recall'] == 0 and score['precision'] == 0
    assert score['both_lane_misses_require_gold'] == ['b']
    assert score['duplicates'] == {'a':2}


def test_evidence_anchor_resolves_only_against_the_named_prompt_snapshot():
    sources={'formatted_schema':'x | sd=2.4 (computed column diagnostic)', 'other':'not this source'}
    good={'anchor':'x | sd=2.4 (computed column diagnostic)','source_id':'formatted_schema'}
    bad={**good,'source_id':'other'}
    anchored=review.verify_anchors([good,bad],sources)
    assert anchored[0]['anchor_verified'] and not anchored[1]['anchor_verified']
    assert anchored[0]['source_support'].startswith('located_only')


def test_trace_agreement_does_not_infer_defaults_from_prose():
    traces=[artifacts.ReplicaDecisionTrace(replica_id=rid,ran=True,open_choices=['two-sided t test']) for rid in ['a','b']]
    out,call=match.trace_equivalence('test',traces)
    assert out.agreement is None and call is None
    for t in traces:
        t.execution_evidence={'analyses':{'a1':{'status':'verified','family':'paired_t','alternative':'two-sided','n':20}}}
    out,call=match.trace_equivalence('test',traces)
    assert out.agreement == 1 and call is None
    assert next(f for f in out.fields if f['field']=='x')['unknown'] == ['a','b']


def test_paired_power_is_conditional_on_direction_and_not_reported_effect(tmp_path):
    two=mde.compute(mde.PAIRED,28,script_path=tmp_path/'unused.R',alternative='two-sided')
    greater=mde.compute(mde.PAIRED,28,script_path=tmp_path/'unused.R',alternative='greater')
    less=mde.compute(mde.PAIRED,28,script_path=tmp_path/'unused.R',alternative='less')
    assert two['mde_metric']=='dz' and two['mde_standardised']>greater['mde_standardised']
    assert greater['mde_standardised']==less['mde_standardised']
    with pytest.raises(mde.MdeError,match='explicit group counts'):
        mde.compute(mde.TWO_GROUP,28,script_path=tmp_path/'unused.R')


def paired_plan(tmp_path, delta=(1.,2.,3.,4.)):
    (tmp_path/'data').mkdir(exist_ok=True)
    pd.DataFrame({'id':range(len(delta)),'x':delta,'y':[0.]*len(delta)}).to_csv(tmp_path/'data/data.csv',index=False)
    return {'family':'paired_t','file':'data/data.csv','x':'x','y':'y','alternative':'two-sided',
            'algorithm':'sign_flip','test_statistic':'mean_difference','resampling_unit':'paired_difference'}


def test_sign_flip_reference_matches_hand_enumerated_extreme_cases(tmp_path):
    plan=paired_plan(tmp_path)
    two=reference.resampling_reference(tmp_path,plan)
    one=reference.resampling_reference(tmp_path,{**plan,'alternative':'greater'})
    assert two['exact'] and two['p_raw']==2/16 and one['p_raw']==1/16
    assert reference.resampling_reference(tmp_path,{**plan,'alternative':'less'})['p_raw']==1


def test_bootstrap_requires_a_centred_null_and_has_valid_mc_uncertainty(tmp_path):
    plan=paired_plan(tmp_path)
    plan.update(algorithm='centred_bootstrap',test_statistic='studentized_mean')
    with pytest.raises(ValueError,match='centring'):
        reference.resampling_reference(tmp_path,plan)
    result=reference.resampling_reference(tmp_path,{**plan,'null_centering':'subtract_observed_mean'},draws=5000)
    assert not result['exact'] and 0<result['p_raw']<1
    assert result['interval'][0] <= result['p_raw'] <= result['interval'][1]


def test_reference_mc_check_cannot_be_rescued_by_correct_point_estimates(tmp_path):
    plan=paired_plan(tmp_path)
    plan.update(spec_id='s',implemented_levels={'inference':'flip'})
    (tmp_path/'out').mkdir()
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps({'specs':[plan]}))
    row={'_spec_id':'s','_converged':True,'effect_metric':'mean_difference','_estimate':2.5,'_n':4,
         'inference_method':'monte_carlo','exceedances':9999,'draws':10000,'p_raw':10000/10001}
    spec={'spec_id':'s','levels':{'inference':'flip'},'reference_settings':{k:plan[k] for k in ['algorithm','test_statistic','resampling_unit','alternative']}}
    checked=reference.check(tmp_path,[row],[spec])
    assert checked['status']=='invalid' and any('null-distribution' in e for e in checked['problems'])


def test_correlation_family_validates_named_pairings_and_numeric_parser():
    from reproscope.intake_validation import validate_family
    ct=artifacts.EstimandContract(analysis_id='a',design={'family':'correlation','contrast':'condition pairs','independent_unit':'person','evidence':'source'})
    schema={'files':[{'path':'d.csv','tables':[{'table':None,'columns':[{'name':'pupil','dtype':'object','numeric_parse':{'n_invalid':0,'n_numeric':3,'n_blank':1}},{'name':'v','dtype':'float64'}]}]}]}
    member={'member_id':'40db','file':'d.csv','table':None,'x':'pupil','y':'v','condition':'40db','sample_rule':'complete pairs','evidence':'deposit labels','numeric_parsing':'strict_float_blank_missing'}
    assert validate_family(ct,{'members':[member]},schema)==[]
    assert validate_family(ct,{'members':[{**member,'y':'missing'}]},schema)
    assert validate_family(ct,{'members':[{**member,'numeric_parsing':'strict_float'}]},schema)


def test_nested_likelihood_diagnostic_preserves_input_and_localises_anomaly(tmp_path):
    from reproscope import data_checks
    data=tmp_path/'d.csv'
    data.write_text('restricted,full\n-4,-3\n-2,-5\n')
    before=data.read_bytes()
    manifest=SimpleNamespace(data_files=['d.csv'],path=lambda rel:tmp_path/rel)
    result=data_checks.run(manifest,[{'analysis_id':'a','file':'d.csv','columns':['restricted','full'],'kind':'nested_loglikelihood','assumption_evidence':'documented nesting'}])[0]
    assert result['status']=='anomaly' and result['affected_row_positions']==[1]
    assert data.read_bytes()==before


def test_verifier_sandbox_executes_statistics_but_denies_external_file_and_network(tmp_path):
    from reproscope.isolation import command,clean_environment
    import os
    cmd,receipt=command([sys.executable,'-c',"import socket; from pathlib import Path; Path('ok').write_text('ok'); socket.create_connection(('127.0.0.1', 1))"],tmp_path)
    if not receipt['enforced']:
        pytest.skip(receipt['reason'])
    proc=subprocess.run(cmd,cwd=tmp_path,capture_output=True,text=True,env=clean_environment(dict(os.environ),tmp_path))
    assert (tmp_path/'ok').exists() and proc.returncode != 0
    assert receipt['external_read_canary']=='denied'
    assert 'Operation not permitted' in proc.stderr or 'PermissionError' in proc.stderr


def test_figure_legend_alone_does_not_validate_a_bracket():
    c=claim(location={'page':1,'kind':'figure'},source_quote='p < .001', source_region='figure 1')
    source_integrity.validate_sources([c],['','p < .001'],'pdf')
    assert c.state=='abstained'


def test_shared_figure_legend_does_not_merge_distinct_panels_or_brackets():
    def bracket(cid,panel,endpoints):
        return claim(claim_id=cid,location={'page':1,'kind':'figure'},
            source_region='figure caption significance legend',figure_panel=panel,
            figure_endpoints=endpoints,legend_quote='p < .001',target_contrast='cue comparison',
            extraction={'source_adjudicated':True})
    a=bracket('a','panel a',['none','low'])
    b=bracket('b','panel b',['none','low'])
    c=bracket('c','panel a',['none','high'])
    source_integrity.validate_sources([a,b,c],['','p < .001'],'pdf')
    assert len({x.occurrence_id for x in (a,b,c)})==3
    assert all(x.state=='complete' for x in (a,b,c))
    duplicate=bracket('duplicate','panel a',['low','none'])
    source_integrity.validate_sources([a,duplicate],['','p < .001'],'pdf')
    assert a.occurrence_id==duplicate.occurrence_id
    assert a.state==duplicate.state=='abstained'


@pytest.mark.parametrize('hardcode_n',[False,True])
@pytest.mark.parametrize('explicit_sample',[False,True])
def test_fresh_replica_reference_and_row_removal_detect_literal_n(tmp_path,monkeypatch,hardcode_n,explicit_sample):
    from reproscope.stage1 import replicas
    work=tmp_path/'work';(work/'data').mkdir(parents=True);(work/'out').mkdir()
    pd.DataFrame({'id':range(6),'x':[1,3,4,8,10,11],'y':[0,1,1,2,3,2]}).to_csv(work/'data/d.csv',index=False)
    packet={'analyses':[{'analysis_id':'a','design':{'family':'paired_t','alternative':'two-sided','effect_metric':'t'},
        'variable_bindings':[{'input_columns':['x','y']}],
        'quantities':[{'claim_id':'t','quantity_kind':'t','quantity_role':'inferential'}]}]}
    if explicit_sample:
        packet['analyses'][0]['sample_selection']={'file':'data/d.csv','id_column':'id','included_ids':list(range(6))}
    (work/'CONTRACT.json').write_text(json.dumps(packet))
    script=work/'out/analysis.py'
    script.write_text('''import json
import pandas as pd
from scipy import stats
from pathlib import Path
d=pd.read_csv('data/d.csv')
t=stats.ttest_rel(d.x,d.y)
plan={'analyses':[{'analysis_id':'a','family':'paired_t','file':'data/d.csv','x':'x','y':'y','alternative':'two-sided','id_column':'id','included_ids':d.id.tolist()}]}
Path('out/analysis_plan.json').write_text(json.dumps(plan))
Path('out/results.json').write_text(json.dumps({'results':[{'analysis_id':'a','claim_id':'t','value':float(t.statistic),'n':''' + ('6' if hardcode_n else 'len(d)') + '''}]}))
''')
    subprocess.run([sys.executable,'out/analysis.py'],cwd=work,check=True)
    monkeypatch.setattr(replicas,'prepare_env',lambda *a:{'interpreter':sys.executable,'env':{},'error':None,'log':'','installed':[],'env_dir':None})
    receipt=replicas.rerun_script(work,script,tmp_path)
    assert receipt['results_match_agent']
    evidence=receipt['execution_evidence']
    assert evidence['perturbation']['status']==('failed' if hardcode_n else 'verified')
    removal=next(c for c in evidence['perturbation']['checks'] if c['operation']=='row_removal')
    assert removal['status']==('failed' if hardcode_n else 'verified')
    assert evidence['analyses']['a']['status']==('unverified' if hardcode_n else 'verified')
    assert evidence['perturbation']['per_analysis']['a']['status']==('failed' if hardcode_n else 'verified')
    feedback=replicas.generation_validation(work)
    assert bool(feedback)==hardcode_n
    if hardcode_n:
        assert any('row_removal' in error and 'sample size differs' in error for error in feedback)


def test_last_page_and_casefolded_quantity_identity():
    base=dict(study_id='s1',target_outcome='Speed',target_contrast='High minus Low',target_model='paired t',
              location={'page':2,'kind':'text'})
    a=claim(**base)
    b=claim(**{**base,'claim_id':'b','target_outcome':'speed','target_contrast':'high minus low','target_model':'Paired T'})
    source_integrity.validate_sources([a],['','Other page','p < .001'],'pdf')
    source_integrity.validate_sources([b],['','Other page','p < .001'],'pdf')
    assert a.source_validation=='text_anchored' and a.quantity_id==b.quantity_id


def test_complete_visual_evidence_without_note_and_fabricated_legend():
    kwargs=dict(location={'page':1,'kind':'figure'},source_region='figure 1',target_contrast='a minus b',
                figure_panel='A',figure_endpoints=['a','b'],legend_quote='p < .001',
                extraction={'source_adjudicated':True,'arbiter_note':None})
    a=claim(**kwargs)
    source_integrity.validate_sources([a],['','Legend: p < .001'],'pdf')
    assert a.source_validation=='visual_adjudicated'
    b=claim(**kwargs)
    source_integrity.validate_sources([b],['','Legend: p < .05'],'pdf')
    assert b.state=='abstained'


def test_keep_cannot_silently_correct_a_value():
    res=arbitrate.Resolution(slim(),'A')
    arbitrate.apply_decision(res,arbitrate.ArbitrationItem(item_id='i',decision='keep',corrected_claim=slim(value=.9)))
    assert res.unresolved and res.claim.value==.001


def test_missing_results_and_unauthorised_sample_do_not_verify(tmp_path):
    from reproscope.execution_evidence import check_replica
    plan=paired_plan(tmp_path)
    plan.update(analysis_id='a',id_column='id',included_ids=[0,1,2])
    (tmp_path/'out').mkdir()
    doc={'analyses':[plan]}
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps(doc))
    packet={'analyses':[{'analysis_id':'a','design':{'family':'paired_t','alternative':'two-sided'},
                        'variable_bindings':[{'input_columns':['x','y']}],
                        'quantities':[{'claim_id':'t','quantity_kind':'t'}]}]}
    assert check_replica(tmp_path,packet)['status']=='unverified'
    result=reference.from_plan(tmp_path,plan)
    (tmp_path/'out/results.json').write_text(json.dumps({'results':[{'analysis_id':'a','claim_id':'t','value':result['t'],'n':3}]}))
    verified=check_replica(tmp_path,packet,regenerated_plan=doc)
    assert verified['status']=='invalid'
    assert 'sample' in ' '.join(verified['analyses']['a']['problems'])


def test_fresh_copy_cannot_reuse_stale_outputs(tmp_path):
    from reproscope.execution import copy_inputs
    work=tmp_path/'work';fresh=tmp_path/'fresh'
    (work/'out').mkdir(parents=True)
    (work/'out/results.json').write_text('{"results":[]}')
    (work/'out/analysis_plan.json').write_text('{}')
    (work/'out/analysis.py').write_text('pass')
    copy_inputs(work,fresh)
    assert (fresh/'out/analysis.py').exists()
    assert not (fresh/'out/results.json').exists() and not (fresh/'out/analysis_plan.json').exists()


def test_review_diagnostic_requires_a_known_executed_record():
    source={'schema':'The column skewness is 2.4.'}
    findings=[{'anchor':source['schema'],'source_id':'schema','diagnostic_ids':['d']},
              {'anchor':source['schema'],'source_id':'schema','diagnostic_ids':['invented']}]
    rows=review.verify_anchors(findings,source,{'d':{'status':'computed','values':{'skewness':2.4}}})
    assert rows[0]['diagnostic_status']=='executed'
    assert rows[1]['diagnostic_status']=='unknown_reference'
    assert rows[0]['source_support'].startswith('located_only')


def test_semantic_report_cannot_pass_an_all_rejected_run(tmp_path):
    source=tmp_path/'stage0';source.mkdir()
    source.joinpath('claims.json').write_text(json.dumps([claim(source_validation='text_anchored').model_dump()]))
    stage3=tmp_path/'stage3';stage3.mkdir()
    stage3.joinpath('space.json').write_text('{"state":"abstained"}')
    replica=tmp_path/'stage1/replicas/r';replica.mkdir(parents=True)
    replica.joinpath('trace.json').write_text(json.dumps({'replica_id':'r','ran':True,
        'hardcoding_audit':{'adjudication':{'decision':'rejected','reason':'known literal'}}}))
    status=source_integrity.review_run(tmp_path)
    assert not status['semantic_ready'] and 'no accepted executed replica' in status['semantic_blockers']


def test_verifier_denies_writes_outside_work(tmp_path):
    from reproscope.isolation import command,clean_environment
    import os,tempfile
    with tempfile.TemporaryDirectory(prefix='reproscope_external_write_') as outside:
        target=Path(outside)/'must_not_exist'
        cmd,receipt=command([sys.executable,'-c','from pathlib import Path; import sys; Path(sys.argv[1]).write_text("bad")',str(target)],tmp_path)
        if not receipt['enforced']:
            pytest.skip(receipt['reason'])
        proc=subprocess.run(cmd,cwd=tmp_path,capture_output=True,env=clean_environment(dict(os.environ),tmp_path))
        assert proc.returncode != 0 and not target.exists()


def test_quote_cannot_support_wrong_statistic_or_printed_precision():
    wrong_kind=claim(value=4.2,comparator='=',source_quote='t = 4.20, p = .001')
    wrong_precision=claim(precision=2)
    source_integrity.validate_sources([wrong_kind],['','t = 4.20, p = .001'],'pdf')
    source_integrity.validate_sources([wrong_precision],['','p < .001'],'pdf')
    assert wrong_kind.state=='abstained' and wrong_precision.state=='abstained'


def test_disputed_model_label_cannot_create_a_second_source_occurrence():
    a=claim(target_model='2 x 3',source_quote='p < .001')
    b=claim(claim_id='b',target_model='3 x 3',source_quote='The result was p < .001')
    source_integrity.validate_sources([a,b],['','The result was p < .001'],'pdf')
    assert a.occurrence_id==b.occurrence_id
    assert a.state==b.state=='abstained'


def test_full_legacy_candidate_context_retains_known_pairs_and_exposes_ambiguity():
    fixture=json.loads((Path(__file__).parent/'fixtures/extraction_full_candidates.json').read_text())
    signatures=[]
    for seed in (1,2,3):
        a=ClaimList(**fixture['a']);b=ClaimList(**fixture['b'])
        random.Random(seed).shuffle(a.claims);random.Random(seed+10).shuffle(b.claims)
        rows=arbitrate.partition(a,b)
        signatures.append(sorted((r.source,r.claim.claim_id,r.rival.claim_id if r.rival else '') for r in rows))
        assert {f'c{n:03d}' for n in (8,9,10,11,12,13,16,17,18)} <= {r.claim.claim_id for r in rows if r.agreed}
        assert ('conflict','c120','c094') in signatures[-1]
        # The legacy B description omits its outcome. Several A records are
        # plausible; equal p-values must not resolve that missing context.
        assert ('A','c063','') in signatures[-1] and ('B','c052','') in signatures[-1]
    assert signatures[0]==signatures[1]==signatures[2]


def test_model_wire_schema_enforces_evidence_without_internal_open_maps():
    from reproscope.llm import schema_payload
    from reproscope.stage0.extract import ModelClaimList
    from pydantic import ValidationError
    assert schema_payload(ModelClaimList)[1]
    assert schema_payload(arbitrate.ArbitrationBatch)[1]
    with pytest.raises(ValidationError):
        ModelClaimList.model_validate({'claims':[{'claim_id':'c','value':28}], 'regions':[]})


def test_chunk_coverage_requires_page_and_claim_inventory_consistency():
    from reproscope.stage0.extract import coverage_errors
    bad=ClaimList(claims=[slim()],regions=[{'page':2,'kind':'text','region_id':'r','status':'complete','claim_ids':['c']}])
    assert coverage_errors(bad,2)
    good=ClaimList(claims=[slim()],regions=[{'page':1,'kind':'text','region_id':'r','status':'complete','claim_ids':['c']}])
    assert coverage_errors(good,1)==[]


def test_anchored_identity_survives_wrong_value_operator_and_semantic_labels():
    quote='processing speed v, t(27) = 4.71, p < 0.001'
    a=slim(quantity_kind='t',value=4.71,comparator='=',precision=2,source_quote=quote,
           target_outcome='visual_processing_speed',target_model='paired t-test')
    b=slim(claim_id='b',quantity_kind='t',value=4.72,comparator='<',precision=2,source_quote=quote,
           target_outcome='processing_speed',target_model='TVA parameter comparison')
    rows=arbitrate.partition(ClaimList(claims=[a]),ClaimList(claims=[b]),['',quote])
    assert len(rows)==1 and rows[0].source=='conflict'
    assert rows[0].claim.value==4.71 and rows[0].rival.value==4.72


def test_different_anchored_occurrences_cannot_be_joined_by_labels():
    a=slim(source_quote='First comparison: p < .001')
    b=slim(claim_id='b',source_quote='Second comparison: p < .001')
    text='First comparison: p < .001. Second comparison: p < .001.'
    rows=arbitrate.partition(ClaimList(claims=[a]),ClaimList(claims=[b]),['',text])
    assert len(rows)==2 and all(not r.agreed for r in rows)


def test_pdf_punctuation_spacing_and_sentence_final_value_are_supported():
    c=claim(source_quote='The result, p < .001.')
    source_integrity.validate_sources([c],['','The result , p < .001.'],'pdf')
    assert c.source_validation=='text_anchored'


def test_unanchored_sibling_degrees_of_freedom_cannot_pair():
    a=slim(quantity_kind='t',source_quote='The result was t(27) = 4.71, p < .001')
    b=slim(claim_id='b',quantity_kind='t',source_quote='The result was t(31) = 2.10, p = .045')
    assert len(arbitrate.partition(ClaimList(claims=[a]),ClaimList(claims=[b]))) == 2


def test_known_position_must_lie_in_other_quotes_possible_spans():
    a=slim(source_quote='First comparison: p < .001')
    b=slim(claim_id='b',source_quote='Second comparison: p < .001')
    text='First comparison: p < .001. Second comparison: p < .001. Second comparison: p < .001.'
    assert len(arbitrate.partition(ClaimList(claims=[a]),ClaimList(claims=[b]),['',text])) == 2


def test_pairing_diagnostics_separate_numeric_and_semantic_disputes():
    a=slim(source_quote='First comparison: p < .001',target_model='paired t')
    b=a.model_copy(update={'claim_id':'b','target_model':'paired t-test'})
    d=arbitrate.pairing_diagnostics(ClaimList(claims=[a]),ClaimList(claims=[b]),['',a.source_quote])
    assert d['n_source_pairs']==d['n_transcription_agreed']==1
    assert d['n_semantic_agreed']==0 and d['field_disputes']['target_model']==1


def test_uppercase_f_kind_cannot_anchor_a_neighbouring_t_statistic():
    c=claim(quantity_kind='F',value=4.2,precision=2,comparator='=',source_quote='t = 4.20, p = .001')
    source_integrity.validate_sources([c],['',c.source_quote],'pdf')
    assert c.state=='abstained'


def test_vector_reference_plan_is_unverified_without_crashing(tmp_path):
    from reproscope.execution_evidence import check_replica
    (tmp_path/'out').mkdir()
    doc={'analyses':[dict(analysis_id='a',family='correlation',file='data/d.csv',x=['x1','x2'],y=['y1','y2'])]}
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps(doc))
    (tmp_path/'out/results.json').write_text('{"results":[]}')
    result=check_replica(tmp_path,{'analyses':[{'analysis_id':'a'}]},regenerated_plan=doc)
    assert result['analyses']['a']['status']=='unverified'
    assert 'scalar' in result['analyses']['a']['reason']


def test_legacy_plan_normalisation_is_closed_and_keeps_unknown_prose_unsupported():
    from reproscope.plan_protocol import normalise
    raw=dict(family='paired_t',x='x',y='y',transformations=['d = x - y; dz = mean(d)/sd(d)'],
             missingness='strict float parsing; blank/whitespace -> missing; complete pairs only')
    plan,receipt,unsupported=normalise(raw)
    assert not unsupported and plan['transformations']==[] and plan['missingness']=='complete_cases'
    assert raw['transformations']  # Original model output is not rewritten.
    assert receipt['rules']
    assert normalise({**raw,'transformations':['d = y - x; dz = mean(d)/sd(d)']})[2]
    assert normalise({**raw,'missingness':'drop inconvenient cases'})[2]


def test_reference_explicit_blank_parser_preserves_real_errors(tmp_path):
    p=paired_plan(tmp_path)
    p.update(missingness='complete_cases',numeric_parsing='strict_float_blank_missing')
    file=tmp_path/p['file']; file.write_text('id,x,y\n0,1,2\n1, ,3\n2,4,2\n3,6,5\n')
    assert reference.from_plan(tmp_path,p)['n']==3
    file.write_text('id,x,y\n0,1,2\n1,broken,3\n2,4,2\n3,6,5\n')
    with pytest.raises(ValueError):reference.from_plan(tmp_path,p)


def test_sandbox_allows_invoked_venv_not_only_resolved_python(tmp_path):
    from reproscope.isolation import command,clean_environment
    import os
    envdir=tmp_path/'runtime';work=tmp_path/'work';work.mkdir()
    subprocess.run([sys.executable,'-m','venv','--without-pip',str(envdir)],check=True)
    python=envdir/'bin/python'
    cmd,receipt=command([str(python),'-c','import sys; print(sys.prefix)'],work)
    if not receipt['enforced']:pytest.skip(receipt['reason'])
    result=subprocess.run(cmd,cwd=work,capture_output=True,text=True,env=clean_environment(dict(os.environ),work))
    assert result.returncode==0,result.stderr
    assert str(envdir) in result.stdout
    assert str(envdir.resolve()) in receipt['runtime_read_roots']
    assert receipt['external_read_canary']=='denied'


def test_closed_plan_rejects_prose_and_unsupported_substitutions():
    from reproscope.plan_protocol import PlanDocument
    from pydantic import ValidationError
    p = dict(analysis_id='a', status='supported', family='paired_t', file='data/d.csv',
             table=None, header=0, x='x', y='y', id_column=None, included_ids=None,
             equal_var=True, alternative='two-sided', transformations=[], missingness='complete_cases',
             numeric_parsing='strict_float_blank_missing', group_column=None, group_values=None, contrast='x minus y')
    def doc(plan): return {'protocol_version':'direct-plan-2', 'analyses':[plan]}
    assert PlanDocument.model_validate(doc(p)).analyses[0].family == 'paired_t'
    for change in ({'missingness':'not stated'}, {'transformations':['baseline subtraction']},
                   {'family':'mixed_model'}, {'y':['y1','y2']}, {'file':'../secret.csv'},
                   {'included_ids':[1,1], 'id_column':'id'}, {'alternative':'unknown'},
                   {'extra_prose':'none'}, {'header':1}):
        with pytest.raises(ValidationError): PlanDocument.model_validate(doc({**p,**change}))
    assert PlanDocument.model_validate(doc({'analysis_id':'a','status':'unsupported','reason':'mixed model'}))
    with pytest.raises(ValidationError): PlanDocument.model_validate(doc({'analysis_id':'a','status':'unsupported','reason':''}))
    with pytest.raises(ValidationError):
        PlanDocument.model_validate({'protocol_version':'direct-plan-2','analyses':[p,p]})


def test_versioned_plan_failure_is_not_a_numerical_mismatch(tmp_path):
    from reproscope.execution_evidence import check_replica
    (tmp_path/'out').mkdir()
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps({'protocol_version':'direct-plan-2',
        'analyses':[{'analysis_id':'a','status':'supported','missingness':'not stated'}]}))
    (tmp_path/'out/results.json').write_text('{"results":[]}')
    result=check_replica(tmp_path,{'analyses':[{'analysis_id':'a'}]})
    assert result['status']=='unverified'
    assert not result['analyses']
    assert 'validation error' in result['reason']


def test_verifier_drops_launcher_python_paths_for_package_inventory(tmp_path):
    import os
    from reproscope import isolation, replica_env
    if not Path(replica_env.base_python()).exists():
        pytest.skip('replica environment not installed')
    denied=tmp_path/'outside';denied.mkdir()
    work=tmp_path/'work';work.mkdir()
    cmd, receipt=isolation.command([replica_env.base_python(),'-m','pip','freeze'],work)
    if not receipt['enforced']: pytest.skip(receipt['reason'])
    env=isolation.clean_environment({**os.environ,'PYTHONPATH':str(denied),'PYTHONHOME':'/invalid'},work)
    assert 'PYTHONPATH' not in env and 'PYTHONHOME' not in env
    result=subprocess.run(cmd,cwd=work,capture_output=True,text=True,env=env)
    assert result.returncode==0, result.stderr
    assert 'numpy==' in result.stdout


def test_correlation_aggregate_uses_exact_members_and_declared_minimum():
    rows={'results':[{'claim_id':'c','analysis_id':'a','value':[.4,-.2,.7],'member_ids':['x','y','z']}]}
    result=match.direct_link('c',json.dumps(rows),quantity_kind='r',comparator='>',aggregation='min',member_ids=['x','y','z'])
    assert result.found and result.value==-.2
    rows['results'][0]['value'][0]=1.2
    assert match.direct_link('c',json.dumps(rows),quantity_kind='r',comparator='>',aggregation='min',member_ids=['x','y','z']).error_kind=='invalid'


def test_fresh_results_comparison_preserves_nested_member_evidence():
    from reproscope.execution import result_fields,equal
    original={'results':[{'analysis_id':'a','claim_id':'c','value':.1,'members':[{'member_id':'m','value':.2}]}]}
    changed=json.loads(json.dumps(original));changed['results'][0]['members'][0]['value']=.9
    assert not equal(result_fields(original),result_fields(changed))


def physical_layout():
    from reproscope.source_layout import parse_bbox
    return parse_bbox('''<html><page width="100" height="200"><line>
    <word xMin="1" yMin="2" xMax="4" yMax="6">p</word>
    <word xMin="5" yMin="2" xMax="7" yMax="6">&lt;</word>
    <word xMin="8" yMin="2" xMax="15" yMax="6">.001</word>
    </line></page></html>''','pdf')


@pytest.mark.parametrize('changes',[{'value':.01},{'comparator':'='},{'precision':2},{'quantity_kind':'t'},{'source_token_id':'invented'},{'location':{'page':2,'kind':'text'}}])
def test_physical_identity_cannot_authorise_wrong_transcription(changes):
    layout=physical_layout()
    token=layout['pages'][0]['numeric_candidates'][0]['source_token_id']
    c=claim(**{'source_token_id':token,'precision':3,**changes})
    source_integrity.validate_sources([c],['','p < .001','p < .001'],'pdf',layout=layout)
    assert c.source_validation=='unresolved'


def test_physical_transcription_does_not_need_a_reconstructed_full_sentence():
    layout=physical_layout();token=layout['pages'][0]['numeric_candidates'][0]['source_token_id']
    c=claim(source_token_id=token,source_quote='The page image has damaged surrounding text.',precision=3)
    source_integrity.validate_sources([c],['','unreadable surrounding text'],'pdf',layout=layout)
    assert c.source_validation=='text_anchored'
    assert 'semantic association requires separate validation' in c.source_anchor_scope
    d=c.model_copy(update={'claim_id':'other','target_model':'different interpretation'})
    source_integrity.validate_sources([c,d],['','unreadable surrounding text'],'pdf',layout=layout)
    assert all(x.source_validation=='unresolved' for x in [c,d])


def test_annotation_identity_pairs_differing_readings_before_semantics():
    a=slim(source_token_id='p001:annotation:marker',figure_panel='A')
    b=slim(source_token_id='p001:annotation:marker',figure_panel='panel one',value=.01)
    assert arbitrate._candidate(a,b,False)==200
    assert arbitrate._candidate(a,b,True) is None
    assert arbitrate._candidate(a,b.model_copy(update={'source_token_id':'different'}),False) is None


def test_split_statistic_symbol_requires_image_adjudication_and_preserves_operator():
    from reproscope.source_layout import parse_bbox
    layout=parse_bbox('<html><page width="100" height="200"><line><word xMin="1" yMin="2" xMax="8" yMax="6">(24)</word><word xMin="9" yMin="2" xMax="12" yMax="6">=</word><word xMin="13" yMin="2" xMax="22" yMax="6">2.61</word></line></page></html>','pdf')
    token=layout['pages'][0]['numeric_candidates'][-1]['source_token_id']
    def make(**kw):return claim(**{'quantity_kind':'t','value':2.61,'comparator':'=','precision':2,'source_token_id':token,'source_quote':'t(24) = 2.61',**kw})
    ordinary=make();checked=make(extraction={'source_adjudicated':True});wrong=make(comparator='<=',source_quote='t(24) <= 2.61',extraction={'source_adjudicated':True})
    for c in [ordinary,checked,wrong]:source_integrity.validate_sources([c],['','(24) = 2.61'],'pdf',layout=layout)
    assert ordinary.source_validation=='unresolved'
    assert checked.source_validation=='visual_adjudicated'
    assert wrong.source_validation=='unresolved'


@pytest.mark.parametrize('computed', [False, True])
def test_unavailable_plan_placeholder_never_counts_as_computation(tmp_path, computed):
    from reproscope.execution_evidence import check_replica
    (tmp_path/'out').mkdir()
    doc={'analyses':[{'analysis_id':'missing','status':'unsupported'}]}
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps(doc))
    (tmp_path/'out/results.json').write_text(json.dumps({'results':[{'analysis_id':'missing','value':1}] if computed else []}))
    packet={'analyses':[], 'analyses_without_data':['missing']}
    result=check_replica(tmp_path,packet,regenerated_plan=doc)
    assert (result['status']=='invalid') == computed
    assert not result['analyses']


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS verifier integration')
def test_canary_uses_the_same_clean_environment_as_execution(tmp_path, monkeypatch):
    import os
    from reproscope import isolation
    work=tmp_path/'work';work.mkdir()
    monkeypatch.setenv('PYTHONPATH','.')
    monkeypatch.setenv('PYTHONHOME','/intentionally-invalid-python-home')
    command, receipt=isolation.command([sys.executable,'-c','print("executed")'],work)
    result=subprocess.run(command,cwd=work,capture_output=True,text=True,
        env=isolation.clean_environment(dict(os.environ),work))
    assert result.returncode==0,result.stderr
    assert result.stdout.strip()=='executed'
    assert receipt['external_read_canary']=='denied'


def test_one_correct_output_cannot_verify_an_incomplete_analysis(tmp_path):
    from reproscope.execution_evidence import check_replica
    plan=paired_plan(tmp_path)
    for key in ('algorithm','test_statistic','resampling_unit'):plan.pop(key)
    plan['analysis_id']='a'
    (tmp_path/'out').mkdir()
    doc={'analyses':[plan]}
    (tmp_path/'out/analysis_plan.json').write_text(json.dumps(doc))
    packet={'analyses':[{'analysis_id':'a','design':{'family':'paired_t','alternative':'two-sided'},
        'variable_bindings':[{'input_columns':['x','y']}],
        'quantities':[{'claim_id':'t','quantity_kind':'t'},{'claim_id':'p','quantity_kind':'p_value'}]}]}
    result=reference.from_plan(tmp_path,plan)
    rows=[{'analysis_id':'a','claim_id':'t','value':result['t']}]
    (tmp_path/'out/results.json').write_text(json.dumps({'results':rows}))
    partial=check_replica(tmp_path,packet,regenerated_plan=doc)
    assert partial['status']=='invalid'
    assert 'Missing requested computed values: p' in partial['analyses']['a']['problems']
    rows.append({'analysis_id':'a','claim_id':'p','value':result['p_raw']})
    (tmp_path/'out/results.json').write_text(json.dumps({'results':rows}))
    assert check_replica(tmp_path,packet,regenerated_plan=doc)['status']=='verified'

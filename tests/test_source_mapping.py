from reproscope.source_mapping import TermMapping, UnassignedClaim, mapping_errors, mapped, unassigned_errors
from reproscope.stage0.extract import SlimClaim


def test_alias_requires_exact_scoped_source_and_located_evidence():
    c=SlimClaim(claim_id='c',study_id='s1',target_outcome='visual_processing_speed')
    q='We compared processing speed between the two conditions.'
    m=TermMapping(field='outcome',study_id='s1',source_text=c.target_outcome,
                  canonical='processing_speed',quote=q,note='Same measured outcome in this study.')
    assert mapping_errors([m],[c],q)==[] and mapped(c,'outcome','processing_speed',[m])
    assert not mapped(c,'outcome','threshold',[m])
    assert mapping_errors([m],[c],'No such passage')
    assert mapping_errors([m,m],[c],q)
    assert mapping_errors([m.model_copy(update={'study_id':'s2'})],[c],q)


def test_alias_cannot_erase_different_design_levels():
    q='The design used intensity and condition as repeated factors.'
    for source,canonical in [('40 dB vs 85 dB','60 dB vs 85 dB'),('2 x 3 ANOVA','3 x 3 ANOVA'),('Experiment 1 paired t','Experiment 2 paired t')]:
        c=SlimClaim(claim_id='c',study_id='s1',target_model=source)
        m=TermMapping(field='model',study_id='s1',source_text=source,canonical=canonical,quote=q,note='Claimed alias')
        assert any('design levels' in e for e in mapping_errors([m],[c],q))


def test_contrast_aliases_can_share_a_destination_without_changing_levels():
    q='We compared the no cue and 40 dB cue conditions.'
    cs=[SlimClaim(claim_id=str(i),study_id='s1',target_contrast=s) for i,s in enumerate(['no cue vs 40 dB cue','40 dB cue versus no cue'])]
    ms=[TermMapping(field='contrast',study_id='s1',source_text=c.target_contrast,canonical='no cue versus 40 dB cue',quote=q,note='The same pair; direction is resolved separately.') for c in cs]
    assert not mapping_errors(ms,cs,q)


def test_abstention_is_exclusive_and_requires_an_explanation():
    c=SlimClaim(claim_id='c')
    q='The procedure for this analysis is not described.'
    u=UnassignedClaim(claim_id='c',reason='methods_insufficient',note='Missing required procedure.',quote=q)
    assert not unassigned_errors([u],[c],set(),q)
    assert unassigned_errors([u],[c],{'c'},q)
    assert unassigned_errors([u,u],[c],set(),q)
    assert unassigned_errors([u],[c],set(),'unrelated')


def test_contract_accepts_evidenced_alias_and_explicit_assignment_abstention():
    from reproscope.artifacts import ClaimRecord
    from reproscope.stage0.contracts import AnalysisIdentity, SlimContract, validate_assignments
    c=ClaimRecord(claim_id='c',study_id='s1',quantity_kind='t',target_outcome='visual speed',state='complete')
    q='We compared visual processing speed between conditions.'
    ct=SlimContract(analysis_id='a',study_id='s1',claim_ids=['c'],identity=AnalysisIdentity(study='s1',outcome='processing_speed',contrast='cue_vs_none',model='paired_t',sample='complete_pairs'))
    m=TermMapping(field='outcome',study_id='s1',source_text='visual speed',canonical='processing_speed',quote=q,note='The same outcome.')
    assert validate_assignments([ct],[c])
    assert not validate_assignments([ct],[c],[m],[],q)
    u=UnassignedClaim(claim_id='c',reason='methods_insufficient',quote=q,note='Sample selection cannot be identified.')
    assert not validate_assignments([], [c], [], [u], q)
    assert validate_assignments([ct], [c], [m], [u], q)


def test_required_assignment_abstention_blocks_semantic_readiness(tmp_path):
    import json
    from reproscope.source_integrity import review_run
    d=tmp_path/'stage0';d.mkdir()
    (d/'claims.json').write_text(json.dumps([{'claim_id':'c','state':'complete','quantity_role':'inferential','source_validation':'text_anchored'}]))
    (d/'contract_assignments.json').write_text(json.dumps({'unassigned':[{'claim_id':'c','reason':'methods_insufficient','note':'Unknown sample'}]}))
    assert any('lack analysis assignments' in b for b in review_run(tmp_path)['semantic_blockers'])


def test_canonical_key_punctuation_cannot_hide_model_arithmetic_conflicts():
    from reproscope.source_mapping import compatible_design
    assert not compatible_design('3 × 4 model versus 2 × 3 model','tva_lrt_3_plus_4_vs_2_x_3')
    assert not compatible_design('2 x 3 ANOVA','3_x_3_anova')
    assert compatible_design('Experiment 1 paired t test','study_1_paired_t')
    assert compatible_design('40 dB cue vs no cue','no_cue_vs_40_dB_cue')


def test_contract_projection_excludes_invalid_sources_without_erasing_audit_records():
    from reproscope.artifacts import ClaimRecord
    from reproscope.stage0.contracts import claims_without_values
    good=ClaimRecord(claim_id='good',quantity_kind='t',source_quote='t(27) = 4.71',value=4.71,state='complete')
    bad=good.model_copy(update={'claim_id':'bad','state':'abstained','abstain_reason':'unresolved source'})
    rows=claims_without_values([good,bad])
    assert [r['claim_id'] for r in rows]==['good']
    assert 'value' not in rows[0] and rows[0]['source_quote']==good.source_quote
    assert bad.state=='abstained' and bad.abstain_reason=='unresolved source'


def test_projection_removes_ineligible_assignments_and_keeps_unknown_ids_for_rejection():
    from reproscope.artifacts import ClaimRecord
    from reproscope.stage0.contracts import ContractsAndMethods,SlimContract,project_eligible
    bad=ClaimRecord(claim_id='bad',state='abstained',study_id='s',target_model='wrong model')
    mapping=TermMapping(field='model',study_id='s',source_text='wrong model',canonical='m',quote='Evidence in a paper',note='Claimed mapping')
    old=ContractsAndMethods(contracts=[SlimContract(analysis_id='a',claim_ids=['bad','unknown'])],term_map=[mapping],redacted_methods='Methods')
    new=project_eligible(old,[bad])
    assert new.contracts[0].claim_ids==['unknown'] and new.term_map==[]
    assert old.contracts[0].claim_ids==['bad','unknown'] and new.redacted_methods=='Methods'


def test_missing_model_placeholder_cannot_create_an_alias_or_a_conflict():
    from reproscope.source_mapping import missing_term
    c=SlimClaim(claim_id='c',study_id='s',target_model='none')
    assert missing_term('Not stated') and not missing_term('none versus cue')
    assert mapped(c,'model','correlation',[])
    u=UnassignedClaim(claim_id='c',reason='sources_conflict',conflict_field='model',quote='The outcome was measured.',note='Model none differs.')
    assert any('not evidence of a conflict' in e for e in unassigned_errors([u],[c],set(),u.quote))


def test_ordered_source_excerpts_tolerate_pdf_spacing_but_not_changed_signs():
    from reproscope.source_mapping import quotation_located
    paper='Results and discussion (Study 2c). Other sentences. A paired test yielded t 35 = -1.01.'
    quote='Results and discussion (Study 2c) ... A paired test yielded t35 = -1.01.'
    assert quotation_located(quote,paper)
    assert not quotation_located(quote.replace('-1.01','1.01'),paper)
    assert not quotation_located('A paired test yielded t35 = -1.01. ... Results and discussion (Study 2c)',paper)


def test_same_phrase_can_resolve_differently_in_disjoint_source_occurrences():
    q='Both measures were included in the source study.'
    cs=[SlimClaim(claim_id=str(i),study_id='s',target_outcome='strategy') for i in range(2)]
    maps=[TermMapping(field='outcome',study_id='s',source_text='strategy',canonical=f'measure{i}',claim_ids=[str(i)],quote=q,note='Located occurrence-specific interpretation.') for i in range(2)]
    assert not mapping_errors(maps,cs,q)
    assert mapped(cs[0],'outcome','measure0',maps)
    assert not mapped(cs[1],'outcome','measure0',maps)
    assert mapping_errors([maps[0],maps[1].model_copy(update={'claim_ids':[]})],cs,q)


def test_correlation_pair_symmetry_preserves_model_and_covariates():
    from reproscope.artifacts import ClaimRecord
    from reproscope.stage0.contracts import SlimContract,AnalysisIdentity,validate_assignments
    c=ClaimRecord(claim_id='c',study_id='s',quantity_kind='r',state='complete',target_outcome='y',target_contrast='x',target_model='partial')
    a=SlimContract(analysis_id='a',study_id='s',claim_ids=['c'],covariates=['age'],
        design={'family':'correlation','contrast':'x with y','independent_unit':'participant','evidence':'Correlation controlling age.'},
        identity=AnalysisIdentity(study='s',outcome='x',contrast='y',model='partial',sample='complete'))
    assert not validate_assignments([a],[c])
    assert validate_assignments([a],[c.model_copy(update={'target_model':'unadjusted'})])


def test_projected_scoped_alias_never_becomes_a_global_alias():
    from reproscope.artifacts import ClaimRecord
    from reproscope.stage0.contracts import ContractsAndMethods,project_eligible
    bad=ClaimRecord(claim_id='bad',state='abstained',study_id='s',target_outcome='strategy')
    good=bad.model_copy(update={'claim_id':'good','state':'complete'})
    mapping=TermMapping(field='outcome',study_id='s',source_text='strategy',canonical='measure',claim_ids=['bad'],quote='The source is contextual.',note='This occurrence only.')
    result=project_eligible(ContractsAndMethods(term_map=[mapping],redacted_methods='Methods'),[bad,good])
    assert not result.term_map

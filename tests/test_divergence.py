import json
from reproscope import divergence


def test_signed_paired_agreement_does_not_create_a_false_divergence():
    r=dict(band='A',exact_reported_precision=False,magnitude_exact_reported_precision=True,
           comparison_basis='paired magnitude and source qualitative direction',replicated=-3.523,reported=3.52)
    assert divergence.row_reason(r) is None
    r['magnitude_exact_reported_precision']=False
    assert divergence.row_reason(r)=='precision_mismatch'
    assert divergence.row_reason(dict(band='B',comparison_basis=None))=='numerical_mismatch'


def test_all_analyses_descriptives_and_limits_are_covered(tmp_path,monkeypatch):
    def save(name,obj):
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(obj))
    claims=[dict(claim_id=f'c{i}') for i in range(1,6)]
    save('stage0/claims.json',claims)
    save('stage0/contracts.json',[dict(analysis_id='a2',claim_ids=['c1','c2'])])
    rows=[dict(claim_id=cid,replica_id=rid,analysis_id='a2',band='fail',reported=10,replicated=30)
          for cid in ('c1','c2') for rid in ('r1','r2')]
    save('stage1/match.json',dict(rows=rows))
    save('stage1/descriptive/report.json',dict(results=[dict(claim_id='c3',verification='verified',matches_printed_rounding=False,value=.05,reported_value=.5)]))
    from reproscope import computation_coverage
    monkeypatch.setattr(computation_coverage,'review',lambda root:dict(rows=[dict(claim_id='c4',status='unavailable',reason='not deposited'),dict(claim_id='c5',status='invalid_input',reason='invalid likelihood')]))
    inv=divergence.inventory(tmp_path)
    assert inv['n_claims']==5 and inv['n_groups']==4
    group=next(g for g in inv['groups'] if g['analysis_id']=='a2')
    assert group['claim_ids']==['c1','c2'] and len(group['evidence'])==4
    diagnoses=[dict(group_id=g['group_id']) for g in inv['groups']]
    save('stage1/diagnosis.json',dict(status='complete',inventory_fingerprint=inv['fingerprint'],diagnoses=diagnoses))
    assert divergence.coverage_status(tmp_path)['complete']
    save('stage1/diagnosis.json',dict(status='complete',inventory_fingerprint=inv['fingerprint'],diagnoses=diagnoses[:-1]))
    assert not divergence.coverage_status(tmp_path)['complete']


def test_unknown_direction_and_rounded_bounds_are_qualified():
    assert divergence.row_reason(dict(outcome_status='direction_unverified'))=='direction_unstated'
    assert divergence.row_reason(dict(bound_rounding_compatible=True,bound_satisfied=False))=='rounding_boundary'


def test_diagnosis_batches_cover_all_groups_without_unrelated_plans(tmp_path):
    from reproscope.stage1.diagnose import diagnosis_batches
    root=tmp_path/'stage1/replicas/r';root.mkdir(parents=True)
    (root/'trace.json').write_text(json.dumps({'execution_evidence':{'analyses':{f'a{i}':{'evidence':'x'*1000} for i in range(8)}}}))
    inv={'groups':[dict(group_id=f'g{i}',analysis_id=f'a{i}',kind='numerical_mismatch',claim_ids=[],claims=[],evidence=[],contract={}) for i in range(8)]}
    batches=list(diagnosis_batches(tmp_path,inv,[f'g{i}' for i in range(8)],max_chars=3000))
    assert len(batches)>1
    assert [g for ids,_ in batches for g in ids]==[f'g{i}' for i in range(8)]
    for ids,sources in batches:
        replica=json.loads(sources['replica:r'])
        assert set(replica['verification'])=={'a'+g[1:] for g in ids}


def test_diagnosis_repairs_only_unanchored_groups(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from reproscope.stage1 import diagnose as m
    stage=tmp_path/'stage1';stage.mkdir()
    groups=[dict(group_id=f'g{i}',analysis_id=f'a{i}',kind='numerical_mismatch',claim_ids=[f'c{i}'],
        claims=[{'claim_id':f'c{i}'}],evidence=[{'claim_id':f'c{i}','reported':1,'replicated':2,'rule':'mismatch'}],contract={}) for i in (1,2)]
    inv={'groups':groups,'fingerprint':'fixed','n_groups':2,'n_claims':2}
    monkeypatch.setattr(m.paths,'run_dir',lambda *args:stage)
    monkeypatch.setattr(m,'key',lambda _: {'fixture':'fixed'})
    monkeypatch.setattr(m.divergence,'inventory',lambda _:inv)
    monkeypatch.setattr(m.artifacts,'prompt_version',lambda _:'v1')
    monkeypatch.setattr(m.artifacts,'load_prompt',lambda _,**kw:kw['material'])
    calls=[]
    def call(step,prompt,**kw):
        shown,_=json.JSONDecoder().raw_decode(prompt);ids=shown['required_group_ids'];calls.append(ids)
        if len(calls)==2:
            assert ids==['g2'] and not any(k.endswith('group:g1') for k in shown['sources'])
        rows=[]
        for gid in ids:
            source=next(k for k in shown['sources'] if k.endswith('group:'+gid))
            quote='fabricated quotation' if gid=='g2' and len(calls)==1 else f'"group_id": "{gid}"'
            rows.append(m.Diagnosis(group_id=gid,evidence_status='hypothesis',explanation='A method difference is possible.',
                evidence_source=source,evidence_quote=quote,next_check='Inspect author code.'))
        return SimpleNamespace(parsed=m.Response(diagnoses=rows),ledger_id=str(len(calls)))
    monkeypatch.setattr(m.review_backend,'call',call)
    m.run('fixture')
    receipt=json.loads((stage/'diagnosis.json').read_text())
    assert receipt['status']=='complete' and len(receipt['diagnoses'])==2
    assert all(d['anchor_verified'] for d in receipt['diagnoses'])
    assert calls==[['g1','g2'],['g2']]
    m.run('fixture')
    assert len(calls)==2

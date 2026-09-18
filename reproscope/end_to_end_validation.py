"""Acceptance receipt for one ordinary prompt-driven development run.

Read-only: this check never launches a model, edits claims or computes paper results.
Run it with the same REPROSCOPE_MODELS configuration as the pipeline.
"""
import argparse,json
from collections import Counter
from . import paths,artifacts,config,ledger,computation_coverage,divergence
from .report.findings import sensitivity
from .stage1.audit import acceptance
from .closed_reference import VERSION as REFERENCE_VERSION


def check(paper_id, *, require_report=True):
    root=paths.run_dir(paper_id)
    def read(rel,default=None):
        path=root/rel
        return json.loads(path.read_text()) if path.exists() else ({} if default is None else default)
    blockers=[];limitations=[]
    for stage in range(4):
        if not (root/f'stage{stage}/done.json').exists():blockers.append(f'stage {stage}: completion receipt missing')
    try:
        from .stage0 import input_hashes
        from .stage1 import inputs as reproduction_inputs
        from .stage2.review import gather
        from .stage3 import _stage_inputs
        from .stage1.blind import validate_packet_audit
        expected={0:input_hashes(paths.manifest(paper_id)),1:reproduction_inputs(paper_id),2:gather(paper_id).hashes,3:_stage_inputs(paper_id)}
        for stage,inputs in expected.items():
            if not paths.is_done(root/f'stage{stage}',inputs):blockers.append(f'stage {stage}: dependencies or outputs stale')
        validate_packet_audit(paper_id)
    except (ValueError,RuntimeError,OSError) as exc:blockers.append('freshness/blinding check: '+str(exc))
    blinding=read('stage0/leak_audit.json')
    if blinding.get('blinding_status')=='limited':limitations.append('Replica packet withholds numerical targets but retains structural cues about which statistics were reported')
    claims=read('stage0/claims.json',[])
    benchmark=read('stage0/extraction_benchmark.json')
    benchmark_current=bool(claims and benchmark.get('claims_sha256')==artifacts.sha256_file(root/'stage0/claims.json'))
    if not benchmark_current or not benchmark.get('passed'):blockers.append('source benchmark missing, stale or below >95% precision/recall target')
    coverage=computation_coverage.review(root)
    if coverage['unresolved_claim_ids']:blockers.append('unresolved computation duties: '+', '.join(coverage['unresolved_claim_ids']))
    if len(coverage['rows'])!=len(claims):blockers.append('quantity accounting does not cover extraction')
    planned=[f'{name}_{i}' for name,spec in config.replicas().items() for i in range(1,spec.runs+1)]
    replicas={}
    for rid in planned:
        trace=read(f'stage1/replicas/{rid}/trace.json');evidence=trace.get('execution_evidence') or {}
        accepted=trace.get('ran') and acceptance(trace.get('hardcoding_audit') or {})=='accepted'
        replicas[rid]={'accepted':bool(accepted),'methods':dict(Counter(a.get('status','unverified') for a in evidence.get('analyses',{}).values()))}
        if not accepted:blockers.append(f'{rid}: no accepted independently executed reproduction')
        if evidence.get('status')=='invalid':blockers.append(f'{rid}: independent method verification found invalid computations')
        elif evidence.get('status')!='verified':blockers.append(f'{rid}: independent method verification incomplete')
    diagnosis=divergence.coverage_status(root)
    if not diagnosis['complete']:blockers.append('divergence diagnosis incomplete or stale')
    review=read('stage2/review.json')
    if review.get('state')!='complete':blockers.append('statistical/interpretation review incomplete')
    if (review.get('questions') or {}).get('citation_validation')=='qualified':limitations.append('statistical review contains quarantined unsupported proposed findings')
    space=read('stage3/space.json');grid=read('stage3/grid.json');execution=read('stage3/execute.json')
    summary=sensitivity(space.get('runs',[]),space.get('factors',[]))
    if space.get('generator')!='general':blockers.append('ordinary multiverse generator not validated')
    if space.get('state')!='complete' or not summary['n_analytical']:blockers.append('multiverse has no accepted analytical results')
    if len(summary['active_dimensions'])<=4:blockers.append('fewer than five executed analytical dimensions')
    if execution.get('problems') or acceptance(execution.get('audit') or {})!='accepted':blockers.append('multiverse output verification/audit not accepted')
    if (space.get('execution') or {}).get('output_fingerprint')!=execution.get('output_fingerprint'):
        blockers.append('multiverse report aggregation is stale relative to verified outputs')
    for name in ('reference','perturbation'):
        if (execution.get(name) or {}).get('status')!='verified':blockers.append(f'multiverse {name} verification incomplete')
    for context,receipt in [('original',execution.get('reference') or {}),('resampled',(execution.get('perturbation') or {}).get('reference') or {})]:
        evidence=receipt.get('evidence') or []
        if receipt.get('version')!=REFERENCE_VERSION or receipt.get('total')!=summary['n_analytical'] or len(evidence)!=summary['n_analytical'] or any(e.get('status')!='verified' for e in evidence):
            blockers.append(f'multiverse {context}: complete per-specification numerical evidence required')
    if require_report and not (root/'report/report.html').exists():blockers.append('HTML report missing')
    costs=sum(row.get('cost_usd') or 0 for row in ledger.rows(paper_id))
    return {'paper_id':paper_id,'passed':not blockers,'blockers':blockers,'limitations':limitations,
        'scope':'Development integration validation; model-assisted extraction benchmark, not human or held-out accuracy.',
        'benchmark_current':benchmark_current,'extraction':{k:benchmark.get(k) for k in ('clean_source_occurrences','accepted_correct','accepted_count','accepted_recall','accepted_precision','correct_metadata_fields','scope')},
        'computation':{'counts':coverage['counts'],'unresolved_claim_ids':coverage['unresolved_claim_ids']},
        'replicas':replicas,'diagnosis':diagnosis,
        'multiverse':{'generator':space.get('generator'),'state':space.get('state'),'dimensions':summary['active_dimensions'],
            'n_specs':summary['n_analytical'],'grid_size':grid.get('grid_size'),'groups':[{k:g[k] for k in ('name','metric','n','min','max','median','null_value','inference','changes')} for g in summary['groups']],
            'reference_status':(execution.get('reference') or {}).get('status'),'perturbation_status':(execution.get('perturbation') or {}).get('status')},
        'metered_cost_usd':costs,'report':str(root/'report/report.html')}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('paper_id');args=parser.parse_args()
    result=check(args.paper_id);out=paths.run_dir(args.paper_id)/'end_to_end_validation.json';out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)

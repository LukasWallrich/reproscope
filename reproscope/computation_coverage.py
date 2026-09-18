"""Account for every extracted number across inferential and descriptive routes.

Assignment is a routing detail. A missing route is an unfinished computation,
regardless of the source quantity's role or statistical family.
"""
from collections import Counter
import json


def review(root):
    def read(name, default):
        path = root / name
        return json.loads(path.read_text()) if path.exists() else default

    claims = read('stage0/claims.json', [])
    contracts = read('stage0/contracts.json', [])
    readiness = read('stage0/readiness.json', {})
    descriptive = read('stage1/descriptive/report.json', {})
    results = {r['claim_id']: r for r in descriptive.get('results', [])}
    bindings = {b['claim_id']: b for b in descriptive.get('bindings', [])}
    matching = read('stage1/match.json', {}).get('rows', [])
    from .stage1.audit import acceptance
    verified = {}
    for path in (root / 'stage1/replicas').glob('*/trace.json'):
        trace = json.loads(path.read_text())
        if trace.get('ran') and acceptance(trace.get('hardcoding_audit') or {}) == 'accepted':
            verified[trace['replica_id']] = {
                aid for aid, a in trace.get('execution_evidence', {}).get('analyses', {}).items()
                if a.get('status') == 'verified'
            }
    rows = []
    for claim in claims:
        cid = claim['claim_id']
        aids = [c['analysis_id'] for c in contracts if cid in c.get('claim_ids', [])]
        row = {'claim_id': cid, 'quantity_kind': claim.get('quantity_kind'),
               'reported': claim.get('value'), 'analysis_ids': aids,
               'status': 'unresolved', 'reason': 'No verified computation or justified data limitation.'}
        computed = [r for r in matching if r['claim_id'] == cid and r.get('outcome_status') in {'graded', 'direction_unverified'}
                    and r.get('replicated') is not None
                    and set(r.get('source_analysis_ids') or [r.get('analysis_id')])
                    <= verified.get(r.get('replica_id'), set())]
        result, binding = results.get(cid, {}), bindings.get(cid, {})
        if computed:
            row.update(status='computed', route='inferential',
                       reason='Independently verified computation; agreement is reported separately.',
                       replicas=[r['replica_id'] for r in computed])
        elif result.get('verification') == 'verified' and descriptive.get('status') == 'verified':
            row.update(status='computed', route='descriptive', reason='Independent Python/R descriptive computation.',
                       computed_value=result.get('value'), matches_printed_rounding=result.get('matches_printed_rounding'))
        elif binding.get('state') == 'no_data' and binding.get('reason', '').strip():
            row.update(status='unavailable', route='descriptive', reason=binding['reason'])
        elif aids and all(readiness.get('per_analysis_outcome', {}).get(a) == 'data_invalid'
                          and readiness.get('per_analysis_reasons', {}).get(a) for a in aids):
            row.update(status='invalid_input', reason='; '.join(readiness['per_analysis_reasons'][a] for a in aids))
        elif aids and all(readiness.get('per_analysis_outcome', {}).get(a) == 'no_data'
                          and readiness.get('per_analysis_reasons', {}).get(a) for a in aids):
            row.update(status='unavailable', route='inferential',
                       reason='; '.join(dict.fromkeys(readiness['per_analysis_reasons'][a] for a in aids)))
        elif aids and any(readiness.get('per_analysis_reasons', {}).get(a) for a in aids):
            row['reason']='; '.join(dict.fromkeys(readiness['per_analysis_reasons'][a] for a in aids
                                                if readiness.get('per_analysis_reasons', {}).get(a)))
        # Invalid extraction never becomes an accepted data limitation.
        if claim.get('state') != 'complete':
            row.update(status='unresolved', reason=claim.get('abstain_reason') or 'Source reading unresolved.')
        rows.append(row)
    counts = dict(Counter(r['status'] for r in rows))
    return {'rows': rows, 'counts': counts, 'source_count': len(claims),
            'unresolved_claim_ids': [r['claim_id'] for r in rows if r['status'] == 'unresolved'],
            'complete': bool(rows) and not counts.get('unresolved'),
            'scope': 'All extracted numbers, including descriptives. Data limitations are accounted for but do not count as computed. Numbers missed by extraction require a separate source inventory.'}

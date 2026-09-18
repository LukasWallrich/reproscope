"""Exhaustive, deterministic inventory for unblinded divergence diagnosis."""
from collections import defaultdict
from pathlib import Path
import json, math
from . import provenance

VERSION = 'all-divergences-1'


def read(root, name, default):
    p = Path(root) / name
    return json.loads(p.read_text()) if p.exists() else default


def row_reason(row):
    if row.get('outcome_status') == 'direction_unverified':
        return 'direction_unstated'
    if row.get('bound_rounding_compatible') and not row.get('bound_satisfied'):
        return 'rounding_boundary'
    if row.get('band') not in {'A', 'B', 'C', 'fail'}:
        return 'ungraded_computation'
    if row.get('band') != 'A':
        return 'numerical_mismatch'
    exact = row.get('magnitude_exact_reported_precision') if (row.get('comparison_basis') or '').startswith('paired magnitude') else row.get('exact_reported_precision')
    if exact is False:
        return 'precision_mismatch'
    return None


def inventory(root):
    root = Path(root)
    claims = {c['claim_id']:c for c in read(root,'stage0/claims.json',[])}
    contracts = read(root,'stage0/contracts.json',[])
    claim_analysis = {cid:c['analysis_id'] for c in contracts for cid in c.get('claim_ids',[])}
    groups = {}
    def add(cid, kind, evidence, aid=None):
        aid = aid or claim_analysis.get(cid)
        group_id = f"{aid or cid}:{kind}"
        group = groups.setdefault(group_id,dict(group_id=group_id, analysis_id=aid, kind=kind, claim_ids=[], evidence=[]))
        if cid not in group['claim_ids']:group['claim_ids'].append(cid)
        group['evidence'].append(evidence)
    rows = read(root,'stage1/match.json',{}).get('rows',[])
    for i,row in enumerate(rows):
        reason = row_reason(row)
        if reason:
            add(row['claim_id'],reason,{'source':'stage1/match.json','row_index':i,**row},row.get('analysis_id'))
    for i,row in enumerate(read(root,'stage1/descriptive/report.json',{}).get('results',[])):
        if row.get('verification') != 'verified' or row.get('matches_printed_rounding') is not True:
            add(row['claim_id'],'descriptive_mismatch',{'source':'stage1/descriptive/report.json','row_index':i,**row})
    from .computation_coverage import review
    coverage = review(root)
    for row in coverage['rows']:
        if row['status'] != 'computed':
            add(row['claim_id'],'coverage_'+row['status'],{'source':'computation_coverage',**row})
    by_claim = defaultdict(list)
    for row in rows:
        if isinstance(row.get('replicated'),(int,float)) and math.isfinite(row['replicated']):by_claim[row['claim_id']].append(row)
    for cid, comparable in by_claim.items():
        def value(r):
            v = r['replicated']
            return abs(v) if (r.get('comparison_basis') or '').startswith('paired magnitude') and r.get('substantive_direction_match') is not False else v
        if len(comparable)>1 and any(not math.isclose(value(comparable[0]),value(r),rel_tol=1e-8,abs_tol=1e-12) for r in comparable[1:]):
            for row in comparable:add(cid,'between_replica',{'source':'stage1/match.json',**row},row.get('analysis_id'))
    for group in groups.values():
        group['claims']=[claims[cid] for cid in group['claim_ids'] if cid in claims]
        group['contract']=next((c for c in contracts if c['analysis_id']==group['analysis_id']),None)
    payload=dict(version=VERSION,groups=list(groups.values()),n_groups=len(groups),
        n_claims=len({cid for g in groups.values() for cid in g['claim_ids']}),
        inventory_rule='Every non-A or ungraded inferential row, A-band failure of printed precision after valid paired-sign handling, descriptive mismatch, uncomputed quantity, and between-replica numerical difference. Group by analysis and issue type; retain every claim and replica row. Data limitations are distinct from observed numerical divergences.')
    payload['fingerprint']=provenance.digest(payload)
    return payload


def coverage_status(root):
    current = inventory(root)
    report = read(root,'stage1/diagnosis.json',{})
    expected = {g['group_id'] for g in current['groups']}
    actual = [g.get('group_id') for g in report.get('diagnoses',[])]
    return dict(complete=report.get('status')=='complete' and report.get('inventory_fingerprint')==current['fingerprint'] and set(actual)==expected and len(actual)==len(expected),
        expected_groups=len(expected), missing=sorted(expected-set(actual)),
        extra=sorted(set(actual)-expected), stale=report.get('inventory_fingerprint')!=current['fingerprint'])

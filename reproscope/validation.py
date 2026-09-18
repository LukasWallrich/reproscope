"""Read-only preflight for accepting an existing cohort; never launches models."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import cohort, paths, provenance


def read(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def check(manifest: dict) -> dict:
    cohort.validate_runs(manifest)
    from .stage0 import input_hashes
    from .stage1 import inputs as stage1_inputs
    from .stage2.review import gather as stage2_inputs
    from .stage3 import _stage_inputs
    from .stage1.audit import acceptance
    from .stage1.blind import validate_packet_audit
    result = {'cohort_fingerprint': manifest['fingerprint'], 'runs': {},
              'scope': 'development' if any(p['split'] == 'development' for p in manifest['papers']) else 'held_out',
              'independent_intake_calibration': 'not established by these execution checks',
              'isolation': 'model generation: working-directory separation; verification: inspect per-replica OS receipts'}
    for entry in manifest['papers']:
        pid = entry['run_id']; root = paths.ROOT / 'runs' / pid
        blockers, limitations = [], []
        try:
            expected = {0: input_hashes(paths.manifest(pid)), 1: stage1_inputs(pid),
                        2: stage2_inputs(pid).hashes, 3: _stage_inputs(pid)}
            for stage in range(4):
                folder = root / f'stage{stage}'
                marker = read(folder / 'done.json')
                dependencies = expected.get(stage, marker.get('inputs', {}))
                if not paths.is_done(folder, dependencies):
                    blockers.append(f'stage{stage}: outputs or dependencies require regeneration/reverification')
            validate_packet_audit(pid)
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            blockers.append(f'intake/blinding: {exc}')
        for rid in entry['replicas']:
            trace = read(root / 'stage1/replicas' / rid / 'trace.json')
            if not trace:
                blockers.append(f'{rid}: planned attempt has no outcome trace')
            elif not trace.get('ran'):
                checks = trace.get('run_checks') or {}
                reason = ('invalid output protocol' if checks.get('output_protocol_status') == 'invalid'
                          else 'execution without usable output')
                limitations.append(f'{rid}: {reason} remains in the planned denominator')
            elif acceptance(trace.get('hardcoding_audit') or {}) == 'unresolved':
                blockers.append(f'{rid}: analytical audit unresolved')
            elif acceptance(trace.get('hardcoding_audit') or {}) == 'rejected':
                limitations.append(f'{rid}: audited rejection remains in the planned denominator')
        grid = read(root / 'stage3/grid.json')
        execution = read(root / 'stage3/execute.json')
        space = read(root / 'stage3/space.json')
        if space.get('state') == 'abstained':
            limitations.append('stage3 abstained: ' + str(space.get('abstain_reason')))
        else:
            if not grid.get('result_contract_version'):
                blockers.append('stage3: execution predates the statistical result contract')
            if execution.get('problems') or acceptance(execution.get('audit') or {}) != 'accepted':
                blockers.append('stage3: deterministic verification or audit not accepted')
            for name in ('reference', 'perturbation'):
                if (execution.get(name) or {}).get('status') != 'verified':
                    limitations.append(f'stage3: independent {name} verification incomplete')
        paper = read(root / 'stage3/paper_level.json')
        if paper.get('unresolved'):
            limitations.append('documented author settings unresolved: ' + ', '.join(paper['unresolved']))
        from .source_integrity import review_run
        semantic = review_run(root)
        result['runs'][pid] = {'current': not blockers, 'execution_current': not blockers,
                              'release_ready': not blockers and semantic['semantic_ready'],
                              'blockers': blockers, 'limitations': limitations, **semantic}
    result['all_runs_current'] = all(r['current'] for r in result['runs'].values())
    result['all_runs_release_ready'] = all(r['release_ready'] for r in result['runs'].values())
    result['generalisation_established'] = False
    result['implementation'] = provenance.implementation()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    report = check(cohort.load(args.cohort))
    text = json.dumps(report, indent=2) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)
    print(text)
    return 0 if report['all_runs_release_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

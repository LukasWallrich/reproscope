"""Numerical sensitivity summaries with influence kept outside analytical choices."""
from collections import defaultdict
import math


def interval_side(row):
    return 'positive' if row['ci_lower'] > 0 else 'negative' if row['ci_upper'] < 0 else 'includes_zero'


def sign(value):
    return 1 if value > 0 else -1 if value < 0 else 0


def span(rows, field):
    values = [r[field] for r in rows]
    return [min(values), max(values)]


def summarise(rows):
    """One record per estimand; no pooled median or significance-vote percentage.

    LOO baselines match every analytical setting, including interval/multiplicity.
    Missing or duplicate baselines and repeated deletions are errors, not silently
    substituted estimates. Max changes describe influence, not sampling intervals.
    """
    full = [r for r in rows if r['spec']['sample'] == 'full']
    loo = [r for r in rows if r['spec']['sample'].startswith('leave_out:')]
    if len(full) + len(loo) != len(rows):
        raise ValueError('unknown sample scope')
    groups = defaultdict(list)
    for r in full:
        groups[(r['spec']['scale'], r['spec']['location'])].append(r)
    analytical = []
    for (scale, location), group in groups.items():
        analytical.append(dict(scale=scale, location=location, n_specs=len(group),
            estimate_range=span(group, 'estimate'), p_range=span(group, 'p'),
            ci_lower_range=span(group, 'ci_lower'), ci_upper_range=span(group, 'ci_upper'),
            interval_sides=sorted({interval_side(r) for r in group}),
            positive_estimates=all(r['estimate'] > 0 for r in group),
            p_below_05_for_all=all(r['p'] < .05 for r in group),
            tail_resolution_flags=[r['spec_id'] for r in group if r.get('bca_tail_resolution_limited')],
            specifications=[{k:r[k] for k in ('spec_id','spec','estimate','ci_lower','ci_upper','p')} for r in group]))
    influence = []
    loo_groups = defaultdict(list)
    for r in loo:
        settings = tuple(sorted((k,v) for k,v in r['spec'].items() if k != 'sample'))
        loo_groups[settings].append(r)
    for settings, group in loo_groups.items():
        baselines = [r for r in full if tuple(sorted((k,v) for k,v in r['spec'].items() if k != 'sample')) == settings]
        if len(baselines) != 1:
            raise ValueError('influence requires exactly one full-sample baseline with identical analytical settings')
        baseline = baselines[0]
        ids = [r['spec']['sample'].removeprefix('leave_out:') for r in group]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate leave-one-out participant')
        if any(r['n'] != baseline['n'] - 1 for r in group):
            raise ValueError('leave-one-out sample size does not equal baseline n minus one')
        deltas = [r['estimate'] - baseline['estimate'] for r in group]
        largest = max(abs(d) for d in deltas)
        influential = [ids[i] for i,d in enumerate(deltas) if math.isclose(abs(d), largest, rel_tol=1e-9, abs_tol=1e-12)]
        diagnostics = [{**{k:r[k] for k in ('spec_id','estimate','ci_lower','ci_upper','p')},
            'participant':pid,'delta':delta,
            'sign_changed':sign(r['estimate']) != sign(baseline['estimate']),
            'interval_side_changed':interval_side(r) != interval_side(baseline),
            'estimate_outside_baseline_interval':not (baseline['ci_lower'] <= r['estimate'] <= baseline['ci_upper']),
            'p_threshold_changed':(r['p'] < .05) != (baseline['p'] < .05)}
            for r,pid,delta in zip(group,ids,deltas)]
        influence.append(dict(**dict(settings), n_deletions=len(group), expected_deletions=baseline['n'],
            complete=len(group)==baseline['n'], baseline_id=baseline['spec_id'],
            baseline_estimate=baseline['estimate'], baseline_se=baseline['se'],
            baseline_ci=[baseline['ci_lower'],baseline['ci_upper']], baseline_p=baseline['p'],
            estimate_range=span(group,'estimate'), p_range=span(group,'p'), max_abs_change=largest,
            max_change_in_baseline_se=largest/baseline['se'] if baseline['se'] > 0 else None,
            most_influential_participants=influential,
            estimates_outside_baseline_interval=sum(d['estimate_outside_baseline_interval'] for d in diagnostics),
            sign_changes=sum(d['sign_changed'] for d in diagnostics),
            interval_side_changes=sum(d['interval_side_changed'] for d in diagnostics),
            p_threshold_changes=sum(d['p_threshold_changed'] for d in diagnostics),
            diagnostics=diagnostics))
    return dict(n_analytical_specs=len(full), n_influence_checks=len(loo),
        analytical=analytical, influence=influence,
        influence_complete=bool(influence) and all(g['complete'] for g in influence),
        aggregation_rule='Group by estimand and match all analytical settings to one full-sample baseline. Report ranges and maximum absolute deletion changes, with participant IDs and sign/interval/p-threshold changes. Do not pool deletions with analytical specifications or treat their frequency as a robustness probability.')


def render_md(summary):
    lines=['## Full-sample sensitivity findings','',
        'Each row below describes one estimand. Interval endpoint ranges are descriptive envelopes across specifications, not a pooled confidence interval. P ranges include the declared multiplicity choices; intervals are unadjusted.', '',
        '| Scale / location | Specifications | Estimate range | Lower CI endpoint range | Upper CI endpoint range | p range | Interval conclusions |',
        '| --- | ---: | --- | --- | --- | --- | --- |']
    fmt=lambda vals:' to '.join(f'{v:.5g}' for v in vals)
    for g in summary['analytical']:
        lines.append(f"| {g['scale']} / {g['location']} | {g['n_specs']} | {fmt(g['estimate_range'])} | {fmt(g['ci_lower_range'])} | {fmt(g['ci_upper_range'])} | {fmt(g['p_range'])} | {', '.join(g['interval_sides'])} |")
    for g in summary['analytical']:
        direction = 'Every tested interval is above zero' if g['interval_sides']==['positive'] else 'Every tested interval is below zero' if g['interval_sides']==['negative'] else 'Interval conclusions vary or include zero'
        threshold = 'all adjusted/unadjusted p values remain below .05' if g['p_below_05_for_all'] else 'at least one p value is .05 or above'
        lines += ['', f"**{g['scale']} / {g['location']}:** {direction}; {threshold}."]
    lines += ['', 'These specifications share observations and are not independent votes. Differences of scale or location change the estimand. See the numerical specification table for the settings behind interval and p-value differences.', '',
        '## Leave-one-out influence diagnostics', '', summary['aggregation_rule'], '',
        'For each scale/location estimand the baseline is the full-sample, unadjusted centred bootstrap with a standard percentile interval. Each deletion uses these same settings. A large deletion effect can motivate a prespecified exclusion-rule sensitivity, but deleting each participant is not itself an analytical-choice multiverse.', '',
        '| Scale / location | Deletions | Full estimate | Deletion estimate range | Maximum absolute change | Change / baseline SE | Participant(s) at maximum | Sign / CI-side / p<.05 changes; outside baseline CI |',
        '| --- | ---: | ---: | --- | ---: | ---: | --- | --- |']
    for g in summary['influence']:
        ratio=f"{g['max_change_in_baseline_se']:.3g}" if g['max_change_in_baseline_se'] is not None else 'undefined'
        lines.append(f"| {g['scale']} / {g['location']} | {g['n_deletions']}/{g['expected_deletions']} | {g['baseline_estimate']:.5g} | {fmt(g['estimate_range'])} | {g['max_abs_change']:.5g} | {ratio} | {', '.join(g['most_influential_participants'])} | {g['sign_changes']} / {g['interval_side_changes']} / {g['p_threshold_changes']}; {g['estimates_outside_baseline_interval']} |")
    lines += ['', 'Changes are relative to the matched baseline, not counts of independent studies. Deletion ranges are not uncertainty intervals. Bootstrap p/interval changes also contain finite-simulation variation; the raw simulation-error intervals remain in the full results.', '']
    return '\n'.join(lines)

"""Effect scales and screened per-specification reporting identities."""
from . import artifacts

NULLS={'mean_difference':0.,'d':0.,'dz':0.,'r':0.,'log_ratio':0.,'log_odds_ratio':0.,'odds_ratio':1.,'risk_ratio':1.,'risk_difference':0.}


def primary_effect(screen, contract, focal):
    target=screen.get('primary_effect') or {}
    metric=target.get('metric') or (contract.design.effect_metric if contract.design else None) or focal['focal_quantity'].get('kind')
    if metric not in NULLS:raise ValueError('no supported effect-scale metric; test statistics and p-values are not effect-size curves')
    return {'metric':metric,'effect_group':target.get('effect_group') or 'focal','null_value':NULLS[metric],
            'rationale':target.get('rationale') or 'Effect metric declared in the analysis contract.'}


def reference(primary, claims, contract):
    matches=[c for c in claims if c.claim_id in contract.claim_ids and c.quantity_kind==primary['metric'] and c.state=='complete']
    if len(matches)==1:
        c=matches[0]
        return {'value':c.value,'metric':primary['metric'],'effect_group':primary['effect_group'],'source':'claim','claim_id':c.claim_id,'precision':c.precision,'note':'Directly reported on this effect scale.'}
    return {'value':None,'metric':primary['metric'],'effect_group':primary['effect_group'],'source':'none','note':'No unique directly reported quantity on this curve scale; no reported-value rank is claimed.'}


def specification_scope(spec, grid):
    if grid.get('reporting_rules') or grid.get('reporting_rules_required'):
        rules=grid.get('reporting_rules') or []
        available={f['name']:{lv['value'] for lv in f['levels']} for f in grid.get('factors',[])}
        for rule in rules:
            for factor,values in rule['when'].items():
                if factor not in available or not values or not set(values)<=available[factor]:
                    raise ValueError('reporting rule references unknown/empty factor levels')
        matched=[r for r in rules if all(spec['levels'].get(f) in values for f,values in r['when'].items())]
        if len(matched)!=1:raise ValueError(f"{spec['spec_id']}: expected exactly one reporting rule, got {len(matched)}")
        rule=matched[0];metric=rule['effect_metric']
        if metric not in NULLS:raise ValueError(f"{spec['spec_id']}: unsupported effect metric {metric}")
        if not all(rule.get(k,'').strip() for k in ('effect_group','null_group','rationale')):
            raise ValueError('reporting rule needs groups and substantive rationale')
        return {k:rule[k] for k in ('effect_group','effect_metric','null_group','role')} | {'null_value':NULLS[metric]}
    levels=[lv for f in grid.get('factors',[]) for lv in f['levels'] if spec['levels'].get(f['name'])==lv['value']]
    related=[lv for lv in levels if lv.get('role')=='related_effect']
    chosen=related or levels
    groups=sorted({lv.get('effect_group') for lv in chosen if lv.get('effect_group') not in (None,'','focal')})
    metrics={lv.get('effect_metric') for lv in chosen if lv.get('effect_metric')}
    if len(metrics)>1:raise ValueError(f"{spec['spec_id']}: incompatible screened effect metrics")
    metric=next(iter(metrics),grid.get('effect_metric'))
    if metric not in NULLS:raise ValueError(f"{spec['spec_id']}: no supported effect metric")
    nulls=sorted({lv.get('null_group') for lv in levels if lv.get('null_group') not in (None,'','focal')})
    return {'effect_group':' / '.join(groups) or grid.get('primary_effect',{}).get('effect_group','focal'),
            'effect_metric':metric,'null_group':' / '.join(nulls) or 'focal',
            'null_value':NULLS[metric], 'role':'related_effect' if related else 'comparable_effect'}


def checks(rows, specs):
    expected={s['spec_id']:s.get('reporting_contract') for s in specs}
    errors=[]
    for row in rows:
        contract=expected.get(row.get('_spec_id'))
        if contract and row.get('_converged'):
            for field in ('effect_group','effect_metric','null_group'):
                if row.get(field)!=contract[field]:errors.append(f"{row.get('_spec_id')}: {field} differs from independently screened reporting contract")
    return errors


def repair_rules(paper_id, grid, problems, attempt):
    """Repair scope declarations against a fixed screened grid, never its results."""
    import json,os
    from . import paths,response_cache,review_backend
    from .stage3.multiverse import ReportingRules,enumerate_specs
    context={k:grid.get(k) for k in ('factors','incompatible','primary_effect','reporting_rules')}
    context['executed_specs']=enumerate_specs(grid)
    prompt=("Repair conditional reporting rules for this independently screened multiverse. Do not change any factor, method, or compatibility decision. No computed or reported results are supplied. Each executed specification must match exactly ONE rule: when maps factor names to lists of accepted level IDs, and all listed conditions must hold. Omitted factors are wildcards. Use disjoint exhaustive rules, not priorities. Define effect_group/effect_metric/null_group/role/rationale for the complete specification, not individual inference factors. Raw justified trimmed and mean differences may share the same raw substantive effect group and mean_difference metric; retain their estimator identities in the factors and distinguish nulls when needed. Transformed or rank metrics need coherent related groups. An interval or resampling factor cannot arbitrarily change the effect metric. Metric must be one of "+', '.join(NULLS)+". Return reporting_rules only.\n"+json.dumps({'problems':problems,'grid':context}))
    tier='strong_alt' if os.environ.get('REPROSCOPE_REVIEW_BACKEND')=='strong_alt' else 'strong'
    key=response_cache.key(prompt,ReportingRules,[],tier)
    cache=paths.run_dir(paper_id,3)/f'reporting_rules_repair{attempt}.response.json'
    saved=response_cache.read(cache,key,ReportingRules)
    if saved:parsed,cid=saved
    else:
        r=review_backend.call('reporting_rules_repair',prompt,paper_id=paper_id,stage='3',tier='strong',schema=ReportingRules,timeout_s=1200)
        if not r.ok or r.parsed is None:raise RuntimeError('reporting-rule repair failed: '+str(r.error))
        parsed,cid=r.parsed,r.ledger_id;response_cache.write(cache,key,parsed,cid)
    return [r.model_dump() for r in parsed.reporting_rules],cid

"""Check printed degrees of freedom alongside the associated test statistic."""
import re
import unicodedata


def canonical_aggregation(claim):
    """A located CI endpoint is scalar; min/max do not enumerate tests."""
    get=claim.get if isinstance(claim,dict) else lambda key,default=None:getattr(claim,key,default)
    aggregation=get('aggregation','scalar')
    if (get('quantity_kind')=='ci_bound' and aggregation in {'min','max'}
            and not get('member_ids',[]) and get('quantity_kind_raw') in {'lower','upper','ci_lower','ci_upper'}):
        return 'scalar'
    return aggregation


def check(claim, evidence):
    from .reported_metadata import degrees_of_freedom
    if claim.aggregation != 'scalar':return None
    dfs=degrees_of_freedom(claim)
    if not dfs:return None
    if claim.quantity_kind=='F' and len(dfs)!=2:
        return {'status':'source_ambiguous','reported_df':None,'source_notation':dfs,'reason':'An F test needs numerator and denominator degrees of freedom. The source annotation has no unambiguous separator; no split is inferred.'}
    reported=dfs[0] if len(dfs)==1 else dfs
    computed = None
    if evidence.get('status') == 'verified':
        if evidence.get('df') is not None:
            computed=evidence['df']
        elif claim.quantity_kind == 't' and evidence.get('family') == 'paired_t' and isinstance(evidence.get('n'), int):
            computed = evidence['n'] - 1
        elif claim.quantity_kind == 'chi2' and evidence.get('family') == 'likelihood_ratio':
            computed = evidence.get('df')
    if computed is None:
        return {'status':'unverified', 'reported_df':reported, 'reason':'No independently verified test degrees of freedom.'}
    if claim.quantity_kind=='F' and not isinstance(computed,(list,tuple)):
        numerator=evidence.get('df_num',evidence.get('df_model'))
        if numerator is None:
            return {'status':'unverified','reported_df':reported,'computed_df':{'denominator':computed},'reason':'Only residual degrees of freedom are independently available; the numerator is not verified.'}
        computed=[numerator,computed]
    return {'status':'match' if reported == computed else 'mismatch', 'reported_df':reported,
            'computed_df':computed, 'reason':'Degrees of freedom checked against the independently verified sample and test parameters.'}


# Compatibility with already loaded callers; both names apply the same checks.
paired_t_df = check

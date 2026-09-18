"""Independent calculations for directly bound two-group, paired, and correlation analyses.

Plans declare data columns and sample identities, never vectors of result values.
Unsupported transformations remain explicitly unverified.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats


def calculate(family: str, x, y, *, equal_var=True, alternative="two-sided") -> dict:
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if min(len(x), len(y)) < 2 or not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("reference requires finite observations and at least two per sample")
    if family == "independent_t":
        test = stats.ttest_ind(x, y, equal_var=equal_var, alternative=alternative)
        pooled = math.sqrt(((len(x)-1)*x.var(ddof=1)+(len(y)-1)*y.var(ddof=1))/(len(x)+len(y)-2))
        difference = float(x.mean()-y.mean())
        return {"n": len(x)+len(y), "df":float(test.df), "t": float(test.statistic), "p_raw": float(test.pvalue),
                "d": difference/pooled, "d_standardizer": "pooled_within_group_sd", "mean_difference": difference,
                "se_mean_difference": (pooled*math.sqrt(1/len(x)+1/len(y)) if equal_var
                                       else math.sqrt(x.var(ddof=1)/len(x)+y.var(ddof=1)/len(y)))}
    if len(x) != len(y):
        raise ValueError("paired/correlation inputs must describe the same observations")
    if family == "paired_t":
        delta = x-y
        test = stats.ttest_rel(x, y, alternative=alternative)
        return {"n": len(x), "df":len(x)-1, "t": float(test.statistic), "p_raw": float(test.pvalue),
                "dz": float(delta.mean()/delta.std(ddof=1)), "mean_difference": float(delta.mean()),
                "se_mean_difference": float(delta.std(ddof=1)/math.sqrt(len(delta)))}
    if family == "correlation":
        test = stats.pearsonr(x, y, alternative=alternative)
        return {"n": len(x), "df":len(x)-2, "r": float(test.statistic), "p_raw": float(test.pvalue)}
    raise ValueError("unsupported reference design")


def read_data(work: Path, plan: dict) -> tuple[Path, pd.DataFrame]:
    path = (work / plan["file"]).resolve()
    if not path.is_relative_to((work / "data").resolve()):
        raise ValueError("reference data must be in the supplied data directory")
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    elif path.suffix.lower() in {".xls", ".xlsx"}:
        frame = pd.read_excel(path, sheet_name=plan.get("table") or 0, header=plan.get("header", 0))
    elif path.suffix.lower() == ".sav":
        import pyreadstat
        frame, _ = pyreadstat.read_sav(str(path))
    else:
        raise ValueError("unsupported reference data format")
    return path, frame


def numeric_sample(frame, plan):
    """Execute an explicit parser/sample policy without forgiving malformed cells."""
    frame = frame.copy()
    columns = [plan["x"]] if plan["family"] in {"independent_t","one_sample_t"} else [plan["x"], plan["y"]]
    if plan['family']=='partial_correlation':columns += plan['covariates']
    elif plan['family']=='linear_regression':columns = [plan['x']]+plan['predictors']
    parser = plan.get("numeric_parsing") or "strict_float"
    if parser not in {"strict_float", "strict_float_blank_missing"}:
        raise ValueError("unsupported reference numeric parser")
    for column in columns:
        values = frame[column]
        if parser == "strict_float_blank_missing":
            values = values.replace(r"^\s*$", np.nan, regex=True)
        frame[column] = pd.to_numeric(values, errors="raise")
    if plan.get("missingness") == "complete_cases":
        frame = frame.dropna(subset=columns)
    return frame


def _canonical_setting(field, value):
    if field=='alternative' and value in {'two_sided','two sided','two-tailed'}:
        return 'two-sided'
    return value


def from_plan(work: Path, plan: dict) -> dict:
    plan={**plan,'alternative':_canonical_setting('alternative',plan.get('alternative','two-sided'))}
    if plan.get("family") in {"paired_t_family", "correlation_family"}:
        members = [from_plan(work, m) for m in plan["members"]]
        common = set.intersection(*(set(m) for m in members)) - {"n"}
        return {**{k:[m[k] for m in members] for k in common},
                "member_ids":[m["analysis_id"] for m in plan["members"]],
                "member_n":[m["n"] for m in members],
                "n": members[0]["n"] if len({m["n"] for m in members}) == 1 else None}
    if plan.get("sensitivity_protocol") == "location-1":
        from .multiverse_reference import calculate as sensitivity_calculate
        return sensitivity_calculate(work, plan)
    _, frame = read_data(work, plan)
    if plan.get("included_ids") is not None:
        identifier = plan["id_column"]
        if frame[identifier].duplicated().any():
            raise ValueError("reference sample IDs must be unique")
        if not set(plan["included_ids"]) <= set(frame[identifier]):
            raise ValueError("reference plan includes unknown sample IDs")
        frame = frame[frame[identifier].isin(plan["included_ids"])]
    frame = numeric_sample(frame, plan)
    if plan['family'] in {'partial_correlation','linear_regression'}:
        from .adjusted_reference import calculate as adjusted_calculate
        return adjusted_calculate(frame,plan)
    if plan['family']=='one_sample_t':
        x=frame[plan['x']].to_numpy(float);mu=float(plan['null_value'])
        if len(x)<2 or not np.isfinite(x).all() or not math.isfinite(mu):raise ValueError('invalid one-sample input')
        test=stats.ttest_1samp(x,mu,alternative=plan.get('alternative','two-sided'))
        delta=float(x.mean()-mu);se=float(x.std(ddof=1)/math.sqrt(len(x)))
        return {'n':len(x),'df':len(x)-1,'t':float(test.statistic),'p_raw':float(test.pvalue),'mean_difference':delta,'se_mean_difference':se,'d':delta/x.std(ddof=1)}
    if plan["family"] == "likelihood_ratio":
        if plan.get("nesting") != "larger_contains_smaller" or plan.get("aggregation") != "sum_subject_loglikelihoods":
            raise ValueError("likelihood nesting and aggregation must be explicit")
        if frame[plan["id_column"]].isna().any() or frame[plan["id_column"]].duplicated().any():
            raise ValueError("likelihood rows require unique nonmissing subject IDs")
        delta=frame[plan["x"]].to_numpy()-frame[plan["y"]].to_numpy()
        if not len(delta) or not np.isfinite(delta).all() or (delta < -1e-8).any():
            raise ValueError("deposited log likelihoods violate nesting or finiteness")
        df=len(delta)*plan["df_per_subject"]
        statistic=float(2*delta.sum())
        return {"n":len(delta),"chi2":statistic,"df":df,"p_raw":float(stats.chi2.sf(statistic,df))}
    if plan["family"] == "independent_t":
        group = plan["group_column"]
        a, b = plan["group_values"]
        x = frame.loc[frame[group] == a, plan["x"]]
        y = frame.loc[frame[group] == b, plan["x"]]
    else:
        x, y = frame[plan["x"]], frame[plan["y"]]
    return calculate(plan["family"], x, y, equal_var=plan.get("equal_var", True),
                     alternative=plan.get("alternative", "two-sided"))


def check(work: Path, rows: list[dict], specs: list[dict]) -> dict:
    if specs and specs[0].get("independent_recipe"):
        from .closed_reference import check as closed_check
        return closed_check(work, rows, specs, specs[0]["recipe_record"])
    plan_path = work / "out" / "analysis_plan.json"
    if not plan_path.exists():
        return {"status": "missing", "checked": 0, "problems": ["missing analysis_plan.json"], "unsupported": []}
    try:
        plans = json.loads(plan_path.read_text())["specs"]
        by_id = {p["spec_id"]: p for p in plans}
        if len(by_id) != len(plans):
            raise ValueError("duplicate reference-plan spec IDs")
        expected = {s["spec_id"]: s["levels"] for s in specs}
        required = {s["spec_id"]: s.get("reference_settings", {}) for s in specs}
        if set(by_id) != set(expected):
            raise ValueError("reference plans must cover the exact executed specification set")
    except (ValueError, TypeError, KeyError) as exc:
        return {"status": "invalid", "checked": 0, "problems": [str(exc)], "unsupported": []}
    row_ids = [row.get("_spec_id") for row in rows]
    if set(row_ids) != set(expected) or len(set(row_ids)) != len(row_ids):
        return {"status": "invalid", "checked": 0, "problems": ["reference rows must cover the exact specification set"], "unsupported": []}
    problems, unsupported, checked = [], [], 0
    for row in rows:
        sid = row.get("_spec_id")
        plan = by_id.get(sid, {})
        if plan.get("implemented_levels") != expected.get(sid):
            problems.append(f"{sid}: implemented settings differ from grid")
        for field, value in required.get(sid, {}).items():
            if _canonical_setting(field,plan.get(field)) != _canonical_setting(field,value):
                problems.append(f"{sid}: reference plan violates screened {field} setting")
        if not row.get("_converged"):
            continue
        if plan.get("status") == "unsupported" and plan.get("reason"):
            unsupported.append({"spec_id": sid, "reason": plan["reason"]})
            continue
        try:
            result = from_plan(work, plan)
            if row.get('p_adjustment') not in (None,'','none'):
                unsupported.append({'spec_id':sid,'reason':'Multiplicity arithmetic is checked; family membership and nonfocal family p-values are not independently verified.'})
            metric = "dz" if row["effect_metric"] == "d" and plan.get("family") == "paired_t" else row["effect_metric"]
            comparisons = [(metric, row["_estimate"]), ("n", row["_n"])]
            if row.get("inference_method") == "analytic":
                comparisons.append(("p_raw", float(row["p_raw"])))
            else:
                fields = {"algorithm", "test_statistic", "resampling_unit", "alternative"}
                if plan.get("algorithm") == "centred_bootstrap":
                    fields.add("null_centering")
                if not fields <= required.get(sid, {}).keys():
                    unsupported.append({"spec_id": sid, "reason": "resampling settings not fixed independently in screened grid"})
                else:
                    simulation = resampling_reference(work, plan)
                    if row.get("inference_method") == "exact":
                        if not simulation["exact"] or not math.isclose(float(row["p_raw"]), simulation["p_raw"], abs_tol=1e-12):
                            problems.append(f"{sid}: exact null-distribution p differs")
                    else:
                        from .statistical import integer_field
                        interval = binomial_interval(integer_field(row["exceedances"],'exceedances'), integer_field(row["draws"],'draws'))
                        lo, hi = simulation["interval"]
                        if interval[1] < lo or interval[0] > hi:
                            problems.append(f"{sid}: independent null-distribution p outside Monte Carlo uncertainty")
                    row["reference_inference"] = simulation
            if row.get("se") not in (None, ""):
                if metric in {"mean_difference", "log_ratio"} and row.get("inference_method")=="analytic":
                    comparisons.append(("se_mean_difference", float(row["se"])))
                else:
                    unsupported.append({"spec_id": sid, "reason": "uncertainty estimator is not independently verified"})
            if row.get('ci_lower') not in (None,'') or row.get('ci_upper') not in (None,''):
                level=float(row.get('ci_level') or plan.get('ci_level') or .95)
                if not 0<level<1:raise ValueError('invalid interval coverage')
                if row.get('ci_method')=='student_t' and metric in {'mean_difference','log_ratio'} and 'df' in result:
                    margin=stats.t.ppf((1+level)/2,result['df'])*result['se_mean_difference']
                    for field,target in [('ci_lower',result[metric]-margin),('ci_upper',result[metric]+margin)]:
                        if not math.isclose(float(row[field]),target,rel_tol=1e-5,abs_tol=1e-10):problems.append(f'{sid}: independent reference differs on {field}')
                else:unsupported.append({'spec_id':sid,'reason':'interval method is not independently verified'})
            for field, actual in comparisons:
                if not math.isclose(result[field], actual, rel_tol=1e-5, abs_tol=1e-10):
                    problems.append(f"{sid}: independent reference differs on {field}")
            checked += 1
        except (ValueError, TypeError, KeyError, OSError, ZeroDivisionError) as exc:
            problems.append(f"{sid}: invalid reference plan: {exc}")
    return {"status": "invalid" if problems else "partial" if unsupported or checked == 0 else "verified",
            "checked": checked, "problems": problems, "unsupported": unsupported}


def perturb_csv_inputs(work: Path) -> bool:
    """Perturb declared outcome columns, keeping identifiers and group coding intact."""
    plans = json.loads((work / "out/analysis_plan.json").read_text())["specs"]
    columns = {}
    for plan in plans:
        if plan.get("status") == "unsupported":
            continue
        path = (work / plan["file"]).resolve()
        if not path.is_relative_to((work / "data").resolve()) or path.suffix.lower() != ".csv":
            continue
        columns.setdefault(path, set()).add(plan["x"])
    for path, names in columns.items():
        frame = pd.read_csv(path)
        for j, name in enumerate(sorted(names)):
            values = pd.to_numeric(frame[name])
            amplitude = max(float(values.std()), 1.)
            frame[name] = values + amplitude * np.random.default_rng(741+j).normal(size=len(values))
        frame.to_csv(path, index=False)
    return bool(columns)


def resampling_reference(work: Path, plan: dict, *, draws: int = 50000) -> dict:
    """Independent paired null distributions; never reads executor counts/results.

    Uses exact sign enumeration up to 16 pairs, otherwise a separate fixed stream.
    Compatibility is checked using Monte Carlo intervals, not equality of seeds.
    """
    import itertools
    algorithm = plan.get("algorithm")
    statistic = plan.get("test_statistic")
    alternative = _canonical_setting("alternative",plan.get("alternative"))
    if plan.get("family") != "paired_t" or algorithm not in {"sign_flip", "centred_bootstrap"}:
        raise ValueError("unsupported resampling design or null algorithm")
    if statistic not in {"mean_difference", "studentized_mean"} or alternative not in {"two-sided", "less", "greater"}:
        raise ValueError("resampling requires explicit statistic and alternative")
    if plan.get("resampling_unit") != "paired_difference":
        raise ValueError("paired resampling must preserve participant pairs")
    if algorithm == "centred_bootstrap" and plan.get("null_centering") != "subtract_observed_mean":
        raise ValueError("bootstrap null requires explicit centring")
    if float(plan.get("trim_fraction", 0)) != 0:
        raise ValueError("trimmed resampling reference is unsupported; declare the plan unsupported rather than checking an untrimmed null")
    if plan.get("sensitivity_protocol") == "location-1":
        from .multiverse_reference import samples
        delta, _ = samples(work, plan)
    else:
        if plan.get("transform", "identity") != "identity" or plan.get("outlier_rule", "none") != "none":
            raise ValueError("resampling preprocessing requires a supported explicit sensitivity protocol")
        _, frame = read_data(work, plan)
        if plan.get("included_ids") is not None:
            frame = frame[frame[plan["id_column"]].isin(plan["included_ids"])]
        frame = numeric_sample(frame, plan)
        delta = frame[plan["x"]].to_numpy(float) - frame[plan["y"]].to_numpy(float)
    if len(delta) < 2 or not np.isfinite(delta).all():
        raise ValueError("resampling requires a finite explicitly bound paired sample")
    def stat(values):
        mean = values.mean(axis=-1)
        if statistic == "mean_difference":
            return mean
        sd = values.std(axis=-1, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(sd == 0, np.where(mean == 0, 0., np.sign(mean)*np.inf), mean / (sd / math.sqrt(len(delta))))
    observed = float(stat(delta))
    if not math.isfinite(observed):
        raise ValueError("degenerate observed resampling statistic")
    def count(values):
        sampled = stat(values)
        tol = 1e-12 * max(1, abs(observed))
        if alternative == "two-sided":
            return int(np.sum(np.abs(sampled) >= abs(observed)-tol))
        if alternative == "greater":
            return int(np.sum(sampled >= observed-tol))
        return int(np.sum(sampled <= observed+tol))
    exact = algorithm == "sign_flip" and len(delta) <= 16
    exceedances = 0
    if exact:
        samples = np.asarray(list(itertools.product((-1, 1), repeat=len(delta)))) * delta
        draws = len(samples)
        exceedances = count(samples)
    else:
        rng = np.random.default_rng(731294)  # independent of executor's declared stream
        centred = delta - delta.mean()
        for start in range(0, draws, 1000):
            n = min(1000, draws-start)
            samples = (rng.choice((-1., 1.), size=(n, len(delta))) * delta if algorithm == "sign_flip"
                       else centred[rng.integers(0, len(delta), size=(n, len(delta)))])
            exceedances += count(samples)
    p = exceedances/draws if exact else (exceedances+1)/(draws+1)
    return {"p_raw": p, "draws": draws, "exceedances": exceedances, "exact": exact,
            "interval": [p, p] if exact else binomial_interval(exceedances, draws)}


def binomial_interval(successes: int, draws: int, error: float = .001) -> list[float]:
    if draws < 1 or not 0 <= successes <= draws:
        raise ValueError("invalid Monte Carlo counts")
    return [float(stats.beta.ppf(error/2, successes, draws-successes+1)) if successes else 0.,
            float(stats.beta.ppf(1-error/2, successes+1, draws-successes)) if successes < draws else 1.]

## Candidate domains, each gated by the deposited data

Only one of the four retained dimensions, Pearson versus Spearman, changes the point estimate. The other three change inference only. The best additions are therefore estimate-changing choices that keep the estimand intact.

1. **Nuisance functional form for age.** Compare linear with a restricted cubic spline (3 knots) or linear plus quadratic. Include this only if the deposited age has enough range and distinct values. Reject categorised or dichotomised age as a loss of information.
2. **Outlier and influence handling.** Compare none with one pre-specified robust rule. An example is excluding cases with |studentized residual| > 3 in either age-residualised variable, or winsorising at a stated percentile. Make it conditional on Pearson only, because Spearman already down-weights extremes. Allow no grids of thresholds.
3. **Missing data.** Compare listwise deletion with multiple imputation, but only if the three variables actually have missing values. If every case is complete, the domain is inapplicable and should not be listed.
4. **Score construction.** Compare sum with prorated mean when a few items are missing. This applies only if item-level data are deposited. With totals alone, the domain is unavailable.
5. **Paper-stated exclusions.** Examples are age limits or attention checks. Include these only where the paper names the criterion and the data contain the indicator.

Additional covariates such as sex are estimand-changing. Reject them unless the paper itself reports them as a sensitivity analysis.

## Generator safeguards

- **Provenance required.** Each dimension cites the paper text, a concrete data feature (missingness count, age range), or an established methods norm for this estimand. Proposals without a citation are dropped.
- **Estimand check.** The generator states explicitly whether the target, "association between totals net of age," is unchanged.
- **Feasibility check.** Proposals are validated against the deposited variables before screening.
- **Zero is a valid output.** The prompt should say that no new dimensions is an acceptable answer, and no minimum count should be enforced.
- **Bounded alternatives.** Allow at most 2–3 levels per dimension, and never parameter sweeps.
- **Dependency declaration.** Conditional nodes (outliers only under Pearson), redundancy with existing dimensions, and inference-only versus estimate-changing are all tagged.
- **Implementation validity.** For permutation inference with a covariate, require Freedman–Lane residual permutation, not naive shuffling. For bootstrap intervals, resample whole cases and re-residualise age within each resample.
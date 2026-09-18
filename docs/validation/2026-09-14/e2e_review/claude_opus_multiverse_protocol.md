# Review of the three pipeline design decisions

## 1. Rejecting a 3-SD exclusion rule because it is post hoc

**Not defensible as a universal criterion.** In a retrospective multiverse almost every alternative is post hoc; that is the design, not a defect. Preregistration status matters for *provenance labelling* and for how the author's own result is interpreted. It is not a validity test for a robustness specification. "Robust estimators already included" is a redundancy argument, and here it is weak:

- A 3-SD exclusion is data-dependent removal based on a non-robust scale (the SD). It is prone to masking and changes n and df.
- Symmetric trimming with fixed γ removes a fixed proportion regardless of how extreme the values are.
- The two rules behave differently, so neither stands in for the other.

**Suggested screening rule.** Accept a specification if all of these hold:

1. **A priori justification.** It is a conventional or methodologically cited choice for this design and outcome type, stated without reference to results.
2. **Outcome-blind.** The screen never sees effect estimates, p-values or direction when deciding. Descriptive data checks (n, ranges) are acceptable if logged.
3. **Estimand mapping recorded.** Either it shares the substantive estimand (per your convention) or it is labelled as a different one.
4. **Valid for the design.** For example, exclusion must operate on the pairing unit and must not break the within-subject structure.
5. **Fully specified.** The spec must state:
   - what is standardised (differences, per-condition scores, or trials)
   - whether it is a single pass or iterative
   - whether the SD includes the candidate point
   - the boundary (`>` or `≥`)
   - which downstream factors it crosses with

**Allowed rejection reasons:** invalid for the design, underspecified, exact duplicate, infeasible, or requires outcome knowledge. Post hoc status goes in metadata (`author_specified` / `preregistered` / `conventional_alternative`), and summaries can be stratified by it.

**Practical notes:**
- With the sample SD, the maximum possible |z| is (n−1)/√n. For n ≤ 10 a 3-SD rule cannot exclude anyone. Keep it but flag it as a no-op rather than silently dropping it.
- Crossing exclusion with trimmed estimators is "double robustification." It is defensible but low priority. Prefer to cross it with mean-based estimators, and report the number of exclusions per spec.

## 2. Paired Yuen versus trimmed mean of differences

**The screen was wrong. Both are valid, established estimators with different estimands.**

| | Dependent Yuen (Yuen 1974; Wilcox; `WRS2::yuend`) | Trimmed mean of differences |
|---|---|---|
| Estimand | μ_t1 − μ_t2 (difference of marginal trimmed means) | μ_t(D), D = X1 − X2 (trimmed location of within-person change) |
| SE | √(d1 + d2 − 2·d12), with d_j = (n−1)s²_wj / (h(h−1)) and d12 = (n−1)·cov_w / (h(h−1)); each margin winsorized separately | s_w(D) / ((1−2γ)√n) (Tukey–McLaughlin) |
| df | h − 1, where h = n − 2g | h − 1 |
| Typical question | Does typical performance differ between conditions? | What is the typical individual change? |

- For untrimmed means the two coincide by linearity, which is why the ordinary paired t-test hides the distinction. With trimming they generally differ unless the distributions are symmetric or in similar special cases.
- Related estimators that are also valid:
  - median of differences
  - Hodges–Lehmann / Wilcoxon signed-rank (a pseudo-median estimand)
  - bootstrap-t or percentile bootstrap versions of either trimmed estimator

**Avoiding adapting the science to the checker:**

- **No silent substitution.** A screen may accept, reject with a stated reason, or request clarification. It may not replace one estimator with another. A rewrite that changes the estimand becomes a *new, separately labelled* spec, and the original stays in the record.
- **Validity claims need grounds.** An "invalid estimator" verdict needs a citation or derivation and should go through arbitration. An LLM assertion alone is not enough.
- **Estimator registry.** Each entry holds a canonical definition, estimand, formula, reference implementation, citation, and validation fixtures (e.g. matched against `WRS2::yuend` and trimse-style output on fixed test data).
- **Capability gaps are reported, not hidden.** If the reference checker lacks an estimator, mark the spec `unsupported_by_reference` and report that as a coverage limitation. Then extend the checker. Do not redefine the spec to match the checker.
- **Keep both levels.** Include both paired robust estimators as distinct levels when both are substantively reasonable.

## 3. Flat `reference_settings` collisions

**Minimal fix: namespace settings by factor role, keep an explicit whitelist of shared keys, and declare cross-role constraints.**

```yaml
reference_settings:
  shared:     {trim: 0.2, exclusion: none, unit: participant, missing: listwise}
  point:      {estimator: trimmed_mean_diff}
  interval:   {method: bootstrap_t, B: 4999, seed_stream: interval}
  test:       {method: sign_flip, statistic: point, B: 9999, seed_stream: test}
constraints:
  - interval.requires: {point.estimator: [trimmed_mean_diff], shared.trim: any}
  - test.statistic == point.estimator   # or an explicitly named statistic
```

**Validation rules:**

1. **Role-namespaced keys never merge across roles.** `interval.algorithm` and `test.algorithm` cannot collide.
2. **Shared keys are a closed, registry-defined set.** They include γ, exclusion rule, analysis sample, resampling or pairing unit, and missing-data handling. A disagreement on a shared key is a hard error. Do not infer sharing from key-name equality.
3. **Cross-role constraints are declared, not implied.** Examples of real incompatibilities that must still fail:
   - a CI method that presupposes a different point estimator or γ
   - resampling trials in one role and participants in another
   - a test statistic that is undefined for the chosen estimator
4. **Closed per-method schemas.** Unknown or misplaced keys are rejected, so relocated keys cannot slip through unchecked.
5. **Independent RNG streams per role**, for reproducibility.

**Situations to label, not treat as errors:**
- **CI and test decisions may disagree**, for example a bootstrap CI excluding 0 while the sign-flip test gives p > .05. Report this and note that CI–test duality does not hold. Do not force agreement.
- **The sign-flip null is stronger than the point estimand.** For D it is symmetry about 0. For dependent Yuen it is within-pair label exchangeability, which is stronger than equal trimmed means. Label the null accordingly.

## Uncertainty

- I have not seen your code, so the schema sketch may need adapting to your existing config and factor types.
- Treating trimmed or outlier-handled estimates as sharing the substantive estimand is a reasonable convention. Strictly, trimmed location differs from the mean under asymmetry, so the exact labels are doing real work and should survive into the report.
- The relative performance of the two paired robust estimators (power, coverage) depends on the joint distribution. That argues for including both rather than choosing one a priori.
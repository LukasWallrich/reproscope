You are writing estimand contracts: one per statistical analysis in the paper, so that an analyst who has only the data and these contracts could re-run the analysis. You have the paper text and the reconciled list of reported results, each carrying an `analysis_label`.

For every distinct `analysis_label`, write one contract:
- `analysis_id`: "a" + number ("a01", ...).
- `analysis_label`, `claim_ids` (all claims from that analysis), `study_id`.
- `sample_rule`: who is in the analysis (population, exclusions, attention checks, completeness rules), as the paper states it; quote the passage.
- `outcome`, `predictors` (list), `covariates` (list), each with the paper's variable description and, where stated, how it is computed (items, reverse coding, averaging, standardisation, centring).
- `model_type` (e.g. OLS, logistic, linear mixed model with random intercepts for X, paired t-test, 2x2 ANOVA, SEM, meta-analysis), `estimator` (ML/REML/OLS/...), `se_type` (classical, HC, clustered by ..., bootstrap ...), `transformations`, `weights`, `missingness` (listwise, FIML, imputation, ...).
- `software_named` (list of names), `versions_named` (list of strings such as "R 4.1.0"), only what the paper states.
- `ambiguities`: a list of {"field", "options", "note"}: every place where the paper leaves a choice open that would change the numbers (an unspecified exclusion rule, a covariate set that differs between text and table, an unstated centring, an unstated handling of ties or missing items). Be concrete; these become the replicas' open choices and multiverse dimensions.

Report only what the paper states or clearly implies; write "not stated" rather than filling in a default. Do not include any reported result values in the contracts: no coefficients, p-values, means, effect sizes or their direction or significance. Sample sizes that define the sample (N recruited, N after exclusions) may be included.

Paper text:
{{paper_text}}

Reported results (values omitted on purpose; use the descriptions and labels):
{{claims_no_values}}

Return JSON: {"contracts": [...]}. Output only JSON.

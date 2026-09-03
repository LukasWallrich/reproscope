You read a paper once and produce two things in one JSON object: the estimand contracts for its statistical analyses, and a results-redacted methods document. Both are for an analyst who must re-run the analyses without learning what the paper found.

## Part 1 — `contracts`

One contract per statistical analysis in the paper. You have the paper text and the reconciled list of reported results, each carrying an `analysis_label`. For every distinct `analysis_label`, write one contract:

- `analysis_id`: "a" + number ("a01", ...).
- `analysis_label`, `claim_ids` (all claims from that analysis), `study_id`.
- `sample_rule`: who is in the analysis (population, exclusions, attention checks, completeness rules), as the paper states it; quote the passage.
- `outcome`, `predictors` (list), `covariates` (list), each with the paper's variable description and, where stated, how it is computed (items, reverse coding, averaging, standardisation, centring).
- `model_type` (e.g. OLS, logistic, linear mixed model with random intercepts for X, paired t-test, 2x2 ANOVA, SEM, meta-analysis), `estimator` (ML/REML/OLS/...), `se_type` (classical, HC, clustered by ..., bootstrap ...), `transformations`, `weights`, `missingness` (listwise, FIML, imputation, ...).
- `software_named` (list of names), `versions_named` (list of strings such as "R 4.1.0"), only what the paper states.
- `ambiguities`: a list of {"field", "options", "note"}: every place where the paper leaves a choice open that would change the numbers (an unspecified exclusion rule, a covariate set that differs between text and table, an unstated centring, an unstated handling of ties or missing items). Be concrete; these become the replicas' open choices and multiverse dimensions.

Report only what the paper states or clearly implies; write "not stated" rather than filling in a default.

## Part 2 — `redacted_methods`

A Markdown document with these sections: Research questions; Design and participants; Materials and measures; Procedure; Analysis plan; Software and settings. The Analysis plan has one subsection per contract, named exactly by the `analysis_label` you emitted in Part 1.

Keep, verbatim where possible: the research questions (without their expected direction), the study design, participants and recruitment, materials and measures, procedure, the description of every variable and how it is computed, the sample rules and exclusions, the analysis plan and every analytical detail (model, estimator, software, covariates, transformations, missing-data handling).

Keep the numbers that describe the study rather than its findings: years, scale ranges, number of items, thresholds, lags, stimulus durations, sample sizes, exclusion counts and rates, the mean and SD of participant age, sex and ethnicity breakdowns, and scale reliabilities reported in the methods. An analyst needs these to rebuild the sample.

Remove all outcome information, in any form: every test statistic, coefficient, effect size, p-value, confidence or credible interval, standard error, group mean or model-implied value that answers a research question; significance stars; signs and directions ("higher", "lower", "positive relationship", "declined"); result language ("significant", "supported", "as predicted", "in line with H1", "contrary to expectations"); and every directional hypothesis (replace "we expected X to increase Y" with "we examined the relationship between X and Y"). Remove results tables and figures entirely, and remove result statements woven into methods or captions. Remove the abstract's result sentences and the entire results and discussion sections apart from analytical details that appear only there — state such details in the analysis plan, without the numbers.

Where a passage would leak a result, replace it with "[redacted: result]" rather than paraphrasing around it. Do not add analytical choices the paper does not state.

## The same rule applies to Part 1

Do not put reported result values in the contracts: no coefficients, p-values, means, effect sizes, or their direction or significance. Sample sizes and exclusion rules that define the sample may be included.

Paper text:
{{paper_text}}

Reported results (values omitted on purpose; use the descriptions and labels):
{{claims_no_values}}

Return JSON: {"contracts": [...], "redacted_methods": "# ...\n..."}. Output only JSON.

You read a paper once and produce two things in one JSON object: the estimand contracts for its statistical analyses, and a results-redacted methods document. Both are for an analyst who must re-run the analyses without learning what the paper found.

## Part 1 — `contracts`

One contract per atomic statistical analysis: a specific study, outcome, contrast, model and sample. Extractor-generated `analysis_label` strings are display hints, NOT analysis identifiers. Different labels can describe the same test, and one label can cover several separate tests. Resolve identity from the paper's methods and the claims' source descriptions; never from equal reported values.

A source statement that reports a bound across an explicitly identifiable family of tests (for example, all pairwise paired tests across named conditions, or one correlation per named condition) needs one family contract. The family is a collection of separate scalar tests, not a joint multivariate test. Define its complete member set in the outcome/contrast and analysis procedure, retain the bound claims on that family, and use the underlying scalar design family (paired_t or correlation). Do not abstain merely because individual test values are not printed: the family bound can be reproduced by computing every member. Abstain only if the methods do not identify the members or their sample/design. Keep individually reported scalar analyses separate; family identity must explicitly name the complete collection.

For each contract provide `identity`: {"study": "canonical study key", "outcome": "one canonical outcome key", "contrast": "one canonical contrast or coefficient key", "model": "canonical model key", "sample": "canonical sample/exclusion key"}. Reuse exactly the same canonical keys for the same method components. Each full identity tuple must be unique. Separate paired tests of different outcomes (e.g. speed, threshold and guessing) into separate contracts even when reported together. A joint multivariate test is one analysis only when the paper actually specifies a joint model/test, not merely several univariate tests in one sentence.

Preserve every supplied claim ID. Duplicate extraction records describing the same source test belong to the SAME contract; do not discard one or create another contract because its label differs. Every complete inferential claim (test statistic, coefficient, effect size, correlation, p-value) must be assigned to exactly one contract OR explicitly listed in unassigned, never both. Shared descriptive quantities and sample counts may support multiple contracts. Keep study IDs consistent with the source claims. For each atomic analysis write:

- `analysis_id`: "a" + number ("a01", ...).
- `analysis_label`, `claim_ids` (all claims from that analysis), `study_id`.
- `sample_rule`: who is in the analysis (population, exclusions, attention checks, completeness rules), as the paper states it; quote the passage.
- `outcome`, `predictors` (list), `covariates` (list), each with the paper's variable description and, where stated, how it is computed (items, reverse coding, averaging, standardisation, centring).
- `model_type` (e.g. OLS, logistic, linear mixed model with random intercepts for X, paired t-test, 2x2 ANOVA, SEM, meta-analysis), `estimator` (ML/REML/OLS/...), `se_type` (classical, HC, clustered by ..., bootstrap ...), `transformations`, `weights`, `missingness` (listwise, FIML, imputation, ...).
- `software_named` (list of names), `versions_named` (list of strings such as "R 4.1.0"), only what the paper states.
- `ambiguities`: a list of {"field", "kind", "options", "note"}: every place where the paper leaves a choice open that would change the numbers (an unspecified exclusion rule, a covariate set that differs between text and table, an unstated centring, an unstated handling of ties or missing items). Set kind="method" when the target is known but an analytical choice is undocumented; set kind="source_identity" when the source occurrence, outcome or comparison itself is unresolved. Assigning a claim to a contract does not resolve a source identity ambiguity. Source identity ambiguities block the affected analysis; method choices become replica open choices and multiverse dimensions.

Report only what the paper states or clearly implies; write "not stated" rather than filling in a default.

For each contract also provide `design`: {"family": "independent_t"|"paired_t"|"correlation"|"mixed_anova"|"other"|"unknown", "contrast": "the specific comparison", "independent_unit": "participant/etc", "repeated_factors": [...], "n_total": integer or null, "group_ns": [n1,n2] or [], "effect_metric": "d/dz/raw difference/etc" or null, "evidence": "verbatim methods passage"}. Use null/unknown for unsupported details. Group counts must sum to n_total. A between-group difference in within-person changes is an interaction, not a paired t test. Do not derive a group split from a total. One contract must describe one identifiable scalar analysis or one explicitly enumerated family; separate analyses with different samples or designs. This design describes the methods, without reported effect values.

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

Eligible source targets (already-excluded source readings remain in a separate audit and must not be assigned for computation; use source context and target fields):
{{claims_no_values}}

Return JSON: {"contracts": [...], "term_map": [...], "unassigned": [...], "redacted_methods": "# ...\n..."}. Output only JSON.

In each structured design, set variance_assumption to equal, unequal, or unknown, and alternative to two-sided, greater, less, or unknown. Unknown is required when the paper does not identify the assumption or test direction; a reported df alone must not resolve an unstated choice. These fields gate power calculations.

Source target_outcome, target_contrast and target_model are independently written descriptions. Reuse a source label as a canonical key when appropriate. For each differing source term assigned to a canonical identity field, emit a term_map entry: {"field":"outcome"|"contrast"|"model", "study_id":"exact claim study_id or empty string", "source_text":"byte-exact source target field", "canonical":"byte-exact destination identity field", "quote":"verbatim paper evidence linking this source result to that analysis component", "note":"why these descriptions identify the same component"}. Treat null, none, unknown, unspecified and not stated as absent information; never make them aliases or use them to claim an identity conflict. One substantive source term within a study and field must have exactly one destination. Multiple genuine aliases may share a destination. Every mapping must be used. Do not use aliases to erase different intensity levels, factorial dimensions, studies, outcomes or analytical models. A located quote is evidence to inspect, not permission to merge incompatible analyses.

If a claim cannot be assigned, emit an unassigned entry: {"claim_id":"original ID", "reason":"not_an_analysis"|"methods_insufficient"|"sources_conflict", "note":"specific explanation", "quote":"verbatim evidence or null for not_an_analysis", "conflict_field":"study"|"outcome"|"contrast"|"model"|"sample"|"source_reading"|null}. Never include the same claim in a contract. Evidence is required for methods_insufficient and sources_conflict. For sources_conflict, name the conflicting field; an unknown source component alone is not a conflict. Do not fabricate an assignment to meet coverage. Unassigned required results remain an explicit finalisation gap; there is no incentive to maximise assignment or numerical agreement. Only complete source claims authorise computation. Redacted methods must contain the required design, measures and analysis procedure only; omit hypotheses, predicted directions, theory/background and conclusions.

For a one-sample t test, design.family="one_sample_t" and design.null_value is the explicitly stated design reference (e.g. scale midpoint). Preserve the test reference as a design constant rather than treating the one-sample test as paired groups.

Distinguish source identity from method convention. An omitted explicit column map is not itself a source conflict when the stated within-condition association and condition labels agree. Do not invent cross-condition/reference-condition interpretations without supporting source evidence. Record genuinely open analytical conventions as kind="method", retain alternatives, and allow a clearly labelled conventional reconstruction. Unresolved study, outcome or contrast identity remains blocking. No choice may be selected by numerical agreement.

Paper source:
{{paper_text}}

Describe the statistical methods for ONLY the supplied fixed analysis groups. Return exactly one body for each group_key. Group membership, source claim IDs, canonical identity and analysis label are controlled by the pipeline; you cannot return or change those fields. Do not merge groups or introduce new analyses. For a family describe the complete supplied list of scalar members; individually reported members remain separate groups.

Each body needs sample_rule (population, exclusions, missingness; quote supporting methods), outcome, predictors, covariates, model_type, estimator, se_type, transformations, weights, missingness, software_named, versions_named, ambiguities, and design. Explain the variables and their scoring, including items, reverse coding, summation/averaging/standardisation where stated. Describe the full fitted model for a coefficient target, while identifying the particular coefficient being checked. Preserve adjustment sets in partial correlations. Include only stated software/version information. Unknown method choices must remain explicit; do not fill in defaults because they are conventional or numerically plausible.

For ambiguities distinguish kind=method (target known, analytical choice undocumented) from kind=source_identity (which source/outcome/contrast is meant cannot be established). Method ambiguity permits a clearly labelled reconstruction and later multiverse; unresolved source identity blocks that analysis. Do not invent ambiguities from absent placeholder labels.

The design.family must agree with the assigned design_family, unless the supplied family is unknown. design.contrast is the specific scalar comparison; independent_unit identifies the sampling unit; evidence is a verbatim methods passage. State variance_assumption and alternative as unknown unless specified. Preserve a one-sample null reference as a design constant. Group counts must sum to n_total. Do not turn an interaction into a paired comparison. Regression uses family=other with the exact coefficient or omnibus target described.

These bodies will be given to a blinded analyst. Omit all reported result statistics, coefficients, effect sizes, p-values, confidence limits, outcome means, significance, and observed or hypothesised directions. Sample sizes, exclusion rules, scale ranges and other actual design constants can be retained. Do not leak results in source quotes or ambiguity notes. This is method reconstruction from the source, never inference from reproduced agreement.

Fixed analysis groups and their source descriptions:
{{groups}}

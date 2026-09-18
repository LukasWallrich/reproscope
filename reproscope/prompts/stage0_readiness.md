You are checking whether a dataset can support a set of analyses. You have a schema summary of every data file (columns, types, example values, value counts for low-cardinality columns, row counts), the codebook if one exists, and the estimand contracts of the analyses to be run. You have not seen the paper's results and must not guess them.

Produce a data-readiness record:
- `files`: for each file, its role (main data, item-level data, lookup, other) and the unit of observation (one row = one participant / trial / country-year ...).
- `keys`: identifier columns and how files join.
- `missing_sentinels`: values that encode missingness (-99, 999, "", "NA", blank strings).
- `variable_bindings`: for every outcome, predictor, covariate, weight, and sample-rule variable in every contract, the candidate column(s) that could represent it, with a note on evidence (label, value range, name). Where several columns are plausible (raw vs. recoded, several versions), list all as `candidate_columns` and leave `chosen` null; where exactly one fits, set `chosen`. Where nothing fits, set `candidate_columns: []` and explain.
- `scale_direction_notes`: places where a scale might be reversed or rescaled relative to the paper's description.
- `weights_columns`, `derived_variables_needed` (variables that must be computed from items; list the items).
- Each variable binding must include analysis_id, contract_field, file (the exact schema path), table (the exact schema table name, null for unlabelled tables), chosen (one exact column name or null), input_columns (exact source names for a derived variable), transformation (explicit formula or null), expected_type (numeric/categorical/string or null), and allowed_range (two numbers only when documented, otherwise []). Actual unresolved source identities remain candidates. Conventional method choices may be chosen only under the declared reconstruction policy below. Derived variables require input_columns and an explicit transformation. Do not write free-form qualified names in chosen.
- For numeric fields stored as strings, set numeric_parsing="strict_float" only when all observed nonmissing entries parse as finite floats, or "strict_float_blank_missing" when whitespace-only entries must explicitly become missing. The schema's numeric_parse profile checks this across ALL rows, not just examples. Describe the parsing and subsequent missing-data rule in transformation. Leave numeric_parsing null for native numeric columns or unsupported parsing. Do not silently convert malformed strings or infer numeric sentinel codes.
- Per contract: state is complete when every required input is available and bound, either source-determined or through an explicitly declared conventional reconstruction. Missing inputs or genuine unresolved source identity require abstention. Return per_analysis as [{"analysis_id": "...", "state": "complete|abstained", "abstain_reason": null or "..."}].
- `open_ambiguities`: a list of binding choices a replica will have to make.

Schema summary:
{{schema}}

Codebook (may be empty):
{{codebook}}

Contracts:
{{contracts}}

Return JSON matching the fields above. Output only JSON.

Use contract_field="outcome", "predictors[0]", "predictors[1]", "covariates[0]", etc., with the zero-based index in that contract. Bind every listed field. Range conflicts (including suspected missing-value sentinels) require an explicit documented recoding and reconciliation before completion. Do not infer sentinel codes.

For each per_analysis entry, declare outcome=bound for a complete executable binding, no_data when the relevant study or observations are not deposited, or unbound when data may be present but bindings or transformations remain unresolved. Explain no_data with file/study evidence; do not call an unresolved variable mapping absent data.

For condition-specific correlation collections, use analysis_families with one member per correlation: stable member_id, file/table, exact x and y columns, condition, exposure, explicit sample_rule, numeric_parsing and deposit evidence. These are separate analyses, not a derived outcome. Do not guess same-condition versus reference-condition pairing from numerical agreement. Condition-matched variables describe a within-condition association when the contract names that association and the deposit labels agree. Do not invent a reference-condition alternative merely because the source omits an explicit column-by-column map. An actual competing source interpretation remains unresolved; a conventional within-condition reconstruction can be computed with its assumption disclosed. Identify deposit tier (raw observations, fitted parameters, processed summaries) and do not imply upstream recomputation from a column binding.

Declare integrity_checks for each relevant analysis: unique_id, paired_complete or nested_loglikelihood, with file/table, columns and assumption_evidence. Nested checks require documented model nesting and columns ordered restricted/full; do not infer nesting from a larger-looking model label. These diagnostics are executed deterministically, preserve the input data, and gate the affected branch when an anomaly is observed.

Within per_analysis, provide sample_selection when an identifier/sample restriction is documented (file, table, id_column, included_ids or null for all rows, evidence), and grouping for independent groups (file, table, group_column, two ordered group_values consistent with the contrast, evidence). Bind these using methods and deposit labels only. Do not choose exclusions or group order from reported results. Omit unsupported selections; verification cannot authorise exclusions from the replica plan itself.

For a computable likelihood-ratio comparison of deposited per-subject maximised log likelihoods, provide likelihood_bindings with analysis_id, file, table, x (larger model), y (nested smaller model), full_parameters_per_subject, reduced_parameters_per_subject, aggregation="sum_subject_loglikelihoods", evidence from the model definitions, and an explicit assumption explaining why subject log likelihoods may be summed. Parameter counts are derived from model structure, not from a reported test statistic, p value or reported degrees of freedom. Preserve uncertainty about the unavailable fitting process. Request a nested_loglikelihood integrity check. A model with fewer free parameters must not exceed the larger model's maximised log likelihood for any participant. Never silently reverse models or clip violations.

For a grouped paired-test claim (for example, all pairwise condition comparisons), use analysis_families with one named member per required pair, just as for grouped correlations. Give each member's exact x/y columns in the oriented contrast and an explicit numeric parser. A vector of column names in one scalar variable binding does not define which pairs to compute.

Binding basis: every per_analysis entry declares binding_basis="source_determined", "conventional_reconstruction", or "unresolved". For a conventional reconstruction, list assumptions and plausible alternatives in separate fields, choose exact available input columns, and retain the assumption in the result scope. This permits ordinary analytical conventions where the substantive population, outcome and contrast are identified, without claiming that the original implementation is uniquely known. It does not permit guessing an outcome, intervention group, study, unavailable sample, reversal or missing sentinel. Do not rank choices by reported numerical agreement; never put reported result values in assumptions. Missing raw data should not block computations defined on available deposited summaries: state the upstream limitation separately.

The registered convention is condition_matched_columns only. For conventional_reconstruction, supply convention={convention_id:"condition_matched_columns",scope_quote:<exact paper quote with within/each/per/all conditions scope>,pairs:[{x:<bound column>,y:<bound column>,index:<condition index shared literally by both names>}]} and assumptions. The two indexed column sets must be one-to-one; reference/baseline/pooled pairings cannot use this convention. No other conventional reconstruction is authorised by this version. Source-determined logical entailments do not require a convention. Genuinely competing source interpretations remain unresolved.

Paper source for binding scope (never choose a binding from reported numerical agreement):
{{paper}}

For a documented subgroup, sample_selection may specify filters [{column,operator:"eq|ne|not_missing",value:<exact observed code as a string or null>}]. The controller resolves these predicates into included_ids from the deposit. Prefer this to guessing IDs from schema examples; included_ids can remain null when filters are declared. This supports a one-sample analysis of a source-defined condition without fabricating participant identifiers. Filters must follow the documented sample, never a desired numerical result.

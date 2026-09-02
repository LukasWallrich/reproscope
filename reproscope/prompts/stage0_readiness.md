You are checking whether a dataset can support a set of analyses. You have a schema summary of every data file (columns, types, example values, value counts for low-cardinality columns, row counts), the codebook if one exists, and the estimand contracts of the analyses to be run. You have not seen the paper's results and must not guess them.

Produce a data-readiness record:
- `files`: for each file, its role (main data, item-level data, lookup, other) and the unit of observation (one row = one participant / trial / country-year ...).
- `keys`: identifier columns and how files join.
- `missing_sentinels`: values that encode missingness (-99, 999, "", "NA", blank strings).
- `variable_bindings`: for every outcome, predictor, covariate, weight, and sample-rule variable in every contract, the candidate column(s) that could represent it, with a note on evidence (label, value range, name). Where several columns are plausible (raw vs. recoded, several versions), list all as `candidate_columns` and leave `chosen` null; where exactly one fits, set `chosen`. Where nothing fits, set `candidate_columns: []` and explain.
- `scale_direction_notes`: places where a scale might be reversed or rescaled relative to the paper's description.
- `weights_columns`, `derived_variables_needed` (variables that must be computed from items; list the items).
- Per contract: `state` "complete" if every required variable has at least one candidate, else "abstained" with `abstain_reason`.
- `open_ambiguities`: a list of binding choices a replica will have to make.

Schema summary:
{{schema}}

Codebook (may be empty):
{{codebook}}

Contracts:
{{contracts}}

Return JSON matching the fields above. Output only JSON.

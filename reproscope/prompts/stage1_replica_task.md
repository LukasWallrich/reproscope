# Task: reproduce the analyses described in METHODS.md from the data in data/

You are working in an isolated directory. It contains:
- `METHODS.md`: the study's methods, with all results removed.
- `data/`: the study's data files. A codebook may be present.
- `out/`: write everything you produce here.
- `CONTRACT.json`: one block per analysis under `analyses`. Each block holds that analysis's estimand contract (sample rule, outcome, predictors, model type, estimator, standard-error type, transformations, weights, missingness) and, under `quantities`, every quantity the paper reports from that one analysis, each with a `claim_id` and a description but no value. A block under `unassigned` lists quantities no contract claims; `analyses_without_data` lists analyses abstained at intake, which you must not attempt.

## Interpreters and packages

- **R**: `Rscript`, R 4.6.1. A large CRAN library is already installed; list it with `Rscript -e 'rownames(installed.packages())'`.
- **Python**: `python3` (also `python`) on PATH, 3.14, is the analysis interpreter. Its pre-installed stack is numpy, pandas, scipy, statsmodels, pyreadstat and openpyxl; list it with `python3 -m pip list`.

Declare anything you use beyond that, or your script will not run when it is checked:

- **`out/requirements.txt`** — pip format, one Python package per line, pinned (`package==1.2.3`) where you know the version, for every Python package you import that is not in the stack above.
- **`out/r_packages.txt`** — one CRAN package name per line, optionally `name==version`, for every R package your script attaches that is not already installed.

After you finish, your script is re-executed with that same `python3` interpreter, plus exactly what these two files declare. A script whose dependencies are not declared fails that check when it imports something missing. Write no file if you use only what is already there.

Each analysis is fitted **once**. Every quantity in that analysis's `quantities` list is then read out of that single fitted object and written to `out/results.json`. Do not refit the model per quantity, and do not skip quantities: a block with thirty table cells is still one fit.

Do this:
1. Inspect the data (columns, labels, value ranges) and map every variable in the contracts to columns. Do not assume; check.
2. Write one script, `out/analysis.R` (preferred) or `out/analysis.py`, that reproduces each analysis in CONTRACT.json faithfully: the same sample rules, the same variables and their computation, the same model, estimator and standard-error type as the methods describe. Use `set.seed(20260901)` (or the Python equivalent) before any stochastic step and match any stated number of bootstrap draws or iterations.
3. Where METHODS.md or the data leave a choice open (an exclusion rule, which of several similar columns, centring, coding of a categorical variable, handling of missing items), pick the single most standard option, apply it, and record it. Do not run alternative versions and do not choose by looking at what gives a cleaner result.
4. Run the script. If it fails, fix it and keep a list of every fix you made and why. Keep the run log in `out/run.log`.
5. Have the script write `out/results.json`: `{"results": [{"claim_id", "analysis_id", "value", "se", "ci_lower", "ci_upper", "n", "note"}]}` with one entry for every claim_id in every block you fitted. Values must be written by the script from computed objects, never typed by hand. For a quantity you cannot compute, add an entry with `"value": null` and the reason in `note`.
6. Write `out/trace.json` with: `filters` (each sample rule you applied, as code-level description and resulting n), `variable_bindings` (contract variable -> column(s) and any recoding), `transformations`, `model_formula` (per analysis), `missingness`, `weights`, `estimator_settings` (package, function, options), `seed`, `open_choices` (each choice from step 3: what was open, which options existed, what you chose and why), `fixes` (from step 4), `software` (the output of `sessionInfo()` or `pip freeze` as a string), `abstentions` (claim_ids you could not compute and why).

Rules: never invent data or results; never hard-code a number as a result; do not search for the paper or its results; do not look outside this directory. Stop when out/results.json and out/trace.json exist and the script runs cleanly from the top. Finish with a two-line summary of what ran and what you could not compute.

Your analysis script must regenerate results from a fresh directory containing only the supplied data, METHODS.md, CONTRACT.json, TASK.md, and your .py/.R source files. Use paths relative to the work directory or your script. Do not read previous result files or hard-code absolute workspace paths. Write sample sizes from the analysed data, and attach an SE only when its units and standardisation match the reported value.

Regenerate `out/analysis_plan.json` from the actual script with `{"protocol_version": "direct-plan-3", "analyses": [...]}`. Cover every requested analysis_id exactly once. Report operations your script executes on the supplied data. Upstream preprocessing mentioned in METHODS.md belongs in trace.json as outside the execution scope; never copy it into implemented method fields.

For each directly supported analysis, use exactly these keys:
- analysis_id; status="supported".
- family: exactly "paired_t", "independent_t", "one_sample_t", or "correlation" (scalar Pearson).
- file: a relative path under data/; table: sheet name/index or null; header: zero-based header row index or null for headerless sheets; CSV files require header=0 (the first row).
- x: a scalar column name. y: a scalar column name for paired/correlation analyses, null for independent groups.
- group_column and group_values: null for paired/correlation; for independent groups give a column and exactly two distinct ordered values. Compute the contrast as first group minus second, or x minus y for paired tests.
- id_column: identifier column or null. included_ids: the actual selected IDs or null for no ID restriction; derive this list from the script's sample selection and never type a fixed sample count.
- equal_var: true or false. alternative: exactly "two-sided", "greater", or "less".
- transformations: [] for direct use of deposited columns. The intrinsic paired difference and dz calculation are not transformations. Any additional transformation is outside this direct adapter: use unsupported instead.
- missingness: exactly "complete_cases" (drop missing analysed values) or "complete_explicit_sample" (all selected analysed values are finite). Describe the executed rule even when the paper does not specify it.
- numeric_parsing: exactly "strict_float" or "strict_float_blank_missing" (whitespace-only cells become missing; malformed numeric text remains an error).
- contrast: a short description of the actual oriented comparison.

For an unsupported operation, return only analysis_id, status="unsupported", and a nonempty reason. Other models and transformations require unsupported entries; do not substitute a supported test. Named families and likelihood comparisons use the additional closed forms below. You may still compute their requested results faithfully. Unsupported verification is separate from computation failure.

Keep free-form explanations in trace.json. Machine fields must use the exact types and enums above. Generate the plan from the same settings and selected data used for computation. A plan is a declaration checked by re-execution and independent numerical references; it does not prove itself correct.

Use variable_bindings and named members supplied in CONTRACT.json. For aggregate results return member values with exact member_ids; do not put ranges in CI fields. Supplied facts receive no computation credit. Derive analysed N from the actual included observations.

Results protocol: `results` contains exactly one row per requested analysis_id/claim_id pair. Do not create auxiliary claim IDs from member IDs. Save extra calculations outside results.json. A scalar target has a numeric value or null. An aggregate target has `value` as an array of every member's value for that target's quantity_kind, `member_ids` as the corresponding ordered IDs from the packet, and `aggregation` copied from the target. Do not replace this array with only its minimum/maximum or put member values in prose. For example, a maximum-p target needs an array of p values; a minimum-r target needs an array of correlations. Set n only when all members use the same analysed sample size, otherwise null. CI fields describe uncertainty in their named quantity, never the range of member estimates.

Additional supported plan forms under direct-plan-3:
- Named paired/correlation family: only analysis_id, status="supported", family="paired_t_family" or "correlation_family", and members (a list of complete scalar direct plans using the fields above). Each member analysis_id is its exact intake member_id, and x/y/file/sample/parser follow that member's intake binding. Return member arrays in results, not extra result rows.
- Nested likelihood ratio: only analysis_id, status="supported", family="likelihood_ratio", file, table, header, x (larger-model subject log likelihood), y (smaller-model subject log likelihood), id_column, included_ids, missingness, numeric_parsing, df_per_subject (difference in free parameters per participant from likelihood_binding), nesting="larger_contains_smaller", aggregation="sum_subject_loglikelihoods", contrast. Calculate 2*sum(x-y), df=N*df_per_subject, and upper-tail chi-square p. Require every larger-model likelihood to be at least the nested smaller-model likelihood within numerical precision. Do not clip violations or manufacture fits. This reproduces from deposited maximised likelihoods conditional on the intake aggregation assumption; it does not rerun the unavailable fitting process.

One-sample tests use family="one_sample_t", x as the measured variable, y=null, group_column/group_values=null, and null_value equal to the source-design reference in CONTRACT. A reference such as a scale midpoint is a design constant, never a paper target result. Apply the intake-authorised subgroup through included_ids; never choose it from agreement. Other direct plans may omit null_value or set it null.

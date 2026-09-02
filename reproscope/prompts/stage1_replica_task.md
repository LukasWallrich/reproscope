# Task: reproduce the analyses described in METHODS.md from the data in data/

You are working in an isolated directory. It contains:
- `METHODS.md`: the study's methods, with all results removed.
- `CONTRACT.json`: the analyses to reproduce (`contracts`) and the quantities the paper reports for each (`claims`, without their values). Every quantity has a `claim_id`.
- `data/`: the study's data files. A codebook may be present.
- `out/`: write everything you produce here.

Do this:
1. Inspect the data (columns, labels, value ranges) and map every variable in the contracts to columns. Do not assume; check.
2. Write one script, `out/analysis.R` (preferred) or `out/analysis.py`, that reproduces each analysis in CONTRACT.json faithfully: the same sample rules, the same variables and their computation, the same model, estimator and standard-error type as the methods describe. Use `set.seed(20260901)` (or the Python equivalent) before any stochastic step and match any stated number of bootstrap draws or iterations.
3. Where METHODS.md or the data leave a choice open (an exclusion rule, which of several similar columns, centring, coding of a categorical variable, handling of missing items), pick the single most standard option, apply it, and record it. Do not run alternative versions and do not choose by looking at what gives a cleaner result.
4. Run the script. If it fails, fix it and keep a list of every fix you made and why. Keep the run log in `out/run.log`.
5. Have the script write `out/results.json`: `{"results": [{"claim_id", "analysis_id", "value", "se", "ci_lower", "ci_upper", "n", "note"}]}` with one entry for every claim_id you could compute. Values must be written by the script from computed objects, never typed by hand. For a claim you cannot compute, add an entry with `"value": null` and the reason in `note`.
6. Write `out/trace.json` with: `filters` (each sample rule you applied, as code-level description and resulting n), `variable_bindings` (contract variable -> column(s) and any recoding), `transformations`, `model_formula` (per analysis), `missingness`, `weights`, `estimator_settings` (package, function, options), `seed`, `open_choices` (each choice from step 3: what was open, which options existed, what you chose and why), `fixes` (from step 4), `software` (the output of `sessionInfo()` or `pip freeze` as a string), `abstentions` (claim_ids you could not compute and why).

Rules: never invent data or results; never hard-code a number as a result; do not search for the paper or its results; do not look outside this directory. Stop when out/results.json and out/trace.json exist and the script runs cleanly from the top. Finish with a two-line summary of what ran and what you could not compute.

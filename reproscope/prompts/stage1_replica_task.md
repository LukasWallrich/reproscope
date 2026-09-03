# Task: reproduce the analyses described in METHODS.md from the data in data/

You are working in an isolated directory. It contains:
- `METHODS.md`: the study's methods, with all results removed.
- `data/`: the study's data files. A codebook may be present.
- `out/`: write everything you produce here.
- `CONTRACT.json`: one block per analysis under `analyses`. Each block holds that analysis's estimand contract (sample rule, outcome, predictors, model type, estimator, standard-error type, transformations, weights, missingness) and, under `quantities`, every quantity the paper reports from that one analysis, each with a `claim_id` and a description but no value. A block under `unassigned` lists quantities no contract claims; `analyses_without_data` lists analyses abstained at intake, which you must not attempt.

## Interpreters and packages

- **R**: `Rscript`, R 4.6.1. A large CRAN library is already installed; list it with `Rscript -e 'rownames(installed.packages())'`.
- **Python**: `python3`, 3.14. The pre-installed stack is numpy, pandas, scipy, statsmodels, pyreadstat and openpyxl; list it with `python3 -m pip list`.

Declare anything you use beyond that, or your script will not run when it is checked:

- **`out/requirements.txt`** — pip format, one Python package per line, pinned (`package==1.2.3`) where you know the version, for every Python package you import that is not in the stack above.
- **`out/r_packages.txt`** — one CRAN package name per line, optionally `name==version`, for every R package your script attaches that is not already installed.

After you finish, your script is re-executed in a fresh environment holding the stack above plus exactly what these two files declare. A script whose dependencies are not declared fails that check when it imports something missing. Write no file if you use only what is already there.

Each analysis is fitted **once**. Every quantity in that analysis's `quantities` list is then read out of that single fitted object and written to `out/results.json`. Do not refit the model per quantity, and do not skip quantities: a block with thirty table cells is still one fit.

Do this:
1. Inspect the data (columns, labels, value ranges) and map every variable in the contracts to columns. Do not assume; check.
2. Write one script, `out/analysis.R` (preferred) or `out/analysis.py`, that reproduces each analysis in CONTRACT.json faithfully: the same sample rules, the same variables and their computation, the same model, estimator and standard-error type as the methods describe. Use `set.seed(20260901)` (or the Python equivalent) before any stochastic step and match any stated number of bootstrap draws or iterations.
3. Where METHODS.md or the data leave a choice open (an exclusion rule, which of several similar columns, centring, coding of a categorical variable, handling of missing items), pick the single most standard option, apply it, and record it. Do not run alternative versions and do not choose by looking at what gives a cleaner result.
4. Run the script. If it fails, fix it and keep a list of every fix you made and why. Keep the run log in `out/run.log`.
5. Have the script write `out/results.json`: `{"results": [{"claim_id", "analysis_id", "value", "se", "ci_lower", "ci_upper", "n", "note"}]}` with one entry for every claim_id in every block you fitted. Values must be written by the script from computed objects, never typed by hand. For a quantity you cannot compute, add an entry with `"value": null` and the reason in `note`.
6. Write `out/trace.json` with: `filters` (each sample rule you applied, as code-level description and resulting n), `variable_bindings` (contract variable -> column(s) and any recoding), `transformations`, `model_formula` (per analysis), `missingness`, `weights`, `estimator_settings` (package, function, options), `seed`, `open_choices` (each choice from step 3: what was open, which options existed, what you chose and why), `fixes` (from step 4), `software` (the output of `sessionInfo()` or `pip freeze` as a string), `abstentions` (claim_ids you could not compute and why).

Rules: never invent data or results; never hard-code a number as a result; do not search for the paper or its results; do not look outside this directory. Stop when out/results.json and out/trace.json exist and the script runs cleanly from the top. Finish with a two-line summary of what ran and what you could not compute.

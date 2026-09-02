You are extracting every reported statistical result from a social-science paper. The paper's pages are attached as images, in order. Work from the images only.

Return a JSON object with one field, `claims`, a list. One entry per reported quantity: every coefficient, effect size, test statistic, p-value, confidence-interval bound, mean, standard deviation, sample size and percentage that the paper reports as a result of its own analysis, in tables, figures (where a value is printed), and in the text. Do not include numbers that describe the design (years, scale ranges, number of items, thresholds, stimulus durations) or numbers cited from other papers.

Each entry:
- `claim_id`: "c" + running number in reading order, e.g. "c001".
- `study_id`: "study1", "study2", ... ("study1" if the paper has one study).
- `claim_type`: "scalar" (a single number in text), "table_cell", "figure", "range".
- `importance`: "headline" if the quantity is one the abstract or the main hypothesis test rests on, else "supporting".
- `quantity_kind`: one of coefficient, se, p_value, t, F, chi2, z, d, r, eta2, OR, mean, sd, n, ci_lower, ci_upper, percent, other.
- `value`: the number as printed (numeric; for "p < .001" give 0.001 and set `comparator` to "<"). `comparator`: "=" / "<" / ">".
- `precision`: number of decimals as printed.
- `location`: {"page": integer page number in the PDF (1-based, counting the images), "kind": "table" | "figure" | "text", "label": e.g. "Table 2", "cell": row and column headers for table cells, e.g. "Model 2 / Openness (b)"}.
- `description`: a short description of what this quantity is, as the paper words it (which outcome, which predictor, which sample, which test). Copy the surrounding sentence for text results.
- `analysis_label`: a short label for the analysis the quantity belongs to, so that all quantities from one model share a label (e.g. "Study 1 regression of X on Y with covariates"); use the same label for all cells of one model.

Be exhaustive on tables: extract every cell that holds a result. Be exact about values; do not round. If a page image is unreadable, note it in `notes` and continue. Output only JSON.

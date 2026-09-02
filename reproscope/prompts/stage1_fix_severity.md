An analyst re-implemented a study's analysis and, while getting the code to run, made the fixes listed below. Rate each fix:
- `minor`: does not change the analysis (a typo, a package load, a path, a type coercion that preserves values).
- `major`: changes an analytical choice within the methods' stated options (a different but described estimator, a changed exclusion rule, a covariate dropped or added, a different missing-data handling).
- `critical`: changes what is estimated or the sample in a way the methods do not allow, or works around a failure by altering data or results (dropping a variable that would not converge, simulating values, hard-coding a number).

Fixes:
{{fixes}}

Context (the analysis plan):
{{contracts}}

Return JSON: {"ratings": [{"index": i, "severity": "minor"|"major"|"critical", "reason": "..."}]}. Output only JSON.

Scan the analysis script below for numeric literals that are used as, or written out as, statistical results (coefficients, means, p-values, effect sizes, test statistics, confidence bounds, sample sizes reported as results) without a computation path from the data. Design constants (seeds, scale ranges, thresholds stated in the methods, number of bootstrap draws, item counts) are fine. Literals that are fed into the results file are the concern.

Script:
{{script}}

Results file the script writes (for reference):
{{results}}

Return JSON: {"hits": [{"line": n, "literal": "...", "used_as": "...", "severity": "suspicious"|"confirmed"}], "verdict": "clean"|"suspicious"|"hardcoded"}. Output only JSON.

Use canonical quantity roles consistently across replicas. Supplied design facts may be repeated but receive no independent computation credit. Literal analysed sample sizes are not supplied facts unless the canonical role explicitly says so. Narrative-only numbers do not contaminate calculations. For every hit identify affected_claim_ids and dependency_scope (isolated, shared_computation, unknown), with evidence of the path to statistical outputs. Shared hard-coded computations invalidate descendants; isolated unsupported fields need not invalidate unrelated computations. A suspicious coincidence alone is not confirmed hardcoding.

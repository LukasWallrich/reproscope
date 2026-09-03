You are enumerating the space of defensible analytical specifications for one focal analysis. Sources, in this order: (1) the choices on which the independent replicas disagreed (their traces are below); (2) a systematic decision grid built from the methods and the data schema: sample rules (exclusions, attention checks, outlier handling), operationalisations (which columns, item subsets, reverse coding, standardisation), covariate sets, model form (estimator, link, random-effects structure), standard-error type, missing-data handling; (3) standard-practice defaults even where the methods are silent (e.g. no outlier removal vs. a common rule). Do not include choices that change what is estimated (a different outcome or predictor); the estimand stays fixed. Do not include seeds or software versions. Split the choices you identify in two. A choice that can be implemented from the data files in the schema is a factor. A choice you can name but cannot implement — typically because the files hold the output of a processing step (fitted parameters, computed scores) rather than its input — goes in `unimplementable` with the reason, not in `factors`. List every such choice you identify; do not drop it silently.

For each factor give the levels and mark which level is the paper's stated or implied choice (`paper_level`). Aim for 4–8 factors with 2–4 levels each; prefer factors that are likely to move the estimate.

Focal contract:
{{contract}}

Data schema:
{{schema}}

Replica traces (open choices and formulas):
{{traces}}

Return JSON: {"factors": [{"name": "...", "source": "trace"|"grid"|"default", "field": "sample_rule|operationalisation|covariates|model|se|missingness", "levels": [{"value": "...", "how": "concrete implementation instruction"}], "paper_level": "..."}], "unimplementable": [{"name": "...", "reason": "..."}], "notes": "..."}. Output only JSON.

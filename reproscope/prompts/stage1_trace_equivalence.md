Several analysts independently re-implemented the same analysis. Their decision traces are below. For each decision field (sample filters, variable bindings, transformations, model formula, missingness handling, weights, estimator settings), judge whether the analysts made equivalent choices, treating differently named but numerically equivalent implementations as equivalent (e.g. `lm()` vs `glm(family=gaussian)`, listwise deletion by hand vs by default).

Traces:
{{traces}}

Return JSON: {"fields": [{"field": "...", "groups": [["replica ids that agree"], ...], "note": "what differs"}], "agreement": fraction of fields on which all replicas that ran agree, "notable_divergences": ["..."]}. Output only JSON.

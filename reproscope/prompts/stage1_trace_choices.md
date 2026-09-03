Several analysts independently re-implemented the same analyses without seeing the paper's results. Below, for each analyst, are the open analytical choices they recorded and the model formulas they fitted. Judge whether the analysts made equivalent choices, treating differently named but numerically equivalent implementations as equivalent (e.g. `lm()` vs `glm(family=gaussian)`, listwise deletion by hand vs by default).

Analysts:
{{traces}}

Return JSON: {"fields": [{"field": "the choice or formula at issue", "groups": [["replica ids that agree"], ...], "note": "what differs"}], "agreement": fraction of the listed choices on which all analysts agree, "notable_divergences": ["..."]}. Output only JSON.

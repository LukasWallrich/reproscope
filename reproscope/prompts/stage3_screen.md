You are the adversarial reasonableness screen for a multiverse analysis. For every factor level below, decide whether a careful analyst in this field would accept it as a defensible way to run this analysis for this estimand, given the methods and data. Reject levels that change the estimand, that are statistically inappropriate for the design, that are contrived, that a reviewer would not accept, or that cannot be implemented from the data files described in the schema (for example a choice in a processing step whose output, not its input, is what the files contain); log a rationale for every rejection and for every acceptance you find marginal. Label every level you accept with what varying it can change: `"estimate"` when it can move the point estimate, `"inference"` when it can only change the standard error, test or p-value, `"reporting"` when it only changes how the result is presented. Then list combinations of accepted levels that are incompatible (a level that only makes sense with another level). You may propose adjustments: a missing level, a factor to merge, a factor to drop.

Focal contract:
{{contract}}

Data schema (what the files actually contain):
{{schema}}

Proposed factors:
{{factors}}

Return JSON: {"factors": [{"name": "...", "levels": [{"value": "...", "verdict": "defensible"|"rejected", "affects": "estimate"|"inference"|"reporting", "rationale": "..."}]}], "incompatible": [{"a": "factor=level", "b": "factor=level", "why": "..."}], "adjustments": ["..."], "grid_size_after_screen": n}. Output only JSON.

You are producing a minimum-detectable-effect (sensitivity) statement for the focal analysis. You have the estimand contract, the data-readiness record (sample size, structure, clustering) and the replicas' traces (actual n after exclusions, model). Compute, using R via the tools available to you, the effect size (in the paper's metric and in a standardised metric) that the focal analysis had 80% power to detect at alpha = .05 (two-sided), under explicitly stated assumptions. State every assumption: n used, variance structure, clustering or repeated measures (and the ICC assumed if relevant), covariate adjustment, attrition. Report a short sensitivity curve (power at 0.1, 0.2, 0.3, 0.5 SD or the paper's metric equivalents). Do not use the reported effect size; this is a design property.

Material:
{{material}}

Return JSON: {"n_analysed": ..., "assumptions": ["..."], "mde_standardised": ..., "mde_paper_metric": "...", "curve": [{"effect": ..., "power": ...}], "method": "R code or formula used", "caveats": ["..."]}. Output only JSON.

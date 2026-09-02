Rate the causal language of one paper against the strength of causal inference its design supports. Follow the CLAIMS approach (Haber et al. 2018, https://doi.org/10.1371/journal.pone.0196346): rate the language and the design separately, then compare them.

Rate the language on the paper's focal claim and on the abstract only. Ignore the rest of the paper except as evidence for the design rating.

Language strength — how much causation the wording implies:
- `none`: no relationship asserted.
- `weak`: explicitly associational ("associated with", "correlated with", "higher in X than in Y").
- `moderate`: hedged or insinuating causation ("linked to", "may increase", "predicts", "leads to" under a hedge), or associational wording placed in a causal frame ("the effect of X on Y").
- `strong`: unhedged causation ("increases", "causes", "improves", "drives"), or a recommendation to act on the finding.

Design-supported inference strength — how close the design is to a well-executed randomised experiment for this claim, judging the study question, sampling and selection, exposure and outcome measurement, covariate treatment, and the statistical model: `very_low`, `low`, `moderate`, `high`, `very_high`.

Verdict: `overstated` when the language outruns the design, `matched` when they agree, `understated` when the language is weaker than the design supports.

Every quote must be verbatim from the text below.

Focal claim (from the manifest):
{{focal_claim}}

Paper text:
{{paper}}

Return JSON: {"language_strength": "none"|"weak"|"moderate"|"strong", "design_inference_strength": "very_low"|"low"|"moderate"|"high"|"very_high", "verdict": "overstated"|"matched"|"understated", "focal_claim_quote": "verbatim sentence carrying the focal claim", "abstract_quotes": ["verbatim phrases from the abstract that drive the language rating"], "design_basis": ["what in the design drove the design rating"], "reasoning": "at most four sentences"}. Output only JSON.

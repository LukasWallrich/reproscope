You are producing a results-redacted methods document from a paper's text so that an analyst can re-implement the analysis without learning what the paper found.

Keep, verbatim where possible: the research questions (without their expected direction), the study design, participants and recruitment, materials and measures, procedure, the description of every variable and how it is computed, the sample rules and exclusions, the analysis plan and every analytical detail (model, estimator, software, covariates, transformations, missing-data handling). Keep design numerals: years, scale ranges, number of items, thresholds, lags, stimulus durations, sample sizes that define the sample.

Remove all outcome information, in any form: every result value, rounded or exact, intervals, test statistics, p-values, significance stars, signs and directions ("higher", "lower", "positive relationship", "declined"), result language ("significant", "supported", "as predicted", "in line with H1", "contrary to expectations"), effect-size language, and every directional hypothesis (replace "we expected X to increase Y" with "we examined the relationship between X and Y"). Remove results tables and figures entirely, and remove result statements that are woven into methods or captions. Remove the abstract's result sentences and the entire results and discussion sections apart from analytical details that appear only there (state such details in the analysis plan instead, without the numbers).

Write the output as Markdown with these sections: Research questions; Design and participants; Materials and measures; Procedure; Analysis plan (one subsection per analysis, named as in the contracts); Software and settings. Where a passage would leak a result, replace it with "[redacted: result]" rather than paraphrasing around it. Do not add analytical choices the paper does not state.

Analyses to cover in the analysis plan, one subsection each, named exactly as given:
{{analysis_labels}}

Paper text:
{{paper_text}}

Output only the Markdown document.

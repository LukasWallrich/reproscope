Paper source:
{{paper_text}}

Assign source claims to atomic statistical analyses. Return exactly ONE row for EVERY supplied claim_id, including descriptive quantities. Do not write contracts, method descriptions, results or a narrative. No benchmark or reproduction outputs are supplied.

A scalar row identifies ONE study, outcome, contrast/coefficient, model and sample. Reuse the exact source target strings as identity keys when suitable; reuse the registry for repeated analyses and synonyms. A scalar correlation is ONE unordered variable pair under ONE adjustment/sample specification. Correlations of X with Y and X with Z are different identities, even when the paper discusses them together. Each regression coefficient is a separate scalar target; the omnibus regression test has a different contrast. A table or paragraph is never itself an analysis. Do not assign several individually reported cells to an umbrella topic such as "associations with demographic variables". Equal numerical values never establish identity.

Repeated reports of the same analysis use the SAME identity. Keep every physical claim_id as a row. For correlations the two variables may exchange outcome/contrast positions, but prefer an existing registry orientation. Partial and unadjusted correlations are different models. A model key must retain relevant covariates and specifications; do not replace a known source model with an unspecified generic one. Study IDs must exactly match the supplied source study IDs.

Use kind=family ONLY for a non-scalar source aggregation (all/any/min/max/vector) that reports a collective bound or vector across identifiable scalar analyses. Enumerate all distinct member identities in members, with the underlying scalar design_family. Individual scalar cells NEVER join the family identity; they retain separate scalar rows. Use members=[] for scalar rows. If membership cannot be identified from the source, give a supported unassigned disposition.

Use kind=unassigned with identity=null, members=[], design_family=unknown and a disposition when no inferential analysis is represented or source identity genuinely cannot be recovered. Descriptive quantities (counts, percentages, means, SDs, reliabilities) normally use reason=not_an_analysis: they are still checked separately through descriptive computation/readout duties; they are not excluded from numerical accounting. An inferential quantity cannot be dismissed as not_an_analysis. For methods_insufficient or sources_conflict, cite a literal located source passage and explain the specific gap. sources_conflict needs the actual conflict_field; a missing method convention is not a source contradiction. When identity is known but a convention is unstated, assign the analysis and preserve the uncertainty for later method generation.

For each differing source target_outcome/target_contrast/target_model assigned to a canonical field, provide a term_map entry with the byte-exact source string, canonical key, study_id, literal source quote, explanation of equivalence, and claim_ids restricted to THIS chunk. Quotation fragments joined by explicit ellipses are allowed. Do not paraphrase inside quotes. Do not map a variable to a broad collection containing it: a part is not a synonym for a family. Do not erase distinct outcomes, predictors, adjustment sets, design levels or model types. Missing placeholders (null, unknown, not stated) are not aliases. Every alias must be used by its scoped claims. Registry aliases are reference information; return only mappings needed for the claims in this chunk.

Allowed design families: independent_t, paired_t, one_sample_t, correlation, mixed_anova, other, unknown. Regression coefficient/omnibus analyses use other. Do not infer an unstated correlation subtype from reported numbers. No reported result values belong in identity keys or member keys. Assigned rows use disposition=null.

Read-only registry from earlier source chunks:
{{registry}}

Claims for THIS chunk, with primary values removed:
{{claims}}

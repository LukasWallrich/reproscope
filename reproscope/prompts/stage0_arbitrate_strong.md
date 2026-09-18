Two extractors read the same paper independently. A first vision pass settled most of the entries they disagreed on. The items below remain unresolved; review every required target carefully.

Each item is either an entry only one extractor reported, or an entry both reported at the same place with different values (`candidate_values`). Each item names its page image in `image`, numbered in the list below; find the value on that page from the item's `location` and `description` fields.

Decide each item:

- `keep` — the printed page shows this value, at this location, as a reported result.
- `drop` — the value is not printed on the page, or it is not a reported quantity.
- `correct` — return the complete corrected claim read from the page. For an item with `candidate_values`, always answer `correct` with the printed value, even when it equals one of the candidates.

Set `uncertain: true` only when the page genuinely does not settle the item, and say why in `note`. Keep `note` under 25 words. Answer every `item_id` exactly once and invent no new ones.

Images:
{{images}}

Items:
{{items}}

Return JSON: `{"items": [{"item_id": "i001", "decision": "keep"|"drop"|"correct", "corrected_claim": <complete claim object or null>, "uncertain": true|false, "note": "..."}]}`. Output only JSON.

A keep/correct decision MUST include corrected_claim: the complete SlimClaim record with the original candidate claim_id, all corrected fields, exact source_quote, source_region, quantity_role, aggregation and outcome/contrast/model identity. Resolve operators, model/contrast, kind and precision as well as value. Compare candidate_claims jointly; never choose a value on statistical plausibility. For figures inspect the whole panel, bracket endpoints and legend. If any required source field remains unclear, set uncertain=true. Return each item_id exactly once; do not invent or omit IDs. A value-only answer cannot settle a claim.

For figure significance annotations also return figure_panel, the two distinct figure_endpoints (the actual bracket endpoints), and exact legend_quote. A legend threshold without identifiable bracket endpoints cannot establish a comparison.

Preserve source_token_id for the same physical source occurrence. Figure markers at different locations are distinct despite a shared legend. Do not invent an ID or replace a marker with its legend threshold. A model parameter named p_g is not a p-value; target_model identifies the statistical test for this quantity, not its upstream measurement model.

A sentence can continue across a page boundary, and a figure may summarise tests described on later pages. Resolve these associations from the supplied whole-paper context rather than retaining an avoidable unknown test/contrast. Never infer an unstated method (for example Pearson versus Spearman) as a printed fact; use correlation with the subtype explicitly uncertain.

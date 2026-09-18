Two extractors read the same paper independently. Entries they agree on are already merged. Your job is the entries below, which are of two sorts: an entry only one extractor reported, and an entry both reported at the same place with different values.

Each item names the image that shows it (`image`), numbered in the list below. An image is either a crop of the page band around the value or the whole page; its file name starts with the page number. `image: 0` means no image is available — then answer `uncertain: true`.

Read each printed quantity from its image. Use supplied paper text to resolve cross-page sentence context, study identity and the test used for a figure comparison:

- `keep` — the printed page shows this value, at this location, as a reported result. Use this only for an item one extractor reported.
- `drop` — the value is not printed on the page, or it is not a reported quantity (a citation, a year, a page number, a scale label).
- `correct` — return the complete corrected claim read from the page. For an item with `candidate_values`, always answer `correct` with the printed value, even when it equals one of the candidates.

Set `uncertain: true` when the image does not settle the item, and say why in `note`. Keep `note` under 20 words. Answer every `item_id` exactly once and invent no new ones.

Images:
{{images}}

Items:
{{items}}

Return JSON: `{"items": [{"item_id": "i001", "decision": "keep"|"drop"|"correct", "corrected_claim": <complete claim object or null>, "uncertain": true|false, "note": "..."}]}`. Output only JSON.

A keep/correct decision MUST include corrected_claim: the complete SlimClaim record with the original candidate claim_id, all corrected fields, exact source_quote, source_region, quantity_role, aggregation and outcome/contrast/model identity. Resolve operators, model/contrast, kind and precision as well as value. Compare candidate_claims jointly; never choose a value on statistical plausibility. For figures inspect the whole panel, bracket endpoints and legend. If any required source field remains unclear, set uncertain=true. Return each item_id exactly once; do not invent or omit IDs. A value-only answer cannot settle a claim.

For figure significance annotations also return figure_panel, the two distinct figure_endpoints (the actual bracket endpoints), and exact legend_quote. A legend threshold without identifiable bracket endpoints cannot establish a comparison.

Preserve source_token_id when correcting the interpretation or transcription of the same physical source occurrence. Different marker IDs within one figure are distinct annotations even if they use the same legend. Do not replace an annotation ID with a legend threshold ID. The upstream measurement model and this quantity's statistical test are distinct; target_model identifies the latter. If choosing another physical occurrence, provide its actual supplied identifier or null when none is supplied, with a reason.

A sentence can continue across a page boundary, and a figure may summarise tests described on later pages. Resolve these associations from the supplied whole-paper context rather than retaining an avoidable unknown test/contrast. Never infer an unstated method (for example Pearson versus Spearman) as a printed fact; use correlation with the subtype explicitly uncertain.

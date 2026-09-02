Two extractors read the same paper independently and produced lists of reported results. You have the page images and both lists. Produce the reconciled list.

Rules:
- Match entries across the two lists by location and description. Where both agree on value, location and quantity kind, keep the entry and set `agreed: true`.
- Where they disagree, look at the page image and decide field by field. Record what you decided and why in `arbiter_note`, and set `agreed: false`. If the image does not settle it, keep the value that is printed and set `confidence: "low"`.
- Where one extractor has an entry the other lacks, check the page: keep it if the value is printed there, otherwise drop it and note the drop in `dropped`.
- Assign fresh sequential `claim_id`s ("c001", ...) in reading order, and make `analysis_label` consistent across all cells of the same model.
- Keep `importance: "headline"` only for quantities the abstract or main hypothesis tests rest on.

Extractor A:
{{list_a}}

Extractor B:
{{list_b}}

Return JSON: {"claims": [...same fields as the input entries plus agreed, arbiter_note, confidence...], "dropped": [{"from": "A"|"B", "description": "...", "reason": "..."}], "notes": "..."}. Output only JSON.

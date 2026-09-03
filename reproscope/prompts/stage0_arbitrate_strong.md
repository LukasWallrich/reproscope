Two extractors read the same paper independently. A first vision pass settled most of the entries they disagreed on. The items below are headline claims it left open, so decide them carefully.

Each item is either an entry only one extractor reported, or an entry both reported at the same place with different values (`candidate_values`). Each item names its page image in `image`, numbered in the list below; find the value on that page from the item's `location` and `description` fields.

Decide each item:

- `keep` — the printed page shows this value, at this location, as a reported result.
- `drop` — the value is not printed on the page, or it is not a reported quantity.
- `correct` — return in `value` the number printed on the page. For an item with `candidate_values`, always answer `correct` with the printed value, even when it equals one of the candidates.

Set `uncertain: true` only when the page genuinely does not settle the item, and say why in `note`. Keep `note` under 25 words. Answer every `item_id` exactly once and invent no new ones.

Images:
{{images}}

Items:
{{items}}

Return JSON: `{"items": [{"item_id": "i001", "decision": "keep"|"drop"|"correct", "value": <number or null>, "uncertain": true|false, "note": "..."}]}`. Output only JSON.

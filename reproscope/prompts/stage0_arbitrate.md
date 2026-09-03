Two extractors read the same paper independently. Entries they agree on are already merged. Your job is the entries below, which are of two sorts: an entry only one extractor reported, and an entry both reported at the same place with different values.

Each item names the image that shows it (`image`), numbered in the list below. An image is either a crop of the page band around the value or the whole page; its file name starts with the page number. `image: 0` means no image is available — then answer `uncertain: true`.

Decide each item from the image alone:

- `keep` — the printed page shows this value, at this location, as a reported result. Use this only for an item one extractor reported.
- `drop` — the value is not printed on the page, or it is not a reported quantity (a citation, a year, a page number, a scale label).
- `correct` — return in `value` the number printed on the page. For an item with `candidate_values`, always answer `correct` with the printed value, even when it equals one of the candidates.

Set `uncertain: true` when the image does not settle the item, and say why in `note`. Keep `note` under 20 words. Answer every `item_id` exactly once and invent no new ones.

Images:
{{images}}

Items:
{{items}}

Return JSON: `{"items": [{"item_id": "i001", "decision": "keep"|"drop"|"correct", "value": <number or null>, "uncertain": true|false, "note": "..."}]}`. Output only JSON.

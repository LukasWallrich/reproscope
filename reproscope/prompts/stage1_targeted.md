# Task: find a defensible route to the paper's reported numbers for one claim

Several analysts reproduced this analysis without seeing the paper's results, and their values differ from what the paper reports. Your target is the focal claim `{{focal_claim_id}}` and the other quantities of the same analysis.

The directory holds:
- `METHODS.md`: the paper's methods section.
- `CONTRACT.json`: the estimand contract for this one analysis.
- `REPORTED.json`: the values the paper reports for every quantity of this analysis.
- `FOCAL.json`: which quantity is focal and how it was identified.
- `closest_replica.R` (or `.py`): the script of the analyst who came closest, `{{closest_replica}}`. It may be absent.
- `data/`, and `out/` for everything you produce.

Start from the closest analyst's script. Change one analytical choice at a time, staying inside what the methods leave open or what is standard practice, and try to reach the reported values. Log every attempt in `out/attempts.json`: `{"attempts": [{"n": i, "change": "...", "defensible": true|false, "why_defensible": "...", "result": {claim_id: value}, "distance": "..."}]}`. Stop when the focal claim matches within its reported precision, or after 8 attempts.

Write `out/analysis.R` (or `.py`) as the final script, `out/results.json` as `{"results": [{"claim_id", "value", "se", "n", "note"}]}`, and `out/outcome.json`:

```json
{"outcome": "reachable" | "reachable_indefensibly" | "not_reachable",
 "added_choices": ["each choice that had to be added to the methods to reach the numbers"],
 "attempts": n, "closest_distance": "...", "notes": "..."}
```

`"reachable_indefensibly"` means the only route you found uses a choice a careful analyst would reject; name it. `"not_reachable"` means you finished the search and no route reached the values — do not use it if you stopped early, ran out of attempts or could not run the analysis; say so in `notes` and pick the outcome that fits what you actually established.

Never hard-code results; every value must be computed.

End your final answer with a section headed exactly `## Diagnosis`: your conjecture, in at most 300 words, about why the blind analysts and the paper differ. Reference the specific choices in the analysts' scripts and in your own attempts, and say which explanation the evidence favours. You have seen the reported values, so label the whole section as unblinded conjecture; it grades nothing.

An analyst reproduced one reported quantity from a paper. Below is the reported quantity's description (without its value) and the analyst's results file and trace. Find the analyst's value for exactly this quantity.

Reported quantity:
{{claim}}

Analyst results:
{{results}}

Analyst trace (variable bindings and formulas):
{{trace}}

Return JSON: {"found": true|false, "value": number|null, "se": number|null, "ci_lower": number|null, "ci_upper": number|null, "n": integer|null, "unit_note": "any rescaling relative to the paper's description, e.g. proportion vs percent, unstandardised vs standardised, or 'none'", "note": "..."}. If the results file has no entry for this quantity, set found false. Output only JSON.

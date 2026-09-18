Identify only the analytical choices explicitly documented by the authors. Neither numerical agreement with their results nor a replica's implementation establishes what the authors did. For each factor, choose a listed level only when an explicit passage establishes that method; quote that passage verbatim. Return null if the choice is ambiguous, conventional, inferred from matching numbers, or unsupported. Do not infer participant identity from sample margins or numerical agreement.

Factors:
{{factors}}

Paper text (evidence for methods, not a target to match):
{{source}}

Return JSON: {"levels": [{"factor": "...", "level": "..." or null, "evidence": "verbatim method passage, or empty when unresolved"}]}. Output only JSON.


Use focal analysis context to scope each source statement by study, outcome and contrast. First identify an exact source method statement, then map it to a factor level. Never quote the supplied focal context as author evidence. Unknown, conflicting, and undocumented settings remain null. Preserve exact quotations without ellipses or reconstructed reading order.

I haven't opened the code, so file names below are inferred from your tree. Wire the term resolution as a Stage 0 sidecar artifact that the checker takes as a plain input.

## 1. Term resolution

**Where it's created**
- Create it in Stage 0, after leak audit and repair finalise the blinded contract, in a new `stage0/terms.py` with its path in `paths.py` and its model in `artifacts.py`.
- Key the cache on `sha256(canonical_json({bindings, model_type, design.contrast}) + resolver_prompt_version + model_id)`. Hashing only what the resolver reads means unrelated contract edits don't invalidate it.
- For existing runs, have the Stage 1 orchestrator call `ensure_term_resolution(contract)` before checking. It is a cache hit or one small call, and it never happens inside the checker.

**Resolver output**
- The schema is `kind` (main, interaction, level_contrast or ambiguous), `binding_keys` (an enum restricted to the bound predictors), an optional `level`, and `evidence_quote`.
- Validate deterministically that `binding_keys` is a subset of the bound predictors and that `evidence_quote` is a verbatim substring of `design.contrast`.
- If there is only one bound predictor, resolve without an LLM call.
- Otherwise run two independent resolutions. If they disagree, record `ambiguous`.
- A single small call on the mid tier is source-only, so it isn't a stronger replica.

**Checker**
- Keep `execution_evidence(plan, outputs, contract, term_resolution)` pure: the orchestrator loads the artifact and passes it in, and the checker has no LLM import.
- If the resolution is missing or ambiguous, return `term_unverified` and keep the current membership check. If it disagrees with the plan, return `term_mismatch`.
- Don't parse labels like `C(g)[T.1]` or `x:z`. Add a structured `coefficient_bindings: [binding_key…]` to the program declaration and compare it to the resolution as a set, so interaction order doesn't matter.
- Keep checking the raw `coefficient` numerically as you do now.

**Blindness and repairs**
- Never render the resolution into the initial replica prompt. It leaks no values, but it would make both replicas depend on the resolver.
- Build the repair message from a fixed template plus binding keys and the contrast quote only, and escalate in two steps:
  1. Say that declared term X does not match the term requested in `design.contrast`, and include the quote.
  2. If that fails, name the resolved binding keys.
- Record the escalation level in provenance.

**Cache and provenance**
- Leave the resolution hash out of the replica cache keys, and include it with `checker_version` in the evidence key. Re-checking is then pure re-evaluation and matching replicas stay untouched.
- Store a repair as a new attempt with `parent_attempt` and `repair_reason: term_mismatch`, and never overwrite the original.

**Validation**
- **Checker unit tests:** cover match, `predictors[0]` against a resolved `predictors[1]`, a reordered interaction, and missing and ambiguous resolutions. Run them with `llm` patched to raise, which shows the checker is deterministic.
- **Resolver tests:**
  - An out-of-binding key and a non-substring quote are rejected.
  - An identical contract is a cache hit, and an edited contrast is a miss.
  - Permuting the predictor order gives the same resolution.
- **Prompt snapshot test:** the rendered replica prompt contains nothing from the resolution artifact.
- **Checker-only replay over the cached Ohtsubo and Petersen runs:**
  - Replica files are byte-identical.
  - Only the known `predictors[0]` cases flip to `term_mismatch`.
  - Count `term_unverified` results.
- **Gold set:** hand-label the requested terms for about 15 contracts, method-only, and track resolver agreement and the ambiguous rate.

## 2. `no_data` versus `unbound`

I'm assuming `unbound` means at least two real candidate mappings that the contract doesn't choose between, and `no_data` means the coding key isn't there at all. On that reading, have the model output only evidence and compute the label in code:

- **`candidates[]`:** each has `column`, `observed_values`, `mapping` (value to label) and `source`, where `source` is a `kind` from {codebook, value_labels, column_name, contract_text} plus a `locator` of file and key or line.
- **`searched[]`:** the locations inspected.
- **Deterministic validation** of each candidate:
  - The column exists.
  - `observed_values` is a subset of the actual unique values.
  - The locator resolves and contains the mapping's labels.
  - After normalisation, the mappings differ pairwise.
- **Derived label:** zero valid candidates gives `no_data`, one gives bound (use it), and two or more distinct gives `unbound`. Log dropped candidates with the reason.

If you must keep a model-emitted label, use a discriminated union where `unbound` requires `candidates` with `minItems: 2`. Put the evidence fields before the label, and re-ask once with the validator error before coercing to `no_data`. Test it with fixtures for a missing key, a single codebook and two conflicting codebooks.
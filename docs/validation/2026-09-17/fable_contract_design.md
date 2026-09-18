## Recommendation: (a), with one twist

Make the grouping step emit one row per claim, not one entry per group. Code then does the grouping, stamps identities onto contracts and assembles the final output.

**Why not (b).** The failing invariants are global: coverage, unique identity tuples and "every mapping used". A batch-local repair cannot validate any of them, which is how your two patches failed. Repair also starts from the wrong topic-level partition, so it is a re-grouping done through a patch schema.

**Why not (c).** The call stays monolithic: the full paper goes in, and all contracts plus the redacted methods come out. That is slow (your 13-minute repair), not resumable, and scales with paper size. Haiku returning one analysis is an output-budget problem, not a reasoning one. Keep the stronger tier as an escalation for a single failed chunk.

## Data flow

**G — assignment rows (cheap model, per study, ≤~40 claims per chunk).**
- Input: a stable paper prefix, then the chunk's `claims_without_values`, then the canonical-key registry so far.
- Output: `rows: [{claim_id, kind: scalar|family|support, study, outcome, contrast, model, sample}]`, plus `families: [{identity, members[]}]`, study- and claim-scoped `term_map`, and `unassigned`.
- There are no contract bodies and no prose. The model cannot bundle by topic because it never emits a group; it has to give each claim ID its own five keys.
- Cross-page restatements become rows with the same tuple. That preserves "duplicates share a contract" without matching on values.

**Deterministic grouping (code).**
- Normalise tuples with your existing regex and group the rows.
- Assign `analysis_id` by sorted (study, first claim location).
- Derive `analysis_label` from the identity.
- Build skeleton contracts (identity, claim_ids, study_id, design.family).

**C — contract bodies (cheap model, one call per group or ≤5 groups from the same study, in parallel).**
- Input: the paper prefix, the fixed identity, the group's claim descriptions and the read-only registry.
- The output schema is `SlimContract` minus `analysis_id`, `identity`, `claim_ids` and `study_id`; code stamps those. A body call therefore cannot break assignments.

**M — redacted methods (one separate call).**
- It takes the deterministic label list and can run in parallel with C.
- The existing leak repair is unchanged.

**Assemble.** Code builds `ContractsAndMethods` and runs the existing `validate_assignments`, `source_method_errors` and `redact.repair` unchanged.

Put `{{paper_text}}` first in all three prompts so provider prefix caching makes the N calls cheap.

## Invariants

- **All claims.**
  - Gate G1 requires the chunk's input IDs to equal its row IDs plus its unassigned IDs, each exactly once.
  - On a violation, retry once with only the missing or duplicated IDs listed, then escalate the tier for that chunk only.
  - Never auto-fill rows.
- **Repeated reports.** These are the same tuple by construction. Optionally, code can flag two same-`quantity_kind` claims in one scalar group whose hidden values differ beyond rounding, asking the model to confirm the restatement without revealing the values. Equal values still never establish identity.
- **Scalar vs family.**
  - Claims with a bound or family `aggregation` must have `kind=family`.
  - A family needs at least 2 enumerated members and a scalar `design.family`.
  - Scalar claims cannot join a family group.
  - Individually reported members keep their own scalar groups.
- **Atomicity lint.** A scalar group is rejected if, after alias resolution, its claims carry more than one distinct (`target_outcome`, `target_contrast`) pair. Your existing unordered-pair rule for correlations still applies. This is the generic, structural replacement for the "age vs sex" sentence in the repair prompt. If that sentence came from benchmark failures, it should leave production prompts.
- **Shared aliases.**
  - The term map is owned by G only.
  - The registry (canonical keys plus mappings) is passed forward to later chunks and to every C call as read-only.
  - One source term has one destination within a study and field, which is already enforced.
  - Chunking by study keeps the registry chain short, because identity is study-scoped anyway.

## Cache keys

All keys go through `response_cache.key` and use content hashes, never analysis IDs.

- **G:** prompt version, schema, tier, `paper_hash`, sorted chunk claim content hash and `registry_in_hash`.
- **C:** prompt version, schema, tier, `paper_hash`, normalised identity tuple, sorted member claim hashes and registry hash restricted to this study.
- **M:** prompt version, tier, `paper_hash` and sorted label list.

Store the responses as `logs/group_<key>.response.json` and `logs/contract_<key>.response.json`. Resumption means re-assembling from what exists and calling only the missing or invalid keys. Adding one claim re-runs one chunk and the groups it touches. This replaces the `resume_candidate` path.

## Gates

1. **G1** (per chunk): coverage, no unknown IDs, non-empty keys, study matches the claim.
2. **G2:** the atomicity and family lints above.
3. **G3** (global): the existing `validate_assignments` on the skeletons, covering unique tuples, mappings used and target conflicts. Errors route back to the owning chunk only.
4. **G4** (per body): schema, `group_ns` sum, design family consistent with G's `kind`, and a leak scan of the body.
5. **G5:** the full existing validation plus redaction repair. On failure, write `invalid_contracts.json` as now.

Repairs stay bounded at one same-tier retry with chunk-scoped errors and one escalated retry. After that the chunk fails explicitly, with no fabricated coverage.

## Minimal implementation

1. Add `stage0_group.md` from the prompt's current identity, family, alias and unassigned paragraphs. Add `stage0_contract_body.md` from its field list and design paragraphs. Cut `stage0_contracts.md` down to Part 2 only.
2. Add `stage0/grouping.py` with the `AssignmentRow`, `Family` and `GroupingChunk` schemas, study chunking, the registry threading, G1–G2 and the deterministic grouper.
3. In `contracts.py`, add a `ContractBody` schema and make `run()` do G → group → G3 → parallel C and M → stamp → existing validation → save. Extend `PROMPTS` to the three names.
4. Let `_generate` take the tier and a cache path per key. Delete the whole-draft patch loop. Keep `contract_repairs.apply` only if you want escalated chunk reruns expressed as patches; otherwise a rerun simply replaces the chunk file.
5. Tests:
   - G1 rejects a dropped ID.
   - The lint rejects a synthetic two-pair scalar group.
   - A restatement on two pages gives one contract.
   - A family bound plus individually reported members gives N+1 contracts.
   - A rerun with a warm cache makes zero calls.

Blindness is unchanged. Values never enter any prompt, and the row and body schemas have no numeric result fields. Everything downstream still passes through the leak scan.

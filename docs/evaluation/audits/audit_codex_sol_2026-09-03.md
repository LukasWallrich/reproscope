The owner is right: the measured run is economically far outside the stated envelope. The ledger totals 75.60M tokens, 5,058 calls, 32.32 cumulative model-hours, $4.99 metered API spend, and $175.91 in subscription list-price equivalent—at least $180.90 total economic cost. This is still an underestimate because Codex subscription calls have no list-price equivalent recorded. Against five pilot papers, that is at least ~$36/paper, versus the intended $2–10 ([SCOPE.html:383](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/SCOPE.html:383); [ledger_breakdown.txt:1](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding/reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:1>)).

## 1. Ranked sources of waste

Percentages below use 75.60M tokens, $180.90 economic cost, and 32.32 cumulative hours as denominators.

1. **Agentic replicas are over-provisioned and carry enormous repeated context.**

   Measured: 21.17M tokens, $32.92 list/API cost, 6.81 hours: **28.0% of tokens, 18.2% of known cost, 21.1% of time** ([ledger lines 15–20](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding/reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:15>)). `models.toml` actually schedules ten replicas per paper—Opus×2, Fable×1, Sol×1, Luna×2, GLM×2, DeepSeek×2—not the scope’s production design of three families×two runs ([models.toml:24](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/models.toml:24); [SCOPE.html:486](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/SCOPE.html:486)).

   The agent task asks every replica to reproduce every bound analysis and claim ([stage1_replica_task.md:9](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/prompts/stage1_replica_task.md:9)). Opencode adds its roughly 17k-token scaffold on the first/each uncached turn; measured opencode replicas average about 225k tokens each. Claude is worse in apparent volume: the route sums ordinary, cache-creation, and cache-read tokens together ([llm.py:303](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/llm.py:303)). A representative 14-turn Opus replica had only 26 ordinary input tokens but 53k cache-created and 505k cache-read tokens; a 20-turn run read ~936k cached tokens. Caching reduces price, but it does not remove latency or the repeated growing-history workload. Separate `claude -p` processes also do not share a conversation ([llm.py:251](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/llm.py:251)).

   **Fix:** production v0.1 should run three diverse cheap replicas once each. Add a second run only for the family implicated in material disagreement. Keep frontier replicas as an offline calibration arm, not in every paper. Replace opencode’s general-purpose scaffold with a lean analysis-specific tool loop, or have one agent produce a preregistered plan and script in a bounded number of turns. Set hard limits such as 12 tool turns and 250k input-equivalent tokens per replica. Split work by data-bound focal analysis rather than giving every replica the entire bound claim inventory.

2. **Targeted reconstruction is the single largest token bucket and is repeatedly rerun.**

   Measured: 17.24M tokens, $19.48, 0.88 hours: **22.8% of tokens and 10.8% of cost** ([ledger line 21](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding-reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:21>)). Ten launches occurred for at most five papers. The work directory contains the full paper, all claims/contracts, all reported values, and every replica’s output and trace ([targeted.py:42](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/targeted.py:42)). The prompt then asks an agent to search up to 12 analytical attempts ([stage1_targeted.md:3](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/prompts/stage1_targeted.md:3)). “12 attempts” does not cap agent turns: one observed targeted Claude run took 41 turns, created ~98k cache tokens, and reread 2.76M cached tokens.

   **Fix:** launch this only after the final replica lineup, only for the focal/headline mismatch, and only if the mismatch exceeds a substantive threshold. Supply:

   - the focal contract and reported focal quantities;
   - the relevant methods/results passages, not `PAPER.md`;
   - a normalized comparison of replica decisions;
   - the closest one or two scripts, not every script and trace.

   Start from a deterministic candidate grid derived from trace differences. Give the agent at most 4–6 explicitly enumerated attempts, then stop. Route to a cheaper capable coding tier; escalate once to frontier only if the compact search fails.

3. **The original per-claim linker created a literal claims × replicas call explosion.**

   Measured: 4,691 calls, 10.81M tokens, $2.06, 9.34 hours: **14.3% of tokens and 28.9% of all time** ([ledger line 14](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding-reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:14>)). Of the pilot-ledger calls, 3,197 failed, mostly after the OpenRouter balance was exhausted. The design explicitly proposed one model call per claim ([SCOPE.html:236](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/SCOPE.html:236)), and `match.run` forms the Cartesian product of linkable claims and traces ([match.py:349](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/match.py:349)).

   The current direct-link shortcut is correct and should eliminate nearly all of this: replicas already write `claim_id`, so `results.json` is the join key ([match.py:228](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/match.py:228)).

   **Fix:** drop normal link calls completely. Reject or repair malformed replica output once per replica. If legacy output lacks IDs, make one batched mapping call per results file—not one per claim—and cache it by the hashes of the claim inventory and results file.

4. **Stage 0 arbitration sends both exhaustive claim lists and every page image to Opus.**

   Measured: 8.96M tokens, $27.97, 1.46 hours: **11.8% of tokens and 15.5% of cost**, the largest single cost line ([ledger line 2](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding/reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:2>)). The arbiter prompt includes both complete extraction lists ([arbitrate.py:116](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/arbitrate.py:116)) and attaches `images=pages`, meaning the whole rendered paper is sent again ([arbitrate.py:121](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/arbitrate.py:121)).

   **Fix:** merge exact agreements deterministically. Only arbitrate unmatched or disagreeing fields, grouped by page. Send the relevant page crop plus the two conflicting records to a cheap vision model; reserve a strong model for unresolved headline claims. Do not resend agreed entries or unrelated pages. This should reduce arbitration from a whole-paper call to perhaps 1–4 small disagreement batches.

5. **Other Stage 0 strong calls repeatedly process paper-scale material.**

   Collectively, arbitration, contracts, readiness, redaction, and scrubbing consumed about **14.38M tokens and ~$73.9 known list cost**—roughly 19% of all tokens and 41% of economic cost. This matches the pilot note that Stage 0 alone had already exceeded the envelope ([PILOT_NOTES.md:43](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/docs/PILOT_NOTES.md:43)).

   Concrete sources:

   - Contract construction includes the full paper plus every claim description ([contracts.py:89](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/contracts.py:89)): 1.62M tokens and $20.31.
   - Redaction sends the full paper to Opus ([redact.py:95](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/redact.py:95)): 753k tokens and $8.05.
   - Readiness includes the complete per-column schema, examples, means/value counts, codebook, and all contracts ([readiness.py:255](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/readiness.py:255)): 2.20M tokens and $7.99.
   - Extraction itself is comparatively cheap: 1.07M tokens and $0.50 across both vision models. The expensive part is re-reading its output and the paper afterward.

   **Fix:** create a deterministic document index once: abstract, methods subsections, analysis paragraphs, result-bearing pages, and table captions. Contracts need only the methods/analysis excerpts and a compact `claim_id → analysis_label/location` index. Redaction should start from those same excerpts rather than asking a model to regenerate a new document from the entire article. Readiness should receive only columns lexically or embedding-matched to the focal/bound contracts; omit numeric means and example observations unless needed to disambiguate a binding. Route ordinary contract/redaction/readiness work to a cheap structured tier, with strong escalation only for low-confidence fields.

6. **Stage 2 repeats full-paper review work and all replica scripts.**

   Measured Stage 2: 4.18M tokens, $26.07, 0.91 hours: **5.5% of tokens and 14.4% of cost** ([ledger lines 24–27](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding-reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:24>)). The broad pass alone is 2.85M tokens and $19.43. It concatenates up to 120k paper characters, the schema, every replica script and results file, and the match summary ([review.py:38](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage2/review.py:38); [review.py:605](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage2/review.py:605)). The causal-language call also receives the whole paper even though its own prompt says it rates only the focal claim and abstract ([review.py:346](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage2/review.py:346); [stage2_causal_language.md:3](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/prompts/stage2_causal_language.md:3)).

   **Fix:** give causal review the abstract, focal sentence, and a structured design card. Keep MDE deterministic; the existing implementation already supports that and should abstain rather than fall into an expensive agentic fallback for unsupported designs ([review.py:439](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage2/review.py:439)). Combine causal-language and focal alignment into one bounded call. For broad review, use the relevant methods/results sections, schema anomalies, static lint output, the best script, and a diff of other scripts against it. Do not paste ten near-duplicate scripts.

7. **Diagnosis republishes the paper, all traces, all scripts, all results, and large derived artifacts.**

   Measured: 1.74M tokens and $16.99: **2.3% of tokens but 9.4% of cost** ([ledger line 11](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding/reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:11>)). Ten calls were made. Its input includes 60k paper characters, every trace, up to 12k characters per script, results, and up to 40k each of match, targeted, and rerun artifacts ([diagnose.py:16](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/diagnose.py:16); [diagnose.py:24](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/diagnose.py:24)).

   **Fix:** run once after Stage 1 is final. Feed only headline mismatch rows, normalized trace differences, relevant script hunks, targeted outcome, and cited paper passages. Merge the diagnosis into the targeted reconstruction’s final response when targeted runs; otherwise use one small non-agentic call.

8. **Systematic contract and redaction retries approximately double those steps.**

   Contracts made 15 calls: eight first attempts and seven explicit leak retries. The retry portion accounts for roughly **50% of contract tokens, cost, and time**. Redaction made six first attempts and six retries; retries similarly account for roughly half of its 753k tokens and $8.05. The retry loops resubmit the original full prompt plus the detected hits ([contracts.py:100](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/contracts.py:100); [redact.py:325](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/redact.py:325)).

   There is also a second retry layer inside `llm.call`: any schema validation failure resends the original prompt, previous response, and validation error ([llm.py:455](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/llm.py:455)). The ledger records only the final attempt’s token statistics, so actual retry token use is undercounted ([llm.py:524](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/llm.py:524)).

   **Fix:** never ask the contract model to paraphrase result-bearing descriptions. Construct value-free claim stubs deterministically, then apply deterministic numeral/direction removal to free-text fields. For redaction, select and transform paragraphs before the call, and redact detected spans locally instead of regenerating the entire document. Record every physical attempt separately in the ledger.

9. **Description scrubbing uses expensive fixed-overhead Claude calls for many tiny strings.**

   Scrub plus the earlier `scrub_descriptions` route consumed 849k tokens, $9.56, and 0.39 hours: **5.3% of total cost**. `SCRUB_CHUNK = 120` creates multiple independent Claude processes ([redact.py:42](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/redact.py:42)); each pays the large Claude Code system/tool context even though the task is simple string rewriting. The cache is useful across reruns, but it keys by item ID and exact source text, so any extraction wording change invalidates entries ([redact.py:136](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/redact.py:136)).

   **Fix:** make extraction emit both `description_original` and a schema-constrained `blind_description`, then validate the latter deterministically. Otherwise batch all fragments into one cheap API call per paper, or one call per analysis—not arbitrary 120-item chunks through `claude -p`. Exclude already structured contract fields that need no rewriting.

10. **Audits and Stage 3 have modest token cost but very poor wall-time efficiency.**

   Hardcoding and fix-severity checks consumed 1.53M tokens, ~$0.49, but **4.57 hours**, 14.1% of time ([ledger lines 12–13](</private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding/reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:12>)). One audit is launched per replica, with up to 60k characters of script/results ([audit.py:50](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/audit.py:50)).

   Stage 3 execution used 1.42M tokens, $0.275, and 1.94 hours; its `paper_level` helper used another 1.40 hours for only four calls ([ledger lines 29–31](</private/tmp/claude-501/-Users-lukaswallrich-Documents/Coding/reproduction-pipeline/88ade0fa-20db-41fe-9d16-318bc4ca0600/scratchpad/ledger_breakdown.txt:29>)). The executor is a general agent rewriting a working analysis into a loop ([stage3_execute.md:10](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/prompts/stage3_execute.md:10)), after which the pipeline reruns the script again for verification ([multiverse.py:1024](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage3/multiverse.py:1024)).

   **Fix:** use AST/static checks for suspicious literals first, then batch all flagged scripts into one cheap audit. Rate fixes in the same batch. For Stage 3, generate the grid runner from a deterministic R/Python template or require the Stage 1 script to expose a `run_spec(spec)` function. Use an LLM only to produce factor-to-code patches. Compute distribution summaries and factor contrasts deterministically; the prose interpretation need not be Opus.

11. **Resume semantics allow downstream recomputation while the replica lineup is incomplete.**

   Stage 1 deliberately stays “open” until all configured replicas exist, but nevertheless runs match, targeted reconstruction, rerun, and diagnosis after every partial family invocation ([stage1/__init__.py:56](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/__init__.py:56)). As the trace fingerprint changes, match invalidates, which invalidates targeted and diagnosis. This explains 14 trace-equivalence calls, ten targeted calls, and ten diagnoses for five papers. Stage 2 was also run against moving Stage 1 inputs: eight causal, eight alignment, ten broad, and four MDE calls. Stage 3 recorded eight executor and nine interpretation calls.

   `--force` is especially dangerous: it is propagated to every replica and every downstream step ([stage1/replicas.py:418](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/replicas.py:418)). In Stage 3, `force` invalidates all seven steps ([stage3/__init__.py:32](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage3/__init__.py:32)).

   **Fix:** separate `run replicas` from `finalize stage1`; do not run targeted, diagnosis, Stage 2, or Stage 3 until the selected lineup is frozen. Add step-level `--force-step`, immutable run IDs, and content-addressed caches. Cache each model result by model, route, prompt hash, input-file hashes, schema hash, and relevant configuration—not merely by whether an output filename exists.

## 2. Proposed v0.1 per-paper budget

This is a production budget, not the calibration experiment. It targets **$3.5–8 list price per ordinary paper**, with a hard $10 cutoff. Because Codex currently reports no list-price equivalent, budget enforcement must use a configured shadow price for every subscription model.

| Stage | Calls per paper | Input cap | Expected list cost | Trade-off |
|---|---:|---:|---:|---|
| Stage 0 | 5–8 | 200–350k tokens | $0.7–1.8 | Primary extraction on candidate/result pages; second vision pass only on uncertain/headline pages. Small risk of lower recall for obscure supporting results. |
| Stage 1 base | 3 replica agents + 1 batched audit | 750k–1.2M | $1.8–3.5 | Three families, one run each. Retains between-family diversity but loses precise within-family variance estimates. |
| Stage 1 escalation | At most 1 targeted call; diagnosis folded into it | 150–300k | $0–1.5 conditional | Smaller search may miss a convoluted but defensible path. Report “search exhausted under budget,” not “not reachable.” |
| Stage 2 | 2 calls; MDE deterministic | 100–200k | $0.6–1.4 | Combined focal checks and compressed broad review may miss issues in unrelated supporting analyses. |
| Stage 3 | 1 enumerate/screen call + 0–1 executor call | 100–250k | $0.4–1.2 | Template execution supports fewer exotic model families; unsupported cases should abstain or request escalation. |
| **Total** | **11–15 base, +1 conditional** | **~1.3–2.3M** | **$3.5–8 typical; hard stop at $10** | Less exhaustive on supporting claims and less precise replica-dispersion estimates, but preserves the focal review objective. |

Operational rules:

- No frontier Opus replica by default. Use frontier runs only for calibration or explicit escalation.
- Stop a stage before launching a call that would cross its token or dollar allocation.
- One model call may not ingest more than 60k input tokens without an explicit “large-context” budget.
- Agentic calls get both a turn cap and a token cap; “12 analytical attempts” is not a turn cap.
- Report economic cost as `api_usd + subscription_list_equiv + configured_codex_shadow_cost`, not metered cash alone.

## 3. Length × claims × replicas scaling

The current design contains several multiplicative paths:

- **Paper length P:** two vision passes are roughly `2P/chunk`, then arbitration rereads all P images, contracts and redaction reread full text, and Stage 2 rereads it again.
- **Claims C:** exhaustive extraction increases arbitration output, contract linkage, description scrubbing, blind contracts, replica workload, and match-table size.
- **Replicas R:** each replica receives all bound analyses; audit is per replica; trace comparison consumes all traces; targeted reconstruction and diagnosis ingest all scripts/traces/results; Stage 2 broad review does the same.
- The former linker was explicitly **C × R** calls.
- Agentic history adds a turns factor **T**, producing roughly `R × T × growing_history`, even when most history is cache-read.
- Incremental execution adds another effective R factor because every newly added replica invalidates match → targeted → diagnosis → Stage 2.
- Stage 3’s grid is multiplicative in factor levels and can become exponential independently of paper length ([stage3_enumerate.md:3](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/prompts/stage3_enumerate.md:3)).

Break the scaling with a funnel:

1. Deterministically index pages and sections.
2. Extract all claims cheaply, but identify headline/data-bound analyses immediately.
3. Build one compact analysis packet per bound analysis.
4. Run replicas on packets, not the paper-wide inventory.
5. Join outputs by IDs; never link claim-by-claim with a model.
6. Normalize each trace once, then pass only a consensus vector and differences downstream.
7. Give targeted reconstruction the closest script plus deltas.
8. Give Stage 2 a canonical script plus cross-replica diffs.
9. Cap Stage 3 by adaptive sampling or a fractional factorial design when the full grid exceeds a fixed compute limit.

That changes the expensive path from approximately `P × C × R` behavior to `P` for indexing/extraction plus roughly `R × focal-analysis-size`, with downstream work largely independent of the number of supporting claims.

## 4. Correctness risks noticed

- **Stale artifacts can be blessed as current.** Stage 0’s top-level `done.json` hashes prompts and inputs, but individual steps reuse any existing output without checking those hashes ([stage0/__init__.py:22](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/__init__.py:22); [contracts.py:84](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/contracts.py:84)). After a prompt change, the stage can reuse old artifacts and write a new `done.json`. Stage 3 has the same filename-existence problem.

- **Match caching omits replica results.** Its fingerprint hashes only top-level trace files, not `results.json` or scripts ([match.py:313](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/match.py:313)). Corrected results can therefore leave `match.json` stale.

- **Focal-claim binding is unsafe.** Stage 2 matches the manifest focal claim by numeric value alone, then falls back to the first headline/first claim and first contract ([review.py:205](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage2/review.py:205)). Repeated values such as `.05`, sample sizes, or means can select the wrong analysis.

- **Invalid targeted output becomes `not_reachable`.** An absent or invalid outcome is coerced to `not_reachable`, even though the record may separately be marked abstained ([targeted.py:123](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage1/targeted.py:123)). That overstates evidence against the paper.

- **Retry accounting is incomplete.** `llm.call` stores only the final attempt’s usage; earlier schema-invalid or transient attempts disappear from token/cost totals while their duration remains included.

- **The leak scan deliberately ignores small integers and threshold p-values.** That avoids false positives but permits genuine results in those forms ([leakcheck.py:101](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage0/leakcheck.py:101)). The semantic audit cannot establish leakage reliably because it has not seen the original result.

- **Stage 3 confidence is too optimistic.** It becomes `"high"` whenever executor verification reports no problems, regardless of focal-binding confidence or uncertainty in enumeration and screening ([stage3/__init__.py:329](/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/reproscope/stage3/__init__.py:329)).

The immediate priorities are: permanently eliminate claim-level linking, freeze the replica lineup before downstream work, replace whole-paper arbitration with page-local disagreements, and cap/compact targeted reconstruction. Those four changes remove most of the token and wall-time pathology without weakening the core focal-analysis objective.

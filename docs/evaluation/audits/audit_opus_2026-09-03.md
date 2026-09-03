# reproscope pilot — efficiency audit

Read-only audit of the five-paper pilot (2026-09-02 14:27 UTC → 2026-09-03 11:20 UTC).
Source: `runs/<paper_id>/ledger.jsonl` (5,047 rows), `stage0/logs/*.log`, `stage1/replicas/*/agent.log`, and the artifacts under `runs/`.
Scratch scripts: `scratch_audit_{ledger,fail,main,dupes,leak1,leak2,turns,turns2,split}.py` in this directory.

## How the money is counted

| field | meaning | source |
|---|---|---|
| `cost_usd` | cash charged. OpenRouter `usage.cost` and opencode `part.cost` only. | `llm.py:212`, `llm.py:411` |
| `cost_usd_equiv` | list-price equivalent of `claude -p` calls, from the CLI's own `total_cost_usd`. Prepaid seat, no marginal cash. | `llm.py:310`, `ledger.py:30-37` |
| `tokens_in` (claude_p) | `input + cache_read + cache_creation` summed together. | `llm.py:304-307` |
| codex | one total booked as `tokens_in`; **no price at all** — `cost_usd = 0.0` and no `cost_usd_equiv`. | `llm.py:358` |

**Reconciliation to the stated ~USD 185.** The ledger books USD 171.45 list-equivalent, all of it `claude -p`. The 27 codex calls (1.76 M tokens: Stage 0 leak audit, 15 replicas, Stage 3 screen) carry no price in the ledger. The gap between USD 171 and the owner's USD 185 is the unpriced codex column, not a discrepancy.

**Wall time.** Cumulative `duration_s` is 30.9 h but calls run 4–6 wide, so that is not elapsed time. Active wall (summing gaps under 30 min, which drops the overnight break) is **5.8 h across all five papers**, 2.0–4.6 h per paper.

---

## 1. Where it went

### 1.1 By stage (successful calls only)

| stage | calls | Mtok | api $ | list-equiv $ | total $ | share | $/paper | active h |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 intake | 96 | 14.8 | 0.45 | 69.41 | 69.86 | 39.6% | 13.97 | 2.4 |
| 1 replication | 1,669 | 53.4 | 4.07 | 74.62 | 78.68 | 44.6% | 15.74 | 4.4 |
| 2 review | 16 | 4.2 | 0.00 | 26.07 | 26.07 | 14.8% | 5.21 | 0.9 |
| 3 multiverse | 30 | 2.2 | 0.41 | 1.35 | 1.77 | 1.0% | 0.35 | 1.6 |
| **total** | **1,811** | **74.5** | **4.93** | **171.45** | **176.38** | | **35.28** | **5.8** |

Stage 3 — the whole specification curve — costs 1% of the run. Stages 0 and 2, which do nothing but read the paper, cost 54%.

### 1.2 By step, ranked by cost

| stage/step | calls | Mtok | api $ | list $ | total $ | share | tok_in / call | $/call | min/call |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1/replica | 50 | 21.17 | 1.47 | 31.45 | 32.92 | 18.7% | — | — | — |
| 0/arbitrate | 5 | 8.20 | 0.00 | 25.78 | 25.78 | 14.6% | 1,537,197 | 5.16 | 14.4 |
| 1/targeted | 6 | 17.24 | 0.00 | 19.48 | 19.48 | 11.0% | 2,836,856 | 3.25 | 8.1 |
| 2/broad | 6 | 2.85 | 0.00 | 19.43 | 19.43 | 11.0% | 443,694 | 3.24 | 6.4 |
| 0/contracts (+retry) | 12 | 1.44 | 0.00 | 18.03 | 18.03 | 10.2% | 96,096 | 1.50 | 4.1 |
| 1/diagnose | 6 | 1.74 | 0.00 | 16.99 | 16.99 | 9.6% | 287,222 | 2.83 | 0.5 |
| 0/scrub | 20 | 0.80 | 0.00 | 8.87 | 8.87 | 5.0% | 32,898 | 0.44 | 1.1 |
| 0/redact (+retry) | 12 | 0.75 | 0.00 | 8.05 | 8.05 | 4.6% | 52,023 | 0.67 | 1.9 |
| 0/readiness | 5 | 2.20 | 0.00 | 7.99 | 7.99 | 4.5% | 417,216 | 1.60 | 4.6 |
| 1/trace_equivalence | 11 | 0.78 | 0.00 | 6.69 | 6.69 | 3.8% | 66,305 | 0.61 | 1.0 |
| 2/alignment | 4 | 0.28 | 0.00 | 2.82 | 2.82 | 1.6% | 61,625 | 0.71 | 1.4 |
| 2/causal_language | 4 | 0.22 | 0.00 | 2.23 | 2.23 | 1.3% | 52,662 | 0.56 | 0.6 |
| **1/link_results** | **1,494** | **10.81** | **2.06** | 0.00 | **2.06** | **1.2%** | 7,236 | 0.0014 | 0.4 |
| 2/mde | 2 | 0.83 | 0.00 | 1.59 | 1.59 | 0.9% | 405,926 | 0.80 | 2.2 |
| 3/interpret | 5 | 0.17 | 0.00 | 1.35 | 1.35 | 0.8% | 32,539 | 0.27 | 0.4 |
| 0/scrub_descriptions | 1 | 0.05 | 0.00 | 0.69 | 0.69 | 0.4% | 37,594 | 0.69 | 1.8 |
| 0/extract (2 models × pages) | 34 | 0.93 | 0.45 | 0.00 | 0.45 | 0.3% | — | 0.013 | 2.4 |
| 1/hardcoding_audit | 49 | 1.21 | 0.41 | 0.00 | 0.41 | 0.2% | — | 0.008 | 4.4 |
| 3/execute | 6 | 1.42 | 0.28 | 0.00 | 0.28 | 0.2% | — | 0.047 | 17.7 |
| all remaining (7 steps) | 79 | 0.87 | 0.26 | 0.00 | 0.26 | 0.1% | | | |

**The 114 `claude -p` calls — about 23 per paper — account for 97% of the cost.** The 1,494 cheap link calls that dominate the call count are 1.2% of the money — but 9.1 cumulative hours and, in the first attempt, the reason the OpenRouter balance ran out (§2.1).

### 1.3 First run vs retries, reruns and failures

Buckets: per-item steps (`link_results`, `extract:*`, `scrub:*`, `fix_severity`, `*hardcoding_audit`) are all first-run by construction; a singleton step is first-run on its first successful occurrence per paper and a rerun thereafter; `:retry` is its own bucket; the 09-03 10:00–11:20 window is the `scratch_repair.sh` rerun.

| bucket | calls | $ | share |
|---|---:|---:|---:|
| first-run, singleton steps | 125 | 128.91 | 73.1% |
| **systematic `:retry` (contracts + redact)** | **12** | **12.85** | **7.3%** |
| first-run, per-item cheap calls | 1,656 | 12.62 | 7.2% |
| **rerun: `scratch_repair.sh` (09-03)** | **9** | **12.00** | **6.8%** |
| **rerun: development iteration (09-02, Ohtsubo)** | **9** | **9.99** | **5.7%** |
| 402 Payment Required, 0 tokens billed | 3,200 | 0.00 | 0.0% (1.05 h) |
| other failures (32 `claude exited 1`, 4 misc) | 36 | 0.00 | 0.0% |
| **total** | **5,047** | **176.38** | |

**19.8% of spend (USD 34.84) is retries, reruns and a bug-fix cascade.**

### 1.4 Per paper: what a clean single run costs

| paper | pages | paper.txt | claims | contracts | clean $ | retry $ | rerun $ | actual $ | active h |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Axt_JournExpSocPsych_2018_zK2 | 60 | 115 k | 229 | 19 | 36.84 | 2.62 | 0.67 | 40.13 | 2.0 |
| Hurst_EvoHumanBehavior_2017_yypJ | 8 | 82 k | 258 | 11 | 38.21 | 2.11 | 0.00 | 40.32 | 3.2 |
| Ohtsubo_EvoHumanBehavior_2014_zlm2 | 30 | 55 k | 204 | 40 | 26.53 | 3.91 | 19.19 | 49.64 | 4.6 |
| Hertel_ClinPsychSci_2018_YabW | 10 | 60 k | 105 | 12 | 22.37 | 1.93 | 0.65 | 24.95 | 2.4 |
| Petersen_Cognition_2017_yJwG | 9 | 78 k | 117 | 12 | 17.58 | 2.29 | 1.47 | 21.35 | 2.8 |
| **mean** | | | 183 | 19 | **28.31** | 2.57 | 4.40 | **35.28** | 3.0 |

**A clean single run costs USD 17.58–38.21 per paper at list price — 2–4× the top of the SCOPE envelope (`SCOPE.html`: "a design envelope of roughly $2–10/paper").** Cash spend is USD 0.71–1.24 per paper, inside the metered budget; the problem is entirely on the subscription side.

Total cost tracks claim count more closely than page count: Hurst (8 pages, 258 claims) costs USD 38.21 against Axt (60 pages, 229 claims) at USD 36.84, and Hurst has no abstained analyses so all 258 claims reach every downstream step. Arbitration is the one step that tracks pages (§2.3).

---

## 2. Ranked waste sources

### 2.1 Per-claim link calls — `stage1/match.py:355` (already fixed; this is what it cost)

**Mechanism.** `futures = {... for c in linkable for t in traces}` built one model call per claim × replica. Measured: 4,691 attempted calls, of which 1,494 succeeded (10.81 M tokens, USD 2.06, 9.08 cumulative h) and **3,199 returned `402 Payment Required`** — the OpenRouter balance was exhausted mid-run by this step alone.

**Share.** 42% of all cash spend, 83% of all calls, and the largest single block of cumulative model time. At 6 workers (`match.py:353`) that is ~1.5 h wall.

**Hidden multiplier.** 1.11 M of the 1.33 M output tokens on this step are *reasoning* tokens (83%) for a reply that is a ~50-token JSON object. `_openrouter` (`llm.py:172-186`) sets no `reasoning` field, so `z-ai/glm-5.3-flash` thinks at full budget on every call.

**Fix (in place).** `direct_link` (`match.py:260`) reads the replica's own `claim_id`-keyed entry, and `results_keyed` (`match.py:251`) short-circuits claims the replica did not compute. Current `match.json` files show 4,060 rows: 3,948 resolved directly from the replica's keyed results, 76 resolved as "replica did not compute it" with no call, and **36 needing a model call** — a 130× reduction on the 4,691 attempted. **Remaining fix:** add `"reasoning": {"max_tokens": 512}` to the OpenRouter body for every structured cheap call; on the pilot's numbers that is a ~4× cut on the cheap route.

### 2.2 `contracts:retry` and `redact:retry` fire on 11 of 11 first passes — and are avoidable

**Measured.** `stage0/logs/` holds `contracts1.log` + `contracts2.log` for all 6 runs and `redact1.log` + `redact2.log` for all 5. The retry never once failed to fire. Cost: USD 8.98 (contracts) + USD 3.87 (redact) = **USD 12.85, 7.3% of total**, plus 37 min of model time.

**Why it always fires.** I reconstructed attempt 1 from the logs' `structured_output` / `result` field and re-ran `leakcheck.scan` against the same `claims.json` and manifest design numbers (`scratch_audit_leak1.py`). 110 hits across the ten attempt-1 documents. Classified by the `quantity_kind` of the claims each hit maps to:

| | hits |
|---|---:|
| maps only to descriptive/design claims (mean, sd, percent, n) | 73 (66%) |
| maps to at least one inferential claim (t, F, d, r, p, CI, coefficient) | 37 (34%) |

Reading all 110 contexts by hand (`scratch_audit_leak1.py` prints them) gives a sharper split:

| what the hit actually is | hits | documents |
|---|---:|---|
| sample description: mean/SD age, sex counts, ethnicity %, family-structure % | 62 | all 10 |
| exclusion rates and processing thresholds (`3.9% of participants`, `1.5 s` artefact rule, `2.0° visual angle`) | 25 | 5 |
| a priori power targets (`80% power to detect d = .30`) | 6 | Axt methods |
| reliability reported in methods (Cronbach's α `.69/.76/.82/.72`, `94%` inter-rater agreement) | 6 | Ohtsubo, Hertel |
| **genuine outcome disclosure** | **11** | **Hertel contracts only** |

The 11 genuine leaks are all in one document, Hertel's attempt-1 contracts: `CI [8.5, 16.8]`, `MSE 310.40 / 746.04 / 635.54`, `M = 0.40 in each group`, `all p values > .25`, `each p > .57`, and the cell means `1.5 / 3.0 / 4.5`. **Nine of the ten attempt-1 documents disclosed no result at all and were rewritten anyway.**

Representative hit contexts:

- Hurst, both documents: `36.67`, `15.73`, `33.13`, `14.16` — **mean and SD of participant age**.
- Petersen, both documents: `22.8`, `1.8`, `23.8`, `1.6`, `24.4`, `2.3` — mean/SD age again; plus `1.5`, the artefact-rejection threshold in seconds.
- Ohtsubo, both documents: `19.3±1.85`, `21.4±2.96`, `18.79±1.98` — mean/SD age; `.69`, `.76` — **Cronbach's alpha**.
- Axt: `.20`, `.30`, `.33`, `.39`, `.45` — **a priori power-analysis effect sizes**; `3.9%`, `8.4%`, `3.2%` — **exclusion-rate percentages**.
- Hertel: `42%`, `67%`, `57%` — ethnicity breakdown of the sample.

**The mechanism is a contradiction between three files.** `stage0_extract.md` tells the extractor to catalogue "every ... mean, standard deviation, sample size and percentage" as a claim. `stage0_redact.md` tells the redactor to "Keep, verbatim where possible: ... participants and recruitment" and "Keep design numerals". `stage0_contracts.md` says "Sample sizes that define the sample ... may be included". `leakcheck.forbidden_strings` (`stage0/leakcheck.py:82-143`) then forbids every printed form of every claim value, exempting only p-thresholds, integers ≤ 30 and manifest `design_numbers`. Mean age is a claim, is not an integer ≤ 30, and is not in `design_numbers` — so a document that correctly describes its sample is by construction a leak.

`variants()` (`leakcheck.py:42-65`) makes it worse: it emits each value at 1, 2 and 3 decimals plus `%g`, so one paper yields 239–396 distinct forbidden strings, of which 69–166 have only **two significant digits** (`.11`, `.12`, `.20`, `1.5`, `2.3`). Those collide with ordinary methods prose at near-certainty.

**Cost is doubled by the retry design.** `contracts.py:127` and `redact.py:337` rebuild `attempt_prompt` from the *full* original prompt — for Axt that re-sends 115 k characters of paper text — with the hit list appended. Attempt 2 costs the same as attempt 1 (measured: contracts 0.71 M vs 0.72 M tokens; redact 0.37 M vs 0.38 M).

**Fix.**
1. Build the forbidden set from **inferential claims only** (`t, F, chi2, z, d, r, OR, eta2, coefficient, p_value, se, ci_bound`), and from descriptive claims only where the claim's `analysis_label` is one the paper reports as a finding. Mean age and ethnicity percentages are sample description, not results.
2. Drop forms with fewer than three significant digits from the scan; keep them only for `headline` claims.
3. Replace the whole-prompt retry with a **local repair**: pass the offending sentences (60 chars either side is already captured in `hits[*].context`) to a cheap model with "rewrite these sentences without the number", and splice. That is ~2 k tokens instead of ~120 k.
4. If a scan-clean document is genuinely unreachable, fail loudly rather than paying twice.

Expected saving: USD 12.85 across five papers, and one fewer failure mode.

### 2.3 Stage 0 arbitration reads all page images through the `Read` tool — `stage0/arbitrate.py:128`, `llm.py:262-265`

**Mechanism.** `arbitrate.run` passes `images=pages` to a `claude -p` call. `_claude_p` has no image-attachment path; it appends a list of file paths and instructs the model to "Read these image files with the Read tool" (`llm.py:262-265`), with `--allowedTools Read`. One nominal call becomes a multi-turn agentic loop, and the whole conversation — every image already read — is re-sent as cache-read input on every turn.

**Measured** (`num_turns` and `duration_ms` from `stage0/logs/arbitrate.log`):

| paper | pages | turns | wall | tok_in (incl. cache) | tok_out | list $ |
|---|---:|---:|---:|---:|---:|---:|
| Axt | 60 | 34 | 33.5 min | 4,518,738 | 247,551 | 12.93 |
| Hurst | 8 | 14 | 17.1 min | 1,469,253 | 127,137 | 5.34 |
| Ohtsubo | 30 | 16 | 8.6 min | 543,985 | 59,253 | 3.24 |
| Petersen | 9 | 18 | 7.7 min | 922,657 | 48,276 | 2.56 |
| Hertel | 10 | 12 | 5.3 min | 231,350 | 35,468 | 1.70 |

Cost scales with page count: Axt's 60 pages cost 7.6× Hertel's 10 pages. Total 8.20 M tokens, USD 25.78, **14.6% of the run**, mean USD 5.16 per paper — for a step whose job is to reconcile two lists that already agree on ~83% of entries (PILOT_NOTES).

**Fix.** Arbitrate deterministically. Match A and B by `(page, quantity_kind, rounded value)`; where they agree, keep with `agreed: true` and no model call. Send only the disagreements to a model, one batched call, with **cropped page regions** for the disputed locations rather than whole pages. On Ohtsubo's numbers that is ~35 disputed entries out of 204. Expected: USD 5.16 → under USD 0.50 per paper.

### 2.4 Stage 0's remaining strong calls: whole-paper text and whole-inventory rewrites

`contracts.run` (`contracts.py:89-93`) and `redact._write_methods` (`redact.py:99-103`) each send `paper_text` in full, and each retries with the full text again — **four full-text passes per paper**. `readiness.run` sends every file's schema plus every contract (417 k tokens per call, USD 1.60). `scrub` rewrites every claim description in chunks of 120 (`redact.py:42`, 20 Opus calls across 5 papers, USD 8.87). Together with `scrub_descriptions`: USD 43.63 (24.7%), all before a single replica starts.

**Fix.** Redaction and contract writing read the same text for adjacent purposes. Merge them into one call that emits `{contracts, redacted_methods}`, and drop `scrub_descriptions` (`redact.py`, one call, USD 0.69) by having that call also emit value-free descriptions. Move `scrub` to the cheap tier — it rewrites short fragments and does not need Opus (USD 8.87 → ~USD 0.20).

### 2.5 Stage 1 replicas — 10 per paper, USD 32.92 (18.7%)

Per-replica medians, from `stage1/replicas/*/agent.log` (`scratch_audit_turns2.py`):

| family | route | n | turns | fresh input | cache read | cache write | cost/replica |
|---|---|---:|---:|---:|---:|---:|---|
| opus | claude_p | 10 | 22 | 41 | 954 k | 60 k | **$1.61** list |
| fable | claude_p | 5 | 17 | 618 | 649 k | 61 k | **$2.23** list |
| deepseek | opencode | 10 | 48 | 180 k | 3.94 M | — | $0.090 cash |
| glm | opencode | 10 | 28 | 142 k | 1.67 M | — | $0.043 cash |
| luna | codex | 10 | — | 81 k total | — | — | unpriced |
| sol | codex | 5 | — | 82 k total | — | — | unpriced |

**The opencode ~17 k system prompt is real.** First `step_finish` reports `tokens.input` of 14,316 (glm) and 16,514 (deepseek) with `cache.read = 0`; every later step shows a small fresh input plus a large `cache.read`. It is re-sent per turn but served from cache.

**A cheap replica costs 1/25th of an Opus replica and runs the same task.** Opus and Fable together are USD 31.45 of the USD 32.92; the four cheap replicas are USD 1.47.

**Ledger bug.** `_opencode` (`llm.py:405-408`) sums `tok.input` and ignores `tok.cache.read`, so the ledger reports 230 k input tokens for a deepseek replica whose log shows 4.12 M (17.9×) and 180 k for a glm replica whose log shows 1.81 M (10×). Cash is right (`part.cost`); token counts on the opencode route are understated 10–18×.

**Input inflation.** `blind.assemble` (`blind.py:173`) writes `bound_contract` into every replica's `CONTRACT.json`. Hurst's is **148 KB / 258 claims / 11 contracts** and Petersen's 97 KB / 117 claims, because `bound_contract` (`blind.py:127-151`) filters by *contract* readiness but keeps every claim of every kept contract. Ohtsubo, where readiness abstained on most analyses, is 17.6 KB. Each replica re-sends ~37 k tokens of claim inventory on all 22–48 turns.

**Fix.** Cut the default lineup to three cheap families × 1 run (glm, deepseek, luna), keep one frontier run for calibration only. Cap `CONTRACT.json` to the focal analysis plus its headline claims — a replica does not need 258 table cells to reproduce one t-test.

### 2.6 Targeted reconstruction — `stage1/targeted.py:42-71`, USD 19.48 (11%)

`assemble()` writes `PAPER.md` (full text), `CONTRACT.json` (all contracts + all claims, unfiltered — `targeted.py:52-57`), `REPORTED.json` (all claims with values), `data/`, and **`replicas/<id>/out/` copied wholesale for all 10 replicas** plus each `trace.json`. The agent then runs up to 12 attempts.

Measured across 6 calls (Petersen did not trigger): 2.04–4.79 M tokens_in, 6.0–12.7 min, USD 2.50–4.84 each; Hurst's call at 4.79 M is the largest single call in the pilot. `stage1_targeted.md` caps *analytical attempts* at 12 but nothing caps turns or tokens.

**Fix.** Give it the single closest replica's script plus the reported values for the headline claims only; drop `PAPER.md` to the methods and the focal analysis section; add a turn cap. Trigger it only on the focal claim, not on any headline claim (`match.targeted_trigger`, `match.py:455-470`, currently fires on every headline claim).

### 2.7 Diagnosis — `stage1/diagnose.py:181-212`, USD 16.99 (9.6%)

`material()` concatenates 60 k chars of paper + all contracts + all claims + for **each of 10 replicas** the full trace, 12 k of script and 8 k of results + 40 k each of `match.json`, `targeted.json`, `rerun.json`. Measured 287 k input tokens per call for **2,009 output tokens** (mean 201 tokens out per call) — a 143:1 input:output ratio, USD 2.83 a call, for a document the docstring says "is never used to grade anything."

**Fix.** Fold diagnosis into the targeted call, which already has all the same material assembled on disk. If kept separate, feed it `match.json` summaries and the two closest traces, not all ten. Expected USD 2.83 → under USD 0.40.

### 2.8 Stage 2's four strong calls — USD 26.07 (14.8%), USD 5.21 per paper

`check_broad` (`review.py:626`) alone is USD 3.24 per call at 444 k input tokens. `check_mde` runs an agentic fallback (`_mde_agentic`, `review.py:487`) at 406 k tokens. `check_causal_language` and `check_alignment` are cheap by comparison (USD 0.71, USD 0.56).

`check_broad` re-reads the whole paper once more. Nothing in `causal_language` or `alignment` needs Opus: both compare stated wording against a fixed contract, with `verify_anchors` (`review.py:591`) already checking quotes deterministically.

**Fix.** `causal_language` and `alignment` to the cheap tier. `mde` is a power calculation — compute it in R and call a model only to name the effect-size convention (`stage2/mde.py` already shells out to Rscript at line 160). Keep one strong `broad` call, scoped to the focal analysis and the match summary rather than the whole paper.

### 2.9 Stage 3 — USD 1.77 total (1%)

The cheapest stage and the one doing the most work: enumerate (USD 0.075), screen (codex, unpriced), execute (opencode, USD 0.28 for 6 runs), interpret (Opus, USD 1.35). Grid sizes 16–126 specifications, all executed. **No cut needed here.** The only inefficiency is `interpret` on the strong tier at USD 0.27 a call, and `paper_level` at 21 min per call on glm-flash with 96% reasoning tokens.

### 2.10 Resume and staleness — the rerun cascade

Three distinct problems.

**(a) Cache keys hash volatile fields.** `match.replica_fingerprint` (`match.py:313-318`) hashes the whole `trace.json`. That file's `meta` block carries `created` (an ISO timestamp) and `model_calls` (fresh UUIDs from `ledger.record`, `ledger.py:23`). Re-saving a trace with byte-identical analytical content changes its hash. The same applies downstream: `diagnose.inputs` (`diagnose.py:215-221`) hashes whole `match.json`, and `stage3._stage_inputs` (`stage3/__init__.py:52-68`) hashes `match.json` plus every `trace.json`. One touched trace therefore invalidates match → trace_equivalence → targeted → diagnose → stage2 → stage3.

That cascade is visible in the ledger: Ohtsubo has `trace_equivalence` ×4, `targeted` ×3, `diagnose` ×3, `broad` ×3, `interpret` ×2, `execute` ×2 — USD 19.19 of rerun on one paper, 5.7% of the whole pilot.

**Fix.** Hash the analytical payload, not the file: `trace.model_dump(exclude={"meta"})`. Same for `match.json`.

**(b) The 09-03 repair rerun cost USD 12.00 (6.8%).** `scratch_repair.sh` deletes `trace.json` for replicas marked not-`ran`, then deletes `match.json`, `stage1/done.json`, `stage3/done.json`, `stage3/space.json` and `stage3/paper_level.json`. Some of that rerun was substantive: re-checked replicas changed real inputs. The ledger cannot separate substantive rerun from cascade. What is certain from (a) is that the cascade fires on every touch regardless of whether content changed.

**(c) Stage-level `done.json` and step-level caching disagree.** `stage0.input_hashes` (`stage0/__init__.py:22-32`) includes the version hash of all six Stage 0 prompts, but every step inside checks only `out_path.exists() and not force` (`contracts.py:86`, `arbitrate.py:113`, `redact.py:307`). Editing a prompt clears the stage marker, the stage then walks through reusing every stale artifact, and `mark_done` (line 72) writes a fresh marker asserting the outputs match the new prompts. Stage 3 has the same shape (`_step`, `stage3/__init__.py:32-34`). This is a correctness bug, not a cost bug — see §5.

---

## 3. Per-paper call budget for v0.1

Target: USD 2–10 per paper at list price (SCOPE.html). Current clean run: USD 17.58–38.21.

| stage | step | now | v0.1 | est. $ | accuracy trade-off |
|---|---|---|---|---:|---|
| 0 | extract | 2 vision models × all pages | **1 model on all pages; 2nd model only on pages carrying a headline or table claim** | 0.30 | Recall on obscure supporting table cells drops. Focal and table claims keep two-model coverage. |
| 0 | arbitrate | 1 Opus call reading every page image | **deterministic match on (page, kind, value); 1 Sonnet call over disagreements only, with cropped page crops** | 0.40 | Agreement cases are already 83% and were never contested; disagreements keep a model and an image. |
| 0 | contracts + redact | 2 Opus calls + 2 Opus retries | **1 Opus call emitting both; local cheap repair instead of full retry** | 2.00 | None expected. The retry currently fixes sample descriptions, not results. |
| 0 | scrub + scrub_descriptions | 21 Opus calls | **cheap tier, same chunking** | 0.20 | Short fragments; a cheap model has been adequate on the same task in Stage 1. |
| 0 | readiness | 1 Opus call | **Sonnet**, schema + contracts only | 0.35 | Column-binding is a matching task with the schema in hand. Ambiguous bindings already abstain. |
| 0 | leak_audit | 1 codex call | keep (unpriced) | 0.00 | — |
| 1 | replicas | 10 (2 Opus, 1 Fable, 3 codex, 4 opencode) | **3 cheap: glm ×1, deepseek ×1, luna ×1** | 0.15 | Loses within-family variance and the frontier-vs-cheap contrast. Between-family dispersion, which drives `numeric_cv` and the targeted trigger, survives. Run the frontier lineup on a calibration subset only. |
| 1 | link_results | model per claim × replica | deterministic (`direct_link`); model only on unkeyed replicas, reasoning capped | 0.05 | None. Replicas already key by `claim_id`. |
| 1 | hardcoding_audit / fix_severity | per replica, uncapped reasoning | keep, `reasoning.max_tokens: 512` | 0.10 | Slightly shallower audit reasoning on a binary verdict. |
| 1 | trace_equivalence | 1 Opus call over all traces | **cheap tier**, traces stripped to `open_choices` + `model_formula` | 0.05 | Agreement score is a set-comparison; it does not need Opus. |
| 1 | targeted | full paper + all 10 replica trees, 12 attempts | **only when the focal claim misses**; closest replica's script + focal contract + reported focal values; turn cap 30 | 1.20 conditional | A smaller search may miss a convoluted route. Report "search exhausted under budget", never "not reachable". |
| 1 | diagnose | separate Opus call over everything | **folded into the targeted call's output** | 0.00 | Diagnosis is explicitly a non-grading conjecture. |
| 2 | causal_language, alignment | 2 Opus calls | **cheap tier** | 0.10 | Both compare wording to a fixed contract; quote anchors are already verified deterministically (`review.py:591`). |
| 2 | mde | Opus, agentic fallback | **R computation + 1 cheap call to name the convention** | 0.05 | None. |
| 2 | broad | 1 Opus call over the whole paper | keep Opus, scope to focal analysis + match summary + redacted methods | 1.20 | Referee findings on unrelated supporting analyses are lost. |
| 3 | enumerate, paper_level, screen, execute | as now, reasoning uncapped | keep; cap reasoning; cap grid at 64 cells with fractional sampling above | 0.25 | Above 64 cells the curve is estimated from a fraction rather than the full grid. |
| 3 | interpret | Opus | keep (USD 0.27) | 0.27 | — |
| | | **~USD 28** | | **~USD 6.7** (USD 5.5 with no targeted arm) | |

Strong-tier `claude -p` calls per paper: **~23 today → 3** (contracts+redact, broad, interpret), plus one conditional targeted arm.

Hard rules to add to `llm.call`:
- Refuse any single non-agentic call above 60 k input tokens without an explicit `large_context=True`.
- Every agentic call takes a `max_turns` as well as a timeout.
- Cheap-route calls default to `reasoning: {max_tokens: 512}`; opt out per step.
- A per-paper running total in `ledger.py`, and a stage refuses to start a call that would cross its allocation.

---

## 4. Scaling

Cost today grows as roughly **P × C × R × T**: paper length P, claims C, replicas R, agent turns T.

| multiplier | where | current behaviour |
|---|---|---|
| P (length) | images: `extract` A and B, `arbitrate` (`arbitrate.py:128`). Text: `contracts` (`contracts.py:92`), `contracts:retry`, `redact` (`redact.py:101`), `redact:retry`, `diagnose` (60 k cap, `diagnose.py:182`), `review.check_broad` | nine passes over the paper per run |
| C (claims) | `scrub` is C/120 calls (`redact.py:42`); `blind_contract` carries all C claims to every replica (`blind.py:143`); `match` was C × R calls; `targeted`/`diagnose` carry all C claims with values | Hurst: C = 258 makes it the most expensive paper despite being 8 pages |
| R (replicas) | 10 agentic runs; `hardcoding_audit` and `fix_severity` per replica; `trace_equivalence` over all R; `targeted` copies all R output trees; `diagnose` embeds all R scripts | R appears in five separate steps |
| T (turns) | agentic history re-sent per turn (22–48 turns measured) | cache absorbs most of it, but `arbitrate` at 34 turns is not cached across page reads |
| R again, incrementally | volatile cache keys (§2.10a) | adding one replica re-runs match → targeted → diagnose → stage 2 → stage 3 |

**How to break it.**

1. **Bind claims to focal analyses before anything expensive.** Readiness already computes `per_analysis_state`, but it runs *after* arbitration, contract writing and scrubbing have processed all C claims. Move data binding to immediately after extraction: bind columns to analyses from the schema, then only write contracts for analyses that bind. On Ohtsubo that is 6 of 40 analyses.
2. **Cap claims per analysis.** A contract needs its headline quantities plus enough table cells to identify the model — cap at, say, 8 per analysis. Hurst's 258-claim contract becomes ~88 and every downstream step shrinks with it.
3. **Chunk by analysis, not by paper.** Build one compact packet per bound analysis (methods section + contract + relevant data columns). `contracts`, `redact`, `readiness` and `targeted` then read a packet, not the paper. Cost becomes linear in *bound analyses*, not in paper length.
4. **Join by identifier, never by model.** Already done for linking; extend it to arbitration (match A/B on page + kind + value) and to `trace_equivalence` (compare `open_choices` sets in Python; call a model only to describe the divergences).
5. **Normalise each trace once.** Downstream steps should consume a consensus vector plus per-replica deltas, not ten full traces. That removes R from `targeted`, `diagnose` and `broad`.
6. **Bound Stage 3's grid.** `stage3_enumerate.md` asks for "4–8 factors with 2–4 levels each", which is 16 to 65,536 cells; Hertel already reached 126. Cap at 64 and switch to a fractional design above that.

With 1–6 the expensive path becomes: P for one indexing pass, plus R × focal-analysis-size, with everything else independent of C.

---

## 5. Correctness risks noticed in passing

1. **Stage 2 picked the wrong focal claim on 2 of 4 papers.** `review.json.focal_claim_rule` reads `"first claim in claims.json (no better rule applied)"` for **Axt and Hurst**. `_focal` (`review.py:205-237`) matches the manifest's focal value by string equality and requires exactly one match; on failure it falls through to `claims[0]`, then to `contracts[0]`. Both papers' whole Stage 2 review therefore describes claim `c001`, not the Multi100 focal claim.

2. **A failed link call is graded as a failed replication.** `link` returns `LinkResult(found=False)` on any error (`match.py:246-247`); `grade` bands `replicated=None` as `"fail"` (`match.py:123-126`); that feeds `fraction_matched` and `targeted_trigger` (`match.py:463`). During the 402 outage 3,197 claim × replica pairs were exposed to this. The 09-03 repair rebuilt every `match.json` and current files contain no `link call failed` notes, so no live artifact is affected — but the failure mode is still open. A failed call must produce `state="abstained"`, not band `"fail"`.

3. **Stale artifacts get blessed as current.** `stage0.mark_done` (`stage0/__init__.py:72`) writes a done marker containing the *new* prompt hashes after the steps inside reused artifacts produced by the *old* prompts (`contracts.py:86`, `arbitrate.py:113`, `readiness.py`, `redact.py:307`). Stage 3 repeats the pattern (`_step`, `stage3/__init__.py:32`). A prompt edit followed by a run leaves the repo asserting freshness it does not have.

4. **`match.replica_fingerprint` ignores results.** It hashes `trace.json` only (`match.py:313-318`), not `out/results.json` or the script. A replica whose results are corrected without a trace rewrite leaves `match.json` silently stale.

5. **Missing targeted output is recorded as evidence against the paper.** `targeted.py:136-137` coerces an absent or invalid `outcome.json` to `"not_reachable"`. The record is separately marked `abstained` (line 149), but `outcome` is what the report reads. An agent that crashed and a genuine exhaustive search produce the same verdict.

6. **Retry usage is not ledgered.** `llm.call`'s loop (`llm.py:329-345`) overwrites `stats` on each attempt, so a schema-invalid or transient first attempt vanishes from the token and cost totals while its duration stays in `duration_s`. All reported token figures are lower bounds.

7. **The opencode ledger understates input 10–18×.** `_opencode` (`llm.py:405-408`) sums `tokens.input` and drops `tokens.cache.read`. Deepseek replicas log 4.12 M input tokens against 230 k recorded (17.9×); glm 1.81 M against 180 k (10×). Cash is unaffected.

8. **Stage 3 confidence ignores focal-binding uncertainty.** `confidence = "high" if not problems else "medium"` (`stage3/__init__.py:339`) reads only the executor's problem list. On Axt and Hurst, where the focal claim fell back to `claims[0]`, Stage 3 can still report high confidence.

9. **The leak scan's exemptions are load-bearing and untested against real leaks.** `leakcheck.py:101-116` skips every integer ≤ 30, every non-headline `n`, and every p-value equal to a threshold. A reported `d = 0.8`, an `n = 29` finding, or `p = .05` exactly passes the scan. Meanwhile the semantic audit rated leakage `"strong"` on all five papers for structural reasons, so it cannot discriminate. The blinding guarantee currently rests on a scan with known holes plus an audit with no discrimination.

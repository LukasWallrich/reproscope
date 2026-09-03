# Handoff — reproscope pilot (2026-09-03)

Read this first in a new session. It states where the pilot stands, the decisions Lukas has taken, and the ordered work list. Background: `docs/PILOT_DESIGN.md` (mechanics), `docs/PILOT_NOTES.md` (findings log), `docs/EFFICIENCY_AUDIT.html` (why the pilot cost 4× the envelope, with both source reviews under `docs/evaluation/audits/`), `SCOPE.html` (design rationale).

## State

- Package `reproscope/` implements Stages 0–3, the report and an evaluation script; 130 offline tests pass (`.venv/bin/python -m pytest tests -q`).
- Corpus: five Multi100 psychology papers under `corpus/` (Ohtsubo, Hurst, Axt, Petersen, Hertel) with PDFs, data and manifests. PDFs, data and paper text are gitignored.
- Runs under `runs/<paper_id>/` (gitignored): Stage 0 complete for all five; Stage 1 replicas complete for all five (10 per paper: opus×2, fable×1, sol×1, luna×2, glm×2, deepseek×2); match/targeted/diagnosis, Stage 2 and Stage 3 exist for Ohtsubo, Hurst, Hertel, Axt in varying states; Petersen stops after replicas. Reports exist for Ohtsubo, Hertel, Hurst, Axt but predate several fixes.
- No pipeline process is running. Spend: USD 5.08 metered (OpenRouter), about USD 171 list-equivalent on the Claude subscription, Codex unpriced. OpenRouter balance was about USD 10 at last check.
- Seven replica traces are marked `ran: false`; most are an artefact of scripts hard-coding the isolation path (fixed in `stage1/replicas.py`, not yet re-checked). `scratch_repair.sh` deletes those traces and the downstream artifacts so a rerun re-checks them without relaunching agents.

## Decisions taken by Lukas (2026-09-03)

1. **Replica lineup for development:** three cheap families × 2 runs (glm, deepseek, luna) plus opus ×1 and fable ×1. Drop sol from the default lineup. Update `models.toml`.
2. **Do not cap the number of items to reproduce.** Instead batch them more clearly: the replica task and the contract should group quantities by analysis so that, for example, all coefficients of one regression are reproduced in one pass. Blind contracts stay complete for data-bound analyses.
3. **Rebuild arbitration** so agreements are merged deterministically and only disagreements go to a model, with cropped page regions.
4. **Stage 2 broad review** gets one canonical script plus diffs, not all scripts.
5. **Redaction must be more efficient** (no whole-paper retry; local repair; forbidden set limited to inferential quantities).
6. Otherwise follow the audit's recommendations at the implementer's judgement.

## Work list, in order

### A. Efficiency fixes (no model calls beyond tests)

1. `models.toml`: lineup per decision 1.
2. `stage0/arbitrate.py`: deterministic merge on (page, quantity_kind, value rounded to reported precision, analysis_label similarity); model call only over disagreements and singletons, batched, with page crops (`pdftoppm -x -y -W -H` or PIL crop from the rendered page around the location) sent to a cheap vision model (`vision_a`); strong model only for unresolved headline claims.
3. `stage0/leakcheck.py`: forbidden set from inferential kinds (t, F, chi2, z, d, r, OR, HR, eta2, coefficient, p_value, se, ci_bound) plus all headline claims; drop forms with fewer than three significant digits for supporting claims; keep design_numbers exemption.
4. `stage0/contracts.py`, `stage0/redact.py`: one call emitting both contracts and the redacted methods (or keep two calls but never retry with the full paper); on scan hits, rewrite only the offending sentences (the hit context) with a cheap call and splice; `scrub` chunks to the cheap tier; drop `scrub_descriptions`.
5. `stage0/readiness.py`: Sonnet tier, schema plus contracts only (add a `mid` tier in models.toml).
6. `stage1/blind.py`: group claims by analysis in CONTRACT.json (one block per contract listing its quantities), and say in `stage1_replica_task.md` that each analysis is reproduced once and all its quantities written from that fit.
7. `stage1/match.py`: keep the deterministic join; failed link call → `state: abstained`, never band `fail`; `replica_fingerprint` hashes `trace.model_dump(exclude={"meta"})` plus `results.json`; trace equivalence on the cheap tier over `open_choices` + `model_formula` only.
8. `stage1/targeted.py` + prompt: trigger on the focal claim only; work dir gets the closest replica's script, the focal contract, reported values for the focal analysis's claims, and the methods section (not PAPER.md); `max_turns` cap (add `--max-turns` for claude_p in `llm.py`); an absent or invalid outcome is `abstained`, never `not_reachable`; the diagnosis is a section of the targeted agent's final answer when it runs, otherwise one small call over match summaries and the two closest traces.
9. `stage2/review.py`: focal claim from the manifest override (`focal_claim.claim_id`) with the same binding as Stage 3 (`stage3.multiverse.bind_focal_claim`); causal_language and alignment on the cheap tier; MDE deterministic, abstain instead of the agentic fallback; broad review gets the focal analysis's methods/results passages, the schema, the canonical script and unified diffs of the others.
10. `llm.py`: `reasoning: {max_tokens: 512}` on OpenRouter structured calls (opt out per step); refuse non-agentic calls above 60k input tokens unless `large_context=True`; ledger every attempt; opencode tokens include `cache.read`; a configurable shadow price for codex models so list-equivalent totals are complete.
11. Cache keys: hash analytical payloads, not files with `meta`; stage markers must not be rewritten when steps reused old outputs (check prompt hashes inside each step); `--force-step`.
12. `stage3`: cap the grid at 64 with fractional sampling above; interpretation stays on the strong tier (cheap).

### B. Finish the pilot on existing replica outputs

1. Run `scratch_repair.sh` (re-checks the seven failed traces without relaunching agents), then per paper `--stages 1 2 3 report` with the fixed code. Expect roughly USD 1 cash and USD 10–15 list-equivalent.
2. `.venv/bin/python -m reproscope.evaluate` for the family comparison; then the writeup (HTML, `docs/evaluation/`), covering: match tables per paper, cheap versus frontier, the Ohtsubo exclusion case, Petersen's unimplementable multiverse factors, Axt/Hertel where families diverged, cost per paper before and after the fixes, and the correctness bugs found.

### C. Known findings to carry into the writeup

- Ohtsubo: 8 of 9 replicas identical (t = 6.20 vs reported 5.91) because the excluded participant is unmarked; the targeted arm reached the reported numbers only by back-solving the excluded case from the reported statistics.
- Hertel: Opus 100% band A; cheap families 83% A; one Opus run and one DeepSeek run misclassified as failed by the isolation-path bug.
- Petersen: the multiverse enumerator proposed factors inside the TVA model fit, which the supplied data have already done; screen now sees the schema.
- Stage 0's leak audit rates every paper "strong" for structural reasons (the claim inventory reveals which analyses carry p-values); it does not discriminate.
- Cost: see `docs/EFFICIENCY_AUDIT.html`.

## How to run

```
.venv/bin/python -m reproscope run <paper_id> --stages 0 1 2 3 report
REPROSCOPE_FAMILIES=glm,deepseek REPROSCOPE_RUNS=1 .venv/bin/python -m reproscope run <paper_id> --stages 1
.venv/bin/python -m reproscope ledger <paper_id>
.venv/bin/python -m reproscope.evaluate
```

Launch long runs with `run_in_background` and a log under `runs/logs/`; `claude -p` calls need `CLAUDECODE` unset (handled in `llm.py`). Concurrent Opus load on the subscription produced `claude exited 1` failures last night; keep at most two papers in flight.

# Handoff — reproscope pilot (2026-09-03, evening)

Read this first in a new session. It states where the pilot stands and what waits on Lukas. Background: `docs/PILOT_DESIGN.md` (mechanics, current), `docs/evaluation/PILOT_EVALUATION.html` (the pilot writeup), `docs/EFFICIENCY_AUDIT.html` (the cost audit the fixes answer), `SCOPE.html` (design rationale).

## State

- Package `reproscope/` implements Stages 0–3, the report and the evaluation; 194 offline tests pass (`.venv/bin/python -m pytest tests -q`).
- The efficiency and correctness work list from the audit is implemented and merged (git log from `36cc1d9` to HEAD). Highlights: deterministic arbitration with cheap-vision batches, one strong call for contracts plus redacted methods, leak scan limited to inferential and headline quantities, CONTRACT.json grouped per analysis, abstained match rows, focal claim bound through `reproscope/focal.py` everywhere, targeted arm on the focal quantity only with `max_turns`, Stage 2 scoped to the focal analysis, Stage 3 execution capped at 64 with stratified sampling, content-hash cache keys with per-step input and prompt checks, `--force-step`, per-attempt ledger rows, opencode cache tokens, Codex shadow prices.
- All five papers have complete runs (`runs/<paper_id>/`, gitignored): Stage 0 from the 2026-09-02 pilot; replica agent runs from the pilot (ten per paper, all traces present); matching, targeted arm, diagnosis, Stage 2, Stage 3 and reports rebuilt on 2026-09-03 with the fixed code. Two DeepSeek replicas (Petersen) stay `ran: false`: their scripts import scipy, which the re-execution interpreter lacks.
- Evaluation: `docs/evaluation/pilot_eval.{md,json}` (from `python -m reproscope.evaluate`), `docs/evaluation/cost_table.json` (from `docs/evaluation/cost_table.py`), and the writeup `docs/evaluation/PILOT_EVALUATION.html` (from `docs/evaluation/build_writeup.py`).
- Spend on the rebuild: about USD 0.5 metered, USD 27 list-equivalent across the five papers including retries; a single clean pass of Stages 1–3 is USD 0.05–0.08 metered and 1.9–6.0 list-equivalent per paper. OpenRouter balance was about USD 8 at the end (45 credited, 36.85 used).
- No pipeline process is running.

## Decisions waiting on Lukas

1. **Shadow prices** are set to OpenAI's input list prices (Sol 4.0, Luna 0.2 USD per million tokens, 2026-08-21 rates); Codex reports one token total, so output tokens are priced as input. Revisit when Sol's promotional rate ends (at least 2026-11-21).
2. **Leak rule for p-values.** The scan forbids inferential kinds plus headline claims, with three significant digits required for supporting claims. Supporting p-values are exempt from the three-digit rule (a printed p rarely has three), so ".03" from a supporting claim is still forbidden. The narrowed rule lets through supporting means, MSEs, percentages and CI bounds that the pilot's first-draft contracts had leaked into ambiguity notes; the cheap description scrub is what removes those now. Confirm or widen (add `other`/`mean` to the inferential set).
3. **Stage 3 interpretation input.** The interpretation prompt receives the rank statistics alongside specs.csv; the design describes a specs-only prompt. Keep or strip.
4. **Matching sign gate for contrasts.** Axt's eight universal fails are one two-group contrast reported with the opposite sign and its CI bounds. A direction-agnostic rule for two-group contrasts would remove them. Decide whether to change the rule or keep it and annotate.
5. **Stage 3 gate.** Petersen's 64 specifications all return the identical estimate because no factor touches the second-stage test. A gate on the screen's output (skip execution when no defensible factor can move the estimand) would save the executor run and the interpretation call.
6. **Replica environment.** DeepSeek's two Petersen scripts need scipy. Either add scipy to the re-execution interpreter or state the pinned environment in the replica task.

## Known findings (in the writeup)

- Ohtsubo: the deposited workbook has 30 rows and no exclusion marker; the targeted arm identifies the excluded participant and reproduces all seven reported quantities exactly.
- Hurst: five cells of the Mini-K correlation table are unreachable by any defensible specification; one is arithmetically inconsistent with its subscales (a likely transcription error). This came from a targeted run under the earlier, broader trigger; kept under `runs/logs/superseded/`.
- Petersen: the multiverse is a point mass; the data are first-stage output.
- Axt: every family produces the same profile; the fails are the sign-convention artefact above.
- Hertel: all ten replicas reproduce the focal F; differences sit in supporting claims (GLM's second run 73% band A, the rest 83–100%).
- The model-based leak audit rates every paper "strong" for structural reasons and does not discriminate.
- Claude Opus returned "529 Overloaded" on 15 strong-call attempts during the rebuild; a retry runner (`scripts/chain_retry.py`) completed them in later passes. `scripts/repair_replicas.sh` re-checks replicas marked failed and clears everything downstream of the traces.

## How to run

```
.venv/bin/python -m reproscope run <paper_id> --stages 0 1 2 3 report
.venv/bin/python -m reproscope run <paper_id> --stages 1 2 --force-step targeted diagnose broad
REPROSCOPE_FAMILIES=glm,deepseek REPROSCOPE_RUNS=1 .venv/bin/python -m reproscope run <paper_id> --stages 1
.venv/bin/python -m reproscope ledger <paper_id>
.venv/bin/python -m reproscope.evaluate
.venv/bin/python docs/evaluation/cost_table.py && .venv/bin/python docs/evaluation/build_writeup.py
```

Launch long runs under a Monitor or a background shell with a log under `runs/logs/`; `claude -p` calls need `CLAUDECODE` unset (handled in `llm.py`). Keep at most two papers in flight on the Claude subscription. Stage 0 has not been rerun since the fixes; the first Stage 0 run on a new paper exercises the rebuilt arbitration, contracts and repair paths live for the first time.

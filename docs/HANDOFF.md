# Handoff — reproscope pilot (2026-09-03, evening)

Read this first in a new session. It states where the pilot stands and what waits on Lukas. Background: `docs/PILOT_DESIGN.md` (mechanics, current), `docs/evaluation/PILOT_EVALUATION.html` (the pilot writeup), `docs/EFFICIENCY_AUDIT.html` (the cost audit the fixes answer), `SCOPE.html` (design rationale).

## State

- Package `reproscope/` implements Stages 0–3, the report and the evaluation; 226 offline tests pass (`.venv/bin/python -m pytest tests -q`).
- The efficiency and correctness work list from the audit is implemented and merged (git log from `36cc1d9` to HEAD). Highlights: deterministic arbitration with cheap-vision batches, one strong call for contracts plus redacted methods, leak scan limited to inferential and headline quantities, CONTRACT.json grouped per analysis, abstained match rows, focal claim bound through `reproscope/focal.py` everywhere, targeted arm on the focal quantity only with `max_turns`, Stage 2 scoped to the focal analysis, Stage 3 execution capped at 64 with stratified sampling, content-hash cache keys with per-step input and prompt checks, `--force-step`, per-attempt ledger rows, opencode cache tokens, Codex shadow prices.
- All five papers have complete runs (`runs/<paper_id>/`, gitignored): Stage 0 from the 2026-09-02 pilot; replica agent runs from the pilot (ten per paper, all traces present); matching, targeted arm, diagnosis, Stage 2, Stage 3 and reports rebuilt on 2026-09-03 with the fixed code. Two DeepSeek replicas (Petersen) stay `ran: false`: their scripts import scipy, which the re-execution interpreter lacks.
- Evaluation: `docs/evaluation/pilot_eval.{md,json}` (from `python -m reproscope.evaluate`), `docs/evaluation/cost_table.json` (from `docs/evaluation/cost_table.py`), and the writeup `docs/evaluation/PILOT_EVALUATION.html` (from `docs/evaluation/build_writeup.py`).
- Spend on the rebuild (all passes, including the evening's reruns): about USD 1.0 metered, USD 46 list-equivalent across the five papers including retries; a single clean pass of Stages 1–3 is USD 0.05–0.08 metered and 1.9–6.0 list-equivalent per paper. OpenRouter balance was about USD 8 at the end (45 credited, 36.85 used).
- No pipeline process is running.

## Decisions taken on 2026-09-03 (evening)

- **Shadow prices** are OpenAI's input list prices (Sol 4.0, Luna 0.2 USD per million tokens; Sol's rate is promotional through at least 2026-11-21).
- **Leak rule** is widened by analysis: every numeric claim of an analysis that carries an inferential or headline claim is forbidden, sample-description analyses stay exempt. Verified offline against the current blind materials (0 hits); not yet exercised on a fresh Stage 0 run.
- **Stage 3 interpretation** reads specs.csv, the grid's factors and the reported estimate only.
- **Sign gate**: a reversed two-group contrast (t, d) is graded on the flipped value and its CI bounds are mirrored, marked `direction_flipped` and shown as "sign flipped" in the report; coefficients and correlations keep the gate.
- **Stage 3 gate**: the enumerator lists unimplementable factors, the screen marks each level as affecting the estimate, the inference or only reporting; reporting-only factors are pinned to one level; a grid with no defensible level that moves the estimate or the inference is recorded as an abstention. Significance shares use each specification's own threshold.
- **Replica packages**: the task names the interpreters and the base stack (numpy, pandas, scipy, statsmodels, pyreadstat, openpyxl); anything beyond goes in `out/requirements.txt` or `out/r_packages.txt`, and the checker builds a per-replica environment from it; an install failure is `abstained: environment`.

## Decisions waiting on Lukas

None open. Two things settled on 2026-09-05: replica agents and the checker share one Python environment outside the repository (`~/.cache/reproscope/replica-env`, built by `reproscope/replica_env.py` from the repo's pins; the agent's environment is scrubbed of the repository path before launch), and Stage 0 ran clean on the new code on a Hertel copy (`runs/_fixture_s0_Hertel`, USD 0.06 metered, 2.29 list-equivalent; 101 claims, 27 contracts, scan clean, focal claim bound). The OpenRouter reasoning cap is opt-in and unused: glm-5.3-flash answers a capped structured call with reasoning only.

## Known findings (in the writeup)

- Ohtsubo: the deposited workbook has 30 rows and no exclusion marker; the targeted arm identifies the excluded participant and reproduces all seven reported quantities exactly.
- Hurst: five cells of the Mini-K correlation table are unreachable by any defensible specification; one is arithmetically inconsistent with its subscales (a likely transcription error). This came from a targeted run under the earlier, broader trigger; kept under `runs/logs/superseded/`.
- Petersen: the data are first-stage output; six factors are unimplementable and the executable curve is two specifications (Bonferroni on or off) with the identical estimate.
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

Launch long runs under a Monitor or a background shell with a log under `runs/logs/`; `claude -p` calls need `CLAUDECODE` unset (handled in `llm.py`). Keep at most two papers in flight on the Claude subscription. Stage 0 on the new code has run once, on a Hertel copy; rerunning Stage 0 in place on a pilot paper renumbers the claim ids that the replica outputs are keyed by, so use a copy under a `_fixture_` id or a new paper.

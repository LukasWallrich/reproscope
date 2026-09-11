# Handoff — reproscope pilot (2026-09-11)

Read this first in a new session. It states where the pilot stands and what waits on Lukas. Background: `docs/PILOT_DESIGN.md` (mechanics, current), `docs/PILOT_NOTES.md` (dated findings), `docs/evaluation/PILOT_EVALUATION.html` (the pilot writeup, from the 2026-09-03 runs), `docs/EFFICIENCY_AUDIT.html`, `SCOPE.html`.

## State

- Package `reproscope/` implements Stages 0–3, the report and the evaluation; 228 offline tests pass (`.venv/bin/python -m pytest tests -q`). Working tree clean, everything pushed to origin.
- Three papers have complete end-to-end runs on the current code under fresh ids: `Hertel_ClinPsychSci_2018_YabW_v2`, `Ohtsubo_EvoHumanBehavior_2014_zlm2_v2`, `Petersen_Cognition_2017_yJwG_v2` (`runs/<id>/`, gitignored; `corpus/<id>/manifest.json` committed). Hurst and Axt have not run on the current code. The 2026-09-03 pilot runs stay on disk under the original ids, with Stage 0 output from the 2026-09-02 code.
- Results of the v2 runs: Hertel 63 specifications all converged, F 5.40–7.46, reported 6.20 at rank 37, every specification significant; Ohtsubo 8 specifications, d 2.14–2.20, reported 2.2 at rank 5; Petersen 9 specifications all equal to the reported 0.89. Replicas: Hertel 8/8, Ohtsubo 8/8, Petersen 6/8 (deepseek_2 script error at the end of its run; glm_2 returned nothing through opencode twice).
- Models: no call goes to Claude Sonnet; the `mid` tier (readiness) is Opus. The Stage 3 executor is deepseek-v4.1-flash through opencode: on Hertel's 63-specification grid it produced the same 63 estimates as glm-5.3-flash in 2 min 17 s for USD 0.05, against 40 min and 0.11.
- Spend per paper including every failed pass: Hertel USD 0.77 metered / 12.6 list-equivalent, Ohtsubo 0.55 / 14.0, Petersen 0.59 / 11.4. OpenRouter credit left: about USD 3.9 of 45. The Claude subscription hit its session limit once during the runs (2026-09-07, about 18:00, reset 19:40).
- `docs/evaluation/` (evaluation, cost table, writeup) has not been regenerated over the v2 runs.
- No pipeline process is running.

## Guards added on 2026-09-07 to 09-11

Every fresh run failed first in a stage that one model call gated silently. The stages now refuse or escalate on the degenerate outcomes: an extraction chunk with no claims on pages that print results is retried once then fails, and an extractor empty while the other is not is rerun once then refused; Stage 0 fails on a dirty leak scan and writes no done marker; readiness that binds no analysis is repeated once on the strong tier then refused; Stage 1 refuses when no replica re-executes; Stage 3 refuses a failed or mismatching execution before ranking. Cache keys follow the artifacts a step reads (Stage 0 steps on their upstream artifacts, the targeted arm and diagnosis on the focal binding). The leak scan no longer forbids degrees of freedom; the focal binder anchors on the reported statistic and binds companions from its own analysis. Route handling: four attempts with backoff, OpenRouter retries skip the host that just failed, a host-ended reply is transient, scrub chunks are 40 items, the claude route reports the API error it received, ledger rows carry provider and finish reason. The retry runner waits 30 min on a session limit and gives up after two passes with nothing to force.

## Decisions waiting on Lukas

- **OpenRouter credit.** About USD 3.9 left. Hurst and Axt need about 0.6 metered each; the evaluation rerun and any retries come on top. Top up before launching them.
- **One readiness call per paper.** Readiness is now one Opus call, repeated once at the same tier when it binds nothing. A wrong but non-empty binding still passes. Options: a second independent readiness call with the union of bindings, a stronger prompt (consider column subsets and reversed items; treat a file whose row count is within a few of a study's sample as that study's data), or leave it.
- **Writeup.** Regenerate `docs/evaluation/` over the five v2 runs once Hurst and Axt exist; until then the evaluation mixes pilot and v2 runs.

## How to run

```
.venv/bin/python -m reproscope run <paper_id> --stages 0 1 2 3 report
./scripts/fullchain.sh <paper_id>                  # Stage 0 (3 attempts) then the retry runner; S0_ARGS='--force-step readiness' passes flags to Stage 0
.venv/bin/python scripts/chain_retry.py <paper_id> # Stages 1-3 + report with retries
.venv/bin/python -m reproscope ledger <paper_id>
.venv/bin/python -m reproscope.evaluate && .venv/bin/python docs/evaluation/cost_table.py && .venv/bin/python docs/evaluation/build_writeup.py
```

Logs go under `runs/logs/` (`fullchain_<id>.log`, `stage0_<id>.log`, `rerun_<id>.log`). To run a paper on the current code, copy `corpus/<id>` to `corpus/<id>_v2` and set `paper_id` (and `multi100.paper_id`) in its manifest; Stage 0 renumbers claim ids, so never rerun it in place on a paper with replica outputs. Keep at most two papers in flight on the Claude subscription. A replica that must be relaunched is moved out of `runs/<id>/stage1/replicas/` (the checker only re-verifies a replica whose results file exists); `runs/<id>/stage1/replicas_superseded/` holds the ones set aside so far, and `runs/Hertel_ClinPsychSci_2018_YabW_v2/stage3/executor_glm_20260908/` holds the glm executor's outputs from the comparison.

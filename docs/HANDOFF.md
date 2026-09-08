# Handoff — reproscope pilot (2026-09-08, evening)

Read this first in a new session. It states where the pilot stands and what waits on Lukas. Background: `docs/PILOT_DESIGN.md` (mechanics), `docs/PILOT_NOTES.md` (dated findings), `docs/evaluation/PILOT_EVALUATION.html` (the pilot writeup, still from the 2026-09-03 runs), `docs/EFFICIENCY_AUDIT.html`, `SCOPE.html`.

## State

- Package `reproscope/` implements Stages 0–3, the report and the evaluation; 228 offline tests pass (`.venv/bin/python -m pytest tests -q`). Everything is pushed to origin.
- Three papers have complete end-to-end runs on the current code under fresh ids: `Hertel_ClinPsychSci_2018_YabW_v2`, `Ohtsubo_EvoHumanBehavior_2014_zlm2_v2`, `Petersen_Cognition_2017_yJwG_v2` (`runs/<id>/`, gitignored; corpus copies under `corpus/<id>/` with only the manifest id changed). Hurst and Axt have not run on the current code; their pilot runs (2026-09-03) and the three other pilot runs stay on disk under the original ids.
- Results of the v2 runs: Hertel 63 specifications all converged, F 5.40–7.46, reported 6.20 at rank 37 (all significant); Ohtsubo 8 specifications, d 2.14–2.20, reported 2.2 at rank 5; Petersen 9 specifications all equal to the reported 0.89. Replicas: Hertel 8/8, Ohtsubo 8/8, Petersen 6/8 (deepseek_2 script error, glm_2 returned nothing twice).
- Spend per paper including every failed pass: Hertel USD 0.77 metered / 12.6 list-equivalent, Ohtsubo 0.55 / 14.0, Petersen 0.59 / 11.4. OpenRouter credit left: about USD 4.1 of 45. The Claude subscription hit its session limit once (2026-09-07 about 18:00, reset 19:40).
- The evaluation and writeup (`docs/evaluation/`) have not been regenerated over the v2 runs.
- No pipeline process is running.

## Fixed on 2026-09-07 and 09-08 (details in PILOT_NOTES)

Degrees of freedom no longer forbidden by the leak scan; an empty extractor is retried then refused; a dirty scan fails Stage 0; Stage 0 steps are keyed on the artifacts they read; the focal binder anchors on the reported statistic and binds companions from its own analysis; the targeted arm and diagnosis are keyed on the binding; Stage 3 refuses a failed execution, the executor has 3600 s and a rule against reading package source; the claude route reports the API error it received; readiness that binds nothing is rechecked at the strong tier then refused; Stage 1 refuses zero runnable replicas; the retry runner waits 30 min on a session limit and gives up after two passes with nothing to force; OpenRouter calls get four attempts with backoff, skip the host that just failed, and treat a host-ended reply as transient; scrub chunks are 40 items; ledger rows carry provider and finish reason.

## Decisions waiting on Lukas

- **Single-call gates.** Three stage-level judgements were made by one cheap or mid-tier call and were wrong on a fresh run: the extractor (empty claim list), the Stage 3 executor (spent its budget in package source), and readiness (bound no analysis). Guards now catch the degenerate cases (empty, zero, failed) and escalate or refuse; a wrong-but-nonempty readiness or extraction still passes. Whether readiness moves to the strong tier by default (about USD 1.4 list-equivalent per paper) or gets a second independent call is a design choice.
- **Executor model.** glm-5.3-flash through opencode completed all three grids, but needed 40 min for 63 specifications and one retry on Petersen after an outage. A stronger or faster executor is a cost choice.
- **OpenRouter credit** needs topping up before Hurst and Axt (about USD 0.6 metered each) and any evaluation rerun.
- **Old Stage 0 outputs.** The pilot runs under the original ids keep Stage 0 output from the 2026-09-02 code. The writeup should be regenerated over the v2 runs once all five exist; the evaluation currently mixes both.

## How to run

```
.venv/bin/python -m reproscope run <paper_id> --stages 0 1 2 3 report
S0_ARGS='--force-step readiness' ./scripts/fullchain.sh <paper_id>      # Stage 0 (3 attempts) then the retry runner, logs under runs/logs/
.venv/bin/python scripts/chain_retry.py <paper_id>                       # Stages 1-3 + report with retries
.venv/bin/python -m reproscope ledger <paper_id>
.venv/bin/python -m reproscope.evaluate && .venv/bin/python docs/evaluation/cost_table.py && .venv/bin/python docs/evaluation/build_writeup.py
```

To run a paper on the current code, copy `corpus/<id>` to `corpus/<id>_v2` and set `paper_id` (and `multi100.paper_id`) in its manifest; Stage 0 renumbers claim ids, so never rerun it in place on a paper with replica outputs. Keep at most two papers in flight on the Claude subscription. A replica that must be relaunched is moved out of `runs/<id>/stage1/replicas/` (the checker only re-verifies a replica whose results file exists); `runs/<id>/stage1/replicas_superseded/` holds the ones set aside so far.

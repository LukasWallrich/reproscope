# Pipeline development status

The shared pipeline requires complete numerical verification for both reproduction replicas and every multiverse specification. Independent source-only method recipes determine the expected calculations; generated executor plans cannot define their own verification coverage. Reports present source quotes, recalculations, diagnoses, combined methods and component-level numerical comparisons.

| Case | Development source recall / precision | Computation accounting | Original-analysis verification | Multiverse verification |
|---|---|---|---|---|
| Hurst cheap v2 | 252/258 (97.67%) / 252/265 (95.09%) | 163 computed, 102 unavailable, 0 unresolved | Both replicas: 65/65 analyses and 123 inferential quantities; 40 descriptive readouts | 40/40 specifications on original and private inputs; 5 active dimensions |
| Petersen v7 | 135/136 (99.26%) / 100% | 124 computed, 9 unavailable, 2 invalid inputs, 0 unresolved | Both replicas: 28/28 executable analyses; 44 descriptive readouts | 12/12 specifications on original and private inputs; 5 active dimensions |
| Hurst v1 | 258/258 (100%) / 98.47% | 158 computed, 104 unavailable, 0 unresolved | Both replicas: 65/65 analyses; 40 descriptive readouts | 36/36 specifications on original and private inputs; 5 active dimensions |
| Ohtsubo v3 | Availability case | Missing studies and unresolved sample/condition/scoring correspondence | Does not count as a successful executable case | No accepted executable multiverse |

The extraction benchmark is model-assisted development validation, not human or held-out accuracy. All divergence groups have diagnoses (22 Petersen; 123 Hurst); an assigned diagnosis does not imply a resolved cause. Hurst v1 retains structural blinding limitations; the fresh cheap v2 packet has no detected numeric leak. Private perturbations test changed observations while preserving within-person records; exact untied signed-rank recipes use a subset without replacement to stay inside their declared domain. These are implementation diagnostics, not analytical choices.

## Reproduce and inspect

Run IDs are `Petersen_Cognition_2017_yJwG_v7_20260914` and `Hurst_EvoHumanBehavior_2017_yypJ_v1_20260915`. The current full-controller logs are `specr_final_refresh.log` in each run. Each run stores its current acceptance receipt in `end_to_end_validation.json`.

```sh
REPROSCOPE_MODELS=runs/<paper_id>/models.toml REPROSCOPE_REVIEW_BACKEND=strong_alt REPROSCOPE_SPECR_EXPORT=1 .venv/bin/python -m reproscope run <paper_id>
REPROSCOPE_MODELS=runs/<paper_id>/models.toml REPROSCOPE_REVIEW_BACKEND=strong_alt .venv/bin/python -m reproscope.end_to_end_validation <paper_id>
```

No paper-specific calculation scripts or hand-edited result tables were supplied. Bounded source repair uses approved inputs and verifier failures without reported numeric targets. Cached replicas require exact generation-input provenance, intact output hashes and verified execution evidence. Do not run concurrent writers on the same stage or change benchmark answers to meet acceptance.

The [specification-curve and clarity validation record](validation/2026-09-17/REVIEW_DISPOSITION.md) supplements the [numerical verification record](validation/2026-09-15/VERIFICATION_REPORTING.md) with regression results, browser QA and publication receipts. The [stage specification](E2E_ANALYSIS_REPORTING_SPEC_2026-09-14.md) and [multiverse literature review](../research/multiverse_scope_literature_review_2026-09-14.md) document the analysis scope. Leave-one-out diagnostics, seeds and draws are excluded from analytical dimensions. Raw trimming/outlier variants can share a substantive raw-effect group with exact estimator labels; different scales and nulls remain separate.

Next validation should use held-out papers and independent human extraction annotation. Add independently anchored numerical methods when newly screened defensible choices require them; unsupported combinations must remain acceptance blockers. Computational agreement does not establish the substantive appropriateness of every reconstruction assumption.

The fresh inexpensive Hurst run is complete and published: `Hurst_EvoHumanBehavior_2017_yypJ_cheap_v2_20260917`. Its final ordinary controller refresh includes stages 0–3 and report generation; `end_to_end_validation.json` passes with no blockers. The run-specific `models.toml` uses Haiku and Luna for general replicas, with targeted Sonnet repairs and focused source review; no general Opus/Fable replica is used. Both numerical replicas and all 40 multiverse specifications pass original/private-input checks. All 122 required diagnosis groups have located source evidence. The unchanged source benchmark remains development validation. See the [fresh-run validation record](validation/2026-09-17/CHEAP_HURST_VALIDATION.md) for methods, checks and limits.

The fresh US$3 metered allowance has US$0.709687 confirmed and US$0.6645216 conservatively reserved, totalling US$1.3742086 against the cap. OpenRouter payment rejection triggered a bounded subscription patch to the existing executor. Subscription consumption and development retries are separate; this run is not a normal per-paper efficiency benchmark. The final offline suite passes 692 tests, and desktop/mobile browser checks and the actual R/specr SVG inspection pass.

 The preceding metered allowance remains US$0.707303 confirmed plus US$1.182020 reserved for an interrupted request with unknown charge: US$1.889323 conservatively, below the authorised US$3 cap. The opt-in budget file is `docs/validation/2026-09-14/e2e_review/metered_budget.json`; do not reset it or reuse the allowance for unrelated work.

Public report destinations are [fresh inexpensive Hurst](https://reproscope-hurst-2017-cheap-v2.surge.sh/), [Petersen](https://reproscope-petersen-2017-v7.surge.sh/) and [Hurst](https://reproscope-hurst-2017-v1.surge.sh/). Exports contain standalone HTML without participant records, run archives or local paths. Preserve substantial pre-existing workspace changes; no commit or repository push was requested.

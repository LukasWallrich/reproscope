# Pipeline development status

Current validation is the fresh ordinary-pipeline run `Petersen_Cognition_2017_yJwG_v7_20260914`, alongside Ohtsubo v3 and Hurst v1. The [current specification](E2E_ANALYSIS_REPORTING_SPEC_2026-09-14.md) and [live validation record](validation/2026-09-14/TWO_PAPER_VALIDATION.md) govern acceptance. Petersen and Ohtsubo exceed 95% extraction recall/precision on model-assisted development benchmarks. Petersen's two replicas verify 28 analyses; final descriptive-sample repairs and the general multiverse are running. Ohtsubo remains an explicit availability/binding limitation, so Hurst is the second executable case. The next validated reports are authorised for Surge publication. Metered task spend remains zero.

The v6 findings below are historical and do not establish acceptance of the current pipeline.


The [multiverse scope literature review](../research/multiverse_scope_literature_review_2026-09-14.md) records the current design recommendation and pending reconciliation tasks. Group justified raw-scale trimming/outlier alternatives with comparable raw effects, retain estimator labels, report inference choices explicitly, and keep influence diagnostics separate. The implementation and v6 receipt still use the existing rules; they do not validate this revised contract or general prompt-based multiverse generation. Reconcile the dimension count and statistical-analysis-review terminology before finalising the pipeline.

The current end-to-end development run, `Petersen_Cognition_2017_yJwG_v6_20260914`, passes acceptance. See the [validation findings and limits](LIVE_INTEGRATION_V6_2026-09-14.md), [report](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/report/report.html), and [acceptance receipt](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/completion_validation.json).

- Extraction: 135/136 clean source occurrences (99.26% recall), with 135/135 meanings confirmed by a separate model judge against the frozen source-first benchmark. This is paper-specific development evidence, not independent human or held-out validation.
- Computation: 124 extracted quantities computed, nine unavailable from the deposit, two blocked by invalid deposited inputs. No extracted number is silently omitted for lacking an analysis assignment.
- Reproduction: both fresh implementations verify all 28 supported analyses; 44 descriptive quantities are independently computed in Python/R. Every replica passes 17 paired-t and six likelihood-ratio degrees-of-freedom checks.
- Signs: the source binds expected direction to ordered columns. Reported t = 3.52 and computed −3.523 agree with the stated decrease. Raw signs remain visible. Per replica, 72 inferential quantities match in the top band, two have unstated direction, two are rounding-compatible bounds, and four are substantive likelihood-ratio discrepancies.
- Divergence diagnosis: all 21 issue groups across 24 source quantities are covered, retaining every source occurrence and replica. This includes descriptive mismatches, within-band precision discrepancies, qualified bounds/directions and data limitations. Missing or stale coverage blocks acceptance.
- Analysis review: the default asks only about clear coding errors and clear interpretation errors. No clear coding error is established in the supplied implementations; input/reporting causes remain unresolved. The reviewer flags non-significant difference tests interpreted as equality or no difference. General causal-language, power and measurement critiques are outside this default check.
- Multiverse: 30 compatible full-sample specifications across five active analytical dimensions; 112 separately labelled influence diagnostics. Independent R and perturbation checks pass. Leave-one-out is not counted as an analytical dimension.
- Validation: 477 tests pass, 14 live tests skipped, one slow test deselected; final report checks also pass. A warm resume makes zero model calls and changes none of 60 scientific artifacts. Report structure and the numerical sensitivity and correctness sections pass their documented QA scope; the existing plots are unchanged.
- Cost: v6 uses 65 recorded subscription-route attempts (62 successful; three input-size rejections before model execution) and $0 new metered usage. Prior recorded API spend plus the $0.45 interruption reserve totals $1.401964943346 against the authorised $5 metered cap.

The low Stage 0 headline was an arbitration-bypass metric. It is now labelled correctly: 35/135 bypass arbitration, 45/135 agree exactly on compared semantic fields, and all 135 paired literal transcriptions agree. Final source correctness is assessed separately. The v5 acceptance claim is superseded by the current run.

## Recheck or resume

```sh
.venv/bin/python runs/Petersen_Cognition_2017_yJwG_v6_20260914/verify_acceptance.py
.venv/bin/python runs/Petersen_Cognition_2017_yJwG_v6_20260914/launch.py
```

Both scripts find the repository root and use run-local subscription settings. The completed run started from PDF/data only and resumed after source-anchor and review-routing fixes; it did not inherit v5 scientific outputs. Current preflight checks bind code, inputs and outputs. Preserve historical validation evidence and all frozen v3/v4 files; acceptance checks 12 v3 artifacts and 645 v4 files.

The next research validation task is an independently annotated held-out corpus, with prespecified denominators and per-quantity/source-layout strata. This is needed before claiming general pipeline accuracy. Generation remains tool-free but not OS-isolated; verification is isolated. Do not overstate blinding or upstream reproduction.

The [review-revision warm resume](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/review_revision_warm_check.json) made zero model calls. Both replica result files and all multiverse numerical rows are unchanged from the archived pre-revision run. Full-sample results are positive with intervals above zero in all four estimand classes; leave-one-out causes no sign, interval-side or p-threshold changes. Maximum raw-mean influence is 2.5099 units (0.468 baseline SE). See the report for all numerical ranges and the precise matched-baseline aggregation rule.

Changes remain uncommitted; no push or publication was requested. A local report server may use port 8874; do not stop unrelated port 8765.

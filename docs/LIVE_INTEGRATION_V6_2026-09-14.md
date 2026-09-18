# Pipeline validation: Petersen 2017

The current pipeline passes its end-to-end development acceptance on this paper: it extracts 135 of 136 clean source result occurrences, accounts for every extracted number, verifies all 28 analyses supported by the deposit, and executes 30 full-sample specifications across five active analytical dimensions. Paired-test matching checks magnitude and source-grounded direction separately, so a positive printed t statistic can agree with a negative recomputed statistic when the ordered subtraction represents the reported decrease.

The [current report](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/report/report.html) and [acceptance receipt](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/completion_validation.json) contain the evidence. This establishes development acceptance for one paper; it does not establish performance on unseen papers or independent human validation.

## Results and their limits

| Requirement | Verified result |
| --- | --- |
| Clean source extraction | 135/136 occurrences: **99.26% recall**, 135/135 judged correct: **100% precision**. |
| Every extracted number accounted for | **124 computed**, nine unavailable from the deposit, two blocked by invalid deposited inputs; no unassigned omissions. |
| Inferential reproduction | Two fresh implementations each verify **28/28 supported analyses**, covering 80 reported quantities. Code audits and perturbation checks pass. |
| Descriptive reproduction | **44 quantities** independently computed in Python and R; nine unavailable quantities have individual reasons. |
| Paired-test signs | Magnitude and substantive direction checked separately against anchored paper statements and named, ordered data columns. Eleven false sign failures resolved. |
| Printed degrees of freedom | **23 checks per replica** (17 paired t tests and six likelihood-ratio tests), all matching: 46 checks total. |
| Multiverse | **Five active analytical dimensions**, 30 compatible full-sample specifications, and 112 separately labelled influence checks. Independent R verification and perturbations pass. |
| Regression checks | **477 tests passed**, 14 live tests skipped, one slow test deselected. Final report-specific checks: 13 passed. |
| Warm resume | Zero new model calls; all **60 scientific artifacts unchanged**. |
| Cost | **$0 new metered usage**, 65 recorded subscription-route attempts (62 successful, three input-size rejections before model execution). Prior recorded spend plus the interruption reserve totals $1.402 against the authorised $5 cap. |

### Extraction quality and arbitration

The low headline percentage measured whether a record bypassed arbitration. It did not measure extraction correctness. The report now labels these quantities separately:

- All 135 paired literal transcriptions agree on the number, operator, precision and statistic kind.
- Exact agreement across compared semantic fields is 45/135 (33.3%). These fields include free-text descriptions, for which wording differences can trigger arbitration without changing meaning.
- Only 35/135 records (25.9%) bypass arbitration; ten otherwise agreeing figure records require mandatory adjudication.
- Final source accuracy is evaluated against a frozen inventory of 136 clean physical result occurrences, using a separate model judge supplied with the paper and candidate meanings, without reproduction values or earlier verdicts.

The inventory was developed from the source and visually audited across all nine pages before comparing pipeline output. The sole missing occurrence is “One participant made above 50% incorrect responses.” Repeated reported results count as separate physical source occurrences. The benchmark is model-assisted and paper-specific; a held-out, independently annotated corpus remains necessary before claiming general extraction performance. Arbitration frequency remains an efficiency issue, distinct from this measured final accuracy.

### Computation coverage and discrepancies

Every extracted quantity now needs a verified computation or a specific unavailable/invalid-input disposition. Descriptive computation is enabled by default; lacking an analysis assignment cannot silently exclude a number. Sample sizes are classified as descriptive quantities and retain their computation obligation.

The 124 computed quantities comprise 80 inferential and 44 descriptive readouts. Nine quantities cannot be recovered from the deposited files: two compensation counts, four quantities about recruited or excluded behavioural samples, two pupil-waveform latencies, and the trial-artifact percentage. Two inferential quantities belong to a likelihood comparison whose deposited inputs violate nested-likelihood ordering. These are explicit limits, not successful reproductions.

Among the 80 inferential quantities, each replica has 72 top-band matches, two magnitude matches with unstated source direction, two rounding-compatible bounds that do not literally satisfy the printed inequality, and four substantive likelihood-ratio discrepancies. Those four discrepancies concern two supported comparisons. The report preserves raw values and distinguishes these outcomes; computation verification does not imply agreement with the paper.

For the user's paired-test example, the reported t(27) = 3.52 and computed t = −3.523081 agree in magnitude and with the stated decrease under the bound column order. The source, rather than the reproduced value, supplies the expected direction. Explicit author subtraction order takes precedence where present; otherwise an unstated direction receives no unqualified directional match. Absolute-value matching is not applied indiscriminately to correlations, coefficients or other signed quantities.

### Five analytical dimensions

Full-sample specifications vary scale (raw/log ratio), location (mean/20% trimmed mean), inference (paired t/centred bootstrap), multiplicity (none/Holm/Bonferroni), and confidence-interval construction (standard t or percentile/bootstrap BCa where compatible). All five change an inferential output in matched full-sample comparisons. Leave-one-out sampling is an influence diagnostic and does not count toward this requirement.

The 30 full-sample specifications include nine primary-estimand and 21 alternative-estimand specifications. Trimmed-location paired t and paired-t BCa combinations are excluded. The 112 influence diagnostics span four scale/location estimands across 28 omitted participants. Results with different units or estimands are displayed separately rather than pooled into a common rank or median.

Bootstrap implementations use 9,999 draws and shared resampling indices for Python/R arithmetic verification. BCa intervals also pass a separate test against [SciPy's bootstrap implementation](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) on a skewed sample. Degenerate bootstrap/jackknife inputs fail explicitly; sparse adjusted tails are flagged. Interval choice does not change the centred-bootstrap p value, and intervals remain unadjusted 95% intervals when multiplicity adjustments change p values. These distinctions are recorded in the output.

## Divergence diagnosis and numerical sensitivity findings

The current inventory has 21 issue groups spanning 24 extracted quantities. Grouping retains every affected claim and replica. It includes three small printed-precision mismatches, four likelihood-ratio quantities grouped into two comparisons, two descriptive mismatches, two rounding-compatible inequality boundaries, two unstated directions, nine unavailable quantities and two quantities blocked by invalid deposited likelihood inputs. The default report diagnoses all groups, including evidence-supported limitations and unresolved causes. This coverage is a release requirement.

The two supported likelihood comparisons exceed the paper's statistics by approximately the same 643.83 offset and share a baseline likelihood column. That supports a shared input/model-mapping hypothesis; it does not identify a demonstrated author coding error. The pupil SD differs by approximately a factor of ten (0.05158 computed versus 0.52 printed), consistent with a possible decimal transcription error. The original analysis outputs are needed to resolve those causes. A mean fit percentage of 98.50684 versus 98 reported could reflect truncation, aggregation or input differences.

The full-sample multiverse results are:

| Estimand | Specifications | Estimate | Unadjusted/adjusted p range | Interval conclusion |
| --- | ---: | ---: | --- | --- |
| Raw mean difference | 9 | 25.7942 | 0.0000668–0.0006 | All intervals above zero |
| Raw 20% trimmed difference | 6 | 22.6650 | 0.0007–0.0021 | All intervals above zero |
| Mean log ratio | 9 | 0.30418 | 0.0000296–0.0003 | All intervals above zero |
| 20% trimmed log ratio | 6 | 0.29662 | 0.0002–0.0006 | All intervals above zero |

Inference, interval construction and multiplicity change uncertainty or p values within each estimand; they do not change its point estimate. These rows are not independent votes, and raw/log or mean/trimmed targets are not pooled. The HTML report includes separate ranges for interval endpoints and the full numerical specification table.

Leave-one-out calculations are separated by `spec.sample`: only `full` rows enter the analytical grid and dimension-activity checks. Each deletion is compared with a full-sample specification matching all five analytical settings. Here the diagnostic baseline uses unadjusted centred bootstrap with a percentile interval for each scale/location estimand. This baseline is distinct from the primary paired-t specification where their inference settings differ.

Maximum deletion changes are 2.5099 raw units (0.468 baseline SE) for the mean, 1.7720 raw units (0.283 SE) for the trimmed mean, 0.019249 log units (0.325 SE) for the mean log ratio, and 0.017798 log units (0.236 SE) for the trimmed log ratio. No deletion changes the estimate sign, interval side relative to zero, or p < .05 classification; no deletion estimate falls outside its matched full-sample interval. The report identifies the participants attaining each maximum. Ranges and maximum shifts describe influence, not uncertainty intervals or robustness probabilities. A prespecified outlier-exclusion rule would be a separate analytical choice; leave-one-participant-out is not one.

## Pipeline root causes addressed

| Root cause | Current behaviour |
| --- | --- |
| Arbitration routing presented as extraction agreement | Separate literal agreement, exact semantic-field agreement, bypass rate and benchmark accuracy. |
| Computation driven only by assigned inferential contracts | A coverage gate covers every extracted record, with descriptive computation enabled by default. |
| Extraction prompt conflating sample-count type with computation duty | Sample counts remain descriptive; routing and coverage enforce their computation. |
| t-test signs compared without ordered contrasts or narrative direction | A source-only direction pass binds evidence to ordered columns; matching checks magnitude and direction separately. |
| PDF spacing/subscripts and cross-page text breaking valid evidence anchors | Conservative text normalisation plus bounded quote-only repair; original evidence retained, unsupported anchors block progress. |
| Source-evidence gaps triggering computational retries | Unknown direction with matching magnitude remains a source limitation; it does not launch a reconstruction. |
| Legitimate targeted audit rejected by the review-backend whitelist | The unblinded targeted audit is an explicitly supported review route. |
| Degrees of freedom hidden inside composite printed statistics | Printed t and likelihood-ratio df are independently checked against the corresponding verified analysis. |
| Influence diagnostics counted as an analytical dimension | Activity is measured on full-sample results; a substantive fifth interval dimension is implemented and independently checked. |
| Incomplete benchmark-judge payload losing subgroup context | Candidate analysis labels and descriptions are included alongside source evidence and frozen expected meanings. |
| Historical execution receipts presented as current acceptance | The report displays current code/input/output preflight checks; stale artifacts cannot establish current readiness. |

## Validation scope and operational evidence

This run began from the PDF and deposited data; no v5 extraction, contracts, generated scripts or results were copied. Execution resumed after source-anchor and review-routing fixes, reusing verified primary computations. The primary Fable and Opus implementations both pass independent method verification. Generation used tool-free subscription routes, but was not OS-isolated; packet checks therefore do not establish complete blinding. Verification execution was isolated. Upstream model fitting and unavailable raw measurements are outside the verified deposited-data computation boundary.

The default Stage 2 now asks only about clear coding and interpretation errors. General causal, measurement and power critiques are outside this default review; the optional extended functions remain available separately. Every finding must have a verified source anchor, a checkable demonstration or explicit unresolved status, and a stated consequence. Divergence diagnosis covers all analyses and descriptive quantities, including small printed-precision departures accepted by the tolerance band.

The acceptance checker confirms 645 frozen v4 files and 12 frozen v3 artifacts are unchanged. Earlier invalid direction grades and the incomplete benchmark-judge payload are retained in run-local validation archives. The final separate judge confirms all 135 candidate meanings; the source claims and frozen denominator were unchanged by the payload correction.

The report passed structural checks for duplicate IDs, unsafe/remote resources and the required qualifications. Headless Chrome screenshots of the correctness and sensitivity sections were inspected at the report’s actual content width. The existing four-panel plots and all numerical outputs are unchanged from the archived run; both plots were previously visually inspected. This does not claim screenshot inspection of every report row.

Recheck the completed run without model generation:

```sh
.venv/bin/python runs/Petersen_Cognition_2017_yJwG_v6_20260914/verify_acceptance.py
```

Resume through all pipeline stages using its recorded subscription configuration:

```sh
.venv/bin/python runs/Petersen_Cognition_2017_yJwG_v6_20260914/launch.py
```

Supporting receipts: [warm resume](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/review_revision_warm_check.json), [tests](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/review_revision_tests.log), [report QA](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/report_qa.json), and [source benchmark](../runs/Petersen_Cognition_2017_yJwG_v6_20260914/stage0/extraction_benchmark.json). Changes remain uncommitted; nothing was pushed or published.

The run before the review revision is preserved under `docs/validation/2026-09-14/pre_review_revision_v6/snapshot`, with its file hashes. The separate extraction judge was reused only after confirming that the shown source meanings and exact cached prompt were unchanged; refreshed extraction metadata is bound by the current benchmark receipt. Citation validation supports conservatively normalised PDF whitespace and decoded JSON evidence strings without changing words, signs or values. Locator-only repairs preserve original anchors.

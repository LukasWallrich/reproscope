# Petersen v5 development evidence (superseded acceptance)

**Current status:** V5 is not current under the revised validation checks. See [HANDOFF](HANDOFF.md) for corrected direction grading, all-number coverage, separate semantic judging, and the fresh v6 run. The historical execution and warm-resume receipts below describe the version at their timestamps; they do not establish acceptance of the revised pipeline.

The extraction benchmark contains **136 clean physical result occurrences**, independently inventoried from the page images before scoring the pipeline output. The new pipeline returns **134 correct occurrences (98.53% recall; 100% precision)**. All ten figure brackets have distinct physical identities and correct panel/comparison meanings. Two occurrences are missed by both readers: an observed incorrect-response percentage and a repeated sample size. The benchmark is development evidence for this paper; it does not establish performance on unseen papers.

The fresh run `Petersen_Cognition_2017_yJwG_v5_20260914` has executed all stages. Both new replicas independently verify **28/28 supported analyses**, including named test families and six conditional likelihood comparisons. A further likelihood comparison is blocked by a nesting violation in the deposit. **43 descriptive quantities** independently agree between Python and R; nine require unavailable inputs. The full multiverse executes **522 independently verified specifications across five active dimensions**. **The acceptance receipt passes with no blockers.** A warm resume adds zero model calls and leaves all 49 checked scientific artifacts unchanged. The suite passes 440 tests, with 14 live tests skipped and one slow environment test deselected.

## Why extraction needed redesign

The former 57.1% figure measured candidate pairing, not extraction accuracy. Candidate labels were being asked to do three different jobs: locate a physical source occurrence, identify the analysis, and encode its meaning. This failed when PDF reading order or fonts damaged the extracted text, when figure brackets shared a significance legend, and when a result's interpretation depended on surrounding or preceding-page text. Strict text matching then rejected correct visual readings, while neither-reader omissions were absent from the agreement denominator.

The pipeline now uses stable identities derived from the PDF hash, page and token coordinates. The identities distinguish the physical bracket from its shared legend. Two readers receive page images and unlabelled physical candidates, but no adjudicated result inventory. Each records page/region coverage. Arbitration resolves semantic meaning from the paper while retaining the physical identity and printed literal. Source validation separately checks location, numeric value, comparison operator, precision and statistical kind. Damaged native text needs an explicitly adjudicated image reading. The pipeline preserves a clearly printed value even when the deposit yields a different number.

Benchmark annotation is outside the pipeline. A source-only image inventory was followed by visual inspection of all nine pages, correction of inclusion decisions and an explicit semantic review. The same assistant reviewed the development benchmark and developed the pipeline; this is not an independent human or held-out annotation study. Frozen gold, physical IDs, candidate mapping, semantic hashes and missed occurrences are retained in `validation_benchmarks/petersen_2017/` and the run's `stage0/extraction_benchmark.json`.

## Root-cause controls across the reported problems

| Problem | Current pipeline behaviour | Acceptance evidence |
| --- | --- | --- |
| Source identity and completeness | Physical occurrence IDs precede semantic matching; complete page inventories expose missing regions. Accuracy uses a source-only denominator. | 134/136 clean occurrences; no extra or duplicate results; all ten figure brackets correct. |
| Arbitration | Meaning and literal transcription are separate. Cross-page context is supplied; the arbiter cannot substitute a legend token for a bracket. | Semantic benchmark checks and wrong-value/operator/precision/location regressions. |
| Readiness | Explicit sample selectors, named scalar members and likelihood bindings describe executable operations. Upstream exclusions are context when the post-exclusion deposit already contains the authorised sample. | Binding, membership, parser and sample-selection regressions; fresh intake checked before generation. |
| Deposit validity | Missingness, identifiers, finite values and nested-likelihood inequalities are checked before computation. | Invalid nested comparisons remain unavailable; the deposit is never silently repaired. |
| Computation | Scripts regenerate a closed plan and every requested result. Named families and likelihood comparisons have independent reference adapters; descriptive readouts have separate Python/R implementations. | 43 descriptive readouts independently verified; both replicas verify 28/28 requested analyses and all three data-perturbation checks. |
| Matching | Ordered member arrays and declared aggregation determine family bounds, including t and effect-size vectors. Equalities use printed precision; bounds retain literal truth values and separate rounding-compatibility notes. | No sign flips or scaling selected by closeness to published values. Both replicas grade all 80 requested inferential quantities. |
| Method agreement | Agreement uses independently checked execution fields and preserves unknown methods. | Exact-member, sample, family, parameter-count and formula checks. |
| Broad review | Hierarchically numbered methods headings are recognised. Findings identify exact supplied snapshots and executable diagnostics. A bounded locator repair preserves original quotations and cannot alter the finding. | Source anchoring, diagnostic execution and semantic entailment remain separate. |
| Causal language and alignment | Intervention/assignment evidence is separate from statistical significance; settings come from execution evidence. | Deterministic source/setting gates; general reviewer calibration remains outside this single-paper acceptance. |
| Power/MDE | Calculations use the relevant paired/independent design and verified N. Unstated test direction yields labelled conditional results. | Numeric design/direction regressions. |
| Author settings | The scoped sensitivity design is explicitly registered; it does not infer author choices from matching results. | Primary row, family, scale, functional, inference and sample scope recorded before computation. |
| Multiverse | Five dimensions: scale, location functional, inference, multiplicity and influence sample. Incompatible cells are excluded; distinct targets have separate panels. | Fresh full run: 522 specifications independently agree with R; five dimensions affect results; all three perturbations and the code audit pass. |
| Generation access | Tool-free generation receives only an explicit blind file payload. Scripts execute with denied external reads/network and a restricted write root. | Live generation/execution probe and OS receipts; this mode applies to the configured Claude route and textual inputs. |
| Retry and comparison policy | Bounded repairs retain original attempts and receipts. Generation and verification have separate cache dependencies. | Failed development attempts remain visible. The two-model development run supports no model-family ranking. |
| Finalisation | Source accuracy, supported reproduction, simulation verification, current dependencies, cost and historical preservation have separate checks. | `verify_acceptance.py` passes; the warm resume adds zero calls and changes none of 49 scientific artifacts. |

## Multiverse interpretation

The grid has 18 compatible full-sample specifications and 18 per leave-one-participant-out sample. Raw mean effects, 20% trimmed effects and log ratios answer different questions. The inference dimension compares a paired t procedure for the mean with a centred empirical bootstrap; trimming removes `floor(0.2*n)` differences from each tail, including in bootstrap samples. Multiplicity uses none, Holm or Bonferroni over an explicitly declared family of distinct verified paired comparisons. The family definition is one analytical choice, not the only defensible family.

Bootstrap calculations use 9,999 draws with recorded seeds and common participant resampling indices. Independent R calculations read the original deposit and the registered indices, verifying the arithmetic exactly without claiming independent random draws. Percentile effect intervals and centred-bootstrap p values are not dual; symmetric intervals are also retained. Raw p values include binomial Monte Carlo intervals. Influence rows are diagnostics and are never pooled into a ranking of author choices.

## Boundaries and reproducibility

All computations start from deposited participant-level summaries and maximised likelihoods. They cannot rerun unavailable trial processing or model fitting. A reproducible disagreement with the printed paper is distinct from an extraction error or an implementation failure.

Use the run-local `launch.py` with the repository on `PYTHONPATH`; it selects the recorded subscription configuration and resumes the ordinary pipeline without a legacy task pin. The benchmark is scored separately. Historical v3/v4 runs are frozen; 645 v4 hashes are recorded for the final preservation check.

The authorised metered cap is **$5**, plus subscription usage. Prior recorded API spend is $0.951964943346, with a separate $0.45 interruption reserve. V5 uses subscription routes. Claude completed extraction and both replica generations before its CLI began returning an authentication error. The recorded `strong_alt` Codex subscription backend handles unblinded reviews and code audits; generation is not rerouted. V5 metered spend is $0; recorded prior spend plus the interruption reserve totals $1.4020, below the $5 cap. Changes are uncommitted and no publication was requested.

## Computation and printed-value agreement

Each replica computes 80 requested inferential quantities. Corrected source-direction grading gives 72 top-band matches, two magnitude-only comparisons whose direction is unstated, two literal family bounds compatible with rounding but not literally satisfied, and four substantial discrepancies in two deposited likelihood comparisons. Paired t/d magnitudes and substantive direction are checked separately against source statements and the verified column ordering; raw values are retained. All 17 printed paired-test degrees of freedom agree with the independently verified sample sizes.

The two-stage reproduction cannot verify the original fitted likelihoods or explain their discrepancies without the underlying fitting inputs. This limitation remains visible even though the independently implemented arithmetic agrees.

## Acceptance artifacts

- [Full pipeline report](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/report/report.html) and [machine-readable report](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/report/report.json).
- [Acceptance and preflight receipt](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/completion_validation.json): not current: preflight requires a fresh run under the revised code and inputs.
- [Extraction benchmark](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/stage0/extraction_benchmark.json): 98.53% recall, 100% precision, both misses retained.
- [Multiverse design](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/stage3/registered_design.json) and [execution verification](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/stage3/execute.json).
- [Warm resume](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/warm_resume_check.json), [test log](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/tests_full.log) and [report QA](../runs/Petersen_Cognition_2017_yJwG_v5_20260914/report_qa.json).

The report is about 416 KB, has no duplicate element IDs, and contains both scoped plot panels. Both final PNGs are byte-identical to the visually inspected probe plots. Native browser preview was unavailable because the computer-use service could not connect to Chrome; static report checks and the standard R plot inspection are recorded separately. All 645 frozen v4 hashes and all 12 recorded v3 hashes remain unchanged.

To resume and recheck without forcing generation:

```sh
PYTHONPATH="$PWD" uv run python runs/Petersen_Cognition_2017_yJwG_v5_20260914/launch.py
PYTHONPATH="$PWD" uv run python runs/Petersen_Cognition_2017_yJwG_v5_20260914/verify_acceptance.py
```

The source-only benchmark is a development benchmark. Validation on unseen papers, independent human semantic annotation and broader calibration of review judgments remain necessary before making general performance claims.

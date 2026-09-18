# Pipeline quality: findings and implementation plan

Implementation status and current validation are in [Pipeline integrity implementation and validation](PIPELINE_IMPLEMENTATION_2026-09-13.md). This document preserves the frozen-run diagnosis and acceptance requirements.

The current run is useful as an execution test, but its reproduction scores are not ready for scientific interpretation. Source extraction introduces incorrect targets, unresolved targets reach grading, and several later judgements rely on unverified prose. These are pipeline problems. Correcting them takes priority over adding replicas or interpreting discrepancies with the paper.

This review covers `Petersen_Cognition_2017_yJwG_v3_20260913`, its report, frozen intermediate artifacts, implementation, and selected source-page checks. It is a development diagnosis, not an independently annotated completeness assessment. The original run remains unchanged. Its operational preflight passes; the separate semantic review does not.

## 1. Extraction: replace the current agreement measure and repair source identity

The reported **57.1% is 84 automatically paired records / 147 retained records**. Extractor A produced 132 records and B produced 106. Pairing classified 84 pairs as agreement and five as numeric conflicts, leaving 43 A-only and 17 B-only records. Arbitration dropped two records. This fraction measures the pairing system's output, not extraction accuracy or recall: both extractors can agree incorrectly or omit the same result.

The frozen outputs establish several distinct faults:

| Evidence | Root cause | Required change |
| --- | --- | --- |
| Nine identical text quantities on page 4 remain separate. Their labels are `Section 3.2 Results` and `3.2 Results`; similarity is 0.72 against a 0.8 cutoff. | Free-text location labels control identity. | Use stable source regions and structured study/outcome/contrast context. Normalise harmless label prefixes, but do not simply lower the fuzzy threshold globally. |
| Two further page-4 quantities are classified as `mean` by A and `other` by B. A includes ten figure significance markers; B includes none. | Extractors lack a sufficiently consistent target taxonomy and coverage inventory. | Define inferential quantities, descriptive quantities, design facts, and figure annotations separately; require page/panel coverage records. |
| Two pairs counted as agreement disagree on `=` versus `<`. Final claims `c099` and `c136` retain the wrong comparator. | Pairing checks numeric values without comparator fidelity; merging preferentially takes A's field. | Match the source occurrence first, then compare every required field. Any operator disagreement requires resolution. |
| Final claims `c075`/`c103` preserve incompatible readings .465/.463 of one bound; `c076`/`c088` preserve .699/.639 of one p-value. | Failed pairing creates singletons which are adjudicated separately, with no final uniqueness/consistency check. | Reconcile candidates jointly within a source region; prevent incompatible versions of one occurrence entering the target inventory. |
| The extractor prompt permits only `=`, `<`, `>`, while source statements include `≥` and `≤`. | The prompt contract loses information. | Represent all five operators explicitly, including inclusive bounds and aggregate statements. |

In [arbitrate.py](../reproscope/stage0/arbitrate.py), pairing is greedy and order-dependent, ignores study identity, and compares values after rounding to the coarser precision. The implementation can treat `.01` and `.015` as agreement. That is inappropriate for transcribing a particular printed token.

**Proposed representation:** a source occurrence has a page, region/table cell/panel, exact token or supported visual reading, surrounding context, and source hash. A unique reported quantity links one or more genuine source occurrences to an analysis and records statistic type, value, precision, comparator, metric, and aggregation. An analysis records the design and estimand. This distinguishes repeated reporting of a quantity from duplicate extraction of one occurrence. Confidence and validation status belong to individual fields.

Establish candidate identity from location and semantics **before comparing values and operators**. Putting the comparator into the identity key would hide comparator conflicts as separate targets. Use constrained matching with an ambiguity margin and an explicit unresolved option; require invariance to candidate order. Preserve decimal tokens and distinguish exact transcription from compatibility with reported rounding. Keep CI endpoints distinct.

**Improve acquisition after these deterministic repairs.** Build a layout-aware text inventory, with independent visual extraction for tables, figures and ambiguous text. Give each lane the same explicit coverage task without revealing the other's answers. Use a full figure, legend and identified panel/bracket for figure arbitration; cropping around `.01` often retrieves the legend without the comparison. Check page reassignment against an anchored occurrence, not a numeric substring elsewhere in the PDF. Test stronger or independent arbitration on labelled conflicts rather than assuming another model solves the problem.

**Acceptance:** zero wrong merges, duplicated occurrences, operator errors or missed known targets in the frozen regression cases; pairing invariant to order. Separately measure source-grounded precision, recall, identity accuracy, operator accuracy, and residual arbitration error on independently annotated pages, including targets missed by both extractors. Report each by text/table/figure and inferential/descriptive/design class. Keep inter-extractor agreement as a diagnostic and cost metric. A higher percentage alone is not acceptance.

## 2. Arbitration and state: prevent uncertain source targets from becoming results

Final figure claims `c023`, `c026` and `c027` explicitly have unresolved arbitration notes, yet their state is `complete` and each receives seven graded outcomes. `c026` also names the wrong contrast: the source bracket concerns NoCue versus 85 dB, while the claim says 40 versus 85 dB. The correctly bound analysis and the incorrect claim prose coexist. This is not evidence that replicas disagree about a sound task.

`apply_decision()` can correct only a numeric value; it cannot repair comparator, contrast, model, statistic type or evidence. `to_records()` lowers confidence for unresolved records but leaves the default complete state. Missing/duplicate arbitration IDs are not treated as a failed response contract.

**Change:** require exact decision-ID coverage and typed field patches backed by source evidence. Persist unresolved fields and reasons. A target with unresolved required source identity, statistic, operator or value must be ineligible for grading and for any generation task that depends on those fields. Other validated analyses may proceed. Genuinely undocumented optional author settings should remain explicit unknowns, without blocking unrelated computations.

Add consistency checks across claims, analysis contracts and the blind packet. For example, `c082`/`c084` describe a 3×3 versus 1×3 model comparison, whereas contract `a20` correctly specifies 2×3 versus 1×3. Replicas receive both instructions. Generate descriptions from one canonical target representation and validate all packet fields against it.

**Acceptance:** deliberately inject missing arbitration decisions, conflicting fields and unresolved figures; none may become a graded complete target. The known conflicting packets must fail before replica generation. Source errors must be reported as invalid pipeline inputs, while affected attempts and coverage remain visible.

## 3. Readiness: distinguish missing data from unresolved analysis structure

Analyses `a27`–`a29` are unbound even though relevant pupil and processing-speed columns exist. The binding schema mixes collections of condition-specific correlations with a single outcome/derived variable, and cannot resolve which speed column pairs with each pupil column. The match summary nevertheless uses the generic explanation “no data file covers it”.

**Change:** introduce explicit analysis-family expansion: each correlation has an outcome column, predictor column, condition, exposure duration, parsing policy and sample rule. Distinguish a derived variable from several separate analyses. Use deposit documentation to establish pairing; if the method remains ambiguous, preserve labelled candidate analyses without selecting the one closest to the paper. Carry typed readiness reasons through matching and reporting.

**Acceptance:** fixtures for multiple condition-specific correlations, blank numeric fields and genuinely absent data produce distinct, correct outcomes. Every executable child analysis has explicit column pairing and provenance. Reports agree with readiness on the precise reason for abstention.

## 4. Data validity and reproduction scope: show what the deposit can establish

The supplied data contain fitted parameters and pupil summaries. Recomputing tests from them does not validate trial preprocessing or model fitting. Data-readiness warnings about log-likelihood columns also require checks beyond successful numeric parsing.

**Change:** record dependencies from raw observations through preprocessing, fitting, summaries and final tests. Mark each step as independently recomputed, reused from the deposit, unavailable or conditionally checked. Add deterministic checks for pairing, exclusions, parameter bounds, and model nesting/log-likelihood ordering where the model contract warrants them. Distinguish a binding error from an observed deposit anomaly or an untestable assumption. Do not silently repair source data. “Original code unavailable” is a coverage outcome, not an execution failure.

**Acceptance:** synthetic swapped-column, broken-pairing and invalid nested-likelihood cases are detected at the affected branch. Every headline reproduction claim names its starting data tier. Reusing identical fitted parameters cannot earn credit for independently validating the upstream fits.

## 5. Computation audits: replace repeated manual judgement with a consistent policy

Seven replica audit adjudications were needed. Literal design facts, calculated sample sizes and narrative constants are not consistently distinguished. Some supplied N claims are accepted for some replicas and excluded for another; additional trace problems may justify different outcomes, but the provenance class of a supplied fact should not change with the model.

**Change:** classify requested outputs once as supplied facts, computable statistics or unsupported targets. Supplied facts may be repeated where useful but receive no independent computation credit. Determine the scope of invalidation from dependencies: a contaminated common computation invalidates its descendants; an isolated unsupported claim need not invalidate unrelated calculations. Retain attempt-level rejection and all planned attempts. Continue hash-bound adjudications, with rule versions and explicit evidence.

Use deterministic dataflow checks and task-specific perturbations alongside model review. Numeric perturbations alone cannot detect a hard-coded N: remove complete participant pairs, permute rows, and renumber IDs where these transformations are appropriate. Include legitimate design constants and note-only numbers as negative controls. Validate statistical adapters on independent reference cases.

**Acceptance:** independently labelled audit cases yield the same decision regardless of replica identity or wording. Known hard-coded outputs fail, legitimate constants do not, and invalidation follows the affected computation path. Record automated and assisted acceptance separately.

## 6. Matching: validate the estimand before grading numerical proximity

The match artifact records 106 sign flips. The matcher can select a sign or unit transformation because it improves the numerical match; no unit rescaling was activated in this run. Range statements are also inconsistently implemented as individual comparisons, arrays or CI-like extrema. Duplicate source records distort weighting.

**Change:** declare contrast orientation and unit conversions from semantics before unblinded matching. Report raw and canonically normalised values, with transformation provenance. A justified reparameterisation may be equivalent; an unexplained reversal is not. Define typed scalar, vector, CI endpoint and aggregate-bound outputs, including the member comparisons and `all`/`any` interpretation. Grade the correct metric and estimand before rounding or tolerance.

Use unique quantities for reproduction summaries, with separate source-occurrence coverage. Separate inferential outcomes, descriptive quantities and supplied facts. Show planned-attempt coverage alongside valid-input performance; invalid source targets must neither count as replica failures nor disappear from pipeline-quality accounting.

**Acceptance:** wrong-direction, wrong-unit and wrong-contrast fixtures cannot pass by searching for a favourable transform. Correct declared transformations remain supported. Aggregate tests include a case with one violating member. Adding a duplicate extraction cannot change reproduction performance.

The source comparator errors in `c099` and `c136` each generate seven apparent failures in the current match table. Those failures cannot be interpreted as reproduction evidence until their inputs are corrected in a new run.

## 7. Decision agreement and divergence: use actual execution records

The reported 67% decision agreement is based on model grouping of free-text traces. Inputs are truncated at 60,000 characters; some groups omit replicas, and undocumented choices are inferred as defaults or treated as equivalent because all scripts reuse deposited summaries. Elsewhere the report calls the eighth replica an abstention, although all eight executed and one was audit-rejected.

**Change:** collect structured, per-analysis execution facts: columns, sample, contrast, estimator, df, tail, metric, filters and reused upstream outputs. Compute equivalence for known fields; distinguish observed equivalence, mathematical equivalence, unknown settings and shared dependency. Validate exact replica coverage. Generate narrative counts from the run record and require citations to execution evidence for claimed method differences. Compare methods within analysis families rather than relying on whole-script cross-language diffs.

**Acceptance:** summaries reproduce execution/audit counts exactly; missing settings remain unknown; invented or misattributed method differences fail validation. Accepted and rejected executions remain distinguishable in method summaries. Report agreement by field with an explicit denominator.

## 8. Broad review: repair evidence anchoring and execute checkable diagnostics

**None of the seven broad-review findings has a verified anchor.** The prompt receives a formatted schema summary, but verification searches raw JSON. Other quotations contain ellipses, mathematical substitutions or text disrupted by two-column reading order. This explains some failures; it does not establish that every finding is substantively correct.

**Change:** provide stable source IDs for the exact text spans and structured facts supplied to the reviewer. Require selection of those IDs and spans rather than regenerated quotations. Preserve mappings through narrowly specified normalisation and provide visual-region evidence where necessary. Separate “source located”, “source supports the claim” and “diagnostic executed”. The current “Not verifiable” heading conflates these states.

Where a finding can be checked from CSVs, run a bounded deterministic diagnostic and attach inputs, code, values and hashes. Boundary counts and skewness are testable; inferred optimisation bias remains a hypothesis without further evidence. Do not turn a plausible mechanism into a verified defect. In `canonical_replica()`, replace selection by closeness to the reported number with a stable accepted baseline or coverage of each distinct method cluster.

**Acceptance:** every factual review statement has valid evidence or an explicit unsupported/hypothesis status. Anchors work for formatted schema facts, Greek symbols, two-column text and figures. Fabricated anchors fail. Baseline selection is invariant to reported-result proximity.

## 9. Causal language and claim alignment: separate the questions being judged

The causal-language check uses sample size, effect magnitude and significance in support of “very high” causal inference. Its three checked quotations are unverified. The broad review discusses a distinct issue—whether the manipulation isolates a particular mechanism—without a shared representation of the causal target. Alignment also makes method assertions from incomplete traces.

**Change:** distinguish the assigned intervention contrast, the measured/modelled outcome, and the proposed mechanism. Require evidence for assignment, timing and design; effect size or a small p-value cannot establish identification. Keep construct/mechanism interpretation separate from numerical estimand alignment. Share the validated focal target and structured execution evidence across these checks.

**Acceptance:** changing only effect magnitude or p-value must not upgrade causal identification. Cases separating an intervention effect from a mechanism claim receive distinct assessments. Alignment cannot assert settings absent from the evidence. This tests the reviewer, not the paper's causal conclusion.

## 10. Power/MDE: retain uncertainty while making the result useful

The adapter abstains because test direction is unresolved, but reports a generic list of possible design, variance and sample-size problems.

**Change:** report the precise missing prerequisite. Where appropriate, provide explicitly conditional one-sided and two-sided MDE calculations under a prespecified alpha, power and standardised effect metric. Do not infer the author's tail from agreement with the reported p-value. Require only assumptions relevant to the design.

**Acceptance:** known paired-design fixtures compute under declared alternatives; unknown alternatives remain unattributed and receive clearly labelled conditional results. An unsupported design produces a specific reason, not a plausible-looking calculation.

## 11. Author-setting attribution: make unknowns diagnosable

All six proposed factors lack an attributed author level. `derive_paper_levels()` receives a focal binding but does not include it in the prompt, and discards rejected candidate quotations without recording reasons. The source explicitly mentions paired tests, but the present artifacts cannot distinguish model abstention from failed quotation validation or failed mapping to the factor.

**Change:** first extract method facts with source anchors and scope; then map supported facts to factor levels for the focal analysis. Supply focal context and preserve raw responses, candidate levels and rejection reasons. Distinguish documented, not documented, ambiguous, conflicting and extraction/validation failure. Never use a replica's choice as an author-method proxy.

**Acceptance:** known explicit method statements map correctly on labelled cases; settings genuinely absent from the source remain unknown. Every rejected candidate has a diagnostic reason. The six-factor result should be explainable field by field, without requiring all six to become known.

## 12. Multiverse: align scope, effect scale and independent verification

Three specifications produce identical `dz` estimates while changing inference. That is a legitimate inference-sensitivity analysis, but it establishes no breadth of estimate robustness. The screen asks for raw mean-difference standard errors alongside `dz`, while the executor leaves them blank. Independent reference checks cover estimates and samples, and the analytic p-value; simulation p-values remain only partially verified.

**Change:** label the output as inference sensitivity when only inference changes. Define robustness around an explicit estimand; distinguish alternative estimands and influence diagnostics suggested by the broad reviewer. Do not manufacture estimate-changing choices to obtain a non-flat curve. Specify uncertainty outputs by metric: raw mean difference and its SE/CI are different quantities from `dz` and its uncertainty.

Independently validate bootstrap and sign-flip procedures, including null construction, exchangeability assumptions, tails, seeds, simulation counts and Monte Carlo uncertainty. Check tiny cases by exact enumeration where feasible and use independently implemented/calibrated reference cases. Repeatability and an `(exceedances + 1)/(B + 1)` formula do not establish algorithm validity. Run these checks on deposited summaries where applicable; they do not require recovering raw trials.

**Acceptance:** every requested output has a valid metric and verification status; the analytic and simulation branches pass their task-specific reference tests. Unknown author settings produce no author position. All-tied estimates retain the existing rank interval and undefined extremeness. Grid contradictions fail before executor generation.

## 13. Blinding: test cues and enforce the declared access boundary

Numeric redaction passed, but theory/background cues remain. Working-directory separation and transcript inspection do not establish an enforced access restriction.

**Change:** generate a minimal methods packet from validated design and target fields, retaining necessary contrast definitions while removing result/theory cues. Evaluate matched packets that vary irrelevant directional cues without changing the true method specification. If a run claims enforced blinding, restrict accessible files/network and save the permission manifest; test a harmless denied-access canary.

**Acceptance:** all included analyses have packet provenance and validated target consistency. Access claims are demonstrated, and cue-sensitivity is measured separately from numerical leakage. A clean numeric scan alone must not produce a full-blinding label.

## 14. Targeted retries, model comparisons and runtime: avoid misleading selection

The targeted arm correctly records that its numeric trigger did not fire, but that trigger depends on source targets and matching rules now known to be flawed. A single assisted case cannot establish cheap-versus-frontier performance. Cash cost also omits some auxiliary subscription work and may omit cancelled-request usage.

**Change:** require validated targets and method fidelity before interpreting the trigger; test source errors separately from legitimate reconstruction uncertainty. Keep a fixed attempt budget, preserve failures, and distinguish targeted from blind performance. Record wall time, model/phase, manual interventions and missing-cost coverage. Prefer deterministic diagnostics and focused evidence packets before increasing model spend; use phase-specific timeouts, bounded retries and checkpointed verification.

**Acceptance:** invalid intake cannot trigger a search for a better numerical match. Warm resumes preserve negative outcomes and add no generation calls. Model comparisons use the same planned cohort, tasks and acceptance rules; broader performance claims require a frozen held-out cohort.

## 15. Release gating: operational success must not imply validated conclusions

The current preflight checks freshness, execution and recorded audit acceptance. It does not detect the source-target errors above.

**Change:** expose separate statuses for execution currentness, source-target validity, method fidelity, independent verification coverage and human assistance. Derive release readiness from required checks for the claimed scope, allowing explicit partial coverage. Both per-paper and aggregate reports must consume these statuses. Preserve the current run as an immutable assisted development run, with this review attached; regenerate dependent stages under a new run ID when the packet changes.

**Acceptance:** this frozen run remains operationally current but fails semantic finalisation. Injected invalid source targets cannot produce a quality-pass report. Exported text, HTML and evaluation tables agree on scope and status.

## Implementation order and validation budget

1. **First: stop invalid evidence propagation.** Implement issues 1–2 and 15, exact comparator support, consistent target identity, complete arbitration decisions and required-field gating. Start with the frozen A/B outputs and source-checked cases; no new model calls are needed to test the deterministic defects. Corrected source readings belong in versioned fixtures, not edits to historical outputs.
2. **Then: make computation judgements reliable.** Implement typed bindings/quantities, audit policy, semantic matching and structured traces (3–7). Add source/diagnostic anchoring and shared causal/estimand scope (8–9). Resolve attribution and task-shaped MDE/Stage 3 validation (10–12). Validate blinding and operational coverage (13–14).
3. **Then: measure extraction, rather than just agreement.** Independently annotate complete selected pages, including all figure/table targets and both-missed quantities. Include every confirmed defect here as a regression case, but reserve separate unseen pages/papers for acceptance. Double-annotate critical identity/operator/contrast fields and adjudicate differences. Report assisted and automatic performance separately.
4. **Finally: rerun under a frozen specification.** A corrected blind packet requires fresh replicas; retrospective regrading alone cannot validate behaviour under corrected instructions. First run the fixed case as an integration regression, then a prespecified held-out cohort covering multi-study papers, repeated values, figures, tables, grouped outcomes and different statistical designs. Estimate and approve any bulk model cost before launching it.

For the known regression cases, require **zero critical identity, operator, contrast or state errors**. For held-out acceptance, specify the tolerated source-error rate and confidence bound before running. A proposed initial target is a one-sided 95% upper bound below 1% for critical errors among accepted inferential targets, plus a separate high-recall requirement; with zero errors, roughly 300 independent targets would be needed for that error bound. Targets cluster within papers, so a few hundred quantities from one paper cannot establish generalisation. Report uncertainty by paper and source class, abstention burden and review effort. This is a proposed release criterion, not a performance claim or a reason to accept lower recall through widespread abstention.

## Evidence and review provenance

The run's `quality_review/` directory contains `intake_diagnostics.py`, its JSON/text replay, `source_review_cases.json`, and `semantic_acceptance_review.json`. The latter is a review attachment, not an implemented replacement for preflight. Report and intermediate artifacts remain frozen. Code entry points include [arbitration](../reproscope/stage0/arbitrate.py), [extraction](../reproscope/stage0/extract.py), [readiness](../reproscope/stage0/readiness.py), [matching](../reproscope/stage1/match.py), [review](../reproscope/stage2/review.py), [multiverse](../reproscope/stage3/multiverse.py), and [report building](../reproscope/report/build.py).

Fable was consulted using `claude -p --model fable`; its response is saved as `quality_review/fable_improvement_review.txt`. The useful recommendations were to prioritise deterministic repairs, freeze A/B fixtures and annotate source truth before further model spending. Its numerical prediction of improved agreement is untested and is not adopted. One supplied label example was imprecise; the actual A/B labels are recorded in section 1. Comparator conflicts must remain detectable after identity matching, optional unknown settings need not block unrelated work, and neither nonblank SEs nor varying estimates are universal multiverse requirements.

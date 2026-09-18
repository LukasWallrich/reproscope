Audit snapshot of commit `8f04de8`, before the implementation changes. Current controls and remaining validation are documented in [PIPELINE_FIXES_2026-09-12.md](PIPELINE_FIXES_2026-09-12.md).

The pipeline needs stronger rules for accepting analytical evidence before the current run can be finalised as a validation of the pipeline. Completion, numerical agreement, and valid inference are currently allowed to substitute for one another. Several failures arise from explicit design choices that the existing tests preserve; changing model tiers or adding retries will not resolve them.

The priorities below concern the pipeline. Existing paper outputs are regression cases, not assessments of the papers. First fix evidence provenance, statistical contracts, execution verification, and dependency tracking. Then regenerate affected artifacts and evaluate a fixed cohort. Preserve the current outputs as evidence of the failures.

**1. A matching result is promoted into evidence of the authors' method. Release blocker.**

[`derive_paper_levels`](../reproscope/stage3/multiverse.py#L160) treats the best band-A replica's choices as the paper's choices. [`build_grid`](../reproscope/stage3/multiverse.py#L250) then retains a purported paper level even when the independent screen rejects it. Together, these rules create circular validation: numerical agreement supplies a method attribution, and that attribution overrides the validity check.

The Ohtsubo v2 artifacts demonstrate the complete path. The screen rejects an arbitrary highest-ID participant exclusion and explicitly states that the original exclusion is unidentified. The chosen replica used that exclusion, so the grid retains it as `paper` and varies the remaining factors around it. This is a pipeline failure even if all resulting estimates are similar.

Separate `documented_author_choice`, `replica_choice`, and `unresolved_choice`, with evidence anchors for the first. A close reconstruction establishes compatibility with the reported result, not identification of the original method. Choose a base implementation using validity and contract compliance; record numerical proximity separately. Keep a documented but rejected author specification as a labelled reference outside the accepted-specification denominator. An unidentified sample should produce an explicit limitation or a separately defined sensitivity analysis over candidate samples.

Required regression: two different methods produce the same reported value; neither becomes documented author practice. A rejected replica choice cannot acquire acceptance through the paper-level exception. Replace the test that currently asserts the screen can never remove a paper level.

**2. Statistical meaning is inferred from prose and generic numeric fields. Release blocker.**

The estimand contract stores model and sampling information mainly as strings. [`classify_design`](../reproscope/stage2/mde.py#L64) accepts any text containing a paired/within-subject phrase as a paired test, before checking the structure of the actual contrast. [`_focal_n`](../reproscope/stage2/review.py#L701) selects the modal `n` across focal-associated result rows, without distinguishing a subgroup count from the analysis sample. Generated Stage 3 scripts independently decide the meaning of `estimate`, `se`, `p`, and `p_threshold`.

Observed consequences span stages:

- Hertel's mixed-design interaction is assigned a paired-test MDE using 54 pairs.
- Ohtsubo's MDE takes a subgroup count of 15 as the total and splits it into seven participants per group. It reports 1.6317; an independent calculation for 15 versus 14 participants gives about 1.0800 under the independent, equal-variance t-test assumptions.
- Petersen's executor reports an SE for the raw mean difference alongside a standardised `dz` estimate. It adjusts p-values for multiplicity and also reduces alpha, applying the correction twice. Its Monte Carlo p-value can be zero because it omits the finite-simulation correction already requested by the screen.

Introduce a validated analysis specification shared across stages: design family, focal contrast, independent unit, repeated factors, analysis sample, group counts, effect metric, SE metric, and inference method. Make unsupported power designs abstain. Store raw and adjusted p-values separately, with adjustment family and a single decision rule. Use deterministic statistical adapters for supported designs, and apply explicit validation to generated analyses outside those adapters. This does not require replacing the whole pipeline with templates.

Required regressions: a between-group difference in within-person changes cannot become a one-sample paired test; subgroup counts cannot become total sample size; `estimate` and `se` have compatible units; corrected p-values are compared with the original alpha; Monte Carlo p-values use a valid finite-simulation calculation. The [statsmodels implementation](https://github.com/statsmodels/statsmodels/blob/main/statsmodels/stats/multitest.py) compares corrected p-values with alpha, and [SciPy documents](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.permutation_test.html) the numerator-and-denominator increment for randomised permutation tests.

Focal binding belongs under the same contract: require an unambiguous study, analysis, and contrast rather than accepting all numerical matches and resolving them through a quantity preference. The automatic `2t/sqrt(df)` conversion in [`focal.py`](../reproscope/focal.py) also needs a verified design; it currently applies without checking whether the t statistic came from independent groups, paired observations, or another model.

**3. Re-execution does not establish regeneration or statistical correctness. Release blocker.**

[`verify_execution`](../reproscope/stage3/multiverse.py#L949) copies `specs.csv` to a backup but leaves the original in place before executing the script. It compares estimates only. Consequently, a successful process that writes nothing can pass, and changes in p-values, SEs, sample sizes, convergence, or thresholds need not invalidate verification. Matching spec IDs establishes row identity, not implementation of the labelled factors; `read_specs` overwrites factor labels from the grid.

A temporary offline fixture confirmed that a script containing only `pass`, with an existing CSV, produces `ok=true` and `rerun_reproduces=true`. The model audit was stubbed to `not_run`; no model call was made. This demonstrates the deterministic verifier's gap, not that a particular live executor fabricated output.

Re-execute in a fresh directory containing declared inputs and implementation files, with no generated outputs or accessible cached results. Require new outputs and validate every downstream-consumed field by spec ID, including finite numeric values, p-value bounds, sample counts, convergence, and uncertainty. Record the actual implemented settings. Add independent reference calculations and input perturbation checks for supported analyses: changing relevant data must change the corresponding output; unrelated data should not.

Required regressions: a no-op executor fails; a p-only or n-only mismatch fails; a copied previous results table fails the input-perturbation check; a factor label without its analytical implementation fails a known reference case. These tests should run without model services.

**4. Review findings are descriptive metadata rather than executable constraints. Release blocker.**

The screen's `adjustments` are copied into the grid as prose. They do not alter the implementation instructions. Missing screen verdicts default to keeping a level. Hardcoding audit findings do not enter Stage 3's `ok` calculation, while Stage 1's `ran` flag depends on successful execution and at least one generated value. Stage 3's assembled confidence is high unless execution problems or a fallback focal binding are recorded; unresolved methodological findings do not determine that confidence.

The current screens identify several issues that remain in execution: merging equivalent branches, correcting permutation p-values, and an unidentified exclusion. A second reviewer would only help if its findings could change the stage outcome.

Represent required changes as structured constraints with statuses such as `satisfied`, `rejected`, and `unresolved`. Every retained level must have an explicit assessment. Rewrite and revalidate the executable grid after accepted amendments. Distinguish successful execution from accepted analytical output, and derive confidence from unresolved dependencies. Audit findings need adjudication because some current hardcoding hits concern harmless assertions or design constants; blanket rejection on a model verdict would introduce another failure mode.

Required regressions: omitted screen responses cannot silently count as accepted; an unmet mandatory adjustment blocks acceptance; missing audits stay unknown; an adjudicated result-hardcoding violation cannot contribute to accepted reproduction statistics.

**5. Cache reuse does not consistently follow the dependency graph. Release blocker for final reruns.**

There are several concrete gaps:

- [`stage1.inputs`](../reproscope/stage1/__init__.py#L29) omits readiness, although readiness determines the packet. It also omits replica prompts and data-file content. Individual replica reuse checks only whether results and trace files exist.
- [`readiness.run`](../reproscope/stage0/readiness.py#L239) rebuilds `schema.json` only when missing or forced. Changed data can invalidate the outer stage while leaving the schema read by readiness stale.
- Stage 3's paper-level and screen caches use upstream stage inputs, but not the actual proposed-factor artifact they read. Forcing enumeration can therefore leave the prior screen or paper-level mapping in use.
- [`executor_stale`](../reproscope/stage3/__init__.py#L87) checks the grid hash and output presence, but not the base script, data, executor prompt, model configuration, or environment. An edited executor prompt can reopen the stage without forcing execution. Ranking and interpretation similarly lack complete input fingerprints.

Give every step a manifest of its immediate inputs, prompt, relevant configuration, implementation version, and execution environment. Both whole-stage and per-step reuse must honour that manifest. Separate input validity from output integrity so edited or missing outputs also invalidate downstream use. A fresh run ID is useful provenance, but cannot be the correctness mechanism.

Required regression: a mutation matrix covering data values with unchanged schema, codebook, readiness, methods, script, prompt, model configuration, enumeration, screen, and specs CSV. Each change must invalidate exactly the affected descendants. A resumed run and a clean run must produce the same validated artifacts under fixed deterministic inputs.

**6. Evaluation denominators reward selective completion, and the cohort is implicit. Must settle before final evaluation.**

[`match.run`](../reproscope/stage1/match.py#L490) gives both missing keyed results and failed linking calls the same abstained status. [`_subset_stats`](../reproscope/evaluate.py#L247) removes them from match-rate denominators. Failed replicas are also excluded from scored pairs. Conditional agreement is useful, but it cannot alone measure whether the pipeline successfully reconstructs requested results. The `found` rate becomes 100% whenever every usable row is, by definition, found.

For example, Hertel's A+B rate is 87.8% over returned rows versus 84.1% over the requested pairs for runnable replicas. Petersen's corresponding figures are 87.2% and 83.0%, before including its two failed replica attempts. These differences demonstrate the metric semantics, not paper quality.

Report separate counts for unavailable data, unresolved binding, attempted-but-omitted results, infrastructure failure, invalid output, and valid numerical disagreement. Show coverage over eligible requests, conditional accuracy over validated outputs, and end-to-end success over planned attempts. Aggregate at paper/analysis level as well as claim level; numerous correlated means, SDs, p-values, and repeated results should not dominate comparisons between models. Distinguish exact reported-precision reproduction from the much broader A+B tolerance.

The default evaluator currently selects eight run directories, including original and v2 versions of three papers. The cost-table script separately hardcodes the five original IDs. Use one explicit evaluation manifest for all metrics, costs, and prose, with run versions, model lineups, retry accounting, and exclusions fixed. Keep a development corpus and a held-out validation corpus; repeated improvements against the same five papers measure development progress, not generalisation.

Required regressions: omitting a difficult result cannot improve end-to-end success; duplicating claim rows cannot dominate a paper-level score; adding an archive directory cannot change the evaluation cohort; all writeup builders consume the same manifest.

**7. Multiverse summaries depend on arbitrary representation choices. Must settle before reporting robustness metrics.**

The grid treats implementation variants as equally weighted specifications even when they encode the same analysis. The screen recommends merging equivalent branches, but those recommendations are not applied. The current 63-, 8-, and 9-row curves contain 15, 2, and 1 distinct estimates respectively. Identical estimates do not by themselves imply duplicate analyses, because inference may differ, but known algebraic equivalences should not receive extra weight through extra labels.

The current extremeness function assigns zero both to an estimate beyond the entire curve and to an estimate tied with every specification. Petersen provides the all-tied case. The same-sign share is also mechanically one for valid F statistics, regardless of the direction of the substantive effect. These are defects in the meaning of the summary, not failures of arithmetic.

Define the target of each summary: distinct analytical specifications, inference variants, or implementation checks. Merge known analytical equivalents before weighting; keep genuinely different procedures even when they happen to yield the same estimate. Label all-tied/degenerate curves explicitly, show tie mass or rank intervals, and omit direction metrics for unsigned statistics. Keep differing effect-size estimators explicitly named and comparable. When the grid is sampled, report descriptive summaries of the executed sample unless a justified weighting scheme supports a wider claim.

Required regressions: adding an equivalent implementation does not change substantive ranking; all-tied and outside-range cases have different summaries; unsigned test statistics do not generate evidence of directional stability.

**8. Intake and blinding need calibrated validation, beyond non-empty output checks. Before claiming pipeline validity.**

Readiness can bind one wrong analysis and still pass the zero-binding guard. Partial extraction omissions also pass the empty-extractor guard. An independent second call can expose disagreement, but taking the union of bindings would also admit unsupported bindings. Validate bindings against executable column, coding, sample, and transformation checks; preserve ambiguity where these checks cannot distinguish alternatives.

The current leakage audits rate Hertel and Ohtsubo `strong` and Petersen `weak`, despite clean deterministic value scans. Some audit findings concern analyses withheld from replicas, so those ratings alone do not establish leakage into the actual focal task. Conversely, a clean number scan cannot establish absence of directional or structural cues. Audit the final packet actually delivered, distinguish numerical leakage from structural cues, and state what the experiment measures. Recorded transcript hits also need context: the Petersen GLM log includes ordinary `out/../data` paths, illustrating why substring hits are not a verdict.

Use a small independently annotated intake set covering multi-study papers, derived variables, reversed items, ambiguous exclusions, repeated numeric values, and partial data deposits. Score extraction coverage and binding precision/recall separately from downstream reproduction. Add matched packet variants to measure sensitivity to structural cues. If claiming enforced isolation, validate the agents' actual permitted access rather than relying only on working-directory placement and transcript scans.

**Implementation order and current-run handling.** First specify the evidence and statistical contracts and replace the acceptance tests that encode the problematic policies. Then implement fresh-output verification, enforce structured screen decisions, and repair cache invalidation. Finally, define the evaluation manifest and metrics. Use the existing v2 outputs as regression fixtures and regenerate only affected stages once the dependency rules are trustworthy. New intake or packet content requires new blind replicas; a scoring or rendering correction alone does not. Run held-out cases only after freezing these choices. More model spend before these changes would produce additional examples without resolving the known failure modes.

Validation performed: reviewed source at commit `8f04de8`, stage artifacts from all three v2 runs, generated multiverse scripts, and evaluation builders; ran the existing offline suite (228 passed, 14 skipped, 1 deselected); independently recalculated the Ohtsubo sample-size example and exclusion sensitivity; reproduced the no-op executor acceptance in a temporary directory. No pipeline implementation or existing run artifacts were changed, and no model-service calls were launched. Broader statistical correctness of every generated analysis remains unverified.

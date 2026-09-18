# Clean analysis and reporting: implementation and validation specification

The pipeline must turn a paper and its deposit into an auditable account of what was extracted, what could be recomputed, what differs and why, and which defensible analytical choices change the conclusion. Both validation papers must use the ordinary prompt-driven pipeline. A registered hand-coded multiverse cannot establish that the general generator works.

## Stage contracts and acceptance

| Stage | Root cause to address | Reusable change | Validation evidence |
|---|---|---|---|
| Input | Text-only execution and CSV-only readouts silently narrow supported deposits | Lossless tabular intake with original hashes, sheet/header mapping, and label metadata; no analyst recoding | Fresh runs from original PDFs/deposits, conversion receipts |
| Extraction | Agreement is confused with correctness; repeated source occurrences and unassigned quantities disappear from summaries | Retain source occurrence identities, page/region coverage, literal and semantic checks; account for every reported empirical number | Source-first benchmark independent of run outputs; precision/recall and unresolved cases separately |
| Analysis binding | Ambiguous columns, sample rules, and unrelated quantities can be grouped together | Require source-grounded identities and explicit bindings; implement only documented or declared choices | Exact assignment coverage and executed sample/method checks |
| Reproduction | A runnable generated script can still implement the wrong analysis | Blind source-only generation, fresh isolated rerun, independent reference checks, bounded repairs fed verification failures rather than paper values | Every attempted analysis has execution, method, comparison, and availability status |
| Diagnosis | A mismatch is mistaken for an author error, and only headline discrepancies get attention | Diagnose all divergence groups with exact affected IDs, competing causes, evidence and next check | Complete diagnosis coverage; unresolved causes remain explicit |
| Statistical review | The prompt asks for author coding errors without author code | Ask about demonstrated statistical analysis and interpretation errors; identify whose code was inspected | Source anchors and demonstrations; no unsupported causal or preference critiques |
| Multiverse | Fixed paired engine bypasses generation; strict functional grouping fragments effects; results are not usefully summarised | Ordinary enumeration, independent screen, executable scope metadata, common-scale effect groups, separate null groups, deterministic summaries | Generated decision space, exact executed grid, valid uncertainty, no LOO/seed inflation; >4 meaningful dimensions where defensible |
| Report | Internal validation dominates, huge raw tables obscure findings, and missing evidence looks like failure | Findings-first report with coverage, diagnosed issues, statistical review, grouped effect curves and inference tables; technical audit appendix | Numeric-to-artifact checks, functional filtering/navigation, desktop/mobile visual checks |
| Completion | A stage marker or old receipt is interpreted as full success | Per-stage receipts and one cross-paper validation summary; preserve failed attempts | Fresh and warm runs, failure reasons, source benchmark limits, actual API totals |

## Report design

Audience: a researcher deciding which findings can be trusted computationally and what needs checking next. First screen: paper title, concise findings, and a coverage-to-reproduction overview. Then navigable sections for reported quantities, discrepancies, statistical review, and analytical sensitivity. Every issue links to its evidence. Full logs, prompt hashes, model costs, and blinding details belong in an audit appendix.

Use left-aligned prose, a wrapping section navigation, a 1,120-pixel content width, 17-pixel body text and horizontally scrollable evidence tables. White, navy and pale blue distinguish source evidence from findings, with amber for qualified results. Quotes use Georgia; prose and controls use a system sans-serif. Responsive plots keep axis labels readable on mobile and expose each selected specification’s choices and numerical verification. Evidence states always have words alongside colour.

## Validation protocol

Use new run IDs and input-only copies; never copy stage outputs or frozen benchmark answers into generation. Petersen is the regression case. Hurst et al. (2017) is the second executable case, a correlation study with named deposited totals. Ohtsubo et al. (2014), an independent-groups design in a multi-sheet workbook with embedded annotation rows, is retained as an availability test. These are development validations, not held-out accuracy claims because this corpus has previously been inspected. Freeze each source-first evaluation before comparing pipeline output. Use the same configuration and prompts for both papers. Any failure must lead to a generic implementation/prompt fix or an explicit data/support limitation, never hand-written paper results. Report both final outcomes and repair history.

Subscription routes are authorised. OpenRouter incremental spending for this task is capped at US$3; prefer subscription calls and track the actual ledger. The validated next report version is authorised for publication on surge.sh. Public exports omit local artifact downloads and deposited data. No repository push is included.

Implementation decisions follow the [multiverse literature review](../research/multiverse_scope_literature_review_2026-09-14.md). The specification is the acceptance target, not a declaration that these checks already pass.

## Current implementation decisions

Effect and null-group identities come from the independent screen and are enforced per specification. The primary curve accepts effect-scale quantities only; reported test statistics are never ranked on that curve. Summaries are deterministic and grouped, including matched changes in p-values and interval widths. Computational limits sample executions while preserving screened dimensions.

Source validation recognises subscript degrees of freedom, statistic labels continued across lines, plural F-statistic notation, and compound number words. Degrees of freedom are projected from their parent test into separately auditable metadata fields. The source benchmark can match these fields without requiring artificial extra analyses. Both versions of the second paper’s source inventory are retained.

Readiness separates source-determined bindings from explicitly declared conventional reconstructions. Condition matching has a registered reconstruction convention, with a located per-condition scope quote, one-to-one shared column indices, and no reference/baseline/pooled scope. The likelihood adapter separately registers independent-subject summation with explicit parameter counts, assumptions and nesting checks. Reports count conventional agreement separately. Missing studies and invalid deposited inputs remain scoped limitations.

Independent reference adapters cover direct paired, independent and one-sample t tests, correlations, named families, declared likelihood-ratio calculations, and a closed location-sensitivity protocol for trimming, transformation and outlier rules. Unsupported uncertainty methods are disclosed and block run acceptance; they cannot inherit verified status from a matching point estimate.

The report shows failed stage status and still renders available findings. Unsupported statistical-review findings are quarantined after a bounded citation repair. Tool-free generated multiverse scripts receive bounded execution and verification feedback; no reported target values enter that repair loop.

Fable reached its subscription quota during validation. The current run configurations use Sonnet and Opus, with Codex for independent unblinded reviews. Failed attempts and original configurations are preserved in each run’s validation_attempts folder. This is a backend substitution, not metered spending; all new API ledger charges remain zero as of the configuration change.

An additional Hurst et al. (2017) case tests a correlation with explicitly labelled deposited total scores. Ohtsubo’s first readiness reading found unresolved instrument/sample correspondence; its independent second reading determines whether it can serve as an executable case or an availability limitation. The extra case ensures that a correctly blocked deposit cannot masquerade as successful second-paper analysis validation.

### Adjusted models, quantity identity and deposited codebooks

Excel codebooks must be parsed sheet by sheet into labelled text. Binary bytes must never enter a model prompt. The same text representation is supplied to readiness and blind reproduction, with the source filename retained. Wide readiness requests preserve every column and contract while removing JSON formatting overhead and explicitly selecting the large-context route.

Blinding preserves operation identity: standardized beta, unstandardized b, confidence-interval endpoints and R² remain distinct even when the extraction schema groups them under a common quantity kind. Only closed semantic labels derived from the validated source description cross the boundary. Reported values and result-bearing prose do not. Inferential quantities classified as `other` remain with their model rather than being routed to the descriptive calculator.

The independent adjusted-model adapter supports directly bound partial Pearson correlations and classical OLS with an intercept. It checks the full covariate/predictor set, source-bound data table and authorised sample before recalculation. Partial-correlation tests use the adjusted residual degrees of freedom. Weighted, robust, categorical recoding and transformed fits require a suitable independently bound adapter. A missing adapter is an explicit limitation and blocks complete-run acceptance. The separate numerical implementation is checked against statsmodels on simulated data, including a confounding example in which the marginal and adjusted associations have opposite signs. [Partial-correlation inference](https://pmc.ncbi.nlm.nih.gov/articles/PMC4681537/) and [OLS result definitions](https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.OLSResults.html) specify the reference methods.

Descriptive readouts include observed extrema and raw Cronbach alpha. Reliability requires exact item membership and source-documented keying, jointly complete observations, and an independently implemented R covariance calculation. Unknown subscale membership is unresolved, not evidence that the deposit lacks data. Reversals cannot be chosen from observed correlations or reported reliability.

Private data perturbations return per-analysis verification results. A failed analysis must not erase passing checks for unrelated analyses. A stale realised-sample trace is a generation error: bounded repair receives the failed method/sample checks, never the paper's target values. Unsupported reference methods require a generic verifier extension or an explicit blocked run; they do not trigger an impossible source-repair loop.

### Multiverse screening and implementation namespaces

Retrospective sensitivity choices do not need to have been preregistered to be defensible. A conventional, fixed SD/IQR/MAD exclusion rule can be evaluated alongside robust estimators when its substantive and statistical rationale is clear. Selection of thresholds to obtain a desired answer remains prohibited. Choices and screening reasons are fixed before executing their results.

Paired marginal trimmed-means comparisons and trimmed means of within-pair differences are different valid estimators. The former uses winsorized covariance, as in [WRS2's paired Yuen procedure](https://r-forge.r-universe.dev/WRS2/doc/manual.html#yuend). A verifier for the latter must not rewrite the former or declare it invalid. Exact estimator labels and appropriate uncertainty remain mandatory even when both share a substantive raw-effect group.

A level's `reference_settings` constrains point estimation and null-test implementation; `ci_reference_settings` constrains interval construction. Combined interval controls occupy `ci_settings` in the execution plan. Distinct algorithms, draws and seeds for a CI and a test are compatible. Conflicts inside either namespace still block execution. Each factor constrains only its own choice rather than repeating unrelated defaults.

Large readiness repairs are partitioned by required binding fields, with exact requested analysis and field coverage checked before any patch is applied. Shared prose mappings cannot replace executable bindings. A dataset-wide unique-ID check may be associated deterministically with source-bound analyses using that same file and table; other analyses are unaffected.

### Blinding and descriptive method identity

Observed sample sizes, excluded counts, group counts, demographics and other empirical summaries are withheld from the replica. The original source contracts retain them for comparison; the delivered contracts contain operational selection rules. Realised sample counts must be computed. Fixed method parameters remain available. A reported number colliding with the generic task's confidence level is exempted only by exact template provenance, with that collision recorded.

Redaction caches are keyed to the scrub prompt, model, schema and route protocol. Identical source fragments are deduplicated within a request; successful chunks are cached individually. Both whole-methods text and contract prose are scrubbed, and a result-leak audit covers the exact delivered packet. Prompt changes invalidate the audit receipt.

Arithmetic verification does not establish correct quantity binding. Percentage operations require an explicit numerator and eligible denominator, or a documented proportion. A scaled row count is rejected. Category codes, skip logic and already-reversed items cannot be inferred from observed distributions or numerical agreement. Coding-sensitive percentages and reliability mappings receive an independent source-method review before computation. Missing documented response labels or item keys are recorded as unavailable metadata; conflicts between actual documented mappings remain unresolved. Both outcomes retain the precise missing input or conflicting evidence.

Coding-sensitive readouts require an independent documentation audit with source-anchored quotes. A reviewer's inference from follow-up response patterns is not an executable coding reconstruction and cannot establish a missing key. Count and percentage versions of the same categorical event share the coding audit; their units and denominators remain distinct. Unanchored claims of source support stay unresolved.

CSV contracts accept finite exact integer representations such as `10000.0` for simulation counts and focal indices, while rejecting fractions, non-finite values and truncation. Paired execution plans explicitly use x minus y; estimates, test statistics and intervals must share that order. Schema feedback validates the declared analysis family first, keeping unrelated union-branch errors out of bounded model repair prompts.

Unassigned inferential quantities receive an independent source-only review of their analysis definition. Missing measure identity is distinct from a pipeline that has not attempted computation. A confirmed missing definition remains in the source denominator as unavailable method information, with the missing field, candidate analyses and source quote recorded. A recoverable identity remains an unresolved pipeline duty until assignment is repaired. Source-to-source restatement links may use printed signatures only after non-numeric fields nominate a closed candidate set; reproduced values never enter this decision. Numeric coincidence alone cannot identify an analysis.

Term mappings can be scoped to explicit claim IDs. Disjoint source occurrences may give the same phrase different meanings; overlapping mappings cannot name different destinations. Correlation identities accept exchanged outcome/predictor order while preserving the measured pair, conditioning variables and model. The report exposes source-specific mappings beside each affected quantity's source evidence.

Large initial readiness jobs are divided into groups of at most 40 required binding fields. They use the same strict per-analysis validation and repair path as smaller jobs. File-format metadata comes from the deposit parser; scientific sample and variable identities come from the source-reading batches. Claim IDs are excluded from readiness prompts because adding a printed quantity does not change the analysis's data binding.

Readiness statuses are a closed schema: `complete` or `abstained`. Intact legacy `ready`/`bound` responses are normalised without changing their source bindings or model-call provenance, and all ordinary validation still runs. Unknown statuses fail validation rather than silently removing analyses.

The legacy location-sensitivity adapter distinguishes eligible starting IDs from the retained sample. The closed multiverse protocol independently derives both samples from the source recipe; its executor plan reports realised retained `included_ids`, which must match that independent selection. Private perturbation checks run inside bounded generation so data-dependent implementation errors receive automatic method-only repair feedback. Final independent execution repeats the check. Incomplete numerical coverage blocks acceptance.

Integrity checks run on the validated analysis sample, including its source-defined filters and starting IDs. Missingness in excluded deposited rows cannot invalidate a selected complete-pair analysis. Receipts retain the full deposit size, selected size and original row positions so the sample boundary remains auditable.

The coding-evidence auditor receives authoritative parsed category labels and validated intake sample contracts, independently of proposed bindings. Self-describing textual responses do not require an invented numeric key; opaque numeric responses still require documented semantics. A frozen three-case controlled regression checks self-labelled text, unlabelled numeric codes and documented numeric codes with the production auditor. All three dispositions passed; this small regression is not a paper-level accuracy estimate.

The subscription validation profile sets `multiverse_min_active_dimensions = 5`. The controller counts levels in compatible executed specifications, excluding pinned factors and reference-only rows. If screening leaves fewer dimensions than requested, at most two source-only refinement rounds can add new decisions before independent re-screening. Existing proposals and rejected alternatives are retained. No new factor is a valid response; an unmet target produces an explicit abstention, never an inflated count. Refinement does not read multiverse outcomes. Targets and counts are audit metadata, separate from the executor’s scientific grid.

Multiplicity verification checks the focal calculation and every source-bound nonfocal family member. A fixed source per-test criterion instead uses a distinct threshold-equivalent rescaling, without inventing p-values or inferring an undocumented family size. Unverified family membership blocks complete-run acceptance.

### Source repair and bounded service fallback

An existing executor receives at most three exact source-patch attempts per configured repair backend. All edits must match uniquely and validate before any file is changed. Source snapshots, call IDs, verifier feedback and isolated execution receipts remain in the run. Repairs see approved inputs and generated source; paper targets and computed result tables are withheld. A quota failure before any source exists can use the same bounded path to generate a source bundle. Every repaired program must pass the ordinary output contract, fresh execution, independent method checks, private perturbation checks and hardcoding audit.

An optional metered backend requires an explicitly authorised shared budget file. It reserves a conservative UTF-8 input bound and capped output charge before each tool-free request, across all case IDs. Actual usage settles the reservation; unknown or interrupted charges retain their full reservation. The two-paper validation authorisation is US$3 total. The report records actual model calls and charges, including repairs. Unblinded multiverse interpretation uses the configured review backend and includes that backend in its cache dependencies.


Private multiverse perturbation uses whole-record resampling with stable destination identifiers. It preserves deterministic relations between raw items and deposited totals, categorical coding and within-record missingness. It still changes the empirical distribution, and a hardcoded-output integration regression must fail. The original outcome-noise perturbator remains available for the separate reproduction checks; multiverse generation and final verification use the record-preserving protocol.

## Complete verification and reader evidence

Multiverse acceptance requires verified per-specification numerical evidence on both original and private record-resampled inputs. Partial checks are blockers. Source-only, separately reviewed closed recipes define expected methods without consulting the executor's code, plans or results. The implementation checks retained identities and all emitted numerical components; unknown method combinations fail closed. The versioned computational protocol fixes random-stream and draw-order conventions without counting them as analytical dimensions. Fixed source significance criteria use a separate threshold contract; Holm requires independently computed nonfocal test bindings and p-values.

Reports expose observed/reference values and tolerances for each specification, alongside its analytical choices. Source quantities link to reported values, independent recalculations, comparison rules, data-column/method information and source quotations. A cached editorial pass groups every diagnosis exactly once into readable substantive topics; it cannot alter numerical evidence or evidence status. Model labels are separate from the raw method record. Any mismatch between the current execution fingerprint and report aggregation suppresses the curve until Stage 3 completes. The [validation and methods record](validation/2026-09-15/VERIFICATION_REPORTING.md) documents the numerical anchors and deliberate-error checks.

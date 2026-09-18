# Complete multiverse verification and readable evidence

Complete multiverse verification is now an acceptance requirement. Every specification must have independently checked estimates, participant selection, emitted standard errors, intervals, raw p-values and multiplicity calculations, on original and private record-resampled inputs. The revised reports expose these comparisons beside readable findings and source evidence. Petersen has 12 fully verified specifications and Hurst has 36, each spanning five active analytical dimensions. Both original and private-input checks cover every specification.

## Acceptance and independence

A run cannot pass with partial reference or perturbation verification. Its acceptance receipt requires a verified evidence record for every executed specification on both input sets. Unknown method combinations and invalid recipe settings fail closed.

The ordinary pipeline translates screened methods and the blind contract into a closed declarative recipe. The translator receives column names but no participant observations, reported targets, executor code, executor plans or computed outputs. A separate tool-free subscription model reviews the recipe against those same source inputs. New generation freezes the recipe before execution; existing generated code can be migrated by source repair and full re-verification. The reference computes from deposited records itself and compares the executor's claimed sample identities, rather than adopting them.

The numerical library covers the methods used by these cases: paired means, separately trimmed paired-Yuen means, trimmed paired differences, log-scale paired effects, signed-rank effects, partial and semi-partial Pearson/rank associations, polynomial and natural-cubic-spline nuisance terms, explicit item-score reconstruction, difference-IQR and Mahalanobis exclusions, matched analytic tests, sign flips, Freedman–Lane permutations, Fisher intervals, paired-Yuen intervals, BCa and participant bootstrap intervals. These checks establish computational conformance; source and substantive assumptions remain separately qualified.

## Defects and resolution

| Pipeline problem | Implemented requirement |
|---|---|
| A partially checked run could pass | Complete numerical and resampled-input evidence is an acceptance gate. A passing point estimate cannot confer a passing interval or p-value. |
| Analytical factor names could overwrite numerical result fields | Factor levels have a separate internal namespace; colliding CSV names use `factor_<name>`. A `ci_method` factor cannot replace the actual interval algorithm. |
| Generation repair used a legacy checker while final verification used the new protocol | Both phases bind the same independent recipes and perturb data using those bindings. A regression checks the shared path. |
| Generated scripts resolved input files relative to their output directory | The Stage 3 protocol identifies the workspace input root and the separate output directory explicitly. |
| Conflicting instructions described starting versus retained IDs and obsolete adapter limits | The shared executor prompt now requires realised retained IDs, exact interval labels and the current complete-verification contract. |
| Executor plans defined which methods could be checked | Source-only recipes independently define the expected transformations, sample, nuisance design, estimator, test, interval and adjustment. |
| Seed did not identify the random stream | A versioned protocol specifies PCG64, draw ordering, participant indices, permutations and sign vectors. Counts and seeded results are checked exactly, within floating-point error for continuous outputs. |
| Fixed Bonferroni threshold represented by 25 copied focal p-values | A distinct fixed-threshold contract records the source criterion and its threshold-equivalent rescaling. It neither invents uncomputed p-values nor claims that the original family size is recovered. |
| Holm nonfocal tests were unverified | Nonfocal source bindings and their independently computed p-values are checked alongside the focal adjustment. |
| Report verification counts included unchecked components | Counts now refer to fully checked specifications; the interactive evidence table shows each observed and independent value. |
| Report generation confused claim/analysis IDs with complete divergence IDs | The writer receives distinct evidence aliases, a complete required-ID list, compact source evidence without archive metadata, and exact missing/duplicate-link feedback. Aliases resolve back to canonical diagnosis IDs before acceptance; missing, duplicate and unknown links are rejected. |
| Diagnoses lacked readable numerical evidence | Each substantive issue includes affected paper values, recalculations, evidence status, cause and the next resolving check. Every diagnosis group is assigned to exactly one reader topic. |
| Long internal labels and static curves obscured methods | Reader labels preserve estimator, unit and null distinctions. Responsive curves support point selection, a method inspector and component-level verification tables. |
| Numerical evidence overflowed the interpretation prompt | Interpretation receives compact verification summaries. Detailed numerical evidence remains in the report and execution archive. |

Different random streams can produce valid but different Monte Carlo outputs. The generator migration makes the computational convention explicit; it is not evidence that the previous stream was statistically invalid. Exact seeded agreement does not eliminate Monte Carlo uncertainty or validate exchangeability assumptions.

## Independent checks of the verifier

A frozen synthetic dataset is checked against R `WRS2::yuend`, `ppcor::pcor.test` and `ppcor::spcor.test`. The paired-Yuen estimate, standard error, degrees of freedom, p-value and interval agree to floating-point precision. Full and semi-partial coefficients agree with the R implementations. The fixtures retain the input values, numerical anchors and provenance.

Deliberately wrong alternatives must be rejected: semi-partial substituted for full partial correlation, a changed polynomial nuisance specification, percentile substituted for BCa, unconditional permutation substituted for Freedman–Lane, wrong sample counts/identities, fabricated fixed-threshold families and unknown/conflicting recipe fields. A separate check confirms that batched bootstrap calculations re-rank and refit within each resample.

Primary implementation references: [WRS2 paired-Yuen source](https://github.com/cran/WRS2/blob/master/R/yuend.R), [SciPy bootstrap definitions](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html), and [partial/semi-partial correlation methods](https://pmc.ncbi.nlm.nih.gov/articles/PMC4681537/).

## Consultation and spending

Fable remained quota-blocked. Claude Opus recommended source-grounded recipe freezing, sample-identity checks, explicit stochastic conventions, mutation tests, honest multiplicity evidence and fail-closed acceptance. Its advice informed the implementation; the advice to infer a family size from a rounded source threshold was not adopted. The pipeline uses the declared source criterion without claiming a recovered family size.

This continuation used subscriptions only. The preceding OpenRouter allowance remains US$1.889323, comprising US$0.707303 confirmed and US$1.182020 reserved for an interrupted request with unknown charge, under the authorised US$3 cap.

The signed-rank method has an additional R exact-distribution anchor at 28 observations. The executor's legacy exact-test cutoff of 25 is not accepted: the screened method uses exact inference where supported by the observed tie/zero structure. Recipes distinguish explicitly screened exact/no-ties inference from [SciPy automatic method selection](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.wilcoxon.html); the final Petersen grid uses the former. Probability comparisons use a relative tolerance rather than a large absolute floor, so a tiny nonzero p-value cannot silently become zero. Deposited-total scoring does not require complete raw items unless the selected reconstruction actually uses them.

The trimmed-difference reference also matches an independent R winsorised-variance calculation. An active-scale test ensures log transformation precedes difference-based outlier exclusion. Newly generated decision spaces can use either marginal paired-Yuen or trimmed paired differences; neither is silently substituted for the other.

The three-knot natural-cubic nuisance implementation is checked against R `splines::ns` with an interior median knot and boundary knots at the 10th and 90th percentiles. The synthetic partial coefficient is 0.36973805688575184 (two-sided p=0.020522281712256514). An additional bootstrap test holds source-selected knots fixed and reranks only the specified variables. The [R spline documentation](https://stat.ethz.ch/R-manual/R-devel/library/splines/html/ns.html) defines the natural boundary conditions; the reference uses a separate truncated-power basis spanning the same space.

Private perturbation respects declared test domains. A screened exact signed-rank method requiring nonzero untied differences receives an 80% whole-record subset without replacement, preserving original IDs and avoiding artificial duplicated differences. Other methods retain whole-record bootstrap perturbation. This is a private implementation test, not a multiverse option. The exact signed-rank recipe rejects out-of-domain original data. Freedman–Lane recipes separately declare whether the outcome or predictor residuals are permuted; a mutation test rejects the wrong choice even when the point partial coefficient is symmetric.

The independent R anchors can be regenerated with [reference.R](../../../tests/fixtures/multiverse_verification/reference.R); [recorded output](r-reference-anchors.txt) includes paired Yuen, trimmed differences, full/semi-partial correlations, natural splines and the exact signed-rank case.

## Integration and regression evidence

| Check | Petersen | Hurst |
|---|---|---|
| Frozen development extraction inventory | 135/136 clean occurrences; 100% precision | 258/258 clean occurrences; 98.47% precision |
| Computation dispositions | 124 computed; 9 unavailable; 2 invalid inputs; none unresolved | 158 computed; 104 unavailable; none unresolved |
| Independent original-analysis replicas | 28/28 each; 44 descriptive readouts | 65/65 each; 40 descriptive readouts |
| Divergence diagnosis coverage | 22/22 groups | 124/124 groups |
| Ordinary multiverse | 12 specifications, 5 active dimensions | 36 specifications, 5 active dimensions |
| Full numerical checks | 12/12 original and 12/12 private-input specifications | 36/36 original and 36/36 private-input specifications |

The [offline suite](offline-tests.log) passes 609 tests, with 14 skipped and one slow test deselected. A subsequent focused reporting run passes 24 tests, including a new regression for distinct diagnosis links, metadata removal and rejection of missing, duplicated or unknown links. Run tests without the live subscription profile override: `env -u REPROSCOPE_MODELS -u REPROSCOPE_REVIEW_BACKEND uv run pytest -q`. Config tests deliberately exercise their fixture profiles; exporting the integration profile into that suite changes what they test.

The primary Petersen raw-effect curve contains seven compatible specifications, with processing-speed differences from 22.6650 to 25.7942 letters per second. Three proportional-scale and two signed-rank specifications have separate effect groups. Hurst separates 24 Pearson partial correlations from 12 rank partial correlations. These are compatible decision grids, not independent observations or votes. Private record perturbations never enter either curve.

Both final acceptance receipts pass without blockers: [Petersen](petersen-acceptance.json) and [Hurst](hurst-acceptance.json). Hurst retains the disclosed structural blinding limitation; neither run has incomplete numerical verification.

[Functional browser checks](functional-qa.json) confirm source quotes for all 135 Petersen and 262 Hurst quantities, searchable evidence, working specification selection and complete numerical evidence for all 12 and 36 specifications. [Responsive checks](responsive-qa.json) show no page overflow at 390 and 1440 pixels. Expanded method/evidence panels were inspected visually.

Published reports: [Petersen](https://reproscope-petersen-2017-v7.surge.sh/) and [Hurst](https://reproscope-hurst-2017-v1.surge.sh/). The existing review slugs retain their shared comments. Deployment logs and HTTP/content verification receipts are stored in this directory. Public exports contain source quotes and aggregate results, without participant records or local file paths.

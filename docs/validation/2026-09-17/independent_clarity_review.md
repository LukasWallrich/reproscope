# Independent report clarity review

The reports now expose much more useful evidence, but the multiverse narrative needs a stronger connection to its numerical results. The most urgent fixes are to remove contradictory Hurst prose, show the reported estimate on the appropriate curve, and give each finding one primary home. These are shared reporting and validation issues.

Reviewed the current local Petersen and Hurst `report/report.html` files and shared renderer on 17 September 2026. This review was conducted independently of the Fable review. It applies the academic style guide's requirement that every sentence summarising a table or figure agree with that table or figure. It is a content and interaction-design review, not a new assessment of either paper, and does not claim browser screenshot validation.

## 1. Block publication when narrative and numerical summaries disagree

**Priority: blocker.** Hurst's multiverse prose says, “The deterministic matched-comparison audit identified CI method as the only matched active dimension, affecting estimates, (p)-values, and interval widths”. Its current table says the opposite: CI-method changes leave estimates and p-values unchanged, while the test, age-adjustment, and missing-item dimensions also have matched comparisons. The prose further says there were no rank-group matched-change comparisons; the displayed rank table contains test, age, and missing-item comparisons.

This is more serious than verbose wording: the reader receives incompatible accounts of what the analysis found. The likely reporting boundary to inspect is the cached Stage 3 interpretation versus the final deterministic sensitivity summaries. The review does not establish the precise cache cause.

Hurst also describes the correlation's sign using “(x-y) order (DSM-5 minus Mini-K)”. A correlation is not a subtraction contrast. Replace this with “Higher DSM-5 symptom scores were associated with lower Mini-K scores after age adjustment.” Correlation orientation must not inherit the paired-difference explanation.

**Implementation:** generate the core range, matched-change, interval-availability, and coverage sentences deterministically from the current summaries. If a model supplies interpretation, give it those same summaries and validate every quantitative or categorical assertion against them. Cache interpretation on the actual final summary artifact, not just a previous generation stage.

**Acceptance checks:** Hurst explicitly reports zero estimate and p-value change from CI choice; acknowledges all four matched Pearson decisions and all three matched rank decisions; no correlation explanation uses subtraction. A fixture with an unchanged grid but changed matched-summary artifact invalidates old interpretation.

## 2. Show the reported estimate where comparison is valid

**Priority: high.** Hurst reports a focal partial correlation of −.51 and shows a raw-score partial-r multiverse spanning roughly −.517 to −.448, but neither the graph nor its adjacent summary shows where −.51 lies. Readers must mentally connect distant sections.

**Implementation:** give each effect group a typed reference object: reported value, source claim/page, unit, orientation, comparison basis, and any rounding range. In the compatible Hurst Pearson panel, draw a labelled horizontal reference line at −.51. Place a short statement next to the graph giving counts of specifications below, equal to, and above the reported value; distinguish numerical ordering from substantive effect strength for negative associations. Show the matching reconstructed baseline as a separate, named point or highlight if its analytical choices can be identified. A reported rounded number and a reconstructed baseline are different objects.

Petersen's prominent reported focal value is d = .89, whereas its primary multiverse reports raw letters-per-second differences. Do not plot .89 on that curve or silently convert it. Say directly beside that panel, “The paper reports a standardised effect; this curve shows differences in letters per second, so no reported-value reference is shown.” If an independently sourced raw difference exists or is derived from reported means, label it with that provenance and derivation. Do not put the Hurst Pearson reference on its rank-effect curve.

**Acceptance checks:** same-scale matching uses analysis identity, coefficient/estimand, outcome, covariate scope, units, and direction rather than matching a symbol alone. No reference is shown on incompatible groups. Tie handling and reported rounding are documented. Positional counts use the displayed group's specifications only and are described as a location in this chosen grid, not a probability or evidence vote.

## 3. Use a linked two-panel specification curve

**Priority: high.** The current upper estimate/CI plot is useful, but the user cannot see which analytical choices produced a run of estimates without selecting individual points. The requested specr-style display solves this directly.

**Implementation:** retain separate effect groups and create, for each group, an upper sorted estimate/CI panel and a lower choice matrix with exactly the same specification order and x coordinates. Group level rows under human-readable dimension labels. Include inference-only dimensions so duplicate estimates with different intervals or tests remain intelligible. Mark the selected specification through both panels and update the existing numerical-evidence inspector. Keep fixed choices in a compact caption or distinguish them from varying dimensions. Use a stable tie-breaker for identical estimates.

Colour requires an explicit key. If colours express a significance decision, derive it from the declared test/threshold, not merely whether a plotted interval crosses zero: the interval and multiplicity-adjusted test may answer different questions. The reported reference and reconstructed baseline should have distinct symbols and labels. A horizontal scroll area is preferable to unreadably small level names on a phone; upper and lower panels must scroll together.

**Acceptance checks:** every matrix column maps to exactly one displayed estimate and inspector record; all level marks match that record's stored factor choices; sorting and selection remain synchronised after resize; keyboard users can select every specification; colour is not the only carrier of meaning; labels remain legible at mobile width. Single-specification effect groups should use a compact estimate/interval card rather than a full mostly empty curve and empty change table.

## 4. Give each issue one primary explanation and reuse links elsewhere

**Priority: high.** Repetition occurs at several levels. Petersen's two likelihood-ratio gaps are fully described under discrepancies, restated in detailed diagnoses, then described again under statistical checks, with repeated numerical demonstrations and next checks. Hurst's unavailable item keys appear in the finding, cause, table reason, diagnosis explanation, and quotation. Several unavailable diagnoses repeat exactly the same paragraph twice consecutively because `explanation` and `evidence_quote` are identical.

**Implementation:** the discrepancy section owns the numerical comparison, source excerpt, established explanation, and unresolved next check. The statistical-review section adds only a new inferential judgement, linking to the existing discrepancy evidence. Do not render a quotation when it duplicates the explanation. Compress common unavailability causes into one cause statement with an expandable list of affected quantities. Keep complete coverage in the searchable source-number inventory rather than repeating every blocked quantity at full length in the main narrative. Use one multiverse coverage/verification sentence and one leave-one-out policy note rather than repeating these in generated prose and template text.

**Acceptance checks:** each diagnosis remains linked and recoverable, but identical explanatory paragraphs do not occur twice in the same card; statistical-review entries link to existing evidence instead of reproducing the whole comparison; the page opening identifies the focal result, material discrepancies, and multiverse conclusion before audit mechanics. Search and source-quantity deep links still work.

## 5. Replace internal evidence fragments with directly inspectable evidence

**Priority: high.** Some “Source evidence” panels show fragments such as `"reported": 21.52, "replicated": 665.3557919999995` and `Evidence: batch1:group:a22:numerical_mismatch`. These repeat the comparison table rather than showing a source or method. Hurst's statistical check for the half-sibling sign contradiction has “Supporting source: Half-siblings (covariate)”, which is insufficient on its own to verify the three-cell sign claim.

**Implementation:** use the paper quotation or table row with page and quantity links for source evidence. Put formula, data bindings, sample size, and relevant computed values in a separate calculation-evidence block. Keep internal IDs as unobtrusive provenance or links, not the visible explanation. A strong sign-consistency claim should display the relevant b, beta, and t values together with the sign identity; a likelihood-ratio claim should show its aggregation formula and the limitation on upstream fits. Avoid implying that agreement between implementations establishes the authors' original procedure.

**Acceptance checks:** every demonstrated contradiction exposes the full set of quantities needed to check it; every source citation resolves to a paper location or linked quantity record; no primary evidence label points only to internal JSON or a diagnosis ID. The existing per-specification observed/reference numerical table should remain available.

## 6. Remove screening and implementation history from reader copy

**Priority: medium.** The factor rationale section leaks instructions from discarded proposals. Petersen says “provided the incorrect claim that SciPy necessarily uses a normal approximation at n=28 is removed” and “after rewriting: the proposed level inconsistently names a percentile interval while specifying BCa”. These describe the pipeline's drafts, not the method that was executed. Other generic boilerplate discusses semi-partial effects and raw trimming in Hurst although neither is part of its displayed multiverse.

**Implementation:** separate the screening audit from final reader-facing method descriptions. The latter states the accepted method, why it is relevant, and its substantive limitations. Retain rejected options and screening history only in a clearly labelled audit appendix. Render caveats conditionally from the methods actually present. Hurst's missing-item alternative should continue to say “detectable filled cells”, not “complete original cases”.

**Acceptance checks:** reader-visible method descriptions contain no “after rewriting”, “proposed level”, or instructions to remove a claim; a group-specific caveat is shown only when relevant. Fixed source threshold wording never implies that the original family of tests has been independently reconstructed.

## 7. Make completion status and evidence status precise

**Priority: medium, blocker if deployed.** The current local Hurst HTML has the banner “Run incomplete. report did not pass.” while its overview also says 36 multiverse specifications verified. These statements can coexist technically, but the report does not explain what is incomplete or which results are usable. This review did not check whether the live Surge version has the same banner.

The overview phrase “0 remain unresolved” refers to computation duties, while numerous discrepancy diagnoses remain unresolved. Readers can easily mistake that for a claim that all causes are known. Also, one Hurst narrative says starter records “were never retained”, which is stronger than their absence from the supplied deposit establishes.

**Implementation:** name any failed stage/check and its consequence in the incomplete banner. Use “Every source quantity has a computation or an explicit reason it cannot be computed” for the duty-accounting status; reserve “unresolved” for causal diagnoses or qualify it. Say “not available in the supplied deposit” unless a source explicitly establishes permanent non-retention. Hide implementation/model labels behind neutral “Independent calculation 1/2” headings, retaining model provenance in verification details.

**Acceptance checks:** completed public reports have a current passing report receipt; deliberately incomplete fixtures identify the actual failing requirement. The opening cannot be read as claiming all discrepancies are explained when they are not. No unsupported retention-history statements remain.

## Suggested release check

Before the cheap-model Hurst rerun, validate the shared report contract against both existing papers: compatible reported-reference placement, sorted choice-matrix integrity, current narrative/table agreement, source evidence adequacy, repetition removal, and responsive interaction. Then run Hurst under the cheap-model profile as a fresh provenance-distinct run. Judge it on the same extraction, reproduction, numerical verification, and reporting criteria; do not relax the acceptance checks to make a cheaper profile pass.

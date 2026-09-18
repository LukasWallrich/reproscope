The full development run passes execution and artifact-freshness checks, but **does not pass semantic finalisation**. The [pipeline quality review and improvement plan](PIPELINE_IMPROVEMENT_PLAN_2026-09-13.md) identifies incorrect source targets, unresolved claims reaching grading, contradictory task instructions and unverified review evidence. Its 15 problem areas and acceptance tests define the required development work. Execution success does not validate the current reproduction scores.

Operational preflight has no blockers, and a warm resume adds no model calls while preserving all replica and executor outputs. These operational findings remain valid. The separate review attachment in `quality_review/semantic_acceptance_review.json` records the semantic blockers without changing the frozen run artifacts.

The live integration case uses run `Petersen_Cognition_2017_yJwG_v3_20260913`, with eight planned replicas and fresh intake from the PDF and three deposited CSV files. This is a development case used while correcting the pipeline. It cannot establish performance on unseen papers. The run-specific cohort preserves all eight attempts; the default three-paper v2 development cohort is unchanged.

## Controls exercised

- Intake produced 147 source claims and 29 analysis contracts. Structured analysis identities place both duplicate focal source records in a single paired-comparison contract. Three nonfocal analyses remain unbound because their required column pairing is unresolved. Other bindings retain data-integrity warnings; complete binding is not evidence of analytical validity.
- The numeric leak scan passed. The packet audit classifies blinding as limited because background/theory cues remain. The audit records the exact packet hash and covers every included analysis.
- All eight generated scripts regenerate their statistical outputs in fresh declared-input directories. The checker validates `(analysis_id, claim_id)` pairs against the actual packet and compares all statistical fields. It preserves shared descriptive/sample claims without collapsing distinct analysis outputs.
- Matching retains all 1,128 eligible claim-by-replica outcomes (141 claims × 8 attempts): 923 graded, 162 invalid, 41 omitted, and 2 unresolved links. Six unbound source claims are separately recorded at intake. These counts describe pipeline coverage, not paper validity.
- Seven replicas have accepted computation audits, with individual invalid claims excluded from grading. One is rejected for literal analysed sample sizes in statistical output fields. These decisions concern computation paths, not whether the analytical methods are correct. The rejected replica remains in the denominator.
- The targeted arm did not trigger. All four Stage 2 checks completed or explicitly abstained. The power adapter abstained because the focal contract did not establish the test direction unambiguously.
- Stage 3 screened six proposed factors into three executable specifications. Mandatory amendments pin the sample and transformation, merge equivalent contrast/model levels, and rewrite resampling procedures. Author settings remain unresolved; no replica was used as an author-method proxy.
- Seven explicit audit adjudications were required. Full-source reviews and exact script/results hashes are recorded in `audit_adjudications.json`; original automated findings are preserved. The acceptance count therefore does not describe an unattended run.

## Pipeline defects exposed by live inputs

| Failure mechanism | Implemented control |
| --- | --- |
| DOI/URL decimals triggered the empty-extraction heuristic on a references page | Remove identifiers before assessing numeric result density. |
| One failed extraction chunk discarded completed work | Atomic, dependency-checked chunk caches; assemble only after all chunks complete. |
| Large vision requests ended without usable content | Four-page chunks and immediate response logging. |
| Empty optional metadata lists invalidated otherwise usable extraction | Normalise only explicitly empty optional metadata. |
| Extractor display labels became analysis identities | Structured study/outcome/contrast/model/sample identity; deterministic assignment validation and a bounded repair step. |
| Numeric strings with whitespace missing values were treated as unusable columns | Full-column finite parsing profiles and explicit numeric/missing-value policies. |
| Model-edited repair identifiers silently prevented redaction | Opaque identifiers with exact coverage and uniqueness validation. |
| New nested contract prose escaped redaction | Scrub nested evidence and display fields; retain canonical identity upstream. |
| Downstream edits invalidated expensive upstream work | Step-specific cache dependencies and separately recorded verification provenance. |
| Shared claim IDs failed fresh result validation | Composite analysis/claim keys and consistent aggregation of repeated claims. Unsupported vectors remain ungraded. |
| Audit scans confused diagnostic text with numerical computation and truncated long source files | Full-source auditing plus explicit, evidence-backed adjudication and per-claim exclusions. |
| A review could refer to a script still being revised | Compare review-input hashes to final collected artifacts; discard mismatched reviews. |
| Provider errors repeated across calls, and timeout usage disappeared | Short failure cooldown, transport-error retries, and retained partial usage. |
| Optional null reference constraints erased concrete settings | Ignore null constraints; reject conflicting concrete values. |
| A verifier exception lost the completed executor generation receipt | Checkpoint generation before verification; resume verification against the same artifacts. |
| Completed failed attempts could be regenerated on resume | Cache the negative outcome unless generation is explicitly forced. |

## End-to-end checks

All three Stage 3 rows cover the exact screened grid, converge, and regenerate every recorded statistical field in a fresh directory. The source audit is clean. Independent calculations agree on all three estimates and sample sizes, and on the analytic p-value. Input perturbation changes outputs and preserves agreement with the independent reference. The reference status remains **partial** because the bootstrap and permutation inference procedures are not independently validated.

The three estimates are tied. The rank interval is 1–3 and extremeness is undefined, so the report does not turn a degenerate curve into evidence of an extreme author choice. Standard errors on the raw mean-difference scale are left empty alongside the `dz` estimates.

The report template exposes limited blinding, reference-check limits, and unresolved author settings. Automated HTML checks cover internal targets, duplicate IDs, and required limitation text. Browser security policy prevented opening the local HTML file, so visual layout was not checked.

The offline suite passes 310 tests with 14 skipped. The separately selected environment integration test also passes (311 passed in total).

## Validation still needed

Author-setting attribution returned all six factors unresolved even though the source explicitly mentions paired tests. The current function does not include the focal binding in its prompt or retain rejected candidate quotations and rejection reasons. This limits diagnosis: unresolved attribution must not be described as proof that the authors omitted the method. Add focal context, preserve raw attribution responses, and record per-factor validation reasons before calibrating attribution recall.

The legacy match-summary text also describes every intake abstention as missing data; this case includes unresolved column pairing despite available data. Reports must carry the actual readiness reason.

An independently annotated intake set must test claim completeness, atomic analysis boundaries, comparator fidelity, and column binding. Nonfocal range claims and some source comparator descriptions remain ambiguous in this case. Method attribution and audit acceptance need calibration against independent judgements. Supplied design facts must remain distinguishable from independently recomputed quantities. Working-directory separation does not establish enforced OS access restrictions.

Freeze the implementation and decisions before testing held-out cases. Do not use numerical agreement on this development case to select methods, amend generated scripts, or override audit findings.

## Run evidence

The ignored run directory preserves the launch plan, source snapshots, superseded attempts, append-only model ledger, Fable reviews, adjudication input snapshots, and `reverification_receipt.json`. The receipt confirms that fresh verification left all eight original scripts and result files unchanged. `integration_test_plan.json` records interventions. Cancelled in-flight HTTP requests may have usage not captured in the ledger; recorded metered cost is therefore a lower bound. Subscription CLI consultations outside the pipeline ledger are listed by their review artifacts.

Final receipts: `integration_result.json`, `preflight.json`, `warm_resume_receipt.json`, and `report_html_checks.json` in the run directory. The ledger contains 83 calls, including exactly eight replica generations and one executor generation. Recorded metered cost is $0.6661; subscription list-price equivalent is $16.8337. Neither figure includes auxiliary subscription review calls, and cancelled requests may have unrecorded metered usage.

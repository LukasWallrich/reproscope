# Final independent report check

Reviewed `/private/tmp/petersen-specr-review.html` and `/private/tmp/hurst-specr-review.html` against the earlier clarity findings. This was a read-only content, embedded-figure, and link check; it did not rerun either analysis or inspect the separate cheap-model run.

## Resolved

- Hurst's multiverse narrative now agrees with the matched-change tables: CI choice changes interval width only; test choice changes p-values; age and item handling change estimates. Rank-group matched comparisons are recognised.
- The false incomplete-report banner is gone. Computation accounting now says “await a computation disposition”, distinguishing it from unexplained discrepancies.
- The Hurst Pearson curve includes the reported −.51 reference and its rounding interval. Incompatible Spearman and Petersen effect scales explicitly explain why no reported reference is drawn.
- The specr-style upper curve and lower choice matrix share a specification order. Embedded SVG checks found exactly 12 unique columns across Petersen's groups and 36 across Hurst's, in ascending estimate order. Every internal fragment link resolves.
- Sign-comparison and printed-precision contradictions are resolved in the displayed comparison records. The Hurst F-value precision discrepancy is retained without the false scalar-df failure.
- Screening history is explicitly separated into a screening audit. Consecutive duplicate diagnosis quotations have been removed. Statistical-review reasoning is collapsed, and source-quantity links retain access to the evidence.
- The unsupported assertion that recruitment records were “never retained” is gone; the report limits the statement to the supplied deposit.

## Remaining material edits

1. **Reported-position caption:** the Hurst categories 4/4/16 concern the reported rounding range, not strict comparison with −.51. Eight estimates are numerically below −.51, including the four that round to it. Say “4 fall below the reported rounding range, 4 round to the reported value, and 16 fall above that range.” Ranks 5–8 correctly describe the rounding-compatible specifications. The parent agent has confirmed this wording is being fixed.
2. **Petersen statistical-review anchors:** two reasoning panels still contain JSON fragments for the likelihood-ratio discrepancies. The parent agent has identified these and is applying the same evidence filtering/source-linking used for diagnosis cards.
3. **Hurst main multiverse prose:** replace internal identifiers (`age_form`, `item_imputation`, `ci_method`, `null_test`, `corr_type`, `bootstrap_ci`, `residual_estimator`) with the existing reader labels. The substantive explanation is correct, but the identifiers require readers to decode implementation names. Remove the residual aside about “the declared x − y subtraction order”; the opening association sentence already explains the direction correctly.

No further material numerical contradiction was found within this bounded check. Browser layout and interaction QA remain separate from these embedded-HTML checks.

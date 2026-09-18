# Fact-check of report-review findings

The review identified two confirmed shared implementation defects: the sign gate uses rounded values, and reader-facing comparison labels ignore printed-precision discrepancies. The F-statistic issue also exposes a metadata validation defect, but attributing the missing separator to PDF extraction is not supported: the published Hurst table itself displays `F(5132)`.

This check inspected existing Stage 0 claims, Stage 1 matches and diagnoses, Stage 2 correctness artifacts, editorial copy, and the shared comparison/rendering code. It also viewed the existing page-six PNG for Hurst. No study analyses were manually recomputed or changed. Small read-only calls to the shared comparison functions reproduced their edge-case behaviour. No shared code was edited.

## 1. Hurst: false opposite-sign labels and a missed sign flag

**Verdict: confirmed implementation bug, with one qualification.** The two replicas agree on the relevant values:

| Claim | Quantity | Reported | Recomputed, approximately | Current `sign_match` | Current rule |
|---|---|---:|---:|---|---|
| c220 | Biological-siblings standardised beta | −.01 | −.003960 | false | opposite signs |
| c228 | Half-siblings b | −.01 | −.003364 | false | opposite signs |
| c232 | Half-siblings t | −.01 | −.003082 | false | opposite signs |
| c230 | Half-siblings standardised beta | +.01 | −.0002563 | true | relative difference 1 |

The qualification is that **c230 is still graded `fail` and included in the discrepancy diagnosis**. It is the sign-specific field and explanation that miss the opposite signs, not the whole discrepancy. The a55 diagnosis and Stage 2 statistical review already recognise the source's inconsistent b/beta/t signs. The a55 and a57 diagnoses explicitly note that the same-negative “opposite signs” labels are wrong.

**Root cause:** `reproscope/stage1/match.py:grade` computes `rounded = _round_to(replicated, precision)` and then compares `(rounded >= 0) == (reported >= 0)`. Each small negative value becomes `-0.0` at two decimal places, and Python considers `-0.0 >= 0` true. This falsely flips the inferred sign for all four cases. This is independent of paired-test contrast handling; these are regression coefficients/t statistics.

**Minimal justified fix:** assess numerical direction from the unrounded, canonical comparison values. Treat exact zero explicitly as zero rather than positive. Preserve rounding comparison as a separate field and do not weaken the existing source-grounded paired-sign logic. A nonzero sign disagreement can remain material even if a rounded estimate displays zero, but the report should show both the tiny magnitude and the sign rather than imply a large effect reversal.

**Acceptance cases:** the first three rows have same-negative direction but retain their printed-value mismatch; c230 has an opposite-sign flag and remains a discrepancy; actual zero is not labelled positive or “opposite” solely due to the Boolean `>= 0` shortcut; paired-t source-direction regression tests remain unchanged. Regenerate match-derived diagnoses and reader copy after correcting the grader so the output does not preserve obsolete caveats about its own labels.

## 2. Hurst: `F(5132)` is malformed printed notation, not a demonstrated extraction artifact

**Verdict: the automatic mismatch is unjustified; the review's proposed origin is not established.** Claims c233 and c234 preserve `F(5132)` in both `source_quote` and `source_anchor_quote`. Their descriptions and visual-adjudication notes interpret it as `(5,132)`. The existing `corpus/Hurst_EvoHumanBehavior_2017_yypJ_v1_20260915/pages/p006.png` visibly displays `F(5132)` for both model summaries. There is no visible separating comma. It therefore cannot be described as a confirmed text-extraction loss.

The current match rows turn `5132` into a single reported degree of freedom, compare it with the verified residual df of 132, and force the whole result to `fail`. The a59/a65 diagnoses recognise the representation issue but assert that both F values match their reported precision. That last assertion is wrong for c233.

There are **two shared metadata defects**:

1. `reported_metadata.degrees_of_freedom` accepts a one-number F annotation. An ordinary model F test requires a numerator/denominator pair, so the annotation should be represented as malformed/ambiguous, not a verified scalar df of 5132.
2. `statistic_metadata.check` compares the parsed reported object directly with `execution_evidence['df']`. The regression verifier currently exposes only residual df. Even a clean synthetic source string `F(5,132) = 9.09` is therefore compared as `[5,132] != 132` and incorrectly flagged. Fixing extraction alone would not fix this.

**Minimal justified fix:** store and validate typed degrees of freedom appropriate to the statistic. Have the independent regression reference expose both model and residual df, and propagate those fields to execution evidence. Parse a clean F pair into those two fields. A malformed single-number F annotation should trigger a source-notation issue and explicit non-verification of the pair; never split its digits merely because a desired model/sample suggests an answer. If a source-only visual adjudication supplies an intended reading, retain both the literal printed notation and the qualified interpretation rather than overwrite the quote.

**Separate F-value result:** c233 reports 9.09 and the independently verified value is 9.084889586040761. The existing `_round_to(..., 2)` returns **9.08**, and `exact_reported_precision` is already false. This small precision mismatch must remain after removing the spurious scalar-df mismatch. c234's 10.489950114987108 rounds to **10.49** and its exact-precision flag is true. Therefore neither “both F values mismatch” nor “both F values match the printed rounding” is an accurate summary.

**Acceptance cases:** a clean `(5,132)` source pair matches independently verified `[5,132]`; wrong numerator and wrong denominator each fail separately; a one-number F annotation is ambiguous, not a confirmed numerical disagreement; c233 remains a precision discrepancy; c234's F value matches while its printed df notation remains ambiguous. The reader report must distinguish source notation from a computational error.

## 3. Petersen: “close agreement” labels coexist with precision-discrepancy cards

**Verdict: confirmed inconsistency between deterministic reporting rules, not an absent diagnosis.**

| Claim | Reported | Recomputed magnitude | Existing diagnosis |
|---|---:|---:|---|
| c052 | t = 2.20 | 2.194814… | a06:precision_mismatch |
| c064 | dz = .53 | .522841… | a17:precision_mismatch |
| c065 | dz = .75 | .743446… | a16:precision_mismatch |

All have band A because they meet the approximate agreement rule. All also have `magnitude_exact_reported_precision = false`. Their paired-direction evidence establishes consistent substantive direction despite subtraction-order differences. The diagnoses correctly retain only the precision issue.

**Root cause:** `divergence.row_reason` checks the exact-precision flag after the A-band result and creates `precision_mismatch`. In contrast, `report/findings.py:assemble` defines problems only as a non-A band or `direction_unverified`, then renders every other verified result as `close agreement`. Thus the inventory and user-facing status answer different questions without saying so.

**Minimal justified fix:** preserve the numerical band for approximate closeness but use a shared comparison disposition that also includes precision, source-direction, and metadata status. For example, “Close numerically; differs at printed precision” is accurate for these cases. Include that status consistently in overview counts, filters, issue tables, and source-quantity details. Do not reclassify a source-consistent paired sign as an error or suppress the existing precision diagnosis.

**Acceptance cases:** all three rows have an explicit printed-precision qualification everywhere they appear; a true printed-precision agreement remains unqualified; exact precision for paired statistics uses the validated magnitude/orientation basis rather than the raw opposite subtraction sign; overview counts and discrepancy inventory use the same disposition rule.

## 4. “Never retained” is an unsupported editorial strengthening

**Verdict: confirmed wording problem introduced in reader copy.**

- Hurst c005 says 71 people did not complete all measures and were excluded.
- Hurst c008 says 209 people started the survey.
- `stage1/descriptive/report.json` says those records “are not retained in the deposited dataset”, which describes deposit availability.
- `stage1/diagnosis.json` carries the same limitation for c005 and does not establish that the original records never existed or were permanently discarded.
- `report/editorial/65740fc4a56b528711a7d012127ed70782b983c96c12eee3002c6e4d5bed2837.json` changes this to records “were never retained”. The source claims and computation evidence do not justify that retention-history claim.

The current editorial prompt already instructs the model to describe absence only as unavailability in the supplied deposit unless supported otherwise. Structural validation checks diagnosis coverage and labels, not this factual expansion. A prompt instruction alone did not guarantee compliant reader copy.

**Minimal justified fix:** use deterministic wording for simple availability dispositions (“The supplied deposit contains only the final sample; these recruitment counts cannot be independently reconstructed from it”). Do not invite a causal explanation of why records are absent unless the availability artifact contains a source-grounded cause. Regenerate the cached editorial copy and validate the rendered result, rather than only replacing one occurrence in an exported HTML file.

**Acceptance cases:** availability-only evidence cannot yield claims of deletion, destruction, or never retaining records; actual source-backed retention statements remain possible with their citations. c005/c008 still have explicit unavailable dispositions and preserve their reported recruitment numbers.

## Scope of the recommended changes

These fixes belong in the shared grader, metadata contract/reference evidence, report-disposition layer, and constrained editorial pipeline. They do not require changing paper-specific data or generated analysis code. Existing numerical execution receipts remain useful; affected match, diagnosis, Stage 2, reporting, and end-to-end acceptance artifacts must be refreshed through their provenance-aware pipeline paths. The cheap-model Hurst rerun should exercise the corrected shared rules without relaxed acceptance criteria.

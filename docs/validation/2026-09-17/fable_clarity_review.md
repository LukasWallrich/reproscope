# Review of the Petersen v7 and Hurst v1 reproduction reports (clarity and evidence)

I reviewed the report text only. I had no tool access this turn, so the prompt and code locations I name are inferred from file names and are not verified.

## Main finding: the reports miss evidence they already contain
- **Petersen likelihood-ratio tests.** The two "unresolved" discrepancies share the same offset: 712 − 68.17 = 643.83 and 665.3558 − 21.52 = 643.84.
  - That points to one corrupt input, the `LogLik_2x3model` column in mmc5. The same fault would explain the blocked 2x3 vs 1x3 test, where a nesting violation is flagged.
  - Both offsets are printed, but each group is diagnosed in isolation and the report concludes "no supplied check discriminates".
  - The `data_integrity` evidence is cited but never shown, so the reader cannot see which rows or values are anomalous.
- **Hurst untested hypotheses.** Several "what would resolve it" items can be computed from the deposit but were not run:
  - Spearman instead of Pearson correlation.
  - Step-parent count as `StepM + StepF`.
  - Truncation versus rounding, tallied across all Table 4–6 cells.
  - Reverse-keying, checked by the signs of item–rest correlations. This needs no reported targets.
- **"Unavailable" mixes two cases.** Genuinely absent data (the 209 survey starters) is given the same status as a key with a small number of candidate conventions.
  - 91 of Hurst's 104 "unavailable" quantities come from two tables, each missing one key with about two candidates (the DSM 1–5 vs 0–4 coding, and the self-harm 1/2 codes).
  - The report already has a "declared convention" tier. It could compute these quantities under each candidate and label them as not independent confirmation.

## Pipeline bugs that show up as findings about the paper
- **Sign gate inverted.** c220, c228 and c232 are flagged "opposite signs" although reported and recomputed values are both negative. The genuinely opposite-signed c230 is not flagged.
- **Degrees of freedom misread.** `F(5132)` is an extraction artifact for F(5, 132), yet c233 and c234 count toward the "24 need attention".
- **Inconsistent grading rule.**
  - A gap of 0.0052 is "Close agreement" in Petersen c052, while 0.0053 is "Check difference" in Hurst c151 and c172.
  - Petersen c052, c064 and c065 are both "Close agreement" and listed as discrepancy issues.
  - The rule should be printed-precision rounding first. Relative difference on near-zero values produces meaningless figures such as "relative diff 1".
- **Reported values stored as floats.** "t = 2.2" and "d = 0.8" lose the printed decimals that every rounding check depends on.
- **Replica sign flips shown as discrepancies.**
  - The header reads "0.89 / −0.89".
  - About 40 rows show raw differences such as −1.7797.
  - The inputs table shows one subtraction order for both replicas, while the method-check lines show two.
- **Narrative contradicts the deterministic tables (Hurst stage 3).**
  - It calls CI method "the only matched active dimension, affecting estimates", but the table shows an estimate change of 0.
  - It says there are no matched comparisons for the rank group, but the table shows 6, 6 and 4.
  - It states a subtraction order for a correlation and leaves stray LaTeX parentheses.
- **Vague status lines and overloaded labels.**
  - "Run incomplete. report did not pass" gives no gate or reason.
  - "0 remain unresolved" sits directly above issues labelled "Unresolved".
  - "Supported explanation" is applied to input gaps and to unverified rounding.
  - The Hypothesis versus Unresolved split looks arbitrary (a23 versus a13).

## Repetition and how to remove it without losing evidence
| Repetition | Example | Fix |
|---|---|---|
| Reason text is identical to its "evidence" and is printed about 5 times per quantity | The self-harm sentence appears about 340 times, under "68 groups" of size 1 | Give each missing key a `missing_key` id with one explanation, list the affected quantities in a member table, and suppress the evidence when it equals the reason. |
| Inputs table and the "Independent method check" line repeated per quantity and per replica | Hurst's 10-line regression block appears about 60 times; t, p, d and the star for one test each get their own block | Render one card per analysis (contract id) with its reported statistics as rows. |
| Identical replica rows and boilerplate rule sentences | "Paired statistic magnitude: A; … Test tail is assessed separately" appears about 90 times | Collapse to "both replicas: x" and expand only on divergence. Move rule text to a coded legend. |
| Restatements and stars counted as separate quantities | c021–c030 duplicate c012 and others; c197–c200 duplicate Table 5; c094 duplicates c060 | Link each restatement to a canonical quantity, and show both occurrence and distinct-test counts in the headline. |
| Stage 2 re-narrates stage 1 | The likelihood-ratio story is told three times | Have stage 2 cite the issue id and add only new evidence. Its one new fact, that the reported χ² and p are mutually consistent, belongs in the issue card. |
| Inference-only settings plotted as extra specifications | Petersen has 7 specs but 2 distinct estimates (22.67 and 25.79), with the "median" taken over duplicates; Hurst has 24 specs but 6 distinct estimates | Plot one point per estimate-defining specification and draw the inference variants as alternative whiskers. Compute summaries over distinct estimates. |
| Empty or single-spec figures, and a flat listing of over 200 log files | The rank-biserial groups | Show groups with fewer than 3 distinct estimates as a table row. Replace the log listing with a collapsible manifest. |

Unrelated leftovers are also merged into single issues, such as "variance explained + pupil SD" and "F df + Mini-K alpha". Issues should be grouped by shared input, table or cause.

## Multiverse figure specification
**Layout.** One figure per comparable effect group, where a group shares estimand, scale, null and contrast orientation.
- The top panel shows estimates and CIs by rank.
- The bottom panel is the choice matrix in the same SVG on the same x-axis.
- Matrix rows are grouped by dimension. Inference-only and inert dimensions sit in a separate greyed block.
- Petersen's 1.5×IQR rule removed no observations, so that dimension is inert and should be marked as such.
- y-axes are never shared across groups.

**Reported value versus recovered author specification.**
- The reported value is drawn as a horizontal line with a rounding band taken from the printed string. For example, −.51 becomes [−.515, −.505].
- It is never a ranked point. If the paper gives only a bound (p < .001), no marker is drawn.
- The author specification is the spec whose every dimension is at `author_level`, drawn with a distinct glyph at its computed estimate.
- Author-level tags are currently unreliable:
  - Hurst: "Complete-item-case" is tagged "paper" while the deposited totals and Pearson are tagged "defensible".
  - Petersen: the paired t test, Student-t interval, raw v scale and "no multiplicity adjustment" are tagged "defensible" although they are the paper's choices.
- Stage 3 should require exactly one author level per dimension, or an explicit "unknown" that makes the author spec set-valued.

**Position and ties.**
- State position as counts. Hurst: "4 specifications more negative, 4 within the band, 16 less negative".
- Do not claim a rank or percentile that the rounding or the ties cannot support.
- Sort ties by a fixed matrix key and mark each tie block.

**No mixing of scales or nulls.** Petersen says no same-scale reported value exists, yet the focal dz = 0.89 is reported.
- Emit dz for the specifications that define it (arithmetic mean, raw scale). Give those their own panel carrying the reported line.
- The trimmed, log-ratio and rank panels say "no reported value on this scale".
- Show Monte Carlo floor p-values as "≤". These appear to be the 0.0025 values, which look like the permutation floor ×25. Exclude them from "largest p change", and label rescaled p-values as rescaled.

## Prioritised fixes (likely location)
1. **Cross-quantity diagnosis in stage 1.** Give the diagnoser the shared-input graph and the residual patterns (a constant offset, a ×10 factor, truncation fit). Any computable hypothesis must be run or marked "not run: reason" (`stage1/diagnose.py`, `targeted.py`).
2. **Comparison correctness.** Store the printed string, make rounding the primary rule, fix the sign gate, parse df as pairs, and fix the contrast order in the contract (`stage0_extract`, `contracts`, `stage1/match.py`).
3. **Status taxonomy.** Use absent data / ambiguous key (k conventions computed) / demonstrated / consistent-but-untested / unresolved. Add `missing_key` grouping (`stage0_readiness`).
4. **Rendering.** Per-analysis cards, deduplicated reasons, collapsed replicas, a legend, and a stated reason when a run fails (`report/build.py` and the template).
5. **Stage 3 schema.**
   - Dimension role (estimate-defining / inference-only / inert).
   - An `author_level` flag per dimension.
   - A focal-scale panel.
   - The specr figure described above.
6. **Narrative checks.** Every number and every "only/no/all" claim in the stage 2 and stage 3 text must resolve to the structured payload. No orientation sentence for symmetric estimands, and no LaTeX (`stage3_interpret`, `stage2_*`).

## Acceptance checks
- No sentence of 12 or more words appears more than twice in either report.
- Hurst's unavailable section has at most 8 groups. Every quantity stays reachable, so the total remains 262.
- The Petersen likelihood-ratio issue reports the common offset and the offending rows as a single issue.
- With replica signs aligned, no |raw difference| exceeds 2×|reported|. The "opposite signs" flag fires exactly when the signs differ.
- c233 and c234 are classed as extraction problems.
- Grading is monotone in the distance to the rounding boundary across all statistic types. No quantity is both "Close agreement" and a discrepancy issue.
- The author-spec estimate in the figure equals the stage-1 replica value within 1e-8: −0.5134 for Hurst and dz 0.8897 for Petersen.
- The reported marker appears only in its own group, and its band width matches the printed decimals.
- Plotted points = distinct estimate-defining specifications. Matrix columns = plotted points, in the same order.
- No headline rank is given when the band or a tie spans more than one specification.
- The narrative check passes against `rank.json` and the matched-comparison tables.
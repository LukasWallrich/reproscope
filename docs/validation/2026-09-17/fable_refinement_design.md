**Yes: add a repair pass, but gate it on a typed rejection.** Your add-only rule fixes padding but merges two different failures: "this choice is scientifically indefensible" and "this choice is fine but poorly specified". Only the second should be repairable.

## Screener verdict
- The screener returns one of `accept`, `reject_substantive`, `reject_operational` or `reject_nonstandard`.
- Operational rejections must list `missing_fields[]` drawn from the factor schema, not just prose.
- `reject_substantive` is final.
- `reject_operational` gets one repair.
- `reject_nonstandard` is repairable only by substituting a named, citable standard method at the same decision node.

Your two rejections fit this split. Rank residual correlation is ambiguous on rank-then-residualize versus residualize-then-rank. Trimming lacks a rule, a threshold, the variables it applies to, and whether it runs before or after adjustment. Both look operational, not substantive.

## Factor schema, per option
- `decision_node`: the analytic decision, which cannot change under repair.
- `procedure`: the algorithm, parameters and thresholds.
- `applies_to`: the variables and the pipeline position.
- `effect_scale`: `raw`, `transformed` or `rank`.
- `comparable_to_baseline`: a boolean.
- `reference`: a method name or citation.
- `kind`: `analytic_choice`, `resampling_diagnostic` or `stochastic_seed`.

Count a dimension only if:
- it is an `analytic_choice`;
- it is deterministic;
- it has at least two accepted options.

Leave-one-out and seeds fail the first test by construction, so they stay out of the count without special-casing. Raw-scale outlier options sit in the main comparable set. Transformed and rank options go in a separate stratum and are never pooled into the same summary. Report dimension counts per stratum.

## Repair mechanics
- The repairer sees the original spec, the reason code and `missing_fields`. It does not see the screener's free text, so it cannot tailor its wording to it.
- A deterministic check enforces that the repaired version keeps the same `decision_node` as the original.
- A split, such as raw-scale robust versus rank, is allowed only if the screener flagged mixed scales. The children inherit the parent ID (F3 → F3a, F3b).
- The rescreener runs in a fresh context with the same rubric. It sees only the repaired spec and is blind to its history, so the spec meets the same standard as a first-time proposal.

## Stopping rules
- Allow one repair per factor and one rescreen, with no re-rolls. A second rejection is final whatever its type.
- Run the order as repair first, then one add-round. Stop when all repairs are resolved and the add-round yields no new accepts, or when the target is met.
- Treat ">4" as a target, not a loop condition. On a shortfall, report the count and the typed reasons. For a covariate-adjusted correlation, two to four defensible dimensions may simply be the honest answer.

## Provenance
- Keep an append-only record per factor version: proposer and screener model, prompt hash, round, verdict, reason code, a field-level repair diff, `parent_id` and final status.
- Never overwrite a rejection. Rejected and repaired factors appear in the report with their history.
- Classify legacy untyped rejections by reason only, not re-judged on merit, and log that classification as its own event.

I haven't read the repo code. The change likely touches `stage3_screen.md` for the typed verdict and `missing_fields`, `stage3_enumerate.md` for the schema fields, and `reproscope/stage3/multiverse.py` for the repair round, identity check and counting rule.
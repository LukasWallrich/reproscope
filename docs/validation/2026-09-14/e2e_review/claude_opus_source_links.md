**Verdict:** the ban is too broad for source-to-source linking. It should stay absolute for computed results. The ban exists to stop two things: choosing an analysis because its output matches (circularity), and matching on numbers alone. Linking a prose restatement to a unique printed table row by a joint signature does neither, provided the rules below hold.

**Rules**

1. **Link records, not contracts.** Produce a `restates: <table_record_id>` link. The prose record inherits the table record's contract. The link never assigns a contract directly.
2. **Source-only inputs.** The linker receives extraction records only. Enforce this in the function's signature and module imports, not just in prompts.
3. **Non-numeric fields nominate; numbers only confirm.**
   - Build the candidate set from study, subgroup, predictor, statistic type, model and covariates. These must match exactly.
   - At most one field may be open, here the outcome measure.
   - That open field must resolve to a closed list the paper itself names, here the two life-history measures.
   - If the candidate set isn't closed and small, don't link.
4. **Joint numeric confirmation.** Every printed quantity must be compatible under rounding intervals. Prose "−.20" means [−.205, −.195). Intersect that with the table's interval, and do the same for p. Note that r and p share n, so they are not independent evidence. They confirm but can't substitute for rule 3.
5. **Uniqueness by exclusion.** Link only if exactly one candidate passes and every other candidate is printed and fails. If a competing measure has no printed value, or two measures both pass, don't link.
6. **No independent double-count.** A linked prose record is reported as "restates Table X row". The reproduction target is the table record. A prose/table mismatch is never used to infer identity.

**Remaining ambiguity**
- **Coincidence:** two-decimal r plus p is a coarse signature. Rule 5 only excludes the named candidates. It can't exclude an unreported analysis, such as a composite score, that the prose actually meant.
- **Typos:** if the prose number is a typo, the record correctly stays unlinked, but the author's intent is lost.
- **Sample drift:** subgroup labels may differ between prose and tables ("half-siblings" vs a coded group). Normalising labels is itself an identity judgement, so keep it exact-string or arbitrated without numbers.
- **Report it:** state the linking basis in the report so readers can reject it.

**Unavailable vs unattempted:** yes, count confirmed-missing definitions as *unavailable method information*. Give them a distinct status such as `method_unspecified`, and record:
- the missing field (`outcome_measure`)
- the candidate list
- why linking failed (`no_unique_printed_match`)

Keep these records in the "all reported numbers" denominator, in their own category. They are neither reproduction failures nor silently skipped. `not_attempted` stays reserved for pipeline gaps. Don't compute all candidates as a fallback. It invites post-hoc reading even when unassigned.

**Implementation (small, deterministic, in `reproscope/stage0/contracts.py`)**
- Keep the LLM's role to extracting structured fields. Printed values must stay as strings so decimals are preserved.
- Add `link_restatements(records) -> list[Link]`. It is pure Python, runs after contract assignment, and only touches unassigned prose records.
- Add `rounding_interval(printed: str) -> tuple[float, float]`.
- Add the `method_unspecified` status and carry it into the report and evaluation counts.

**Tests (`tests/test_stage0_contracts.py`)**
1. A unique joint match produces a link, and the contract is inherited.
2. Both named measures pass, so no link.
3. The competing measure is unprinted, so no link.
4. Numbers are identical but covariates, subgroup or predictor differ, so no link.
5. Rounding: −.204 links to "−.20"; −.21 doesn't; "p = .02" vs "p < .05" is compatible but not sufficient alone.
6. Two open fields, so no link.
7. Numbers alone with no nominated candidates, so no link.
8. Purity: the linker imports nothing from stage1–3. Assignments are byte-identical with and without stage-1 artifacts on disk.
9. An unlinked record gets `method_unspecified` with its reason and candidates, and counts in the denominator.
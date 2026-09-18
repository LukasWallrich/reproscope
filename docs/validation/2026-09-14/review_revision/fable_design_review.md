**Implementation policy: divergence diagnosis, Stage 2 review, multiverse reporting**

**1. Divergence inventory (Stage 3)**

- **One row per reported number.** Key each row to its location in the paper (table, cell, or sentence). Descriptives, Ns, and cell counts get rows, the same as test statistics. Most real defects surface there.
- **Fields.** Reported value, reproduced value, absolute and relative difference, rounding flag, direction flag, invalid-input flag, status, cause, evidence tier.
- **Rounding bound.** Compute the interval implied by the reported precision. A reproduced value inside that interval is "within rounding", never "divergent".
- **Direction unknown.** When sign cannot be recovered from the paper or code, record the status "direction unknown" and diagnose the magnitude only.
- **Invalid inputs.** When a reported value is impossible given N, scale, or degrees of freedom, record "not reproducible" and state the constraint it violates. This is a finding in itself.
- **Status vocabulary, fixed.** exact match, within rounding, divergent, not reproducible, direction unknown.
- **Grouping without coverage loss.** Group by estimand identity, never by similarity of value. Repeated citations of one estimand collapse into one row listing all locations. Replicas (seeds, executor runs) collapse into one row with min, max, and spread. Invariant: every reported number maps to exactly one row, and the mapping is stored.
- **Diagnosis is mandatory for every non-match row.** The cause may be "unknown". A missing cause is allowed. A missing diagnosis attempt is not.

**2. Evidence tiers**

- **Confirmed defect.** A specific code line or data step, plus a demonstration: either the fix recovers the reported number, or the reported number is shown impossible from the stated inputs.
- **Hypothesis.** A plausible mechanism with the confirming test named but not run.
- **Unknown.** Divergence with no candidate mechanism.
- **Rule.** The word "error" in any writeup requires the confirmed tier. Hypotheses go in a separate list. Repetition across replicas never upgrades a tier.

**3. Stage 2 schema**

Two questions only, each answered yes, no, or unclear, with one line of evidence pointing to a location and a severity of "alters conclusion" or "does not alter".

- **Q1, coding.** Does the code compute what the methods section says it computes? Covers variable selection, filters, model form, and transformations.
- **Q2, interpretation.** Does the text's claim follow from the reported number? Covers wrong sign, wrong magnitude, non-significant result described as an effect, and confidence intervals misread.

**Causal language.** Drop it from the defect schema. Keep at most a single non-scoring flag, raised only when the design cannot support the claim on its face: cross-sectional observational data, no identification strategy, and a causal verb in the abstract. Anything needing a plausibility judgment is out of scope.

**4. Multiverse reporting**

Every deviation is reported relative to the faithful reproduction baseline, never as a peer of it.

- **Sort choices into two kinds.** Estimand-changing: raw versus log outcome, mean versus trimmed mean. Inference-changing: t versus bootstrap, percentile versus BCa (bias-corrected and accelerated) intervals, multiplicity correction.
- **Estimand-changing choices define compatibility classes.** Never pool point estimates across classes. Per class report: baseline estimate and interval, range of estimates within the class, sign consistency, and the single choice that moves the estimate most. A log-scale effect is reported on its own scale, not back-transformed into the raw class.
- **Inference-changing choices share a point estimate.** Report interval endpoints side by side. For each interval state whether it contains the baseline estimate and whether it excludes zero. Multiplicity corrections adjust the threshold, not the estimate: show adjusted and unadjusted together, never merged into one count.
- **Conclusion robustness replaces vote counting.** Per estimand, state whether the baseline conclusion (direction plus interval excluding the null) holds in every specification of the same class. If not, name the choice that breaks it. A fraction-significant figure may appear as a descriptive labelled "not a verdict", or be omitted.
- **Leave-one-out is a separate object.** Run it on the baseline specification only, dropping one unit, or one cluster for repeated measures, at a time. Per estimand report: full-sample estimate, maximum absolute shift, the unit producing it, and whether any leave-one-out estimate leaves the full-sample interval or crosses zero.
- **Leave-one-out aggregation.** One table row per estimand, matched to its full-sample baseline. Do not average shifts across estimands. Do not cross leave-one-out with the specification grid.

**Report layout.** Three separate blocks: divergence inventory with tiers, Stage 2 answers, multiverse with leave-one-out in its own table. Confirmed defects lead. Hypotheses and unknowns follow, never mixed.

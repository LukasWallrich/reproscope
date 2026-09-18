**Recommend (A): remove `n_total`/`group_ns` from every blind contract.**

- **N is a checked outcome, not an input.** You independently recompute N, so a nominal N in the generator's context is the target value. Row-removal reexecution catches hardcoding. It cannot catch anchoring during generation: a generator can adjust exclusion logic until the rows come to 138, and that logic still reruns correctly after a row is dropped.
- **"Forbid fitting to nominal N" can't be enforced.** It is only a prompt instruction. You can't audit whether the model used the number. Removing the field removes the channel.
- **The generator loses nothing it needs.** Eligibility is already fixed and source-grounded. The generator should derive N from those rules and the rows. A mismatch with the paper is a finding your descriptive engine should surface, not something the generator should correct.
- **The policy stops depending on the scanner.** Under B, blindness depends on the scanner, which flags 138 but misses 28. Under A, the rule is the same for every paper and holds regardless of scanner thresholds.
- **The cost is one-time.** You regenerate where contracts change, and the blind status becomes verifiable afterwards. Keep arm and group *labels*; drop the counts. Nominal N can stay in non-blind contexts such as MDE, alignment and reporting.

**CI 0.95:** Yes, this is a source-provenance collision, not an empirical leak. The value is a conventional analysis parameter fixed by a registered generic template before and independently of the paper. It carries no information about the data or results.

Two cautions:
- Whitelist it by provenance (unmodified template constant), not by value. A 0.95 that enters through paper-specific text should still be flagged.
- Log the collision instead of silently suppressing it.
**Boundary rule.** The screen decides which analysis choices the source permits. The executor implements only fully specified recipes and never fills an open field. An open field goes to the completion step or the arm is excluded.

**Source-only completion, before executor generation**
- Input: the screen output and the source text.
- Output: one complete recipe per accepted arm, with a fixed field list:
  - correlation type (full or semi-partial, Pearson or Spearman);
  - covariate set, and which variable is residualised;
  - inference method, with CI level, resample count and seed;
  - the trim definition: which model's residuals, internally studentized, the maximum across raw variables, and the rule for 5% of a non-integer N;
  - step order: trim, rank, residualise, estimate;
  - tie handling and reported N.
- Every field carries one tag:
  - `source`, with the quoted text span;
  - `default`, from an approved list;
  - `analytical`.
- The step adds no arms and does not reinterpret accepted methods. It runs once.

**Default or analytical choice.** Two questions decide this. Would a competent analyst pick a different value and get a materially different number? Does the choice change what is estimated?
- **Defaults** are conventional and do not change the estimand. They include CI level, resample count, seed, and percentile bootstrap when the source gives no hint.
- **Analytical choices** change results in ways a reader would want to see. The source resolves them, or they become explicit arms, or the arm is excluded with a reason. They are never filled silently.

The three open items from the screen:
- **Semi-partial analytical CI:** analytical. No single standard closed form exists. Use bootstrap for that cell or exclude it. Do not invent a formula.
- **Permutation CI:** analytical. A permutation scheme gives a p-value. Turning it into a CI needs a further construction, such as test inversion, that the source must state. Without that, keep the permutation p-value, take the CI from bootstrap, and tag it.
- **Rank Fisher CI:** allowed only when labelled approximate, with the variance constant stated. Otherwise use bootstrap.

With covariates present, the permutation scheme is also analytical. The options are permuting raw outcomes, permuting residuals, or Freedman–Lane (permute the residuals of the reduced model). Trimming interacts with resampling. State whether the trim is re-applied inside each resample or fixed once. This materially changes the interval.

**Closed verifier gap.** The executor must not hand-write residual trimming, residual permutation or conditional patches.
- **Generic primitives:** add residual trimming and simple residual permutation to the closed library under review, with tests against known values.
- **One-off conditional patches:** keep them out of the library. Mark those arms "accepted, not verifiable" and report them outside the verified set.

An arm counts as verified only when the closed library contains every primitive its recipe uses.

**Screen self-contradiction.** For each arm the screen emits either an incompatibility or an applied rewrite, never both. Use two separate lists:
- `incompatible`: the arm is excluded, with a reason.
- `rewritten`: original form, applied form, reason.

A mechanical check enforces that no arm appears in both lists. An incompatibility whose rewrite is already applied is deleted and recorded as a rewrite. The check runs as code, not as a prompt instruction.

**Independent review**
- The review runs in a fresh context, preferably with a different model.
- It receives the source and the completed recipes only, not the screen's reasoning.
- It gives pass or fail per recipe, not prose, on these checks:
  - every `source` tag resolves to its quoted span;
  - every `default` is on the approved list;
  - every `analytical` item is an arm or an exclusion;
  - every primitive exists in the closed library;
  - the two screen lists are disjoint;
  - the step order is stated.
- Failed recipes go back to completion once. A second failure excludes the arm and logs the reason.

**Report counts.** Report accepted, completed, verified and excluded arms separately. This keeps multiverse coverage visible and stops a shrinking verified set from reading as robustness.

# Adapting `coarse` for management / social / organizational psychology

Read-only investigation, 2026-08-31, against `/Users/lukaswallrich/Documents/Coding/coarse`
(v1.4.0) and upstream `Davidvandijcke/coarse` v1.9.1. Nothing was modified.

Builds on `research_coarse_fork.md` (pipeline architecture); this report covers only the
field-adaptation question.

---

## 1. Verdict up front

A psych adaptation is **worth doing and is small: 3-5 focused days**, not weeks. But it is
**not a prompt-swap** — three things must change together, and the least obvious one is the
most important.

Recommended shape: **an overlay package that patches prompt constants at runtime**, not a
hard fork and not a patch stack. Second choice, if the overlay proves fiddly: a
long-lived branch on the existing fork, rebased occasionally. Upstream churn in the files
you would touch is low enough that either works.

---

## 2. The finding that changes the plan: the editorial gates delete psych comments

The obvious plan is "rewrite the section rubrics for psych." That plan fails silently.

`_CRITIQUE_SYSTEM_TEMPLATE` (prompts.py L1794-1878) and `_EDITORIAL_SYSTEM_TEMPLATE`
(L1931-2042) run *after* the section agents and decide which comments survive and what
severity they get. Their keep/delete criteria are written in proof vocabulary. Verbatim
from the editorial template:

- `- The comment asserts a specific numerical value without showing a derivation from
  the paper's definitions — DELETE.`
- `- The comment claims a proof step requires a condition but does not identify the
  specific line in the derivation where that condition is invoked — DELETE.`
- `unbounded, identifiable vs not identifiable), REMOVE the comment unless it provides
  a complete, self-contained derivation disproving the paper's claim.`
- Severity ladder: `"critical" (concrete proof error, equation demonstrably wrong)`.

And from the critique template, what earns a keep:

- `- It identifies a specific mathematical error with a re-derivation or calculation`
- `- It identifies a missing assumption that is actually needed for a stated result`

Consequence: a rewritten Results rubric that produces "N=84 gives ~25% power for the
claimed interaction", "the mediation analysis is cross-sectional so the causal claim does
not follow", or "the preregistered DV is not the one analysed" generates comments that the
editorial pass then judges against a derivation standard they cannot meet. Best case they
are demoted to "minor". Worst case they are deleted, and the run looks like it simply
found nothing.

**So the gates must be rewritten in the same pass as the rubrics.** This is the single
reason a naive prompt swap would produce a reviewer that looks working and is not.

The same shape appears one stage earlier in `_CONFIDENCE_GATE` (L56) — "For mathematical
claims: show the correct derivation step-by-step" — and in `_STEELMAN_BEFORE_ATTACK`
(L314), whose steps 3 and 4 are written entirely about algebraic lines and formal
derivations. Both are appended to most system prompts.

---

## 3. Prompt-by-prompt: what is econ-specific vs field-neutral

Counting hits for proof/estimation/identification/derivation/equation/DGP/welfare/
Monte Carlo vocabulary across all 2,453 lines:

| Block | Lines | Econ hits | Disposition |
|---|---:|---:|---|
| `PROOF_VERIFY_SYSTEM` | 80 | 22 | Leave; never fires for psych if routing is fixed |
| `SECTION_PROOF_SYSTEM` | 70 | 21 | Leave; same |
| `_CRITIQUE_SYSTEM_TEMPLATE` | 84 | 15 | **Rewrite the gate/severity portion (~30 lines)** |
| `_EDITORIAL_SYSTEM_TEMPLATE` | 111 | 11 | **Rewrite the gate/severity portion (~30 lines)** |
| shared blocks (L27-395) | ~250 | 14 | **Rewrite ~60 lines**, keep the rest |
| `OVERVIEW_SYSTEM` | 65 | 13 | **Rewrite** |
| `COMPLETENESS_SYSTEM` | 66 | 10 | **Rewrite** |
| `_CROSSREF_SYSTEM_TEMPLATE` | 56 | 8 | Light edit |
| `MATH_DETECTION_SYSTEM` | 31 | 7 | **Tighten** (see §4) |
| `SECTION_SYSTEM` (general) | 62 | 6 | **Rewrite** |
| `CROSS_SECTION_SYSTEM` | 47 | 5 | Light edit — the discussion-vs-results logic transfers |
| `SECTION_METHODOLOGY_SYSTEM` | 45 | 3 | **Rewrite fully** |
| `SECTION_DISCUSSION_SYSTEM` | 44 | 2 | Light edit |
| `SECTION_LITERATURE_SYSTEM` | 29 | 0 | Keep as-is |
| `METADATA` / `CALIBRATION` / `CONTRIBUTION` | 95 | 2 | Keep; small wording fixes |
| `QUOTE_REPAIR` / `EXTRACTION_QA` / tone / humanizer / boundary / quote instructions | ~400 | 3 | Keep unchanged |

**Genuinely field-neutral and worth keeping verbatim**: `_TONE_BLOCK`, `_HUMANIZER_BLOCK`,
`_CONFIDENCE_CALIBRATION`, `_ENGAGEMENT_PATTERN`, `_OCR_ARTIFACT_NOTICE`,
`_CONTENT_BOUNDARY_NOTICE`, `_LITERATURE_BOUNDARY_NOTICE`, `_QUOTE_INSTRUCTIONS`,
`_DO_NOT_COMMENT_BLOCK`, `_FORWARD_REFERENCE_LENIENCY`, `_INTRO_LENIENCY`,
`_REMEDIATION_SPECIFICITY`, `_TABLE_VERIFICATION`, `_DOCUMENT_FORM_NOTICES`,
`author_notes_block`. That is a real asset — roughly 400 lines of hard-won
anti-hallucination and anti-AI-slop scaffolding that costs nothing to reuse.
`_TABLE_VERIFICATION` in particular transfers directly to psych results tables.

**Math-flavoured shared blocks needing rewrite** (~60 lines): `_NUMERICAL_CLAIMS` (its
examples are "volume, order, determinant, dimension, rank"), `_EQUIVALENCE_CLAIMS`
(pure math), plus the derivation clauses inside `_CONFIDENCE_GATE` and
`_STEELMAN_BEFORE_ATTACK`.

**Missing entirely.** Grep across all 2,453 lines returns zero hits for: p-value,
multiple comparisons, effect size, preregistration, statistical power, construct
validity, reliability, measurement invariance, common method bias, mediation,
moderation, sample size justification, attention checks, data/code availability.

Checked against upstream v1.9.1's `prompts.py` as well, not just the local v1.4.0: the
same terms are absent there, and `SECTION_SYSTEM_MAP` at v1.9.1 L1589 still has only the
five keys with no `results` entry. The gap is upstream's, not a stale-fork artifact.

---

## 4. It is three files, not one

`prompts.py` is the bulk, but two code files break psych papers before any prompt runs.

**(a) Routing precedence — `_detect_section_focus`, review_stages.py L61.**

```python
if section.math_content:
    return "proof"
if section.section_type == SectionType.METHODOLOGY:
    return "methodology"
if section.section_type == SectionType.RESULTS:
    return "results"
```

`math_content` outranks everything. A psych Results section containing a regression
equation or an SEM specification routes to the **proof** rubric — 70 lines of theorem
checking aimed at a table of betas. Fix: invert so `section_type` wins for
RESULTS/METHODOLOGY. ~5 lines.

**(b) `"results"` has no rubric.** `SECTION_SYSTEM_MAP` (prompts.py L1509) contains only
`proof`, `methodology`, `literature`, `discussion`, `general`. `agents/section.py` L74 does
`SECTION_SYSTEM_MAP.get(focus, SECTION_SYSTEM)`, so Results sections fall through to the
generic prompt. For a psych paper the Results section is where nearly all the reviewable
substance lives. This is the highest-value single addition.

**(c) Section classification misses psych headings — `_TYPE_KEYWORDS`, structure.py L31-60.**
(Upstream v1.9.1 renamed this to `_ENGLISH_TYPE_KEYWORDS` and added a companion
`_NON_ENGLISH_TYPE_KEYWORDS` for the i18n work; the English entries are unchanged, so the
gap below is identical in both versions — only the name differs.)
The keyword map has `method`, `model`, `identification`, `estimation`, `result`,
`experiment`, `simulation`, `empirical`. It has no `participants`, `measures`, `materials`,
`procedure`, `sample`, `analytic strategy`, `design`, or `study 1`/`study 2`. So a
standard psych manuscript's "Participants", "Measures" and "Study 1" headings classify as
`OTHER` → `general` focus. ~10 lines to fix.

**(d) Proof false positives — `_PROOF_KEYWORDS`, structure.py L355.** The keyword fallback
flags a section as math if it contains `"we show that"` or `"it follows that"`. Both are
ubiquitous in psych prose. This fires only when LLM math detection fails, but combined
with (a) it routes ordinary psych sections into proof review. Drop those two entries.

**(e) Literature search is arXiv-based** (`agents/literature.py`). Coverage of management,
social and organizational psychology on arXiv is close to nil, so the literature context
block will usually be empty or off-target. Either point it at OpenAlex/Crossref (you
already have OpenAlex keys) or accept a weaker literature stage. The fork
`mzchou/coarse` has already written the OpenAlex swap — see §8; port that diff rather
than rewriting it.

---

## 5. What a psych rubric set needs to contain

New or rewritten rubric content, roughly in value order:

1. **`SECTION_RESULTS_SYSTEM`** (new, ~55 lines). Inferential reporting completeness
   (test statistic, df, exact p, effect size with CI); do reported dfs match the stated N;
   do subgroup Ns sum to the total; multiplicity across the reported tests; p-values
   inconsistent with their test statistics (a statcheck-style check, which the LLM can do
   approximately and which anchors well to verbatim table quotes); "marginally significant"
   framing; CIs that contradict the significance claim; mediation/moderation claims from
   cross-sectional data; interaction claims tested only via separate simple slopes.

2. **`SECTION_METHODOLOGY_SYSTEM` rewritten** (~50 lines, replacing the 45 identification
   lines). Sample size justification and power for the *smallest* effect of interest;
   sampling frame and generalisability; exclusion rules and their timing relative to
   analysis; measurement — established scale vs ad hoc items, reliability reported and
   adequate, construct-vs-measure slippage, single-item measures; common method variance
   when predictor and outcome share a source; preregistration existence and adherence;
   attention/manipulation checks; missing data handling; nesting (employees in teams,
   participants in sessions) and whether the model accounts for it.

3. **A "measures" rubric** — worth having as a separate entry once `_TYPE_KEYWORDS`
   recognises Measures/Materials headings, but it can start as a section of the
   methodology rubric. Do not build it on day one.

4. **`OVERVIEW_SYSTEM` and `COMPLETENESS_SYSTEM` rewritten** (~130 lines combined).
   Replace "does the result have bite / worked example / Monte Carlo" with the psych
   equivalents of completeness: is there a preregistration and does the analysis match it;
   are effect sizes reported for every focal test; is there a limitations section that
   names the actual threats; are data and analysis code available; does the abstract's
   causal language match the design; JARS-style reporting gaps.

5. **Editorial and critique gates rewritten** (~60 lines of the 195). Replace the
   derivation standard with a psych evidentiary standard: keep a comment if it cites a
   specific reported number, N, scale, or preregistered claim from the paper and states
   the concrete inconsistency. Rewrite the severity ladder so "the claimed causal effect
   is not supported by the design" and "the reported df contradicts the stated N" can be
   `critical`.

Optional and higher-value than any rubric text if you want it: the `DomainCalibration`
stage currently *invents* the review criteria per paper at runtime. Replacing that
LLM-generated rubric with an authored static psych calibration (a `DomainCalibration`
object you write once) is ~30 lines of code and removes the main source of run-to-run
drift. It also lets you encode "do not check" items — telling the reviewer explicitly not
to demand proofs is as useful as telling it what to demand.

---

## 6. Surface-area estimate

| | Lines |
|---|---:|
| Rewritten in `prompts.py` | ~350 (methodology 45, overview 65, completeness 66, section-general 62, gate portions ~60, shared math blocks ~60) |
| New in `prompts.py` | ~60-110 (results rubric; optionally measures) |
| Unchanged in `prompts.py` | ~1,900 of 2,453 |
| Code changes | ~30-45 lines across `review_stages.py`, `structure.py`, `agents/section.py` |
| Optional: static calibration + OpenAlex literature | ~80 lines |

Roughly **400-600 lines rewritten or added out of 2,453**, plus a few dozen lines of code.

Effort: **3-5 days** for a working version, most of it spent writing and iterating rubric
prose against real manuscripts, not on code. Add ~2 days if you want the static
calibration and an OpenAlex literature stage. The code changes are half a day.

The dominant cost is validation, not construction: you need 3-5 papers where you already
know the flaws (ideally including one you have reviewed yourself) to check that psych
comments now survive the editorial pass. Without that loop you cannot tell a working
adaptation from a broken one, because the failure mode is silent deletion.

---

## 7. Fork vs upstream-tracking patches vs overlay

**Upstream churn is low.** `v1.4.0...v1.9.1` is 74 commits. In the files a psych
adaptation touches:

| File | Change over 74 commits |
|---|---|
| `src/coarse/prompts.py` | **+97 / −2** |
| `src/coarse/review_stages.py` | +46 / −9 |
| `src/coarse/structure.py` | +190 / −6 |

Two deleted lines in `prompts.py` across five minor releases. Upstream almost only
appends. That kills the usual argument against tracking patches — rebase conflicts in
`prompts.py` would be rare.

`structure.py` is the exception: its +190 lines are the i18n work, which *did* rename
`_TYPE_KEYWORDS` to `_ENGLISH_TYPE_KEYWORDS` and split out a non-English map. The English
entries themselves are untouched, so a psych patch to that map still applies cleanly — but
this is a concrete instance of upstream renaming a private name an overlay would bind to,
which is exactly the risk §7 asks you to guard with a startup assertion.

Note the earlier report's finding still holds: none of that 74-commit churn adds a
configuration surface for rubrics. `prompts.py` is composed from string literals at import
time — no file reads, no env vars, no templating. Upstream is not going to hand you a
plugin system.

**Recommended: an overlay package.** Three patch mechanics, all verified in the source:

- **Mutable containers — patch once.** `SECTION_SYSTEM_MAP` is imported by reference and
  read at call time (`agents/section.py` L74: `SECTION_SYSTEM_MAP.get(focus, SECTION_SYSTEM)`).
  Mutating the dict in place installs a psych `results` rubric and replaces the
  `methodology` one with two lines. Same for the keyword maps in `structure.py`.
- **Accessor functions — patch one global.** `editorial_system()`, `critique_system()` and
  `crossref_system()` (prompts.py L2045, L1881, L1723) each return the module-level
  `_EDITORIAL_SYSTEM_TEMPLATE` / `_CRITIQUE_SYSTEM_TEMPLATE` / `_CROSSREF_SYSTEM_TEMPLATE`,
  resolved at call time. Reassigning that one global in `coarse.prompts` reaches every
  caller. This covers the §2 headline fix cheaply.
- **Import-bound constants — patch per agent module.** `OVERVIEW_SYSTEM`,
  `COMPLETENESS_SYSTEM`, `SECTION_SYSTEM`, and the `EDITORIAL_SYSTEM` / `CRITIQUE_SYSTEM`
  fast paths are bound into each agent's namespace at import. Note the agents use both
  paths — e.g. `agents/editorial.py` L69 is
  `editorial_system(comment_target) if comment_target else EDITORIAL_SYSTEM` — so the
  gates need *both* the global and the per-module constant patched, or half the runs keep
  the econ gate. Patch `coarse.agents.overview.OVERVIEW_SYSTEM` and friends directly, the
  same monkey-patch pattern `headless_review.py` already uses to swap `LLMClient` in both
  `coarse.llm` and `coarse.pipeline`.

That gives you:

- `pip install -U coarse-ink` keeps working; no rebasing, no divergent checkout
- all psych prose in your own files, reviewable as a unit, diffable, testable
- the code fixes (§4 a-d) are the only things that cannot be done by patching constants —
  `_detect_section_focus`, `_TYPE_KEYWORDS` and `_PROOF_KEYWORDS` are module-level
  functions and frozensets, and can be patched the same way (reassign
  `coarse.review_stages._detect_section_focus`; rebuild `coarse.structure._TYPE_KEYWORDS`).

The cost is that the overlay is coupled to private names (`_TYPE_KEYWORDS`,
`_detect_section_focus`). Upstream can rename them without warning. Mitigate with a
startup assertion that each patch target exists and has the expected type — a five-line
check that turns a silent no-op into a loud failure. That check is the difference between
an overlay that quietly stops applying after an upgrade and one that tells you.

**Against a hard fork**: you would inherit the whole service infrastructure (cost gate,
web handoff, Modal worker, Supabase callback, i18n) for the sake of editing ~20% of one
file, and the existing fork is already 74+ commits behind, which is exactly how that ends.

**Against a patch stack on the fork branch**: workable given the low churn, and strictly
simpler to write than an overlay. Choose this if the overlay's private-name coupling
bothers you more than the periodic rebase does. The two options are close; the overlay
wins mainly because it keeps you on released PyPI versions.

---

## 8. Do field-specific forks already exist?

**No field-specific fork exists.** Six of 39 forks have real commits; none adapts the
review content to a field.

Compared every fork's default branch against upstream `dev` (all forks default to `dev`).
Six diverge, verified individually:

| Fork | Ahead | What it changes |
|---|---:|---|
| `marcdordal/coarse` | 9 | PyMuPDF extraction, OpenRouter key handling, referee-report script, LaTeX title handling |
| `arthur-albuquerque/coarse-skills` | 9 | Strips the app down to a standalone Claude Code / OpenCode skill; PyMuPDF auto-extraction; installer |
| `mzchou/coarse` | 7 | **Replaces the arXiv literature fallback with OpenAlex** for broader coverage; deeper search; multi-file LaTeX `\input` inlining |
| `fbelotti/coarse` | 3 | CI workflow fixes |
| `erdeyl/coarse` | 2 | CI workflow fixes |
| `fditraglia/coarse` | 1 | Personal usage notes on an econometrics paper |

Every one is infrastructure — extraction, packaging, CI, literature plumbing. Not one
touches `prompts.py` rubric content. The remaining 33 forks carry no commits at all.

**`mzchou/coarse` is directly reusable.** It already did §4(e): swapped the arXiv fallback
for OpenAlex, explicitly to fix coverage for social science. Seven commits, MIT, and you
have OpenAlex keys. Lift it rather than writing it. It is 81 commits behind upstream, so
port the diff, don't merge the branch.

**`arthur-albuquerque/coarse-skills` is worth a look for packaging**, not content — it is
the "run coarse as a Claude Code skill without API keys" pattern, which overlaps what your
existing `coarse-review` skill does. Albuquerque works in medical meta-research, so this
is the closest anyone has come to a field adaptation, and it is purely architectural.

Method caveat: default branches only. A fork could hold field work on a side branch and
not show here.

**Upstream is moving further into formal mathematics, not toward field breadth.** The
active roadmap is issue #255, "evidence-first Deep Agent, Lean verification, and open
evaluation" (narrowed 2026-08-27). Issue #268 is titled "build pinned Lean/Mathlib
**domain packs**" — but "domain pack" there means a pinned Lean + Mathlib build
environment (base / economics / statistics-ML-theory), with tools for `lean.check`, goal
inspection and premise retrieval. It is a formal-proof-checking substrate, not a rubric
plugin system. If you saw "domain packs" in a changelog and hoped it was your extension
point, it is not.

Nothing in the open or closed issue list mentions psychology, management, medicine,
reporting standards, effect sizes, or configurable prompts.

One upstream item is directly useful to you: **issue #260**, "allow evidence-based
abstention and remove forced-comment minima" — it changes every section contract from
"produce 1-5 comments" to "0-5", because the forced minimum makes false positives
structural. That matters for psych review, where the current floor guarantees the agent
invents a comment per section. Worth tracking, and an argument for the overlay approach
that lets you pick it up on upgrade. Note its scope line: *"Preserve proof, literature,
methodology, discussion, and general-section specialization"* — upstream is explicitly not
adding a results rubric.

**Version note.** The task brief referenced v1.9.2; the newest *tag* is **v1.9.1** (commit
dated 2026-08-27, matching PyPI `coarse-ink` 1.9.1), with a `codex/release-v1.9.2-prep`
branch in flight, so v1.9.2 is unreleased. The GitHub Releases list is stale (newest entry
v1.1.3) — use tags, not releases. The measured gap from your fork is **74 commits**
(v1.4.0 → v1.9.1), not 84. Upstream's integration branch is `dev`; `main` is production.

**Comparable tools.** No AI reviewer aimed specifically at psychology or management
surfaced in the fork or upstream analysis. **The web sweep for non-economics mentions of
coarse.ink did not complete** — this session's WebSearch budget was exhausted and the
fallback fetches returned nothing usable, so whether psych/management researchers are
using coarse is genuinely unresolved rather than answered negatively. Rerun in a fresh
session if it matters. Direct fetches of coarse.ink and the PyPI page describe the tool as
discipline-agnostic and make no field-specific claim. The verdict here does not depend on
this: zero field-specific fork divergence is the load-bearing fact and it is settled.
The nearest field-specific machinery is single-purpose statistical checkers
(statcheck for p-value consistency, GRIM/SPRITE for reported-mean plausibility) rather
than review pipelines. Those are complements, not substitutes: statcheck's check is
exactly the kind of item worth naming in the Results rubric, and running the real
statcheck alongside coarse is cheaper and more reliable than asking an LLM to imitate it.

---

## 9. Recommended sequence

1. **Half a day — code fixes.** Invert `_detect_section_focus` precedence; add psych
   headings to `_TYPE_KEYWORDS`; drop `"we show that"` / `"it follows that"` from
   `_PROOF_KEYWORDS`; register a `results` key in `SECTION_SYSTEM_MAP`. Run stock coarse
   on one psych paper before and after; the routing change alone should visibly improve
   the output.
2. **One day — the Results rubric.** The highest-value single artifact.
3. **One day — methodology rubric plus the editorial and critique gates.** These must ship
   together, per §2.
4. **One day — overview and completeness rubrics.**
5. **Half a day — static `DomainCalibration`**, replacing the runtime-invented rubric.
6. **Ongoing — validation** on papers with known flaws.

Stop after step 3 if the output is already useful. Steps 4-5 are refinement.

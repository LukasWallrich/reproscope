# Does the "6% precision" figure for LLM error detection transfer to social science?

Fact-check of the SPOT / FLAWS numbers cited in
`/Users/lukaswallrich/Documents/Coding/reproduction_pipeline/research/research_statreview_multiverse.md`
(lines 10–13, 171–180). Compiled 2026-08-31. All numbers below were read from the
primary PDFs, not from secondary summaries.

---

## Bottom line

The 6.1% precision figure is real, correctly cited, and **the wrong anchor** for a
social-science statistical-review stage. Three independent reasons:

1. **Domain.** SPOT contains no psychology, no social science, no economics, no
   management papers. Zero.
2. **Error mix.** 70% of SPOT's errors are mathematical derivations and image
   forensics. Only 4 of 91 errors (4.4%) are statistical-reporting errors.
3. **The one relevant subscore points the other way.** On SPOT's own
   statistical-reporting category, o3 reaches **88.4% pass@4 / 45.7% pass@1** —
   the best of all six categories, and four times the headline recall.

The 6.1% precision number is also partly an artifact of how SPOT scores. See §1.4.

What *does* transfer from SPOT regardless of field: run-to-run instability (errors
rarely rediscovered across eight runs) and the need for a second human pass.

---

## 1. SPOT's composition

**Citation.** Son, G., Hong, J., Fan, H., Nam, H., Ko, H., Lim, S., Song, J., Choi, J.,
Paulo, G., Yu, Y., & Biderman, S. (2025). *When AI Co-Scientists Fail: SPOT — a
Benchmark for Automated Verification of Scientific Research*. arXiv:2505.11855v1
[cs.CL], 17 May 2025. (NeurIPS 2025 submission.) Verified: title, author list,
abstract, and all numbers below read from the PDF.

### 1.1 Fields — no social science at all

SPOT classifies its 83 manuscripts into **ten domains**, quoting the paper verbatim:

> "Mathematics, Physics, Biology, Chemistry, Materials Science, Medicine,
> Environmental Science, Engineering, Computer Science, and Multidisciplinary,
> based on its journal venue or arXiv subject."

Psychology, social science, economics, management, education and political science
are absent. This is not an oversight of the classification scheme — it follows from
the sourcing. Seeds came from two repositories only:

- **WithdrarXiv** — a dataset of 14,000 retracted arXiv papers.
- **PubPeer** — crawled comments.

The authors explicitly tried and abandoned the two preprint servers that would have
supplied life- and social-science material: "We briefly attempted to include medRxiv
and bioRxiv, but having retrieved only 1 and 13 papers, respectively, we dropped them
due to the low yield." An arXiv-retraction-plus-PubPeer pipeline structurally selects
for physical-science and CS papers.

### 1.2 Error types — 4 of 91 are statistical reporting

SPOT's Table 1, six inductively derived categories with instance counts:

| Category | Description (verbatim) | n | % |
|---|---|---|---|
| Equation / proof | Incorrect mathematical derivations | 37 | 40.7 |
| Figure duplication | Reused or manipulated images | 27 | 29.7 |
| Data inconsistency | Mismatched values between text, tables, and figures | 18 | 19.8 |
| **Statistical reporting** | **Misused statistical values or inappropriate tests** | **4** | **4.4** |
| Reagent identity | Mislabeled or incorrect materials | 3 | 3.3 |
| Experiment setup | Missing controls or misreported protocols | 2 | 2.2 |

Other structural facts: 76 of 83 manuscripts contain exactly one annotated error;
59 errors led to errata, 32 to retractions; manuscripts average 12,887 tokens and
**17.5 images** (max 80). SPOT is a long-context *multimodal* benchmark. A typical
psychology paper has 3–6 figures and no image-forensics surface at all.

### 1.3 The subscore that actually matters

SPOT Appendix G, Table 4 — o3's pass@K broken down by error category (mean over
eight trials):

| Error category | pass@1 | pass@2 | pass@4 |
|---|---|---|---|
| **Statistical reporting** | **45.7** | **62.8** | **88.4** |
| Equation / proof | 33.6 | 51.6 | 67.5 |
| Reagent identity | 22.0 | 40.7 | 62.7 |
| Data inconsistency | 13.1 | 19.4 | 25.7 |
| Experiment setup | 0.0 | 0.0 | 0.0 |
| Figure duplication | 0.0 | 0.0 | 0.0 |

The headline 21.1% recall is a weighted average dragged down by the 27 figure-
duplication items on which o3 scores exactly zero (a reasoning model doing image
forensics), plus the two experiment-setup items. On the category closest to the
proposed pipeline stage, o3 finds the error 46% of the time in one pass and 88% of
the time within four.

**Caveat that must travel with this number: n = 4.** Four instances, so the
confidence interval is enormous (SD 17.2 at pass@1). It is not evidence that LLMs are
good at statistical review. It *is* enough to refuse SPOT as evidence they are bad
at it.

The same pattern appears by paper category (o3 pass@1): Mathematics 34.3, Physics
33.7, Computer Science 21.0, Multidisciplinary 20.0, Materials Science 14.2,
Biology 5.1, Environmental Science 5.1, **Chemistry 0.0, Engineering 0.0,
Medicine 0.0**. Performance is concentrated in the formal-derivation domains. What
this shows for psychology is genuinely ambiguous: psychology is neither a
derivation-heavy field (where o3 does well) nor an image/wet-lab field (where it
scores zero).

The multimodality ablation reinforces this. On the 48 figure-independent instances
(SPOT Table 3), o3's recall rises from 21.1% to **34.6%** and pass@4 from 37.8% to
**61.1%**. Remove the image forensics and the benchmark looks substantially different.

### 1.4 The precision metric is partly an artifact

SPOT's evaluation protocol, verbatim:

> "We treat the error annotations included in SPOT as exhaustive: any model-reported
> error not matching an annotation is counted as a false positive. Although models
> could, in principle, flag genuine errors outside our annotations, through case
> studies later in this paper, we notice such cases are highly unlikely."

With 91 annotations across 83 papers (~1.1 per paper), a model that reports *k*
errors per paper has a maximum achievable precision of about 1.1/k **by
construction** — a genuine error the original authors never acknowledged scores as a
false positive.

Derived from the reported figures (my arithmetic, not the paper's): recall 21.1% of
91 gives ~19 true positives; precision 6.1% then implies ~295 false positives, i.e.
**~3.8 flags per paper**. The ceiling at that flag rate is ~29%, not 100%. So 6.1%
against a 29% ceiling, not against 100%.

The authors' defence of "highly unlikely" rests on an expert case study of **two**
papers (one pure mathematics, one materials science) — and that case study itself
found one genuine unannotated error, which they concede: "this error is the only
instance in which we observe an LLM identifying an unannotated but genuine error."
Their own Limitations section then walks it back: "the complexity of scientific
manuscripts means some true errors may be unannotated."

**Conclusion on §1:** 6.1% is a valid statement about "fraction of o3's flags that
matched one of 91 author-acknowledged errors in physical-science and CS papers,
mostly proofs and image duplications." It is not an estimate of how often an LLM's
flag on a psychology paper is a real problem.

---

## 2. FLAWS — the 39.1% figure is ML-only, and is not a precision measure

**Citation.** Xi, S., Rao, V., Payan, J., & Shah, N. B. (2025). *FLAWS: A Benchmark
for Error Identification and Localization in Scientific Papers*. arXiv:2511.21843,
26 Nov 2025. Verified from PDF.

- **Corpus: ICML 2025 papers only.** From the paper's own limitations: "Currently,
  FLAWS consists only of papers from ICML 2025, which are primarily focused on AI and
  ML. Expanding to fields such as physics, economics, and other disciplines would
  allow us to evaluate the generalizability of our framework." Even the authors do
  not claim cross-domain transfer.
- **Error taxonomy is ML-shaped**: algorithm/proof errors, errors in reported results,
  implementation errors (wrong algorithm, plotting or training procedure),
  inconsistencies in definitions, errors in core assumptions, incorrect/incomplete
  analysis.
- **It measures recall, not precision.** "Identification accuracy at k = 10" is the
  fraction of seeded errors recovered within the model's top-10 ranked candidates.
  FLAWS reports no precision figure. The k = 1 numbers are the harsher story:
  "the identification accuracy is only 5–10% across all evaluated models."
- Errors are LLM-inserted, so the benchmark measures detection of synthetic errors,
  not naturally occurring ones.

**Conclusion on §2:** correctly cited in the existing report, but it is a recall
number on machine-learning papers with seeded machine-learning errors. It says
nothing about precision in any field.

---

## 3. The rubric-constrained middle ground

### 3.1 "To Err Is Human" — where the 83.2% comes from

**Citation.** Bianchi, F., Kwon, Y., Izzo, Z., Zhang, L., & Zou, J. (2025). *To Err
Is Human: Systematic Quantification of Errors in Published AI Papers via LLM
Analysis*. arXiv:2512.05925. Verified from PDF.

**The scope that produced 83.2%**, verbatim: "we restrict our focus to objective
errors — those in formulas, derivations, calculations, figures, and tables — that
have a clearly verifiable ground truth." Novelty, writing quality and other
subjective criteria are excluded by design.

Both halves of the validation, which the existing report only gives one of:

- **Precision 83.2%** — 60 papers sampled, 316 flags, human authors verified 263 as
  genuine. Important selection caveat: the 60 papers were "randomly sample[d] ...
  [from those] that contain at least one potentially substantive mistake as flagged
  by the AI Checker," so precision is measured on the checker's own hit set.
- **Recall 60.0%** — measured separately on 90 mistakes injected into 15 copies of
  five papers the authors themselves wrote. By category: **Math/Formula 66.7%,
  Table/Figure 61.9%, Text 55.9%, Cross-reference 53.8%.**
- Base rate: 4.66 mistakes per paper (SE 0.04) across 2,500 ICLR/NeurIPS/TMLR papers;
  99.2% of papers had at least one flagged mistake.

The load-bearing lesson: **83.2% precision at 60% recall**, on deterministic
recomputable checks, with the model required to name the specific formula, number,
table cell or cross-reference it disputes. Both numbers are needed — the scope
restriction bought precision without collapsing recall.

### 3.2 Deterministic tools set the ceiling for the checkable classes

For the specific error classes named in the question (test-statistic/p-value
inconsistency, impossible descriptives, N mismatch), deterministic algorithms already
outperform any LLM and should own the arithmetic:

- **statcheck**: sensitivity 85.3–100%, specificity 96–100%, overall accuracy
  96–99.9% — but only on results reported in complete APA style with test statistic,
  df and p in order. Roughly 61% of tests are parsed at all.
- **GRIM**: sensitivity >83%, specificity >96%, accuracy >92%.

Both sets of figures as summarised in Alnaimat, F., AlSamhori, A. R. F., El Sharu, H.,
Othman, L., Oralbek, A., & Zimba, O. (2025). *Artificial Intelligence in Detecting
Statistical Errors: Implications for Authors, Reviewers, and Editors*. Journal of
Korean Medical Science, 40, e342. doi:10.3346/jkms.2025.40.e342. Note this is a
narrative review, not primary validation; the underlying statcheck figures trace to
Nuijten & Polanin's validity work. The same review reports "AI has moderate accuracy
overall but performs better in controlled settings" and a 52% pooled diagnostic
accuracy across general LLM applications.

Practical implication: the LLM's job in these classes is **extraction** (pull the test
statistic, df, p, N, M, SD out of prose and tables) and the deterministic tool's job
is the **check**. That splits the error surface: extraction errors are auditable,
arithmetic is exact. This is also what the `ERROR` R package does
(github.com/ianhussey/ERROR — statcheck + GRIM + GRIMMER + SPRITE + effect-size
recalculation, with no LLM component).

---

## 4. Field-specific evidence: what exists and what does not

### 4.1 No psychology-specific LLM error-detection benchmark exists

Searched OpenAlex (title+abstract, 2024-06 onward) across ~10 query formulations
covering LLM error detection, statistical reporting errors, GRIM, statcheck,
methodological-flaw detection, AI peer review of psychology manuscripts, and
retracted-psychology-paper detection. **No study evaluates LLM open-ended error or
flaw detection on a corpus of psychology, management or social-science papers with
known errors.** This absence is itself a finding: neither 6% nor 83% has been
measured in the target field.

Adjacent benchmarks that exist are all in other fields: MolErr2Fix (chemistry,
arXiv:2509.00063), BioKGBench (biomedical, arXiv:2407.00466), PRISMM-Bench,
CORE-Bench.

### 4.2 The ERROR project — human baseline, psychology corpus, no LLM arm

error.reviews, run from Malte Elson's Psychology of Digitalisation group at Bern with
Ian Hussey and Ruben Arslan; stated payout pool 250,000 CHF.

- Elson, M. (2024). *Pay researchers to spot errors in published papers*. Nature, 629,
  730. doi:10.1038/d41586-024-01465-y. (Crossref lists Elson as sole author.)
- Nowogrodzki, J. (2024). *Cash for errors: project offers bounty for spotting
  mistakes in published papers*. Nature. doi:10.1038/d41586-024-02681-2.
- *Offering scientists cash to spot errors in published papers doesn't work*. Science
  (2026). doi:10.1126/science.zh9l2q0. **[body not retrieved — science.org returns
  403; title and DOI verified via redirect resolution only]**

The completed-reviews list is entirely psychology and adjacent social science:
Fernbach et al. (2019) on GM-food opposition; Lades et al. (2020) on COVID emotional
well-being; Hehman et al. (2018) on police lethal force and regional racial bias;
Cikara et al. (2014) on intergroup empathy; Joel et al. (2017) on predicting romantic
desire; Wessel (2018) on go/no-go paradigms. **[6 completed reviews visible at time of
check; per-paper error counts and severities not extracted]**

**ERROR has no LLM arm.** It is the right corpus and the right error distribution for
the question, and nobody has run models against it. That is the single most useful
evaluation that could be built here, and it is cheap: the reviews are public and the
errors are expert-confirmed.

### 4.3 The closest social-science evidence: automated reproducibility, not error detection

**Citation.** Holtdirk, T., Marcolongo, P., Steinberg Schulten, A., Henninger, F.,
Rose, S., Ball, S., Ma, B., Kreuter, F., Weinmann, M., & Feuerriegel, S. (2026).
*Automated reproducibility assessments in the social and behavioral sciences using
large language models*. Research Square preprint,
doi:10.21203/rs.3.rs-10313775/v1, posted 2026-08-05, CC BY. Verified from PDF.

Design: N = 180 published studies from **psychology, political science and economics**
with predefined claims. An agentic pipeline (primary model Claude Opus 4.7; GPT-5.5
and GLM-5.1 as robustness checks) receives the original dataset and the focal claim,
writes and executes its own analysis code, and is run five times per study.

Results, verbatim from the abstract:

> "For 11 studies, the LLM pipeline could not produce a viable effect size estimate.
> For the remaining studies, the LLM reached the same qualitative conclusion as the
> original study in 80% of cases, and recovered the original effect sizes (using a
> ±0.05 tolerance in Cohen's d) in 24% of studies. In a subset with human reanalyses,
> the LLM reached the same qualitative conclusion as the original study in 95% of
> studies, similar to human reanalysts (83%), and the LLM recovered the original
> effect sizes using a ±0.05 tolerance in 40% of studies, again broadly similar to
> human reanalysts (28%)."

This is a reproduction task, not error detection, so it yields no precision figure.
Its relevance is as a competence check on the underlying capability: on
social-science analytic reasoning, a frontier model performs **at the level of human
reanalysts** (Multi100 comparison). That is inconsistent with the "student-level
misconceptions" characterisation SPOT applies to models reading algebraic-geometry
papers.

### 4.4 The counter-evidence that does transfer

**Dycke, N., & Gurevych, I. (2025/2026).** *Automatic reviewers fail to detect faulty
reasoning in research papers*. arXiv:2508.21422. Papers paired with counterfactual
versions containing injected **logical** flaws; injected flaws had no significant
effect on the reviews produced. Output essentially invariant to whether the paper's
logic was sound. **[cited from the existing report; PDF not independently verified in
this pass]**

This is the finding that should worry the interpretive half of a review stage, and it
is not a domain-mismatch objection — reasoning flaws are reasoning flaws. It also
tested *holistic review prompts*, which is the condition every comparative study finds
worst.

---

## 5. What precision to expect, by error class

The right unit is not "a paper" but "an error class." Anchors, best available:

| Class | Nearest measured anchor | Expected precision | Confidence |
|---|---|---|---|
| Test-statistic ↔ p-value inconsistency | statcheck: specificity 96–100% | >95%, if the LLM only extracts and statcheck computes | High |
| Impossible descriptives (GRIM/GRIMMER) | GRIM: specificity >96% | >95%, same split | High |
| N mismatch across text/tables/abstract | SPOT "data inconsistency" o3 pass@1 13.1 / pass@4 25.7; To Err Is Human cross-reference recall 53.8% | 60–80% precision, but **low recall** — this is the weak class | Medium |
| Values inconsistent between text, tables and figures | To Err Is Human 83.2% precision / 61.9% Table-Figure recall | ~80% | Medium |
| Inappropriate test / misused statistic | SPOT "statistical reporting" o3 pass@1 45.7 / pass@4 88.4 (n=4) | Unquantified; plausibly 50–80% under a tight rubric | Low |
| Causal overclaiming from correlational design | **Nothing measured.** Nearest: Dycke & Gurevych — reviews invariant to injected logical flaws | Unknown; assume low without local validation | None |
| Design appropriateness, analytic-choice judgement | **Nothing measured** in any field | Unknown | None |

### Is 6% a fair anchor?

**No.** It is a domain mismatch (no social science in the corpus), an error-mix
mismatch (70% proofs and image forensics), and a metric artifact (single-annotation
exhaustiveness caps achievable precision near 29%). SPOT's own
statistical-reporting subscore runs the opposite direction.

**A defensible planning range for a rubric-constrained stage:** 70–85% precision on
the deterministic and cross-reference-checkable classes, matching To Err Is Human's
83.2% — conditional on three design constraints that every comparative study supports:

1. **Decompose into named checks.** Targeted "find X" prompts beat holistic
   "review this paper" in every study that compared them. Dycke & Gurevych is the
   worked example of the holistic failure.
2. **Require a binding.** The model must cite the specific claim and the specific
   number it disputes, and the flag is scored on that binding, not on the prose.
   This is what makes 83.2% verifiable at all.
3. **Aggregate across runs.** SPOT's eight-run instability is field-independent.
   Single-pass output is not a stable measurement; pass@4 roughly doubles pass@1 in
   every SPOT category that is non-zero.

For the **interpretive** classes — causal overclaiming, design appropriateness,
analytic-choice judgement — the honest answer is that nobody has measured it in any
field, and the one adjacent result (Dycke & Gurevych) is discouraging. Do not carry a
number for those. Generate one locally: seed known interpretive flaws into a small
set of psychology papers, or run against the ERROR project's six public expert
reviews, and measure.

---

## 6. Suggested corrections to the existing report

`research_statreview_multiverse.md`, lines 10–13 and 171–180. Each is an addition,
not a retraction — the numbers as printed are accurate.

1. Line 11, SPOT row: add the corpus scope — "ten physical-science, life-science and
   CS domains; no social science" — and the error mix (37 equation/proof, 27 figure
   duplication, 4 statistical reporting).
2. Line 11: add the subscore. o3 reaches 88.4% pass@4 on SPOT's statistical-reporting
   category (n = 4) and 0.0% on figure duplication. The 21.1% headline is a weighted
   average over a mix that does not resemble a psychology paper.
3. Line 11: note that precision treats the 91 annotations as exhaustive, with ~1.1
   annotations per paper, so achievable precision is capped near 29% at o3's observed
   flag rate.
4. Line 10, FLAWS row: add "ICML 2025 papers only" and note that identification
   accuracy is recall, not precision; the authors flag the domain limitation
   themselves.
5. Line 177, To Err Is Human row: add the recall half — 60.0% overall on 90 injected
   errors (Math/Formula 66.7, Table/Figure 61.9, Text 55.9, Cross-reference 53.8) —
   and the selection caveat that the 60 precision papers were drawn from the
   checker's own hit set.
6. Line 13, the framing sentence: "Precision is bought by narrowing scope, not by
   better prompting" survives, but the sentence should not imply 6.1% is the
   unnarrowed baseline for this field. It is the unnarrowed baseline for
   author-acknowledged errata in mathematics, physics and biology papers.
7. Add §4.3 (Holtdirk et al. 2026) as the field-matched competence anchor, and §4.2
   (ERROR) as the field-matched evaluation that has not been run.

---

## 7. Verification status

**Verified from primary PDF:** SPOT (arXiv:2505.11855v1) — domains, error taxonomy
and counts, Table 1 statistics, Table 2 precision/recall, Table 3 text-only ablation,
Appendix G Table 4 per-category and per-domain pass@K, evaluation protocol, case-study
and limitations text. FLAWS (arXiv:2511.21843) — abstract, ICML-2025-only corpus,
error category list, k = 1 accuracy range, domain limitation. To Err Is Human
(arXiv:2512.05925) — scope statement, precision and recall protocols, 83.2% / 60.0%,
per-category recall, 4.66 mistakes/paper. Holtdirk et al. (rs.3.rs-10313775/v1) —
title, full author list, abstract verbatim, design, models.

**Verified via metadata / landing page only:** Alnaimat et al. JKMS 2025 (fetched, but
it is a narrative review — statcheck and GRIM figures are secondhand there and should
be re-sourced to Nuijten's validity study before being quoted in a manuscript).
error.reviews completed-review list.

**Not verified:** Science (2026) doi:10.1126/science.zh9l2q0 — 403 from science.org;
only the title and DOI resolution were confirmed. Dycke & Gurevych arXiv:2508.21422 —
carried over from the existing report, not independently read in this pass.

**Search coverage limit:** WebSearch quota was exhausted for the session. Literature
search used the OpenAlex API (title+abstract, ~10 query formulations) and direct
fetches; arXiv's API rate-limited. A psychology-specific LLM error-detection study
published very recently and not yet indexed in OpenAlex could have been missed,
though the ERROR group's own output would be the likeliest source and shows no such
arm.

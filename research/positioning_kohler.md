# Positioning brief: the new review instrument against Kohler et al. (arXiv:2604.21965)

Source read in full: `https://arxiv.org/html/2604.21965v1`, extracted to
`/private/tmp/claude-501/-Users-lukaswallrich-Documents-Coding-reproduction-pipeline/091360f7-0790-417e-a3e0-7223c3dd800f/scratchpad/kohler.txt`
(18,333 words, main body + Appendices A–C including all prompts). Every number and quotation below
comes from that text.

Kohler, B., Zollikofer, D., Einsiedler, J., Hoyle, A., & Ash, E. (2026). *Read the Paper, Write the
Code: Agentic Reproduction of Social-Science Results*. arXiv:2604.21965v1 [cs.AI], 23 April 2026.
ETH Zurich (Einsiedler: University of Basel). Hoyle and Ash share equal supervision.
Contact: benjamin.kohler@gess.ethz.ch, ashe@ethz.ch.

---

## 1. What Kohler et al. actually did

### 1.1 Task setup

The agent's input is an **extracted methods description, blinded table templates, and the original
data** — nothing else. Withheld: the paper PDF, the original analysis code, and all numerical
results.

- **Methods description.** An LLM reads the complete PDF and emits a structured methods document:
  research question, setting, data sources, general and per-table data manipulations, and per-table
  structure (caption, exact row and column labels, panel structure, table-specific filters,
  regression specifications, fixed effects, clustering, sample restrictions). The extraction prompt
  (Appendix C1) says verbatim: *"Never include: regression coefficients, standard errors,
  t-statistics, p-values, significance stars, point estimates, confidence intervals, effect sizes, or
  descriptions of direction/magnitude."*
- **Leak check on that document.** *"The model is explicitly instructed not to include any numerical
  results or conclusions, verified by checking for any numerals in the table description."* A
  deterministic numeral scan.
- **Blinded templates.** The results extractor returns a structured table where each cell carries row
  and column indices plus label names, and each cell's string content is decomposed into a numeric
  value, a metric-type classification (coefficient, standard error, p-value, R², N, F-stat, other), a
  significance-star count, and — for SEs and p-values — a pointer to the parent coefficient. The
  template is that object with **all values and star counts set to null**.
- **Data.** GPT-5-mini reads the full directory tree and README of the reproduction package and picks
  the *least pre-processed, minimum-viable* data files. It also classifies whether the package has
  enough data to reproduce the paper at all; papers with no usable data are skipped.
- **Sandbox.** Each agent gets a workspace with `TASK.md`, `methodology_summary.json`,
  `table_templates/*.json`, a symlink to the data, and scaffold-specific instruction files. The
  original replication package and paper PDF **sit on the same machine but outside the workspace
  boundary**. File access outside the workspace is blocked; web retrieval of the package or paper is
  prohibited; *"Web access was restricted using the agent scaffold's configuration to the extent
  possible."*
- **Output.** One Python script per table, run on the original data, filling in that table's
  template. (Original packages are Stata 54%, R 27.1%, zero Python — so agents always cross
  languages.)

Their stated reason for the isolation, in a footnote aimed at ReplicatorBench: *"in preliminary
versions of our setup where models had access to results, agents would often copy them directly."*

### 1.2 Blinding integrity: a two-stage audit plus a hardcoding audit

- **Regex scan (deterministic).** Every absolute path and URL in the raw event trace is classified as
  `allowed_workspace`, `allowed_data`, `forbidden_replication_package`, `forbidden_paper_pdf`, or
  `forbidden_external`. URLs and web keywords (`curl`, `wget`, `requests`) are flagged separately.
- **LLM review.** GPT-5.4-mini reads the normalised event trace and workspace artifacts and labels
  breaches as `external_result_lookup`, `forbidden_paper_access`, or `forbidden_code_access`, each
  with artifact, line range, severity, confidence, and an evidence chain. Run-level verdict runs
  `clean` → `severe_violation`, plus `insufficient_evidence`. The authors report the LLM review is
  **over-inclusive**; severe cases are manually inspected and rerun if a breach is confirmed.
- **Hardcoding audit (separate).** GPT-5.4-mini looks for numeric literals that appear as statistical
  results with no computation path from the data. Runs classified `clean` (n=299) average grade 3.02
  (≈C); non-clean runs (n=37) average 2.50 (≈D). Hardcoding does not inflate grades.

### 1.3 Pipeline architecture (four steps)

| Step | What | Model / determinism |
|---|---|---|
| 1a Method extraction | Structured methods doc, results-free, numeral-scanned | LLM on full PDF |
| 1b Results extraction + blinding | Cells with indices, decomposed into value / metric type / stars / parent coefficient, then nulled | **GPT-5-mini on the PDF rendered as page images** |
| 1c Data identification | Minimum-viable least-preprocessed files; skip packages with missing data | GPT-5-mini |
| 2 Reimplementation | Sandboxed agent, one Python script per table | 7 scaffold × model configurations |
| 2b Guardrail + hardcoding audits | Regex path/URL classifier; LLM breach reviewer; literal-without-computation-path check | regex + GPT-5.4-mini |
| 3 Evaluation | Cell alignment (with power-of-ten rescale), sign, % difference, SE-scaled difference, letter grades, cell→table→paper | **fully deterministic, no LLM judge** |
| 4 Explanation | Locate the relevant code in *both* the original package and the agent script, describe the discrepancy, bucket the root cause | GPT-5.4 + Codex CLI, plus an LLM auditor |

Two statements to quote in any related-work paragraph:

> *"Separating the pipeline into distinct steps minimizes information leakage of both existing
> numerical results and original code to the agents."*

> *"Unlike some of the prior work, our approach avoids the ambiguity and opacity of LLM-judges."*

**Vision beats text for table extraction:** *"Table parsing uses GPT-5-mini applied to the PDF
rendered as images, which we found to outperform extraction from machine-readable PDF text."*
Validated by hand on a random 5 papers / 24 tables: perfect on portrait tables, occasional errors in
the 2nd–3rd decimal on landscape or multi-page tables.

**Figures are handled but not scored.** The extractor writes an axes/structure description plus a
Python plotting template; a vision model grades A–F (visually indistinguishable → fundamentally
different). The authors decline to report quantitative figure results because *"whether such models
can provide fair and consistent evaluations remains an open question."*

### 1.4 Models and scaffolds

Four LLMs: GPT-5.4, GPT-5.3 Codex, Claude Opus 4.6, and open-weights **GLM-5**. Four scaffolds:
Claude Code, Codex CLI, mini-SWE-agent, OpenCode. Seven combinations run (both open-source scaffolds
run GPT-5.4 and GLM-5).

### 1.5 Corpus

**48 papers**, every paper I4Replication classified as *fully reproducible*. Economics 29 (AER 8,
EJ 9, AEJ:Pol 5, AEJ:AE 3, REStud 2, AEJ:Macro 1, QJE 1); political science 19 (AJPS 11, JOP 5,
APSR 3). Original code: Stata 54%, R 27.1%, no Python; packages average 5,324 lines.

Extracted elements: **222 tables, 14,214 cells** — 5,149 coefficients, 4,253 standard errors, 1,701
N-observations, 1,607 other numeric, 779 p-values, 590 R², 121 F-stats, 112 CIs, 10 t-stats.
Only tables in the published journal PDF are included; **online-appendix tables are excluded, and
about 8% of tables from 18 papers are dropped for extraction failures**.

### 1.6 Tolerance scheme (exact)

Cells are aligned first, with **rescaling when an approximate power-of-ten mismatch is detected**.
Reproduced values are **rounded to the number of digits reported in the original paper** before
comparison.

| Grade | Near-zero original (\|x\| < 0.001) | Otherwise |
|---|---|---|
| A | absolute difference < 0.002 (also when both are exactly zero) | percentage difference < 2% |
| B | < 0.02 | < 20% |
| C | < 0.05 | < 40% |
| D | < 0.1 | < 60% |
| E | ≥ 0.1, **or signs differ** | ≥ 60%, **or signs differ** |
| F | either the original or the reproduced value is missing | |

Aggregation: A=5 … E=1, F=0; average over **non-F cells only**; map back with fixed thresholds
([4.5,5]→A, [3.5,4.5)→B, …). Paper grades average table grades the same way, excluding unverifiable
items, flagged judge errors, and F grades. A table is F only if every cell is F.

Alongside the grades they report sign agreement and the **coefficient difference scaled by the
original standard error**, compared against 1.96.

### 1.7 Headline results

- **Completion.** Usable results for 92–100% of papers, 82–97% of tables, but only **52–72% of
  cells**. Best overall completion: Claude Code + Opus 4.6 (72% of cells, 100% of papers). Worst:
  mini-SWE-agent + GLM-5 (52% of cells). Coefficients complete at 82% on average, SEs at 80%.
- **Sign agreement** (missing coefficients excluded): 78% (SWE-Agent GPT-5.4) to **91% (OpenCode
  GPT-5.4)**. Naive "guess positive" baseline is 68%.
- **Within the 95% CI** of the original (|difference| / original SE < 1.96): over 50% even in the
  worst configuration; **over 80% for OpenCode GPT-5.4**.
- **Exact reproduction.** The strongest models reproduce **more than 40% of coefficients and standard
  errors exactly**.
- **Table and paper level.** Best configurations grade A (average cell within 2%) on **more than a
  fifth of tables** and B or better on **more than 60%**. Agent rankings compress at paper level.
- **Effort explains the ranking.** OpenCode GPT-5.4 wins by spending far more — more tokens, more
  time, more money, more than twice the tool calls of any other setup. The authors' reading:
  *"differences in observed accuracy may partly reflect differences in implicit compute budgets
  rather than purely differences in capability."*
- **Error sources (Figure 7).** Five buckets: agent error, extractor error, original error, data
  missing, other/unknown. **Over three-quarters of divergences trace to a specific, interpretable
  source.** The **largest single share is "original error"** — mismatch between the paper and the
  underlying code. Missing data is another substantial share. Agent error is second-largest overall
  and **declines markedly for the strongest agents**. *No per-cause percentages are printed in the
  text; Figure 7 is a bar chart and its values are not recoverable from the HTML render. Do not quote
  a numeric breakdown.*
- **Re-run stability.** Three runs each on 20 random papers, with Claude Code and Codex GPT-5.4.
  **More than 80% of tables vary by at most one grade step.** But at the coefficient level, *"about
  half of estimated coefficients are statistically different from themselves … across run pairs."*
  Their own conclusion: *"fine-grained comparisons between agents should be interpreted with caution,
  especially when differences are small."*
- **Inter-agent agreement (Appendix A.6, Figure A8).** Share of papers where two agents assign the
  same grade, and where grades are within one step. Finding: *"agents—particularly those developed by
  the same organization—tend to agree more than would be expected by chance, though between-agent
  performance nonetheless varies substantially."*
- **Within-paper difficulty (Figure A9).** Worst-to-best grade range across all agent–model
  combinations stays within two grade steps for most papers.
- **Contamination.** Five EJ papers before and five after the model knowledge cutoff, run on Claude
  Code (Opus 4.6) and Codex (GPT-5.4). No statistically significant difference; if anything
  post-cutoff is slightly higher.
- **Correlates.** Descriptive-statistics tables are easier than results tables; main, mechanism and
  robustness tables perform similarly. Political science reproduces better than economics, and R
  better than Stata or MATLAB — both flagged as selection artifacts of the I4R sample. No
  relationship with dataset size; a modest positive association with the length of reproduced code.

### 1.8 Stated limitations and future work

There is **no dedicated limitations section**, no data-availability statement, and **no repository
URL anywhere in the paper**. The limitations are scattered:

- Methods-extraction quality is load-bearing and imperfect: *"An incomplete or erroneous extraction
  will result in a failed replication … there is likely scope for further improvements."*
- Table extraction misses ~8% of tables; online-appendix tables are out of scope.
- Figure reproduction is implemented but unscored because vision-model grading is not validated.
- Large deviations are often the comparison system's fault, not the agent's: *"the majority stem from
  unit scaling issues not accounted for by our comparison system (e.g., the original authors report
  values in dollars, whereas the dataset is denominated in cents)."*
- The leakage test is small (10 papers), the papers are not independently reproducibility-verified,
  and it *"does not rule out leakage arising during post-training."*
- Discipline and language comparisons are confounded by I4R selection.

**Future work, from the conclusion** — this paragraph is the single most important passage for
positioning:

> *"This perspective extends naturally to a broader spectrum of automated scientific tasks … What if
> the data are unavailable, requiring agents to recover or reconstruct them? What if only the
> research question or hypothesis is given, and methods must be inferred rather than followed? **What
> if agents are tasked not just with reproducing results, but with refining the analysis through
> specification checks, falsification of identification assumptions, or exploration of underlying
> mechanisms?** And what if the goal shifts from reproduction to replication … This shift requires us
> to define new criteria for scientific validity, including how to assess identification, robustness,
> and the reliability of conclusions generated without direct human oversight."*

They also set up the three-way taxonomy explicitly (§2): reproducibility is (1) re-running the
authors' code, (2) reimplementing from the paper's information, (3) *"testing whether results are
robust to reasonable alternative analytical decisions applied to the same data."* Then: **"Our work
falls under (2), re-implementation."** Type (3) is named and disclaimed.

Their normative conclusion is that **the code, not the paper, is the source of truth for what was
done**, and that the paper's job is to explain *why*; automated reproduction should therefore be used
as a **diagnostic for narrative–code misalignment**.

---

## 2. Overlap map — what Kohler already delivers

Read this section as a list of things the new tool should cite rather than claim.

| New tool stage | Kohler status | Detail |
|---|---|---|
| Input regime: paper + data, no code | **Delivered, and stricter** | Kohler's agent never sees the paper PDF either — only the derived methods document |
| Vision extraction on rendered pages | **Delivered** | GPT-5-mini on page images, with the explicit finding that it beats machine-readable text |
| Claims/results table with structured cells | **Delivered** | Row/column indices, labels, value, metric type, star count, parent-coefficient pointer |
| Results-redacted methods document | **Delivered** | Full prompt published in Appendix C1 |
| Deterministic leak check on that document | **Delivered** | Numeral scan over table descriptions |
| Blinding at run time | **Delivered, and harder** | Workspace boundary, path restrictions, web-tool prohibition, package and PDF outside the boundary |
| Blinding *verification* | **Delivered, and more thorough** | Regex path/URL classifier + LLM breach reviewer with severity/confidence/evidence chain + manual inspection and rerun + a **separate hardcoding audit** with an empirical test that hardcoding does not inflate grades |
| Tolerance bands (sign gate, precision rounding, A/B/C, near-zero absolute fallback) | **Delivered — this is Kohler's scheme** | Plus D and E bands, power-of-ten rescaling, and the SE-scaled 1.96 criterion |
| Unblinded divergence diagnosis | **Delivered, and stronger** | Step 4 reads the **original code** as well as the agent script; a second LLM auditor buckets root causes into Human Error (Missing Data; Paper vs Code) and Agent Error (Paper vs Methods Extraction; Method Extraction vs Agent) |
| Multiple runs / repeated sampling | **Partly delivered** | 3 runs × 20 papers × 2 configurations, reported as a robustness check |
| Cross-family model comparison | **Delivered as a benchmark axis** | 4 models × 4 scaffolds, 7 combinations |
| Within- vs between-family agreement | **Partly delivered — see §3** | Figure A8 reports paper-level inter-agent grade agreement and names the same-organisation effect |
| Cheap open-weights family in the mix | **Delivered** | GLM-5 is one of the four models, and full token/time/cost accounting is reported |
| Contamination control | **Delivered** | Pre/post knowledge-cutoff split |
| Multiverse / specification space / m-value | **Not delivered** | Explicitly excluded (type 3) and named as future work |
| Rubric commentary on causal language, power, claim–analysis alignment | **Not delivered** | The paper is strictly numeric |
| Reconstruct-and-re-run arm when code exists | **Not delivered as an arm** | Step 4 *reads* the original code but never executes it; I4R did the execution offline |
| Review-stage use on unverified papers | **Not delivered** | Corpus is 48 papers pre-certified as fully reproducible |

---

## 3. The genuine deltas

### 3a. Claimed deltas that Kohler already has — flag these prominently

These four should be dropped from any contribution list, or reframed as adoptions.

1. **Blinding and redaction integrity is not a delta.** Kohler has the results-free methods document
   with a deterministic numeral check, nulled table templates, a filesystem and web boundary, a
   deterministic regex leak classifier, an LLM breach reviewer with an evidence chain, manual review
   with reruns, *and* a hardcoding audit that the new design does not currently include. Claiming
   this as new invites an immediate reviewer objection. Adopt it and cite it.

2. **Unblinded divergence diagnosis is not a delta.** Kohler's Step 4 is exactly that pass, and it is
   better resourced: it reads the original replication package, so it can attribute a discrepancy to
   "the paper contradicts the code" rather than guessing. The new tool's version, run without code
   access, is *weaker* on the papers where code is absent — the "labeled as conjecture" framing is a
   correct and necessary honesty adjustment, not a capability gain. Frame it that way.

3. **Vision extraction on rendered pages is not a delta.** Kohler did it and published the finding
   that it beats text extraction. What is new is only the **two-model cross-check**: Kohler runs a
   single GPT-5-mini pass validated by hand on 5 of 48 papers, and drops ~8% of tables. A
   cross-checked extractor with a disagreement flag is a real improvement, but a small,
   engineering-grade one. Size the claim accordingly.

4. **Cheap-model batch economics is not a delta.** GLM-5 is in Kohler's grid with full cost
   accounting. Worse, it is their *weakest* configuration — mini-SWE-agent + GLM-5 completes only 52%
   of cells, and OpenCode GLM-5 54%, against 72% for Claude Code + Opus 4.6. Their own analysis
   attributes performance to effort spent, not model identity. So a cheap-model k=6 design buys
   replicate count at a documented cost in cell completion. The defensible framing is that **k
   replicates are the point and cheapness is what makes k affordable** — not that cheap models are
   adequate substitutes. Say so before a reviewer does.

### 3b. Genuine deltas, strongest first

1. **k=6 blinded replicas, with inter-replica agreement as a reported instrument statistic rather
   than a robustness footnote.** Kohler measures the ingredients and treats them as caveats: 3 runs
   on 20 papers, ~50% of coefficients statistically different from themselves across run pairs, and a
   paper-level inter-agent grade-agreement chart. Two things separate the new design.
   *First, the unit of agreement.* Kohler's Figure A8 compares agents on **grades**, which are
   defined against the published values — it is agreement about how well each agent scored, and it
   cannot be computed for a paper with no verified target. The new tool measures agreement among
   replicas on the **reproduced values themselves**, which is defined with no ground truth at all.
   *Second, the role.* Kohler's ~50% self-disagreement result is the field's strongest argument that
   a single agent run is not an instrument, and they draw the defensive conclusion ("interpret
   cautiously"). The new tool draws the constructive one: run k, and report the spread as the
   measurement it is. This is a clean, well-motivated contribution that their own numbers justify.
   **Caveat to state honestly:** their within/between-organisation agreement observation is the same
   idea in embryo, so the claim is "operationalised as a primary statistic on an unverified paper",
   not "first to notice".

2. **The multiverse layer with an m-value.** Nothing in Kohler, disclaimed by their own taxonomy
   (type 3), and named in their conclusion as future work. Their §5.3 finding sets it up precisely:
   agents diverge because papers are underspecified, and *"agents may still reproduce the correct
   result if their implicit assumptions happen to align with the original implementation."* That
   sentence describes an unmeasured quantity — the size of the defensible specification space around
   the published choice — and the m-value is a direct answer to it. The union of (a) the replicas'
   organic disagreements, (b) an enumerated decision grid, and (c) standard-practice defaults the
   paper never mentions, with adversarial screening and a rejection log, also turns Kohler's largest
   error bucket ("original error", i.e. paper–code mismatch) from a benchmark nuisance into the
   instrument's raw material. **This is the strongest single claim to lead with.**

3. **A review-stage instrument rather than a benchmark, with the consequences taken seriously.**
   Kohler's 48 papers are all pre-certified fully reproducible by I4R. Every grade is scored against a
   known-good target, so no grade in the paper answers the reviewer's question — *what does a C mean
   for a paper nobody has verified?* Three concrete design consequences follow, and each is a real
   contribution: (i) coverage must be complete for the paper in front of you, where a benchmark can
   skip papers with missing data and drop 8% of tables; (ii) the output must separate what is
   decision-relevant (step-1 reproduction) from what is context (everything else), where a benchmark
   emits one number; (iii) the failure to reproduce must be reportable **without** an implied verdict
   about the paper, which is exactly what the k-replica spread and the m-value make possible. Kohler
   gestures at this — their conclusion proposes automated reproduction as *"both a tool for
   verification and a diagnostic"* — but they built and validated a benchmark.

4. **Rubric-constrained commentary (causal language vs design, sensitivity and power, claim–analysis
   alignment), labelled as context.** Entirely absent from Kohler, whose scope is numeric agreement.
   This is a genuine addition but the weakest of the four: it is adjacent to a large error-detection
   and statistical-review literature, so its novelty rests on the rubric constraint and the
   non-verdict framing, not on doing commentary at all.

5. **Two-model cross-checked extraction with a disagreement flag** (small; see §3a.3).

6. **A reconstruct-and-re-run arm when code exists, inside the same instrument.** Kohler reads the
   original code only in the diagnosis step and never runs it; execution-based work (REPRO-Bench,
   Shah et al., Xu & Yang) runs code but does not reimplement from the paper. Having both arms under
   one comparison scheme lets the code-vs-paper gap be measured directly on a single study, which is
   the quantity Kohler's normative conclusion is actually about. Modest but real, and cheap to argue.

---

## 4. Positioning recommendation

### 4a. Stance: complement and extend, cite heavily, adopt openly

Kohler is not a competitor to be differentiated from at arm's length. It is the closest prior art,
and the new tool reuses its most defensible components — the tolerance grades, the isolation
architecture, the deterministic-not-LLM-judge evaluation stance. The strongest position is explicit
adoption plus a clearly bounded extension: **Kohler establishes that paper-derived reproduction
works and measures how well; the new tool asks what a single reproduction attempt is worth when
nobody knows the answer in advance, and answers with replicate agreement and the specification
space.** Cite Kohler for the grading rubric by name in the methods section, cite their ~50%
coefficient-level self-disagreement as the motivation for k>1, and cite their conclusion paragraph as
the invitation to do the specification-check work.

Reframe the contribution list now: move blinding integrity, vision extraction, tolerance bands and
cheap-model economics from "contributions" to "adopted from Kohler et al., with the following
modifications". Lead with the m-value.

Two corpus points to state explicitly, since a reviewer will check:
- **No held-out contamination from Kohler.** Their 48 papers are all economics and political science
  (AER, EJ, AEJ, REStud, QJE, AJPS, JOP, APSR), so the quasi-held-out set — I4R × *Psychological
  Science* — cannot intersect them. **Verified from the journal table.** The dev corpora are a
  separate question: Multi100 and ReplicatorBench both draw on older, mostly non-economics social
  science, so overlap is unlikely, but this has **not** been checked. Compare paper identifiers
  against Kohler's Appendix Table A3 (the full list is in `kohler.txt`) before stating it in a
  writeup.
- **Do note the shared I4R provenance.** Both projects draw on I4R material. The new tool's dev
  corpora (Multi100, ReplicatorBench) are independent of I4R, which keeps the split defensible, but
  the overlap should be named rather than left for a reviewer to find.

### 4b. Contacting the authors: yes, and soon

Reasons this is worth doing:
- **The paper has no code or data availability statement and no repository URL.** The pipeline, the
  extraction prompts beyond Appendix C, the per-cell outputs, and the Figure 7 error-source counts
  are all unpublished. The cell-level output for 48 papers × 7 configurations is a directly reusable
  validation asset and would let the new tool calibrate its agreement statistic against a set with
  known ground truth — the exact anchoring a review instrument needs.
- **Figure 7's numbers are not in the text.** If any per-cause percentage is to be cited, it must
  come from the authors.
- **The ask is complementary, not competitive.** The new tool works on the type (3) axis they
  disclaimed and flagged as future work. There is no scooping risk in either direction, and a short
  note to Kohler and Ash saying "we are building the specification-check layer you name in your
  conclusion; can we use your grading implementation and cell-level outputs" is a low-cost, high-yield
  message. Ash's group also sits close to the I4R and ETH replication community, which is the same
  network the review-stage deployment would need.

Send it before the first preprint, not after.

### 4c. The contribution, in one paragraph

> Kohler et al. (2026) showed that LLM agents can reproduce published social-science results from a
> paper's methods description and data alone, and built the deterministic cell-level grading scheme
> that makes such reproductions comparable. We adopt that architecture — results-blinded methods
> extraction with a leak check, sandboxed reimplementation, and their sign-gated tolerance grades —
> and ask the question that follows it: what a reproduction attempt is worth for a paper that no one
> has yet verified. Two changes make it answerable. First, we run k=6 blinded reimplementations
> across three model families and report their mutual agreement, split within and between families,
> as a primary statistic — a measurement that needs no ground truth and that Kohler et al.'s own
> finding, that roughly half of coefficients differ statistically from themselves across repeated
> runs of the same agent, shows to be necessary. Second, where they attribute divergences to
> underspecification in the original paper and stop, we treat that underspecification as the object of
> measurement: we assemble the specification space from the replicas' organic disagreements, an
> enumerated decision grid, and standard-practice defaults the paper leaves unstated, screen it
> adversarially with a logged rejection record, and report an m-value for how extreme the published
> specification is within its own defensible space. The result is a review-stage instrument rather
> than a benchmark. Step-1 reproduction remains the decision-relevant output; the agreement spread,
> the specification space, and a rubric-constrained commentary layer are supplied as context for human
> judgement, and are labelled as such.

---

## 5. Verification notes

- Full text read from the arXiv HTML render of v1 (430 KB, complete through Appendix C). PDF
  downloads from `arxiv.org/pdf/` were throttled and repeatedly truncated; the HTML is the usable
  source.
- Tolerance-band figures in §1.6 come from a separate tag-stripped dump of the raw HTML around
  Table A5, where the LaTeX annotation text survives. The main text conversion dropped the inline
  thresholds. The values are exact as printed.
- **Figure 7 and Figure A8 carry no printed values.** The error-source breakdown and the inter-agent
  agreement percentages are bar charts. Their *direction* is stated in the text and quoted above; no
  per-cause or per-pair percentage should be cited without asking the authors or reading the figures
  from the PDF at full resolution.
- Confirmed absent from the paper: any repository URL, any data or code availability statement, any
  dedicated limitations section, and any execution of the original analysis code.

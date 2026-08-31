# Reproduction Pipeline — Research Synthesis

*Synthesized 2026-08-31 from three commissioned research reports in this directory:
`research_reproduction_sota.md` (AI reproduction benchmarks & pipelines),
`research_statreview_multiverse.md` (statistical checking, LLM review, multiverse tooling),
`research_coarse_fork.md` + `research_coarse_psych_fork.md` (coarse architecture and adaptation).
All headline claims below are sourced and citation-verified in those reports.*

## Goal (as stated)

A clearly documented tool that (1) computationally reproduces papers, (2) evaluates
the appropriateness of statistical choices and interpretation, and (3) tests
robustness — likely via a multiverse with multi-agent review of specifications.

## What the evidence says about each part

### 1. Computational reproduction: execution is near-solved; judgment is not

- Execution stopped being the bottleneck during 2026. Claude Code + recent Opus
  reaches ~78% on CORE-Bench Hard and ~78% paper-level accuracy on
  SocSci-Repro-Bench. The oft-quoted "agents get ~21%" is a 2024 GPT-4o number.
- What remains hard: the reproducibility *verdict* and *diagnosis*. Best verdict
  accuracy is ~45–51%; agents collapse to binary verdicts and rarely explain why
  a reproduction failed.
- Stage separation has causal evidence. PaperRepro's ablation (model held
  constant): merging Setup+Execution or Execution+Scoring drops accuracy ~10–13
  points. Zhu et al. (2026) cut critical failures 72% → 16% by making LLMs reason
  but not execute, handling data deterministically, and adding three binding
  human gates.
- The dominant integrity failure is **fabrication, triggered by giving the
  execution agent the paper PDF**: accuracy on non-reproducible tasks drops
  100% → 63% when the PDF is supplied. Multiple benchmarks find this
  independently. Design rule: the executor never sees the paper's claims; a
  separate extractor produces the target-quantities table.
- Reading the paper is the residual bottleneck: number-extraction/linking is the
  main error source (~87 F1 vs ~99% execution verification). Three teams
  independently converged on the fix: render pages as images and use a vision
  model, not the PDF text layer.
- Tolerance must be explicit. Adopt Kohler et al. (2026): sign gate → round to
  the paper's reported precision → percentage bands (A <2%, B <20%, C <40%) →
  absolute threshold (<0.002) instead of percentages when |x| < 0.001.
- Production precedent exists: the AEA Data Editor's replication template ships
  Claude Code skills (Aug 2026) with per-agent stage boundaries, an independent
  cross-checking pass, and mandatory human sign-off. Operating rule: *"Code that
  runs is not code that reproduces."*
- Environment reconstruction is where most reproductions die before statistics:
  ~74–75% of archived R supplements fail to run; ~99% of OSF R supplements lack
  executable dependency descriptions.

### 2. Statistical appropriateness & interpretation: weakest evidence base

- LLM error detection in papers is poor when open-ended: 21% recall / 6%
  precision on real erratum-causing errors (SPOT); ~39% on seeded errors
  (FLAWS). The only high-precision result (83%) restricted scope to
  arithmetic/formula/table checks.
- **Analytic appropriateness is the least-evidenced capability in the entire
  scan** — no benchmark isolates it. Any such stage needs a seeded-error gold
  set built *first*, before trusting its output.
- Deterministic checkers exist and should be wrapped, not rebuilt:
  **metacheck** (renamed from papercheck; modular: statcheck, effect sizes,
  causal claims, power, prereg consistency, retraction/PubPeer lookups),
  statcheck, JATSdecoder+tableParser, scrutiny/rsprite2 (GRIM/SPRITE), ODDPub,
  rtransparent, RegCheck. Caveats: metacheck modules have no published
  validation; statcheck recall is ~52% of all tests and near 0% from PDF —
  work from source formats and always report coverage alongside flags.
- Interpretation checks carry a specific hazard: LLM summaries *amplify*
  causal overclaiming by stripping hedges, and LLMs are more spin-susceptible
  than humans. Both recover under explicit cautionary prompting. Never feed the
  paper's own abstract as context when judging that abstract.

### 3. Multiverse / robustness: viable, with a clear open niche

- LLM multiverses work at scale (~5,000 runs with a ~67% auditor pass rate in
  the PNAS study) and agents reproduce effects in the same accuracy band as
  human reanalysts (24% vs 34% within ±0.05 d; 40% vs 28% on a matched subset —
  though whether the two studies applied the ±0.05 d tolerance identically is
  unverified, so treat the head-to-head as indicative).
- Bias lives in **interpretation, not estimation**: a confirmatory prompt
  flipped verdicts 10% → 90% with unchanged coefficient distributions. Estimate
  and interpret in separate, differently-prompted (or differently-modeled)
  stages.
- Adopt the **m-value** (Miao, Pritchard & Zou 2026): probability that the
  paper's reported analysis is extreme within its own defensible analysis
  space. A ready-made headline statistic for the robustness report. Their
  finding: 13.5% of published human analyses fall in their own most-extreme 5%.
- Spec review is currently weak everywhere: 86% of contradictory analyses
  passed AI review (78% passed human expert review). A multi-agent
  reasonableness screen needs adversarial design, plus a log of rejected
  specifications and why (Type-E/N/U screening).
- **The unfilled gap — plausibly this project's niche**: no tool derives
  multiverse decision points from a paper's *existing analysis code*. Every
  current tool (specr, multiverse, boba, rdfanalysis) needs hand-annotated
  branches. Code-comprehension → decision-point extraction is checkable output
  an LLM stage can own.
- Execution should go through existing engines (`multiverse`/`specr`/`boba`),
  with PIMA for valid inference over the specification set.

### 4. coarse: borrow components, don't fork (for this pipeline)

- Coarse has no stage toggles, hard-coded econ/math prompts, and a quote-
  verification invariant tied to a single paper document — comments about code
  files cannot survive it. Fork cost exceeds slim-build cost for an
  analysis-only reviewer.
- Reuse: `quote_verify.py` (generalized to a paper+code corpus), the
  `DetailedComment`/`Review` schema, `extract_and_structure()` as a library
  call for PDF→sections, and the headless `claude -p` client pattern.
- Separate finding: a psych-field adaptation of *full* coarse (for general peer
  review, not this pipeline) is worth ~3–5 days as a runtime overlay on the pip
  package — no field-specific forks exist yet. Distinct project; keep it off
  this pipeline's critical path.

## Emerging architecture (to be stress-tested, not yet agreed)

1. **Intake & extraction** (vision model on rendered pages): claims table —
   every reported quantity with location, plus data/code inventory. Deterministic
   checkers (metacheck et al.) run here on source formats.
2. **Environment reconstruction & execution** (agent, never sees the paper's
   claims): container/renv rebuild, run, capture outputs. Expect this to be the
   most engineering-heavy stage and the most common failure point.
3. **Matching & verdict** (separate agent + deterministic tolerance rule):
   link outputs to claims, apply Kohler bands, diagnose discrepancies. This is
   the research-frontier stage — invest here.
4. **Analysis review** (slim coarse-derived stage over paper+code corpus):
   appropriateness of statistical choices; deterministic-first, LLM findings
   treated as candidates requiring a verification pass; gold set before trust.
5. **Multiverse**: decision-point extraction from the actual analysis code (the
   novel bit) → adversarial multi-agent reasonableness screen with rejection log
   → execution via existing engines → m-value + PIMA → interpretation by a
   separately-prompted stage.
6. **Human gates** throughout (AEA precedent): binding sign-off at
   environment-ready, verdict, and final report.

## Open scoping questions (grilling agenda)

- Target corpus: which fields, languages (R only? Stata is systematically
  weakest with no tooling), and input guarantees (data+code available? open
  data only?).
- Is stage 4 (appropriateness) in scope for v1, given it needs a gold set
  built first and has the weakest evidence?
- What is the unit of output — a graded report per paper? For whom (authors,
  editors, meta-scientists)? Which decisions does it need to support?
- Build substrate: Claude Code skills/agents (AEA-style) vs. a standalone
  orchestrated pipeline? Cost per paper and who pays?
- Evaluation: which benchmark(s) anchor development (SocSci-Repro-Bench?
  seeded-error sets?), and what counts as "good enough" per stage?
- Relationship to the Institute for Replication's actual work (robustness
  reproduction) — the one task no benchmark covers.

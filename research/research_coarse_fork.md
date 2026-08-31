# Forking `coarse` into an analysis-only reviewer — feasibility assessment

Read-only investigation, 2026-08-31. Nothing was modified.

---

## 1. Where the code lives

| Thing | Path |
|---|---|
| Local checkout | `/Users/lukaswallrich/Documents/Coding/coarse` |
| Installed CLI | `/Users/lukaswallrich/.local/bin/coarse` (PyPI package `coarse-ink`) |
| Skill | `/Users/lukaswallrich/.claude/skills/coarse-review/SKILL.md` (pinned to `coarse-ink==1.4.0`; `scripts/` is empty) |
| Package source | `/Users/lukaswallrich/Documents/Coding/coarse/src/coarse/` |

The local checkout is a **fork** of `Davidvandijcke/coarse` (`gh api` confirms `fork: true`, `parent: Davidvandijcke/coarse`). It sits on branch `docs/readme-subscription-path` at v1.4.0 and is **84 commits behind upstream `main` (now v1.9.2)**. The fork's own changes are README/CHANGELOG text about the subscription path; no source divergence.

Size: 41 Python files, ~12,900 lines. `prompts.py` alone is 2,453 lines (19% of the codebase).

---

## 2. Pipeline architecture map

Orchestrator: `src/coarse/pipeline.py::review_paper()` (lines 236-497). Linear with two parallel fan-outs.

```
extract_file()                    extraction.py / extraction_formats.py / extraction_openrouter.py
  ├ PDF   → Mistral OCR via OpenRouter file-parser plugin (paid, ~$0.05-0.15/paper)
  ├ DOCX/HTML/TeX → docling, with mammoth/markdownify/regex fallbacks
  └ MD/TXT → passthrough                                     → PaperText(full_markdown, tokens, garble_ratio)
  ↓
extraction QA (PDF only, vision model re-reads rendered pages)  extraction_qa.py
  ↓
cost gate (interactive $ approval, skippable)                   cost.py + pipeline_spec.py
  ↓
analyze_structure()                                             structure.py
  regex heading parse → SectionInfo[]; cheap LLM call for title/domain/taxonomy/document_form;
  keyword+LLM math-section detection; claims/definitions extraction
  ↓
── parallel, 3 threads ─────────────────────────────────────────
  calibrate_domain()      review_stages.py:127   → DomainCalibration (LLM-invented per-paper rubric)
  search_literature()     agents/literature.py   → arXiv/Perplexity context string
  extract_contribution()  review_stages.py:155   → ContributionContext
  ↓
Phase 1  OverviewAgent          agents/overview.py    → OverviewFeedback (macro issues + recommendation)
Phase 1b CompletenessAgent      agents/completeness.py → merged into overview (max 12 issues)
  ↓
Phase 2  SectionAgent × N       agents/section.py, 10 threads, capped at 25 sections
         per section: focus = _detect_section_focus()  review_stages.py:61
                      → proof | methodology | results | literature | discussion | general
         chained ProofVerifyAgent (agents/verify.py) when focus == "proof"
         quote verification after every stage                 quote_verify.py
Phase 2b CrossSectionAgent      agents/cross_section.py  (results↔discussion, ≤3 calls)
  ↓
Phase 3  run_editorial_pass()   review_stages.py:180
         EditorialAgent (dedup + contradiction + quality), falling back to CrossrefAgent → CritiqueAgent
  ↓
quote verify + QuoteRepairAgent salvage    pipeline.py:127, agents/quote_repair.py
  ↓
render_review()   synthesis.py  — pure deterministic markdown, no LLM
```

**Data model** (`types.py`): `PaperText`, `SectionInfo`/`SectionType`, `PaperStructure`, `DomainCalibration`, `ContributionContext`, `OverviewFeedback`/`OverviewIssue`, `DetailedComment`, `Review`. Every comment carries a **verbatim quote (min 20 chars)**, severity, and confidence.

**Quote verification** (`quote_verify.py`, 440 lines) is the most reusable non-prompt asset. Deterministic fuzzy matching of each quote against the paper markdown: normalisation, Jaccard candidate retrieval, `SequenceMatcher` refinement, 0.80 similarity floor (0.92 for math-heavy text), special handling for markdown tables. Comments that cannot be anchored are dropped, then one LLM repair pass re-anchors plausible ones.

**LLM backend abstraction.** There is no interface class. `LLMClient` (`llm.py`, 846 lines) wraps litellm + instructor for structured Pydantic output. The headless path (`headless_review.py`) **monkey-patches** `coarse.llm.LLMClient` and `coarse.pipeline.LLMClient` with a factory returning `ClaudeCodeClient` / `CodexClient` / `GeminiClient` from `headless_clients.py` (1,074 lines), each of which shells out to `claude -p` / `codex` / `gemini` per call, strips host env vars, retries JSON parse failures 3×, and caps concurrency (`COARSE_HEADLESS_CONCURRENCY`, default 3). The duck-typed contract an alternative backend must satisfy is small: `complete(messages, ResponseModel, max_tokens, temperature)`, `complete_text(...)`, `model`, `cost_usd`, `add_cost()`, `supports_prompt_caching`.

**Entry points** (`pyproject.toml`): `coarse` / `coarse-ink` → `cli.py:app` (typer), `coarse-review` → `cli_review.py:main` (detach/attach worker used by the skill). Python API: `from coarse import review_paper`. There is also `extract_and_structure()` (`pipeline.py:177`) — extraction + structure with **no review stages** — explicitly documented as the reuse hook "for callers which want to drive review reasoning themselves". That is the single cleanest integration point for a custom pipeline.

---

## 3. Configurability and license

**License: MIT** (both the fork and `Davidvandijcke/coarse`). Copyright David Van Dijcke, 2026. Forking, modifying and redistributing is unencumbered.

**Configuration surface is small and is not about stages.** `~/.coarse/config.toml` → `CoarseConfig` (`config.py:42`) holds exactly: `default_model`, `vision_model`, `extraction_qa`, `max_cost_usd`, `api_keys`. Upstream v1.9.2 adds one field, `review_language`. Nothing else.

**Stages cannot be disabled, replaced, or reordered.** The stage list is hard-coded control flow in `review_paper()`. There is no plugin registry, no stage spec object, no `--skip` flags. `pipeline_spec.py` is a *cost-estimation* constants file, not a stage definition — it exists so the Python and web cost estimators agree, despite upstream's `docs/architecture.md` calling it a "Stage Manifest".

Confirmed against upstream v1.9.2, not just the local v1.4.0: `review_paper()`'s signature there is `(pdf_path, model, skip_cost_gate, config, author_notes, language, site_language, progress_callback, deep_literature_search)`. The only stage-shaped switch in 84 commits of new work is `deep_literature_search: bool`, which toggles depth within one existing sub-stage. Upstream's `docs/architecture.md` describes the same fixed stage graph and documents no extension point.

**Custom rubrics cannot be injected.** `prompts.py` is entirely hard-coded Python string literals composed with `+` at import time — no file reads, no env vars, no templating engine, no config lookup. Variation happens through exactly four mechanisms:

1. f-string interpolation in the `*_user()` builders,
2. optional context blocks (`_format_calibration`, `_format_contribution_context`, notation, literature),
3. `document_form_notice()` — a fixed dict of 7 notices appended to system prompts (manuscript/outline/draft/proposal/report/notes/other),
4. `author_notes_block()` — free text, fence-stripped, truncated to 2,000 chars, and **explicitly framed in the prompt as non-binding steering that must not override the rubric**.

The only route by which statistics-specific criteria enter today is `DomainCalibration` — an LLM-generated, per-paper set of "methodology concerns" and "assumption red flags". It is invented at runtime, not authored, so it is not a control surface you can rely on.

**Content gap for our use case.** Grep across all 2,453 lines of `prompts.py` finds **zero occurrences** of: p-value, multiple comparisons, effect size (as a review target), preregistration, statistical power (outside the `proposal` notice), code availability, data availability, reproducibility, open science, model specification. "Robustness" appears twice, "identification" twice. The vocabulary is mathematical-economics: proofs, derivations, identification arguments, algebra checking.

**A `results` rubric does not exist.** `_detect_section_focus()` (`review_stages.py:61`) can return `"results"`, but `SECTION_SYSTEM_MAP` (`prompts.py:1509`) has only `proof`, `methodology`, `literature`, `discussion`, `general`. Results sections silently fall through to the generic prompt via `SECTION_SYSTEM_MAP.get(focus, SECTION_SYSTEM)` (`agents/section.py:74`). Verified identical in upstream v1.9.2. Worse for our purposes: `math_content` outranks section type in `_detect_section_focus`, so a Results section containing equations is routed to the *proof* rubric.

**The pipeline never sees code or data.** Input is one document file. There is no notion of a repository, a script, a dataset, or an execution log anywhere in `types.py`, `extraction.py`, or the agents. `DetailedComment.quote` must be verbatim from the paper markdown, and quote verification enforces this — a comment about a line in `analysis.R` cannot survive `verify_quotes()`.

**Upstream direction (84 commits, v1.4.0 → v1.9.2)** is multilingual review output (`languages.py`, `review_labels.py`, `lang_eval.py`, `textscript.py`), a model registry, progress callbacks, and extraction fixes. No move toward stage configuration or rubric injection. An analysis-only mode is not going to arrive from upstream.

---

## 4. Recommendation: build slim, borrow parts — do not fork

**Do not fork the pipeline.** Reasoning:

1. **The overlap is the part we would delete.** Of the stages, an analysis reviewer keeps roughly: extraction, structure, and a results/methods review pass. It discards overview synthesis, completeness, literature search, cross-section synthesis, proof verification, the editorial dedup chain, the accept/revise/reject recommendation, and the whole macro-issue frame. That is most of `pipeline.py`, most of `prompts.py`, and 9 of the 12 agent modules (only `section`, `quote_repair` and `base` survive).

2. **The parts we would keep are prompts we must rewrite anyway.** The section rubrics are tuned for theory papers. There is no results rubric to inherit, no statistics vocabulary, and the one rubric closest to our need (methodology) is 44 lines of identification-argument checking. We would be writing the analysis rubric from scratch inside someone else's 2,453-line prompt module.

3. **The core mismatch is architectural, not textual.** An analysis-focused reviewer for a reproduction pipeline needs to reason over *paper + code + data + our own execution output*, and its comments need to anchor to script lines and result tables, not only to paper prose. Coarse's document-in / quoted-comments-out contract is enforced at the type level (`DetailedComment.quote`) and at the verification level (`quote_verify.py` drops anything not found in the markdown). Fitting a code reviewer into it means fighting the invariant that makes coarse good.

4. **A fork inherits a maintenance tax with no upside.** The local checkout is already 84 commits behind. Upstream's active work (i18n, model registry) is orthogonal to our needs, so rebasing buys nothing while our deletions guarantee conflicts across `pipeline.py`, `prompts.py`, and `types.py`.

5. **Cost/complexity we do not need.** The cost gate, the web handoff, the Modal worker, the Supabase callback, the extraction cache, the three-host headless client layer — all of it is infrastructure for a public service.

**What to take instead.** Four assets are worth copying (MIT permits it; attribute in a header comment):

- **`quote_verify.py`** — copy near-verbatim. Deterministic quote anchoring with a fuzzy floor and table handling is genuinely hard to get right, and it is the mechanism that stops an LLM reviewer from hallucinating what the paper says. Directly applicable to grounding claims in both the manuscript and code files.
- **The comment schema** — `DetailedComment` (quote / feedback / severity / confidence) plus `Review`. Small, well-shaped, and already proven against real reviews.
- **`extract_and_structure()` plus the extraction stack** — call coarse as a *library dependency* for PDF→markdown→sections. This is a solved, boring problem we should not re-solve. It costs one OpenRouter key and ~$0.10 per paper for PDFs, and is free for markdown/TeX input.
- **`headless_clients.py` patterns** — the `claude -p` subprocess wrapper with JSON repair, retry, concurrency cap and host-env stripping. Worth reading before writing our own; possibly worth copying `_HeadlessCLIClient` wholesale.

**Sketch of the slim stage** (~600-900 lines, one prompts file):

| Element | Choice |
|---|---|
| Input | paper markdown (via coarse extraction) + code files + data dictionary + our reproduction run output |
| Structure | reuse `SectionInfo`; add `CodeArtifact` (path, language, text) and `ReproResult` |
| Stages | (1) analysis-plan extraction — what the paper claims it did, per hypothesis; (2) code-vs-plan consistency; (3) results-vs-code consistency (do reported numbers match what the code produces); (4) interpretation review — does the prose overclaim relative to what the analysis supports; (5) one dedup/severity pass |
| Rubric content | statistical choices (model specification, assumption checks, clustering/nesting, missing data, transformations), inference (p-values, multiplicity, power, effect sizes, CI interpretation), robustness and researcher degrees of freedom, code-results consistency, preregistration adherence |
| Grounding | quote verification against a *multi-source* corpus (paper + each code file), reusing coarse's matcher with the source id recorded per comment |
| Backend | `claude -p` subprocess, or Claude API directly — our own thin client, no litellm/instructor needed if we use the Claude API's structured output |
| Output | same `Review`-shaped markdown, so it composes with the rest of the reproduction pipeline |

**If a fork is chosen anyway**, the minimum change set is: delete the overview/completeness/literature/cross-section/proof-verify/editorial stages from `review_paper()`; add `SECTION_RESULTS_SYSTEM` and `SECTION_ANALYSIS_SYSTEM` and register them in `SECTION_SYSTEM_MAP`; invert the precedence in `_detect_section_focus()` so `section_type` beats `math_content`; extend `PaperText`/`SectionInfo` to carry code artifacts; generalise `verify_quotes()` to a multi-document corpus; replace `DomainCalibration` with an authored static rubric; rip out the cost gate, web handoff and Modal deploy. That touches every file the report names, which is the argument against it.

---

## 5. Open questions for the caller

- Will the analysis reviewer see our *own* reproduction output (re-run results, diffs against reported numbers)? If yes, the fork case weakens further — coarse has no representation for it.
- Is a full peer review of the paper also wanted as a separate pipeline stage? If so, run stock `coarse` unmodified via the existing skill for that stage, and build the analysis reviewer beside it. The two stay independent and coarse stays upgradeable.

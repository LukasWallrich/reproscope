# Benchmarks and corpora for a paper+data reproduction tool — findings

Date of research: 2026-08-31.

Method note: this session's web-search budget was exhausted before work started, so all
findings come from direct fetches of primary sources (publisher pages, official docs,
OSF, arXiv, GitHub) rather than keyword search. Items marked NOT VERIFIED could not be
confirmed from a primary source.

---

## 4. deepseek-v4-flash vision — VERIFIED

`deepseek-v4-flash` (DeepSeek-V4-Flash-0731) is **text only**; sending an image returns
`400 "This model does not support image"`. Image input lives on a separate model id,
**`deepseek-v4-flash-vision-exp`** (DeepSeek-V4-Flash-Vision-Exp, released 2026-08-21,
described in DeepSeek's changelog as "an experimental model").

- **No special base URL.** It runs on the normal `https://api.deepseek.com` endpoints:
  OpenAI-compatible `/chat/completions` with `image_url` content blocks, the Responses
  API (`input_image`), the Anthropic-compatible `/anthropic/messages` with `image`
  blocks, and the Files API (`{"type":"file","file_id":"file-api-..."}`).
  The "experimental" label attaches to the model, not the endpoint.
- **Stability:** experimental. (`deepseek-v4-flash` is public beta; `deepseek-v4-pro` is GA.)
  Treat the model id as liable to change.
- **Pricing** (USD/1M tokens, off-peak / peak; off-peak is exactly half): input cache hit
  0.007 / 0.014, cache miss 0.22 / 0.44, output 0.66 / 1.32 — identical to plain flash.
  No separate image price: each image is resized to ~800x800 total pixels and capped at
  **384 input tokens**, counted per image. 600 images (the per-request max) cost at most
  ~230k input tokens.
- **Limits:** JPEG/PNG/GIF/WebP; images in `user` messages only; 48 MiB request body;
  32 MiB per image inline or by URL, 64 MiB via Files API; 8192 px per side, dropping to
  4096 px at 15+ images; 1M context, 384K max output; thinking mode supported;
  FIM completion NOT supported on the vision model.
- OpenRouter also lists a `deepseek-v4-flash-vision-exp` entry at $0.22/M in, $0.66/M out.
  Exact slug not confirmed. Going direct to `api.deepseek.com` is better documented and
  gets off-peak pricing.

Sources: <https://api-docs.deepseek.com/guides/vision>,
<https://api-docs.deepseek.com/quick_start/pricing>,
<https://api-docs.deepseek.com/updates>, <https://openrouter.ai/deepseek>

---

## 1. Multi100 — VERIFIED, materials OPEN, outcome data MIT-licensed

**Paper:** Aczel, Szaszi, Clelland et al., "Investigating the analytical robustness of the
social and behavioural sciences", *Nature* 652(8108):135-142, 2 April 2026,
doi:10.1038/s41586-025-09844-9 (title, journal, date Crossref-verified).
OpenAlex reports green OA, `cc-by`, published version, via the Bath repository:
<https://researchportal.bath.ac.uk/en/publications/9e719707-a664-417d-8389-6eff23ee6566>.
Preprint: MetaArXiv, doi:10.31222/osf.io/twqsv_v1, posted 2026-03-31, CC BY 4.0.

### Where the materials are

| Component | URL |
|---|---|
| Main OSF project (public, created 2022-02-01) | <https://osf.io/q5h2c/> — verified via OSF API |
| OSF component "Project Materials" | <https://osf.io/4ntua/> |
| OSF component "Figures" | <https://osf.io/wg3fr/> |
| GitHub: all outcome data + analysis code | <https://github.com/marton-balazs-kovacs/multi100> — verified via GitHub API: `spdx_id: MIT`, 13 stars, last push 2025-12-16, default branch `master` |
| Per-paper analyst nodes | ~100 public OSF nodes named `<Paper_id> - Multi100 - <SCORE id>`, e.g. <https://osf.io/hd8e6/> |

No Zenodo deposit by the Multi100 team. (A third-party record exists:
doi:10.5281/zenodo.19811342, "Structural predictors of analytical fragility in social
science: evidence from SCORE Multi100", archive <https://osf.io/tjehy/>.)

Data availability statement (from the repo's manuscript source `analysis/multi100_results.qmd`):

> "Study data and materials are available on the project OSF (<https://osf.io/q5h2c/>) and
> GitHub repositories (<https://github.com/marton-balazs-kovacs/multi100/>). Archived data
> include the original datasets **or a description of how to gain access to them**. Our
> shared materials include all the survey questions and the general communication texts and
> instructions that we sent to the re-analysts and peer-evaluators. We excluded from our
> data files the email addresses of the re-analysts, as well as the records of those
> analysts who did not comply with the instructions and did not submit all the required
> analyses by the deadline."

### What is open

- **List of the 100 papers — yes, but NO DOIs.** `Selected claims and dropped papers.xlsx`
  (<https://osf.io/download/tg6a8/>): sheet "selected papers" has exactly 100 rows, 20
  columns; "dropped papers" has 29 rows with reason codes. Machine-readable equivalent:
  `data/raw/multi100_all-paper_raw_data.csv` in the repo (columns `original_title,
  paper_id, paper_discipline, general_osf_link, instructions_given, original_claim,
  original_materials, paper_link, experimental_or_observational,
  original_paper_reference`). `paper_link` holds OSF view-only URLs, not publisher DOIs
  (0/100 contain "doi"); `original_paper_reference` is a short key like
  `Andreoni_etal_2017`. **DOIs would have to be recovered by Crossref title matching.**
  Discipline split: political science 37, economics 30, psychology 17, sociology 8,
  marketing/organisational behaviour 5, criminology 1, management 1, demography 1.
- **Predefined claims — yes.** Two versions per paper in the xlsx (`the claim /the
  re-analysts saw/` and `the claim from SCORE collection`), plus `instructions_for_task_2`,
  the original in-text statistical result, test statistic family, test statistic, df1/df2,
  sample size, and page location. Also in the CSV as `original_claim`.
- **Per-analyst effect sizes and conclusions — yes, fully open on GitHub.**
  `data/processed/multi100_processed_data.csv` (11,038 rows, ~90 columns including
  `analyst_id, paper_id, task1_conclusion, task1_categorisation, task2_conclusion,
  direction_of_result, p_value_report, original_cohens_d, original_correlation_coef`),
  `multi100_reanalyzed_effect-sizes_processed_data.csv` (per-analyst statistic, df, N, r,
  Cohen's d), `multi100_original_effect-sizes_processed_data.csv`, the peer-evaluation
  files, and `multi100_master_processed_data.csv`, each with a codebook CSV. Analyst names
  are attached; email addresses were removed.
- **Underlying datasets — hosted by SCORE, not Multi100.** Each of the 100 rows has an
  `original_materials` link to a public OSF "Original Materials" node carrying a redundant
  `view_only` token (the nodes resolve through the OSF API without it). Spot-checks found
  a "Phase 2 Reproduction Materials" folder with data zips in most cases.
- **Per-analyst code:** navigation sheet <https://osf.io/download/px8gf/> maps each paper
  to its OSF node; within each node one component per `analyst_id` holds that analyst's
  scripts.

### Licence — per artifact, no single project licence

- **GitHub repo (code AND all outcome data): MIT** — "Copyright (c) 2025 Marton Kovacs,
  Balazs Aczel". Confirmed via the GitHub API.
- **Main OSF project q5h2c: no licence set.** `api.osf.io/v2/nodes/q5h2c/` returns a null
  licence. Not CC0, not CC BY — unspecified.
- **MetaArXiv preprint: CC BY 4.0.** Nature article: green OA, cc-by per OpenAlex.
- **Data use restrictions:** none stated for the Multi100 outcome data. Restrictions are
  inherited from the original studies.

### How many of the 100 have genuinely open data — 47

Not in the main paper; in the Supplementary Information
(`analysis/multi100_supplementary.docx` in the repo), verbatim:

> "We checked each study to determine whether it had open data. It is worth noting that
> data openness is a spectrum. We encountered several instances where data were technically
> open but still unavailable due to expired links, closed-access articles, defunct pages,
> etc. We settled on an operationalization where only a few clicks should be enough to get
> the data. Otherwise, we labeled the data as closed access. **Out of the 100 studies, 47
> had available data upon further examination, and 53 did not.** Where the original data
> were available, 27% (47 out of 173) of the re-analysts arrived at the same result as the
> original study (within a tolerance region of +/- 0.05 Cohen's d). In contrast, this value
> was 39% (87 out of 223) for those papers for which we could not easily locate the
> original data."

Underlying coding sheet (public, 100 rows, `paper_id, original_materials,
available_data`, CSV export confirms 47 TRUE / 53 FALSE):
<https://docs.google.com/spreadsheets/d/1GwDGeNqloliZqkaNMbgWGnzAHwWWDoXO-Egc0s9tR60/>

Two things to keep separate:
- 47/53 describes the **original publications'** data openness, not Multi100's
  redistribution.
- Re-analysts got data for all 100 via the SCORE OSF nodes, and those nodes are public with
  links published in the open xlsx. Three of the 53 "not open" cases (bsv24, fh7k4, q67m9)
  were spot-checked and all three hold downloadable data files. **Only 4 of 100 nodes were
  checked** — the Data availability wording implies some nodes hold only access
  instructions. So: all 100 datasets are publicly *linked*; how many are actually
  *downloadable* is UNVERIFIED and worth a scripted sweep before planning around it.

Related numbers from the supplementary and methods: the COS team could reproduce the
original results for **78 of 100** studies. SCORE reproduction routes: data and code both
available n=63; code adapted n=7; data only, new code written n=10; secondary source data
shared on request n=11; never attempted n=9.

### Training-data contamination — no Multi100-specific discussion found

Verified negative, with one avenue not exhausted:
- All 14 works citing the Nature paper in OpenAlex are meta-science, replication or domain
  commentary — none LLM-related.
- OpenAlex title/abstract search on "Multi100" returns only the OSF nodes; Semantic Scholar
  returns nothing.
- **arXiv API queries were rate-limited and never ran**, and WebSearch was unavailable.
  arXiv/NeurIPS-style preprints are the likeliest venue, so this is NOT exhausted.

Adjacent published work that does treat the problem:
1. **Luo et al. 2024, "Large language models surpass human experts in predicting
   neuroscience results"**, *Nature Human Behaviour*, doi:10.1038/s41562-024-02046-9
   (preprint arXiv:2403.03230). The strongest methodological precedent — a section titled
   "LLM performance is not driven by data memorization":
   > "When LLMs perform well on a benchmark, one general concern is that the benchmark
   > itself was part of the training set, allowing the LLM to memorize the correct answers.
   > To address this concern, we used a commonly applied measure, zlib-perplexity ratio, for
   > evaluating whether LLMs have memorized passages. ... We found no indication that
   > BrainBench was memorized by LLMs."

   And their strongest control:
   > "As a final check, we trained a relatively small LLM from scratch on the published
   > neuroscience literature (excluding preprints and BrainBench items), which eliminated
   > any possible overlap between training data and BrainBench, and found superhuman
   > performance on BrainBench."
2. **CORE-Bench** (arXiv:2409.11363) mentions continually adding new tasks, "which could
   mitigate concerns about contamination and saturation" — one sentence only.
3. **Hewitt et al. 2026, "Large language models can predict the results of social science
   experiments"**, *Nature*, doi:10.1038/s41586-026-10742-x (preprint
   doi:10.31234/osf.io/3svep_v1). On-point topic; text could not be fetched, so what it
   says about contamination is UNVERIFIED.
4. Alizadeh et al. (SocSci-Repro-Bench) ran a memorisation test with 11.1% metadata recall;
   Kohler et al. ran a pre- vs post-cutoff date split with no significant difference. Both
   are usable templates — see sections 3a and 3e.

Not a published claim, but the situation: Multi100's claims, per-analyst conclusions and
effect sizes have been public on GitHub and OSF for years, and the 100 source papers date
2009-2018. Any model with a 2025+ cutoff plausibly has both the originals and the
re-analysis outcomes.

### Other flags
- The Nature article page itself was not read (login redirect to `idp.nature.com`); all
  manuscript quotes come from the repo's `.qmd`/`.docx` sources.
- The OSF wiki lists a "Supplementary Information.pdf" and a "Data and Analysis component"
  that do not exist. The supplementary lives in the repo as
  `analysis/multi100_supplementary.qmd` / `.docx`. The wiki is stale.

### Usability verdict
Best-documented human-ground-truth corpus of the four, with per-analyst effect sizes under
MIT. Two practical limits: DOIs must be recovered by title matching, and only 47 of 100
source studies have easily obtainable data by the team's own operationalisation.
Contamination risk is high and unstudied for this corpus — use it as a **development**
corpus, not held-out validation.

## 2. "ReplicatorBench" — VERIFIED, exact name, OPEN (Apache-2.0)

**ReplicatorBench: Benchmarking LLM Agents for Replicability in Social and Behavioral
Sciences.** Bang Nguyen, Dominik Soós, Qian Ma, Rochana R. Obadage, Zack Ranjan,
Sai Koneru, Timothy M. Errington, Shakhlo Nematova, Sarah Rajtmajer, Jian Wu, Meng Jiang
(Notre Dame / Old Dominion / Penn State / Center for Open Science).
arXiv:2602.11354 — v1 11 Feb 2026, v3 29 Jun 2026. Accepted, KDD 2026 AI4Science track.
Title, authors, dates and abstract verified directly from the arXiv abstract page.

- Repo: <https://github.com/CenterForOpenScience/llm-benchmarking> — **Apache-2.0**
  (confirmed via GitHub API and the README's own statement; 7 stars, last push
  2026-06-24). Supplementary artifact: <https://doi.org/10.5281/zenodo.20506946>
  (prompts, structured output schemas, supplementary materials).
- **39 instances**, each a paper with a human expert replication report from the DARPA
  **SCORE** (Systemizing Confidence in Open Research and Evidence) programme. Verified
  verbatim from the arXiv HTML full text. Topic split reported by the agent: economics 10,
  health 9, psychology/cognitive science 8, sociology 5, political science 4, education 2,
  public administration 1; 20 observational, 19 experimental.
- **3,128 gradable checkpoints** across three stages (verified verbatim): (1) Extraction —
  from paper PDF + focal claim, produce a 24-field "post-registration" and find the
  replication data on the open web; (2) Generation — pre-register a plan (30 fields), then
  build a Docker environment and execute; (3) Interpretation — 13 fields ending in a
  binary criteria met / unmet call.
- Grading: LLM-as-judge against human-annotated references (3 annotators, leave-one-out
  for extraction); the human SCORE replication report is ground truth for interpretation.
- **Ground-truth diversity is the selling point.** From the abstract: existing benchmarks
  "[lack] ground-truth diversity by focusing only on reproducible papers, thereby failing
  to evaluate an agent's ability to identify non-replicable research." ReplicatorBench
  includes "human-verified replicable and non-replicable research claims".
- **Levels of code access are a design variable.** The abstract states they evaluate
  "different design choices of programming language and levels of code access". The agent
  reports these as an *easy* setting (data and code) and a **hard setting (replication
  data only; the agent must write the analysis code from the paper's methods
  description)** — the exact setting of the tool being built. LOWER CONFIDENCE: the
  easy/hard labels and the 20 met / 19 unmet split could not be confirmed from the arXiv
  HTML; check the paper body or repo before relying on them.
- Headline finding: agents design and execute computational experiments competently but
  **fail at retrieving the replication data**.

**Verdict: this is what the user meant.** It is real, exactly named, openly licensed,
social science, and its data-only condition matches the tool's task design. Its 39
SCORE-backed instances are a ready-made **development and comparison** set with human
ground truth including negative cases.

**It is not clean held-out validation.** The benchmark has been on arXiv since February
2026 with code on GitHub and an artifact on Zenodo, and its ground truth is SCORE
replication reports public since roughly 2021. By the date rule in section 3, it carries
the same contamination exposure as every other public corpus here.

**Circularity with Multi100 — UNCHECKED.** Both corpora draw on the DARPA SCORE
programme: Multi100's per-paper OSF nodes are named `<Paper_id> - Multi100 - <SCORE id>`,
and ReplicatorBench's 39 instances are SCORE papers with human replication reports.
Overlap between the 39 and the 100 is plausible and would make a Multi100-development /
ReplicatorBench-evaluation split partly circular. Compare paper IDs before splitting:
Multi100 IDs are in `data/raw/multi100_all-paper_raw_data.csv`; ReplicatorBench instances
are under `replicatorbench/data/` in the repo (the repo README does not list them, so this
needs a checkout).

Repo layout, for reference: `replicatorbench/` contains `core`, `data` ("Benchmark
datasets and ground truth"), `generator`, `info_extractor`, `interpreter`, `samples`,
`templates`, `tests`, `validator`; a separate `robustness/` module sits alongside it.
The repo README does not state instance counts, paper IDs, or the easy/hard labels.

### Disambiguation — the near-misses

| Name | What it is | Why it is not ReplicatorBench |
|---|---|---|
| **ReplicationBench** | Astrophysics paper replication, Stanford + Toronto | Different domain and team |
| **RepliBench** | UK AI Security Institute eval of LLM agents' *self*-replication | Unrelated topic |
| **REPRO-Bench** | Judging *whether* a paper is reproducible | Assessment, not doing the reproduction |
| **ReplicationRadar** | No verifiable hit on arXiv, OpenAlex or GitHub | Probably does not exist |

**ReplicationBench: Can AI Agents Replicate Astrophysics Research Papers?** — Ye, Yuan,
Cooray, Dillmann, Roque, Baron, Frank, Martin-Alvarez, Koblischke, Qu, Yang, Wechsler,
Ciucă. arXiv:2510.24591v2, CC BY 4.0. **111 expert-written tasks over 20 papers**, plus
ReplicationBench-Plus (11 papers, 58 LLM-generated tasks). The agent gets manuscript +
dataset + execution metadata and must implement from scratch, **no original code**.
Automated grading against the paper's ground-truth numbers with tolerances. Repo
<https://github.com/Christine8888/replicationbench-release> (**MIT**); HF dataset
`ChristineYe8/ReplicationBench`. Frontier models score under 20%. **Method matches the
tool exactly; only the domain differs — the best available model for harness design and
tolerance-based grading.**

**RepliBench** — Black, Cooper Stickland, Pencharz, Sourbut, Schmatz, Bailey, Matthews,
Millwood, Remedios, Cooney (UK AI Security Institute). arXiv:2504.18565v2, CC BY 4.0.
20 task families / 86 tasks on obtaining resources, exfiltrating weights, replicating onto
compute, persisting. Built on Inspect. **No public task release found** (absent from
`UKGovernmentBEIS/inspect_evals`, no repo of that name); the absence is verified, the
reason is not stated anywhere.

**Institute for Replication** — has no benchmark. See section 3c.

### Other benchmarks in the same space

- **CORE-Bench** — Siegel, Kapoor, Nadgir, Stroebl, Narayanan (Princeton),
  arXiv:2409.11363. 270 tasks / 90 papers from CodeOcean (CS, social science, medicine),
  three difficulty levels. Agent gets **code + data + paper** and must run it and read off
  the numbers. <https://github.com/siegelz/core-bench>, **MIT**. A 2026 follow-up
  (arXiv:2606.26158) reports it near saturation.
  *Name collision:* an unrelated CORE-Bench for **code retrieval** exists
  (arXiv:2606.11864, 180K queries) — no connection to reproducibility.
- **PaperBench** — Starace et al. (OpenAI), arXiv:2504.01848. 20 ICML 2024 papers,
  8,316 gradable leaf nodes, paper-only input, ML domain. In
  <https://github.com/openai/frontier-evals> (formerly `openai/preparedness`), **MIT**.
- **SUPER** — Bogin et al. (AI2), arXiv:2409.07440. 45 end-to-end + 152 sub-problems + 602
  auto-generated; setting up and running existing ML/NLP repos.
  <https://github.com/allenai/super-benchmark>, **Apache-2.0**.
- **ResearchCodeBench** — Hua et al. (Stanford), arXiv:2506.02314. 212 code-completion
  challenges from 2024-25 ML papers.
  <https://github.com/PatrickHua/ResearchCodeBench> — no licence file.
- **SciReplicate-Bench** — Xiang, Yan, Ouyang, Gui, He (KCL), arXiv:2504.00255. 100 tasks
  from 36 NLP papers; generate code from algorithm descriptions.
  <https://github.com/xyzCS/SciReplicate-Bench> — no licence file.
- **AutoReproduce** — Zhao et al. (Tsinghua), arXiv:2505.20662. A multi-agent *method* for
  reproducing AI experiments, not a task set.
  <https://github.com/AI9Stars/AutoReproduce> — no licence file.
- **VERITAS** — Liu, Tjiaranata, Tan (Chicago), arXiv:2607.02931. A domain-agnostic
  replication tool over CLI coding agents; 65 papers across CS, social science, medicine
  and astrophysics; reports state of the art on both CORE-Bench and ReplicationBench.
  **Closest existing tool to what the user is building** — worth reading before designing
  the harness.

### Fit against the tool's setting (social science, paper + data, no original code, human ground truth)

- **Direct fit:** ReplicatorBench (hard setting) — matches on all four axes, and is the
  only one that includes non-replicable ground truth.
- **Method fit, wrong domain:** ReplicationBench (astrophysics).
- **Wrong setting — these hand the agent the original code:** CORE-Bench, SUPER,
  REPRO-Bench, SocSci-Repro-Bench, AutoReproduce. Useful for baselines, not for the
  no-code condition.
- **Wrong task shape:** PaperBench, ResearchCodeBench, SciReplicate-Bench (paper-to-code
  in ML/NLP, no data reproduction); RepliBench (unrelated).

## 3. Other open benchmarks and corpora

### 3a. SocSci-Repro-Bench — VERIFIED, OPEN (CC BY 4.0)

Alizadeh, Mosleh, Gilardi, Kasirzadeh & Tucker, "AI Coding Agents Can Reproduce Social
Science Findings", arXiv:2606.11447, 9 June 2026. Title, authors, date and abstract
confirmed directly from the arXiv abstract page.

- Repo: <https://github.com/malizad/SocSci-Repro-Bench> (13 stars, last push 2026-03-06;
  GitHub API reports licence "Other" because the plain-text CC BY 4.0 file is not
  auto-detected). Materials also on Harvard Dataverse:
  <https://dataverse.harvard.edu/dataverse/meysam_alizadeh> (file list not enumerated).
- **221 reproduction tasks from 54 papers**, four disciplines (political science,
  sociology, psychology, communication; the README also lists economics) and 13
  substantive domains. Up to 3 tasks per paper. R, Python and Stata.
- Ground truth is machine-readable: `benchmark/SocSci_Repro_Bench.json` (gold answers for
  all 221 tasks), `SocSci_Repro_Bench_RQ.json`, `SocSci_Repro_Bench_Metadata.json`,
  `benchmark/papers_tasks/1..54.json`. Gold answers of `"No Data"` / `"No Code or Data"`
  mark deliberately non-reproducible papers.
- Reported results: Claude Code 93.4% task-level / 78.0% paper-level; Codex 62.1% / 35.8%.
- **Task-shape mismatch:** the benchmark hands agents the *original analysis code* and asks
  them to execute it. The gold target quantities are reusable; the framing is not.

### 3b. REPRO-Bench — VERIFIED, but NOT LICENSED

Hu, Zhang, Lim, Wadhwani, Peters & Kang, "REPRO-Bench: Can Agentic AI Systems Assess the
Reproducibility of Social Science Research?", arXiv:2507.18901 (25 July 2025),
ACL 2025 Findings.

- Code: <https://github.com/uiuc-kang-lab/REPRO-Bench>; data:
  <https://huggingface.co/datasets/chuxuan/REPRO-Bench>
- **112 task instances**: paper PDF + reproduction package + gold reproducibility label.
  Provenance: 92 from Brodeur et al. (2024) mass reproducibility, 11 from the I4R
  Discussion Paper Series, 7 from Retraction Watch, 2 from Twitter/X posts.
- Ground truth is *assessment*-shaped (is this paper reproducible?), not per-quantity
  numeric targets. Wrong task shape for a re-implementation tool.
- **No licence anywhere** — GitHub API returns `license: None`, the HF card has no licence
  tag. Default is all-rights-reserved; contact the authors before redistributing
  derivatives. The HF dataset viewer is also broken (inconsistent split formats).
- Baseline accuracy 21.4% for the best existing agent.
- Related, not investigated in depth: PaperRepro (arXiv:2603.00058) introduces
  REPRO-Bench-S, a difficulty-stratified variant.

### 3c. Institute for Replication (I4R) — VERIFIED, large and public, ground truth mostly prose

- <https://i4replication.org/reports> — **241 reports across 15 journals**, each linking to
  an individual OSF project. No CSV export, no API, no bulk database.
- <https://i4replication.org/papers> — 232+ discussion papers.
- <https://github.com/I4Replication> — 4 public repos.
- **The one bulk machine-readable outcome source:**
  <https://github.com/I4Replication/I4R-First-Meta-Paper> (**MIT**), the replication
  package for the Nature meta-paper. Per-paper outcomes as Stata/CSV, notably
  `Replication Package/data/Cleaned - First Meta Database - For I4R - 10 Jan 2025.dta`,
  plus `Team - Cleaned…dta`, `many_analysts.dta`, `MM Data.dta`. Covers 110 papers and
  5,500+ reanalyses.
- Licence: the reports themselves carry no licence statement; each OSF project has (or
  lacks) its own. Treat per-report reuse as unlicensed unless the OSF page says otherwise.

Economics precedents:
- I4R Discussion Paper No. 107, "Mass Reproducibility and Replicability: A New Hope",
  April 2024.
- Brodeur, Mikola, Cook, Fiala, Brailey, Briggs et al., "Reproducibility and robustness of
  economics and political science research", *Nature*, 1 April 2026,
  doi:10.1038/s41586-026-10251-x (Crossref-verified). 110 papers; ~25% contain coding
  errors; 70% robustness across 5,500+ reanalyses.
- 2026 successor: Brodeur, Valenta, Marcoci, Aparicio, Mikola et al., "AI-assisted teams
  outperform AI-led teams but not human-only teams in assessing research reproducibility
  in quantitative social science", *PNAS*, 28 May 2026, doi:10.1073/pnas.2524747123
  (Crossref-verified). Package <https://github.com/I4Replication/AI-Games> (code MIT,
  data CC BY 4.0); preregistration <https://osf.io/sz2g8/>.

### 3d. I4R × Psychological Science — VERIFIED as ONGOING, nothing released

<https://i4replication.org/projects/psychological-science-collaboration> (fetched
directly). Launch date 1 December 2023, status "Ongoing". Scope: verify computational
reproducibility, find coding errors, check deviations from preregistration, assess
robustness, at scale, executed through Replication Games. The announcement was published
in the journal itself. **Number of target papers not disclosed; no completed outputs,
dataset or results are publicly linked.** Confirmed against the projects page, the reports
page and the I4R blog (posts through 27 August 2026).

Other non-economics I4R projects, all "Ongoing" with no public outputs:
Nature Human Behaviour collaboration (100 papers,
<https://i4replication.org/projects/nature-human-behaviour-collaboration>), tropical
disease research, early childhood interventions.

### 3e. Near-identical prior art — Kohler et al. 2026

Kohler, Zollikofer, Einsiedler, Hoyle & Ash, "Read the Paper, Write the Code: Agentic
Reproduction of Social-Science Results", arXiv:2604.21965, 23 April 2026.
Abstract verified directly.

This is the same design as the tool being built: agents extract structured methods
descriptions from papers and reimplement them under strict information isolation —
"agents never see the original code, results, or paper" — with deterministic cell-level
comparison to the original results and an error-attribution step. Corpus: **48 papers
with human-verified reproducibility** (the set I4R classified as fully reproducible),
from AER, EJ, AJPS, JOP and APSR. Four agent scaffolds x four LLMs. Finding: agents
largely recover published results; failures split between agent errors and
underspecification in the papers themselves.

They also ran a contamination check: performance on papers published before vs after the
August 2025 model cutoff showed no statistically significant difference.

**No data/code availability statement or repo URL found on the arXiv abstract page.**
Whether their pipeline or task set is released is UNVERIFIED — worth emailing the authors.

### Suitability summary

| Corpus | Verified | Open for reuse | Data + ground truth | Contamination risk | Role |
|---|---|---|---|---|---|
| SocSci-Repro-Bench (221 tasks / 54 papers) | Yes | Yes, CC BY 4.0 | Yes, gold JSON per task | Public since ~Mar 2026; authors' own memorisation test found 11.1% metadata recall | **Best development corpus.** Psychology, sociology and communication coverage fits. Strip the provided code, keep the gold quantities. |
| REPRO-Bench (112 tasks) | Yes | **No licence** | Packages + gold reproducibility labels | High — arXiv Jul 2025, ACL 2025, heavily downloaded | Reference only. Wrong task shape; needs author permission to redistribute. |
| I4R public reports (241 reports) | Yes | Partly — reports unlicensed; `I4R-First-Meta-Paper` is MIT | Structured outcomes for 110 papers in .dta/.csv; the rest are prose PDFs | High — public since 2024 | Best source of human-reanalysis ground truth for development; needs parsing of prose reports beyond the 110-paper meta database. |
| I4R x Psychological Science | Yes (ongoing) | Nothing released | Not yet | **Zero — unpublished** | **Strongest held-out validation candidate.** Requires contacting I4R (contact@i4replication.org) about embargoed or in-progress reports. Nature Human Behaviour (100 papers) is a second candidate. |

**Two structural warnings**

1. **Circularity.** REPRO-Bench draws 103 of its 112 tasks from I4R sources, and Kohler et
   al. draw all 48 from I4R. An I4R-development / REPRO-Bench-validation split would be
   testing on training data. SocSci-Repro-Bench is the only one of the three with
   provenance independent of I4R, so an I4R-dev / SocSci-Repro-Bench-holdout split (or the
   reverse) is defensible; an I4R / REPRO-Bench split is not.
   A second, separate overlap: Multi100 and ReplicatorBench both derive from DARPA SCORE,
   so their paper sets may intersect. Compare paper IDs before using one for development
   and the other for evaluation (see section 2).
2. **Contamination cuts by date, not by dataset.** Everything public here predates
   mid-2026 and is inside current model training data. A genuinely clean held-out set must
   be material published after the evaluation models' cutoffs — in practice the unreleased
   I4R Psychological Science and Nature Human Behaviour outputs. The pre- vs post-cutoff
   date split that Kohler et al. ran is the cheapest defensible substitute.

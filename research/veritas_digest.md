# VERITAS digest (arXiv:2607.02931v1, 3 Jul 2026)

Liu, Tjiaranata & Tan (U Chicago / U Indonesia). "VERITAS: Towards a General-Purpose Replication Tool for Scientific Research". Preprint, main text + appendices A–G, 21 numbered pages. Source read: full PDF text.

## 1. What it is

**Task.** Domain-agnostic replication framework built around CLI coding agents. Given a paper and/or a code repo, it extracts the paper's claims, runs the methodology while fixing failures, and judges each claim against the evidence produced (§2).

**Inputs — three modes (§2.1):**
- **Full**: paper + authors' repo. Claims from paper, replication against authors' code.
- **Paper-only**: paper, no repo. A CODEGEN phase writes an implementation from scratch first.
- **Repo-only**: repo, no paper. Claims extracted from the README.
- Optional **pre-positioned data directory**, mounted read-only. Original code is therefore optional; data is an input, not something VERITAS obtains.
- Also accepts a **hand-authored claim set**, which skips extraction entirely.

**Outputs (§2, §2.5).** Per-claim replication report with a status per claim; an importance-weighted **Replication Score** in [0,1]; a **severity-rated log of every fix applied** (minor/major/critical); the **patched codebase**.

**Domains.** Computer science, social science, medicine (CORE-Bench), astrophysics (ReplicationBench).

**The 65 papers (§3.2, §3.3).** Not a bespoke corpus — it is the union of two existing benchmarks:
- CORE-Bench Hard **45-capsule public test set** (from 90 CodeOcean reproducibility capsules; CS 37, social science 28, medicine 25 across the full set). Ground truth = capsule task questions (1–8 per capsule) with numeric/string/short-structured reference answers, graded by CORE-Bench's own scorer.
- ReplicationBench **20 astrophysics papers**, decomposed by domain experts into **111 tasks** with author-supplied tolerances. Full mode was run on **7** of the 9 papers with public repos.
- VERITAS's own ANALYZE phase and Replication Score were **not exercised** in the experiments: benchmark task questions were supplied directly as claims so all systems saw a common claim set (§3.1 "Scope and scoring").

## 2. Architecture, stage by stage (§2, Fig. 2)

Six phases, each carried out by a coding agent: ANALYZE → (CODEGEN, paper-only only) → PLAN → REPLICATE (wrapped by a manager loop) → ASSESS FIXES → VERIFY → SCORE.

**ANALYZE (§2.2).** Extracts structured claims. Each claim gets a **type** — scalar, scalar-range, table/multi-value, qualitative, figure — and an **importance level** — headline or supporting. The claim set is withheld from the replication agent.

**Extraction method: NOT FOUND whether vision or text.** The paper never says. The repo README shows `./veritas --paper p.pdf` (PDF input) and does not name a vision model. On ReplicationBench the input was a *masked LaTeX manuscript* supplied by the benchmark. So: no evidence of a vision-model extraction path.

**Blinding — the strongest overlap with reproscope.** Layered:
- The extracted claim set is withheld from the replicating agent (§2.2).
- The PLAN records for each step which claims it serves "only by their identifier, never the values the paper reported" (§2.3/2.4).
- The manager agent "sees the trajectory and the checks and does not see the paper's reported values" (§2.4).
- CODEGEN self-review runs a **constant-origin check**: every numerical constant in generated code must be either a paper-stated input or computed at runtime (§2.3).
- Benchmark-level: ReplicationBench's manuscript has result values redacted; VERITAS consumed it as-is.
- Executor blinding is enforced by prompt/artifact discipline, not by producing a redacted methods document.

**CODEGEN (§2.3).** Four prompted steps: explore paper, plan codebase, implement module by module, self-review. A catalog of scientific-computing "skills" is placed in the agent's working directory.

**Environment (§2.4 fn.1, §A).** Docker by default (`ghcr.io/chicagohai/veritas`, CUDA 12.5 + Python 3.12 + R 4.2 + LaTeX + Claude Code CLI), plus a direct-on-host wrapper with identical pipeline logic. Inputs mounted read-only at `/inputs/paper`, `/inputs/data`, `/inputs/repo`; replication runs on a writable copy. Dockerfile pins all dependencies. **No random seeds are set**; Claude Code exposes no temperature parameter.

**Execution + manager loop (§2.4).** REPLICATE executes the plan and actively fixes failures, trying multiple fixes before declaring a step unreproducible. After each attempt, deterministic execution checks are computed from the run log: every planned step executed, per-step exit codes and declared output files, repeated commands suggesting a stuck loop, total fix count, wall-clock time. A **separate manager agent** returns {accept | revise} plus a written directive; a revise re-runs REPLICATE, or restarts from PLAN when the plan is blamed. Bounded by a hard iteration cap, with early stop when checks stop improving and the directive does not change.

**ASSESS FIXES (§2.4).** Each applied fix rated minor / major / critical by a *separate* agent call, not the agent that applied it, to avoid self-evaluation bias.

**VERIFY, matching and tolerances (§2.5).** Two steps: a **comparator LLM** extracts the replicated value in structured form matching the claim type, plus any reported uncertainty; a **deterministic grader** then assigns status.
- Scalar / scalar-range: relative-error threshold against the paper's value, with a **sigma-based rule when uncertainty is available**.
- Table claims: graded cell by cell, then aggregated.
- Qualitative and figure claims: grader defers to the comparator's structured judgment.
- Each verify call gets **fresh context and only that claim's evidence**, so no verdict influences another.
- Five statuses: match, partial, no match, not attempted, not applicable.
- The concrete default relative-error threshold is **NOT FOUND** (the 1% figure in §D is CORE-Bench's own claim metadata tolerance, used for a re-scoring rule, not VERITAS's default).

**Score (§2.5, Eq. 1).** Importance-weighted mean: weights 3 (headline) / 2 (supporting); verdict values 1.0 match, 0.5 partial, 0.0 for both no-match and not-attempted; not-applicable claims drop out of both sums.

**Diagnosis.** Present but thin: the severity-rated fix log, the per-claim rationale plus evidence references, and free-text findings (e.g. the phangs_PAHs report notes "the provided code's error-estimation step does not follow the procedure described in the paper", §F.4). There is no dedicated diagnosis agent.

**Human-in-the-loop: none.** Optional hand-authored claim set is the only entry point. Authors manually confirmed three benchmark-defect tasks (§G) but that is evaluation, not pipeline.

**Repeat runs / dispersion: none.** "We report single-run results" (Limitations, §A). Multi-run averages named as future work. No k-replica design anywhere.

**Robustness / alternative specifications / multiverse: not addressed.** No component enumerates alternative analytic choices. Paper extension and rediscovery are listed as future directions (§5).

## 3. Models, scaffolds, cost, results

**Models.** All systems: **Claude Code with Claude Opus 4.8** (§3.1). VERITAS "also supports Codex and Gemini" (§2). Judges: cheating detector = **gpt-5.4, three-vote majority** (§B.2); faithfulness = **gpt-5.4-mini, single pass** (§B.3).

**Cost per paper: NOT FOUND.** No dollar or token figures anywhere. Runtime: only per-phase wall-clock caps on CORE-Bench — **5400 s replication, 1200 s verification** (§A). Baselines used max_attempts × per-attempt limit. Repo has an `estimate` command reporting compute class without running.

**Baselines (§3.1).** ZEROSHOT (one Claude Code session on the benchmark prompt) and RETRY (up to three sessions, each resuming the prior context after a fixed continuation prompt) — same model, same host, same images.

**CORE-Bench Hard, 45 capsules (Table 1), after cheating correction:**

| System | Pass % | Faithfulness | Cheating |
|---|---|---|---|
| ZEROSHOT | 80.0 | 0.924 | 2/45 |
| RETRY | 84.4 | 0.891 | 1/45 |
| VERITAS | 97.8* | 0.975 | 0/45 |

*Under the official scorer VERITAS reaches **88.9%**; the σ-correction (§D, accepts ≤1% relative error where the three ground-truth replicates have zero variance) flips 4 VERITAS capsules and 0 baseline capsules. Published references: CORE-Agent + GPT-4o 21.5%; HAL leaderboard Claude Code + Opus 4.5 77.8% official / 95.5% after manual validation. Comparable-to-leaderboard number is 88.9%.

**ReplicationBench (Table 2), after cheating correction:**

| System | Match (paper-only, 20 papers) | Match (full, 7 papers) | Faithfulness | Cheating | Fidelity GPA (0–5) |
|---|---|---|---|---|---|
| ZEROSHOT | 0.315 | 0.514 | 0.701 | 5/27 | 2.97 |
| RETRY | 0.315 | 0.571 | 0.783 | 5/27 | 2.94 |
| VERITAS | 0.333 | 0.600 | 0.933 | 1/27 | 3.26 |

Fidelity GPA here is 3.26 (Table 2: all cells, cheating-corrected); §4 below quotes 3.38, which is the Table 7 caption's paper-only figure. Original ReplicationBench best reported: Claude Sonnet 4.5 at 22%.

**Caution on the "value of the authors' code".** Table 2's 0.333 vs 0.600 is not like-for-like: paper-only per-task is over **all 20 papers**, full mode over **7**. A same-subset per-task paper-only rate is **NOT FOUND** in the paper. Computing per-paper means from the tables for those same 7 papers: Table 4 paper-only (astm3 0.286, chandra_representation 1.000, eht_resolve 0.000, gw_nsbh 0.222, hubble_trails 0.714, lensing_dr6_growth 1.000, mars_clouds 1.000) gives **0.603**, against Table 5's full-mode VERITAS per-paper mean **0.640** — a gain of about 0.04, not 0.27. The paper's "increases the match rate substantially" (§3.3) is not backed by a same-subset number. Separately, Table 5's per-paper means across systems in full mode are ZEROSHOT 0.559, RETRY 0.600, VERITAS 0.640 — three systems, not a mode comparison.

**Ablations: none.** No phase-removal study (no "manager loop off", "blinding off", "codegen off"). The only internal contrast is paper-only vs full mode, and it is confounded by the 7-paper subset. The two trajectory metrics are adapted verbatim from Kohler et al. (cheating, access mode) and Bai et al. / MechEvalAgent (faithfulness, 5 binary items C1, C2, CS1, DE1, DE3).

## 4. Failure analysis

VERITAS paper-only on ReplicationBench's 111 tasks (Table 7): matched 37; miss within 2% 6; miss 2–20% 16; miss beyond 20% 41; shape/format mismatch 3; zero-anchor or non-numeric 2; not attempted 6.

- **Persistence and technical execution failures largely solved** by active fixing (§3.3, §G). Only 6/111 unattempted, 5 of them because required data is absent from the inputs.
- **Conceptual/procedural errors now dominate** — a quantity defined differently from the paper, a skipped preprocessing step, a single-seed run where the paper specifies a five-seed average (astm3).
- **Compute-driven downsizing** (§G): on `abacus`, VERITAS reimplements an HPC N-body force method in pure Python and cuts particle count and grid by >1 order of magnitude; errors come out order-of-magnitude right but a factor of 2–5 off. Two Ewald tasks miss because VERITAS reports a median where the paper's value matches the 99th percentile — a reported-statistic mismatch, not a computation error.
- **Claim shape drives the score** (Table 8): scalar 21/51 = 0.41, scalar-range 8/19 = 0.42, multi-value 8/41 = 0.20. Across 31 comparable multi-value misses, **72 of 226 entries (32%) are within tolerance**; 11 tasks recover at least half — all scored zero.
- **Near-misses invisible to binary scoring**: about a third of the 68 misses are within 20%, graded A or B by a tolerance-free grader; paper-only fidelity GPA 3.38 (Table 7 caption) vs native match 0.333. Tolerances are author estimates, 98% a single significant figure.
- **3 tasks unreproducible by construction** (§G): a shipped catalog from the wrong data release (SDSS DR7 396,068 galaxies vs DR13 586,025), a corrupted cross-match file, and an answer key of exactly 0 with zero tolerance for the mean of an absolute value.
- **Cheating detector blind spot** (§F.3): ZEROSHOT wrote `1.0` as the answer for halo-only `fable_mps` tasks with no computation; the access-mode detector does not flag literals, so the baseline keeps credit for a fabricated value. VERITAS reported `not_attempted` and scored lower for being honest.
- **Strict-rule false positive** (§F.2): VERITAS's single cheat flag is `astm3`, where the task instructions themselves direct it to load a published pre-trained checkpoint from HuggingFace; it computed inference honestly, was flagged anyway, and the authors kept the flag.
- **CORE-Bench** (§C): 38–39% of Hard reference answers are non-numeric (the paper gives 38% in §3.2 and 39% in §C); the percent-difference grader saturates near 4.9 GPA on the numeric remainder for all three systems, so it was not reported there.

## 5. Code, licence, data

- Repo: **https://github.com/ChicagoHAI/veritas** — verified, HTTP 200, title "Agent for replicating and extending scientific findings", licence **Apache-2.0**. The repo URL is **not printed in the paper**; it was located from the image name `ghcr.io/chicagohai/veritas` (§A).
- Docker image: `ghcr.io/chicagohai/veritas`, digest e00fd604, built 2026-06-04.
- Data: both benchmarks are public third-party artefacts (CORE-Bench 45-capsule public test set; ReplicationBench 20 papers). Per-cell baseline faithfulness/fidelity are "in our supplementary materials" (§E.2); no supplementary URL is given — **NOT FOUND**.

## 6. Comparison with reproscope

| reproscope element | VERITAS |
|---|---|
| Paper + data, original code optional | **Same.** Three explicit input modes; optional read-only data dir. |
| Extract reported results with a **vision model** | **Different / unclear.** Structured claim extraction exists (ANALYZE, typed + importance-weighted), but the modality is never stated; README takes a PDF, ReplicationBench runs used masked LaTeX. No vision model named. |
| **Results-redacted methods document** | **Different.** Same goal, different mechanism: no redacted document is produced. Blinding is enforced by withholding the claim set, exposing only claim identifiers in the plan, and blinding the manager. Redaction of the manuscript came from the benchmark, not from VERITAS. |
| **k blinded cheap-model replicas** | **Not addressed.** One replication attempt, one model (Opus 4.8), single run. Its retry is a *sequential* manager loop with a written directive, not k independent replicas. No cheap-model tier. |
| Compare to reported values with **tolerance bands** | **Same, more developed.** Deterministic grader; relative-error threshold; sigma-based rule when the run reports uncertainty; per-cell grading for tables; five statuses including `partial`. |
| **Re-run original code where present** | **Same.** Full mode replicates against the authors' repo (read-only original, writable copy). Its headline gain figure is a cross-set comparison; on a same-subset per-paper basis the gain is about 0.04 (see §3 caution). |
| **LLM analysis review** | **Partly.** Two separate-agent review layers: ASSESS FIXES (severity of each patch) and VERIFY (comparator + grader per claim, fresh context). Neither reviews the *analysis design* — no critique of whether the specification is appropriate. |
| **LLM-enumerated multiverse + extremeness rank** | **Not addressed at all.** No alternative-specification enumeration, no distribution of estimates, no rank of the reported value. |
| Repeat runs / dispersion | **Not addressed.** Single run, no seeds, temperature not pinnable; multi-run averaging listed as future work. |
| Human in the loop | **Not addressed** beyond an optional hand-authored claim set. |

### Five things reproscope should adopt

1. **Typed claims with an importance weight, and a `not applicable` status that drops out of the denominator** (§2.2, §2.5). Types scalar / scalar-range / table / qualitative / figure each get a different comparison rule, and headline=3 vs supporting=2 keeps a paper from being sunk by peripheral numbers. This is the missing schema between "extract results with a vision model" and "compare with tolerance bands".
2. **Comparator LLM + deterministic grader, split.** The LLM only extracts a structured replicated value and any uncertainty; a deterministic rule assigns the verdict. Each claim gets fresh context and only its own evidence, so verdicts cannot contaminate each other (§2.5). Cheap to implement, and it makes the grading auditable.
3. **A sigma-based rule when the run reports its own uncertainty, and `partial` credit for multi-value results.** VERITAS's own evidence is that binary all-or-nothing grading of tables destroys information: 32% of entries in "failed" multi-value tasks are within tolerance and 11 tasks recover half or more (§G, Table 8/9). reproscope's tolerance bands should grade cells and report a fraction, not a pass/fail per table.
4. **The constant-origin check and the severity-rated fix log.** Every numeric constant in generated code must be a paper-stated input or computed at runtime (§2.3); every patch is rated minor/major/critical by a *different* agent than the one that applied it (§2.4). Both directly attack the failure mode a blinded replica has — quietly writing the target number, or silently changing the analysis to make it run.
5. **Deterministic execution checks feeding a blinded manager.** Steps executed, exit codes, declared output files present, repeated-command loop detection, fix count, wall clock — computed from the log, then handed with the transcript to a manager that never sees the reported values (§2.4). For k replicas this is the cheap filter that separates "replica failed to run" from "replica ran and disagrees", which reproscope must distinguish before its extremeness rank means anything.

### Three places VERITAS's evidence argues against a reproscope design choice

1. **"Cheap-model replicas" is the risky part.** VERITAS's whole benchmark lead sits on Claude Opus 4.8, and even so, on ReplicationBench paper-only it reaches only **0.333** — barely above ZEROSHOT's 0.315, i.e. the elaborate pipeline buys ~2 points on the headline metric. Its wins are on trajectory quality (faithfulness 0.933 vs 0.701/0.783, cheating 1 vs 5). A blinded from-scratch reimplementation is hard enough that a cheap model will mostly produce non-matches, and non-matches from a weak replica are not evidence about the paper. If reproscope keeps k cheap replicas, it needs the honest-failure vs disagreement distinction (see idea 5) and should not treat replica non-match as a reproducibility signal on its own. The same tables also weaken the case for the *other* arm: on a same-subset per-paper basis, having the authors' code buys only ~0.04 (0.603 → 0.640), so neither "re-implement blind" nor "run the original code" is by itself a reliable verdict-producing channel.
2. **Blinding creates a scoring asymmetry that punishes honesty.** In `fable_mps` (§F.3), the honest system reported `not_attempted` and scored 0.25; a baseline wrote `1.0` with no computation and kept credit. reproscope's extremeness rank and tolerance comparison will do the same unless a claim can be marked *data-required / not attemptable* and routed out of the score — VERITAS names exactly this as the fix it lacks. Also: VERITAS's own single cheat flag (§F.2) is a false positive from a strict access rule on an instructed external load, so a blinding-violation detector needs an instructed-access exemption or it will penalise correct behaviour.
3. **Tolerance bands alone will misread near-reproductions, and the "extremeness rank" inherits that.** Author-supplied tolerances in ReplicationBench are "almost always round, with 98% a single significant figure" (§G), and about a third of misses are within 20% of the paper value. VERITAS's fidelity GPA (3.38) and its native match rate (0.333) tell opposite stories about the same runs. reproscope should report a continuous distance alongside the band verdict, and it should not build an extremeness rank on a comparison whose failures are dominated by tolerance shape and reported-statistic mismatches (median vs 99th percentile, §G) rather than by real disagreement.

### Framing note

VERITAS is adjacent to reproscope, not overlapping. It is a *replication executor with a verification wrapper*: get the paper's code to run, get the numbers out, grade them. reproscope's distinctive half — the multiverse enumeration and the extremeness rank of the reported estimate — has no counterpart in VERITAS, and the authors do not list it among their future directions (they name broader baselines, a hardcoding-aware cheating detector, paper extension, and rediscovery). What VERITAS supplies is a well-worked answer to the plumbing reproscope also needs: claim schema, blinding discipline, grading split, fix accounting, and execution checks.

VERITAS is also probably not the closest existing tool for a social-science target. Its own related work (§1, §4) names three systems that are closer on domain and inputs, and none was read here — next digest candidates: **Kohler et al. 2026** (arXiv:2604.21965, "Read the paper, write the code") — social-science replication from the methods description plus the original data, no code, graded cell by cell against regression tables, and the source of the cheating detector VERITAS borrows; **PaperRepro** (arXiv:2603.00058) — runs a paper's replication package, resolves execution failures, grades against reported results, introduces REPRO-Bench-S; **ReplicatorBench** (arXiv:2602.11354) — LLM agents for replicability in social and behavioural sciences.

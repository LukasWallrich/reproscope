# v0 pilot notes

Running log of decisions, deviations and spend for the first pilot (started 2026-09-02).

## Corpus

Five Multi100 psychology papers set up under `corpus/` (see `reproscope/corpus_setup.py`):

| paper_id | focal analysis | data | PDF |
|---|---|---|---|
| Ohtsubo_EvoHumanBehavior_2014_zlm2 | independent-samples t-test, n = 29 after one exclusion | 3-sheet .xls, partly Japanese labels, pre-exclusion (30 rows) | green OA (Kobe repository, submitted version) |
| Hurst_EvoHumanBehavior_2017_yypJ | correlation / OLS, n = 138 | Dataset.csv + Codebook.xlsx | publisher PDF via institutional access |
| Axt_JournExpSocPsych_2018_zK2 | t-test on IAT D-scores, n = 856 | Study1Data.csv + codebook + original SPSS syntax | PsyArXiv preprint (pagination differs from the journal version) |
| Petersen_Cognition_2017_yJwG | paired t-test on TVA parameters, n = 28 | three CSVs | author-repository copy of the published article |
| Hertel_ClinPsychSci_2018_YabW | 2×2 mixed ANOVA, n = 54 | one .sav | publisher PDF via institutional access (user download) |

Multi100 ground truth per paper (claim, reported statistic, analysts' Cohen's d range) is in each manifest.

## Deviations from SCOPE.html

- **No Docker.** Replicas run on the local R 4.6.1 / Python 3.14 stacks; each trace records `sessionInfo()` or `pip freeze`.
- **`claude -p` runs with `--setting-sources project`** so the user's global CLAUDE.md does not steer replicas or judges.
- **Re-run arm** is abstained for papers whose original code is SPSS syntax (no SPSS on the machine).
- **Axt** is run on the preprint; page locations will not match the journal version, and numbers may differ where the preprint predates revision.
- **Replica lineup for the calibration run**: Opus ×2, Fable ×1, GPT-5.6 Sol ×1 (all subscription) and GLM-5.3-flash ×2, DeepSeek-v4-flash ×2 (OpenRouter). Cheap-versus-frontier comparison is on the same blind directories.

## Cost estimate (before spending)

Budget: USD 10 outside subscriptions. Metered spend goes only through OpenRouter.

| item | per paper | basis |
|---|---|---|
| Stage 0 vision extraction, two models | ~$0.03–0.10 | 10–30 page images × ~1.5k tokens each × 2 models at $0.075–0.20/MTok in, plus a few k output tokens |
| Stage 0/1 cheap structured calls (link, audit, severity, enumerate) | ~$0.02–0.05 | dozens of calls at < 20k tokens |
| Cheap agentic replicas, 4 per paper | ~$0.20–0.80 | opencode carries a ~17k-token system prompt per turn; 20–60 turns per replica at $0.075–0.14/MTok in |
| Stage 3 executor (opencode) | ~$0.05–0.20 | one agentic run |
| **Total** | **~$0.3–1.2 per paper**, so roughly $1.5–6 for five papers | |

Actual spend is read from `runs/<paper_id>/ledger.jsonl` (`python -m reproscope ledger <paper_id>`) and reported in the evaluation writeup.

## Findings log

- **2026-09-02, Stage 0 on Ohtsubo.** 26 model calls: 8 OpenRouter calls at $0.078 (two vision extractors over 30 pages in 8-page chunks, plus contract scrubbing) and 18 strong-tier calls on subscriptions (15 Opus, 3 Codex) with a list-price equivalent of $16.58. At list price a single paper's intake already exceeds the scope's $2–10 envelope; the envelope holds only with subscription routing or a cheaper strong tier. The arbiter, contract writer, readiness check, redactor and description scrubber each read the full 55k-character paper text, so the cost scales with paper length rather than with the number of claims.
- Extraction: 204 claims, 83% two-model agreement, focal claim (t = 5.91, p. 16) found by both extractors. Redaction: deterministic scan clean; the Codex leak audit still rated leakage "strong" for structural reasons (the claim inventory reveals which analyses carry p-values; one exclusion rule is itself an outlier value). This is a limit of results-redaction as a method, not of the redactor.
- Only 6 of 40 analyses can be bound to data (Study 2a); the other 34 abstain at intake and are withheld from the replicas.
- Expected Stage 1 outcome on Ohtsubo, written before the run: the file holds 30 rows and the excluded participant is unmarked, so replicas should reach t ≈ 6.2 (band B against 5.91) and d ≈ 2.26 (B against 2.20), means 4.58 (A) and 2.78 (B against 2.82). No replica should reach band A on the focal t; that triggers the targeted reconstruction, whose question is whether any defensible exclusion reaches the reported values.
- **2026-09-03, where the time and tokens went (five papers, before the fix).** The claim-to-result link step made 4,691 cheap-model calls (10.8 M tokens, $2.06, 9.3 cumulative hours) because it called a model for every claim × replica pair. Replicas key their results by claim id, so linking is now deterministic and the model is called only for a replica that ignored the format. Stage 0's strong-tier calls (61 calls, 14.4 M tokens, $74 list-equivalent) each read the whole paper; agentic replicas took 21 M tokens ($1.47 metered plus $31 list-equivalent on subscriptions). Metered total at that point: $4.96.
- **2026-09-03, rebuild after the efficiency audit.** The audit's work list (docs/HANDOFF.md of that morning) is implemented: deterministic arbitration with cheap-vision batches, one strong call for contracts plus redacted methods with local leak repair, the leak scan limited to inferential and headline quantities, CONTRACT.json grouped per analysis, abstained match rows, one shared focal-claim binding, a targeted arm on the focal quantity only, Stage 2 scoped to the focal analysis, Stage 3 capped at 64 executed specifications, content-hash cache keys with per-step input and prompt checks, `--force-step`, and complete ledgering. Matching, targeted arm, reviews, multiverse and reports were rebuilt on the pilot's replica outputs for all five papers: USD 0.49 metered and USD 27 list-equivalent including retries, or USD 1.9–6.0 list-equivalent per paper for a single clean pass of Stages 1–3. Claude Opus returned "529 Overloaded" on 15 strong-call attempts during the rebuild. Five of the seven replicas marked failed re-execute cleanly once the checker runs the script in its isolation copy and from its own directory; the two DeepSeek scripts on Petersen import scipy, which the re-execution interpreter lacks. Writeup: docs/evaluation/PILOT_EVALUATION.html.

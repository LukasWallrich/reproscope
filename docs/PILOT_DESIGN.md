# reproscope v0 pilot — build design

Single source of truth for the pilot build. Every subagent implementing a stage reads this first.
SCOPE.html holds the rationale; this file holds the mechanics.

## Layout

```
reproscope/                Python package (Python 3.14, uv-managed .venv)
  cli.py                   python -m reproscope run <paper_id> --stages 0 1 2 3 [--from <artifact>]
  config.py                loads models.toml: tier -> {route, model}; per-stage overrides
  llm.py                   the only place that talks to models (see Model routes)
  ledger.py                append-only runs/<paper_id>/ledger.jsonl: one row per model call
  artifacts.py             pydantic models for the artifact chain + load/save + input hashing
  paths.py                 corpus/run path helpers
  stage0/                  extract.py arbitrate.py contracts.py readiness.py redact.py leakcheck.py
  stage1/                  blind.py replicas.py rerun.py match.py audit.py targeted.py diagnose.py
  stage2/                  review.py
  stage3/                  multiverse.py
  report/                  build.py (HTML + JSON sidecar), templates/
  prompts/                 <stage>_<step>.md, versioned by file content hash (recorded in artifacts)
models.toml                model configuration (user-editable)
corpus/<paper_id>/         manifest.json (tracked) + paper.pdf, data/, code/, pages/ (gitignored)
runs/<paper_id>/           stage0/ stage1/ stage2/ stage3/ report/ ledger.jsonl (gitignored)
docs/                      this file, pilot notes, evaluation writeup
```

## Manifest (corpus/<paper_id>/manifest.json)

```json
{"paper_id": "...", "title": "...", "doi": "...", "pdf": "paper.pdf", "licence": "...",
 "data_files": ["data/x.csv"], "codebook": null, "original_code": [],
 "focal_claim": {"text": "...", "source": "multi100", "reported": {"statistic": "...", "value": ..., "df": ..., "n": ..., "page": ...}},
 "multi100": {"paper_id": "...", "n_analysts": ..., "analyst_d": {"min":..,"median":..,"max":..}},
 "environment": {"language_hint": "R", "versions_named": {}}}
```

## Artifact chain (reproscope/artifacts.py)

All artifacts are JSON files. Every artifact carries `meta`: `{artifact, version, created, stage, inputs: {name: sha256}, prompt_versions: {name: sha256}, model_calls: [ledger ids]}`.
Every claim-level artifact carries `claim_id`. Every artifact may have `state: "complete" | "abstained"` with `abstain_reason` and `confidence: "high"|"medium"|"low"` and `open_ambiguities: [str]`.

- `ClaimRecord` (stage0/claims.json, list): claim_id, study_id, claim_type (scalar|range|table_cell|qualitative|figure), importance (headline|supporting), quantity_kind (coefficient|p_value|t|F|chi2|d|r|OR|mean|sd|n|ci_bound|other), value, precision (decimals as reported), uncertainty (se/ci if reported alongside), location {page, kind: table|figure|text, label, cell}, description (the sentence or cell header), extraction {model_a, model_b, agreed: bool, arbiter_note}.
- `EstimandContract` (stage0/contracts.json, list; one per analysis, linked from claims): analysis_id, claim_ids, study_id, sample_rule, outcome, predictors, covariates, model_type, estimator, se_type, transformations, weights, missingness, software_named, versions_named, ambiguities [ {field, options, note} ].
- `DataReadinessRecord` (stage0/readiness.json): files [{path, format, rows, cols}], unit_of_observation, keys, missing_sentinels, variable_bindings [{contract_field, candidate_columns, chosen: null, note}], scale_direction_notes, weights_columns, state (complete|abstained per analysis_id).
- `RedactedMethods` (stage0/redacted_methods.md + stage0/redaction_report.json): the replica document; report lists removed spans by kind and the deterministic scan result (must be zero hits) and the leakage-audit verdict.
- `ReplicaDecisionTrace` (stage1/replicas/<family>_<run>/trace.json): replica_id, family, model, route, filters, transformations, model_formula, missingness, weights, estimator_settings, seed, software (sessionInfo / pip freeze), fixes [{description, severity: minor|major|critical (rated by separate call)}], ran (bool), run_checks {steps_done, exit_code, outputs_present, loops, n_fixes, wall_s}, hardcoding_audit {hits: [...]}.
- `ReplicaResults` (stage1/replicas/<family>_<run>/results.json): list of {claim_id, analysis_id, value, se, ci, n, note} written by the replica agent; must be produced by code, not typed.
- `ComparableResult` (stage1/match.json): per claim_id × replica: reported, replicated, unit_check, raw_diff, std_diff (by replica se where available), sign_match, band (A|B|C|fail per quantity-specific rule), sigma_rule (within|outside|na); per claim summary: n_ran, fraction_matched, dispersion {decision_agreement, numeric_cv}.
- `TargetedReconstruction` (stage1/targeted.json): triggered (bool), outcome (reachable|reachable_indefensibly|not_reachable|not_triggered), added_choices [], attempts, notes.
- `Diagnosis` (stage1/diagnosis.md): unblinded conjecture, labeled as such.
- `AnalysisReview` (stage2/review.json + review.md): narrow {causal_language: CLAIMS-style rating with quotes, mde: assumptions + curve values, alignment: verdict + open choices per replica}, broad {findings: [{severity, quote, location, comment}]}.
- `SpecificationSpace` (stage3/space.json): factors [{name, source: trace|grid|default|code, levels: [{value, verdict: defensible|rejected, rationale}]}], incompatibilities [], grid_size, runs [{spec, estimate, se, p, converged}], reported_estimate, rank, n_specs, interpretation (separate call).

## Model routes (reproscope/llm.py)

One function `call(step, messages_or_prompt, *, tier, schema=None, images=None, cwd=None, agentic=False)` that dispatches on models.toml:

| route | invocation | used for |
|---|---|---|
| `openrouter` | POST /chat/completions with `response_format` json_schema when schema given, `usage.include=true`, provider `{sort:"price", preferred_min_throughput:40, require_parameters:true}`; images as base64 data URLs | vision extraction, cheap structured steps |
| `claude_p` | `claude -p --output-format json --model <m> [--permission-mode bypassPermissions] [--allowedTools ...]`, cwd set, `CLAUDECODE` unset in env; parse `result`, `total_cost_usd`, `usage` | strong arbitration/screen/review/diagnosis; frontier replicas |
| `codex` | `codex exec --skip-git-repo-check -m <m> [--sandbox read-only | --dangerously-bypass-approvals-and-sandbox] -C <cwd> -` prompt on stdin; final answer after last `codex` line; tokens from `tokens used` | second strong family; Sol replicas |
| `opencode` | `opencode run --format json --auto --dir <cwd> -m openrouter/<m> "<prompt>"`; parse NDJSON, final text + `step_finish.tokens/cost` | cheap agentic replicas and multiverse execution |

Every call appends a ledger row: `{id, ts, paper_id, stage, step, route, model, tokens_in, tokens_out, tokens_reasoning, cost_usd (0 for subscription routes, with cost_source: "subscription"), duration_s, ok, error}`. Structured calls validate the JSON against the pydantic schema and retry once with the validation error appended.

Long-running agentic calls are launched with a log file per call; the driver waits on the process, never polls a timer loop.

## Blinding (physical)

Replicas run in a fresh directory `runs/<paper_id>/stage1/replicas/<replica_id>/work/` containing ONLY: `METHODS.md` (redacted), `CONTRACT.json` (estimand contracts + claim records with `value`, `uncertainty`, `precision` fields removed, and descriptions scrubbed by the same redactor), `data/` (copy or symlink of data files, no original code), `TASK.md` (the replica instructions), and an empty `out/`. The deterministic value scan (stage0/leakcheck.py) runs over METHODS.md and CONTRACT.json before launch: every reported value from claims.json, plus its rounding to 1–3 decimals, plus its absolute value, is searched as a token; any hit blocks the launch. The LLM leakage audit (a model that has not seen the paper is asked to state the results from the blind directory contents) is run once per paper in the pilot and recorded.

## Replica task (stage1/replicas.py)

The replica agent: reads METHODS.md and CONTRACT.json, inspects data/, writes `out/analysis.R` (or .py), runs it, and produces `out/results.json` (schema above, one entry per claim_id it could bind), `out/trace.json` (ReplicaDecisionTrace fields it can fill), `out/run.log`. Rules stated in TASK.md: reproduce the paper's analysis faithfully (same sample rules, variables, model); when the methods leave a choice open, pick the most standard option, log it in trace.open_choices, and do not try alternatives; fix seeds; never type result numbers by hand; abstain per claim with a reason when it cannot bind the claim to the data. Deterministic run checks and the hardcoding audit run after the agent exits; the fix-severity rating is a separate cheap call over the agent's own fix list and the diff of its script versions if any.

## Matching rules (stage1/match.py)

Unit check first (cheap model flags rescaling, e.g. percentage vs proportion, then deterministic). Then by quantity_kind:
- coefficient/mean/sd/d/r (unbounded or effect sizes): sign gate; round replicated value to reported precision; relative diff bands A <2%, B <20%, C <40%, else fail; absolute rule |diff|<0.002 when |reported|<0.001.
- p_value: match if both on the same side of .05, .01, .001 thresholds AND (both <.001 or relative diff <50%); report raw diff.
- t/F/chi2: same as coefficient bands but on the statistic.
- OR / HR: bands on log scale.
- ci_bound: band on the bound with the same rule as its estimate.
- n: exact or within 1%.
When the replica reports se: sigma rule = |reported − replicated| / se ≤ 2.
Tables: fraction of cells matched (A or B), reported per table.

## Stages 2 and 3 (pilot minimum)

Stage 2: three narrow checks (CLAIMS causal-language rating with quotes; MDE/sensitivity curve with stated assumptions computed in R from the data's n and structure; claim–analysis alignment against the contract and the replicas' open choices) and one broad referee-style pass, all strong tier, reading the full paper text (pdftotext layer plus page images if needed), the readiness record, and replica code.
Stage 3: on the focal claim only. Enumerator (cheap) proposes factors from trace disagreements, a decision grid over the methods and schema, and standard defaults; screen (strong, different family) labels every level with a rationale and flags incompatible combinations; an executor agent (cheap, agentic) takes the best-matching replica's script and writes one R script that loops over the grid and writes `specs.csv`; rank of the paper's reported estimate is computed deterministically; interpretation is a separate neutral prompt over specs.csv only.

## Resume semantics

Each stage writes its outputs and a `done.json` with the input hashes it used. `run` skips a stage whose done.json matches the current inputs unless `--force`. Replica runs are individually resumable (a replica with results.json is not rerun).

## Environment deviation

No Docker on the pilot machine. Replicas run on local R 4.6.1 and Python 3.14 with the packages present. Every trace records sessionInfo()/pip freeze so version-sensitive defaults stay visible. Recorded as a pilot deviation from the scope's pinned image.

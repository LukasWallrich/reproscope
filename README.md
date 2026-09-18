# reproscope

Reproscope checks whether a social-science paper's reported numbers can be reconstructed
from its methods and deposited data, identifies clear statistical and interpretation errors,
and tests defensible analytical alternatives. The pipeline produces a report with source
quotations, numerical comparisons, discrepancy diagnoses and specification curves.

**Status: experimental.** Current results demonstrate development integration on a small
number of papers. They do not establish general accuracy or replace statistical review.
Contributions are welcome; please discuss substantial changes and review AI-generated code.

## Current validation

| Run | Extraction recall / precision | Independent reconstruction checks | Verified multiverse |
|---|---|---|---|
| [Hurst, inexpensive profile](https://reproscope-hurst-2017-cheap-v2.surge.sh/) | 97.67% / 95.09% | Both replicas: 65 analyses and 123 inferential quantities each; 40 descriptive readouts | 40/40 specifications, 5 analytical dimensions |
| [Petersen v7](https://reproscope-petersen-2017-v7.surge.sh/) | 99.26% / 100% | Both replicas: 28 analyses; 44 descriptive readouts | 12/12 specifications, 5 analytical dimensions |
| [Hurst v1](https://reproscope-hurst-2017-v1.surge.sh/) | 100% / 98.47% | Both replicas: 65 analyses; 40 descriptive readouts | 36/36 specifications, 5 analytical dimensions |

These are versioned development runs, not repeated measurements under identical model
configurations. Extraction is scored against frozen, model-assisted source inventories,
not human annotation or held-out papers. Accepted numerical results are independently
checked on the deposited data and private altered inputs. This verifies implementation of
the declared methods; it does not imply agreement with every published number or validate
all statistical assumptions. Hurst v1 also retains a documented structural blinding limitation.

The fresh inexpensive Hurst run accounts for all 265 retained quantities: 163 computed,
102 unavailable and none awaiting a computation disposition. Missing inputs remain visible.
All 122 required discrepancy/availability groups have source-anchored diagnoses; a diagnosis
can identify a hypothesis or an unresolved cause. Ohtsubo remains an availability case and
is not counted as a successful executable validation.

The current offline suite has **692 passing tests**, 14 skips and one slow test deselected.
Desktop/mobile and public-page checks cover the reports and their evidence panels. See the
[fresh Hurst validation record](docs/validation/2026-09-17/CHEAP_HURST_VALIDATION.md),
[clarity reviews and dispositions](docs/validation/2026-09-17/REVIEW_DISPOSITION.md),
and [current handoff](docs/HANDOFF.md) for scope, receipts and earlier cases.

## What the stages do

| Stage | Work and acceptance boundary |
|---|---|
| **0 — Extract and specify** | Independent paper readings, source reconciliation, estimand contracts, deposited-variable bindings and redacted reconstruction packets. Every retained empirical number receives a computation duty or an explicit disposition. |
| **1 — Reconstruct and diagnose** | Separate replica programs work from blinded inputs. The controller checks requested terms, every requested numerical quantity, sample membership and private-input behaviour. Original code is rerun when supplied. Every divergence receives a source-located diagnosis. |
| **2 — Review correctness** | Two focused questions: clear statistical-analysis errors and clear interpretation errors. Proposed findings require evidence. Causal-language review is not a separate default task. |
| **3 — Generate and verify a multiverse** | Propose and screen analytical choices, complete operational methods before execution, generate code, and verify every specification through independently source-translated numerical recipes. Unsupported verification blocks acceptance. |
| **Report** | Reader-facing findings, searchable source quantities, discrepancy evidence, statistical checks, specification curves and component-level verification. |

The computation inventory includes inferential and descriptive quantities. Missing columns,
response-code keys or other required inputs are reasons for explicit unavailability, not
silent exclusion or successful reproduction. Paired-test signs are compared using the
source-supported contrast or magnitude convention, with raw results retained.

Multiverses distinguish comparable effect estimates from related scales/estimators and
inference-only choices. Raw trimming/outlier variants can share a substantive effect curve
with exact estimator labels. Different scales and null hypotheses remain separately labelled.
Leave-one-out influence checks, seeds and resampling counts do not count as analytical
choices or inflate the dimension count. See the
[multiverse literature review](research/multiverse_scope_literature_review_2026-09-14.md).

## Install and prepare inputs

The validated environment uses Python 3.14, `uv`, Poppler (`pdftoppm` and `pdftotext`),
authenticated Claude/Codex CLIs, and R for the applicable statistical adapters.
Verification isolation currently uses macOS `sandbox-exec` with a denied-read canary;
other hosts retain an explicit unenforced/unverified status rather than the same isolation claim.
The verifier restricts files and network access, not IPC or the process namespace.

```sh
uv sync --group dev
uv run python -m reproscope --help
```

For optional R/specr figure exports, install the plotting dependencies in the R library
available to `Rscript`:

```sh
Rscript -e 'install.packages(c("specr", "ggplot2", "jsonlite", "cowplot", "svglite"), repos="https://cloud.r-project.org")'
```

A source paper lives in `corpus/<source_id>/` with a `manifest.json` naming its PDF,
deposited data, optional codebook and original code. Existing corpus manifests show the
schema. Obtain those inputs separately; PDFs, deposited records, codebooks and run archives
are not distributed with the repository. Create a new run ID from the original inputs:

```sh
uv run python -m reproscope prepare <source_id> <new_run_id>
```

Intake preserves original files, converts supported tabular containers and checks every
converted cell and missing value. It does not rescore, recode or clean analytical values.
Existing corpus or run IDs are rejected by `prepare`.

## Configure and run

Model routes, tiers, replicas and executor are configured in TOML. `REPROSCOPE_MODELS`
selects the file; without it, the pipeline reads `models.toml`. OpenRouter requires
`OPENROUTER_API_KEY`; subscription routes use the authenticated local CLIs.

| Profile | Intended use |
|---|---|
| [`models.cheap-validated.toml`](models.cheap-validated.toml) | The successful inexpensive Hurst configuration: Haiku and metered Luna replicas, with selected Sonnet source tasks and opt-in bounded repairs. |
| [`models.cheap.toml`](models.cheap.toml) | Original un-escalated experiment: two Haiku replica sessions, with Luna extraction/reviews. This does not supply cross-family replica agreement and is not the successful Hurst configuration. |
| [`models.subscription.toml`](models.subscription.toml) | Stronger subscription configuration, including general Sonnet/Opus replicas. |

Use a run-specific copy to preserve the chosen configuration. The following configures the
validated inexpensive route; it permits targeted Sonnet repairs but no general Opus replica:

```sh
export PAPER_ID=your_new_run_id
mkdir -p "runs/$PAPER_ID"
cp models.cheap-validated.toml "runs/$PAPER_ID/models.toml"
export REPROSCOPE_MODELS="runs/$PAPER_ID/models.toml"
export REPROSCOPE_REVIEW_BACKEND=strong_alt
export CLAUDE_CODE_MAX_OUTPUT_TOKENS=64000
export MAX_STRUCTURED_OUTPUT_RETRIES=5
export MAX_THINKING_TOKENS=8192
export REPROSCOPE_REPLICA_REPAIR_TIER=contract_repair
export REPROSCOPE_METHOD_REPAIR_TIER=contract_repair
export REPROSCOPE_EXECUTOR_REPAIR_TIER=contract_repair
export REPROSCOPE_SPECR_EXPORT=1
uv run python -m reproscope run "$PAPER_ID" --stages 0
```

The output allowance accommodates dense extraction pages. Exhausted structured-output
retries and output-limit errors terminate the unchanged request rather than triggering
unbounded retries. `contract_strategy = "chunked"` separates source assignments from
fixed-group method descriptions, preserving claim ownership during repair.

### Metered budget

Before starting metered replica generation, create a shared budget file. This example uses
a US$3 cap and incorporates already-recorded OpenRouter charges from intake. Choose a cap
authorised for your own run; the development run's allowance is not a standing authorisation.
The exclusive file creation deliberately refuses to reset an existing budget.

```sh
export REPROSCOPE_METERED_BUDGET_FILE="runs/$PAPER_ID/metered_budget.json"
uv run python - <<'PY'
import json, os
from pathlib import Path
from reproscope import ledger
baseline = sum(r.get("cost_usd") or 0 for r in ledger.rows(os.environ["PAPER_ID"])
               if r.get("route") == "openrouter")
budget = {"cap_usd": 3, "baseline_usd": baseline,
          "model": "openai/gpt-5.6-luna", "max_output_tokens": 24000, "calls": []}
with Path(os.environ["REPROSCOPE_METERED_BUDGET_FILE"]).open("x") as f:
    json.dump(budget, f, indent=2)
PY
uv run python -m reproscope run "$PAPER_ID" --stages 1 2 3 report
uv run python -m reproscope ledger "$PAPER_ID"
```

The budget file bounds calls through the metered **source-generation** route, reserving
conservative maximum charges before requests and settling them when usage is known.
Interrupted/unknown charges remain reserved. It is not a universal cap on other OpenRouter
calls: monitor extraction and any separately configured API routes, including subsequent
intake reruns, and account for them in the shared allowance. Subscription consumption is
reported separately from metered charges.

The successful inexpensive Hurst run recorded US$0.709687 confirmed and US$0.6645216
conservatively reserved, totalling US$1.3742086 against its US$3 cap. OpenRouter later
rejected requests with HTTP 402; bounded executor repair continued through the subscription
route. This development run includes repeated repairs and is not a normal per-paper
runtime or subscription-consumption benchmark.

### Repair and review controls

| Setting | Scope |
|---|---|
| `tiers.source_repair`, `tiers.contracts`, `tiers.contract_repair` | Separate unresolved-source repair, contract construction and invalid-contract repair models. |
| `REPROSCOPE_REVIEW_BACKEND=strong_alt` | Independent reviews use the configured alternate tier; Luna in the validated cheap profile. |
| `REPROSCOPE_REPLICA_REPAIR_TIER` | At most two source patches to an existing tool-free replica through a configured `claude_p` tier. |
| `REPROSCOPE_METHOD_REPAIR_TIER` | Source-only multiverse completion and method-recipe repair. Analytical additions are disclosed and separately reviewed before execution. |
| `REPROSCOPE_EXECUTOR_REPAIR_TIER` | Selects a subscription tier for up to three patches to an existing multiverse program per repair-policy fingerprint. Without this override, an enabled metered budget selects budgeted repairs. Payment rejection ends that metered repair loop. |
| `REPROSCOPE_RECIPE_ADJUDICATION_MODEL` | Optional focused subscription adjudication after repeated source-review disagreement. The Hurst run used `fable`; the setting is omitted above unless deliberately enabled. |

Repairs receive approved inputs, existing source and verifier failures, not reported targets
or independent reference values. Exact edits, before/after source, calls and isolated
executions are archived. Source-only adjudication receives no executor code or numerical
results. Neither reviewers nor adjudication can waive controller binding, participant
identity or numerical-verification failures. The general replica lineup remains separately
configured, and the report names repair-model provenance.

## Validate and resume

A successful `run` command means the stages finished; it is not sufficient evidence of
analytical acceptance. Build and review an independent-context source inventory, freeze it,
then score the extraction and run the complete acceptance check using the same model and
review configuration:

```sh
uv run python -m reproscope.source_benchmark inventory "$PAPER_ID"
uv run python -m reproscope.source_benchmark review "$PAPER_ID"
uv run python -m reproscope.source_benchmark score "$PAPER_ID"
uv run python -m reproscope.end_to_end_validation "$PAPER_ID"
uv run pytest -q
```

The benchmark inventory is source-only and separate from production extraction; scoring
must not edit its answers. These commands can make model calls. The acceptance command
is read-only and requires current receipts, greater than 95% benchmark recall **and**
precision, complete quantity accounting and diagnosis, verified replicas, and a fully
verified ordinary multiverse with more than four executed analytical dimensions.
Unsupported numerical methods, unbound duties and stale evidence remain blockers.

Rerun the ordinary command to resume. The controller reuses artifacts only when their
inputs and output fingerprints match; changes to verification code trigger the appropriate
checks. Run one writer per paper at a time. `--force-step <step>` selectively regenerates a
named step; `--force` is broader and can incur substantial model usage. The legacy
`scripts/fullchain.sh` / `scripts/chain_retry.py` helpers retain local paths and retry
assumptions; the module commands above are the portable entry points.

Outputs live in `runs/<paper_id>/`: stage artifacts, generated programs, model-call ledger,
`pipeline_status.json`, `end_to_end_validation.json` and `report/report.html`. Failed attempts
remain available for diagnosis. The default test command excludes the marked slow test;
`uv run pytest -m slow` explicitly selects it. Platform or integration prerequisites can
also produce skips.

## Read and share reports

Interactive figures show sorted estimates and declared intervals above an aligned choice
matrix. A source-reported estimate is marked only on the same scale and comparison, with
its rounding range and below/tied/above position. Selecting a specification exposes its
combined method and independent numerical evidence. `REPROSCOPE_SPECR_EXPORT=1` adds
standard R/specr SVG downloads from the verified aggregate results, without refitting models.
Declared tests determine significance colours; an interval need not encode the same criterion.

Local reports can link to run artifacts. For public sharing, render through
`reproscope.report.build(paper_id, public=True)` after acceptance and review the standalone
HTML before publishing. Public verification payloads contain aggregate sample counts,
not participant identifiers or records. Do not upload the corpus or run directory.
The current Surge report links are in the validation table above.

## Design and development records

- [Stage contracts and acceptance specification](docs/E2E_ANALYSIS_REPORTING_SPEC_2026-09-14.md)
- [Pipeline mechanics](docs/PILOT_DESIGN.md) and [current status](docs/HANDOFF.md)
- [Numerical verification and reporting](docs/validation/2026-09-15/VERIFICATION_REPORTING.md)
- [Fresh inexpensive Hurst validation](docs/validation/2026-09-17/CHEAP_HURST_VALIDATION.md)
- [Fable and independent clarity feedback, with dispositions](docs/validation/2026-09-17/REVIEW_DISPOSITION.md)
- [Research reviews](research/README.md), including their review-status caveats
- [Original design document](https://lukaswallrich.github.io/reproscope/SCOPE.html), retained as design history; current operational behaviour is documented here and in the stage specification

Generated benchmark inventories, raw model transcripts and run snapshots remain local.
The repository retains implementation, regression fixtures, review prose and selected
aggregate validation receipts. Dated development records describe their recorded version;
the current acceptance requirements above supersede earlier partial-verification criteria.

## Licence

MIT.

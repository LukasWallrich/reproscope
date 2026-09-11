# reproscope

An open-source tool that puts a social-science paper through escalating scrutiny: does it
compute, is the analysis sound, does the result hold up across defensible alternatives. It needs
only the paper and its data. Where the original analysis code is provided, the code is re-run and
its results are compared with those reconstructed from the paper alone, but the question whether
the paper by itself allows the results to be reproduced is always answered.

**Status: experiment.** This project is exploratory and open from the start. It may or may not
yield a broadly useful tool, depending on initial results and my capacity. Contributions are
welcome, but please check first whether they match the direction, and make sure AI-generated code
is reviewed.

## What is here

- [`SCOPE.html`](https://lukaswallrich.github.io/reproscope/SCOPE.html): the design document
  (pipeline stages, model tiers, corpora, decision register, versions, risks, references).
- `reproscope/`: the pipeline. Stage 0 extracts the paper's claims, writes estimand contracts,
  checks the deposited data against them and redacts the methods; Stage 1 runs blinded replica
  agents on the redacted material and grades their results against the paper; Stage 2 reviews
  the focal analysis; Stage 3 runs a specification multiverse around the focal estimate; `report`
  renders one HTML report per paper. `docs/PILOT_DESIGN.md` describes the mechanics.
- `docs/`: `PILOT_DESIGN.md` (mechanics), `PILOT_NOTES.md` (dated findings), `HANDOFF.md` (where
  the pilot stands), `EFFICIENCY_AUDIT.html` and `evaluation/` (the pilot evaluation and writeup).
- [`research/`](research/): AI-generated research reports and design reviews that ground the
  scope; see its README for the caveat that they are unreviewed.

## Running it

A paper lives under `corpus/<paper_id>/` with a `manifest.json`, the PDF and the deposited data
(the PDF and data are not committed). Model routes and tiers are set in `models.toml`; API keys
come from the environment (`OPENROUTER_API_KEY`); the Claude and Codex routes use the local CLIs.

```
.venv/bin/python -m reproscope run <paper_id> --stages 0 1 2 3 report
.venv/bin/python -m reproscope ledger <paper_id>
.venv/bin/python -m pytest tests -q
```

`scripts/fullchain.sh <paper_id>` runs Stage 0 (three attempts) and then `scripts/chain_retry.py`,
which reruns Stages 1–3 and the report retrying the steps that failed on an API error; both log
under `runs/logs/`.

## Licence

MIT.

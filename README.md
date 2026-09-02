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
  Open the raw file locally if the rendered link does not work yet.
- [`research/`](research/): AI-generated research reports and design reviews that ground the
  scope; see its README for the caveat that they are unreviewed.

No code yet. The first milestone is Stage 0 (extraction, estimand contracts, data readiness,
redaction) worked through by hand on one paper, then the batch driver.

## Licence

MIT.

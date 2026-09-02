# Task: run the specification grid

Directory contents: `BASE_ANALYSIS.R` (or .py; a working script that reproduces the focal analysis), `GRID.json` (factors, their defensible levels with implementation instructions, and incompatible combinations), `CONTRACT.json` (the focal analysis), `data/`.

Write `out/multiverse.R` (or .py) that: builds the full factorial grid of defensible levels, drops incompatible combinations, and for each specification runs the focal analysis and records the focal estimate (the quantity in `CONTRACT.json` `focal_claim`), its standard error, p-value, n, and a `converged` flag. Write `out/specs.csv` with one row per specification: one column per factor plus `estimate, se, p, n, converged, error`. Errors in one specification must not stop the loop; record them. Run it, keep `out/run.log`, and write `out/notes.md` with what you had to decide to implement any level. Never hard-code estimates. Use `set.seed(20260901)`.

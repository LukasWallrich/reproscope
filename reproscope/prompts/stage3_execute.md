# Task: run the specification grid

Directory contents: `BASE_ANALYSIS.R` (or .py; a working script that reproduces the focal analysis), `GRID.json`, `CONTRACT.json` (the focal analysis), `data/`.

`GRID.json` holds:

- `factors`: each factor's name and its levels, every level with a `value` and a `how` instruction saying how to implement it.
- `specs`: the complete list of specifications to run, already pruned of incompatible combinations. Each entry is `{"spec_id": "spec_001", "levels": {"<factor name>": "<level value>", ...}}`.

Write `out/multiverse.R` (or .py) that iterates over `specs` exactly as given and, for each one, runs the focal analysis with every factor set to the level named in `levels`, implemented per that level's `how` instruction. Record the focal estimate (the quantity in `CONTRACT.json` `focal_claim`), its standard error, p-value, n, and a `converged` flag.

Read the spec list from `GRID.json` at run time. Do not build your own factorial, do not add, drop, reorder or merge specifications, and do not invent, rename or renumber spec ids.

Write `out/specs.csv` with one row per specification and the columns `spec_id, estimate, se, p, n, converged, error`, in that order. `spec_id` must be copied verbatim from `GRID.json`. When a level sets a significance threshold other than .05 — its `how` names a multiplicity correction, or `GRID.json` gives the level a `p_threshold` — add a `p_threshold` column after `error` holding the alpha that specification was judged against. Factor columns may be added after that for readability; they are not read. Every spec id gets exactly one row, including a specification that fails or is not implementable: set `converged` to `FALSE`, leave the numeric fields empty, and put the reason in `error`. Errors in one specification must not stop the loop.

Implement each level through the documented interface of the packages you use; do not read or deparse package source. A level you cannot implement as its `how` says after two attempts marks its specifications `converged = FALSE` with the reason in `error`, and the loop moves on: a complete `specs.csv` with some failed rows is the deliverable, a perfect script that never runs is not.

Run it, keep `out/run.log`, and write `out/notes.md` with what you had to decide to implement any level. Never hard-code estimates. Use `set.seed(20260901)`.

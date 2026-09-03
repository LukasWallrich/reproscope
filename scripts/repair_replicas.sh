#!/bin/zsh
# Redo run checks for replicas marked failed, then rerun everything downstream of them.
#
# Deleting a trace.json while its results.json stays on disk makes replicas.run_one
# redo only the checks (results_present, hardcoding audit, ...) without relaunching the
# agent: `results_path.exists() and not force` takes the "redo checks only" branch. See
# reproscope/stage1/replicas.py run_one.
#
# Everything downstream of a trace is removed so it is rebuilt from the corrected trace
# rather than reusing stale artifacts: stage 1's match/targeted/rerun/diagnosis and its
# done marker, all of stage 2, and the parts of stage 3 that read the traces or the
# match table (done marker, space, paper-level derivation, rank, interpretation) and the
# report. Stage 3's focal binding, factor proposal, screen and grid do not read the
# traces or match table and are kept, along with the executor's work/ directory.
cd /Users/lukaswallrich/Documents/Coding/reproduction_pipeline

for P in Ohtsubo_EvoHumanBehavior_2014_zlm2 Hurst_EvoHumanBehavior_2017_yypJ Petersen_Cognition_2017_yJwG Axt_JournExpSocPsych_2018_zK2 Hertel_ClinPsychSci_2018_YabW; do
  .venv/bin/python - "$P" <<'PY'
import glob
import json
import os
import shutil
import sys

P = sys.argv[1]
run_dir = f"runs/{P}"
if not os.path.isdir(run_dir):
    print(f"{P}: no run directory, skipping")
    sys.exit(0)

for t in sorted(glob.glob(f"{run_dir}/stage1/replicas/*/trace.json")):
    d = json.load(open(t))
    if not d.get("ran"):
        os.remove(t)
        print("recheck (agent not relaunched):", t)

FILES = [
    # stage 1: everything downstream of a replica trace or match table
    "stage1/match.json",
    "stage1/targeted.json",
    "stage1/diagnosis.md",
    "stage1/diagnosis.meta.json",
    "stage1/rerun.json",
    "stage1/done.json",
    # stage 3: kept are focal.json, factors_proposed.json, screen.json, grid.json,
    # execute.json and work/ — none of them read the traces or the match table
    "stage3/done.json",
    "stage3/space.json",
    "stage3/paper_level.json",
    "stage3/rank.json",
    "stage3/interpretation.md",
    "stage3/interpretation.json",
]
DIRS = [
    "stage1/targeted",
    "stage2",
    "report",
]

for f in FILES:
    p = f"{run_dir}/{f}"
    if os.path.exists(p):
        os.remove(p)
        print("removed:", p)

for d in DIRS:
    p = f"{run_dir}/{d}"
    if os.path.isdir(p):
        shutil.rmtree(p)
        print("removed:", p, "(directory)")
PY
done

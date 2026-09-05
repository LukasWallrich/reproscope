"""Re-run the authors' own code, when there is code that this machine can run.

Most pilot papers ship SPSS syntax (.sps) or no code at all. There is no SPSS on
the pilot machine, so those papers abstain with the reason recorded.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

from .. import artifacts, paths, replica_env
from . import blind, replicas

RUNNABLE = {".r", ".py"}
TIMEOUT_S = 900


def rerun_dir(paper_id: str) -> Path:
    return paths.run_dir(paper_id, 1) / "rerun"


def runnable_scripts(paper_id: str) -> list[Path]:
    man = paths.manifest(paper_id)
    return [man.path(rel) for rel in man.original_code if Path(rel).suffix.lower() in RUNNABLE]


def run(paper_id: str, force: bool = False) -> dict:
    out_path = paths.run_dir(paper_id, 1) / "rerun.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text())

    man = paths.manifest(paper_id)
    scripts = runnable_scripts(paper_id)
    if not man.original_code:
        payload = {
            "state": "abstained",
            "abstain_reason": "the manifest lists no original code for this paper",
        }
    elif not scripts:
        kinds = sorted({Path(p).suffix.lower() or "(no extension)" for p in man.original_code})
        payload = {
            "state": "abstained",
            "abstain_reason": (
                f"the original code is {', '.join(kinds)}, which this machine cannot run "
                "(no SPSS, Stata or SAS installed); only .R and .py are re-run"
            ),
            "original_code": list(man.original_code),
        }
    else:
        # The authors' Python code runs on the same stack as the replicas.
        replica_env.ensure_base_env()
        work = rerun_dir(paper_id) / "work"
        (work / "out").mkdir(parents=True, exist_ok=True)
        blind.copy_data(paper_id, work / "data")
        runs = []
        for src in scripts:
            shutil.copy2(src, work / src.name)
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    replicas.script_command(work / src.name, work),
                    cwd=str(work), capture_output=True, text=True, timeout=TIMEOUT_S,
                )
                exit_code, log = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
            except subprocess.TimeoutExpired:
                exit_code, log = 124, f"[timed out after {TIMEOUT_S}s]"
            except FileNotFoundError as e:
                exit_code, log = 127, f"[interpreter not found] {e}"
            (rerun_dir(paper_id) / f"{src.stem}.log").write_text(log)
            runs.append(
                {"script": src.name, "exit_code": exit_code,
                 "wall_s": round(time.monotonic() - started, 2)}
            )
        payload = {
            "state": "complete",
            "runs": runs,
            "all_clean": all(r["exit_code"] == 0 for r in runs),
            "note": "The authors' scripts were copied next to a copy of the data and run in "
                    "order; their own outputs are in rerun/work/.",
        }

    payload["meta"] = artifacts.ArtifactMeta(artifact="OriginalCodeRerun", stage="1").model_dump()
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return payload

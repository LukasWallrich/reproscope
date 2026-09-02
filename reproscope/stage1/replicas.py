"""Launch the blind replicas, then check what each of them actually did.

One replica = one agentic model call in its own blind directory. After the agent
exits, three things happen that the agent has no say in: the script is re-executed
from the top, its script is audited for hard-coded results, and its own list of
fixes is rated for severity. The result is a ReplicaDecisionTrace per replica.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import artifacts, config, llm, paths
from . import audit, blind

AGENT_TIMEOUT_S = 2400
RERUN_TIMEOUT_S = 900
MAX_WORKERS = 4


# --- selection ------------------------------------------------------------


def _env_list(name: str) -> list[str] | None:
    raw = os.environ.get(name, "").strip()
    return [x.strip() for x in raw.split(",") if x.strip()] or None


def selected(
    families: list[str] | None = None, only: list[str] | None = None
) -> dict[str, config.ReplicaSpec]:
    """Families to run, honouring REPROSCOPE_FAMILIES and the REPROSCOPE_RUNS cap.

    `families` selects families; `only` selects individual replica ids and implies
    their families. An explicit argument wins over the environment variable.
    """
    all_specs = config.replicas()
    wanted = families or _env_list("REPROSCOPE_FAMILIES")
    if only:
        wanted = sorted({rid.rsplit("_", 1)[0] for rid in only})
    if wanted:
        unknown = [f for f in wanted if f not in all_specs]
        if unknown:
            raise KeyError(f"unknown replica families {unknown}; have {sorted(all_specs)}")
        all_specs = {f: all_specs[f] for f in wanted}
    cap = os.environ.get("REPROSCOPE_RUNS")
    if cap:
        n = int(cap)
        all_specs = {
            f: s.model_copy(update={"runs": min(s.runs, n)}) for f, s in all_specs.items()
        }
    return all_specs


def replica_ids(
    families: list[str] | None = None, only: list[str] | None = None
) -> list[tuple[str, str, config.ReplicaSpec]]:
    out = []
    for family, spec in selected(families, only).items():
        for i in range(1, spec.runs + 1):
            rid = f"{family}_{i}"
            if only and rid not in only:
                continue
            out.append((family, rid, spec))
    return out


# --- deterministic run checks --------------------------------------------


def find_script(out_dir: Path) -> Path | None:
    for name in ("analysis.R", "analysis.r", "analysis.py"):
        if (out_dir / name).exists():
            return out_dir / name
    for pattern in ("*.R", "*.r", "*.py"):
        found = sorted(out_dir.glob(pattern))
        if found:
            return found[0]
    return None


def script_command(script: Path, cwd: Path) -> list[str]:
    """Command to re-run `script` from `cwd`, as the agent would have run it."""
    try:
        rel = str(script.resolve().relative_to(Path(cwd).resolve()))
    except ValueError:
        rel = str(script)
    if script.suffix.lower() == ".r":
        return ["Rscript", rel]
    venv = paths.ROOT / ".venv" / "bin" / "python"
    return [str(venv if venv.exists() else sys.executable), rel]


def _read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _result_values(payload: Any) -> dict[str, Any]:
    rows = payload.get("results", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}
    return {
        str(r.get("claim_id")): r.get("value")
        for r in rows
        if isinstance(r, dict) and r.get("claim_id")
    }


def _same_values(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if set(a) != set(b):
        return False
    for k, va in a.items():
        vb = b[k]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            if not math.isclose(float(va), float(vb), rel_tol=1e-6, abs_tol=1e-12):
                return False
        elif va != vb:
            return False
    return True


_CMD_LINE = re.compile(r"^\s*(?:\$|>|\+)?\s*(Rscript|python3?|R CMD|library\(|source\()")


def count_loops(logs: list[str]) -> int:
    """Repeats beyond the first of the most-repeated non-trivial line; 0 means no loop."""
    counts: Counter[str] = Counter()
    for text in logs:
        for line in text.splitlines():
            line = line.strip()
            if len(line) < 12 or line.startswith("#"):
                continue
            if _CMD_LINE.match(line) or "Error" in line or "error:" in line:
                counts[line] += 1
    return max((c - 1 for c in counts.values()), default=0)


def rerun_script(work: Path, script: Path, rdir: Path) -> dict[str, Any]:
    """Re-execute the agent's script from the top and see whether it rebuilds results.

    The agent's own results.json is kept as results.agent.json and the file is
    removed before the run, so its presence afterwards proves the script wrote it.
    """
    out_dir = work / "out"
    results = out_dir / "results.json"
    agent_copy = rdir / "results.agent.json"
    agent_payload = None
    if results.exists():
        shutil.copy2(results, agent_copy)
        agent_payload = _read_json(agent_copy)
        results.unlink()

    started = time.monotonic()
    try:
        proc = subprocess.run(
            script_command(script, work),
            cwd=str(work),
            capture_output=True,
            text=True,
            timeout=RERUN_TIMEOUT_S,
        )
        exit_code, log = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        exit_code = 124
        log = f"[re-execution timed out after {RERUN_TIMEOUT_S}s]\n{e.stdout or ''}{e.stderr or ''}"
    except FileNotFoundError as e:
        exit_code, log = 127, f"[interpreter not found] {e}"
    wall = time.monotonic() - started
    (rdir / "check.log").write_text(log)

    regenerated = results.exists()
    new_payload = _read_json(results) if regenerated else None
    if not regenerated and agent_copy.exists():
        shutil.copy2(agent_copy, results)  # keep the agent's file for the match step

    agent_vals = _result_values(agent_payload) if agent_payload is not None else {}
    new_vals = _result_values(new_payload) if new_payload is not None else {}
    values = new_vals or agent_vals
    return {
        "exit_code": exit_code,
        "wall_s": round(wall, 2),
        "script": script.name,
        "regenerated_results": regenerated,
        "results_match_agent": _same_values(agent_vals, new_vals) if regenerated else None,
        "results_from_script": regenerated,
        "n_values": sum(1 for v in values.values() if v is not None),
    }


# --- trace normalisation --------------------------------------------------


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        return [f"{k}: {json.dumps(v) if not isinstance(v, str) else v}" for k, v in value.items()]
    if isinstance(value, list):
        return [v if isinstance(v, str) else json.dumps(v) for v in value]
    return [str(value)]


def _as_text(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_as_str_list(value))
    return json.dumps(value)


def _as_fixes(value: Any) -> list[artifacts.ReplicaFix]:
    fixes = []
    for item in value if isinstance(value, list) else _as_str_list(value):
        if isinstance(item, dict):
            desc = item.get("description") or item.get("fix") or item.get("what") or json.dumps(item)
            extra = {k: v for k, v in item.items() if k not in {"description", "severity"}}
            fixes.append(artifacts.ReplicaFix(description=str(desc), **extra))
        else:
            fixes.append(artifacts.ReplicaFix(description=str(item)))
    return fixes


def _as_seed(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        m = re.search(r"-?\d+", value)
        return int(m.group()) if m else None
    return None


def normalise_trace(raw: Any) -> dict[str, Any]:
    """Coerce the agent's own trace.json into ReplicaDecisionTrace fields."""
    if not isinstance(raw, dict):
        return {"agent_trace_unreadable": True}
    return {
        "filters": _as_str_list(raw.get("filters")),
        "transformations": _as_str_list(raw.get("transformations")),
        "model_formula": _as_text(raw.get("model_formula")),
        "missingness": _as_text(raw.get("missingness")),
        "weights": _as_text(raw.get("weights")),
        "estimator_settings": raw.get("estimator_settings")
        if isinstance(raw.get("estimator_settings"), dict)
        else {"described": _as_text(raw.get("estimator_settings"))},
        "seed": _as_seed(raw.get("seed")),
        "software": _as_text(raw.get("software")),
        "open_choices": _as_str_list(raw.get("open_choices")),
        "fixes": _as_fixes(raw.get("fixes")),
        "variable_bindings": raw.get("variable_bindings"),
        "abstentions": raw.get("abstentions"),
    }


# --- one replica ----------------------------------------------------------


def _steps_done(result: llm.LLMResult | None, log_text: str) -> int | None:
    if result is None:
        return None
    raw = result.raw
    if isinstance(raw, dict) and raw.get("num_turns") is not None:
        return int(raw["num_turns"])
    steps = log_text.count('"type":"step_finish"') + log_text.count('"type": "step_finish"')
    return steps or None


def run_one(
    paper_id: str, family: str, replica_id: str, spec: config.ReplicaSpec, force: bool = False
) -> artifacts.ReplicaDecisionTrace:
    rdir = blind.replica_dir(paper_id, replica_id)
    work = rdir / "work"
    results_path = work / "out" / "results.json"
    trace_path = rdir / "trace.json"

    if results_path.exists() and trace_path.exists() and not force:
        loaded = artifacts.load(artifacts.ReplicaDecisionTrace, trace_path)
        return loaded if isinstance(loaded, artifacts.ReplicaDecisionTrace) else loaded[0]

    result: llm.LLMResult | None = None
    if results_path.exists() and not force:
        # Interrupted between the agent finishing and the trace being written:
        # keep the agent's work and redo the checks only.
        pass
    else:
        work = blind.assemble(paper_id, replica_id)
        # The agent runs in a copy outside the repository, so relative paths reach neither
        # the paper nor the extracted claims; its outputs are copied back afterwards.
        iso = blind.isolate(work, paper_id, replica_id)
        result = llm.call(
            "replica",
            (work / "TASK.md").read_text(),
            paper_id=paper_id,
            stage="1",
            route=spec.route,
            model=spec.model,
            cwd=iso,
            agentic=True,
            timeout_s=AGENT_TIMEOUT_S,
            log_path=rdir / "agent.log",
            extra={"replica_id": replica_id, "family": family},
        )
        blind.collect(iso, work)

    out_dir = work / "out"
    agent_log = (rdir / "agent.log").read_text() if (rdir / "agent.log").exists() else ""
    run_log = (out_dir / "run.log").read_text() if (out_dir / "run.log").exists() else ""
    script = find_script(out_dir)

    checks: dict[str, Any] = {
        "results_present": results_path.exists(),
        "results_parseable": _read_json(results_path) is not None,
        "agent_trace_present": (out_dir / "trace.json").exists(),
        "script_present": script is not None,
        "run_log_present": bool(run_log),
        "loops": count_loops([agent_log, run_log]),
        "blind_transcript_hits": blind.transcript_hits(agent_log),
        "steps_done": _steps_done(result, agent_log),
    }
    if script is not None:
        checks.update(rerun_script(work, script, rdir))
    else:
        checks.update({"exit_code": None, "wall_s": None, "regenerated_results": False,
                       "results_match_agent": None, "n_values": 0})
    checks["outputs_present"] = bool(
        checks["results_present"] and checks["script_present"] and checks["agent_trace_present"]
    )

    trace_fields = normalise_trace(_read_json(out_dir / "trace.json"))
    fixes = trace_fields.pop("fixes", [])
    checks["n_fixes"] = len(fixes)

    call_ids = [result.ledger_id] if result and result.ledger_id else []
    contracts_text = (work / "CONTRACT.json").read_text() if (work / "CONTRACT.json").exists() else ""
    fixes, fix_call = audit.fix_severity(paper_id, fixes, contracts_text)
    if fix_call:
        call_ids.append(fix_call)
    hard, hard_call = audit.hardcoding_audit(
        paper_id,
        script.read_text() if script else "",
        results_path.read_text() if results_path.exists() else "",
    )
    if hard_call:
        call_ids.append(hard_call)

    ran = bool(
        checks.get("exit_code") == 0
        and checks.get("regenerated_results")
        and checks.get("n_values", 0) >= 1
    )
    usage = (
        {
            "route": result.route,
            "model": result.model,
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "tokens_reasoning": result.tokens_reasoning,
            "cost_usd": result.cost_usd,
            "duration_s": round(result.duration_s, 2),
            "ok": result.ok,
            "error": result.error,
        }
        if result
        else None
    )

    trace = artifacts.ReplicaDecisionTrace(
        replica_id=replica_id,
        family=family,
        model=spec.model,
        route=spec.route,
        fixes=fixes,
        ran=ran,
        run_checks=artifacts.RunChecks(**checks),
        hardcoding_audit=hard,
        state="complete" if ran else "abstained",
        abstain_reason=None if ran else "script did not re-execute cleanly with results",
        usage=usage,
        meta=artifacts.ArtifactMeta(
            artifact="ReplicaDecisionTrace",
            stage="1",
            model_calls=call_ids,
            prompt_versions={"replica_task": artifacts.prompt_version("stage1_replica_task")},
        ),
        **trace_fields,
    )
    artifacts.save(trace, trace_path)
    return trace


def run(
    paper_id: str,
    force: bool = False,
    families: list[str] | None = None,
    only: list[str] | None = None,
) -> list[artifacts.ReplicaDecisionTrace]:
    jobs = replica_ids(families, only)
    if not jobs:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as pool:
        futures = [
            pool.submit(run_one, paper_id, family, rid, spec, force) for family, rid, spec in jobs
        ]
        return [f.result() for f in futures]


def load_traces(paper_id: str) -> list[artifacts.ReplicaDecisionTrace]:
    root = paths.run_dir(paper_id, 1) / "replicas"
    traces = []
    for trace_path in sorted(root.glob("*/trace.json")):
        loaded = artifacts.load(artifacts.ReplicaDecisionTrace, trace_path)
        traces.append(loaded if isinstance(loaded, artifacts.ReplicaDecisionTrace) else loaded[0])
    return traces

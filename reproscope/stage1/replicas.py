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
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .. import artifacts, config, llm, paths, replica_env
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


def script_command(script: Path, cwd: Path, python: str | None = None) -> list[str]:
    """Command to re-run `script` from `cwd`, as the agent would have run it."""
    try:
        rel = str(script.resolve().relative_to(Path(cwd).resolve()))
    except ValueError:
        rel = str(script)
    if script.suffix.lower() == ".r":
        return ["Rscript", rel]
    return [python or replica_env.base_python(), rel]


# --- declared environments ------------------------------------------------

INSTALL_TIMEOUT_S = 600
CRAN = "https://cloud.r-project.org"


def r_package_names(text: str) -> list[str]:
    """CRAN names from r_packages.txt. `install.packages` takes no version, so a
    declared `name==version` pin is recorded but installed by name."""
    names = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line.split("==")[0].strip())
    return names


def prepare_env(out_dir: Path, rdir: Path) -> dict[str, Any]:
    """Build the environment the agent declared and say how to run the script in it.

    `out/requirements.txt` gets a fresh venv at `<rdir>/env`, built from the shared
    replica interpreter and holding the base stack plus the declared packages;
    `out/r_packages.txt` gets a per-replica R library at `<rdir>/rlib`. Both live under the replica's run directory, outside the work copy the
    agent worked in — the agent has exited by the time this runs, so nothing here can
    reach it.

    Returns `interpreter`, `env` (extra variables for the run), `installed`, `env_dir`,
    `error` (the packages that could not be installed) and the install `log`.
    """
    info: dict[str, Any] = {
        "interpreter": None, "env": {}, "installed": [], "env_dir": None,
        "error": None, "log": "",
    }

    def step(cmd: list[str], what: str) -> subprocess.CompletedProcess | None:
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=INSTALL_TIMEOUT_S,
                env={**os.environ, **info["env"]},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            info["log"] += f"[{what}] {' '.join(cmd)}\n{e}\n"
            return None
        info["log"] += f"[{what}] {' '.join(cmd)}\n{proc.stdout or ''}{proc.stderr or ''}\n"
        return proc if proc.returncode == 0 else None

    rdir.mkdir(parents=True, exist_ok=True)
    req = out_dir / "requirements.txt"
    if req.exists():
        declared = [
            ln.split("#", 1)[0].strip()
            for ln in req.read_text().splitlines()
            if ln.split("#", 1)[0].strip()
        ]
        env_dir = rdir / "env"
        shutil.rmtree(env_dir, ignore_errors=True)
        python = str(env_dir / "bin" / "python")
        # The declared file lists only the extras, so the base stack goes in first: an
        # env with scipy but no pandas would fail the check for the wrong reason.
        # The pins come from the shared environment's stamp, not from a live freeze,
        # so a package an agent installed into the shared env cannot reach another
        # replica's check.
        base = rdir / "base_requirements.txt"
        pins = replica_env.stamped_pins()
        if not pins:
            info["error"] = "base stack pins unavailable (shared environment has no stamp)"
        else:
            base.write_text("\n".join(pins) + "\n")
            ok = step(
                ["uv", "venv", str(env_dir), "--python", replica_env.base_python()], "venv"
            )
            # Two installs rather than one resolution over both files: a declared pin
            # that differs from the base pin replaces it instead of conflicting.
            for source, what in ((base, "base stack install"), (req, "declared install")):
                if ok is not None:
                    ok = step(
                        ["uv", "pip", "install", "--python", python, "-r", str(source)], what
                    )
            if ok is None:
                info["error"] = ", ".join(declared) or "declared Python packages"
            else:
                info.update(interpreter=python, env_dir=str(env_dir))
                info["installed"] += declared

    rpkgs = out_dir / "r_packages.txt"
    if rpkgs.exists() and info["error"] is None:
        names = r_package_names(rpkgs.read_text())
        lib = rdir / "rlib"
        lib.mkdir(parents=True, exist_ok=True)
        info["env"]["R_LIBS_USER"] = str(lib)
        vector = ", ".join(f'"{n}"' for n in names)
        code = (
            f'lib <- "{lib}"; pkgs <- c({vector}); '
            "miss <- setdiff(pkgs, rownames(installed.packages())); "
            f'if (length(miss)) install.packages(miss, lib=lib, repos="{CRAN}"); '
            "bad <- setdiff(pkgs, rownames(installed.packages())); "
            'if (length(bad)) { cat("missing:", bad, "\\n"); quit(status=1) }'
        )
        if names and step(["Rscript", "-e", code], "R packages") is None:
            info["error"] = ", ".join(names)
        else:
            info["installed"] += names

    if info["error"]:
        info["error"] = f"environment: {info['error']} could not be installed"
    return info


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


def rerun_script(work: Path, script: Path, rdir: Path, *, term_receipt=None) -> dict[str, Any]:
    """Re-execute the agent's script from the top and see whether it rebuilds results.

    The agent's own results.json is kept as results.agent.json and the file is
    removed before the run, so its presence afterwards proves the script wrote it.
    """
    import tempfile
    from ..execution import copy_inputs, equal, result_fields, external_file_literals

    env_info = prepare_env(work / "out", rdir)
    path_problems = external_file_literals(work)
    if path_problems:
        env_info["error"] = "; ".join(path_problems)
    original = _read_json(work / "out" / "results.json")
    regenerated_plan = None
    isolation = {"enforced": False, "reason": "verification not executed"}
    packet = _read_json(work / "CONTRACT.json") if (work / "CONTRACT.json").exists() else None
    if term_receipt is not None:
        from ..coefficient_identity import attach
        packet=attach(packet or {},term_receipt)
    started = time.monotonic()
    exit_code, regenerated, same, values, log = None, False, False, {}, ""
    output_protocol_error = None
    if not env_info["error"]:
        with tempfile.TemporaryDirectory(prefix="reproscope_replica_check_") as folder:
            fresh = Path(folder)
            copy_inputs(work, fresh)
            target = fresh / "out" / script.name
            for cwd in (fresh, fresh / "out"):
                output = fresh / "out" / "results.json"
                output.unlink(missing_ok=True)
                (fresh / "out/analysis_plan.json").unlink(missing_ok=True)
                try:
                    from ..isolation import command as isolated_command, clean_environment
                    cmd, isolation = isolated_command(script_command(target, cwd, env_info["interpreter"]), fresh, env_info["env"])
                    proc = subprocess.run(cmd,
                        cwd=cwd, capture_output=True, text=True, timeout=RERUN_TIMEOUT_S,
                        env=clean_environment({**os.environ, **env_info["env"]}, fresh))
                    exit_code = proc.returncode
                    log += (proc.stdout or "") + (proc.stderr or "")
                except subprocess.TimeoutExpired:
                    exit_code, log = 124, log + "fresh execution timed out"
                    break
                except (OSError, RuntimeError) as exc:
                    exit_code, log = 127, log + str(exc)
                    break
                if exit_code == 0:
                    break
            regenerated = output.is_file()
            regenerated_plan = _read_json(fresh / "out/analysis_plan.json")
            if regenerated:
                try:
                    values = result_fields(_read_json(output), packet)
                    same = equal(result_fields(original, packet), values)
                except (ValueError, TypeError, AttributeError) as exc:
                    output_protocol_error = str(exc)
                    log += str(exc)
    from ..execution_evidence import check_replica
    execution_evidence = check_replica(work, packet or {}, regenerated_plan=regenerated_plan) if regenerated and same else {"status": "unverified", "analyses": {}}
    from ..execution_evidence import perturbation_checks
    perturbation = perturbation_checks(work, script, packet or {}, env_info, rdir) if any(a.get("status") == "verified" for a in execution_evidence.get("analyses", {}).values()) else {"status": "unverified", "reason": "reference method not verified"}
    if perturbation["status"] != "verified" and execution_evidence.get("status") == "verified":
        execution_evidence["status"] = "partial"
    for aid, item in execution_evidence.get("analyses", {}).items():
        item["perturbation_status"] = (perturbation.get('per_analysis',{}).get(aid,{}).get('status',perturbation['status'])
                                       if aid in perturbation.get("analysis_ids", []) else "unverified")
        if item.get("status") == "verified" and item["perturbation_status"] != "verified":
            item["status"] = "unverified"
            item["reason"] = "independent reference passed; data-dependence perturbation incomplete"
    execution_evidence["perturbation"] = perturbation
    (rdir / "check.log").write_text(env_info["log"] + log)
    return {
        "exit_code": exit_code, "wall_s": round(time.monotonic() - started, 2),
        "script": script.name, "ran_from": "fresh declared-input directory",
        "regenerated_results": regenerated, "results_match_agent": same,
        "results_from_script": regenerated and same,
        "script_execution_status": "executed" if exit_code == 0 else "not_run" if exit_code is None else "failed",
        "output_protocol_status": "invalid" if output_protocol_error else "validated" if regenerated else "missing",
        "output_protocol_error": output_protocol_error,
        "execution_evidence": execution_evidence,
        "isolation": isolation,
        "n_values": sum(r.get("value") is not None for r in values.values()),
        "env_error": env_info["error"], "interpreter": env_info["interpreter"],
        "installed": env_info["installed"], "env_dir": env_info["env_dir"],
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


def generation_validation(work, *, term_receipt=None):
    """Return blind protocol/method errors for a bounded code repair."""
    from ..execution_evidence import check_replica
    packet = json.loads((work / "CONTRACT.json").read_text())
    if term_receipt is not None:
        from ..coefficient_identity import attach
        packet=attach(packet,term_receipt)
    plan = _read_json(work / "out/analysis_plan.json")
    evidence = check_replica(work, packet, regenerated_plan=plan)
    errors = []
    if evidence.get("status") == "invalid" or not evidence.get("analyses"):
        if evidence.get("reason"):errors.append(evidence["reason"])
    for aid, item in evidence.get("analyses", {}).items():
        if item.get("status") != "verified":
            reasons=item.get("problems", []) + ([item['reason']] if item.get('reason') else [])
            if item.get('unverified_quantities'):reasons.append('Unverified requested quantities: '+', '.join(item['unverified_quantities']))
            errors += [f"{aid}: {reason}" for reason in (reasons or ['Requested analysis lacks complete independent method verification'])]
    if not errors and any(a.get('status')=='verified' for a in evidence.get('analyses',{}).values()):
        from ..execution_evidence import perturbation_checks
        script=find_script(work/'out')
        environment=prepare_env(work/'out',work.parent)
        if environment.get('error'):return [environment['error']]
        if script:
            check=perturbation_checks(work,script,packet,environment,work.parent)
            if check.get('status') in {'failed','invalid'}:
                for operation in check.get('checks',[]):
                    if operation['status']=='verified':continue
                    if operation.get('reason'):errors.append(operation['operation']+': '+operation['reason'])
                    for aid,item in operation.get('reference',{}).get('analyses',{}).items():
                        if item.get('status')!='verified':
                            errors.append(f"{operation['operation']} / {aid}: "+'; '.join(item.get('problems',[])+([item['reason']] if item.get('reason') else [])))
                if not errors:errors.append('Data perturbation did not preserve methods and independently correct outputs.')
                errors.append('Regenerate method/sample traces from the actual execution. included_ids must name the rows actually analysed after applying the authorised sample rule to the available data, including private row-removal checks. Do not hardcode the original included-ID list as the realised sample.')
    return errors


def run_one(
    paper_id: str, family: str, replica_id: str, spec: config.ReplicaSpec, force: bool = False, *, term_receipt=None
) -> artifacts.ReplicaDecisionTrace:
    rdir = blind.replica_dir(paper_id, replica_id)
    work = rdir / "work"
    results_path = work / "out" / "results.json"
    trace_path = rdir / "trace.json"
    from .. import provenance
    blind.validate_packet_audit(paper_id)
    dependency_inputs = generation_inputs(paper_id, spec)
    loaded=None
    if trace_path.exists() and not force:
        loaded=artifacts.load(artifacts.ReplicaDecisionTrace,trace_path)
        loaded=loaded if isinstance(loaded,artifacts.ReplicaDecisionTrace) else loaded[0]
        if loaded.meta and loaded.meta.inputs==dependency_inputs and not results_path.exists() and getattr(loaded,'output_fingerprint',None)==replica_outputs(work):
            return loaded
    from .. import coefficient_identity
    if term_receipt is None:
        term_receipt=coefficient_identity.resolve(paper_id,blind.blind_packet(paper_id,paths.run_dir(paper_id,0)/'blind_contract.json'))
    from .. import review_backend
    verification_inputs = {
        "coefficient_identity": provenance.digest(term_receipt),
        "source_repair_tier": provenance.digest(config.tier(os.environ['REPROSCOPE_REPLICA_REPAIR_TIER']).model_dump()) if os.environ.get('REPROSCOPE_REPLICA_REPAIR_TIER') else '',
        "review_backend": review_backend.fingerprint(),
        "code": provenance.implementation("stage1/replicas.py", "stage1/audit.py", "execution.py",
                                           "execution_evidence.py", "extended_reference.py", "adjusted_reference.py", "coefficient_identity.py", "replica_repair.py", "plan_protocol.py", "reference.py", "isolation.py", "replica_env.py"),
        "audit_prompt": artifacts.prompt_version("stage1_hardcoding_audit"),
        "fix_prompt": artifacts.prompt_version("stage1_fix_severity"),
        **provenance.files({"environment": paths.ROOT / "uv.lock"}),
    }
    previous = None
    if trace_path.exists() and not force:
        if not loaded.meta or loaded.meta.inputs != dependency_inputs:
            force = True
        elif (not results_path.exists()
              and getattr(loaded, "output_fingerprint", None) == replica_outputs(work)):
            # A completed attempt with no result is a recorded failure. Repeating it
            # requires an explicit force, not an unrelated verification-code change.
            return loaded
        elif (getattr(loaded, "verification_inputs", None) == verification_inputs
              and getattr(loaded, "output_fingerprint", None) == replica_outputs(work)
              and (loaded.hardcoding_audit or {}).get("verdict") not in {None, "not_run"}):
            return loaded
        if not force:
            previous = loaded
        # A changed checker or edited implementation re-verifies existing work,
        # without paying to generate it again.
    receipt = _read_json(rdir / "generation_receipt.json")
    recovery_receipt = (receipt if receipt and receipt.get("inputs") == dependency_inputs
                        and receipt.get("outputs") == replica_outputs(work) else None)
    if work.exists() and previous is None and recovery_receipt is None:
        force = True
    if force and rdir.exists():
        import uuid
        archive = rdir.parent.parent / "replicas_superseded" / uuid.uuid4().hex / replica_id
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(rdir), archive)
        rdir.mkdir(parents=True, exist_ok=True)

    # The agent and the re-execution check share one interpreter and one package stack.
    replica_env.ensure_base_env()

    result: llm.LLMResult | None = None
    generation_receipt = recovery_receipt if not force else None
    if (results_path.exists() or generation_receipt is not None) and not force:
        # Interrupted between the agent finishing and the trace being written:
        # keep the agent's work and redo the checks only.
        receipt = _read_json(rdir / "generation_receipt.json")
        if receipt and receipt.get("inputs") == dependency_inputs and receipt.get("outputs") == replica_outputs(work):
            generation_receipt = receipt
    else:
        work = blind.assemble(paper_id, replica_id)
        # The agent runs in a copy outside the repository, so relative paths reach neither
        # the paper nor the extracted claims; its outputs are copied back afterwards.
        iso = blind.isolate(work, paper_id, replica_id)
        if spec.generation_mode == "tool_free":
            from ..bounded_generation import generate
            result = generate(iso, paper_id=paper_id, stage="1", spec=spec,
                prompt=(work / "TASK.md").read_text(), log_path=rdir / "agent.log",
                script_stem="analysis", timeout_s=AGENT_TIMEOUT_S,
                validate_outputs=lambda work:generation_validation(work,term_receipt=term_receipt))
        else:
            result = llm.call(
                "replica",
                (work / "TASK.md").read_text(),
                paper_id=paper_id,
                stage="1",
                route=spec.route,
                model=spec.model,
                cwd=iso,
                agentic=True,
                env_extra=replica_env.agent_env(iso),
                timeout_s=AGENT_TIMEOUT_S,
                log_path=rdir / "agent.log",
                extra={"replica_id": replica_id, "family": family},
            )
        blind.collect(iso, work)
        generation_receipt = {"inputs": dependency_inputs, "outputs": replica_outputs(work),
            "model_calls": [result.ledger_id] if result.ledger_id else [],
            "usage": {k:getattr(result,k) for k in ("route", "model", "tokens_in", "tokens_out", "tokens_reasoning",
                                                   "cost_usd", "duration_s", "ok", "error")}}
        (rdir / "generation_receipt.json").write_text(json.dumps(generation_receipt, indent=2) + "\n")

    out_dir = work / "out"
    repair_events=[]
    if spec.generation_mode=='tool_free' and os.environ.get('REPROSCOPE_REPLICA_REPAIR_TIER') and results_path.exists():
        from ..replica_repair import repair
        repair_events=repair(work,paper_id,rdir,term_receipt,generation_validation(work,term_receipt=term_receipt))
        if repair_events:
            generation_receipt=dict(generation_receipt or {})
            generation_receipt.setdefault('before_source_repair',{'outputs':generation_receipt.get('outputs'), 'usage':generation_receipt.get('usage')})
            generation_receipt['outputs']=replica_outputs(work)
            generation_receipt['source_repairs']=repair_events
            generation_receipt['model_calls']=list(dict.fromkeys(generation_receipt.get('model_calls',[])+[e['model_call'] for e in repair_events if e.get('model_call')]))
            (rdir/'generation_receipt.json').write_text(json.dumps(generation_receipt,indent=2)+'\n')
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
        checks.update(rerun_script(work, script, rdir,term_receipt=term_receipt))
    else:
        checks.update({"exit_code": None, "wall_s": None, "regenerated_results": False,
                       "results_match_agent": None, "n_values": 0, "env_error": None})
    checks["outputs_present"] = bool(
        checks["results_present"] and checks["script_present"] and checks["agent_trace_present"]
    )

    trace_fields = normalise_trace(_read_json(out_dir / "trace.json"))
    trace_fields["execution_evidence"] = checks.get("execution_evidence", {"status": "unverified", "analyses": {}})
    fixes = trace_fields.pop("fixes", [])
    checks["n_fixes"] = len(fixes)

    call_ids = ([result.ledger_id] if result and result.ledger_id else
                list(previous.meta.model_calls) if previous and previous.meta else
                list(generation_receipt["model_calls"]) if generation_receipt else [])
    call_ids=list(dict.fromkeys(call_ids+[e['model_call'] for e in repair_events if e.get('model_call')]))
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
        and checks.get("results_match_agent")
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
        else previous.usage if previous else generation_receipt["usage"] if generation_receipt else None
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
        acceptance=audit.acceptance(hard),
        output_fingerprint=replica_outputs(work),
        verification_inputs=verification_inputs,
        state="complete" if ran else "abstained",
        abstain_reason=None
        if ran
        else (checks.get("env_error") or ("output protocol: " + checks["output_protocol_error"] if checks.get("output_protocol_error") else None)
              or "script did not regenerate matching, usable results"),
        usage=usage,
        meta=artifacts.ArtifactMeta(
            artifact="ReplicaDecisionTrace",
            stage="1",
            inputs=dependency_inputs,
            model_calls=call_ids,
            prompt_versions={"replica_task": artifacts.prompt_version("stage1_replica_task")},
        ),
        **trace_fields,
    )
    artifacts.save(trace, trace_path)
    return trace



def generation_inputs(paper_id: str, spec) -> dict[str, str]:
    from .. import provenance
    s0 = paths.run_dir(paper_id, 0)
    return {**provenance.corpus(paper_id),
            "methods": artifacts.sha256_file(s0 / "redacted_methods.md"),
            "packet": provenance.digest(blind.blind_packet(paper_id, s0 / "blind_contract.json")),
            "task": (artifacts.prompt_version("stage1_replica_task") if blind.replica_task(paper_id)==artifacts.load_prompt("stage1_replica_task") else provenance.digest(blind.replica_task(paper_id))),
            "replica_spec": provenance.digest(spec.model_dump(exclude={"runs"})),
            "launch_version": "3",
            "model_client": provenance.implementation("llm.py", "bounded_generation.py", "metered_generation.py", "plan_protocol.py"),
            "environment_code": provenance.implementation("replica_env.py"),
            **provenance.files({"environment": paths.ROOT / "uv.lock"})}

def replica_outputs(work: Path) -> dict[str, str]:
    from .. import provenance
    return provenance.files({str(p.relative_to(work)): p for p in (work / "out").glob("*")
                             if p.is_file() and (p.name in {"results.json", "analysis_plan.json", "trace.json", "requirements.txt", "r_packages.txt"}
                                                 or p.suffix.lower() in {".py", ".r"})})


def run(
    paper_id: str,
    force: bool = False,
    families: list[str] | None = None,
    only: list[str] | None = None,
) -> list[artifacts.ReplicaDecisionTrace]:
    jobs = replica_ids(families, only)
    if not jobs:
        return []
    from ..coefficient_identity import resolve
    term_receipt=resolve(paper_id,blind.blind_packet(paper_id,paths.run_dir(paper_id,0)/'blind_contract.json'))
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(jobs))) as pool:
        futures = [
            pool.submit(run_one, paper_id, family, rid, spec, force, term_receipt=term_receipt) for family, rid, spec in jobs
        ]
        return [f.result() for f in futures]


def load_traces(paper_id: str) -> list[artifacts.ReplicaDecisionTrace]:
    root = paths.run_dir(paper_id, 1) / "replicas"
    traces = []
    for trace_path in sorted(root.glob("*/trace.json")):
        loaded = artifacts.load(artifacts.ReplicaDecisionTrace, trace_path)
        traces.append(loaded if isinstance(loaded, artifacts.ReplicaDecisionTrace) else loaded[0])
    return traces

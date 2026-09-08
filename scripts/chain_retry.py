"""Run stages 1-3 + report per paper, retrying strong-tier steps that failed on an API error.

Usage: .venv/bin/python scripts/chain_retry.py <paper_id> [<paper_id> ...]
Each attempt forces only the steps whose artifact records an LLM failure; up to
MAX_ATTEMPTS per paper with a pause between them so an overloaded model can recover.
"""
import json, subprocess, sys, time
from pathlib import Path

MAX_ATTEMPTS, PAUSE_S = 8, 600
LIMIT_PAUSE_S = 1800  # a subscription session limit resets on the hour scale, not minutes
ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv/bin/python"


def _read(p):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def failed_steps(paper):
    run = ROOT / "runs" / paper
    steps = []
    t = _read(run / "stage1/targeted.json") or {}
    if "LLMError" in str(t.get("abstain_reason") or "") or "LLMError" in str(t.get("notes") or ""):
        steps += ["targeted", "diagnose"]
    rv = _read(run / "stage2/review.json") or {}
    broad = (rv.get("broad") or {})
    if "LLMError" in json.dumps(broad) or "LLMError" in str(rv.get("abstain_reason") or ""):
        steps.append("broad")
    for name in ("causal_language", "mde", "alignment"):
        rec = _read(run / f"stage2/{name}.json") or {}
        if any(w in str(rec.get("abstain_reason") or "") for w in ("Error", "Timeout")):
            steps.append(name)
    for name in ("broad",):
        rec = _read(run / f"stage2/{name}.json") or {}
        if "LLMError" in str(rec.get("abstain_reason") or ""):
            steps.append(name)
    ex = _read(run / "stage3/execute.json") or {}
    if (ex.get("executor") or {}).get("ok") is False or ex.get("problems"):
        steps.append("execute")
    return sorted(set(steps))


def run_once(paper, force):
    cmd = [str(PY), "-m", "reproscope", "run", paper, "--stages", "1", "2", "3", "report"]
    if force:
        cmd += ["--force-step", *force]
    print(f"--- {time.strftime('%H:%M:%S')} {paper}: {' '.join(cmd[3:])}", flush=True)
    log = ROOT / "runs/logs" / f"rerun_{paper}.log"
    with log.open("a") as f:
        proc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=ROOT)
    return proc.returncode


papers = sys.argv[1:]
pending = list(papers)
for attempt in range(1, MAX_ATTEMPTS + 1):
    for paper in list(pending):
        rc = run_once(paper, failed_steps(paper))
        remaining = failed_steps(paper)
        done = rc == 0 and not remaining and (ROOT / "runs" / paper / "report").exists()
        print(f"{paper}: pass {attempt} rc={rc} failed_steps={remaining} done={done}", flush=True)
        if done:
            pending.remove(paper)
    if not pending:
        break
    limited = any(
        "session limit" in (ROOT / "runs/logs" / f"rerun_{p}.log").read_text()[-20000:]
        for p in pending
    )
    pause = LIMIT_PAUSE_S if limited else PAUSE_S
    print(f"pass {attempt} leaves {pending}; pausing {pause}s{' (session limit)' if limited else ''}", flush=True)
    time.sleep(pause)
else:
    print(f"GAVE UP on {pending} after {MAX_ATTEMPTS} passes", flush=True)
print("ALL DONE", flush=True)

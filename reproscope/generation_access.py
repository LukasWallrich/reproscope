"""Observed direct file reads in OpenCode transcripts; not an isolation proof."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path


def review(log: Path, work: Path) -> dict:
    root = Path(work).resolve()
    violations, checked = [], 0
    if not Path(log).exists():
        return {"status": "unobserved", "scope": "generation transcript unavailable", "violations": []}
    try:
        receipt=json.loads(Path(log).read_text())
    except (ValueError,TypeError):
        receipt={}
    if receipt.get('version') in {'bounded-generation-1','bounded-generation-2','bounded-generation-3'} and receipt.get('tool_surface') == 'none':
        return {'status':'enforced', 'scope':'tool-free generation from recorded supplied payload; script executions use a separate OS boundary',
                'transcript_sha256':hashlib.sha256(Path(log).read_bytes()).hexdigest(), 'violations':[],
                'input_hashes':receipt.get('inputs',{}),'executions':receipt.get('executions',[])}
    for line in Path(log).read_text(errors="replace").splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        part = event.get("part") or {}
        if not isinstance(part, dict):
            continue
        state = part.get("state") or {}
        if not isinstance(state, dict):
            continue
        if part.get("tool") != "read" or state.get("status") != "completed":
            continue
        supplied = state.get("input") or {}
        name = supplied.get("filePath") if isinstance(supplied, dict) else None
        if not isinstance(name, str):
            continue
        checked += 1
        path = Path(name).expanduser()
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_relative_to(root):
            violations.append({"path": str(path), "tool": "read", "call_id": part.get("callID")})
    return {"status": "violated" if violations else "no_direct_read_violation_observed",
            "transcript_sha256": hashlib.sha256(Path(log).read_bytes()).hexdigest(),
            "scope": "completed OpenCode read-tool events only; shell access and other routes are not certified",
            "direct_reads_checked": checked, "violations": violations}

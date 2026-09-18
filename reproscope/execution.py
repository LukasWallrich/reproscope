"""Fresh execution inputs and comparisons of statistical outputs."""
from __future__ import annotations

import math
import shutil
from pathlib import Path


def copy_inputs(work: Path, fresh: Path) -> None:
    (fresh / "out").mkdir(parents=True, exist_ok=True)
    for source in work.iterdir():
        if source.name == "data" and source.is_dir():
            shutil.copytree(source, fresh / "data")
        elif source.is_file() and (source.suffix.lower() in {".py", ".r"}
                                   or source.name in {"GRID.json", "CONTRACT.json", "METHODS.md", "TASK.md"}):
            shutil.copy2(source, fresh / source.name)
    for source in (work / "out").iterdir():
        if source.is_file() and source.suffix.lower() in {".py", ".r"}:
            shutil.copy2(source, fresh / "out" / source.name)


def equal(a, b) -> bool:
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-12)
    return a == b


def result_fields(payload, packet: dict | None = None) -> dict:
    """One row per analysis/claim request, preserving shared-claim provenance."""
    rows = payload.get("results", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise ValueError("results must be a list")
    allowed = None
    if packet is not None:
        allowed = {(a["analysis_id"], q["claim_id"]) for a in packet.get("analyses", [])
                   for q in a.get("quantities", [])}
        allowed |= {(None, q["claim_id"]) for q in packet.get("unassigned", [])}
    keys = ("claim_id", "analysis_id", "value", "se", "ci", "ci_lower", "ci_upper", "n", "p", "p_raw", "p_adjustment", "p_threshold",
            "member_ids", "members", "aggregation", "statistic", "estimate", "effect_metric", "se_metric", "df", "converged", "uncertainty")
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("result rows must be objects")
        cid = row.get("claim_id")
        aid = row.get("analysis_id")
        if not isinstance(cid, str) or not cid or (aid is not None and not isinstance(aid, str)):
            raise ValueError("result rows require string claim/analysis IDs")
        key = (aid, cid)
        if key in result:
            raise ValueError("results require unique analysis/claim pairs")
        if allowed is not None and key not in allowed:
            raise ValueError(f"result analysis/claim pair {key!r} was not requested by the packet")
        result[key] = {k: row.get(k) for k in keys}
    return result


def external_file_literals(work: Path) -> list[str]:
    """Reject obvious nonportable input/result paths; this is not an OS sandbox.

    Relative out/../data paths are valid. Absolute paths and relative escapes to
    data or result files can bypass a fresh-directory check and are refused.
    """
    import ast
    import re
    problems = []
    scripts = [p for base in (work, work / 'out') for p in base.iterdir()
               if p.is_file() and p.suffix.lower() in {'.py', '.r'}]
    for script in scripts:
        text = script.read_text(errors='replace')
        if script.suffix.lower() == '.py':
            try:
                literals = [n.value for n in ast.walk(ast.parse(text))
                            if isinstance(n, ast.Constant) and isinstance(n.value, str)]
            except SyntaxError:
                continue  # the interpreter reports syntax failure
        else:
            literals = [m.group(2) for m in re.finditer(r'''(["'])([^"'\n]+)\1''', text)]
        for value in literals:
            if '\n' in value or len(value) > 1000:
                continue
            path = Path(value)
            if path.suffix.lower() not in {'.csv', '.json', '.sav', '.xlsx', '.xls', '.rds', '.rdata', '.tsv'}:
                continue
            if path.is_absolute() or (value.startswith('../') and not any(
                (base / path).resolve().is_relative_to(work.resolve()) for base in (work, work / 'out'))):
                problems.append(f'{script.name}: input/result path must be relative to supplied work: {value}')
    return problems

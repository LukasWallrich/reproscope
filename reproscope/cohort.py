"""Explicit, shared membership for pipeline evaluation and cost reporting."""
from __future__ import annotations

import json
from pathlib import Path

from . import paths, provenance


def load(path: Path | None = None) -> dict:
    path = path or paths.ROOT / "docs/evaluation/cohort.json"
    doc = json.loads(path.read_text())
    entries = doc.get("papers", [])
    for key in ("paper_id", "run_id"):
        values = [p[key] for p in entries]
        if len(set(values)) != len(values):
            raise ValueError(f"evaluation cohort contains duplicate {key}")
    if not entries:
        raise ValueError("evaluation cohort is empty")
    for entry in entries:
        replicas = entry.get("replicas", [])
        if not replicas or len(replicas) != len(set(replicas)):
            raise ValueError("each paper needs a unique planned replica lineup")
        if entry.get("split") not in {"development", "held_out"}:
            raise ValueError("each paper must declare development or held_out")
    doc["fingerprint"] = provenance.digest(doc)
    return doc


def validate_runs(doc: dict, root: Path | None = None) -> None:
    root = root or paths.ROOT / "runs"
    for entry in doc["papers"]:
        run = root / entry["run_id"]
        if not run.is_relative_to(root) or Path(entry["run_id"]).name != entry["run_id"]:
            raise ValueError("cohort run_id must be a directory name")
        if not run.is_dir():
            raise ValueError(f"cohort run does not exist: {entry['run_id']}")

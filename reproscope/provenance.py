"""Dependency fingerprints used at stage and step boundaries."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import artifacts, paths


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def files(items: dict[str, Path]) -> dict[str, str]:
    return {name: artifacts.sha256_file(p) if p.is_file() else "missing"
            for name, p in items.items()}


def corpus(paper_id: str) -> dict[str, str]:
    man = paths.manifest(paper_id)
    names = list(man.data_files) + ([man.codebook] if man.codebook else [])
    return files({f"data:{name}": man.path(name) for name in names})


def implementation(*modules: str) -> str:
    """Conservative package-version fingerprint, including local uncommitted edits."""
    package = Path(__file__).parent
    source = ({name: package / name for name in modules} if modules
              else {str(p.relative_to(package)): p for p in package.rglob("*") if p.is_file() and p.suffix.lower() in {".py", ".r"}})
    if not modules:
        source.update({name: paths.ROOT / name for name in ("models.toml", "uv.lock", "pyproject.toml")})
    return digest(files(source))


def outputs(stage: Path) -> dict[str, str]:
    """Analytical outputs only; logs and installed libraries are not cache dependencies."""
    patterns = ("*.json", "*.md", "replicas/*/work/out/requirements.txt", "replicas/*/work/out/r_packages.txt",
                "work/out/requirements.txt", "work/out/r_packages.txt", "replicas/*/trace.json", "replicas/*/work/out/results.json",
                "replicas/*/work/out/*.py", "replicas/*/work/out/*.R", "replicas/*/work/out/*.r", "replicas/*/work/out/analysis_plan.json", "work/out/specs.csv",
                "work/out/*.py", "work/out/*.R", "work/out/*.r", "work/out/analysis_plan.json", "descriptive/report.json", "work/out/*.svg", "*.html")
    found = {str(p.relative_to(stage)): p for pattern in patterns for p in stage.glob(pattern)
             if p.name != "done.json" and p.is_file()}
    return files(found)

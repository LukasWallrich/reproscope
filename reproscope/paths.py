"""Corpus and run path helpers, plus the manifest model and stage done-markers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parent.parent


def corpus_dir(paper_id: str) -> Path:
    return ROOT / "corpus" / paper_id


def run_dir(paper_id: str, stage: str | int | None = None) -> Path:
    d = ROOT / "runs" / paper_id
    if stage is not None:
        d = d / (f"stage{stage}" if isinstance(stage, int) or str(stage).isdigit() else str(stage))
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- manifest -------------------------------------------------------------


class ReportedValue(BaseModel):
    model_config = ConfigDict(extra="allow")

    statistic: str | None = None
    value: float | str | None = None
    df: float | str | None = None
    n: int | None = None
    page: int | str | None = None


class FocalClaim(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    source: str | None = None
    reported: ReportedValue | None = None


class Multi100(BaseModel):
    model_config = ConfigDict(extra="allow")

    paper_id: str | None = None
    n_analysts: int | None = None
    analyst_d: dict[str, float] | None = None


class Environment(BaseModel):
    model_config = ConfigDict(extra="allow")

    language_hint: str | None = None
    versions_named: dict[str, str] = {}


class Manifest(BaseModel):
    model_config = ConfigDict(extra="allow")

    paper_id: str
    title: str | None = None
    doi: str | None = None
    pdf: str = "paper.pdf"
    licence: str | None = None
    data_files: list[str] = []
    codebook: str | None = None
    original_code: list[str] = []
    focal_claim: FocalClaim | None = None
    multi100: Multi100 | None = None
    environment: Environment = Environment()
    design_numbers: list[float] = []  # reported values that are also design constants; exempt from the leak scan

    @property
    def dir(self) -> Path:
        return corpus_dir(self.paper_id)

    def path(self, rel: str) -> Path:
        return corpus_dir(self.paper_id) / rel


def manifest(paper_id: str) -> Manifest:
    p = corpus_dir(paper_id) / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"no manifest at {p}")
    return Manifest.model_validate_json(p.read_text())


# --- done markers ---------------------------------------------------------


def done_path(stage_dir: Path) -> Path:
    return Path(stage_dir) / "done.json"


def is_done(stage_dir: Path, inputs: dict[str, str]) -> bool:
    p = done_path(stage_dir)
    if not p.exists():
        return False
    try:
        prev: dict[str, Any] = json.loads(p.read_text())
    except json.JSONDecodeError:
        return False
    return prev.get("inputs") == inputs


def mark_done(stage_dir: Path, inputs: dict[str, str]) -> Path:
    from datetime import datetime, timezone

    p = done_path(stage_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"inputs": inputs, "created": datetime.now(timezone.utc).isoformat()},
            indent=2,
            sort_keys=True,
        )
    )
    return p


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()

"""Pydantic models for the artifact chain, plus save/load, hashing and prompt loading.

Every artifact carries `meta` (provenance) and the shared abstention fields.
Fields stay Optional wherever extraction may legitimately come up empty, and every
model allows extra keys so a stage can attach detail without a schema change here.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from . import paths

ARTIFACT_VERSION = "0.1"

State = Literal["complete", "abstained"]
Confidence = Literal["high", "medium", "low"]
Severity = Literal["minor", "major", "critical"]
Band = Literal["A", "B", "C", "fail"]
QuantityKind = Literal[
    "coefficient", "p_value", "t", "F", "chi2", "d", "r", "OR", "HR",
    "mean", "sd", "n", "ci_bound", "other",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    artifact: str
    version: str = ARTIFACT_VERSION
    created: str = Field(default_factory=_now)
    stage: str | None = None
    inputs: dict[str, str] = {}
    prompt_versions: dict[str, str] = {}
    model_calls: list[str] = []


class Artifact(BaseModel):
    """Base for every artifact: provenance plus the shared abstention fields."""

    model_config = ConfigDict(extra="allow")

    meta: ArtifactMeta | None = None
    state: State = "complete"
    abstain_reason: str | None = None
    confidence: Confidence | None = None
    open_ambiguities: list[str] = []


# --- stage 0 --------------------------------------------------------------


class ClaimLocation(BaseModel):
    model_config = ConfigDict(extra="allow")

    page: int | None = None
    kind: Literal["table", "figure", "text"] | None = None
    label: str | None = None
    cell: str | None = None


class ClaimExtraction(BaseModel):
    model_config = ConfigDict(extra="allow")

    model_a: str | None = None
    model_b: str | None = None
    agreed: bool | None = None
    arbiter_note: str | None = None


class ClaimRecord(Artifact):
    claim_id: str
    study_id: str | None = None
    claim_type: Literal["scalar", "range", "table_cell", "qualitative", "figure"] | None = None
    importance: Literal["headline", "supporting"] | None = None
    quantity_kind: QuantityKind | None = None
    value: float | str | None = None
    precision: int | None = None  # decimals as reported
    uncertainty: dict[str, Any] | None = None  # se / ci as reported alongside
    location: ClaimLocation | None = None
    description: str | None = None
    extraction: ClaimExtraction | None = None


class ContractAmbiguity(BaseModel):
    model_config = ConfigDict(extra="allow")

    field: str
    options: list[str] = []
    note: str | None = None


class EstimandContract(Artifact):
    analysis_id: str
    claim_ids: list[str] = []
    study_id: str | None = None
    sample_rule: str | None = None
    outcome: str | None = None
    predictors: list[str] = []
    covariates: list[str] = []
    model_type: str | None = None
    estimator: str | None = None
    se_type: str | None = None
    transformations: list[str] = []
    weights: str | None = None
    missingness: str | None = None
    software_named: list[str] = []
    versions_named: dict[str, str] = {}
    ambiguities: list[ContractAmbiguity] = []


class DataFileRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    path: str
    format: str | None = None
    rows: int | None = None
    cols: int | None = None


class VariableBinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_field: str
    candidate_columns: list[str] = []
    chosen: str | None = None
    note: str | None = None


class DataReadinessRecord(Artifact):
    files: list[DataFileRecord] = []
    unit_of_observation: str | None = None
    keys: list[str] = []
    missing_sentinels: list[str] = []
    variable_bindings: list[VariableBinding] = []
    scale_direction_notes: list[str] = []
    weights_columns: list[str] = []
    per_analysis_state: dict[str, State] = {}


class RemovedSpan(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    text: str | None = None
    location: str | None = None


class RedactionReport(Artifact):
    """Sidecar for stage0/redacted_methods.md."""

    removed_spans: list[RemovedSpan] = []
    scan_hits: list[str] = []  # deterministic value scan; must be empty to launch
    scan_clean: bool = False
    leakage_audit_verdict: str | None = None
    leakage_audit_note: str | None = None


# --- stage 1 --------------------------------------------------------------


class ReplicaFix(BaseModel):
    model_config = ConfigDict(extra="allow")

    description: str
    severity: Severity | None = None


class RunChecks(BaseModel):
    model_config = ConfigDict(extra="allow")

    steps_done: int | None = None
    exit_code: int | None = None
    outputs_present: bool | None = None
    loops: int | None = None
    n_fixes: int | None = None
    wall_s: float | None = None


class ReplicaDecisionTrace(Artifact):
    replica_id: str
    family: str | None = None
    model: str | None = None
    route: str | None = None
    filters: list[str] = []
    transformations: list[str] = []
    model_formula: str | None = None
    missingness: str | None = None
    weights: str | None = None
    estimator_settings: dict[str, Any] = {}
    seed: int | None = None
    software: str | None = None  # sessionInfo() / pip freeze
    open_choices: list[str] = []
    fixes: list[ReplicaFix] = []
    ran: bool = False
    run_checks: RunChecks | None = None
    hardcoding_audit: dict[str, Any] = {}


class ReplicaResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    claim_id: str
    analysis_id: str | None = None
    value: float | None = None
    se: float | None = None
    ci: list[float] | None = None
    n: int | None = None
    note: str | None = None


class ReplicaResults(Artifact):
    replica_id: str | None = None
    results: list[ReplicaResult] = []


class ComparableRow(BaseModel):
    """One claim x replica comparison."""

    model_config = ConfigDict(extra="allow")

    claim_id: str
    replica_id: str
    quantity_kind: QuantityKind | None = None
    reported: float | None = None
    replicated: float | None = None
    unit_check: str | None = None
    raw_diff: float | None = None
    std_diff: float | None = None
    sign_match: bool | None = None
    band: Band | None = None
    sigma_rule: Literal["within", "outside", "na"] = "na"


class Dispersion(BaseModel):
    model_config = ConfigDict(extra="allow")

    decision_agreement: float | None = None
    numeric_cv: float | None = None


class MatchSummary(BaseModel):
    """Per-claim roll-up across replicas."""

    model_config = ConfigDict(extra="allow")

    claim_id: str
    n_ran: int = 0
    fraction_matched: float | None = None
    dispersion: Dispersion | None = None


class ComparableResult(Artifact):
    rows: list[ComparableRow] = []
    summaries: list[MatchSummary] = []
    table_cell_fractions: dict[str, float] = {}


class TargetedReconstruction(Artifact):
    triggered: bool = False
    outcome: Literal[
        "reachable", "reachable_indefensibly", "not_reachable", "not_triggered"
    ] = "not_triggered"
    added_choices: list[str] = []
    attempts: int = 0
    notes: str | None = None


# --- stage 2 --------------------------------------------------------------


class CausalLanguageRating(BaseModel):
    model_config = ConfigDict(extra="allow")

    rating: str | None = None  # CLAIMS-style
    quotes: list[str] = []
    note: str | None = None


class MdeCheck(BaseModel):
    model_config = ConfigDict(extra="allow")

    assumptions: list[str] = []
    curve: list[dict[str, float]] = []
    note: str | None = None


class AlignmentCheck(BaseModel):
    model_config = ConfigDict(extra="allow")

    verdict: str | None = None
    open_choices_per_replica: dict[str, list[str]] = {}
    note: str | None = None


class ReviewFinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    severity: str
    quote: str | None = None
    location: str | None = None
    comment: str


class NarrowChecks(BaseModel):
    model_config = ConfigDict(extra="allow")

    causal_language: CausalLanguageRating | None = None
    mde: MdeCheck | None = None
    alignment: AlignmentCheck | None = None


class BroadReview(BaseModel):
    model_config = ConfigDict(extra="allow")

    findings: list[ReviewFinding] = []


class AnalysisReview(Artifact):
    narrow: NarrowChecks | None = None
    broad: BroadReview | None = None


# --- stage 3 --------------------------------------------------------------


class FactorLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    verdict: Literal["defensible", "rejected", "paper"] | None = None
    rationale: str | None = None


class SpecFactor(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    source: Literal["trace", "grid", "default", "code"] | None = None
    levels: list[FactorLevel] = []


class SpecRun(BaseModel):
    model_config = ConfigDict(extra="allow")

    spec: dict[str, str] = {}
    estimate: float | None = None
    se: float | None = None
    p: float | None = None
    converged: bool | None = None


class SpecificationSpace(Artifact):
    claim_id: str | None = None
    factors: list[SpecFactor] = []
    incompatibilities: list[list[str]] = []
    grid_size: int | None = None
    runs: list[SpecRun] = []
    reported_estimate: float | None = None
    rank: int | None = None
    n_specs: int | None = None
    interpretation: str | None = None


# --- save / load / hashing ------------------------------------------------


def save(model_or_list: BaseModel | list[BaseModel], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(model_or_list, list):
        payload = "[\n" + ",\n".join(m.model_dump_json(indent=2) for m in model_or_list) + "\n]\n"
    else:
        payload = model_or_list.model_dump_json(indent=2) + "\n"
    path.write_text(payload)
    return path


def load[T: BaseModel](cls: type[T], path: Path | str) -> T | list[T]:
    import json

    data = json.loads(Path(path).read_text())
    if isinstance(data, list):
        return [cls.model_validate(d) for d in data]
    return cls.model_validate(data)


def sha256_file(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_files(paths_: dict[str, Path | str]) -> dict[str, str]:
    return {name: sha256_file(p) for name, p in paths_.items()}


# --- prompts --------------------------------------------------------------


def prompt_path(name: str) -> Path:
    return paths.ROOT / "reproscope" / "prompts" / f"{name}.md"


def prompt_version(name: str) -> str:
    """First 12 hex of the sha256 of the prompt file — recorded in artifact meta."""
    return hashlib.sha256(prompt_path(name).read_bytes()).hexdigest()[:12]


_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def load_prompt(name: str, **kwargs: Any) -> str:
    """Read reproscope/prompts/<name>.md and substitute {{key}} placeholders.

    Substitution is literal replacement, so JSON braces in the prompt are safe.
    An unfilled placeholder is an error: a prompt sent with a literal {{claim}} in
    it is a silent quality bug otherwise.
    """
    text = prompt_path(name).read_text()
    for key, value in kwargs.items():
        text = text.replace("{{" + key + "}}", str(value))
    left = sorted(set(_PLACEHOLDER.findall(text)))
    if left:
        raise KeyError(f"prompt {name!r} has unfilled placeholders: {left}")
    return text

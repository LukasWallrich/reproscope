"""Stage 2 — analysis review.

Four checks, each a function that writes its own JSON under runs/<paper_id>/stage2/
so a rerun repeats only what changed: `causal_language`, `mde`, `alignment`, `broad`.
`assemble` folds them into review.json (AnalysisReview) and review.md.

Every check is scoped to the focal analysis, bound once in `gather` through
`focal.bind_focal_claim`. No prompt carries the whole paper: the causal-language check
reads the abstract, the focal passages and the contract; the broad referee pass reads
the focal analysis's methods and results passages, the data schema, one canonical
replica script and unified diffs of the others. paper.txt stays in memory only as the
haystack the quote and anchor checks are verified against.
"""

from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from .. import focal as focal_mod
from ..artifacts import (
    AlignmentCheck,
    AnalysisReview,
    ArtifactMeta,
    Artifact,
    BroadReview,
    CausalLanguageRating,
    ClaimRecord,
    EstimandContract,
    MdeCheck,
    NarrowChecks,
    ReviewFinding,
)
from . import mde as mde_mod

STAGE = "2"
CHECKS = ("causal_language", "mde", "alignment", "broad")
PROMPTS = ("stage2_causal_language", "stage2_alignment", "stage2_broad")
DIFF_LINE_CAP = 150  # lines of unified diff carried per non-canonical replica
CHEAP_REASONING_CAP = 512  # hidden-reasoning cap on the two cheap-tier checks


# --- per-check record -----------------------------------------------------


class CheckRecord(Artifact):
    """One check's own artifact: the model's payload plus its provenance."""

    check: str
    response: dict[str, Any] | None = None


def check_path(paper_id: str, check: str) -> Path:
    return paths.run_dir(paper_id, 2) / f"{check}.json"


def load_check(paper_id: str, check: str) -> CheckRecord | None:
    p = check_path(paper_id, check)
    if not p.exists():
        return None
    try:
        return CheckRecord.model_validate_json(p.read_text())
    except Exception:  # a half-written or stale-schema record is simply redone
        return None


def reusable(
    record: CheckRecord | None,
    inputs: dict[str, str],
    prompts: tuple[str, ...] = (),
) -> bool:
    """Whether a record on disk still stands: same inputs, same prompts, complete."""
    return bool(
        record
        and record.state == "complete"
        and record.meta is not None
        and record.meta.inputs == inputs
        and not artifacts.prompt_stale(record, prompts)
    )


def write_check(
    paper_id: str,
    check: str,
    *,
    inputs: dict[str, str],
    prompt_versions: dict[str, str],
    model_calls: list[str],
    response: dict[str, Any] | None,
    abstain_reason: str | None = None,
) -> CheckRecord:
    rec = CheckRecord(
        check=check,
        response=response,
        state="abstained" if abstain_reason else "complete",
        abstain_reason=abstain_reason,
        meta=ArtifactMeta(
            artifact=f"Stage2Check:{check}",
            stage=STAGE,
            inputs=inputs,
            prompt_versions=prompt_versions,
            model_calls=model_calls,
        ),
    )
    artifacts.save(rec, check_path(paper_id, check))
    return rec


# --- model response schemas (mirror the prompt files) ---------------------


class CausalLanguageResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    language_strength: Literal["none", "weak", "moderate", "strong"]
    design_inference_strength: Literal["very_low", "low", "moderate", "high", "very_high"]
    verdict: Literal["overstated", "matched", "understated"]
    focal_claim_quote: str
    abstract_quotes: list[str] = []
    design_basis: list[str] = []
    reasoning: str


class OpenChoiceItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    choice: str
    options: list[str] = []
    replica_choices: dict[str, str] = {}
    matters_for_claim: bool | None = None
    note: str | None = None


class AlignmentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    verdict: Literal["aligned", "partly_aligned", "misaligned"]
    reasoning: str
    claim_quote: str | None = None
    contract_basis: list[str] = []
    open_choices: list[OpenChoiceItem] = []


class BroadFinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    severity: Literal["major", "minor", "note"]
    category: Literal["coding_error", "analytical_choice", "measurement", "reporting"]
    anchor: str
    location: str | None = None
    comment: str
    checkable_by: str | None = None


class BroadResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    findings: list[BroadFinding] = []
    summary: str | None = None


# --- inputs ---------------------------------------------------------------


@dataclass
class Replica:
    replica_id: str
    trace: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] | None = None
    script_path: Path | None = None
    script_text: str = ""


@dataclass
class Stage2Inputs:
    paper_id: str
    manifest: Any
    paper_text: str
    claims: list[ClaimRecord]
    contracts: list[EstimandContract]
    readiness: dict[str, Any] | None
    schema_text: str
    redacted_methods: str
    match: dict[str, Any] | None
    replicas: list[Replica]
    hashes: dict[str, str]
    focal: dict[str, Any] | None
    focal_error: str | None
    focal_claim: ClaimRecord | None
    focal_contract: EstimandContract | None
    focal_rule: str


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


# --- passage extraction ---------------------------------------------------
#
# Enough structure to hand a prompt the focal analysis instead of the paper. Both
# helpers work on the pdftotext layer as plain lines and paragraphs.

_HEADING_MAX_CHARS = 60  # a wrapped body line is longer than any section heading
_METHODS_HEAD = re.compile(
    r"^(\d+\.?\s*)?(method|methods|materials and methods|participants)\b", re.I
)
_METHODS_END = re.compile(r"^(\d+\.?\s*)?(results|discussion)\b", re.I)
_ABSTRACT_HEAD = re.compile(r"^(abstract|summary)\b[:.]?$", re.I)
_ABSTRACT_END = re.compile(
    r"^(\d+\.?\s*)?(introduction|keywords?|highlights|background|method|methods)\b", re.I
)
_PARA_SPLIT = re.compile(r"\n\s*\n")
ABSTRACT_MAX_CHARS = 4000  # papers whose layer carries no heading after the abstract
SCHEMA_SUMMARY_MAX_CHARS = 12_000


def _heading(line: str, pattern: re.Pattern[str]) -> bool:
    s = line.strip()
    return bool(s) and len(s) <= _HEADING_MAX_CHARS and bool(pattern.match(s))


def methods_section(paper_text: str) -> str | None:
    """The methods section of the pdftotext layer, or None when no heading is found."""
    lines = paper_text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _heading(ln, _METHODS_HEAD)), None)
    if start is None:
        return None
    end = next(
        (j for j in range(start + 1, len(lines)) if _heading(lines[j], _METHODS_END)),
        len(lines),
    )
    return "\n".join(lines[start:end]).strip() or None


def abstract_section(paper_text: str) -> str:
    """The abstract, or the paper's opening when it carries no abstract heading.

    Capped: a layer with no heading after the abstract would otherwise hand back most
    of the paper.
    """
    lines = paper_text.splitlines()
    start = next((i for i, ln in enumerate(lines) if _heading(ln, _ABSTRACT_HEAD)), None)
    body = ""
    if start is not None:
        keep: list[str] = []
        for ln in lines[start + 1:]:
            if _heading(ln, _ABSTRACT_END):
                break
            keep.append(ln)
        body = "\n".join(keep).strip()
    return (body or paper_text)[:ABSTRACT_MAX_CHARS]


def _paragraph_hits(paras: list[str], needles: list[str], max_hits: int) -> list[int]:
    hits = []
    for i, p in enumerate(paras):
        hay = normalise(p)
        if any(normalise(n) in hay for n in needles):
            hits.append(i)
        if len(hits) >= max_hits:
            break
    return hits


def focal_passages(
    paper_text: str, claim: ClaimRecord | None, *, window: int = 1, max_hits: int = 3
) -> list[str]:
    """Paragraphs carrying the focal claim, each with its neighbour on either side.

    A paragraph counts as a hit when it contains the claim's reported value as printed
    or the opening of its description. A claim whose value lives only in a table image
    matches neither, so the claim's location label ("Table 1") is tried after them.
    """
    if claim is None:
        return []
    paras = [p for p in _PARA_SPLIT.split(paper_text) if p.strip()]
    needles = [n for n in (
        str(claim.value) if claim.value is not None else None,
        (claim.description or "")[:60],
    ) if n and n.strip()]
    hits = _paragraph_hits(paras, needles, max_hits) if needles else []
    label = getattr(claim.location, "label", None) if claim.location else None
    if not hits and label:
        hits = _paragraph_hits(paras, [label], max_hits)
    if not hits:
        return []
    keep = sorted({j for i in hits for j in range(max(0, i - window), min(len(paras), i + window + 1))})
    out: list[str] = []
    run: list[str] = []
    previous = None
    for i in keep:
        if previous is not None and i != previous + 1:
            out.append("\n\n".join(run))
            run = []
        run.append(paras[i])
        previous = i
    if run:
        out.append("\n\n".join(run))
    return out


def gather(paper_id: str) -> Stage2Inputs:
    corpus = paths.corpus_dir(paper_id)
    s0 = paths.run_dir(paper_id, 0)
    s1 = paths.run_dir(paper_id, 1)

    # The stage marker covers the prompts as well as the files: an edited prompt must
    # clear it, otherwise the stage is skipped before any check can see the change.
    hashes: dict[str, str] = {f"prompt:{n}": artifacts.prompt_version(n) for n in PROMPTS}

    def note(name: str, path: Path) -> None:
        if path.exists():
            hashes[name] = artifacts.sha256_file(path)

    def note_artifact(name: str, path: Path, cls: type) -> None:
        """Hash the analytical payload, not the file: `meta` carries volatile fields."""
        if not path.exists():
            return
        try:
            hashes[name] = artifacts.content_hash(artifacts.load(cls, path))
        except Exception:
            hashes[name] = artifacts.sha256_file(path)

    paper_path = corpus / "paper.txt"
    if not paper_path.exists():
        raise FileNotFoundError(f"stage 2 needs {paper_path} (stage 0 pdftotext layer)")
    note("paper.txt", paper_path)
    note("manifest.json", corpus / "manifest.json")
    paper_text = paper_path.read_text(errors="replace")

    note_artifact("stage0/claims.json", s0 / "claims.json", ClaimRecord)
    note_artifact("stage0/contracts.json", s0 / "contracts.json", EstimandContract)
    note_artifact("stage0/readiness.json", s0 / "readiness.json", artifacts.DataReadinessRecord)
    for name in ("schema.json", "redacted_methods.md"):
        note(f"stage0/{name}", s0 / name)
    note_artifact("stage1/match.json", s1 / "match.json", artifacts.ComparableResult)

    claims_raw = _read_json(s0 / "claims.json") or []
    claims = [ClaimRecord.model_validate(c) for c in claims_raw]
    contracts_raw = _read_json(s0 / "contracts.json") or []
    contracts = [EstimandContract.model_validate(c) for c in contracts_raw]
    readiness = _read_json(s0 / "readiness.json")
    schema_path = s0 / "schema.json"
    schema_text = schema_path.read_text() if schema_path.exists() else ""
    methods_path = s0 / "redacted_methods.md"
    redacted_methods = methods_path.read_text(errors="replace") if methods_path.exists() else ""
    match = _read_json(s1 / "match.json")

    replicas: list[Replica] = []
    rdir = s1 / "replicas"
    if rdir.exists():
        for d in sorted(p for p in rdir.iterdir() if p.is_dir()):
            trace = _read_json(d / "trace.json") or {}
            note_artifact(
                f"stage1/{d.name}/trace.json", d / "trace.json", artifacts.ReplicaDecisionTrace
            )
            results = _read_json(d / "work" / "out" / "results.json")
            note(f"stage1/{d.name}/results.json", d / "work" / "out" / "results.json")
            script = next(
                (p for p in ((d / "work" / "out" / "analysis.R"), (d / "work" / "out" / "analysis.py"))
                 if p.exists()),
                None,
            )
            if script is not None:
                note(f"stage1/{d.name}/script", script)
            replicas.append(
                Replica(
                    replica_id=trace.get("replica_id") or d.name,
                    trace=trace,
                    results=results,
                    script_path=script,
                    script_text=script.read_text(errors="replace") if script else "",
                )
            )

    manifest = paths.manifest(paper_id)
    focal: dict[str, Any] | None = None
    focal_error: str | None = None
    claim: ClaimRecord | None = None
    contract: EstimandContract | None = None
    rule = ""
    try:
        # The one shared binding: the manifest's `focal_claim.claim_id` override wins,
        # then a numeric match against the reported statistic. No model call here —
        # Stage 2 abstains rather than paying for a guess Stage 3 already made.
        focal = focal_mod.bind_focal_claim(
            manifest, claims, contracts, paper_id=paper_id, allow_llm=False
        )
    except ValueError as e:
        focal_error = str(e)
    if focal is not None:
        focal_id = focal["focal_quantity"]["claim_id"]
        claim = next((c for c in claims if c.claim_id == focal_id), None)
        contract = next(
            (ct for ct in contracts if ct.analysis_id == focal["analysis_id"]), None
        )
        rule = "; ".join(focal["notes"]) or (
            "exact numeric match against the manifest's reported statistic"
        )
    else:
        rule = f"unbound: {focal_error}"

    return Stage2Inputs(
        paper_id=paper_id,
        manifest=manifest,
        paper_text=paper_text,
        claims=claims,
        contracts=contracts,
        readiness=readiness,
        schema_text=schema_text,
        redacted_methods=redacted_methods,
        match=match,
        replicas=replicas,
        hashes=hashes,
        focal=focal,
        focal_error=focal_error,
        focal_claim=claim,
        focal_contract=contract,
        focal_rule=rule,
    )


def _subset(hashes: dict[str, str], *prefixes: str, exclude: tuple[str, ...] = ()) -> dict[str, str]:
    return {
        k: v for k, v in hashes.items()
        if any(k.startswith(p) for p in prefixes) and k not in exclude
    }


def _focal_claim_text(inp: Stage2Inputs) -> str:
    fc = getattr(inp.manifest, "focal_claim", None)
    parts = []
    if fc is not None:
        parts.append(fc.text)
        if fc.reported is not None:
            parts.append("As reported: " + json.dumps(fc.reported.model_dump(), default=str))
    if inp.focal_claim is not None:
        parts.append("Matched claim record: " + inp.focal_claim.model_dump_json())
    if inp.focal_rule:
        parts.append(f"Bound by: {inp.focal_rule}")
    return "\n".join(p for p in parts if p) or "(no focal claim in the manifest)"


def _versions(*names: str) -> dict[str, str]:
    return {n: artifacts.prompt_version(n) for n in names}


def _focal_abstain(
    inp: Stage2Inputs, check: str, inputs: dict[str, str], prompts: tuple[str, ...]
) -> CheckRecord | None:
    """Abstain without a model call when the focal claim could not be bound."""
    if inp.focal_error is None:
        return None
    return write_check(
        inp.paper_id, check, inputs=inputs, prompt_versions=_versions(*prompts),
        model_calls=[], response=None,
        abstain_reason=f"focal claim not bound: {inp.focal_error}",
    )


def _focal_material(inp: Stage2Inputs) -> tuple[str, str]:
    """The methods text and the results/discussion passages for the focal analysis."""
    methods = methods_section(inp.paper_text)
    if methods is None:
        methods = inp.redacted_methods or "(no methods section found in paper.txt)"
    passages = focal_passages(inp.paper_text, inp.focal_claim)
    joined = "\n\n---\n\n".join(passages) if passages else \
        "(no paragraph in paper.txt carries the focal claim's value or description)"
    return methods, joined


def _num(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _row_distance(row: dict[str, Any]) -> float:
    reported, replicated = _num(row.get("reported")), _num(row.get("replicated"))
    if reported is not None and replicated is not None:
        return abs(replicated - reported)
    raw = _num(row.get("raw_diff"))
    return abs(raw) if raw is not None else float("inf")


def canonical_replica(inp: Stage2Inputs) -> tuple[Replica | None, str]:
    """The replica whose focal estimate is closest to the reported value.

    Ties break on replica id, so the choice is the same on every run. Only replicas
    with a script are eligible; without match rows for the focal claim the first
    such replica by id is used.
    """
    eligible = sorted((r for r in inp.replicas if r.script_text), key=lambda r: r.replica_id)
    if not eligible:
        return None, "no replica wrote a script"
    focal_ids = set(inp.focal["claim_ids"]) if inp.focal else set()
    focal_id = inp.focal["focal_quantity"]["claim_id"] if inp.focal else None
    rows = (inp.match or {}).get("rows") or []
    scoped = [r for r in rows if r.get("claim_id") == focal_id] \
        or [r for r in rows if r.get("claim_id") in focal_ids]
    distances: dict[str, float] = {}
    for row in scoped:
        rid = row.get("replica_id")
        if rid is None:
            continue
        distances[rid] = min(distances.get(rid, float("inf")), _row_distance(row))
    if not distances:
        return eligible[0], "no match row for the focal claim; first replica with a script by id"
    best = min(eligible, key=lambda r: (distances.get(r.replica_id, float("inf")), r.replica_id))
    d = distances.get(best.replica_id)
    if d is None or d == float("inf"):
        return best, "no usable match distance for the focal claim; first replica by id"
    return best, f"closest to the reported focal value on the match table (|difference| = {d:g})"


def replica_diffs(canonical: Replica, others: list[Replica]) -> list[tuple[str, str]]:
    """Unified diffs of every other replica's script against the canonical one."""
    out = []
    base = canonical.script_text.splitlines()
    base_name = canonical.script_path.name if canonical.script_path else "script"
    for rep in others:
        lines = list(difflib.unified_diff(
            base, rep.script_text.splitlines(),
            fromfile=f"{canonical.replica_id}/{base_name}",
            tofile=f"{rep.replica_id}/{rep.script_path.name if rep.script_path else 'script'}",
            lineterm="",
        ))
        if not lines:
            out.append((rep.replica_id, "(identical to the canonical script)"))
            continue
        if len(lines) > DIFF_LINE_CAP:
            lines = lines[:DIFF_LINE_CAP] + [
                f"... diff truncated at {DIFF_LINE_CAP} lines"
            ]
        out.append((rep.replica_id, "\n".join(lines)))
    return out


def focal_match_summary(inp: Stage2Inputs) -> dict[str, Any]:
    """The match rows and per-claim summaries belonging to the focal analysis."""
    if not inp.match:
        return {}
    ids = set(inp.focal["claim_ids"]) if inp.focal else set()
    analysis_id = inp.focal["analysis_id"] if inp.focal else None
    return {
        "summaries": [s for s in (inp.match.get("summaries") or [])
                      if s.get("claim_id") in ids
                      or (analysis_id and s.get("analysis_id") == analysis_id)],
        "rows": [r for r in (inp.match.get("rows") or []) if r.get("claim_id") in ids],
    }


def focal_results(rep: Replica, inp: Stage2Inputs) -> list[dict[str, Any]]:
    """A replica's result rows for the focal analysis's claims."""
    rows = (rep.results or {}).get("results", []) if isinstance(rep.results, dict) else []
    ids = set(inp.focal["claim_ids"]) if inp.focal else set()
    analysis_id = inp.focal["analysis_id"] if inp.focal else None
    return [r for r in rows
            if r.get("claim_id") in ids
            or (analysis_id and r.get("analysis_id") == analysis_id)]


def _column_line(col: dict[str, Any]) -> str:
    bits = [str(col.get("name")), str(col.get("dtype") or col.get("type") or "?")]
    if col.get("n_missing"):
        bits.append(f"missing={col['n_missing']}")
    if col.get("n_distinct") is not None:
        bits.append(f"distinct={col['n_distinct']}")
    levels = col.get("levels") or list(col.get("value_counts") or {})
    if levels:
        shown = ", ".join(str(x) for x in levels[:8])
        bits.append(f"levels=[{shown}{', ...' if len(levels) > 8 else ''}]")
    elif col.get("min") is not None or col.get("max") is not None:
        bits.append(f"range={col.get('min')}..{col.get('max')}")
    if col.get("mean") is not None:
        bits.append(f"mean={col['mean']}")
    return "  - " + " | ".join(bits)


def schema_summary(schema_text: str, *, cap: int = SCHEMA_SUMMARY_MAX_CHARS) -> str:
    """One line per table and per column: name, type, missingness, range or levels.

    schema.json carries the full profile of every column, examples included, which on a
    wide dataset is larger than everything else in the prompt together. The raw text is
    used when the file has a shape this cannot read.
    """
    if not schema_text.strip():
        return "(none)"
    try:
        data = json.loads(schema_text)
    except json.JSONDecodeError:
        return schema_text[:cap]
    lines: list[str] = []
    columns_seen = 0
    for f in (data.get("files") or []) if isinstance(data, dict) else []:
        # Two shapes in use: columns directly on the file, or one level down per table.
        tables = f.get("tables") or [{"table": None, "rows": f.get("rows"),
                                      "columns": f.get("columns") or []}]
        for t in tables:
            name = f"{f.get('path')}" + (f" [{t['table']}]" if t.get("table") else "")
            cols = t.get("columns") or []
            columns_seen += len(cols)
            lines.append(f"{name}: {t.get('rows')} rows, {len(cols)} columns")
            lines += [_column_line(c) for c in cols]
    if not columns_seen:
        return schema_text[:cap]
    out = "\n".join(lines)
    if len(out) > cap:
        out = out[:cap] + f"\n... schema summary truncated at {cap} characters"
    return out


# --- check 1: causal language --------------------------------------------


def check_causal_language(inp: Stage2Inputs, *, force: bool = False) -> CheckRecord:
    prompts = ("stage2_causal_language",)
    inputs = _subset(
        inp.hashes, "paper.txt", "manifest.json", "stage0/claims", "stage0/contracts"
    )
    abstained = _focal_abstain(inp, "causal_language", inputs, prompts)
    if abstained is not None:
        return abstained
    existing = load_check(inp.paper_id, "causal_language")
    if reusable(existing, inputs, prompts) and not force:
        return existing  # type: ignore[return-value]

    _, passages = _focal_material(inp)
    prompt = artifacts.load_prompt(
        "stage2_causal_language",
        focal_claim=_focal_claim_text(inp),
        abstract=abstract_section(inp.paper_text),
        passages=passages,
        contract=(inp.focal_contract.model_dump_json(indent=2) if inp.focal_contract
                  else "(no contract available)"),
    )
    r = llm.call(
        "causal_language",
        prompt,
        paper_id=inp.paper_id,
        stage=STAGE,
        tier="cheap",
        schema=CausalLanguageResponse,
        reasoning_max_tokens=CHEAP_REASONING_CAP,
        log_path=paths.run_dir(inp.paper_id, 2) / "logs" / "causal_language.log",
    )
    versions = _versions(*prompts)
    calls = [r.ledger_id] if r.ledger_id else []
    if r.parsed is None:
        return write_check(
            inp.paper_id, "causal_language", inputs=inputs, prompt_versions=versions,
            model_calls=calls, response=None,
            abstain_reason=r.error or "model returned no valid rating",
        )
    payload = r.parsed.model_dump()
    # Quotes are checked against the whole paper, not just the passages the model saw:
    # a quote invented from a nearby sentence should still fail.
    payload["quotes_verified"] = _verify_quotes(payload, inp.paper_text)
    payload["focal_claim_rule"] = inp.focal_rule
    return write_check(
        inp.paper_id, "causal_language", inputs=inputs, prompt_versions=versions,
        model_calls=calls, response=payload,
    )


def _verify_quotes(payload: dict[str, Any], paper_text: str) -> dict[str, bool]:
    quotes = [payload.get("focal_claim_quote")] + list(payload.get("abstract_quotes") or [])
    hay = normalise(paper_text)
    return {q: normalise(q) in hay for q in quotes if q}


# --- check 2: MDE ---------------------------------------------------------


def _focal_n(inp: Stage2Inputs) -> tuple[int | None, str]:
    """n for the power calculation, preferring what the replicas actually analysed.

    Every claim of the focal analysis counts: a replica often reports n on the test
    statistic's row only, so restricting to the curve quantity's own claim would
    throw the number away.
    """
    claim_ids = set(inp.focal["claim_ids"]) if inp.focal else set()
    ns: list[int] = []
    for rep in inp.replicas:
        for row in (rep.results or {}).get("results", []) if isinstance(rep.results, dict) else []:
            if row.get("n") is None:
                continue
            if not claim_ids or row.get("claim_id") in claim_ids:
                ns.append(int(row["n"]))
    if ns:
        mode = max(set(ns), key=ns.count)
        source = f"replica results.json (n = {sorted(set(ns))}; modal value used)" if len(set(ns)) > 1 \
            else "replica results.json"
        return mode, source
    files = (inp.readiness or {}).get("files") or []
    rows = [f.get("rows") for f in files if f.get("rows")]
    if rows:
        return int(max(rows)), "readiness record row count (no replica reported n)"
    reported = getattr(getattr(inp.manifest, "focal_claim", None), "reported", None)
    if reported is not None and reported.n:
        return int(reported.n), "manifest focal_claim.reported.n"
    return None, "no source for n"


def check_mde(inp: Stage2Inputs, *, force: bool = False) -> CheckRecord:
    """The MDE for the focal analysis, computed in R, or an abstention with the reason.

    No model is involved: a power calculation the deterministic path cannot cover is a
    design the pipeline does not know how to state assumptions for, and a modelled
    guess would put an unverifiable number in the report.
    """
    # match.json is deliberately excluded: the check does not read it, so a stage 1
    # rematch must not invalidate the computation.
    inputs = _subset(
        inp.hashes, "manifest.json", "stage0/claims", "stage0/contracts", "stage0/readiness",
        "stage1/", exclude=("stage1/match.json",),
    )
    abstained = _focal_abstain(inp, "mde", inputs, ())
    if abstained is not None:
        return abstained
    existing = load_check(inp.paper_id, "mde")
    if reusable(existing, inputs) and not force:
        return existing  # type: ignore[return-value]

    ct = inp.focal_contract
    n, n_source = _focal_n(inp)
    formula = next((r.trace.get("model_formula") for r in inp.replicas if r.trace.get("model_formula")), None)
    design = (
        mde_mod.classify_design(
            ct.model_type if ct else None,
            n_predictors=len(ct.predictors) if ct else 0,
            n_covariates=len(ct.covariates) if ct else 0,
            formula=formula,
        )
        if ct is not None
        else None
    )

    if design is not None and n:
        try:
            script_path = paths.run_dir(inp.paper_id, 2) / "mde_power.R"
            result = mde_mod.compute(
                design, n,
                script_path=script_path,
                extra_assumptions=[f"n taken from: {n_source}"],
            )
            result["r_script"] = str(script_path.relative_to(paths.ROOT))
            result["design_source"] = f"contract model_type = {ct.model_type!r}"
            return write_check(
                inp.paper_id, "mde", inputs=inputs, prompt_versions={},
                model_calls=[], response=result,
            )
        except mde_mod.MdeError as e:
            reason = f"the power computation failed: {e}"
    elif design is None:
        reason = (
            f"model_type {ct.model_type!r} is not one of the designs the power "
            "computation covers" if ct is not None
            else "no estimand contract to read the design from"
        )
    else:
        reason = f"no analysed n available ({n_source})"

    return write_check(
        inp.paper_id, "mde", inputs=inputs, prompt_versions={}, model_calls=[],
        response=None, abstain_reason=reason,
    )


# --- check 3: alignment ---------------------------------------------------


def check_alignment(inp: Stage2Inputs, *, force: bool = False) -> CheckRecord:
    prompts = ("stage2_alignment",)
    # match.json is deliberately excluded: the check does not read it, so a stage 1
    # rematch must not invalidate the call.
    inputs = _subset(
        inp.hashes, "manifest.json", "stage0/claims", "stage0/contracts", "stage0/readiness",
        "stage1/", exclude=("stage1/match.json",),
    )
    abstained = _focal_abstain(inp, "alignment", inputs, prompts)
    if abstained is not None:
        return abstained
    existing = load_check(inp.paper_id, "alignment")
    if reusable(existing, inputs, prompts) and not force:
        return existing  # type: ignore[return-value]

    open_choices = {
        r.replica_id: {
            "open_choices": r.trace.get("open_choices") or [],
            "model_formula": r.trace.get("model_formula"),
            "filters": r.trace.get("filters") or [],
            "transformations": r.trace.get("transformations") or [],
            "missingness": r.trace.get("missingness"),
        }
        for r in inp.replicas
    }
    prompt = artifacts.load_prompt(
        "stage2_alignment",
        claim=_focal_claim_text(inp),
        contract=(inp.focal_contract.model_dump_json(indent=2) if inp.focal_contract
                  else "(no contract available)"),
        readiness=json.dumps(inp.readiness, indent=2) if inp.readiness else "(no readiness record)",
        open_choices=json.dumps(open_choices, indent=2, default=str),
    )
    r = llm.call(
        "alignment",
        prompt,
        paper_id=inp.paper_id,
        stage=STAGE,
        tier="cheap",
        schema=AlignmentResponse,
        reasoning_max_tokens=CHEAP_REASONING_CAP,
        log_path=paths.run_dir(inp.paper_id, 2) / "logs" / "alignment.log",
    )
    versions = _versions(*prompts)
    calls = [r.ledger_id] if r.ledger_id else []
    if r.parsed is None:
        return write_check(
            inp.paper_id, "alignment", inputs=inputs, prompt_versions=versions,
            model_calls=calls, response=None,
            abstain_reason=r.error or "model returned no valid alignment verdict",
        )
    payload = r.parsed.model_dump()
    payload["traced_open_choices"] = {k: v["open_choices"] for k, v in open_choices.items()}
    payload["focal_claim_rule"] = inp.focal_rule
    return write_check(
        inp.paper_id, "alignment", inputs=inputs, prompt_versions=versions,
        model_calls=calls, response=payload,
    )


# --- check 4: broad review + anchor verification -------------------------

_QUOTE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-", "‐": "-", "­": "",
    " ": " ",
}


def normalise(text: str) -> str:
    """Case-folded, whitespace-collapsed, quote- and dash-normalised text."""
    text = unicodedata.normalize("NFKC", text or "")
    for a, b in _QUOTE_MAP.items():
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip().casefold()


def verify_anchors(findings: list[dict[str, Any]], sources: dict[str, str]) -> list[dict[str, Any]]:
    """Mark each finding with whether its anchor occurs verbatim in a source.

    Findings are kept either way; review.md lists the unverified ones separately.
    """
    hay = {name: normalise(text) for name, text in sources.items()}
    out = []
    for f in findings:
        anchor = normalise(f.get("anchor") or "")
        found = [name for name, text in hay.items() if anchor and anchor in text]
        out.append({**f, "anchor_verified": bool(found), "anchor_found_in": found})
    return out


def broad_material(inp: Stage2Inputs) -> tuple[str, dict[str, Any]]:
    """The one strong-tier prompt's payload, scoped to the focal analysis.

    One canonical replica script in full plus unified diffs of the others: ten
    near-identical scripts say nothing the diffs do not, and cost ten times as much.
    """
    methods, passages = _focal_material(inp)
    canonical, why = canonical_replica(inp)
    blocks = [
        f"## Focal claim\n\n{_focal_claim_text(inp)}",
        f"## Focal analysis — estimand contract\n\n"
        + (inp.focal_contract.model_dump_json(indent=2) if inp.focal_contract
           else "(no contract available)"),
        f"## Methods section (from paper.txt)\n\n{methods}",
        f"## Results and discussion passages carrying the focal claim\n\n{passages}",
        f"## Data schema (stage0/schema.json)\n\n{schema_summary(inp.schema_text)}",
    ]
    provenance: dict[str, Any] = {"canonical_replica": None, "canonical_replica_reason": why,
                                  "diffed_replicas": []}
    if canonical is not None:
        name = canonical.script_path.name if canonical.script_path else "script"
        blocks.append(
            f"## Canonical replica script — {canonical.replica_id} / {name}\n"
            f"Chosen because it is {why}.\n\n```\n{canonical.script_text}\n```"
        )
        rows = focal_results(canonical, inp)
        blocks.append(
            f"## Canonical replica results for the focal analysis — {canonical.replica_id}\n\n"
            f"{json.dumps(rows, indent=2, default=str) if rows else '(none)'}"
        )
        others = [r for r in inp.replicas
                  if r.replica_id != canonical.replica_id and r.script_text]
        diffs = replica_diffs(canonical, sorted(others, key=lambda r: r.replica_id))
        provenance["canonical_replica"] = canonical.replica_id
        provenance["diffed_replicas"] = [rid for rid, _ in diffs]
        for rid, diff in diffs:
            blocks.append(
                f"## Replica {rid} — unified diff against {canonical.replica_id}\n\n"
                f"```diff\n{diff}\n```"
            )
    else:
        blocks.append(f"## Replica scripts\n\n({why})")
    blocks.append(
        "## Match summary for the focal analysis\n\n"
        + json.dumps(focal_match_summary(inp), indent=2, default=str)
    )
    return "\n\n".join(blocks), provenance


def check_broad(inp: Stage2Inputs, *, force: bool = False) -> CheckRecord:
    prompts = ("stage2_broad",)
    inputs = _subset(
        inp.hashes, "paper.txt", "manifest.json", "stage0/claims", "stage0/contracts",
        "stage0/schema", "stage0/redacted_methods", "stage1/",
    )
    abstained = _focal_abstain(inp, "broad", inputs, prompts)
    if abstained is not None:
        return abstained
    existing = load_check(inp.paper_id, "broad")
    if reusable(existing, inputs, prompts) and not force:
        return existing  # type: ignore[return-value]

    material, provenance = broad_material(inp)
    prompt = artifacts.load_prompt("stage2_broad", material=material)
    r = llm.call(
        "broad",
        prompt,
        paper_id=inp.paper_id,
        stage=STAGE,
        tier="strong",
        schema=BroadResponse,
        log_path=paths.run_dir(inp.paper_id, 2) / "logs" / "broad.log",
    )
    versions = _versions(*prompts)
    calls = [r.ledger_id] if r.ledger_id else []
    if r.parsed is None:
        return write_check(
            inp.paper_id, "broad", inputs=inputs, prompt_versions=versions,
            model_calls=calls, response=None,
            abstain_reason=r.error or "model returned no valid referee findings",
        )
    payload = r.parsed.model_dump()
    # Anchors are checked against everything on disk, not only what the prompt carried.
    sources = {"paper.txt": inp.paper_text, "schema.json": inp.schema_text}
    for rep in inp.replicas:
        if rep.script_text:
            sources[f"{rep.replica_id}/{rep.script_path.name}"] = rep.script_text  # type: ignore[union-attr]
    payload["findings"] = verify_anchors(payload.get("findings") or [], sources)
    payload["anchor_sources"] = sorted(sources)
    payload["focal_claim_rule"] = inp.focal_rule
    payload.update(provenance)
    return write_check(
        inp.paper_id, "broad", inputs=inputs, prompt_versions=versions,
        model_calls=calls, response=payload,
    )


# --- assembly -------------------------------------------------------------

SEVERITY_ORDER = {"major": 0, "minor": 1, "note": 2}


def assemble(inp: Stage2Inputs, records: dict[str, CheckRecord]) -> AnalysisReview:
    cl = records["causal_language"]
    md = records["mde"]
    al = records["alignment"]
    br = records["broad"]

    causal = None
    if cl.response:
        p = cl.response
        causal = CausalLanguageRating(
            rating=(
                f"language={p.get('language_strength')}; "
                f"design_supports={p.get('design_inference_strength')}; "
                f"verdict={p.get('verdict')}"
            ),
            quotes=[q for q in ([p.get("focal_claim_quote")] + list(p.get("abstract_quotes") or [])) if q],
            note=p.get("reasoning"),
            **{k: p[k] for k in
               ("language_strength", "design_inference_strength", "verdict",
                "design_basis", "quotes_verified") if k in p},
        )

    mde_check = None
    if md.response:
        p = md.response
        mde_check = MdeCheck(
            assumptions=list(p.get("assumptions") or []),
            curve=[{"effect": float(c["effect"]), "power": float(c["power"])}
                   for c in (p.get("curve") or []) if "effect" in c and "power" in c],
            note=p.get("method"),
            **{k: p[k] for k in
               ("design", "n_analysed", "n_per_group", "mde_standardised", "mde_metric",
                "alpha", "target_power", "caveats", "r_script", "design_source")
               if k in p},
        )

    alignment = None
    if al.response:
        p = al.response
        per_replica: dict[str, list[str]] = {rid: [] for rid in (p.get("traced_open_choices") or {})}
        for item in p.get("open_choices") or []:
            for rid, chosen in (item.get("replica_choices") or {}).items():
                per_replica.setdefault(rid, []).append(f"{item.get('choice')}: {chosen}")
        for rid, choices in (p.get("traced_open_choices") or {}).items():
            if not per_replica.get(rid):
                per_replica[rid] = list(choices)
        alignment = AlignmentCheck(
            verdict=p.get("verdict"),
            open_choices_per_replica=per_replica,
            note=p.get("reasoning"),
            claim_quote=p.get("claim_quote"),
            contract_basis=p.get("contract_basis") or [],
            open_choices=p.get("open_choices") or [],
        )

    broad = None
    if br.response:
        findings = sorted(
            br.response.get("findings") or [],
            key=lambda f: (SEVERITY_ORDER.get(f.get("severity"), 3), not f.get("anchor_verified")),
        )
        broad = BroadReview(
            findings=[
                ReviewFinding(
                    severity=f.get("severity", "note"),
                    quote=f.get("anchor"),
                    location=f.get("location"),
                    comment=f.get("comment", ""),
                    category=f.get("category"),
                    anchor=f.get("anchor"),
                    anchor_verified=f.get("anchor_verified"),
                    anchor_found_in=f.get("anchor_found_in") or [],
                    checkable_by=f.get("checkable_by"),
                )
                for f in findings
            ],
            summary=br.response.get("summary"),
        )

    abstained = [name for name, rec in records.items() if rec.state == "abstained"]
    model_calls: list[str] = []
    for name in CHECKS:
        for cid in (records[name].meta.model_calls if records[name].meta else []):
            if cid not in model_calls:
                model_calls.append(cid)
    prompt_versions: dict[str, str] = {}
    for name in CHECKS:
        prompt_versions.update(records[name].meta.prompt_versions if records[name].meta else {})

    ambiguities = [f"check {name} abstained: {records[name].abstain_reason}" for name in abstained]
    if inp.focal_error:
        ambiguities.append(f"focal claim not bound: {inp.focal_error}")

    return AnalysisReview(
        narrow=NarrowChecks(causal_language=causal, mde=mde_check, alignment=alignment),
        broad=broad,
        state="abstained" if len(abstained) == len(CHECKS) else "complete",
        abstain_reason="; ".join(ambiguities) if len(abstained) == len(CHECKS) else None,
        open_ambiguities=ambiguities,
        claim_id=inp.focal_claim.claim_id if inp.focal_claim else None,
        focal_claim_rule=inp.focal_rule,
        checks_abstained=abstained,
        meta=ArtifactMeta(
            artifact="AnalysisReview",
            stage=STAGE,
            inputs=inp.hashes,
            prompt_versions=prompt_versions,
            model_calls=model_calls,
        ),
    )


# --- markdown -------------------------------------------------------------


def _md_quote(text: str | None) -> str:
    if not text:
        return "_(none)_"
    return "> " + str(text).strip().replace("\n", "\n> ")


def render_md(inp: Stage2Inputs, review: AnalysisReview, records: dict[str, CheckRecord]) -> str:
    L: list[str] = [f"# Stage 2 — analysis review: {inp.paper_id}", ""]
    L.append(f"Focal claim could not be bound: {inp.focal_error}." if inp.focal_error
             else f"Focal claim bound by: {inp.focal_rule}.")
    if inp.focal_claim:
        L.append(f"Focal claim id: `{inp.focal_claim.claim_id}`.")
    if inp.focal_contract:
        L.append(f"Focal analysis: `{inp.focal_contract.analysis_id}` "
                 f"(model_type: {inp.focal_contract.model_type}).")
    L += ["", "Stage 2 is context for a human reviewer, not a verdict on the paper.", ""]

    def abstained(name: str) -> bool:
        rec = records[name]
        if rec.state == "abstained":
            L.append(f"_Abstained: {rec.abstain_reason}_")
            L.append("")
            return True
        return False

    # 1. causal language
    L += ["## 1. Causal language versus design", ""]
    if not abstained("causal_language"):
        c = review.narrow.causal_language if review.narrow else None
        p = records["causal_language"].response or {}
        if c is not None:
            L += [
                f"- Language strength: **{p.get('language_strength')}**",
                f"- Inference strength the design supports: **{p.get('design_inference_strength')}**",
                f"- Verdict: **{p.get('verdict')}**",
                "",
                str(c.note or ""),
                "",
                "Quotes (verbatim check against paper.txt in brackets):",
                "",
            ]
            verified = p.get("quotes_verified") or {}
            for q in c.quotes:
                mark = "verified" if verified.get(q) else "NOT FOUND in paper.txt"
                L += [_md_quote(q), f"[{mark}]", ""]
            if p.get("design_basis"):
                L += ["Design basis:", ""] + [f"- {b}" for b in p["design_basis"]] + [""]

    # 2. MDE
    L += ["## 2. Minimum detectable effect", ""]
    if not abstained("mde"):
        m = review.narrow.mde if review.narrow else None
        p = records["mde"].response or {}
        if m is not None:
            L.append(f"Computed in R from n and the model form ({p.get('design')} design).")
            mde_val = p.get("mde_standardised")
            metric = p.get("mde_metric") or p.get("mde_paper_metric") or "standardised effect"
            if mde_val is not None:
                L.append(
                    f"**MDE at {int(float(p.get('target_power', 0.8)) * 100)}% power "
                    f"(alpha = {p.get('alpha', 0.05)}, two-sided): {metric} = {mde_val}**"
                )
            L += ["", "| effect | power |", "|---:|---:|"]
            for row in m.curve:
                L.append(f"| {row['effect']:g} | {row['power']:.3f} |")
            L += ["", "Assumptions:", ""] + [f"- {a}" for a in m.assumptions] + [""]
            for cav in p.get("caveats") or []:
                L.append(f"- Caveat: {cav}")
            if p.get("r_script"):
                L.append(f"- R script: `{p['r_script']}`")
            L.append("")

    # 3. alignment
    L += ["## 3. Claim–analysis alignment", ""]
    if not abstained("alignment"):
        a = review.narrow.alignment if review.narrow else None
        p = records["alignment"].response or {}
        if a is not None:
            L += [f"Verdict: **{a.verdict}**", "", str(a.note or ""), ""]
            if p.get("claim_quote"):
                L += ["Claim as worded:", "", _md_quote(p["claim_quote"]), ""]
            if p.get("contract_basis"):
                L += ["Contract parts the claim rests on:", ""] + \
                     [f"- {b}" for b in p["contract_basis"]] + [""]
            L += ["### Open choices", ""]
            for item in p.get("open_choices") or []:
                matters = item.get("matters_for_claim")
                flag = " **(matters for the claim)**" if matters else ""
                L.append(f"- **{item.get('choice')}**{flag}")
                if item.get("options"):
                    L.append(f"  - options: {', '.join(item['options'])}")
                for rid, chosen in (item.get("replica_choices") or {}).items():
                    L.append(f"  - `{rid}`: {chosen}")
                if item.get("note"):
                    L.append(f"  - {item['note']}")
            L += ["", "### Open choices as logged by each replica", ""]
            for rid, choices in (p.get("traced_open_choices") or {}).items():
                L.append(f"- `{rid}`: " + ("; ".join(choices) if choices else "_none logged_"))
            L.append("")

    # 4. broad
    L += ["## 4. Broad referee pass", ""]
    if not abstained("broad"):
        b = review.broad
        p = records["broad"].response or {}
        if b is not None:
            if p.get("canonical_replica"):
                L += [
                    f"Read: the focal analysis's methods and results passages, the data "
                    f"schema, replica `{p['canonical_replica']}`'s script in full "
                    f"({p.get('canonical_replica_reason')}), and unified diffs of "
                    f"{', '.join('`' + r + '`' for r in p.get('diffed_replicas') or []) or 'no other replica'}.",
                    "",
                ]
            if p.get("summary"):
                L += [str(p["summary"]), ""]
            verified = [f for f in b.findings if getattr(f, "anchor_verified", False)]
            unverified = [f for f in b.findings if not getattr(f, "anchor_verified", False)]

            def block(f: ReviewFinding) -> list[str]:
                cat = getattr(f, "category", None)
                head = f"**{f.severity}** · {cat or 'uncategorised'}" + \
                       (f" · {f.location}" if f.location else "")
                out = [head, "", _md_quote(f.quote), "", f.comment]
                if getattr(f, "checkable_by", None):
                    out.append(f"_Check by: {f.checkable_by}_")
                found = getattr(f, "anchor_found_in", None)
                if found:
                    out.append(f"_Anchor found in: {', '.join(found)}_")
                return out + [""]

            for f in verified:
                L += block(f)
            L += ["### Not verifiable", ""]
            if unverified:
                L.append(
                    "The anchor for these findings was not found verbatim in paper.txt, "
                    "schema.json or any replica script. They are kept for the reader to judge."
                )
                L.append("")
                for f in unverified:
                    L += block(f)
            else:
                L += ["Every finding's anchor was found verbatim.", ""]
            L.append(f"Anchor sources searched: {', '.join(p.get('anchor_sources') or [])}.")
            L.append("")

    if review.open_ambiguities:
        L += ["## Open ambiguities", ""] + [f"- {a}" for a in review.open_ambiguities] + [""]
    ids = review.meta.model_calls if review.meta else []
    L += ["## Model calls", "", ("`" + "`, `".join(ids) + "`") if ids else "_none_", ""]
    return "\n".join(L)

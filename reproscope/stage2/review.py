"""Stage 2 — analysis review.

Four checks, each a function that writes its own JSON under runs/<paper_id>/stage2/
so a rerun repeats only what changed: `causal_language`, `mde`, `alignment`, `broad`.
`assemble` folds them into review.json (AnalysisReview) and review.md.
"""

from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
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
PAPER_TEXT_LIMIT = 120_000  # characters of paper.txt inlined into a prompt


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


def reusable(record: CheckRecord | None, inputs: dict[str, str]) -> bool:
    return bool(
        record
        and record.state == "complete"
        and record.meta is not None
        and record.meta.inputs == inputs
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


class MdeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    n_analysed: int | None = None
    assumptions: list[str] = []
    mde_standardised: float | None = None
    mde_paper_metric: str | None = None
    curve: list[dict[str, float]] = []
    method: str | None = None
    caveats: list[str] = []


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
    paper_truncated: bool
    claims: list[ClaimRecord]
    contracts: list[EstimandContract]
    readiness: dict[str, Any] | None
    schema_text: str
    match: dict[str, Any] | None
    replicas: list[Replica]
    hashes: dict[str, str]
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


def _focal(
    manifest: Any, claims: list[ClaimRecord], contracts: list[EstimandContract]
) -> tuple[ClaimRecord | None, EstimandContract | None, str]:
    """Pick the focal claim and its contract, and say which rule fired.

    Stage 0 does not mark a focal claim, so this walks a fallback chain and
    records the step it stopped at.
    """
    claim: ClaimRecord | None = None
    rule = "none"
    reported = getattr(getattr(manifest, "focal_claim", None), "reported", None)
    target = getattr(reported, "value", None)
    if target is not None:
        matches = [c for c in claims if c.value is not None and str(c.value) == str(target)]
        if len(matches) == 1:
            claim, rule = matches[0], "manifest focal_claim.reported.value matched one claim"
    if claim is None:
        headline = [c for c in claims if c.importance == "headline"]
        if len(headline) == 1:
            claim, rule = headline[0], "single claim marked importance=headline"
    if claim is None and claims:
        claim, rule = claims[0], "first claim in claims.json (no better rule applied)"

    contract: EstimandContract | None = None
    if claim is not None:
        for ct in contracts:
            if claim.claim_id in ct.claim_ids:
                contract = ct
                break
    if contract is None and contracts:
        contract = contracts[0]
        rule += "; contract = first in contracts.json"
    return claim, contract, rule


def gather(paper_id: str) -> Stage2Inputs:
    corpus = paths.corpus_dir(paper_id)
    s0 = paths.run_dir(paper_id, 0)
    s1 = paths.run_dir(paper_id, 1)

    hashes: dict[str, str] = {}

    def note(name: str, path: Path) -> None:
        if path.exists():
            hashes[name] = artifacts.sha256_file(path)

    paper_path = corpus / "paper.txt"
    if not paper_path.exists():
        raise FileNotFoundError(f"stage 2 needs {paper_path} (stage 0 pdftotext layer)")
    note("paper.txt", paper_path)
    note("manifest.json", corpus / "manifest.json")
    raw = paper_path.read_text(errors="replace")
    truncated = len(raw) > PAPER_TEXT_LIMIT
    paper_text = raw[:PAPER_TEXT_LIMIT] if truncated else raw

    for name in ("claims.json", "contracts.json", "readiness.json", "schema.json"):
        note(f"stage0/{name}", s0 / name)
    note("stage1/match.json", s1 / "match.json")

    claims_raw = _read_json(s0 / "claims.json") or []
    claims = [ClaimRecord.model_validate(c) for c in claims_raw]
    contracts_raw = _read_json(s0 / "contracts.json") or []
    contracts = [EstimandContract.model_validate(c) for c in contracts_raw]
    readiness = _read_json(s0 / "readiness.json")
    schema_path = s0 / "schema.json"
    schema_text = schema_path.read_text() if schema_path.exists() else ""
    match = _read_json(s1 / "match.json")

    replicas: list[Replica] = []
    rdir = s1 / "replicas"
    if rdir.exists():
        for d in sorted(p for p in rdir.iterdir() if p.is_dir()):
            trace = _read_json(d / "trace.json") or {}
            note(f"stage1/{d.name}/trace.json", d / "trace.json")
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
    claim, contract, rule = _focal(manifest, claims, contracts)
    return Stage2Inputs(
        paper_id=paper_id,
        manifest=manifest,
        paper_text=paper_text,
        paper_truncated=truncated,
        claims=claims,
        contracts=contracts,
        readiness=readiness,
        schema_text=schema_text,
        match=match,
        replicas=replicas,
        hashes=hashes,
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
    return "\n".join(p for p in parts if p) or "(no focal claim in the manifest)"


# --- check 1: causal language --------------------------------------------


def check_causal_language(inp: Stage2Inputs, *, force: bool = False) -> CheckRecord:
    inputs = _subset(inp.hashes, "paper.txt", "manifest.json")
    existing = load_check(inp.paper_id, "causal_language")
    if reusable(existing, inputs) and not force:
        return existing  # type: ignore[return-value]

    prompt = artifacts.load_prompt(
        "stage2_causal_language",
        focal_claim=_focal_claim_text(inp),
        paper=inp.paper_text,
    )
    r = llm.call(
        "causal_language",
        prompt,
        paper_id=inp.paper_id,
        stage=STAGE,
        tier="strong",
        schema=CausalLanguageResponse,
        log_path=paths.run_dir(inp.paper_id, 2) / "logs" / "causal_language.log",
    )
    versions = {"stage2_causal_language": artifacts.prompt_version("stage2_causal_language")}
    calls = [r.ledger_id] if r.ledger_id else []
    if r.parsed is None:
        return write_check(
            inp.paper_id, "causal_language", inputs=inputs, prompt_versions=versions,
            model_calls=calls, response=None,
            abstain_reason=r.error or "model returned no valid rating",
        )
    payload = r.parsed.model_dump()
    payload["quotes_verified"] = _verify_quotes(payload, inp.paper_text)
    if inp.paper_truncated:
        payload.setdefault("caveats", []).append(
            f"paper.txt was truncated to the first {PAPER_TEXT_LIMIT} characters"
        )
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
    """n for the power calculation, preferring what the replicas actually analysed."""
    claim_id = inp.focal_claim.claim_id if inp.focal_claim else None
    ns: list[int] = []
    for rep in inp.replicas:
        for row in (rep.results or {}).get("results", []) if isinstance(rep.results, dict) else []:
            if row.get("n") is None:
                continue
            if claim_id is None or row.get("claim_id") == claim_id:
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
    # match.json is deliberately excluded: neither check reads it, so a stage 1
    # rematch must not invalidate a strong-tier call.
    inputs = _subset(
        inp.hashes, "manifest.json", "stage0/contracts", "stage0/readiness", "stage1/",
        exclude=("stage1/match.json",),
    )
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
            fallback_reason = f"deterministic path failed: {e}"
    elif design is None:
        fallback_reason = (
            f"model_type {ct.model_type!r} is not one of the covered designs"
            if ct is not None else "no estimand contract to read the design from"
        )
    else:
        fallback_reason = f"no analysed n available ({n_source})"

    return _mde_agentic(inp, inputs, fallback_reason)


def _mde_agentic(inp: Stage2Inputs, inputs: dict[str, str], reason: str) -> CheckRecord:
    """Fallback: an agentic call in a directory holding only the design inputs."""
    work = paths.run_dir(inp.paper_id, 2) / "mde_work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    if inp.focal_contract is not None:
        (work / "CONTRACT.json").write_text(inp.focal_contract.model_dump_json(indent=2))
    if inp.readiness is not None:
        (work / "READINESS.json").write_text(json.dumps(inp.readiness, indent=2))
    (work / "TRACES.json").write_text(
        json.dumps([r.trace for r in inp.replicas], indent=2, default=str)
    )

    material = (
        f"The working directory holds CONTRACT.json, READINESS.json and TRACES.json. "
        f"Read them there and run R with Rscript.\n"
        f"Deterministic power computation was not applicable: {reason}.\n"
        f"Effect grid to report power for: {', '.join(str(e) for e in mde_mod.EFFECTS)}."
    )
    prompt = artifacts.load_prompt("stage2_mde", material=material)
    r = llm.call(
        "mde",
        prompt,
        paper_id=inp.paper_id,
        stage=STAGE,
        tier="strong",
        agentic=True,
        cwd=work,
        schema=MdeResponse,
        log_path=paths.run_dir(inp.paper_id, 2) / "logs" / "mde.log",
    )
    versions = {"stage2_mde": artifacts.prompt_version("stage2_mde")}
    calls = [r.ledger_id] if r.ledger_id else []
    if r.parsed is None:
        return write_check(
            inp.paper_id, "mde", inputs=inputs, prompt_versions=versions, model_calls=calls,
            response={"method": "agentic", "fallback_reason": reason},
            abstain_reason=r.error or "model returned no valid MDE",
        )
    payload = r.parsed.model_dump()
    payload["method"] = payload.get("method") or "agentic"
    payload["computed_by"] = "agentic"
    payload["fallback_reason"] = reason
    return write_check(
        inp.paper_id, "mde", inputs=inputs, prompt_versions=versions,
        model_calls=calls, response=payload,
    )


# --- check 3: alignment ---------------------------------------------------


def check_alignment(inp: Stage2Inputs, *, force: bool = False) -> CheckRecord:
    # match.json is deliberately excluded: neither check reads it, so a stage 1
    # rematch must not invalidate a strong-tier call.
    inputs = _subset(
        inp.hashes, "manifest.json", "stage0/contracts", "stage0/readiness", "stage1/",
        exclude=("stage1/match.json",),
    )
    existing = load_check(inp.paper_id, "alignment")
    if reusable(existing, inputs) and not force:
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
        tier="strong",
        schema=AlignmentResponse,
        log_path=paths.run_dir(inp.paper_id, 2) / "logs" / "alignment.log",
    )
    versions = {"stage2_alignment": artifacts.prompt_version("stage2_alignment")}
    calls = [r.ledger_id] if r.ledger_id else []
    if r.parsed is None:
        return write_check(
            inp.paper_id, "alignment", inputs=inputs, prompt_versions=versions,
            model_calls=calls, response=None,
            abstain_reason=r.error or "model returned no valid alignment verdict",
        )
    payload = r.parsed.model_dump()
    payload["traced_open_choices"] = {k: v["open_choices"] for k, v in open_choices.items()}
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


def check_broad(inp: Stage2Inputs, *, force: bool = False) -> CheckRecord:
    inputs = _subset(inp.hashes, "paper.txt", "stage0/schema", "stage1/")
    existing = load_check(inp.paper_id, "broad")
    if reusable(existing, inputs) and not force:
        return existing  # type: ignore[return-value]

    blocks = [f"## Paper text\n\n{inp.paper_text}"]
    blocks.append(f"## Data schema (stage0/schema.json)\n\n{inp.schema_text or '(none)'}")
    for rep in inp.replicas:
        name = rep.script_path.name if rep.script_path else "(no script)"
        blocks.append(f"## Replica {rep.replica_id} — {name}\n\n```\n{rep.script_text}\n```")
        blocks.append(
            f"## Replica {rep.replica_id} — results.json\n\n"
            f"{json.dumps(rep.results, indent=2, default=str) if rep.results else '(none)'}"
        )
    blocks.append(
        "## Match summary (stage1/match.json)\n\n"
        + (json.dumps((inp.match or {}).get("summaries") or inp.match, indent=2, default=str)
           if inp.match else "(none)")
    )
    prompt = artifacts.load_prompt("stage2_broad", material="\n\n".join(blocks))
    r = llm.call(
        "broad",
        prompt,
        paper_id=inp.paper_id,
        stage=STAGE,
        tier="strong",
        schema=BroadResponse,
        log_path=paths.run_dir(inp.paper_id, 2) / "logs" / "broad.log",
    )
    versions = {"stage2_broad": artifacts.prompt_version("stage2_broad")}
    calls = [r.ledger_id] if r.ledger_id else []
    if r.parsed is None:
        return write_check(
            inp.paper_id, "broad", inputs=inputs, prompt_versions=versions,
            model_calls=calls, response=None,
            abstain_reason=r.error or "model returned no valid referee findings",
        )
    payload = r.parsed.model_dump()
    sources = {"paper.txt": inp.paper_text, "schema.json": inp.schema_text}
    for rep in inp.replicas:
        if rep.script_text:
            sources[f"{rep.replica_id}/{rep.script_path.name}"] = rep.script_text  # type: ignore[union-attr]
    payload["findings"] = verify_anchors(payload.get("findings") or [], sources)
    payload["anchor_sources"] = sorted(sources)
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
                "mde_paper_metric", "alpha", "target_power", "caveats", "r_script",
                "fallback_reason", "design_source", "computed_by") if k in p},
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
    if inp.paper_truncated:
        ambiguities.append(f"paper.txt truncated to {PAPER_TEXT_LIMIT} characters for the prompts")

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
    L.append(f"Focal claim selected by: {inp.focal_rule}.")
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
            how = "computed in R" if p.get("method") == "deterministic" else "produced by an agentic model call"
            L.append(f"Method: {how}.")
            if p.get("fallback_reason"):
                L.append(f"Deterministic path not used because {p['fallback_reason']}.")
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

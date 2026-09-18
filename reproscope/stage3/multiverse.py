"""Stage 3 — the multiverse on the focal claim.

Seven steps, each writing its own JSON under runs/<paper_id>/stage3/ and each skipped
when its output is already there and `force` is off:

1. `focal.json`      bind the manifest's focal claim to a claim_id and pick the quantity
                     the curve is drawn in (`focal_quantity`)
2. `factors_proposed.json`   cheap enumerator over contract, schema and replica traces
3. `screen.json` + `grid.json`   adversarial screen (different model family), then a
                     deterministic grid build with incompatible pruning, a size cap and
                     a stratified fractional sample above the execution cap. The grid
                     is rebuilt every run: it is a pure function of the two steps above.
4. `execute.json`    agentic executor writes and runs out/multiverse.R -> out/specs.csv,
                     then deterministic verification plus a hardcoding audit
5. `rank.json`       where the paper's reported estimate sits in the curve
6. `interpretation.md` / `interpretation.json`   neutral read of specs.csv only
7. `space.json`      the SpecificationSpace artifact
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import random
import re
import shutil
import subprocess
import tempfile
import sys
import copy
from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths, provenance
from ..statistical import validate_result
from ..artifacts import ClaimRecord, EstimandContract
from ..focal import QUANTITY_PREFERENCE, _TSTAT_KINDS, _as_float, _norm, bind_focal_claim  # noqa: F401

# Two caps with different jobs. GRID_CAP bounds the design itself: above it, low-priority
# factors are pinned or dropped, so the grid stays a grid a reader can describe. EXEC_CAP
# bounds what is actually run: above it the curve is estimated from a stratified fraction
# of the pruned grid instead of all of it.
GRID_CAP = 256
EXEC_CAP = 64
EXECUTOR_TIMEOUT_S = 3600


# --- structured-output schemas -------------------------------------------


class ProposedLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    how: str = ""
    # The significance threshold this level implies, when it changes one (a Bonferroni
    # or other multiplicity correction). Absent means the executor's default of .05.
    p_threshold: float | None = None


class ProposedFactor(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    source: str | None = None
    field: str | None = None
    levels: list[ProposedLevel] = []
    paper_level: str | None = None
    author_evidence: str | None = None


class Unimplementable(BaseModel):
    """A choice the enumerator identified but the supplied data cannot vary."""

    model_config = ConfigDict(extra="allow")

    name: str
    reason: str = ""


class EnumerateOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    factors: list[ProposedFactor] = []
    unimplementable: list[Unimplementable] = []
    notes: str | None = None


class ScreenedLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    reference_settings: dict[str, Any] = {}
    ci_reference_settings: dict[str, Any] = {}
    role: Literal["comparable_effect", "related_effect", "inference_only", "diagnostic"] = "comparable_effect"
    effect_group: str = "focal"
    null_group: str = "focal"
    estimator: str = "unspecified"
    effect_metric: str | None = None
    comparability_rationale: str = ""
    verdict: Literal["defensible", "rejected"]
    # What varying the level can change. A screen output written before this field
    # existed says nothing, and the level is taken to bear on the estimate.
    affects: Literal["estimate", "inference", "reporting"] = "estimate"
    rationale: str | None = None
    rejection_kind: Literal['substantive','operational','nonstandard'] | None = None
    missing_details: list[Literal['algorithm','parameters','variables','order','uncertainty','null','scale','dependencies']] = []


class ScreenedFactor(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    levels: list[ScreenedLevel] = []


class Incompatible(BaseModel):
    model_config = ConfigDict(extra="allow")

    a: str
    b: str
    why: str | None = None


class ScreenAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["merge_levels", "pin_level", "rewrite_how", "add_level", "unresolved"]
    factor: str
    levels: list[str] = []
    canonical: str | None = None
    how: str | None = None
    rationale: str
    mandatory: bool = True


class PrimaryEffect(BaseModel):
    metric: str
    effect_group: str
    rationale: str


class ReportingRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: dict[str, list[str]]
    effect_group: str
    effect_metric: str
    null_group: str
    role: Literal["comparable_effect", "related_effect", "inference_only"]
    rationale: str


class ReportingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reporting_rules: list[ReportingRule]


class ScreenOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    factors: list[ScreenedFactor] = []
    incompatible: list[Incompatible] = []
    adjustments: list[ScreenAdjustment] = []
    grid_size_after_screen: int | None = None
    primary_effect: PrimaryEffect | None = None
    reporting_rules: list[ReportingRule] = []


class PaperLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    factor: str
    level: str | None = None
    evidence: str = ""


class PaperLevelsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    levels: list[PaperLevel] = []


# --- small helpers --------------------------------------------------------


def _read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def _write_json(path: Path, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str) + "\n")
    return path



def _truthy(x: Any) -> bool:
    return str(x).strip().lower() in {"1", "true", "t", "yes", "y"}


# --- step 1: focal-claim binding -----------------------------------------
def derive_paper_levels(
    paper_id: str, proposed: dict[str, Any], focal: dict[str, Any]
) -> dict[str, Any]:
    """Document author choices from explicit source evidence, independently of matches."""
    from ..stage1.blind import paper_text

    source = paper_text(paper_id)
    prompt = artifacts.load_prompt(
        "stage3_paper_level", factors=json.dumps(proposed.get("factors", [])),
        source=source + "\n\nFOCAL ANALYSIS CONTEXT (scope only, not source evidence):\n" + json.dumps(focal, default=str),
    )
    r = llm.call("paper_level", prompt, paper_id=paper_id, stage="3",
                 tier="cheap", schema=PaperLevelsOut,
                 log_path=paths.run_dir(paper_id, 3) / "logs/paper_level.log")
    if not r.ok or r.parsed is None:
        raise llm.LLMError(f"author-method evidence call failed: {r.error}")
    out = {"levels": {}, "source": "documented author evidence", "evidence": {},
           "notes": [], "unresolved": [], "diagnostics": {},
           "raw_response": r.parsed.model_dump(), "focal_context": focal, "_ledger_id": r.ledger_id}
    answers = {item.factor: item for item in r.parsed.levels} if r.ok and r.parsed else {}
    if len(answers) != len(r.parsed.levels) or not set(answers) <= {f["name"] for f in proposed.get("factors", [])}:
        out["notes"].append("duplicate or unknown attribution factor IDs; candidates rejected")
        answers = {}
    for factor in proposed.get("factors", []):
        name = factor["name"]
        item = answers.get(name)
        options = {lv["value"] for lv in factor.get("levels", [])}
        # A quote is necessary, but cannot establish that it entails the claimed
        # method. Keep the source visible for human/reference validation.
        if (item and item.level in options and len(item.evidence.strip()) >= 20
                and " ".join(item.evidence.casefold().split()) in " ".join(source.casefold().split())):
            out["levels"][name] = item.level
            out["evidence"][name] = item.evidence
            out["diagnostics"][name] = {"status": "documented_candidate", "entailment": "requires_validation"}
        else:
            out["unresolved"].append(name)
            out["diagnostics"][name] = {"status": "missing_response" if item is None else
                "not_documented_or_ambiguous" if item.level is None else
                "invalid_level" if item.level not in options else "source_quote_rejected",
                "candidate": item.model_dump() if item else None}
    if out["unresolved"]:
        out["notes"].append("author specification undetermined for: " + ", ".join(out["unresolved"]))
    return out


def apply_adjustments(proposed: dict, screen: dict) -> tuple[dict, list[dict], list[str]]:
    """Apply the screen's executable amendments once; unresolved requirements block."""
    proposed = copy.deepcopy(proposed)
    records, blocking = [], []
    factors = {f["name"]: f for f in proposed.get("factors", [])}
    for raw in screen.get("adjustments", []):
        try:
            change = ScreenAdjustment.model_validate(raw)
            factor = factors[change.factor]
            levels = {lv["value"]: lv for lv in factor["levels"]}
            if change.kind == "rewrite_how" and change.canonical in levels and change.how:
                levels[change.canonical]["how"] = change.how
            elif change.kind in {"merge_levels", "pin_level"} and change.canonical in levels:
                if not set(change.levels) <= levels.keys():
                    raise ValueError("unknown level in adjustment")
                if change.kind == "pin_level":
                    factor["levels"] = [levels[change.canonical]]
                else:
                    removed = set(change.levels) - {change.canonical}
                    factor["levels"] = [lv for lv in factor["levels"] if lv["value"] not in removed]
                    levels[change.canonical]["equivalent_levels"] = sorted(removed)
            elif change.kind == "add_level" and change.canonical and change.how:
                if change.canonical in levels:
                    raise ValueError("added level already exists")
                factor["levels"].append({"value": change.canonical, "how": change.how})
            else:
                raise ValueError("unresolved or incomplete screen adjustment")
            records.append({**change.model_dump(), "status": "applied"})
        except (ValueError, KeyError, TypeError) as exc:
            records.append({"instruction": raw, "status": "unresolved", "reason": str(exc)})
            if not isinstance(raw, dict) or raw.get("mandatory", True):
                blocking.append(f"unresolved mandatory screen adjustment: {raw}")
    return proposed, records, blocking


def _verdicts(screen: dict[str, Any]) -> dict[tuple[str, str], ScreenedLevel]:
    out: dict[tuple[str, str], ScreenedLevel] = {}
    for f in screen.get("factors", []):
        for lv in f.get("levels", []):
            out[(_norm(f.get("name", "")), _norm(lv.get("value", "")))] = ScreenedLevel(**lv)
    return out


def _parse_ref(ref: str) -> tuple[str, str] | None:
    """`factor=level` from the screen's incompatibility list."""
    if "=" not in str(ref):
        return None
    name, _, level = str(ref).partition("=")
    return _norm(name), _norm(level)


def build_grid(
    proposed: dict[str, Any],
    screen: dict[str, Any],
    *,
    cap: int = GRID_CAP,
    exec_cap: int | None = EXEC_CAP,
    paper_id: str | None = None,
    paper_levels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build an explicitly screened grid; documented rejected choices are references."""
    original_proposed = proposed
    proposed, adjustments, blocking = apply_adjustments(proposed, screen)
    verdicts = _verdicts(screen)
    notes: list[str] = []
    factors: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    flagged: list[dict[str, str]] = []
    # Preserve explicit rejections even when a pin or merge removes the level
    # before grid construction. The exclusion record describes the full screen.
    retained_keys = {(_norm(f['name']), _norm(lv['value']))
                     for f in proposed.get('factors', []) for lv in f.get('levels', [])}
    for f in original_proposed.get('factors', []):
        for lv in f.get('levels', []):
            key = (_norm(f['name']), _norm(lv['value']))
            verdict = verdicts.get(key)
            if key not in retained_keys and verdict and verdict.verdict == 'rejected':
                rejected.append({'factor': f['name'], 'level': lv['value'],
                                 'rationale': verdict.rationale or ''})
    original_author_levels = dict(paper_levels or {})
    paper_levels = dict(original_author_levels)
    for change in adjustments:
        if change.get("status") == "applied" and change.get("kind") == "merge_levels":
            name = change["factor"]
            if paper_levels.get(name) in change.get("levels", []):
                paper_levels[name] = change["canonical"]

    for pf in proposed.get("factors", []):
        name = pf.get("name", "")
        paper_level = paper_levels.get(name)
        levels: list[dict[str, Any]] = []
        for lv in pf.get("levels", []):
            value = lv.get("value", "")
            alpha = {"p_threshold": lv["p_threshold"]} if lv.get("p_threshold") else {}
            is_paper = bool(paper_level) and _norm(paper_level) == _norm(value)
            sv = verdicts.get((_norm(name), _norm(value)))
            if sv is None:
                blocking.append(f"{name}={value}: no explicit screen verdict")
                continue
            diagnostic = sv.role == "diagnostic" or bool(re.search(r"leave[ _-]one[ _-]out|jackknife|bootstrap[ _-]replicate|random[ _-]seed", name+" "+value, re.I))
            if diagnostic:
                rejected.append({"factor": name, "level": value, "rationale": "Diagnostic or internal computational control; excluded from analytical dimensions"})
                continue
            if sv.verdict == "rejected":
                rejected.append({"factor": name, "level": value, "rationale": sv.rationale or ""})
                if is_paper:
                    flagged.append({"factor": name, "level": value, "rationale": sv.rationale or ""})
                continue
            else:
                levels.append({"value": value, "how": lv.get("how", "") + (
                    " Report once-adjusted p in p, declare the raw p family and adjustment; compare against family alpha .05."
                    if alpha else ""),
                               "verdict": "paper" if is_paper else "defensible",
                               "affects": sv.affects, "rationale": sv.rationale or "",
                               "equivalent_levels": lv.get("equivalent_levels", []),
                               "reference_settings": sv.reference_settings,
                               "ci_reference_settings": sv.ci_reference_settings,
                               **{k: getattr(sv, k) for k in ("role", "effect_group", "null_group", "estimator", "effect_metric", "comparability_rationale")}})
        if not levels and all((verdicts.get((_norm(name), _norm(lv.get("value", "")))) and verdicts[(_norm(name), _norm(lv.get("value", "")))].role == "diagnostic") or re.search(r"leave[ _-]one[ _-]out|jackknife|bootstrap[ _-]replicate|random[ _-]seed", name+" "+lv.get("value", ""), re.I) for lv in pf.get("levels", [])):
            notes.append(f"{name}: diagnostic/computational factor omitted from analytical grid")
            continue
        if not levels:
            blocking.append(f"required factor {name!r} has no defensible level")
            factors.append({"name": name, "levels": [], "paper_level": None})
            continue
        paper_kept = any(_norm(paper_level) == _norm(lv["value"]) for lv in levels)
        if paper_level and not paper_kept:
            notes.append(f"factor {name!r}: the paper's level {paper_level!r} matches none of "
                         "the enumerated levels")
        pinned = None
        if len(levels) > 1 and all(lv.get("affects", "estimate") == "reporting" for lv in levels):
            # A factor that only changes how the result is written (a sign convention,
            # an effect-size label) is not a branch of the curve; executing it would
            # multiply the grid and, for a sign convention, mirror the estimates.
            keep = next((lv for lv in levels if lv.get("verdict") == "paper"), levels[0])
            levels, pinned = [keep], "reporting-only factor pinned to one level"
            notes.append(f"factor {name!r}: {pinned} ({keep['value']!r})")
        factors.append({
            "name": name,
            "field": pf.get("field"),
            "source": pf.get("source"),
            "paper_level": paper_level if paper_kept else None,
            "pinned": pinned,
            "levels": levels,
        })

    # Incompatible pairs, resolved against the surviving factors.
    by_name = {_norm(f["name"]): f for f in factors}

    def resolves(ref: str) -> bool:
        parsed = _parse_ref(ref)
        if parsed is None:
            return False
        fn, lv = parsed
        f = by_name.get(fn)
        return f is not None and any(_norm(x["value"]) == lv for x in f["levels"])

    original_refs = {(_norm(f["name"]), _norm(lv["value"]))
                     for f in original_proposed.get("factors", []) for lv in f["levels"]}
    incompatible: list[dict[str, Any]] = []
    for inc in screen.get("incompatible", []):
        a, b = inc.get("a", ""), inc.get("b", "")
        if resolves(a) and resolves(b):
            incompatible.append({"a": a, "b": b, "why": inc.get("why")})
        elif _parse_ref(a) not in original_refs or _parse_ref(b) not in original_refs:
            blocking.append(f"incompatibility contains an unknown factor or level: {a!r}, {b!r}")
        else:
            notes.append(f"incompatibility {a!r} x {b!r} ignored: it does not resolve to two "
                         "surviving levels")

    dropped: list[str] = []
    size = _grid_size(factors,incompatible)
    if size>cap:
        notes.append(f"Screened grid has {size} compatible specifications; all analytical dimensions retained, execution sampling applies.")

    grid = {
        "factors": factors,
        "incompatible": incompatible,
        "rejected_levels": rejected,
        "paper_level_flagged": flagged,
        "grid_size": _grid_size(factors, incompatible),
        "full_factorial": math.prod(len(f["levels"]) for f in factors) if factors else 0,
        "dropped_factors": dropped,
        "unimplementable": [dict(u) for u in proposed.get("unimplementable", [])],
        "cap": cap,
        "adjustments": adjustments,
        "blocking_issues": blocking,
        "author_levels": paper_levels,
        "reference_specs": [],
        "notes": notes,
    }
    if grid["full_factorial"]>200_000:
        blocking.append("screened Cartesian grid exceeds the 200,000-combination enumeration limit; reduce redundant levels or implement a sparse design without dropping analytical dimensions")
    if blocking:
        grid["grid_size"] = 0
        grid["n_specs"] = 0
        grid["sampled_spec_ids"] = []
        return grid
    for factor in factors:
        author = paper_levels.get(factor["name"])
        if author and not any(_norm(lv["value"]) == _norm(author) for lv in factor["levels"]):
            if not any(x["factor"] == factor["name"] for x in flagged):
                flagged.append({"factor": factor["name"], "level": author,
                                "rationale": "documented level removed by a screen amendment"})
    if flagged and len(original_author_levels) == len(original_proposed.get("factors", [])):
        grid["reference_specs"] = [{"spec_id": "reference_author", "levels": original_author_levels,
                                    "role": "author_reference", "is_paper_level": True}]
        grid["reference_factors"] = original_proposed.get("factors", [])
    apply_exec_cap(grid, paper_id=paper_id, exec_cap=exec_cap)
    grid["n_reference_specs"] = len(grid["reference_specs"])
    return grid


def result_moving_levels(grid: dict[str, Any]) -> list[dict[str, str]]:
    """The defensible levels, other than the paper's own, that can change the result.

    Robustness covers the estimate and its significance, so a level that only moves the
    test or the p-value (an adjusted alpha, a one- versus two-tailed test) is a branch
    worth running. A level that changes only how the result is presented is not: a grid
    holding nothing else has no curve to draw, and the rest of the stage would spend an
    executor run and two model calls to say so.
    """
    return [
        {"factor": f["name"], "level": lv["value"]}
        for f in grid.get("factors", [])
        for lv in f.get("levels", [])
        if lv.get("verdict") != "paper"
        and lv.get("affects", "estimate") in ("estimate", "inference")
    ]


def apply_exec_cap(
    grid: dict[str, Any], *, paper_id: str | None, exec_cap: int | None
) -> dict[str, Any]:
    """Decide which specifications of the grid are executed, and record the decision.

    `grid_size` keeps the full count of the pruned grid. `n_specs` is what runs,
    `sampled` says whether that is a fraction, and `sample_fraction` how large a one.
    """
    specs = [s for s in enumerate_specs(grid) if s.get("role") != "author_reference"]
    grid["exec_cap"] = exec_cap
    grid["n_specs"] = len(specs)
    varying = [f for f in grid.get("factors", []) if len(f.get("levels", [])) > 1]
    grid["sensitivity_scope"] = "inference_only" if varying and all(lv.get("affects") == "inference" for f in varying for lv in f["levels"]) else "estimate_and_inference" if varying else "single_specification"
    grid["sampled"] = False
    grid["sample_fraction"] = 1.0
    if exec_cap is None or len(specs) <= exec_cap:
        return grid
    chosen = sample_specs(specs, grid, paper_id=paper_id, cap=exec_cap)
    grid["sampled_spec_ids"] = [s["spec_id"] for s in chosen]
    grid["n_specs"] = len(chosen)
    grid["sampled"] = True
    grid["sample_fraction"] = round(len(chosen) / len(specs), 6)
    note = (f"the grid of {len(specs)} specifications exceeds the execution cap of "
            f"{exec_cap}; {len(chosen)} are executed as a stratified fractional sample "
            f"seeded from the paper id")
    if not any(s.get("is_paper_level") for s in specs):
        note += "; the paper's own specification is not identified in this grid"
    grid.setdefault("notes", []).append(note)
    return grid


def sample_specs(
    specs: list[dict[str, Any]],
    grid: dict[str, Any],
    *,
    paper_id: str | None,
    cap: int,
) -> list[dict[str, Any]]:
    """A deterministic fraction of the grid that still covers every factor level.

    The seed is fixed from the paper id, so the same paper always executes the same
    specifications. The paper's own specification goes in first; then every level of
    every factor is given at least one specification, as far as the cap allows; then the
    remainder is drawn at random. The result is in grid order.
    """
    seed = int(hashlib.sha256((paper_id or "").encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    by_id = {s["spec_id"]: s for s in specs}
    order = {s["spec_id"]: i for i, s in enumerate(specs)}
    chosen: list[str] = []

    def take(spec_id: str) -> None:
        if spec_id not in chosen and len(chosen) < cap:
            chosen.append(spec_id)

    for s in specs:
        if s.get("is_paper_level"):
            take(s["spec_id"])
            break

    pool = [s["spec_id"] for s in specs]
    rng.shuffle(pool)
    for f in grid.get("factors", []):
        name = f["name"]
        for lv in f["levels"]:
            value = _norm(lv["value"])
            if any(_norm(by_id[c]["levels"].get(name, "")) == value for c in chosen):
                continue
            hit = next((sid for sid in pool
                        if sid not in chosen
                        and _norm(by_id[sid]["levels"].get(name, "")) == value), None)
            if hit is not None:
                take(hit)
    for sid in pool:
        if len(chosen) >= cap:
            break
        take(sid)
    return sorted((by_id[c] for c in chosen), key=lambda s: order[s["spec_id"]])


def _grid_size(factors: list[dict[str, Any]], incompatible: list[dict[str, Any]]) -> int:
    """Exact count of the factorial minus the incompatible combinations."""
    if not factors:
        return 0
    full = math.prod(len(f["levels"]) for f in factors)
    if not incompatible:
        return full
    if full > 200_000:  # exact constrained count unavailable; the bounded-enumeration gate will stop this grid
        return full
    pairs = []
    for inc in incompatible:
        a, b = _parse_ref(inc["a"]), _parse_ref(inc["b"])
        if a and b:
            pairs.append((a, b))
    kept = 0
    for combo in product(*[[(_norm(f["name"]), _norm(lv["value"])) for lv in f["levels"]]
                           for f in factors]):
        s = set(combo)
        if any(a in s and b in s for a, b in pairs):
            continue
        kept += 1
    return kept


def grid_specs(grid: dict[str, Any]) -> list[dict[str, str]]:
    """Every specification the executor is expected to run, as {factor: level} dicts."""
    factors = grid.get("factors", [])
    if not factors:
        return []
    pairs = []
    for inc in grid.get("incompatible", []):
        a, b = _parse_ref(inc["a"]), _parse_ref(inc["b"])
        if a and b:
            pairs.append((a, b))
    out = []
    for combo in product(*[[lv["value"] for lv in f["levels"]] for f in factors]):
        keyed = {_norm(f["name"]): _norm(v) for f, v in zip(factors, combo)}
        s = set(keyed.items())
        if any(a in s and b in s for a, b in pairs):
            continue
        out.append({f["name"]: v for f, v in zip(factors, combo)})
    return out


def enumerate_specs(grid: dict[str, Any]) -> list[dict[str, Any]]:
    """The numbered specification list both the executor and the reader work from.

    The order is the enumerator's factor order with the last factor varying fastest,
    incompatible combinations removed. Ids are `spec_001`, `spec_002`, ... — a pure
    function of the grid, so the same grid always yields the same id for the same
    combination of levels and no side of the pipeline has to store the mapping.

    `is_paper_level` marks the one specification that uses the paper's own level on
    every factor. It is absent when the screen or the size cap left any factor without
    a paper level, because then the paper's own specification is not fully determined.

    When the grid carries `sampled_spec_ids`, only those specifications are returned.
    Ids still come from the full enumeration, so a sampled specification keeps the id it
    would have had in the whole grid.
    """
    if grid.get("sampled_spec_ids") == []:
        return grid.get("reference_specs",[])
    combos = grid_specs(grid)
    width = max(3, len(str(len(combos))))
    factors = grid.get("factors", [])
    paper = {f["name"]: f.get("paper_level") for f in factors}
    complete = bool(factors) and all(paper.values())
    out = []
    for i, levels in enumerate(combos, start=1):
        spec: dict[str, Any] = {"spec_id": f"spec_{i:0{width}d}", "levels": levels}
        if complete and all(_norm(levels[k]) == _norm(v) for k, v in paper.items()):
            spec["is_paper_level"] = True
        out.append(spec)
    sampled = grid.get("sampled_spec_ids")
    if sampled is not None:
        keep = set(sampled)
        out = [s for s in out if s["spec_id"] in keep]
    return out + grid.get("reference_specs", [])


# --- step 5: rank ---------------------------------------------------------


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


RESULT_COLUMNS = ("spec_id", "estimate", "se", "p", "n", "converged", "error",
                  "p_threshold", "effect_metric", "se_metric", "p_raw", "p_adjustment",
                  "p_family", "p_index", "inference_method", "draws", "exceedances",
                  "effect_group", "null_group", "estimator", "ci_lower", "ci_upper",
                  "ci_method", "ci_level", "per_test_alpha")
DEFAULT_ALPHA = 0.05


def read_specs(path: Path, grid: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Rows of specs.csv, carrying one column per factor with the grid's exact level string.

    The executor is asked for a `spec_id` column and the levels are joined back from
    `enumerate_specs(grid)`, so a row's levels are the grid's own strings whatever the
    executor wrote next to them. A row whose id is not in the grid keeps its own columns
    and is left for `verify_execution` to report.

    Without a `spec_id` column the factor columns themselves are matched, allowing for
    the normalised names (snake_case, punctuation dropped) an executor tends to write.
    """
    if grid is None:
        grid_path = Path(path).parents[2] / "grid.json"
        grid = json.loads(grid_path.read_text()) if grid_path.exists() else None
    return read_specs_text(Path(path).read_text(), grid)


def read_specs_text(text: str, grid: dict | None = None) -> list[dict]:
    """Canonical result/factor decoding shared by verification and interpretation."""
    rows = list(csv.DictReader(io.StringIO(text)))
    if rows and "spec_id" in rows[0]:
        by_id = {s["spec_id"]: s["levels"] for s in enumerate_specs(grid or {})}
        roles = {s["spec_id"]: s.get("role", "defensible") for s in enumerate_specs(grid or {})}
        for r in rows:
            sid = (r.get("spec_id") or "").strip()
            r["_spec_id"] = sid
            levels = by_id.get(sid)
            r["_role"] = roles.get(sid, "unknown")
            r["_factor_mismatches"] = [k for k, v in (levels or {}).items()
                for supplied, actual in r.items() if (_norm_name(supplied) == _norm_name('factor_'+k)
                    or (k not in RESULT_COLUMNS and _norm_name(supplied) == _norm_name(k)))
                and _norm(actual) != _norm(v)]
            r['_factor_mismatches'] += [k for k in (levels or {}) if k in RESULT_COLUMNS and 'factor_'+k not in r]
            if levels:
                r['_factor_levels']=dict(levels)
                r.update({k:v for k,v in levels.items() if k not in RESULT_COLUMNS})
    elif grid and rows:
        by_norm = {_norm_name(f["name"]): f["name"] for f in grid.get("factors", [])}
        rename = {}
        for c in rows[0]:
            # The result columns are never factor columns; without this an `se` column
            # matches a factor called "Sex covariate set" on the prefix rule below.
            if c in by_norm.values() or c in RESULT_COLUMNS:
                continue
            n = _norm_name(c)
            exact = by_norm.get(n)
            prefix = [v for k, v in by_norm.items() if k.startswith(n) or n.startswith(k)]
            if exact:
                rename[c] = exact
            elif len(prefix) == 1:  # the executor shortened the name
                rename[c] = prefix[0]
        if rename:
            rows = [{rename.get(k, k): v for k, v in r.items()} for r in rows]
    for r in rows:
        r["_estimate"] = _as_float(r.get("estimate"))
        r["_se"] = _as_float(r.get("se"))
        r["_p"] = _as_float(r.get("p"))
        r["_converged"] = _truthy(r.get("converged", "true")) if "converged" in r else True
        alpha = _as_float(r.get("p_threshold"))
        r["_alpha"] = alpha if alpha else DEFAULT_ALPHA
        n = _as_float(r.get("n"))
        r["_n"] = int(n) if n is not None and math.isfinite(n) and n.is_integer() else None
    return rows


def rank_reported(
    rows: list[dict[str, Any]],
    reported: float | None,
    grid: dict[str, Any] | None = None,
    *,
    precision: int | None = None,
    quantity_kind: str | None = None,
) -> dict[str, Any]:
    """Where the paper's estimate sits in the curve, plus the sign/significance shares.

    Comparison happens at the precision the paper reported: a specification whose
    estimate rounds to the reported value is a tie, not a specification above or below
    it. Without that, an estimate of 0.6334 counts as above a reported 0.63 on a
    difference the paper never claimed to resolve.

    `share_below`, `share_above` and `share_tied` are the fractions of converged
    estimates on each side and equal after rounding. Two-sided extremeness is
    min(share_below, share_above): 0 when the reported value sits at or outside one end
    of the curve, near 0.5 when it sits in the middle. `rank` counts the estimates below
    the reported value plus one, and is kept for information.
    """
    reference_rows = [r for r in rows if r.get("_role") == "author_reference"]
    rows = [r for r in rows if r.get("_role") != "author_reference"]
    ok = [r for r in rows if r["_converged"] and r["_estimate"] is not None
          and math.isfinite(r["_estimate"])]
    est = sorted(r["_estimate"] for r in ok)
    n = len(est)
    out: dict[str, Any] = {
        "n_specs_total": len(rows),
        "n_converged": n,
        "n_failed": len(rows) - n,
        "reported_estimate": reported,
        "median": st_median(est),
        "min": est[0] if est else None,
        "max": est[-1] if est else None,
    }
    if n and reported is not None:
        at = (lambda x: round(x, precision)) if precision is not None else (lambda x: x)
        target = at(reported)
        below = sum(1 for e in est if at(e) < target)
        above = sum(1 for e in est if at(e) > target)
        out["reported_precision"] = precision
        out["rank"] = below + 1
        out["share_below"] = round(below / n, 6)
        out["share_above"] = round(above / n, 6)
        out["share_tied"] = round((n - below - above) / n, 6)
        out["rank_interval"] = [below + 1, n - above] if below + above < n else [below + 1, below + 1]
        out["curve_state"] = "all_tied" if below == above == 0 else "varying"
        out["extremeness"] = None if below == above == 0 else round(min(below, above) / n, 6)
        sign = (reported > 0) - (reported < 0)
        out["share_same_sign"] = (round(
            sum(1 for e in est if ((e > 0) - (e < 0)) == sign) / n, 6
        ) if quantity_kind not in {"F", "chi2", "sd", "n", "eta2"} else None)
        closest = min(ok, key=lambda r: abs(r["_estimate"] - reported))
        out["closest_spec"] = {
            "estimate": closest["_estimate"],
            "abs_diff": round(abs(closest["_estimate"] - reported), 6),
            "spec": _spec_of(closest, grid),
        }
    with_p = [r for r in ok if r["_p"] is not None]
    out["n_with_p"] = len(with_p)
    if with_p:
        out["share_significant"] = round(
            sum(1 for r in with_p if r["_p"] < r.get("_alpha", DEFAULT_ALPHA)) / len(with_p), 6)
        out["alphas"] = sorted({r.get("_alpha", DEFAULT_ALPHA) for r in with_p})

    out["author_reference"] = [{"estimate": r["_estimate"], "converged": r["_converged"]}
                               for r in reference_rows]
    if grid:
        paper = {f["name"]: f["paper_level"] for f in grid.get("factors", [])
                 if f.get("paper_level")}
        out["paper_level_spec"] = paper or None
        if paper and len(paper) == len(grid.get("factors", [])):
            paper_spec = next(
                (s for s in enumerate_specs(grid) if s.get("is_paper_level")), None
            )
            out["paper_level_spec_id"] = paper_spec["spec_id"] if paper_spec else None
            hit = next(
                (r for r in ok if paper_spec and r.get("_spec_id") == paper_spec["spec_id"]),
                None,
            ) or next(
                (r for r in ok
                 if all(_norm(r.get('_factor_levels',r).get(k, "")) == _norm(v) for k, v in paper.items())), None
            )
            out["paper_level_estimate"] = hit["_estimate"] if hit else None
            if hit is None:
                out["paper_level_note"] = "the paper's own combination is not a row in specs.csv"
        elif paper:
            out["paper_level_note"] = (
                "the screen or the cap left factors without a paper level, so the paper's own "
                "specification is not fully determined"
            )
    return out


def st_median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def _spec_of(row: dict[str, Any], grid: dict[str, Any] | None) -> dict[str, str]:
    names = [f["name"] for f in (grid or {}).get("factors", [])]
    levels = row.get("_factor_levels", row)
    return {k: levels[k] for k in names if k in levels}


# --- work-directory assembly ---------------------------------------------


def _best_replica(
    paper_id: str, focal: dict[str, Any]
) -> tuple[str | None, Path | None, str, str | None]:
    """The replica whose script Stage 3 builds on.

    Returns (replica_id, script path, why, band on the focal claim). The band is None
    when no match row picked the replica. Selection uses stable replica order among
    accepted focal-producing implementations; numerical agreement does not determine author choices.
    """
    stage1 = paths.run_dir(paper_id, 1)
    reps = sorted(p for p in (stage1 / "replicas").glob("*") if p.is_dir()) \
        if (stage1 / "replicas").exists() else []

    def script_of(rid: str) -> Path | None:
        out = stage1 / "replicas" / rid / "work" / "out"
        try:  # Stage 1 decides what counts as a replica's script.
            from ..stage1.replicas import find_script

            return find_script(out) if out.exists() else None
        except ImportError:
            for name in ("analysis.R", "analysis.r", "analysis.py"):
                if (out / name).exists():
                    return out / name
            return None

    from ..stage1.audit import acceptance
    comparison = _read_json(stage1 / "match.json") if (stage1 / "match.json").exists() else {}
    focal_rows = {r["replica_id"]: r for r in comparison.get("rows", [])
                  if r.get("claim_id") == focal["focal_quantity"]["claim_id"]
                  and r.get("replicated") is not None and r.get("state", "complete") == "complete"}
    for p in reps:
        trace = p / "trace.json"
        if not trace.exists():
            continue
        record = _read_json(trace)
        if (p.name not in focal_rows or not record.get("ran")
                or acceptance(record.get("hardcoding_audit") or {}) != "accepted"):
            continue
        s = script_of(p.name)
        if s:
            return p.name, s, "first runnable, audit-accepted focal implementation; independent of numerical proximity", focal_rows[p.name].get("band")
    return None, None, "no replica script found", None


def assemble_work(paper_id: str, focal: dict[str, Any], grid: dict[str, Any]) -> dict[str, Any]:
    """Build runs/<paper_id>/stage3/work/ for the executor agent."""
    stage3 = paths.run_dir(paper_id, 3)
    work = stage3 / "work"
    manifest = paths.manifest(paper_id)
    rid, script, why, band = _best_replica(paper_id, focal)
    if script is None:
        raise FileNotFoundError(f"no replica analysis script under {paths.run_dir(paper_id, 1)}")

    # The executor writes the script that produces the numbers the reported value is
    # ranked against, so no printed form of that value may reach its directory.
    tokens = leak_tokens(
        focal["focal_quantity"].get("reported_value"),
        (manifest.focal_claim.reported.value if manifest.focal_claim
         and manifest.focal_claim.reported else None),
    )
    scan_hits: list[str] = []

    if work.exists():
        import uuid
        archive = stage3 / "work_superseded" / uuid.uuid4().hex
        archive.parent.mkdir(exist_ok=True)
        shutil.move(str(work), archive)
    (work / "out").mkdir(parents=True, exist_ok=True)
    base_name = "BASE_ANALYSIS" + script.suffix
    shutil.copy2(script, work / base_name)
    _write_json(work / "GRID.json", scrub_values(executor_grid(grid), tokens, scan_hits))

    data_dir = work / "data"
    data_dir.mkdir(exist_ok=True)
    from ..stage1.blind import copy_data
    copied = ['data/'+name for name in copy_data(paper_id,data_dir)]

    contracts = _load_contracts(paper_id, blind_first=True)
    focal_contract = next(
        (c for c in contracts if c.analysis_id == focal["analysis_id"]),
        None,
    )
    if focal_contract is None:
        raise ValueError("focal analysis has no matching blind contract")
    # `description` is the paper's results sentence: it carries the group means and the
    # test statistic even after the focal value itself is scrubbed. The executor needs the
    # quantity, not the sentence.
    fq = {k: v for k, v in focal["focal_quantity"].items()
          if k not in {"reported_value", "reported_precision", "description"}}
    contract_json = {
        "focal_claim": {
            "text": focal.get("focal_claim_text"),
            "quantity": fq,
            "note": "The reported value is deliberately withheld from this directory.",
        },
        "contract": focal_contract.model_dump() if focal_contract else None,
    }
    _write_json(work / "CONTRACT.json", scrub_values(contract_json, tokens, scan_hits))

    return {"work": str(work), "base_script": base_name, "base_replica": rid,
            "base_replica_reason": why, "data_files": copied,
            "value_scan": {"tokens_removed": sorted(set(scan_hits)),
                           "clean": not scan_hits}}


def executor_grid(grid: dict[str, Any]) -> dict[str, Any]:
    """The executor's view of the grid: the specifications to run, and how to run them.

    `specs` is the whole job — one entry per specification, already pruned of
    incompatible combinations — so the executor loops over a list instead of building
    its own factorial and paraphrasing the level strings on the way. `factors` says what
    each level means and how to implement it.

    `grid.json` labels levels `defensible` or `paper` for the reader. Handing those
    labels to the executor invites its script to filter on them and quietly drop the
    paper's own specification, so the work copy carries only what a level is and how to
    implement it. Screening rationales stay in `grid.json`.
    """
    factors = copy.deepcopy(grid.get("factors", []))
    for source in grid.get("reference_factors", []):
        target = next((f for f in factors if f["name"] == source["name"]), None)
        needed = {s["levels"].get(source["name"]) for s in grid.get("reference_specs", [])}
        if target is not None:
            present = {lv["value"] for lv in target["levels"]}
            target["levels"] += [lv for lv in source["levels"] if lv["value"] in needed - present]
    return {
        "result_contract_version": grid.get("result_contract_version"),
        "effect_metric": grid.get("effect_metric"),
        "factors": [
            {"name": f["name"], "field": f.get("field"),
             "levels": [{"value": lv["value"], "how": lv.get("how", ""), "reference_settings": lv.get("reference_settings", {}), "ci_reference_settings":lv.get("ci_reference_settings",{}), **{k:lv.get(k) for k in ("role","effect_group","null_group","estimator","effect_metric")}}
                        for lv in f["levels"]]}
            for f in factors
        ],
        # The executor gets ids and levels only; which spec is the paper's stays out of its view.
        "specs": [{k: v for k, v in s.items() if k not in {"is_paper_level", "role"}} for s in enumerate_specs(grid)],
        "incompatible": grid.get("incompatible", []),
        "grid_size": grid.get("grid_size"),
        "n_specs": len(enumerate_specs(grid)),
        "reporting_contracts": grid.get("reporting_contracts", {}),
        "cap": grid.get("cap"),
    }


def leak_tokens(*values: Any) -> list[str]:
    """Every printed form of a reported value that must not reach the executor.

    The value itself and its absolute value, at the precision it was reported and at one
    to four decimals — the same idea as the Stage 1 blinding scan, applied to the one
    number the executor's script would otherwise be able to aim at.
    """
    out: set[str] = set()
    for v in values:
        f = _as_float(v)
        if f is None:
            continue
        for x in {f, abs(f)}:
            out.add(repr(x))
            out.add(str(x))
            for dp in range(1, 5):
                s = f"{x:.{dp}f}"
                out.add(s)
                out.add(s.lstrip("0") if s.startswith("0.") else s)
    return sorted((t for t in out if len(t) >= 3), key=len, reverse=True)


def scrub_values(obj: Any, tokens: list[str], hits: list[str] | None = None) -> Any:
    """Replace every printed form of a withheld value inside a JSON-ish structure."""
    if isinstance(obj, dict):
        return {k: scrub_values(v, tokens, hits) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub_values(v, tokens, hits) for v in obj]
    if isinstance(obj, str):
        for t in tokens:
            if t in obj:
                if hits is not None:
                    hits.append(t)
                obj = obj.replace(t, "[value withheld]")
        return obj
    return obj


def _load_contracts(paper_id: str, *, blind_first: bool = False) -> list[EstimandContract]:
    stage0 = paths.run_dir(paper_id, 0)
    names = ["blind_contract.json", "contracts.json"] if blind_first else ["contracts.json"]
    for name in names:
        p = stage0 / name
        if p.exists():
            raw = json.loads(p.read_text())
            if isinstance(raw, dict) and "contracts" in raw:  # blind_contract.json shape
                return [EstimandContract.model_validate(c) for c in raw["contracts"]]
            got = artifacts.load(EstimandContract, p)
            return got if isinstance(got, list) else [got]
    raise FileNotFoundError(f"no contracts under {stage0}")


# --- step 4b: verification ------------------------------------------------


def verify_execution(work: Path, grid: dict[str, Any], paper_id: str) -> dict[str, Any]:
    """Deterministic checks on the executor's output, plus a hardcoding audit."""
    work = Path(work)
    out = work / "out"
    specs_path = out / "specs.csv"
    report: dict[str, Any] = {"specs_csv": str(specs_path), "checks": {}, "problems": []}
    from ..generation_access import review as review_generation_access
    report["generation_access"] = review_generation_access(work.parent / "logs/execute.log", work)
    if report["generation_access"]["status"] == "violated":
        report["problems"].append("generation read files outside its supplied work directory")

    if not specs_path.exists():
        report["problems"].append("out/specs.csv does not exist")
        report["ok"] = False
        return report

    from ..execution import external_file_literals
    path_problems = external_file_literals(work)
    if path_problems:
        report["problems"].extend(path_problems)
        report.update(ok=False, acceptance="rejected")
        return report
    rows = read_specs(specs_path, grid)
    try:
        specs = reference_specifications(grid)
        if grid.get("result_contract_version") and grid.get("reporting_contracts") and paper_id:
            bind_independent_recipes(work, grid, specs, paper_id)
    except ValueError as exc:
        report["problems"].append(str(exc))
        report.update(ok=False, acceptance="rejected",
                      reference={"status": "blocked", "reason": str(exc)},
                      output_fingerprint=executor_outputs(work))
        report["checks"]["n_rows"] = len(rows)
        return report
    # The executed count, not the grid size: above the execution cap only a sample runs.
    from ..multiverse_contract import checks as reporting_checks
    report["problems"].extend(reporting_checks(rows,specs))
    expected = len(specs)
    report["checks"]["n_rows"] = len(rows)
    report["checks"]["n_expected"] = expected
    report["checks"]["grid_size"] = grid.get("grid_size")
    report["checks"]["sampled"] = bool(grid.get("sampled"))
    report["checks"]["row_count_matches"] = len(rows) == expected
    if len(rows) != expected:
        report["problems"].append(f"specs.csv has {len(rows)} rows, grid expects {expected}")

    factor_names = [f["name"] for f in grid.get("factors", [])]
    by_spec_id = "_spec_id" in (rows[0] if rows else {})
    report["checks"]["matched_by"] = "spec_id" if by_spec_id else "factor_columns"

    if by_spec_id:
        want = [s["spec_id"] for s in specs]
        got = [r["_spec_id"] for r in rows]
        counts = Counter(got)
        missing = [s for s in want if s not in counts]
        unexpected = sorted(g for g in counts if g not in set(want))
        duplicated = sorted(g for g, c in counts.items() if c > 1)
        report["checks"].update({
            "missing_spec_ids": missing, "unexpected_spec_ids": unexpected,
            "duplicate_spec_ids": duplicated,
            "missing_specs": len(missing), "extra_specs": len(unexpected),
            "duplicate_rows": len(got) - len(set(got)),
        })
        report["checks"]["specs_match_grid"] = not (missing or unexpected or duplicated)
        report["checks"]["factor_columns_present"] = True
        if not report["checks"]["specs_match_grid"]:
            report["problems"].append(
                f"specs.csv spec ids do not match the grid: {len(missing)} missing "
                f"({missing[:5]}), {len(unexpected)} unexpected ({unexpected[:5]}), "
                f"{len(duplicated)} duplicated ({duplicated[:5]})"
            )
    else:
        report["problems"].append("specs.csv has no spec_id column; matched on factor columns")
        missing_cols = [n for n in factor_names if rows and n not in rows[0]]
        report["checks"]["factor_columns_present"] = not missing_cols
        if missing_cols:
            report["problems"].append(f"specs.csv is missing factor columns: {missing_cols}")

        # Row identity, not just row count: an executor that loops over the wrong thing
        # can still produce the right number of rows.
        def key(spec: dict[str, Any]) -> tuple:
            return tuple(sorted((_norm(k), _norm(spec.get(k, ""))) for k in factor_names))

        if factor_names and not missing_cols:
            want_keys = {key(s["levels"]) for s in specs}
            got_keys = [key(r) for r in rows]
            report["checks"]["missing_specs"] = len(want_keys - set(got_keys))
            report["checks"]["extra_specs"] = len(set(got_keys) - want_keys)
            report["checks"]["duplicate_rows"] = len(got_keys) - len(set(got_keys))
            report["checks"]["specs_match_grid"] = (
                set(got_keys) == want_keys and len(got_keys) == len(set(got_keys))
            )
            if not report["checks"]["specs_match_grid"]:
                report["problems"].append(
                    f"specs.csv rows do not match the grid: {report['checks']['missing_specs']} "
                    f"missing, {report['checks']['extra_specs']} unexpected, "
                    f"{report['checks']['duplicate_rows']} duplicated"
                )

    conv = [r for r in rows if r["_converged"]]
    bad = [i for i, r in enumerate(conv) if r["_estimate"] is None]
    report["checks"]["n_converged"] = len(conv)
    report["checks"]["converged_rows_numeric"] = not bad
    if not conv:
        report["problems"].append("no specification converged")
    if bad:
        report["problems"].append(f"{len(bad)} converged rows have a non-numeric estimate")
    report["checks"]["distinct_estimates"] = len({r["_estimate"] for r in conv
                                                  if r["_estimate"] is not None})

    strict = bool(grid.get("result_contract_version"))
    for row in rows:
        for problem in validate_result(row, strict=strict):
            report["problems"].append(f"{row.get('_spec_id')}: {problem}")
        if row.get("_factor_mismatches"):
            report["problems"].append(f"{row.get('_spec_id')}: factor labels disagree with the grid")
        if (strict and row.get("_converged") and grid.get("effect_metric")
                and row.get("effect_metric") != grid["effect_metric"]
                and not any(lv.get("role")=="related_effect" and lv.get("effect_metric")==row.get("effect_metric") for f in grid.get("factors",[]) for lv in f["levels"] if row.get('_factor_levels',row).get(f["name"])==lv["value"])):
            report["problems"].append(f"{row.get('_spec_id')}: effect metric differs from focal contract")

    # A fresh work tree carries declared inputs and source files, never previous
    # results. The authoritative agent output is not changed by verification.
    script = next((out / n for n in ("multiverse.R", "multiverse.py") if (out / n).exists()), None)
    if script is None:
        report["problems"].append("no out/multiverse.R or out/multiverse.py to re-run")
        report["checks"]["rerun_reproduces"] = False
    else:
        try:
            with tempfile.TemporaryDirectory(prefix="reproscope_verify_") as folder:
                fresh = Path(folder)
                from ..execution import copy_inputs
                from ..stage1.replicas import prepare_env, script_command
                copy_inputs(work, fresh)
                environment = prepare_env(out, work.parent / "verification_environment")
                if environment["error"]:
                    raise ValueError(environment["error"])
                cmd = script_command(fresh / "out" / script.name, fresh, environment["interpreter"])
                from ..isolation import command as isolated_command, clean_environment
                cmd, report["verification_isolation"] = isolated_command(cmd, fresh, environment["env"])
                import os
                run_env = clean_environment({**os.environ, **environment["env"]}, fresh)
                proc = subprocess.run(cmd, cwd=fresh, capture_output=True, text=True, timeout=EXECUTOR_TIMEOUT_S, env=run_env)
                (out / "rerun.log").write_text((proc.stdout or "") + "\n[stderr]\n" + (proc.stderr or ""))
                report["checks"]["rerun_exit_code"] = proc.returncode
                generated = fresh / "out" / "specs.csv"
                report["checks"]["regenerated_results"] = generated.exists()
                new = read_specs(generated, grid) if generated.exists() else []
                new_by_id = {r.get("_spec_id"): r for r in new}
                same = len(new) == len(rows) and len(new_by_id) == len(new)
                same = same and all(same_result(row, new_by_id.get(row.get("_spec_id"))) for row in rows)
                report["checks"]["rerun_reproduces"] = bool(proc.returncode == 0 and same and generated.exists())
                if not report["checks"]["rerun_reproduces"]:
                    report["problems"].append("fresh execution did not regenerate every result field")
                if strict and report["checks"]["rerun_reproduces"]:
                    from .. import reference
                    report["reference"] = reference.check(fresh, new, specs)
                    report["problems"].extend(report["reference"]["problems"])
                    from ..multiverse_perturbation import resample_records
                    if not report["reference"]["problems"] and resample_records(fresh, recipes=[s["independent_recipe"] for s in specs] if specs and specs[0].get("independent_recipe") else None):
                        generated.unlink()
                        (fresh / "out/analysis_plan.json").unlink()
                        perturbed = subprocess.run(cmd, cwd=fresh, capture_output=True, text=True, timeout=EXECUTOR_TIMEOUT_S, env=run_env)
                        perturbed_rows = read_specs(generated, grid) if generated.exists() else []
                        perturb_check = reference.check(fresh, perturbed_rows, specs)
                        changed = any(a.get("_estimate") != b.get("_estimate") for a, b in zip(new, perturbed_rows))
                        perturb_ok = (perturbed.returncode == 0 and len(perturbed_rows) == len(new)
                                      and changed and not perturb_check["problems"]
                                      and perturb_check["checked"] == report["reference"]["checked"]
                                      and perturb_check["checked"] > 0)
                        fully_checked = all(r.get('status') == 'verified'
                                            for r in (report['reference'], perturb_check))
                        report["perturbation"] = {"status": ("verified" if fully_checked else "partial") if perturb_ok else "failed",
                                                   "checked": perturb_check['checked'],
                                                   "total": len(new),
                                                   "reference": perturb_check}
                        if not perturb_ok:
                            report["problems"].append("input perturbation did not reproduce independent reference results")
                    else:
                        report["perturbation"] = {"status": "unsupported", "reason": "no validated direct CSV outcome to perturb"}

        except (subprocess.TimeoutExpired, OSError, ValueError, RuntimeError) as exc:
            report["checks"]["rerun_reproduces"] = False
            report["problems"].append(f"fresh re-execution failed: {exc}")

    if strict:
        for component in ("reference", "perturbation"):
            if report.get(component, {}).get("status") != "verified":
                report["problems"].append(f"Complete independent {component} verification is required for acceptance")
    report["audit"] = hardcoding_audit(script, specs_path, paper_id)
    from ..stage1.audit import acceptance
    report["ok"] = not report["problems"]
    report["acceptance"] = acceptance(report["audit"]) if report["ok"] else "rejected"
    report["output_fingerprint"] = executor_outputs(work)
    return report



def executor_outputs(work: Path) -> dict[str, str]:
    out = work / "out"
    return provenance.files({p.name: p for p in out.glob("*") if p.is_file()
                             and (p.suffix.lower() in {".py", ".r"}
                                  or p.name in {"specs.csv", "analysis_plan.json", "requirements.txt", "r_packages.txt"})})

def same_result(a: dict, b: dict | None) -> bool:
    if b is None:
        return False
    contract_fields = {"spec_id", "estimate", "se", "p", "n", "converged", "p_threshold",
                       "effect_metric", "se_metric", "p_raw", "p_adjustment", "p_family", "p_index",
                       "inference_method", "exceedances", "draws", "ci_lower", "ci_upper"}
    keys = contract_fields & (a.keys() | b.keys())
    if (contract_fields & a.keys()) != (contract_fields & b.keys()):
        return False
    if a.get("_factor_mismatches") or b.get("_factor_mismatches"):
        return False
    for key in keys:
        av, bv = a[key], b[key]
        if av == bv:
            continue
        try:
            if not math.isclose(float(av), float(bv), rel_tol=1e-6, abs_tol=1e-12):
                return False
        except (ValueError, TypeError):
            return False
    return True


def hardcoding_audit(script: Path | None, specs_path: Path, paper_id: str) -> dict[str, Any]:
    """Stage 1's audit idea applied to the multiverse script."""
    if script is None or not script.exists():
        return {"verdict": "not_run", "hits": [], "note": "no script to audit"}
    script_text = script.read_text()
    head = "\n".join(Path(specs_path).read_text().splitlines()[:15])
    try:  # Stage 1 owns the canonical implementation.
        from ..stage1.audit import hardcoding_audit as stage1_hardcoding_audit

        out, ledger_id = stage1_hardcoding_audit(
            paper_id, script_text, head, step="stage3_hardcoding_audit", stage="3"
        )
        out["_ledger_id"] = ledger_id
        return out
    except ImportError:
        pass
    prompt = artifacts.load_prompt(
        "stage1_hardcoding_audit", script=script_text[:20000], results=head
    )
    r = llm.call("hardcoding_audit", prompt, paper_id=paper_id, stage="3", tier="cheap")
    try:
        out = json.loads(llm.first_json_object(r.text))
        out["_ledger_id"] = r.ledger_id
        return out
    except Exception:  # noqa: BLE001
        return {"verdict": "unparsed", "hits": [], "raw": (r.text or "")[:2000],
                "error": r.error, "_ledger_id": r.ledger_id}


# --- step 6: interpretation ----------------------------------------------


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


SPECS_CAP = 60000


def interpretation_prompt(specs_text: str, reported: Any, grid: dict[str, Any], *, method_context=None) -> str:
    """Supply deterministic, scale-separated summaries to the narrative reader."""
    import io
    from ..report.findings import sensitivity
    names=[f['name'] for f in grid.get('factors',[])]
    rows=[]
    for r in read_specs_text(specs_text, grid):
        rows.append({**r,'spec':{n:r.get('_factor_levels',r).get(n,'') for n in names},
                     'converged':r['_converged']})
    summary=sensitivity(rows,grid.get('factors',[]))
    for group in summary['groups']:group.pop('rows',None)
    return artifacts.load_prompt('stage3_interpret',specs=specs_text[:SPECS_CAP],
        methods=json.dumps(method_context or {'primary_effect':grid.get('primary_effect')}),
        summary=json.dumps(summary,indent=2), reported=json.dumps(grid.get('curve_reference') or {'value':reported}),
        factors=json.dumps([{'name':f['name'],'levels':[lv['value'] for lv in f['levels']]} for f in grid.get('factors',[])]),
        coverage='a sample of the multiverse' if grid.get('sampled') else 'the whole screened compatible grid')


def parse_interpretation(text: str) -> dict[str, Any]:
    m = _JSON_BLOCK.search(text or "")
    blob = m.group(1) if m else None
    if blob is None:
        try:
            blob = llm.first_json_object(text)
        except Exception:  # noqa: BLE001
            return {}
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return {}


def defensible_csv(path: Path, grid: dict) -> str:
    """Keep reference-only executions out of the interpreter's curve input."""
    import io
    excluded = {s["spec_id"] for s in grid.get("reference_specs", [])}
    reader = csv.DictReader(path.read_text().splitlines())
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=reader.fieldnames or [])
    writer.writeheader()
    writer.writerows(r for r in reader if r.get("spec_id") not in excluded)
    return buf.getvalue()


def reference_specifications(grid: dict) -> list[dict]:
    specs = copy.deepcopy(enumerate_specs(grid))
    for spec in specs:
        required = {}
        ci_required = {}
        for factor in grid.get("factors", []):
            value = spec["levels"].get(factor["name"])
            level = next((lv for lv in factor["levels"] if lv["value"] == value), {})
            for key, setting in level.get("reference_settings", {}).items():
                # Optional schema fields are unknown constraints, not instructions
                # to erase a value supplied by another factor.
                if setting is None:
                    continue
                if key in required and required[key] != setting:
                    raise ValueError(f"conflicting screened reference settings for {spec['spec_id']}: {key}")
                required[key] = setting
            for key,setting in level.get('ci_reference_settings',{}).items():
                if setting is None:continue
                if key in ci_required and ci_required[key]!=setting:
                    raise ValueError(f"conflicting screened interval settings for {spec['spec_id']}: {key}")
                ci_required[key]=setting
        if ci_required:required['ci_settings']=ci_required
        spec["reference_settings"] = required
        spec["reporting_contract"] = grid.get("reporting_contracts", {}).get(spec["spec_id"])
    return specs


def bind_independent_recipes(work, grid, specs, paper_id=None):
    """Use the same source-only reference in generation and final verification."""
    if not grid.get('reporting_contracts'):return
    from ..verification_recipe import prepare, compile_book
    record=prepare(Path(work),grid,paper_id or Path(work).parent.parent.name)
    compiled=compile_book(record['book'],grid)
    for specification in specs:
        specification['independent_recipe']=compiled[specification['spec_id']]
        specification['recipe_record']=record


def generation_checks(work, grid):
    """Feed mechanical contract/method failures back to the generator, never source targets."""
    path=Path(work)/'out/specs.csv'
    if not path.exists():return ['Missing out/specs.csv']
    rows=read_specs(path,grid)
    specs=reference_specifications(grid)
    bind_independent_recipes(work,grid,specs)
    want={s['spec_id'] for s in specs}
    got=[r.get('_spec_id') for r in rows]
    errors=[]
    if set(got)!=want or len(got)!=len(want):errors.append('CSV must cover every grid spec exactly once')
    for row in rows:
        if not row.get('_converged'):
            errors.append(str(row.get('_spec_id'))+': generated calculation failed: '+str(row.get('error') or 'no error reason supplied')[:500])
        errors += [str(row.get('_spec_id'))+': '+e for e in validate_result(row,strict=True)]
        if row.get('_factor_mismatches'):errors.append(str(row.get('_spec_id'))+': factor labels differ from grid; result columns are reserved, so use factor_<name> for colliding factors: '+', '.join(row['_factor_mismatches']))
        for k in ('ci_lower','ci_upper'):
            if row.get(k) not in (None,''):
                try:
                    if not math.isfinite(float(row[k])):raise ValueError()
                except (ValueError,TypeError):errors.append(str(row.get('_spec_id'))+': invalid '+k)
        if bool(row.get('ci_lower'))!=bool(row.get('ci_upper')):errors.append(str(row.get('_spec_id'))+': incomplete interval')
        if row.get('ci_lower') not in (None,'') and row.get('ci_upper') not in (None,''):
            if float(row['ci_lower'])>float(row['ci_upper']):errors.append(str(row.get('_spec_id'))+': reversed interval')
    from ..multiverse_contract import checks as reporting_checks
    errors.extend(reporting_checks(rows,specs))
    if errors:return errors[:40]
    from ..reference import check
    errors=check(Path(work),rows,specs)['problems']
    if errors:return errors[:40]
    return generation_perturbation_checks(Path(work), grid, specs)


def generation_perturbation_checks(work, grid, specs):
    """Repair data-dependent implementation errors inside bounded generation.

    Only a private input copy is changed. Feedback contains contract failures,
    never paper targets or the private replacement data.
    """
    import os
    from .. import reference
    from ..execution import copy_inputs
    from ..stage1.replicas import prepare_env, script_command
    from ..isolation import command, clean_environment
    script=next((work/'out'/n for n in ('multiverse.py','multiverse.R') if (work/'out'/n).exists()),None)
    if script is None:return ['Missing executable multiverse source']
    with tempfile.TemporaryDirectory(prefix='reproscope_generation_check_') as folder:
        fresh=Path(folder)
        copy_inputs(work,fresh)
        # The perturbation constructor reads only declared source-column bindings.
        # copy_inputs deliberately omits generated result and plan files.
        import shutil
        shutil.copy2(work/'out/analysis_plan.json',fresh/'out/analysis_plan.json')
        from ..multiverse_perturbation import resample_records
        recipes=[s['independent_recipe'] for s in specs] if specs and specs[0].get('independent_recipe') else None
        if not resample_records(fresh, recipes=recipes):return []
        (fresh/'out/analysis_plan.json').unlink()
        environment=prepare_env(work/'out',work.parent/'verification_environment')
        if environment['error']:return ['Perturbation environment unavailable: '+environment['error']]
        cmd,_=command(script_command(fresh/'out'/script.name,fresh,environment['interpreter']),fresh,environment['env'])
        try:
            proc=subprocess.run(cmd,cwd=fresh,capture_output=True,text=True,timeout=300,
                env=clean_environment({**os.environ,**environment['env']},fresh))
        except subprocess.TimeoutExpired:return ['Private input perturbation exceeded the execution budget']
        if proc.returncode!=0:return ['Script failed on private perturbed inputs; implement the declared sample and method for changed observations']
        path=fresh/'out/specs.csv'
        if not path.exists():return ['Private input perturbation did not regenerate specs.csv']
        checked=reference.check(fresh,read_specs(path,grid),specs)
        return ['Private input perturbation: '+e for e in checked['problems'][:40]]

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
from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from ..artifacts import ClaimRecord, EstimandContract
from ..focal import QUANTITY_PREFERENCE, _TSTAT_KINDS, _as_float, _norm, bind_focal_claim  # noqa: F401

# Two caps with different jobs. GRID_CAP bounds the design itself: above it, low-priority
# factors are pinned or dropped, so the grid stays a grid a reader can describe. EXEC_CAP
# bounds what is actually run: above it the curve is estimated from a stratified fraction
# of the pruned grid instead of all of it.
GRID_CAP = 256
EXEC_CAP = 64
EXECUTOR_TIMEOUT_S = 2400


# --- structured-output schemas -------------------------------------------


class ProposedLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    how: str = ""


class ProposedFactor(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    source: str | None = None
    field: str | None = None
    levels: list[ProposedLevel] = []
    paper_level: str | None = None


class EnumerateOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    factors: list[ProposedFactor] = []
    notes: str | None = None


class ScreenedLevel(BaseModel):
    model_config = ConfigDict(extra="allow")

    value: str
    verdict: Literal["defensible", "rejected"]
    rationale: str | None = None


class ScreenedFactor(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    levels: list[ScreenedLevel] = []


class Incompatible(BaseModel):
    model_config = ConfigDict(extra="allow")

    a: str
    b: str
    why: str | None = None


class ScreenOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    factors: list[ScreenedFactor] = []
    incompatible: list[Incompatible] = []
    adjustments: list[str] = []
    grid_size_after_screen: int | None = None


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
    """Read the paper's own level for each factor off the best-matching replica.

    The enumerator marks a `paper_level` per factor, but it only ever sees the contract,
    so it guesses whenever the methods leave the choice open. A replica that landed in
    band A on the focal claim reproduced the paper's number, so its script and trace are
    the better evidence for what the paper actually did, and they override the guess.
    Any other band leaves the enumerator's mark standing.
    """
    stage1 = paths.run_dir(paper_id, 1)
    rid, script, why, band = _best_replica(paper_id, focal)
    fallback = {
        pf.get("name", ""): pf.get("paper_level")
        for pf in proposed.get("factors", []) if pf.get("paper_level")
    }
    out: dict[str, Any] = {
        "levels": fallback, "source": "enumerator", "replica_id": rid, "band": band,
        "replica_reason": why, "evidence": {}, "notes": [],
    }
    if band != "A" or script is None:
        out["notes"].append(
            f"no band-A replica on the focal claim ({why}); the enumerator's marks stand"
        )
        return out

    trace_path = stage1 / "replicas" / str(rid) / "trace.json"
    factors = [{"name": pf.get("name"), "levels": [lv.get("value") for lv in pf.get("levels", [])]}
               for pf in proposed.get("factors", [])]
    prompt = artifacts.load_prompt(
        "stage3_paper_level",
        factors=json.dumps(factors, indent=2),
        trace=trace_path.read_text()[:12000] if trace_path.exists() else "(no trace)",
        script=script.read_text()[:20000],
    )
    r = llm.call("paper_level", prompt, paper_id=paper_id, stage="3",
                 tier="cheap", schema=PaperLevelsOut)
    if not r.ok or r.parsed is None:
        out["notes"].append(f"reading the replica's levels failed ({r.error}); "
                            "the enumerator's marks stand")
        return out

    # Map the model's answers back onto the enumerator's exact factor and level strings.
    by_factor = {_norm(pf.get("name", "")): pf for pf in proposed.get("factors", [])}
    levels = dict(fallback)
    for item in r.parsed.levels:
        pf = by_factor.get(_norm(item.factor))
        if pf is None or item.level is None:
            continue
        canonical = next((lv.get("value") for lv in pf.get("levels", [])
                          if _norm(lv.get("value", "")) == _norm(item.level)), None)
        if canonical is None:
            out["notes"].append(
                f"{pf.get('name')}: replica level {item.level!r} matches no enumerated level"
            )
            continue
        name = pf.get("name", "")
        if fallback.get(name) and _norm(fallback[name]) != _norm(canonical):
            out["notes"].append(
                f"{name}: the enumerator guessed {fallback[name]!r}; replica {rid} "
                f"(band A) shows {canonical!r}"
            )
        levels[name] = canonical
        out["evidence"][name] = item.evidence
    out["levels"] = levels
    out["source"] = f"replica {rid} (band A)"
    out["_ledger_id"] = r.ledger_id
    return out


# --- step 3b: deterministic grid build ------------------------------------


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
    """Turn the enumerator's factors plus the screen's verdicts into the executor's GRID.json.

    Levels the screen rejected are dropped, with one exception: the paper's own level
    always stays in the grid, carrying the verdict `paper` and the screen's rationale, so
    the reported estimate has a place on the curve even when the screen calls it
    indefensible. Those cases are listed in `paper_level_flagged`.

    Factors left with no level disappear; a factor left with one level stays (it
    constrains the analysis but does not multiply the grid). Incompatible pairs are
    counted out exactly. If the surviving grid is still larger than `cap`, multi-level
    factors are dropped from the end of the enumerator's list, which is where it was
    asked to put the choices least likely to move the estimate.

    A grid still larger than `exec_cap` after that is executed as a stratified fraction:
    `grid_size` stays the full count, `n_specs` says how many specifications run, and
    `sampled_spec_ids` names them.

    `paper_levels` maps factor name to the level the paper itself used, read off the
    best-matching replica; it overrides the enumerator's own `paper_level` mark.
    """
    verdicts = _verdicts(screen)
    notes: list[str] = []
    factors: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    flagged: list[dict[str, str]] = []
    paper_levels = paper_levels or {}

    for pf in proposed.get("factors", []):
        name = pf.get("name", "")
        paper_level = paper_levels.get(name, pf.get("paper_level"))
        levels: list[dict[str, Any]] = []
        for lv in pf.get("levels", []):
            value = lv.get("value", "")
            is_paper = bool(paper_level) and _norm(paper_level) == _norm(value)
            sv = verdicts.get((_norm(name), _norm(value)))
            if sv is None:
                notes.append(f"{name}={value}: not returned by the screen; kept by default")
                levels.append({"value": value, "how": lv.get("how", ""),
                               "verdict": "paper" if is_paper else "defensible",
                               "rationale": "not screened"})
            elif sv.verdict == "rejected" and is_paper:
                # Never drop the paper's own choice: the curve must have room for the
                # estimate the paper reported, labelled for what the screen thinks of it.
                flagged.append({"factor": name, "level": value,
                                "rationale": sv.rationale or ""})
                notes.append(f"factor {name!r}: the screen rejected the paper's own level "
                             f"{value!r}; kept in the grid with verdict 'paper'")
                levels.append({"value": value, "how": lv.get("how", ""),
                               "verdict": "paper", "rationale": sv.rationale or "",
                               "screen_verdict": "rejected"})
            elif sv.verdict == "rejected":
                rejected.append({"factor": name, "level": value, "rationale": sv.rationale or ""})
            else:
                levels.append({"value": value, "how": lv.get("how", ""),
                               "verdict": "paper" if is_paper else "defensible",
                               "rationale": sv.rationale or ""})
        if not levels:
            notes.append(f"factor {name!r} dropped: every level was rejected")
            continue
        paper_kept = any(_norm(paper_level) == _norm(lv["value"]) for lv in levels)
        if paper_level and not paper_kept:
            notes.append(f"factor {name!r}: the paper's level {paper_level!r} matches none of "
                         "the enumerated levels")
        factors.append({
            "name": name,
            "field": pf.get("field"),
            "source": pf.get("source"),
            "paper_level": paper_level if paper_kept else None,
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

    incompatible: list[dict[str, Any]] = []
    for inc in screen.get("incompatible", []):
        a, b = inc.get("a", ""), inc.get("b", "")
        if resolves(a) and resolves(b):
            incompatible.append({"a": a, "b": b, "why": inc.get("why")})
        else:
            notes.append(f"incompatibility {a!r} x {b!r} ignored: it does not resolve to two "
                         "surviving levels")

    dropped: list[str] = []
    while True:
        size = _grid_size(factors, incompatible)
        if size <= cap:
            break
        multi = [i for i, f in enumerate(factors) if len(f["levels"]) > 1]
        if not multi:
            break
        i = multi[-1]  # lowest priority: last in the enumerator's list
        f = factors[i]
        dropped.append(f["name"])
        # Pin the factor to the paper's level rather than removing it, so the paper's own
        # specification stays reachable and the executor still implements the choice.
        keep = next((lv for lv in f["levels"] if _norm(lv["value"]) == _norm(f["paper_level"])),
                    None) if f.get("paper_level") else None
        if keep is not None:
            notes.append(
                f"factor {f['name']!r} pinned to the paper's level {keep['value']!r} to bring "
                f"the grid under the cap of {cap} (was {size} specifications)"
            )
            f["levels"] = [keep]
        else:
            notes.append(
                f"factor {f['name']!r} dropped to bring the grid under the cap of {cap} "
                f"(was {size} specifications); it has no paper level to pin to"
            )
            factors.pop(i)
        by_name = {_norm(f2["name"]): f2 for f2 in factors}
        incompatible = [inc for inc in incompatible if resolves(inc["a"]) and resolves(inc["b"])]

    grid = {
        "factors": factors,
        "incompatible": incompatible,
        "rejected_levels": rejected,
        "paper_level_flagged": flagged,
        "grid_size": _grid_size(factors, incompatible),
        "full_factorial": math.prod(len(f["levels"]) for f in factors) if factors else 0,
        "dropped_factors": dropped,
        "cap": cap,
        "adjustments": screen.get("adjustments", []),
        "notes": notes,
    }
    apply_exec_cap(grid, paper_id=paper_id, exec_cap=exec_cap)
    return grid


def apply_exec_cap(
    grid: dict[str, Any], *, paper_id: str | None, exec_cap: int | None
) -> dict[str, Any]:
    """Decide which specifications of the grid are executed, and record the decision.

    `grid_size` keeps the full count of the pruned grid. `n_specs` is what runs,
    `sampled` says whether that is a fraction, and `sample_fraction` how large a one.
    """
    specs = enumerate_specs(grid)
    grid["exec_cap"] = exec_cap
    grid["n_specs"] = len(specs)
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
    if full > 200_000:  # too big to enumerate; the cap loop will shrink it first
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
    return out


# --- step 5: rank ---------------------------------------------------------


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name).lower()).strip("_")


RESULT_COLUMNS = ("spec_id", "estimate", "se", "p", "n", "converged", "error")


def read_specs(path: Path, grid: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Rows of specs.csv, carrying one column per factor with the grid's exact level string.

    The executor is asked for a `spec_id` column and the levels are joined back from
    `enumerate_specs(grid)`, so a row's levels are the grid's own strings whatever the
    executor wrote next to them. A row whose id is not in the grid keeps its own columns
    and is left for `verify_execution` to report.

    Without a `spec_id` column the factor columns themselves are matched, allowing for
    the normalised names (snake_case, punctuation dropped) an executor tends to write.
    """
    rows = list(csv.DictReader(io.StringIO(Path(path).read_text())))
    if grid is None:
        grid_path = Path(path).parents[2] / "grid.json"
        grid = json.loads(grid_path.read_text()) if grid_path.exists() else None

    if rows and "spec_id" in rows[0]:
        by_id = {s["spec_id"]: s["levels"] for s in enumerate_specs(grid or {})}
        for r in rows:
            sid = (r.get("spec_id") or "").strip()
            r["_spec_id"] = sid
            levels = by_id.get(sid)
            if levels:
                r.update(levels)
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
        n = _as_float(r.get("n"))
        r["_n"] = int(n) if n is not None else None
    return rows


def rank_reported(
    rows: list[dict[str, Any]],
    reported: float | None,
    grid: dict[str, Any] | None = None,
    *,
    precision: int | None = None,
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
    ok = [r for r in rows if r["_converged"] and r["_estimate"] is not None]
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
        out["extremeness"] = round(min(below, above) / n, 6)
        sign = (reported > 0) - (reported < 0)
        out["share_same_sign"] = round(
            sum(1 for e in est if ((e > 0) - (e < 0)) == sign) / n, 6
        )
        closest = min(ok, key=lambda r: abs(r["_estimate"] - reported))
        out["closest_spec"] = {
            "estimate": closest["_estimate"],
            "abs_diff": round(abs(closest["_estimate"] - reported), 6),
            "spec": _spec_of(closest, grid),
        }
    with_p = [r for r in ok if r["_p"] is not None]
    out["n_with_p"] = len(with_p)
    if with_p:
        out["share_p05"] = round(sum(1 for r in with_p if r["_p"] < 0.05) / len(with_p), 6)

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
                 if all(_norm(r.get(k, "")) == _norm(v) for k, v in paper.items())), None
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
    return {k: row[k] for k in names if k in row}


# --- work-directory assembly ---------------------------------------------


def _best_replica(
    paper_id: str, focal: dict[str, Any]
) -> tuple[str | None, Path | None, str, str | None]:
    """The replica whose script Stage 3 builds on.

    Returns (replica_id, script path, why, band on the focal claim). The band is None
    when no match row picked the replica; only a band-A replica is trusted to say what
    the paper itself did.
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

    order = {"A": 0, "B": 1, "C": 2, "fail": 3}
    match_path = stage1 / "match.json"
    if match_path.exists():
        claim_ids = set(focal.get("claim_ids", []))
        focal_id = focal["focal_quantity"]["claim_id"]
        rows = _read_json(match_path).get("rows", [])
        cands = [r for r in rows if r.get("claim_id") == focal_id] \
            or [r for r in rows if r.get("claim_id") in claim_ids]
        def closeness(r: dict[str, Any]) -> tuple[int, float, float]:
            sd, rd = _as_float(r.get("std_diff")), _as_float(r.get("raw_diff"))
            return (order.get(r.get("band"), 4),
                    9e9 if sd is None else abs(sd),
                    9e9 if rd is None else abs(rd))

        cands.sort(key=closeness)
        for r in cands:
            s = script_of(r.get("replica_id", ""))
            if s:
                return (r["replica_id"], s,
                        f"best match on {focal_id} (band {r.get('band')})", r.get("band"))

    for p in reps:
        trace = p / "trace.json"
        if trace.exists() and not _read_json(trace).get("ran", False):
            continue
        s = script_of(p.name)
        if s:
            return p.name, s, "fallback: first replica that ran with a script", None
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

    (work / "out").mkdir(parents=True, exist_ok=True)
    base_name = "BASE_ANALYSIS" + script.suffix
    shutil.copy2(script, work / base_name)
    _write_json(work / "GRID.json", scrub_values(executor_grid(grid), tokens, scan_hits))

    data_dir = work / "data"
    data_dir.mkdir(exist_ok=True)
    copied = []
    for rel in list(manifest.data_files) + ([manifest.codebook] if manifest.codebook else []):
        src = manifest.path(rel)
        if src.exists():
            shutil.copy2(src, data_dir / Path(rel).name)
            copied.append(f"data/{Path(rel).name}")

    contracts = _load_contracts(paper_id, blind_first=True)
    focal_contract = next(
        (c for c in contracts if c.analysis_id == focal["analysis_id"]),
        contracts[0] if contracts else None,
    )
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
    return {
        "factors": [
            {"name": f["name"], "field": f.get("field"),
             "levels": [{"value": lv["value"], "how": lv.get("how", "")} for lv in f["levels"]]}
            for f in grid.get("factors", [])
        ],
        # The executor gets ids and levels only; which spec is the paper's stays out of its view.
        "specs": [{k: v for k, v in s.items() if k != "is_paper_level"} for s in enumerate_specs(grid)],
        "incompatible": grid.get("incompatible", []),
        "grid_size": grid.get("grid_size"),
        "n_specs": grid.get("n_specs"),
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

    if not specs_path.exists():
        report["problems"].append("out/specs.csv does not exist")
        report["ok"] = False
        return report

    rows = read_specs(specs_path, grid)
    specs = enumerate_specs(grid)
    # The executed count, not the grid size: above the execution cap only a sample runs.
    expected = grid.get("n_specs", len(specs))
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
    if bad:
        report["problems"].append(f"{len(bad)} converged rows have a non-numeric estimate")
    report["checks"]["distinct_estimates"] = len({r["_estimate"] for r in conv
                                                  if r["_estimate"] is not None})

    # Re-run the executor's own script once and compare.
    script = next((out / n for n in ("multiverse.R", "multiverse.py") if (out / n).exists()), None)
    if script is None:
        report["problems"].append("no out/multiverse.R or out/multiverse.py to re-run")
        report["checks"]["rerun_reproduces"] = False
    else:
        kept = specs_path.with_name("specs_agent.csv")
        shutil.copy2(specs_path, kept)
        cmd = ["Rscript", str(script.relative_to(work))] if script.suffix == ".R" \
            else ["python3", str(script.relative_to(work))]
        try:
            proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=1800)
            (out / "rerun.log").write_text((proc.stdout or "") + "\n[stderr]\n" + (proc.stderr or ""))
            report["checks"]["rerun_exit_code"] = proc.returncode
            new = read_specs(specs_path, grid) if specs_path.exists() else []
            old = read_specs(kept, grid)
            if by_spec_id:
                # Pair the two runs by spec id: a script that reorders its rows still
                # reproduces the same specifications.
                new_by_id = {r["_spec_id"]: r for r in new}
                pairs = [(a, new_by_id.get(a["_spec_id"])) for a in old]
                same = len(new) == len(old) and all(b is not None for _, b in pairs)
            else:
                pairs = list(zip(old, new))
                same = len(new) == len(old)
            same = same and all(
                (a["_estimate"] is None and b["_estimate"] is None)
                or (a["_estimate"] is not None and b["_estimate"] is not None
                    and abs(a["_estimate"] - b["_estimate"]) < 1e-6)
                for a, b in pairs if b is not None
            )
            report["checks"]["rerun_reproduces"] = bool(proc.returncode == 0 and same)
            if not report["checks"]["rerun_reproduces"]:
                report["problems"].append(
                    "re-running the executor's script did not reproduce specs.csv"
                )
            rows = new or old
        except subprocess.TimeoutExpired:
            report["checks"]["rerun_reproduces"] = False
            report["problems"].append("re-run of the executor's script timed out")

    report["audit"] = hardcoding_audit(script, specs_path, paper_id)
    report["ok"] = not report["problems"]
    return report


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

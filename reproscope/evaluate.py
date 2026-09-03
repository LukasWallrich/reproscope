"""Pilot evaluation: aggregate Stage 1 replica outcomes across papers.

    .venv/bin/python -m reproscope.evaluate [--papers id ...] [--include-fixtures]

Reads what the pipeline already wrote — `stage1/replicas/*/trace.json`,
`stage1/match.json`, `stage1/targeted.json`, `stage3/focal.json`, `ledger.jsonl`,
the corpus manifest — and writes `docs/evaluation/pilot_eval.json` (raw per-replica
rows, so every printed number can be re-derived) and `pilot_eval.md` (tables), then
prints the markdown.

The comparison the pilot is built around: replica families on subscription routes
(opus, fable, sol) against cheap OpenRouter families (glm, deepseek), on identical
blind directories.

Reading never creates directories: paths are built from `paths.ROOT` directly rather
than through `paths.run_dir`, which makes them.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, paths
from . import focal as focal_mod

BANDS = ("A", "B", "C", "fail", "not_found")
SEVERITIES = ("minor", "major", "critical", "unrated")
VERDICTS = ("clean", "suspicious", "hardcoded", "not_run")
TIER_ORDER = ("frontier", "cheap", "unknown")
NA = "n/a"


# --- small helpers --------------------------------------------------------


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def family_of(replica_id: str, trace_family: str | None = None) -> str:
    """Family = the trace's own label, else the replica_id prefix before the last _<n>."""
    if trace_family:
        return trace_family
    m = re.fullmatch(r"(.+)_\d+", replica_id)
    return m.group(1) if m else replica_id


def tier_of(family: str, route: str | None = None) -> str:
    """frontier = subscription routes (claude_p, codex); cheap = opencode.

    models.toml is the authority; a family absent from it falls back to the route
    recorded in its own trace.
    """
    spec = config.replicas().get(family)
    r = spec.route if spec else route
    if r in config.SUBSCRIPTION_ROUTES:
        return "frontier"
    if r == "opencode":
        return "cheap"
    return "unknown"


# --- loading one paper ----------------------------------------------------


def _runs_root() -> Path:
    return paths.ROOT / "runs"


def paper_ids(include_fixtures: bool = False) -> list[str]:
    root = _runs_root()
    if not root.is_dir():
        return []
    def is_run(d: Path) -> bool:
        # a run directory holds a ledger or at least one stage directory; runs/logs
        # holds neither (its stage*.log files are files, not directories)
        return (d / "ledger.jsonl").exists() or any(p.is_dir() for p in d.glob("stage*"))

    return sorted(
        d.name
        for d in root.iterdir()
        if d.is_dir() and is_run(d) and (include_fixtures or not d.name.startswith("_"))
    )


def _ledger_by_replica(rows: list[dict]) -> dict[str, dict[str, float | None]]:
    """Sum the step == 'replica' ledger rows per replica_id (a retry adds a row)."""
    fields = ("tokens_in", "tokens_out", "tokens_reasoning", "cost_usd", "cost_usd_equiv",
              "duration_s")
    out: dict[str, dict[str, float | None]] = {}
    for r in rows:
        if r.get("step") != "replica":
            continue
        rid = r.get("replica_id") or (r.get("extra") or {}).get("replica_id")
        if not rid:
            continue
        acc = out.setdefault(rid, {f: None for f in fields} | {"calls": 0})
        acc["calls"] = (acc["calls"] or 0) + 1
        for f in fields:
            v = _as_float(r.get(f))
            if v is not None:
                acc[f] = (acc[f] or 0.0) + v
    return out


def _stage_costs(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Per-stage pipeline spend, split into metered API cost and subscription list price."""
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        stage = str(r.get("stage") or "?")
        acc = out.setdefault(stage, {"calls": 0, "cost_usd": 0.0, "cost_usd_equiv": 0.0})
        acc["calls"] += 1
        acc["cost_usd"] += _as_float(r.get("cost_usd")) or 0.0
        acc["cost_usd_equiv"] += _as_float(r.get("cost_usd_equiv")) or 0.0
    return out


def _focal(paper_id: str, stage0: Path, stage3: Path) -> tuple[dict | None, str | None]:
    """Focal claim binding: stage3/focal.json when the stage has run, else bind offline."""
    cached = _read_json(stage3 / "focal.json")
    if cached and cached.get("focal_quantity"):
        return cached, "stage3/focal.json"
    try:
        from . import artifacts

        man = paths.manifest(paper_id)
        claims = [artifacts.ClaimRecord.model_validate(c)
                  for c in (_read_json(stage0 / "claims.json") or [])]
        contracts = [artifacts.EstimandContract.model_validate(c)
                     for c in (_read_json(stage0 / "contracts.json") or [])]
        return focal_mod.bind_focal_claim(
            man, claims, contracts, paper_id=paper_id, allow_llm=False
        ), "bound offline from the manifest focal claim"
    except Exception:  # no manifest, no claims, or nothing matched numerically
        return None, None


def load_paper(paper_id: str) -> dict[str, Any]:
    """Everything the aggregation needs for one paper, as plain dicts."""
    run = _runs_root() / paper_id
    stage0, stage1, stage3 = run / "stage0", run / "stage1", run / "stage3"

    ledger_rows: list[dict] = []
    lp = run / "ledger.jsonl"
    if lp.exists():
        ledger_rows = [json.loads(ln) for ln in lp.read_text().splitlines() if ln.strip()]
    per_replica_cost = _ledger_by_replica(ledger_rows)

    replicas: list[dict[str, Any]] = []
    rep_root = stage1 / "replicas"
    if rep_root.is_dir():
        for d in sorted(p for p in rep_root.iterdir() if p.is_dir()):
            trace = _read_json(d / "trace.json")
            rid = (trace or {}).get("replica_id") or d.name
            checks = (trace or {}).get("run_checks") or {}
            hits = checks.get("blind_transcript_hits")
            audit = (trace or {}).get("hardcoding_audit") or {}
            replicas.append({
                "replica_id": rid,
                "family": family_of(rid, (trace or {}).get("family")),
                "route": (trace or {}).get("route"),
                "model": (trace or {}).get("model"),
                "has_trace": trace is not None,
                "ran": bool((trace or {}).get("ran")) if trace else None,
                "exit_code": checks.get("exit_code"),
                "fixes": (trace or {}).get("fixes") or [],
                "hardcoding_verdict": audit.get("verdict"),
                "blind_hits": len(hits) if isinstance(hits, list) else _as_float(hits),
                **{k: v for k, v in (per_replica_cost.get(rid) or {}).items()},
            })

    match = _read_json(stage1 / "match.json") or {}
    claims = _read_json(stage0 / "claims.json") or []
    importance = {
        c.get("claim_id"): c.get("importance")
        for c in claims if isinstance(c, dict)
    }
    for s in match.get("summaries", []):
        if s.get("importance"):
            importance[s["claim_id"]] = s["importance"]

    focal, focal_source = _focal(paper_id, stage0, stage3)
    man_path = paths.corpus_dir(paper_id) / "manifest.json"
    man = _read_json(man_path) or {}

    return {
        "paper_id": paper_id,
        "replicas": replicas,
        "match_rows": match.get("rows", []),
        "summaries": match.get("summaries", []),
        "importance": importance,
        "focal": focal,
        "focal_source": focal_source,
        "targeted": _read_json(stage1 / "targeted.json"),
        "multi100": man.get("multi100"),
        "focal_claim": man.get("focal_claim"),
        "stage_costs": _stage_costs(ledger_rows),
        "n_ledger_rows": len(ledger_rows),
    }


# --- aggregation ----------------------------------------------------------


def _band_of(row: dict) -> str:
    """A row whose replica could not bind the claim is 'not found', not a failed match."""
    if row.get("replicated") is None:
        return "not_found"
    band = row.get("band")
    return band if band in BANDS else "not_found"


def _subset_stats(rows: list[dict]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "n_found": None, "share_found": None, "bands": dict.fromkeys(BANDS, 0),
                "share_a": None, "share_ab": None}
    counts = Counter(_band_of(r) for r in rows)
    n = len(rows)
    found = n - counts["not_found"]
    return {
        "n": n,
        "n_found": found,
        "share_found": found / n,
        "bands": {b: counts[b] for b in BANDS},
        "share_a": counts["A"] / n,
        "share_ab": (counts["A"] + counts["B"]) / n,
    }


def _group_row(label: str, paper_slices: list[tuple[dict, list[dict]]]) -> dict[str, Any]:
    """One family or tier row: run counts, match shares, fixes, audits, blinding, cost."""
    reps = [r for _, rs in paper_slices for r in rs]
    ran_ids_by_paper = [
        (paper, {r["replica_id"] for r in rs if r.get("ran")}) for paper, rs in paper_slices
    ]

    # match statistics pool the rows of every replica that ran, across papers
    pooled_rows: list[dict] = []
    headline_rows: list[dict] = []
    focal_rows: list[dict] = []
    for paper, ids in ran_ids_by_paper:
        if not ids:
            continue
        sel = [r for r in paper["match_rows"] if r.get("replica_id") in ids]
        pooled_rows += sel
        headline_rows += [r for r in sel
                          if paper["importance"].get(r.get("claim_id")) == "headline"]
        fids = set((paper.get("focal") or {}).get("claim_ids") or [])
        focal_rows += [r for r in sel if r.get("claim_id") in fids]

    fixes = Counter()
    n_fixes = 0
    for r in reps:
        for f in r["fixes"]:
            n_fixes += 1
            fixes[f.get("severity") or "unrated"] += 1

    verdicts = Counter()
    for r in reps:
        v = r.get("hardcoding_verdict")
        verdicts[v if v in VERDICTS else "not_run"] += 1

    hits = [r["blind_hits"] for r in reps if r.get("blind_hits") is not None]

    def total(field: str) -> float | None:
        vals = [r[field] for r in reps if r.get(field) is not None]
        return sum(vals) if vals else None

    return {
        "label": label,
        "launched": len(reps),
        "ran": sum(1 for r in reps if r.get("ran")),
        "failed": sum(1 for r in reps if r.get("has_trace") and not r.get("ran")),
        "no_trace": sum(1 for r in reps if not r.get("has_trace")),
        "match": {
            "all": _subset_stats(pooled_rows),
            "headline": _subset_stats(headline_rows),
            "focal": _subset_stats(focal_rows),
        },
        "fixes": {"total": n_fixes, **{s: fixes[s] for s in SEVERITIES}},
        "hardcoding": {v: verdicts[v] for v in VERDICTS},
        "blind_hits": {"total": sum(hits) if hits else None, "reporting": len(hits),
                       "replicas": len(reps)},
        "cost": {
            "tokens_in": total("tokens_in"),
            "tokens_out": total("tokens_out"),
            "cost_usd": total("cost_usd"),
            "cost_usd_equiv": total("cost_usd_equiv"),
            "duration_s": total("duration_s"),
            "duration_mean_s": (total("duration_s") / max(1, sum(
                1 for r in reps if r.get("duration_s") is not None)))
            if total("duration_s") is not None else None,
        },
    }


def _focal_values(paper: dict) -> tuple[dict[str, float], str | None]:
    """Replicated value of the focal claim per replica, on the scale the claim was reported.

    `focal_quantity.reported_value` may have been converted to d; the replicas' values
    stay on the claim's own scale, which the returned label names.
    """
    fq = (paper.get("focal") or {}).get("focal_quantity") or {}
    cid = fq.get("claim_id")
    if not cid:
        return {}, None
    out: dict[str, float] = {}
    scale = None
    for r in paper["match_rows"]:
        if r.get("claim_id") == cid and r.get("replicated") is not None:
            out[r["replica_id"]] = float(r["replicated"])
            scale = r.get("quantity_kind") or scale
    return out, scale


def _focal_dispersion(paper: dict) -> dict[str, Any]:
    """Spread of the focal value within each family (≥2 runs) against the spread between."""
    values, scale = _focal_values(paper)
    by_family: dict[str, list[float]] = defaultdict(list)
    fam_of = {r["replica_id"]: r["family"] for r in paper["replicas"]}
    for rid, v in values.items():
        by_family[fam_of.get(rid, family_of(rid))].append(v)

    within = {}
    for fam, vals in sorted(by_family.items()):
        if len(vals) >= 2:
            within[fam] = {"n": len(vals), "values": sorted(vals),
                           "max_abs_diff": max(vals) - min(vals)}
    means = {f: _mean(v) for f, v in by_family.items() if v}
    between = (max(means.values()) - min(means.values())) if len(means) >= 2 else None
    return {"values": values, "scale": scale, "family_means": means, "within_family": within,
            "between_family_range": between}


def _focal_d(paper: dict) -> dict[str, Any]:
    """Focal effect size on the d scale, for the Multi100 comparison."""
    focal_ids = set((paper.get("focal") or {}).get("claim_ids") or [])
    d_rows = [r for r in paper["match_rows"]
              if r.get("claim_id") in focal_ids and r.get("quantity_kind") == "d"]
    if d_rows:
        reported = next((_as_float(r.get("reported")) for r in d_rows
                         if r.get("reported") is not None), None)
        return {
            "source": "reported d claim",
            "note": None,
            "reported": reported,
            "replicas": {r["replica_id"]: _as_float(r.get("replicated")) for r in d_rows
                         if r.get("replicated") is not None},
        }

    fq = (paper.get("focal") or {}).get("focal_quantity") or {}
    df = _as_float(((paper.get("focal_claim") or {}).get("reported") or {}).get("df"))
    t_rows = [r for r in paper["match_rows"]
              if r.get("claim_id") == fq.get("claim_id") and r.get("quantity_kind") == "t"]
    if not (df and df > 0 and t_rows):
        # No replica rows yet: the paper's own d is still worth showing next to Multi100
        on_d = fq.get("kind") == "d"
        return {
            "source": "focal quantity, no replica rows yet" if on_d else None,
            "note": (f"converted with d = 2t/sqrt(df) from the reported "
                     f"{fq.get('derived_from')}; assumes two independent groups of equal size"
                     if on_d and fq.get("derived_from") else None),
            "reported": _as_float(fq.get("reported_value")) if on_d else None,
            "replicas": {},
        }

    def conv(t: float | None) -> float | None:
        return 2 * t / math.sqrt(df) if t is not None else None

    return {
        "source": "converted from t",
        "note": (f"d = 2t/sqrt(df) with df = {df:g}; assumes two independent groups of "
                 f"equal size"),
        "reported": conv(next((_as_float(r.get("reported")) for r in t_rows), None)),
        "replicas": {r["replica_id"]: conv(_as_float(r.get("replicated"))) for r in t_rows
                     if r.get("replicated") is not None},
    }


def evaluate(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate loaded paper records into family, tier, per-paper and per-replica views."""
    # tier is derived here, not at load, so a synthetic record only needs family + route
    for paper in papers:
        focal_ids = set((paper.get("focal") or {}).get("claim_ids") or [])
        focal_values, _ = _focal_values(paper)
        for r in paper["replicas"]:
            r["tier"] = tier_of(r["family"], r.get("route"))
            # per-replica match counts, so every pooled share in the tables re-derives
            own = [row for row in paper["match_rows"]
                   if row.get("replica_id") == r["replica_id"]] if r.get("ran") else []
            r["match"] = {
                "all": _subset_stats(own),
                "headline": _subset_stats(
                    [row for row in own
                     if paper["importance"].get(row.get("claim_id")) == "headline"]),
                "focal": _subset_stats([row for row in own
                                        if row.get("claim_id") in focal_ids]),
            }
            r["focal_value"] = focal_values.get(r["replica_id"])

    by_family: dict[str, list[tuple[dict, list[dict]]]] = defaultdict(list)
    by_tier: dict[str, list[tuple[dict, list[dict]]]] = defaultdict(list)
    for paper in papers:
        fams: dict[str, list[dict]] = defaultdict(list)
        tiers: dict[str, list[dict]] = defaultdict(list)
        for r in paper["replicas"]:
            fams[r["family"]].append(r)
            tiers[r["tier"]].append(r)
        for f, rs in fams.items():
            by_family[f].append((paper, rs))
        for t, rs in tiers.items():
            by_tier[t].append((paper, rs))

    families = [_group_row(f, sl) for f, sl in sorted(by_family.items())]
    tiers = [_group_row(t, by_tier[t]) for t in TIER_ORDER if t in by_tier]

    paper_blocks = []
    for paper in papers:
        fams: dict[str, list[dict]] = defaultdict(list)
        for r in paper["replicas"]:
            fams[r["family"]].append(r)
        agreements = [_as_float((s.get("dispersion") or {}).get("decision_agreement"))
                      for s in paper["summaries"]]
        cvs = [_as_float((s.get("dispersion") or {}).get("numeric_cv"))
               for s in paper["summaries"]]
        paper_blocks.append({
            "paper_id": paper["paper_id"],
            "n_claims_scored": len({r.get("claim_id") for r in paper["match_rows"]}) or None,
            "families": [_group_row(f, [(paper, rs)]) for f, rs in sorted(fams.items())],
            "decision_agreement_mean": _mean([a for a in agreements if a is not None]),
            "numeric_cv_median": _median([c for c in cvs if c is not None]),
            "focal": {
                "source": paper.get("focal_source"),
                "quantity": (paper.get("focal") or {}).get("focal_quantity"),
                "claim_ids": (paper.get("focal") or {}).get("claim_ids") or [],
                **_focal_dispersion(paper),
            },
            "focal_d": _focal_d(paper),
            "multi100": paper.get("multi100"),
            "targeted": paper.get("targeted"),
            "stage_costs": paper["stage_costs"],
            "replicas": paper["replicas"],
        })

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "papers": [p["paper_id"] for p in papers],
        "families": families,
        "tiers": tiers,
        "per_paper": paper_blocks,
    }


# --- rendering ------------------------------------------------------------


def _f(value: Any, nd: int = 2) -> str:
    v = _as_float(value)
    return NA if v is None else f"{v:,.{nd}f}"


def _pct(value: Any) -> str:
    v = _as_float(value)
    return NA if v is None else f"{100 * v:.0f}%"


def _int(value: Any) -> str:
    v = _as_float(value)
    return NA if v is None else f"{int(round(v)):,d}"


def _table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |",
             "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


def _runs_cells(g: dict) -> list[str]:
    m = g["match"]
    return [
        g["label"], str(g["launched"]), str(g["ran"]), str(g["failed"]), str(g["no_trace"]),
        _int(m["all"]["n"]) if m["all"]["n"] else NA,
        _pct(m["all"]["share_found"]), _pct(m["all"]["share_a"]), _pct(m["all"]["share_ab"]),
        _pct(m["headline"]["share_ab"]), _pct(m["focal"]["share_ab"]),
    ]


def _bands_cells(g: dict) -> list[str]:
    b = g["match"]["all"]["bands"]
    n = g["match"]["all"]["n"]
    if not n:
        return [g["label"]] + [NA] * 5
    return [g["label"]] + [str(b[k]) for k in BANDS]


def _process_cells(g: dict) -> list[str]:
    fx, hc, bh = g["fixes"], g["hardcoding"], g["blind_hits"]
    hits = NA if bh["total"] is None else f"{int(bh['total'])} ({bh['reporting']}/{bh['replicas']})"
    # with no trace in the group there is no fix list to count, which is not zero fixes
    fix_cells = ([NA] * 5 if g["launched"] == g["no_trace"]
                 else [str(fx["total"]), str(fx["minor"]), str(fx["major"]),
                       str(fx["critical"]), str(fx["unrated"])])
    return [g["label"], *fix_cells,
            str(hc["clean"]), str(hc["suspicious"]), str(hc["hardcoded"]), str(hc["not_run"]),
            hits]


def _cost_cells(g: dict) -> list[str]:
    c = g["cost"]
    return [g["label"], _int(c["tokens_in"]), _int(c["tokens_out"]),
            _f(c["cost_usd"], 4), _f(c["cost_usd_equiv"], 4), _f(c["duration_mean_s"], 0)]


def render_md(result: dict[str, Any]) -> str:
    out: list[str] = []
    out.append("# reproscope v0 pilot — replica evaluation")
    out.append("")
    out.append(f"Generated {result['generated']}. "
               f"Papers: {', '.join(result['papers']) if result['papers'] else 'none'}.")
    out.append("")
    out.append("Match shares are over every claim × replica pair that Stage 1 scored in "
               "`match.json`, restricted to replicas that ran. A pair whose replica could "
               "not bind the claim to the data counts as *not found*, not as a failed "
               "match. `n/a` means the metric could not be computed from the files present.")
    out.append("")

    out.append("## Runs and reproduction, by family")
    out.append("")
    header = ["family", "launched", "ran", "failed", "no trace", "pairs scored",
              "found", "A", "A+B", "headline A+B", "focal A+B"]
    rows = [_runs_cells(g) for g in result["families"]]
    rows += [_runs_cells(g) for g in result["tiers"]]
    out.append(_table(header, rows))
    out.append("")
    out.append("The last rows pool every replica in the tier (frontier = claude_p / codex "
               "subscription routes, cheap = opencode via OpenRouter); they are not averages "
               "of the family rates above. *no trace* is a replica directory without a "
               "`trace.json` — launched but not finished, distinct from *failed* "
               "(trace written, `ran` false).")
    out.append("")

    out.append("## Band distribution (all scored pairs)")
    out.append("")
    rows = [_bands_cells(g) for g in result["families"]] + \
           [_bands_cells(g) for g in result["tiers"]]
    out.append(_table(["family", "A", "B", "C", "fail", "not found"], rows))
    out.append("")

    out.append("## Fixes, hardcoding audit, blinding")
    out.append("")
    header = ["family", "fixes", "minor", "major", "critical", "unrated",
              "clean", "suspicious", "hardcoded", "audit n/r", "blind hits"]
    rows = [_process_cells(g) for g in result["families"]] + \
           [_process_cells(g) for g in result["tiers"]]
    out.append(_table(header, rows))
    out.append("")
    out.append("Hardcoding columns count replicas by audit verdict. *blind hits* is the "
               "total of `run_checks.blind_transcript_hits` with the number of replicas "
               "reporting the field in brackets; traces written before the check existed "
               "do not report it.")
    out.append("")

    out.append("## Cost and effort (replica calls only)")
    out.append("")
    rows = [_cost_cells(g) for g in result["families"]] + \
           [_cost_cells(g) for g in result["tiers"]]
    out.append(_table(["family", "tokens in", "tokens out", "cost $ (API)",
                       "list-price equiv $", "mean wall s"], rows))
    out.append("")
    out.append("`cost $ (API)` is metered spend, which only the OpenRouter-backed families "
               "incur. `list-price equiv $` is what the subscription calls would have cost "
               "at API list price; the `claude -p` route reports it, the codex route does "
               "not, so codex-backed families show n/a there. The codex route also reports "
               "only a token total, which the ledger stores as `tokens_in`, so its "
               "`tokens out` reads 0.")
    out.append("")

    out.append("## Per paper")
    for block in result["per_paper"]:
        out.append("")
        out.append(f"### {block['paper_id']}")
        out.append("")
        out.append(_table(
            ["family", "launched", "ran", "failed", "no trace", "pairs scored",
             "found", "A", "A+B", "headline A+B", "focal A+B"],
            [_runs_cells(g) for g in block["families"]] or [["(no replicas)"] + [NA] * 10],
        ))
        out.append("")
        out.append(f"- Claims scored: {block['n_claims_scored'] or NA}")
        out.append(f"- Decision agreement (mean over claims): "
                   f"{_f(block['decision_agreement_mean'], 3)}")
        out.append(f"- Numeric CV (median over claims): {_f(block['numeric_cv_median'], 3)}")

        focal = block["focal"]
        q = focal.get("quantity") or {}
        if q:
            derived = f", converted from {q['derived_from']}" if q.get("derived_from") else ""
            out.append(f"- Focal quantity: {q.get('kind', NA)} = "
                       f"{_f(q.get('reported_value'), 3)} (claim {q.get('claim_id', NA)}, "
                       f"{focal.get('source') or NA}{derived})")
            if focal.get("claim_ids"):
                out.append(f"  - focal claim set (the *focal A+B* column above pools these): "
                           f"{', '.join(focal['claim_ids'])}")
        else:
            out.append(f"- Focal quantity: {NA}")
        if focal.get("values"):
            out.append(f"  - replica values are on the {focal.get('scale') or NA} scale, "
                       f"as the claim was reported")
        if focal.get("within_family"):
            for fam, w in focal["within_family"].items():
                out.append(f"  - within {fam} ({w['n']} runs): "
                           f"{', '.join(_f(v, 4) for v in w['values'])} — "
                           f"spread {_f(w['max_abs_diff'], 4)}")
        else:
            out.append(f"  - within-family focal spread: {NA} (no family with two runs "
                       f"reporting the focal value)")
        out.append(f"  - between-family range of family means: "
                   f"{_f(focal.get('between_family_range'), 4)}")

        fd, m100 = block["focal_d"], block.get("multi100") or {}
        ad = (m100.get("analyst_d") or {})
        if fd.get("replicas") or ad:
            reps = ", ".join(f"{k} {_f(v, 3)}" for k, v in sorted(fd.get("replicas", {}).items()))
            out.append(f"- Focal d — reported {_f(fd.get('reported'), 3)}; "
                       f"replicas: {reps or NA}")
            out.append(f"  - Multi100 analysts (n = {m100.get('n_analysts', NA)}): "
                       f"min {_f(ad.get('min'), 3)}, median {_f(ad.get('median'), 3)}, "
                       f"max {_f(ad.get('max'), 3)}")
            if fd.get("note"):
                out.append(f"  - {fd['note']}")
        else:
            out.append(f"- Focal d: {NA}")

        tgt = block.get("targeted") or {}
        out.append(f"- Targeted reconstruction: {tgt.get('outcome', NA)}"
                   + (f" — {tgt['notes']}" if tgt.get("notes") else ""))

        costs = block["stage_costs"]
        if costs:
            out.append("")
            out.append(_table(
                ["stage", "calls", "cost $ (API)", "list-price equiv $"],
                [[s, str(c["calls"]), _f(c["cost_usd"], 4), _f(c["cost_usd_equiv"], 4)]
                 for s, c in sorted(costs.items())]
                + [["total", str(sum(c["calls"] for c in costs.values())),
                    _f(sum(c["cost_usd"] for c in costs.values()), 4),
                    _f(sum(c["cost_usd_equiv"] for c in costs.values()), 4)]],
            ))
    out.append("")
    return "\n".join(out)


def write(result: dict[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / "pilot_eval.json", out_dir / "pilot_eval.md"
    jp.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n")
    mp.write_text(render_md(result))
    return jp, mp


# --- entry point ----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m reproscope.evaluate",
        description="Aggregate Stage 1 replica outcomes across papers into "
                    "docs/evaluation/pilot_eval.{json,md}.",
    )
    p.add_argument("--papers", nargs="+", help="paper ids (default: every run except _fixtures)")
    p.add_argument("--include-fixtures", action="store_true",
                   help="also include runs whose id starts with _")
    p.add_argument("--out-dir", default=None, help="default docs/evaluation")
    args = p.parse_args(argv)

    ids = args.papers or paper_ids(include_fixtures=args.include_fixtures)
    if not ids:
        print("no runs found under runs/")
        return 1
    result = evaluate([load_paper(pid) for pid in ids])
    out_dir = Path(args.out_dir) if args.out_dir else paths.ROOT / "docs" / "evaluation"
    jp, mp = write(result, out_dir)
    print(render_md(result))
    print(f"\nwritten: {mp}\n         {jp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

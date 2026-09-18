"""Build the per-paper report: a self-contained HTML page plus a JSON sidecar.

Every stage is optional. Missing artifacts render a "not run" box; a present
artifact carrying `state: "abstained"` renders an abstention box with its reason.
Artifacts are read as plain JSON, never validated against the pydantic models, so
that a schema drift in one stage cannot stop the report from being built.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from ..multiverse_summary import render_md as render_sensitivity_md
from typing import Any

import markdown as md_lib
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from .. import ledger, paths

TEMPLATES = Path(__file__).resolve().parent / "templates"
SUBSCRIPTION_ROUTES = {"claude_p", "codex"}


# --- small helpers --------------------------------------------------------


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def read_text(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def maybe_json(value: Any) -> Any:
    """Several stage-1 trace fields are typed `str` but hold JSON-encoded objects."""
    if isinstance(value, str):
        s = value.strip()
        if s[:1] in "{[":
            try:
                return json.loads(s)
            except json.JSONDecodeError:
                return value
    return value


def md_to_html(text: str | None) -> Markup:
    if not text:
        return Markup("")
    html = md_lib.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    return Markup(html)


def num(x: Any, nd: int = 3) -> str:
    if x is None or isinstance(x, bool):
        return "—"
    if isinstance(x, (int, float)):
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return "—"
        if isinstance(x, int) or float(x).is_integer() and abs(x) < 1e15:
            return f"{int(x)}"
        return f"{x:.{nd}g}" if abs(x) < 1e-3 else f"{round(x, nd):g}"
    return str(x)


def pct(x: Any) -> str:
    return "—" if x is None else f"{100 * float(x):.0f}%"


def tier_of(route: str | None) -> str:
    return "frontier" if route in SUBSCRIPTION_ROUTES else "cheap"


def _first(d: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(d, dict):
        return default
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return default


# --- stage loaders --------------------------------------------------------


def _stage0(base: Path) -> dict[str, Any] | None:
    from ..computation_coverage import review as computation_review
    d = base / "stage0"
    claims = load_json(d / "claims.json")
    contracts = load_json(d / "contracts.json")
    readiness = load_json(d / "readiness.json")
    redaction = load_json(d / "redaction_report.json")
    leak = load_json(d / "leak_audit.json")
    methods = read_text(d / "redacted_methods.md")
    if not any(x is not None for x in (claims, contracts, readiness, redaction, leak, methods)):
        return None

    claims = claims or []
    by_type: dict[str, int] = {}
    by_importance: dict[str, int] = {}
    pairing = load_json(d / "arbitration.json") or {}
    assignments = load_json(d / "contract_assignments.json") or {}
    n_extracted = n_agreed = 0
    for c in claims:
        by_type[str(c.get("claim_type") or "unknown")] = by_type.get(str(c.get("claim_type") or "unknown"), 0) + 1
        key = str(c.get("importance") or "unclassified")
        by_importance[key] = by_importance.get(key, 0) + 1
        ex = c.get("extraction")
        if isinstance(ex, dict) and ex.get("agreed") is not None:
            n_extracted += 1
            n_agreed += 1 if ex["agreed"] else 0

    contract_rows = []
    for c in contracts or []:
        contract_rows.append(
            {
                "analysis_id": c.get("analysis_id"),
                "model_type": c.get("model_type"),
                "sample_rule": c.get("sample_rule"),
                "outcome": c.get("outcome"),
                "claim_ids": c.get("claim_ids") or [],
                "ambiguities": c.get("ambiguities") or [],
                "state": c.get("state"),
                "readiness_state": (readiness or {}).get("per_analysis_state", {}).get(c.get("analysis_id"))
                if isinstance(readiness, dict)
                else None,
            }
        )

    bindings = []
    if isinstance(readiness, dict):
        for b in readiness.get("variable_bindings") or []:
            bindings.append(
                {
                    "analysis_id": b.get("analysis_id"),
                    "field": b.get("contract_field"),
                    "candidates": b.get("candidate_columns") or [],
                    "chosen": b.get("chosen"),
                    "input_columns": b.get("input_columns") or [],
                    "transformation": b.get("transformation"),
                    "note": b.get("note"),
                    "unbound": not b.get("chosen") and not b.get("input_columns"),
                }
            )

    leak_verdict = _first(leak, "verdict", "leakage_audit_verdict") or _first(
        redaction, "leakage_audit_verdict"
    )
    leak_note = _first(leak, "note", "leakage_audit_note") or _first(redaction, "leakage_audit_note")

    return {
        "claims": claims,
        "n_claims": len(claims),
        "by_type": sorted(by_type.items()),
        "by_importance": sorted(by_importance.items()),
        "extraction": {
            "pairing": pairing,
            "numeric_clause_anchors": sum(c.get("source_anchor_scope") == "numeric_clause_only" for c in claims),
            "n_with_records": n_extracted,
            "n_agreed": n_agreed,
            "rate": (n_agreed / n_extracted) if n_extracted else None,
        },
        "contracts": contract_rows,
        "assignments": assignments,
        "computation_coverage": computation_review(base),
        "source_diagnostics": load_json(d / "source_diagnostics.json") or {},
        "extraction_benchmark": load_json(d / "extraction_benchmark.json"),
        "readiness": readiness if isinstance(readiness, dict) else None,
        "bindings": bindings,
        "redaction": redaction if isinstance(redaction, dict) else None,
        "leak_verdict": leak_verdict,
        "leak_note": leak_note,
        "methods_html": md_to_html(methods),
        "has_methods": bool(methods),
    }


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    from collections import Counter
    from ..stage1.audit import acceptance
    fixes = trace.get("fixes") or []
    sev: dict[str, int] = {"minor": 0, "major": 0, "critical": 0, "unrated": 0}
    for f in fixes:
        s = (f or {}).get("severity") or "unrated"
        sev[s] = sev.get(s, 0) + 1
    checks = trace.get("run_checks") or {}
    detail_keys = (
        "filters",
        "transformations",
        "model_formula",
        "missingness",
        "weights",
        "estimator_settings",
        "seed",
        "variable_bindings",
        "abstentions",
    )
    details = []
    for k in detail_keys:
        v = trace.get(k)
        if v in (None, [], {}, ""):
            continue
        if isinstance(v, list):
            v = [maybe_json(x) for x in v]
        else:
            v = maybe_json(v)
        details.append((k, json.dumps(v, indent=1) if not isinstance(v, (str, int, float)) else str(v)))
    return {
        "replica_id": trace.get("replica_id"),
        "family": trace.get("family"),
        "model": trace.get("model"),
        "source_repair_models": sorted({e['model'] for e in trace.get('source_repairs',[]) if e.get('model')}),
        "route": trace.get("route"),
        "tier": tier_of(trace.get("route")),
        "ran": bool(trace.get("ran")),
        "script_execution": checks.get("script_execution_status") or ("executed" if checks.get("exit_code") == 0 else "unverified"),
        "output_protocol": checks.get("output_protocol_status") or "unverified",
        "state": trace.get("state"),
        "abstain_reason": trace.get("abstain_reason"),
        "fixes": fixes,
        "fix_counts": sev,
        "n_fixes": len(fixes),
        "hardcoding": (trace.get("hardcoding_audit") or {}).get("verdict")
        or ("hits" if (trace.get("hardcoding_audit") or {}).get("hits") else None),
        "hardcoding_hits": (trace.get("hardcoding_audit") or {}).get("hits") or [],
        "audit_acceptance": acceptance(trace.get("hardcoding_audit") or {}),
        "turns": checks.get("loops") if checks.get("loops") is not None else checks.get("steps_done"),
        "exit_code": checks.get("exit_code"),
        "wall_s": checks.get("wall_s"),
        "software": trace.get("software"),
        "open_choices": [maybe_json(x) for x in (trace.get("open_choices") or [])],
        "details": details,
        "execution_evidence": trace.get("execution_evidence") or {},
        "method_counts": dict(Counter(a.get("status", "unverified") for a in (trace.get("execution_evidence") or {}).get("analyses", {}).values())),
        "computation_counts": dict(Counter(a.get("computation_status", "not_run") for a in (trace.get("execution_evidence") or {}).get("analyses", {}).values())),
    }


def _stage1(base: Path, claims: list[dict[str, Any]], ledger_rows: list[dict]) -> dict[str, Any] | None:
    d = base / "stage1"
    match = load_json(d / "match.json")
    targeted = load_json(d / "targeted.json")
    rerun = load_json(d / "rerun.json")
    diagnosis = read_text(d / "diagnosis.md")
    traces: dict[str, dict[str, Any]] = {}
    rep_dir = d / "replicas"
    if rep_dir.is_dir():
        for sub in sorted(p for p in rep_dir.iterdir() if p.is_dir()):
            t = load_json(sub / "trace.json")
            if isinstance(t, dict):
                receipt=load_json(sub/'generation_receipt.json') or {}
                t['source_repairs']=receipt.get('source_repairs',[])
                traces[t.get("replica_id") or sub.name] = t
    if match is None and not traces and targeted is None and rerun is None and diagnosis is None:
        return None

    rows = (match or {}).get("rows") or []
    summaries = {s.get("claim_id"): s for s in (match or {}).get("summaries") or []}

    replica_ids = list(traces) + [r.get("replica_id") for r in rows if r.get("replica_id") not in traces]
    replica_ids = sorted(dict.fromkeys(x for x in replica_ids if x))

    usage: dict[str, dict[str, float]] = {}
    for r in ledger_rows:
        rid = r.get("replica_id")
        if not rid:
            continue
        u = usage.setdefault(rid, {"tokens_in": 0.0, "tokens_out": 0.0, "cost_usd": 0.0, "cost_usd_equiv": 0.0, "calls": 0})
        u["calls"] += 1
        for k in ("tokens_in", "tokens_out", "cost_usd", "cost_usd_equiv"):
            u[k] += float(r.get(k) or 0)

    replicas = []
    for rid in replica_ids:
        t = traces.get(rid) or {"replica_id": rid}
        info = _trace_summary(t)
        if info["replica_id"] is None:
            info["replica_id"] = rid
        if not traces.get(rid):
            info["ran"] = any(r.get("replica_id") == rid and r.get("replicated") is not None for r in rows)
            info["no_trace"] = True
        info["usage"] = usage.get(rid)
        replicas.append(info)

    claim_meta = {c.get("claim_id"): c for c in claims}
    order = {"headline": 0, "supporting": 1}
    claim_ids = [c.get("claim_id") for c in claims] or sorted({r.get("claim_id") for r in rows if r.get("claim_id")})
    claim_ids = sorted(
        claim_ids,
        key=lambda cid: (order.get(str((claim_meta.get(cid) or {}).get("importance")), 2), str(cid)),
    )

    cells_by_key = {(r.get("claim_id"), r.get("replica_id")): r for r in rows}
    from ..computation_coverage import review as computation_review
    computation = {r['claim_id']: r for r in computation_review(base)['rows']}
    tier_by_rid = {r["replica_id"]: r["tier"] for r in replicas}
    ran_by_rid = {r["replica_id"]: r["ran"] for r in replicas}

    tier_counts = {"cheap": [0, 0], "frontier": [0, 0]}  # [matched, comparable]
    table = []
    for cid in claim_ids:
        cm = claim_meta.get(cid) or {}
        prec = cm.get("precision")
        nd = (prec + 1) if isinstance(prec, int) else 4
        cells = []
        for rid in replica_ids:
            row = cells_by_key.get((cid, rid))
            summary = summaries.get(cid) or {}
            accounting = computation.get(cid, {})
            if row is None and accounting.get('route') == 'descriptive':
                cells.append({'state': 'abstained', 'label': 'descriptive route' if accounting['status'] == 'computed' else 'data unavailable',
                              'row': None, 'detail': accounting['reason']})
                continue
            if not row and summary.get("state") == "abstained" and summary.get("outcome_status") in {"input_invalid", "unbound", "no_data", "supplied_fact"}:
                cells.append({"state": "abstained", "label": "input excluded" if summary.get("outcome_status") == "input_invalid" else "intake abstention",
                              "row": None, "detail": summary.get("abstain_reason") or ""})
                continue
            if not ran_by_rid.get(rid, True):
                cells.append({"state": "failed", "label": "did not run", "row": None})
                continue
            if row is None:
                cells.append({"state": "notfound", "label": "not found", "row": None})
                continue
            if row.get("state") == "abstained" or row.get("replicated") is None:
                cells.append(
                    {
                        "state": "abstained",
                        "label": "abstained",
                        "row": row,
                        "detail": row.get("abstain_reason") or "",
                    }
                )
                continue
            band = row.get("band")
            # Paired statistics compare magnitude and source direction; raw signs
            # remain visible. Unknown direction has no full-match credit.
            state = "fail" if band == "fail" else f"band-{band}" if band else "notfound"
            if row.get('outcome_status') == 'direction_unverified':
                state = 'direction-unverified'
            elif row.get('bound_rounding_compatible') and row.get('bound_satisfied') is False:
                state = 'rounding-compatible'
            tier = tier_by_rid.get(rid, "cheap")
            tier_counts.setdefault(tier, [0, 0])
            tier_counts[tier][1] += 1
            if band in ("A", "B"):
                tier_counts[tier][0] += 1
            cells.append(
                {
                    "state": state,
                    "band": band,
                    "flipped": bool(row.get("direction_flipped")),
                    "label": num(row.get("replicated"), nd),
                    "row": row,
                    "detail": " · ".join(
                        x
                        for x in (
                            row.get("rule") or "",
                            f"raw diff {num(row.get('raw_diff'), 3)}" if row.get("raw_diff") is not None else "",
                            f"std diff {num(row.get('std_diff'), 3)}" if row.get("std_diff") is not None else "",
                            f"σ-rule {row.get('sigma_rule')}" if row.get("sigma_rule") not in (None, "na") else "",
                            f"unit: {row.get('unit_check')}" if row.get("unit_check") else "",
                        )
                        if x
                    ),
                }
            )
        s = summaries.get(cid) or {}
        disp = s.get("dispersion") or {}
        table.append(
            {
                "claim_id": cid,
                "importance": cm.get("importance"),
                "quantity_kind": cm.get("quantity_kind"),
                "description": cm.get("description"),
                "reported": num(cm.get("value"), nd),
                "cells": cells,
                "fraction_matched": s.get("fraction_matched"),
                "numeric_cv": disp.get("numeric_cv"),
                "decision_agreement": disp.get("decision_agreement"),
                "n_ran": s.get("n_ran"),
            }
        )

    split = [
        {
            "tier": t,
            "matched": v[0],
            "comparable": v[1],
            "rate": (v[0] / v[1]) if v[1] else None,
            "replicas": [r["replica_id"] for r in replicas if r["tier"] == t],
        }
        for t, v in sorted(tier_counts.items())
        if v[1] or any(r["tier"] == t for r in replicas)
    ]

    return {
        "match": match,
        "source_direction": load_json(d / 'source_direction.json') or {},
        "table": table,
        "replicas": replicas,
        "replica_ids": replica_ids,
        "split": split,
        "targeted": targeted,
        "rerun": rerun,
        "diagnosis_html": md_to_html(diagnosis),
        "has_diagnosis": bool(diagnosis),
        "trace_equivalence": (match or {}).get("trace_equivalence"),
    }


def _stage2(base: Path) -> dict[str, Any] | None:
    d = base / "stage2"
    review = load_json(d / "review.json")
    review_md = read_text(d / "review.md")
    if review is None and review_md is None:
        return None
    narrow = (review or {}).get("narrow") or {}
    return {
        "review": review,
        "mode": (review or {}).get("mode"),
        "questions": (review or {}).get("questions") or {},
        "review_html": md_to_html(review_md),
        "has_md": bool(review_md),
        "causal": narrow.get("causal_language"),
        "mde": narrow.get("mde"),
        "alignment": narrow.get("alignment"),
        "findings": ((review or {}).get("broad") or {}).get("findings") or [],
        "claim_id": (review or {}).get("claim_id"),
    }


# --- specification curve --------------------------------------------------


def spec_curve_svg(runs: list[dict], reported: float | None, paper_spec: dict | None, null_value: float = 0.) -> str:
    """Sorted specification estimates as points with CI whiskers, drawn by hand."""
    pts = [r for r in runs if isinstance(r.get("estimate"), (int, float))]
    if not pts:
        return ""
    pts = sorted(pts, key=lambda r: r["estimate"])
    w, h = 900, 340
    ml, mr, mt, mb = 62, 18, 18, 46
    pw, ph = w - ml - mr, h - mt - mb

    lo = hi = pts[0]["estimate"]
    for r in pts:
        e = r["estimate"]
        se = r.get("se") if isinstance(r.get("se"), (int, float)) else None
        a, b = ((r["ci_lower"], r["ci_upper"]) if isinstance(r.get("ci_lower"), (int, float)) and isinstance(r.get("ci_upper"), (int, float))
                else (e, e))
        lo, hi = min(lo, a), max(hi, b)
    if isinstance(reported, (int, float)):
        lo, hi = min(lo, reported), max(hi, reported)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    pad = 0.08 * (hi - lo)
    lo, hi = lo - pad, hi + pad

    n = len(pts)
    inset = 16  # keep the first and last point clear of the plot border

    def x(i: int) -> float:
        span = pw - 2 * inset
        return ml + inset + (span / 2 if n == 1 else span * i / (n - 1))

    def y(v: float) -> float:
        return mt + ph * (hi - v) / (hi - lo)

    out = [
        f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" '
        'aria-label="specification curve" xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="{ml}" y="{mt}" width="{pw}" height="{ph}" fill="var(--panel)" stroke="var(--line)"/>',
    ]
    # y gridlines
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        yy = y(v)
        out.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{ml + pw}" y2="{yy:.1f}" stroke="var(--line)" stroke-dasharray="2 3"/>')
        out.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" text-anchor="end" font-size="11" fill="var(--muted)">{v:.3g}</text>')
    if lo < null_value < hi:
        out.append(f'<line x1="{ml}" y1="{y(null_value):.1f}" x2="{ml + pw}" y2="{y(null_value):.1f}" stroke="var(--muted)"/>')

    if isinstance(reported, (int, float)):
        yr = y(reported)
        out.append(f'<line x1="{ml}" y1="{yr:.1f}" x2="{ml + pw}" y2="{yr:.1f}" stroke="#b3261e" stroke-width="2"/>')
        out.append(
            f'<text x="{ml + 6}" y="{yr - 6:.1f}" font-size="11" fill="#b3261e">'
            f"reported {reported:g}</text>"
        )

    for i, r in enumerate(pts):
        e = r["estimate"]
        se = r.get("se") if isinstance(r.get("se"), (int, float)) else None
        xi = x(i)
        ci = ((r["ci_lower"], r["ci_upper"]) if isinstance(r.get("ci_lower"), (int,float)) and isinstance(r.get("ci_upper"), (int,float)) else None)
        if ci:
            out.append(
                f'<line x1="{xi:.1f}" y1="{y(ci[0]):.1f}" x2="{xi:.1f}" '
                f'y2="{y(ci[1]):.1f}" stroke="var(--muted)" stroke-width="1.5"/>'
            )
        p = r.get("p")
        sig = isinstance(p, (int, float)) and p < 0.05
        fill = "#1f6f43" if sig else "var(--panel)"
        is_paper = bool(paper_spec) and r.get("spec") == paper_spec
        out.append(
            f'<circle cx="{xi:.1f}" cy="{y(e):.1f}" r="{6 if is_paper else 4}" fill="{fill}" '
            f'stroke="{"#b3261e" if is_paper else "#1f6f43"}" stroke-width="{2.5 if is_paper else 1.5}">'
            f"<title>estimate {e:.4g}"
            + (f", se {se:.3g}" if se else "")
            + (f", p {p:.3g}" if isinstance(p, (int, float)) else "")
            + ("  [paper-level specification]" if is_paper else "")
            + "</title></circle>"
        )
    out.append(
        f'<text x="{ml + pw / 2:.0f}" y="{h - 14}" text-anchor="middle" font-size="12" fill="var(--muted)">'
        f"{n} specification{'s' if n != 1 else ''}, sorted by estimate (filled = p &lt; .05, "
        + ("whiskers = declared intervals)</text>" if all(isinstance(r.get("ci_lower"),(int,float)) for r in pts) else "whiskers shown only for declared intervals)</text>")
    )
    out.append(f'<text x="14" y="{mt + ph / 2:.0f}" font-size="12" fill="var(--muted)" transform="rotate(-90 14 {mt + ph / 2:.0f})" text-anchor="middle">estimate</text>')
    out.append("</svg>")
    return "".join(out)


def inline_svg(path: Path, prefix: str) -> Markup:
    """Keep generated SVG definitions local when several plots share one document."""
    text = read_text(path) or ""
    start = text.find("<svg")
    if start < 0:
        return Markup("")
    text = text[start:]
    identifiers = re.findall(r'\bid="([^"]+)"', text)
    for identifier in identifiers:
        name = prefix + "_" + identifier
        text = text.replace('id="' + identifier + '"', 'id="' + name + '"')
        text = text.replace('href="#' + identifier + '"', 'href="#' + name + '"')
        text = text.replace('url(#' + identifier + ')', 'url(#' + name + ')')
    return Markup(text)


def _stage3(base: Path) -> dict[str, Any] | None:
    d = base / "stage3"
    space = load_json(d / "space.json")
    interp = read_text(d / "interpretation.md")
    if space is None and interp is None:
        return None
    space = space or {}
    latest_execution=load_json(d/'execute.json') or {}
    recorded_fingerprint=(space.get('execution') or {}).get('output_fingerprint')
    if space.get('state')=='complete' and recorded_fingerprint and recorded_fingerprint!=latest_execution.get('output_fingerprint'):
        space={**space,'state':'abstained','runs':[],
               'abstain_reason':'The multiverse results changed after report aggregation. Complete Stage 3 before interpreting the current curve.',
               'execution':latest_execution}
    elif recorded_fingerprint and recorded_fingerprint==latest_execution.get('output_fingerprint'):
        space={**space,'execution':latest_execution}
    if space.get('state')=='complete' and (latest_execution.get('ok') is False or latest_execution.get('problems')):
        space={**space,'state':'abstained','runs':[],
               'abstain_reason':'The latest multiverse execution failed validation. No current accepted curve is available.',
               'execution':latest_execution}
    factors = space.get("factors") or []
    if space.get("state") == "abstained":
        # Abstention can precede generation or follow a rejected attempt. Neither
        # permits a curve or ranking from outputs left in the directory.
        return {
            "space": space,
            "abstained": True,
            "abstain_reason": space.get("abstain_reason"),
            "attempted_specs": space.get("attempted_specs", 0),
            "factors": factors,
            "unimplementable": space.get("unimplementable") or [],
            "screen_adjustments": space.get("screen_adjustments") or [],
            "claim_id": space.get("claim_id"),
            "focal_quantity": space.get("focal_quantity") or {},
            "reported_estimate": space.get("reported_estimate"),
            "grid_size": space.get("grid_size"),
            "incompatibilities": space.get("incompatibilities") or [],
            "dropped_factors": space.get("dropped_factors") or [],
        }
    all_runs = space.get("runs") or []
    runs = [r for r in all_runs if r.get("role") != "author_reference"]
    if not all_runs:
        runs = _runs_from_csv(d / "work" / "out" / "specs.csv")
    ranking = space.get("ranking") or {}
    ij = space.get("interpretation_json") or {}
    # The level the paper itself used, per factor. Recorded in three places over
    # the life of Stage 3: on each factor, in the ranking, or in paper_level.json.
    levels = {f.get("name"): f.get("paper_level") for f in factors if f.get("paper_level") is not None}
    if not levels:
        levels = ranking.get("paper_level_spec") or (
            load_json(d / "paper_level.json") or {}
        ).get("levels") or {}
        for f in factors:
            if f.get("name") in levels:
                f["paper_level"] = levels[f["name"]]
    paper_spec = levels if levels and len(levels) == len(factors) else None
    n_converged = sum(1 for r in runs if r.get("converged"))
    return {
        "space": space,
        "abstained": False,
        "factors": factors,
        "runs": runs,
        "unimplementable": space.get("unimplementable") or [],
        "screen_adjustments": space.get("screen_adjustments") or [],
        "grid_size": space.get("grid_size"),
        "n_specs": space.get("n_specs") or len(runs),
        "sensitivity_scope": space.get("sensitivity_scope") or (load_json(d / "grid.json") or {}).get("sensitivity_scope", "undetermined"),
        "n_converged": ranking.get("n_converged", n_converged),
        "sampled": bool(space.get("sampled")),
        "sample_fraction": space.get("sample_fraction"),
        "incompatibilities": space.get("incompatibilities") or [],
        "reported_estimate": space.get("reported_estimate") or ranking.get("reported_estimate"),
        "rank": space.get("rank") if space.get("rank") is not None else ranking.get("rank"),
        "extremeness": ranking.get("extremeness"),
        "curve_state": ranking.get("curve_state"),
        "rank_interval": ranking.get("rank_interval"),
        "author_reference": ranking.get("author_reference", []),
        "share_same_sign": ranking.get("share_same_sign"),
        "share_significant": ranking.get("share_significant", ij.get("share_significant")),
        "alphas": ranking.get("alphas") or [],
        "median": ranking.get("median"),
        "range": [ranking.get("min"), ranking.get("max")],
        "claim_id": space.get("claim_id"),
        "focal_quantity": space.get("focal_quantity") or {},
        "paper_spec": paper_spec,
        "svg": Markup("") if str(space.get("mode",'')).startswith('scoped-paired-') else Markup(spec_curve_svg(runs, space.get("reported_estimate") or ranking.get("reported_estimate"), paper_spec)),
        "scoped_full_rows": [r for r in runs if r.get("spec", {}).get("sample") == "full"] if str(space.get("mode",'')).startswith('scoped-paired-') else [],
        "scoped_design": load_json(d / "registered_design.json") or {},
        "sensitivity_summary": load_json(d / "sensitivity_summary.json") or {},
        "sensitivity_summary_html": md_to_html(render_sensitivity_md(load_json(d / 'sensitivity_summary.json'))) if (d / 'sensitivity_summary.json').exists() else '',
        "scoped_panels": [{"name":name,"svg":inline_svg(d / "work/out" / filename, Path(filename).stem)} for name,filename in (("Full-sample sensitivity", "full_sample.svg"),("Influence diagnostics", "influence.svg"))] if str(space.get("mode",'')).startswith('scoped-paired-') else [],
        "interpretation_html": md_to_html((interp or space.get("interpretation") or "").split("## Analytical scope and methods",1)[-1] if (d / "sensitivity_summary.json").exists() else interp or space.get("interpretation")),
        "dropped_factors": space.get("dropped_factors") or [],
    }


def _runs_from_csv(path: Path) -> list[dict[str, Any]]:
    import csv

    try:
        with path.open() as f:
            rows = list(csv.DictReader(f))
    except OSError:
        return []
    out = []
    for r in rows:
        spec = {k: v for k, v in r.items() if k not in ("estimate", "se", "p", "n", "converged", "error")}

        def f(key: str) -> float | None:
            try:
                return float(r[key])
            except (KeyError, TypeError, ValueError):
                return None

        out.append(
            {
                "spec": spec,
                "estimate": f("estimate"),
                "se": f("se"),
                "p": f("p"),
                "converged": str(r.get("converged", "")).upper() in ("TRUE", "1"),
            }
        )
    return out


# --- focal claim ----------------------------------------------------------


def _focal(manifest: dict[str, Any], claims: list[dict], s2: dict | None, s3: dict | None,
           s1: dict | None) -> dict[str, Any]:
    fc = manifest.get("focal_claim") or {}
    reported = fc.get("reported") or {}
    claim_id, rule = None, None
    if s3 and s3.get("claim_id"):
        claim_id, rule = s3["claim_id"], "claim_id recorded by Stage 3 (space.json)"
    elif s2 and s2.get("claim_id"):
        claim_id, rule = s2["claim_id"], "claim_id recorded by Stage 2 (review.json)"
    else:
        val = reported.get("value")
        hits = [c for c in claims if isinstance(val, (int, float)) and c.get("value") == val]
        if len(hits) == 1:
            claim_id, rule = hits[0].get("claim_id"), "manifest focal_claim.reported.value matched exactly one claim"
        else:
            heads = [c for c in claims if c.get("importance") == "headline"]
            if heads:
                claim_id = heads[0].get("claim_id")
                rule = f"no recorded focal claim id; showing the first headline claim of {len(heads)}"
            else:
                rule = "no focal claim id could be resolved"

    claim = next((c for c in claims if c.get("claim_id") == claim_id), None)
    replica_values = []
    if s1 and claim_id:
        for row in (s1.get("match") or {}).get("rows") or []:
            if row.get("claim_id") == claim_id:
                replica_values.append(
                    {
                        "replica_id": row.get("replica_id"),
                        "value": num(row.get("replicated"), (claim or {}).get("precision", 3) + 1 if claim and isinstance(claim.get("precision"), int) else 4),
                        "band": row.get("band"),
                        "se": row.get("se"),
                    }
                )
    m100 = manifest.get("multi100")
    return {
        "text": fc.get("text"),
        "source": fc.get("source"),
        "reported": reported,
        "reported_kind": reported.get("family") or reported.get("statistic"),
        "claim_id": claim_id,
        "rule": rule,
        "claim": claim,
        "replica_values": replica_values,
        "multi100": m100 if isinstance(m100, dict) else None,
        "multi100_kind": "d",
        "quantity_kind": (claim or {}).get("quantity_kind") or (s3 or {}).get("focal_quantity", {}).get("kind"),
    }


# --- ledger ---------------------------------------------------------------


def _empty_ledger(paper_id: str) -> dict[str, Any]:
    blank = {"calls": 0, "ok": 0, **{f: 0.0 for f in ledger.NUMERIC_FIELDS}}
    summary = {"paper_id": paper_id, "total": blank, "route": {}, "model": {}, "stage": {}}
    return {"rows": [], "summary": summary, "table": [], "models": []}


def _ledger_ctx(paper_id: str) -> dict[str, Any]:
    # ledger.rows()/summary() go through paths.run_dir(), which creates the run
    # directory. Building a report must never create one for a paper with no run.
    if not (paths.ROOT / "runs" / paper_id / "ledger.jsonl").exists():
        return _empty_ledger(paper_id)
    rows = ledger.rows(paper_id)
    summary = ledger.summary(paper_id)
    cross: dict[tuple[str, str], dict[str, float]] = {}
    for r in rows:
        key = (str(r.get("stage") or "?"), str(r.get("model") or "?"))
        b = cross.setdefault(key, {"calls": 0, "tokens_in": 0.0, "tokens_out": 0.0, "cost_usd": 0.0, "cost_usd_equiv": 0.0, "route": r.get("route") or "?"})
        b["calls"] += 1
        for k in ("tokens_in", "tokens_out", "cost_usd", "cost_usd_equiv"):
            b[k] += float(r.get(k) or 0)
    table = [{"stage": s, "model": m, **v} for (s, m), v in sorted(cross.items())]
    models = sorted({str(r.get("model")) for r in rows if r.get("model")})
    return {"rows": rows, "summary": summary, "table": table, "models": models}


# --- assembly -------------------------------------------------------------


MAX_ATTACHMENTS = 400


def _attachments(base: Path) -> list[dict[str, Any]]:
    """Current analytical artifacts, with summaries before detailed logs and work."""
    out = []
    patterns = ("stage?/*.*", "stage?/logs/*.*", "stage?/work/out/*.*",
                "stage1/replicas/*/trace.json", "stage1/replicas/*/generation_receipt.json",
                "stage1/replicas/*/packet_provenance.json", "stage1/replicas/*/check.log",
                "stage1/replicas/*/work/out/*.*")
    files = {p for pattern in patterns for p in base.glob(pattern)}
    files.update(base / name for name in ("ledger.jsonl", "cohort.json", "replica_task_pin.json",
                                         "integration_checks.json", "warm_resume_check.json"))
    for p in sorted(files, key=lambda p: (len(p.relative_to(base).parts), str(p))):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if rel.parts[0].startswith(".") or rel.parts[0] == "report":
            continue
        out.append({"path": str(rel), "size_kb": round(p.stat().st_size / 1024, 1)})
        if len(out) >= MAX_ATTACHMENTS:
            out.append({"path": f"… truncated at {MAX_ATTACHMENTS} files", "size_kb": None})
            break
    return out


def _session_info(s1: dict | None) -> str | None:
    for r in (s1 or {}).get("replicas", []):
        if r.get("software"):
            return "\n".join(str(r["software"]).splitlines()[:8])
    return None


def build(paper_id: str, *, public: bool = False) -> tuple[str, dict[str, Any]]:
    """Render the report HTML and the JSON sidecar for one paper. Pure: writes nothing."""
    base = paths.ROOT / "runs" / paper_id
    try:
        manifest = json.loads((paths.corpus_dir(paper_id) / "manifest.json").read_text())
    except (OSError, json.JSONDecodeError):
        manifest = {"paper_id": paper_id}

    led = _ledger_ctx(paper_id)
    s0 = _stage0(base)
    claims = (s0 or {}).get("claims") or []
    s1 = _stage1(base, claims, led["rows"])
    s2 = _stage2(base)
    s3 = _stage3(base)

    from ..source_integrity import review_run
    semantic = review_run(base)
    preflight = None
    if (base / 'cohort.json').exists():
        from .. import cohort, validation
        try:
            preflight = validation.check(cohort.load(base / 'cohort.json'))
        except (ValueError, RuntimeError, OSError) as exc:
            preflight = {'all_runs_release_ready': False, 'error': str(exc)}
    from ..end_to_end_validation import check as check_end_to_end
    try:
        development_validation=check_end_to_end(paper_id, require_report=False)
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as exc:
        development_validation={'passed':False,'blockers':['Current validation could not complete: '+str(exc)],'limitations':[]}
    task_pin = load_json(base / "replica_task_pin.json") or {}
    protocol_provenance = ({"task_sha256": task_pin.get("sha256"), "scope": task_pin.get("reason")}
                           if task_pin else None)
    doi = manifest.get("doi")
    ctx = {
        "paper_id": paper_id,
        "pipeline_status": load_json(base/"pipeline_status.json") or {},
        "manifest": manifest,
        "semantic_validation": semantic,
        "current_preflight": preflight,
        "development_validation": development_validation,
        "protocol_provenance": protocol_provenance,
        "title": manifest.get("title") or paper_id,
        "doi": doi,
        "doi_url": f"https://doi.org/{doi}" if doi else None,
        "run_date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "focal": _focal(manifest, claims, s2, s3, s1),
        "s0": s0,
        "s1": s1,
        "descriptive": load_json(base / "stage1/descriptive/report.json"),
        "s2": s2,
        "s3": s3,
        "ledger": led,
        "cost_api": led["summary"]["total"]["cost_usd"],
        "cost_unknown": sum(float(r.get('cost_usd') or 0) for r in led['rows'] if r.get('cost_source')=='reserved_unknown'),
        "cost_equiv": led["summary"]["total"]["cost_usd_equiv"],
        "attachments": [] if public else _attachments(base),
        "public_export": public,
        "session_info": _session_info(s1),
        "num": num,
        "pct": pct,
    }

    from .findings import assemble as reader_findings
    diagnosis_context=load_json(base/'stage1/diagnosis.json') or {}
    diagnosis_context['inventory']=load_json(base/'stage1/divergence_inventory.json') or {}
    ctx['findings'] = reader_findings(s0,s1,s2,s3,ctx['descriptive'],diagnosis_context)
    from .reader import enrich, numeric, label
    ctx['_diagnosis_context'] = diagnosis_context
    ctx['reader'] = enrich(ctx, base)
    for group in ctx['findings']['sensitivity']['groups']:
        reference=((s3 or {}).get('space') or {}).get('curve_reference') or {}
        same_scale=reference.get('metric')==group['metric'] and reference.get('effect_group')==group['name']
        from .specification import specification_curve_svg
        group['svg'] = Markup(specification_curve_svg(group))
        if __import__('os').environ.get('REPROSCOPE_SPECR_EXPORT')=='1':
            from .specr_export import export
            group['specr_download']=export(group,base/'report/figures')

    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True, trim_blocks=True, lstrip_blocks=True)
    env.filters["num"] = num
    env.filters["pct"] = pct
    env.filters["number"] = numeric
    env.filters["label"] = label
    from .reader import prose_evidence
    env.filters["prose_evidence"] = prose_evidence
    html = env.get_template("report.html.j2").render(**ctx)

    sidecar = {
        "paper_id": paper_id,
        "generated": datetime.now(timezone.utc).isoformat(),
        "findings": ctx["findings"],
        "manifest": manifest,
        "semantic_validation": semantic,
        "protocol_provenance": protocol_provenance,
        "stage0": {
            "claims": claims,
            "contracts": load_json(base / "stage0" / "contracts.json"),
            "readiness": load_json(base / "stage0" / "readiness.json"),
            "redaction_report": load_json(base / "stage0" / "redaction_report.json"),
            "leak_audit": load_json(base / "stage0" / "leak_audit.json"),
        }
        if s0
        else None,
        "stage1": {
            "match": (s1 or {}).get("match"),
            "traces": [
                load_json(p / "trace.json")
                for p in sorted((base / "stage1" / "replicas").glob("*"))
                if (p / "trace.json").exists()
            ],
            "targeted": (s1 or {}).get("targeted"),
            "rerun": (s1 or {}).get("rerun"),
            "diagnosis_md": read_text(base / "stage1" / "diagnosis.md"),
        }
        if s1
        else None,
        "stage2": (s2 or {}).get("review") if s2 else None,
        "stage3": (s3 or {}).get("space") if s3 else None,
        "ledger_summary": led["summary"],
        "attachments": ctx["attachments"],
    }
    return html, sidecar


def run(paper_id: str, force: bool = False) -> Path:
    """Write runs/<paper_id>/report/report.html and report.json. Always regenerates."""
    from .editorial import prepare
    prepare(paper_id)
    html, sidecar = build(paper_id)
    out = paths.run_dir(paper_id, "report")
    (out / "report.html").write_text(html)
    (out / "report.json").write_text(json.dumps(sidecar, indent=2, default=str) + "\n")
    size = len(html.encode())
    if size > 2_000_000:
        print(f"warning: report.html is {size / 1e6:.2f} MB (target < 2 MB)")
    print(f"report → {out / 'report.html'} ({size / 1024:.0f} KB)")
    return out / "report.html"

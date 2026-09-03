"""Append-only per-paper record of every model call: runs/<paper_id>/ledger.jsonl."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from . import paths
from .config import SUBSCRIPTION_ROUTES, shadow_price

NUMERIC_FIELDS = ("tokens_in", "tokens_out", "tokens_reasoning", "cost_usd", "cost_usd_equiv", "duration_s")


def ledger_path(paper_id: str):
    return paths.run_dir(paper_id) / "ledger.jsonl"


def record(paper_id: str, row: dict[str, Any]) -> str:
    """Append one call row. Returns the row id, which artifacts cite in meta.model_calls."""
    call_id = uuid.uuid4().hex[:12]
    out = {
        "id": call_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "paper_id": paper_id,
        **row,
    }
    if out.get("route") in SUBSCRIPTION_ROUTES:
        # Subscription seats are prepaid: the marginal spend of a call is zero.
        # For claude_p the CLI still reports a list-price equivalent, kept as
        # cost_usd_equiv for sizing, never summed into cost_usd.
        # Routes that report nothing (codex) get the list-equivalent from the
        # shadow price in models.toml, applied to every token the route reported.
        if out.get("cost_usd"):
            out.setdefault("cost_usd_equiv", out["cost_usd"])
        else:
            price = shadow_price(str(out.get("model") or ""))
            if price:
                tokens = sum(
                    float(out.get(f) or 0)
                    for f in ("tokens_in", "tokens_out", "tokens_reasoning")
                )
                out.setdefault("cost_usd_equiv", tokens * price / 1e6)
        out["cost_usd"] = 0.0
        out["cost_source"] = "subscription"
    else:
        out.setdefault("cost_source", "api")
    p = ledger_path(paper_id)
    with p.open("a") as f:
        f.write(json.dumps(out) + "\n")
    return call_id


def rows(paper_id: str) -> list[dict[str, Any]]:
    p = ledger_path(paper_id)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def summary(paper_id: str) -> dict[str, Any]:
    """Totals overall and grouped by route, model and stage."""
    all_rows = rows(paper_id)

    def blank() -> dict[str, Any]:
        return {"calls": 0, "ok": 0, **{f: 0.0 for f in NUMERIC_FIELDS}}

    groups: dict[str, dict[str, dict[str, Any]]] = {
        "route": defaultdict(blank),
        "model": defaultdict(blank),
        "stage": defaultdict(blank),
    }
    total = blank()
    for r in all_rows:
        buckets = [total] + [groups[k][str(r.get(k) or "?")] for k in groups]
        for b in buckets:
            b["calls"] += 1
            b["ok"] += 1 if r.get("ok", True) else 0
            for f in NUMERIC_FIELDS:
                b[f] += float(r.get(f) or 0)
    return {"paper_id": paper_id, "total": total, **{k: dict(v) for k, v in groups.items()}}


def format_summary(paper_id: str) -> str:
    s = summary(paper_id)
    if not s["total"]["calls"]:
        return f"no ledger rows for {paper_id}"
    header = f"{'group':<28}{'calls':>6}{'ok':>5}{'tok_in':>10}{'tok_out':>9}{'reason':>8}{'cost $':>10}{'equiv $':>10}"
    lines = [f"ledger summary — {paper_id}", header, "-" * len(header)]

    def line(label: str, b: dict[str, Any]) -> str:
        return (
            f"{label:<28}{b['calls']:>6}{b['ok']:>5}{int(b['tokens_in']):>10}"
            f"{int(b['tokens_out']):>9}{int(b['tokens_reasoning']):>8}"
            f"{b['cost_usd']:>10.4f}{b['cost_usd_equiv']:>10.4f}"
        )

    for key in ("stage", "route", "model"):
        for name, b in sorted(s[key].items()):
            lines.append(line(f"{key}:{name}", b))
        lines.append("")
    lines.append(line("TOTAL", s["total"]))
    lines.append("cost_usd excludes subscription routes; equiv $ is their list-price equivalent.")
    return "\n".join(lines)

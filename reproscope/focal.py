"""Bind the manifest's focal claim to extracted claims: shared by Stages 1, 2 and 3.

Deterministic first (manifest `claim_id` override, then numeric match against the
reported statistic, then description overlap); a cheap model call only when nothing
matches. Every consumer of "the focal claim" must go through `bind_focal_claim`.
"""

from __future__ import annotations

import math
import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from . import llm, paths
from .artifacts import ClaimRecord, EstimandContract
from .stage0.leakcheck import _DF_GROUP

# The quantity the specification curve is drawn in. A test statistic is the last
# resort: it mixes the effect with the sample size, so it moves for reasons the
# multiverse is not about.
QUANTITY_PREFERENCE = [
    "coefficient", "d", "r", "OR", "HR", "mean", "sd", "t", "F", "chi2", "other",
]
_TSTAT_KINDS = {"t", "F", "chi2"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s).lower())


_LEADING_COMPARATOR = re.compile(r"^\s*[<>]=?\s*")


def _as_float(x: Any) -> float | None:
    if isinstance(x, str):
        x = _LEADING_COMPARATOR.sub("", x)
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


class BindOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    claim_id: str
    rationale: str = ""



def _numbers_in(text: str) -> list[float]:
    return [float(m) for m in re.findall(r"-?(?:\d+\.?\d*|\.\d+)", text or "")]




def bind_focal_claim(
    manifest: paths.Manifest,
    claims: list[ClaimRecord],
    contracts: list[EstimandContract],
    *,
    paper_id: str | None = None,
    allow_llm: bool = True,
) -> dict[str, Any]:
    """Find the claims that carry the manifest's focal claim and pick the curve quantity.

    Deterministic first: the manifest's `reported.value` is the test statistic, so the
    claims printing it anchor the binding (narrowed to `reported.family` when the
    manifest names one). `reported.statistic` is the in-text sentence, and the other
    numbers in it (effect size, MSE, p) bind the claims of the anchors' own analysis
    only: a bare "1" or a df in that sentence matches unrelated claims everywhere else.
    Without an anchor every claim printing a sentence number is bound. A cheap model
    call breaks the tie only when nothing matches numerically.
    """
    reported = (manifest.focal_claim.reported if manifest.focal_claim else None)
    stat_text = (reported.statistic if reported else "") or ""
    stat_value = _as_float(reported.value if reported else None)
    family = getattr(reported, "family", None) if reported else None
    # Degrees of freedom sit inside the statistic label and are not claim values.
    sentence_numbers = _numbers_in(_DF_GROUP.sub(" ", stat_text))
    notes: list[str] = []

    def prints(c: ClaimRecord, numbers: list[float]) -> bool:
        v = _as_float(c.value)
        return v is not None and any(
            math.isclose(v, n, rel_tol=1e-6, abs_tol=1e-9) for n in numbers
        )

    matched: list[ClaimRecord] = []
    override = getattr(manifest.focal_claim, "claim_id", None) if manifest.focal_claim else None
    if override:
        matched = [c for c in claims if c.claim_id == override]
        notes.append(f"focal claim fixed by the manifest: {override}")
    if not matched and stat_value is not None:
        anchors = [c for c in claims if prints(c, [stat_value])]
        of_family = [c for c in anchors if family and c.quantity_kind == family]
        anchors = of_family or anchors
        if anchors:
            analyses = {
                ct.analysis_id for ct in contracts
                if any(a.claim_id in (ct.claim_ids or []) for a in anchors)
            }
            in_analysis = {
                cid for ct in contracts if ct.analysis_id in analyses
                for cid in (ct.claim_ids or [])
            }
            matched = anchors + [
                c for c in claims
                if c not in anchors and c.claim_id in in_analysis and prints(c, sentence_numbers)
            ]
    if not matched:
        matched = [c for c in claims if prints(c, sentence_numbers + ([stat_value] if stat_value is not None else []))]

    if not matched:
        # Fall back to text overlap between the claim description and the focal sentence.
        target = _norm(stat_text) or _norm(manifest.focal_claim.text if manifest.focal_claim else "")
        matched = [c for c in claims if c.description and _norm(c.description)[:80] in target]
        if matched:
            notes.append("no numeric match; claims bound by description overlap with the "
                         "focal sentence")

    if not matched and allow_llm and claims and paper_id:
        listing = "\n".join(
            f"- {c.claim_id}: kind={c.quantity_kind} value={c.value} — {(c.description or '')[:200]}"
            for c in claims
        )
        prompt = (
            "Which extracted claim below is the paper's focal claim?\n\n"
            f"Focal claim text: {manifest.focal_claim.text if manifest.focal_claim else ''}\n"
            f"Reported statistic as printed: {stat_text}\n\n"
            f"Extracted claims:\n{listing}\n\n"
            'Return JSON only: {"claim_id": "...", "rationale": "..."}'
        )
        r = llm.call("bind_focal", prompt, paper_id=paper_id, stage="3",
                     tier="cheap", schema=BindOut)
        if r.ok and r.parsed is not None:
            matched = [c for c in claims if c.claim_id == r.parsed.claim_id]
            notes.append(f"bound by cheap model call ({r.ledger_id}): {r.parsed.rationale}")

    if not matched:
        raise ValueError("could not bind the manifest focal claim to any claim in claims.json")

    def rank_of(c: ClaimRecord) -> int:
        kind = c.quantity_kind or "other"
        return QUANTITY_PREFERENCE.index(kind) if kind in QUANTITY_PREFERENCE else 99

    usable = [c for c in matched if c.quantity_kind not in {"p_value", "n"}]
    usable.sort(key=rank_of)
    if not usable:
        raise ValueError("focal claim matched only p-values / sample sizes; no estimate to rank")
    chosen = usable[0]

    kind = chosen.quantity_kind or "other"
    value = _as_float(chosen.value)
    derived = False
    if kind in _TSTAT_KINDS and value is not None:
        # Only a test statistic is reported: convert to d so the curve is on an effect scale.
        df = _as_float(reported.df if reported else None)
        if kind == "t" and df and df > 0:
            value = 2 * value / math.sqrt(df)
            kind, derived = "d", True
            notes.append(
                f"only a t statistic was reported for the focal estimate; converted with "
                f"d = 2t/sqrt(df) = {value:.4f}, which assumes two independent groups of "
                f"equal size"
            )
        else:
            notes.append(f"focal estimate stays on the {kind} scale; no conversion available")

    focal_contract = next(
        (ct for ct in contracts if chosen.claim_id in (ct.claim_ids or [])), None
    ) or next(
        (ct for ct in contracts
         if any(c.claim_id in (ct.claim_ids or []) for c in matched)), None
    ) or (contracts[0] if contracts else None)
    if focal_contract is None:
        raise ValueError("no estimand contract to hang the focal claim on")

    return {
        "claim_ids": [c.claim_id for c in matched],
        "analysis_id": focal_contract.analysis_id,
        "focal_quantity": {
            "claim_id": chosen.claim_id,
            "kind": kind,
            "reported_value": value,
            "reported_precision": chosen.precision,
            "derived_from": "t" if derived else None,
            "description": chosen.description,
        },
        "focal_claim_text": manifest.focal_claim.text if manifest.focal_claim else None,
        "reported_statistic": stat_text,
        "notes": notes,
    }



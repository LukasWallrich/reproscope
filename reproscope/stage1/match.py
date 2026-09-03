"""Compare each replica's results with the paper's reported values.

Two steps per claim x replica. A cheap model links the claim to one entry in the
replica's results file, seeing the claim's description but never its value. The
grade is then deterministic, by quantity_kind, following the design's matching
rules.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .. import artifacts, llm, paths
from ._prompt import fill
from . import blind, replicas

P_THRESHOLDS = (0.05, 0.01, 0.001)
BAND_EDGES = ((0.02, "A"), (0.20, "B"), (0.40, "C"))
SMALL = 0.001  # |reported| below this uses the absolute rule
SMALL_TOL = 0.002
LOG_KINDS = {"OR", "HR"}
UNSIGNED_KINDS = {"sd", "n", "F", "chi2", "p_value", "se", "eta2", "percent"}
BLIND_CLAIM_FIELDS = {"value", "precision", "uncertainty"}
PROMPTS = ("stage1_link_results", "stage1_trace_choices")


class LinkResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    found: bool = False
    value: float | None = None
    se: float | None = None
    ci_lower: float | None = None
    ci_upper: float | None = None
    n: int | None = None
    unit_note: str | None = None
    note: str | None = None
    # Set when the link step itself could not run or returned nothing usable. The
    # replica's evidence is then unknown, which is different from a replica that
    # computed nothing for the claim.
    error: str | None = None


class TraceEquivalence(BaseModel):
    model_config = ConfigDict(extra="allow")

    fields: list[dict[str, Any]] = []
    agreement: float | None = None
    notable_divergences: list[str] = []


# --- deterministic grading ------------------------------------------------

_COMPARATOR = re.compile(r"^\s*([<>]=?)\s*(-?(?:\d+\.?\d*|\.\d+))\s*$")


def parse_reported(value: float | str | None) -> tuple[float | None, str | None]:
    """Return (number, comparator). `"< .001"` becomes (0.001, "<")."""
    if value is None or isinstance(value, (int, float)):
        return (float(value) if value is not None else None), None
    m = _COMPARATOR.match(str(value))
    if m:
        return float(m.group(2)), m.group(1)
    try:
        return float(str(value).strip()), None
    except ValueError:
        return None, None


def _round_to(value: float, precision: int | None) -> float:
    return round(value, precision) if precision is not None else value


def _rel_band(reported: float, replicated: float) -> tuple[str, float]:
    diff = replicated - reported
    if abs(reported) < SMALL:
        return ("A" if abs(diff) < SMALL_TOL else "fail"), abs(diff)
    rel = abs(diff) / abs(reported)
    for edge, band in BAND_EDGES:
        if rel < edge:
            return band, rel
    return "fail", rel


def _satisfies(comparator: str, value: float, bound: float) -> bool:
    return {
        "<": value < bound,
        "<=": value <= bound,
        ">": value > bound,
        ">=": value >= bound,
    }[comparator]


def _grade_p(reported: float, replicated: float) -> tuple[str, float]:
    """Same side of .05/.01/.001, and either both below .001 or close in relative terms.

    A when the two are effectively the same number (or both below .001), B when
    they merely agree on every threshold, fail otherwise.
    """
    same_side = all((reported < t) == (replicated < t) for t in P_THRESHOLDS)
    both_tiny = reported < 0.001 and replicated < 0.001
    rel = abs(replicated - reported) / abs(reported) if reported else math.inf
    if not (same_side and (both_tiny or rel < 0.5)):
        return "fail", rel
    return ("A" if both_tiny or rel < 0.02 else "B"), rel


def grade(
    quantity_kind: str | None,
    reported: float | None,
    replicated: float | None,
    *,
    precision: int | None = None,
    se: float | None = None,
    comparator: str | None = None,
) -> dict[str, Any]:
    """Band one claim x replica pair. Returns band, diffs, sign and sigma rule."""
    out: dict[str, Any] = {
        "band": None, "raw_diff": None, "std_diff": None,
        "sign_match": None, "sigma_rule": "na", "rule": None,
    }
    if reported is None or replicated is None:
        out["band"] = "fail" if replicated is None else None
        out["rule"] = "no value to compare"
        return out

    out["raw_diff"] = replicated - reported
    if se:
        out["std_diff"] = (replicated - reported) / se
        out["sigma_rule"] = "within" if abs(replicated - reported) / se <= 2 else "outside"

    if comparator:
        out["band"] = "A" if _satisfies(comparator, replicated, reported) else "fail"
        out["rule"] = f"comparator {comparator}{reported:g}: threshold side only"
        out["raw_diff"] = None
        return out

    rounded = _round_to(replicated, precision)
    kind = quantity_kind or "other"

    if kind == "p_value":
        band, rel = _grade_p(reported, replicated)
        out.update(band=band, rule=f"p-value thresholds; relative diff {rel:.3g}")
        return out

    if kind == "n":
        rel = abs(rounded - reported) / abs(reported) if reported else math.inf
        out.update(
            band="A" if rounded == reported else ("B" if rel <= 0.01 else "fail"),
            rule=f"n: exact or within 1% (relative diff {rel:.3g})",
        )
        return out

    if kind not in UNSIGNED_KINDS and abs(reported) >= SMALL:
        out["sign_match"] = (rounded >= 0) == (reported >= 0)
        if not out["sign_match"]:
            out.update(band="fail", rule="sign gate: opposite signs")
            return out

    if kind in LOG_KINDS:
        if rounded <= 0 or reported <= 0:
            out.update(band="fail", rule="ratio must be positive to compare on the log scale")
            return out
        band, rel = _rel_band(math.log(reported), math.log(rounded))
        out.update(band=band, rule=f"log-scale relative diff {rel:.3g}")
        return out

    band, rel = _rel_band(reported, rounded)
    out.update(band=band, rule=f"relative diff {rel:.3g} (A<2%, B<20%, C<40%)")
    return out


def unit_candidates(replicated: float) -> list[tuple[float, str]]:
    return [
        (replicated * 100, "rescaled x100 (proportion -> percent)"),
        (replicated / 100, "rescaled /100 (percent -> proportion)"),
        (-replicated, "sign flipped (contrast coded the other way)"),
    ]


BAND_ORDER = {"A": 0, "B": 1, "C": 2, "fail": 3, None: 4}


def grade_with_unit_check(
    quantity_kind: str | None,
    reported: float | None,
    replicated: float | None,
    *,
    precision: int | None = None,
    se: float | None = None,
    comparator: str | None = None,
    unit_note: str | None = None,
) -> dict[str, Any]:
    """Grade as reported; if the linker flagged a rescaling, try the obvious ones.

    A rescaled candidate is used only when it lands in a strictly better band, and
    the rescaling applied is recorded in unit_check.
    """
    base = grade(quantity_kind, reported, replicated,
                 precision=precision, se=se, comparator=comparator)
    base["unit_check"] = unit_note or "none"
    base["replicated_used"] = replicated
    flagged = bool(unit_note) and unit_note.strip().lower() not in {"none", "n/a", "no", ""}
    if not flagged or replicated is None or reported is None:
        return base
    best = base
    for candidate, label in unit_candidates(replicated):
        alt = grade(quantity_kind, reported, candidate,
                    precision=precision, se=se, comparator=comparator)
        if BAND_ORDER[alt["band"]] < BAND_ORDER[best["band"]]:
            alt["unit_check"] = f"{unit_note}; {label}"
            alt["replicated_used"] = candidate
            best = alt
    return best


# --- linking --------------------------------------------------------------


def blind_claim(claim: artifacts.ClaimRecord) -> str:
    data = claim.model_dump(exclude_none=True)
    for f in BLIND_CLAIM_FIELDS | {"meta", "extraction", "state"}:
        data.pop(f, None)
    return json.dumps(data, indent=2)


def link(
    paper_id: str, claim: artifacts.ClaimRecord, results_text: str, trace_text: str
) -> tuple[LinkResult, str | None]:
    direct = direct_link(claim.claim_id, results_text)
    if direct is not None:
        return direct, None
    if results_keyed(results_text):
        # The replica keyed its results by claim_id and has no value for this one:
        # it did not compute it. No model call needed.
        return LinkResult(found=False, note="not in the replica's keyed results.json"), None
    prompt = fill(
        "stage1_link_results",
        claim=blind_claim(claim),
        results=results_text[:20_000],
        trace=trace_text[:20_000],
    )
    r = llm.call("link_results", prompt, paper_id=paper_id, stage="1",
                 tier="cheap", schema=LinkResult)
    if r.parsed is None:
        return LinkResult(error=f"link call failed: {r.error}"), r.ledger_id
    linked: LinkResult = r.parsed  # type: ignore[assignment]
    if linked.found and linked.value is None:
        linked.error = "link call reported a match but returned no value"
    return linked, r.ledger_id


def results_keyed(results_text: str) -> bool:
    """Whether the replica's results.json uses claim_id keys (the TASK.md format)."""
    try:
        entries = json.loads(results_text).get("results", [])
    except (json.JSONDecodeError, AttributeError):
        return False
    return any(isinstance(e, dict) and e.get("claim_id") for e in entries)


def direct_link(claim_id: str, results_text: str) -> LinkResult | None:
    """The replica's own results entry for this claim_id, when it wrote one with a value.

    Replicas are asked to key results by claim_id, so the entry is the link; the model
    call is reserved for claims the replica did not key (or keyed without a value).
    """
    try:
        entries = json.loads(results_text).get("results", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    for e in entries:
        if isinstance(e, dict) and e.get("claim_id") == claim_id and e.get("value") is not None:
            try:
                value = float(e["value"])
            except (TypeError, ValueError):
                return None
            def _f(k):
                try:
                    return float(e[k]) if e.get(k) is not None else None
                except (TypeError, ValueError):
                    return None
            n = e.get("n")
            return LinkResult(
                found=True, value=value, se=_f("se"), ci_lower=_f("ci_lower"),
                ci_upper=_f("ci_upper"), n=int(n) if isinstance(n, (int, float)) else None,
                unit_note="none", note="direct: replica keyed this claim_id in results.json",
            )
    return None


def trace_equivalence(paper_id: str, traces: list[artifacts.ReplicaDecisionTrace]):
    """One cheap call over the two fields that carry the analytical choices.

    `open_choices` and `model_formula` are where replicas actually diverge; the rest of
    a trace is bookkeeping that costs tokens without moving the agreement score.
    """
    if len(traces) < 2:
        return TraceEquivalence(agreement=None, notable_divergences=[]), None
    payload = json.dumps(
        [
            {
                "replica_id": t.replica_id,
                "open_choices": t.open_choices,
                "model_formula": t.model_formula,
            }
            for t in traces
        ],
        indent=2,
        default=str,
    )
    r = llm.call("trace_choices", fill("stage1_trace_choices", traces=payload[:60_000]),
                 paper_id=paper_id, stage="1", tier="cheap", schema=TraceEquivalence,
                 reasoning_max_tokens=256)
    if r.parsed is None:
        return TraceEquivalence(agreement=None, notable_divergences=[]), r.ledger_id
    return r.parsed, r.ledger_id  # type: ignore[return-value]


# --- the stage step -------------------------------------------------------


def _results_text(paper_id: str, replica_id: str) -> str:
    p = blind.replica_dir(paper_id, replica_id) / "work" / "out" / "results.json"
    return p.read_text() if p.exists() else ""


def replica_fingerprint(paper_id: str, traces: list[artifacts.ReplicaDecisionTrace]) -> dict[str, str]:
    """Cache key for match.json: each replica's analytical content and its results.

    The trace contributes `content_hash` (everything but `meta`), so re-saving a trace
    with unchanged content does not invalidate the match; the results file is hashed as
    bytes, so a corrected results.json does.
    """
    out: dict[str, str] = {}
    for t in traces:
        results = blind.replica_dir(paper_id, t.replica_id) / "work" / "out" / "results.json"
        h = hashlib.sha256(artifacts.content_hash(t).encode())
        h.update(results.read_bytes() if results.exists() else b"")
        out[t.replica_id] = h.hexdigest()
    return out


def closest_replicas(
    result: artifacts.ComparableResult, claim_id: str, n: int = 1
) -> list[str]:
    """Replica ids ranked by how close they came on one claim, closest first.

    Distance is |std_diff| where the replica reported a standard error, and the
    relative difference otherwise. Rows without a replicated value are not ranked.
    """
    scored: list[tuple[float, str]] = []
    for row in result.rows:
        if row.claim_id != claim_id or row.replicated is None or row.state == "abstained":
            continue
        if row.std_diff is not None:
            distance = abs(row.std_diff)
        elif row.reported not in (None, 0) and row.raw_diff is not None:
            distance = abs(row.raw_diff) / abs(row.reported)
        elif row.raw_diff is not None:
            distance = abs(row.raw_diff)
        else:
            continue
        scored.append((distance, row.replica_id))
    scored.sort()
    return [rid for _, rid in scored[:n]]


def run(paper_id: str, force: bool = False) -> artifacts.ComparableResult:
    out_path = paths.run_dir(paper_id, 1) / "match.json"
    claims = blind.claims(paper_id)
    contracts = blind.contracts(paper_id)
    traces = [t for t in replicas.load_traces(paper_id) if t.ran]
    fingerprint = replica_fingerprint(paper_id, traces)

    if out_path.exists() and not force:
        loaded = artifacts.load(artifacts.ComparableResult, out_path)
        cached = loaded if isinstance(loaded, artifacts.ComparableResult) else loaded[0]
        fresh = not artifacts.prompt_stale(cached, PROMPTS)
        if cached.meta and cached.meta.inputs == fingerprint and fresh:
            return cached

    call_ids: list[str] = []

    equivalence, eq_call = trace_equivalence(paper_id, traces)
    if eq_call:
        call_ids.append(eq_call)
    analysis_of = {cid: c.analysis_id for c in contracts for cid in c.claim_ids}

    # Only claims the replicas were asked about are linked; claims from analyses that
    # abstained at intake (no data) get an abstained summary and no model call.
    s0 = blind.stage0_dir(paper_id)
    bound_ids = blind.bound_claim_ids(blind.blind_packet(paper_id, s0 / "blind_contract.json"))
    results_texts = {t.replica_id: _results_text(paper_id, t.replica_id) for t in traces}
    trace_json = {t.replica_id: t.model_dump_json() for t in traces}

    def _link(claim, trace):
        return link(paper_id, claim, results_texts[trace.replica_id], trace_json[trace.replica_id])

    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=6)
    linkable = [c for c in claims if c.claim_id in bound_ids]
    futures = {(c.claim_id, t.replica_id): pool.submit(_link, c, t) for c in linkable for t in traces}

    rows: list[artifacts.ComparableRow] = []
    summaries: list[artifacts.MatchSummary] = []
    for claim in claims:
        reported, comparator = parse_reported(claim.value)
        comparator = comparator or getattr(claim, "comparator", None)
        if comparator == "=":
            comparator = None
        values: list[float] = []
        matched = 0
        matched_a = 0
        found = 0
        abstained = 0
        if claim.claim_id not in bound_ids:
            summaries.append(
                artifacts.MatchSummary(
                    claim_id=claim.claim_id, n_ran=0, n_found=0, n_matched=0,
                    importance=claim.importance, analysis_id=analysis_of.get(claim.claim_id),
                    state="abstained",
                    abstain_reason="analysis abstained at intake: no data file covers it",
                )
            )
            continue
        for trace in traces:
            linked, call = futures[(claim.claim_id, trace.replica_id)].result()
            if call:
                call_ids.append(call)
            # A failed link call and a replica that simply produced no value for this
            # claim carry the same evidential weight: none. Both abstain rather than
            # grading a missing value as band "fail".
            if linked.error or not linked.found:
                abstained += 1
                rows.append(
                    artifacts.ComparableRow(
                        claim_id=claim.claim_id,
                        replica_id=trace.replica_id,
                        quantity_kind=claim.quantity_kind,
                        reported=reported,
                        comparator=comparator,
                        band=None,
                        state="abstained",
                        abstain_reason=linked.error
                        or "replica produced no value for this claim",
                        link_note=linked.note,
                    )
                )
                continue
            if linked.found and linked.value is not None:
                found += 1
            graded = grade_with_unit_check(
                claim.quantity_kind, reported,
                linked.value if linked.found else None,
                precision=claim.precision, se=linked.se, comparator=comparator,
                unit_note=linked.unit_note,
            )
            if graded["band"] in {"A", "B"}:
                matched += 1
            if graded["band"] == "A":
                matched_a += 1
            if linked.found and linked.value is not None:
                values.append(graded["replicated_used"])
            rows.append(
                artifacts.ComparableRow(
                    claim_id=claim.claim_id,
                    replica_id=trace.replica_id,
                    quantity_kind=claim.quantity_kind,
                    reported=reported,
                    replicated=graded["replicated_used"],
                    unit_check=graded["unit_check"],
                    raw_diff=graded["raw_diff"],
                    std_diff=graded["std_diff"],
                    sign_match=graded["sign_match"],
                    band=graded["band"],
                    sigma_rule=graded["sigma_rule"],
                    comparator=comparator,
                    rule=graded["rule"],
                    se=linked.se,
                    n=linked.n,
                    link_note=linked.note,
                )
            )
        n_ran = len(traces) - abstained  # replicas that produced a usable row
        cv = None
        if len(values) > 1 and statistics.fmean(values):
            cv = statistics.stdev(values) / abs(statistics.fmean(values))
        summaries.append(
            artifacts.MatchSummary(
                claim_id=claim.claim_id,
                n_ran=n_ran,
                n_abstained=abstained,
                n_found=found,
                n_matched=matched,
                fraction_matched=(matched / n_ran) if n_ran else None,
                fraction_a=(matched_a / n_ran) if n_ran else None,
                importance=claim.importance,
                dispersion=artifacts.Dispersion(
                    decision_agreement=equivalence.agreement, numeric_cv=cv
                ),
                analysis_id=analysis_of.get(claim.claim_id),
                state="complete" if n_ran else "abstained",
                abstain_reason=None if n_ran else "no replica produced a usable value for this claim",
            )
        )

    result = artifacts.ComparableResult(
        rows=rows,
        summaries=summaries,
        trace_equivalence=equivalence.model_dump(),
        state="complete" if traces else "abstained",
        abstain_reason=None if traces else "no replica produced runnable results",
        meta=artifacts.ArtifactMeta(
            artifact="ComparableResult", stage="1", model_calls=call_ids,
            inputs=fingerprint,
            prompt_versions={name: artifacts.prompt_version(name) for name in PROMPTS},
        ),
    )
    artifacts.save(result, out_path)
    return result


def targeted_trigger(
    result: artifacts.ComparableResult, claim_ids: list[str]
) -> tuple[bool, list[str]]:
    """Whether the focal claim missed: under half the usable rows in A/B, none in A, or CV above 0.2.

    `claim_ids` are the claims carrying the focal claim; nothing else can trigger the arm.
    Abstained rows are already out of `n_ran` and the fractions.
    """
    wanted = set(claim_ids)
    reasons = []
    for s in result.summaries:
        if s.claim_id not in wanted or not s.n_ran:
            continue
        if s.fraction_matched is None:  # abstained at intake: nothing to reconstruct
            continue
        if (s.fraction_matched or 0) < 0.5:
            reasons.append(f"{s.claim_id}: {s.fraction_matched:.0%} of {s.n_ran} replicas in A/B")
        elif getattr(s, "fraction_a", None) == 0:
            reasons.append(f"{s.claim_id}: no replica reached band A")
        cv = s.dispersion.numeric_cv if s.dispersion else None
        if cv is not None and cv > 0.2:
            reasons.append(f"{s.claim_id}: numeric CV {cv:.2f} across replicas")
    return bool(reasons), reasons

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
from . import blind, replicas, audit

P_THRESHOLDS = (0.05, 0.01, 0.001)
BAND_EDGES = ((0.02, "A"), (0.20, "B"), (0.40, "C"))
SMALL = 0.001  # |reported| below this uses the absolute rule
SMALL_TOL = 0.002
LOG_KINDS = {"OR", "HR"}
UNSIGNED_KINDS = {"sd", "n", "F", "chi2", "p_value", "se", "eta2", "percent"}
BLIND_CLAIM_FIELDS = {"value", "precision", "uncertainty", "source_quote", "source_anchor_quote", "source_anchor_scope", "source_region", "abstain_reason"}
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
    error_kind: str | None = None
    source_analysis_ids: list[str] = []


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
    if precision is None:
        return value
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(str(value)).quantize(Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP))


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
    """Band one claim x replica pair. Returns band, diffs, sign and sigma rule.

    `replicated_used` is the supplied canonical value. The grader never chooses
    an orientation or unit transformation by closeness to the reported result.
    """
    out: dict[str, Any] = {
        "band": None, "raw_diff": None, "std_diff": None,
        "sign_match": None, "sigma_rule": "na", "rule": None,
        "replicated_used": replicated, "direction_flipped": False,
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
        satisfied = _satisfies(comparator, replicated, reported)
        out["band"] = "A" if satisfied else "fail"
        out["bound_satisfied"] = satisfied
        out["rule"] = f"comparator {comparator}{reported:g}: literal bound {'satisfied' if satisfied else 'not satisfied'}"
        # Rounding can explain a displayed family bound, but never changes its
        # truth value or the grade. Conventional p cutoffs remain exact thresholds.
        conventional_cutoff = quantity_kind == "p_value" and reported in P_THRESHOLDS
        if not satisfied and precision is not None and not conventional_cutoff:
            half_unit = .5 * 10.0 ** (-precision)
            edge = reported + half_unit if comparator.startswith("<") else reported - half_unit
            out["bound_rounding_compatible"] = _satisfies(comparator, replicated, edge)
            if out["bound_rounding_compatible"]:
                out["rule"] += "; compatible with rounding the bound, without satisfying the printed inequality"
        out["raw_diff"] = None
        return out

    rounded = _round_to(replicated, precision)
    kind = quantity_kind or "other"

    if kind == "p_value":
        if precision is not None and rounded == reported:
            out.update(band="A", rule="p-value equality matches printed rounding; rounded equality does not establish a strict significance bound")
            return out
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
        out["sign_match"] = None if replicated == 0 else (replicated > 0) == (reported > 0)
        if out["sign_match"] is False:
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
    """Grade the supplied canonical value and preserve any explicit unit note."""
    base = grade(quantity_kind, reported, replicated,
                 precision=precision, se=se, comparator=comparator)
    base["unit_check"] = unit_note or "none"
    # A prose linker hint cannot authorise a transformation. Conversion must be
    # fixed in the semantic contract and applied before calling the grader.
    return base


# --- linking --------------------------------------------------------------


def blind_claim(claim: artifacts.ClaimRecord) -> str:
    data = claim.model_dump(exclude_none=True)
    for f in BLIND_CLAIM_FIELDS | {"meta", "extraction", "state"}:
        data.pop(f, None)
    return json.dumps(data, indent=2)


def link(
    paper_id: str, claim: artifacts.ClaimRecord, results_text: str, trace_text: str
) -> tuple[LinkResult, str | None]:
    from ..statistic_metadata import canonical_aggregation
    direct = direct_link(claim.claim_id, results_text, quantity_kind=claim.quantity_kind,
                         comparator=getattr(claim, "comparator", None),
                         aggregation=canonical_aggregation(claim), member_ids=claim.member_ids)
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


def direct_link(claim_id: str, results_text: str, *, quantity_kind=None, comparator=None, aggregation="scalar", member_ids=None) -> LinkResult | None:
    """Link a shared source claim only when its repeated numerical outputs agree."""
    try:
        entries = json.loads(results_text).get("results", [])
    except (json.JSONDecodeError, AttributeError):
        return None
    rows = [e for e in entries if isinstance(e, dict) and e.get("claim_id") == claim_id]
    valued = [e for e in rows if e.get("value") is not None]
    if not valued:
        return None
    aggregations = []
    normalised = []
    for row in valued:
        raw = row["value"]
        if aggregation != "scalar":
            expected_members = member_ids or []
            got = row.get("member_ids") or []
            if not expected_members or len(got) != len(set(got)) or set(got) != set(expected_members):
                return LinkResult(error="aggregate membership absent or inconsistent", error_kind="invalid")
            if not isinstance(raw, list):
                return LinkResult(error="aggregate target requires values for every declared member", error_kind="invalid")
        if isinstance(raw, list):
            # "All p > c" is a minimum-p claim; "all p < c" is a maximum-p
            # claim. The bound defines the aggregation, never numerical agreement.
            if (aggregation not in {"all", "any", "min", "max"} or len(raw) != len(member_ids or [])
                    or quantity_kind not in {"p_value", "r", "t", "d"} or not raw
                    or (aggregation in {"all", "any"} and comparator not in {"<", "<=", ">", ">="})):
                return LinkResult(error="vector output has no supported explicit bound", error_kind="ambiguous")
            try:
                vector = [float(x) for x in raw]
                lower, upper = (0, 1) if quantity_kind == "p_value" else (-1, 1) if quantity_kind == "r" else (-math.inf, math.inf)
                if any(isinstance(x, bool) for x in raw) or any(not math.isfinite(x) or not lower <= x <= upper for x in vector):
                    raise ValueError("invalid bounded statistic")
            except (TypeError, ValueError, OverflowError):
                return LinkResult(error=f"invalid {quantity_kind} vector", error_kind="invalid")
            use_minimum = aggregation == "min" or (aggregation == "all" and comparator.startswith(">")) or (aggregation == "any" and comparator.startswith("<"))
            row = {**row, "value": min(vector) if use_minimum else max(vector)}
            aggregations.append(("min" if use_minimum else "max") + f"({quantity_kind}) from declared aggregation and bound")
        normalised.append(row)
    valued = normalised
    analyses = sorted({str(e["analysis_id"]) for e in valued if e.get("analysis_id") is not None})
    from ..execution import equal
    merged = {}
    for field in ("value", "se", "ci_lower", "ci_upper", "n"):
        values = []
        for row in valued:
            raw = row.get(field)
            if raw is None:
                continue
            try:
                value = float(raw)
                if isinstance(raw, bool) or not math.isfinite(value) or (field == "n" and value != int(value)):
                    raise ValueError("invalid numeric value")
            except (ValueError, TypeError, OverflowError):
                return LinkResult(error=f"invalid {field} in keyed result for {claim_id}", error_kind="invalid",
                                  source_analysis_ids=analyses)
            values.append(value)
        if values and any(not equal(values[0], value) for value in values[1:]):
            return LinkResult(error=f"conflicting repeated {field} outputs for {claim_id}", error_kind="ambiguous",
                              note=json.dumps({"analysis_ids": analyses, "field": field, "values": values}),
                              source_analysis_ids=analyses)
        merged[field] = values[0] if values else None
    if merged["n"] is not None:
        merged["n"] = int(merged["n"])
    return LinkResult(found=True, **merged, unit_note="none", source_analysis_ids=analyses,
                      note="direct: agreeing keyed outputs from analyses " + ", ".join(analyses)
                           + ("; " + "; ".join(sorted(set(aggregations))) if aggregations else ""))


def trace_equivalence(paper_id: str, traces: list[artifacts.ReplicaDecisionTrace]):
    """Deterministic agreement among independently checked execution fields."""
    fields, proportions = [], []
    keys = ("family", "x", "y", "alternative", "n", "effect_metric", "included_ids")
    evidence = {t.replica_id: getattr(t, "execution_evidence", {}) for t in traces}
    analyses = sorted({a for e in evidence.values() for a in e.get("analyses", {})})
    for aid in analyses:
        for key in keys:
            groups, unknown = {}, []
            for trace in traces:
                item = evidence[trace.replica_id].get("analyses", {}).get(aid, {})
                if item.get("status") != "verified" or item.get(key) is None:
                    unknown.append(trace.replica_id)
                else:
                    raw = sorted(item[key], key=str) if key == "included_ids" else item[key]
                    value = json.dumps(raw, sort_keys=True)
                    groups.setdefault(value, []).append(trace.replica_id)
            known = sum(map(len, groups.values()))
            agreement = max(map(len, groups.values())) / known if known >= 2 else None
            if agreement is not None:
                proportions.append(agreement)
            fields.append({"analysis_id": aid, "field": key, "groups": list(groups.values()),
                           "unknown": unknown, "known": known, "planned": len(traces),
                           "agreement": agreement})
    return TraceEquivalence(fields=fields,
        agreement=sum(proportions)/len(proportions) if proportions else None,
        notable_divergences=[], basis="verified structured execution; unknowns excluded explicitly",
        replica_status={t.replica_id: {"ran": t.ran, "audit": audit.acceptance(t.hardcoding_audit)} for t in traces}), None


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


def mirror_ci_bounds(
    rows: list[artifacts.ComparableRow],
    links: dict[tuple[str, str], LinkResult],
    claims_by_id: dict[str, artifacts.ClaimRecord],
    analysis_of: dict[str, str | None],
) -> None:
    """Compatibility entry point: result-selected mirroring is prohibited.

    Use apply_declared_transform before grading when an intake-authorised mapping
    defines the orientation. A neighbouring estimate's match cannot authorise it.
    """
    return None


def apply_declared_transform(value, *, scale=1., ci=None, se=None, provenance=None):
    if not provenance or not math.isfinite(scale) or scale == 0:
        raise ValueError("normalisation requires a finite nonzero scale and intake provenance")
    return {"value": value * scale, "se": abs(scale) * se if se is not None else None,
            "ci": sorted(x * scale for x in ci) if ci is not None else None,
            "normalisation": {"scale": scale, "provenance": provenance}}


def run(paper_id: str, force: bool = False) -> artifacts.ComparableResult:
    out_path = paths.run_dir(paper_id, 1) / "match.json"
    claims = blind.claims(paper_id)
    contracts = blind.contracts(paper_id)
    from .. import source_direction, provenance
    direction_record = source_direction.run(paper_id)
    directions = {r['analysis_id']: r for r in direction_record['items']}
    traces = replicas.load_traces(paper_id)
    from . import inputs as stage_inputs
    fingerprint = {**stage_inputs(paper_id), **replica_fingerprint(paper_id, traces)}
    fingerprint['source_direction'] = provenance.digest(direction_record)

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
    assignment_path = blind.stage0_dir(paper_id) / "contract_assignments.json"
    assignment_reasons = {u["claim_id"]: u["reason"] + ": " + u["note"] for u in json.loads(assignment_path.read_text()).get("unassigned", [])} if assignment_path.exists() else {}
    readiness_file = blind.stage0_dir(paper_id) / "readiness.json"
    readiness_reasons = json.loads(readiness_file.read_text()).get("per_analysis_reasons", {}) if readiness_file.exists() else {}
    readiness_outcomes = json.loads(readiness_file.read_text()).get("per_analysis_outcome", {}) if readiness_file.exists() else {}

    # Only claims the replicas were asked about are linked; claims from analyses that
    # abstained at intake (no data) get an abstained summary and no model call.
    s0 = blind.stage0_dir(paper_id)
    packet = blind.blind_packet(paper_id, s0 / "blind_contract.json")
    bound_ids = blind.bound_claim_ids(packet)
    packet_quantities = {q["claim_id"]: q for a in packet["analyses"] for q in a["quantities"]}
    claims = [c.model_copy(update={"member_ids": packet_quantities.get(c.claim_id, {}).get("member_ids", c.member_ids)}) for c in claims]
    results_texts = {t.replica_id: _results_text(paper_id, t.replica_id) for t in traces}
    trace_json = {t.replica_id: t.model_dump_json() for t in traces}

    def _link(claim, trace):
        return link(paper_id, claim, results_texts[trace.replica_id], trace_json[trace.replica_id])

    from concurrent.futures import ThreadPoolExecutor
    pool = ThreadPoolExecutor(max_workers=6)
    from ..source_integrity import source_status
    source = source_status(claims)
    linkable = [c for c in claims if c.claim_id in bound_ids and c.claim_id not in source["invalid_claims"]
                and c.quantity_role != "supplied_fact"]
    futures = {(c.claim_id, t.replica_id): pool.submit(_link, c, t)
               for c in linkable for t in traces if t.ran
               and audit.acceptance(t.hardcoding_audit) == "accepted"}

    # Grade every claim x replica pair first. The CI-mirroring pass below needs a whole
    # analysis's rows, and the per-claim summaries are counted from the rows it leaves.
    rows: list[artifacts.ComparableRow] = []
    links: dict[tuple[str, str], LinkResult] = {}
    claims_by_id = {c.claim_id: c for c in claims}
    for claim in claims:
        reported, comparator = parse_reported(claim.value)
        comparator = comparator or getattr(claim, "comparator", None)
        if comparator == "=":
            comparator = None
        if claim.claim_id not in bound_ids:
            continue
        for trace in traces:
            source_reason = source["invalid_claims"].get(claim.claim_id)
            if source_reason or claim.quantity_role == "supplied_fact":
                rows.append(artifacts.ComparableRow(claim_id=claim.claim_id, replica_id=trace.replica_id,
                    analysis_id=analysis_of.get(claim.claim_id), quantity_kind=claim.quantity_kind,
                    reported=reported, state="abstained", band=None,
                    outcome_status="input_invalid" if source_reason else "supplied_fact",
                    abstain_reason=source_reason or "supplied fact; no independent computation credit"))
                continue
            invalid_claims = (trace.hardcoding_audit.get("adjudication") or {}).get("invalid_claims") or {}
            if claim.claim_id in invalid_claims:
                rows.append(artifacts.ComparableRow(
                    claim_id=claim.claim_id, replica_id=trace.replica_id,
                    analysis_id=analysis_of.get(claim.claim_id), quantity_kind=claim.quantity_kind,
                    reported=reported, state="abstained", band=None, outcome_status="invalid",
                    abstain_reason=str(invalid_claims[claim.claim_id])))
                continue
            if not trace.ran or audit.acceptance(trace.hardcoding_audit) != "accepted":
                rejected = audit.acceptance(trace.hardcoding_audit) == "rejected"
                rows.append(artifacts.ComparableRow(
                    claim_id=claim.claim_id, replica_id=trace.replica_id,
                    analysis_id=analysis_of.get(claim.claim_id), quantity_kind=claim.quantity_kind,
                    reported=reported, state="abstained", band=None,
                    outcome_status="replica_failed" if not trace.ran else "invalid" if rejected else "audit_unresolved",
                    abstain_reason=(trace.abstain_reason or "replica failed") if not trace.ran else "audit rejected statistical outputs" if rejected else "audit requires adjudication"))
                continue
            linked, call = futures[(claim.claim_id, trace.replica_id)].result()
            links[(claim.claim_id, trace.replica_id)] = linked
            if call:
                call_ids.append(call)
            # A failed link call and a replica that simply produced no value for this
            # claim carry the same evidential weight: none. Both abstain rather than
            # grading a missing value as band "fail".
            if linked.error or not linked.found:
                rows.append(
                    artifacts.ComparableRow(
                        claim_id=claim.claim_id,
                        replica_id=trace.replica_id,
                        analysis_id=analysis_of.get(claim.claim_id),
                        outcome_status="invalid" if linked.error_kind == "invalid" else "link_failed" if linked.error else "omitted",
                        link_error_kind=linked.error_kind,
                        quantity_kind=claim.quantity_kind,
                        reported=reported,
                        comparator=comparator,
                        band=None,
                        state="abstained",
                        abstain_reason=linked.error
                        or "replica produced no value for this claim",
                        link_note=linked.note,
                        source_analysis_ids=linked.source_analysis_ids,
                    )
                )
                continue
            if linked.value is None or not math.isfinite(linked.value):
                rows.append(artifacts.ComparableRow(
                    claim_id=claim.claim_id, replica_id=trace.replica_id,
                    analysis_id=analysis_of.get(claim.claim_id), state="abstained",
                    outcome_status="invalid", abstain_reason="non-finite result", reported=reported))
                continue
            graded = grade_with_unit_check(
                claim.quantity_kind, reported,
                linked.value if linked.found else None,
                precision=claim.precision, se=linked.se, comparator=comparator,
                unit_note=linked.unit_note,
            )
            aid = analysis_of.get(claim.claim_id)
            evidence = (getattr(trace, 'execution_evidence', None) or {}).get('analyses', {}).get(aid, {})
            graded = source_direction.grade_paired(graded, kind=claim.quantity_kind,
                reported=reported, computed=linked.value, precision=claim.precision,
                comparator=comparator, direction=directions.get(aid), evidence=evidence)
            from ..statistic_metadata import check as check_df
            df_check = check_df(claim, evidence)
            if df_check and df_check['status'] == 'mismatch':
                graded['band'] = 'fail'
                graded['rule'] += '; reported degrees of freedom disagree with the verified sample'
            rows.append(
                artifacts.ComparableRow(
                    claim_id=claim.claim_id,
                    replica_id=trace.replica_id,
                    analysis_id=analysis_of.get(claim.claim_id),
                    **{k: graded.get(k) for k in ('sign_convention_status', 'magnitude_band',
                        'magnitude_exact_reported_precision', 'substantive_direction_match',
                        'raw_sign_match', 'raw_signed_difference', 'comparison_basis', 'direction_evidence',
                        'author_aligned_statistic', 'author_order_sign_match')},
                    outcome_status="direction_unverified" if graded['band'] is None else "graded",
                    degrees_of_freedom=df_check,
                    exact_reported_precision=(_round_to(linked.value, claim.precision) == _round_to(reported, claim.precision)
                        if isinstance(claim.precision, int) and reported is not None and comparator is None else None),
                    quantity_kind=claim.quantity_kind,
                    reported=reported,
                    replicated=graded["replicated_used"],
                    unit_check=graded["unit_check"],
                    raw_diff=graded["raw_diff"],
                    std_diff=graded["std_diff"],
                    sign_match=graded["sign_match"],
                    direction_flipped=graded["direction_flipped"],
                    band=graded["band"],
                    sigma_rule=graded["sigma_rule"],
                    comparator=comparator,
                    rule=graded["rule"],
                    bound_satisfied=graded.get("bound_satisfied"),
                    bound_rounding_compatible=graded.get("bound_rounding_compatible"),
                    se=linked.se,
                    n=linked.n,
                    link_note=linked.note,
                    source_analysis_ids=linked.source_analysis_ids,
                )
            )
    # No result-selected CI mirroring: orientation must be fixed before grading.

    summaries: list[artifacts.MatchSummary] = []
    from ..computation_coverage import review as computation_review
    accounting = {r['claim_id']: r for r in computation_review(paths.run_dir(paper_id, 1).parent)['rows']}
    rows_by_claim: dict[str, list[artifacts.ComparableRow]] = {}
    for row in rows:
        rows_by_claim.setdefault(row.claim_id, []).append(row)
    for claim in claims:
        if claim.claim_id not in bound_ids:
            disposition = accounting.get(claim.claim_id, {})
            handled = disposition.get('status') in {'computed', 'unavailable', 'invalid_input'}
            summaries.append(
                artifacts.MatchSummary(
                    claim_id=claim.claim_id, n_ran=0, n_found=0, n_matched=0,
                    importance=claim.importance, analysis_id=analysis_of.get(claim.claim_id),
                    state="complete" if disposition.get('status') == 'computed' else "abstained",
                    abstain_reason=(disposition['reason'] if handled else source["invalid_claims"].get(claim.claim_id) or assignment_reasons.get(claim.claim_id) or "analysis abstained at intake: " + str(readiness_reasons.get(analysis_of.get(claim.claim_id), "binding unresolved"))),
                    outcome_status=(disposition['status'] if handled else "input_invalid" if claim.claim_id in source["invalid_claims"] or readiness_outcomes.get(analysis_of.get(claim.claim_id)) == "source_unresolved" else "unbound"),
                )
            )
            continue
        claim_rows = rows_by_claim.get(claim.claim_id, [])
        graded_rows = [r for r in claim_rows if r.state != "abstained"]
        abstained = len(claim_rows) - len(graded_rows)
        n_ran = len(graded_rows)  # replicas that produced a usable row
        matched = sum(1 for r in graded_rows if r.band in {"A", "B"})
        matched_a = sum(1 for r in graded_rows if r.band == "A")
        values = [r.replicated for r in graded_rows if r.replicated is not None]
        cv = None
        if len(values) > 1 and statistics.fmean(values):
            cv = statistics.stdev(values) / abs(statistics.fmean(values))
        summaries.append(
            artifacts.MatchSummary(
                claim_id=claim.claim_id,
                n_ran=n_ran,
                n_abstained=abstained,
                n_found=n_ran,
                n_matched=matched,
                fraction_matched=(matched / n_ran) if n_ran else None,
                fraction_a=(matched_a / n_ran) if n_ran else None,
                n_requested=len(claim_rows),
                coverage=n_ran / len(claim_rows) if claim_rows else None,
                end_to_end_matched=matched / len(claim_rows) if claim_rows else None,
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
        source_coverage=source,
        method_fidelity={t.replica_id: getattr(t, "execution_evidence", {"status": "unverified"}) for t in traces},
        unique_quantities=len({c.quantity_id or c.claim_id for c in claims}),
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
        if s.claim_id not in wanted:
            continue
        claim_rows=[r for r in result.rows if r.claim_id==s.claim_id]
        if claim_rows and all(r.outcome_status=='direction_unverified' and getattr(r,'magnitude_band',None) in {'A','B'} for r in claim_rows):
            # A source interpretation gap is not a computational miss.
            continue
        if not s.n_ran:
            if getattr(s, "n_requested", 0):
                reasons.append(f"{s.claim_id}: no accepted focal result")
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

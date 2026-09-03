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
# Quantities of a two-group contrast, whose sign records which group was subtracted from
# which. That order is a coding choice, so a replica that reversed it produces the same
# magnitude with the opposite sign. Coefficients, correlations and ratios carry a
# substantive sign and keep the sign gate.
FLIPPABLE_KINDS = {"t", "d"}
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
    """Band one claim x replica pair. Returns band, diffs, sign and sigma rule.

    `replicated_used` is the value the band was computed on, which is the sign-flipped
    value for a two-group contrast the replica coded the other way round.
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
            if kind in FLIPPABLE_KINDS:
                flipped = grade(kind, reported, -replicated,
                                precision=precision, se=se, comparator=comparator)
                if flipped["band"] != "fail":
                    flipped.update(
                        sign_match=False, direction_flipped=True,
                        rule=f"sign flipped (group order is a coding choice); {flipped['rule']}",
                    )
                    return flipped
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
    flagged = bool(unit_note) and unit_note.strip().lower() not in {"none", "n/a", "no", ""}
    if not flagged or replicated is None or reported is None:
        return base
    best = base
    for candidate, label in unit_candidates(replicated):
        alt = grade(quantity_kind, reported, candidate,
                    precision=precision, se=se, comparator=comparator)
        if BAND_ORDER[alt["band"]] < BAND_ORDER[best["band"]]:
            alt["unit_check"] = f"{unit_note}; {label}"
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


def mirror_ci_bounds(
    rows: list[artifacts.ComparableRow],
    links: dict[tuple[str, str], LinkResult],
    claims_by_id: dict[str, artifacts.ClaimRecord],
    analysis_of: dict[str, str | None],
) -> None:
    """Regrade the CI bounds of a direction-flipped contrast on the mirrored interval.

    An estimate that came out with the opposite sign brings its confidence interval with
    it: the replica's lower bound is minus the reported upper bound, and its upper bound
    minus the reported lower bound. Each `ci_bound` row of an analysis and replica whose
    estimate row flipped is therefore regraded on the mirrored value: the negation of the
    replica's counterpart bound, found in one of three ways, in order.

    1. The flipped estimate's own link recorded `ci_lower` and `ci_upper`, and this row's
       value is one of them; the counterpart is the other.
    2. The analysis's ci_bound rows split by the sample size their link reported, and this
       row's group of that size holds exactly two rows; the counterpart is the other one.
       This separates the intervals of two analyses run on different samples.
    3. Neither identifies a counterpart, so the row's own value is negated.

    The new grade is kept only when it lands in a better band, so a bound that mirroring
    does not explain stays as it was.
    """
    groups: dict[tuple[str | None, str], list[artifacts.ComparableRow]] = {}
    for row in rows:
        groups.setdefault((analysis_of.get(row.claim_id), row.replica_id), []).append(row)

    for group in groups.values():
        flipped = [r for r in group
                   if r.direction_flipped and r.quantity_kind != "ci_bound"]
        if not flipped:
            continue
        intervals = []
        for r in flipped:
            link = links.get((r.claim_id, r.replica_id))
            if link and link.ci_lower is not None and link.ci_upper is not None:
                intervals.append((link.ci_lower, link.ci_upper))

        # The values as linked, read before any row is regraded in place: a bound whose
        # counterpart has already been mirrored must still pair with the linked value.
        bounds = [r for r in group if r.quantity_kind == "ci_bound" and r.replicated is not None]
        raw = {r.claim_id: r.replicated for r in bounds}
        by_n: dict[int | None, list[str]] = {}
        for r in bounds:
            link = links.get((r.claim_id, r.replica_id))
            by_n.setdefault(link.n if link else None, []).append(r.claim_id)

        for row in bounds:
            value = raw[row.claim_id]
            link = links.get((row.claim_id, row.replica_id))
            mirrored = -value
            for lower, upper in intervals:
                if math.isclose(value, lower, rel_tol=1e-9):
                    mirrored = -upper
                    break
                if math.isclose(value, upper, rel_tol=1e-9):
                    mirrored = -lower
                    break
            else:
                pair = by_n[link.n if link else None]
                if len(pair) == 2:
                    other = next(cid for cid in pair if cid != row.claim_id)
                    mirrored = -raw[other]
            claim = claims_by_id[row.claim_id]
            graded = grade_with_unit_check(
                row.quantity_kind, row.reported, mirrored,
                precision=claim.precision, se=link.se if link else None,
                comparator=getattr(row, "comparator", None),
            )
            if BAND_ORDER[graded["band"]] >= BAND_ORDER[row.band]:
                continue
            row.replicated = graded["replicated_used"]
            row.raw_diff = graded["raw_diff"]
            row.std_diff = graded["std_diff"]
            row.sign_match = False
            row.direction_flipped = True
            row.band = graded["band"]
            row.sigma_rule = graded["sigma_rule"]
            row.rule = f"CI mirrored about zero with the flipped estimate; {graded['rule']}"


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
            graded = grade_with_unit_check(
                claim.quantity_kind, reported,
                linked.value if linked.found else None,
                precision=claim.precision, se=linked.se, comparator=comparator,
                unit_note=linked.unit_note,
            )
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
                    direction_flipped=graded["direction_flipped"],
                    band=graded["band"],
                    sigma_rule=graded["sigma_rule"],
                    comparator=comparator,
                    rule=graded["rule"],
                    se=linked.se,
                    n=linked.n,
                    link_note=linked.note,
                )
            )
    mirror_ci_bounds(rows, links, claims_by_id, analysis_of)

    summaries: list[artifacts.MatchSummary] = []
    rows_by_claim: dict[str, list[artifacts.ComparableRow]] = {}
    for row in rows:
        rows_by_claim.setdefault(row.claim_id, []).append(row)
    for claim in claims:
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

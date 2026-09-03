"""Deterministic value scan: does a blind document contain a reported result?

Pure Python, no model call. Stage 1 imports `scan()` and must refuse to launch a
replica while it returns hits.

What counts as a result: the quantities a reader would use to judge the study's
findings. A claim is forbidden material when its quantity kind is inferential
(t, F, chi2, z, d, r, OR, HR, eta2, coefficient, p_value, se, ci_bound), when the
paper reports it as a headline claim, or when it is any numeric claim of an analysis
that carries one of those two — the descriptive quantities printed alongside a test
recover the test. A supporting claim of an analysis that carries neither is sample
description (mean age, sex percentages, exclusion rates, scale reliability), which
the redacted methods are meant to state, and is skipped.

Thresholds and the design-number exemption apply to every forbidden claim alike:
2 significant digits from a headline claim or a p-value, 3 from any other, roundings
onto an alpha level dropped, and values the manifest names as design constants exempt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

# Quantity kinds that carry an inferential result. Every claim of one of these
# kinds is forbidden, whatever its importance.
INFERENTIAL_KINDS = frozenset(
    {"t", "F", "chi2", "z", "d", "r", "OR", "HR", "eta2", "coefficient", "p_value", "se", "ci_bound"}
)

# Significant digits a printed form must carry to be forbidden. Two digits from a
# headline claim still recover the finding; three are needed before a supporting
# claim's digits can be told apart from ordinary methods prose.
HEADLINE_MIN_DIGITS = 2
SUPPORTING_MIN_DIGITS = 3

# Significance conventions every methods section names ("effects with p between .05
# and .10"). A coarser rounding of a value onto one of these cannot be told apart
# from that convention, so it is not searched; the value as the paper printed it is.
ALPHA_LEVELS = {0.1, 0.05, 0.01, 0.001}


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip().lstrip("<>=~ ").replace(",", ""))
        except ValueError:
            return None
    return None


def _significant_digits(form: str) -> int:
    """Digits carrying information. A trailing zero after the decimal point counts:
    ".50" is a two-decimal correlation, not a one-digit probability."""
    return len(form.replace("-", "").replace(".", "").lstrip("0"))


def _decimals(form: str) -> int:
    return len(form.partition(".")[2])


def variants(value: float, precision: int | None = None, min_digits: int = HEADLINE_MIN_DIGITS) -> set[str]:
    """Every printed form of `value` a leak could take (sign handled by the regex).

    The reported form and every coarser rounding of it. Forms are never padded past
    the reported precision, so a value of 0.8 yields ".8" and not ".800".

    Forms below `min_digits` significant digits are left out: they recover little and
    collide with alpha levels, scale points and design probabilities.
    """
    a = abs(value)
    natural = f"{a:g}"
    if "e" in natural or "inf" in natural or "nan" in natural:
        return set()
    reported = precision if isinstance(precision, int) and 0 <= precision <= 6 else _decimals(natural)
    as_printed = f"{a:.{reported}f}" if reported else natural
    forms = {natural, as_printed} | {f"{a:.{d}f}" for d in range(1, reported + 1)}
    if a == int(a):
        forms.add(str(int(a)))
    out: set[str] = set()
    for f in forms:
        if _significant_digits(f) < min_digits:
            continue
        if f != as_printed and round(float(f), 6) in ALPHA_LEVELS:
            continue
        out.add(f)
        if f.startswith("0."):
            out.add(f[1:])  # ".82" as psychologists print it
    return out


def _claim_field(claim: Any, name: str) -> Any:
    if isinstance(claim, dict):
        return claim.get(name)
    return getattr(claim, name, None)


def _kinds(claim: Any) -> set[str]:
    """The validated kind and the extractor's own label ("ci_upper" for a ci_bound)."""
    return {
        str(_claim_field(claim, f) or "")
        for f in ("quantity_kind", "quantity_kind_raw")
    } - {""}


def _uncertainty_numbers(unc: Any) -> list[float]:
    """Numbers hidden inside an uncertainty record (se, ci bounds, sd)."""
    if unc is None:
        return []
    text = json.dumps(unc) if not isinstance(unc, str) else unc
    return [float(t) for t in re.findall(r"-?\d*\.?\d+", text) if t not in {".", "-"}]


def _contract_field(contract: Any, name: str) -> Any:
    if isinstance(contract, dict):
        return contract.get(name)
    return getattr(contract, name, None)


def result_claim_ids(claims: Iterable[Any], contracts: Iterable[Any]) -> set[str]:
    """Claim ids of every analysis that carries a result.

    An analysis carries a result when at least one of its claims is of an inferential
    kind or is a headline claim. Every claim of such an analysis is then treated as a
    result, because the means and counts printed beside a test recover the test.
    Claims no contract lists are not included.
    """
    carries: dict[str, bool] = {}
    for claim in claims:
        cid = str(_claim_field(claim, "claim_id") or "")
        carries[cid] = bool(
            (_kinds(claim) & INFERENTIAL_KINDS)
            or _claim_field(claim, "importance") == "headline"
        )
    out: set[str] = set()
    for contract in contracts:
        ids = [str(c) for c in (_contract_field(contract, "claim_ids") or [])]
        if any(carries.get(cid) for cid in ids):
            out.update(ids)
    return out


def forbidden_strings(
    claims: Iterable[Any],
    design_numbers: Iterable[float] = (),
    result_claim_ids: Iterable[str] = (),
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Map printed-form -> claim_ids it came from, plus the values deliberately skipped.

    `result_claim_ids` names the claims of result-carrying analyses; each is forbidden
    whatever its own quantity kind.
    """
    design = {round(float(d), 6) for d in design_numbers if _as_float(d) is not None}
    result_ids = {str(c) for c in result_claim_ids}
    forbidden: dict[str, list[str]] = {}
    skipped: list[dict[str, Any]] = []

    for claim in claims:
        cid = str(_claim_field(claim, "claim_id") or "?")
        kinds = _kinds(claim)
        headline = _claim_field(claim, "importance") == "headline"
        precision = _claim_field(claim, "precision")
        value = _as_float(_claim_field(claim, "value"))
        if value is None:
            continue

        if not headline and not (kinds & INFERENTIAL_KINDS) and cid not in result_ids:
            skipped.append(
                {
                    "claim_id": cid,
                    "value": value,
                    "reason": f"supporting {'/'.join(sorted(kinds)) or 'claim'} of an "
                    "analysis that reports no result: sample description",
                }
            )
            continue

        # A printed p-value rarely carries three significant digits (".03", "< .25"),
        # so the supporting-claim threshold would exempt almost every one of them.
        min_digits = HEADLINE_MIN_DIGITS if headline or "p_value" in kinds else SUPPORTING_MIN_DIGITS
        numbers = [(value, precision if isinstance(precision, int) else None)]
        numbers += [(u, None) for u in _uncertainty_numbers(_claim_field(claim, "uncertainty"))]
        for num, prec in numbers:
            if round(abs(num), 6) in design:
                skipped.append(
                    {
                        "claim_id": cid,
                        "value": num,
                        "reason": "also a design number in the manifest",
                    }
                )
                continue
            for form in variants(num, prec, min_digits):
                forbidden.setdefault(form, [])
                if cid not in forbidden[form]:
                    forbidden[form].append(cid)

    return forbidden, skipped


# Dimensionless statistics: a paper never prints one with a percent sign, so a
# number followed by "%" is an exclusion rate or a proportion of the sample, not
# this claim's value.
NEVER_PERCENT = frozenset({"t", "F", "chi2", "z", "d", "r", "OR", "HR", "eta2", "p_value"})


def _pattern(form: str, allow_percent: bool = True) -> re.Pattern[str]:
    # A number, not a digit run inside an identifier or a dotted label: "5.9" must
    # not match inside "5.91", "c591" or "Section 5.9.1", and a leading minus is
    # part of the number.
    # A confidence level ("95% CI") is design text even when 95 is also a reported percentage.
    tail = r"(?!\s*%\s*(?:CI|confidence))" if allow_percent else r"(?!\s*%)"
    return re.compile(r"(?<![\w.])-?" + re.escape(form) + r"(?!\w)(?!\.\d)" + tail)


# JSON keys that carry bookkeeping rather than content: ids, hashes, timestamps
# and page numbers, whose digits are never results.
SKIP_KEYS = {
    "meta",
    "claim_id",
    "claim_ids",
    "analysis_id",
    "page",
    "quantity_kind",
    "quantity_kind_raw",
    "location",  # table/figure/section labels such as "Section 4.2", never values
}


def _json_leaves(obj: Any, path: str = "$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SKIP_KEYS:
                continue
            yield from _json_leaves(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _json_leaves(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        yield path, repr(obj)


def segments(path: Path) -> list[tuple[str, str]]:
    """(location, text) pairs to scan. JSON is walked, so ids and meta stay out."""
    text = path.read_text(errors="replace")
    if path.suffix.lower() == ".json":
        try:
            return list(_json_leaves(json.loads(text)))
        except json.JSONDecodeError:
            pass
    return [("", text)]


def scan(
    files: Iterable[Path | str],
    claims: Iterable[Any],
    design_numbers: Iterable[float] = (),
    paper_id: str | None = None,
    result_claim_ids: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Every occurrence of a reported value in the given blind files.

    Each hit carries `start`/`end`, the match offsets inside its segment, so the
    repair step can locate the sentence to rewrite.

    Pass `paper_id` (or `design_numbers`) so the paper's own design constants are
    exempt; without them a manipulation probability the methods must state reads as
    a leak of any result that rounds to the same digits.

    Pass `result_claim_ids` (from `result_claim_ids(claims, contracts)`) so every claim
    of an analysis that reports a result is searched, not only the inferential ones.
    """
    if paper_id is not None and not design_numbers:
        from .. import paths as _paths

        design_numbers = design_numbers_from_manifest(_paths.manifest(paper_id))
    claims = list(claims)
    kinds = {str(_claim_field(c, "claim_id")): _kinds(c) for c in claims}
    forbidden, _ = forbidden_strings(claims, design_numbers, result_claim_ids)
    patterns = [
        (
            form,
            cids,
            _pattern(form, any(kinds.get(c, set()) - NEVER_PERCENT for c in cids)),
        )
        for form, cids in forbidden.items()
    ]
    hits: list[dict[str, Any]] = []
    for path in files:
        path = Path(path)
        if not path.exists():
            continue
        for location, text in segments(path):
            for form, cids, pat in patterns:
                for m in pat.finditer(text):
                    start = max(0, m.start() - 60)
                    hits.append(
                        {
                            "file": path.name,
                            "location": location or f"offset {m.start()}",
                            "value": form,
                            "claim_ids": cids,
                            "start": m.start(),
                            "end": m.end(),
                            "context": text[start : m.end() + 60].replace("\n", " "),
                        }
                    )
    return hits


def design_numbers_from_manifest(manifest: Any) -> list[float]:
    """Numbers the manifest states as design facts, never as results.

    Sample size and degrees of freedom from the focal claim, plus any explicit
    `design_numbers` list (manipulation probabilities, scale points, thresholds) a
    curator added because the methods must state them.
    """
    out: list[float] = []
    for d in getattr(manifest, "design_numbers", None) or []:
        v = _as_float(d)
        if v is not None:
            out.append(v)
    focal = getattr(manifest, "focal_claim", None)
    reported = getattr(focal, "reported", None) if focal else None
    for field in ("n", "df"):
        v = _as_float(getattr(reported, field, None)) if reported else None
        if v is not None:
            out.append(v)
    return out

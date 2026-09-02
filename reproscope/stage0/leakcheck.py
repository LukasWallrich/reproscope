"""Deterministic value scan: does a blind document contain a reported result?

Pure Python, no model call. Stage 1 imports `scan()` and must refuse to launch a
replica while it returns hits.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

# p-value thresholds the redacted methods are allowed to name (alpha levels,
# "p < .001" conventions). A claim reporting `p < .05` carries no information
# beyond the threshold itself, so its value is not forbidden.
P_THRESHOLDS = {0.1, 0.05, 0.01, 0.001}

# Integers this small are design furniture (item counts, scale points, group
# sizes) far more often than results, so they are skipped unless the claim is a
# headline sample size.
SMALL_INT_MAX = 30


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
    return len(form.replace("-", "").replace(".", "").lstrip("0"))


def variants(value: float, precision: int | None = None) -> set[str]:
    """Every printed form of `value` a leak could take (sign handled by the regex).

    Forms with a single significant digit are left out: ".1" or ".8" recovers no
    result, and it collides with alpha levels and design probabilities.
    """
    a = abs(value)
    forms: list[str] = []
    if precision is not None and 0 <= precision <= 6:
        forms.append(f"{a:.{precision}f}")
    forms += [f"{a:.{d}f}" for d in (1, 2, 3)]
    forms.append(f"{a:g}")
    if a == int(a):
        forms.append(str(int(a)))
    out: set[str] = set()
    for f in forms:
        if not f or "e" in f or "inf" in f or "nan" in f:
            continue
        if _significant_digits(f) < 2:
            continue
        out.add(f)
        if f.startswith("0."):
            out.add(f[1:])  # ".82" as psychologists print it
    return out


def _claim_field(claim: Any, name: str) -> Any:
    if isinstance(claim, dict):
        return claim.get(name)
    return getattr(claim, name, None)


def _uncertainty_numbers(unc: Any) -> list[float]:
    """Numbers hidden inside an uncertainty record (se, ci bounds, sd)."""
    if unc is None:
        return []
    text = json.dumps(unc) if not isinstance(unc, str) else unc
    return [float(t) for t in re.findall(r"-?\d*\.?\d+", text) if t not in {".", "-"}]


def forbidden_strings(
    claims: Iterable[Any], design_numbers: Iterable[float] = ()
) -> tuple[dict[str, list[str]], list[dict[str, Any]]]:
    """Map printed-form -> claim_ids it came from, plus the values deliberately skipped."""
    design = {round(float(d), 6) for d in design_numbers if _as_float(d) is not None}
    forbidden: dict[str, list[str]] = {}
    skipped: list[dict[str, Any]] = []

    for claim in claims:
        cid = str(_claim_field(claim, "claim_id") or "?")
        kind = _claim_field(claim, "quantity_kind") or ""
        raw_kind = _claim_field(claim, "quantity_kind_raw") or kind
        importance = _claim_field(claim, "importance")
        comparator = _claim_field(claim, "comparator")
        precision = _claim_field(claim, "precision")
        value = _as_float(_claim_field(claim, "value"))
        if value is None:
            continue

        headline_n = str(raw_kind) == "n" and importance == "headline"

        if str(raw_kind) == "p_value" and comparator in {"<", ">"} and round(abs(value), 6) in P_THRESHOLDS:
            skipped.append({"claim_id": cid, "value": value, "reason": "p-value threshold, not a result value"})
            continue
        if str(raw_kind) == "n" and not headline_n:
            # A sample size defines who is in the analysis, so the blind methods must
            # state it. Only a sample size the paper reports as a finding is a result.
            skipped.append({"claim_id": cid, "value": value, "reason": "sample size, not a headline result"})
            continue
        if not headline_n and value == int(value) and abs(value) <= SMALL_INT_MAX:
            skipped.append({"claim_id": cid, "value": value, "reason": f"small integer (|v| <= {SMALL_INT_MAX})"})
            continue
        if not headline_n and round(abs(value), 6) in design:
            skipped.append({"claim_id": cid, "value": value, "reason": "also a design number in the manifest"})
            continue

        numbers = [(value, precision if isinstance(precision, int) else None)]
        numbers += [(u, None) for u in _uncertainty_numbers(_claim_field(claim, "uncertainty"))]
        dropped_forms: set[str] = set()
        for num, prec in numbers:
            if num is None or (num == int(num) and abs(num) <= SMALL_INT_MAX and not headline_n):
                continue
            for form in variants(num, prec):
                # Every methods section names its alpha levels, so a form that is
                # exactly a threshold cannot be told apart from that convention.
                if round(abs(float(form)), 6) in P_THRESHOLDS:
                    dropped_forms.add(form)
                    continue
                forbidden.setdefault(form, [])
                if cid not in forbidden[form]:
                    forbidden[form].append(cid)
        if dropped_forms:
            skipped.append(
                {
                    "claim_id": cid,
                    "value": value,
                    "reason": "forms equal to a significance threshold: "
                    + ", ".join(sorted(dropped_forms)),
                }
            )

    return forbidden, skipped


def _pattern(form: str) -> re.Pattern[str]:
    # A number, not a digit run inside an identifier or a dotted label: "5.9" must
    # not match inside "5.91", "c591" or "Section 5.9.1", and a leading minus is
    # part of the number.
    return re.compile(r"(?<![\w.])-?" + re.escape(form) + r"(?!\w)(?!\.\d)")


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
) -> list[dict[str, Any]]:
    """Every occurrence of a reported value in the given blind files.

    Pass `paper_id` (or `design_numbers`) so the paper's own design constants are
    exempt; without them a manipulation probability the methods must state reads as
    a leak of any result that rounds to the same digits.
    """
    if paper_id is not None and not design_numbers:
        from .. import paths as _paths

        design_numbers = design_numbers_from_manifest(_paths.manifest(paper_id))
    forbidden, _ = forbidden_strings(claims, design_numbers)
    patterns = [(form, cids, _pattern(form)) for form, cids in forbidden.items()]
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

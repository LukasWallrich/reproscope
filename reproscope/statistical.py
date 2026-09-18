"""Statistical contracts and model-free checks shared by pipeline stages."""
from __future__ import annotations

import json
import math
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnalysisDesign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: Literal["independent_t", "paired_t", "one_sample_t", "correlation", "mixed_anova", "other", "unknown"]
    contrast: str
    null_value: float | None = None
    independent_unit: str
    repeated_factors: list[str] = []
    variance_assumption: Literal["equal", "unequal", "unknown"] = "unknown"
    alternative: Literal["two-sided", "greater", "less", "unknown"] = "unknown"
    n_total: int | None = Field(default=None, gt=1)
    group_ns: list[int] = []
    effect_metric: str | None = None
    evidence: str

    @model_validator(mode="after")
    def coherent_sample(self):
        if any(n < 2 for n in self.group_ns):
            raise ValueError("each group requires at least two independent observations")
        if self.group_ns and self.n_total != sum(self.group_ns):
            raise ValueError("group counts must sum to n_total")
        if self.family == "independent_t" and self.repeated_factors:
            raise ValueError("an independent t test cannot silently absorb repeated factors")
        if self.family == "independent_t" and self.group_ns and len(self.group_ns) != 2:
            raise ValueError("independent_t requires two groups")
        return self


def adjusted_p(values: list[float], method: str) -> list[float]:
    """Apply one declared correction to a complete family of raw p-values."""
    if not values or any(not math.isfinite(p) or not 0 <= p <= 1 for p in values):
        raise ValueError("raw p-value family must contain finite probabilities")
    if method == "none":
        return list(values)
    if method == "bonferroni":
        return [min(1., p * len(values)) for p in values]
    if method != "holm":
        raise ValueError(f"unsupported multiplicity method: {method}")
    result, previous = [0.] * len(values), 0.
    for i, index in enumerate(sorted(range(len(values)), key=values.__getitem__)):
        previous = max(previous, min(1., (len(values) - i) * values[index]))
        result[index] = previous
    return result


def monte_carlo_p(exceedances: int, draws: int) -> float:
    exceedances=integer_field(exceedances,'exceedances');draws=integer_field(draws,'draws')
    if not 0 <= exceedances <= draws or draws < 1:
        raise ValueError("invalid Monte Carlo counts")
    return (exceedances + 1) / (draws + 1)


def integer_field(value,name):
    """CSV nullable integer columns may use 10000.0; never truncate fractions."""
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number!=number.to_integral_value():raise ValueError()
        return int(number)
    except (InvalidOperation,ValueError,TypeError):
        raise ValueError(f'{name} must be a finite exact integer') from None


def validate_result(row: dict, *, strict: bool = False) -> list[str]:
    """Check dimensions, sample, and inference, without inferring meaning from labels."""
    problems = []
    if not row.get("_converged"):
        if not row.get("error"):
            problems.append("failed specification requires an error reason")
        return problems
    for name in ("estimate", "se", "p", "n", "p_threshold"):
        value = row.get(name)
        if value in (None, ""):
            continue
        try:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError()
            if name == "se" and number < 0:
                raise ValueError()
            if name == "p" and not 0 <= number <= 1:
                raise ValueError()
            if name == "p_threshold" and not 0 < number < 1:
                raise ValueError()
            if name == "n" and (number < 2 or not number.is_integer()):
                raise ValueError()
        except (TypeError, ValueError):
            problems.append(f"invalid {name}: {value!r}")
    if not strict:
        return problems
    for name in ("estimate", "n", "effect_metric", "p_raw", "p_adjustment", "p_threshold", "inference_method"):
        if row.get(name) in (None, ""):
            problems.append(f"missing result contract field: {name}")
    if row.get("inference_method") not in {"analytic", "exact", "monte_carlo"}:
        problems.append("unsupported inference method")
    if row.get("se") not in (None, "") and row.get("se_metric") != row.get("effect_metric"):
        problems.append("SE and estimate must use the same metric")
    try:
        method = row["p_adjustment"]
        family = json.loads(row.get("p_family") or "[]")
        if method == "none" and not family:
            family = [float(row["p_raw"])]
        index = integer_field(row.get("p_index") or 0,'p_index')
        if index < 0:
            raise ValueError("negative focal index")
        if method == "fixed_threshold":
            alpha = float(row["per_test_alpha"])
            if not 0 < alpha <= .05 or family:
                raise ValueError("fixed source threshold requires alpha and no invented p family")
            expected = min(1., float(row["p_raw"]) * .05 / alpha)
        else:
            expected = adjusted_p(family, method)[index]
            if not math.isclose(float(row["p_raw"]), family[index], rel_tol=1e-6, abs_tol=1e-12):
                problems.append("focal raw p does not match its declared family")
        if not math.isclose(float(row["p"]), expected, rel_tol=1e-6, abs_tol=1e-12):
            problems.append("p must contain the once-adjusted focal p-value")
        if not math.isclose(float(row["p_threshold"]), .05):
            problems.append("adjusted p-values must use the pipeline's family alpha .05")
        if row.get("inference_method") == "monte_carlo":
            expected_raw = monte_carlo_p(row["exceedances"], row["draws"])
            if not math.isclose(float(row["p_raw"]), expected_raw, rel_tol=1e-6, abs_tol=1e-12):
                problems.append("invalid finite-simulation p-value")
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        problems.append("invalid or incomplete inference contract: "+str(exc))
    return problems

"""Minimum detectable effect for the focal analysis.

The power curve and the 80%-power MDE come from R (`power.t.test`, `pwr::pwr.r.test`)
for the designs listed below. Any other design is outside what this module can state
assumptions for, and `check_mde` abstains with the reason.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

EFFECTS = (0.1, 0.2, 0.3, 0.5, 0.8)
ALPHA = 0.05
TARGET_POWER = 0.80

# Designs the deterministic path covers.
TWO_GROUP = "two_group"
PAIRED = "paired"
CORRELATION = "correlation"


def rscript() -> str | None:
    return shutil.which("Rscript")


def has_pwr() -> bool:
    exe = rscript()
    if not exe:
        return False
    proc = subprocess.run(
        [exe, "-e", 'cat(requireNamespace("pwr", quietly = TRUE))'],
        capture_output=True, text=True,
    )
    return "TRUE" in (proc.stdout or "")


def install_pwr() -> bool:
    exe = rscript()
    if not exe:
        return False
    subprocess.run(
        [exe, "-e", 'install.packages("pwr", repos = "https://cloud.r-project.org")'],
        capture_output=True, text=True,
    )
    return has_pwr()


# --- design classification ------------------------------------------------

_PAIRED = re.compile(r"paired|within[- ]subject|repeated[- ]measures|matched[- ]pairs", re.I)
_TWO_GROUP = re.compile(
    r"\b(two[- ]sample|independent[- ]samples?|between[- ]subjects?|welch|student'?s? t)\b"
    r"|\bt[- ]?test\b|\bone[- ]way anova\b|\banova\b",
    re.I,
)
_CORRELATION = re.compile(r"\bcorrelat|\bpearson\b|\bspearman\b|\bsimple (linear )?regression\b", re.I)
_OLS = re.compile(r"\bols\b|\blinear (model|regression)\b|\blm\b", re.I)


def classify_design(
    model_type: str | None,
    *,
    n_predictors: int = 0,
    n_covariates: int = 0,
    formula: str | None = None,
) -> str | None:
    """Map a contract's model_type onto one of the covered power cases, or None.

    None means "not one of the covered designs" and makes the caller abstain. Guessing
    a design would put a wrong number in the report.
    """
    text = " ".join(x for x in (model_type, formula) if x)
    if not text.strip():
        return None
    if _PAIRED.search(text):
        return PAIRED
    if _TWO_GROUP.search(text):
        # power.t.test covers a two-group test only without covariates.
        return TWO_GROUP if n_covariates == 0 else None
    if _CORRELATION.search(text) and n_predictors <= 1 and n_covariates == 0:
        return CORRELATION
    if _OLS.search(text) and n_predictors == 1 and n_covariates == 0:
        return CORRELATION
    return None


# --- R computation --------------------------------------------------------

_R_TEMPLATE = """# reproscope stage 2 - minimum detectable effect (generated; safe to re-run)
alpha <- {alpha}
target <- {target}
effects <- c({effects})
design <- "{design}"
n <- {n}
n_per_group <- {n_per_group}

emit <- function(key, value) cat(sprintf("%s=%s\\n", key, format(value, digits = 10)))

if (design == "two_group") {{
  for (d in effects) emit(paste0("power_", d),
    power.t.test(n = n_per_group, delta = d, sd = 1, sig.level = alpha,
                 type = "two.sample", alternative = "two.sided")$power)
  emit("mde", power.t.test(n = n_per_group, sd = 1, sig.level = alpha, power = target,
                           type = "two.sample", alternative = "two.sided")$delta)
}} else if (design == "paired") {{
  for (d in effects) emit(paste0("power_", d),
    power.t.test(n = n, delta = d, sd = 1, sig.level = alpha,
                 type = "paired", alternative = "two.sided")$power)
  emit("mde", power.t.test(n = n, sd = 1, sig.level = alpha, power = target,
                           type = "paired", alternative = "two.sided")$delta)
}} else if (design == "correlation") {{
  library(pwr)
  for (r in effects) emit(paste0("power_", r),
    pwr.r.test(n = n, r = r, sig.level = alpha, alternative = "two.sided")$power)
  emit("mde", pwr.r.test(n = n, sig.level = alpha, power = target,
                         alternative = "two.sided")$r)
}} else {{
  stop(paste("unsupported design:", design))
}}
emit("ok", 1)
"""


class MdeError(RuntimeError):
    pass


def r_script(design: str, n: int, n_per_group: int | None) -> str:
    return _R_TEMPLATE.format(
        alpha=ALPHA,
        target=TARGET_POWER,
        effects=", ".join(str(e) for e in EFFECTS),
        design=design,
        n=n,
        n_per_group=n_per_group if n_per_group is not None else "NA",
    )


def run_r(script: str, script_path: Path) -> dict[str, float]:
    exe = rscript()
    if not exe:
        raise MdeError("Rscript is not on PATH")
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script)
    proc = subprocess.run([exe, str(script_path)], capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise MdeError(f"Rscript exited {proc.returncode}: {(proc.stderr or '')[-600:]}")
    out: dict[str, float] = {}
    for line in (proc.stdout or "").splitlines():
        key, _, value = line.partition("=")
        try:
            out[key.strip()] = float(value.strip())
        except ValueError:
            continue
    if "ok" not in out or "mde" not in out:
        raise MdeError(f"Rscript produced no usable output: {(proc.stdout or '')[:400]}")
    return out


def compute(
    design: str,
    n: int,
    *,
    script_path: Path,
    n_per_group: int | None = None,
    metric: str = "Cohen's d",
    extra_assumptions: list[str] | None = None,
) -> dict[str, Any]:
    """Power curve and 80%-power MDE for one of the covered designs."""
    if design == CORRELATION and not has_pwr() and not install_pwr():
        raise MdeError("R package `pwr` is required for the correlation design and is not installed")
    if design == TWO_GROUP and n_per_group is None:
        n_per_group = n // 2
    values = run_r(r_script(design, n, n_per_group), script_path)
    curve = [{"effect": e, "power": round(values[f"power_{e}"], 4)} for e in EFFECTS]

    assumptions = [f"alpha = {ALPHA}, two-sided", f"target power = {TARGET_POWER}"]
    if design == TWO_GROUP:
        assumptions += [
            f"n = {n} analysed, split as {n_per_group} per group"
            + (" (equal split assumed; the traces do not report per-group n)"
               if n_per_group == n // 2 else ""),
            "independent-samples t test on a continuous outcome, equal variances, no covariates",
            f"effect metric: {metric} (standardised mean difference, sd = 1)",
        ]
    elif design == PAIRED:
        assumptions += [
            f"n = {n} pairs analysed",
            "paired t test; the standardised effect is on the difference scores",
            f"effect metric: {metric}",
        ]
    else:
        assumptions += [
            f"n = {n} analysed",
            "test of a single Pearson correlation, bivariate normal, no covariates",
            "effect metric: Pearson r",
        ]
    assumptions.append(
        "no clustering or repeated measurement beyond the design named above; "
        "attrition is already inside the analysed n"
    )
    assumptions += extra_assumptions or []

    return {
        "design": design,
        "method": "deterministic",
        "n_analysed": n,
        "n_per_group": n_per_group,
        "alpha": ALPHA,
        "target_power": TARGET_POWER,
        "mde_standardised": round(values["mde"], 4),
        "mde_metric": metric if design != CORRELATION else "Pearson r",
        "curve": curve,
        "assumptions": assumptions,
        "r_script": str(script_path),
        "caveats": [
            "This is a design property computed from n and the model form only. "
            "The reported effect size was not used.",
        ],
    }

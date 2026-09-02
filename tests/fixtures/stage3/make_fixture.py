"""Regenerate the Stage 3 fixture: a synthetic paper with data, stage0 and stage1 outputs.

Run:  .venv/bin/python tests/fixtures/stage3/make_fixture.py

Writes `corpus/` and `runs/` trees next to this file. The reported statistics in the
manifest are computed from the generated data under the paper's own specification
(attention-check failures excluded, no covariate), so the fixture is self-consistent.
"""

from __future__ import annotations

import csv
import json
import math
import random
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
N_PER_GROUP = 40
SEED = 20260901


def make_rows() -> list[dict]:
    rng = random.Random(SEED)
    rows = []
    for i in range(2 * N_PER_GROUP):
        treat = 1 if i >= N_PER_GROUP else 0
        baseline = rng.gauss(0, 1)
        outcome = 4.30 + 0.85 * treat + 0.40 * baseline + rng.gauss(0, 1.0)
        rows.append(
            {
                "pid": i + 1,
                "condition": "treatment" if treat else "control",
                "baseline": round(baseline, 4),
                "outcome": round(outcome, 4),
                "attention_check": 1,
                "age": rng.randint(18, 65),
            }
        )
    # eight participants fail the attention check, spread over both arms
    for i in (3, 11, 25, 37, 44, 52, 66, 78):
        rows[i]["attention_check"] = 0
    # one outlier in the control arm (kept in the data; a factor level removes it)
    rows[7]["outcome"] = 12.40
    return rows


def paper_spec_stats(rows: list[dict]) -> dict:
    """The paper's own analysis: drop attention-check failures, Welch t-test, Cohen's d."""
    kept = [r for r in rows if r["attention_check"] == 1]
    a = [r["outcome"] for r in kept if r["condition"] == "control"]
    b = [r["outcome"] for r in kept if r["condition"] == "treatment"]
    na, nb = len(a), len(b)
    ma, mb = st.mean(a), st.mean(b)
    va, vb = st.variance(a), st.variance(b)
    se = math.sqrt(va / na + vb / nb)
    t = (mb - ma) / se
    df = (va / na + vb / nb) ** 2 / ((va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1))
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    d = (mb - ma) / sp
    return {
        "n": na + nb, "m_control": ma, "m_treatment": mb,
        "t": t, "df": df, "d": d, "diff": mb - ma,
    }


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2) + "\n")


def main() -> None:
    rows = make_rows()
    s = paper_spec_stats(rows)
    r2 = lambda x: round(x, 2)  # noqa: E731 - reported precision is two decimals

    data_path = HERE / "corpus" / "data" / "fixture_study.csv"
    data_path.parent.mkdir(parents=True, exist_ok=True)
    with data_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    (HERE / "corpus" / "data" / "codebook.md").write_text(
        "# Codebook — fixture_study.csv\n\n"
        "| column | meaning |\n|---|---|\n"
        "| pid | participant id |\n"
        "| condition | `control` or `treatment` (random assignment) |\n"
        "| baseline | pre-test score, standardised |\n"
        "| outcome | post-test score, the dependent variable |\n"
        "| attention_check | 1 = passed, 0 = failed |\n"
        "| age | years |\n"
    )

    statistic = (
        f"Participants in the treatment condition scored higher (M = {r2(s['m_treatment'])}) "
        f"than controls (M = {r2(s['m_control'])}), t({r2(s['df'])}) = {r2(s['t'])}, "
        f"p < .01, d = {r2(s['d'])}."
    )
    write_json(HERE / "corpus" / "manifest.json", {
        "paper_id": "_fixture3",
        "title": "A synthetic two-group experiment (Stage 3 fixture)",
        "doi": None,
        "pdf": "paper.pdf",
        "licence": "fixture",
        "data_files": ["data/fixture_study.csv"],
        "codebook": "data/codebook.md",
        "original_code": [],
        "focal_claim": {
            "text": "The treatment raised post-test scores relative to control. (p. 4)",
            "source": "fixture",
            "reported": {
                "statistic": statistic, "family": "t",
                "value": r2(s["t"]), "df": r2(s["df"]), "n": s["n"], "page": 4,
            },
        },
        "multi100": None,
        "environment": {"language_hint": "R", "versions_named": {}},
    })

    sentence = statistic
    write_json(HERE / "runs" / "stage0" / "claims.json", [
        {"claim_id": "c1", "study_id": "s1", "claim_type": "scalar", "importance": "headline",
         "quantity_kind": "t", "value": r2(s["t"]), "precision": 2,
         "location": {"page": 4, "kind": "text", "label": "Results"},
         "description": sentence,
         "extraction": {"model_a": "fixture", "model_b": "fixture", "agreed": True}},
        {"claim_id": "c2", "study_id": "s1", "claim_type": "scalar", "importance": "headline",
         "quantity_kind": "d", "value": r2(s["d"]), "precision": 2,
         "location": {"page": 4, "kind": "text", "label": "Results"},
         "description": sentence,
         "extraction": {"model_a": "fixture", "model_b": "fixture", "agreed": True}},
        {"claim_id": "c3", "study_id": "s1", "claim_type": "scalar", "importance": "supporting",
         "quantity_kind": "mean", "value": r2(s["m_treatment"]), "precision": 2,
         "location": {"page": 4, "kind": "text", "label": "Results"},
         "description": "Mean outcome in the treatment condition.",
         "extraction": {"model_a": "fixture", "model_b": "fixture", "agreed": True}},
        {"claim_id": "c4", "study_id": "s1", "claim_type": "scalar", "importance": "supporting",
         "quantity_kind": "p_value", "value": 0.01, "precision": 2,
         "location": {"page": 4, "kind": "text", "label": "Results"},
         "description": sentence,
         "extraction": {"model_a": "fixture", "model_b": "fixture", "agreed": True}},
    ])

    contract = {
        "analysis_id": "a1", "claim_ids": ["c1", "c2", "c3", "c4"], "study_id": "s1",
        "sample_rule": "All randomised participants; the methods mention an attention check "
                       "but do not state whether failures were excluded.",
        "outcome": "outcome (post-test score)",
        "predictors": ["condition (control vs treatment)"],
        "covariates": ["baseline (optional; the methods report both adjusted and unadjusted means)"],
        "model_type": "two-group comparison (t-test or linear model)",
        "estimator": "OLS / Welch t-test", "se_type": "unspecified",
        "transformations": [], "weights": None,
        "missingness": "complete cases", "software_named": ["R"], "versions_named": {},
        "ambiguities": [
            {"field": "sample_rule", "options": ["exclude attention-check failures", "keep all cases"],
             "note": "The attention check is described but no exclusion is stated."},
            {"field": "covariates", "options": ["baseline adjusted", "unadjusted"],
             "note": "Both adjusted and unadjusted means appear in the paper."},
            {"field": "sample_rule", "options": ["no outlier rule", "3 SD trim", "winsorise"],
             "note": "No outlier handling is described."},
        ],
    }
    write_json(HERE / "runs" / "stage0" / "contracts.json", [contract])

    blind = dict(contract)
    blind["claim_ids"] = ["c1", "c2", "c3", "c4"]
    write_json(HERE / "runs" / "stage0" / "blind_contract.json", [blind])

    write_json(HERE / "runs" / "stage0" / "schema.json", {
        "files": [{
            "path": "data/fixture_study.csv", "format": "csv", "rows": len(rows), "cols": 6,
            "columns": [
                {"name": "pid", "type": "integer", "role": "identifier"},
                {"name": "condition", "type": "character", "levels": ["control", "treatment"],
                 "role": "predictor"},
                {"name": "baseline", "type": "numeric", "role": "covariate",
                 "note": "standardised pre-test score"},
                {"name": "outcome", "type": "numeric", "role": "outcome",
                 "note": "post-test score; one value of 12.4 is far above the rest"},
                {"name": "attention_check", "type": "integer", "levels": [0, 1],
                 "role": "screening", "note": "8 participants scored 0"},
                {"name": "age", "type": "integer", "role": "demographic"},
            ],
        }],
        "unit_of_observation": "participant",
        "missing_sentinels": [],
    })

    write_json(HERE / "runs" / "stage0" / "readiness.json", {
        "files": [{"path": "data/fixture_study.csv", "format": "csv", "rows": len(rows), "cols": 6}],
        "unit_of_observation": "participant", "keys": ["pid"], "missing_sentinels": [],
        "variable_bindings": [
            {"contract_field": "outcome", "candidate_columns": ["outcome"], "chosen": "outcome"},
            {"contract_field": "predictors", "candidate_columns": ["condition"], "chosen": "condition"},
            {"contract_field": "covariates", "candidate_columns": ["baseline"], "chosen": "baseline"},
        ],
        "scale_direction_notes": ["Higher outcome = better performance."],
        "weights_columns": [], "per_analysis_state": {"a1": "complete"},
    })

    for rid, family, model, keep_failures, ran in [
        ("opus_1", "opus", "opus", False, True),
        ("glm_1", "glm", "z-ai/glm-5.3-flash", True, True),
    ]:
        rule = ("kept all cases; the methods do not state an exclusion"
                if keep_failures else "excluded participants failing the attention check")
        write_json(HERE / "runs" / "stage1" / "replicas" / rid / "trace.json", {
            "replica_id": rid, "family": family, "model": model,
            "route": "claude_p" if family == "opus" else "opencode",
            "filters": [rule],
            "transformations": [], "model_formula": "outcome ~ condition",
            "missingness": "complete cases", "weights": None,
            "estimator_settings": {"var_equal": False},
            "seed": 20260901, "software": "R 4.6.1",
            "open_choices": [
                f"attention check: {rule}",
                "covariate: ran the unadjusted comparison; baseline adjustment was also available",
                "outliers: no trimming rule applied",
            ],
            "fixes": [], "ran": ran,
            "run_checks": {"steps_done": 4, "exit_code": 0, "outputs_present": True,
                           "loops": 0, "n_fixes": 0, "wall_s": 41.0},
            "hardcoding_audit": {"hits": []},
        })

    analysis_r = """# Replica opus_1 — focal analysis for claim c2 (Cohen's d)
set.seed(20260901)
library(jsonlite)

d <- read.csv("data/fixture_study.csv", stringsAsFactors = FALSE)
d <- d[d$attention_check == 1, ]                    # attention-check failures excluded
d$condition <- factor(d$condition, levels = c("control", "treatment"))

tt <- t.test(outcome ~ condition, data = d, var.equal = FALSE)
a <- d$outcome[d$condition == "control"]
b <- d$outcome[d$condition == "treatment"]
sp <- sqrt(((length(a) - 1) * var(a) + (length(b) - 1) * var(b)) / (length(a) + length(b) - 2))
cohen_d <- (mean(b) - mean(a)) / sp

res <- list(
  list(claim_id = "c1", analysis_id = "a1", value = unname(-tt$statistic),
       n = nrow(d), note = "Welch t, treatment vs control"),
  list(claim_id = "c2", analysis_id = "a1", value = cohen_d,
       se = sqrt((length(a) + length(b)) / (length(a) * length(b)) +
                 cohen_d^2 / (2 * (length(a) + length(b)))),
       n = nrow(d), note = "Cohen's d, pooled SD"),
  list(claim_id = "c3", analysis_id = "a1", value = mean(b), n = length(b), note = "treatment mean")
)
dir.create("out", showWarnings = FALSE)
write_json(list(replica_id = "opus_1", results = res), "out/results.json",
           auto_unbox = TRUE, digits = 6)
"""
    p = HERE / "runs" / "stage1" / "replicas" / "opus_1" / "work" / "out"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analysis.R").write_text(analysis_r)
    se_d = math.sqrt(2 / (s["n"] / 2) + s["d"] ** 2 / (2 * s["n"]))
    write_json(p / "results.json", {"replica_id": "opus_1", "results": [
        {"claim_id": "c1", "analysis_id": "a1", "value": round(s["t"], 4), "n": s["n"],
         "note": "Welch t, treatment vs control"},
        {"claim_id": "c2", "analysis_id": "a1", "value": round(s["d"], 4), "se": round(se_d, 4),
         "n": s["n"], "note": "Cohen's d, pooled SD"},
        {"claim_id": "c3", "analysis_id": "a1", "value": round(s["m_treatment"], 4),
         "n": s["n"] // 2, "note": "treatment mean"},
    ]})

    write_json(HERE / "runs" / "stage1" / "match.json", {
        "rows": [
            {"claim_id": "c2", "replica_id": "opus_1", "quantity_kind": "d",
             "reported": r2(s["d"]), "replicated": round(s["d"], 4), "unit_check": "ok",
             "raw_diff": round(s["d"] - r2(s["d"]), 4), "std_diff": 0.01,
             "sign_match": True, "band": "A", "sigma_rule": "within"},
            {"claim_id": "c2", "replica_id": "glm_1", "quantity_kind": "d",
             "reported": r2(s["d"]), "replicated": round(s["d"] * 0.86, 4), "unit_check": "ok",
             "raw_diff": round(s["d"] * 0.86 - r2(s["d"]), 4), "std_diff": 0.5,
             "sign_match": True, "band": "B", "sigma_rule": "within"},
            {"claim_id": "c1", "replica_id": "opus_1", "quantity_kind": "t",
             "reported": r2(s["t"]), "replicated": round(s["t"], 4), "unit_check": "ok",
             "raw_diff": 0.0, "std_diff": None, "sign_match": True, "band": "A",
             "sigma_rule": "na"},
        ],
        "summaries": [
            {"claim_id": "c2", "n_ran": 2, "fraction_matched": 1.0,
             "dispersion": {"decision_agreement": 0.5, "numeric_cv": 0.09}},
            {"claim_id": "c1", "n_ran": 1, "fraction_matched": 1.0, "dispersion": None},
        ],
        "table_cell_fractions": {},
    })

    print(f"fixture written under {HERE}")
    print(f"  paper spec: n={s['n']}  t={s['t']:.3f}  df={s['df']:.2f}  d={s['d']:.3f}")


if __name__ == "__main__":
    main()

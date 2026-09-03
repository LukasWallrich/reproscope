"""Offline tests for Stage 3: focal-claim binding, the grid builder, and the ranking.

The live fixture run is driven from the CLI, not from here:
    .venv/bin/python tests/fixtures/stage3/install.py
    .venv/bin/python -m reproscope run _fixture3 --stages 3
"""

from __future__ import annotations

import csv
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from reproscope import artifacts, paths
from reproscope import focal as focal_mod
from reproscope.artifacts import ClaimRecord, EstimandContract
from reproscope.stage3 import multiverse as mv

FIXTURE = Path(__file__).parent / "fixtures" / "stage3"


def _load(name: str, path: Path):
    """Import a fixture helper by path: several fixture dirs hold an `install.py`,
    so putting them on sys.path would make the first one imported win for all."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixture_install = _load("stage3_fixture_install", FIXTURE / "install.py")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A reproscope root holding only the fixture paper, plus the real prompts."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    real = Path(__file__).resolve().parent.parent
    shutil.copytree(real / "reproscope" / "prompts", tmp_path / "reproscope" / "prompts")
    fixture_install.install(tmp_path)
    return tmp_path


# --- number parsing --------------------------------------------------------


def test_numbers_in_reads_a_leading_decimal_point_as_a_fraction():
    assert focal_mod._numbers_in("d = .42, t(27) = 5.91") == [0.42, 27.0, 5.91]


def test_as_float_strips_a_leading_comparator():
    assert focal_mod._as_float("< .001") == pytest.approx(0.001)
    assert focal_mod._as_float(">=2.5") == pytest.approx(2.5)
    assert focal_mod._as_float("3.2") == pytest.approx(3.2)


# --- step 1: focal-claim binding -----------------------------------------


def _fixture_inputs(root: Path):
    manifest = paths.manifest("_fixture3")
    claims = artifacts.load(ClaimRecord, root / "runs" / "_fixture3" / "stage0" / "claims.json")
    contracts = artifacts.load(
        EstimandContract, root / "runs" / "_fixture3" / "stage0" / "contracts.json"
    )
    return manifest, claims, contracts


def test_binding_prefers_the_effect_size_over_the_test_statistic(sandbox):
    manifest, claims, contracts = _fixture_inputs(sandbox)
    focal = focal_mod.bind_focal_claim(manifest, claims, contracts, allow_llm=False)

    # every claim whose value appears in the reported sentence is bound...
    assert set(focal["claim_ids"]) >= {"c1", "c2", "c3"}
    # ...but the curve is drawn in d, not in t
    assert focal["focal_quantity"]["claim_id"] == "c2"
    assert focal["focal_quantity"]["kind"] == "d"
    assert focal["focal_quantity"]["reported_value"] == pytest.approx(0.63, abs=0.01)
    assert focal["focal_quantity"]["derived_from"] is None
    assert focal["analysis_id"] == "a1"


def test_binding_derives_d_when_only_t_is_reported(sandbox):
    manifest, claims, contracts = _fixture_inputs(sandbox)
    claims = [c for c in claims if c.quantity_kind != "d"]  # paper reports no effect size
    focal = focal_mod.bind_focal_claim(manifest, claims, contracts, allow_llm=False)

    fq = focal["focal_quantity"]
    assert fq["claim_id"] == "c3" or fq["kind"] in {"d", "mean"}
    # drop the group mean too: only the t statistic is left
    claims = [c for c in claims if c.quantity_kind not in {"d", "mean"}]
    fq = focal_mod.bind_focal_claim(manifest, claims, contracts, allow_llm=False)["focal_quantity"]
    assert fq["kind"] == "d"
    assert fq["derived_from"] == "t"
    t, df = manifest.focal_claim.reported.value, manifest.focal_claim.reported.df
    assert fq["reported_value"] == pytest.approx(2 * t / df**0.5)


def test_binding_raises_when_nothing_matches(sandbox):
    manifest, _claims, contracts = _fixture_inputs(sandbox)
    other = [ClaimRecord(claim_id="x1", quantity_kind="coefficient", value=99.9,
                         description="An unrelated coefficient.")]
    with pytest.raises(ValueError):
        focal_mod.bind_focal_claim(manifest, other, contracts, allow_llm=False)


# --- step 3: grid builder ------------------------------------------------


PROPOSED = {
    "factors": [
        {"name": "attention check", "field": "sample_rule", "source": "trace",
         "paper_level": "exclude failures",
         "levels": [{"value": "exclude failures", "how": "filter attention_check == 1"},
                    {"value": "keep all", "how": "no filter"}]},
        {"name": "covariate", "field": "covariates", "source": "trace",
         "paper_level": "unadjusted",
         "levels": [{"value": "unadjusted", "how": "outcome ~ condition"},
                    {"value": "baseline adjusted", "how": "outcome ~ condition + baseline"}]},
        {"name": "outliers", "field": "sample_rule", "source": "default",
         "paper_level": "keep",
         "levels": [{"value": "keep", "how": "no trimming"},
                    {"value": "3 SD trim", "how": "drop |z| > 3 on outcome"},
                    {"value": "drop odd ids", "how": "drop odd pid"}]},
        {"name": "estimator", "field": "model", "source": "grid", "paper_level": "welch",
         "levels": [{"value": "welch", "how": "var.equal = FALSE"},
                    {"value": "pooled", "how": "var.equal = TRUE"}]},
    ]
}
SCREEN = {
    "factors": [
        {"name": "attention check",
         "levels": [{"value": "exclude failures", "verdict": "defensible", "rationale": "standard"},
                    {"value": "keep all", "verdict": "defensible", "rationale": "pre-registered ITT"}]},
        {"name": "covariate",
         "levels": [{"value": "unadjusted", "verdict": "defensible", "rationale": "the paper's own"},
                    {"value": "baseline adjusted", "verdict": "defensible", "rationale": "ANCOVA"}]},
        {"name": "outliers",
         "levels": [{"value": "keep", "verdict": "defensible", "rationale": "no rule stated"},
                    {"value": "3 SD trim", "verdict": "defensible", "rationale": "common"},
                    {"value": "drop odd ids", "verdict": "rejected",
                     "rationale": "arbitrary; unrelated to the outcome"}]},
        {"name": "estimator",
         "levels": [{"value": "welch", "verdict": "defensible", "rationale": "default"},
                    {"value": "pooled", "verdict": "defensible", "rationale": "equal n"}]},
    ],
    "incompatible": [
        {"a": "covariate=baseline adjusted", "b": "estimator=welch",
         "why": "Welch's correction has no meaning in a covariate-adjusted linear model"},
        {"a": "covariate=baseline adjusted", "b": "nonexistent=level", "why": "unresolvable"},
    ],
    "adjustments": ["consider merging the two sample-rule factors"],
}


def test_grid_drops_rejected_levels_and_prunes_incompatible_pairs():
    grid = mv.build_grid(PROPOSED, SCREEN)

    outliers = next(f for f in grid["factors"] if f["name"] == "outliers")
    assert [lv["value"] for lv in outliers["levels"]] == ["keep", "3 SD trim"]
    assert grid["rejected_levels"] == [
        {"factor": "outliers", "level": "drop odd ids",
         "rationale": "arbitrary; unrelated to the outcome"}
    ]

    # the unresolvable incompatibility is dropped and noted, the real one is kept
    assert len(grid["incompatible"]) == 1
    assert any("does not resolve" in n for n in grid["notes"])

    # 2 x 2 x 2 x 2 = 16 full factorial, minus the 4 combinations pairing
    # "baseline adjusted" with "welch"
    assert grid["full_factorial"] == 16
    assert grid["grid_size"] == 12
    specs = mv.grid_specs(grid)
    assert len(specs) == 12
    assert not any(s["covariate"] == "baseline adjusted" and s["estimator"] == "welch"
                   for s in specs)

    assert outliers["paper_level"] == "keep"


def test_grid_keeps_a_single_level_factor_without_multiplying_the_grid():
    screen = json.loads(json.dumps(SCREEN))
    for lv in next(f for f in screen["factors"] if f["name"] == "estimator")["levels"]:
        if lv["value"] == "pooled":
            lv["verdict"] = "rejected"
            lv["rationale"] = "unequal variances by design"
    grid = mv.build_grid(PROPOSED, screen)

    estimator = next(f for f in grid["factors"] if f["name"] == "estimator")
    assert [lv["value"] for lv in estimator["levels"]] == ["welch"]
    # 2 x 2 x 2 x 1 = 8, minus the 4 combinations pairing adjusted with the only
    # surviving estimator level
    assert grid["grid_size"] == 4


def test_grid_drops_a_whole_factor_when_the_screen_rejects_every_level():
    proposed = json.loads(json.dumps(PROPOSED))
    next(f for f in proposed["factors"] if f["name"] == "outliers")["paper_level"] = None
    screen = json.loads(json.dumps(SCREEN))
    for lv in next(f for f in screen["factors"] if f["name"] == "outliers")["levels"]:
        lv["verdict"] = "rejected"
    grid = mv.build_grid(proposed, screen)

    assert not any(f["name"] == "outliers" for f in grid["factors"])
    assert any("every level was rejected" in n for n in grid["notes"])


def test_the_screen_can_never_remove_the_paper_s_own_level():
    """The reported estimate must have a place on the curve, however the screen votes."""
    screen = json.loads(json.dumps(SCREEN))
    for lv in next(f for f in screen["factors"] if f["name"] == "outliers")["levels"]:
        lv["verdict"] = "rejected"          # including "keep", the paper's own choice
        lv["rationale"] = "no rule was prespecified"
    grid = mv.build_grid(PROPOSED, screen)

    outliers = next(f for f in grid["factors"] if f["name"] == "outliers")
    assert [(lv["value"], lv["verdict"]) for lv in outliers["levels"]] == [("keep", "paper")]
    assert outliers["levels"][0]["screen_verdict"] == "rejected"
    assert outliers["paper_level"] == "keep"
    assert grid["paper_level_flagged"] == [
        {"factor": "outliers", "level": "keep", "rationale": "no rule was prespecified"}
    ]
    # the other two levels are still rejected outright
    assert {r["level"] for r in grid["rejected_levels"]} == {"3 SD trim", "drop odd ids"}


def test_derived_paper_levels_override_the_enumerator_s_guess():
    grid = mv.build_grid(PROPOSED, SCREEN,
                         paper_levels={"attention check": "keep all"})

    attention = next(f for f in grid["factors"] if f["name"] == "attention check")
    assert attention["paper_level"] == "keep all"       # not the enumerator's "exclude failures"
    assert [lv["verdict"] for lv in attention["levels"]] == ["defensible", "paper"]


def test_grid_cap_drops_the_lowest_priority_factors_last_first():
    proposed = {"factors": [
        {"name": f"f{i}", "paper_level": "a",
         "levels": [{"value": "a", "how": ""}, {"value": "b", "how": ""},
                    {"value": "c", "how": ""}]}
        for i in range(8)
    ]}
    screen = {"factors": [
        {"name": f["name"], "levels": [{"value": lv["value"], "verdict": "defensible"}
                                       for lv in f["levels"]]}
        for f in proposed["factors"]
    ]}
    grid = mv.build_grid(proposed, screen, cap=256)

    assert grid["grid_size"] <= 256
    assert grid["grid_size"] == 3**5  # 243; a sixth varying factor would be 729
    assert grid["dropped_factors"] == ["f7", "f6", "f5"]
    # Pinned to the paper's level rather than removed, so the paper's own specification
    # is still a row in the grid and the executor still implements the choice.
    assert [f["name"] for f in grid["factors"]] == [f"f{i}" for i in range(8)]
    assert [len(f["levels"]) for f in grid["factors"]] == [3, 3, 3, 3, 3, 1, 1, 1]
    assert all(f["levels"][0]["value"] == "a" for f in grid["factors"][5:])
    assert any("pinned to the paper's level" in n for n in grid["notes"])


def test_unscreened_levels_are_kept_and_flagged():
    screen = json.loads(json.dumps(SCREEN))
    screen["factors"] = [f for f in screen["factors"] if f["name"] != "estimator"]
    grid = mv.build_grid(PROPOSED, screen)

    estimator = next(f for f in grid["factors"] if f["name"] == "estimator")
    assert len(estimator["levels"]) == 2
    assert any("not returned by the screen" in n for n in grid["notes"])


# --- step 5: ranking ------------------------------------------------------


def _rows(estimates, ps=None, converged=None):
    ps = ps or [0.01] * len(estimates)
    converged = converged if converged is not None else [True] * len(estimates)
    return [
        {"estimate": "" if e is None else e, "p": p, "converged": str(c).lower(),
         "se": 0.2, "n": 72, "spec": f"s{i}", "_estimate": e, "_se": 0.2, "_p": p,
         "_converged": c}
        for i, (e, p, c) in enumerate(zip(estimates, ps, converged))
    ]


def test_rank_places_the_reported_estimate_and_reports_extremeness():
    rows = _rows([0.1, 0.2, 0.3, 0.4, 0.5])
    r = mv.rank_reported(rows, 0.46)

    assert r["n_converged"] == 5
    assert r["rank"] == 5              # four estimates lie below 0.46
    assert r["share_below"] == pytest.approx(4 / 5)
    assert r["share_above"] == pytest.approx(1 / 5)
    assert r["share_tied"] == 0.0
    assert r["extremeness"] == pytest.approx(1 / 5)   # the smaller of the two shares
    assert r["median"] == 0.3
    assert r["share_same_sign"] == 1.0
    assert r["share_p05"] == 1.0
    assert r["closest_spec"]["estimate"] == 0.5


def test_estimates_that_round_to_the_reported_value_are_ties():
    """0.6334 is not "above" a reported 0.63: the paper never resolved that digit."""
    rows = _rows([0.386, 0.495, 0.574, 0.6334, 0.6334])
    r = mv.rank_reported(rows, 0.63, precision=2)

    assert r["share_below"] == pytest.approx(3 / 5)
    assert r["share_tied"] == pytest.approx(2 / 5)
    assert r["share_above"] == 0.0
    assert r["extremeness"] == 0.0          # the paper sits at the top of the curve
    assert r["rank"] == 4
    assert r["reported_precision"] == 2

    # Without a precision the same rows compare exactly, and the ties become "above".
    exact = mv.rank_reported(rows, 0.63)
    assert exact["share_above"] == pytest.approx(2 / 5)
    assert exact["share_tied"] == 0.0
    assert exact["extremeness"] == pytest.approx(2 / 5)


def test_extremeness_is_symmetric_at_both_ends():
    """Outside the curve is 0 whichever end it falls off; the middle is the maximum."""
    rows = _rows([1.0, 2.0, 3.0])
    low, high, mid = (mv.rank_reported(rows, v) for v in (0.0, 9.0, 2.0))

    assert (low["rank"], high["rank"]) == (1, 4)
    assert low["share_below"] == 0.0 and low["share_above"] == pytest.approx(1.0)
    assert high["share_below"] == pytest.approx(1.0) and high["share_above"] == 0.0
    assert low["extremeness"] == high["extremeness"] == 0.0
    # 2.0 ties one estimate: one below, one above, the tie counts towards neither
    assert mid["share_below"] == mid["share_above"] == pytest.approx(1 / 3)
    assert mid["share_tied"] == pytest.approx(1 / 3)
    assert mid["extremeness"] == pytest.approx(1 / 3)


def test_rank_ignores_failed_specifications_and_counts_shares():
    rows = _rows([0.5, -0.2, 0.9, None], ps=[0.01, 0.4, 0.02, None],
                 converged=[True, True, True, False])
    r = mv.rank_reported(rows, 0.6)

    assert r["n_specs_total"] == 4
    assert r["n_converged"] == 3
    assert r["n_failed"] == 1
    assert r["share_same_sign"] == pytest.approx(2 / 3)
    assert r["share_p05"] == pytest.approx(2 / 3)


def test_rank_finds_the_paper_level_specification():
    grid = mv.build_grid(PROPOSED, SCREEN)
    specs = mv.grid_specs(grid)
    rows = []
    for i, s in enumerate(specs):
        row = dict(s)
        row.update({"_estimate": 0.1 * i, "_se": 0.2, "_p": 0.01, "_converged": True})
        rows.append(row)
    r = mv.rank_reported(rows, 0.35, grid)

    assert r["paper_level_spec"] == {"attention check": "exclude failures",
                                     "covariate": "unadjusted", "outliers": "keep",
                                     "estimator": "welch"}
    assert r["paper_level_estimate"] is not None


# --- specs.csv reading ----------------------------------------------------


def test_read_specs_parses_flags_and_blank_estimates(tmp_path):
    p = tmp_path / "specs.csv"
    p.write_text("outliers,estimate,se,p,n,converged,error\n"
                 "keep,0.63,0.24,0.01,72,TRUE,\n"
                 "3 SD trim,,,,,FALSE,singular fit\n")
    rows = mv.read_specs(p)

    assert rows[0]["_estimate"] == 0.63 and rows[0]["_converged"] is True
    assert rows[0]["_n"] == 72          # an integer, not the CSV's text
    assert rows[1]["_estimate"] is None and rows[1]["_converged"] is False
    assert rows[1]["_n"] is None


def test_parse_interpretation_reads_the_trailing_json_block():
    md = "Some prose.\n\n```json\n{\"median\": 0.5, \"n_specs\": 12}\n```\n"
    assert mv.parse_interpretation(md) == {"median": 0.5, "n_specs": 12}


def test_interpretation_prompt_carries_specs_and_factors_but_no_ranking():
    grid = {"factors": [{"name": "outliers", "levels": [{"value": "keep"}, {"value": "drop"}]}],
            "sampled": False, "n_specs": 2, "grid_size": 2}
    prompt = mv.interpretation_prompt("spec_id,estimate\n1,0.3\n2,0.4\n", 0.35, grid)
    assert "spec_id,estimate" in prompt and "0.35" in prompt
    assert "outliers" in prompt and "keep" in prompt
    assert "the whole grid" in prompt
    for leaked in ("extremeness", "share_below", "share_above", "rank"):
        assert leaked not in prompt


def test_interpretation_prompt_says_when_the_executed_set_is_a_sample():
    grid = {"factors": [], "sampled": True, "n_specs": 64, "grid_size": 256}
    assert "a sample of the multiverse" in mv.interpretation_prompt("csv", 1.0, grid)


# --- work assembly --------------------------------------------------------


def test_assemble_work_picks_the_best_matching_replica_and_withholds_the_value(sandbox):
    manifest, claims, contracts = _fixture_inputs(sandbox)
    focal = focal_mod.bind_focal_claim(manifest, claims, contracts, allow_llm=False)
    grid = mv.build_grid(PROPOSED, SCREEN)
    info = mv.assemble_work("_fixture3", focal, grid)

    work = Path(info["work"])
    assert info["base_replica"] == "opus_1"      # band A on the focal claim
    assert (work / "BASE_ANALYSIS.R").exists()
    assert (work / "data" / "fixture_study.csv").exists()
    assert (work / "data" / "codebook.md").exists()
    executor_grid = json.loads((work / "GRID.json").read_text())
    assert executor_grid["grid_size"] == 12
    # Every level in the executor's copy is a level to run: no verdict to filter on,
    # which is how a generated script would otherwise drop the paper's own level.
    levels = [lv for f in executor_grid["factors"] for lv in f["levels"]]
    assert levels and all(set(lv) == {"value", "how"} for lv in levels)
    # The specifications are enumerated for the executor, not left for it to derive.
    assert [s["spec_id"] for s in executor_grid["specs"]] == [
        f"spec_{i:03d}" for i in range(1, 13)
    ]

    contract = json.loads((work / "CONTRACT.json").read_text())
    assert contract["focal_claim"]["quantity"]["kind"] == "d"
    assert "reported_value" not in contract["focal_claim"]["quantity"]
    # The results sentence carries the group means and the test statistic, so it is not
    # copied at all; the focal value itself is scrubbed wherever else it appears.
    assert "description" not in contract["focal_claim"]["quantity"]
    blob = json.dumps(contract)
    for token in ("0.63", "5.37", "4.43", "2.69"):
        assert token not in blob
    assert info["value_scan"]["clean"] is True


def test_verification_flags_spec_ids_that_do_not_match_the_grid(sandbox, monkeypatch):
    """Twelve rows carrying the wrong ids must not pass as twelve correct ones."""
    grid = mv.build_grid(PROPOSED, SCREEN)
    ids = [s["spec_id"] for s in mv.enumerate_specs(grid)]
    work = sandbox / "work"
    (work / "out").mkdir(parents=True)

    def write(spec_ids):
        with (work / "out" / "specs.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(mv.RESULT_COLUMNS))
            w.writeheader()
            for i, sid in enumerate(spec_ids):
                w.writerow({"spec_id": sid, "estimate": 0.1 * i, "se": 0.2, "p": 0.01,
                            "n": 72, "converged": "TRUE", "error": ""})

    monkeypatch.setattr(mv, "hardcoding_audit", lambda *a, **k: {"verdict": "clean", "hits": []})

    write(ids)
    ok = mv.verify_execution(work, grid, "_fixture3")
    assert ok["checks"]["matched_by"] == "spec_id"
    assert ok["checks"]["specs_match_grid"] is True
    # no multiverse.R was written, so that is the only complaint
    assert ok["problems"] == ["no out/multiverse.R or out/multiverse.py to re-run"]

    write(ids[:10] + [ids[0], "spec_999"])   # right count, one duplicated, one invented
    bad = mv.verify_execution(work, grid, "_fixture3")
    assert bad["checks"]["row_count_matches"] is True
    assert bad["checks"]["duplicate_spec_ids"] == [ids[0]]
    assert bad["checks"]["missing_spec_ids"] == [ids[10], ids[11]]
    assert bad["checks"]["unexpected_spec_ids"] == ["spec_999"]
    assert any("spec ids do not match the grid" in p for p in bad["problems"])


def test_verification_falls_back_to_factor_columns_without_spec_ids(sandbox, monkeypatch):
    """Old-format output still verifies, and says it was matched the weaker way."""
    grid = mv.build_grid(PROPOSED, SCREEN)
    specs = mv.grid_specs(grid)
    names = [f["name"] for f in grid["factors"]]
    work = sandbox / "work"
    (work / "out").mkdir(parents=True)
    with (work / "out" / "specs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[mv._norm_name(n) for n in names]
                           + ["estimate", "se", "p", "n", "converged", "error"])
        w.writeheader()
        for i, s in enumerate(specs):
            w.writerow({**{mv._norm_name(k): v for k, v in s.items()},
                        "estimate": 0.1 * i, "se": 0.2, "p": 0.01, "n": 72,
                        "converged": "TRUE", "error": ""})

    monkeypatch.setattr(mv, "hardcoding_audit", lambda *a, **k: {"verdict": "clean", "hits": []})
    report = mv.verify_execution(work, grid, "_fixture3")

    assert report["checks"]["matched_by"] == "factor_columns"
    # `se` must not be read as a shortened "Sex covariate set": the result columns are
    # never factor columns.
    assert report["checks"]["specs_match_grid"] is True
    assert any("no spec_id column" in p for p in report["problems"])


def _wide_grid(paper_id: str | None = "_fixture3"):
    """A 4 x 5 x 5 x 2 = 200-specification grid, every level defensible."""
    sizes = (4, 5, 5, 2)
    proposed = {"factors": [
        {"name": f"f{i}", "paper_level": "L0",
         "levels": [{"value": f"L{j}", "how": ""} for j in range(n)]}
        for i, n in enumerate(sizes)
    ]}
    screen = {"factors": [
        {"name": f["name"], "levels": [{"value": lv["value"], "verdict": "defensible"}
                                       for lv in f["levels"]]}
        for f in proposed["factors"]
    ]}
    return mv.build_grid(proposed, screen, paper_id=paper_id)


def test_a_grid_over_the_execution_cap_runs_a_stratified_sample():
    grid = _wide_grid()

    assert grid["grid_size"] == 200          # the full pruned grid is still reported
    assert grid["n_specs"] == mv.EXEC_CAP == 64
    assert grid["sampled"] is True
    assert grid["sample_fraction"] == 0.32
    assert any("stratified fractional sample" in n for n in grid["notes"])

    specs = mv.enumerate_specs(grid)
    assert len(specs) == 64
    # the paper's own specification is in, and every level of every factor is covered
    assert [s["spec_id"] for s in specs if s.get("is_paper_level")] == ["spec_001"]
    for f in grid["factors"]:
        covered = {s["levels"][f["name"]] for s in specs}
        assert covered == {lv["value"] for lv in f["levels"]}, f["name"]
    # ids keep their place in the full enumeration, so they are not renumbered 1..64
    assert specs[-1]["spec_id"] != "spec_064"


def test_the_sample_is_the_same_on_every_call_and_differs_by_paper():
    assert _wide_grid()["sampled_spec_ids"] == _wide_grid()["sampled_spec_ids"]
    assert _wide_grid("other_paper")["sampled_spec_ids"] != _wide_grid()["sampled_spec_ids"]


def test_a_grid_under_the_execution_cap_runs_whole(sandbox):
    grid = mv.build_grid(PROPOSED, SCREEN, paper_id="_fixture3")
    assert grid["n_specs"] == grid["grid_size"] == 12
    assert grid["sampled"] is False
    assert "sampled_spec_ids" not in grid
    assert len(mv.enumerate_specs(grid)) == 12


def test_verification_expects_the_executed_count_not_the_grid_size(tmp_path):
    grid = _wide_grid()
    specs = mv.enumerate_specs(grid)
    out = tmp_path / "out"
    out.mkdir()
    with (out / "specs.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["spec_id", "estimate", "se", "p", "n", "converged"])
        for s in specs:
            w.writerow([s["spec_id"], 0.4, 0.1, 0.01, 100, "TRUE"])

    report = mv.verify_execution(tmp_path, grid, "_fixture3")
    assert report["checks"]["n_expected"] == 64
    assert report["checks"]["grid_size"] == 200
    assert report["checks"]["sampled"] is True
    assert report["checks"]["specs_match_grid"] is True
    assert report["checks"]["row_count_matches"] is True
    assert not any("rows" in p for p in report["problems"])


def test_enumerated_specs_are_stable_and_mark_the_paper_s_own(sandbox):
    grid = mv.build_grid(PROPOSED, SCREEN)
    specs = mv.enumerate_specs(grid)

    assert len(specs) == grid["grid_size"] == 12
    assert [s["spec_id"] for s in specs] == [f"spec_{i:03d}" for i in range(1, 13)]
    # enumerator order, last factor varying fastest
    assert specs[0]["levels"] == {"attention check": "exclude failures",
                                  "covariate": "unadjusted", "outliers": "keep",
                                  "estimator": "welch"}
    assert specs[1]["levels"]["estimator"] == "pooled"
    assert mv.enumerate_specs(grid) == specs
    paper = [s for s in specs if s.get("is_paper_level")]
    assert [s["spec_id"] for s in paper] == ["spec_001"]


def test_read_specs_joins_the_grid_levels_onto_spec_ids(tmp_path):
    """The executor may write ids alone; the level strings come from the grid."""
    grid = mv.build_grid(PROPOSED, SCREEN)
    p = tmp_path / "specs.csv"
    p.write_text("spec_id,estimate,se,p,n,converged,error\n"
                 "spec_003,0.41,0.2,0.03,72,TRUE,\n"
                 "spec_001,0.63,0.24,0.01,72,TRUE,\n"
                 "spec_404,,,,,FALSE,unknown spec\n")
    rows = mv.read_specs(p, grid)

    assert [r["_spec_id"] for r in rows] == ["spec_003", "spec_001", "spec_404"]
    assert rows[1]["attention check"] == "exclude failures"   # the grid's exact string
    assert rows[0]["outliers"] == "3 SD trim"
    assert "outliers" not in rows[2]                          # no id, nothing joined

    ranked = mv.rank_reported(rows, 0.63, grid, precision=2)
    assert ranked["paper_level_spec_id"] == "spec_001"
    assert ranked["paper_level_estimate"] == 0.63


# --- step 2b: the paper's own levels --------------------------------------


def test_a_band_b_replica_does_not_override_the_enumerator(sandbox, monkeypatch):
    """Only a replica that reproduced the paper's number speaks for the paper."""
    match = sandbox / "runs" / "_fixture3" / "stage1" / "match.json"
    data = json.loads(match.read_text())
    for row in data["rows"]:
        row["band"] = "B"
    match.write_text(json.dumps(data))

    def refuse(*a, **k):  # the step must not spend a call it cannot trust
        raise AssertionError("derive_paper_levels called a model for a band-B replica")

    monkeypatch.setattr(mv.llm, "call", refuse)
    manifest, claims, contracts = _fixture_inputs(sandbox)
    focal = focal_mod.bind_focal_claim(manifest, claims, contracts, allow_llm=False)
    out = mv.derive_paper_levels("_fixture3", PROPOSED, focal)

    assert out["source"] == "enumerator"
    assert out["band"] == "B"
    assert out["levels"] == {"attention check": "exclude failures", "covariate": "unadjusted",
                             "outliers": "keep", "estimator": "welch"}
    assert any("no band-A replica" in n for n in out["notes"])


def test_a_band_a_replica_overrides_and_records_the_disagreement(sandbox, monkeypatch):
    answer = mv.PaperLevelsOut(levels=[
        # different case and spacing: it must map back onto the enumerator's own string
        mv.PaperLevel(factor="Attention Check", level="KEEP  ALL",
                      evidence="script has no attention_check filter"),
        mv.PaperLevel(factor="covariate", level="unadjusted", evidence="outcome ~ condition"),
        mv.PaperLevel(factor="outliers", level=None, evidence="not settled by the script"),
        mv.PaperLevel(factor="estimator", level="pooled", evidence="var.equal = TRUE"),
    ])
    monkeypatch.setattr(
        mv.llm, "call",
        lambda *a, **k: type("R", (), {"ok": True, "parsed": answer, "error": None,
                                       "ledger_id": "abc123"})(),
    )
    manifest, claims, contracts = _fixture_inputs(sandbox)
    focal = focal_mod.bind_focal_claim(manifest, claims, contracts, allow_llm=False)
    out = mv.derive_paper_levels("_fixture3", PROPOSED, focal)

    assert out["band"] == "A" and out["replica_id"] == "opus_1"
    assert out["levels"]["attention check"] == "keep all"      # overridden
    assert out["levels"]["estimator"] == "pooled"              # overridden
    assert out["levels"]["outliers"] == "keep"                 # unsettled: enumerator stands
    assert any("the enumerator guessed 'exclude failures'" in n for n in out["notes"])
    assert out["evidence"]["attention check"] == "script has no attention_check filter"


# --- step 4: a changed grid invalidates the executor's output --------------


def test_a_changed_grid_forces_the_executor_to_rerun(tmp_path):
    """specs.csv from an older grid must not be ranked against the new one."""
    import reproscope.stage3 as stage3

    stage_dir = tmp_path / "stage3"
    (stage_dir / "work" / "out").mkdir(parents=True)
    (stage_dir / "work" / "out" / "specs.csv").write_text("estimate\n0.5\n")
    execute = stage_dir / "execute.json"

    execute.write_text(json.dumps({"grid_sha": "sha-of-the-grid-it-ran"}))
    assert stage3.executor_stale(stage_dir, "sha-of-the-grid-it-ran", force=False) is False
    assert stage3.executor_stale(stage_dir, "a different grid", force=False) is True
    assert stage3.executor_stale(stage_dir, "sha-of-the-grid-it-ran", force=True) is True

    # no report, or a report whose specs.csv is gone: run it either way
    execute.unlink()
    assert stage3.executor_stale(stage_dir, "any", force=False) is True
    execute.write_text(json.dumps({"grid_sha": "any"}))
    (stage_dir / "work" / "out" / "specs.csv").unlink()
    assert stage3.executor_stale(stage_dir, "any", force=False) is True


def test_confidence_drops_when_the_focal_binding_used_a_fallback():
    import reproscope.stage3 as stage3

    grid = mv.build_grid(PROPOSED, SCREEN)
    paper = {"source": "replica opus_1 (band A)", "evidence": {}, "notes": []}

    def space_for(notes):
        focal = {"claim_ids": ["c2"], "analysis_id": "a1", "notes": notes,
                 "focal_quantity": {"claim_id": "c2", "kind": "d", "reported_value": 0.63}}
        return stage3._assemble("_fixture3", focal, grid, [], {}, {"problems": []},
                                "prose", {}, {}, [], paper)

    # an exact numeric match leaves no note; the manifest override and the t -> d
    # conversion are determinate too
    assert space_for([]).confidence == "high"
    assert space_for(["focal claim fixed by the manifest: c2"]).confidence == "high"
    assert space_for([
        "focal claim fixed by the manifest: c2",
        "only a t statistic was reported for the focal estimate; converted with d = ...",
    ]).confidence == "high"

    shaky = space_for(["no numeric match; claims bound by description overlap with the "
                       "focal sentence"])
    assert shaky.confidence == "medium"
    assert any("bound by a fallback rule" in a for a in shaky.open_ambiguities)
    assert space_for(["bound by cheap model call (abc): it names the same outcome"]) \
        .confidence == "medium"


def test_the_paper_verdict_survives_into_the_artifact():
    """space.json says `paper` outright, with the screen's own verdict alongside."""
    import reproscope.stage3 as stage3
    from reproscope.artifacts import SpecificationSpace

    screen = json.loads(json.dumps(SCREEN))
    for lv in next(f for f in screen["factors"] if f["name"] == "outliers")["levels"]:
        lv["verdict"] = "rejected"
        lv["rationale"] = "no rule was prespecified"
    grid = mv.build_grid(PROPOSED, screen)
    focal = {"claim_ids": ["c2"], "analysis_id": "a1", "notes": [],
             "focal_quantity": {"claim_id": "c2", "kind": "d", "reported_value": 0.63}}

    space = stage3._assemble(
        "_fixture3", focal, grid, [], {}, {"problems": []}, "prose", {}, {}, [],
        {"source": "replica opus_1 (band A)", "evidence": {}, "notes": []},
    )
    SpecificationSpace.model_validate(space.model_dump())   # the Literal accepts "paper"

    outliers = next(f for f in space.factors if f.name == "outliers")
    level = outliers.levels[0]
    assert (level.value, level.verdict) == ("keep", "paper")
    assert level.screen_verdict == "rejected"
    assert space.paper_level_flagged[0]["factor"] == "outliers"
    # a level nobody flagged keeps the screen's own verdict
    unadjusted = next(f for f in space.factors if f.name == "covariate").levels[0]
    assert (unadjusted.verdict, unadjusted.screen_verdict) == ("paper", "defensible")

"""Stage 1: the deterministic parts — grading rules, leak scan, assembly, trace coercion.

Everything here is offline. The live chain is exercised separately on the fixture
paper (tests/fixtures/stage1) with REPROSCOPE_FAMILIES / REPROSCOPE_RUNS.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from reproscope import artifacts, paths
from reproscope.stage1 import blind, match, replicas, rerun

FIXTURE = Path(__file__).parent / "fixtures" / "stage1"
sys.path.insert(0, str(FIXTURE))
import install  # noqa: E402


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A temp ROOT with the real prompts and models.toml, and the fixture paper installed."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    real = Path(__file__).resolve().parents[1]
    shutil.copytree(real / "reproscope" / "prompts", tmp_path / "reproscope" / "prompts")
    shutil.copy2(real / "models.toml", tmp_path / "models.toml")
    install.install(tmp_path)
    return tmp_path


# --- grading: bands on the relative rule ----------------------------------


@pytest.mark.parametrize(
    "replicated,band",
    [(4.694, "A"), (5.0, "B"), (5.8, "C"), (8.0, "fail")],
)
def test_relative_bands(replicated, band):
    assert match.grade("t", 4.69, replicated)["band"] == band


def test_sign_gate_fails_before_bands():
    g = match.grade("d", 1.21, -1.209)
    assert g["band"] == "fail" and g["sign_match"] is False


def test_unsigned_kinds_have_no_sign_gate():
    assert match.grade("sd", 0.66, 0.661)["sign_match"] is None


def test_absolute_rule_for_near_zero_reported():
    assert match.grade("coefficient", 0.0005, 0.0015)["band"] == "A"
    assert match.grade("coefficient", 0.0005, 0.004)["band"] == "fail"


def test_sign_gate_does_not_apply_to_a_near_zero_reported_value():
    # A coefficient reported as 0.000 has no meaningful sign; the absolute rule decides.
    assert match.grade("coefficient", 0.0005, -0.0003)["band"] == "A"


def test_rounding_to_reported_precision_is_applied():
    # 0.1049 differs by 4.9% raw, but the paper reports two decimals.
    assert match.grade("coefficient", 0.10, 0.1049)["band"] == "B"
    assert match.grade("coefficient", 0.10, 0.1049, precision=2)["band"] == "A"


# --- grading: p values and comparators ------------------------------------


@pytest.mark.parametrize(
    "reported,replicated,band",
    [
        (0.03, 0.0301, "A"),      # same number
        (0.03, 0.04, "B"),        # same side of every threshold, 33% apart
        (0.03, 0.06, "fail"),     # crosses .05
        (0.008, 0.02, "fail"),    # crosses .01
        (1e-5, 1e-8, "A"),        # both below .001
    ],
)
def test_p_value_rule(reported, replicated, band):
    assert match.grade("p_value", reported, replicated)["band"] == band


def test_comparator_claims_grade_on_the_threshold_side_only():
    reported, comparator = match.parse_reported("<.001")
    assert (reported, comparator) == (0.001, "<")
    hit = match.grade("p_value", reported, 1.7e-5, comparator=comparator)
    miss = match.grade("p_value", reported, 0.02, comparator=comparator)
    assert (hit["band"], miss["band"]) == ("A", "fail")
    assert hit["raw_diff"] is None


# --- grading: log scale, n, sigma rule, unit check -------------------------


def test_odds_ratio_bands_are_on_the_log_scale():
    # 1.05 vs 1.10 is 4.8% apart linearly but 95% apart in log odds.
    assert match.grade("coefficient", 1.05, 1.10)["band"] == "B"
    assert match.grade("OR", 1.05, 1.10)["band"] == "fail"
    assert match.grade("OR", 2.0, 2.02)["band"] == "A"
    assert match.grade("HR", 2.0, -1.0)["band"] == "fail"


def test_n_is_exact_or_within_one_percent():
    assert match.grade("n", 60, 60)["band"] == "A"
    assert match.grade("n", 1000, 1005)["band"] == "B"
    assert match.grade("n", 1000, 1100)["band"] == "fail"


def test_sigma_rule_uses_the_replica_se():
    assert match.grade("t", 4.69, 5.0, se=0.2)["sigma_rule"] == "within"
    assert match.grade("t", 4.69, 5.0, se=0.1)["sigma_rule"] == "outside"
    assert match.grade("t", 4.69, 5.0)["sigma_rule"] == "na"
    assert match.grade("t", 4.69, 5.0, se=0.2)["std_diff"] == pytest.approx(1.55)


def test_unit_rescale_is_tried_only_when_flagged():
    flagged = match.grade_with_unit_check(
        "mean", 45.0, 0.45, unit_note="analyst reports a proportion, paper reports a percentage"
    )
    assert flagged["band"] == "A" and "x100" in flagged["unit_check"]
    assert flagged["replicated_used"] == pytest.approx(45.0)

    unflagged = match.grade_with_unit_check("mean", 45.0, 0.45, unit_note="none")
    assert unflagged["band"] == "fail" and unflagged["unit_check"] == "none"


def test_sign_flip_rescale_recovers_a_reversed_contrast():
    g = match.grade_with_unit_check("d", 1.21, -1.21, unit_note="contrast coded control - attention")
    assert g["band"] == "A" and "sign flipped" in g["unit_check"]


def test_missing_replicated_value_fails():
    assert match.grade("d", 1.21, None)["band"] == "fail"


# --- blinding -------------------------------------------------------------


def test_assemble_gives_the_replica_only_the_blind_material(sandbox):
    work = blind.assemble("_fixture", "glm_1")
    assert sorted(p.name for p in work.iterdir()) == [
        "CONTRACT.json", "METHODS.md", "TASK.md", "data", "out",
    ]
    assert sorted(p.name for p in (work / "data").iterdir()) == ["codebook.csv", "study1.csv"]
    contract = json.loads((work / "CONTRACT.json").read_text())
    assert {"contracts", "claims"} == set(contract)
    assert all("value" not in c for c in contract["claims"])
    assert "reproduce the analyses" in (work / "TASK.md").read_text()


def test_assemble_blocks_when_a_reported_value_leaks(sandbox):
    methods = sandbox / "runs" / "_fixture" / "stage0" / "redacted_methods.md"
    methods.write_text(methods.read_text() + "\nThe t statistic was 4.69.\n")
    with pytest.raises(blind.LeakDetected, match="4.69"):
        blind.assemble("_fixture", "glm_1")


def test_assemble_blocks_when_author_notes_in_the_data_folder_state_a_result(sandbox):
    corpus = sandbox / "corpus" / "_fixture"
    (corpus / "data" / "author_notes_analysis.txt").write_text(
        "The t test gave t = 4.69 for the condition difference.\n"
    )
    man_path = corpus / "manifest.json"
    man = json.loads(man_path.read_text())
    man["data_files"].append("data/author_notes_analysis.txt")
    man_path.write_text(json.dumps(man))
    with pytest.raises(blind.LeakDetected, match="data folder"):
        blind.assemble("_fixture", "glm_1")
    assert not (sandbox / "runs" / "_fixture" / "stage1" / "replicas" / "glm_1" / "work").exists()


def test_data_tables_are_not_scanned_for_reported_values(sandbox):
    # A reported value that also occurs as a data cell is not leakage.
    corpus = sandbox / "corpus" / "_fixture"
    csv = corpus / "data" / "study1.csv"
    csv.write_text(csv.read_text().replace("3.51", "4.69", 1))
    assert blind.assemble("_fixture", "glm_1").exists()


def test_local_scan_ignores_digits_inside_longer_numbers(sandbox):
    claims = blind.claims("_fixture")
    p = sandbox / "scratch_scan.md"
    p.write_text("The identifier 14.0912 and the code 34690 are not results.")
    assert blind._local_scan([p], claims) == []


# --- replica bookkeeping --------------------------------------------------


def test_normalise_trace_coerces_what_agents_actually_write():
    out = replicas.normalise_trace(
        {
            "filters": {"study": "all 60 participants"},
            "fixes": ["installed effsize", {"description": "coerced condition to factor"}],
            "seed": "set.seed(20260901)",
            "software": ["R 4.6.1", "base"],
            "estimator_settings": "t.test(var.equal = TRUE)",
            "model_formula": {"a1": "closeness ~ condition"},
        }
    )
    assert out["filters"] == ["study: all 60 participants"]
    assert [f.description for f in out["fixes"]] == [
        "installed effsize", "coerced condition to factor"
    ]
    assert out["seed"] == 20260901
    assert out["software"] == "R 4.6.1\nbase"
    assert out["estimator_settings"] == {"described": "t.test(var.equal = TRUE)"}
    assert "closeness ~ condition" in out["model_formula"]


def test_normalise_trace_survives_a_non_object():
    assert replicas.normalise_trace(["not", "a", "trace"]) == {"agent_trace_unreadable": True}


def test_selection_honours_families_and_the_runs_cap(monkeypatch):
    monkeypatch.delenv("REPROSCOPE_FAMILIES", raising=False)
    monkeypatch.setenv("REPROSCOPE_RUNS", "1")
    assert [rid for _, rid, _ in replicas.replica_ids(["glm", "opus"])] == ["glm_1", "opus_1"]
    monkeypatch.setenv("REPROSCOPE_FAMILIES", "glm")
    assert [rid for _, rid, _ in replicas.replica_ids()] == ["glm_1"]
    monkeypatch.delenv("REPROSCOPE_RUNS")
    assert [rid for _, rid, _ in replicas.replica_ids()] == ["glm_1", "glm_2"]
    with pytest.raises(KeyError):
        replicas.replica_ids(["no_such_family"])


def test_count_loops_counts_repeats_beyond_the_first():
    log = "\n".join(["Rscript out/analysis.R"] * 4 + ["Error in library(effsize) : no package"] * 3)
    assert replicas.count_loops([log]) == 3
    assert replicas.count_loops(["Rscript out/analysis.R"]) == 0


def test_full_lineup_is_the_whole_models_toml_regardless_of_env(monkeypatch):
    from reproscope import stage1

    monkeypatch.setenv("REPROSCOPE_FAMILIES", "glm")
    monkeypatch.setenv("REPROSCOPE_RUNS", "1")
    lineup = stage1.full_lineup()
    assert "opus_2" in lineup and "deepseek_2" in lineup
    assert [rid for _, rid, _ in replicas.replica_ids()] == ["glm_1"]


def test_same_values_tolerates_float_noise_but_not_a_changed_result():
    a = {"c1": 4.0863333333, "c2": None}
    assert replicas._same_values(a, {"c1": 4.08633333331, "c2": None})
    assert not replicas._same_values(a, {"c1": 4.09, "c2": None})
    assert not replicas._same_values(a, {"c1": 4.0863333333})


# --- triggers and abstentions ---------------------------------------------


def _summary(claim_id, importance, fraction, cv=None):
    return artifacts.MatchSummary(
        claim_id=claim_id, n_ran=2, fraction_matched=fraction, importance=importance,
        dispersion=artifacts.Dispersion(numeric_cv=cv),
    )


def test_targeted_triggers_on_a_headline_miss_or_high_dispersion():
    ok = artifacts.ComparableResult(summaries=[_summary("c3", "headline", 1.0, 0.01)])
    assert match.targeted_trigger(ok) == (False, [])

    missed = artifacts.ComparableResult(summaries=[_summary("c3", "headline", 0.0, 0.01)])
    assert match.targeted_trigger(missed)[0] is True

    dispersed = artifacts.ComparableResult(summaries=[_summary("c3", "headline", 1.0, 0.4)])
    assert match.targeted_trigger(dispersed)[0] is True

    supporting = artifacts.ComparableResult(summaries=[_summary("c1", "supporting", 0.0, 0.9)])
    assert match.targeted_trigger(supporting) == (False, [])


def test_rerun_abstains_without_runnable_code(sandbox):
    assert "no original code" in rerun.run("_fixture")["abstain_reason"]

    man_path = sandbox / "corpus" / "_fixture" / "manifest.json"
    man = json.loads(man_path.read_text())
    man["original_code"] = ["code/Study1Syntax.sps"]
    man_path.write_text(json.dumps(man))
    (sandbox / "runs" / "_fixture" / "stage1" / "rerun.json").unlink(missing_ok=True)
    out = rerun.run("_fixture", force=True)
    assert out["state"] == "abstained" and ".sps" in out["abstain_reason"]

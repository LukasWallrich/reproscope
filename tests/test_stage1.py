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
from reproscope.stage1 import blind, diagnose, match, replicas, rerun, targeted

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
    packet = json.loads((work / "CONTRACT.json").read_text())
    assert [a["analysis_id"] for a in packet["analyses"]] == ["a1"]
    quantities = packet["analyses"][0]["quantities"]
    assert [q["claim_id"] for q in quantities] == ["c1", "c2", "c3", "c4", "c5"]
    assert all("value" not in q for q in quantities)
    assert "unassigned" not in packet
    assert "reproduce the analyses" in (work / "TASK.md").read_text()


def test_grouped_contract_carries_no_reported_value_past_the_scan(sandbox):
    """Positive control first: the scan does fire on a value, and not on the packet."""
    claims = blind.claims("_fixture")
    leaky = sandbox / "scratch_leaky_contract.json"
    leaky.write_text(json.dumps({"analyses": [{"quantities": [{"note": "t was 4.69"}]}]}))
    assert blind.scan([leaky], claims, paper_id="_fixture")

    work = blind.assemble("_fixture", "glm_1")
    assert blind.scan([work / "CONTRACT.json"], claims, paper_id="_fixture") == []


def test_claims_no_contract_claims_go_to_unassigned(sandbox):
    src = sandbox / "runs" / "_fixture" / "stage0" / "blind_contract.json"
    doc = json.loads(src.read_text())
    doc["claims"].append({"claim_id": "c9", "description": "orphan quantity"})
    src.write_text(json.dumps(doc))
    packet = blind.blind_packet("_fixture", src)
    assert [c["claim_id"] for c in packet["unassigned"]] == ["c9"]
    assert blind.bound_claim_ids(packet) == {"c1", "c2", "c3", "c4", "c5", "c9"}


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
    assert "opus_1" in lineup and "deepseek_2" in lineup
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


def test_targeted_triggers_on_the_focal_claim_only():
    focal_ids = ["c3"]
    ok = artifacts.ComparableResult(summaries=[_summary("c3", "headline", 1.0, 0.01)])
    assert match.targeted_trigger(ok, focal_ids) == (False, [])

    missed = artifacts.ComparableResult(summaries=[_summary("c3", "headline", 0.0, 0.01)])
    assert match.targeted_trigger(missed, focal_ids)[0] is True

    dispersed = artifacts.ComparableResult(summaries=[_summary("c3", "headline", 1.0, 0.4)])
    assert match.targeted_trigger(dispersed, focal_ids)[0] is True

    # A headline claim outside the focal binding does not open the arm.
    other_headline = artifacts.ComparableResult(summaries=[_summary("c5", "headline", 0.0, 0.9)])
    assert match.targeted_trigger(other_headline, focal_ids) == (False, [])


def test_rerun_abstains_without_runnable_code(sandbox):
    assert "no original code" in rerun.run("_fixture")["abstain_reason"]

    man_path = sandbox / "corpus" / "_fixture" / "manifest.json"
    man = json.loads(man_path.read_text())
    man["original_code"] = ["code/Study1Syntax.sps"]
    man_path.write_text(json.dumps(man))
    (sandbox / "runs" / "_fixture" / "stage1" / "rerun.json").unlink(missing_ok=True)
    out = rerun.run("_fixture", force=True)
    assert out["state"] == "abstained" and ".sps" in out["abstain_reason"]


# --- abstention on a failed link, and the match fingerprint ----------------


def _install_replica(root: Path, replica_id: str, results: dict) -> None:
    rdir = root / "runs" / "_fixture" / "stage1" / "replicas" / replica_id
    (rdir / "work" / "out").mkdir(parents=True, exist_ok=True)
    (rdir / "work" / "out" / "results.json").write_text(json.dumps(results))
    artifacts.save(
        artifacts.ReplicaDecisionTrace(
            replica_id=replica_id, family=replica_id.split("_")[0], ran=True,
            model_formula="closeness ~ condition", open_choices=["pooled variance"],
            meta=artifacts.ArtifactMeta(artifact="ReplicaDecisionTrace", stage="1"),
        ),
        rdir / "trace.json",
    )


def _fake_llm(monkeypatch, **result):
    """Replace llm.call with a stub; returns the list the calls are recorded in."""
    from types import SimpleNamespace

    from reproscope import llm

    defaults = {"text": "", "parsed": None, "ok": False, "error": "boom", "ledger_id": None}
    calls: list[tuple[str, dict]] = []

    def fake(step, prompt, **kwargs):
        calls.append((step, kwargs))
        return SimpleNamespace(**{**defaults, **result})

    monkeypatch.setattr(llm, "call", fake)
    return calls


def test_a_failed_link_abstains_and_leaves_the_denominator(sandbox, monkeypatch):
    _install_replica(sandbox, "glm_1", {"results": [{"claim_id": "c3", "value": 4.70}]})
    # Without a claim_id the deterministic join cannot fire, so the link call is made.
    _install_replica(sandbox, "glm_2", {"results": [{"label": "t statistic", "value": 4.70}]})
    _fake_llm(monkeypatch)

    result = match.run("_fixture")
    rows = {r.replica_id: r for r in result.rows if r.claim_id == "c3"}
    assert rows["glm_1"].band == "A" and rows["glm_1"].state == "complete"
    assert rows["glm_2"].band is None
    assert rows["glm_2"].state == "abstained"
    assert "link call failed" in rows["glm_2"].abstain_reason

    summary = next(s for s in result.summaries if s.claim_id == "c3")
    assert (summary.n_ran, summary.n_abstained) == (1, 1)
    assert summary.fraction_matched == 1.0 and summary.fraction_a == 1.0


def test_an_omitted_keyed_claim_abstains_rather_than_grading_fail(sandbox, monkeypatch):
    """A replica that keys its results by claim_id but has no entry for this claim did
    not compute it; that abstains, the same as a failed link call, rather than grading
    the missing value as band "fail"."""
    _install_replica(sandbox, "glm_1", {"results": [{"claim_id": "c1", "value": 1.0}]})
    _fake_llm(monkeypatch)  # any model call here would be a bug: no entry needs one

    result = match.run("_fixture")
    row = next(r for r in result.rows if r.claim_id == "c3" and r.replica_id == "glm_1")
    assert row.state == "abstained"
    assert row.band is None
    assert row.abstain_reason == "replica produced no value for this claim"

    summary = next(s for s in result.summaries if s.claim_id == "c3")
    assert summary.n_abstained >= 1
    assert summary.n_ran == 0  # the only replica for c3 abstained; nothing usable


def test_fingerprint_follows_results_and_ignores_trace_meta(sandbox):
    _install_replica(sandbox, "glm_1", {"results": [{"claim_id": "c3", "value": 4.70}]})
    before = match.replica_fingerprint("_fixture", replicas.load_traces("_fixture"))

    trace_path = sandbox / "runs" / "_fixture" / "stage1" / "replicas" / "glm_1" / "trace.json"
    doc = json.loads(trace_path.read_text())
    doc["meta"]["created"] = "2030-01-01T00:00:00+00:00"
    doc["meta"]["model_calls"] = ["a-fresh-call-id"]
    trace_path.write_text(json.dumps(doc))
    assert match.replica_fingerprint("_fixture", replicas.load_traces("_fixture")) == before

    out = sandbox / "runs" / "_fixture" / "stage1" / "replicas" / "glm_1" / "work" / "out"
    (out / "results.json").write_text(json.dumps({"results": [{"claim_id": "c3", "value": 4.71}]}))
    assert match.replica_fingerprint("_fixture", replicas.load_traces("_fixture")) != before


# --- targeted reconstruction ----------------------------------------------


def test_methods_section_takes_every_method_to_results_span():
    paper = "\n".join(
        [
            "Introduction", "We asked whether attention matters.",
            "Method", "Sixty students took part.",
            "Participants.", "They were undergraduates.",
            "Results", "The effect was large.",
            "Experiment 2", "Method", "Fifty-four students took part.",
            "General Discussion", "Attention matters.",
        ]
    )
    section = targeted.methods_section(paper)
    assert "Sixty students" in section and "Fifty-four students" in section
    assert "They were undergraduates" in section  # a subheading does not close the span
    assert "The effect was large" not in section
    assert "We asked whether" not in section
    assert "Attention matters" not in section
    assert targeted.methods_section("No headings here, only prose.") == ""


def _missed_focal_result() -> artifacts.ComparableResult:
    return artifacts.ComparableResult(
        rows=[
            artifacts.ComparableRow(
                claim_id="c3", replica_id="glm_1", reported=4.69, replicated=3.10,
                raw_diff=-1.59, band="fail",
            )
        ],
        summaries=[
            artifacts.MatchSummary(
                claim_id="c3", n_ran=1, fraction_matched=0.0, fraction_a=0.0,
                importance="headline", analysis_id="a1",
            )
        ],
    )


def test_targeted_abstains_when_the_agent_writes_no_outcome(sandbox, monkeypatch):
    _install_replica(sandbox, "glm_1", {"results": [{"claim_id": "c3", "value": 3.10}]})
    out = sandbox / "runs" / "_fixture" / "stage1" / "replicas" / "glm_1" / "work" / "out"
    (out / "analysis.R").write_text("t.test(closeness ~ condition, data = d)\n")
    calls = _fake_llm(monkeypatch, text="I ran out of time.", ok=True, error=None,
                      ledger_id="call1")

    rec = targeted.run("_fixture", _missed_focal_result())
    assert rec.triggered is True
    assert rec.outcome == "abstained" and rec.state == "abstained"
    assert rec.started_from == "glm_1"
    assert calls[0][1]["max_turns"] == targeted.MAX_TURNS

    work = targeted.targeted_dir("_fixture") / "work"
    assert sorted(p.name for p in work.iterdir()) == [
        "CONTRACT.json", "FOCAL.json", "METHODS.md", "REPORTED.json", "TASK.md",
        "closest_replica.R", "data", "out",
    ]
    assert json.loads((work / "CONTRACT.json").read_text())["analysis_id"] == "a1"
    reported = json.loads((work / "REPORTED.json").read_text())["claims"]
    assert [c["claim_id"] for c in reported] == ["c1", "c2", "c3", "c4", "c5"]


def test_the_agents_diagnosis_section_is_taken_verbatim():
    answer = (
        "Attempt 3 reached the reported t.\n\n"
        "## Diagnosis (unblinded conjecture)\n\n"
        "The analysts kept the two excluded participants.\n"
    )
    assert targeted._split_diagnosis(answer) == "The analysts kept the two excluded participants."
    assert targeted._split_diagnosis("No section here.") is None


def test_diagnosis_reuses_the_targeted_section_without_a_call(sandbox, monkeypatch):
    artifacts.save(
        artifacts.TargetedReconstruction(
            triggered=True, outcome="reachable",
            diagnosis="The analysts kept the two excluded participants.",
            meta=artifacts.ArtifactMeta(artifact="TargetedReconstruction", stage="1"),
        ),
        sandbox / "runs" / "_fixture" / "stage1" / "targeted.json",
    )
    calls = _fake_llm(monkeypatch)

    text = diagnose.run("_fixture").read_text()
    assert "kept the two excluded participants" in text
    assert "unblinded conjecture" in text.lower()
    assert calls == []

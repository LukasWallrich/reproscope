"""Offline tests for stage 2: the deterministic MDE, the anchor check, and assembly.

`install_fixture` copies tests/fixtures/stage2 into a paths.ROOT so the same tree
can be used by the sandboxed tests and by a live CLI run on `_fixture2`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from reproscope import paths
from reproscope.artifacts import ArtifactMeta
from reproscope.stage2 import mde, review

FIXTURE = Path(__file__).parent / "fixtures" / "stage2"
HAVE_R = mde.rscript() is not None


def install_fixture(root: Path, paper_id: str = "_fixture2") -> None:
    """Copy the fixture corpus and run tree into `root`, replacing what is there."""
    for kind in ("corpus", "runs"):
        src = FIXTURE / kind / paper_id
        dst = root / kind / paper_id
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)


@pytest.fixture
def fixture_root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    # artifacts.prompt_path resolves under ROOT, so the prompts come along
    real = Path(__file__).resolve().parent.parent
    shutil.copytree(real / "reproscope" / "prompts", tmp_path / "reproscope" / "prompts")
    install_fixture(tmp_path)
    return tmp_path


# --- design classification ------------------------------------------------


def test_classify_design():
    assert mde.classify_design("independent-samples t test") == mde.TWO_GROUP
    assert mde.classify_design("paired t test") == mde.PAIRED
    assert mde.classify_design("Pearson correlation", n_predictors=1) == mde.CORRELATION
    assert mde.classify_design("OLS regression", n_predictors=1) == mde.CORRELATION
    # a covariate takes it out of power.t.test's design
    assert mde.classify_design("independent-samples t test", n_covariates=1) is None
    # multi-predictor regression and anything unrecognised go to the fallback
    assert mde.classify_design("OLS regression", n_predictors=3) is None
    assert mde.classify_design("linear mixed-effects model") is None
    assert mde.classify_design(None) is None


# --- deterministic MDE ----------------------------------------------------


@pytest.mark.skipif(not HAVE_R, reason="Rscript not on PATH")
def test_mde_two_group_matches_r(tmp_path):
    # 128 analysed, 64 per group: power.t.test(n=64, delta=0.5) = 0.8014586
    out = mde.compute(mde.TWO_GROUP, 128, script_path=tmp_path / "mde.R")
    powers = {row["effect"]: row["power"] for row in out["curve"]}
    assert powers[0.5] == pytest.approx(0.8014586, abs=1e-4)
    assert powers[0.1] < powers[0.2] < powers[0.3] < powers[0.5] < powers[0.8]
    assert out["n_per_group"] == 64
    assert out["mde_standardised"] == pytest.approx(0.4990, abs=1e-3)
    assert out["method"] == "deterministic"
    assert any("64 per group" in a for a in out["assumptions"])


@pytest.mark.skipif(not HAVE_R, reason="Rscript not on PATH")
def test_mde_two_group_fixture_n(tmp_path):
    # the fixture analyses 58, i.e. 29 per group: MDE at 80% power = 0.7486596
    out = mde.compute(mde.TWO_GROUP, 58, script_path=tmp_path / "mde.R")
    assert out["n_per_group"] == 29
    assert out["mde_standardised"] == pytest.approx(0.7486596, abs=1e-4)


@pytest.mark.skipif(not HAVE_R, reason="Rscript not on PATH")
def test_mde_paired_matches_r(tmp_path):
    out = mde.compute(mde.PAIRED, 58, script_path=tmp_path / "mde.R")
    assert out["mde_standardised"] == pytest.approx(0.3742138, abs=1e-4)


@pytest.mark.skipif(not HAVE_R or not mde.has_pwr(), reason="Rscript or pwr not available")
def test_mde_correlation_matches_r(tmp_path):
    out = mde.compute(mde.CORRELATION, 84, script_path=tmp_path / "mde.R")
    powers = {row["effect"]: row["power"] for row in out["curve"]}
    assert powers[0.3] == pytest.approx(0.799647, abs=1e-4)
    assert out["mde_standardised"] == pytest.approx(0.3001298, abs=1e-4)
    assert out["mde_metric"] == "Pearson r"


@pytest.mark.skipif(not HAVE_R, reason="Rscript not on PATH")
def test_mde_rejects_unknown_design(tmp_path):
    with pytest.raises(mde.MdeError):
        mde.compute("multilevel", 58, script_path=tmp_path / "mde.R")


# --- anchor verification --------------------------------------------------


def test_normalise_collapses_whitespace_and_quotes():
    assert review.normalise("The  effect\nwas  large.") == "the effect was large."
    assert review.normalise("“quoted” — dash") == review.normalise('"quoted" - dash')


def test_verify_anchors():
    sources = {
        "paper.txt": "The difference in contributions was significant,\n  t(56) = 2.41, p = .019.",
        "schema.json": '{"name": "attn_check_pass"}',
        "opus_1/analysis.R": 'fit <- t.test(contribution ~ condition, var.equal = TRUE)',
    }
    findings = [
        {"anchor": "t(56) = 2.41, p = .019", "comment": "in the paper, across a line break"},
        {"anchor": "ATTN_CHECK_PASS", "comment": "case-insensitive schema hit"},
        {"anchor": "var.equal = TRUE", "comment": "script hit"},
        {"anchor": "the authors used a Bonferroni correction", "comment": "not in any source"},
        {"anchor": "", "comment": "empty anchor"},
    ]
    out = review.verify_anchors(findings, sources)
    assert [f["anchor_verified"] for f in out] == [True, True, True, False, False]
    assert out[0]["anchor_found_in"] == ["paper.txt"]
    assert out[2]["anchor_found_in"] == ["opus_1/analysis.R"]


# --- inputs and focal selection ------------------------------------------


def test_gather_and_focal_selection(fixture_root):
    inp = review.gather("_fixture2")
    assert inp.focal_claim is not None and inp.focal_claim.claim_id == "c1"
    assert "manifest focal_claim" in inp.focal_rule
    assert inp.focal_contract is not None and inp.focal_contract.analysis_id == "a1"
    assert [r.replica_id for r in inp.replicas] == ["glm_1", "opus_1"]
    assert all(r.script_text for r in inp.replicas)
    assert "paper.txt" in inp.hashes and "stage0/claims.json" in inp.hashes
    assert not inp.paper_truncated


def test_focal_n_prefers_replica_results(fixture_root):
    inp = review.gather("_fixture2")
    n, source = review._focal_n(inp)
    assert n == 58
    assert "replica results.json" in source


@pytest.mark.skipif(not HAVE_R, reason="Rscript not on PATH")
def test_check_mde_deterministic_on_fixture(fixture_root):
    inp = review.gather("_fixture2")
    rec = review.check_mde(inp)
    assert rec.state == "complete"
    assert rec.response["method"] == "deterministic"
    assert rec.response["design"] == mde.TWO_GROUP
    assert rec.response["n_analysed"] == 58
    assert rec.response["mde_standardised"] == pytest.approx(0.7486596, abs=1e-4)
    assert rec.meta.model_calls == []  # deterministic: no ledger row by design
    # a second call reuses the record rather than recomputing
    again = review.check_mde(inp)
    assert again.meta.created == rec.meta.created


# --- assembly and markdown ------------------------------------------------


def _record(check: str, response, abstain: str | None = None, calls=()) -> review.CheckRecord:
    return review.CheckRecord(
        check=check,
        response=response,
        state="abstained" if abstain else "complete",
        abstain_reason=abstain,
        meta=ArtifactMeta(artifact=f"Stage2Check:{check}", stage="2", model_calls=list(calls)),
    )


def test_assemble_and_render_with_one_abstained_check(fixture_root):
    inp = review.gather("_fixture2")
    records = {
        "causal_language": _record("causal_language", {
            "language_strength": "strong",
            "design_inference_strength": "moderate",
            "verdict": "overstated",
            "focal_claim_quote": "Attention increases cooperation.",
            "abstract_quotes": ["Attention is therefore a cheap and effective lever"],
            "design_basis": ["randomised assignment", "single small student sample"],
            "reasoning": "The abstract recommends action on a single small experiment.",
            "quotes_verified": {"Attention increases cooperation.": True,
                                "Attention is therefore a cheap and effective lever": True},
        }, calls=["call1"]),
        "mde": _record("mde", None, abstain="Rscript failed", calls=["call2"]),
        "alignment": _record("alignment", {
            "verdict": "partly_aligned",
            "reasoning": "The claim is causal; the contract supports a between-condition difference.",
            "claim_quote": "Giving participants attention raised contributions",
            "contract_basis": ["outcome: tokens contributed", "predictor: condition"],
            "open_choices": [{
                "choice": "variance assumption for the t test",
                "options": ["Student", "Welch"],
                "replica_choices": {"opus_1": "Student", "glm_1": "Welch"},
                "matters_for_claim": False,
                "note": "changes the statistic in the third decimal",
            }],
            "traced_open_choices": {"opus_1": ["pooled variance"], "glm_1": ["Welch"]},
        }, calls=["call3"]),
        "broad": _record("broad", {
            "summary": "One measurement concern and one reporting concern.",
            "findings": [
                {"severity": "note", "category": "reporting", "anchor": "p = .019",
                 "location": "Results", "comment": "exact p reported", "checkable_by": "read Results",
                 "anchor_verified": True, "anchor_found_in": ["paper.txt"]},
                {"severity": "major", "category": "measurement",
                 "anchor": "No reliability coefficient is reported for the closeness scale.",
                 "location": "Method", "comment": "no alpha for a three-item scale",
                 "checkable_by": "read Measures", "anchor_verified": True,
                 "anchor_found_in": ["paper.txt"]},
                {"severity": "minor", "category": "coding_error",
                 "anchor": "a Bonferroni correction was applied",
                 "location": "Analysis", "comment": "not found in the paper",
                 "anchor_verified": False, "anchor_found_in": []},
            ],
            "anchor_sources": ["paper.txt", "schema.json"],
        }, calls=["call4"]),
    }
    out = review.assemble(inp, records)

    assert out.state == "complete"
    assert out.claim_id == "c1"
    assert out.narrow.mde is None
    assert out.narrow.causal_language.rating == (
        "language=strong; design_supports=moderate; verdict=overstated"
    )
    assert out.narrow.alignment.open_choices_per_replica["opus_1"] == [
        "variance assumption for the t test: Student"
    ]
    # findings come back sorted major -> minor -> note
    assert [f.severity for f in out.broad.findings] == ["major", "minor", "note"]
    assert out.meta.model_calls == ["call1", "call2", "call3", "call4"]
    assert any("mde abstained" in a for a in out.open_ambiguities)

    md = review.render_md(inp, out, records)
    assert "## 2. Minimum detectable effect" in md
    assert "_Abstained: Rscript failed_" in md
    assert "### Not verifiable" in md
    assert "a Bonferroni correction was applied" in md
    assert "`opus_1`: Student" in md
    assert "`call1`" in md


def test_assemble_all_abstained(fixture_root):
    inp = review.gather("_fixture2")
    records = {c: _record(c, None, abstain="model call failed") for c in review.CHECKS}
    out = review.assemble(inp, records)
    assert out.state == "abstained"
    assert out.abstain_reason and "causal_language" in out.abstain_reason
    md = review.render_md(inp, out, records)
    assert md.count("_Abstained: model call failed_") == 4


def test_check_record_roundtrip(fixture_root):
    rec = review.write_check(
        "_fixture2", "broad",
        inputs={"paper.txt": "abc"}, prompt_versions={"stage2_broad": "0" * 12},
        model_calls=["x1"], response={"findings": []},
    )
    loaded = review.load_check("_fixture2", "broad")
    assert loaded is not None and loaded.response == {"findings": []}
    assert review.reusable(loaded, {"paper.txt": "abc"})
    assert not review.reusable(loaded, {"paper.txt": "different"})
    assert json.loads(review.check_path("_fixture2", "broad").read_text())["check"] == "broad"
    assert rec.state == "complete"

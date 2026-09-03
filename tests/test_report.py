"""Offline checks for the report builder: it renders from whatever is on disk and
never crashes on a stage that did not run."""

from __future__ import annotations

import json

import pytest

import importlib

from reproscope import paths
from reproscope.report import build
from reproscope.report.build import spec_curve_svg

# `reproscope.report/__init__.py` does `from .build import build`, which shadows the
# submodule attribute with the function; import the module directly to reach `_stage1`.
build_mod = importlib.import_module("reproscope.report.build")

FIXTURES = ["_fixture", "_fixture2", "_fixture3"]
STAGE_MARKER = {
    "stage0": "Stage 0 not run",
    "stage1": "Stage 1 not run",
    "stage2": "Stage 2 not run",
    "stage3": "Stage 3 not run",
}


# The files each stage section actually reads; a stage directory holding only
# intermediates still counts as "not run" for the report.
STAGE_FILES = {
    "stage0": ["claims.json", "contracts.json", "readiness.json", "redaction_report.json",
               "leak_audit.json", "redacted_methods.md"],
    "stage1": ["match.json", "targeted.json", "rerun.json", "diagnosis.md"],
    "stage2": ["review.json", "review.md"],
    "stage3": ["space.json", "interpretation.md"],
}


def _has_stage(paper_id: str, stage: str) -> bool:
    d = paths.ROOT / "runs" / paper_id / stage
    if stage == "stage1" and any((d / "replicas").glob("*/trace.json")):
        return True
    return any((d / f).exists() for f in STAGE_FILES[stage])


@pytest.mark.parametrize("paper_id", FIXTURES)
def test_report_builds_from_fixture(paper_id: str) -> None:
    run_dir = paths.ROOT / "runs" / paper_id
    if not run_dir.is_dir():
        pytest.skip(f"no run directory for {paper_id}")

    html, sidecar = build(paper_id)

    # Header, fixed guidance box and favicon.
    assert "<title>reproscope" in html
    assert paper_id in html
    assert "How to read this report" in html
    assert "A close match shows that one route to the reported number exists" in html
    assert "Stage 1 findings are worth acting on" in html
    assert "complete" in html and "abstained" in html
    assert "text y='.9em' font-size='90'>🔬" in html

    # A stage with artifacts renders its content; a stage without renders the box.
    for stage, marker in STAGE_MARKER.items():
        if _has_stage(paper_id, stage):
            assert marker not in html, f"{paper_id}: {stage} has artifacts but rendered 'not run'"
        else:
            assert marker in html, f"{paper_id}: {stage} is absent but no 'not run' box"

    # Self-contained: no external stylesheet, script or image.
    assert "<script" not in html
    assert 'rel="stylesheet"' not in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert len(html.encode()) < 2_000_000

    # Sidecar round-trips and carries the ledger summary.
    text = json.dumps(sidecar, indent=2, default=str)
    again = json.loads(text)
    assert again["paper_id"] == paper_id
    assert "ledger_summary" in again


def test_missing_paper_renders_every_not_run_box() -> None:
    html, sidecar = build("_no_such_paper_at_all")
    for marker in STAGE_MARKER.values():
        assert marker in html
    assert sidecar["stage0"] is None
    assert sidecar["stage3"] is None


def test_match_table_shows_bands_and_claim_ids() -> None:
    if not _has_stage("_fixture", "stage1"):
        pytest.skip("no stage1 fixture")
    html, _ = build("_fixture")
    assert "Match table" in html
    assert 'class="cell band-A"' in html
    assert "c1" in html and "glm_1" in html and "opus_1" in html
    assert "Conjecture" in html  # diagnosis.md is labelled as conjecture


def test_abstained_match_row_renders_as_abstained_not_notfound(tmp_path) -> None:
    stage1 = tmp_path / "stage1"
    replica_dir = stage1 / "replicas" / "glm_1"
    replica_dir.mkdir(parents=True)
    (replica_dir / "trace.json").write_text(json.dumps({"replica_id": "glm_1", "ran": True}))
    (stage1 / "match.json").write_text(json.dumps({
        "rows": [
            {
                "claim_id": "c1", "replica_id": "glm_1", "state": "abstained",
                "abstain_reason": "replica produced no value for this claim",
                "band": None, "replicated": None,
            },
        ],
        "summaries": [{"claim_id": "c1", "n_ran": 0, "n_abstained": 1}],
    }))
    claims = [{"claim_id": "c1", "importance": "headline", "quantity_kind": "mean", "value": 4.09}]
    ctx = build_mod._stage1(tmp_path, claims, [])
    assert ctx is not None
    cell = ctx["table"][0]["cells"][0]
    assert cell["state"] == "abstained"
    assert cell["label"] == "abstained"
    assert "not found" not in cell["label"]


def test_spec_curve_svg_handles_edge_cases() -> None:
    assert spec_curve_svg([], 1.0, None) == ""
    one = spec_curve_svg([{"estimate": 0.5, "se": None, "p": 0.2, "spec": {}}], 0.5, None)
    assert one.startswith("<svg") and "circle" in one
    # A reported estimate outside the range of the runs must still be drawn.
    wide = spec_curve_svg(
        [{"estimate": 0.1, "se": 0.05, "p": 0.04, "spec": {"a": "x"}}], 9.0, {"a": "x"}
    )
    assert "reported 9" in wide

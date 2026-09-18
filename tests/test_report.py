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


def test_computed_but_qualified_cells_are_not_missing_or_plain_failures(tmp_path):
    stage=tmp_path/'stage1';stage.mkdir()
    (stage/'match.json').write_text(json.dumps({'rows':[
        {'claim_id':'c1','replica_id':'r1','replicated':-.17,'band':None,'outcome_status':'direction_unverified'},
        {'claim_id':'c2','replica_id':'r1','replicated':.743149,'band':'fail','bound_satisfied':False,'bound_rounding_compatible':True}]}))
    data=build_mod._stage1(tmp_path,[{'claim_id':'c1'},{'claim_id':'c2'}],[])
    assert [r['cells'][0]['state'] for r in data['table']]==['direction-unverified','rounding-compatible']
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

    # Reader purpose and appropriately limited claims.
    assert "<title>Reproduction report" in html
    assert paper_id in html
    assert "What this run establishes" in html
    assert "A discrepancy alone does not establish an error" in html
    assert "Stage 1 findings are worth acting on" not in html

    # A stage with artifacts renders its content; a stage without renders the box.
    for stage, marker in STAGE_MARKER.items():
        if _has_stage(paper_id, stage):
            assert marker not in html, f"{paper_id}: {stage} has artifacts but rendered 'not run'"
        else:
            assert marker in html, f"{paper_id}: {stage} is absent but no 'not run' box"

    # Self-contained: no external stylesheet, script or image.
    assert '<script src=' not in html
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
    assert "Every reported number" in html
    assert 'agreement' in html.lower()
    assert "c1" in html and "glm 1" in html and "opus 1" in html
    assert "Discrepancies and their causes" in html


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


def test_report_separates_unsupported_method_from_numeric_mismatch():
    r=build_mod._trace_summary({'replica_id':'r','ran':True,'execution_evidence':{'analyses':{
        'a':{'status':'unverified','support_status':'unsupported','computation_status':'not_run'},
        'b':{'status':'invalid','computation_status':'recomputed_mismatch'},
        'c':{'status':'verified','computation_status':'recomputed_match'}}}})
    assert r['method_counts']=={'unverified':1,'invalid':1,'verified':1}
    assert r['computation_counts']=={'not_run':1,'recomputed_mismatch':1,'recomputed_match':1}


def test_invalid_source_is_not_rendered_as_replica_missing_result(tmp_path):
    root=tmp_path/'stage1';p=root/'replicas/r';p.mkdir(parents=True)
    (p/'trace.json').write_text(json.dumps({'replica_id':'r','ran':False}))
    (root/'match.json').write_text(json.dumps({'rows':[],'summaries':[{'claim_id':'c','state':'abstained',
        'outcome_status':'input_invalid','abstain_reason':'source identity unresolved'}]}))
    result=build_mod._stage1(tmp_path,[{'claim_id':'c'}],[])
    cell=result['table'][0]['cells'][0]
    assert cell['label']=='input excluded' and cell['state']=='abstained'


def test_multi_column_binding_is_not_displayed_as_unbound(tmp_path):
    from reproscope.report.build import _stage0
    d=tmp_path/'stage0';d.mkdir()
    (d/'claims.json').write_text('[]')
    (d/'readiness.json').write_text(json.dumps({'variable_bindings':[
        {'analysis_id':'a1','contract_field':'outcome','chosen':None,'input_columns':['x','y']},
        {'analysis_id':'a2','contract_field':'outcome','chosen':None,'input_columns':[]}]}))
    bindings=_stage0(tmp_path)['bindings']
    assert bindings[0]['analysis_id']=='a1' and not bindings[0]['unbound']
    assert bindings[0]['input_columns']==['x','y']
    assert bindings[1]['unbound']


def test_report_index_prioritises_current_artifacts_over_snapshots(tmp_path):
    from reproscope.report.build import _attachments
    for name in ['old_source/reproscope/a.py','stage3/execute.json','stage1/replicas/r/work/out/results.json','stage1/replicas/r/env/bin/python','ledger.jsonl']:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
    names={p['path'] for p in _attachments(tmp_path)}
    assert names=={'stage3/execute.json','stage1/replicas/r/work/out/results.json','ledger.jsonl'}


def test_embedded_svg_definitions_are_namespaced_per_plot(tmp_path):
    from reproscope.report.build import inline_svg
    source=tmp_path/'plot.svg'
    source.write_text('<?xml version="1.0"?><svg><defs><path id="glyph0"/><clipPath id="clip1"/></defs><use xlink:href="#glyph0"/><g style="clip-path:url(#clip1)"/></svg>')
    first=str(inline_svg(source,'first'));second=str(inline_svg(source,'second'))
    assert 'id="first_glyph0"' in first and 'href="#first_glyph0"' in first
    assert 'url(#second_clip1)' in second and 'id="glyph0"' not in first+second
def test_failed_latest_executor_hides_previous_completed_curve(tmp_path):
    import json
    from reproscope.report.build import _stage3
    d=tmp_path/'stage3';d.mkdir()
    (d/'space.json').write_text(json.dumps({'state':'complete','runs':[{'estimate':999,'converged':True}]}))
    (d/'execute.json').write_text(json.dumps({'ok':False,'problems':['no current specs.csv']}))
    view=_stage3(tmp_path)
    assert view['abstained'] and not view['space']['runs']
    assert 'latest multiverse execution failed' in view['abstain_reason']


def test_changed_multiverse_results_cannot_inherit_old_curve(tmp_path):
    stage=tmp_path/'stage3';stage.mkdir()
    (stage/'space.json').write_text(json.dumps({'state':'complete','runs':[{'estimate':1,'converged':True}],
        'execution':{'output_fingerprint':{'specs.csv':'old'}}}))
    (stage/'execute.json').write_text(json.dumps({'ok':True,'problems':[], 'output_fingerprint':{'specs.csv':'new'},'reference':{'status':'verified'}}))
    got=build_mod._stage3(tmp_path)
    assert got['abstained'] and 'changed after report aggregation' in got['abstain_reason']

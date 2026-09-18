"""--force-step: validation, and that it threads into a stage's per-step force flags."""

from __future__ import annotations

from pathlib import Path

import pytest

from reproscope import artifacts, cli, paths
from reproscope import stage2
from reproscope.stage2 import review as _review


def test_force_steps_accepts_known_names():
    assert cli._force_steps(["match", "targeted"]) == {"match", "targeted"}
    assert cli._force_steps(None) == set()


def test_force_steps_rejects_unknown_name():
    with pytest.raises(SystemExit):
        cli._force_steps(["not_a_step"])


def test_force_step_reruns_only_the_named_step(tmp_path, monkeypatch):
    """stage2.run_extended(force_steps={"mde"}) must force only the mde check, not the other three."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    stage_dir = paths.run_dir("_p", 2)
    stage_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        _review, "gather",
        lambda paper_id: _review.Stage2Inputs(
            paper_id=paper_id, manifest=None, paper_text="", claims=[], contracts=[],
            readiness=None, schema_text="", redacted_methods="", match=None, replicas=[],
            hashes={"h": "1"}, focal=None, focal_error="no focal claim in this fixture",
            focal_claim=None, focal_contract=None, focal_rule="unbound",
        ),
    )
    seen: dict[str, bool] = {}

    def make_check(name):
        def fn(inp, *, force=False):
            seen[name] = force
            return artifacts.AnalysisReview.model_construct(
                meta=None, state="complete", abstain_reason=None, confidence=None,
                open_ambiguities=[], narrow=None, broad=None,
            )
        return fn

    for name in stage2.EXTENDED_STEPS:
        monkeypatch.setattr(_review, f"check_{name}", make_check(name))
    monkeypatch.setattr(_review, "assemble", lambda inp, records: artifacts.AnalysisReview())
    monkeypatch.setattr(_review, "render_md", lambda *a, **kw: "")

    stage2.run_extended("_p", force_steps={"mde"})

    assert seen == {"causal_language": False, "mde": True, "alignment": False, "broad": False}


def test_report_retry_does_not_render_previous_failure(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    monkeypatch.setattr(paths,'ROOT',tmp_path)
    root=paths.run_dir('p');root.mkdir(parents=True,exist_ok=True)
    status=root/'pipeline_status.json';status.write_text(json.dumps({'stages':{'report':{'status':'failed','error':'old failure'}}}))
    def render(*args,**kwargs):
        assert json.loads(status.read_text())['stages']['report']=={'status':'running'}
    monkeypatch.setattr(cli.importlib,'import_module',lambda name:SimpleNamespace(run=render))
    monkeypatch.setattr(cli.ledger,'format_summary',lambda p:'done')
    cli.cmd_run(SimpleNamespace(paper_id='p',stages=['report'],force_step=None,force=False))
    assert json.loads(status.read_text())['stages']['report']['status']=='finished'

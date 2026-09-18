import json
from reproscope.generation_access import review


def event(path, status="completed"):
    return json.dumps({"part": {"tool": "read", "callID": "read-1",
        "state": {"status": status, "input": {"filePath": str(path)}}}})


def test_generation_reads_detect_parent_and_symlink_escape(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("reported numbers")
    (work / "alias").symlink_to(source)
    log = tmp_path / "execute.log"
    log.write_text("\n".join([event(work / "CONTRACT.json"), event("../source.txt"),
                               event("alias"), event(source, "error")]))
    out = review(log, work)
    assert out["status"] == "violated"
    assert out["direct_reads_checked"] == 3
    assert len(out["violations"]) == 2


def test_unobserved_access_cannot_certify_isolation(tmp_path):
    log = tmp_path / "execute.log"
    assert review(log, tmp_path)["status"] == "unobserved"
    log.write_text("unstructured transcript\n[]\n" + event("CONTRACT.json"))
    out = review(log, tmp_path)
    assert out["status"] == "no_direct_read_violation_observed"
    assert "not certified" in out["scope"]


def test_multiverse_retains_generation_violation_in_failure_receipt(tmp_path):
    from reproscope.stage3.multiverse import verify_execution
    work = tmp_path / "work"
    work.mkdir()
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs/execute.log").write_text(event(tmp_path / "source.txt"))
    out = verify_execution(work, {}, "unused")
    assert not out["ok"]
    assert out["generation_access"]["status"] == "violated"
    assert "generation read files outside its supplied work directory" in out["problems"]


def test_semantic_report_preserves_multiverse_failure_with_verified_arithmetic(tmp_path):
    from reproscope.source_integrity import review_run
    (tmp_path / "stage3").mkdir()
    (tmp_path / "stage3/execute.json").write_text(json.dumps({
        "reference": {"status": "verified"}, "perturbation": {"status": "verified"},
        "audit": {"verdict": "clean"},
        "problems": ["generation read files outside its supplied work directory"]}))
    out = review_run(tmp_path)
    assert any("generation read files outside" in b for b in out["semantic_blockers"])
    assert not out["semantic_ready"]


def test_conflicting_screened_reference_is_a_retained_failure(tmp_path):
    from reproscope.stage3.multiverse import verify_execution
    work = tmp_path / "work"
    (work / "out").mkdir(parents=True)
    (work / "out/specs.csv").write_text("spec_id,estimate,converged\nspec_001,1,TRUE\n")
    grid = {"grid_size": 1, "factors": [
        {"name": "sample", "levels": [{"value": "all", "reference_settings": {"family": "paired_t"}}]},
        {"name": "inference", "levels": [{"value": "bootstrap", "reference_settings": {"family": "paired_bootstrap"}}]}]}
    out = verify_execution(work, grid, "unused")
    assert out["acceptance"] == "rejected"
    assert out["checks"]["n_rows"] == 1
    assert out["reference"]["status"] == "blocked"
    assert "conflicting screened reference settings" in out["problems"][0]

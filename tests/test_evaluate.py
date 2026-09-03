"""Offline tests for the pilot evaluation aggregation.

Two sources: the real fixture run under runs/_fixture (two replicas, glm_1 and opus_1),
and a synthetic in-memory paper with mixed bands, a failed replica and missing fields.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reproscope import evaluate, paths

FIXTURE_MATCH = paths.ROOT / "runs" / "_fixture" / "stage1" / "match.json"
needs_fixture = pytest.mark.skipif(
    not FIXTURE_MATCH.exists(), reason="runs/_fixture has no Stage 1 output"
)


def _group(result: dict, label: str) -> dict:
    for g in result["families"] + result["tiers"]:
        if g["label"] == label:
            return g
    raise AssertionError(f"no group {label!r} in {[g['label'] for g in result['families'] + result['tiers']]}")


# --- family and tier assignment -------------------------------------------


def test_family_from_replica_id():
    assert evaluate.family_of("glm_1") == "glm"
    assert evaluate.family_of("deepseek_12") == "deepseek"
    assert evaluate.family_of("weird") == "weird"
    assert evaluate.family_of("glm_1", "glm-flash") == "glm-flash"


def test_tier_from_models_toml():
    assert evaluate.tier_of("opus") == "frontier"
    assert evaluate.tier_of("luna") == "frontier"
    assert evaluate.tier_of("glm") == "cheap"
    assert evaluate.tier_of("deepseek") == "cheap"


def test_tier_falls_back_to_the_trace_route_then_unknown():
    assert evaluate.tier_of("not_in_models_toml", "codex") == "frontier"
    assert evaluate.tier_of("not_in_models_toml", "opencode") == "cheap"
    assert evaluate.tier_of("not_in_models_toml", None) == "unknown"


# --- synthetic paper ------------------------------------------------------


def _row(claim, replica, band, replicated=1.0, kind="d", reported=1.0):
    return {"claim_id": claim, "replica_id": replica, "band": band, "reported": reported,
            "replicated": replicated, "quantity_kind": kind}


@pytest.fixture
def synthetic() -> dict:
    """Four replicas: two frontier runs that ran, one cheap run that failed, one still out.

    opus_1 has no ledger cost fields and no blind_transcript_hits (an older trace);
    opus_2 has both. glm_1 wrote a trace with ran = false, so its rows are excluded.
    deepseek_1 has no trace at all — launched but unfinished.
    """
    return {
        "paper_id": "synth",
        "replicas": [
            {"replica_id": "opus_1", "family": "opus", "route": "claude_p", "model": "opus",
             "has_trace": True, "ran": True, "fixes": [{"description": "x", "severity": "minor"}],
             "hardcoding_verdict": "clean", "blind_hits": None},
            {"replica_id": "opus_2", "family": "opus", "route": "claude_p", "model": "opus",
             "has_trace": True, "ran": True,
             "fixes": [{"description": "y", "severity": "major"},
                       {"description": "z", "severity": "critical"},
                       {"description": "w", "severity": None}],
             "hardcoding_verdict": "suspicious", "blind_hits": 2,
             "tokens_in": 1000, "tokens_out": 100, "cost_usd": 0.0,
             "cost_usd_equiv": 0.5, "duration_s": 60.0},
            {"replica_id": "glm_1", "family": "glm", "route": "opencode", "model": "z-ai/x",
             "has_trace": True, "ran": False, "fixes": [], "hardcoding_verdict": None,
             "blind_hits": None},
            {"replica_id": "deepseek_1", "family": "deepseek", "route": None, "model": None,
             "has_trace": False, "ran": None, "fixes": [], "hardcoding_verdict": None,
             "blind_hits": None},
        ],
        "match_rows": [
            _row("c1", "opus_1", "A"), _row("c2", "opus_1", "B", 1.1),
            _row("c3", "opus_1", "C", 1.3), _row("c4", "opus_1", None, None),
            _row("c1", "opus_2", "A"), _row("c2", "opus_2", "fail", 9.0),
            _row("c3", "opus_2", "A"), _row("c4", "opus_2", "fail", None),
            # glm_1 did not run; these rows must not be counted
            _row("c1", "glm_1", "A"), _row("c2", "glm_1", "A"),
        ],
        "summaries": [
            {"claim_id": "c1", "dispersion": {"decision_agreement": 0.8, "numeric_cv": 0.1}},
            {"claim_id": "c2", "dispersion": {"decision_agreement": 0.6, "numeric_cv": 0.3}},
            {"claim_id": "c3", "dispersion": {"decision_agreement": None, "numeric_cv": None}},
        ],
        "importance": {"c1": "headline", "c2": "supporting", "c3": "headline",
                       "c4": "supporting"},
        "focal": {"claim_ids": ["c1"],
                  "focal_quantity": {"claim_id": "c1", "kind": "d", "reported_value": 1.0}},
        "focal_source": "test",
        "targeted": {"outcome": "not_reachable", "notes": "synthetic"},
        "multi100": {"n_analysts": 4, "analyst_d": {"min": 0.5, "median": 1.0, "max": 2.0}},
        "focal_claim": {"reported": {"df": 27}},
        "stage_costs": {"1": {"calls": 3, "cost_usd": 0.01, "cost_usd_equiv": 0.5}},
        "n_ledger_rows": 3,
    }


def test_run_counts_separate_failed_from_no_trace(synthetic):
    r = evaluate.evaluate([synthetic])
    opus, glm = _group(r, "opus"), _group(r, "glm")
    assert (opus["launched"], opus["ran"], opus["failed"], opus["no_trace"]) == (2, 2, 0, 0)
    assert (glm["launched"], glm["ran"], glm["failed"], glm["no_trace"]) == (1, 0, 1, 0)


def test_bands_count_only_replicas_that_ran(synthetic):
    r = evaluate.evaluate([synthetic])
    opus = _group(r, "opus")["match"]["all"]
    assert opus["n"] == 8  # 4 claims x 2 replicas; glm_1's rows excluded
    assert opus["bands"] == {"A": 3, "B": 1, "C": 1, "fail": 1, "not_found": 2}
    assert opus["n_found"] == 6
    assert opus["share_a"] == pytest.approx(3 / 8)
    assert opus["share_ab"] == pytest.approx(4 / 8)


def test_a_row_without_a_replicated_value_is_not_found_not_a_failed_match(synthetic):
    r = evaluate.evaluate([synthetic])
    # c4/opus_2 carries band "fail" with replicated None; it must land in not_found
    assert _group(r, "opus")["match"]["all"]["bands"]["not_found"] == 2


def test_headline_and_focal_subsets(synthetic):
    r = evaluate.evaluate([synthetic])
    m = _group(r, "opus")["match"]
    assert m["headline"]["n"] == 4 and m["headline"]["share_ab"] == pytest.approx(3 / 4)
    assert m["focal"]["n"] == 2 and m["focal"]["share_a"] == 1.0


def test_a_group_with_no_running_replica_yields_na(synthetic):
    r = evaluate.evaluate([synthetic])
    glm = _group(r, "glm")["match"]["all"]
    assert glm["n"] == 0
    assert glm["share_found"] is None and glm["share_a"] is None


def test_fix_severities_and_hardcoding_verdicts(synthetic):
    r = evaluate.evaluate([synthetic])
    opus = _group(r, "opus")
    assert opus["fixes"] == {"total": 4, "minor": 1, "major": 1, "critical": 1, "unrated": 1}
    assert opus["hardcoding"] == {"clean": 1, "suspicious": 1, "hardcoded": 0, "not_run": 0}
    assert _group(r, "glm")["hardcoding"]["not_run"] == 1


def test_missing_fields_yield_none_not_zero(synthetic):
    r = evaluate.evaluate([synthetic])
    glm = _group(r, "glm")
    assert glm["cost"]["cost_usd"] is None and glm["cost"]["duration_mean_s"] is None
    assert glm["blind_hits"]["total"] is None
    opus = _group(r, "opus")
    assert opus["blind_hits"] == {"total": 2, "reporting": 1, "replicas": 2}
    # opus_1 reports no cost fields, so the family total is opus_2's alone
    assert opus["cost"]["cost_usd_equiv"] == pytest.approx(0.5)
    assert opus["cost"]["duration_mean_s"] == pytest.approx(60.0)


def test_a_replica_without_a_trace_is_no_trace_not_failed(synthetic):
    r = evaluate.evaluate([synthetic])
    ds = _group(r, "deepseek")
    assert (ds["launched"], ds["ran"], ds["failed"], ds["no_trace"]) == (1, 0, 0, 1)
    assert ds["hardcoding"]["not_run"] == 1


def test_fix_columns_read_na_when_no_trace_was_written(synthetic):
    md = evaluate.render_md(evaluate.evaluate([synthetic]))
    section = md.split("## Fixes, hardcoding audit, blinding")[1].split("##")[0]
    row = next(ln for ln in section.splitlines() if ln.startswith("| deepseek |"))
    assert row.split("|")[2:7] == [" n/a "] * 5
    assert row.split("|")[10].strip() == "1"  # the audit not-run count is a real count


def test_tiers_pool_replicas(synthetic):
    r = evaluate.evaluate([synthetic])
    assert _group(r, "frontier")["match"]["all"]["n"] == 8
    assert _group(r, "cheap")["launched"] == 2


def test_dispersion_and_targeted(synthetic):
    r = evaluate.evaluate([synthetic])
    block = r["per_paper"][0]
    assert block["decision_agreement_mean"] == pytest.approx(0.7)
    assert block["numeric_cv_median"] == pytest.approx(0.2)
    assert block["targeted"]["outcome"] == "not_reachable"


def test_focal_d_uses_the_reported_d_claim(synthetic):
    block = evaluate.evaluate([synthetic])["per_paper"][0]
    fd = block["focal_d"]
    assert fd["source"] == "reported d claim" and fd["reported"] == pytest.approx(1.0)
    assert set(fd["replicas"]) == {"opus_1", "opus_2", "glm_1"}


def test_focal_d_converts_from_t_when_no_d_claim(synthetic):
    for row in synthetic["match_rows"]:
        row["quantity_kind"] = "t"
    fd = evaluate.evaluate([synthetic])["per_paper"][0]["focal_d"]
    assert fd["source"] == "converted from t"
    assert fd["reported"] == pytest.approx(2 * 1.0 / 27 ** 0.5)
    assert "independent groups" in fd["note"]


def test_within_and_between_family_focal_spread(synthetic):
    focal = evaluate.evaluate([synthetic])["per_paper"][0]["focal"]
    assert focal["within_family"]["opus"]["n"] == 2
    assert focal["within_family"]["opus"]["max_abs_diff"] == pytest.approx(0.0)
    assert focal["between_family_range"] == pytest.approx(0.0)  # glm_1 also reports c1 = 1.0
    assert focal["scale"] == "d"


def test_markdown_prints_na_where_a_metric_is_missing(synthetic):
    md = evaluate.render_md(evaluate.evaluate([synthetic]))
    glm_lines = [ln for ln in md.splitlines() if ln.startswith("| glm |")]
    assert glm_lines and all("n/a" in ln for ln in glm_lines)
    assert "### synth" in md


# --- the real fixture run -------------------------------------------------


@needs_fixture
def test_fixture_run_end_to_end(tmp_path: Path):
    result = evaluate.evaluate([evaluate.load_paper("_fixture")])
    labels = [g["label"] for g in result["families"]]
    assert labels == ["glm", "opus"]
    assert [g["label"] for g in result["tiers"]] == ["frontier", "cheap"]
    assert _group(result, "opus")["cost"]["cost_usd_equiv"] > 0
    assert _group(result, "glm")["cost"]["cost_usd"] > 0
    for label in ("glm", "opus"):
        g = _group(result, label)
        assert (g["launched"], g["ran"]) == (1, 1)
        assert g["match"]["all"]["n"] == 5
        assert g["match"]["all"]["share_ab"] == 1.0
        assert g["blind_hits"]["total"] is None  # the fixture traces predate the check

    block = result["per_paper"][0]
    assert block["targeted"]["outcome"] == "not_triggered"
    assert block["focal"]["quantity"]["claim_id"] == "c3"
    assert block["focal_d"]["source"] == "converted from t"

    jp, mp = evaluate.write(result, tmp_path)
    assert jp.exists() and "reproscope v0 pilot" in mp.read_text()


@needs_fixture
def test_paper_ids_skips_fixtures_by_default():
    ids = evaluate.paper_ids()
    assert not any(i.startswith("_") for i in ids)
    assert "logs" not in ids
    assert "_fixture" in evaluate.paper_ids(include_fixtures=True)


def test_loading_does_not_create_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    (tmp_path / "runs").mkdir()
    paper = evaluate.load_paper("nothing_here")
    assert paper["replicas"] == [] and paper["match_rows"] == []
    assert list((tmp_path / "runs").iterdir()) == []

"""Offline tests for stage 0's deterministic parts: schema summary and leak scan."""

from __future__ import annotations

import json

from reproscope.stage0 import leakcheck, readiness


def claim(**kw):
    base = {
        "claim_id": "c001",
        "quantity_kind": "t",
        "value": 5.91,
        "precision": 2,
        "importance": "headline",
    }
    base.update(kw)
    return base


# --- schema summary -------------------------------------------------------


def test_schema_summary_csv(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("id,cnd,score,label\n1,1,4.5,a\n2,2,,b\n3,1,3.5,a\n")
    rec = readiness.summarise_file(p)

    assert rec["format"] == "csv"
    table = rec["tables"][0]
    assert (table["rows"], table["cols"]) == (3, 4)
    cols = {c["name"]: c for c in table["columns"]}
    assert cols["score"]["n_missing"] == 1
    assert cols["score"]["min"] == 3.5 and cols["score"]["max"] == 4.5
    # low-cardinality columns get counts; every column gets examples
    assert cols["cnd"]["value_counts"] == {"1": 2, "2": 1}
    assert cols["label"]["examples"][:2] == ["a", "b"]


def test_schema_summary_two_header_rows(tmp_path):
    """An Excel sheet with merged group labels above the real names."""
    import pandas as pd

    p = tmp_path / "d.xlsx"
    frame = pd.DataFrame(
        [
            ["ID", "cnd", "Intimacy"],
            [1, 1, 5.75],
            [2, 2, 2.50],
        ],
        columns=["Demographics", None, "Intimacy Questionnaire"],
    )
    frame.to_excel(p, index=False, sheet_name="Sheet3")

    rec = readiness.summarise_file(p)
    table = rec["tables"][0]
    assert table["rows"] == 2
    names = [c["name"] for c in table["columns"]]
    assert names == ["ID", "cnd", "Intimacy"]
    labels = {c["name"]: c.get("label") for c in table["columns"]}
    assert labels["Intimacy"] == "Intimacy Questionnaire"
    assert labels["cnd"] == "Demographics"  # merged label carried forward


def test_schema_summary_free_text(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("Thanks for your message. The data are attached.\n")
    rec = readiness.summarise_file(p)
    assert rec["format"] == "text"
    assert "Thanks" in rec["text"]


# --- forbidden strings ----------------------------------------------------


def test_forbidden_strings_cover_rounding_and_leading_zero():
    forbidden, _ = leakcheck.forbidden_strings([claim(value=0.82, precision=2)])
    assert {"0.82", ".82", "0.8", ".8", "0.820", ".820"} <= set(forbidden)
    assert forbidden["0.82"] == ["c001"]


def test_forbidden_strings_skip_rules():
    claims = [
        claim(claim_id="c1", value=5.91),
        claim(claim_id="c2", quantity_kind="p_value", value=0.001, comparator="<"),
        claim(claim_id="c3", quantity_kind="n", value=29, importance="supporting"),
        claim(claim_id="c4", quantity_kind="n", value=29, importance="headline"),
    ]
    forbidden, skipped = leakcheck.forbidden_strings(claims, design_numbers=[29])
    reasons = {s["claim_id"]: s["reason"] for s in skipped}
    assert "c2" in reasons and "threshold" in reasons["c2"]
    assert "c3" in reasons  # small integer
    assert "c4" not in reasons  # a headline sample size is a result
    assert "29" in forbidden and forbidden["29"] == ["c4"]
    assert "5.91" in forbidden


def test_forbidden_strings_include_uncertainty_numbers():
    forbidden, _ = leakcheck.forbidden_strings(
        [claim(value=4.58, precision=2, uncertainty="SD = 0.82")]
    )
    assert "4.58" in forbidden and "0.82" in forbidden


# --- the scan -------------------------------------------------------------


def test_scan_finds_a_leak(tmp_path):
    doc = tmp_path / "redacted_methods.md"
    doc.write_text("Intimacy differed between conditions, t(27) = 5.91.\n")
    hits = leakcheck.scan([doc], [claim(value=5.91)])
    assert len(hits) == 1
    assert hits[0]["value"] == "5.91" and hits[0]["claim_ids"] == ["c001"]
    assert "5.91" in hits[0]["context"]


def test_scan_clean_document(tmp_path):
    doc = tmp_path / "redacted_methods.md"
    doc.write_text(
        "Participants rated intimacy on a 7-point scale. "
        "Group means were compared with a two-sample t test at alpha = .05.\n"
    )
    blind = tmp_path / "blind_contract.json"
    blind.write_text(
        json.dumps({"contracts": [{"analysis_id": "a01", "model_type": "two-sample t test"}]})
    )
    claims = [
        claim(value=5.91),
        claim(claim_id="c002", quantity_kind="p_value", value=0.001, comparator="<"),
        claim(claim_id="c003", quantity_kind="n", value=7, importance="supporting"),
    ]
    assert leakcheck.scan([doc, blind], claims) == []


def test_scan_respects_number_boundaries(tmp_path):
    doc = tmp_path / "m.md"
    doc.write_text("The lag was 5.915 days and the code is 15.91.\n")
    # "5.91" must not match inside "5.915"; "15.91" must not match as a suffix.
    assert leakcheck.scan([doc], [claim(value=5.91, precision=2)]) == []


def test_scan_matches_a_negative_value(tmp_path):
    doc = tmp_path / "m.md"
    doc.write_text("The coefficient was -0.47.\n")
    hits = leakcheck.scan([doc], [claim(quantity_kind="coefficient", value=0.47, precision=2)])
    assert [h["value"] for h in hits] == ["0.47"]

"""Offline tests for stage 0's deterministic parts: schema summary and leak scan."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from reproscope import artifacts, llm, paths
from reproscope.stage0 import contracts, extract, leakcheck, readiness, redact


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
    assert {"0.82", ".82"} <= set(forbidden)
    assert forbidden["0.82"] == ["c001"]
    # One significant digit recovers no result and collides with alpha levels.
    assert "0.8" not in forbidden and ".8" not in forbidden


def test_forbidden_strings_cover_inferential_and_headline_claims_only():
    claims = [
        claim(claim_id="c1", value=5.91),  # headline t
        claim(claim_id="c2", quantity_kind="r", value=0.314, importance="supporting"),
        claim(claim_id="c3", quantity_kind="mean", value=36.67, importance="supporting"),
        claim(claim_id="c4", quantity_kind="percent", value=42.0, importance="headline"),
        claim(claim_id="c5", quantity_kind="sd", value=15.73, importance="supporting"),
    ]
    forbidden, skipped = leakcheck.forbidden_strings(claims)
    reasons = {s["claim_id"]: s["reason"] for s in skipped}

    assert "5.91" in forbidden  # headline t
    assert "0.314" in forbidden  # supporting correlation: an inferential kind
    assert "42" in forbidden  # headline percentage
    # Sample description the redacted methods must be able to state.
    assert "c3" in reasons and "c5" in reasons
    assert "36.67" not in forbidden and "15.73" not in forbidden


def test_supporting_claims_need_three_significant_digits():
    def forms(**kw):
        return set(leakcheck.forbidden_strings([claim(quantity_kind="d", **kw)])[0])

    # Two significant digits from a supporting claim collide with ordinary prose.
    assert forms(value=0.85, importance="supporting") == set()
    assert forms(value=12.0, precision=0, importance="supporting") == set()
    assert {"0.812", ".812"} <= forms(value=0.812, precision=3, importance="supporting")
    # A headline claim keeps its two-digit forms.
    assert {"0.85", ".85"} <= forms(value=0.85, importance="headline")


def test_a_rounding_onto_an_alpha_level_is_not_searched():
    """Methods sections name their significance convention ("p between .05 and .10")."""
    forbidden, _ = leakcheck.forbidden_strings(
        [claim(quantity_kind="eta2", value=0.099, precision=3)]
    )
    assert "0.099" in forbidden and ".099" in forbidden
    assert "0.10" not in forbidden and ".10" not in forbidden
    # A value the paper itself printed at that precision is searched.
    at_precision, _ = leakcheck.forbidden_strings(
        [claim(quantity_kind="p_value", value=0.1, precision=2)]
    )
    assert "0.10" in at_precision and ".10" in at_precision


def test_the_extractors_own_kind_label_still_counts_as_inferential():
    """The arbiter records `ci_upper` alongside the validated kind `ci_bound`."""
    forbidden, _ = leakcheck.forbidden_strings(
        [
            claim(
                quantity_kind="ci_bound",
                quantity_kind_raw="ci_upper",
                value=16.8,
                precision=1,
                importance="supporting",
            )
        ]
    )
    assert "16.8" in forbidden


def test_scan_does_not_read_a_percentage_as_a_test_statistic(tmp_path):
    doc = tmp_path / "m.md"
    doc.write_text("We excluded 8.4% of the participants for failing the attention check.\n")
    assert leakcheck.scan([doc], [claim(quantity_kind="t", value=8.4, precision=1)]) == []
    # The same digits without the percent sign are the statistic.
    doc.write_text("The test gave 8.4 on this comparison.\n")
    assert len(leakcheck.scan([doc], [claim(quantity_kind="t", value=8.4, precision=1)])) == 1


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


def test_scan_ignores_json_ids_and_metadata(tmp_path):
    """Digits in claim ids, analysis ids and artifact metadata are not values."""
    blind = tmp_path / "blind_contract.json"
    blind.write_text(
        json.dumps(
            {
                "meta": {"version": "0.1", "created": "2026-09-02T14:52:56"},
                "contracts": [
                    {
                        "analysis_id": "a36",
                        "claim_ids": ["c196", "c104"],
                        "sample_rule": "All 196 recruited students completed the task.",
                    }
                ],
            }
        )
    )
    claims = [
        claim(claim_id="c1", quantity_kind="p_value", value=0.104, precision=3),
        claim(claim_id="c2", quantity_kind="n", value=196, importance="headline"),
        claim(claim_id="c3", quantity_kind="F", value=36.0, precision=1),
    ]
    hits = leakcheck.scan([blind], claims)
    # "c196"/"c104"/"a36"/"0.1" are scaffolding; only the prose sentence leaks.
    assert [(h["value"], h["location"]) for h in hits] == [
        ("196", "$.contracts[0].sample_rule")
    ]


def test_scan_matches_a_negative_value(tmp_path):
    doc = tmp_path / "m.md"
    doc.write_text("The coefficient was -0.47.\n")
    hits = leakcheck.scan([doc], [claim(quantity_kind="coefficient", value=0.47, precision=2)])
    assert [h["value"] for h in hits] == ["0.47"]


def test_scan_ignores_dotted_section_labels(tmp_path):
    doc = tmp_path / "blind_contract.json"
    doc.write_text(json.dumps({"contracts": [{"sample_rule": "As set out in Section 2.2.1."}]}))
    assert leakcheck.scan([doc], [claim(quantity_kind="d", value=2.20, precision=2)]) == []


def test_design_numbers_exempt_a_colliding_value(tmp_path):
    """A manipulation constant the methods must state is not a forbidden string."""
    doc = tmp_path / "m.md"
    doc.write_text("The signal turned blue with probability .50 per quiz.\n")
    claims = [claim(claim_id="c1", quantity_kind="r", value=0.50, precision=2)]
    assert len(leakcheck.scan([doc], claims)) == 1
    hits = leakcheck.scan([doc], claims, design_numbers=[0.5])
    assert hits == []


def test_scan_takes_design_numbers_from_a_paper_id(monkeypatch):
    """Stage 1 calls scan(files, claims, paper_id=...) and gets the paper's exemptions."""
    from reproscope import paths
    from reproscope.stage0 import leakcheck as lc

    class FakeManifest:
        design_numbers = [0.5]
        focal_claim = None

    monkeypatch.setattr(paths, "manifest", lambda pid: FakeManifest())
    assert lc.design_numbers_from_manifest(FakeManifest()) == [0.5]


# --- the combined contracts + redaction call ------------------------------


@pytest.fixture
def stage0_root(tmp_path, monkeypatch):
    """A run tree under tmp_path, with the real prompt files copied in."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    real = Path(__file__).resolve().parent.parent
    shutil.copytree(real / "reproscope" / "prompts", tmp_path / "reproscope" / "prompts")
    (tmp_path / "corpus" / "_p").mkdir(parents=True)
    return tmp_path


class Manifest:
    paper_id = "_p"
    design_numbers: list[float] = []
    focal_claim = None

    @property
    def dir(self):
        return paths.corpus_dir("_p")


def record(**kw):
    return artifacts.ClaimRecord.model_validate(claim(**kw))


PAPER = "Participants were 40 students. Intimacy differed by condition, t(27) = 5.91, p < .001."


def test_combined_call_writes_contracts_and_methods(stage0_root, monkeypatch):
    calls = []

    def fake_call(step, prompt, **kw):
        calls.append((step, prompt, kw))
        return llm.LLMResult(
            text="",
            parsed=contracts.ContractsAndMethods(
                contracts=[
                    contracts.SlimContract(
                        analysis_id="a01",
                        analysis_label="intimacy by condition",
                        model_type="paired t test",
                        versions_named=["R 4.1.0"],
                    )
                ],
                redacted_methods="# Methods\n\nParticipants were 40 students.\n",
            ),
            ledger_id="L1",
        )

    monkeypatch.setattr(llm, "call", fake_call)
    records, ledger = contracts.run(Manifest(), [record()], PAPER, {"pdf": "h"})

    assert [c.analysis_id for c in records] == ["a01"]
    assert records[0].versions_named == {"R": "4.1.0"}
    assert ledger == ["L1"]
    stage_dir = paths.run_dir("_p", 0)
    assert "Participants were 40 students" in (stage_dir / "redacted_methods.md").read_text()

    step, prompt, kw = calls[0]
    assert (step, kw["tier"], kw["large_context"]) == ("contracts", "strong", True)
    assert PAPER in prompt  # the paper is read exactly once
    assert len(calls) == 1  # a clean scan means no repair call

    # A second run reuses what is on disk instead of paying for the paper again.
    calls.clear()
    again, ledger = contracts.run(Manifest(), [record()], PAPER, {"pdf": "h"})
    assert calls == [] and ledger == [] and [c.analysis_id for c in again] == ["a01"]


def test_leak_repair_sends_only_the_offending_sentences(stage0_root, monkeypatch):
    prompts = []

    def fake_call(step, prompt, **kw):
        prompts.append((step, prompt, kw))
        if step == "contracts":
            return llm.LLMResult(
                text="",
                parsed=contracts.ContractsAndMethods(
                    contracts=[contracts.SlimContract(analysis_id="a01")],
                    redacted_methods=(
                        "# Methods\n\nParticipants were 40 students recruited on campus.\n"
                        "Intimacy differed between conditions, t(27) = 5.91.\n"
                        "The scale had seven points.\n"
                    ),
                ),
                ledger_id="L1",
            )
        sent = json.loads(prompt.split("Items:\n")[1].split("\nReturn JSON")[0])
        return llm.LLMResult(
            text="",
            parsed=redact.ScrubOut(
                items=[
                    redact.ScrubbedText(id=i["id"], text="The t statistic compared the conditions.")
                    for i in sent
                ]
            ),
            ledger_id="L2",
        )

    monkeypatch.setattr(llm, "call", fake_call)
    contracts.run(Manifest(), [record()], PAPER, {})

    repair_step, repair_prompt, kw = prompts[1]
    assert repair_step == "leak_repair:1" and kw["tier"] == "cheap"
    assert PAPER not in repair_prompt  # the paper never reaches the repair call
    assert "recruited on campus" not in repair_prompt  # only the leaking sentence goes
    assert "5.91" in repair_prompt
    assert len(prompts) == 2  # one repair round clears it

    methods = (paths.run_dir("_p", 0) / "redacted_methods.md").read_text()
    assert "5.91" not in methods
    assert "recruited on campus" in methods and "seven points" in methods


def test_repair_stops_after_two_rounds_and_leaves_the_hits(stage0_root, monkeypatch):
    methods = paths.run_dir("_p", 0) / "redacted_methods.md"
    methods.write_text("Intimacy differed between conditions, t(27) = 5.91.\n")
    rounds = []

    def fake_call(step, prompt, **kw):
        rounds.append(step)
        sent = json.loads(prompt.split("Items:\n")[1].split("\nReturn JSON")[0])
        # A rewrite that keeps the number: the repair does not converge.
        return llm.LLMResult(
            text="",
            parsed=redact.ScrubOut(
                items=[redact.ScrubbedText(id=i["id"], text=i["text"]) for i in sent]
            ),
            ledger_id="L",
        )

    monkeypatch.setattr(llm, "call", fake_call)
    hits, calls = redact.repair(Manifest(), [methods], [record()], [])

    assert rounds == ["leak_repair:1", "leak_repair:2"]
    assert len(calls) == 2
    assert [h["value"] for h in hits] == ["5.91"]  # the caller abstains on these


def _fake_contracts_call(calls):
    def fake_call(step, prompt, **kw):
        calls.append((step, prompt, kw))
        return llm.LLMResult(
            text="",
            parsed=contracts.ContractsAndMethods(
                contracts=[contracts.SlimContract(analysis_id="a01", model_type="paired t test")],
                redacted_methods="# Methods\n\nParticipants were 40 students.\n",
            ),
            ledger_id="L1",
        )
    return fake_call


def test_contracts_rebuilds_when_the_prompt_changes(stage0_root, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "call", _fake_contracts_call(calls))
    contracts.run(Manifest(), [record()], PAPER, {"pdf": "h"})
    assert len(calls) == 1

    # Editing the prompt file must invalidate the cached contracts, even though
    # nothing else about the run changed.
    prompt_file = paths.ROOT / "reproscope" / "prompts" / "stage0_contracts.md"
    prompt_file.write_text(prompt_file.read_text() + "\n<!-- edited -->\n")

    calls.clear()
    contracts.run(Manifest(), [record()], PAPER, {"pdf": "h"})
    assert len(calls) == 1  # rebuilt, not reused


def test_contracts_rebuilds_when_an_input_changes(stage0_root, monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "call", _fake_contracts_call(calls))
    contracts.run(Manifest(), [record()], PAPER, {"pdf": "h1"})
    assert len(calls) == 1

    # A different input hash (e.g. the PDF was re-extracted) must invalidate the cache
    # even though the prompt is unchanged.
    calls.clear()
    contracts.run(Manifest(), [record()], PAPER, {"pdf": "h2"})
    assert len(calls) == 1  # rebuilt, not reused


# --- extraction page check -------------------------------------------------


def _slim_claim(page, value, precision=2):
    return extract.SlimClaim(
        claim_id="c1", value=value, precision=precision,
        location=extract.SlimLocation(page=page),
    )


def test_verify_claim_pages_reassigns_to_the_one_nearby_page_that_prints_the_value():
    texts = ["", "nothing here", "still nothing", "the effect was t(27) = 5.91", "", "", ""]
    claims = [_slim_claim(page=1, value=5.91, precision=2)]
    out = extract.verify_claim_pages(claims, texts)
    assert out[0].location.page == 3
    assert out[0].page_corrected == {"from": 1, "to": 3}


def test_verify_claim_pages_leaves_a_claim_that_matches_its_own_page():
    texts = ["", "t(27) = 5.91"]
    claims = [_slim_claim(page=1, value=5.91, precision=2)]
    out = extract.verify_claim_pages(claims, texts)
    assert out[0].location.page == 1
    assert out[0].page_corrected is None


def test_verify_claim_pages_leaves_a_claim_found_on_no_nearby_page():
    texts = ["", "nothing here", "nor here", "nor here either"]
    claims = [_slim_claim(page=1, value=5.91, precision=2)]
    out = extract.verify_claim_pages(claims, texts)
    assert out[0].location.page == 1
    assert out[0].page_corrected is None


def test_verify_claim_pages_leaves_a_claim_ambiguous_between_two_nearby_pages():
    texts = ["", "nothing", "t = 5.91", "5.91 again", ""]
    claims = [_slim_claim(page=1, value=5.91, precision=2)]
    out = extract.verify_claim_pages(claims, texts)
    assert out[0].location.page == 1  # two candidates: too ambiguous to reassign
    assert out[0].page_corrected is None


# --- readiness ------------------------------------------------------------


def test_readiness_prompt_carries_the_schema_and_no_paper_text(stage0_root, monkeypatch):
    data = stage0_root / "corpus" / "_p" / "data"
    data.mkdir()
    (data / "d.csv").write_text("pid,intimacy\n1,4.5\n2,3.5\n")

    class M(Manifest):
        data_files = ["data/d.csv"]
        codebook = None

        def path(self, rel):
            return paths.corpus_dir("_p") / rel

    seen = {}

    def fake_call(step, prompt, **kw):
        seen.update({"step": step, "prompt": prompt, **kw})
        return llm.LLMResult(
            text="", parsed=readiness.ReadinessOut(confidence="high"), ledger_id="L"
        )

    monkeypatch.setattr(llm, "call", fake_call)
    contract = artifacts.EstimandContract(
        analysis_id="a01",
        outcome="intimacy",
        meta=artifacts.ArtifactMeta(artifact="EstimandContract"),
    )
    readiness.run(M(), [contract], {})

    assert seen["tier"] == "mid"
    assert "intimacy" in seen["prompt"]  # schema column and contract field
    assert PAPER not in seen["prompt"] and "t(27)" not in seen["prompt"]
    assert "EstimandContract" not in seen["prompt"]  # contract meta is stripped

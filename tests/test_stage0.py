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


def test_forbidden_strings_skip_degrees_of_freedom():
    forbidden, _ = leakcheck.forbidden_strings(
        [
            claim(value=2.42, precision=2, uncertainty="t(29) = 2.42, 95% CI [0.10, 0.52]"),
            claim(claim_id="c002", value=6.15, precision=2, uncertainty={"reported": "F(1, 42, 32)"}),
            claim(claim_id="c003", value=1.9, precision=1, uncertainty="Welch t(27.4)"),
        ]
    )
    assert ".52" in forbidden  # the CI bound survives the stripping
    for df in ("29", "42", "32", "27.4"):
        assert df not in forbidden


def test_uncertainty_df_labels_do_not_exempt_real_result_values():
    assert leakcheck._uncertainty_numbers({"reported": "df=24; SE=0.82", "df": 31,
                                          "ci": [0.12, 0.45]}) == [0.82, 0.12, 0.45]
    assert leakcheck._uncertainty_numbers("df1 = 1; df2: 27.4; SD=24") == [24.0]
    forbidden, _ = leakcheck.forbidden_strings([claim(value=24, precision=0,
                                                      uncertainty={"reported": "df=24"})])
    assert "24" in forbidden  # A statistic of 24 still leaks; this is not a value whitelist.


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


def test_result_claim_ids_widen_the_scan_to_a_whole_analysis():
    """A mean printed beside a test recovers the test; a mean in a descriptives-only
    analysis is sample description the redacted methods must be able to state."""
    claims = [
        claim(claim_id="c1", quantity_kind="t", value=5.91, importance="supporting"),
        claim(claim_id="c2", quantity_kind="mean", value=4.581, precision=3,
              importance="supporting"),
        claim(claim_id="c3", quantity_kind="mean", value=36.674, precision=3,
              importance="supporting"),
    ]
    contracts = [
        {"analysis_id": "a1", "claim_ids": ["c1", "c2"]},
        {"analysis_id": "a2", "claim_ids": ["c3"]},
    ]
    result_ids = leakcheck.result_claim_ids(claims, contracts)
    assert result_ids == {"c1", "c2"}

    forbidden, skipped = leakcheck.forbidden_strings(claims, result_claim_ids=result_ids)
    assert "4.581" in forbidden
    assert "36.674" not in forbidden
    assert [s["claim_id"] for s in skipped] == ["c3"]


def test_result_claim_ids_skip_claims_no_contract_lists():
    claims = [
        claim(claim_id="c1", quantity_kind="t", value=5.91),
        claim(claim_id="c9", quantity_kind="mean", value=4.58, importance="supporting"),
    ]
    contracts = [{"analysis_id": "a1", "claim_ids": ["c1"]}]
    assert leakcheck.result_claim_ids(claims, contracts) == {"c1"}


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


def atomic_contract(**kwargs):
    kwargs.setdefault("claim_ids", ["c001"])
    kwargs.setdefault("identity", contracts.AnalysisIdentity(study="study1", outcome="intimacy",
                       contrast="condition", model="paired_t", sample="complete"))
    return contracts.SlimContract(**kwargs)


PAPER = "Participants were 40 students. Intimacy differed by condition, t(27) = 5.91, p < .001."


def test_combined_call_writes_contracts_and_methods(stage0_root, monkeypatch):
    calls = []

    def fake_call(step, prompt, **kw):
        calls.append((step, prompt, kw))
        return llm.LLMResult(
            text="",
            parsed=contracts.ContractsAndMethods(
                contracts=[
                    atomic_contract(
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


def test_contract_identity_repair_is_bounded_and_preserves_all_claims(stage0_root, monkeypatch):
    calls = []

    def fake_call(step, prompt, **kw):
        calls.append(step)
        contract = atomic_contract(analysis_id="a01", claim_ids=[] if len(calls) == 1 else ["c001"])
        from reproscope.stage0.contract_repairs import ContractRepair
        parsed = contracts.ContractsAndMethods(contracts=[contract], redacted_methods="# Methods\nParticipants were 40 students.") if len(calls) == 1 else ContractRepair(contracts=[contract])
        return llm.LLMResult(text="", parsed=parsed, ledger_id=f"L{len(calls)}")

    monkeypatch.setattr(llm, "call", fake_call)
    records, ledger = contracts.run(Manifest(), [record()], PAPER, {})
    assert calls == ["contracts", "contracts:identity_repair"]
    assert records[0].claim_ids == ["c001"] and ledger == ["L1", "L2"]


def test_contract_identity_repair_failure_never_publishes_contracts(stage0_root, monkeypatch):
    calls = []

    def fake_call(step, prompt, **kw):
        calls.append(step)
        from reproscope.stage0.contract_repairs import ContractRepair
        parsed = contracts.ContractsAndMethods(contracts=[atomic_contract(analysis_id="a01", claim_ids=[])], redacted_methods="# Methods\nParticipants were 40 students.") if len(calls) == 1 else ContractRepair()
        return llm.LLMResult(text="", parsed=parsed, ledger_id="L")

    monkeypatch.setattr(llm, "call", fake_call)
    with pytest.raises(llm.LLMError, match="invalid analysis identities"):
        contracts.run(Manifest(), [record()], PAPER, {})
    assert len(calls) == 3
    assert not (paths.run_dir("_p", 0) / "contracts.json").exists()
    assert (paths.run_dir("_p", 0) / "invalid_contracts.json").exists()


def test_leak_repair_sends_only_the_offending_sentences(stage0_root, monkeypatch):
    prompts = []

    def fake_call(step, prompt, **kw):
        prompts.append((step, prompt, kw))
        if step == "contracts":
            return llm.LLMResult(
                text="",
                parsed=contracts.ContractsAndMethods(
                    contracts=[atomic_contract(analysis_id="a01")],
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
    assert repair_step.startswith("leak_repair:1:") and kw["tier"] == "cheap"
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

    assert [step.split(':')[1] for step in rounds] == ['1', '2']
    assert len(calls) == 2
    assert [h["value"] for h in hits] == ["5.91"]  # the caller abstains on these


def _fake_contracts_call(calls):
    def fake_call(step, prompt, **kw):
        calls.append((step, prompt, kw))
        return llm.LLMResult(
            text="",
            parsed=contracts.ContractsAndMethods(
                contracts=[atomic_contract(analysis_id="a01", model_type="paired t test")],
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


def test_verify_claim_pages_requires_source_quote_before_reassignment():
    texts = ["", "nothing here", "still nothing", "the effect was t(27) = 5.91", "", "", ""]
    claims = [_slim_claim(page=1, value=5.91, precision=2)]
    assert extract.verify_claim_pages(claims, texts)[0].location.page == 1
    claims[0].source_quote = "the effect was t(27) = 5.91"
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


def test_readiness_prompt_carries_schema_without_requiring_an_optional_text_copy(stage0_root, monkeypatch):
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


def test_leak_repair_rejects_changed_ids_without_applying_partial_output(stage0_root, monkeypatch):
    p = paths.run_dir('_p', 0) / 'blind_contract.json'
    p.write_text(json.dumps({'description': 'The t statistic was 5.91.'}))
    original = p.read_text()
    def fake_call(step, prompt, **kwargs):
        payload = json.loads(prompt.split('Items:\n')[1].split('\nReturn JSON')[0])
        assert payload[0]['id'] == 'r0000'
        return llm.LLMResult(text='', parsed=redact.ScrubOut(items=[
            redact.ScrubbedText(id='changed', text='[redacted: result]')]), ledger_id='L')
    monkeypatch.setattr(llm, 'call', fake_call)
    with pytest.raises(llm.LLMError, match='item IDs'):
        redact.repair(Manifest(), [p], [record()], [])
    assert p.read_text() == original


def test_dense_partition_preserves_relative_pages_ids_and_all_calls(monkeypatch):
    from reproscope.stage0 import extract
    def one(manifest,tier,pages,start,n_pages):
        assert n_pages==1
        claim=extract.SlimClaim(claim_id='same',value=start,location=extract.SlimLocation(page=1),source_token_id=f'p{start+1}:token')
        part=extract.ClaimList(claims=[claim],regions=[extract.RegionCoverage(page=1,kind='table',region_id='table',status='complete',claim_ids=['same'])])
        return start,part,f'call{start}'
    monkeypatch.setattr(extract,'_chunk_call',one)
    start,part,calls=extract._split_chunk(None,'vision_a',[None]*8,4,2)
    assert start==4 and calls==['call4','call5']
    assert [c.location.page for c in part.claims]==[1,2]
    assert [c.source_token_id for c in part.claims]==['p5:token','p6:token']
    assert not extract.coverage_errors(part,2)


def test_partition_cache_migration_requires_every_semantic_input_unchanged():
    from reproscope.stage0.extract import _compatible_inputs,PARTITION_COMPATIBLE_IMPLEMENTATIONS
    old={'implementation':next(iter(PARTITION_COMPATIBLE_IMPLEMENTATIONS)),'pdf':'pdf','prompt':'prompt','model':'same'}
    current={**old,'implementation':'adaptive_partition'}
    assert _compatible_inputs(old,current)
    assert not _compatible_inputs(old,{**current,'prompt':'changed'})
    assert not _compatible_inputs(old,{**current,'model':'different'})


def test_bare_decimal_tables_count_towards_the_extraction_output_budget():
    from reproscope.stage0.extract import _output_density
    assert _output_density(' '.join(['.52 −.71 0.25']*40))==120


def test_blind_contracts_remove_observed_counts_without_losing_design_parameters():
    c=artifacts.EstimandContract(analysis_id='a',sample_rule='eligible adults',design={'family':'paired_t','n_total':28,'group_ns':[14,14],'null_value':0,'contrast':'x minus y','independent_unit':'participant','evidence':'paired design'})
    result=redact.blind_contracts([c],{})[0]
    assert 'n_total' not in result['design'] and 'group_ns' not in result['design']
    assert result['design']['null_value']==0 and result['sample_rule']=='eligible adults'


def test_scrub_cache_tracks_prompt_and_reuses_identical_fragments(stage0_root,monkeypatch):
    from types import SimpleNamespace
    calls=[]
    def chunk(manifest,items,index):
        calls.append(items)
        return redact.ScrubOut(items=[redact.ScrubbedText(id=i['id'],text='eligible participants') for i in items]),'call'
    monkeypatch.setattr(redact,'_scrub_chunk',chunk)
    man=SimpleNamespace(paper_id='_p');items=[{'id':'a','text':'The 138 participants'},{'id':'b','text':'The 138 participants'}]
    out,_=redact.scrub_texts(man,items)
    assert out=={'a':'eligible participants','b':'eligible participants'} and len(calls[0])==1
    redact.scrub_texts(man,items);assert len(calls)==1
    monkeypatch.setattr(redact,'SCRUB_PROMPT',redact.SCRUB_PROMPT+' Changed policy.')
    redact.scrub_texts(man,items);assert len(calls)==2
    redact.scrub_texts(man,[{'id':'methods_document','text':'original methods'}])
    redact.scrub_texts(man,[{'id':'methods_document','text':'eligible participants\n'}])
    assert len(calls)==3


def test_ci_constant_collision_requires_exact_registered_template(tmp_path):
    c=artifacts.ClaimRecord(claim_id='ci',quantity_kind='ci_bound',value=.95,precision=2,importance='headline')
    task=tmp_path/'TASK.md'
    task.write_text(artifacts.load_prompt('stage1_replica_task')+'\n\n'+artifacts.load_prompt('stage1_adjusted_protocol'))
    collisions=[]
    assert not leakcheck.scan([task],[c],method_collisions=collisions)
    assert len(collisions)==1 and collisions[0]['claim_ids']==['ci']
    task.write_text(task.read_text()+'\nPaper-specific addition.')
    assert leakcheck.scan([task],[c])


def test_semantic_leak_repair_anchors_decoded_json_prose(tmp_path):
    from reproscope.stage0 import redact
    p=tmp_path/'blind_contract.json'
    p.write_text(json.dumps({'contracts':[{'sample_rule':'"One participant on medication was excluded".','design':{'null_value':0}}]}))
    audit={'passage_checks':[{'quote':'"One participant on medication was excluded".','kind':'numeric_result','anchored':True},
                             {'quote':'unseen finding','kind':'directional_result','anchored':False}]}
    items=redact.semantic_repair_items([p],audit)
    assert len(items)==1 and items[0]['location']=='$.contracts[0].sample_rule'
    redact.apply_repairs([p],items,{items[0]['id']:'Participants on medication were excluded.'})
    result=json.loads(p.read_text())
    assert result['contracts'][0]['design']['null_value']==0
    assert result['contracts'][0]['sample_rule']=='Participants on medication were excluded.'


def test_dense_source_scopes_cover_each_physical_occurrence_and_image_only():
    from reproscope.stage0 import extract
    ids=[f'p001:n{i}' for i in range(85)]
    page={'numeric_candidates':[{'source_token_id':v} for v in ids],
          'marker_candidates':[{'source_token_id':'p001:star'}]}
    scopes=extract._dense_scopes(page)
    assert [i for s in scopes for i in s['ids']]==ids+['p001:star']
    assert all(len(s['ids'])<=40 for s in scopes)
    assert len([s for s in scopes if s['image_only']])==1
    claim=extract.SlimClaim(claim_id='c1',source_token_id='p001:n0')
    part=extract.ClaimList(claims=[claim])
    assert not extract._scope_errors(part,scopes[0])
    assert extract._scope_errors(part,scopes[1])
    assert extract._scope_errors(part,scopes[-1])
    claim.source_token_id=None
    assert not extract._scope_errors(part,scopes[-1])
    assert extract._scope_errors(part,scopes[0])


def test_dense_page_partition_merges_and_resumes_completed_source_calls(monkeypatch,tmp_path):
    from reproscope.stage0 import extract
    from reproscope import source_layout
    from types import SimpleNamespace
    page=tmp_path/'page.png';page.write_bytes(b'original image')
    layout={'pages':[{'numeric_candidates':[{'source_token_id':f'p001:n{i}'} for i in range(45)]}]}
    monkeypatch.setattr(source_layout,'build',lambda _:layout)
    monkeypatch.setattr(extract.paths,'run_dir',lambda *args:tmp_path/'stage0')
    manifest=SimpleNamespace(paper_id='test',pdf='paper.pdf',path=lambda _:tmp_path/'paper.pdf')
    calls=[]
    def one(man,tier,pages,start,n_pages,scope):
        calls.append(scope['part'])
        token=scope['ids'][0] if scope['ids'] else None
        c=extract.SlimClaim(claim_id='c1',source_token_id=token,location=extract.SlimLocation(page=1))
        part=extract.ClaimList(claims=[c],regions=[extract.RegionCoverage(page=1,kind='table',region_id='r',status='complete',claim_ids=['c1'])])
        return start,part,f'call{scope["part"]}'
    monkeypatch.setattr(extract,'_chunk_call',one)
    _,result,ids=extract._partition_dense_page(manifest,'vision_a',[page],0)
    assert ids==['call1','call2','call3']
    assert [c.claim_id for c in result.claims]==['c001','c002','c003']
    assert len({r.region_id for r in result.regions})==3
    assert not extract.coverage_errors(result,1)
    extract._partition_dense_page(manifest,'vision_a',[page],0)
    assert sorted(calls)==[1,2,3]


def test_dense_partitions_keep_visual_rows_together_despite_column_order():
    from reproscope.stage0.extract import _dense_scopes
    candidates=[{'source_token_id':f'{x}:{y}','bbox':[x,y,x+1,y+1]} for x in [0,10] for y in [0,10,20]]
    scopes=_dense_scopes({'numeric_candidates':candidates},limit=3)
    assert [s['ids'] for s in scopes[:-1]]==[['0:0','10:0'],['0:10','10:10'],['0:20','10:20']]


def test_leak_repair_batches_cache_and_apply_complete_scope(stage0_root, monkeypatch):
    p = paths.run_dir('_p', 0) / 'redacted_methods.md'
    original = '\n'.join(f'Comparison {i} yielded t = 5.91.' for i in range(85))
    calls = []
    def call(step, prompt, **kw):
        sent = json.loads(prompt.split('Items:\n')[1].split('\nReturn JSON')[0])
        calls.append(len(sent))
        return llm.LLMResult(text='', parsed=redact.ScrubOut(items=[
            redact.ScrubbedText(id=i['id'], text='The t statistic compared conditions.') for i in sent]), ledger_id=step)
    monkeypatch.setattr(llm, 'call', call)
    for _ in range(2):
        p.write_text(original)
        hits, ids = redact.repair(Manifest(), [p], [record()], [])
        assert not hits and '5.91' not in p.read_text()
        assert len(ids) == 3
    assert sorted(calls) == [5, 40, 40]

"""Stage 0 arbitration: the deterministic merge, the crop fallback, and what reaches a model."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from reproscope import artifacts, llm, paths
from reproscope.stage0 import arbitrate
from reproscope.stage0.extract import ClaimList, SlimClaim, SlimLocation


def claim(claim_id="c001", value=5.91, precision=2, kind="t", page=3, label="Results", **kw):
    return SlimClaim(
        claim_id=claim_id,
        quantity_kind=kind,
        value=value,
        precision=precision,
        importance=kw.pop("importance", "supporting"),
        description=kw.pop("description", None),
        location=SlimLocation(page=page, kind="text", label=label, cell=kw.pop("cell", None)),
        **kw,
    )


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A temp ROOT holding the real prompts, so prompt versions and loading are live."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    real = Path(__file__).resolve().parents[1]
    shutil.copytree(real / "reproscope" / "prompts", tmp_path / "reproscope" / "prompts")
    return tmp_path


class FakeManifest:
    paper_id = "_arb"
    pdf = "paper.pdf"

    def path(self, rel):
        return paths.ROOT / "corpus" / self.paper_id / rel


# --- deterministic pairing ------------------------------------------------


def test_agreements_conflicts_and_singletons_are_separated():
    a = ClaimList(
        claims=[
            claim("c001", value=5.91),
            claim("c002", value=0.32, kind="r", label="Table 2", cell="row 1"),
            claim("c003", value=41, precision=0, kind="n", label="Participants", page=2),
        ]
    )
    b = ClaimList(
        claims=[
            claim("c001", value=5.91, label="results", description="t test"),
            claim("c002", value=0.23, kind="r", label="Table 2", cell="row 1"),
        ]
    )
    resolutions = arbitrate.partition(a, b)

    by_source = {r.source: r for r in resolutions}
    assert sorted(r.source for r in resolutions) == ["A", "agreed", "conflict"]
    # The agreement takes A's fields and fills the gaps from B.
    merged = by_source["agreed"]
    assert merged.claim.value == 5.91 and merged.claim.description == "t test"
    assert merged.agreed and not merged.unresolved
    assert by_source["conflict"].rival.value == 0.23
    assert by_source["A"].claim.value == 41


def test_agreement_tolerates_the_coarser_reported_precision():
    a = ClaimList(claims=[claim(value=5.9, precision=1)])
    b = ClaimList(claims=[claim(value=5.91, precision=2)])
    assert [r.source for r in arbitrate.partition(a, b)] == ["agreed"]


def test_a_different_label_is_not_the_same_claim():
    a = ClaimList(claims=[claim(label="Table 1 memory scores")])
    b = ClaimList(claims=[claim(label="Appendix B pilot sample")])
    assert sorted(r.source for r in arbitrate.partition(a, b)) == ["A", "B"]


def test_two_table_cells_are_not_a_value_conflict():
    """Different rows of one table stay two claims, each checked on its own."""
    a = ClaimList(claims=[claim(value=4.3, kind="percent", label="Table 3", cell="Sandpaper / Men")])
    b = ClaimList(claims=[claim(value=11.1, kind="percent", label="Table 3", cell="Carving / Women")])
    assert sorted(r.source for r in arbitrate.partition(a, b)) == ["A", "B"]


def test_two_sentences_on_one_page_are_not_a_value_conflict():
    a = ClaimList(
        claims=[
            claim(
                value=0.29,
                kind="p_value",
                description="p = .29 for the baseline vs. suppressed comparison in ruminators (flanker latencies).",
            )
        ]
    )
    b = ClaimList(
        claims=[
            claim(
                value=0.209,
                kind="p_value",
                description="Target ratings by ruminators were not significantly different, p = .209.",
            )
        ]
    )
    assert sorted(r.source for r in arbitrate.partition(a, b)) == ["A", "B"]


def test_table_four_is_not_table_five():
    a = ClaimList(claims=[claim(value=0.2, kind="r", label="Table 4", cell="age")])
    b = ClaimList(claims=[claim(value=0.2, kind="r", label="Table 5", cell="age")])
    assert sorted(r.source for r in arbitrate.partition(a, b)) == ["A", "B"]


def test_headline_from_either_extractor_survives_the_merge():
    a = ClaimList(claims=[claim(importance="supporting")])
    b = ClaimList(claims=[claim(importance="headline")])
    assert arbitrate.partition(a, b)[0].claim.importance == "headline"


# --- the crop helper ------------------------------------------------------


def test_crop_falls_back_to_the_full_page_when_the_bbox_lookup_fails(tmp_path):
    missing = tmp_path / "nothing.pdf"
    assert arbitrate.crop_page(missing, 3, 5.91, 2, tmp_path / "crops") is None


def test_crop_falls_back_when_the_value_is_not_on_the_page(tmp_path, monkeypatch):
    monkeypatch.setattr(arbitrate, "page_words", lambda pdf, page: (600.0, 800.0, [(10.0, 20.0, 90.0, "4.71")]))
    assert arbitrate.crop_page(tmp_path / "p.pdf", 3, 5.91, 2, tmp_path / "crops") is None


def test_value_forms_cover_the_leading_zero_and_thousands_separator():
    assert arbitrate.value_forms(0.82, 2) == ["0.82", ".82"]
    assert arbitrate.value_forms(41, 0) == ["41"]
    assert arbitrate.value_forms(60088, 0) == ["60088", "60,088"]


def test_overlapping_bands_share_one_crop():
    bands = [(10.0, 40.0), (30.0, 60.0), (200.0, 220.0)]
    assert arbitrate.merge_bands(bands, limit=500.0) == [(10.0, 60.0), (200.0, 220.0)]
    # A merge that would exceed the height limit is not made.
    assert arbitrate.merge_bands(bands, limit=40.0) == [(10.0, 40.0), (30.0, 60.0), (200.0, 220.0)]


def test_a_value_inside_a_longer_number_is_not_a_hit():
    assert not arbitrate._word_holds("5.915", "5.91")
    assert not arbitrate._word_holds("15.91", "5.91")
    assert arbitrate._word_holds("t(27)=5.91,", "5.91")
    # The value at either edge of the word, which is how tables and CIs print it.
    assert arbitrate._word_holds("270.8]", "270.8")
    assert arbitrate._word_holds("[8.5,", "8.5")
    assert arbitrate._word_holds("16.8", "16.8")


# --- the model calls ------------------------------------------------------


def test_only_disagreements_and_singletons_reach_a_model(sandbox, monkeypatch):
    a = ClaimList(
        claims=[
            claim("c001", value=5.91),
            claim("c002", value=0.32, kind="r", label="Table 2", cell="row 1"),
            claim("c003", value=41, precision=0, kind="n", label="Participants", page=2),
        ]
    )
    b = ClaimList(claims=[claim("c001", value=5.91), claim("c002", value=0.23, kind="r", label="Table 2", cell="row 1")])

    sent: list[dict] = []

    def fake_call(step, prompt, **kw):
        items = json.loads(prompt.split("Items:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
        sent.append({"step": step, "tier": kw.get("tier"), "items": items})
        return llm.LLMResult(
            text="",
            parsed=arbitrate.ArbitrationBatch(
                items=[
                    arbitrate.ArbitrationItem(
                        item_id=i["item_id"], decision="correct", value=0.23, note="printed"
                    )
                    if i.get("candidate_values")
                    else arbitrate.ArbitrationItem(item_id=i["item_id"], decision="keep")
                    for i in items
                ]
            ),
            ledger_id="L1",
        )

    monkeypatch.setattr(llm, "call", fake_call)
    monkeypatch.setattr(arbitrate, "value_band", lambda *a, **k: None)

    records, calls = arbitrate.run(FakeManifest(), a, b, [], inputs={})

    assert len(sent) == 1 and sent[0]["tier"] == "vision_a"
    # Two items only: the conflicting r and the singleton n. The agreed t is untouched.
    assert {i["value"] for i in sent[0]["items"]} == {None, 41.0}
    assert len(sent[0]["items"]) == 2
    assert calls == ["L1"]

    by_value = {r.value: r for r in records}
    assert by_value[5.91].extraction.agreed is True
    assert by_value[5.91].confidence == "high"
    assert by_value[0.23].extraction.agreed is False  # corrected to the printed value
    assert by_value[41.0].extraction.arbiter_note is None and by_value[41.0].confidence == "medium"
    assert [r.claim_id for r in records] == ["c001", "c002", "c003"]  # page order, then label


def test_an_unresolved_headline_claim_escalates_and_a_supporting_one_does_not(sandbox, monkeypatch):
    a = ClaimList(
        claims=[
            claim("c001", value=5.91, importance="headline"),
            claim("c002", value=0.32, kind="r", label="Table 2", importance="supporting"),
        ]
    )
    b = ClaimList(claims=[])
    steps: list[str] = []

    def fake_call(step, prompt, **kw):
        steps.append(f"{step}/{kw.get('tier')}")
        items = json.loads(prompt.split("Items:\n", 1)[1].split("\n\nReturn JSON", 1)[0])
        if step.startswith("arbitrate:batch"):
            return llm.LLMResult(
                text="",
                parsed=arbitrate.ArbitrationBatch(
                    items=[
                        arbitrate.ArbitrationItem(item_id=i["item_id"], decision="keep", uncertain=True)
                        for i in items
                    ]
                ),
                ledger_id="L1",
            )
        return llm.LLMResult(
            text="",
            parsed=arbitrate.ArbitrationBatch(
                items=[
                    arbitrate.ArbitrationItem(item_id=i["item_id"], decision="drop", note="not printed")
                    for i in items
                ]
            ),
            ledger_id="L2",
        )

    monkeypatch.setattr(llm, "call", fake_call)
    monkeypatch.setattr(arbitrate, "value_band", lambda *a, **k: None)

    records, _ = arbitrate.run(FakeManifest(), a, b, [], inputs={})

    assert steps == ["arbitrate:batch1/vision_a", "arbitrate:strong/strong"]
    # The headline claim was dropped by the strong pass; the supporting one stays, at low confidence.
    assert [r.value for r in records] == [0.32]
    assert records[0].confidence == "low"
    assert records[0].extraction.arbiter_note == "unresolved"
    summary = json.loads((paths.run_dir("_arb", 0) / "arbitration.json").read_text())
    assert (summary["n_escalated"], summary["n_singleton"], len(summary["dropped"])) == (1, 2, 1)


def test_a_failed_batch_leaves_every_item_unresolved(sandbox, monkeypatch):
    a = ClaimList(claims=[claim("c001", value=5.91)])
    monkeypatch.setattr(
        llm, "call", lambda *a, **k: llm.LLMResult(text="", parsed=None, ok=False, ledger_id="L1")
    )
    monkeypatch.setattr(arbitrate, "value_band", lambda *a, **k: None)

    records, _ = arbitrate.run(FakeManifest(), a, ClaimList(claims=[]), [], inputs={})
    assert records[0].confidence == "low" and records[0].extraction.arbiter_note == "unresolved"


def test_claims_json_is_reused_until_a_prompt_changes(sandbox, monkeypatch):
    a = ClaimList(claims=[claim("c001", value=5.91)])
    b = ClaimList(claims=[claim("c001", value=5.91)])
    calls: list[str] = []
    monkeypatch.setattr(llm, "call", lambda *args, **kw: calls.append(kw.get("tier")))

    first, _ = arbitrate.run(FakeManifest(), a, b, [], inputs={})
    assert calls == []  # a full agreement needs no model at all

    again, made = arbitrate.run(FakeManifest(), a, b, [], inputs={})
    assert made == [] and [r.claim_id for r in again] == [r.claim_id for r in first]

    prompt = artifacts.prompt_path("stage0_arbitrate")
    prompt.write_text(prompt.read_text() + "\nOne more rule.\n")
    rebuilt, _ = arbitrate.run(FakeManifest(), a, b, [], inputs={})
    assert rebuilt[0].meta.prompt_versions["stage0_arbitrate"] == artifacts.prompt_version(
        "stage0_arbitrate"
    )

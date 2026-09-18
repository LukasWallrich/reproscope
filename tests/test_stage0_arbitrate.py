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
        source_region=kw.pop("source_region", "paragraph:paired-comparison"),
        quantity_role="inferential",
        location=SlimLocation(page=page, kind="text", label=label, cell=kw.pop("cell", None)),
        **kw,
    )


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A temp ROOT holding the real prompts, so prompt versions and loading are live."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    real = Path(__file__).resolve().parents[1]
    shutil.copytree(real / "reproscope" / "prompts", tmp_path / "reproscope" / "prompts")
    from reproscope import source_layout
    monkeypatch.setattr(source_layout, "build", lambda pdf: {"pdf_sha256": None, "pages": []})
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


def test_different_printed_precision_and_values_require_resolution():
    a = ClaimList(claims=[claim(value=5.9, precision=1)])
    b = ClaimList(claims=[claim(value=5.91, precision=2)])
    assert [r.source for r in arbitrate.partition(a, b)] == ["conflict"]


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
                source_region="paragraph:target-ratings",
            )
        ]
    )
    assert sorted(r.source for r in arbitrate.partition(a, b)) == ["A", "B"]


def test_a_cell_is_matched_on_its_words_not_their_order():
    assert arbitrate.cells_match("Attachment - Total attachment / SD", "Total attachment / SD")
    assert arbitrate.cells_match("HKSS / Total attachment", "Total attachment / HKSS")
    assert arbitrate.cells_match("Total attachment / SD", None)
    # One word apart is a different cell of the same table.
    assert not arbitrate.cells_match("Banging head / Men - Percentage", "Banging head / Women percentage")
    assert not arbitrate.cells_match("Total attachment / SD", "Total attachment / M")
    assert not arbitrate.cells_match("Table 3 row 1", "Table 3 row 2")


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
                        item_id=i["item_id"], decision="correct", value=0.23, note="printed",
                        corrected_claim=SlimClaim(**{**i["candidate_claims"][0], "value": 0.23})
                    )
                    if i.get("candidate_values")
                    else arbitrate.ArbitrationItem(item_id=i["item_id"], decision="keep", corrected_claim=SlimClaim(**i["candidate_claims"][0]))
                    for i in items
                ]
            ),
            ledger_id="L1",
        )

    monkeypatch.setattr(llm, "call", fake_call)
    monkeypatch.setattr(arbitrate, "value_band", lambda *a, **k: None)

    records, calls = arbitrate.run(FakeManifest(), a, b, [], inputs={})

    assert len(sent) == 1 and sent[0]["tier"] == "arbiter"
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


def test_unresolved_required_source_fields_escalate_regardless_of_importance(sandbox, monkeypatch):
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

    assert steps == ["arbitrate:batch1/arbiter", "arbitrate:strong/strong"]
    assert records == []  # both unresolved source readings were escalated and dropped
    summary = json.loads((paths.run_dir("_arb", 0) / "arbitration.json").read_text())
    assert (summary["n_escalated"], summary["n_singleton"], len(summary["dropped"])) == (2, 2, 2)


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


def test_decision_trace_keeps_original_candidates_after_final_renumbering():
    from reproscope.stage0.extract import ClaimList, SlimClaim, SlimLocation
    a=SlimClaim(claim_id='original_a',quantity_kind='t',value=4.71,source_quote='The result t(27) = 4.71',location=SlimLocation(page=1,kind='text'))
    b=a.model_copy(update={'claim_id':'original_b','target_model':'paired t'})
    rows=arbitrate.partition(ClaimList(claims=[a]),ClaimList(claims=[b]),['',a.source_quote])
    rows[0].item_id='i001'; rows[0].decision_calls=['cheap_call','strong_call']
    records=arbitrate.to_records(rows,'A','B',artifacts.ArtifactMeta(artifact='ClaimRecord'))
    trace=arbitrate.decision_trace(rows,records)
    assert trace[0]['source_claim_ids']=={'A':'original_a','B':'original_b'}
    assert trace[0]['claim_id']=='c001' and trace[0]['decision_calls']==['cheap_call','strong_call']


def test_rival_local_id_is_accepted_only_for_same_physical_token():
    a=claim('reader_a',source_token_id='p003:word:0')
    b=a.model_copy(update={'claim_id':'reader_b'})
    resolution=arbitrate.Resolution(a,'conflict',b)
    arbitrate.apply_decision(resolution,arbitrate.ArbitrationItem(item_id='i1',decision='correct',corrected_claim=b))
    assert not resolution.unresolved and resolution.claim.claim_id=='reader_a'
    resolution=arbitrate.Resolution(a,'conflict',b)
    wrong=b.model_copy(update={'source_token_id':'p003:another:0'})
    arbitrate.apply_decision(resolution,arbitrate.ArbitrationItem(item_id='i1',decision='correct',corrected_claim=wrong))
    assert resolution.unresolved


def test_keep_can_reconcile_semantic_wording_but_cannot_change_literal():
    a=claim(target_outcome='reaction time')
    resolution=arbitrate.Resolution(a,'A')
    b=a.model_copy(update={'target_outcome':'reaction_time'})
    arbitrate.apply_decision(resolution,arbitrate.ArbitrationItem(item_id='i1',decision='keep',corrected_claim=b))
    assert not resolution.unresolved
    resolution=arbitrate.Resolution(a,'A')
    arbitrate.apply_decision(resolution,arbitrate.ArbitrationItem(item_id='i1',decision='keep',corrected_claim=b.model_copy(update={'value':9})))
    assert resolution.unresolved


def test_duplicate_source_peers_are_reviewed_together_at_batch_boundaries():
    from reproscope.stage0.arbitrate import _joint_source_batches,Resolution
    from reproscope.stage0.extract import SlimClaim,SlimLocation
    items=[]
    for i in range(5):
        r=Resolution(claim=SlimClaim(claim_id=f'c{i}',location=SlimLocation(page=1)),source='A')
        r.note='source validation: duplicate source occurrence requires reconciliation'
        items.append((f'i{i}',r))
    batches=_joint_source_batches(items,[['i0','i3']],size=2)
    assert any({i for i,_ in b}=={'i0','i3'} for b in batches)
    assert sorted(i for b in batches for i,_ in b)==[f'i{i}' for i in range(5)]
    assert 'wrong source_token_id' in items[0][1].note
    assert 'i0, i3' in items[3][1].note


def test_source_repair_rechecks_new_collisions_with_previously_accepted_records(sandbox, monkeypatch):
    from reproscope import source_integrity
    a = arbitrate.Resolution(claim('a', source_token_id='wrong'), 'A')
    b = arbitrate.Resolution(claim('b', source_token_id='right'), 'B')
    a.item_id, b.item_id = 'ia', 'ib'
    b.unresolved = False
    meta = artifacts.ArtifactMeta(artifact='ClaimRecord')
    records = arbitrate.to_records([a, b], 'A', 'B', meta)
    records[0].state = 'abstained'
    records[0].abstain_reason = 'wrong physical source pointer'
    reviewed = []

    def review(manifest, prompt, tier, step, batch, *args, **kwargs):
        reviewed.append([iid for iid, _ in batch])
        decisions = {}
        for iid, res in batch:
            decision = 'drop' if iid == 'ib' else 'correct'
            decisions[iid] = arbitrate.ArbitrationItem(
                item_id=iid, decision=decision,
                corrected_claim=res.claim.model_copy(update={'source_token_id': 'right'}))
        return decisions, step

    def validate(records, *args, **kwargs):
        if len(records) == 2:
            for record in records:
                record.state = 'abstained'
                record.abstain_reason = 'duplicate source occurrence requires reconciliation'
                record.occurrence_id = 'same-physical-number'
        else:
            records[0].source_validation = 'visual_adjudicated'

    monkeypatch.setattr(arbitrate, '_call_batch', review)
    monkeypatch.setattr(source_integrity, 'validate_sources', validate)
    repaired = arbitrate._repair_sources(FakeManifest(), [a, b], records,
        [Path('p1'), Path('p2'), Path('p3')], sandbox, meta, [], [], {}, {})
    assert reviewed == [['ia'], ['ia', 'ib']]
    assert len(repaired) == 1 and repaired[0].state == 'complete'
    assert b.dropped


def test_source_repair_stops_after_four_failed_passes(sandbox, monkeypatch):
    from reproscope import source_integrity
    a = arbitrate.Resolution(claim('a'), 'A')
    a.item_id = 'ia'
    meta = artifacts.ArtifactMeta(artifact='ClaimRecord')
    records = arbitrate.to_records([a], 'A', 'B', meta)
    def invalidate(records, *args, **kwargs):
        records[0].state = 'abstained'
        records[0].abstain_reason = 'source evidence unresolved'
    invalidate(records)
    calls = []
    monkeypatch.setattr(arbitrate, '_call_batch', lambda *a, **k: ({}, 'failed'))
    monkeypatch.setattr(source_integrity, 'validate_sources', invalidate)
    repaired = arbitrate._repair_sources(FakeManifest(), [a], records,
        [Path('p1'), Path('p2'), Path('p3')], sandbox, meta, calls, [], {}, {})
    assert calls == ['failed'] * 4
    assert repaired[0].state == 'abstained'


def test_source_repair_can_correct_a_known_rivals_bad_physical_pointer():
    a = claim('reader_a', source_token_id='wrong')
    b = a.model_copy(update={'claim_id': 'reader_b'})
    resolution = arbitrate.Resolution(a, 'conflict', b)
    corrected = b.model_copy(update={'source_token_id': 'right'})
    arbitrate.apply_decision(resolution, arbitrate.ArbitrationItem(
        item_id='i1', decision='correct', corrected_claim=corrected), source_repair=True)
    assert not resolution.unresolved
    assert resolution.claim.claim_id == 'reader_a'
    assert resolution.claim.source_token_id == 'right'
    assert resolution.source_claim_ids == {'A': 'reader_a', 'B': 'reader_b'}
    unrelated = corrected.model_copy(update={'claim_id': 'unrelated'})
    arbitrate.apply_decision(resolution, arbitrate.ArbitrationItem(
        item_id='i1', decision='correct', corrected_claim=unrelated), source_repair=True)
    assert resolution.unresolved

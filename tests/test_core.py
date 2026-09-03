"""Offline tests for the core, plus live route probes gated on REPROSCOPE_LIVE=1."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from reproscope import artifacts, config, ledger, llm, paths

LIVE = os.environ.get("REPROSCOPE_LIVE") == "1"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Point ROOT at a temp tree so nothing touches the real runs/ or corpus/."""
    monkeypatch.setattr(paths, "ROOT", tmp_path)
    (tmp_path / "reproscope" / "prompts").mkdir(parents=True)
    return tmp_path


# --- ledger ---------------------------------------------------------------


def test_ledger_append_and_summary(sandbox):
    a = ledger.record("p1", {"stage": "0", "step": "extract", "route": "openrouter",
                             "model": "m1", "tokens_in": 100, "tokens_out": 10,
                             "cost_usd": 0.25, "ok": True})
    ledger.record("p1", {"stage": "0", "step": "extract", "route": "openrouter",
                         "model": "m1", "tokens_in": 50, "tokens_out": 5,
                         "cost_usd": 0.25, "ok": False})
    ledger.record("p1", {"stage": "1", "step": "replica", "route": "claude_p",
                         "model": "opus", "tokens_in": 7, "cost_usd": 3.5, "ok": True})

    assert len(a) == 12
    lines = ledger.ledger_path("p1").read_text().strip().splitlines()
    assert len(lines) == 3
    assert all(json.loads(ln)["paper_id"] == "p1" for ln in lines)

    s = ledger.summary("p1")
    assert s["total"]["calls"] == 3
    assert s["total"]["ok"] == 2
    assert s["total"]["tokens_in"] == 157
    # subscription route contributes 0 to cost, but keeps the list-price equivalent
    assert s["total"]["cost_usd"] == pytest.approx(0.5)
    assert s["total"]["cost_usd_equiv"] == pytest.approx(3.5)
    assert s["route"]["claude_p"]["cost_usd"] == 0.0
    assert s["stage"]["0"]["calls"] == 2
    assert "TOTAL" in ledger.format_summary("p1")


def test_ledger_summary_empty(sandbox):
    assert ledger.summary("nobody")["total"]["calls"] == 0


# --- config ---------------------------------------------------------------


def test_config_reads_models_toml():
    spec = config.tier("strong")
    assert (spec.route, spec.model) == ("claude_p", "opus")
    assert config.tier("mid").model == "sonnet"
    assert config.replicas()["glm"].runs == 2
    assert "sol" not in config.replicas()
    assert config.executor().route == "opencode"
    labels = dict((s.route + "/" + s.model, label) for label, s in config.all_specs())
    assert "opencode/z-ai/glm-5.3-flash" in labels
    assert config.shadow_price("gpt-5.6-luna") == 2.5
    assert config.shadow_price("opus") is None
    with pytest.raises(KeyError):
        config.tier("no_such_tier")


# --- prompts --------------------------------------------------------------


def test_prompt_substitution_and_version(sandbox):
    p = sandbox / "reproscope" / "prompts" / "stage0_extract.md"
    p.write_text('Claim: {{claim}}\nReply as {"value": 1}\n')
    assert artifacts.load_prompt("stage0_extract", claim="beta = .3") == (
        'Claim: beta = .3\nReply as {"value": 1}\n'
    )
    v = artifacts.prompt_version("stage0_extract")
    assert len(v) == 12
    p.write_text('Claim: {{claim}}\nchanged\n')
    assert artifacts.prompt_version("stage0_extract") != v


def test_load_prompt_rejects_unfilled_placeholder(sandbox):
    (sandbox / "reproscope" / "prompts" / "x.md").write_text("{{a}} and {{b}}")
    with pytest.raises(KeyError, match="b"):
        artifacts.load_prompt("x", a="1")


# --- artifacts ------------------------------------------------------------


def test_artifact_round_trip(tmp_path):
    claims = [
        artifacts.ClaimRecord(
            claim_id="c1", quantity_kind="d", value=0.42, precision=2,
            importance="headline",
            location=artifacts.ClaimLocation(page=7, kind="table", label="Table 2", cell="r3c2"),
            meta=artifacts.ArtifactMeta(artifact="ClaimRecord", stage="0",
                                        inputs={"pdf": "ab" * 32}, model_calls=["deadbeef1234"]),
        ),
        artifacts.ClaimRecord(claim_id="c2", state="abstained", abstain_reason="figure only"),
    ]
    path = artifacts.save(claims, tmp_path / "claims.json")
    back = artifacts.load(artifacts.ClaimRecord, path)
    assert [c.claim_id for c in back] == ["c1", "c2"]
    assert back[0].location.page == 7
    assert back[0].meta.version == "0.1"
    assert back[1].state == "abstained"

    space = artifacts.SpecificationSpace(
        claim_id="c1", grid_size=8, rank=3,
        factors=[artifacts.SpecFactor(name="covariates", source="trace",
                                      levels=[artifacts.FactorLevel(value="none",
                                                                    verdict="defensible")])],
    )
    p2 = artifacts.save(space, tmp_path / "space.json")
    assert artifacts.load(artifacts.SpecificationSpace, p2).factors[0].levels[0].value == "none"


def test_artifacts_allow_extra_fields():
    c = artifacts.ClaimRecord.model_validate({"claim_id": "c1", "invented_by_a_stage": 3})
    assert c.invented_by_a_stage == 3


def test_sha256_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello")
    assert artifacts.sha256_file(f) == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )


# --- paths / done markers -------------------------------------------------


def test_done_marker_tracks_inputs(tmp_path):
    stage_dir = tmp_path / "stage0"
    inputs = {"pdf": "aa", "manifest": "bb"}
    assert not paths.is_done(stage_dir, inputs)
    paths.mark_done(stage_dir, inputs)
    assert paths.is_done(stage_dir, inputs)
    assert not paths.is_done(stage_dir, {"pdf": "aa", "manifest": "CHANGED"})
    paths.done_path(stage_dir).write_text("not json")
    assert not paths.is_done(stage_dir, inputs)


def test_manifest_loads(sandbox):
    d = paths.corpus_dir("demo")
    d.mkdir(parents=True)
    (d / "manifest.json").write_text(json.dumps({
        "paper_id": "demo", "title": "T", "doi": "10.1/x", "data_files": ["data/x.csv"],
        "focal_claim": {"text": "d = .42", "source": "multi100",
                        "reported": {"statistic": "d", "value": 0.42, "n": 200, "page": 7}},
        "environment": {"language_hint": "R"},
    }))
    m = paths.manifest("demo")
    assert m.focal_claim.reported.value == 0.42
    assert m.pdf == "paper.pdf"
    assert m.path("data/x.csv") == d / "data/x.csv"
    with pytest.raises(FileNotFoundError):
        paths.manifest("missing")


# --- llm helpers ----------------------------------------------------------


class Probe(BaseModel):
    answer: str
    note: str | None = None


def test_first_json_object_and_fences():
    assert llm.strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert llm.first_json_object('here you go:\n```json\n{"a": {"b": 1}}\n```\nthanks') == (
        '{"a": {"b": 1}}'
    )
    assert llm.first_json_object('{"a": "}"} trailing') == '{"a": "}"}'
    assert llm.validate(Probe, 'prose {"answer": "OK"} more').answer == "OK"


def test_strictify_closes_objects():
    s = llm.strictify(Probe.model_json_schema())
    assert s["additionalProperties"] is False
    assert set(s["required"]) == {"answer", "note"}
    assert "default" not in json.dumps(s)
    assert llm.strict_safe(s)


def test_open_maps_disable_strict_mode():
    """dict[str, Any] fields cannot be closed, so those schemas go the prompt route."""
    payload, strict = llm.schema_payload(artifacts.ReplicaDecisionTrace)
    assert not strict  # estimator_settings / hardcoding_audit are open maps
    assert '"additionalProperties": true' in json.dumps(payload)
    assert llm.schema_payload(Probe)[1] is True
    assert "JSON object matching this schema" in llm.schema_instruction(Probe)


def test_unknown_route_raises_and_records_a_ledger_row(sandbox):
    with pytest.raises(llm.LLMError, match="unknown route"):
        llm.call("boom", "hi", paper_id="p1", stage="0", route="nonexistent", model="m")
    row = json.loads(ledger.ledger_path("p1").read_text().strip())
    assert row["ok"] is False and row["attempt"] == 1


# --- llm routing, with the network and the CLIs mocked ---------------------


def _or_reply(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": 10, "completion_tokens": 5, "cost": 0.001,
            "completion_tokens_details": {"reasoning_tokens": 3},
        },
    }


def openrouter_stub(monkeypatch, replies: list[dict]) -> list[dict]:
    """Serve `replies` in order to `_openrouter`; returns the list of posted bodies."""
    import httpx

    posted: list[dict] = []
    queue = list(replies)

    class FakeResponse:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def post(self, _url, headers=None, json=None):
            posted.append(json)
            return FakeResponse(queue.pop(0))

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(httpx, "Client", FakeClient)
    return posted


def cli_stub(monkeypatch, stdout: str, returncode: int = 0):
    # opencode reads the OpenRouter key before it spawns; keep the real one out.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        llm, "_run",
        lambda *a, **k: SimpleNamespace(returncode=returncode, stdout=stdout, stderr=""),
    )


def test_reasoning_cap_applies_to_structured_openrouter_calls_only(sandbox, monkeypatch):
    posted = openrouter_stub(monkeypatch, [_or_reply('{"answer": "OK"}'), _or_reply("plain")])
    r = llm.call("s", "hi", paper_id="p", stage="0", route="openrouter", model="m", schema=Probe)
    assert r.ok, r.error
    assert posted[0]["reasoning"] == {"max_tokens": 512}
    llm.call("s", "hi", paper_id="p", stage="0", route="openrouter", model="m")
    assert "reasoning" not in posted[1]


def test_oversize_non_agentic_input_is_refused_and_ledgered(sandbox, monkeypatch):
    big = "x" * (4 * llm.MAX_INPUT_TOKENS + 400)
    with pytest.raises(llm.LLMError, match="exceeds"):
        llm.call("big", big, paper_id="p", stage="0", route="openrouter", model="m")
    rows = ledger.rows("p")
    assert len(rows) == 1
    assert rows[0]["ok"] is False and "large_context=True" in rows[0]["error"]

    openrouter_stub(monkeypatch, [_or_reply("fine")])
    r = llm.call("big", big, paper_id="p", stage="0", route="openrouter", model="m",
                 large_context=True)
    assert r.ok and len(ledger.rows("p")) == 2


def test_every_attempt_is_ledgered_and_tokens_sum(sandbox, monkeypatch):
    posted = openrouter_stub(monkeypatch, [_or_reply("not json"), _or_reply('{"answer": "OK"}')])
    r = llm.call("s", "hi", paper_id="p", stage="0", route="openrouter", model="m", schema=Probe)
    assert r.ok and r.parsed.answer == "OK"
    assert "did not validate" in posted[1]["messages"][0]["content"]

    rows = ledger.rows("p")
    assert [row["attempt"] for row in rows] == [1, 2]
    assert [row["ok"] for row in rows] == [False, True]
    assert r.ledger_id == rows[1]["id"]
    assert (r.tokens_in, r.tokens_out, r.tokens_reasoning) == (20, 10, 6)
    assert r.cost_usd == pytest.approx(0.002)


def test_opencode_counts_cached_input_tokens(sandbox, monkeypatch):
    stdout = "\n".join([
        json.dumps({"type": "text", "part": {"text": "OK"}}),
        json.dumps({"type": "step_finish", "part": {
            "tokens": {"input": 100, "output": 10, "reasoning": 5,
                       "cache": {"read": 900, "write": 50}},
            "cost": 0.01,
        }}),
    ])
    cli_stub(monkeypatch, stdout)
    r = llm.call("s", "hi", paper_id="p", stage="0", route="opencode", model="m")
    assert r.ok and r.text == "OK"
    assert (r.tokens_in, r.tokens_out, r.tokens_reasoning) == (1050, 10, 5)


def test_codex_tokens_are_priced_at_the_shadow_rate(sandbox, monkeypatch):
    cli_stub(monkeypatch, "codex\nOK\ntokens used: 1,000\n")
    r = llm.call("s", "hi", paper_id="p", stage="0", route="codex", model="gpt-5.6-luna")
    assert r.ok and r.tokens_in == 1000
    assert r.cost_usd == 0.0  # subscription seat: no marginal cash
    row = ledger.rows("p")[0]
    assert row["cost_source"] == "subscription"
    assert row["cost_usd_equiv"] == pytest.approx(1000 * 2.5 / 1e6)


# --- live route probes ----------------------------------------------------


@pytest.mark.skipif(not LIVE, reason="set REPROSCOPE_LIVE=1 to run live model calls")
@pytest.mark.parametrize(
    "route,model",
    [
        ("openrouter", "z-ai/glm-5.3-flash"),
        ("claude_p", "claude-fable-5-1"),
        ("codex", "gpt-5.6-sol"),
        ("opencode", "z-ai/glm-5.3-flash"),
    ],
)
def test_live_route(route, model, tmp_path):
    r = llm.call(
        "probe", "Reply with exactly: OK",
        paper_id="_probe", stage="probe", route=route, model=model,
        cwd=tmp_path, timeout_s=300, log_path=tmp_path / f"{route}.log",
    )
    assert r.ok, r.error
    assert "OK" in r.text
    assert r.tokens_in > 0
    print(f"\n{route}/{model}: in={r.tokens_in} out={r.tokens_out} "
          f"reason={r.tokens_reasoning} cost=${r.cost_usd:.5f} {r.duration_s:.1f}s")


@pytest.mark.skipif(not LIVE, reason="set REPROSCOPE_LIVE=1 to run live model calls")
@pytest.mark.parametrize("route,model", [("openrouter", "z-ai/glm-5.3-flash"),
                                         ("claude_p", "claude-fable-5-1"),
                                         ("codex", "gpt-5.6-sol")])
def test_live_structured(route, model, tmp_path):
    r = llm.call(
        "probe_schema",
        'Reply with a JSON object: answer must be exactly "OK", note may be null.',
        paper_id="_probe", stage="probe", route=route, model=model,
        schema=Probe, cwd=tmp_path, timeout_s=300,
    )
    assert r.ok, r.error
    assert isinstance(r.parsed, Probe) and r.parsed.answer == "OK"


@pytest.mark.skipif(not LIVE, reason="set REPROSCOPE_LIVE=1 to run live model calls")
@pytest.mark.parametrize("route,model", [("openrouter", "z-ai/glm-5.3-flash"),
                                         ("claude_p", "claude-fable-5-1"),
                                         ("codex", "gpt-5.6-sol")])
def test_live_open_map_schema(route, model, tmp_path):
    """An artifact schema with dict[str, Any] fields still comes back valid."""
    r = llm.call(
        "probe_open_schema",
        "Return a ReplicaDecisionTrace for replica_id 'r1', family 'opus', ran true, "
        "seed 1, estimator_settings {\"cluster\": \"school\"}. Leave the rest empty.",
        paper_id="_probe", stage="probe", route=route, model=model,
        schema=artifacts.ReplicaDecisionTrace, cwd=tmp_path, timeout_s=300,
    )
    assert r.ok, r.error
    assert r.parsed.replica_id


@pytest.mark.skipif(not LIVE, reason="set REPROSCOPE_LIVE=1 to run live model calls")
@pytest.mark.parametrize("route,model", [("claude_p", "claude-fable-5-1"),
                                         ("codex", "gpt-5.6-sol"),
                                         ("opencode", "z-ai/glm-5.3-flash")])
def test_live_agentic_writes_a_file(route, model, tmp_path):
    r = llm.call(
        "probe_agentic",
        "Create a file named hello.txt containing exactly OK in the current directory, "
        "then reply DONE.",
        paper_id="_probe", stage="probe", route=route, model=model,
        cwd=tmp_path, agentic=True, timeout_s=300,
    )
    assert r.ok, r.error
    assert (tmp_path / "hello.txt").exists(), r.text[:400]


@pytest.mark.skipif(not LIVE, reason="set REPROSCOPE_LIVE=1 to run live model calls")
def test_live_openrouter_vision(tmp_path):
    png = tmp_path / "img.png"
    png.write_bytes(
        __import__("base64").b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmM"
            "IQAAAABJRU5ErkJggg=="
        )
    )
    r = llm.call(
        "probe_vision", "This is a 1x1 image. Reply with exactly: OK",
        paper_id="_probe", stage="probe", route="openrouter",
        model="openai/gpt-5.6-luna", images=[png], timeout_s=300,
    )
    assert r.ok, r.error
    assert "OK" in r.text


def test_cli_parses():
    from reproscope.cli import build_parser

    args = build_parser().parse_args(["run", "demo", "--stages", "0", "1", "--force"])
    assert args.paper_id == "demo" and args.stages == ["0", "1"] and args.force
    assert build_parser().parse_args(["probe"]).paper_id == "_probe"
